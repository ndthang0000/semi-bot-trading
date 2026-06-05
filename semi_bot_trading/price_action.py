from __future__ import annotations

from sqlite3 import Connection

from .structure import StructurePoint, replace_structure_points
from .zones import CandleSlice, candle_body, candle_range, load_candle_slices, true_range


PRICE_ACTION_DETECTOR = "price_action_v1"


def detect_price_action_patterns(
    candles: list[CandleSlice],
    symbol: str,
    timeframe: str,
    atr_period: int = 14,
    displacement_atr_multiplier: float = 1.5,
    displacement_body_ratio: float = 0.60,
    pinbar_wick_body_ratio: float = 2.0,
    pinbar_min_wick_ratio: float = 0.55,
    engulfing_min_body_ratio: float = 0.45,
    marubozu_min_body_ratio: float = 0.75,
    star_large_body_ratio: float = 0.45,
    star_small_body_ratio: float = 0.35,
) -> list[StructurePoint]:
    points: list[StructurePoint] = []
    atr_before = atr_before_candle(candles, atr_period)
    for index, candle in enumerate(candles):
        points.extend(
            detect_single_candle_patterns(
                candles,
                index,
                atr_before[index],
                symbol,
                timeframe,
                displacement_atr_multiplier,
                displacement_body_ratio,
                pinbar_wick_body_ratio,
                pinbar_min_wick_ratio,
                marubozu_min_body_ratio,
            )
        )
        if index >= 1:
            engulfing = detect_engulfing_pattern(
                candles[index - 1],
                candle,
                symbol,
                timeframe,
                engulfing_min_body_ratio,
            )
            if engulfing:
                points.append(engulfing)
        if index >= 2:
            star = detect_star_pattern(
                candles[index - 2],
                candles[index - 1],
                candle,
                symbol,
                timeframe,
                star_large_body_ratio,
                star_small_body_ratio,
            )
            if star:
                points.append(star)

    points.sort(key=lambda point: (point.event_time, point.detector, point.point_type))
    return points


def detect_single_candle_patterns(
    candles: list[CandleSlice],
    index: int,
    atr_value: float | None,
    symbol: str,
    timeframe: str,
    displacement_atr_multiplier: float,
    displacement_body_ratio: float,
    pinbar_wick_body_ratio: float,
    pinbar_min_wick_ratio: float,
    marubozu_min_body_ratio: float,
) -> list[StructurePoint]:
    candle = candles[index]
    metrics = candle_metrics(candle)
    if metrics is None:
        return []

    points: list[StructurePoint] = []
    pinbar = detect_pinbar(candle, metrics, symbol, timeframe, pinbar_wick_body_ratio, pinbar_min_wick_ratio)
    if pinbar:
        points.append(pinbar)

    marubozu = detect_marubozu(candle, metrics, symbol, timeframe, marubozu_min_body_ratio)
    if marubozu:
        points.append(marubozu)

    displacement = detect_displacement_candle(
        candles[index],
        metrics,
        atr_value,
        symbol,
        timeframe,
        displacement_atr_multiplier,
        displacement_body_ratio,
    )
    if displacement:
        points.append(displacement)

    return points


def detect_pinbar(
    candle: CandleSlice,
    metrics: dict[str, float],
    symbol: str,
    timeframe: str,
    wick_body_ratio: float,
    min_wick_ratio: float,
) -> StructurePoint | None:
    if metrics["body"] <= 0:
        return None
    if (
        metrics["lower_wick"] >= metrics["body"] * wick_body_ratio
        and metrics["lower_wick_ratio"] >= min_wick_ratio
        and metrics["close_position"] >= 0.55
    ):
        confidence = min(0.45 + metrics["lower_wick_ratio"] * 0.45 + metrics["body_ratio"] * 0.10, 0.92)
        return price_action_point(
            symbol,
            timeframe,
            "pinbar_bullish",
            "up",
            candle.close,
            candle.open_time,
            confidence,
            {**metrics, "pattern": "pinbar", "pinbar_wick": "lower"},
        )
    if (
        metrics["upper_wick"] >= metrics["body"] * wick_body_ratio
        and metrics["upper_wick_ratio"] >= min_wick_ratio
        and metrics["close_position"] <= 0.45
    ):
        confidence = min(0.45 + metrics["upper_wick_ratio"] * 0.45 + metrics["body_ratio"] * 0.10, 0.92)
        return price_action_point(
            symbol,
            timeframe,
            "pinbar_bearish",
            "down",
            candle.close,
            candle.open_time,
            confidence,
            {**metrics, "pattern": "pinbar", "pinbar_wick": "upper"},
        )
    return None


