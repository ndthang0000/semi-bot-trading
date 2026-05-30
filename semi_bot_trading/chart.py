from __future__ import annotations

import json
from sqlite3 import Connection
from typing import Any


CHART_PAYLOAD_VERSION = 1


def json_loads(value: str | None, default: Any) -> Any:
    if value in (None, ""):
        return default
    return json.loads(value)


def load_chart_candles(
    conn: Connection,
    symbol: str,
    timeframe: str,
    limit: int,
    start: str | None = None,
    end: str | None = None,
) -> list[dict[str, Any]]:
    clauses = ["symbol = ?", "timeframe = ?"]
    params: list[Any] = [symbol, timeframe]
    if start:
        clauses.append("open_time >= ?")
        params.append(start)
    if end:
        clauses.append("open_time <= ?")
        params.append(end)

    rows = conn.execute(
        f"""
        SELECT open_time, open, high, low, close, volume
        FROM (
            SELECT open_time, open, high, low, close, volume
            FROM candles
            WHERE {' AND '.join(clauses)}
            ORDER BY open_time DESC
            LIMIT ?
        )
        ORDER BY open_time
        """,
        (*params, limit),
    ).fetchall()
    return [
        {
            "time": row["open_time"],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]) if row["volume"] is not None else None,
        }
        for row in rows
    ]


