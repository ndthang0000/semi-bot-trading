from __future__ import annotations

from datetime import UTC, datetime, timedelta
from sqlite3 import Connection
from typing import Any

from .zones import CandleSlice, latest_atr


SESSION_WINDOWS_UTC = (
    ("asia", "Asia", 0, 7),
    ("london", "London", 7, 17),
    ("new_york", "New York", 12, 21),
)
STALE_BROKEN_DISTANCE_ATR = 5.0


def build_intraday_map(conn: Connection, symbol: str, as_of: str) -> dict[str, Any]:
    """Build replay-safe intraday liquidity references from closed M15 candles."""
    as_of_dt = _parse_iso(as_of)
    history_start = (as_of_dt - timedelta(days=4)).isoformat()
    rows = conn.execute(
        """
        SELECT open_time, close_time, open, high, low, close
        FROM candles
        WHERE symbol = ? AND timeframe = 'M15'
          AND open_time >= ? AND close_time <= ?
        ORDER BY open_time
        """,
        (symbol, history_start, as_of_dt.isoformat()),
    ).fetchall()
    candles = [
        {
            "time": str(row["open_time"]),
            "close_time": str(row["close_time"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        }
        for row in rows
    ]
    if not candles:
        return _empty_map(as_of_dt)

    current_price = float(candles[-1]["close"])
    atr = latest_atr(
        [
            CandleSlice(
                open_time=item["time"],
                open=item["open"],
                high=item["high"],
                low=item["low"],
                close=item["close"],
            )
            for item in candles
        ],
        14,
    )
    allowance = max(0.6, 0.25 * float(atr or 0.0))
    today = as_of_dt.date()
    today_start = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
    levels: list[dict[str, Any]] = []

    previous_day_start, previous_day = _previous_trading_day(candles, today_start)
    if previous_day:
        previous_day_end = previous_day_start + timedelta(days=1)
        levels.extend(
            _high_low_levels(
                "previous_day",
                "PD",
                previous_day,
                previous_day_start,
                previous_day_end,
                candles,
                current_price,
                atr,
                allowance,
                priority=100,
                live=False,
            )
        )

    today_candles = _candles_between(candles, today_start, as_of_dt + timedelta(microseconds=1))
    if today_candles:
        levels.extend(
            _high_low_levels(
                "current_day",
                "Day",
                today_candles,
                today_start,
                as_of_dt,
                candles,
                current_price,
                atr,
                allowance,
                priority=55,
                live=True,
            )
        )

    current_session = _current_session(as_of_dt.hour)
    for key, label, start_hour, end_hour in SESSION_WINDOWS_UTC:
        start = today_start + timedelta(hours=start_hour)
        end = today_start + timedelta(hours=end_hour)
        session_candles = _candles_between(candles, start, min(end, as_of_dt + timedelta(microseconds=1)))
        if not session_candles or as_of_dt < start:
            continue
        is_live = as_of_dt < end
        levels.extend(
            _high_low_levels(
                key,
                label,
                session_candles,
                start,
                as_of_dt if is_live else end,
                candles,
                current_price,
                atr,
                allowance,
                priority=75 if is_live else 85,
                live=is_live,
            )
        )

    levels.extend(_latest_m15_swings(conn, symbol, as_of_dt, candles, current_price, atr, allowance))
    levels.sort(key=lambda item: (-item["priority"], abs(item["distance"])))
    actionable = [item for item in levels if item["status"] not in {"broken", "stale"}]
    nearest_above = min(
        (item for item in actionable if item["price"] > current_price),
        key=lambda item: (item["price"], 0 if item["live"] else 1),
        default=None,
    )
    nearest_below = max(
        (item for item in actionable if item["price"] < current_price),
        key=lambda item: (item["price"], 1 if item["live"] else 0),
        default=None,
    )
    return {
        "as_of": as_of_dt.isoformat(),
        "timezone": "UTC",
        "current_price": round(current_price, 5),
        "current_session": current_session,
        "atr_m15": round(float(atr), 5) if atr is not None else None,
        "approach_allowance": round(allowance, 5),
        "nearest_above_id": nearest_above["id"] if nearest_above else None,
        "nearest_below_id": nearest_below["id"] if nearest_below else None,
        "levels": levels,
    }


def _latest_m15_swings(
    conn: Connection,
    symbol: str,
    as_of: datetime,
    candles: list[dict[str, Any]],
    current_price: float,
    atr: float | None,
    allowance: float,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, point_type, price, event_time, metadata_json
        FROM structure_points
        WHERE symbol = ? AND timeframe = 'M15' AND status = 'confirmed'
          AND point_type IN ('HH', 'LH', 'HL', 'LL') AND event_time <= ?
        ORDER BY event_time DESC
        LIMIT 20
        """,
        (symbol, as_of.isoformat()),
    ).fetchall()
    found: dict[str, Any] = {}
    import json

    for row in rows:
        metadata = json.loads(row["metadata_json"] or "{}")
        confirmed_at = _parse_iso(str(metadata.get("confirmed_at", row["event_time"])))
        if confirmed_at > as_of:
            continue
        side = "high" if str(row["point_type"]) in {"HH", "LH"} else "low"
        if side in found:
            continue
        price = float(row["price"])
        found[side] = _make_level(
            level_id=f"m15_{side}",
            kind="m15_swing",
            label=f"M15 {row['point_type']}",
            side=side,
            price=price,
            period_start=str(row["event_time"]),
            period_end=confirmed_at.isoformat(),
            subsequent=[item for item in candles if _parse_iso(item["time"]) >= confirmed_at],
            current_price=current_price,
            atr=atr,
            allowance=allowance,
            priority=65,
            live=False,
        )
        if len(found) == 2:
            break
    return list(found.values())


def _high_low_levels(
    key: str,
    label: str,
    period_candles: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    all_candles: list[dict[str, Any]],
    current_price: float,
    atr: float | None,
    allowance: float,
    priority: int,
    live: bool,
) -> list[dict[str, Any]]:
    subsequent = [item for item in all_candles if _parse_iso(item["time"]) >= end]
    return [
        _make_level(
            f"{key}_high",
            key,
            f"{label} H" if label != "PD" else "PDH",
            "high",
            max(item["high"] for item in period_candles),
            start.isoformat(),
            end.isoformat(),
            subsequent,
            current_price,
            atr,
            allowance,
            priority,
            live,
        ),
        _make_level(
            f"{key}_low",
            key,
            f"{label} L" if label != "PD" else "PDL",
            "low",
            min(item["low"] for item in period_candles),
            start.isoformat(),
            end.isoformat(),
            subsequent,
            current_price,
            atr,
            allowance,
            priority,
            live,
        ),
    ]


def _make_level(
    level_id: str,
    kind: str,
    label: str,
    side: str,
    price: float,
    period_start: str,
    period_end: str,
    subsequent: list[dict[str, Any]],
    current_price: float,
    atr: float | None,
    allowance: float,
    priority: int,
    live: bool,
) -> dict[str, Any]:
    status = "live" if live else _level_status(side, price, subsequent)
    distance = price - current_price
    if status == "unswept" and abs(distance) <= allowance:
        status = "testing"
    elif status == "broken" and abs(distance) <= allowance:
        status = "testing_flip"
    elif status == "broken" and atr and abs(distance / atr) > STALE_BROKEN_DISTANCE_ATR:
        status = "stale"
    return {
        "id": level_id,
        "kind": kind,
        "label": label,
        "side": side,
        "price": round(price, 5),
        "period_start": period_start,
        "period_end": period_end,
        "status": status,
        "priority": priority,
        "live": live,
        "distance": round(distance, 5),
        "distance_atr": round(distance / atr, 4) if atr else None,
        "approach_low": round(price - allowance, 5),
        "approach_high": round(price + allowance, 5),
    }


def _level_status(side: str, price: float, candles: list[dict[str, Any]]) -> str:
    crossed = [item for item in candles if item["high"] > price] if side == "high" else [item for item in candles if item["low"] < price]
    if not crossed:
        return "unswept"
    last_close = float(candles[-1]["close"]) if candles else price
    beyond = last_close > price if side == "high" else last_close < price
    if beyond:
        return "broken"
    crossing_close = float(crossed[-1]["close"])
    reclaimed_on_cross = crossing_close <= price if side == "high" else crossing_close >= price
    return "reclaimed" if reclaimed_on_cross or not beyond else "swept"


def _candles_between(candles: list[dict[str, Any]], start: datetime, end: datetime) -> list[dict[str, Any]]:
    return [item for item in candles if start <= _parse_iso(item["time"]) < end]


def _previous_trading_day(
    candles: list[dict[str, Any]],
    today_start: datetime,
) -> tuple[datetime, list[dict[str, Any]]]:
    by_date: dict[Any, list[dict[str, Any]]] = {}
    for item in candles:
        opened = _parse_iso(item["time"])
        if opened >= today_start:
            continue
        by_date.setdefault(opened.date(), []).append(item)
    if not by_date:
        return today_start - timedelta(days=1), []
    # Skip the short Sunday reopen fragment when a full Friday session exists.
    eligible = [day for day, items in by_date.items() if len(items) >= 24]
    selected = max(eligible or by_date.keys())
    return datetime.combine(selected, datetime.min.time(), tzinfo=UTC), by_date[selected]


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _current_session(hour: int) -> str:
    if hour < 7:
        return "Asia"
    if hour < 12:
        return "London"
    if hour < 17:
        return "London-NY"
    if hour < 21:
        return "New York"
    return "Off-hours"


def _empty_map(as_of: datetime) -> dict[str, Any]:
    return {
        "as_of": as_of.isoformat(),
        "timezone": "UTC",
        "current_price": None,
        "current_session": "unknown",
        "atr_m15": None,
        "approach_allowance": None,
        "nearest_above_id": None,
        "nearest_below_id": None,
        "levels": [],
    }
