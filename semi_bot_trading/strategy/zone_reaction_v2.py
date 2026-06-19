from __future__ import annotations

from typing import Any

from ..config import StrategyConfig
from .helpers import (
    _is_pinbar_reject,
    average_body,
    bias_to_direction,
    candle_body,
    candle_touches_zone,
    close_inside_zone,
    expected_trade_direction,
    first_text,
    fvg_fill_ratio,
    inside_zone_close_position,
    internal_reject_window_metadata,
    reaction,
    reaction_v2,
    sr_penetration_atr,
    trigger_points_for_direction,
    trigger_types_for_ids,
    unique_ids,
    zone_has_explicit_trade_mode,
    zone_is_human_thesis,
    zone_mid,
    zone_touch_count,
    zone_trade_modes,
    zone_width_atr_ratio,
)
from .zone_reaction_levels import compute_zone_reaction_v2_levels
from .types import PLAYBOOK_ZONE_TYPES, ReactionResult, SetupCandidate


# ---------------------------------------------------------------------------
# Classification: how does price behave at this zone?
# ---------------------------------------------------------------------------

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
        if (
            config.zone_reaction_v2_reject_pinbar_enabled
            and low <= zone_high
            and close > zone_high
            and _is_pinbar_reject(
                last, "long",
                config.zone_reaction_v2_reject_pinbar_wick_body_ratio,
                config.zone_reaction_v2_reject_pinbar_min_wick_ratio,
                avg_body=avg_body,
                body_min_ratio=config.zone_reaction_v2_reject_body_min_ratio,
            )
        ):
            return reaction_v2("reject", "long", True, last, ["Bullish pinbar rejection at zone."], buffer)
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
        if (
            config.zone_reaction_v2_reject_pinbar_enabled
            and high >= zone_low
            and close < zone_low
            and _is_pinbar_reject(
                last, "short",
                config.zone_reaction_v2_reject_pinbar_wick_body_ratio,
                config.zone_reaction_v2_reject_pinbar_min_wick_ratio,
                avg_body=avg_body,
                body_min_ratio=config.zone_reaction_v2_reject_body_min_ratio,
            )
        ):
            return reaction_v2("reject", "short", True, last, ["Bearish pinbar rejection at zone."], buffer)
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

    internal_window_metadata = internal_reject_window_metadata(candles, config)
    slow = slow_reaction_direction(zone, candles, atr, config)
    if slow:
        return reaction_v2(
            "slow_reaction",
            slow,
            True,
            last,
            ["Slow reaction inside zone; waiting for BOS/CHOCH."],
            buffer,
            internal_window_metadata,
        )
    if touched:
        return reaction_v2(
            "waiting_bos",
            expected,
            True,
            last,
            ["Touched zone; waiting for stronger M15 reaction."],
            buffer,
            internal_window_metadata,
        )
    # Surface zones the price is closing in on so the UI state machine can show
    # an APPROACHING step before the first touch. Distance is measured from the
    # candle close to the nearest zone edge.
    distance = zone_low - close if close < zone_low else close - zone_high if close > zone_high else 0.0
    approach_limit = atr * config.approach_atr_multiplier
    if 0.0 < distance <= approach_limit:
        return reaction_v2(
            "approaching",
            expected,
            False,
            last,
            [f"Price within {config.approach_atr_multiplier:.2f} ATR of zone; watching for touch."],
            buffer,
            {"approach_distance_atr": round(distance / max(atr, 0.00001), 4)},
        )
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
    lookback = candles[-(config.zone_reaction_v2_retest_max_bars + 1):-1]
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


def slow_reaction_direction(
    zone: dict[str, Any],
    candles: list[dict[str, Any]],
    atr: float,
    config: StrategyConfig,
) -> str | None:
    if len(candles) < config.zone_reaction_v2_slow_min_bars:
        return None
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    window = candles[-config.zone_reaction_v2_slow_max_bars:]
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


