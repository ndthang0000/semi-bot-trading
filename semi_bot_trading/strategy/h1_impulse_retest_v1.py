from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class H1ImpulsePreviewConfig:
    atr_period: int = 14
    stop_buffer_atr: float = 0.1
    min_stop_atr: float = 0.5
    max_stop_atr: float = 1.2
    min_body_atr: float = 0.8
    min_range_atr: float = 0.9
    max_range_atr: float = 2.5
    min_body_range_ratio: float = 0.6
    min_close_location: float = 0.75
    max_close_side_wick_ratio: float = 0.2
    expiry_medium_body_atr: float = 1.2
    expiry_large_body_atr: float = 1.6
    expiry_hours_small: int = 6
    expiry_hours_medium: int = 12
    expiry_hours_large: int = 18


DEFAULT_H1_IMPULSE_PREVIEW_CONFIG = H1ImpulsePreviewConfig()


def h1_impulse_preview_config_from_strategy(strategy_config: Any) -> H1ImpulsePreviewConfig:
    return H1ImpulsePreviewConfig(
        atr_period=int(strategy_config.h1_impulse_retest_v1_atr_period),
        stop_buffer_atr=float(strategy_config.h1_impulse_retest_v1_stop_buffer_atr),
        min_stop_atr=float(strategy_config.h1_impulse_retest_v1_min_stop_atr),
        max_stop_atr=float(strategy_config.h1_impulse_retest_v1_max_stop_atr),
        min_body_atr=float(strategy_config.h1_impulse_retest_v1_min_body_atr),
        min_range_atr=float(strategy_config.h1_impulse_retest_v1_min_range_atr),
        max_range_atr=float(strategy_config.h1_impulse_retest_v1_max_range_atr),
        min_body_range_ratio=float(strategy_config.h1_impulse_retest_v1_min_body_range_ratio),
        min_close_location=float(strategy_config.h1_impulse_retest_v1_min_close_location),
        max_close_side_wick_ratio=float(strategy_config.h1_impulse_retest_v1_max_close_side_wick_ratio),
        expiry_medium_body_atr=float(strategy_config.h1_impulse_retest_v1_expiry_medium_body_atr),
        expiry_large_body_atr=float(strategy_config.h1_impulse_retest_v1_expiry_large_body_atr),
        expiry_hours_small=int(strategy_config.h1_impulse_retest_v1_expiry_hours_small),
        expiry_hours_medium=int(strategy_config.h1_impulse_retest_v1_expiry_hours_medium),
        expiry_hours_large=int(strategy_config.h1_impulse_retest_v1_expiry_hours_large),
    )


def build_h1_impulse_markers(
    candles: list[dict[str, Any]],
    *,
    visible_start: str,
    visible_end: str,
    config: H1ImpulsePreviewConfig = DEFAULT_H1_IMPULSE_PREVIEW_CONFIG,
) -> list[dict[str, Any]]:
    """Build review markers using only information available at each H1 close."""
    true_ranges: list[float] = []
    previous_close: float | None = None
    markers: list[dict[str, Any]] = []
    for index, signal in enumerate(candles):
        high = float(signal["high"])
        low = float(signal["low"])
        close = float(signal["close"])
        current_range = high - low if previous_close is None else max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )
        true_ranges.append(current_range)
        previous_close = close
        if index == 0:
            continue

        candle_time = str(signal.get("time"))
        if candle_time < visible_start or candle_time > visible_end:
            continue
        atr_window = true_ranges[-config.atr_period :]
        atr = sum(atr_window) / len(atr_window) if atr_window else 0.0
        if atr <= 0:
            continue
        body_atr_ratio = abs(close - float(signal["open"])) / atr
        if body_atr_ratio < config.min_body_atr:
            continue

        preview = build_h1_impulse_preview(
            signal=signal,
            previous=candles[index - 1],
            atr=atr,
            reference_price=close,
            config=config,
        )
        markers.append(
            {
                "time": candle_time,
                "close_time": signal.get("close_time"),
                "direction": preview["direction"],
                "status": "eligible" if preview["status"] == "eligible" else "candidate",
                "body_atr_ratio": preview["signal"]["body_atr_ratio"],
                "range_atr_ratio": preview["signal"]["range_atr_ratio"],
                "body_range_ratio": preview["signal"]["body_range_ratio"],
                "entry_source": preview["entry_source"],
                "blocked_reason": preview["blocked_reason"],
            }
        )
    return markers


