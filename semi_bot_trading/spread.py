from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from sqlite3 import Connection, Row
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def record_spread_snapshot(
    conn: Connection,
    *,
    symbol: str,
    broker_symbol: str,
    bid: float,
    ask: float,
    spread: float | None = None,
    snapshot_at: datetime | str | None = None,
    source: str = "mt5",
    metadata: dict[str, Any] | None = None,
) -> str:
    """Persist a bid/ask spread observation in price units."""
    observed_at = _iso(snapshot_at) if snapshot_at is not None else utc_now_iso()
    spread_value = max(0.0, float(ask) - float(bid)) if spread is None else max(0.0, float(spread))
    snapshot_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO spread_snapshots (
            id, symbol, broker_symbol, bid, ask, spread, snapshot_at, source, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            symbol,
            broker_symbol,
            float(bid),
            float(ask),
            spread_value,
            observed_at,
            source,
            json.dumps(metadata or {}, separators=(",", ":")),
        ),
    )
    conn.commit()
    return snapshot_id


def latest_spread_snapshot(conn: Connection, symbol: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, symbol, broker_symbol, bid, ask, spread, snapshot_at, source, metadata_json
        FROM spread_snapshots
        WHERE symbol = ?
        ORDER BY snapshot_at DESC
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()
    return _row_to_snapshot(row) if row else None


def spread_summary(conn: Connection, symbol: str, *, hours: int = 24, now: datetime | None = None) -> dict[str, Any]:
    now_dt = now or datetime.now(UTC)
    since = now_dt - timedelta(hours=max(1, int(hours)))
    rows = conn.execute(
        """
        SELECT spread
        FROM spread_snapshots
        WHERE symbol = ? AND snapshot_at >= ?
        ORDER BY snapshot_at
        """,
        (symbol, since.isoformat()),
    ).fetchall()
    values = sorted(float(row["spread"]) for row in rows)
    latest = latest_spread_snapshot(conn, symbol)
    if not values:
        return {
            "symbol": symbol,
            "hours": int(hours),
            "count": 0,
            "latest": latest,
            "min": None,
            "avg": None,
            "p50": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "max": None,
        }
    return {
        "symbol": symbol,
        "hours": int(hours),
        "count": len(values),
        "latest": latest,
        "min": values[0],
        "avg": sum(values) / len(values),
        "p50": percentile(values, 50),
        "p90": percentile(values, 90),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": values[-1],
    }


def percentile(sorted_values: list[float], percent: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * (percent / 100.0)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    weight = rank - low
    return sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight


def _row_to_snapshot(row: Row) -> dict[str, Any]:
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "broker_symbol": row["broker_symbol"],
        "bid": row["bid"],
        "ask": row["ask"],
        "spread": row["spread"],
        "snapshot_at": row["snapshot_at"],
        "source": row["source"],
        "metadata": metadata,
    }


def _iso(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return value