def promote_internal_reject_if_confirmed(
    zone: dict[str, Any],
    base_reaction: ReactionResult,
    atr: float,
    config: StrategyConfig,
    has_structure_trigger: bool,
    has_price_action_trigger: bool,
    has_current_trigger: bool,
) -> ReactionResult:
    if base_reaction.state in {"reject", "fakeout", "retest_reject", "clean_breakout", "far", "invalid"}:
        return base_reaction
    if not config.zone_reaction_v2_internal_reject_enabled or not base_reaction.touched:
        return base_reaction
    if not has_current_trigger:
        return base_reaction

    direction = base_reaction.direction
    if direction not in {"long", "short"}:
        return base_reaction
    zone_type = str(zone.get("type"))
    if zone_type not in {"support", "resistance", "fvg"}:
        return base_reaction

    # SR zones need the stricter structure confirmation: PA alone inside a
    # support/resistance band backtests as knife-catching (-5.5R support longs),
    # while FVG fills reverse fine on PA alone (+7R FVG longs).
    requires_structure = (
        config.zone_reaction_v2_internal_reject_sr_requires_structure
        if zone_type in {"support", "resistance"}
        else config.zone_reaction_v2_internal_reject_requires_structure
    )
    if requires_structure and not has_structure_trigger:
        return base_reaction
    if config.zone_reaction_v2_internal_reject_requires_price_action and not has_price_action_trigger:
        return base_reaction

    candle = {
        "time": base_reaction.metadata.get("reaction_candle_time"),
        "open": base_reaction.metadata.get("reaction_open"),
        "high": base_reaction.metadata.get("reaction_high"),
        "low": base_reaction.metadata.get("reaction_low"),
        "close": base_reaction.metadata.get("reaction_close"),
    }
    if not close_inside_zone(candle, zone):
        return base_reaction

    metadata: dict[str, Any] = {
        "inside_zone_close_position": round(inside_zone_close_position(candle, zone), 4),
        "zone_width_atr": round(zone_width_atr_ratio(zone, atr), 4),
    }
    if zone_type == "fvg":
        fill_ratio = fvg_fill_ratio(zone, candle)
        metadata["fill_ratio"] = round(fill_ratio, 4)
        if fill_ratio < config.zone_reaction_v2_internal_reject_min_fvg_fill_ratio:
            return base_reaction
        depth_label = "deep " if fill_ratio >= config.zone_reaction_v2_internal_reject_deep_fvg_fill_ratio else ""
        side = "bullish FVG" if direction == "long" else "bearish FVG"
        reason = [f"Internal reject inside {side} after {depth_label}{fill_ratio:.0%} fill."]
    else:
        penetration = sr_penetration_atr(zone, candle, direction, atr)
        metadata["sr_penetration_atr"] = round(penetration, 4)
        if penetration < config.zone_reaction_v2_internal_reject_min_sr_penetration_atr:
            return base_reaction
        side = "support" if direction == "long" else "resistance"
        reason = [f"Internal reject inside {side} after {penetration:.2f} ATR penetration."]

    metadata["internal_reject_reason"] = reason[0]
    return reaction_v2(
        "internal_reject",
        direction,
        True,
        candle,
        [
            *reason,
            "M15 BOS/CHOCH and price action confirmed inside zone.",
        ],
        float(base_reaction.metadata.get("breakout_buffer", 0.0)),
        {
            **base_reaction.metadata,
            **metadata,
            # The reaction_v2 helper stamps "reaction_v2" into metadata, so the
            # inherited base value must be overwritten or trades get mislabeled
            # with the pre-promotion state (e.g. slow_reaction).
            "reaction_v2": "internal_reject",
            "previous_reaction_v2": base_reaction.state,
        },
    )


