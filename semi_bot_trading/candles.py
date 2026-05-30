from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import Connection

from .timeframes import timeframe_delta


@dataclass(frozen=True)
class Candle:
    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    source: str

    @property
    def id(self) -> str:
        raw = f"{self.symbol}|{self.timeframe}|{self.open_time.isoformat()}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def parse_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_csv_candles(path: Path, symbol: str, timeframe: str) -> list[Candle]:
    delta = timeframe_delta(timeframe)
    candles: list[Candle] = []
    with path.open("r", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"time", "open", "high", "low", "close"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} missing required columns: {sorted(missing)}")

        for row_number, row in enumerate(reader, start=2):
            open_time = parse_datetime(row["time"])
            try:
                volume = row.get("volume")
                candles.append(
                    Candle(
                        symbol=symbol,
                        timeframe=timeframe,
                        open_time=open_time,
                        close_time=open_time + delta,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(volume) if volume not in (None, "") else None,
                        source=str(path),
                    )
                )
            except ValueError as exc:
                raise ValueError(f"{path}:{row_number} has invalid numeric data") from exc
    return candles


def upsert_candles(conn: Connection, candles: list[Candle]) -> int:
    if not candles:
        return 0

    rows = [
        (
            candle.id,
            candle.symbol,
            candle.timeframe,
            candle.open_time.isoformat(),
            candle.close_time.isoformat(),
            candle.open,
            candle.high,
            candle.low,
            candle.close,
            candle.volume,
            candle.source,
        )
        for candle in candles
    ]
    conn.executemany(
        """
        INSERT INTO candles (
            id, symbol, timeframe, open_time, close_time,
            open, high, low, close, volume, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(symbol, timeframe, open_time) DO UPDATE SET
            close_time = excluded.close_time,
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            close = excluded.close,
            volume = excluded.volume,
            source = excluded.source
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def candle_summary(conn: Connection) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT
            symbol,
            timeframe,
            COUNT(*) AS candle_count,
            MIN(open_time) AS first_open_time,
            MAX(open_time) AS last_open_time
        FROM candles
        GROUP BY symbol, timeframe
        ORDER BY symbol, timeframe
        """
    ).fetchall()
    return [dict(row) for row in rows]


def find_gaps(conn: Connection, symbol: str, timeframe: str, limit: int = 20) -> list[dict[str, object]]:
    delta = timeframe_delta(timeframe)
    rows = conn.execute(
        """
        SELECT open_time
        FROM candles
        WHERE symbol = ? AND timeframe = ?
        ORDER BY open_time
        """,
        (symbol, timeframe),
    ).fetchall()
    gaps: list[dict[str, object]] = []
    previous: datetime | None = None
    for row in rows:
        current = parse_datetime(row["open_time"])
        if previous is not None and current - previous != delta:
            gaps.append(
                {
                    "expected": (previous + delta).isoformat(),
                    "actual": current.isoformat(),
                    "minutes": int((current - previous - delta).total_seconds() / 60),
                }
            )
            if len(gaps) >= limit:
                break
        previous = current
    return gaps
