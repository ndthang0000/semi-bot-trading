from __future__ import annotations

import json
from sqlite3 import Connection
from typing import Any

from .strategy import build_setup_candidates


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
    start_index: int | None = None,
) -> list[dict[str, Any]]:
    if start_index is not None and start is None and end is None:
        rows = conn.execute(
            """
            SELECT open_time, open, high, low, close, volume
            FROM candles
            WHERE symbol = ? AND timeframe = ?
            ORDER BY open_time
            LIMIT ? OFFSET ?
            """,
            (symbol, timeframe, limit, start_index),
        ).fetchall()
        return chart_candle_rows_to_dicts(rows)

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
    return chart_candle_rows_to_dicts(rows)


def chart_candle_rows_to_dicts(rows: list[Any]) -> list[dict[str, Any]]:
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
        "status != 'deleted'",
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
        metadata = json_loads(row["metadata_json"], {})
        status = row["status"]
        visual_end = row["end_time"]
        invalidated_at = row["invalidated_at"]
        deterministic_expiry = metadata.get("expired_rule") == "smc_zone_max_active_days" or (
            metadata.get("max_active_days") is not None and row["valid_until"] == row["end_time"]
        )
        if row["end_time"] is not None and row["end_time"] > end and not deterministic_expiry:
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
            "metadata": metadata,
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


def load_chart_trades(
    conn: Connection,
    symbol: str,
    start: str,
    end: str,
    allowed_playbooks: set[str] | None = None,
) -> list[dict[str, Any]]:
    playbook_clause = ""
    params: list[Any] = [symbol, end, start]
    if allowed_playbooks is not None:
        if not allowed_playbooks:
            return []
        placeholders = ", ".join("?" for _ in allowed_playbooks)
        playbook_clause = f" AND trade_ideas.playbook IN ({placeholders})"
        params.extend(sorted(allowed_playbooks))

    rows = conn.execute(
        f"""
        SELECT trade_orders.id, trade_orders.trade_idea_id, trade_orders.side,
               trade_orders.order_type, trade_orders.status, trade_orders.entry_price,
               trade_orders.stop_loss, trade_orders.take_profit_json,
               trade_orders.quantity, trade_orders.opened_at, trade_orders.closed_at,
               trade_orders.close_price, trade_orders.pnl, trade_orders.pnl_r,
               trade_orders.source, trade_orders.metadata_json,
               trade_ideas.playbook, trade_ideas.direction,
               trade_reviews.id AS review_id,
               trade_reviews.grade AS review_grade,
               trade_reviews.verdict AS review_verdict,
               trade_reviews.mistake_tags_json AS review_mistake_tags_json,
               trade_reviews.should_trade_again AS review_should_trade_again,
               trade_reviews.comment AS review_comment,
               trade_reviews.reviewer AS review_reviewer,
               trade_reviews.created_at AS review_created_at,
               trade_reviews.updated_at AS review_updated_at
        FROM trade_orders
        JOIN trade_ideas ON trade_ideas.id = trade_orders.trade_idea_id
        LEFT JOIN trade_reviews ON trade_reviews.trade_order_id = trade_orders.id
        WHERE trade_orders.symbol = ?
          AND trade_orders.opened_at IS NOT NULL
          AND trade_orders.opened_at <= ?
          AND (trade_orders.closed_at IS NULL OR trade_orders.closed_at >= ?)
          {playbook_clause}
        ORDER BY COALESCE(trade_orders.opened_at, trade_orders.created_at)
        """,
        params,
    ).fetchall()
    return [trade_order_row_to_chart(row) for row in rows]


def trade_order_row_to_chart(row: Any) -> dict[str, Any]:
    result = {
        "id": row["id"],
        "trade_idea_id": row["trade_idea_id"],
        "playbook": row["playbook"],
        "direction": row["direction"],
        "side": row["side"],
        "order_type": row["order_type"],
        "status": row["status"],
        "entry_price": float(row["entry_price"]) if row["entry_price"] is not None else None,
        "stop_loss": float(row["stop_loss"]) if row["stop_loss"] is not None else None,
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
    if row_has_key(row, "review_id") and row["review_id"] is not None:
        result["review"] = {
            "id": row["review_id"],
            "trade_order_id": row["id"],
            "grade": row["review_grade"],
            "verdict": row["review_verdict"],
            "mistake_tags": json_loads(row["review_mistake_tags_json"], []),
            "should_trade_again": row["review_should_trade_again"],
            "comment": row["review_comment"] or "",
            "reviewer": row["review_reviewer"],
            "created_at": row["review_created_at"],
            "updated_at": row["review_updated_at"],
        }
    else:
        result["review"] = None
    return result


def row_has_key(row: Any, key: str) -> bool:
    if hasattr(row, "keys"):
        return key in row.keys()
    return key in row


def build_chart_payload(
    conn: Connection,
    symbol: str,
    timeframe: str,
    limit: int,
    start: str | None = None,
    end: str | None = None,
    start_index: int | None = None,
    active_zones_only: bool = False,
    structure_timeframe: str | None = None,
    strategy_config: Any | None = None,
    allowed_playbooks: set[str] | None = None,
) -> dict[str, Any]:
    candles = load_chart_candles(conn, symbol, timeframe, limit, start, end, start_index)
    if not candles:
        raise ValueError(f"No candles found for {symbol} {timeframe}")

    range_start = candles[0]["time"]
    range_end = candles[-1]["time"]
    effective_structure_timeframe = structure_timeframe or timeframe
    zones = load_chart_zones(conn, symbol, timeframe, range_start, range_end, active_only=active_zones_only)
    contexts = load_chart_contexts(conn, symbol)
    setup_candidates: list[dict[str, Any]] = []
    if strategy_config is not None:
        strategy_candles = load_chart_candles(conn, symbol, strategy_config.timeframe, 240, end=range_end)
        if strategy_candles:
            setup_candidates = build_setup_candidates(
                symbol=symbol,
                zones=zones,
                contexts=contexts,
                candles=strategy_candles,
                structure_points=load_chart_structure(
                    conn,
                    symbol,
                    strategy_config.timeframe,
                    strategy_candles[0]["time"],
                    strategy_candles[-1]["time"],
                ),
                config=strategy_config,
                context_timeframe=effective_structure_timeframe,
                allowed_playbooks=allowed_playbooks,
            )
    return {
        "version": CHART_PAYLOAD_VERSION,
        "symbol": symbol,
        "timeframe": timeframe,
        "range": {
            "start": range_start,
            "end": range_end,
            "limit": limit,
            "start_index": start_index,
            "requested_start": start,
            "requested_end": end,
        },
        "layers": {
            "candles": candles,
            "structure": load_chart_structure(conn, symbol, effective_structure_timeframe, range_start, range_end),
            "structure_timeframe": effective_structure_timeframe,
            "zones": zones,
            "contexts": contexts,
            "trades": load_chart_trades(conn, symbol, range_start, range_end, allowed_playbooks=allowed_playbooks),
            "setup_candidates": setup_candidates,
        },
    }
