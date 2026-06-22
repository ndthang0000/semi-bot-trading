from __future__ import annotations

from sqlite3 import Connection
from typing import Any

from .chart import (
    CHART_PAYLOAD_VERSION,
    build_m15_trigger_overlays,
    build_atr_snapshot,
    build_rsi_snapshot,
    load_chart_candles,
    load_chart_trades,
    load_chart_zones,
)
from .config import AppConfig
from .context import percentile_rank, rolling_average, score_bias_from_structure, score_macro_trend, true_ranges
from .price_action import detect_price_action_patterns
from .smc_zones import detect_smc_zones
from .strategy import build_setup_candidates
from .structure import CandleView, StructurePoint, SwingLevel, detect_break_structure, detect_swing_structure
from .zones import (
    CandleSlice,
    SwingPoint,
    apply_lifecycle_to_zones,
    detect_support_resistance_zones,
)


def build_realtime_replay_payload(
    conn: Connection,
    config: AppConfig,
    symbol: str,
    timeframe: str,
    limit: int,
    replay_start: str,
    replay_at: str,
    active_zones_only: bool = False,
    include_human_zones: bool = True,
    allowed_playbooks: set[str] | None = None,
    replay_enabled: bool = True,
    start_index: int | None = None,
) -> dict[str, Any]:
    candles = load_chart_candles(conn, symbol, timeframe, limit, start=replay_start, end=replay_at)
    if not candles:
        raise ValueError(f"No replay candles found for {symbol} {timeframe}")

    range_start = candles[0]["time"]
    range_end = candles[-1]["time"]
    structure_timeframe = config.bias.timeframe
    structure_candles = load_chart_candles(conn, symbol, structure_timeframe, 3000, start=replay_start, end=replay_at)
    structure_views = chart_candles_to_views(structure_candles)
    swing_config = config.swing_for(structure_timeframe)
    swing_points = detect_swing_structure(
        structure_views,
        symbol,
        structure_timeframe,
        swing_config.window,
        swing_config.tolerance,
    )
    break_points = detect_break_structure(
        structure_views,
        structure_points_to_swing_levels(swing_points),
        symbol,
        structure_timeframe,
        close_break_buffer=config.breaks.close_break_buffer,
    )
    structure_points = [*swing_points, *break_points]
    structure_points.sort(key=lambda point: (point.event_time, point.detector, point.point_type))

    zone_swings = structure_points_to_zone_swings(swing_points)
    structure_slices = chart_candles_to_slices(structure_candles)
    zones = detect_support_resistance_zones(
        zone_swings[-config.support_resistance.lookback_swings :],
        symbol,
        structure_timeframe,
        config.support_resistance.tolerance_pct,
        config.support_resistance.min_zone_width,
        config.support_resistance.min_touches,
        config.support_resistance.max_zones,
        structure_slices,
        config.support_resistance.atr_width_multiplier,
        candidate_close_break_buffer=config.zone_lifecycle.close_break_buffer,
        candidate_close_break_buffer_atr_multiplier=config.zone_lifecycle.close_break_buffer_atr_multiplier,
    )
    zones = apply_lifecycle_to_zones(
        zones,
        structure_slices,
        config.zone_lifecycle.close_break_buffer,
        config.zone_lifecycle.recent_touch_lookback_candles,
        config.zone_lifecycle.age_decay_per_100_candles,
        config.zone_lifecycle.freshness_bonus,
        config.zone_lifecycle.invalidation_weight_multiplier,
        config.zone_lifecycle.close_break_buffer_atr_multiplier,
        config.zone_reaction.reaction_window_candles,
        config.zone_reaction.min_reaction_atr,
        config.zone_reaction.strong_reaction_atr,
        config.zone_reaction.recent_reaction_count,
        config.zone_decay.max_healthy_touches,
        config.zone_decay.weak_touch_penalty,
        config.zone_decay.too_many_touches_penalty,
        config.zone_decay.linger_penalty,
        config.zone_lifecycle.false_break_refine_enabled,
        config.zone_lifecycle.false_break_refine_max_width_atr_multiplier,
        config.zone_lifecycle.false_break_parent_weight_multiplier,
    )
    smc_detected = detect_smc_zones(
        structure_slices,
        zone_swings[-config.smc_zones.lookback_swings :],
        symbol,
        structure_timeframe,
        fvg_middle_candle_atr_multiplier=config.smc_zones.fvg_middle_candle_atr_multiplier,
        fvg_gap_atr_ratio=config.smc_zones.fvg_gap_atr_ratio,
        fvg_min_width_atr_ratio=config.smc_zones.fvg_min_width_atr_ratio,
        fvg_max_width_atr_ratio=config.smc_zones.fvg_max_width_atr_ratio,
        fvg_third_candle_follow_through_required=config.smc_zones.fvg_third_candle_follow_through_required,
        fvg_third_candle_min_body_ratio=config.smc_zones.fvg_third_candle_min_body_ratio,
        fvg_max_active_days=config.smc_zones.fvg_max_active_days_for(structure_timeframe),
        fvg_decay_start_days=config.smc_zones.fvg_decay_start_days_for(structure_timeframe),
        ob_displacement_atr_multiplier=config.smc_zones.ob_displacement_atr_multiplier,
        ob_min_body_ratio=config.smc_zones.ob_min_body_ratio,
        ob_min_width_atr_ratio=config.smc_zones.ob_min_width_atr_ratio,
        ob_max_width_atr_ratio=config.smc_zones.ob_max_width_atr_ratio,
        ob_require_structure_break=config.smc_zones.ob_require_structure_break,
        ob_merge_overlap_ratio=config.smc_zones.ob_merge_overlap_ratio,
        ob_max_active_days=config.smc_zones.ob_max_active_days_for(structure_timeframe),
        ob_decay_start_days=config.smc_zones.ob_decay_start_days_for(structure_timeframe),
        max_fvg_zones=config.smc_zones.max_fvg_zones,
        max_order_block_zones=config.smc_zones.max_order_block_zones,
        max_liquidity_zones=config.smc_zones.max_liquidity_zones,
        max_consolidation_zones=config.smc_zones.max_consolidation_zones,
    )
    smc_zones = [zone for detector_zones in smc_detected.values() for zone in detector_zones]
    if active_zones_only:
        zones = [zone for zone in zones if zone.status == "active"]
        smc_zones = [zone for zone in smc_zones if zone.status == "active"]
    human_zones = []
    if include_human_zones:
        human_zones = [
            zone
            for zone in load_chart_zones(conn, symbol, structure_timeframe, range_start, range_end, active_only=active_zones_only)
            if zone["detector"] == "human_manual_v1"
        ]

    contexts = build_replay_contexts(symbol, structure_timeframe, structure_points, structure_views, config)
    chart_zones = [*human_zones, *[zone_to_chart(zone) for zone in [*zones, *smc_zones]]]
    strategy_candles = load_chart_candles(conn, symbol, config.strategy.timeframe, 3000, start=replay_start, end=replay_at)
    setup_candidates: list[dict[str, Any]] = []
    if strategy_candles:
        strategy_slices = chart_candles_to_slices(strategy_candles)
        strategy_views = chart_candles_to_views(strategy_candles)
        strategy_swing_config = config.swing_for(config.strategy.timeframe)
        strategy_swings = detect_swing_structure(
            strategy_views,
            symbol,
            config.strategy.timeframe,
            strategy_swing_config.window,
            strategy_swing_config.tolerance,
        )
        strategy_breaks = detect_break_structure(
            strategy_views,
            structure_points_to_swing_levels(strategy_swings),
            symbol,
            config.strategy.timeframe,
            close_break_buffer=config.breaks.close_break_buffer,
        )
        strategy_price_action = detect_price_action_patterns(
            strategy_slices,
            symbol,
            config.strategy.timeframe,
            atr_period=config.price_action.atr_period,
            displacement_atr_multiplier=config.price_action.displacement_atr_multiplier,
            displacement_body_ratio=config.price_action.displacement_body_ratio,
            pinbar_wick_body_ratio=config.price_action.pinbar_wick_body_ratio,
            pinbar_min_wick_ratio=config.price_action.pinbar_min_wick_ratio,
            engulfing_min_body_ratio=config.price_action.engulfing_min_body_ratio,
            marubozu_min_body_ratio=config.price_action.marubozu_min_body_ratio,
            star_large_body_ratio=config.price_action.star_large_body_ratio,
            star_small_body_ratio=config.price_action.star_small_body_ratio,
        )
        strategy_points = [*strategy_swings, *strategy_breaks, *strategy_price_action]
        strategy_points.sort(key=lambda point: (point.event_time, point.detector, point.point_type))
        setup_candidates = build_setup_candidates(
            symbol=symbol,
            zones=chart_zones,
            contexts=contexts,
            candles=strategy_candles,
            structure_points=[structure_point_to_chart(point) for point in strategy_points],
            config=config.strategy,
            context_timeframe=structure_timeframe,
            allowed_playbooks=allowed_playbooks,
            # Breakout logic expects context-timeframe (H1) candles; the replay
            # view candles may be M15, which would diverge from the backtest.
            context_candles=structure_candles,
        )
    m15_triggers = build_m15_trigger_overlays(
        conn,
        symbol,
        timeframe,
        structure_timeframe,
        range_start,
        range_end,
        chart_zones,
        setup_candidates,
    )
    payload = {
        "version": CHART_PAYLOAD_VERSION,
        "symbol": symbol,
        "timeframe": timeframe,
        "range": {
            "start": range_start,
            "end": range_end,
            "limit": limit,
            "start_index": start_index,
            "requested_start": replay_start,
            "requested_end": replay_at,
        },
        "layers": {
            "candles": candles,
            "structure": [structure_point_to_chart(point) for point in structure_points if range_start <= point.event_time <= range_end],
            "structure_timeframe": structure_timeframe,
            "zones": chart_zones,
            "contexts": contexts,
            "atr": build_atr_snapshot(conn, symbol, ["H1", "M15"], period=14, end=range_end),
            "rsi": build_rsi_snapshot(conn, symbol, ["H1"], period=14, end=range_end),
            "trades": load_chart_trades(conn, symbol, range_start, range_end, allowed_playbooks=allowed_playbooks),
            "setup_candidates": setup_candidates,
            "m15_triggers": m15_triggers,
        },
    }
    if replay_enabled:
        payload["replay"] = {
            "enabled": True,
            "as_of": replay_at,
            "start": replay_start,
            "lookahead_guard": "detectors recomputed from replay window candles only",
        }
    return payload


