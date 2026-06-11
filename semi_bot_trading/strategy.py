from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .config import StrategyConfig
from .zones import CandleSlice, latest_atr


BULLISH_PA = {"pinbar_bullish", "engulfing_bullish", "marubozu_bullish", "morning_star", "displacement_bullish"}
BEARISH_PA = {"pinbar_bearish", "engulfing_bearish", "marubozu_bearish", "evening_star", "displacement_bearish"}
BULLISH_BREAKS = {"BOS", "CHOCH"}
BEARISH_BREAKS = {"BOS", "CHOCH"}
PLAYBOOK_ZONE_TYPES: dict[str, set[str]] = {
    "zone_reaction_v2": {"support", "resistance", "fvg"},
}


@dataclass(frozen=True)
class ReactionResult:
    state: str
    direction: str | None
    touched: bool
    candle_time: str | None
    reason: list[str]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SetupCandidate:
    symbol: str
    timeframe: str
    playbook: str
    direction: str
    status: str
    zone_reaction_state: str
    score: float
    entry: float | None
    stop_loss: float | None
    take_profit: list[float]
    risk_reward: float | None
    primary_zone_id: str | None
    related_zone_ids: list[str]
    trigger_point_ids: list[str]
    reason: list[str]
    blocked_reason: list[str]
    expires_at: str | None
    metadata: dict[str, Any]

    @property
    def id(self) -> str:
        raw = (
            f"{self.symbol}|{self.timeframe}|{self.playbook}|{self.direction}|"
            f"{self.primary_zone_id}|{self.zone_reaction_state}|{self.metadata.get('as_of')}"
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def to_chart(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "playbook": self.playbook,
            "direction": self.direction,
            "status": self.status,
            "zone_reaction_state": self.zone_reaction_state,
            "score": round(self.score, 4),
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_reward": self.risk_reward,
            "primary_zone_id": self.primary_zone_id,
            "related_zone_ids": self.related_zone_ids,
            "trigger_point_ids": self.trigger_point_ids,
            "reason": self.reason,
            "blocked_reason": self.blocked_reason,
            "expires_at": self.expires_at,
            "metadata": self.metadata,
        }


def build_setup_candidates(
    symbol: str,
    zones: list[dict[str, Any]],
    contexts: dict[str, dict[str, dict[str, Any]]],
    candles: list[dict[str, Any]],
    structure_points: list[dict[str, Any]],
    config: StrategyConfig,
    context_timeframe: str = "H1",
    allowed_playbooks: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not candles:
        return []
    candle_slices = chart_candles_to_slices(candles)
    atr = latest_atr(candle_slices, period=config.atr_period) or latest_range(candles) or 1.0
    last_candle = candles[-1]
    last_close = float(last_candle["close"])
    bias = contexts.get(context_timeframe, {}).get("bias", {})
    regime = contexts.get(context_timeframe, {}).get("regime", {})
    bias_value = str(bias.get("effective_value") or "neutral")
    secondary_bias = bias.get("secondary_value")
    regime_value = str(regime.get("effective_value") or "unknown")
    overlays = parse_overlays(regime)

    recent_points = [point for point in structure_points if point.get("time") <= last_candle["time"]]
    candidates: list[SetupCandidate] = []
    allowed_zone_types = allowed_zone_types_for_playbooks(allowed_playbooks)
    active_zones = [
        zone
        for zone in zones
        if zone.get("status") == "active"
        and (allowed_zone_types is None or str(zone.get("type")) in allowed_zone_types)
        and not zone_trade_disabled_after_sweep(zone)
    ]

    for zone in active_zones:
        # Runtime strategy is intentionally Zone Reaction V2 only. Other detectors
        # can still draw zones on the chart, but they do not emit legacy trades.
        if not playbook_allowed("zone_reaction_v2", allowed_playbooks):
            continue
        reaction_v2 = classify_zone_reaction_v2(zone, candles, atr, config)
        if reaction_v2.state == "far":
            continue
        candidates.extend(
            evaluate_zone_reaction_v2(
                symbol,
                zone,
                reaction_v2,
                last_close,
                atr,
                bias_value,
                secondary_bias,
                regime_value,
                overlays,
                recent_points,
                active_zones,
                config,
                as_of=str(last_candle["time"]),
            )
        )

    if allowed_playbooks is not None:
        candidates = [candidate for candidate in candidates if candidate.playbook in allowed_playbooks]

    ranked = sorted(candidates, key=lambda item: (status_rank(item.status), item.score), reverse=True)
    selected: list[SetupCandidate] = []
    eligible_count = 0
    waiting_count = 0
    blocked_count = 0
    for candidate in ranked:
        if candidate.status == "eligible":
            if eligible_count >= config.max_eligible:
                continue
            eligible_count += 1
        elif candidate.status in {"watching", "waiting_confirmation"}:
            if waiting_count >= config.max_waiting:
                continue
            waiting_count += 1
        elif candidate.status == "blocked":
            if blocked_count >= config.max_waiting:
                continue
            blocked_count += 1
        selected.append(candidate)
    return [candidate.to_chart() for candidate in selected]


def evaluate_zone_reaction_v2(
    symbol: str,
    zone: dict[str, Any],
    reaction: ReactionResult,
    last_close: float,
    atr: float,
    bias: str,
    secondary_bias: Any,
    regime: str,
    overlays: set[str],
    structure_points: list[dict[str, Any]],
    zones: list[dict[str, Any]],
    config: StrategyConfig,
    as_of: str,
) -> list[SetupCandidate]:
    if not config.zone_reaction_v2_enabled:
        return []
    if str(zone.get("type")) not in PLAYBOOK_ZONE_TYPES["zone_reaction_v2"]:
        return []

    direction = reaction.direction
    if direction not in {"long", "short"}:
        return []

    trigger_ids = trigger_points_for_direction(structure_points, direction, as_of, not_before=reaction.candle_time)
    trigger_types = trigger_types_for_ids(structure_points, trigger_ids)
    confluence = zone_confluence_metadata(zone, zones, atr, config.zone_reaction_v2_confluence_score_bonus)
    status, blocked, reasons = zone_reaction_v2_status(direction, reaction, bool(trigger_ids), bias, secondary_bias, regime, config)
    entry, stop, take_profit, rr = compute_zone_reaction_v2_levels(zone, direction, reaction, last_close, atr, config)
    stop_distance = abs(entry - stop) if entry is not None and stop is not None else None
    if rr is None or rr < config.zone_reaction_v2_rr_minimum:
        blocked.append(f"RR {rr or 0:.2f} is below Zone Reaction V2 minimum {config.zone_reaction_v2_rr_minimum:.2f}.")
        status = "blocked"
    if (
        stop_distance is not None
        and config.zone_reaction_v2_max_stop_distance > 0
        and stop_distance > config.zone_reaction_v2_max_stop_distance
    ):
        blocked.append(
            f"Stop distance {stop_distance:.2f} exceeds Zone Reaction V2 maximum "
            f"{config.zone_reaction_v2_max_stop_distance:.2f}."
        )
        status = "blocked"
    if blocked:
        status = "blocked"

    score = score_zone_reaction_v2(zone, reaction, direction, bias, regime, overlays, rr, bool(trigger_ids), status, confluence, config)
    candidate = SetupCandidate(
        symbol=symbol,
        timeframe=config.timeframe,
        playbook="zone_reaction_v2",
        direction=direction,
        status=status,
        zone_reaction_state=reaction.state,
        score=score,
        entry=entry,
        stop_loss=stop,
        take_profit=take_profit,
        risk_reward=rr,
        primary_zone_id=str(zone.get("id")) if zone.get("id") else None,
        related_zone_ids=[str(zone.get("id"))] + list(confluence["confluence_zone_ids"]),
        trigger_point_ids=trigger_ids,
        reason=reasons + reaction.reason,
        blocked_reason=blocked,
        expires_at=None,
        metadata={
            "as_of": as_of,
            "zone_type": zone.get("type"),
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
            "zone_touch_count": zone_touch_count(zone),
            "zone_mitigation_ratio": zone.get("metadata", {}).get("mitigation_ratio") if isinstance(zone.get("metadata"), dict) else None,
            "zone_fill_ratio": zone.get("metadata", {}).get("fill_ratio") if isinstance(zone.get("metadata"), dict) else None,
            "h1_bias": bias,
            "h1_regime": regime,
            "overlays": sorted(overlays),
            "trigger_types": trigger_types,
            "atr": round(atr, 5),
            "reaction_v2": reaction.state,
            "state_machine": zone_reaction_v2_state_machine(reaction, status, blocked, bool(trigger_ids)),
            "confluence_count": confluence["confluence_count"],
            "confluence_types": confluence["confluence_types"],
            "confluence_score_bonus": confluence["confluence_score_bonus"],
            **reaction.metadata,
        },
    )
    return [candidate]


def zone_reaction_v2_status(
    direction: str,
    reaction: ReactionResult,
    has_trigger: bool,
    bias: str,
    secondary_bias: Any,
    regime: str,
    config: StrategyConfig,
) -> tuple[str, list[str], list[str]]:
    blocked: list[str] = []
    reasons = ["Zone Reaction V2 single-zone reaction setup.", f"Reaction V2: {reaction.state}."]
    if config.zone_reaction_v2_block_news_or_risk_off and regime in {"news", "risk_off"}:
        blocked.append(f"Regime {regime} blocks Zone Reaction V2.")

    expected = bias_to_direction(bias)
    if direction != expected:
        if bias == "neutral":
            if not (config.zone_reaction_v2_allow_neutral_range_trade and regime == "ranging"):
                blocked.append("Neutral bias only allows Zone Reaction V2 range trade in ranging regime.")
            else:
                reasons.append("Neutral+ranging allows two-sided zone reaction.")
        elif secondary_allows_direction(secondary_bias, direction):
            reasons.append("Countertrend allowed by human secondary bias.")
        else:
            blocked.append("Zone Reaction V2 requires direction aligned with bias.")

    if reaction.state == "fakeout" and config.zone_reaction_v2_require_trigger_for_fakeout and not has_trigger:
        reasons.append("Fakeout requires M15 trigger; waiting for confirmation.")
        status = "waiting_confirmation"
    elif (
        reaction.state == "fakeout"
        and float(reaction.metadata.get("fakeout_reaction_depth_atr", 0.0)) > config.zone_reaction_v2_fakeout_max_reaction_depth_atr
    ):
        reasons.append("Fakeout wick is too deep; waiting for follow-through confirmation.")
        status = "waiting_confirmation"
    elif reaction.state not in set(config.zone_reaction_v2_allowed_reactions):
        # We still surface disabled states in UI/backtest metadata so humans can
        # debug the state machine, but only configured reactions may become trades.
        reasons.append(f"Reaction {reaction.state} is disabled for Zone Reaction V2; reject-only phase keeps it for debug only.")
        status = "waiting_confirmation"
    elif reaction.state in {"reject", "fakeout", "retest_reject"}:
        status = "eligible"
    elif reaction.state == "waiting_bos" and has_trigger:
        reasons.append("BOS/CHOCH confirmed after slow reaction.")
        status = "eligible"
    elif reaction.state in {"slow_reaction", "waiting_bos", "waiting_retest", "clean_breakout"}:
        status = "waiting_confirmation"
    elif reaction.state == "invalid":
        status = "blocked"
    else:
        status = "blocked"
    return status, blocked, reasons


def zone_reaction_v2_state_machine(
    reaction: ReactionResult,
    status: str,
    blocked: list[str],
    has_trigger: bool,
) -> list[dict[str, str]]:
    active = reaction.state
    if reaction.state == "retest_reject":
        active = "PREPARE_ENTRY"
    elif reaction.state in {"reject", "fakeout"} and status == "eligible":
        active = "PREPARE_ENTRY"
    elif reaction.state == "fakeout" and status == "waiting_confirmation":
        active = "WAIT_FOR_BOS"
    elif reaction.state == "waiting_bos":
        active = "PREPARE_ENTRY" if has_trigger and status == "eligible" else "WAIT_FOR_BOS"
    elif reaction.state == "slow_reaction":
        active = "WAIT_FOR_BOS"
    elif reaction.state == "clean_breakout":
        active = "WAITING_RETEST" if status != "blocked" else "BIAS_WARNING"
    elif reaction.state == "waiting_retest":
        active = "WAITING_RETEST"
    elif status == "blocked" or blocked:
        active = "BIAS_WARNING" if reaction.state == "clean_breakout" else "IDLE"

    steps = [
        ("IDLE", "Context check"),
        ("ZONE_TOUCHED", "Zone touched"),
        ("REACTING_IN_ZONE", "M15 reaction"),
        ("WAIT_FOR_BOS", "Wait BOS/CHOCH"),
        ("WAITING_RETEST", "Wait retest"),
        ("BIAS_WARNING", "Bias warning"),
        ("PREPARE_ENTRY", "Prepare entry"),
    ]
    return [
        {
            "key": key,
            "label": label,
            "status": "active" if key == active else "done" if step_done(key, active) else "pending",
        }
        for key, label in steps
    ]


def step_done(key: str, active: str) -> bool:
    order = {
        "IDLE": 0,
        "ZONE_TOUCHED": 1,
        "REACTING_IN_ZONE": 2,
        "WAIT_FOR_BOS": 3,
        "WAITING_RETEST": 3,
        "BIAS_WARNING": 4,
        "PREPARE_ENTRY": 5,
    }
    return order.get(key, 99) < order.get(active, 99)


def playbook_allowed(playbook: str, allowed_playbooks: set[str] | None) -> bool:
    return allowed_playbooks is None or playbook in allowed_playbooks


def zone_trade_disabled_after_sweep(zone: dict[str, Any]) -> bool:
    metadata = zone.get("metadata")
    return bool(isinstance(metadata, dict) and metadata.get("trade_disabled_after_sweep"))


def allowed_zone_types_for_playbooks(allowed_playbooks: set[str] | None) -> set[str]:
    playbooks = set(PLAYBOOK_ZONE_TYPES) if allowed_playbooks is None else allowed_playbooks
    zone_types: set[str] = set()
    for playbook in playbooks:
        zone_types.update(PLAYBOOK_ZONE_TYPES.get(playbook, set()))
    return zone_types


def classify_zone_reaction_v2(
    zone: dict[str, Any],
    candles: list[dict[str, Any]],
    atr: float,
    config: StrategyConfig,
) -> ReactionResult:
    if not candles:
        return reaction("far", None, False, {}, [], 0.0)
    zone_type = str(zone.get("type"))
    if zone_type == "order_block":
        return reaction("far", None, False, candles[-1], ["Order Block is excluded from Zone Reaction V2."], 0.0)
    if zone_type == "consolidation":
        return classify_consolidation_reaction_v2(zone, candles, atr, config)

    last = candles[-1]
    low = float(last["low"])
    high = float(last["high"])
    close = float(last["close"])
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    touched = high >= zone_low and low <= zone_high
    expected = expected_trade_direction(zone)
    if expected not in {"long", "short"}:
        return reaction("far", None, touched, last, [], 0.0)

    retest = breakout_retest_reaction(zone, candles, atr, config, expected)
    if retest is not None:
        return retest

    body = candle_body(last)
    avg_body = average_body(candles, config.zone_reaction_v2_reject_avg_body_period)
    strong_reject = body >= avg_body * config.zone_reaction_v2_reject_body_min_ratio
    breakout_body = body >= atr * config.zone_reaction_v2_breakout_min_body_atr
    fakeout_limit = atr * config.zone_reaction_v2_fakeout_max_atr
    buffer = atr * config.breakout_buffer_atr_multiplier
    min_close_outside = atr * config.zone_reaction_v2_breakout_min_close_outside_atr

    if expected == "long":
        penetration = max(zone_low - low, 0.0)
        if penetration > 0 and penetration <= fakeout_limit and close >= zone_low:
            reaction_depth = max(close - low, 0.0)
            return reaction_v2(
                "fakeout",
                "long",
                True,
                last,
                ["Fakeout below bullish zone and close reclaimed zone."],
                buffer,
                {
                    "fakeout_distance_atr": round(penetration / max(atr, 0.00001), 4),
                    "fakeout_reaction_depth_atr": round(reaction_depth / max(atr, 0.00001), 4),
                },
            )
        if touched and close > zone_high and strong_reject:
            return reaction_v2("reject", "long", True, last, ["Strong bullish rejection from zone."], buffer)
        close_outside = zone_low - close
        if close_outside >= min_close_outside and breakout_body:
            return reaction_v2(
                "clean_breakout",
                "short",
                touched,
                last,
                ["Clean break below bullish zone."],
                buffer,
                {
                    "bias_phase": "transition_bearish",
                    "breakout_close_outside_atr": round(close_outside / max(atr, 0.00001), 4),
                },
            )
    else:
        penetration = max(high - zone_high, 0.0)
        if penetration > 0 and penetration <= fakeout_limit and close <= zone_high:
            reaction_depth = max(high - close, 0.0)
            return reaction_v2(
                "fakeout",
                "short",
                True,
                last,
                ["Fakeout above bearish zone and close reclaimed zone."],
                buffer,
                {
                    "fakeout_distance_atr": round(penetration / max(atr, 0.00001), 4),
                    "fakeout_reaction_depth_atr": round(reaction_depth / max(atr, 0.00001), 4),
                },
            )
        if touched and close < zone_low and strong_reject:
            return reaction_v2("reject", "short", True, last, ["Strong bearish rejection from zone."], buffer)
        close_outside = close - zone_high
        if close_outside >= min_close_outside and breakout_body:
            return reaction_v2(
                "clean_breakout",
                "long",
                touched,
                last,
                ["Clean break above bearish zone."],
                buffer,
                {
                    "bias_phase": "transition_bullish",
                    "breakout_close_outside_atr": round(close_outside / max(atr, 0.00001), 4),
                },
            )

    slow = slow_reaction_direction(zone, candles, atr, config)
    if slow:
        return reaction_v2("slow_reaction", slow, True, last, ["Slow reaction inside zone; waiting for BOS/CHOCH."], buffer)
    if touched:
        return reaction_v2("waiting_bos", expected, True, last, ["Touched zone; waiting for stronger M15 reaction."], buffer)
    return reaction_v2("far", expected, False, last, [], buffer)


def breakout_retest_reaction(
    zone: dict[str, Any],
    candles: list[dict[str, Any]],
    atr: float,
    config: StrategyConfig,
    expected: str,
) -> ReactionResult | None:
    if len(candles) < 2:
        return None
    last = candles[-1]
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    buffer = atr * config.breakout_buffer_atr_multiplier
    breakout_body_threshold = atr * config.zone_reaction_v2_breakout_min_body_atr
    min_close_outside = atr * config.zone_reaction_v2_breakout_min_close_outside_atr
    lookback = candles[-(config.zone_reaction_v2_retest_max_bars + 1) : -1]
    breakout_candle: dict[str, Any] | None = None
    breakout_direction: str | None = None

    for candle in reversed(lookback):
        body = candle_body(candle)
        close = float(candle["close"])
        if expected == "long" and zone_low - close >= min_close_outside and body >= breakout_body_threshold:
            breakout_candle = candle
            breakout_direction = "short"
            break
        if expected == "short" and close - zone_high >= min_close_outside and body >= breakout_body_threshold:
            breakout_candle = candle
            breakout_direction = "long"
            break
    if breakout_candle is None or breakout_direction is None:
        return None

    high = float(last["high"])
    low = float(last["low"])
    close = float(last["close"])
    body = candle_body(last)
    avg_body = average_body(candles, config.zone_reaction_v2_reject_avg_body_period)
    strong_retest_reject = body >= avg_body
    if breakout_direction == "short":
        retested = high >= zone_low and low <= zone_high
        if retested and close < zone_low and strong_retest_reject:
            return reaction_v2(
                "retest_reject",
                "short",
                True,
                last,
                ["Clean break below zone, retest rejected from underside."],
                buffer,
                {
                    "breakout_candle_time": breakout_candle.get("time"),
                    "breakout_direction": "short",
                    "state_machine_path": "CLEAN_BREAK -> WAITING_RETEST -> RETEST_REJECT -> PREPARE_ENTRY",
                },
            )
        if retested:
            return reaction_v2(
                "waiting_retest",
                "short",
                True,
                last,
                ["Clean break below zone; retest is still waiting for bearish rejection."],
                buffer,
                {"breakout_candle_time": breakout_candle.get("time"), "breakout_direction": "short"},
            )
    else:
        retested = low <= zone_high and high >= zone_low
        if retested and close > zone_high and strong_retest_reject:
            return reaction_v2(
                "retest_reject",
                "long",
                True,
                last,
                ["Clean break above zone, retest rejected from topside."],
                buffer,
                {
                    "breakout_candle_time": breakout_candle.get("time"),
                    "breakout_direction": "long",
                    "state_machine_path": "CLEAN_BREAK -> WAITING_RETEST -> RETEST_REJECT -> PREPARE_ENTRY",
                },
            )
        if retested:
            return reaction_v2(
                "waiting_retest",
                "long",
                True,
                last,
                ["Clean break above zone; retest is still waiting for bullish rejection."],
                buffer,
                {"breakout_candle_time": breakout_candle.get("time"), "breakout_direction": "long"},
            )
    return None


def classify_consolidation_reaction_v2(
    zone: dict[str, Any],
    candles: list[dict[str, Any]],
    atr: float,
    config: StrategyConfig,
) -> ReactionResult:
    last = candles[-1]
    low = float(last["low"])
    high = float(last["high"])
    close = float(last["close"])
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    midpoint = (zone_low + zone_high) / 2
    buffer = atr * config.breakout_buffer_atr_multiplier
    body = candle_body(last)
    breakout_body = body >= atr * config.zone_reaction_v2_consolidation_breakout_body_atr
    fakeout_limit = atr * config.zone_reaction_v2_fakeout_max_atr
    touched = high >= zone_low and low <= zone_high

    upper_fakeout = max(high - zone_high, 0.0)
    lower_fakeout = max(zone_low - low, 0.0)
    if upper_fakeout > 0 and upper_fakeout <= fakeout_limit and close <= zone_high:
        return reaction_v2(
            "fakeout",
            "short",
            True,
            last,
            ["Fakeout above consolidation high and close back inside."],
            buffer,
            {"fakeout_distance_atr": round(upper_fakeout / max(atr, 0.00001), 4)},
        )
    if lower_fakeout > 0 and lower_fakeout <= fakeout_limit and close >= zone_low:
        return reaction_v2(
            "fakeout",
            "long",
            True,
            last,
            ["Fakeout below consolidation low and close back inside."],
            buffer,
            {"fakeout_distance_atr": round(lower_fakeout / max(atr, 0.00001), 4)},
        )
    if close > zone_high + buffer and breakout_body:
        return reaction_v2("clean_breakout", "long", touched, last, ["Clean breakout above consolidation."], buffer)
    if close < zone_low - buffer and breakout_body:
        return reaction_v2("clean_breakout", "short", touched, last, ["Clean breakout below consolidation."], buffer)
    if touched and close > midpoint and body >= average_body(candles, config.zone_reaction_v2_reject_avg_body_period):
        return reaction_v2("reject", "short", True, last, ["Bearish range-bound reaction near consolidation high."], buffer)
    if touched and close <= midpoint and body >= average_body(candles, config.zone_reaction_v2_reject_avg_body_period):
        return reaction_v2("reject", "long", True, last, ["Bullish range-bound reaction near consolidation low."], buffer)
    slow = slow_reaction_direction(zone, candles, atr, config)
    if slow:
        return reaction_v2("slow_reaction", slow, True, last, ["Slow reaction inside consolidation; waiting for BOS/CHOCH."], buffer)
    if touched:
        return reaction_v2("waiting_bos", "short" if close > midpoint else "long", True, last, ["Inside consolidation; waiting for trigger."], buffer)
    return reaction_v2("far", None, False, last, [], buffer)


def reaction(
    state: str,
    direction: str | None,
    touched: bool,
    candle: dict[str, Any],
    reason: list[str],
    buffer: float,
) -> ReactionResult:
    return ReactionResult(
        state=state,
        direction=direction,
        touched=touched,
        candle_time=str(candle.get("time")),
        reason=reason,
        metadata={"reaction_candle_time": candle.get("time"), "breakout_buffer": round(buffer, 5)},
    )


def reaction_v2(
    state: str,
    direction: str | None,
    touched: bool,
    candle: dict[str, Any],
    reason: list[str],
    buffer: float,
    metadata: dict[str, Any] | None = None,
) -> ReactionResult:
    base = {
        "reaction_candle_time": candle.get("time"),
        "breakout_buffer": round(buffer, 5),
        "reaction_v2": state,
        "reaction_open": candle.get("open"),
        "reaction_high": candle.get("high"),
        "reaction_low": candle.get("low"),
        "reaction_close": candle.get("close"),
        "reaction_body": round(candle_body(candle), 5) if candle else 0.0,
    }
    if metadata:
        base.update(metadata)
    return ReactionResult(state=state, direction=direction, touched=touched, candle_time=str(candle.get("time")), reason=reason, metadata=base)


def candle_body(candle: dict[str, Any]) -> float:
    return abs(float(candle.get("close", 0.0)) - float(candle.get("open", 0.0)))


def average_body(candles: list[dict[str, Any]], period: int) -> float:
    window = candles[-max(period, 1) :]
    bodies = [candle_body(candle) for candle in window]
    return sum(bodies) / len(bodies) if bodies else 0.0


def slow_reaction_direction(zone: dict[str, Any], candles: list[dict[str, Any]], atr: float, config: StrategyConfig) -> str | None:
    if len(candles) < config.zone_reaction_v2_slow_min_bars:
        return None
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    window = candles[-config.zone_reaction_v2_slow_max_bars :]
    inside_or_touching = [
        candle for candle in window if float(candle["high"]) >= zone_low and float(candle["low"]) <= zone_high
    ]
    if len(inside_or_touching) < config.zone_reaction_v2_slow_min_bars:
        return None
    avg_body = average_body(inside_or_touching, len(inside_or_touching))
    if avg_body > atr * config.zone_reaction_v2_slow_body_max_ratio:
        return None
    expected = expected_trade_direction(zone)
    if expected in {"long", "short"}:
        return expected
    last_close = float(candles[-1]["close"])
    return "short" if last_close > zone_mid(zone) else "long"


def compute_zone_reaction_v2_levels(
    zone: dict[str, Any],
    direction: str,
    reaction: ReactionResult,
    last_close: float,
    atr: float,
    config: StrategyConfig,
) -> tuple[float | None, float | None, list[float], float | None]:
    metadata = reaction.metadata
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    reaction_low = float(metadata.get("reaction_low", zone_low))
    reaction_high = float(metadata.get("reaction_high", zone_high))
    # Stops use the reaction wick plus a small ATR buffer, then clamp to a
    # realistic min/max distance so tiny noisy SLs and huge invalid setups are blocked.
    buffer = max(atr * config.zone_reaction_v2_stop_buffer_atr, 0.01)
    min_stop_distance = max(config.zone_reaction_v2_min_stop_price, atr * config.zone_reaction_v2_min_stop_atr)
    target_rr = config.zone_reaction_v2_rr_minimum
    entry = round(last_close, 5)
    if direction == "long":
        natural_stop = reaction_low - buffer if reaction.state == "retest_reject" else min(zone_low, reaction_low) - buffer
        stop = round(min(natural_stop, entry - min_stop_distance), 5)
        risk = entry - stop
        if risk <= 0:
            return entry, stop, [], None
        take_profit = [round(entry + risk * target_rr, 5)]
    else:
        natural_stop = reaction_high + buffer if reaction.state == "retest_reject" else max(zone_high, reaction_high) + buffer
        stop = round(max(natural_stop, entry + min_stop_distance), 5)
        risk = stop - entry
        if risk <= 0:
            return entry, stop, [], None
        take_profit = [round(entry - risk * target_rr, 5)]
    return entry, stop, take_profit, round(target_rr, 4)


def zone_confluence_metadata(zone: dict[str, Any], zones: list[dict[str, Any]], atr: float, bonus: float = 0.0) -> dict[str, Any]:
    zone_id = str(zone.get("id"))
    zone_type = str(zone.get("type"))
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    tolerance = max(atr * 0.25, 0.01)
    types = {zone_type}
    ids: list[str] = []
    for other in zones:
        other_id = str(other.get("id"))
        other_type = str(other.get("type"))
        if other_id == zone_id or other_type == "order_block":
            continue
        if other_type not in PLAYBOOK_ZONE_TYPES["zone_reaction_v2"]:
            continue
        other_low = float(other["price_low"])
        other_high = float(other["price_high"])
        overlaps = other_high >= zone_low - tolerance and other_low <= zone_high + tolerance
        if not overlaps:
            continue
        types.add(other_type)
        ids.append(other_id)
    count = len(types)
    return {
        "confluence_count": count,
        "confluence_types": sorted(types),
        "confluence_zone_ids": ids,
        "confluence_score_bonus": bonus if count > 1 else 0.0,
    }


def score_zone_reaction_v2(
    zone: dict[str, Any],
    reaction: ReactionResult,
    direction: str,
    bias: str,
    regime: str,
    overlays: set[str],
    rr: float | None,
    has_trigger: bool,
    status: str,
    confluence: dict[str, Any],
    config: StrategyConfig,
) -> float:
    score = float(zone.get("weight") or 0.0) * 0.24
    score += {
        "fakeout": 0.32,
        "reject": 0.26,
        "slow_reaction": 0.12,
        "waiting_bos": 0.08,
        "clean_breakout": 0.10,
        "waiting_retest": 0.10,
    }.get(reaction.state, 0.0)
    if direction == bias_to_direction(bias):
        score += 0.18
    elif bias == "neutral" and regime == "ranging":
        score += 0.10
    if regime == "ranging" and str(zone.get("type")) == "consolidation":
        score += 0.08
    if "expansion" in overlays and reaction.state == "clean_breakout":
        score += 0.08
    if "contraction" in overlays and reaction.state in {"slow_reaction", "waiting_bos"}:
        score += 0.04
    if has_trigger:
        score += 0.10
    if rr is not None:
        score += min(rr / 8, 0.10)
    if int(confluence.get("confluence_count") or 1) > 1:
        score += config.zone_reaction_v2_confluence_score_bonus
    if status == "blocked":
        score *= 0.5
    return round(min(score, 1.0), 4)


def trigger_points_for_direction(
    points: list[dict[str, Any]],
    direction: str,
    as_of: str,
    not_before: str | None = None,
) -> list[str]:
    wanted = BULLISH_PA if direction == "long" else BEARISH_PA
    wanted_break_direction = "up" if direction == "long" else "down"
    result: list[str] = []
    for point in reversed(points[-40:]):
        point_time = str(point.get("time"))
        if point_time > as_of:
            continue
        if not_before is not None and point_time < not_before:
            continue
        point_type = str(point.get("type"))
        metadata = point.get("metadata") if isinstance(point.get("metadata"), dict) else {}
        if point_type in wanted:
            result.append(str(point.get("id")))
        elif point_type in (BULLISH_BREAKS if direction == "long" else BEARISH_BREAKS) and metadata.get("direction") == wanted_break_direction:
            result.append(str(point.get("id")))
        if len(result) >= 3:
            break
    return list(reversed(result))


def trigger_types_for_ids(points: list[dict[str, Any]], trigger_ids: list[str]) -> list[str]:
    point_by_id = {str(point.get("id")): str(point.get("type")) for point in points}
    return [point_by_id[point_id] for point_id in trigger_ids if point_id in point_by_id]


def zone_touch_count(zone: dict[str, Any]) -> int | None:
    metadata = zone.get("metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("touch_count_total", metadata.get("touch_count"))
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def status_rank(status: str) -> int:
    return {"eligible": 4, "waiting_confirmation": 3, "watching": 2, "blocked": 1, "expired": 0}.get(status, 0)


def expected_trade_direction(zone: dict[str, Any]) -> str:
    zone_type = str(zone.get("type"))
    direction = str(zone.get("direction"))
    if direction == "bullish" or zone_type == "support":
        return "long"
    if direction == "bearish" or zone_type == "resistance":
        return "short"
    return "neutral"


def bias_to_direction(bias: str) -> str:
    if bias == "bullish":
        return "long"
    if bias == "bearish":
        return "short"
    return "neutral"


def secondary_allows_direction(value: Any, direction: str) -> bool:
    if value is None:
        return False
    text = str(value).lower()
    return (direction == "long" and "bull" in text) or (direction == "short" and "bear" in text)


def parse_overlays(regime: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    secondary = regime.get("secondary_value")
    if isinstance(secondary, str):
        values.update(part.strip() for part in secondary.split(",") if part.strip())
    metadata = regime.get("metadata")
    if isinstance(metadata, dict):
        overlays = metadata.get("overlays")
        if isinstance(overlays, list):
            values.update(str(item) for item in overlays)
    return values


def zone_mid(zone: dict[str, Any]) -> float:
    return (float(zone["price_low"]) + float(zone["price_high"])) / 2


def zone_width_atr_ratio(zone: dict[str, Any], atr: float) -> float:
    return (float(zone["price_high"]) - float(zone["price_low"])) / max(atr, 0.00001)


def chart_candles_to_slices(candles: list[dict[str, Any]]) -> list[CandleSlice]:
    return [
        CandleSlice(
            open_time=str(candle["time"]),
            open=float(candle["open"]),
            high=float(candle["high"]),
            low=float(candle["low"]),
            close=float(candle["close"]),
        )
        for candle in candles
    ]


def latest_range(candles: list[dict[str, Any]]) -> float | None:
    if not candles:
        return None
    candle = candles[-1]
    return float(candle["high"]) - float(candle["low"])
