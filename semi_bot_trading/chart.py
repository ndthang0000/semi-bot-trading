from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from sqlite3 import Connection
from typing import Any

from .context import score_macro_trend
from .indicators import latest_rsi_snapshot
from .strategy import average_body, build_setup_candidates, candle_body
from .zones import CandleSlice, latest_atr


CHART_PAYLOAD_VERSION = 1
MAX_TOUCH_ONLY_M15_TRIGGER_OVERLAYS = 500


def build_m15_signal_snapshot(
    candles: list[dict[str, Any]],
    setup_candidates: list[dict[str, Any]],
    avg_body_period: int = 20,
) -> dict[str, Any] | None:
    """Describe the last closed M15 candle and its best zone-trigger candidate.

    The dashboard intentionally receives closed-candle data only. Live/forming
    candles can be useful for chart touch overlays, but they must not look like
    a confirmed strategy trigger before the worker can evaluate them.
    """
    if not candles:
        return None
    candle = candles[-1]
    period = max(int(avg_body_period), 1)
    average = average_body(candles, period)
    body = candle_body(candle)
    body_ratio = body / average if average > 0 else None
    close = float(candle["close"])
    open_ = float(candle["open"])
    direction = "bullish" if close > open_ else "bearish" if close < open_ else "doji"

    status_priority = {
        "eligible": 0,
        "waiting_confirmation": 1,
        "blocked": 2,
        "watching": 3,
        "approaching": 4,
    }
    best_candidate = min(
        setup_candidates,
        key=lambda candidate: (
            status_priority.get(str(candidate.get("status") or ""), 9),
            -float(candidate.get("score") or 0.0),
            str(candidate.get("id") or ""),
        ),
        default=None,
    )
    result: dict[str, Any] = {
        "candle_time": candle["time"],
        "candle_close_time": candle.get("close_time"),
        "candle_closed": True,
        "open": open_,
        "high": float(candle["high"]),
        "low": float(candle["low"]),
        "close": close,
        "candle_direction": direction,
        "avg_body_period": period,
        "avg_body": round(average, 5),
        "body": round(body, 5),
        "body_avg_ratio": round(body_ratio, 4) if body_ratio is not None else None,
        "candidate_count": len(setup_candidates),
        "candidate_id": None,
        "status": "watching",
        "reaction_state": None,
        "trigger_method": None,
        "trigger_candle_time": None,
        "trigger_is_latest_closed_candle": False,
        "trigger_avg_body": None,
        "trigger_body": None,
        "trigger_body_avg_ratio": None,
        "strength_size": None,
        "strength_avg_ratio": None,
        "zone_id": None,
        "zone_type": None,
        "reason": None,
    }
    if best_candidate is None:
        return result

    metadata = best_candidate.get("metadata") if isinstance(best_candidate.get("metadata"), dict) else {}
    reasons = best_candidate.get("reason") if isinstance(best_candidate.get("reason"), list) else []
    reaction_state = str(best_candidate.get("zone_reaction_state") or metadata.get("reaction_v2") or "")
    trigger_method = str(metadata.get("reaction_trigger_method") or "")
    if not trigger_method:
        if metadata.get("wick_reject_confirmed") is True:
            trigger_method = "confirmed_wick"
        elif reaction_state == "internal_reject":
            trigger_method = "strong_body"
        elif any("strong " in str(reason).lower() and "rejection" in str(reason).lower() for reason in reasons):
            trigger_method = "strong_body"
    trigger_time = str(metadata.get("reaction_candle_time") or "")
    reaction_body = _optional_float(metadata.get("reaction_body"))
    reaction_average = _optional_float(metadata.get("reaction_avg_body"))
    reaction_body_ratio = _optional_float(metadata.get("reaction_body_avg_ratio"))
    rejection_size = _optional_float(metadata.get("reaction_rejection_size"))
    rejection_ratio = _optional_float(metadata.get("reaction_rejection_avg_ratio"))
    if trigger_method == "pinbar":
        strength_size = rejection_size
        strength_ratio = rejection_ratio
    elif trigger_method == "confirmed_wick":
        strength_size = _optional_float(metadata.get("wick_reject_rejection_size"))
        strength_ratio = _optional_float(metadata.get("wick_reject_rejection_avg_ratio"))
    else:
        strength_size = reaction_body
        strength_ratio = reaction_body_ratio

    result.update(
        {
            "candidate_id": best_candidate.get("id"),
            "status": best_candidate.get("status"),
            "reaction_state": reaction_state or None,
            "trigger_method": trigger_method or None,
            "trigger_candle_time": trigger_time or None,
            "trigger_is_latest_closed_candle": trigger_time == str(candle["time"]),
            "trigger_avg_body": round(reaction_average, 5) if reaction_average is not None else None,
            "trigger_body": round(reaction_body, 5) if reaction_body is not None else None,
            "trigger_body_avg_ratio": round(reaction_body_ratio, 4) if reaction_body_ratio is not None else None,
            "strength_size": round(strength_size, 5) if strength_size is not None else None,
            "strength_avg_ratio": round(strength_ratio, 4) if strength_ratio is not None else None,
            "zone_id": best_candidate.get("primary_zone_id"),
            "zone_type": metadata.get("zone_type"),
            "reason": str(reasons[0]) if reasons else None,
        }
    )
    return result


