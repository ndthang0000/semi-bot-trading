from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..config import StrategyConfig
from .helpers import (
    candle_body,
    reaction_v2,
    zone_allows_breakout,
    zone_eligible_for_sr_breakout_v1,
    zone_has_explicit_trade_mode,
    zone_trade_modes,
    zone_width_atr_ratio,
)
from .types import PLAYBOOK_ZONE_TYPES, ReactionResult, SetupCandidate


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

# London-NY overlap (12:00–17:00 UTC) has the highest gold volume/momentum.
_LONDON_NY_START = 12
_LONDON_NY_END = 17


def _candle_hour_utc(candle: dict[str, Any]) -> int | None:
    """Return the UTC hour of a candle's open_time, or None if unparseable."""
    raw = candle.get("time") or candle.get("open_time")
    if raw is None:
        return None
    try:
        dt = datetime.fromisoformat(str(raw))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.hour
    except ValueError:
        return None


def _in_london_ny_session(candle: dict[str, Any]) -> bool:
    hour = _candle_hour_utc(candle)
    if hour is None:
        return True  # unknown → allow rather than block
    return _LONDON_NY_START <= hour < _LONDON_NY_END


# ---------------------------------------------------------------------------
# Direction: which way does a breakout trade go?
# ---------------------------------------------------------------------------

def sr_breakout_direction(zone: dict[str, Any], macro_trend: str) -> tuple[str | None, bool]:
    zone_type = str(zone.get("type"))
    human_breakout = zone_has_explicit_trade_mode(zone, "breakout")
    # Human breakout mode bypasses every context gate including macro trend:
    # direction comes purely from which side the zone breaks.
    if human_breakout:
        if zone_type == "resistance":
            return "long", True
        if zone_type == "support":
            return "short", True
        return None, True
    # Bot zones stay macro-aligned: long breakouts only in an up trend,
    # short breakouts only in a down trend.
    if macro_trend == "up" and zone_type == "resistance":
        return "long", False
    if macro_trend == "down" and zone_type == "support":
        return "short", False
    return None, False


# ---------------------------------------------------------------------------
# Classification: what stage is the breakout in?
# ---------------------------------------------------------------------------

def classify_sr_breakout_v1(
    zone: dict[str, Any],
    candles: list[dict[str, Any]],
    atr: float,
    direction: str,
    config: StrategyConfig,
) -> ReactionResult:
    last = candles[-1]
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    close = float(last["close"])
    high = float(last["high"])
    low = float(last["low"])
    buffer = atr * config.sr_breakout_v1_breakout_buffer_atr
    near_limit = atr * config.sr_breakout_v1_market_entry_max_distance_atr

    retest = sr_breakout_retest_reaction(zone, candles, atr, direction, config)
    if retest is not None:
        return retest

    # Weak-bodied candles drifting past the zone edge are not real breakouts;
    # they are the group most likely to mean-revert straight back into the zone.
    body_ok = candle_body(last) >= atr * config.sr_breakout_v1_min_body_atr

    if direction == "long":
        distance = close - zone_high
        if distance >= buffer and not body_ok:
            return reaction_v2(
                "waiting_retest",
                "long",
                high >= zone_high,
                last,
                ["Breakout body too small; waiting for retest instead of market entry."],
                buffer,
                {"entry_model": "wait_retest", "breakout_body_atr": round(candle_body(last) / max(atr, 0.00001), 4)},
            )
        if distance >= buffer:
            return reaction_v2(
                "breakout_close" if distance <= near_limit else "waiting_retest",
                "long",
                high >= zone_high,
                last,
                [
                    "H1 closed above resistance breakout buffer."
                    if distance <= near_limit
                    else "H1 breakout closed far above resistance; waiting for retest."
                ],
                buffer,
                {
                    "entry_model": "next_h1_open" if distance <= near_limit else "wait_retest",
                    "breakout_close_distance": round(distance, 5),
                    "breakout_close_distance_atr": round(distance / max(atr, 0.00001), 4),
                },
            )
    else:
        distance = zone_low - close
        if distance >= buffer and not body_ok:
            return reaction_v2(
                "waiting_retest",
                "short",
                low <= zone_low,
                last,
                ["Breakout body too small; waiting for retest instead of market entry."],
                buffer,
                {"entry_model": "wait_retest", "breakout_body_atr": round(candle_body(last) / max(atr, 0.00001), 4)},
            )
        if distance >= buffer:
            return reaction_v2(
                "breakout_close" if distance <= near_limit else "waiting_retest",
                "short",
                low <= zone_low,
                last,
                [
                    "H1 closed below support breakout buffer."
                    if distance <= near_limit
                    else "H1 breakout closed far below support; waiting for retest."
                ],
                buffer,
                {
                    "entry_model": "next_h1_open" if distance <= near_limit else "wait_retest",
                    "breakout_close_distance": round(distance, 5),
                    "breakout_close_distance_atr": round(distance / max(atr, 0.00001), 4),
                },
            )
    return reaction_v2("far", direction, False, last, [], buffer)


