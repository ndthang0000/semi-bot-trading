from __future__ import annotations

import json
from datetime import datetime, timedelta
from dataclasses import replace
from sqlite3 import Connection

from .zones import (
    CandleSlice,
    PriceZone,
    SwingPoint,
    candle_body,
    candle_range,
    latest_atr,
    load_candle_slices,
    load_recent_swings,
    replace_price_zones,
    true_range,
)


FVG_DETECTOR = "fvg_v1"
ORDER_BLOCK_DETECTOR = "order_block_v1"
LIQUIDITY_DETECTOR = "liquidity_v1"
CONSOLIDATION_DETECTOR = "consolidation_v1"
SMC_DETECTORS = (FVG_DETECTOR, ORDER_BLOCK_DETECTOR, LIQUIDITY_DETECTOR, CONSOLIDATION_DETECTOR)
FVG_H1_MAX_ACTIVE_DAYS = 2.0
FVG_H1_DECAY_START_DAYS = 0.75
FVG_M15_MAX_ACTIVE_DAYS = 1.0
FVG_M15_DECAY_START_DAYS = 0.5
OB_H1_MAX_ACTIVE_DAYS = 3.0
OB_H1_DECAY_START_DAYS = 1.0
OB_M15_MAX_ACTIVE_DAYS = 2.0
OB_M15_DECAY_START_DAYS = 1.0


def detect_fvg_zones(
    candles: list[CandleSlice],
    symbol: str,
    timeframe: str,
    atr_period: int = 14,
    middle_candle_atr_multiplier: float = 2.0,
    gap_atr_ratio: float = 0.25,
    min_width_atr_ratio: float = 1.0,
    max_width_atr_ratio: float = 1.5,
    third_candle_follow_through_required: bool = True,
    third_candle_min_body_ratio: float = 0.20,
    max_zones: int = 80,
    fill_threshold: float = 0.95,
    partial_fill_threshold: float = 0.50,
    min_middle_body_ratio: float = 0.50,
    max_active_days: float | None = None,
    decay_start_days: float | None = None,
) -> list[PriceZone]:
    zones: list[PriceZone] = []
    if len(candles) < 3:
        return zones

    atr_values = atr_before_candle(candles, atr_period)
    for index in range(2, len(candles)):
        first = candles[index - 2]
        middle = candles[index - 1]
        third = candles[index]
        middle_range = candle_range(middle)
        if middle_range <= 0:
            continue
        middle_body_ratio = candle_body(middle) / middle_range
        if middle_body_ratio < min_middle_body_ratio:
            continue
        atr_value = atr_values[index - 1]
        if atr_value is None or atr_value <= 0:
            continue
        middle_range_atr = middle_range / atr_value
        if middle_range_atr < middle_candle_atr_multiplier:
            continue
        third_body_ratio = candle_body(third) / candle_range(third) if candle_range(third) > 0 else 0.0

        zone: PriceZone | None = None
        if third.low > first.high and (third.low - first.high) / atr_value >= max(gap_atr_ratio, min_width_atr_ratio):
            if third_candle_follow_through_required and not has_fvg_follow_through(
                third,
                "bullish",
                third_candle_min_body_ratio,
            ):
                continue
            zone = create_fvg_zone(
                symbol=symbol,
                timeframe=timeframe,
                direction="bullish",
                price_low=first.high,
                price_high=third.low,
                detected_at=third.open_time,
                middle_body_ratio=middle_body_ratio,
                middle_range_atr=middle_range_atr,
                gap_atr_ratio=(third.low - first.high) / atr_value,
                atr_value=atr_value,
                max_width_atr_ratio=max_width_atr_ratio,
                middle_time=middle.open_time,
                third_body_ratio=third_body_ratio,
                third_candle_follow_through_required=third_candle_follow_through_required,
            )
        elif third.high < first.low and (first.low - third.high) / atr_value >= max(gap_atr_ratio, min_width_atr_ratio):
            if third_candle_follow_through_required and not has_fvg_follow_through(
                third,
                "bearish",
                third_candle_min_body_ratio,
            ):
                continue
            zone = create_fvg_zone(
                symbol=symbol,
                timeframe=timeframe,
                direction="bearish",
                price_low=third.high,
                price_high=first.low,
                detected_at=third.open_time,
                middle_body_ratio=middle_body_ratio,
                middle_range_atr=middle_range_atr,
                gap_atr_ratio=(first.low - third.high) / atr_value,
                atr_value=atr_value,
                max_width_atr_ratio=max_width_atr_ratio,
                middle_time=middle.open_time,
                third_body_ratio=third_body_ratio,
                third_candle_follow_through_required=third_candle_follow_through_required,
            )
        if zone is None:
            continue

        zone = apply_fvg_fill_state(
            zone,
            candles[index + 1 :],
            fill_threshold,
            partial_fill_threshold,
            max_active_days=resolved_fvg_max_days(timeframe, max_active_days),
            decay_start_days=resolved_fvg_decay_start_days(timeframe, decay_start_days),
        )
        zones.append(zone)

    zones.sort(key=lambda zone: (zone.detected_at, zone.effective_weight), reverse=True)
    return zones[:max_zones]


def has_fvg_follow_through(candle: CandleSlice, direction: str, min_body_ratio: float) -> bool:
    candle_range_value = candle_range(candle)
    if candle.open is None or candle_range_value <= 0:
        return False
    body_ratio = candle_body(candle) / candle_range_value
    if body_ratio < min_body_ratio:
        return False
    if direction == "bullish":
        return candle.close > candle.open
    return candle.close < candle.open