def _optional_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def compute_live_macro_trend_context(
    conn: Connection,
    symbol: str,
    macro_trend_config: Any,
    end: str | None = None,
) -> dict[str, Any] | None:
    """Compute a chart-context dict for macro trend straight from candles.

    Used as a fallback so the dashboard always shows a fresh macro trend even
    when no `detect-macro-trend` CLI run has persisted one to market_contexts.
    """
    limit = macro_trend_config.lookback_candles + macro_trend_config.atr_period + 2
    candles = load_chart_candles(conn, symbol, macro_trend_config.timeframe, limit, end=end)
    if not candles:
        return None
    candle_rows = [
        {
            "open_time": candle["time"],
            "high": candle["high"],
            "low": candle["low"],
            "close": candle["close"],
        }
        for candle in candles
    ]
    score = score_macro_trend(
        candle_rows,
        macro_trend_config.lookback_candles,
        macro_trend_config.flat_threshold_atr,
        macro_trend_config.atr_period,
    )
    value = str(score["value"])
    confidence = float(score["confidence"])
    return {
        "bot_value": value,
        "primary_value": value,
        "secondary_value": None,
        "bot_confidence": confidence,
        "effective_value": value,
        "effective_confidence": confidence,
        "source": "bot",
        "valid_from": str(candles[-1]["time"]),
        "valid_until": None,
        "status": "active",
        "metadata": {
            "detector": "macro_trend_v1_live",
            "version": 1,
            "lookback_candles": score["lookback_candles"],
            "momentum": score["momentum"],
            "momentum_atr": score["momentum_atr"],
            "atr": score["atr"],
            "reference_time": score["reference_time"],
        },
    }


def json_loads(value: str | None, default: Any) -> Any:
    if value in (None, ""):
        return default
    return json.loads(value)


def load_live_candle(
    conn: Connection,
    symbol: str,
    timeframe: str,
) -> dict[str, Any] | None:
    """Return the currently forming (live) candle from live_candles, or None."""
    row = conn.execute(
        """
        SELECT open_time, open, high, low, close, volume
        FROM live_candles
        WHERE symbol = ? AND timeframe = ?
        """,
        (symbol, timeframe),
    ).fetchone()
    if row is None:
        return None
    return {
        "time": row["open_time"],
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"]) if row["volume"] is not None else None,
    }