def chart_candles_to_views(candles: list[dict[str, Any]]) -> list[CandleView]:
    return [
        CandleView(
            open_time=str(candle["time"]),
            high=float(candle["high"]),
            low=float(candle["low"]),
            close=float(candle["close"]),
        )
        for candle in candles
    ]


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


def structure_points_to_swing_levels(points: list[StructurePoint]) -> list[SwingLevel]:
    levels: list[SwingLevel] = []
    for point in points:
        swing_type = point.metadata.get("swing_type")
        if swing_type not in ("high", "low"):
            continue
        levels.append(
            SwingLevel(
                id=point.id,
                point_type=point.point_type,
                swing_type=str(swing_type),
                price=point.price,
                event_time=point.event_time,
                confirmed_at=str(point.metadata.get("confirmed_at", point.event_time)),
            )
        )
    return sorted(levels, key=lambda item: (item.confirmed_at, item.event_time))


def structure_points_to_zone_swings(points: list[StructurePoint]) -> list[SwingPoint]:
    swings: list[SwingPoint] = []
    for point in points:
        swing_type = point.metadata.get("swing_type")
        if swing_type not in ("high", "low"):
            continue
        swings.append(
            SwingPoint(
                id=point.id,
                point_type=point.point_type,
                price=point.price,
                event_time=point.event_time,
                swing_type=str(swing_type),
            )
        )
    return sorted(swings, key=lambda item: item.event_time)