def sr_breakout_retest_reaction(
    zone: dict[str, Any],
    candles: list[dict[str, Any]],
    atr: float,
    direction: str,
    config: StrategyConfig,
) -> ReactionResult | None:
    if len(candles) < 3:
        return None
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    buffer = atr * config.sr_breakout_v1_breakout_buffer_atr
    near_limit = atr * config.sr_breakout_v1_market_entry_max_distance_atr
    last = candles[-1]
    lookback = candles[-(config.sr_breakout_v1_retest_max_bars + 1):-1]
    breakout_candle: dict[str, Any] | None = None
    min_body = atr * config.sr_breakout_v1_min_body_atr
    for candle in reversed(lookback):
        close = float(candle["close"])
        if direction == "long":
            distance = close - zone_high
        else:
            distance = zone_low - close
        if distance > near_limit and candle_body(candle) >= min_body:
            breakout_candle = candle
            break
    if breakout_candle is None:
        return None

    high = float(last["high"])
    low = float(last["low"])
    close = float(last["close"])
    if direction == "long":
        retested = low <= zone_high + buffer and high >= zone_low
        if retested and close > zone_high:
            return reaction_v2(
                "retest_breakout",
                "long",
                True,
                last,
                ["Far resistance breakout retested and held above zone."],
                buffer,
                {
                    "entry_model": "retest_next_h1_open",
                    "breakout_candle_time": breakout_candle.get("time"),
                    "state_machine_path": "BREAKOUT_CONFIRMED -> WAITING_RETEST -> RETEST_CONFIRMED -> PREPARE_ENTRY",
                },
            )
        if retested and close < zone_low:
            return reaction_v2(
                "far",
                "long",
                True,
                last,
                ["Broken resistance retest failed; H1 closed back below the zone."],
                buffer,
                {"entry_model": "failed_retest", "breakout_candle_time": breakout_candle.get("time")},
            )
        if retested:
            return reaction_v2(
                "waiting_retest",
                "long",
                True,
                last,
                ["Retest touched broken resistance; waiting for close back above zone."],
                buffer,
                {"entry_model": "wait_retest", "breakout_candle_time": breakout_candle.get("time")},
            )
    else:
        retested = high >= zone_low - buffer and low <= zone_high
        if retested and close < zone_low:
            return reaction_v2(
                "retest_breakout",
                "short",
                True,
                last,
                ["Far support breakout retested and held below zone."],
                buffer,
                {
                    "entry_model": "retest_next_h1_open",
                    "breakout_candle_time": breakout_candle.get("time"),
                    "state_machine_path": "BREAKOUT_CONFIRMED -> WAITING_RETEST -> RETEST_CONFIRMED -> PREPARE_ENTRY",
                },
            )
        if retested and close > zone_high:
            return reaction_v2(
                "far",
                "short",
                True,
                last,
                ["Broken support retest failed; H1 closed back above the zone."],
                buffer,
                {"entry_model": "failed_retest", "breakout_candle_time": breakout_candle.get("time")},
            )
        if retested:
            return reaction_v2(
                "waiting_retest",
                "short",
                True,
                last,
                ["Retest touched broken support; waiting for close back below zone."],
                buffer,
                {"entry_model": "wait_retest", "breakout_candle_time": breakout_candle.get("time")},
            )
    return None


