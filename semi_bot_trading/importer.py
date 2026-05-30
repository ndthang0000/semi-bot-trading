from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection

from .candles import read_csv_candles, upsert_candles
from .timeframes import normalize_timeframe


@dataclass(frozen=True)
class ImportResult:
    path: Path
    symbol: str
    timeframe: str
    rows_seen: int
    rows_upserted: int


def infer_symbol_timeframe(path: Path) -> tuple[str, str]:
    stem = path.stem.upper()
    parts = stem.split("_")
    if len(parts) < 2:
        raise ValueError(f"Cannot infer symbol/timeframe from filename: {path.name}")
    timeframe = normalize_timeframe(parts[-1])
    symbol = "_".join(parts[:-1])
    return symbol, timeframe


def import_csv_file(conn: Connection, path: Path) -> ImportResult:
    symbol, timeframe = infer_symbol_timeframe(path)
    candles = read_csv_candles(path, symbol=symbol, timeframe=timeframe)
    rows_upserted = upsert_candles(conn, candles)
    return ImportResult(
        path=path,
        symbol=symbol,
        timeframe=timeframe,
        rows_seen=len(candles),
        rows_upserted=rows_upserted,
    )


def import_data_dir(conn: Connection, data_dir: Path) -> list[ImportResult]:
    files = sorted(data_dir.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No CSV files found in {data_dir}")
    return [import_csv_file(conn, path) for path in files]
