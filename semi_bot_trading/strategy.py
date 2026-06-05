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
    "trend_pullback": {"support", "resistance", "order_block", "fvg"},
    "ob_mitigation_continuation": {"order_block"},
    "fvg_fill_go": {"fvg"},
    "breakout_retest": {"consolidation"},
    "momentum_expansion_continuation": {"support", "resistance", "order_block", "fvg"},
    "range_boundary_reversal": {"support", "resistance", "consolidation"},
    "liquidity_sweep_reversal": {"support", "resistance", "liquidity_pool"},
    "failed_breakout_trap": {"consolidation"},
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
        if zone.get("status") == "active" and (allowed_zone_types is None or str(zone.get("type")) in allowed_zone_types)
    ]

    for zone in active_zones:
        reaction = classify_zone_reaction(zone, candles, atr, config)
        if reaction.state == "far":
            continue
        candidates.extend(
            evaluate_zone_playbooks(
                symbol,
                zone,
                reaction,
                last_close,
                atr,
                bias_value,
                secondary_bias,
                regime_value,
                overlays,
                recent_points,
                config,
                as_of=str(last_candle["time"]),
                allowed_playbooks=allowed_playbooks,
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


def evaluate_zone_playbooks(
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
    config: StrategyConfig,
    as_of: str,
    allowed_playbooks: set[str] | None = None,
) -> list[SetupCandidate]:
    zone_type = str(zone.get("type"))
    zone_direction = expected_trade_direction(zone)
    trigger_ids = trigger_points_for_direction(structure_points, zone_direction, as_of, not_before=reaction.candle_time)
    trigger_types = trigger_types_for_ids(structure_points, trigger_ids)
    has_displacement = has_directional_displacement(structure_points, zone_direction, as_of)
    candidates: list[SetupCandidate] = []

    if zone_direction in {"long", "short"}:
        if playbook_allowed("trend_pullback", allowed_playbooks):
            candidates.append(
                make_directional_candidate(
                    "trend_pullback",
                    symbol,
                    zone,
                    zone_direction,
                    reaction,
                    last_close,
                    atr,
                    bias,
                    secondary_bias,
                    regime,
                    overlays,
                    trigger_ids,
                    trigger_types,
                    config,
                    as_of,
                    required_regime="trending",
                    allowed_zone_types={"support", "resistance", "order_block", "fvg"},
                    base_reason="Pullback into a bias-aligned zone.",
                )
            )
    if zone_direction in {"long", "short"}:
        if zone_type == "order_block" and playbook_allowed("ob_mitigation_continuation", allowed_playbooks):
            candidates.append(
                make_directional_candidate(
                    "ob_mitigation_continuation",
                    symbol,
                    zone,
                    zone_direction,
                    reaction,
                    last_close,
                    atr,
                    bias,
                    secondary_bias,
                    regime,
                    overlays,
                    trigger_ids,
                    trigger_types,
                    config,
                    as_of,
                    required_regime=None,
                    allowed_zone_types={"order_block"},
                    base_reason="Order block mitigation with M15 reaction.",
                )
            )
        if zone_type == "fvg" and playbook_allowed("fvg_fill_go", allowed_playbooks):
            candidates.append(
                make_directional_candidate(
                    "fvg_fill_go",
                    symbol,
                    zone,
                    zone_direction,
                    reaction,
                    last_close,
                    atr,
                    bias,
                    secondary_bias,
                    regime,
                    overlays,
                    trigger_ids,
                    trigger_types,
                    config,
                    as_of,
                    required_regime=None,
                    allowed_zone_types={"fvg"},
                    base_reason="FVG fill is reacting in the expected direction.",
                )
            )
        if (
            "expansion" in overlays
            and zone_type in {"order_block", "fvg", "support", "resistance"}
            and playbook_allowed("momentum_expansion_continuation", allowed_playbooks)
        ):
            candidates.append(
                make_directional_candidate(
                    "momentum_expansion_continuation",
                    symbol,
                    zone,
                    zone_direction,
                    reaction,
                    last_close,
                    atr,
                    bias,
                    secondary_bias,
                    regime,
                    overlays,
                    trigger_ids,
                    trigger_types,
                    config,
                    as_of,
                    required_regime=None,
                    allowed_zone_types={"support", "resistance", "order_block", "fvg"},
                    base_reason="Expansion regime can continue after a shallow M15 reaction.",
                    require_displacement=True,
                    has_displacement=has_displacement,
                )
            )

    if zone_type == "consolidation" and (
        playbook_allowed("breakout_retest", allowed_playbooks)
        or playbook_allowed("range_boundary_reversal", allowed_playbooks)
        or playbook_allowed("failed_breakout_trap", allowed_playbooks)
    ):
        candidates.extend(
            evaluate_consolidation_playbooks(
                symbol,
                zone,
                reaction,
                last_close,
                atr,
                bias,
                secondary_bias,
                regime,
                overlays,
                structure_points,
                config,
                as_of,
            )
        )
    if zone_type == "liquidity_pool" and playbook_allowed("liquidity_sweep_reversal", allowed_playbooks):
        liquidity_direction = directional_reaction(reaction) or ("short" if last_close > zone_mid(zone) else "long")
        liquidity_trigger_ids = trigger_points_for_direction(structure_points, liquidity_direction, as_of, not_before=reaction.candle_time)
        candidates.append(
            make_directional_candidate(
                "liquidity_sweep_reversal",
                symbol,
                zone,
                liquidity_direction,
                reaction,
                last_close,
                atr,
                bias,
                secondary_bias,
                regime,
                overlays,
                liquidity_trigger_ids,
                trigger_types_for_ids(structure_points, liquidity_trigger_ids),
                config,
                as_of,
                required_regime=None,
                allowed_zone_types={"liquidity_pool"},
                base_reason="Liquidity area has a reclaim/rejection candidate.",
                allow_countertrend_with_secondary=True,
            )
        )
    return [candidate for candidate in candidates if candidate is not None]


def playbook_allowed(playbook: str, allowed_playbooks: set[str] | None) -> bool:
    return allowed_playbooks is None or playbook in allowed_playbooks


def allowed_zone_types_for_playbooks(allowed_playbooks: set[str] | None) -> set[str] | None:
    if allowed_playbooks is None:
        return None
    zone_types: set[str] = set()
    for playbook in allowed_playbooks:
        zone_types.update(PLAYBOOK_ZONE_TYPES.get(playbook, set()))
    return zone_types


def make_directional_candidate(
    playbook: str,
    symbol: str,
    zone: dict[str, Any],
    direction: str,
    reaction: ReactionResult,
    last_close: float,
    atr: float,
    bias: str,
    secondary_bias: Any,
    regime: str,
    overlays: set[str],
    trigger_ids: list[str],
    trigger_types: list[str],
    config: StrategyConfig,
    as_of: str,
    required_regime: str | None,
    allowed_zone_types: set[str],
    base_reason: str,
    require_displacement: bool = False,
    has_displacement: bool = False,
    allow_countertrend_with_secondary: bool = False,
) -> SetupCandidate | None:
    if zone.get("type") not in allowed_zone_types:
        return None

    reasons = [base_reason, f"Zone reaction: {reaction.state}."]
    blocked: list[str] = []
    if required_regime and regime != required_regime:
        blocked.append(f"Requires {required_regime} regime, current is {regime}.")
    if direction != bias_to_direction(bias):
        if bias == "neutral":
            reasons.append("Neutral bias allows two-sided range/reaction setup.")
        elif secondary_allows_direction(secondary_bias, direction):
            reasons.append("Countertrend allowed by human secondary bias/regime.")
        else:
            blocked.append("Countertrend setup requires human secondary bias.")
    if require_displacement and not has_displacement:
        blocked.append("Requires M15 displacement in setup direction.")
    if playbook == "trend_pullback" and zone.get("type") == "fvg":
        zone_width_atr = zone_width_atr_ratio(zone, atr)
        if zone_width_atr < config.trend_pullback_fvg_min_width_atr:
            blocked.append(
                f"FVG width {zone_width_atr:.2f} ATR is below Trend Pullback minimum "
                f"{config.trend_pullback_fvg_min_width_atr:.2f}."
            )
        if zone_width_atr > config.trend_pullback_fvg_max_width_atr:
            blocked.append(
                f"FVG width {zone_width_atr:.2f} ATR is above Trend Pullback maximum "
                f"{config.trend_pullback_fvg_max_width_atr:.2f}."
            )

    entry, stop, take_profit, rr = compute_trade_levels(zone, direction, last_close, atr)
    if rr is None or rr < config.min_risk_reward:
        blocked.append(f"RR {rr or 0:.2f} is below minimum {config.min_risk_reward:.2f}.")

    has_trigger = bool(trigger_ids)
    if reaction.state == "rejected":
        status = "eligible" if has_trigger and not blocked else "waiting_confirmation"
    elif reaction.state in {"touched", "inside_wait", "retest_waiting"}:
        status = "waiting_confirmation"
    elif reaction.state == "approaching":
        status = "watching"
    elif blocked:
        status = "blocked"
    else:
        status = "blocked"

    if not has_trigger and status == "eligible":
        status = "waiting_confirmation"
    if blocked:
        status = "blocked"

    score = score_candidate(zone, reaction, direction, bias, regime, overlays, rr, has_trigger, status)
    return SetupCandidate(
        symbol=symbol,
        timeframe=config.timeframe,
        playbook=playbook,
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
            "zone_width_atr": round((float(zone["price_high"]) - float(zone["price_low"])) / max(atr, 0.00001), 4),
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
            **reaction.metadata,
        },
    )


def evaluate_consolidation_playbooks(
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
    config: StrategyConfig,
    as_of: str,
) -> list[SetupCandidate]:
    direction = reaction.direction or ("short" if last_close >= zone_mid(zone) else "long")
    trigger_ids = trigger_points_for_direction(structure_points, direction, as_of, not_before=reaction.candle_time)
    trigger_types = trigger_types_for_ids(structure_points, trigger_ids)
    candidates: list[SetupCandidate] = []
    failed_breakout = any("Failed breakout" in item for item in reaction.reason)
    playbooks: list[tuple[str, str, str | None]] = []
    if failed_breakout:
        playbooks.append(("failed_breakout_trap", "Failed breakout back inside consolidation.", None))
    elif reaction.state in {"approaching", "inside_wait", "rejected"}:
        playbooks.append(("range_boundary_reversal", "Range boundary reaction candidate.", "ranging"))
    elif reaction.state == "retest_waiting":
        playbooks.append(("breakout_retest", "Breakout has confirmed; waiting for retest/rejection.", None))

    for playbook, reason, required_regime in playbooks:
        candidates.append(
            make_directional_candidate(
                playbook,
                symbol,
                zone,
                direction,
                reaction,
                last_close,
                atr,
                bias,
                secondary_bias,
                regime,
                overlays,
                trigger_ids,
                trigger_types,
                config,
                as_of,
                required_regime=required_regime,
                allowed_zone_types={"consolidation"},
                base_reason=reason,
                allow_countertrend_with_secondary=True,
            )
        )
    return [candidate for candidate in candidates if candidate is not None]


def classify_zone_reaction(
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
    buffer = atr * config.breakout_buffer_atr_multiplier
    approach_distance = atr * config.approach_atr_multiplier
    midpoint = (zone_low + zone_high) / 2
    touched = high >= zone_low and low <= zone_high
    direction = expected_trade_direction(zone)

    if zone.get("type") == "consolidation":
        return classify_consolidation_reaction(zone, candles, atr, config)

    if direction == "long":
        if close < zone_low - buffer:
            return reaction("breakout_confirmed", direction, touched, last, [f"Closed below bullish zone by {buffer:.2f} buffer."], buffer)
        if touched and close > zone_high:
            return reaction("rejected", direction, True, last, ["Touched bullish zone and closed back above it."], buffer)
        if touched and close >= midpoint:
            return reaction("inside_wait", direction, True, last, ["Closed in upper half of bullish zone; waiting for confirmation."], buffer)
        if touched:
            return reaction("touched", direction, True, last, ["Touched bullish zone."], buffer)
        if abs(close - zone_high) <= approach_distance:
            return reaction("approaching", direction, False, last, ["Price is approaching bullish zone."], buffer)
    elif direction == "short":
        if close > zone_high + buffer:
            return reaction("breakout_confirmed", direction, touched, last, [f"Closed above bearish zone by {buffer:.2f} buffer."], buffer)
        if touched and close < zone_low:
            return reaction("rejected", direction, True, last, ["Touched bearish zone and closed back below it."], buffer)
        if touched and close <= midpoint:
            return reaction("inside_wait", direction, True, last, ["Closed in lower half of bearish zone; waiting for confirmation."], buffer)
        if touched:
            return reaction("touched", direction, True, last, ["Touched bearish zone."], buffer)
        if abs(close - zone_low) <= approach_distance:
            return reaction("approaching", direction, False, last, ["Price is approaching bearish zone."], buffer)
    elif touched:
        return reaction("touched", direction, True, last, ["Touched neutral zone."], buffer)

    return reaction("far", direction, False, last, [], buffer)


def classify_consolidation_reaction(
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
    approach_distance = atr * config.approach_atr_multiplier
    touched = high >= zone_low and low <= zone_high

    if close > zone_high + buffer:
        return reaction("retest_waiting", "long", touched, last, ["Consolidation broke upward; waiting for retest."], buffer)
    if close < zone_low - buffer:
        return reaction("retest_waiting", "short", touched, last, ["Consolidation broke downward; waiting for retest."], buffer)
    if high > zone_high + buffer and close <= zone_high:
        return reaction("rejected", "short", True, last, ["Failed breakout above range; closed back inside."], buffer)
    if low < zone_low - buffer and close >= zone_low:
        return reaction("rejected", "long", True, last, ["Failed breakout below range; closed back inside."], buffer)
    if abs(close - zone_high) <= approach_distance:
        return reaction("approaching", "short", touched, last, ["Price is approaching range high."], buffer)
    if abs(close - zone_low) <= approach_distance:
        return reaction("approaching", "long", touched, last, ["Price is approaching range low."], buffer)
    if touched and close > midpoint:
        return reaction("inside_wait", "short", True, last, ["Inside upper half of range; waiting for boundary reaction."], buffer)
    if touched and close <= midpoint:
        return reaction("inside_wait", "long", True, last, ["Inside lower half of range; waiting for boundary reaction."], buffer)
    return reaction("far", None, False, last, [], buffer)


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


def compute_trade_levels(
    zone: dict[str, Any],
    direction: str,
    last_close: float,
    atr: float,
) -> tuple[float | None, float | None, list[float], float | None]:
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    buffer = max(atr * 0.25, (zone_high - zone_low) * 0.15, 0.01)
    entry = round(last_close, 5)
    if direction == "long":
        stop = round(zone_low - buffer, 5)
        risk = entry - stop
        if risk <= 0:
            return entry, stop, [], None
        take_profit = [round(entry + risk * 2, 5), round(entry + risk * 3, 5)]
    else:
        stop = round(zone_high + buffer, 5)
        risk = stop - entry
        if risk <= 0:
            return entry, stop, [], None
        take_profit = [round(entry - risk * 2, 5), round(entry - risk * 3, 5)]
    return entry, stop, take_profit, round(abs(take_profit[0] - entry) / risk, 4)


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


def has_directional_displacement(points: list[dict[str, Any]], direction: str, as_of: str) -> bool:
    wanted = "displacement_bullish" if direction == "long" else "displacement_bearish"
    return any(point.get("time") <= as_of and point.get("type") == wanted for point in points[-40:])


def score_candidate(
    zone: dict[str, Any],
    reaction: ReactionResult,
    direction: str,
    bias: str,
    regime: str,
    overlays: set[str],
    rr: float | None,
    has_trigger: bool,
    status: str,
) -> float:
    score = float(zone.get("weight") or 0.0) * 0.28
    score += {
        "rejected": 0.25,
        "inside_wait": 0.12,
        "touched": 0.10,
        "approaching": 0.05,
        "breakout_confirmed": 0.08,
        "retest_waiting": 0.14,
    }.get(reaction.state, 0)
    if direction == bias_to_direction(bias):
        score += 0.18
    if regime == "trending":
        score += 0.08
    if "expansion" in overlays:
        score += 0.06
    if has_trigger:
        score += 0.16
    if rr is not None:
        score += min(rr / 5, 0.12)
    if status == "blocked":
        score *= 0.6
    return round(min(score, 1.0), 4)


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


def directional_reaction(reaction: ReactionResult) -> str | None:
    return reaction.direction if reaction.direction in {"long", "short"} else None


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
