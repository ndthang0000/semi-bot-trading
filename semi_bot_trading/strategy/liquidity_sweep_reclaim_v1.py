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
TERMINAL_STATES = {"invalidated_breakout", "invalidated_risk", "timed_out", "consumed"}
TRADE_DIRECTIONS = {"long", "short"}


@dataclass(frozen=True)
class LiquiditySweepState:
    state: str = "idle"
    trade_direction: str = "long"
    touched_edge_at: datetime | None = None
    deadline_at: datetime | None = None
    atr_at_touch: float | None = None
    extreme_price: float | None = None
    invalidation_price: float | None = None
    reclaimed_at: datetime | None = None
    terminal_reason: str | None = None


@dataclass(frozen=True)
class LiquiditySweepTransition:
    state: LiquiditySweepState
    became_eligible: bool = False


def transition_liquidity_sweep(
    state: LiquiditySweepState,
    *,
    trade_direction: str,
    now: datetime,
    bid: float,
    ask: float,
    price_low: float,
    price_high: float,
    atr: float,
    timeout_minutes: int,
    max_sweep_atr: float,
) -> LiquiditySweepTransition:
    """Advance one quote observation for either side of a liquidity zone.

    Long: Bid sweeps the lower edge and Ask reclaims the upper edge.
    Short: Ask sweeps the upper edge and Bid reclaims the lower edge.
    Touch and reclaim must be separate observations. The deadline is exclusive,
    invalidation wins over timeout/reclaim, and an exact configured ATR boundary is allowed.
    """
    if trade_direction not in TRADE_DIRECTIONS:
        return LiquiditySweepTransition(state)
    now = _utc(now)
    if state.state in TERMINAL_STATES:
        return LiquiditySweepTransition(state)
    if atr <= 0 or price_low >= price_high or bid <= 0 or ask <= 0:
        return LiquiditySweepTransition(state)

    current = state
    just_touched = False
    if current.state == "idle":
        if not _touches_sweep_edge(trade_direction, bid, ask, price_low, price_high):
            return LiquiditySweepTransition(current)
        snapshot_atr = float(atr)
        sweep_limit = max(max_sweep_atr, 0.0) * snapshot_atr
        extreme = bid if trade_direction == "long" else ask
        invalidation = price_low - sweep_limit if trade_direction == "long" else price_high + sweep_limit
        current = LiquiditySweepState(
            state="waiting_reclaim",
            trade_direction=trade_direction,
            touched_edge_at=now,
            deadline_at=now + timedelta(minutes=max(timeout_minutes, 1)),
            atr_at_touch=snapshot_atr,
            extreme_price=extreme,
            invalidation_price=invalidation,
        )
        just_touched = True

    extreme = _next_extreme(trade_direction, current.extreme_price, bid, ask)
    current = LiquiditySweepState(
        state=current.state,
        trade_direction=trade_direction,
        touched_edge_at=current.touched_edge_at,
        deadline_at=current.deadline_at,
        atr_at_touch=current.atr_at_touch,
        extreme_price=extreme,
        invalidation_price=current.invalidation_price,
        reclaimed_at=current.reclaimed_at,
        terminal_reason=current.terminal_reason,
    )

    if _sweep_exceeded_limit(trade_direction, extreme, current.invalidation_price):
        return LiquiditySweepTransition(
            LiquiditySweepState(
                **{**current.__dict__, "state": "invalidated_breakout", "terminal_reason": "sweep_exceeded_max_atr"}
            )
        )
    if current.deadline_at is not None and now >= current.deadline_at:
        return LiquiditySweepTransition(
            LiquiditySweepState(**{**current.__dict__, "state": "timed_out", "terminal_reason": "reclaim_timeout"})
        )
    if just_touched:
        return LiquiditySweepTransition(current)
    if _reclaimed_opposite_edge(trade_direction, bid, ask, price_low, price_high):
        edge = "upper" if trade_direction == "long" else "lower"
        return LiquiditySweepTransition(
            LiquiditySweepState(
                **{
                    **current.__dict__,
                    "state": "reclaimed",
                    "reclaimed_at": now,
                    "terminal_reason": f"{edge}_edge_reclaimed",
                }
            ),
            became_eligible=True,
        )
    return LiquiditySweepTransition(current)


def transition_buy_liquidity_sweep(
    state: LiquiditySweepState,
    **kwargs: Any,
) -> LiquiditySweepTransition:
    """Backward-compatible long-side wrapper."""
    return transition_liquidity_sweep(state, trade_direction="long", **kwargs)


