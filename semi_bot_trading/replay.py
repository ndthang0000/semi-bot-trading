from __future__ import annotations

from sqlite3 import Connection


def replay_candles(
    conn: Connection,
    symbol: str,
    timeframe: str,
    limit: int,
    start: str | None = None,
) -> list[dict[str, object]]:
    params: list[object] = [symbol, timeframe]
    where = "WHERE symbol = ? AND timeframe = ?"
    if start:
        where += " AND open_time >= ?"
        params.append(start)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT open_time, open, high, low, close, volume
        FROM candles
        {where}
        ORDER BY open_time
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]