def build_h1_impulse_preview(
    signal: dict[str, Any],
    previous: dict[str, Any],
    atr: float,
    reference_price: float | None,
    risk_reward: float = 2.5,
    config: H1ImpulsePreviewConfig = DEFAULT_H1_IMPULSE_PREVIEW_CONFIG,
) -> dict[str, Any]:
    if atr <= 0:
        raise ValueError("H1 ATR must be greater than zero")
    if not 1.5 <= risk_reward <= 4:
        raise ValueError("Risk:reward must be between 1.5 and 4")

    open_price = float(signal["open"])
    high = float(signal["high"])
    low = float(signal["low"])
    close = float(signal["close"])
    previous_high = float(previous["high"])
    previous_low = float(previous["low"])
    candle_range = high - low
    body = abs(close - open_price)
    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low
    soft_blocked: list[str] = []
    hard_blocked: list[str] = []

    if candle_range <= 0:
        raise ValueError("Signal candle range must be greater than zero")
    if close == open_price:
        direction = "neutral"
        hard_blocked.append("Signal candle is a doji; direction cannot be determined.")
    else:
        direction = "long" if close > open_price else "short"

    body_atr_ratio = body / atr
    range_atr_ratio = candle_range / atr
    body_range_ratio = body / candle_range
    close_location = (close - low) / candle_range if direction == "long" else (high - close) / candle_range
    close_side_wick = upper_wick if direction == "long" else lower_wick
    opposite_wick = lower_wick if direction == "long" else upper_wick
    close_side_wick_ratio = close_side_wick / candle_range
    opposite_wick_ratio = opposite_wick / candle_range
    expiry_hours = expiry_hours_for_body_atr(body_atr_ratio, config)
    signal_close_time = str(signal.get("close_time"))
    expires_at = (datetime.fromisoformat(signal_close_time) + timedelta(hours=expiry_hours)).isoformat()

    _require_min(soft_blocked, body_atr_ratio, config.min_body_atr, "Body/ATR")
    _require_min(soft_blocked, range_atr_ratio, config.min_range_atr, "Range/ATR")
    _require_max(soft_blocked, range_atr_ratio, config.max_range_atr, "Range/ATR")
    _require_min(soft_blocked, body_range_ratio, config.min_body_range_ratio, "Body/range")
    _require_min(soft_blocked, close_location, config.min_close_location, "Directional close location")
    _require_max(soft_blocked, close_side_wick_ratio, config.max_close_side_wick_ratio, "Close-side wick/range")

    stop_buffer = atr * config.stop_buffer_atr
    min_stop_distance = atr * config.min_stop_atr
    max_stop_distance = atr * config.max_stop_atr
    fib_midpoint = (high + low) / 2

    if direction == "long":
        stop_loss = low - stop_buffer
        previous_entry = previous_high
        previous_stop_distance = previous_entry - stop_loss
        broke_previous_edge = close > previous_high
        if not broke_previous_edge:
            soft_blocked.append("Bullish signal did not close above the previous H1 high.")
        entry, entry_source = _long_entry(
            stop_loss,
            previous_entry,
            fib_midpoint,
            previous_stop_distance,
            min_stop_distance,
            max_stop_distance,
        )
        stop_distance = entry - stop_loss
        take_profit = entry + risk_reward * stop_distance
        limit_placement_valid = reference_price is None or entry < reference_price
        if entry <= stop_loss:
            hard_blocked.append("LONG entry must be above stop loss.")
        if reference_price is not None and not limit_placement_valid:
            hard_blocked.append("LONG entry is not below the reference price, so it is not a valid BUY LIMIT.")
    elif direction == "short":
        stop_loss = high + stop_buffer
        previous_entry = previous_low
        previous_stop_distance = stop_loss - previous_entry
        broke_previous_edge = close < previous_low
        if not broke_previous_edge:
            soft_blocked.append("Bearish signal did not close below the previous H1 low.")
        entry, entry_source = _short_entry(
            stop_loss,
            previous_entry,
            fib_midpoint,
            previous_stop_distance,
            min_stop_distance,
            max_stop_distance,
        )
        stop_distance = stop_loss - entry
        take_profit = entry - risk_reward * stop_distance
        limit_placement_valid = reference_price is None or entry > reference_price
        if entry >= stop_loss:
            hard_blocked.append("SHORT entry must be below stop loss.")
        if reference_price is not None and not limit_placement_valid:
            hard_blocked.append("SHORT entry is not above the reference price, so it is not a valid SELL LIMIT.")
    else:
        stop_loss = low - stop_buffer
        previous_entry = previous_high
        previous_stop_distance = 0.0
        entry = fib_midpoint
        entry_source = "unavailable"
        stop_distance = 0.0
        take_profit = entry
        broke_previous_edge = False
        limit_placement_valid = False

    if stop_distance < min_stop_distance:
        hard_blocked.append(
            f"Final stop distance {stop_distance / atr:.2f} ATR is below the {config.min_stop_atr:.2f} ATR minimum."
        )
    if stop_distance > max_stop_distance:
        hard_blocked.append(
            f"Final stop distance {stop_distance / atr:.2f} ATR exceeds the {config.max_stop_atr:.2f} ATR maximum."
        )

    entry_options = build_entry_options(
        direction=direction,
        high=high,
        low=low,
        previous_high=previous_high,
        previous_low=previous_low,
        stop_loss=stop_loss,
        min_stop_distance=min_stop_distance,
        max_stop_distance=max_stop_distance,
        min_stop_atr=config.min_stop_atr,
        max_stop_atr=config.max_stop_atr,
    )

    blocked = [*soft_blocked, *hard_blocked]
    return {
        "schema_version": 1,
        "playbook": "h1_impulse_retest_v1",
        "status": "eligible" if not blocked else "blocked",
        "direction": direction,
        "signal_candle_time": signal.get("time"),
        "signal_candle_close_time": signal.get("close_time"),
        "expires_at": expires_at,
        "expiry_hours": expiry_hours,
        "previous_candle_time": previous.get("time"),
        "atr": _round(atr),
        "atr_period": config.atr_period,
        "reference_price": _round_optional(reference_price),
        "risk_reward": risk_reward,
        "entry": _round(entry),
        "entry_source": entry_source,
        "entry_options": entry_options,
        "previous_edge_entry": _round(previous_entry),
        "fib_0_5_entry": _round(fib_midpoint),
        "stop_loss": _round(stop_loss),
        "stop_buffer": _round(stop_buffer),
        "stop_distance": _round(stop_distance),
        "stop_distance_atr": _round(stop_distance / atr),
        "min_stop_distance": _round(min_stop_distance),
        "max_stop_distance": _round(max_stop_distance),
        "take_profit": _round(take_profit),
        "limit_placement_valid": limit_placement_valid,
        "broke_previous_edge": broke_previous_edge,
        "blocked_reason": blocked,
        "soft_blocked_reason": soft_blocked,
        "hard_blocked_reason": hard_blocked,
        "signal": {
            "open": _round(open_price),
            "high": _round(high),
            "low": _round(low),
            "close": _round(close),
            "range": _round(candle_range),
            "body": _round(body),
            "upper_wick": _round(upper_wick),
            "lower_wick": _round(lower_wick),
            "body_atr_ratio": _round(body_atr_ratio),
            "range_atr_ratio": _round(range_atr_ratio),
            "body_range_ratio": _round(body_range_ratio),
            "close_location": _round(close_location),
            "close_side_wick_ratio": _round(close_side_wick_ratio),
            "opposite_wick_ratio": _round(opposite_wick_ratio),
        },
        "previous": {
            "open": _round(float(previous["open"])),
            "high": _round(previous_high),
            "low": _round(previous_low),
            "close": _round(float(previous["close"])),
            "entry_stop_distance": _round(previous_stop_distance),
            "entry_stop_distance_atr": _round(previous_stop_distance / atr),
        },
        "parameters": asdict(config),
    }


