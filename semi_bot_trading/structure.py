from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from sqlite3 import Connection


SWING_DETECTOR = "swing_v1"
BREAK_DETECTOR = "break_v1"


@dataclass(frozen=True)
class CandleView:
    open_time: str
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class StructurePoint:
    symbol: str
    timeframe: str
    detector: str
    status: str
    point_type: str
    price: float
    event_time: str
    confidence: float
    related_zone_ids: list[str]
    metadata: dict[str, object]

    @property
    def id(self) -> str:
        raw = (
            f"{self.symbol}|{self.timeframe}|{self.detector}|"
            f"{self.point_type}|{self.event_time}|{self.price:.5f}"
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SwingLevel:
    id: str
    point_type: str
    swing_type: str
    price: float
    event_time: str
    confirmed_at: str


def load_candle_views(conn: Connection, symbol: str, timeframe: str) -> list[CandleView]:
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
        CandleView(
            open_time=row["open_time"],
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for row in rows
    ]


def classify_high(price: float, previous_high: float | None, tolerance: float) -> str:
    if previous_high is None:
        return "swing_high"
    if price > previous_high + tolerance:
        return "HH"
    if price < previous_high - tolerance:
        return "LH"
    return "swing_high"


def classify_low(price: float, previous_low: float | None, tolerance: float) -> str:
    if previous_low is None:
        return "swing_low"
    if price > previous_low + tolerance:
        return "HL"
    if price < previous_low - tolerance:
        return "LL"
    return "swing_low"


def is_pivot_high(candles: list[CandleView], index: int, window: int, tolerance: float) -> bool:
    price = candles[index].high
    for offset in range(index - window, index + window + 1):
        if offset == index:
            continue
        if price <= candles[offset].high + tolerance:
            return False
    return True


def is_pivot_low(candles: list[CandleView], index: int, window: int, tolerance: float) -> bool:
    price = candles[index].low
    for offset in range(index - window, index + window + 1):
        if offset == index:
            continue
        if price >= candles[offset].low - tolerance:
            return False
    return True


def detect_swing_structure(
    candles: list[CandleView],
    symbol: str,
    timeframe: str,
    window: int,
    tolerance: float = 0.0,
) -> list[StructurePoint]:
    if window < 1:
        raise ValueError("window must be >= 1")
    if len(candles) < (window * 2) + 1:
        return []

    points: list[StructurePoint] = []
    previous_high: float | None = None
    previous_low: float | None = None

    for index in range(window, len(candles) - window):
        candle = candles[index]
        high_pivot = is_pivot_high(candles, index, window, tolerance)
        low_pivot = is_pivot_low(candles, index, window, tolerance)

        if high_pivot:
            point_type = classify_high(candle.high, previous_high, tolerance)
            label = "EQH" if point_type == "swing_high" and previous_high is not None else point_type
            points.append(
                StructurePoint(
                    symbol=symbol,
                    timeframe=timeframe,
                    detector=SWING_DETECTOR,
                    status="confirmed",
                    point_type=point_type,
                    price=candle.high,
                    event_time=candle.open_time,
                    confidence=1.0,
                    related_zone_ids=[],
                    metadata={
                        "swing_type": "high",
                        "structure_label": label,
                        "window": window,
                        "tolerance": tolerance,
                        "candle_index": index,
                        "confirmed_at": candles[index + window].open_time,
                        "previous_swing_high": previous_high,
                    },
                )
            )
            previous_high = candle.high

        if low_pivot:
            point_type = classify_low(candle.low, previous_low, tolerance)
            label = "EQL" if point_type == "swing_low" and previous_low is not None else point_type
            points.append(
                StructurePoint(
                    symbol=symbol,
                    timeframe=timeframe,
                    detector=SWING_DETECTOR,
                    status="confirmed",
                    point_type=point_type,
                    price=candle.low,
                    event_time=candle.open_time,
                    confidence=1.0,
                    related_zone_ids=[],
                    metadata={
                        "swing_type": "low",
                        "structure_label": label,
                        "window": window,
                        "tolerance": tolerance,
                        "candle_index": index,
                        "confirmed_at": candles[index + window].open_time,
                        "previous_swing_low": previous_low,
                    },
                )
            )
            previous_low = candle.low

    return points


def replace_structure_points(
    conn: Connection,
    symbol: str,
    timeframe: str,
    detector: str,
    points: list[StructurePoint],
) -> int:
    conn.execute(
        "DELETE FROM structure_points WHERE symbol = ? AND timeframe = ? AND detector = ?",
        (symbol, timeframe, detector),
    )
    if points:
        conn.executemany(
            """
            INSERT INTO structure_points (
                id, symbol, timeframe, detector, status, point_type, price, event_time,
                confidence, related_zone_ids_json, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    point.id,
                    point.symbol,
                    point.timeframe,
                    point.detector,
                    point.status,
                    point.point_type,
                    point.price,
                    point.event_time,
                    point.confidence,
                    json.dumps(point.related_zone_ids),
                    json.dumps(point.metadata, sort_keys=True),
                )
                for point in points
            ],
        )
    conn.commit()
    return len(points)


def detect_and_store_swing_structure(
    conn: Connection,
    symbol: str,
    timeframe: str,
    window: int,
    tolerance: float = 0.0,
) -> int:
    candles = load_candle_views(conn, symbol, timeframe)
    points = detect_swing_structure(candles, symbol, timeframe, window, tolerance)
    return replace_structure_points(conn, symbol, timeframe, SWING_DETECTOR, points)


def load_swing_levels(conn: Connection, symbol: str, timeframe: str) -> list[SwingLevel]:
    rows = conn.execute(
        """
        SELECT id, point_type, price, event_time, metadata_json
        FROM structure_points
        WHERE symbol = ? AND timeframe = ? AND detector = ?
        ORDER BY event_time
        """,
        (symbol, timeframe, SWING_DETECTOR),
    ).fetchall()
    levels: list[SwingLevel] = []
    for row in rows:
        metadata = json.loads(row["metadata_json"])
        swing_type = metadata.get("swing_type")
        if swing_type not in ("high", "low"):
            continue
        levels.append(
            SwingLevel(
                id=row["id"],
                point_type=row["point_type"],
                swing_type=str(swing_type),
                price=float(row["price"]),
                event_time=row["event_time"],
                confirmed_at=str(metadata.get("confirmed_at", row["event_time"])),
            )
        )
    return sorted(levels, key=lambda item: (item.confirmed_at, item.event_time))


def break_point_type(current_direction: str | None, break_direction: str) -> str:
    if current_direction is None or current_direction == break_direction:
        return "BOS"
    return "CHOCH"


def detect_break_structure(
    candles: list[CandleView],
    swings: list[SwingLevel],
    symbol: str,
    timeframe: str,
    close_break_buffer: float = 0.0,
) -> list[StructurePoint]:
    points: list[StructurePoint] = []
    swing_index = 0
    active_high: SwingLevel | None = None
    active_low: SwingLevel | None = None
    current_direction: str | None = None
    broken_swing_ids: set[str] = set()

    for candle in candles:
        while swing_index < len(swings) and swings[swing_index].confirmed_at <= candle.open_time:
            swing = swings[swing_index]
            if swing.id not in broken_swing_ids:
                if swing.swing_type == "high":
                    active_high = swing
                else:
                    active_low = swing
            swing_index += 1

        if active_high and candle.close > active_high.price + close_break_buffer:
            point_type = break_point_type(current_direction, "up")
            previous_direction = current_direction
            current_direction = "up"
            broken_swing_ids.add(active_high.id)
            points.append(
                StructurePoint(
                    symbol=symbol,
                    timeframe=timeframe,
                    detector=BREAK_DETECTOR,
                    status="confirmed",
                    point_type=point_type,
                    price=active_high.price,
                    event_time=candle.open_time,
                    confidence=1.0,
                    related_zone_ids=[],
                    metadata={
                        "direction": "up",
                        "broken_swing_id": active_high.id,
                        "broken_swing_type": active_high.point_type,
                        "broken_swing_time": active_high.event_time,
                        "broken_level": active_high.price,
                        "close_price": candle.close,
                        "previous_direction": previous_direction,
                        "close_break_buffer": close_break_buffer,
                    },
                )
            )
            active_high = None

        if active_low and candle.close < active_low.price - close_break_buffer:
            point_type = break_point_type(current_direction, "down")
            previous_direction = current_direction
            current_direction = "down"
            broken_swing_ids.add(active_low.id)
            points.append(
                StructurePoint(
                    symbol=symbol,
                    timeframe=timeframe,
                    detector=BREAK_DETECTOR,
                    status="confirmed",
                    point_type=point_type,
                    price=active_low.price,
                    event_time=candle.open_time,
                    confidence=1.0,
                    related_zone_ids=[],
                    metadata={
                        "direction": "down",
                        "broken_swing_id": active_low.id,
                        "broken_swing_type": active_low.point_type,
                        "broken_swing_time": active_low.event_time,
                        "broken_level": active_low.price,
                        "close_price": candle.close,
                        "previous_direction": previous_direction,
                        "close_break_buffer": close_break_buffer,
                    },
                )
            )
            active_low = None

    return points


def detect_and_store_break_structure(
    conn: Connection,
    symbol: str,
    timeframe: str,
    close_break_buffer: float = 0.0,
) -> int:
    candles = load_candle_views(conn, symbol, timeframe)
    swings = load_swing_levels(conn, symbol, timeframe)
    points = detect_break_structure(
        candles,
        swings,
        symbol,
        timeframe,
        close_break_buffer=close_break_buffer,
    )
    return replace_structure_points(conn, symbol, timeframe, BREAK_DETECTOR, points)


def structure_summary(conn: Connection, symbol: str | None = None, timeframe: str | None = None) -> list[dict[str, object]]:
    clauses: list[str] = []
    params: list[object] = []
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol)
    if timeframe:
        clauses.append("timeframe = ?")
        params.append(timeframe)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT symbol, timeframe, detector, point_type, COUNT(*) AS point_count,
               MIN(event_time) AS first_event_time, MAX(event_time) AS last_event_time
        FROM structure_points
        {where}
        GROUP BY symbol, timeframe, detector, point_type
        ORDER BY symbol, timeframe, detector, point_type
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def latest_structure_points(
    conn: Connection,
    symbol: str,
    timeframe: str,
    limit: int = 20,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT event_time, point_type, price, metadata_json
        FROM structure_points
        WHERE symbol = ? AND timeframe = ?
        ORDER BY event_time DESC
        LIMIT ?
        """,
        (symbol, timeframe, limit),
    ).fetchall()
    return [dict(row) for row in rows]
