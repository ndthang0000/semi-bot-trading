from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from sqlite3 import Connection
from typing import Any

from ..config import StrategyConfig
from ..zones import CandleSlice, latest_atr


PLAYBOOK = "liquidity_sweep_reclaim_v1"
TRADE_MODE = "liquidity_sweep"
TERMINAL_STATES = {"invalidated_breakout", "timed_out", "consumed"}


@dataclass(frozen=True)
class LiquiditySweepState:
    state: str = "idle"
    touched_lower_at: datetime | None = None
    deadline_at: datetime | None = None
    atr_at_touch: float | None = None
    deepest_bid: float | None = None
    invalidation_price: float | None = None
    reclaimed_at: datetime | None = None
    terminal_reason: str | None = None


@dataclass(frozen=True)
class LiquiditySweepTransition:
    state: LiquiditySweepState
    became_eligible: bool = False


def transition_buy_liquidity_sweep(
    state: LiquiditySweepState,
    *,
    now: datetime,
    bid: float,
    ask: float,
    price_low: float,
    price_high: float,
    atr: float,
    timeout_minutes: int,
    max_sweep_atr: float,
) -> LiquiditySweepTransition:
    """Advance one quote observation for a bullish liquidity zone.

    Bid measures the downside sweep. Ask must reclaim the upper edge because a
    real Buy is filled on Ask. The deadline is exclusive: reclaim exactly at
    the deadline is too late. A move strictly deeper than max_sweep_atr is a
    true breakout; exactly max_sweep_atr remains valid.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)
    if state.state in TERMINAL_STATES:
        return LiquiditySweepTransition(state)
    if atr <= 0 or price_low >= price_high or bid <= 0 or ask <= 0:
        return LiquiditySweepTransition(state)

    current = state
    just_touched = False
    if current.state == "idle":
        if bid > price_low:
            return LiquiditySweepTransition(current)
        snapshot_atr = float(atr)
        current = LiquiditySweepState(
            state="waiting_reclaim",
            touched_lower_at=now,
            deadline_at=now + timedelta(minutes=max(timeout_minutes, 1)),
            atr_at_touch=snapshot_atr,
            deepest_bid=bid,
            invalidation_price=price_low - max(max_sweep_atr, 0.0) * snapshot_atr,
        )
        just_touched = True

    deepest_bid = min(float(current.deepest_bid or bid), bid)
    current = LiquiditySweepState(
        state=current.state,
        touched_lower_at=current.touched_lower_at,
        deadline_at=current.deadline_at,
        atr_at_touch=current.atr_at_touch,
        deepest_bid=deepest_bid,
        invalidation_price=current.invalidation_price,
        reclaimed_at=current.reclaimed_at,
        terminal_reason=current.terminal_reason,
    )

    # Invalidation wins over timeout/reclaim when one observation crosses more
    # than one boundary (for example after a quote gap).
    if current.invalidation_price is not None and deepest_bid < current.invalidation_price:
        return LiquiditySweepTransition(
            LiquiditySweepState(
                **{**current.__dict__, "state": "invalidated_breakout", "terminal_reason": "sweep_exceeded_max_atr"}
            )
        )
    if current.deadline_at is not None and now >= current.deadline_at:
        return LiquiditySweepTransition(
            LiquiditySweepState(**{**current.__dict__, "state": "timed_out", "terminal_reason": "reclaim_timeout"})
        )
    # Touch and reclaim must be two ordered quote observations. Otherwise a
    # narrow zone plus spread (or one gapped quote) could fabricate a bounce.
    if just_touched:
        return LiquiditySweepTransition(current)
    # Re-emit while the reclaim condition remains true. Execution guards may
    # temporarily block the first observation (news/spread/risk); the stable
    # candidate id lets the execution layer retry safely without duplicating a
    # successfully sent order. The original touch deadline still applies.
    if ask >= price_high:
        return LiquiditySweepTransition(
            LiquiditySweepState(
                **{
                    **current.__dict__,
                    "state": "reclaimed",
                    "reclaimed_at": now,
                    "terminal_reason": "upper_edge_reclaimed",
                }
            ),
            became_eligible=True,
        )
    return LiquiditySweepTransition(current)


def evaluate_live_buy_liquidity_zones(
    conn: Connection,
    *,
    symbol: str,
    timeframe: str,
    account_label: str,
    bid: float,
    ask: float,
    spread: float,
    now: datetime,
    config: StrategyConfig,
) -> list[dict[str, Any]]:
    """Persist quote-driven states and return only newly reclaimed candidates."""
    if not config.liquidity_sweep_reclaim_v1_enabled:
        return []
    atr = _latest_closed_atr(conn, symbol, timeframe, config.atr_period)
    if atr is None or atr <= 0:
        return []
    zones = conn.execute(
        """
        SELECT * FROM price_zones
        WHERE symbol = ? AND UPPER(timeframe) = 'H1'
          AND zone_type = 'liquidity_pool' AND direction = 'bullish'
          AND status = 'active'
          AND (valid_until IS NULL OR valid_until > ?)
        ORDER BY effective_weight DESC, updated_at DESC
        """,
        (symbol, now.astimezone(UTC).isoformat()),
    ).fetchall()
    candidates: list[dict[str, Any]] = []
    for row in zones:
        metadata = _json_object(row["metadata_json"])
        modes = metadata.get("trade_modes")
        if not isinstance(modes, list) or TRADE_MODE not in {str(mode) for mode in modes}:
            continue
        persisted = conn.execute(
            "SELECT * FROM liquidity_sweep_states WHERE zone_id = ? AND account_label = ?",
            (row["id"], account_label),
        ).fetchone()
        # Editing zone geometry is an explicit new thesis and starts a fresh event.
        state = (
            _state_from_row(persisted)
            if persisted is not None and str(persisted["zone_updated_at"]) == _zone_version(row)
            else LiquiditySweepState()
        )
        transition = transition_buy_liquidity_sweep(
            state,
            now=now,
            bid=bid,
            ask=ask,
            price_low=float(row["price_low"]),
            price_high=float(row["price_high"]),
            atr=atr,
            timeout_minutes=config.liquidity_sweep_reclaim_v1_timeout_minutes,
            max_sweep_atr=config.liquidity_sweep_reclaim_v1_max_sweep_atr,
        )
        _upsert_state(conn, row, account_label, transition.state, now)
        if transition.became_eligible:
            candidates.append(
                _build_candidate(
                    row,
                    transition.state,
                    symbol=symbol,
                    timeframe=timeframe,
                    account_label=account_label,
                    ask=ask,
                    spread=spread,
                    config=config,
                )
            )
    conn.commit()
    return candidates


def _latest_closed_atr(conn: Connection, symbol: str, timeframe: str, period: int) -> float | None:
    rows = conn.execute(
        """
        SELECT open_time, open, high, low, close
        FROM candles WHERE symbol = ? AND timeframe = ?
        ORDER BY open_time DESC LIMIT ?
        """,
        (symbol, timeframe, max(period + 1, 2)),
    ).fetchall()
    candles = [
        CandleSlice(
            open_time=str(row["open_time"]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for row in reversed(rows)
    ]
    return latest_atr(candles, period=period)


def _state_from_row(row: Any) -> LiquiditySweepState:
    return LiquiditySweepState(
        state=str(row["state"]),
        touched_lower_at=_parse_datetime(row["touched_lower_at"]),
        deadline_at=_parse_datetime(row["deadline_at"]),
        atr_at_touch=float(row["atr_at_touch"]) if row["atr_at_touch"] is not None else None,
        deepest_bid=float(row["deepest_bid"]) if row["deepest_bid"] is not None else None,
        invalidation_price=float(row["invalidation_price"]) if row["invalidation_price"] is not None else None,
        reclaimed_at=_parse_datetime(row["reclaimed_at"]),
        terminal_reason=str(row["terminal_reason"]) if row["terminal_reason"] else None,
    )


def _upsert_state(conn: Connection, zone: Any, account_label: str, state: LiquiditySweepState, now: datetime) -> None:
    conn.execute(
        """
        INSERT INTO liquidity_sweep_states (
            zone_id, account_label, symbol, zone_updated_at, state,
            touched_lower_at, deadline_at, atr_at_touch, deepest_bid,
            invalidation_price, reclaimed_at, terminal_reason, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(zone_id, account_label) DO UPDATE SET
            symbol = excluded.symbol, zone_updated_at = excluded.zone_updated_at,
            state = excluded.state, touched_lower_at = excluded.touched_lower_at,
            deadline_at = excluded.deadline_at, atr_at_touch = excluded.atr_at_touch,
            deepest_bid = excluded.deepest_bid, invalidation_price = excluded.invalidation_price,
            reclaimed_at = excluded.reclaimed_at, terminal_reason = excluded.terminal_reason,
            updated_at = excluded.updated_at
        """,
        (
            zone["id"], account_label, zone["symbol"], _zone_version(zone), state.state,
            _iso(state.touched_lower_at), _iso(state.deadline_at), state.atr_at_touch,
            state.deepest_bid, state.invalidation_price, _iso(state.reclaimed_at),
            state.terminal_reason, now.astimezone(UTC).isoformat(),
        ),
    )


def _build_candidate(
    zone: Any,
    state: LiquiditySweepState,
    *,
    symbol: str,
    timeframe: str,
    account_label: str,
    ask: float,
    spread: float,
    config: StrategyConfig,
) -> dict[str, Any]:
    atr = float(state.atr_at_touch or 0.0)
    deepest = float(state.deepest_bid or zone["price_low"])
    stop = deepest - max(float(spread), config.liquidity_sweep_reclaim_v1_sl_buffer_atr * atr)
    risk = ask - stop
    take_profit = ask + risk * config.liquidity_sweep_reclaim_v1_rr
    touched_at = _iso(state.touched_lower_at)
    raw_id = f"{symbol}|{account_label}|{zone['id']}|{PLAYBOOK}|{touched_at}"
    candidate_id = hashlib.sha1(raw_id.encode("utf-8")).hexdigest()
    return {
        "id": candidate_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "playbook": PLAYBOOK,
        "direction": "long",
        "status": "eligible",
        "zone_reaction_state": "liquidity_reclaim",
        "score": round(float(zone["effective_weight"]), 4),
        "entry": round(ask, 5),
        "stop_loss": round(stop, 5),
        "take_profit": [round(take_profit, 5)],
        "risk_reward": config.liquidity_sweep_reclaim_v1_rr,
        "primary_zone_id": str(zone["id"]),
        "related_zone_ids": [str(zone["id"])],
        "trigger_point_ids": [],
        "reason": ["Bid swept the lower edge and Ask reclaimed the upper edge within the liquidity timeout."],
        "blocked_reason": [],
        "expires_at": _iso(state.deadline_at),
        "metadata": {
            "as_of": _iso(state.reclaimed_at),
            "order_type": "market",
            "entry_model": "quote_reclaim",
            "zone_type": "liquidity_pool",
            "liquidity_trade_side": "buy",
            "trade_modes": [TRADE_MODE],
            "touched_lower_at": touched_at,
            "deadline_at": _iso(state.deadline_at),
            "atr_at_touch": round(atr, 5),
            "deepest_bid": round(deepest, 5),
            "invalidation_price": round(float(state.invalidation_price or 0.0), 5),
            "max_sweep_atr": config.liquidity_sweep_reclaim_v1_max_sweep_atr,
        },
    }


def _json_object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _zone_version(zone: Any) -> str:
    raw = "|".join(
        (
            str(zone["updated_at"]),
            str(zone["direction"]),
            f"{float(zone['price_low']):.8f}",
            f"{float(zone['price_high']):.8f}",
            str(zone["metadata_json"]),
        )
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None