def create_fvg_zone(
    symbol: str,
    timeframe: str,
    direction: str,
    price_low: float,
    price_high: float,
    detected_at: str,
    middle_body_ratio: float,
    middle_range_atr: float,
    gap_atr_ratio: float,
    atr_value: float,
    max_width_atr_ratio: float,
    middle_time: str,
    third_body_ratio: float,
    third_candle_follow_through_required: bool,
) -> PriceZone:
    original_price_low = price_low
    original_price_high = price_high
    original_width = max(price_high - price_low, 0.0)
    max_width = atr_value * max_width_atr_ratio if max_width_atr_ratio > 0 and atr_value > 0 else original_width
    was_shrunk = original_width > max_width > 0
    if was_shrunk:
        # Keep the side that price is expected to retest first, so FVG reject trades
        # do not inherit a huge stop from the far edge of a very wide imbalance.
        if direction == "bullish":
            price_high = price_low + max_width
        else:
            price_low = price_high - max_width
    width = max(price_high - price_low, 0.0)
    confidence = min(0.40 + middle_body_ratio * 0.25 + min(middle_range_atr, 3.0) * 0.08, 0.92)
    weight = min(0.35 + min(gap_atr_ratio, 1.0) * 0.20 + min(middle_range_atr, 3.0) * 0.08, 0.90)
    return PriceZone(
        symbol=symbol,
        timeframe=timeframe,
        detector=FVG_DETECTOR,
        zone_type="fvg",
        direction=direction,
        price_low=round(price_low, 5),
        price_high=round(price_high, 5),
        start_time=detected_at,
        end_time=None,
        valid_from=detected_at,
        valid_until=None,
        invalidated_at=None,
        invalidated_by_structure_point_id=None,
        detected_at=detected_at,
        bot_confidence=round(confidence, 4),
        bot_weight=round(weight, 4),
        effective_confidence=round(confidence, 4),
        effective_weight=round(weight, 4),
        status="active",
        source="bot",
        metadata={
            "detector": FVG_DETECTOR,
            "middle_candle_time": middle_time,
            "middle_body_ratio": round(middle_body_ratio, 4),
            "middle_range_atr": round(middle_range_atr, 4),
            "third_body_ratio": round(third_body_ratio, 4),
            "third_candle_follow_through_required": third_candle_follow_through_required,
            "gap_size": round(width, 5),
            "gap_atr_ratio": round(gap_atr_ratio, 4),
            "original_gap_low": round(original_price_low, 5),
            "original_gap_high": round(original_price_high, 5),
            "original_gap_size": round(original_width, 5),
            "max_width_atr_ratio": round(max_width_atr_ratio, 4),
            "max_width_price": round(max_width, 5),
            "shrunk_for_entry": was_shrunk,
            "atr_at_detection": round(atr_value, 5),
            "consequent_encroachment": round((price_low + price_high) / 2, 5),
            "fill_ratio": 0.0,
        },
    )


def apply_fvg_fill_state(
    zone: PriceZone,
    future_candles: list[CandleSlice],
    fill_threshold: float,
    partial_fill_threshold: float,
    max_active_days: float,
    decay_start_days: float,
) -> PriceZone:
    width = max(zone.price_high - zone.price_low, 0.00001)
    expires_at = zone_expiry_time(zone, max_active_days)
    fill_ratio = 0.0
    fill_time: str | None = None
    observed_until = future_candles[-1].open_time if future_candles else zone.detected_at
    for candle in future_candles:
        if candle.open_time > expires_at:
            break
        if zone.direction == "bullish":
            if candle.low >= zone.price_high:
                continue
            fill_ratio = max(fill_ratio, (zone.price_high - max(candle.low, zone.price_low)) / width)
        else:
            if candle.high <= zone.price_low:
                continue
            fill_ratio = max(fill_ratio, (min(candle.high, zone.price_high) - zone.price_low) / width)
        if fill_ratio >= fill_threshold:
            fill_time = candle.open_time
            break

    metadata = {**zone.metadata, "fill_ratio": round(min(fill_ratio, 1.0), 4)}
    if fill_ratio >= fill_threshold:
        return replace(
            zone,
            status="mitigated",
            end_time=fill_time,
            valid_until=fill_time,
            invalidated_at=fill_time,
            effective_weight=round(zone.bot_weight * 0.25, 4),
            effective_confidence=round(zone.bot_confidence * 0.70, 4),
            metadata={**metadata, "fill_state": "filled"},
        )
    if fill_ratio >= partial_fill_threshold:
        return finish_unresolved_smc_zone(
            replace(
                zone,
                effective_weight=round(zone.bot_weight * 0.60, 4),
                effective_confidence=round(zone.bot_confidence * 0.85, 4),
                metadata={**metadata, "fill_state": "partial"},
            ),
            observed_until=observed_until,
            max_active_days=max_active_days,
            decay_start_days=decay_start_days,
        )
    return finish_unresolved_smc_zone(
        replace(zone, metadata={**metadata, "fill_state": "open"}),
        observed_until=observed_until,
        max_active_days=max_active_days,
        decay_start_days=decay_start_days,
    )


