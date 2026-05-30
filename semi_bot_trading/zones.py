from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from sqlite3 import Connection


SR_DETECTOR = "sr_v1"


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
) -> list[ZoneCluster]:
    clusters: list[ZoneCluster] = []
    candidates = sorted(
        [swing for swing in swings if swing.swing_type == swing_type],
        key=lambda item: item.price,
    )
    for swing in candidates:
        matched: ZoneCluster | None = None
        for cluster in clusters:
            tolerance = max(cluster.center * tolerance_pct, min_zone_width)
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
) -> PriceZone:
    prices = [point.price for point in cluster.points]
    center = cluster.center
    half_width = max(center * tolerance_pct, min_zone_width)
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
        valid_from=cluster.first_time,
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
            "tolerance_pct": tolerance_pct,
            "min_zone_width": min_zone_width,
            "swing_point_ids": [point.id for point in cluster.points],
            "swing_point_times": [point.event_time for point in cluster.points],
            "swing_point_prices": prices,
        },
    )


def load_candle_slices(conn: Connection, symbol: str, timeframe: str) -> list[CandleSlice]:
    rows = conn.execute(
        """
        SELECT open_time, high, low, close
        FROM candles
        WHERE symbol = ? AND timeframe = ?
        ORDER BY open_time
        """,
        (symbol, timeframe),
    ).fetchall()
    return [
        CandleSlice(
            open_time=row["open_time"],
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for row in rows
    ]


def candle_overlaps_zone(candle: CandleSlice, zone: PriceZone) -> bool:
    return candle.high >= zone.price_low and candle.low <= zone.price_high


def invalidates_zone(candle: CandleSlice, zone: PriceZone, close_break_buffer: float) -> bool:
    if zone.zone_type == "resistance":
        return candle.close > zone.price_high + close_break_buffer
    if zone.zone_type == "support":
        return candle.close < zone.price_low - close_break_buffer
    return False


def apply_lifecycle_to_zone(
    zone: PriceZone,
    candles: list[CandleSlice],
    close_break_buffer: float,
    recent_touch_lookback_candles: int,
    age_decay_per_100_candles: float,
    freshness_bonus: float,
    invalidation_weight_multiplier: float,
) -> PriceZone:
    relevant = [candle for candle in candles if candle.open_time >= zone.detected_at]
    if not relevant:
        return zone

    invalidated_at: str | None = None
    touch_count_after_detection = 0
    last_touch_time: str | None = None
    in_touch = False

    for candle in relevant:
        if invalidates_zone(candle, zone, close_break_buffer):
            invalidated_at = candle.open_time
            break

        overlaps = candle_overlaps_zone(candle, zone)
        if overlaps and not in_touch:
            touch_count_after_detection += 1
            last_touch_time = candle.open_time
        in_touch = overlaps

    latest_time = relevant[-1].open_time
    if invalidated_at is not None:
        latest_time = invalidated_at

    latest_index = next((index for index, candle in reversed(list(enumerate(candles))) if candle.open_time <= latest_time), len(candles) - 1)
    detected_index = next((index for index, candle in enumerate(candles) if candle.open_time >= zone.detected_at), latest_index)
    age_candles = max(latest_index - detected_index, 0)

    last_touch_index: int | None = None
    if last_touch_time:
        last_touch_index = next((index for index, candle in enumerate(candles) if candle.open_time == last_touch_time), None)
    recent_touch = (
        last_touch_index is not None
        and latest_index - last_touch_index <= recent_touch_lookback_candles
    )

    metadata = dict(zone.metadata)
    base_touch_count = int(metadata.get("touch_count", 0))
    total_touch_count = base_touch_count + touch_count_after_detection
    age_penalty = (age_candles / 100.0) * age_decay_per_100_candles
    touch_score = min(total_touch_count * 0.08, 0.45)
    weight = 0.30 + touch_score - age_penalty
    if recent_touch:
        weight += freshness_bonus
    if invalidated_at is not None:
        weight *= invalidation_weight_multiplier
    weight = min(max(weight, 0.05), 1.0)

    confidence = min(0.35 + total_touch_count * 0.08, 1.0)
    if invalidated_at is not None:
        confidence = min(confidence, 0.25)

    metadata.update(
        {
            "touch_count_base": base_touch_count,
            "touch_count_after_detection": touch_count_after_detection,
            "touch_count_total": total_touch_count,
            "last_touch_time": last_touch_time,
            "recent_touch": recent_touch,
            "age_candles": age_candles,
            "age_penalty": round(age_penalty, 6),
            "lifecycle_close_break_buffer": close_break_buffer,
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
) -> list[PriceZone]:
    return [
        apply_lifecycle_to_zone(
            zone,
            candles,
            close_break_buffer,
            recent_touch_lookback_candles,
            age_decay_per_100_candles,
            freshness_bonus,
            invalidation_weight_multiplier,
        )
        for zone in zones
    ]


def detect_support_resistance_zones(
    swings: list[SwingPoint],
    symbol: str,
    timeframe: str,
    tolerance_pct: float,
    min_zone_width: float,
    min_touches: int,
    max_zones: int,
) -> list[PriceZone]:
    if not swings:
        return []
    latest_swing_time = max(point.event_time for point in swings)
    clusters = [
        *cluster_swings(swings, "high", tolerance_pct, min_zone_width),
        *cluster_swings(swings, "low", tolerance_pct, min_zone_width),
    ]
    zones = [
        zone_from_cluster(symbol, timeframe, cluster, tolerance_pct, min_zone_width, latest_swing_time)
        for cluster in clusters
        if len(cluster.points) >= min_touches
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
    conn.execute(
        "DELETE FROM price_zones WHERE symbol = ? AND timeframe = ? AND detector = ?",
        (symbol, timeframe, detector),
    )
    if zones:
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
                for zone in zones
            ],
        )
    conn.commit()
    return len(zones)


def detect_and_store_support_resistance_zones(
    conn: Connection,
    symbol: str,
    timeframe: str,
    tolerance_pct: float,
    min_zone_width: float,
    min_touches: int,
    lookback_swings: int,
    max_zones: int,
    close_break_buffer: float = 0.0,
    recent_touch_lookback_candles: int = 80,
    age_decay_per_100_candles: float = 0.08,
    freshness_bonus: float = 0.15,
    invalidation_weight_multiplier: float = 0.15,
) -> int:
    swings = load_recent_swings(conn, symbol, timeframe, lookback_swings)
    zones = detect_support_resistance_zones(
        swings,
        symbol,
        timeframe,
        tolerance_pct,
        min_zone_width,
        min_touches,
        max_zones,
    )
    candles = load_candle_slices(conn, symbol, timeframe)
    zones = apply_lifecycle_to_zones(
        zones,
        candles,
        close_break_buffer,
        recent_touch_lookback_candles,
        age_decay_per_100_candles,
        freshness_bonus,
        invalidation_weight_multiplier,
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
