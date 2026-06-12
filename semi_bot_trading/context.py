from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from sqlite3 import Connection


BIAS_DETECTOR = "bias_v2"
REGIME_DETECTOR = "regime_v1"
MACRO_TREND_DETECTOR = "macro_trend_v1"

BIAS_DIRECTION_THRESHOLD = 0.25
BIAS_RANGE_EFFICIENCY_NEUTRAL_MAX = 0.25
BIAS_RANGE_SCORE_MAX = 0.45


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
    metadata = metadata_from_structure(row)
    direction = metadata.get("direction")
    return str(direction) if direction in ("up", "down") else None


def metadata_from_structure(row: dict[str, object]) -> dict[str, object]:
    if isinstance(row.get("metadata"), dict):
        return dict(row["metadata"])  # type: ignore[arg-type]
    if "metadata_json" not in row:
        return {}
    return json.loads(str(row["metadata_json"]))


def recency_weight(index: int, total: int, minimum: float = 0.60, maximum: float = 1.0) -> float:
    if total <= 1:
        return maximum
    return minimum + ((maximum - minimum) * (index / (total - 1)))


def break_quality_multiplier(row: dict[str, object], atr_value: float | None) -> float:
    metadata = metadata_from_structure(row)
    if not atr_value or atr_value <= 0:
        return 1.0
    try:
        close_price = float(metadata["close_price"])
        broken_level = float(metadata["broken_level"])
    except (KeyError, TypeError, ValueError):
        return 1.0
    break_atr = abs(close_price - broken_level) / atr_value
    return min(max(0.80 + min(break_atr, 1.50) * 0.20, 0.80), 1.30)


def recent_atr(candles: list[dict[str, object]], period: int = 14) -> float | None:
    if len(candles) < 2:
        return None
    ranges = true_ranges(candles)
    window = ranges[-period:]
    return sum(window) / len(window) if window else None


def range_efficiency(candles: list[dict[str, object]]) -> float | None:
    if len(candles) < 2:
        return None
    first_close = float(candles[0]["close"])
    last_close = float(candles[-1]["close"])
    travel = sum(true_ranges(candles))
    return abs(last_close - first_close) / travel if travel else 0.0


