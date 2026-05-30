from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from sqlite3 import Connection


BIAS_DETECTOR = "bias_v1"
REGIME_DETECTOR = "regime_v1"


@dataclass(frozen=True)
class MarketContext:
    symbol: str
    timeframe: str
    context_type: str
    bot_value: str
    primary_value: str
    secondary_value: str | None
    bot_confidence: float
    effective_value: str
    effective_confidence: float
    source: str
    valid_from: str
    valid_until: str | None
    status: str
    metadata: dict[str, object]

    @property
    def id(self) -> str:
        raw = f"{self.symbol}|{self.timeframe}|{self.context_type}|{self.valid_from}|{self.bot_value}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def load_recent_structure(
    conn: Connection,
    symbol: str,
    timeframe: str,
    point_types: tuple[str, ...],
    limit: int,
    end_time: str | None = None,
) -> list[dict[str, object]]:
    placeholders = ", ".join("?" for _ in point_types)
    end_clause = "AND event_time <= ?" if end_time else ""
    params: tuple[object, ...] = (symbol, timeframe, *point_types, end_time, limit) if end_time else (symbol, timeframe, *point_types, limit)
    rows = conn.execute(
        f"""
        SELECT point_type, price, event_time, metadata_json
        FROM structure_points
        WHERE symbol = ? AND timeframe = ? AND point_type IN ({placeholders})
          {end_clause}
        ORDER BY event_time DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in reversed(rows)]


def direction_from_break(row: dict[str, object]) -> str | None:
    metadata = json.loads(str(row["metadata_json"]))
    direction = metadata.get("direction")
    return str(direction) if direction in ("up", "down") else None


def detect_bias_context(
    conn: Connection,
    symbol: str,
    timeframe: str,
    recent_swings: int,
    recent_breaks: int,
    end_time: str | None = None,
) -> MarketContext:
    swings = load_recent_structure(
        conn,
        symbol,
        timeframe,
        ("HH", "HL", "LH", "LL"),
        recent_swings,
        end_time=end_time,
    )
    breaks = load_recent_structure(
        conn,
        symbol,
        timeframe,
        ("BOS", "CHOCH"),
        recent_breaks,
        end_time=end_time,
    )

    swing_score = 0
    for row in swings:
        if row["point_type"] in ("HH", "HL"):
            swing_score += 1
        elif row["point_type"] in ("LH", "LL"):
            swing_score -= 1

    break_score = 0
    latest_break_direction: str | None = None
    latest_break_type: str | None = None
    for row in breaks:
        direction = direction_from_break(row)
        if direction == "up":
            break_score += 1
        elif direction == "down":
            break_score -= 1
        latest_break_direction = direction
        latest_break_type = str(row["point_type"])

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

    valid_from = str((breaks or swings)[-1]["event_time"]) if (breaks or swings) else ""
    if not valid_from:
        raise ValueError(f"Cannot detect bias without structure points for {symbol} {timeframe}")

    return MarketContext(
        symbol=symbol,
        timeframe=timeframe,
        context_type="bias",
        bot_value=value,
        primary_value=value,
        secondary_value=None,
        bot_confidence=round(confidence, 4),
        effective_value=value,
        effective_confidence=round(confidence, 4),
        source="bot",
        valid_from=valid_from,
        valid_until=None,
        status="active",
        metadata={
            "detector": BIAS_DETECTOR,
            "recent_swings": recent_swings,
            "recent_breaks": recent_breaks,
            "swing_score": swing_score,
            "break_score": break_score,
            "raw_score": raw_score,
            "latest_break_type": latest_break_type,
            "latest_break_direction": latest_break_direction,
            "swing_points": [
                {
                    "time": row["event_time"],
                    "type": row["point_type"],
                    "price": row["price"],
                }
                for row in swings
            ],
            "break_points": [
                {
                    "time": row["event_time"],
                    "type": row["point_type"],
                    "direction": direction_from_break(row),
                    "price": row["price"],
                }
                for row in breaks
            ],
        },
    )


def replace_active_context(conn: Connection, context: MarketContext) -> None:
    conn.execute(
        """
        UPDATE market_contexts
        SET status = 'superseded', updated_at = CURRENT_TIMESTAMP
        WHERE symbol = ? AND timeframe = ? AND context_type = ? AND source = 'bot' AND status = 'active'
        """,
        (context.symbol, context.timeframe, context.context_type),
    )
    conn.execute(
        """
        INSERT INTO market_contexts (
            id, symbol, timeframe, context_type, bot_value, primary_value, secondary_value,
            bot_confidence, effective_value, effective_confidence, source,
            valid_from, valid_until, status, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            bot_value = excluded.bot_value,
            primary_value = excluded.primary_value,
            secondary_value = excluded.secondary_value,
            bot_confidence = excluded.bot_confidence,
            effective_value = excluded.effective_value,
            effective_confidence = excluded.effective_confidence,
            source = excluded.source,
            valid_until = excluded.valid_until,
            status = excluded.status,
            metadata_json = excluded.metadata_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            context.id,
            context.symbol,
            context.timeframe,
            context.context_type,
            context.bot_value,
            context.primary_value,
            context.secondary_value,
            context.bot_confidence,
            context.effective_value,
            context.effective_confidence,
            context.source,
            context.valid_from,
            context.valid_until,
            context.status,
            json.dumps(context.metadata, sort_keys=True),
        ),
    )
    conn.commit()