def evaluate_live_liquidity_zones(
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
    allowed_directions: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Persist account-scoped quote state and return reclaim candidates."""
    if not config.liquidity_sweep_reclaim_v1_enabled:
        return []
    now = _utc(now)
    atr = _latest_closed_atr(conn, symbol, timeframe, config.atr_period)
    if atr is None or atr <= 0:
        return []
    zone_directions = allowed_directions or {"bullish", "bearish"}
    placeholders = ",".join("?" for _ in zone_directions)
    zones = conn.execute(
        f"""
        SELECT * FROM price_zones
        WHERE symbol = ? AND UPPER(timeframe) = 'H1'
          AND zone_type = 'liquidity_pool' AND direction IN ({placeholders})
          AND status = 'active'
          AND (valid_until IS NULL OR valid_until > ?)
        ORDER BY effective_weight DESC, updated_at DESC
        """,
        (symbol, *sorted(zone_directions), now.isoformat()),
    ).fetchall()
    candidates: list[dict[str, Any]] = []
    for row in zones:
        metadata = _json_object(row["metadata_json"])
        modes = metadata.get("trade_modes")
        if not isinstance(modes, list) or TRADE_MODE not in {str(mode) for mode in modes}:
            continue
        trade_direction = "long" if str(row["direction"]) == "bullish" else "short"
        persisted = conn.execute(
            "SELECT * FROM liquidity_sweep_states WHERE zone_id = ? AND account_label = ?",
            (row["id"], account_label),
        ).fetchone()
        state = (
            _state_from_row(persisted, fallback_direction=trade_direction)
            if persisted is not None and str(persisted["zone_updated_at"]) == _zone_version(row)
            else LiquiditySweepState(trade_direction=trade_direction)
        )
        transition = transition_liquidity_sweep(
            state,
            trade_direction=trade_direction,
            now=now,
            bid=bid,
            ask=ask,
            price_low=float(row["price_low"]),
            price_high=float(row["price_high"]),
            atr=atr,
            timeout_minutes=config.liquidity_sweep_reclaim_v1_timeout_minutes,
            max_sweep_atr=config.liquidity_sweep_reclaim_v1_max_sweep_atr,
        )
        next_state = transition.state
        if transition.became_eligible:
            candidate = _build_candidate(
                row,
                transition.state,
                symbol=symbol,
                timeframe=timeframe,
                account_label=account_label,
                bid=bid,
                ask=ask,
                spread=spread,
                config=config,
            )
            if candidate is None:
                next_state = LiquiditySweepState(
                    **{
                        **transition.state.__dict__,
                        "state": "invalidated_risk",
                        "terminal_reason": "stop_distance_exceeded_3_atr",
                    }
                )
            else:
                candidates.append(candidate)
        _upsert_state(conn, row, account_label, next_state, now)
    conn.commit()
    return candidates


def evaluate_live_buy_liquidity_zones(conn: Connection, **kwargs: Any) -> list[dict[str, Any]]:
    """Backward-compatible evaluator restricted to bullish zones."""
    return evaluate_live_liquidity_zones(conn, allowed_directions={"bullish"}, **kwargs)


def _touches_sweep_edge(direction: str, bid: float, ask: float, low: float, high: float) -> bool:
    return bid <= low if direction == "long" else ask >= high


def _reclaimed_opposite_edge(direction: str, bid: float, ask: float, low: float, high: float) -> bool:
    return ask >= high if direction == "long" else bid <= low


def _next_extreme(direction: str, previous: float | None, bid: float, ask: float) -> float:
    observed = bid if direction == "long" else ask
    if previous is None:
        return float(observed)
    return min(float(previous), bid) if direction == "long" else max(float(previous), ask)


def _sweep_exceeded_limit(direction: str, extreme: float, invalidation: float | None) -> bool:
    if invalidation is None:
        return False
    return extreme < invalidation if direction == "long" else extreme > invalidation


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


def _state_from_row(row: Any, *, fallback_direction: str) -> LiquiditySweepState:
    keys = set(row.keys())
    direction = str(row["trade_direction"]) if "trade_direction" in keys and row["trade_direction"] else fallback_direction
    touched = row["touched_edge_at"] if "touched_edge_at" in keys else None
    extreme = row["extreme_price"] if "extreme_price" in keys else None
    if touched is None and "touched_lower_at" in keys:
        touched = row["touched_lower_at"]
    if extreme is None and "deepest_bid" in keys:
        extreme = row["deepest_bid"]
    return LiquiditySweepState(
        state=str(row["state"]),
        trade_direction=direction,
        touched_edge_at=_parse_datetime(touched),
        deadline_at=_parse_datetime(row["deadline_at"]),
        atr_at_touch=float(row["atr_at_touch"]) if row["atr_at_touch"] is not None else None,
        extreme_price=float(extreme) if extreme is not None else None,
        invalidation_price=float(row["invalidation_price"]) if row["invalidation_price"] is not None else None,
        reclaimed_at=_parse_datetime(row["reclaimed_at"]),
        terminal_reason=str(row["terminal_reason"]) if row["terminal_reason"] else None,
    )


def _upsert_state(conn: Connection, zone: Any, account_label: str, state: LiquiditySweepState, now: datetime) -> None:
    legacy_touched = _iso(state.touched_edge_at) if state.trade_direction == "long" else None
    legacy_extreme = state.extreme_price if state.trade_direction == "long" else None
    conn.execute(
        """
        INSERT INTO liquidity_sweep_states (
            zone_id, account_label, symbol, zone_updated_at, state, trade_direction,
            touched_edge_at, deadline_at, atr_at_touch, extreme_price,
            invalidation_price, reclaimed_at, terminal_reason, updated_at,
            touched_lower_at, deepest_bid
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(zone_id, account_label) DO UPDATE SET
            symbol = excluded.symbol, zone_updated_at = excluded.zone_updated_at,
            state = excluded.state, trade_direction = excluded.trade_direction,
            touched_edge_at = excluded.touched_edge_at, deadline_at = excluded.deadline_at,
            atr_at_touch = excluded.atr_at_touch, extreme_price = excluded.extreme_price,
            invalidation_price = excluded.invalidation_price, reclaimed_at = excluded.reclaimed_at,
            terminal_reason = excluded.terminal_reason, updated_at = excluded.updated_at,
            touched_lower_at = excluded.touched_lower_at, deepest_bid = excluded.deepest_bid
        """,
        (
            zone["id"], account_label, zone["symbol"], _zone_version(zone), state.state,
            state.trade_direction, _iso(state.touched_edge_at), _iso(state.deadline_at),
            state.atr_at_touch, state.extreme_price, state.invalidation_price,
            _iso(state.reclaimed_at), state.terminal_reason, now.isoformat(),
            legacy_touched, legacy_extreme,
        ),
    )


def _build_candidate(
    zone: Any,
    state: LiquiditySweepState,
    *,
    symbol: str,
    timeframe: str,
    account_label: str,
    bid: float,
    ask: float,
    spread: float,
    config: StrategyConfig,
) -> dict[str, Any] | None:
    atr = float(state.atr_at_touch or 0.0)
    extreme = float(state.extreme_price or (zone["price_low"] if state.trade_direction == "long" else zone["price_high"]))
    buffer = max(float(spread), config.liquidity_sweep_reclaim_v1_sl_buffer_atr * atr)
    if state.trade_direction == "long":
        entry = ask
        stop = extreme - buffer
        risk = entry - stop
        side = "buy"
        reason = "Bid swept the lower edge and Ask reclaimed the upper edge within the liquidity timeout."
    else:
        entry = bid
        stop = extreme + buffer
        risk = stop - entry
        side = "sell"
        reason = "Ask swept the upper edge and Bid reclaimed the lower edge within the liquidity timeout."
    stop_distance_atr = risk / atr if atr > 0 else float("inf")
    risk_reward = liquidity_sweep_rr_for_stop(stop_distance_atr)
    if risk_reward is None:
        return None
    take_profit = entry + risk * risk_reward if state.trade_direction == "long" else entry - risk * risk_reward
    touched_at = _iso(state.touched_edge_at)
    raw_id = f"{symbol}|{account_label}|{zone['id']}|{PLAYBOOK}|{state.trade_direction}|{touched_at}"
    candidate_id = hashlib.sha1(raw_id.encode("utf-8")).hexdigest()
    return {
        "id": candidate_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "playbook": PLAYBOOK,
        "direction": state.trade_direction,
        "status": "eligible",
        "zone_reaction_state": "liquidity_reclaim",
        "score": round(float(zone["effective_weight"]), 4),
        "entry": round(entry, 5),
        "stop_loss": round(stop, 5),
        "take_profit": [round(take_profit, 5)],
        "risk_reward": risk_reward,
        "primary_zone_id": str(zone["id"]),
        "related_zone_ids": [str(zone["id"])],
        "trigger_point_ids": [],
        "reason": [reason],
        "blocked_reason": [],
        "expires_at": _iso(state.deadline_at),
        "metadata": {
            "as_of": _iso(state.reclaimed_at),
            "order_type": "market",
            "entry_model": "quote_reclaim",
            "zone_type": "liquidity_pool",
            "liquidity_trade_side": side,
            "trade_modes": [TRADE_MODE],
            "trade_direction": state.trade_direction,
            "touched_edge_at": touched_at,
            "deadline_at": _iso(state.deadline_at),
            "atr_at_touch": round(atr, 5),
            "stop_distance_atr": round(stop_distance_atr, 5),
            "dynamic_risk_reward": risk_reward,
            "extreme_price": round(extreme, 5),
            "invalidation_price": round(float(state.invalidation_price or 0.0), 5),
            "max_sweep_atr": config.liquidity_sweep_reclaim_v1_max_sweep_atr,
            "partial_take_profit": {
                "enabled": True,
                "close_fraction": 0.4,
                "move_stop_to": "breakeven",
                "breakeven_buffer": 0.0,
            },
        },
    }


def liquidity_sweep_rr_for_stop(stop_distance_atr: float) -> float | None:
    """Return the final target RR for the structural stop width."""
    if stop_distance_atr <= 0:
        return None
    if stop_distance_atr <= 1.5:
        return 4.0
    if stop_distance_atr <= 2.25:
        return 3.0
    if stop_distance_atr <= 3.0:
        return 2.0
    return None


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
    return _utc(parsed)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return _utc(value).isoformat() if value is not None else None
