from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from sqlite3 import Connection
from typing import Any


SR_DETECTOR = "sr_v2"
LEGACY_SR_DETECTORS = ("sr_v1",)


@dataclass(frozen=True)
class SwingPoint:
    id: str
    point_type: str
    price: float
    event_time: str
    swing_type: str


@dataclass(frozen=True)
class PriceZone:
    symbol: str
    timeframe: str
    detector: str
    zone_type: str
    direction: str
    price_low: float
    price_high: float
    start_time: str
    end_time: str | None
    valid_from: str
    valid_until: str | None
    invalidated_at: str | None
    invalidated_by_structure_point_id: str | None
    detected_at: str
    bot_confidence: float
    bot_weight: float
    effective_confidence: float
    effective_weight: float
    status: str
    source: str
    metadata: dict[str, object]

    @property
    def id(self) -> str:
        raw = (
            f"{self.symbol}|{self.timeframe}|{self.detector}|{self.zone_type}|"
            f"{self.price_low:.5f}|{self.price_high:.5f}|{self.start_time}"
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CandleSlice:
    open_time: str
    high: float
    low: float
    close: float
    open: float | None = None


@dataclass(frozen=True)
class TouchEvent:
    start_time: str
    end_time: str
    start_index: int
    end_index: int
    touch_type: str
    duration_candles: int
    penetration_ratio: float
    clean_rejection: bool
    wick_absorption: bool
    reaction_score: float
    reaction_metrics: dict[str, object]


@dataclass
class ZoneCluster:
    swing_type: str
    points: list[SwingPoint]

    @property
    def center(self) -> float:
        return sum(point.price for point in self.points) / len(self.points)

    @property
    def first_time(self) -> str:
        return min(point.event_time for point in self.points)

    @property
    def last_time(self) -> str:
        return max(point.event_time for point in self.points)


def zone_half_width(
    center: float,
    tolerance_pct: float,
    min_zone_width: float,
    atr_value: float | None = None,
    atr_width_multiplier: float = 0.0,
) -> float:
    atr_width = (atr_value or 0.0) * atr_width_multiplier
    return max(center * tolerance_pct, atr_width, min_zone_width)


def atr_for_time(candles: list[CandleSlice] | None, end_time: str, fallback: float | None = None) -> float | None:
    if candles:
        return latest_atr(candles, end_time=end_time)
    return fallback


def atr_lookup_by_time(candles: list[CandleSlice], period: int = 14) -> dict[str, float]:
    values: dict[str, float] = {}
    ranges: list[float] = []
    previous_close: float | None = None
    rolling_sum = 0.0
    for candle in candles:
        current_range = true_range(candle, previous_close)
        ranges.append(current_range)
        rolling_sum += current_range
        if len(ranges) > period:
            rolling_sum -= ranges[-period - 1]
        window_size = min(len(ranges), period)
        if window_size:
            values[candle.open_time] = rolling_sum / window_size
        previous_close = candle.close
    return values


def load_recent_swings(
    conn: Connection,
    symbol: str,
    timeframe: str,
    lookback_swings: int,
) -> list[SwingPoint]:
    rows = conn.execute(
        """
        SELECT id, point_type, price, event_time, metadata_json
        FROM structure_points
        WHERE symbol = ? AND timeframe = ? AND detector = 'swing_v1'
        ORDER BY event_time DESC
        LIMIT ?
        """,
        (symbol, timeframe, lookback_swings),
    ).fetchall()
    swings: list[SwingPoint] = []
    for row in rows:
        metadata = json.loads(row["metadata_json"])
        swing_type = metadata.get("swing_type")
        if swing_type not in ("high", "low"):
            continue
        swings.append(
            SwingPoint(
                id=row["id"],
                point_type=row["point_type"],
                price=float(row["price"]),
                event_time=row["event_time"],
                swing_type=str(swing_type),
            )
        )
    return sorted(swings, key=lambda item: item.event_time)


def cluster_swings(
    swings: list[SwingPoint],
    swing_type: str,
    tolerance_pct: float,
    min_zone_width: float,
    atr_candles: list[CandleSlice] | None = None,
    atr_width_multiplier: float = 0.0,
    fallback_atr_value: float | None = None,
    atr_lookup: dict[str, float] | None = None,
) -> list[ZoneCluster]:
    clusters: list[ZoneCluster] = []
    candidates = sorted(
        [swing for swing in swings if swing.swing_type == swing_type],
        key=lambda item: item.price,
    )
    for swing in candidates:
        matched: ZoneCluster | None = None
        for cluster in clusters:
            atr_value = atr_lookup.get(swing.event_time) if atr_lookup else atr_for_time(atr_candles, swing.event_time, fallback_atr_value)
            tolerance = zone_half_width(cluster.center, tolerance_pct, min_zone_width, atr_value, atr_width_multiplier)
            if abs(swing.price - cluster.center) <= tolerance:
                matched = cluster
                break
        if matched is None:
            clusters.append(ZoneCluster(swing_type=swing_type, points=[swing]))
        else:
            matched.points.append(swing)
    return clusters


def zone_from_cluster(
    symbol: str,
    timeframe: str,
    cluster: ZoneCluster,
    tolerance_pct: float,
    min_zone_width: float,
    latest_swing_time: str,
    atr_candles: list[CandleSlice] | None = None,
    atr_width_multiplier: float = 0.0,
    fallback_atr_value: float | None = None,
    atr_lookup: dict[str, float] | None = None,
) -> PriceZone:
    prices = [point.price for point in cluster.points]
    center = cluster.center
    atr_value = atr_lookup.get(cluster.last_time) if atr_lookup else atr_for_time(atr_candles, cluster.last_time, fallback_atr_value)
    half_width = zone_half_width(center, tolerance_pct, min_zone_width, atr_value, atr_width_multiplier)
    price_low = min(prices) - half_width
    price_high = max(prices) + half_width
    touch_count = len(cluster.points)
    recency_rank = sum(1 for point in cluster.points if point.event_time >= latest_swing_time)
    confidence = min(0.35 + touch_count * 0.12, 1.0)
    weight = min(0.25 + touch_count * 0.10 + recency_rank * 0.10, 1.0)
    zone_type = "resistance" if cluster.swing_type == "high" else "support"
    direction = "bearish" if zone_type == "resistance" else "bullish"

    return PriceZone(
        symbol=symbol,
        timeframe=timeframe,
        detector=SR_DETECTOR,
        zone_type=zone_type,
        direction=direction,
        price_low=round(price_low, 5),
        price_high=round(price_high, 5),
        start_time=cluster.first_time,
        end_time=None,
        valid_from=cluster.last_time,
        valid_until=None,
        invalidated_at=None,
        invalidated_by_structure_point_id=None,
        detected_at=cluster.last_time,
        bot_confidence=round(confidence, 4),
        bot_weight=round(weight, 4),
        effective_confidence=round(confidence, 4),
        effective_weight=round(weight, 4),
        status="active",
        source="bot",
        metadata={
            "detector": SR_DETECTOR,
            "touch_count": touch_count,
            "center": round(center, 5),
            "half_width": round(half_width, 5),
            "atr_at_detection": round(atr_value, 5) if atr_value is not None else None,
            "tolerance_pct": tolerance_pct,
            "atr_width_multiplier": atr_width_multiplier,
            "min_zone_width": min_zone_width,
            "swing_point_ids": [point.id for point in cluster.points],
            "swing_point_times": [point.event_time for point in cluster.points],
            "swing_point_prices": prices,
        },
    )


def load_candle_slices(conn: Connection, symbol: str, timeframe: str) -> list[CandleSlice]:
    rows = conn.execute(
        """
        SELECT open_time, open, high, low, close
        FROM candles
        WHERE symbol = ? AND timeframe = ?
        ORDER BY open_time
        """,
        (symbol, timeframe),
    ).fetchall()
    return [
        CandleSlice(
            open_time=row["open_time"],
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for row in rows
    ]


def true_range(candle: CandleSlice, previous_close: float | None) -> float:
    if previous_close is None:
        return candle.high - candle.low
    return max(candle.high - candle.low, abs(candle.high - previous_close), abs(candle.low - previous_close))


def latest_atr(candles: list[CandleSlice], period: int = 14, end_time: str | None = None) -> float | None:
    scoped = [candle for candle in candles if end_time is None or candle.open_time <= end_time]
    if len(scoped) < 2:
        return None
    ranges: list[float] = []
    previous_close: float | None = None
    for candle in scoped:
        ranges.append(true_range(candle, previous_close))
        previous_close = candle.close
    window = ranges[-period:]
    if not window:
        return None
    return sum(window) / len(window)


def average_body(candles: list[CandleSlice], end_index: int, lookback: int = 20) -> float:
    start = max(0, end_index - lookback + 1)
    bodies = [candle_body(candle) for candle in candles[start : end_index + 1]]
    return sum(bodies) / len(bodies) if bodies else 0.0


def candle_overlaps_zone(candle: CandleSlice, zone: PriceZone) -> bool:
    return candle.high >= zone.price_low and candle.low <= zone.price_high


def invalidates_zone(candle: CandleSlice, zone: PriceZone, close_break_buffer: float) -> bool:
    if zone.zone_type == "resistance":
        return candle.close > zone.price_high + close_break_buffer
    if zone.zone_type == "support":
        return candle.close < zone.price_low - close_break_buffer
    return False


def false_breaks_zone(candle: CandleSlice, zone: PriceZone) -> bool:
    if zone.zone_type == "support":
        return candle.low < zone.price_low and candle.close > zone.price_high
    if zone.zone_type == "resistance":
        return candle.high > zone.price_high and candle.close < zone.price_low
    return False


def false_break_price(candle: CandleSlice, zone: PriceZone) -> float:
    return candle.low if zone.zone_type == "support" else candle.high


def refined_zone_from_false_break(
    zone: PriceZone,
    candle: CandleSlice,
    atr_value: float,
    max_width_atr_multiplier: float,
) -> PriceZone | None:
    if zone.zone_type not in {"support", "resistance"}:
        return None
    if zone.metadata.get("refined_from_false_break"):
        return None

    zone_width = max(zone.price_high - zone.price_low, 0.00001)
    max_width = max(atr_value * max_width_atr_multiplier, zone_width * 0.50, 0.00001)

    if zone.zone_type == "support":
        price_low = candle.low
        price_high = min(zone.price_low, candle.low + max_width)
        if price_high <= price_low:
            price_high = min(zone.price_high, price_low + max_width)
    else:
        price_high = candle.high
        price_low = max(zone.price_high, candle.high - max_width)
        if price_low >= price_high:
            price_low = max(zone.price_low, price_high - max_width)

    if price_high <= price_low:
        return None

    metadata = {
        "touch_count": 1,
        "touch_prices": [round(false_break_price(candle, zone), 5)],
        "refined_from_false_break": True,
        "parent_zone_id": zone.id,
        "parent_zone_low": round(zone.price_low, 5),
        "parent_zone_high": round(zone.price_high, 5),
        "parent_zone_weight": zone.effective_weight,
        "parent_zone_confidence": zone.effective_confidence,
        "false_break_time": candle.open_time,
        "false_break_price": round(false_break_price(candle, zone), 5),
        "false_break_close": round(candle.close, 5),
        "false_break_atr": round(atr_value, 6),
        "refined_width": round(price_high - price_low, 6),
        "refined_width_atr": round((price_high - price_low) / max(atr_value, 0.00001), 6),
    }
    return PriceZone(
        symbol=zone.symbol,
        timeframe=zone.timeframe,
        detector=zone.detector,
        zone_type=zone.zone_type,
        direction=zone.direction,
        price_low=round(price_low, 5),
        price_high=round(price_high, 5),
        start_time=candle.open_time,
        end_time=None,
        valid_from=candle.open_time,
        valid_until=zone.valid_until,
        invalidated_at=None,
        invalidated_by_structure_point_id=None,
        detected_at=candle.open_time,
        bot_confidence=round(max(min(zone.effective_confidence * 0.90, 1.0), 0.05), 4),
        bot_weight=round(max(min(zone.effective_weight * 0.85, 1.0), 0.05), 4),
        effective_confidence=round(max(min(zone.effective_confidence * 0.90, 1.0), 0.05), 4),
        effective_weight=round(max(min(zone.effective_weight * 0.85, 1.0), 0.05), 4),
        status="active",
        source=zone.source,
        metadata=metadata,
    )


def invalidated_before_detection(
    zone: PriceZone,
    candles: list[CandleSlice] | None,
    close_break_buffer: float,
    close_break_buffer_atr_multiplier: float,
) -> bool:
    if not candles or zone.start_time >= zone.detected_at:
        return False
    atr_value = latest_atr(candles, end_time=zone.detected_at) or max(zone.price_high - zone.price_low, 1.0)
    effective_close_break_buffer = max(close_break_buffer, atr_value * close_break_buffer_atr_multiplier)
    for candle in candles:
        if candle.open_time <= zone.start_time:
            continue
        if candle.open_time >= zone.detected_at:
            break
        if invalidates_zone(candle, zone, effective_close_break_buffer):
            return True
    return False


def candle_open(candle: CandleSlice) -> float:
    return candle.open if candle.open is not None else candle.close


def candle_body(candle: CandleSlice) -> float:
    return abs(candle.close - candle_open(candle))


def candle_range(candle: CandleSlice) -> float:
    return max(candle.high - candle.low, 0.0)


def close_position(candle: CandleSlice) -> float:
    span = candle_range(candle)
    if span <= 0:
        return 0.5
    return (candle.close - candle.low) / span


def wick_lengths(candle: CandleSlice) -> tuple[float, float]:
    body_low = min(candle_open(candle), candle.close)
    body_high = max(candle_open(candle), candle.close)
    lower_wick = max(body_low - candle.low, 0.0)
    upper_wick = max(candle.high - body_high, 0.0)
    return lower_wick, upper_wick


def body_overlaps_zone(candle: CandleSlice, zone: PriceZone) -> bool:
    body_low = min(candle_open(candle), candle.close)
    body_high = max(candle_open(candle), candle.close)
    return body_high >= zone.price_low and body_low <= zone.price_high


def close_inside_zone(candle: CandleSlice, zone: PriceZone) -> bool:
    return zone.price_low <= candle.close <= zone.price_high


def classify_touch(candle: CandleSlice, zone: PriceZone) -> str:
    if close_inside_zone(candle, zone):
        return "close_inside"
    if body_overlaps_zone(candle, zone):
        return "body_touch"
    if zone.zone_type == "support" and candle.low <= zone.price_high and candle.close > zone.price_high:
        return "wick_touch"
    if zone.zone_type == "resistance" and candle.high >= zone.price_low and candle.close < zone.price_low:
        return "wick_touch"
    return "overlap_touch"


def is_clean_rejection(candle: CandleSlice, zone: PriceZone) -> bool:
    body = max(candle_body(candle), 0.00001)
    lower_wick, upper_wick = wick_lengths(candle)
    position = close_position(candle)
    if zone.zone_type == "support":
        return candle.low <= zone.price_high and candle.close > zone.price_high and lower_wick >= body * 1.5 and position >= 0.60
    if zone.zone_type == "resistance":
        return candle.high >= zone.price_low and candle.close < zone.price_low and upper_wick >= body * 1.5 and position <= 0.40
    return False


def is_wick_absorption(candle: CandleSlice, zone: PriceZone) -> bool:
    span = candle_range(candle)
    if span <= 0:
        return False
    lower_wick, upper_wick = wick_lengths(candle)
    position = close_position(candle)
    if zone.zone_type == "support":
        return lower_wick / span >= 0.45 and position >= 0.60
    if zone.zone_type == "resistance":
        return upper_wick / span >= 0.45 and position <= 0.40
    return False


def penetration_ratio(candle: CandleSlice, zone: PriceZone) -> float:
    width = max(zone.price_high - zone.price_low, 0.00001)
    if zone.zone_type == "support":
        depth = max(zone.price_high - candle.low, 0.0)
    elif zone.zone_type == "resistance":
        depth = max(candle.high - zone.price_low, 0.0)
    else:
        depth = 0.0
    return min(max(depth / width, 0.0), 1.0)


def displacement_after_touch(candle: CandleSlice, zone: PriceZone, average_body_size: float) -> bool:
    body = candle_body(candle)
    position = close_position(candle)
    threshold = max(average_body_size * 1.3, 0.00001)
    if zone.zone_type == "support":
        return candle.close > candle_open(candle) and body >= threshold and position >= 0.70
    if zone.zone_type == "resistance":
        return candle.close < candle_open(candle) and body >= threshold and position <= 0.30
    return False


def measure_reaction_after_touch(
    zone: PriceZone,
    touch_start_index: int,
    touch_end_index: int,
    candles: list[CandleSlice],
    atr_value: float,
    reaction_window_candles: int,
    min_reaction_atr: float,
    strong_reaction_atr: float,
) -> dict[str, object]:
    touch_candles = candles[touch_start_index : touch_end_index + 1]
    future = candles[touch_end_index + 1 : touch_end_index + 1 + reaction_window_candles]
    touch_candle = touch_candles[-1]
    touch_low = min(candle.low for candle in touch_candles)
    touch_high = max(candle.high for candle in touch_candles)
    atr = max(atr_value, 0.00001)

    if zone.zone_type == "support":
        best_reaction_price = max([candle.high for candle in future] + [touch_candle.high])
        bounce_distance = max(best_reaction_price - touch_low, 0.0)
        momentum_follow_through = bool(future and future[-1].close > touch_candle.close)
    else:
        best_reaction_price = min([candle.low for candle in future] + [touch_candle.low])
        bounce_distance = max(touch_high - best_reaction_price, 0.0)
        momentum_follow_through = bool(future and future[-1].close < touch_candle.close)

    bounce_atr = bounce_distance / atr
    reaction_score = 0.0
    if bounce_atr >= strong_reaction_atr:
        reaction_score += 0.20
    elif bounce_atr >= min_reaction_atr:
        reaction_score += 0.10
    else:
        reaction_score -= 0.08

    next_candle = future[0] if future else None
    avg_body = average_body(candles, touch_end_index)
    has_displacement = bool(next_candle and displacement_after_touch(next_candle, zone, avg_body))
    if has_displacement:
        reaction_score += 0.20
    if momentum_follow_through:
        reaction_score += 0.15
    else:
        reaction_score -= 0.05

    return {
        "reaction_score": round(reaction_score, 6),
        "bounce_distance": round(bounce_distance, 5),
        "bounce_atr": round(bounce_atr, 6),
        "displacement_after_touch": has_displacement,
        "momentum_follow_through": momentum_follow_through,
        "future_candles": len(future),
    }


def clamp(value: float, low: float, high: float) -> float:
    return min(max(value, low), high)


def apply_lifecycle_to_zone(
    zone: PriceZone,
    candles: list[CandleSlice],
    close_break_buffer: float,
    recent_touch_lookback_candles: int,
    age_decay_per_100_candles: float,
    freshness_bonus: float,
    invalidation_weight_multiplier: float,
    close_break_buffer_atr_multiplier: float = 0.0,
    reaction_window_candles: int = 5,
    min_reaction_atr: float = 0.8,
    strong_reaction_atr: float = 1.5,
    recent_reaction_count: int = 3,
    max_healthy_touches: int = 3,
    weak_touch_penalty: float = 0.08,
    too_many_touches_penalty: float = 0.06,
    linger_penalty: float = 0.10,
) -> PriceZone:
    atr_value = latest_atr(candles, end_time=zone.detected_at) or latest_atr(candles) or max(zone.price_high - zone.price_low, 1.0)
    effective_close_break_buffer = max(close_break_buffer, atr_value * close_break_buffer_atr_multiplier)
    relevant = [candle for candle in candles if candle.open_time >= zone.detected_at]
    if not relevant:
        return zone

    invalidated_at: str | None = None
    invalidated_index: int | None = None
    last_touch_time: str | None = None
    in_touch = False
    touch_start_index: int | None = None
    touch_types: set[str] = set()
    max_touch_penetration = 0.0
    has_clean_rejection = False
    has_wick_absorption = False
    touch_events: list[TouchEvent] = []
    false_break_events: list[dict[str, object]] = []

    def finalize_touch(end_index: int) -> None:
        nonlocal touch_start_index, touch_types, max_touch_penetration, has_clean_rejection, has_wick_absorption, last_touch_time
        if touch_start_index is None:
            return
        duration = end_index - touch_start_index + 1
        reaction = measure_reaction_after_touch(
            zone,
            touch_start_index,
            end_index,
            candles,
            atr_value,
            reaction_window_candles,
            min_reaction_atr,
            strong_reaction_atr,
        )
        if duration <= 2 and has_clean_rejection:
            reaction["reaction_score"] = round(float(reaction["reaction_score"]) + 0.12, 6)
        if duration >= 4:
            reaction["reaction_score"] = round(float(reaction["reaction_score"]) - linger_penalty, 6)
        if has_wick_absorption:
            reaction["reaction_score"] = round(float(reaction["reaction_score"]) + 0.12, 6)

        touch_type = "mixed_touch" if len(touch_types) > 1 else next(iter(touch_types), "overlap_touch")
        touch_events.append(
            TouchEvent(
                start_time=candles[touch_start_index].open_time,
                end_time=candles[end_index].open_time,
                start_index=touch_start_index,
                end_index=end_index,
                touch_type=touch_type,
                duration_candles=duration,
                penetration_ratio=round(max_touch_penetration, 6),
                clean_rejection=has_clean_rejection,
                wick_absorption=has_wick_absorption,
                reaction_score=float(reaction["reaction_score"]),
                reaction_metrics=reaction,
            )
        )
        last_touch_time = candles[end_index].open_time
        touch_start_index = None
        touch_types = set()
        max_touch_penetration = 0.0
        has_clean_rejection = False
        has_wick_absorption = False

    for index, candle in enumerate(candles):
        if candle.open_time < zone.detected_at:
            continue

        if invalidates_zone(candle, zone, effective_close_break_buffer):
            if in_touch and touch_start_index is not None:
                finalize_touch(max(index - 1, touch_start_index))
            invalidated_at = candle.open_time
            invalidated_index = index
            break

        if false_breaks_zone(candle, zone):
            false_break_events.append(
                {
                    "time": candle.open_time,
                    "price": round(false_break_price(candle, zone), 5),
                    "close": round(candle.close, 5),
                    "atr": round(atr_value, 6),
                }
            )

        overlaps = candle_overlaps_zone(candle, zone)
        if overlaps:
            if not in_touch:
                touch_start_index = index
                touch_types = set()
                max_touch_penetration = 0.0
                has_clean_rejection = False
                has_wick_absorption = False
            touch_types.add(classify_touch(candle, zone))
            max_touch_penetration = max(max_touch_penetration, penetration_ratio(candle, zone))
            has_clean_rejection = has_clean_rejection or is_clean_rejection(candle, zone)
            has_wick_absorption = has_wick_absorption or is_wick_absorption(candle, zone)
        elif in_touch and touch_start_index is not None:
            finalize_touch(index - 1)
        in_touch = overlaps

    if invalidated_at is None and in_touch and touch_start_index is not None:
        finalize_touch(len(candles) - 1)

    latest_time = relevant[-1].open_time
    if invalidated_at is not None:
        latest_time = invalidated_at

    latest_index = invalidated_index
    if latest_index is None:
        latest_index = next((index for index, candle in reversed(list(enumerate(candles))) if candle.open_time <= latest_time), len(candles) - 1)
    detected_index = next((index for index, candle in enumerate(candles) if candle.open_time >= zone.detected_at), latest_index)
    age_candles = max(latest_index - detected_index, 0)

    last_touch_index = touch_events[-1].end_index if touch_events else None
    recent_touch = (
        last_touch_index is not None
        and latest_index - last_touch_index <= recent_touch_lookback_candles
    )

    metadata = dict(zone.metadata)
    base_touch_count = int(metadata.get("touch_count", 0))
    touch_count_after_detection = len(touch_events)
    total_touch_count = base_touch_count + touch_count_after_detection
    age_penalty = (age_candles / 100.0) * age_decay_per_100_candles

    recent_reactions = [event.reaction_score for event in touch_events[-recent_reaction_count:]]
    avg_reaction_score = sum(recent_reactions) / len(recent_reactions) if recent_reactions else 0.0
    reaction_score = clamp(avg_reaction_score, -0.20, 0.35)
    latest_reaction_score = touch_events[-1].reaction_score if touch_events else 0.0
    max_reaction_score = max([event.reaction_score for event in touch_events], default=0.0)
    weak_touch_count = sum(1 for event in touch_events if event.reaction_score < 0)
    clean_rejection_count = sum(1 for event in touch_events if event.clean_rejection)
    displacement_reaction_count = sum(1 for event in touch_events if bool(event.reaction_metrics.get("displacement_after_touch")))
    momentum_follow_through_count = sum(1 for event in touch_events if bool(event.reaction_metrics.get("momentum_follow_through")))
    max_penetration_ratio = max([event.penetration_ratio for event in touch_events], default=0.0)

    base_score = 0.25
    touch_score = min(total_touch_count * 0.06, 0.24)
    recency_score = freshness_bonus if recent_touch else 0.0
    confluence_score = 0.0
    overtest_penalty = (
        max(total_touch_count - max_healthy_touches, 0) * too_many_touches_penalty
        if total_touch_count > max_healthy_touches
        else 0.0
    )
    if latest_reaction_score < 0:
        overtest_penalty += weak_touch_penalty
    mitigation_penalty = 0.12 if max_penetration_ratio > 0.70 else 0.06 if max_penetration_ratio > 0.50 else 0.0
    false_break_penalty = 0.0
    if false_break_events:
        false_break_penalty = min(0.20 + (len(false_break_events) - 1) * 0.06, 0.40)
    invalidation_penalty = 0.70 if invalidated_at is not None else 0.0

    weight = (
        base_score
        + touch_score
        + recency_score
        + reaction_score
        + confluence_score
        - age_penalty
        - overtest_penalty
        - mitigation_penalty
        - false_break_penalty
        - invalidation_penalty
    )
    if invalidated_at is not None:
        weight *= invalidation_weight_multiplier
    weight = clamp(weight, 0.05, 1.0)

    confidence = 0.30 + min(total_touch_count * 0.08, 0.25) + min(abs(avg_reaction_score), 0.20)
    if invalidated_at is not None:
        confidence -= invalidation_penalty
    confidence = clamp(confidence, 0.05, 1.0)
    if invalidated_at is not None:
        confidence = min(confidence, 0.25)

    weight_components = {
        "base_score": round(base_score, 6),
        "touch_score": round(touch_score, 6),
        "recency_score": round(recency_score, 6),
        "reaction_score": round(reaction_score, 6),
        "confluence_score": round(confluence_score, 6),
        "age_penalty": round(age_penalty, 6),
        "overtest_penalty": round(overtest_penalty, 6),
        "mitigation_penalty": round(mitigation_penalty, 6),
        "false_break_penalty": round(false_break_penalty, 6),
        "invalidation_penalty": round(invalidation_penalty, 6),
    }

    metadata.update(
        {
            "touch_count_base": base_touch_count,
            "touch_count_after_detection": touch_count_after_detection,
            "touch_count_total": total_touch_count,
            "last_touch_time": last_touch_time,
            "last_touch_type": touch_events[-1].touch_type if touch_events else None,
            "last_reaction_score": round(latest_reaction_score, 6),
            "avg_reaction_score": round(avg_reaction_score, 6),
            "max_reaction_score": round(max_reaction_score, 6),
            "weak_touch_count": weak_touch_count,
            "clean_rejection_count": clean_rejection_count,
            "displacement_reaction_count": displacement_reaction_count,
            "momentum_follow_through_count": momentum_follow_through_count,
            "recent_touch": recent_touch,
            "age_candles": age_candles,
            "age_penalty": round(age_penalty, 6),
            "overtest_penalty": round(overtest_penalty, 6),
            "mitigation_penalty": round(mitigation_penalty, 6),
            "false_break_penalty": round(false_break_penalty, 6),
            "confluence_score": round(confluence_score, 6),
            "weight_components": weight_components,
            "false_break_count": len(false_break_events),
            "false_break_events": false_break_events[-10:],
            "trade_disabled_after_sweep": bool(false_break_events),
            "touch_events": [
                {
                    "start_time": event.start_time,
                    "end_time": event.end_time,
                    "touch_type": event.touch_type,
                    "duration_candles": event.duration_candles,
                    "penetration_ratio": event.penetration_ratio,
                    "clean_rejection": event.clean_rejection,
                    "wick_absorption": event.wick_absorption,
                    "reaction_score": round(event.reaction_score, 6),
                    "reaction_metrics": event.reaction_metrics,
                }
                for event in touch_events[-10:]
            ],
            "lifecycle_close_break_buffer": round(effective_close_break_buffer, 6),
            "lifecycle_close_break_buffer_static": close_break_buffer,
            "lifecycle_close_break_buffer_atr_multiplier": close_break_buffer_atr_multiplier,
            "lifecycle_atr": round(atr_value, 6),
            "lifecycle_latest_time": latest_time,
        }
    )
    if invalidated_at is not None:
        metadata["invalidation_reason"] = "close_beyond_zone"

    status = "invalidated" if invalidated_at is not None else "active"
    return replace(
        zone,
        end_time=invalidated_at,
        valid_until=invalidated_at,
        invalidated_at=invalidated_at,
        status=status,
        bot_confidence=round(confidence, 4),
        bot_weight=round(weight, 4),
        effective_confidence=round(confidence, 4),
        effective_weight=round(weight, 4),
        metadata=metadata,
    )


def apply_lifecycle_to_zones(
    zones: list[PriceZone],
    candles: list[CandleSlice],
    close_break_buffer: float,
    recent_touch_lookback_candles: int,
    age_decay_per_100_candles: float,
    freshness_bonus: float,
    invalidation_weight_multiplier: float,
    close_break_buffer_atr_multiplier: float = 0.0,
    reaction_window_candles: int = 5,
    min_reaction_atr: float = 0.8,
    strong_reaction_atr: float = 1.5,
    recent_reaction_count: int = 3,
    max_healthy_touches: int = 3,
    weak_touch_penalty: float = 0.08,
    too_many_touches_penalty: float = 0.06,
    linger_penalty: float = 0.10,
    false_break_refine_enabled: bool = True,
    false_break_refine_max_width_atr_multiplier: float = 0.8,
    false_break_parent_weight_multiplier: float = 0.35,
) -> list[PriceZone]:
    updated = [
        apply_lifecycle_to_zone(
            zone,
            candles,
            close_break_buffer,
            recent_touch_lookback_candles,
            age_decay_per_100_candles,
            freshness_bonus,
            invalidation_weight_multiplier,
            close_break_buffer_atr_multiplier,
            reaction_window_candles,
            min_reaction_atr,
            strong_reaction_atr,
            recent_reaction_count,
            max_healthy_touches,
            weak_touch_penalty,
            too_many_touches_penalty,
            linger_penalty,
        )
        for zone in zones
    ]
    if not false_break_refine_enabled:
        return updated

    refined_children: list[PriceZone] = []
    child_parent_ids = {
        str(zone.metadata.get("parent_zone_id"))
        for zone in updated
        if zone.metadata.get("refined_from_false_break") and zone.metadata.get("parent_zone_id")
    }
    for zone in updated:
        if zone.id in child_parent_ids:
            continue
        if zone.zone_type not in {"support", "resistance"}:
            continue
        if zone.metadata.get("refined_from_false_break"):
            continue
        false_break_events = zone.metadata.get("false_break_events")
        if not isinstance(false_break_events, list) or not false_break_events:
            continue
        event_times = {str(event.get("time")) for event in false_break_events if isinstance(event, dict)}
        for candle in candles:
            if candle.open_time not in event_times:
                continue
            atr_value = latest_atr(candles, end_time=candle.open_time) or latest_atr(candles) or max(zone.price_high - zone.price_low, 1.0)
            child = refined_zone_from_false_break(
                zone,
                candle,
                atr_value,
                false_break_refine_max_width_atr_multiplier,
            )
            if child is None:
                continue
            child = apply_lifecycle_to_zone(
                child,
                candles,
                close_break_buffer,
                recent_touch_lookback_candles,
                age_decay_per_100_candles,
                freshness_bonus,
                invalidation_weight_multiplier,
                close_break_buffer_atr_multiplier,
                reaction_window_candles,
                min_reaction_atr,
                strong_reaction_atr,
                recent_reaction_count,
                max_healthy_touches,
                weak_touch_penalty,
                too_many_touches_penalty,
                linger_penalty,
            )
            refined_children.append(child)

    if not refined_children:
        return updated

    parent_ids = {str(child.metadata.get("parent_zone_id")) for child in refined_children}
    adjusted_parents: list[PriceZone] = []
    child_ids_by_parent: dict[str, list[str]] = {}
    for child in refined_children:
        parent_id = str(child.metadata.get("parent_zone_id"))
        child_ids_by_parent.setdefault(parent_id, []).append(child.id)
    for zone in updated:
        if zone.id not in parent_ids:
            adjusted_parents.append(zone)
            continue
        metadata = dict(zone.metadata)
        metadata["refined_child_zone_ids"] = child_ids_by_parent.get(zone.id, [])
        # After a false break, the old parent SR is kept for visual context but
        # disabled for trading; the refined child around the new sweep low/high
        # is the only zone eligible for fresh reactions.
        metadata["trade_disabled_after_sweep"] = True
        metadata["false_break_parent_weight_multiplier"] = false_break_parent_weight_multiplier
        weight = clamp(zone.effective_weight * false_break_parent_weight_multiplier, 0.05, 1.0)
        confidence = clamp(zone.effective_confidence * max(false_break_parent_weight_multiplier, 0.05), 0.05, 1.0)
        adjusted_parents.append(
            replace(
                zone,
                bot_weight=round(weight, 4),
                effective_weight=round(weight, 4),
                bot_confidence=round(confidence, 4),
                effective_confidence=round(confidence, 4),
                metadata=metadata,
            )
        )

    deduped: dict[str, PriceZone] = {}
    for zone in [*adjusted_parents, *refined_children]:
        deduped[zone.id] = zone
    return list(deduped.values())


def detect_support_resistance_zones(
    swings: list[SwingPoint],
    symbol: str,
    timeframe: str,
    tolerance_pct: float,
    min_zone_width: float,
    min_touches: int,
    max_zones: int,
    atr_candles: list[CandleSlice] | None = None,
    atr_width_multiplier: float = 0.0,
    atr_value: float | None = None,
    candidate_close_break_buffer: float = 0.0,
    candidate_close_break_buffer_atr_multiplier: float = 0.0,
) -> list[PriceZone]:
    if not swings:
        return []
    latest_swing_time = max(point.event_time for point in swings)
    atr_lookup = atr_lookup_by_time(atr_candles) if atr_candles else None
    clusters = [
        *cluster_swings(swings, "high", tolerance_pct, min_zone_width, atr_candles, atr_width_multiplier, atr_value, atr_lookup),
        *cluster_swings(swings, "low", tolerance_pct, min_zone_width, atr_candles, atr_width_multiplier, atr_value, atr_lookup),
    ]
    zones = [
        zone_from_cluster(
            symbol,
            timeframe,
            cluster,
            tolerance_pct,
            min_zone_width,
            latest_swing_time,
            atr_candles,
            atr_width_multiplier,
            atr_value,
            atr_lookup,
        )
        for cluster in clusters
        if len(cluster.points) >= min_touches
    ]
    if atr_candles and (candidate_close_break_buffer > 0 or candidate_close_break_buffer_atr_multiplier > 0):
        zones = [
            zone
            for zone in zones
            if not invalidated_before_detection(
                zone,
                atr_candles,
                candidate_close_break_buffer,
                candidate_close_break_buffer_atr_multiplier,
            )
        ]
    zones.sort(key=lambda zone: (zone.effective_weight, zone.detected_at), reverse=True)
    return zones[:max_zones]


def replace_price_zones(
    conn: Connection,
    symbol: str,
    timeframe: str,
    detector: str,
    zones: list[PriceZone],
) -> int:
    protected_ids = protected_price_zone_ids(conn, symbol, timeframe, detector)
    if detector == SR_DETECTOR:
        placeholders = ", ".join("?" for _ in (SR_DETECTOR, *LEGACY_SR_DETECTORS))
        query = f"DELETE FROM price_zones WHERE symbol = ? AND timeframe = ? AND detector IN ({placeholders})"
        params: list[Any] = [symbol, timeframe, SR_DETECTOR, *LEGACY_SR_DETECTORS]
    else:
        query = "DELETE FROM price_zones WHERE symbol = ? AND timeframe = ? AND detector = ?"
        params = [symbol, timeframe, detector]
    if protected_ids:
        protected_placeholders = ", ".join("?" for _ in protected_ids)
        query += f" AND id NOT IN ({protected_placeholders})"
        params.extend(sorted(protected_ids))
    conn.execute(query, params)
    insert_zones = [zone for zone in zones if zone.id not in protected_ids]
    if insert_zones:
        conn.executemany(
            """
            INSERT INTO price_zones (
                id, symbol, timeframe, detector, zone_type, direction,
                price_low, price_high, start_time, end_time, valid_from, valid_until,
                invalidated_at, invalidated_by_structure_point_id, detected_at,
                bot_confidence, bot_weight, effective_confidence, effective_weight,
                status, source, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    zone.id,
                    zone.symbol,
                    zone.timeframe,
                    zone.detector,
                    zone.zone_type,
                    zone.direction,
                    zone.price_low,
                    zone.price_high,
                    zone.start_time,
                    zone.end_time,
                    zone.valid_from,
                    zone.valid_until,
                    zone.invalidated_at,
                    zone.invalidated_by_structure_point_id,
                    zone.detected_at,
                    zone.bot_confidence,
                    zone.bot_weight,
                    zone.effective_confidence,
                    zone.effective_weight,
                    zone.status,
                    zone.source,
                    json.dumps(zone.metadata, sort_keys=True),
                )
                for zone in insert_zones
            ],
        )
    conn.commit()
    return len(insert_zones) + len(protected_ids)


def protected_price_zone_ids(conn: Connection, symbol: str, timeframe: str, detector: str) -> set[str]:
    """Rows touched by a human must survive bot detector/materializer refreshes.

    Detector commands replace bot output wholesale. Without this guard, a bot FVG
    edited by the user becomes source=mixed, then the next detect/materialize run
    deletes that row and inserts the original bot geometry again.
    """

    if detector == SR_DETECTOR:
        placeholders = ", ".join("?" for _ in (SR_DETECTOR, *LEGACY_SR_DETECTORS))
        rows = conn.execute(
            f"""
            SELECT id, source, metadata_json
            FROM price_zones
            WHERE symbol = ? AND timeframe = ? AND detector IN ({placeholders})
            """,
            (symbol, timeframe, SR_DETECTOR, *LEGACY_SR_DETECTORS),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, source, metadata_json
            FROM price_zones
            WHERE symbol = ? AND timeframe = ? AND detector = ?
            """,
            (symbol, timeframe, detector),
        ).fetchall()

    protected: set[str] = set()
    for row in rows:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        if row["source"] != "bot" or metadata.get("human_adjusted") is True or metadata.get("human_created") is True:
            protected.add(str(row["id"]))
    return protected


def detect_and_store_support_resistance_zones(
    conn: Connection,
    symbol: str,
    timeframe: str,
    tolerance_pct: float,
    min_zone_width: float,
    min_touches: int,
    lookback_swings: int,
    max_zones: int,
    atr_width_multiplier: float = 0.0,
    close_break_buffer: float = 0.0,
    close_break_buffer_atr_multiplier: float = 0.0,
    recent_touch_lookback_candles: int = 80,
    age_decay_per_100_candles: float = 0.08,
    freshness_bonus: float = 0.15,
    invalidation_weight_multiplier: float = 0.15,
    reaction_window_candles: int = 5,
    min_reaction_atr: float = 0.8,
    strong_reaction_atr: float = 1.5,
    recent_reaction_count: int = 3,
    max_healthy_touches: int = 3,
    weak_touch_penalty: float = 0.08,
    too_many_touches_penalty: float = 0.06,
    linger_penalty: float = 0.10,
    false_break_refine_enabled: bool = True,
    false_break_refine_max_width_atr_multiplier: float = 0.8,
    false_break_parent_weight_multiplier: float = 0.35,
) -> int:
    swings = load_recent_swings(conn, symbol, timeframe, lookback_swings)
    candles = load_candle_slices(conn, symbol, timeframe)
    zones = detect_support_resistance_zones(
        swings,
        symbol,
        timeframe,
        tolerance_pct,
        min_zone_width,
        min_touches,
        max_zones,
        candles,
        atr_width_multiplier,
        candidate_close_break_buffer=close_break_buffer,
        candidate_close_break_buffer_atr_multiplier=close_break_buffer_atr_multiplier,
    )
    zones = apply_lifecycle_to_zones(
        zones,
        candles,
        close_break_buffer,
        recent_touch_lookback_candles,
        age_decay_per_100_candles,
        freshness_bonus,
        invalidation_weight_multiplier,
        close_break_buffer_atr_multiplier,
        reaction_window_candles,
        min_reaction_atr,
        strong_reaction_atr,
        recent_reaction_count,
        max_healthy_touches,
        weak_touch_penalty,
        too_many_touches_penalty,
        linger_penalty,
        false_break_refine_enabled,
        false_break_refine_max_width_atr_multiplier,
        false_break_parent_weight_multiplier,
    )
    return replace_price_zones(conn, symbol, timeframe, SR_DETECTOR, zones)


def load_price_zones(conn: Connection, symbol: str, timeframe: str, detector: str = SR_DETECTOR) -> list[PriceZone]:
    rows = conn.execute(
        """
        SELECT *
        FROM price_zones
        WHERE symbol = ? AND timeframe = ? AND detector = ?
        ORDER BY start_time
        """,
        (symbol, timeframe, detector),
    ).fetchall()
    zones: list[PriceZone] = []
    for row in rows:
        zones.append(
            PriceZone(
                symbol=row["symbol"],
                timeframe=row["timeframe"],
                detector=row["detector"],
                zone_type=row["zone_type"],
                direction=row["direction"],
                price_low=float(row["price_low"]),
                price_high=float(row["price_high"]),
                start_time=row["start_time"],
                end_time=row["end_time"],
                valid_from=row["valid_from"],
                valid_until=row["valid_until"],
                invalidated_at=row["invalidated_at"],
                invalidated_by_structure_point_id=row["invalidated_by_structure_point_id"],
                detected_at=row["detected_at"],
                bot_confidence=float(row["bot_confidence"]),
                bot_weight=float(row["bot_weight"]),
                effective_confidence=float(row["effective_confidence"]),
                effective_weight=float(row["effective_weight"]),
                status=row["status"],
                source=row["source"],
                metadata=json.loads(row["metadata_json"]),
            )
        )
    return zones


def apply_and_store_zone_lifecycle(
    conn: Connection,
    symbol: str,
    timeframe: str,
    close_break_buffer: float,
    recent_touch_lookback_candles: int,
    age_decay_per_100_candles: float,
    freshness_bonus: float,
    invalidation_weight_multiplier: float,
    close_break_buffer_atr_multiplier: float = 0.0,
    reaction_window_candles: int = 5,
    min_reaction_atr: float = 0.8,
    strong_reaction_atr: float = 1.5,
    recent_reaction_count: int = 3,
    max_healthy_touches: int = 3,
    weak_touch_penalty: float = 0.08,
    too_many_touches_penalty: float = 0.06,
    linger_penalty: float = 0.10,
    false_break_refine_enabled: bool = True,
    false_break_refine_max_width_atr_multiplier: float = 0.8,
    false_break_parent_weight_multiplier: float = 0.35,
) -> int:
    zones = load_price_zones(conn, symbol, timeframe, SR_DETECTOR)
    candles = load_candle_slices(conn, symbol, timeframe)
    updated = apply_lifecycle_to_zones(
        zones,
        candles,
        close_break_buffer,
        recent_touch_lookback_candles,
        age_decay_per_100_candles,
        freshness_bonus,
        invalidation_weight_multiplier,
        close_break_buffer_atr_multiplier,
        reaction_window_candles,
        min_reaction_atr,
        strong_reaction_atr,
        recent_reaction_count,
        max_healthy_touches,
        weak_touch_penalty,
        too_many_touches_penalty,
        linger_penalty,
        false_break_refine_enabled,
        false_break_refine_max_width_atr_multiplier,
        false_break_parent_weight_multiplier,
    )
    return replace_price_zones(conn, symbol, timeframe, SR_DETECTOR, updated)


def zone_summary(conn: Connection, symbol: str, timeframe: str | None = None, limit: int = 20) -> list[dict[str, object]]:
    clauses = ["symbol = ?"]
    params: list[object] = [symbol]
    if timeframe:
        clauses.append("timeframe = ?")
        params.append(timeframe)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT symbol, timeframe, detector, zone_type, direction, price_low, price_high,
               start_time, end_time, detected_at, effective_weight, effective_confidence,
               status, metadata_json
        FROM price_zones
        WHERE {' AND '.join(clauses)}
        ORDER BY effective_weight DESC, detected_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]
