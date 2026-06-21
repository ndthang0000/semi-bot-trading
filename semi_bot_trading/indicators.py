from __future__ import annotations

from typing import Any


def rsi_series(closes: list[float], period: int = 14) -> list[float | None]:
    """Return Wilder RSI aligned with closes.

    Values before the first completed RSI window are `None`. The formula uses
    only previous closed candles, so callers can safely pass a point-in-time
    candle slice from replay/backtest without leaking future data.
    """
    if period <= 0:
        raise ValueError("period must be positive")
    result: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return result

    gains: list[float] = []
    losses: list[float] = []
    for prev, current in zip(closes, closes[1:]):
        change = current - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result[period] = _rsi_from_averages(avg_gain, avg_loss)

    for close_index in range(period + 1, len(closes)):
        gain = gains[close_index - 1]
        loss = losses[close_index - 1]
        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period
        result[close_index] = _rsi_from_averages(avg_gain, avg_loss)
    return result


def latest_rsi_snapshot(
    candles: list[dict[str, Any]],
    period: int = 14,
    slope_periods: tuple[int, ...] = (3, 5),
) -> dict[str, Any]:
    closes = [float(candle["close"]) for candle in candles if candle.get("close") is not None]
    values = rsi_series(closes, period=period)
    current = values[-1] if values else None
    snapshot: dict[str, Any] = {
        "period": period,
        "value": round(current, 5) if current is not None else None,
        "as_of": candles[-1]["time"] if candles else None,
    }
    for slope_period in slope_periods:
        slope_key = f"slope_{slope_period}"
        previous_index = len(values) - 1 - slope_period
        previous = values[previous_index] if previous_index >= 0 and values else None
        snapshot[slope_key] = round(current - previous, 5) if current is not None and previous is not None else None
    return snapshot


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))