# ---------------------------------------------------------------------------
# Evaluation: given a classified reaction, should we trade?
# ---------------------------------------------------------------------------

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
    macro_trend: str = "unknown",
    stop_fallback_atr: float | None = None,
) -> list[SetupCandidate]:
    if not config.zone_reaction_v2_enabled:
        return []
    if str(zone.get("type")) not in PLAYBOOK_ZONE_TYPES["zone_reaction_v2"]:
        return []

    direction = reaction.direction
    if direction not in {"long", "short"}:
        return []

    # trade_modes governs which reaction families a zone may trade. Human-created
    # or human-adjusted zones bypass context gates for the allowed family: the
    # thesis is explicit even when the UI uses the zone-type default trade modes.
    required_mode = "internal_reject" if reaction.state == "internal_reject" else "reject"
    if required_mode not in zone_trade_modes(zone):
        return []
    context_bypass = zone_has_explicit_trade_mode(zone, required_mode) or zone_is_human_thesis(zone)

    trigger_ids = trigger_points_for_direction(structure_points, direction, as_of, not_before=reaction.candle_time)
    structure_trigger_ids = trigger_points_for_direction(
        structure_points, direction, as_of, not_before=reaction.candle_time, trigger_kind="structure",
    )
    price_action_trigger_ids = trigger_points_for_direction(
        structure_points, direction, as_of, not_before=reaction.candle_time, trigger_kind="price_action",
    )
    trigger_types = trigger_types_for_ids(structure_points, trigger_ids)
    structure_trigger_types = trigger_types_for_ids(structure_points, structure_trigger_ids)
    price_action_trigger_types = trigger_types_for_ids(structure_points, price_action_trigger_ids)

    # Internal reject reads a short reaction window inside wide zones. A BOS/CHOCH
    # and PA often do not print on the exact same M15 candle, but at least one of
    # them must be current so stale signals cannot promote every later candle.
    internal_window_start = str(reaction.metadata.get("internal_reject_trigger_window_start") or reaction.candle_time)
    recent_structure_trigger_ids = trigger_points_for_direction(
        structure_points, direction, as_of, not_before=internal_window_start, trigger_kind="structure",
    )
    recent_price_action_trigger_ids = trigger_points_for_direction(
        structure_points, direction, as_of, not_before=internal_window_start, trigger_kind="price_action",
    )
    current_has_internal_trigger = bool(structure_trigger_ids or price_action_trigger_ids)
    reaction = promote_internal_reject_if_confirmed(
        zone,
        reaction,
        atr,
        config,
        has_structure_trigger=bool(recent_structure_trigger_ids),
        has_price_action_trigger=bool(recent_price_action_trigger_ids),
        has_current_trigger=current_has_internal_trigger,
    )
    if reaction.state == "internal_reject":
        trigger_ids = unique_ids([*recent_structure_trigger_ids, *recent_price_action_trigger_ids])
        structure_trigger_ids = recent_structure_trigger_ids
        price_action_trigger_ids = recent_price_action_trigger_ids
        trigger_types = trigger_types_for_ids(structure_points, trigger_ids)
        structure_trigger_types = trigger_types_for_ids(structure_points, structure_trigger_ids)
        price_action_trigger_types = trigger_types_for_ids(structure_points, price_action_trigger_ids)
    confluence = zone_confluence_metadata(zone, zones, atr, config.zone_reaction_v2_confluence_score_bonus)
    status, blocked, reasons = zone_reaction_v2_status(
        direction,
        reaction,
        bool(trigger_ids),
        bias,
        secondary_bias,
        regime,
        config,
        has_structure_trigger=bool(structure_trigger_ids),
        has_price_action_trigger=bool(price_action_trigger_ids),
        macro_trend=macro_trend,
        context_bypass=context_bypass,
        zone_type=str(zone.get("type", "")),
    )
    level_metadata: dict[str, Any] = {}
    entry, stop, take_profit, rr = compute_zone_reaction_v2_levels(
        zone,
        direction,
        reaction,
        last_close,
        atr,
        config,
        stop_fallback_atr=stop_fallback_atr,
        level_metadata=level_metadata,
    )
    stop_distance = abs(entry - stop) if entry is not None and stop is not None else None
    if reaction.state != "approaching":
        # Approaching zones stay "watching": entry/stop are placeholders until the
        # first touch, so RR/stop-distance/blocked checks would only add noise.
        if rr is None or rr < config.zone_reaction_v2_rr_minimum:
            blocked.append(f"RR {rr or 0:.2f} is below Zone Reaction V2 minimum {config.zone_reaction_v2_rr_minimum:.2f}.")
            status = "blocked"
        if (
            stop_distance is not None
            and config.zone_reaction_v2_max_stop_distance > 0
            and stop_distance > config.zone_reaction_v2_max_stop_distance
            and level_metadata.get("stop_source") != "atr_fallback"
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
            "macro_trend": macro_trend,
            "context_bypass": context_bypass,
            "trade_modes": zone_trade_modes(zone),
            "overlays": sorted(overlays),
            "trigger_types": trigger_types,
            "structure_trigger_ids": structure_trigger_ids,
            "structure_trigger_types": structure_trigger_types,
            "price_action_trigger_ids": price_action_trigger_ids,
            "price_action_trigger_types": price_action_trigger_types,
            "atr": round(atr, 5),
            "stop_fallback_atr": level_metadata.get("stop_fallback_atr"),
            "stop_fallback_atr_multiplier": level_metadata.get("stop_fallback_atr_multiplier"),
            "stop_distance": round(stop_distance, 5) if stop_distance is not None else None,
            "stop_source": level_metadata.get("stop_source"),
            "reject_stop_mode": config.zone_reaction_v2_reject_stop_mode,
            "reject_wide_stop_fallback": config.zone_reaction_v2_reject_wide_stop_fallback,
            "reaction_v2": reaction.state,
            "state_machine": zone_reaction_v2_state_machine(reaction, status, blocked, bool(trigger_ids)),
            "confluence_count": confluence["confluence_count"],
            "confluence_types": confluence["confluence_types"],
            "confluence_score_bonus": confluence["confluence_score_bonus"],
            **reaction.metadata,
        },
    )
    return [candidate]