def apply_persisted_fvg_mitigation(
    conn: Connection,
    symbol: str,
    timeframe: str,
    fill_threshold: float = 0.95,
    partial_fill_threshold: float = 0.50,
) -> int:
    """Apply FVG fill lifecycle to persisted zones from any source.

    Detector refresh already handles fresh bot FVGs, but human/mixed FVG rows are
    protected from replacement. This pass makes every persisted FVG obey the same
    fill/mitigation rule regardless of source.
    """

    candles = load_candle_slices(conn, symbol, timeframe)
    if not candles:
        return 0
    rows = conn.execute(
        """
        SELECT *
        FROM price_zones
        WHERE symbol = ?
          AND timeframe = ?
          AND zone_type = 'fvg'
          AND status = 'active'
        ORDER BY detected_at
        """,
        (symbol, timeframe),
    ).fetchall()
    updates = 0
    for row in rows:
        width = max(float(row["price_high"]) - float(row["price_low"]), 0.00001)
        detected_at = str(row["detected_at"] or row["valid_from"] or row["start_time"])
        valid_until = row["valid_until"]
        fill_ratio = 0.0
        fill_time: str | None = None
        for candle in candles:
            if candle.open_time <= detected_at:
                continue
            if valid_until and candle.open_time > str(valid_until):
                break
            if row["direction"] == "bullish":
                if candle.low >= float(row["price_high"]):
                    continue
                fill_ratio = max(fill_ratio, (float(row["price_high"]) - max(candle.low, float(row["price_low"]))) / width)
            else:
                if candle.high <= float(row["price_low"]):
                    continue
                fill_ratio = max(fill_ratio, (min(candle.high, float(row["price_high"])) - float(row["price_low"])) / width)
            if fill_ratio >= fill_threshold:
                fill_time = candle.open_time
                break

        if fill_ratio < partial_fill_threshold:
            continue

        metadata = _metadata_from_json(row["metadata_json"])
        previous_fill_ratio = float(metadata.get("fill_ratio") or 0.0)
        next_fill_ratio = round(min(fill_ratio, 1.0), 4)
        if fill_ratio < fill_threshold and metadata.get("fill_state") == "partial" and previous_fill_ratio >= next_fill_ratio:
            continue
        metadata.update(
            {
                "fill_ratio": next_fill_ratio,
                "fvg_lifecycle_applied_to_source": row["source"],
            }
        )
        if fill_ratio >= fill_threshold and fill_time is not None:
            metadata.update(
                {
                    "fill_state": "filled",
                    "mitigated_rule": "fvg_fill_threshold",
                    "mitigated_at": fill_time,
                }
            )
            conn.execute(
                """
                UPDATE price_zones
                SET status = 'mitigated',
                    end_time = ?,
                    valid_until = ?,
                    invalidated_at = ?,
                    effective_weight = ?,
                    effective_confidence = ?,
                    metadata_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    fill_time,
                    fill_time,
                    fill_time,
                    round(float(row["bot_weight"]) * 0.25, 4),
                    round(float(row["bot_confidence"]) * 0.70, 4),
                    json.dumps(metadata, sort_keys=True),
                    row["id"],
                ),
            )
            updates += 1
        else:
            metadata["fill_state"] = "partial"
            conn.execute(
                """
                UPDATE price_zones
                SET effective_weight = ?,
                    effective_confidence = ?,
                    metadata_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    round(float(row["bot_weight"]) * 0.60, 4),
                    round(float(row["bot_confidence"]) * 0.85, 4),
                    json.dumps(metadata, sort_keys=True),
                    row["id"],
                ),
            )
            updates += 1
    return updates