def build_atr_snapshot(
    conn: Connection,
    symbol: str,
    timeframes: list[str],
    period: int = 14,
    end: str | None = None,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for timeframe in timeframes:
        candles = load_chart_candles(conn, symbol, timeframe, period + 2, end=end)
        atr_value = latest_atr(
            [
                CandleSlice(
                    open_time=candle["time"],
                    high=candle["high"],
                    low=candle["low"],
                    close=candle["close"],
                    open=candle["open"],
                )
                for candle in candles
            ],
            period=period,
        )
        result[timeframe] = {
            "period": period,
            "value": round(float(atr_value), 5) if atr_value is not None else None,
            "as_of": candles[-1]["time"] if candles else None,
        }
    return result


def build_rsi_snapshot(
    conn: Connection,
    symbol: str,
    timeframes: list[str],
    period: int = 14,
    slope_periods: tuple[int, ...] = (3, 5),
    end: str | None = None,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    limit = period + max(slope_periods, default=0) + 5
    for timeframe in timeframes:
        candles = load_chart_candles(conn, symbol, timeframe, limit, end=end)
        result[timeframe] = latest_rsi_snapshot(candles, period=period, slope_periods=slope_periods)
    return result


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
            SELECT open_time, close_time, open, high, low, close, volume
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
        SELECT open_time, close_time, open, high, low, close, volume
        FROM (
            SELECT open_time, close_time, open, high, low, close, volume
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
            "close_time": row["close_time"],
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
    if timeframe.upper() != "H1":
        return []
    clauses = [
        "symbol = ?",
        "timeframe = ?",
        "status != 'deleted'",
        "start_time <= ?",
        "detected_at <= ?",
        "(status = 'draft' OR end_time IS NULL OR end_time >= ?)",
    ]
    params: list[Any] = [symbol, timeframe, end, end, start]
    if active_only:
        # Drafts are deliberately excluded here because live workers request
        # active-only chart payloads for strategy evaluation.
        clauses.append(
            "(status = 'active' OR (status NOT IN ('draft', 'disabled') AND end_time IS NOT NULL AND end_time > ?))"
        )
        clauses.append("(status != 'active' OR valid_until > ?)")
        params.append(end)
        params.append(end)

    rows = conn.execute(
        f"""
        SELECT id, detector, zone_type, direction, price_low, price_high,
               start_time, end_time, valid_from, valid_until, invalidated_at,
               invalidated_by_structure_point_id, detected_at, effective_weight,
               effective_confidence, status, source, metadata_json, created_at, updated_at
        FROM price_zones
        WHERE {' AND '.join(clauses)}
        ORDER BY status ASC, effective_weight DESC, detected_at DESC
        """,
        params,
    ).fetchall()
    zones: list[dict[str, Any]] = []
    for row in rows:
        metadata = json_loads(row["metadata_json"], {})
        is_bot_sr = (
            row["zone_type"] in ("support", "resistance")
            and row["source"] != "human"
            and row["detector"] != "human_manual_v1"
        )
        visual_start = row["detected_at"] if is_bot_sr and row["detected_at"] else row["start_time"]
        projection = project_zone_lifecycle_for_chart(row, metadata, end, is_bot_sr=is_bot_sr)
        status = projection["status"]
        visual_end = projection["visual_end"]
        invalidated_at = projection["invalidated_at"]
        zones.append(
            {
            "id": row["id"],
            "type": row["zone_type"],
            "timeframe": timeframe,
            "direction": row["direction"],
            "detector": row["detector"],
            "status": status,
            "source": row["source"],
            "price_low": float(row["price_low"]),
            "price_high": float(row["price_high"]),
            "visual_start": visual_start,
            "visual_end": visual_end,
            "valid_from": row["valid_from"],
            "valid_until": row["valid_until"],
            "invalidated_at": invalidated_at,
            "invalidated_by_structure_point_id": row["invalidated_by_structure_point_id"] if invalidated_at else None,
            "detected_at": row["detected_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "weight": float(row["effective_weight"]),
            "confidence": float(row["effective_confidence"]),
            "metadata": metadata,
            }
        )
    return zones


def attach_liquidity_sweep_states(conn: Connection, zones: list[dict[str, Any]]) -> None:
    """Attach the newest account-scoped runtime state for dashboard inspection."""
    liquidity_zone_ids = [zone["id"] for zone in zones if zone["type"] == "liquidity_pool"]
    if not liquidity_zone_ids:
        return
    placeholders = ",".join("?" for _ in liquidity_zone_ids)
    rows = conn.execute(
        f"""
        SELECT * FROM liquidity_sweep_states
        WHERE zone_id IN ({placeholders})
        ORDER BY updated_at DESC
        """,
        liquidity_zone_ids,
    ).fetchall()
    newest_by_zone: dict[str, Any] = {}
    for row in rows:
        newest_by_zone.setdefault(str(row["zone_id"]), row)
    for zone in zones:
        row = newest_by_zone.get(str(zone["id"]))
        if row is None:
            continue
        zone["metadata"]["liquidity_sweep_state"] = {
            "account_label": row["account_label"],
            "state": row["state"],
            "touched_lower_at": row["touched_lower_at"],
            "deadline_at": row["deadline_at"],
            "atr_at_touch": row["atr_at_touch"],
            "deepest_bid": row["deepest_bid"],
            "invalidation_price": row["invalidation_price"],
            "reclaimed_at": row["reclaimed_at"],
            "terminal_reason": row["terminal_reason"],
            "updated_at": row["updated_at"],
        }


def project_zone_lifecycle_for_chart(
    row: Any,
    metadata: dict[str, Any],
    range_end: str,
    *,
    is_bot_sr: bool,
) -> dict[str, str | None]:
    """Project persisted lifecycle fields into chart-only presentation values.

    `end_time` is exposed as `visual_end`; strategy code must use status,
    valid_until, and invalidated_at instead of this projection.
    """
    status = str(row["status"])
    visual_end = row["end_time"]
    invalidated_at = row["invalidated_at"]
    deterministic_expiry = metadata.get("expired_rule") == "smc_zone_max_active_days" or (
        metadata.get("max_active_days") is not None and row["valid_until"] == row["end_time"]
    )
    if (
        status != "draft"
        and row["end_time"] is not None
        and row["end_time"] > range_end
        and not deterministic_expiry
    ):
        # A historical chart window may predate the lifecycle event persisted
        # today. At that point in time the zone was still active.
        status = "active"
        invalidated_at = None
        is_human_zone = row["source"] == "human" or metadata.get("human_created") is True
        if is_human_zone:
            visual_end = row["end_time"]
        elif is_bot_sr:
            visual_end = row["valid_until"] or row["end_time"]
        else:
            visual_end = None
    return {
        "status": status,
        "visual_end": visual_end,
        "invalidated_at": invalidated_at,
    }


def merge_zones_by_id(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for zone in group:
            zone_id = str(zone.get("id") or "")
            if zone_id and zone_id in seen:
                continue
            if zone_id:
                seen.add(zone_id)
            merged.append(zone)
    return merged


def build_m15_trigger_overlays(
    conn: Connection,
    symbol: str,
    chart_timeframe: str,
    context_timeframe: str,
    range_start: str,
    range_end: str,
    zones: list[dict[str, Any]],
    setup_candidates: list[dict[str, Any]],
    include_live_candle: bool = False,
) -> list[dict[str, Any]]:
    if chart_timeframe.upper() != context_timeframe.upper() or context_timeframe.upper() != "H1":
        return []
    if not zones:
        return []

    candidates_by_zone_time: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in setup_candidates:
        zone_id = str(candidate.get("primary_zone_id") or "")
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        reaction_time = str(metadata.get("reaction_candle_time") or "")
        if zone_id and reaction_time:
            candidates_by_zone_time[(zone_id, reaction_time)] = candidate

    candles = load_chart_candles(conn, symbol, "M15", 5000, start=range_start, end=range_end)
    # In latest mode the still-forming M15 candle is the one most likely to be
    # touching a zone a human just drew, so include it for immediate feedback —
    # otherwise the marker only appears once that M15 candle closes.
    if include_live_candle:
        live_candle = load_live_candle(conn, symbol, "M15")
        if live_candle is not None and (not candles or live_candle["time"] > candles[-1]["time"]):
            candles = [*candles, live_candle]
    candidate_overlays: list[dict[str, Any]] = []
    touch_overlays: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for candle in candles:
        high = float(candle["high"])
        low = float(candle["low"])
        for zone in zones:
            zone_id = str(zone.get("id") or "")
            if not zone_id:
                continue
            if high < float(zone["price_low"]) or low > float(zone["price_high"]):
                continue
            key = (zone_id, str(candle["time"]))
            if key in seen:
                continue
            seen.add(key)
            candidate = candidates_by_zone_time.get(key)
            metadata = candidate.get("metadata", {}) if candidate else {}
            overlay = {
                "time": candle["time"],
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "zone_id": zone_id,
                "zone_type": zone.get("type"),
                "reaction_state": candidate.get("zone_reaction_state") if candidate else "touch",
                "candidate_id": candidate.get("id") if candidate else None,
                "status": candidate.get("status") if candidate else "touch",
                "reason": list(candidate.get("reason") or [])[:3] if candidate else ["M15 candle touched H1 zone."],
                "direction": candidate.get("direction") if candidate else zone.get("direction"),
                "metadata": {
                    "reaction_open": metadata.get("reaction_open"),
                    "reaction_high": metadata.get("reaction_high"),
                    "reaction_low": metadata.get("reaction_low"),
                    "reaction_close": metadata.get("reaction_close"),
                    "trigger_types": metadata.get("trigger_types"),
                },
            }
            if candidate:
                candidate_overlays.append(overlay)
            else:
                touch_overlays.append(overlay)
    capped_touch_overlays = touch_overlays[-MAX_TOUCH_ONLY_M15_TRIGGER_OVERLAYS:]
    return sorted(
        [*capped_touch_overlays, *candidate_overlays],
        key=lambda item: (str(item.get("time") or ""), str(item.get("zone_id") or "")),
    )


def load_chart_contexts(conn: Connection, symbol: str, as_of: str | None = None) -> dict[str, dict[str, dict[str, Any]]]:
    as_of_iso = as_of or datetime.now(UTC).replace(microsecond=0).isoformat()
    rows = conn.execute(
        """
        SELECT timeframe, context_type, bot_value, primary_value, secondary_value,
               bot_confidence, effective_value, effective_confidence, source,
               valid_from, valid_until, status, metadata_json
        FROM market_contexts
        WHERE symbol = ?
          AND status = 'active'
          AND (valid_until IS NULL OR valid_until > ?)
        ORDER BY timeframe, context_type,
                 CASE source WHEN 'bot' THEN 0 WHEN 'human' THEN 1 WHEN 'news_calendar' THEN 2 ELSE 1 END
        """,
        (symbol, as_of_iso),
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
               trade_orders.account_label,
               trade_orders.order_type, trade_orders.status, trade_orders.entry_price,
               trade_orders.stop_loss, trade_orders.take_profit_json,
               trade_orders.quantity, trade_orders.opened_at, trade_orders.closed_at,
               trade_orders.close_price, trade_orders.pnl, trade_orders.pnl_r,
               trade_orders.hidden_on_chart, trade_orders.source, trade_orders.metadata_json,
               trade_ideas.playbook, trade_ideas.direction,
               trade_reviews.id AS review_id,
               trade_reviews.grade AS review_grade,
               trade_reviews.verdict AS review_verdict,
               trade_reviews.mistake_tags_json AS review_mistake_tags_json,
               trade_reviews.should_trade_again AS review_should_trade_again,
               trade_reviews.comment AS review_comment,
               trade_reviews.metadata_json AS review_metadata_json,
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


def load_live_traded_candidate_refs(
    conn: Connection,
    symbol: str,
    account_label: str | None = None,
) -> tuple[set[str], set[str]]:
    account_clause = ""
    params: list[Any] = [symbol]
    if account_label is not None:
        account_clause = " AND trade_orders.account_label = ?"
        params.append(account_label)
    rows = conn.execute(
        f"""
        SELECT trade_orders.metadata_json, trade_ideas.context_snapshot_json
        FROM trade_orders
        JOIN trade_ideas ON trade_ideas.id = trade_orders.trade_idea_id
        WHERE trade_orders.symbol = ?
          AND trade_orders.source = 'live'
          AND trade_orders.opened_at IS NOT NULL
          AND trade_orders.status IN ('filled', 'pending_fill')
          {account_clause}
        """,
        params,
    ).fetchall()
    candidate_ids: set[str] = set()
    zone_ids: set[str] = set()
    for row in rows:
        metadata = json_loads(row["metadata_json"], {})
        candidate_id = metadata.get("candidate_id")
        if candidate_id:
            candidate_ids.add(str(candidate_id))
        candidate_metadata = metadata.get("candidate_metadata")
        if isinstance(candidate_metadata, dict):
            zone_id = candidate_metadata.get("primary_zone_id")
            if zone_id:
                zone_ids.add(str(zone_id))
        snapshot = json_loads(row["context_snapshot_json"], {})
        candidate = snapshot.get("candidate")
        if isinstance(candidate, dict):
            snapshot_candidate_id = candidate.get("id")
            if snapshot_candidate_id:
                candidate_ids.add(str(snapshot_candidate_id))
            snapshot_zone_id = candidate.get("primary_zone_id")
            if snapshot_zone_id:
                zone_ids.add(str(snapshot_zone_id))
    return candidate_ids, zone_ids


def filter_traded_setup_candidates(
    conn: Connection,
    symbol: str,
    candidates: list[dict[str, Any]],
    account_label: str | None = None,
) -> list[dict[str, Any]]:
    if not candidates:
        return candidates
    traded_candidate_ids, traded_zone_ids = load_live_traded_candidate_refs(conn, symbol, account_label=account_label)
    if not traded_candidate_ids and not traded_zone_ids:
        return candidates
    return [
        candidate
        for candidate in candidates
        if str(candidate.get("id")) not in traded_candidate_ids
        and str(candidate.get("primary_zone_id")) not in traded_zone_ids
    ]


def trade_order_row_to_chart(row: Any) -> dict[str, Any]:
    result = {
        "id": row["id"],
        "trade_idea_id": row["trade_idea_id"],
        "account_label": row["account_label"] if row_has_key(row, "account_label") else "Default",
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
        "hidden_on_chart": bool(row["hidden_on_chart"]) if row_has_key(row, "hidden_on_chart") else False,
        "source": row["source"],
        "metadata": json_loads(row["metadata_json"], {}),
    }
    if row_has_key(row, "review_id") and row["review_id"] is not None:
        review_metadata = json_loads(row["review_metadata_json"], {}) if row_has_key(row, "review_metadata_json") else {}
        if not isinstance(review_metadata, dict):
            review_metadata = {}
        strategy_review = review_metadata.get("strategy_review") if isinstance(review_metadata.get("strategy_review"), dict) else {}
        operator_review = review_metadata.get("operator_review") if isinstance(review_metadata.get("operator_review"), dict) else {}
        review_metadata = {**review_metadata, "strategy_review": strategy_review, "operator_review": operator_review}
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
            "metadata": review_metadata,
            "strategy_review": strategy_review,
            "operator_review": operator_review,
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
    candidate_zone_timeframes: set[str] | None = None,
    allowed_playbooks: set[str] | None = None,
    macro_trend_config: Any | None = None,
    include_live_strategy_candle: bool = False,
    traded_account_label: str | None = None,
) -> dict[str, Any]:
    candles = load_chart_candles(conn, symbol, timeframe, limit, start, end, start_index)
    if not candles:
        raise ValueError(f"No candles found for {symbol} {timeframe}")

    # In latest mode (no historical window), append the forming candle from live_candles
    # so the UI always shows the in-progress bar even before it closes.
    is_latest_mode = start_index is None and start is None and end is None
    if is_latest_mode:
        live_candle = load_live_candle(conn, symbol, timeframe)
        if live_candle is not None and live_candle["time"] > candles[-1]["time"]:
            candles = [*candles, live_candle]

    range_start = candles[0]["time"]
    range_end = candles[-1]["time"]
    effective_structure_timeframe = structure_timeframe or "H1"
    zones = load_chart_zones(conn, symbol, effective_structure_timeframe, range_start, range_end, active_only=active_zones_only)
    if is_latest_mode:
        attach_liquidity_sweep_states(conn, zones)
    context_as_of = None if is_latest_mode else range_end
    contexts = load_chart_contexts(conn, symbol, as_of=context_as_of)
    if macro_trend_config is not None:
        macro_timeframe = str(macro_trend_config.timeframe)
        # Persisted contexts (including human overrides) win; the live value is a fallback.
        if "macro_trend" not in contexts.get(macro_timeframe, {}):
            live_macro = compute_live_macro_trend_context(conn, symbol, macro_trend_config)
            if live_macro is not None:
                contexts.setdefault(macro_timeframe, {})["macro_trend"] = live_macro
    strategy_end = None if is_latest_mode else range_end
    strategy_timeframe = str(strategy_config.timeframe) if strategy_config is not None else "M15"
    closed_strategy_candles = load_chart_candles(conn, symbol, strategy_timeframe, 240, end=strategy_end)
    strategy_candles = list(closed_strategy_candles)
    raw_setup_candidates: list[dict[str, Any]] = []
    setup_candidates: list[dict[str, Any]] = []
    if strategy_config is not None:
        zone_groups_by_timeframe: dict[str, list[dict[str, Any]]] = {effective_structure_timeframe: zones}
        # H1 is the only zone/context timeframe. M15 remains the strategy
        # trigger timeframe, but it must never contribute price_zones.
        candidate_timeframes = candidate_zone_timeframes or {effective_structure_timeframe}
        for zone_timeframe in sorted(candidate_timeframes):
            if zone_timeframe not in zone_groups_by_timeframe:
                zone_groups_by_timeframe[zone_timeframe] = load_chart_zones(
                    conn,
                    symbol,
                    zone_timeframe,
                    range_start,
                    range_end,
                    active_only=active_zones_only,
                )
        candidate_zones = merge_zones_by_id(
            *[zone_groups_by_timeframe[zone_timeframe] for zone_timeframe in sorted(candidate_timeframes)]
        )
        # Latest chart mode should evaluate setup candidates from the latest closed
        # strategy candle, not from the H1 chart range end. Otherwise M15 touches
        # after the current H1 candle opens are invisible until the next H1 close.
        if include_live_strategy_candle and is_latest_mode:
            live_strategy_candle = load_live_candle(conn, symbol, strategy_config.timeframe)
            if live_strategy_candle is not None and (
                not strategy_candles or live_strategy_candle["time"] > strategy_candles[-1]["time"]
            ):
                strategy_candles = [*strategy_candles, live_strategy_candle]
        context_candles = load_chart_candles(conn, symbol, effective_structure_timeframe, 240, end=range_end)
        if strategy_candles:
            raw_setup_candidates = build_setup_candidates(
                symbol=symbol,
                zones=candidate_zones,
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
                context_candles=context_candles,
            )
            setup_candidates = filter_traded_setup_candidates(
                conn,
                symbol,
                raw_setup_candidates,
                account_label=traded_account_label,
            )
    avg_body_period = (
        int(getattr(strategy_config, "zone_reaction_v2_reject_avg_body_period", 20))
        if strategy_config is not None
        else 20
    )
    m15_signal = build_m15_signal_snapshot(
        closed_strategy_candles,
        raw_setup_candidates,
        avg_body_period=avg_body_period,
    )
    m15_triggers = build_m15_trigger_overlays(
        conn,
        symbol,
        timeframe,
        effective_structure_timeframe,
        range_start,
        range_end,
        zones,
        setup_candidates,
        include_live_candle=is_latest_mode,
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
            "atr": build_atr_snapshot(conn, symbol, ["H1", "M15"], period=14, end=range_end),
            "rsi": build_rsi_snapshot(conn, symbol, ["H1"], period=14, end=range_end),
            "trades": load_chart_trades(conn, symbol, range_start, range_end, allowed_playbooks=allowed_playbooks),
            "setup_candidates": setup_candidates,
            "m15_triggers": m15_triggers,
            "m15_signal": m15_signal,
        },
    }