# ---------------------------------------------------------------------------
# Status: context gates → watching / waiting / eligible / blocked
# ---------------------------------------------------------------------------

def zone_reaction_v2_status(
    direction: str,
    reaction: ReactionResult,
    has_trigger: bool,
    bias: str,
    secondary_bias: Any,
    regime: str,
    config: StrategyConfig,
    has_structure_trigger: bool = False,
    has_price_action_trigger: bool = False,
    macro_trend: str = "unknown",
    context_bypass: bool = False,
    zone_type: str = "",
) -> tuple[str, list[str], list[str]]:
    blocked: list[str] = []
    reasons = ["Zone Reaction V2 single-zone reaction setup.", f"Reaction V2: {reaction.state}."]
    if context_bypass:
        # Human explicitly opted this zone into the reaction family, so every
        # context gate (bias/regime/news/macro) is bypassed: the human thesis
        # outranks bot context. Signal-quality conditions still apply.
        reasons.append("Human zone/trade mode bypasses all context gates including macro trend.")
    if not context_bypass and config.zone_reaction_v2_block_news_or_risk_off and regime in {"news", "risk_off"}:
        blocked.append(f"Regime {regime} blocks Zone Reaction V2.")

    # Macro trend gate: counter-macro trades had a clear negative edge in backtest
    # (resistance shorts during the 2023-2026 gold uptrend). "flat"/"unknown"
    # macro allows both directions so the gate degrades gracefully without history.
    # FVG zones have a separate gate controlled by fvg_macro_gate_enabled in config.
    is_fvg = zone_type == "fvg"
    active_macro_gate = (
        config.zone_reaction_v2_macro_gate_enabled
        if not is_fvg
        else config.zone_reaction_v2_fvg_macro_gate_enabled
    )
    if not context_bypass and active_macro_gate:
        if macro_trend == "up" and direction == "short":
            blocked.append("Macro trend up blocks Zone Reaction V2 short.")
        elif macro_trend == "down" and direction == "long":
            blocked.append("Macro trend down blocks Zone Reaction V2 long.")
        else:
            reasons.append(f"Macro trend {macro_trend} allows {direction}.")
    elif not active_macro_gate:
        gate_scope = "FVG" if is_fvg else "all zones"
        reasons.append(f"Macro trend gate disabled for {gate_scope} (macro={macro_trend}, direction={direction}).")

    # TEMP RESEARCH OVERRIDE:
    # The normal context gate requires bias-aligned trades and only allows
    # two-sided neutral trades when `regime == "ranging"`. That means
    # `neutral + trending` blocks both long and short setups. It is disabled
    # temporarily so backtests can measure raw zone reaction quality.
    #
    # To restore the production gate, uncomment this block:
    #
    # expected = bias_to_direction(bias)
    # if direction != expected:
    #     if bias == "neutral":
    #         if not (config.zone_reaction_v2_allow_neutral_range_trade and regime == "ranging"):
    #             blocked.append("Neutral bias only allows Zone Reaction V2 range trade in ranging regime.")
    #         else:
    #             reasons.append("Neutral+ranging allows two-sided zone reaction.")
    #     elif secondary_allows_direction(secondary_bias, direction):
    #         reasons.append("Countertrend allowed by human secondary bias.")
    #     else:
    #         blocked.append("Zone Reaction V2 requires direction aligned with bias.")
    reasons.append("Bias/regime direction gate temporarily disabled for reaction research.")

    if reaction.state == "approaching":
        reasons.append("Price approaching zone; no touch yet.")
        return "watching", blocked, reasons

    if reaction.state == "fakeout" and config.zone_reaction_v2_require_trigger_for_fakeout and not has_trigger:
        reasons.append("Fakeout requires M15 trigger; waiting for confirmation.")
        status = "waiting_confirmation"
    elif (
        reaction.state == "fakeout"
        and float(reaction.metadata.get("fakeout_reaction_depth_atr", 0.0)) > config.zone_reaction_v2_fakeout_max_reaction_depth_atr
    ):
        reasons.append("Fakeout wick is too deep; waiting for follow-through confirmation.")
        status = "waiting_confirmation"
    elif reaction.state == "internal_reject" and reaction.state not in set(config.zone_reaction_v2_allowed_reactions):
        reasons.append("Internal reject is disabled for Zone Reaction V2; keeping it for debug only.")
        status = "waiting_confirmation"
    elif reaction.state == "internal_reject" and config.zone_reaction_v2_internal_reject_requires_structure and not has_structure_trigger:
        reasons.append("Internal reject requires M15 BOS/CHOCH; waiting for structure confirmation.")
        status = "waiting_confirmation"
    elif reaction.state == "internal_reject" and config.zone_reaction_v2_internal_reject_requires_price_action and not has_price_action_trigger:
        reasons.append("Internal reject requires M15 price action; waiting for PA confirmation.")
        status = "waiting_confirmation"
    elif reaction.state not in set(config.zone_reaction_v2_allowed_reactions):
        # We still surface disabled states in UI/backtest metadata so humans can
        # debug the state machine, but only configured reactions may become trades.
        reasons.append(f"Reaction {reaction.state} is disabled for Zone Reaction V2; keeping it for debug only.")
        status = "waiting_confirmation"
    elif reaction.state in {"reject", "fakeout", "retest_reject", "internal_reject"}:
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