def structure_point_to_chart(point: StructurePoint) -> dict[str, Any]:
    return {
        "id": point.id,
        "time": point.event_time,
        "type": point.point_type,
        "price": point.price,
        "detector": point.detector,
        "status": point.status,
        "confidence": point.confidence,
        "direction": point.metadata.get("direction"),
        "related_zone_ids": point.related_zone_ids,
        "metadata": point.metadata,
    }


def zone_to_chart(zone: Any) -> dict[str, Any]:
    return {
        "id": zone.id,
        "type": zone.zone_type,
        "direction": zone.direction,
        "detector": zone.detector,
        "status": zone.status,
        "source": zone.source,
        "price_low": zone.price_low,
        "price_high": zone.price_high,
        "visual_start": zone.start_time,
        "visual_end": zone.end_time,
        "valid_from": zone.valid_from,
        "valid_until": zone.valid_until,
        "invalidated_at": zone.invalidated_at,
        "invalidated_by_structure_point_id": zone.invalidated_by_structure_point_id,
        "detected_at": zone.detected_at,
        "weight": zone.effective_weight,
        "confidence": zone.effective_confidence,
        "metadata": zone.metadata,
    }


def build_replay_contexts(
    symbol: str,
    timeframe: str,
    structure_points: list[StructurePoint],
    candles: list[CandleView],
    config: AppConfig,
    macro_candles: list[CandleView] | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    contexts: dict[str, dict[str, dict[str, Any]]] = {timeframe: {}}
    bias = detect_replay_bias(symbol, timeframe, structure_points, candles, config)
    if bias:
        contexts[timeframe]["bias"] = bias
    regime = detect_replay_regime(symbol, timeframe, structure_points, candles, config)
    if regime:
        contexts[timeframe]["regime"] = regime
    macro = detect_replay_macro_trend(symbol, timeframe, macro_candles if macro_candles is not None else candles, config)
    if macro:
        contexts[timeframe]["macro_trend"] = macro
    return contexts


def detect_replay_macro_trend(
    symbol: str,
    timeframe: str,
    candles: list[CandleView],
    config: AppConfig,
) -> dict[str, Any] | None:
    if not candles:
        return None
    candle_rows = [
        {
            "open_time": candle.open_time,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
        }
        for candle in candles
    ]
    score = score_macro_trend(
        candle_rows,
        config.macro_trend.lookback_candles,
        config.macro_trend.flat_threshold_atr,
        config.macro_trend.atr_period,
    )
    return context_to_chart(
        value=str(score["value"]),
        confidence=float(score["confidence"]),
        valid_from=candles[-1].open_time,
        metadata={
            "detector": "macro_trend_v1_replay",
            "version": 1,
            "symbol": symbol,
            "timeframe": timeframe,
            "lookback_candles": score["lookback_candles"],
            "momentum": score["momentum"],
            "momentum_atr": score["momentum_atr"],
            "atr": score["atr"],
            "reference_time": score["reference_time"],
        },
    )


def detect_replay_bias(
    symbol: str,
    timeframe: str,
    points: list[StructurePoint],
    candles: list[CandleView],
    config: AppConfig,
) -> dict[str, Any] | None:
    swings = [point for point in points if point.point_type in ("HH", "HL", "LH", "LL")][-config.bias.recent_swings :]
    breaks = [point for point in points if point.point_type in ("BOS", "CHOCH")][-config.bias.recent_breaks :]
    if not swings and not breaks:
        return None

    swing_rows = [
        {
            "point_type": point.point_type,
            "price": point.price,
            "event_time": point.event_time,
            "metadata": point.metadata,
        }
        for point in swings
    ]
    break_rows = [
        {
            "point_type": point.point_type,
            "price": point.price,
            "event_time": point.event_time,
            "metadata": point.metadata,
        }
        for point in breaks
    ]
    candle_rows = [
        {
            "open_time": candle.open_time,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
        }
        for candle in candles[-60:]
    ]
    score = score_bias_from_structure(swing_rows, break_rows, candle_rows)
    value = str(score["value"])
    confidence = float(score["confidence"])
    valid_from = (breaks or swings)[-1].event_time
    return context_to_chart(
        value=value,
        confidence=round(confidence, 4),
        valid_from=valid_from,
        metadata={
            "detector": "bias_v2_replay",
            "version": 2,
            "symbol": symbol,
            "timeframe": timeframe,
            "swing_score": round(float(score["swing_score"]), 6),
            "break_score": round(float(score["break_score"]), 6),
            "raw_score": round(float(score["raw_score"]), 6),
            "normalized_score": round(float(score["normalized_score"]), 6),
            "total_weight": round(float(score["total_weight"]), 6),
            "latest_break_type": score["latest_break_type"],
            "latest_break_direction": score["latest_break_direction"],
            "latest_choch_direction": score["latest_choch_direction"],
            "neutral_reason": score["neutral_reason"],
            "choch_neutralized": score["choch_neutralized"],
            "range_neutralized": score["range_neutralized"],
            "range_efficiency": round(float(score["range_efficiency"]), 6) if score["range_efficiency"] is not None else None,
            "atr": round(float(score["atr"]), 6) if score["atr"] is not None else None,
            "recent_swings": len(swings),
            "recent_breaks": len(breaks),
            "swing_points": score["swing_contributions"],
            "break_points": score["break_contributions"],
        },
    )


def detect_replay_regime(
    symbol: str,
    timeframe: str,
    points: list[StructurePoint],
    candles: list[CandleView],
    config: AppConfig,
) -> dict[str, Any] | None:
    required = config.regime.atr_period + 2
    if len(candles) < required:
        return None
    recent = candles[-config.regime.lookback :] if len(candles) >= config.regime.lookback else candles
    candle_dicts = [
        {"open_time": candle.open_time, "high": candle.high, "low": candle.low, "close": candle.close}
        for candle in candles
    ]
    ranges = true_ranges(candle_dicts)
    atr_values = rolling_average(ranges, config.regime.atr_period)
    if not atr_values:
        return None

    recent_atrs = atr_values[-len(recent) :]
    current_atr = recent_atrs[-1]
    average_atr = sum(recent_atrs) / len(recent_atrs)
    atr_ratio = current_atr / average_atr if average_atr else 1.0
    atr_percentile = percentile_rank(recent_atrs, current_atr)
    first_close = recent[0].close
    last_close = recent[-1].close
    total_travel = sum(true_ranges([{"high": c.high, "low": c.low, "close": c.close} for c in recent]))
    range_efficiency = abs(last_close - first_close) / total_travel if total_travel else 0.0
    start_time = recent[0].open_time
    bos_breaks = [point for point in points if point.point_type == "BOS" and point.event_time >= start_time]
    directions = [point.metadata.get("direction") for point in bos_breaks]
    up_count = sum(1 for direction in directions if direction == "up")
    down_count = sum(1 for direction in directions if direction == "down")
    directional_count = max(up_count, down_count)
    directional_ratio = directional_count / len(bos_breaks) if bos_breaks else 0.0

    if len(bos_breaks) >= config.regime.trend_min_bos and directional_ratio >= config.regime.trend_break_ratio:
        primary = "trending"
    elif range_efficiency <= config.regime.range_efficiency_max:
        primary = "ranging"
    else:
        primary = "trending"
    overlays: list[str] = []
    if atr_ratio >= config.regime.expansion_atr_ratio:
        overlays.append("expansion")
    elif atr_ratio <= config.regime.contraction_atr_ratio:
        overlays.append("contraction")
    if atr_percentile >= config.regime.atr_high_percentile:
        overlays.append("high_volatility")
    elif atr_percentile <= config.regime.atr_low_percentile:
        overlays.append("low_volatility")
    confidence = directional_ratio if primary == "trending" else min(1.0 - range_efficiency, 1.0)
    return context_to_chart(
        value=primary,
        confidence=round(confidence, 4),
        valid_from=recent[-1].open_time,
        secondary_value=",".join(overlays) if overlays else None,
        metadata={
            "detector": "regime_v1_replay",
            "symbol": symbol,
            "timeframe": timeframe,
            "overlays": overlays,
            "atr_ratio": round(atr_ratio, 6),
            "atr_percentile": round(atr_percentile, 6),
            "range_efficiency": round(range_efficiency, 6),
            "bos_count": len(bos_breaks),
            "bos_up_count": up_count,
            "bos_down_count": down_count,
        },
    )


def context_to_chart(
    value: str,
    confidence: float,
    valid_from: str,
    secondary_value: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "bot_value": value,
        "primary_value": value,
        "secondary_value": secondary_value,
        "bot_confidence": confidence,
        "effective_value": value,
        "effective_confidence": confidence,
        "source": "bot",
        "valid_from": valid_from,
        "valid_until": None,
        "status": "active",
        "metadata": metadata or {},
    }