def _metadata_from_json(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        metadata = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return metadata if isinstance(metadata, dict) else {}


def detect_order_block_zones(
    candles: list[CandleSlice],
    symbol: str,
    timeframe: str,
    swings: list[SwingPoint] | None = None,
    atr_period: int = 14,
    displacement_atr_multiplier: float = 1.5,
    min_body_ratio: float = 0.60,
    min_width_atr_ratio: float = 0.05,
    max_width_atr_ratio: float = 1.0,
    require_structure_break: bool = True,
    merge_overlap_ratio: float = 0.60,
    lookback_candles: int = 3,
    max_zones: int = 60,
    max_active_days: float | None = None,
    decay_start_days: float | None = None,
) -> list[PriceZone]:
    zones: list[PriceZone] = []
    structure_swings = swings or []
    seen_candidates: set[tuple[str, str]] = set()
    atr_values = atr_before_candle(candles, atr_period)
    for index in range(1, len(candles)):
        candle = candles[index]
        candle_range_value = candle_range(candle)
        if candle_range_value <= 0:
            continue
        body_ratio = candle_body(candle) / candle_range_value
        atr_value = atr_values[index]
        if atr_value is None or candle_range_value < atr_value * displacement_atr_multiplier or body_ratio < min_body_ratio:
            continue

        direction = "bullish" if candle.close > (candle.open or candle.close) else "bearish"
        broken_swing = order_block_structure_break(candle, direction, structure_swings)
        if require_structure_break and broken_swing is None:
            continue
        candidate = find_order_block_candidate(candles, index, direction, lookback_candles)
        if candidate is None:
            continue
        body_low = min(candidate.open if candidate.open is not None else candidate.close, candidate.close)
        body_high = max(candidate.open if candidate.open is not None else candidate.close, candidate.close)
        width_atr = (body_high - body_low) / atr_value
        if width_atr < min_width_atr_ratio or width_atr > max_width_atr_ratio:
            continue
        candidate_key = (candidate.open_time, direction)
        if candidate_key in seen_candidates:
            continue
        seen_candidates.add(candidate_key)
        zone = create_order_block_zone(
            candidate,
            displacement=candle,
            symbol=symbol,
            timeframe=timeframe,
            direction=direction,
            atr_value=atr_value,
            body_ratio=body_ratio,
            broken_swing=broken_swing,
        )
        zones.append(
            apply_order_block_state(
                zone,
                candles[index + 1 :],
                max_active_days=resolved_ob_max_days(timeframe, max_active_days),
                decay_start_days=resolved_ob_decay_start_days(timeframe, decay_start_days),
            )
        )

    zones = merge_overlapping_order_blocks(zones, merge_overlap_ratio)
    zones.sort(key=lambda zone: (zone.detected_at, zone.effective_weight), reverse=True)
    return zones[:max_zones]


def find_order_block_candidate(
    candles: list[CandleSlice],
    displacement_index: int,
    direction: str,
    lookback_candles: int,
) -> CandleSlice | None:
    start = max(0, displacement_index - lookback_candles)
    for candidate in reversed(candles[start:displacement_index]):
        if candidate.open is None:
            continue
        if direction == "bullish" and candidate.close < candidate.open:
            return candidate
        if direction == "bearish" and candidate.close > candidate.open:
            return candidate
    return None


def create_order_block_zone(
    candidate: CandleSlice,
    displacement: CandleSlice,
    symbol: str,
    timeframe: str,
    direction: str,
    atr_value: float,
    body_ratio: float,
    broken_swing: SwingPoint | None,
) -> PriceZone:
    body_low = min(candidate.open if candidate.open is not None else candidate.close, candidate.close)
    body_high = max(candidate.open if candidate.open is not None else candidate.close, candidate.close)
    displacement_range_atr = candle_range(displacement) / atr_value
    structure_break_bonus = 0.12 if broken_swing is not None else 0.0
    confidence = min(0.42 + body_ratio * 0.24 + min(displacement_range_atr, 2.5) * 0.08 + structure_break_bonus, 0.94)
    weight = min(0.36 + body_ratio * 0.18 + min(displacement_range_atr, 2.5) * 0.10 + structure_break_bonus, 0.94)
    return PriceZone(
        symbol=symbol,
        timeframe=timeframe,
        detector=ORDER_BLOCK_DETECTOR,
        zone_type="order_block",
        direction=direction,
        price_low=round(body_low, 5),
        price_high=round(body_high, 5),
        start_time=candidate.open_time,
        end_time=None,
        valid_from=displacement.open_time,
        valid_until=None,
        invalidated_at=None,
        invalidated_by_structure_point_id=None,
        detected_at=displacement.open_time,
        bot_confidence=round(confidence, 4),
        bot_weight=round(weight, 4),
        effective_confidence=round(confidence, 4),
        effective_weight=round(weight, 4),
        status="active",
        source="bot",
        metadata={
            "detector": ORDER_BLOCK_DETECTOR,
            "definition": "last opposite candle body before displacement that breaks structure",
            "candidate_time": candidate.open_time,
            "displacement_time": displacement.open_time,
            "displacement_range_atr": round(displacement_range_atr, 4),
            "displacement_body_ratio": round(body_ratio, 4),
            "body_zone_low": round(body_low, 5),
            "body_zone_high": round(body_high, 5),
            "body_width_atr": round((body_high - body_low) / atr_value, 4),
            "wick_extension_low": round(candidate.low, 5),
            "wick_extension_high": round(candidate.high, 5),
            "broken_swing_id": broken_swing.id if broken_swing else None,
            "broken_swing_type": broken_swing.swing_type if broken_swing else None,
            "broken_swing_price": round(broken_swing.price, 5) if broken_swing else None,
            "broken_swing_time": broken_swing.event_time if broken_swing else None,
            "mitigation_ratio": 0.0,
        },
    )


def order_block_structure_break(candle: CandleSlice, direction: str, swings: list[SwingPoint]) -> SwingPoint | None:
    if not swings:
        return None
    if direction == "bullish":
        candidates = [swing for swing in swings if swing.swing_type == "high" and swing.event_time < candle.open_time]
        candidates.sort(key=lambda swing: swing.event_time, reverse=True)
        for swing in candidates[:5]:
            if candle.close > swing.price:
                return swing
    else:
        candidates = [swing for swing in swings if swing.swing_type == "low" and swing.event_time < candle.open_time]
        candidates.sort(key=lambda swing: swing.event_time, reverse=True)
        for swing in candidates[:5]:
            if candle.close < swing.price:
                return swing
    return None


def merge_overlapping_order_blocks(zones: list[PriceZone], overlap_ratio: float) -> list[PriceZone]:
    if overlap_ratio <= 0 or not zones:
        return zones
    merged: list[PriceZone] = []
    for zone in sorted(zones, key=lambda item: (item.detected_at, item.effective_weight), reverse=True):
        existing_index = next(
            (
                index
                for index, existing in enumerate(merged)
                if existing.direction == zone.direction and price_overlap_ratio(existing, zone) >= overlap_ratio
            ),
            None,
        )
        if existing_index is None:
            merged.append(zone)
            continue
        if order_block_rank(zone) > order_block_rank(merged[existing_index]):
            merged[existing_index] = zone
    return merged


def price_overlap_ratio(first: PriceZone, second: PriceZone) -> float:
    overlap = min(first.price_high, second.price_high) - max(first.price_low, second.price_low)
    if overlap <= 0:
        return 0.0
    smaller_width = max(min(first.price_high - first.price_low, second.price_high - second.price_low), 0.00001)
    return overlap / smaller_width


def order_block_rank(zone: PriceZone) -> tuple[int, float, str]:
    status_rank = 2 if zone.status == "active" else 1 if zone.status == "mitigated" else 0
    return (status_rank, zone.effective_weight, zone.detected_at)


def apply_order_block_state(
    zone: PriceZone,
    future_candles: list[CandleSlice],
    max_active_days: float,
    decay_start_days: float,
) -> PriceZone:
    width = max(zone.price_high - zone.price_low, 0.00001)
    expires_at = zone_expiry_time(zone, max_active_days)
    mitigation_ratio = 0.0
    mitigation_time: str | None = None
    invalidated_at: str | None = None
    observed_until = future_candles[-1].open_time if future_candles else zone.detected_at
    for candle in future_candles:
        if candle.open_time > expires_at:
            break
        if zone.direction == "bullish":
            if candle.close < zone.price_low:
                invalidated_at = candle.open_time
                break
            if candle.low <= zone.price_high and candle.high >= zone.price_low:
                mitigation_ratio = max(mitigation_ratio, (zone.price_high - max(candle.low, zone.price_low)) / width)
                mitigation_time = candle.open_time
        else:
            if candle.close > zone.price_high:
                invalidated_at = candle.open_time
                break
            if candle.high >= zone.price_low and candle.low <= zone.price_high:
                mitigation_ratio = max(mitigation_ratio, (min(candle.high, zone.price_high) - zone.price_low) / width)
                mitigation_time = candle.open_time

    metadata = {**zone.metadata, "mitigation_ratio": round(min(mitigation_ratio, 1.0), 4)}
    if invalidated_at:
        return replace(
            zone,
            status="invalidated",
            end_time=invalidated_at,
            valid_until=invalidated_at,
            invalidated_at=invalidated_at,
            effective_weight=round(zone.bot_weight * 0.15, 4),
            effective_confidence=round(zone.bot_confidence * 0.65, 4),
            metadata={**metadata, "invalidated_rule": "close beyond order block body"},
        )
    if mitigation_ratio >= 0.80:
        return replace(
            zone,
            status="mitigated",
            end_time=mitigation_time,
            valid_until=mitigation_time,
            invalidated_at=mitigation_time,
            effective_weight=round(zone.bot_weight * 0.30, 4),
            effective_confidence=round(zone.bot_confidence * 0.75, 4),
            metadata={**metadata, "mitigation_state": "full"},
        )
    if mitigation_ratio >= 0.50:
        return finish_unresolved_smc_zone(
            replace(
                zone,
                effective_weight=round(zone.bot_weight * 0.65, 4),
                effective_confidence=round(zone.bot_confidence * 0.88, 4),
                metadata={**metadata, "mitigation_state": "partial"},
            ),
            observed_until=observed_until,
            max_active_days=max_active_days,
            decay_start_days=decay_start_days,
        )
    return finish_unresolved_smc_zone(
        replace(zone, metadata={**metadata, "mitigation_state": "fresh"}),
        observed_until=observed_until,
        max_active_days=max_active_days,
        decay_start_days=decay_start_days,
    )


def finish_unresolved_smc_zone(
    zone: PriceZone,
    observed_until: str,
    max_active_days: float,
    decay_start_days: float,
) -> PriceZone:
    expires_at = zone_expiry_time(zone, max_active_days)
    age_days = max((datetime.fromisoformat(observed_until) - datetime.fromisoformat(zone.detected_at)).total_seconds() / 86400, 0.0)
    decay_multiplier = smc_age_decay_multiplier(age_days, max_active_days, decay_start_days)
    metadata = {
        **zone.metadata,
        "max_active_days": max_active_days,
        "decay_start_days": decay_start_days,
        "expires_at": expires_at,
        "age_days_at_evaluation": round(age_days, 4),
        "age_decay_multiplier": round(decay_multiplier, 4),
    }
    if observed_until >= expires_at:
        return replace(
            zone,
            status="expired",
            end_time=expires_at,
            valid_until=expires_at,
            effective_weight=round(zone.effective_weight * 0.20, 4),
            effective_confidence=round(zone.effective_confidence * 0.80, 4),
            metadata={**metadata, "expired_rule": "smc_zone_max_active_days"},
        )
    return replace(
        zone,
        end_time=expires_at,
        valid_until=expires_at,
        effective_weight=round(zone.effective_weight * decay_multiplier, 4),
        effective_confidence=round(zone.effective_confidence * max(decay_multiplier, 0.80), 4),
        metadata=metadata,
    )


def zone_expiry_time(zone: PriceZone, max_active_days: float) -> str:
    base_time = datetime.fromisoformat(zone.detected_at)
    return (base_time + timedelta(days=max_active_days)).isoformat()


def smc_age_decay_multiplier(age_days: float, max_active_days: float, decay_start_days: float) -> float:
    if max_active_days <= decay_start_days or age_days <= decay_start_days:
        return 1.0
    progress = min((age_days - decay_start_days) / (max_active_days - decay_start_days), 1.0)
    return max(1.0 - progress * 0.50, 0.50)


def resolved_fvg_max_days(timeframe: str, override: float | None = None) -> float:
    if override is not None:
        return override
    return FVG_M15_MAX_ACTIVE_DAYS if timeframe.upper() == "M15" else FVG_H1_MAX_ACTIVE_DAYS


def resolved_fvg_decay_start_days(timeframe: str, override: float | None = None) -> float:
    if override is not None:
        return override
    return FVG_M15_DECAY_START_DAYS if timeframe.upper() == "M15" else FVG_H1_DECAY_START_DAYS


def resolved_ob_max_days(timeframe: str, override: float | None = None) -> float:
    if override is not None:
        return override
    return OB_M15_MAX_ACTIVE_DAYS if timeframe.upper() == "M15" else OB_H1_MAX_ACTIVE_DAYS


def resolved_ob_decay_start_days(timeframe: str, override: float | None = None) -> float:
    if override is not None:
        return override
    return OB_M15_DECAY_START_DAYS if timeframe.upper() == "M15" else OB_H1_DECAY_START_DAYS


def detect_liquidity_sweep_zones(
    candles: list[CandleSlice],
    swings: list[SwingPoint],
    symbol: str,
    timeframe: str,
    atr_period: int = 14,
    zone_atr_multiplier: float = 0.12,
    max_zones: int = 80,
) -> list[PriceZone]:
    if not candles or not swings:
        return []
    candles_by_time = {candle.open_time: candle for candle in candles}
    candle_times = [candle.open_time for candle in candles]
    zones: list[PriceZone] = []
    for swing in swings:
        start_index = first_candle_index_after(candle_times, swing.event_time)
        if start_index is None:
            continue
        for index in range(start_index, len(candles)):
            candle = candles[index]
            if swing.swing_type == "high" and candle.high > swing.price and candle.close < swing.price:
                zones.append(
                    create_liquidity_zone(
                        symbol,
                        timeframe,
                        swing,
                        candle,
                        candles[: index + 1],
                        direction="bearish",
                        sweep_type="buy_side_sweep",
                        zone_atr_multiplier=zone_atr_multiplier,
                        atr_period=atr_period,
                    )
                )
                break
            if swing.swing_type == "low" and candle.low < swing.price and candle.close > swing.price:
                zones.append(
                    create_liquidity_zone(
                        symbol,
                        timeframe,
                        swing,
                        candle,
                        candles[: index + 1],
                        direction="bullish",
                        sweep_type="sell_side_sweep",
                        zone_atr_multiplier=zone_atr_multiplier,
                        atr_period=atr_period,
                    )
                )
                break

    deduped: dict[tuple[str, str], PriceZone] = {}
    for zone in zones:
        deduped[(str(zone.metadata["swing_point_id"]), str(zone.metadata["sweep_time"]))] = zone
    result = list(deduped.values())
    result.sort(key=lambda zone: (zone.detected_at, zone.effective_weight), reverse=True)
    return result[:max_zones]


def first_candle_index_after(candle_times: list[str], event_time: str) -> int | None:
    for index, open_time in enumerate(candle_times):
        if open_time > event_time:
            return index
    return None


def create_liquidity_zone(
    symbol: str,
    timeframe: str,
    swing: SwingPoint,
    sweep_candle: CandleSlice,
    candles_to_sweep: list[CandleSlice],
    direction: str,
    sweep_type: str,
    zone_atr_multiplier: float,
    atr_period: int,
) -> PriceZone:
    atr_value = latest_atr(candles_to_sweep, period=atr_period) or max(swing.price * 0.0005, 1.0)
    half_width = max(atr_value * zone_atr_multiplier, swing.price * 0.0002, 0.5)
    confidence = 0.72 if candle_body(sweep_candle) > 0 else 0.64
    weight = 0.70
    return PriceZone(
        symbol=symbol,
        timeframe=timeframe,
        detector=LIQUIDITY_DETECTOR,
        zone_type="liquidity_pool",
        direction=direction,
        price_low=round(swing.price - half_width, 5),
        price_high=round(swing.price + half_width, 5),
        start_time=swing.event_time,
        end_time=sweep_candle.open_time,
        valid_from=swing.event_time,
        valid_until=sweep_candle.open_time,
        invalidated_at=sweep_candle.open_time,
        invalidated_by_structure_point_id=swing.id,
        detected_at=sweep_candle.open_time,
        bot_confidence=round(confidence, 4),
        bot_weight=round(weight, 4),
        effective_confidence=round(confidence, 4),
        effective_weight=round(weight * 0.55, 4),
        status="swept",
        source="bot",
        metadata={
            "detector": LIQUIDITY_DETECTOR,
            "swing_point_id": swing.id,
            "swing_type": swing.swing_type,
            "sweep_type": sweep_type,
            "sweep_time": sweep_candle.open_time,
            "swept_level": round(swing.price, 5),
            "sweep_close_reclaim": round(abs(sweep_candle.close - swing.price), 5),
            "atr_at_sweep": round(atr_value, 5),
        },
    )


def atr_before_candle(candles: list[CandleSlice], period: int) -> list[float | None]:
    values: list[float | None] = []
    ranges: list[float] = []
    previous_close: float | None = None
    rolling_sum = 0.0
    for candle in candles:
        if ranges:
            window_size = min(len(ranges), period)
            values.append(rolling_sum / window_size)
        else:
            values.append(None)

        current_range = true_range(candle, previous_close)
        ranges.append(current_range)
        rolling_sum += current_range
        if len(ranges) > period:
            rolling_sum -= ranges[-period - 1]
        previous_close = candle.close
    return values


def detect_consolidation_zones(
    candles: list[CandleSlice],
    symbol: str,
    timeframe: str,
    min_candles: int = 12,
    max_candles: int = 36,
    max_width_atr: float = 4.0,
    max_efficiency: float = 0.35,
    min_touches: int = 4,
    max_zones: int = 30,
) -> list[PriceZone]:
    zones: list[PriceZone] = []
    if len(candles) < min_candles:
        return zones

    true_ranges = candle_true_ranges(candles)
    true_range_prefix = prefix_sums(true_ranges)
    index = min_candles
    while index <= len(candles):
        best_zone: PriceZone | None = None
        best_end = index
        for window in range(min_candles, min(max_candles, index) + 1):
            start = index - window
            travel = window_true_range_sum(candles, true_ranges, true_range_prefix, start, index)
            atr_value = travel / window
            candidate = candles[start:index]
            zone = consolidation_candidate_to_zone(
                candidate,
                symbol,
                timeframe,
                max_width_atr,
                max_efficiency,
                min_touches,
                atr_value,
                travel,
            )
            if zone is not None:
                best_zone = zone
                best_end = index
        if best_zone is None:
            index += 1
            continue
        zones.append(apply_consolidation_breakout(best_zone, candles[best_end:]))
        index = best_end + max(3, min_candles // 3)

    zones = merge_similar_consolidations(zones)
    zones.sort(key=lambda zone: (zone.detected_at, zone.effective_weight), reverse=True)
    return zones[:max_zones]


def consolidation_candidate_to_zone(
    window: list[CandleSlice],
    symbol: str,
    timeframe: str,
    max_width_atr: float,
    max_efficiency: float,
    min_touches: int,
    atr_value: float | None = None,
    travel: float | None = None,
) -> PriceZone | None:
    atr_value = average_true_range(window) if atr_value is None else atr_value
    if atr_value <= 0:
        return None
    high = max(candle.high for candle in window)
    low = min(candle.low for candle in window)
    width = high - low
    if width > atr_value * max_width_atr:
        return None
    if travel is None:
        travel = sum(true_range(candle, window[index - 1].close if index else None) for index, candle in enumerate(window))
    efficiency = abs(window[-1].close - window[0].close) / max(travel, 0.00001)
    if efficiency > max_efficiency:
        return None
    high_touches = sum(1 for candle in window if high - candle.high <= width * 0.18)
    low_touches = sum(1 for candle in window if candle.low - low <= width * 0.18)
    touch_count = high_touches + low_touches
    if touch_count < min_touches or high_touches == 0 or low_touches == 0:
        return None

    confidence = min(0.40 + touch_count * 0.04 + (max_efficiency - efficiency) * 0.50, 0.88)
    weight = min(0.35 + touch_count * 0.035 + max(0.0, max_width_atr - width / atr_value) * 0.05, 0.86)
    return PriceZone(
        symbol=symbol,
        timeframe=timeframe,
        detector=CONSOLIDATION_DETECTOR,
        zone_type="consolidation",
        direction="neutral",
        price_low=round(low, 5),
        price_high=round(high, 5),
        start_time=window[0].open_time,
        end_time=None,
        valid_from=window[-1].open_time,
        valid_until=None,
        invalidated_at=None,
        invalidated_by_structure_point_id=None,
        detected_at=window[-1].open_time,
        bot_confidence=round(confidence, 4),
        bot_weight=round(weight, 4),
        effective_confidence=round(confidence, 4),
        effective_weight=round(weight, 4),
        status="active",
        source="bot",
        metadata={
            "detector": CONSOLIDATION_DETECTOR,
            "window_candles": len(window),
            "width_atr": round(width / atr_value, 4),
            "range_efficiency": round(efficiency, 4),
            "touch_count": touch_count,
            "high_touches": high_touches,
            "low_touches": low_touches,
            "atr_at_detection": round(atr_value, 5),
        },
    )


def average_true_range(candles: list[CandleSlice]) -> float:
    if not candles:
        return 0.0
    ranges = [
        true_range(candle, candles[index - 1].close if index else None)
        for index, candle in enumerate(candles)
    ]
    return sum(ranges) / len(ranges)


def candle_true_ranges(candles: list[CandleSlice]) -> list[float]:
    values: list[float] = []
    previous_close: float | None = None
    for candle in candles:
        values.append(true_range(candle, previous_close))
        previous_close = candle.close
    return values


def prefix_sums(values: list[float]) -> list[float]:
    result = [0.0]
    total = 0.0
    for value in values:
        total += value
        result.append(total)
    return result


def window_true_range_sum(
    candles: list[CandleSlice],
    true_ranges: list[float],
    prefix: list[float],
    start: int,
    end: int,
) -> float:
    if start >= end:
        return 0.0
    first_range = candle_range(candles[start])
    rest = prefix[end] - prefix[start + 1] if start + 1 < end else 0.0
    return first_range + rest


def apply_consolidation_breakout(zone: PriceZone, future_candles: list[CandleSlice]) -> PriceZone:
    width = max(zone.price_high - zone.price_low, 0.00001)
    breakout_buffer = width * 0.08
    for candle in future_candles:
        if candle.close > zone.price_high + breakout_buffer:
            return replace(
                zone,
                status="broken",
                direction="bullish",
                end_time=candle.open_time,
                invalidated_at=candle.open_time,
                effective_weight=round(zone.bot_weight * 0.45, 4),
                effective_confidence=round(zone.bot_confidence * 0.80, 4),
                metadata={**zone.metadata, "breakout_direction": "bullish", "breakout_time": candle.open_time},
            )
        if candle.close < zone.price_low - breakout_buffer:
            return replace(
                zone,
                status="broken",
                direction="bearish",
                end_time=candle.open_time,
                invalidated_at=candle.open_time,
                effective_weight=round(zone.bot_weight * 0.45, 4),
                effective_confidence=round(zone.bot_confidence * 0.80, 4),
                metadata={**zone.metadata, "breakout_direction": "bearish", "breakout_time": candle.open_time},
            )
    return zone


def merge_similar_consolidations(zones: list[PriceZone]) -> list[PriceZone]:
    merged: list[PriceZone] = []
    for zone in sorted(zones, key=lambda item: item.start_time):
        if not merged:
            merged.append(zone)
            continue
        previous = merged[-1]
        overlap_low = max(previous.price_low, zone.price_low)
        overlap_high = min(previous.price_high, zone.price_high)
        overlap = max(0.0, overlap_high - overlap_low)
        smaller_width = max(min(previous.price_high - previous.price_low, zone.price_high - zone.price_low), 0.00001)
        if overlap / smaller_width >= 0.60 and zone.start_time <= (previous.end_time or zone.start_time):
            better = zone if zone.effective_weight >= previous.effective_weight else previous
            merged[-1] = better
        else:
            merged.append(zone)
    return merged


def detect_smc_zones(
    candles: list[CandleSlice],
    swings: list[SwingPoint],
    symbol: str,
    timeframe: str,
    fvg_middle_candle_atr_multiplier: float = 2.0,
    fvg_gap_atr_ratio: float = 0.25,
    fvg_min_width_atr_ratio: float = 1.0,
    fvg_max_width_atr_ratio: float = 1.5,
    fvg_third_candle_follow_through_required: bool = True,
    fvg_third_candle_min_body_ratio: float = 0.20,
    fvg_max_active_days: float | None = None,
    fvg_decay_start_days: float | None = None,
    ob_displacement_atr_multiplier: float = 1.5,
    ob_min_body_ratio: float = 0.60,
    ob_min_width_atr_ratio: float = 0.05,
    ob_max_width_atr_ratio: float = 1.0,
    ob_require_structure_break: bool = True,
    ob_merge_overlap_ratio: float = 0.60,
    ob_max_active_days: float | None = None,
    ob_decay_start_days: float | None = None,
    max_fvg_zones: int = 80,
    max_order_block_zones: int = 60,
    max_liquidity_zones: int = 80,
    max_consolidation_zones: int = 30,
) -> dict[str, list[PriceZone]]:
    detected: dict[str, list[PriceZone]] = {
        FVG_DETECTOR: [],
        ORDER_BLOCK_DETECTOR: [],
        LIQUIDITY_DETECTOR: [],
        CONSOLIDATION_DETECTOR: [],
    }
    if max_fvg_zones > 0:
        detected[FVG_DETECTOR] = detect_fvg_zones(
            candles,
            symbol,
            timeframe,
            middle_candle_atr_multiplier=fvg_middle_candle_atr_multiplier,
            gap_atr_ratio=fvg_gap_atr_ratio,
            min_width_atr_ratio=fvg_min_width_atr_ratio,
            max_width_atr_ratio=fvg_max_width_atr_ratio,
            third_candle_follow_through_required=fvg_third_candle_follow_through_required,
            third_candle_min_body_ratio=fvg_third_candle_min_body_ratio,
            max_active_days=fvg_max_active_days,
            decay_start_days=fvg_decay_start_days,
            max_zones=max_fvg_zones,
        )
    if max_order_block_zones > 0:
        detected[ORDER_BLOCK_DETECTOR] = detect_order_block_zones(
            candles,
            symbol,
            timeframe,
            swings=swings,
            displacement_atr_multiplier=ob_displacement_atr_multiplier,
            min_body_ratio=ob_min_body_ratio,
            min_width_atr_ratio=ob_min_width_atr_ratio,
            max_width_atr_ratio=ob_max_width_atr_ratio,
            require_structure_break=ob_require_structure_break,
            merge_overlap_ratio=ob_merge_overlap_ratio,
            max_active_days=ob_max_active_days,
            decay_start_days=ob_decay_start_days,
            max_zones=max_order_block_zones,
        )
    if max_liquidity_zones > 0:
        detected[LIQUIDITY_DETECTOR] = detect_liquidity_sweep_zones(
            candles,
            swings,
            symbol,
            timeframe,
            max_zones=max_liquidity_zones,
        )
    if max_consolidation_zones > 0:
        detected[CONSOLIDATION_DETECTOR] = detect_consolidation_zones(
            candles,
            symbol,
            timeframe,
            max_zones=max_consolidation_zones,
        )
    return detected


def detect_and_store_smc_zones(
    conn: Connection,
    symbol: str,
    timeframe: str,
    max_candles: int = 5000,
    lookback_swings: int = 300,
    fvg_middle_candle_atr_multiplier: float = 2.0,
    fvg_gap_atr_ratio: float = 0.25,
    fvg_min_width_atr_ratio: float = 1.0,
    fvg_max_width_atr_ratio: float = 1.5,
    fvg_third_candle_follow_through_required: bool = True,
    fvg_third_candle_min_body_ratio: float = 0.20,
    fvg_max_active_days: float | None = None,
    fvg_decay_start_days: float | None = None,
    ob_displacement_atr_multiplier: float = 1.5,
    ob_min_body_ratio: float = 0.60,
    ob_min_width_atr_ratio: float = 0.05,
    ob_max_width_atr_ratio: float = 1.0,
    ob_require_structure_break: bool = True,
    ob_merge_overlap_ratio: float = 0.60,
    ob_max_active_days: float | None = None,
    ob_decay_start_days: float | None = None,
    max_fvg_zones: int = 80,
    max_order_block_zones: int = 60,
    max_liquidity_zones: int = 80,
    max_consolidation_zones: int = 30,
) -> dict[str, int]:
    candles = load_candle_slices(conn, symbol, timeframe)
    if max_candles > 0:
        candles = candles[-max_candles:]
    swings = load_recent_swings(conn, symbol, timeframe, lookback_swings)
    if candles:
        first_candle_time = candles[0].open_time
        swings = [swing for swing in swings if swing.event_time >= first_candle_time]
    detected = detect_smc_zones(
        candles,
        swings,
        symbol,
        timeframe,
        fvg_middle_candle_atr_multiplier=fvg_middle_candle_atr_multiplier,
        fvg_gap_atr_ratio=fvg_gap_atr_ratio,
        fvg_min_width_atr_ratio=fvg_min_width_atr_ratio,
        fvg_max_width_atr_ratio=fvg_max_width_atr_ratio,
        fvg_third_candle_follow_through_required=fvg_third_candle_follow_through_required,
        fvg_third_candle_min_body_ratio=fvg_third_candle_min_body_ratio,
        fvg_max_active_days=fvg_max_active_days,
        fvg_decay_start_days=fvg_decay_start_days,
        ob_displacement_atr_multiplier=ob_displacement_atr_multiplier,
        ob_min_body_ratio=ob_min_body_ratio,
        ob_min_width_atr_ratio=ob_min_width_atr_ratio,
        ob_max_width_atr_ratio=ob_max_width_atr_ratio,
        ob_require_structure_break=ob_require_structure_break,
        ob_merge_overlap_ratio=ob_merge_overlap_ratio,
        ob_max_active_days=ob_max_active_days,
        ob_decay_start_days=ob_decay_start_days,
        max_fvg_zones=max_fvg_zones,
        max_order_block_zones=max_order_block_zones,
        max_liquidity_zones=max_liquidity_zones,
        max_consolidation_zones=max_consolidation_zones,
    )
    return {
        detector: replace_price_zones(conn, symbol, timeframe, detector, zones)
        for detector, zones in detected.items()
    }