# ---------------------------------------------------------------------------
# State machine (UI visualization)
# ---------------------------------------------------------------------------

def zone_reaction_v2_state_machine(
    reaction: ReactionResult,
    status: str,
    blocked: list[str],
    has_trigger: bool,
) -> list[dict[str, str]]:
    active = reaction.state
    if reaction.state == "approaching":
        active = "APPROACHING"
    elif reaction.state == "retest_reject":
        active = "PREPARE_ENTRY"
    elif reaction.state in {"reject", "fakeout", "internal_reject"} and status == "eligible":
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
        ("APPROACHING", "Approaching zone"),
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
            "status": "active" if key == active else "done" if _step_done(key, active) else "pending",
        }
        for key, label in steps
    ]


def _step_done(key: str, active: str) -> bool:
    order = {
        "IDLE": 0,
        "APPROACHING": 1,
        "ZONE_TOUCHED": 2,
        "REACTING_IN_ZONE": 3,
        "WAIT_FOR_BOS": 4,
        "WAITING_RETEST": 4,
        "BIAS_WARNING": 5,
        "PREPARE_ENTRY": 6,
    }
    return order.get(key, 99) < order.get(active, 99)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

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
        "internal_reject": 0.28,
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


# ---------------------------------------------------------------------------
# Confluence
# ---------------------------------------------------------------------------

def zone_confluence_metadata(
    zone: dict[str, Any],
    zones: list[dict[str, Any]],
    atr: float,
    bonus: float = 0.0,
) -> dict[str, Any]:
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


# ---------------------------------------------------------------------------
# Public alias: step_done kept for any external callers
# ---------------------------------------------------------------------------

step_done = _step_done