def detect_engulfing_pattern(
    previous: CandleSlice,
    current: CandleSlice,
    symbol: str,
    timeframe: str,
    min_body_ratio: float,
) -> StructurePoint | None:
    previous_metrics = candle_metrics(previous)
    current_metrics = candle_metrics(current)
    if previous_metrics is None or current_metrics is None:
        return None
    if current_metrics["body_ratio"] < min_body_ratio:
        return None
    previous_low, previous_high = body_bounds(previous)
    current_low, current_high = body_bounds(current)
    body_engulfs = current_low <= previous_low and current_high >= previous_high
    if not body_engulfs:
        return None

    if is_bearish(previous) and is_bullish(current):
        confidence = min(0.50 + current_metrics["body_ratio"] * 0.25 + min(current_metrics["body"] / max(previous_metrics["body"], 0.00001), 2.0) * 0.08, 0.92)
        return price_action_point(
            symbol,
            timeframe,
            "engulfing_bullish",
            "up",
            current.close,
            current.open_time,
            confidence,
            {
                **current_metrics,
                "pattern": "engulfing",
                "previous_time": previous.open_time,
                "previous_body": round(previous_metrics["body"], 5),
            },
        )
    if is_bullish(previous) and is_bearish(current):
        confidence = min(0.50 + current_metrics["body_ratio"] * 0.25 + min(current_metrics["body"] / max(previous_metrics["body"], 0.00001), 2.0) * 0.08, 0.92)
        return price_action_point(
            symbol,
            timeframe,
            "engulfing_bearish",
            "down",
            current.close,
            current.open_time,
            confidence,
            {
                **current_metrics,
                "pattern": "engulfing",
                "previous_time": previous.open_time,
                "previous_body": round(previous_metrics["body"], 5),
            },
        )
    return None


def detect_marubozu(
    candle: CandleSlice,
    metrics: dict[str, float],
    symbol: str,
    timeframe: str,
    min_body_ratio: float,
) -> StructurePoint | None:
    if metrics["body_ratio"] < min_body_ratio:
        return None
    if metrics["upper_wick_ratio"] > 0.15 or metrics["lower_wick_ratio"] > 0.15:
        return None
    direction = "up" if is_bullish(candle) else "down"
    point_type = "marubozu_bullish" if direction == "up" else "marubozu_bearish"
    confidence = min(0.55 + metrics["body_ratio"] * 0.35, 0.95)
    return price_action_point(
        symbol,
        timeframe,
        point_type,
        direction,
        candle.close,
        candle.open_time,
        confidence,
        {**metrics, "pattern": "marubozu"},
    )


def detect_star_pattern(
    first: CandleSlice,
    middle: CandleSlice,
    third: CandleSlice,
    symbol: str,
    timeframe: str,
    large_body_ratio: float,
    small_body_ratio: float,
) -> StructurePoint | None:
    first_metrics = candle_metrics(first)
    middle_metrics = candle_metrics(middle)
    third_metrics = candle_metrics(third)
    if first_metrics is None or middle_metrics is None or third_metrics is None:
        return None
    if first_metrics["body_ratio"] < large_body_ratio or middle_metrics["body_ratio"] > small_body_ratio or third_metrics["body_ratio"] < large_body_ratio:
        return None

    first_midpoint = (first.open + first.close) / 2 if first.open is not None else first.close
    if is_bearish(first) and is_bullish(third) and third.close >= first_midpoint:
        confidence = min(0.56 + third_metrics["body_ratio"] * 0.20 + (small_body_ratio - middle_metrics["body_ratio"]) * 0.25, 0.92)
        return price_action_point(
            symbol,
            timeframe,
            "morning_star",
            "up",
            third.close,
            third.open_time,
            confidence,
            {
                **third_metrics,
                "pattern": "morning_star",
                "first_time": first.open_time,
                "middle_time": middle.open_time,
                "first_midpoint": round(first_midpoint, 5),
            },
        )
    if is_bullish(first) and is_bearish(third) and third.close <= first_midpoint:
        confidence = min(0.56 + third_metrics["body_ratio"] * 0.20 + (small_body_ratio - middle_metrics["body_ratio"]) * 0.25, 0.92)
        return price_action_point(
            symbol,
            timeframe,
            "evening_star",
            "down",
            third.close,
            third.open_time,
            confidence,
            {
                **third_metrics,
                "pattern": "evening_star",
                "first_time": first.open_time,
                "middle_time": middle.open_time,
                "first_midpoint": round(first_midpoint, 5),
            },
        )
    return None


