from __future__ import annotations

from datetime import timedelta
from typing import Any

from ..config import StrategyConfig
from ..timeframes import timeframe_delta
from .helpers import (
    average_body,
    bias_to_direction,
    candle_body,
    candle_touches_zone,
    close_inside_zone,
    expected_trade_direction,
    first_text,
    zone_fill_ratio,
    inside_zone_close_position,
    internal_reject_window_metadata,
    parse_utc_datetime,
    reaction,
    reaction_v2,
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

    average_period = max(config.zone_reaction_v2_reject_avg_body_period, 1)
    baseline_candles = candles[:-1][-average_period:]
    baseline_ready = len(baseline_candles) == average_period
    avg_body = average_body(baseline_candles, average_period) if baseline_ready else 0.0
    rejection_size = close - low if expected == "long" else high - close
    rejection_ratio = rejection_size / avg_body if avg_body > 0 else 0.0
    recovery_threshold = config.zone_reaction_v2_reject_recovery_min_avg_body_ratio
    recovery_metadata = {
        "reaction_trigger_method": "close_extreme_recovery",
        "reaction_rejection_size": round(rejection_size, 5),
        "reaction_rejection_avg_ratio": round(rejection_ratio, 4),
        "reaction_rejection_min_ratio": recovery_threshold,
        "reaction_avg_body": round(avg_body, 5) if baseline_ready else None,
        "reaction_avg_body_period": average_period,
        "reaction_avg_body_sample_count": len(baseline_candles),
        "reaction_avg_body_ready": baseline_ready,
    }
    strong_recovery = baseline_ready and rejection_ratio >= recovery_threshold
    fakeout_limit = atr * config.zone_reaction_v2_fakeout_max_atr
    buffer = atr * config.breakout_buffer_atr_multiplier

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
        if touched and close > zone_high and strong_recovery:
            return reaction_v2(
                "reject",
                "long",
                True,
                last,
                ["Bullish close-to-low recovery rejected the zone."],
                buffer,
                recovery_metadata,
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
        if touched and close < zone_low and strong_recovery:
            return reaction_v2(
                "reject",
                "short",
                True,
                last,
                ["Bearish high-to-close recovery rejected the zone."],
                buffer,
                recovery_metadata,
            )

    closed_through_zone = (
        expected == "long" and close < zone_low
    ) or (
        expected == "short" and close > zone_high
    )
    if closed_through_zone:
        return reaction_v2(
            "far",
            expected,
            touched,
            last,
            ["Price closed through zone; Zone Reaction V2 stops tracking this reaction."],
            buffer,
            {"zone_closed_through": True},
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
            {**internal_window_metadata, **recovery_metadata},
        )
    if touched:
        return reaction_v2(
            "waiting_bos",
            expected,
            True,
            last,
            ["Touched zone; waiting for stronger M15 reaction."],
            buffer,
            {**internal_window_metadata, **recovery_metadata},
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
    if base_reaction.state in {"reject", "fakeout", "far", "invalid"}:
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

    # Internal reject closes before fully reclaiming the zone. Require configured
    # directional body quality (default 1.5x, same as classic reject) so a tiny
    # pinbar body does not promote merely because a PA marker exists.
    reaction_open = float(base_reaction.metadata.get("reaction_open", 0.0))
    reaction_close = float(base_reaction.metadata.get("reaction_close", 0.0))
    reaction_body_ratio = float(base_reaction.metadata.get("reaction_body_avg_ratio", 0.0))
    body_direction_aligned = (
        direction == "long" and reaction_close > reaction_open
    ) or (
        direction == "short" and reaction_close < reaction_open
    )
    body_metadata = {
        "internal_reject_body_min_ratio": config.zone_reaction_v2_internal_reject_body_min_ratio,
        "internal_reject_body_direction_aligned": body_direction_aligned,
    }
    if not body_direction_aligned:
        return internal_reject_gate_failure(
            base_reaction,
            {**body_metadata, "internal_reject_body_gate_passed": False},
            f"Internal reject {direction.upper()} requires a directional reaction body.",
        )
    if reaction_body_ratio < config.zone_reaction_v2_internal_reject_body_min_ratio:
        return internal_reject_gate_failure(
            base_reaction,
            {**body_metadata, "internal_reject_body_gate_passed": False},
            (
                f"Internal reject body {reaction_body_ratio:.2f}x is below required "
                f"{config.zone_reaction_v2_internal_reject_body_min_ratio:.2f}x."
            ),
        )

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
        **body_metadata,
        "internal_reject_body_gate_passed": True,
        "internal_reject_gate_passed": True,
    }
    # Both zone families now use the same normalized depth threshold. The FVG
    # branch keeps only its lifecycle/deep-fill wording; SR no longer depends on
    # ATR, which previously made the threshold inconsistent across zone widths.
    fill_ratio = zone_fill_ratio(zone, candle)
    metadata["fill_ratio"] = round(fill_ratio, 4)
    if fill_ratio < config.zone_reaction_v2_internal_reject_min_fill_ratio:
        return internal_reject_gate_failure(
            base_reaction,
            metadata,
            (
                f"Internal reject fill {fill_ratio:.0%} is below required "
                f"{config.zone_reaction_v2_internal_reject_min_fill_ratio:.0%}."
            ),
        )
    if zone_type == "fvg":
        depth_label = "deep " if fill_ratio >= config.zone_reaction_v2_internal_reject_deep_fvg_fill_ratio else ""
        side = "bullish FVG" if direction == "long" else "bearish FVG"
        reason = [f"Internal reject inside {side} after {depth_label}{fill_ratio:.0%} fill."]
    else:
        side = "support" if direction == "long" else "resistance"
        reason = [f"Internal reject inside {side} after {fill_ratio:.0%} fill."]

    metadata["internal_reject_reason"] = reason[0]
    confirmation_reason = (
        "M15 BOS/CHOCH and price action confirmed inside zone."
        if requires_structure
        else "M15 price action confirmed inside zone."
    )
    return reaction_v2(
        "internal_reject",
        direction,
        True,
        candle,
        [
            *reason,
            confirmation_reason,
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


def internal_reject_gate_failure(
    base_reaction: ReactionResult,
    metadata: dict[str, Any],
    reason: str,
) -> ReactionResult:
    """Keep the pre-promotion state while exposing why Internal was rejected."""
    return ReactionResult(
        state=base_reaction.state,
        direction=base_reaction.direction,
        touched=base_reaction.touched,
        candle_time=base_reaction.candle_time,
        reason=[*base_reaction.reason, reason],
        metadata={
            **base_reaction.metadata,
            **metadata,
            "internal_reject_gate_passed": False,
        },
    )


# ---------------------------------------------------------------------------
# Evaluation: given a classified reaction, should we trade?
# ---------------------------------------------------------------------------

def directional_h1_touch_metadata(
    *,
    zone: dict[str, Any],
    direction: str,
    context_candles: list[dict[str, Any]],
    as_of: str,
    config: StrategyConfig,
) -> dict[str, Any]:
    lookback = config.zone_reaction_v2_reject_h1_touch_lookback_bars
    signal_open = parse_utc_datetime(as_of)
    evaluated_at = signal_open + timeframe_delta(config.timeframe) if signal_open else None
    eligible: list[dict[str, Any]] = []
    for candle in context_candles:
        candle_open = parse_utc_datetime(candle.get("time"))
        if evaluated_at is None or candle_open is None:
            continue
        if candle_open + timeframe_delta("H1") <= evaluated_at:
            eligible.append(candle)
    recent = eligible[-lookback:]
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    matched: dict[str, Any] | None = None
    for candle in reversed(recent):
        touches = float(candle["high"]) >= zone_low and float(candle["low"]) <= zone_high
        directional = (
            float(candle["close"]) > float(candle["open"])
            if direction == "long"
            else float(candle["close"]) < float(candle["open"])
        )
        if touches and directional:
            matched = candle
            break
    return {
        "h1_directional_touch_required": config.zone_reaction_v2_reject_h1_touch_required,
        "h1_directional_touch_passed": matched is not None,
        "h1_touch_lookback_bars": lookback,
        "h1_touch_sample_count": len(recent),
        "h1_touch_evaluated_at": evaluated_at.isoformat() if evaluated_at else None,
        "h1_touch_candle_time": matched.get("time") if matched else None,
        "h1_touch_candle_open": matched.get("open") if matched else None,
        "h1_touch_candle_high": matched.get("high") if matched else None,
        "h1_touch_candle_low": matched.get("low") if matched else None,
        "h1_touch_candle_close": matched.get("close") if matched else None,
    }

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
    stop_fallback_atr_timeframe: str | None = None,
    context_candles: list[dict[str, Any]] | None = None,
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
    trade_modes = zone_trade_modes(zone)
    required_mode = zone_reaction_required_mode(reaction, trade_modes)
    if required_mode not in trade_modes:
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
    required_mode = zone_reaction_required_mode(reaction, trade_modes)
    if required_mode not in trade_modes:
        return []
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
    h1_touch_metadata = directional_h1_touch_metadata(
        zone=zone,
        direction=direction,
        context_candles=context_candles or [],
        as_of=as_of,
        config=config,
    )
    if (
        config.zone_reaction_v2_reject_h1_touch_required
        and reaction.state in {"reject", "internal_reject"}
        and not h1_touch_metadata["h1_directional_touch_passed"]
    ):
        if status != "blocked":
            status = "waiting_confirmation"
        reasons.append(
            "No closed H1 candle both touched this zone and matched the trade direction "
            f"within the last {config.zone_reaction_v2_reject_h1_touch_lookback_bars} H1 bars."
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
        stop_fallback_atr_timeframe=stop_fallback_atr_timeframe,
        level_metadata=level_metadata,
    )
    order_type = "market"
    entry_model = "market_reject"
    limit_order_expires_at: str | None = None
    impulse_limit_metadata = maybe_apply_impulse_retest_limit(
        zone=zone,
        direction=direction,
        reaction=reaction,
        entry=entry,
        stop=stop,
        atr=atr,
        as_of=as_of,
        config=config,
    )
    if impulse_limit_metadata:
        order_type = "limit"
        entry_model = "impulse_retest_limit"
        entry = impulse_limit_metadata["entry"]
        take_profit = impulse_limit_metadata["take_profit"]
        rr = impulse_limit_metadata["risk_reward"]
        limit_order_expires_at = impulse_limit_metadata["limit_order_expires_at"]
        level_metadata.update(impulse_limit_metadata["metadata"])
    stop_distance = abs(entry - stop) if entry is not None and stop is not None else None
    if reaction.state != "approaching":
        # Approaching zones stay "watching": entry/stop are placeholders until the
        # first touch, so RR/stop-distance/blocked checks would only add noise.
        if rr is None or rr < config.zone_reaction_v2_rr_minimum:
            blocked.append(f"RR {rr or 0:.2f} is below Zone Reaction V2 minimum {config.zone_reaction_v2_rr_minimum:.2f}.")
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
        expires_at=limit_order_expires_at,
        metadata={
            "as_of": as_of,
            "order_type": order_type,
            "entry_model": entry_model,
            "limit_order_expires_at": limit_order_expires_at,
            "zone_type": zone.get("type"),
            "zone_timeframe": zone.get("timeframe"),
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
            **h1_touch_metadata,
            "trade_modes": trade_modes,
            "overlays": sorted(overlays),
            "trigger_types": trigger_types,
            "structure_trigger_ids": structure_trigger_ids,
            "structure_trigger_types": structure_trigger_types,
            "price_action_trigger_ids": price_action_trigger_ids,
            "price_action_trigger_types": price_action_trigger_types,
            "atr": round(atr, 5),
            "stop_fallback_atr": level_metadata.get("stop_fallback_atr"),
            "stop_fallback_atr_timeframe": level_metadata.get("stop_fallback_atr_timeframe"),
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
            **{key: value for key, value in level_metadata.items() if str(key).startswith("impulse_limit")},
            **reaction.metadata,
        },
    )
    return [candidate]


def maybe_apply_impulse_retest_limit(
    *,
    zone: dict[str, Any],
    direction: str,
    reaction: ReactionResult,
    entry: float | None,
    stop: float | None,
    atr: float,
    as_of: str,
    config: StrategyConfig,
) -> dict[str, Any] | None:
    if reaction.state != "reject" or entry is None or stop is None or atr <= 0:
        return None
    range_threshold = config.zone_reaction_v2_impulse_limit_range_atr
    extension_threshold = config.zone_reaction_v2_impulse_limit_extension_atr
    expiry_bars = config.zone_reaction_v2_impulse_limit_expiry_bars
    if range_threshold <= 0 or extension_threshold <= 0 or expiry_bars <= 0:
        return None

    reaction_range = float(reaction.metadata.get("reaction_high") or 0.0) - float(
        reaction.metadata.get("reaction_low") or 0.0
    )
    if direction == "long":
        zone_edge = float(zone["price_high"])
        extension = entry - zone_edge
        limit_entry = zone_edge
        risk = limit_entry - stop
        take_profit = [limit_entry + risk * config.zone_reaction_v2_rr_minimum]
    else:
        zone_edge = float(zone["price_low"])
        extension = zone_edge - entry
        limit_entry = zone_edge
        risk = stop - limit_entry
        take_profit = [limit_entry - risk * config.zone_reaction_v2_rr_minimum]

    if reaction_range <= atr * range_threshold or extension <= atr * extension_threshold:
        return None
    if risk <= 0:
        return None

    expiry = impulse_limit_expiry(as_of, config.timeframe, expiry_bars)
    metadata = {
        "impulse_limit": True,
        "impulse_limit_reason": "reject_range_and_extension",
        "impulse_limit_signal_entry": round(entry, 5),
        "impulse_limit_entry": round(limit_entry, 5),
        "impulse_limit_zone_edge": round(zone_edge, 5),
        "impulse_limit_extension": round(extension, 5),
        "impulse_limit_extension_atr": round(extension / atr, 4),
        "impulse_limit_range": round(reaction_range, 5),
        "impulse_limit_range_atr": round(reaction_range / atr, 4),
        "impulse_limit_range_threshold_atr": range_threshold,
        "impulse_limit_extension_threshold_atr": extension_threshold,
        "impulse_limit_expiry_bars": expiry_bars,
    }
    return {
        "entry": limit_entry,
        "take_profit": take_profit,
        "risk_reward": config.zone_reaction_v2_rr_minimum,
        "limit_order_expires_at": expiry,
        "metadata": metadata,
    }


def impulse_limit_expiry(as_of: str, timeframe: str, expiry_bars: int) -> str | None:
    signal_time = parse_utc_datetime(as_of)
    if signal_time is None:
        return None
    try:
        delta = timeframe_delta(timeframe)
    except Exception:
        delta = timedelta(minutes=15)
    # The setup appears after the signal candle closes, so add one extra candle
    # before counting the future bars the limit order may wait for a retest.
    expires_at = signal_time + delta * (expiry_bars + 1)
    return expires_at.replace(microsecond=0).isoformat()


def zone_reaction_required_mode(reaction: ReactionResult, trade_modes: list[str]) -> str:
    if reaction.state == "internal_reject":
        return "internal_reject"
    if reaction.state in {"slow_reaction", "waiting_bos"} and "internal_reject" in trade_modes:
        return "internal_reject"
    return "reject"


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

    # SR keeps the original macro-only gate. Bot FVGs use an OR gate instead:
    # either H1 bias or macro trend may support the zone direction. This lets a
    # fresh H1 FVG trade when one context has turned but the slower one still lags.
    # Human zones continue to bypass both context gates.
    is_fvg = zone_type == "fvg"
    active_macro_gate = (
        config.zone_reaction_v2_macro_gate_enabled
        if not is_fvg
        else config.zone_reaction_v2_fvg_macro_gate_enabled
    )
    if not context_bypass and is_fvg and active_macro_gate:
        expected_bias = "bullish" if direction == "long" else "bearish"
        expected_macro = "up" if direction == "long" else "down"
        bias_supports = bias == expected_bias
        macro_supports = macro_trend == expected_macro
        if bias_supports or macro_supports:
            supporters = []
            if bias_supports:
                supporters.append(f"H1 bias {bias}")
            if macro_supports:
                supporters.append(f"macro trend {macro_trend}")
            reasons.append(f"FVG {direction} allowed by {' or '.join(supporters)}.")
        else:
            blocked.append(
                f"FVG {direction} requires H1 bias {expected_bias} or macro trend {expected_macro} "
                f"(bias={bias}, macro={macro_trend})."
            )
    elif not context_bypass and active_macro_gate:
        if macro_trend == "up" and direction == "short":
            blocked.append("Macro trend up blocks Zone Reaction V2 short.")
        elif macro_trend == "down" and direction == "long":
            blocked.append("Macro trend down blocks Zone Reaction V2 long.")
        else:
            reasons.append(f"Macro trend {macro_trend} allows {direction}.")
    elif not active_macro_gate:
        gate_scope = "FVG bias-or-macro" if is_fvg else "all zones"
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
    if is_fvg and active_macro_gate and not context_bypass:
        reasons.append("Standalone bias/regime gate disabled; H1 bias is evaluated by the FVG bias-or-macro gate.")
    else:
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
    elif reaction.state in {"reject", "fakeout", "internal_reject"}:
        status = "eligible"
    elif reaction.state == "waiting_bos" and has_trigger:
        reasons.append("BOS/CHOCH confirmed after slow reaction.")
        status = "eligible"
    elif reaction.state in {"slow_reaction", "waiting_bos"}:
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
    elif reaction.state in {"reject", "fakeout", "internal_reject"} and status == "eligible":
        active = "PREPARE_ENTRY"
    elif reaction.state == "fakeout" and status == "waiting_confirmation":
        active = "WAIT_FOR_BOS"
    elif reaction.state == "waiting_bos":
        active = "PREPARE_ENTRY" if has_trigger and status == "eligible" else "WAIT_FOR_BOS"
    elif reaction.state == "slow_reaction":
        active = "WAIT_FOR_BOS"
    elif status == "blocked" or blocked:
        active = "IDLE"

    steps = [
        ("IDLE", "Context check"),
        ("APPROACHING", "Approaching zone"),
        ("ZONE_TOUCHED", "Zone touched"),
        ("REACTING_IN_ZONE", "M15 reaction"),
        ("WAIT_FOR_BOS", "Wait BOS/CHOCH"),
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
    }.get(reaction.state, 0.0)
    if direction == bias_to_direction(bias):
        score += 0.18
    elif bias == "neutral" and regime == "ranging":
        score += 0.10
    if regime == "ranging" and str(zone.get("type")) == "consolidation":
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