def score_bias_from_structure(
    swings: list[dict[str, object]],
    breaks: list[dict[str, object]],
    candles: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    atr_value = recent_atr(candles or [])
    range_eff = range_efficiency(candles or [])

    swing_score = 0.0
    swing_weight_total = 0.0
    swing_contributions: list[dict[str, object]] = []
    for index, row in enumerate(swings):
        point_type = str(row["point_type"])
        direction_score = 1.0 if point_type in ("HH", "HL") else -1.0 if point_type in ("LH", "LL") else 0.0
        weight = recency_weight(index, len(swings), 0.55, 1.0)
        contribution = direction_score * weight
        swing_score += contribution
        swing_weight_total += abs(weight)
        swing_contributions.append(
            {
                "time": row["event_time"],
                "type": point_type,
                "price": row["price"],
                "weight": round(weight, 6),
                "contribution": round(contribution, 6),
            }
        )

    break_score = 0.0
    break_weight_total = 0.0
    break_contributions: list[dict[str, object]] = []
    latest_break_direction: str | None = None
    latest_break_type: str | None = None
    latest_choch_direction: str | None = None
    for index, row in enumerate(breaks):
        point_type = str(row["point_type"])
        direction = direction_from_break(row)
        direction_score = 1.0 if direction == "up" else -1.0 if direction == "down" else 0.0
        type_weight = 1.60 if point_type == "CHOCH" else 1.20
        weight = recency_weight(index, len(breaks), 0.75, 1.15) * type_weight * break_quality_multiplier(row, atr_value)
        contribution = direction_score * weight
        break_score += contribution
        break_weight_total += abs(weight)
        latest_break_direction = direction
        latest_break_type = point_type
        if point_type == "CHOCH":
            latest_choch_direction = direction
        break_contributions.append(
            {
                "time": row["event_time"],
                "type": point_type,
                "direction": direction,
                "price": row["price"],
                "weight": round(weight, 6),
                "contribution": round(contribution, 6),
                "quality_multiplier": round(break_quality_multiplier(row, atr_value), 6),
            }
        )

    raw_score = swing_score + break_score
    total_weight = max(swing_weight_total + break_weight_total, 1.0)
    normalized_score = raw_score / total_weight
    value = "neutral"
    neutral_reason: str | None = None
    if normalized_score >= BIAS_DIRECTION_THRESHOLD:
        value = "bullish"
    elif normalized_score <= -BIAS_DIRECTION_THRESHOLD:
        value = "bearish"
    else:
        neutral_reason = "structure_conflict"

    choch_neutralized = False
    if latest_break_type == "CHOCH" and latest_break_direction == "up" and value == "bearish":
        value = "neutral"
        neutral_reason = "opposing_choch_up"
        choch_neutralized = True
    elif latest_break_type == "CHOCH" and latest_break_direction == "down" and value == "bullish":
        value = "neutral"
        neutral_reason = "opposing_choch_down"
        choch_neutralized = True

    range_neutralized = False
    if (
        value != "neutral"
        and range_eff is not None
        and range_eff <= BIAS_RANGE_EFFICIENCY_NEUTRAL_MAX
        and abs(normalized_score) < BIAS_RANGE_SCORE_MAX
    ):
        value = "neutral"
        neutral_reason = "ranging_structure_weak"
        range_neutralized = True

    if value == "neutral" and neutral_reason is None:
        neutral_reason = "structure_conflict"

    if value == "neutral":
        confidence = max(0.35, min(1.0, 1.0 - abs(normalized_score)))
        if neutral_reason and neutral_reason.startswith("opposing_choch"):
            confidence = max(confidence, 0.60)
        if neutral_reason == "ranging_structure_weak":
            confidence = max(confidence, 0.65)
    else:
        confidence = min(max(abs(normalized_score), 0.35), 1.0)

    return {
        "value": value,
        "confidence": confidence,
        "swing_score": swing_score,
        "break_score": break_score,
        "raw_score": raw_score,
        "normalized_score": normalized_score,
        "total_weight": total_weight,
        "latest_break_type": latest_break_type,
        "latest_break_direction": latest_break_direction,
        "latest_choch_direction": latest_choch_direction,
        "neutral_reason": neutral_reason,
        "choch_neutralized": choch_neutralized,
        "range_neutralized": range_neutralized,
        "range_efficiency": range_eff,
        "atr": atr_value,
        "swing_contributions": swing_contributions,
        "break_contributions": break_contributions,
    }


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

    candles = load_recent_candles(conn, symbol, timeframe, limit=60, end_time=end_time)
    score = score_bias_from_structure(swings, breaks, candles)
    value = str(score["value"])
    confidence = float(score["confidence"])

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
            "version": 2,
            "recent_swings": recent_swings,
            "recent_breaks": recent_breaks,
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
            "swing_points": score["swing_contributions"],
            "break_points": score["break_contributions"],
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


def score_macro_trend(
    candles: list[dict[str, object]],
    lookback_candles: int,
    flat_threshold_atr: float,
    atr_period: int = 14,
) -> dict[str, object]:
    """Slow higher-timeframe momentum: last close vs close `lookback_candles` ago, in ATR units.

    Returns value in {"up", "down", "flat", "unknown"}. "unknown" means not enough history;
    callers should treat it like "flat" (no directional gate).
    """
    if len(candles) <= lookback_candles or lookback_candles <= 0:
        return {
            "value": "unknown",
            "confidence": 0.35,
            "momentum": None,
            "momentum_atr": None,
            "atr": None,
            "lookback_candles": lookback_candles,
            "reference_time": None,
        }
    last = candles[-1]
    reference = candles[-1 - lookback_candles]
    momentum = float(last["close"]) - float(reference["close"])
    atr_value = recent_atr(candles, period=atr_period)
    momentum_atr = momentum / atr_value if atr_value else None
    if momentum_atr is None:
        value = "up" if momentum > 0 else "down" if momentum < 0 else "flat"
    elif momentum_atr > flat_threshold_atr:
        value = "up"
    elif momentum_atr < -flat_threshold_atr:
        value = "down"
    else:
        value = "flat"
    if momentum_atr is None:
        confidence = 0.5
    else:
        # Scale: |momentum| of 10+ ATR over the lookback maps to full confidence.
        confidence = min(max(abs(momentum_atr) / 10.0, 0.35), 1.0)
    return {
        "value": value,
        "confidence": round(confidence, 4),
        "momentum": round(momentum, 5),
        "momentum_atr": round(momentum_atr, 6) if momentum_atr is not None else None,
        "atr": round(atr_value, 6) if atr_value is not None else None,
        "lookback_candles": lookback_candles,
        "reference_time": reference["open_time"],
    }


def detect_macro_trend_context(
    conn: Connection,
    symbol: str,
    timeframe: str,
    lookback_candles: int,
    flat_threshold_atr: float,
    atr_period: int = 14,
    end_time: str | None = None,
) -> MarketContext:
    candles = load_recent_candles(conn, symbol, timeframe, limit=lookback_candles + atr_period + 2, end_time=end_time)
    if not candles:
        raise ValueError(f"Cannot detect macro trend without candles for {symbol} {timeframe}")
    score = score_macro_trend(candles, lookback_candles, flat_threshold_atr, atr_period)
    value = str(score["value"])
    confidence = float(score["confidence"])
    return MarketContext(
        symbol=symbol,
        timeframe=timeframe,
        context_type="macro_trend",
        bot_value=value,
        primary_value=value,
        secondary_value=None,
        bot_confidence=round(confidence, 4),
        effective_value=value,
        effective_confidence=round(confidence, 4),
        source="bot",
        valid_from=str(candles[-1]["open_time"]),
        valid_until=None,
        status="active",
        metadata={
            "detector": MACRO_TREND_DETECTOR,
            "version": 1,
            "lookback_candles": lookback_candles,
            "flat_threshold_atr": flat_threshold_atr,
            "momentum": score["momentum"],
            "momentum_atr": score["momentum_atr"],
            "atr": score["atr"],
            "reference_time": score["reference_time"],
        },
    )


def detect_and_store_macro_trend(
    conn: Connection,
    symbol: str,
    timeframe: str,
    lookback_candles: int,
    flat_threshold_atr: float,
    atr_period: int = 14,
) -> MarketContext:
    context = detect_macro_trend_context(conn, symbol, timeframe, lookback_candles, flat_threshold_atr, atr_period)
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