def detect_displacement_candle(
    candle: CandleSlice,
    metrics: dict[str, float],
    atr_value: float | None,
    symbol: str,
    timeframe: str,
    atr_multiplier: float,
    min_body_ratio: float,
) -> StructurePoint | None:
    if metrics["body_ratio"] < min_body_ratio:
        return None
    if atr_value is None or atr_value <= 0:
        return None
    range_atr = metrics["range"] / atr_value
    if range_atr < atr_multiplier:
        return None
    direction = "up" if is_bullish(candle) else "down"
    point_type = "displacement_bullish" if direction == "up" else "displacement_bearish"
    confidence = min(0.50 + min(range_atr, 3.0) * 0.10 + metrics["body_ratio"] * 0.20, 0.95)
    return price_action_point(
        symbol,
        timeframe,
        point_type,
        direction,
        candle.close,
        candle.open_time,
        confidence,
        {
            **metrics,
            "pattern": "displacement",
            "atr_at_detection": round(atr_value, 5),
            "range_atr": round(range_atr, 4),
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


def candle_metrics(candle: CandleSlice) -> dict[str, float] | None:
    if candle.open is None:
        return None
    full_range = candle_range(candle)
    if full_range <= 0:
        return None
    body = candle_body(candle)
    upper_wick = candle.high - max(candle.open, candle.close)
    lower_wick = min(candle.open, candle.close) - candle.low
    return {
        "open": round(candle.open, 5),
        "high": round(candle.high, 5),
        "low": round(candle.low, 5),
        "close": round(candle.close, 5),
        "range": round(full_range, 5),
        "body": round(body, 5),
        "body_ratio": round(body / full_range, 4),
        "upper_wick": round(max(upper_wick, 0.0), 5),
        "lower_wick": round(max(lower_wick, 0.0), 5),
        "upper_wick_ratio": round(max(upper_wick, 0.0) / full_range, 4),
        "lower_wick_ratio": round(max(lower_wick, 0.0) / full_range, 4),
        "close_position": round((candle.close - candle.low) / full_range, 4),
    }


def price_action_point(
    symbol: str,
    timeframe: str,
    point_type: str,
    direction: str,
    price: float,
    event_time: str,
    confidence: float,
    metadata: dict[str, object],
) -> StructurePoint:
    return StructurePoint(
        symbol=symbol,
        timeframe=timeframe,
        detector=PRICE_ACTION_DETECTOR,
        status="confirmed",
        point_type=point_type,
        price=price,
        event_time=event_time,
        confidence=round(confidence, 4),
        related_zone_ids=[],
        metadata={
            **metadata,
            "direction": direction,
            "confirmation_role": "entry_trigger",
            "confirmed_at": event_time,
        },
    )


def body_bounds(candle: CandleSlice) -> tuple[float, float]:
    open_price = candle.open if candle.open is not None else candle.close
    return min(open_price, candle.close), max(open_price, candle.close)


def is_bullish(candle: CandleSlice) -> bool:
    return candle.open is not None and candle.close > candle.open


def is_bearish(candle: CandleSlice) -> bool:
    return candle.open is not None and candle.close < candle.open


def detect_and_store_price_action_patterns(
    conn: Connection,
    symbol: str,
    timeframe: str,
    atr_period: int = 14,
    displacement_atr_multiplier: float = 1.5,
    displacement_body_ratio: float = 0.60,
    pinbar_wick_body_ratio: float = 2.0,
    pinbar_min_wick_ratio: float = 0.55,
    engulfing_min_body_ratio: float = 0.45,
    marubozu_min_body_ratio: float = 0.75,
    star_large_body_ratio: float = 0.45,
    star_small_body_ratio: float = 0.35,
) -> int:
    candles = load_candle_slices(conn, symbol, timeframe)
    points = detect_price_action_patterns(
        candles,
        symbol,
        timeframe,
        atr_period=atr_period,
        displacement_atr_multiplier=displacement_atr_multiplier,
        displacement_body_ratio=displacement_body_ratio,
        pinbar_wick_body_ratio=pinbar_wick_body_ratio,
        pinbar_min_wick_ratio=pinbar_min_wick_ratio,
        engulfing_min_body_ratio=engulfing_min_body_ratio,
        marubozu_min_body_ratio=marubozu_min_body_ratio,
        star_large_body_ratio=star_large_body_ratio,
        star_small_body_ratio=star_small_body_ratio,
    )
    return replace_structure_points(conn, symbol, timeframe, PRICE_ACTION_DETECTOR, points)