def evaluate_h1_impulse_preview(
    preview: dict[str, Any],
    future_candles: list[dict[str, Any]],
) -> dict[str, Any]:
    if preview["status"] != "eligible":
        return _outcome("blocked")

    direction = str(preview["direction"])
    entry = float(preview["entry"])
    stop_loss = float(preview["stop_loss"])
    take_profit = float(preview["take_profit"])
    risk_reward = float(preview["risk_reward"])
    raw_expires_at = preview.get("expires_at")
    expires_at = datetime.fromisoformat(str(raw_expires_at)) if raw_expires_at else None
    filled_at: str | None = None
    bars_to_fill: int | None = None
    bars_held = 0

    for index, candle in enumerate(future_candles, start=1):
        high = float(candle["high"])
        low = float(candle["low"])
        candle_time = str(candle.get("time"))
        candle_close_time = str(candle.get("close_time") or candle_time)
        if filled_at is None and expires_at is not None and datetime.fromisoformat(candle_time) >= expires_at:
            return _outcome("expired_unfilled", exited_at=str(raw_expires_at))
        entry_touched = low <= entry if direction == "long" else high >= entry
        if filled_at is None:
            if not entry_touched:
                continue
            filled_at = candle_time
            bars_to_fill = index
            bars_held = 1
            stop_touched = low <= stop_loss if direction == "long" else high >= stop_loss
            target_touched = high >= take_profit if direction == "long" else low <= take_profit
            if stop_touched and target_touched:
                return _outcome("ambiguous", filled_at, candle_close_time, bars_to_fill, bars_held, None)
            if stop_touched:
                return _outcome("loss", filled_at, candle_close_time, bars_to_fill, bars_held, -1.0)
            # On the fill candle OHLC cannot prove whether TP happened before or
            # after the limit was filled. Lower-timeframe data is required.
            if target_touched:
                return _outcome("ambiguous", filled_at, candle_close_time, bars_to_fill, bars_held, None)
            continue

        bars_held += 1
        stop_touched = low <= stop_loss if direction == "long" else high >= stop_loss
        target_touched = high >= take_profit if direction == "long" else low <= take_profit
        if stop_touched and target_touched:
            return _outcome("ambiguous", filled_at, candle_close_time, bars_to_fill, bars_held, None)
        if stop_touched:
            return _outcome("loss", filled_at, candle_close_time, bars_to_fill, bars_held, -1.0)
        if target_touched:
            return _outcome("win", filled_at, candle_close_time, bars_to_fill, bars_held, risk_reward)

    if filled_at is None:
        return _outcome("unfilled")
    return _outcome("open", filled_at, None, bars_to_fill, bars_held, None)