# ---------------------------------------------------------------------------
# Levels: entry / stop / take-profit
# ---------------------------------------------------------------------------

def compute_sr_breakout_v1_levels(
    direction: str,
    signal_candle: dict[str, Any],
    atr: float,
    config: StrategyConfig,
    zone: dict[str, Any] | None = None,
    stop_atr: float | None = None,
) -> tuple[float | None, float | None, list[float], float | None]:
    entry = round(float(signal_candle["close"]), 5)
    rr = config.sr_breakout_v1_rr
    effective_stop_atr = stop_atr if stop_atr is not None else atr
    stop_distance = effective_stop_atr * config.sr_breakout_v1_sl_atr
    if config.sr_breakout_v1_sl_mode == "zone_edge" and zone is not None:
        # Structural stop: the broken edge flips role (resistance -> support),
        # so invalidation is a close back through that edge plus a buffer.
        # A floor keeps the stop from collapsing when entry hugs the edge.
        edge_buffer = effective_stop_atr * config.sr_breakout_v1_sl_zone_buffer_atr
        min_distance = effective_stop_atr * config.sr_breakout_v1_sl_min_atr
        if direction == "long":
            natural = float(zone["price_high"]) - edge_buffer
            stop_distance = max(entry - natural, min_distance)
        else:
            natural = float(zone["price_low"]) + edge_buffer
            stop_distance = max(natural - entry, min_distance)
    if direction == "long":
        stop = round(entry - stop_distance, 5)
        tp = round(entry + stop_distance * rr, 5)
    else:
        stop = round(entry + stop_distance, 5)
        tp = round(entry - stop_distance * rr, 5)
    return entry, stop, [tp], round(rr, 4)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_sr_breakout_v1(
    zone: dict[str, Any],
    reaction: ReactionResult,
    direction: str,
    macro_trend: str,
    status: str,
) -> float:
    score = float(zone.get("weight") or 0.0) * 0.35
    score += {"breakout_close": 0.32, "retest_breakout": 0.36, "waiting_retest": 0.16}.get(reaction.state, 0.0)
    if (macro_trend == "up" and direction == "long") or (macro_trend == "down" and direction == "short"):
        score += 0.18
    if str(zone.get("source")) in {"human", "mixed"} or "breakout" in zone_trade_modes(zone):
        score += 0.08
    if status == "blocked":
        score *= 0.5
    return round(min(score, 1.0), 4)


# ---------------------------------------------------------------------------
# State machine (UI visualization)
# ---------------------------------------------------------------------------

def sr_breakout_v1_state_machine(reaction: ReactionResult, status: str) -> list[dict[str, str]]:
    active = "IDLE"
    if reaction.state == "breakout_close":
        active = "PREPARE_ENTRY" if status == "eligible" else "BREAKOUT_CONFIRMED"
    elif reaction.state == "waiting_retest":
        active = "WAITING_RETEST"
    elif reaction.state == "retest_breakout":
        active = "PREPARE_ENTRY" if status == "eligible" else "RETEST_CONFIRMED"
    elif status == "blocked":
        active = "IDLE"
    steps = [
        ("IDLE", "Wait SR zone"),
        ("BREAKOUT_CONFIRMED", "H1 close outside zone"),
        ("WAITING_RETEST", "Wait retest"),
        ("RETEST_CONFIRMED", "Retest held"),
        ("PREPARE_ENTRY", "Prepare entry"),
    ]
    order = {key: index for index, (key, _) in enumerate(steps)}
    return [
        {
            "key": key,
            "label": label,
            "status": "active" if key == active else "done" if order[key] < order.get(active, 99) else "pending",
        }
        for key, label in steps
    ]


# ---------------------------------------------------------------------------
# Evaluation: given a classified reaction, should we trade?
# ---------------------------------------------------------------------------