def detect_and_store_bias(
    conn: Connection,
    symbol: str,
    timeframe: str,
    recent_swings: int,
    recent_breaks: int,
) -> MarketContext:
    context = detect_bias_context(conn, symbol, timeframe, recent_swings, recent_breaks)
    replace_active_context(conn, context)
    return context


def load_recent_candles(conn: Connection, symbol: str, timeframe: str, limit: int, end_time: str | None = None) -> list[dict[str, object]]:
    clauses = ["symbol = ?", "timeframe = ?"]
    params: list[object] = [symbol, timeframe]
    if end_time:
        clauses.append("open_time <= ?")
        params.append(end_time)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT open_time, open, high, low, close
        FROM candles
        WHERE {' AND '.join(clauses)}
        ORDER BY open_time DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in reversed(rows)]


def true_ranges(candles: list[dict[str, object]]) -> list[float]:
    ranges: list[float] = []
    previous_close: float | None = None
    for candle in candles:
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])
        if previous_close is None:
            ranges.append(high - low)
        else:
            ranges.append(
                max(
                    high - low,
                    abs(high - previous_close),
                    abs(low - previous_close),
                )
            )
        previous_close = close
    return ranges


def rolling_average(values: list[float], period: int) -> list[float]:
    if period < 1:
        raise ValueError("period must be >= 1")
    if len(values) < period:
        return []
    return [
        sum(values[index - period : index]) / period
        for index in range(period, len(values) + 1)
    ]


def percentile_rank(values: list[float], value: float) -> float:
    if not values:
        return 0.5
    below_or_equal = sum(1 for item in values if item <= value)
    return below_or_equal / len(values)


