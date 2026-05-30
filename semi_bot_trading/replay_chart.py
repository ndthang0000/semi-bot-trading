from __future__ import annotations

from sqlite3 import Connection
from typing import Any

from .chart import CHART_PAYLOAD_VERSION, load_chart_candles, load_chart_trades
from .config import AppConfig
from .context import percentile_rank, rolling_average, true_ranges
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
    zones = detect_support_resistance_zones(
        zone_swings[-config.support_resistance.lookback_swings :],
        symbol,
        timeframe,
        config.support_resistance.tolerance_pct,
        config.support_resistance.min_zone_width,
        config.support_resistance.min_touches,
        config.support_resistance.max_zones,
    )
    zones = apply_lifecycle_to_zones(
        zones,
        chart_candles_to_slices(candles),
        config.zone_lifecycle.close_break_buffer,
        config.zone_lifecycle.recent_touch_lookback_candles,
        config.zone_lifecycle.age_decay_per_100_candles,
        config.zone_lifecycle.freshness_bonus,
        config.zone_lifecycle.invalidation_weight_multiplier,
    )
    if active_zones_only:
        zones = [zone for zone in zones if zone.status == "active"]

    contexts = build_replay_contexts(symbol, structure_timeframe, structure_points, structure_views, config)
    return {
        "version": CHART_PAYLOAD_VERSION,
        "symbol": symbol,
        "timeframe": timeframe,
        "range": {
            "start": range_start,
            "end": range_end,
            "limit": limit,
            "requested_start": replay_start,
            "requested_end": replay_at,
        },
        "layers": {
            "candles": candles,
            "structure": [structure_point_to_chart(point) for point in structure_points if range_start <= point.event_time <= range_end],
            "structure_timeframe": structure_timeframe,
            "zones": [zone_to_chart(zone) for zone in zones],
            "contexts": contexts,
            "trades": load_chart_trades(conn, symbol, range_start, range_end),
        },
        "replay": {
            "enabled": True,
            "as_of": replay_at,
            "start": replay_start,
            "lookahead_guard": "detectors recomputed from replay window candles only",
        },
    }


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
) -> dict[str, dict[str, dict[str, Any]]]:
    contexts: dict[str, dict[str, dict[str, Any]]] = {timeframe: {}}
    bias = detect_replay_bias(symbol, timeframe, structure_points, config)
    if bias:
        contexts[timeframe]["bias"] = bias
    regime = detect_replay_regime(symbol, timeframe, structure_points, candles, config)
    if regime:
        contexts[timeframe]["regime"] = regime
    return contexts


def detect_replay_bias(symbol: str, timeframe: str, points: list[StructurePoint], config: AppConfig) -> dict[str, Any] | None:
    swings = [point for point in points if point.point_type in ("HH", "HL", "LH", "LL")][-config.bias.recent_swings :]
    breaks = [point for point in points if point.point_type in ("BOS", "CHOCH")][-config.bias.recent_breaks :]
    if not swings and not breaks:
        return None

    swing_score = sum(1 if point.point_type in ("HH", "HL") else -1 for point in swings)
    break_score = 0
    latest_break_direction: str | None = None
    latest_break_type: str | None = None
    for point in breaks:
        direction = point.metadata.get("direction")
        if direction == "up":
            break_score += 1
        elif direction == "down":
            break_score -= 1
        latest_break_direction = str(direction) if direction in ("up", "down") else None
        latest_break_type = point.point_type

    raw_score = swing_score + break_score
    if raw_score >= 2:
        value = "bullish"
    elif raw_score <= -2:
        value = "bearish"
    else:
        value = "neutral"
    if latest_break_type == "CHOCH" and latest_break_direction == "up" and value == "bearish":
        value = "neutral"
    elif latest_break_type == "CHOCH" and latest_break_direction == "down" and value == "bullish":
        value = "neutral"

    total_inputs = max(len(swings) + len(breaks), 1)
    confidence = min(abs(raw_score) / total_inputs, 1.0)
    if value == "neutral":
        confidence = max(0.35, 1.0 - confidence)
    valid_from = (breaks or swings)[-1].event_time
    return context_to_chart(
        value=value,
        confidence=round(confidence, 4),
        valid_from=valid_from,
        metadata={
            "detector": "bias_v1_replay",
            "symbol": symbol,
            "timeframe": timeframe,
            "swing_score": swing_score,
            "break_score": break_score,
            "raw_score": raw_score,
            "recent_swings": len(swings),
            "recent_breaks": len(breaks),
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
