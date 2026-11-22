from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from sqlite3 import Connection
from typing import Any


MAX_SOURCE_BARS = 5_000
DEFAULT_SETTINGS: dict[str, Any] = {
    "rows": 24,
    "value_area_pct": 70.0,
    "mode": "up_down",
    "width_pct": 30.0,
    "placement": "left",
    "show_poc": True,
    "show_vah": True,
    "show_val": True,
}


class VolumeProfileError(ValueError):
    pass


@dataclass
class _Bin:
    low: float
    high: float
    up: float = 0.0
    down: float = 0.0

    @property
    def total(self) -> float:
        return self.up + self.down


def normalize_volume_profile_settings(value: dict[str, Any] | None) -> dict[str, Any]:
    raw = value or {}
    settings = {**DEFAULT_SETTINGS, **{key: raw[key] for key in DEFAULT_SETTINGS if key in raw}}
    try:
        settings["rows"] = int(settings["rows"])
        settings["value_area_pct"] = float(settings["value_area_pct"])
        settings["width_pct"] = float(settings["width_pct"])
    except (TypeError, ValueError) as exc:
        raise VolumeProfileError("Volume Profile settings must be numeric") from exc
    if not 10 <= settings["rows"] <= 200:
        raise VolumeProfileError("Volume Profile rows must be between 10 and 200")
    if not 1 <= settings["value_area_pct"] <= 100:
        raise VolumeProfileError("Volume Profile value area must be between 1 and 100 percent")
    if not 10 <= settings["width_pct"] <= 100:
        raise VolumeProfileError("Volume Profile width must be between 10 and 100 percent")
    if settings["mode"] not in {"total", "up_down", "delta"}:
        raise VolumeProfileError("Volume Profile mode must be total, up_down, or delta")
    if settings["placement"] not in {"left", "right"}:
        raise VolumeProfileError("Volume Profile placement must be left or right")
    for key in ("show_poc", "show_vah", "show_val"):
        if not isinstance(settings[key], bool):
            raise VolumeProfileError(f"Volume Profile {key} must be true or false")
    return settings


def instrument_tick_size(conn: Connection, symbol: str) -> tuple[float, str]:
    row = conn.execute(
        "SELECT trade_tick_size, point FROM instrument_metadata WHERE symbol = ?",
        (symbol,),
    ).fetchone()
    if row is not None:
        tick_size = float(row["trade_tick_size"] or 0)
        if tick_size > 0:
            return tick_size, "trade_tick_size"
        point = float(row["point"] or 0)
        if point > 0:
            return point, "point"
    return (0.01, "xauusd_fallback") if symbol.upper().startswith("XAUUSD") else (0.00001, "fallback")


def calculate_fixed_range_profile(
    conn: Connection,
    *,
    symbol: str,
    start: datetime,
    end: datetime,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if end <= start:
        raise VolumeProfileError("Volume Profile end must be after start")
    normalized = normalize_volume_profile_settings(settings)
    rows = conn.execute(
        """
        SELECT open_time, open, high, low, close, volume
        FROM candles
        WHERE symbol = ? AND timeframe = 'M1' AND open_time >= ? AND open_time < ?
        ORDER BY open_time ASC
        LIMIT ?
        """,
        (symbol, start.isoformat(), end.isoformat(), MAX_SOURCE_BARS + 1),
    ).fetchall()
    if not rows:
        raise VolumeProfileError("M1 volume data is not ready for this range")
    if len(rows) > MAX_SOURCE_BARS:
        raise VolumeProfileError(f"Volume Profile range exceeds {MAX_SOURCE_BARS} M1 bars")
    if any(row["volume"] is None for row in rows):
        raise VolumeProfileError("M1 tick volume is missing for this range")

    profile_low_raw = min(float(row["low"]) for row in rows)
    profile_high_raw = max(float(row["high"]) for row in rows)
    tick_size, tick_size_source = instrument_tick_size(conn, symbol)
    profile_low = math.floor(profile_low_raw / tick_size) * tick_size
    span = max(profile_high_raw - profile_low, tick_size)
    row_size = max(tick_size, math.ceil((span / normalized["rows"]) / tick_size) * tick_size)
    profile_high = profile_low + row_size * normalized["rows"]
    bins = [_Bin(profile_low + index * row_size, profile_low + (index + 1) * row_size) for index in range(normalized["rows"])]

    source_total = 0.0
    for candle in rows:
        low = float(candle["low"])
        high = float(candle["high"])
        volume = float(candle["volume"])
        if volume < 0:
            raise VolumeProfileError("M1 tick volume must not be negative")
        source_total += volume
        target = "up" if float(candle["close"]) >= float(candle["open"]) else "down"
        if high <= low:
            index = min(normalized["rows"] - 1, max(0, int((low - profile_low) / row_size)))
            setattr(bins[index], target, getattr(bins[index], target) + volume)
            continue
        overlaps: list[tuple[int, float]] = []
        for index, item in enumerate(bins):
            overlap = max(0.0, min(high, item.high) - max(low, item.low))
            if overlap > 0:
                overlaps.append((index, overlap))
        overlap_total = sum(overlap for _, overlap in overlaps)
        if overlap_total <= 0:
            raise VolumeProfileError("M1 candle lies outside calculated Volume Profile rows")
        distributed = 0.0
        for position, (index, overlap) in enumerate(overlaps):
            share = volume - distributed if position == len(overlaps) - 1 else volume * overlap / overlap_total
            distributed += share
            setattr(bins[index], target, getattr(bins[index], target) + share)

    if source_total <= 0:
        raise VolumeProfileError("M1 tick volume is zero for this range")

    poc_index = max(range(len(bins)), key=lambda index: (bins[index].total, index))
    value_indices = _value_area_indices(bins, poc_index, source_total * normalized["value_area_pct"] / 100)
    result_rows = []
    for index, item in enumerate(bins):
        result_rows.append({
            "index": index,
            "price_low": item.low,
            "price_high": item.high,
            "price_mid": (item.low + item.high) / 2,
            "up_volume": item.up,
            "down_volume": item.down,
            "total_volume": item.total,
            "delta": item.up - item.down,
            "in_value_area": index in value_indices,
        })
    return {
        "source_timeframe": "M1",
        "volume_kind": "tick_volume",
        "tick_size": tick_size,
        "tick_size_source": tick_size_source,
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "source_bar_count": len(rows),
        "total_volume": source_total,
        "profile_low": profile_low,
        "profile_high": profile_high,
        "row_size": row_size,
        "poc": result_rows[poc_index]["price_mid"],
        "vah": bins[max(value_indices)].high,
        "val": bins[min(value_indices)].low,
        "settings": normalized,
        "rows": result_rows,
    }


def _value_area_indices(bins: list[_Bin], poc_index: int, target: float) -> set[int]:
    selected = {poc_index}
    accumulated = bins[poc_index].total
    below = poc_index - 1
    above = poc_index + 1
    while accumulated < target and (below >= 0 or above < len(bins)):
        below_volume = bins[below].total if below >= 0 else -1.0
        above_volume = bins[above].total if above < len(bins) else -1.0
        # Equal adjacent volume expands upward first, matching the deterministic
        # TradingView-style tie rule used by this project.
        if above_volume >= below_volume:
            selected.add(above)
            accumulated += bins[above].total
            above += 1
        else:
            selected.add(below)
            accumulated += bins[below].total
            below -= 1
    return selected