def load_breaks_since(conn: Connection, symbol: str, timeframe: str, start_time: str, end_time: str | None = None) -> list[dict[str, object]]:
    end_clause = "AND event_time <= ?" if end_time else ""
    params: tuple[object, ...] = (symbol, timeframe, start_time, end_time) if end_time else (symbol, timeframe, start_time)
    rows = conn.execute(
        f"""
        SELECT point_type, event_time, metadata_json
        FROM structure_points
        WHERE symbol = ? AND timeframe = ?
          AND detector = 'break_v1'
          AND event_time >= ?
          {end_clause}
        ORDER BY event_time
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def detect_regime_context(
    conn: Connection,
    symbol: str,
    timeframe: str,
    atr_period: int,
    lookback: int,
    atr_high_percentile: float,
    atr_low_percentile: float,
    expansion_atr_ratio: float,
    contraction_atr_ratio: float,
    trend_break_ratio: float,
    trend_min_bos: int,
    range_efficiency_max: float,
    end_time: str | None = None,
) -> MarketContext:
    candles = load_recent_candles(conn, symbol, timeframe, limit=lookback + atr_period + 1, end_time=end_time)
    if len(candles) < atr_period + 2:
        raise ValueError(f"Not enough candles to detect regime for {symbol} {timeframe}")

    recent = candles[-lookback:] if len(candles) >= lookback else candles
    ranges = true_ranges(candles)
    atr_values = rolling_average(ranges, atr_period)
    if not atr_values:
        raise ValueError(f"Not enough ATR values to detect regime for {symbol} {timeframe}")

    recent_atrs = atr_values[-len(recent) :]
    current_atr = recent_atrs[-1]
    average_atr = sum(recent_atrs) / len(recent_atrs)
    atr_ratio = current_atr / average_atr if average_atr else 1.0
    atr_percentile = percentile_rank(recent_atrs, current_atr)

    first_close = float(recent[0]["close"])
    last_close = float(recent[-1]["close"])
    total_travel = sum(true_ranges(recent))
    range_efficiency = abs(last_close - first_close) / total_travel if total_travel else 0.0

    start_time = str(recent[0]["open_time"])
    breaks = load_breaks_since(conn, symbol, timeframe, start_time, end_time=end_time)
    bos_breaks = [row for row in breaks if row["point_type"] == "BOS"]
    directions = [direction_from_break(row) for row in bos_breaks]
    up_count = sum(1 for direction in directions if direction == "up")
    down_count = sum(1 for direction in directions if direction == "down")
    directional_count = max(up_count, down_count)
    directional_ratio = directional_count / len(bos_breaks) if bos_breaks else 0.0

    if len(bos_breaks) >= trend_min_bos and directional_ratio >= trend_break_ratio:
        primary = "trending"
        primary_reason = "directional_bos_density"
    elif range_efficiency <= range_efficiency_max:
        primary = "ranging"
        primary_reason = "low_range_efficiency"
    else:
        primary = "trending" if range_efficiency > range_efficiency_max else "ranging"
        primary_reason = "range_efficiency_fallback"

    overlays: list[str] = []
    if atr_ratio >= expansion_atr_ratio:
        overlays.append("expansion")
    elif atr_ratio <= contraction_atr_ratio:
        overlays.append("contraction")

    if atr_percentile >= atr_high_percentile:
        overlays.append("high_volatility")
    elif atr_percentile <= atr_low_percentile:
        overlays.append("low_volatility")

    if primary == "trending":
        confidence = max(directional_ratio, min(range_efficiency / max(range_efficiency_max, 0.0001), 1.0))
    else:
        confidence = min(1.0 - range_efficiency, 1.0)

    valid_from = str(recent[-1]["open_time"])
    return MarketContext(
        symbol=symbol,
        timeframe=timeframe,
        context_type="regime",
        bot_value=primary,
        primary_value=primary,
        secondary_value=",".join(overlays) if overlays else None,
        bot_confidence=round(confidence, 4),
        effective_value=primary,
        effective_confidence=round(confidence, 4),
        source="bot",
        valid_from=valid_from,
        valid_until=None,
        status="active",
        metadata={
            "detector": REGIME_DETECTOR,
            "primary": primary,
            "primary_reason": primary_reason,
            "overlays": overlays,
            "atr_period": atr_period,
            "lookback": lookback,
            "current_atr": round(current_atr, 6),
            "average_atr": round(average_atr, 6),
            "atr_ratio": round(atr_ratio, 6),
            "atr_percentile": round(atr_percentile, 6),
            "range_efficiency": round(range_efficiency, 6),
            "bos_count": len(bos_breaks),
            "bos_up_count": up_count,
            "bos_down_count": down_count,
            "directional_ratio": round(directional_ratio, 6),
            "start_time": start_time,
        },
    )


def detect_and_store_regime(
    conn: Connection,
    symbol: str,
    timeframe: str,
    atr_period: int,
    lookback: int,
    atr_high_percentile: float,
    atr_low_percentile: float,
    expansion_atr_ratio: float,
    contraction_atr_ratio: float,
    trend_break_ratio: float,
    trend_min_bos: int,
    range_efficiency_max: float,
) -> MarketContext:
    context = detect_regime_context(
        conn,
        symbol,
        timeframe,
        atr_period,
        lookback,
        atr_high_percentile,
        atr_low_percentile,
        expansion_atr_ratio,
        contraction_atr_ratio,
        trend_break_ratio,
        trend_min_bos,
        range_efficiency_max,
    )
    replace_active_context(conn, context)
    return context


def latest_contexts(
    conn: Connection,
    symbol: str,
    timeframe: str | None = None,
    context_type: str | None = None,
) -> list[dict[str, object]]:
    clauses = ["symbol = ?"]
    params: list[object] = [symbol]
    if timeframe:
        clauses.append("timeframe = ?")
        params.append(timeframe)
    if context_type:
        clauses.append("context_type = ?")
        params.append(context_type)
    rows = conn.execute(
        f"""
        SELECT symbol, timeframe, context_type, effective_value, effective_confidence,
               source, valid_from, status, metadata_json
        FROM market_contexts
        WHERE {' AND '.join(clauses)}
        ORDER BY created_at DESC
        LIMIT 20
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]