def load_chart_structure(
    conn: Connection,
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, detector, status, point_type, price, event_time, confidence,
               related_zone_ids_json, metadata_json
        FROM structure_points
        WHERE symbol = ? AND timeframe = ? AND event_time >= ? AND event_time <= ?
        ORDER BY event_time
        """,
        (symbol, timeframe, start, end),
    ).fetchall()
    points: list[dict[str, Any]] = []
    for row in rows:
        metadata = json_loads(row["metadata_json"], {})
        points.append(
            {
                "id": row["id"],
                "time": row["event_time"],
                "type": row["point_type"],
                "price": float(row["price"]),
                "detector": row["detector"],
                "status": row["status"],
                "confidence": float(row["confidence"]),
                "direction": metadata.get("direction"),
                "related_zone_ids": json_loads(row["related_zone_ids_json"], []),
                "metadata": metadata,
            }
        )
    return points


def load_chart_zones(
    conn: Connection,
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    clauses = [
        "symbol = ?",
        "timeframe = ?",
        "start_time <= ?",
        "detected_at <= ?",
        "(end_time IS NULL OR end_time >= ?)",
    ]
    params: list[Any] = [symbol, timeframe, end, end, start]
    if active_only:
        clauses.append("(status = 'active' OR (end_time IS NOT NULL AND end_time > ?))")
        params.append(end)

    rows = conn.execute(
        f"""
        SELECT id, detector, zone_type, direction, price_low, price_high,
               start_time, end_time, valid_from, valid_until, invalidated_at,
               invalidated_by_structure_point_id, detected_at, effective_weight,
               effective_confidence, status, source, metadata_json
        FROM price_zones
        WHERE {' AND '.join(clauses)}
        ORDER BY status ASC, effective_weight DESC, detected_at DESC
        """,
        params,
    ).fetchall()
    zones: list[dict[str, Any]] = []
    for row in rows:
        status = row["status"]
        visual_end = row["end_time"]
        invalidated_at = row["invalidated_at"]
        if row["end_time"] is not None and row["end_time"] > end:
            status = "active"
            visual_end = None
            invalidated_at = None
        zones.append(
            {
            "id": row["id"],
            "type": row["zone_type"],
            "direction": row["direction"],
            "detector": row["detector"],
            "status": status,
            "source": row["source"],
            "price_low": float(row["price_low"]),
            "price_high": float(row["price_high"]),
            "visual_start": row["start_time"],
            "visual_end": visual_end,
            "valid_from": row["valid_from"],
            "valid_until": row["valid_until"],
            "invalidated_at": invalidated_at,
            "invalidated_by_structure_point_id": row["invalidated_by_structure_point_id"] if invalidated_at else None,
            "detected_at": row["detected_at"],
            "weight": float(row["effective_weight"]),
            "confidence": float(row["effective_confidence"]),
            "metadata": json_loads(row["metadata_json"], {}),
            }
        )
    return zones


def load_chart_contexts(conn: Connection, symbol: str) -> dict[str, dict[str, dict[str, Any]]]:
    rows = conn.execute(
        """
        SELECT timeframe, context_type, bot_value, primary_value, secondary_value,
               bot_confidence, effective_value, effective_confidence, source,
               valid_from, valid_until, status, metadata_json
        FROM market_contexts
        WHERE symbol = ? AND status = 'active'
        ORDER BY timeframe, context_type
        """,
        (symbol,),
    ).fetchall()
    contexts: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        timeframe_contexts = contexts.setdefault(row["timeframe"], {})
        timeframe_contexts[row["context_type"]] = {
            "bot_value": row["bot_value"],
            "primary_value": row["primary_value"],
            "secondary_value": row["secondary_value"],
            "bot_confidence": float(row["bot_confidence"]),
            "effective_value": row["effective_value"],
            "effective_confidence": float(row["effective_confidence"]),
            "source": row["source"],
            "valid_from": row["valid_from"],
            "valid_until": row["valid_until"],
            "status": row["status"],
            "metadata": json_loads(row["metadata_json"], {}),
        }
    return contexts


def load_chart_trades(conn: Connection, symbol: str, start: str, end: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT trade_orders.id, trade_orders.trade_idea_id, trade_orders.side,
               trade_orders.order_type, trade_orders.status, trade_orders.entry_price,
               trade_orders.stop_loss, trade_orders.take_profit_json,
               trade_orders.quantity, trade_orders.opened_at, trade_orders.closed_at,
               trade_orders.close_price, trade_orders.pnl, trade_orders.pnl_r,
               trade_orders.source, trade_orders.metadata_json,
               trade_ideas.playbook, trade_ideas.direction
        FROM trade_orders
        JOIN trade_ideas ON trade_ideas.id = trade_orders.trade_idea_id
        WHERE trade_orders.symbol = ?
          AND (
            (trade_orders.opened_at IS NOT NULL AND trade_orders.opened_at <= ?)
            OR (trade_orders.closed_at IS NOT NULL AND trade_orders.closed_at >= ?)
          )
        ORDER BY COALESCE(trade_orders.opened_at, trade_orders.created_at)
        """,
        (symbol, end, start),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "trade_idea_id": row["trade_idea_id"],
            "playbook": row["playbook"],
            "direction": row["direction"],
            "side": row["side"],
            "order_type": row["order_type"],
            "status": row["status"],
            "entry_price": float(row["entry_price"]) if row["entry_price"] is not None else None,
            "stop_loss": float(row["stop_loss"]),
            "take_profit": json_loads(row["take_profit_json"], []),
            "quantity": float(row["quantity"]),
            "opened_at": row["opened_at"],
            "closed_at": row["closed_at"],
            "close_price": float(row["close_price"]) if row["close_price"] is not None else None,
            "pnl": float(row["pnl"]) if row["pnl"] is not None else None,
            "pnl_r": float(row["pnl_r"]) if row["pnl_r"] is not None else None,
            "source": row["source"],
            "metadata": json_loads(row["metadata_json"], {}),
        }
        for row in rows
    ]


def build_chart_payload(
    conn: Connection,
    symbol: str,
    timeframe: str,
    limit: int,
    start: str | None = None,
    end: str | None = None,
    active_zones_only: bool = False,
    structure_timeframe: str | None = None,
) -> dict[str, Any]:
    candles = load_chart_candles(conn, symbol, timeframe, limit, start, end)
    if not candles:
        raise ValueError(f"No candles found for {symbol} {timeframe}")

    range_start = candles[0]["time"]
    range_end = candles[-1]["time"]
    effective_structure_timeframe = structure_timeframe or timeframe
    return {
        "version": CHART_PAYLOAD_VERSION,
        "symbol": symbol,
        "timeframe": timeframe,
        "range": {
            "start": range_start,
            "end": range_end,
            "limit": limit,
            "requested_start": start,
            "requested_end": end,
        },
        "layers": {
            "candles": candles,
            "structure": load_chart_structure(conn, symbol, effective_structure_timeframe, range_start, range_end),
            "structure_timeframe": effective_structure_timeframe,
            "zones": load_chart_zones(conn, symbol, timeframe, range_start, range_end, active_only=active_zones_only),
            "contexts": load_chart_contexts(conn, symbol),
            "trades": load_chart_trades(conn, symbol, range_start, range_end),
        },
    }