def evaluate_sr_breakout_v1(
    symbol: str,
    zone: dict[str, Any],
    candles: list[dict[str, Any]],
    atr: float,
    stop_atr: float | None,
    macro_trend: str,
    bias: str,
    regime: str,
    config: StrategyConfig,
) -> list[SetupCandidate]:
    if not config.sr_breakout_v1_enabled or len(candles) < 2:
        return []
    zone_type = str(zone.get("type"))
    if zone_type not in PLAYBOOK_ZONE_TYPES["sr_breakout_v1"]:
        return []
    if not zone_allows_breakout(zone, config):
        return []

    direction, context_bypass = sr_breakout_direction(zone, macro_trend)
    if direction is None:
        return []
    reaction = classify_sr_breakout_v1(zone, candles, atr, direction, config)
    if reaction.state == "far":
        return []

    last = candles[-1]
    if not _in_london_ny_session(last):
        return []
    entry, stop, take_profit, rr = compute_sr_breakout_v1_levels(direction, last, atr, config, zone, stop_atr=stop_atr)
    blocked: list[str] = []
    reasons = [
        "SR Breakout V1 uses H1 close outside support/resistance.",
        f"Breakout model: {reaction.state}.",
    ]
    if context_bypass:
        reasons.append("Human breakout mode bypasses all context gates including macro trend.")
    else:
        reasons.append(f"Macro trend {macro_trend} allows {direction} breakout.")
    stop_distance = abs(entry - stop) if entry is not None and stop is not None else None
    if stop_distance is not None and stop_distance > config.sr_breakout_v1_max_stop_distance:
        blocked.append(
            f"Stop distance {stop_distance:.2f} exceeds SR Breakout V1 maximum {config.sr_breakout_v1_max_stop_distance:.2f}."
        )
    allowed_entries = set(config.sr_breakout_v1_allowed_entries)
    if blocked:
        status = "blocked"
    elif reaction.state in {"breakout_close", "retest_breakout"} and reaction.state in allowed_entries:
        status = "eligible"
    else:
        status = "waiting_confirmation"
        if reaction.state in {"breakout_close", "retest_breakout"}:
            # Detected but disabled entries stay visible for UI/alerts/research.
            # breakout_close backtested at -5.24R/45 trades (buying the top of the
            # move); retest entries are the configured default.
            reasons.append(f"Entry {reaction.state} is disabled for SR Breakout V1; waiting for allowed entry.")
    score = score_sr_breakout_v1(zone, reaction, direction, macro_trend, status)
    candidate = SetupCandidate(
        symbol=symbol,
        timeframe="H1",
        playbook="sr_breakout_v1",
        direction=direction,
        status=status,
        zone_reaction_state=reaction.state,
        score=score,
        entry=entry,
        stop_loss=stop,
        take_profit=take_profit,
        risk_reward=rr,
        primary_zone_id=str(zone.get("id")) if zone.get("id") else None,
        related_zone_ids=[str(zone.get("id"))] if zone.get("id") else [],
        trigger_point_ids=[],
        reason=[*reasons, *reaction.reason],
        blocked_reason=blocked,
        expires_at=None,
        metadata={
            "as_of": last.get("time"),
            "zone_type": zone_type,
            "zone_direction": zone.get("direction"),
            "zone_detector": zone.get("detector"),
            "zone_source": zone.get("source"),
            "zone_status": zone.get("status"),
            "zone_weight": zone.get("weight"),
            "zone_confidence": zone.get("confidence"),
            "zone_price_low": zone.get("price_low"),
            "zone_price_high": zone.get("price_high"),
            "zone_width": round(float(zone["price_high"]) - float(zone["price_low"]), 5),
            "zone_width_atr": round(zone_width_atr_ratio(zone, atr), 4),
            "zone_detected_at": zone.get("detected_at"),
            "zone_visual_start": zone.get("visual_start"),
            "h1_bias": bias,
            "h1_regime": regime,
            "macro_trend": macro_trend,
            "atr": round(atr, 5),
            "stop_atr": round(stop_atr, 5) if stop_atr is not None else round(atr, 5),
            "stop_atr_multiplier": config.sr_breakout_v1_sl_atr,
            "entry_model": reaction.metadata.get("entry_model"),
            "breakout_close_distance_atr": reaction.metadata.get("breakout_close_distance_atr"),
            "context_bypass": context_bypass,
            "trade_modes": zone_trade_modes(zone),
            "reaction_v2": reaction.state,
            "state_machine": sr_breakout_v1_state_machine(reaction, status),
            **reaction.metadata,
        },
    )
    return [candidate]