def _long_entry(
    stop_loss: float,
    previous_entry: float,
    fib_midpoint: float,
    previous_distance: float,
    min_distance: float,
    max_distance: float,
) -> tuple[float, str]:
    if previous_distance < min_distance:
        fib_distance = fib_midpoint - stop_loss
        if fib_distance > max_distance:
            return stop_loss + max_distance, "fib_0.5_then_atr_1.2_cap"
        return fib_midpoint, "fib_0.5_min_stop_fallback"
    if previous_distance > max_distance:
        return stop_loss + max_distance, "atr_1.2_max_stop_cap"
    return previous_entry, "previous_h1_high"


def expiry_hours_for_body_atr(body_atr_ratio: float, config: H1ImpulsePreviewConfig) -> int:
    if body_atr_ratio >= config.expiry_large_body_atr:
        return config.expiry_hours_large
    if body_atr_ratio >= config.expiry_medium_body_atr:
        return config.expiry_hours_medium
    return config.expiry_hours_small


def build_entry_options(
    *,
    direction: str,
    high: float,
    low: float,
    previous_high: float,
    previous_low: float,
    stop_loss: float,
    min_stop_distance: float,
    max_stop_distance: float,
    min_stop_atr: float,
    max_stop_atr: float,
) -> list[dict[str, Any]]:
    candle_range = high - low
    if direction == "long":
        values = [
            ("previous_h1_high", "Previous H1 high", previous_high),
            ("fib_0.382", "Fib 0.382", high - candle_range * 0.382),
            ("fib_0.5", "Fib 0.5", high - candle_range * 0.5),
            ("fib_0.618", "Fib 0.618", high - candle_range * 0.618),
            ("min_stop_atr", f"Min SL · {min_stop_atr:g} ATR", stop_loss + min_stop_distance),
            ("max_stop_atr", f"Max SL · {max_stop_atr:g} ATR", stop_loss + max_stop_distance),
        ]
    elif direction == "short":
        values = [
            ("previous_h1_low", "Previous H1 low", previous_low),
            ("fib_0.382", "Fib 0.382", low + candle_range * 0.382),
            ("fib_0.5", "Fib 0.5", low + candle_range * 0.5),
            ("fib_0.618", "Fib 0.618", low + candle_range * 0.618),
            ("min_stop_atr", f"Min SL · {min_stop_atr:g} ATR", stop_loss - min_stop_distance),
            ("max_stop_atr", f"Max SL · {max_stop_atr:g} ATR", stop_loss - max_stop_distance),
        ]
    else:
        return []
    return [{"source": source, "label": label, "price": _round(price)} for source, label, price in values]


def _short_entry(
    stop_loss: float,
    previous_entry: float,
    fib_midpoint: float,
    previous_distance: float,
    min_distance: float,
    max_distance: float,
) -> tuple[float, str]:
    if previous_distance < min_distance:
        fib_distance = stop_loss - fib_midpoint
        if fib_distance > max_distance:
            return stop_loss - max_distance, "fib_0.5_then_atr_1.2_cap"
        return fib_midpoint, "fib_0.5_min_stop_fallback"
    if previous_distance > max_distance:
        return stop_loss - max_distance, "atr_1.2_max_stop_cap"
    return previous_entry, "previous_h1_low"


def _require_min(blocked: list[str], actual: float, minimum: float, label: str) -> None:
    if actual < minimum:
        blocked.append(f"{label} {actual:.2f} is below minimum {minimum:.2f}.")


def _require_max(blocked: list[str], actual: float, maximum: float, label: str) -> None:
    if actual > maximum:
        blocked.append(f"{label} {actual:.2f} exceeds maximum {maximum:.2f}.")


def _round(value: float) -> float:
    return round(float(value), 5)


def _round_optional(value: float | None) -> float | None:
    return None if value is None else _round(value)


def _outcome(
    status: str,
    filled_at: str | None = None,
    exited_at: str | None = None,
    bars_to_fill: int | None = None,
    bars_held: int | None = None,
    result_r: float | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "filled_at": filled_at,
        "exited_at": exited_at,
        "bars_to_fill": bars_to_fill,
        "bars_held": bars_held,
        "result_r": result_r,
    }
