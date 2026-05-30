from __future__ import annotations

from datetime import timedelta


TIMEFRAME_SECONDS = {
    "M1": 60,
    "M5": 5 * 60,
    "M15": 15 * 60,
    "H1": 60 * 60,
    "H4": 4 * 60 * 60,
    "D1": 24 * 60 * 60,
}


def normalize_timeframe(value: str) -> str:
    timeframe = value.strip().upper()
    if timeframe not in TIMEFRAME_SECONDS:
        raise ValueError(f"Unsupported timeframe: {value}")
    return timeframe


def timeframe_delta(value: str) -> timedelta:
    return timedelta(seconds=TIMEFRAME_SECONDS[normalize_timeframe(value)])
