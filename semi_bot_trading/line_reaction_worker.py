"""Account-scoped Line Reaction processing with durable execution claims."""

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from .chart import build_wave_metrics, load_chart_candles, load_chart_structure
from .line_reaction import PLAYBOOK, SESSION_ENDED_BEFORE_EXECUTION, dt, evaluate_line, price_line
from .line_reaction_api import row_api
from .strategy.helpers import chart_candles_to_slices
from .trading_sessions import selected_session_end
from .zones import latest_atr


ACTIVE_STATUSES = frozenset(
    {"armed", "executing", "pending", "open", "cancel_requested", "reconciliation_required"}
)
UNKNOWN_INTENT_ERROR = (
    "Execution state is uncertain after worker interruption. Check MT5 before resolving this Line."
)


def process_line_reactions(conn, config, env, client, broker_symbol, now):
    """Advance every active Line Reaction plan for one worker account."""
    from .live_worker import live_trade_idea_id, manual_ai_risk_pct, maybe_execute_candidates

    rows = conn.execute(
        """SELECT * FROM line_reaction_plans
        WHERE account_label=? AND symbol=?
          AND status IN ('armed','executing','pending','open','cancel_requested','reconciliation_required')
        ORDER BY created_at,id""",
        (env.account_label, config.symbol),
    ).fetchall()
    for raw in rows:
        line = row_api(raw)
        idea_id = live_trade_idea_id(line["id"], account_label=env.account_label)
        order = conn.execute(
            "SELECT * FROM trade_orders WHERE trade_idea_id=? ORDER BY created_at DESC LIMIT 1",
            (idea_id,),
        ).fetchone()
        # A hard-disabled worker may inspect persisted intents, but must never
        # issue broker mutations such as pending-order cancellation.
        if order is not None and not env.execution_enabled:
            continue
        if _reconcile_trade_order(conn, line, order, client, broker_symbol, now):
            continue

        request = conn.execute(
            """SELECT id,status,failure_reason,created_at,updated_at
            FROM execution_requests WHERE trade_idea_id=? ORDER BY created_at DESC LIMIT 1""",
            (idea_id,),
        ).fetchone()
        if _reconcile_execution_request(
            conn, line, request, client, broker_symbol, env.mt5_magic,
            config.strategy.line_reaction_v1_pending_intent_grace_minutes, now,
        ):
            continue
        if _stop_expired_or_cancelled_line(conn, line, now):
            continue
        if not env.execution_enabled:
            continue
        if not config.strategy.line_reaction_v1_enabled:
            continue

        session_close = selected_session_end(line["config"]["trade_sessions"], now.isoformat())
        if session_close is None:
            _clear_unsubmitted_signal_after_session(conn, line, now)
            continue

        signal = line["signal"]
        if signal is None:
            signal = _detect_line_signal(conn, config, line, now)
            if signal is None or not _claim_line_signal(conn, line["id"], signal, now):
                continue
            line["signal"] = signal
            line["status"] = "executing"

        if now >= dt(signal["signal_close_time"]) + timedelta(minutes=15):
            transition_line(conn, line["id"], {"executing"}, "expired", now)
            continue

        _submit_line_candidate(
            conn, config, env, client, broker_symbol, line, signal, session_close,
            idea_id, now, maybe_execute_candidates, manual_ai_risk_pct(env.account_profile),
        )


def _reconcile_trade_order(conn, line, order, client, broker_symbol, now: datetime) -> bool:
    """Synchronize a Line that already has a durable trade order."""
    if order is None:
        return False
    if order["status"] == "filled":
        transition_line(conn, line["id"], ACTIVE_STATUSES, "open", now)
        return True
    if order["status"] != "pending_fill":
        next_status = "closed" if order["status"] == "closed" else "cancelled"
        transition_line(conn, line["id"], ACTIVE_STATUSES, next_status, now)
        return True

    expiry = dt(line["expires_at"])
    if line["signal"]:
        signal_expiry = dt(line["signal"]["signal_close_time"]) + timedelta(
            minutes=line["config"]["limit_ttl_minutes"]
        )
        expiry = min(expiry, signal_expiry)
    outside_session = selected_session_end(line["config"]["trade_sessions"], now.isoformat()) is None
    must_cancel = now >= expiry or line["status"] == "cancel_requested" or outside_session
    if not must_cancel:
        transition_line(conn, line["id"], ACTIVE_STATUSES, "pending", now)
        return True

    metadata = json.loads(order["metadata_json"] or "{}")
    ticket = str(metadata.get("broker_order_id") or "")
    try:
        broker_state = client.get_pending_order_state(broker_symbol, order_ticket=ticket)
        if broker_state == "pending":
            reason = "Line session ended" if outside_session else "Line expired"
            client.cancel_pending_order(broker_symbol, order_ticket=ticket, comment=reason)
        elif broker_state not in {"cancelled", "expired"}:
            return True
    except Exception as exc:
        _record_line_error(conn, line["id"], str(exc), now)
        return True

    conn.execute(
        "UPDATE trade_orders SET status='cancelled',closed_at=?,updated_at=? WHERE id=? AND status='pending_fill'",
        (now.isoformat(), now.isoformat(), order["id"]),
    )
    next_status = "cancelled" if line["status"] == "cancel_requested" or outside_session else "expired"
    transition_line(conn, line["id"], ACTIVE_STATUSES, next_status, now)
    return True


def _reconcile_execution_request(
    conn, line, request, client, broker_symbol: str, magic: int,
    grace_minutes: int, now: datetime,
) -> bool:
    """Keep persisted intents reserved and project terminal failures onto the Line."""
    if request is None:
        return False
    status = request["status"]
    if status == "cancelled" and request["failure_reason"] == SESSION_ENDED_BEFORE_EXECUTION:
        return False
    if status in {"failed", "cancelled"}:
        transition_line(conn, line["id"], ACTIVE_STATUSES, "failed", now)
    elif status in {"pending", "reconciliation_required"}:
        if status == "pending" and now < dt(request["created_at"]) + timedelta(minutes=grace_minutes):
            return True
        try:
            open_positions, pending_orders = client.bot_order_counts(broker_symbol, magic=magic)
        except Exception:
            open_positions, pending_orders = -1, -1
        if open_positions == 0 and pending_orders == 0:
            cleared_error = (
                "Stale execution intent stopped after MT5 confirmed no active bot "
                "position or pending order for this symbol."
            )
            conn.execute(
                """UPDATE execution_requests
                SET status='failed',failure_reason=?,updated_at=?
                WHERE id=? AND status IN ('pending','reconciliation_required')""",
                (cleared_error, now.isoformat(), request["id"]),
            )
            conn.execute(
                """UPDATE line_reaction_plans
                SET status='failed',last_error=?,updated_at=?
                WHERE id=? AND status IN ('executing','pending','reconciliation_required')""",
                (cleared_error, now.isoformat(), line["id"]),
            )
            conn.commit()
            return True
        if status == "pending":
            conn.execute(
                """UPDATE execution_requests
                SET status='reconciliation_required',failure_reason=?,updated_at=?
                WHERE id=? AND status='pending'""",
                (UNKNOWN_INTENT_ERROR, now.isoformat(), request["id"]),
            )
            conn.execute(
                """UPDATE line_reaction_plans
                SET status='reconciliation_required',last_error=?,updated_at=?
                WHERE id=? AND status IN ('executing','pending')""",
                (UNKNOWN_INTENT_ERROR, now.isoformat(), line["id"]),
            )
            conn.commit()
    return True


def _stop_expired_or_cancelled_line(conn, line, now: datetime) -> bool:
    if now < dt(line["expires_at"]) and line["status"] != "cancel_requested":
        return False
    next_status = "cancelled" if line["status"] == "cancel_requested" else "expired"
    transition_line(conn, line["id"], ACTIVE_STATUSES, next_status, now)
    return True


def _clear_unsubmitted_signal_after_session(conn, line, now: datetime) -> None:
    if line["signal"] is None or line["status"] != "executing":
        return
    conn.execute(
        """UPDATE line_reaction_plans
        SET status='armed',signal_json=NULL,
            last_error='Signal cleared because its selected trading session ended',updated_at=?
        WHERE id=? AND status='executing'""",
        (now.isoformat(), line["id"]),
    )
    conn.commit()


def _detect_line_signal(conn, config, line, now: datetime) -> dict[str, Any] | None:
    """Build one closed-candle signal and freeze its ATR/wave evidence."""
    candles = load_chart_candles(
        conn, config.symbol, "M15", line["config"]["body_period"] + 15, end=now.isoformat(),
    )
    candles = [candle for candle in candles if dt(candle["time"]) + timedelta(minutes=15) <= now]
    h1_candles = load_chart_candles(conn, config.symbol, "H1", 500, end=now.isoformat())
    h1_candles = [candle for candle in h1_candles if dt(candle["time"]) + timedelta(hours=1) <= now]
    atr = latest_atr(chart_candles_to_slices(candles), 14)
    h1_atr = latest_atr(chart_candles_to_slices(h1_candles), 14)
    if atr is None or h1_atr is None:
        return None
    signal = evaluate_line(line, candles, atr, h1_atr, now)
    if signal is None:
        return None
    signal["wave_metrics"] = build_wave_metrics(
        load_chart_structure(
            conn, config.symbol, "H1", h1_candles[0]["time"], signal["signal_close_time"],
        ),
        h1_candles,
        as_of=signal["signal_close_time"],
    )
    return signal


def _claim_line_signal(conn, line_id: str, signal: dict[str, Any], now: datetime) -> bool:
    """Atomically reserve the account slot before any execution work begins."""
    try:
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        changed = conn.execute(
            """UPDATE line_reaction_plans SET status='executing',signal_json=?,updated_at=?
            WHERE id=? AND status='armed' AND removed_at IS NULL""",
            (json.dumps(signal), now.isoformat(), line_id),
        ).rowcount
        conn.commit()
        return bool(changed)
    except sqlite3.IntegrityError:
        conn.rollback()
        return False


def _submit_line_candidate(
    conn, config, env, client, broker_symbol, line, signal, session_close,
    idea_id, now, execute_candidates, risk_pct,
) -> None:
    """Price and hand one reserved Line to the shared live execution engine."""
    try:
        side = "buy" if line["direction"] == "long" else "sell"
        broker_price = client.current_price_for_side(broker_symbol, side)
        levels = price_line(line, signal, broker_price, signal.get("wave_metrics"))
        levels["expires_at"] = min(dt(levels["expires_at"]), session_close).isoformat()
        candidate = {
            "id": line["id"], "symbol": config.symbol, "timeframe": "M15", "playbook": PLAYBOOK,
            "direction": line["direction"], "status": "eligible", "score": 1,
            "reason": ["Closed M15 single-ended recovery touched armed line"],
            "related_zone_ids": [], "primary_zone_id": None, **levels,
        }
        execute_candidates(
            conn, config, env, client, [candidate], broker_symbol, risk_pct_override=risk_pct,
        )
        execution = conn.execute(
            "SELECT status FROM execution_requests WHERE trade_idea_id=? ORDER BY created_at DESC LIMIT 1",
            (idea_id,),
        ).fetchone()
        error = None if execution and execution["status"] == "sent" else (
            "Entry deferred/rejected: check spread, account, news and risk execution events."
        )
        _record_line_error(conn, line["id"], error, now)
    except Exception as exc:
        _record_line_error(conn, line["id"], str(exc), now)


def transition_line(
    conn,
    line_id: str,
    from_statuses: set[str] | frozenset[str],
    to_status: str,
    now: datetime,
) -> bool:
    """Commit one guarded lifecycle transition and report whether it applied."""
    allowed = sorted(from_statuses)
    if not allowed:
        return False
    parameters: list[Any] = [to_status, now.isoformat()]
    placeholders = ",".join("?" for _ in allowed)
    parameters.extend((line_id, *allowed))
    changed = conn.execute(
        f"UPDATE line_reaction_plans SET status=?,updated_at=? WHERE id=? AND status IN ({placeholders})",
        parameters,
    ).rowcount
    conn.commit()
    return bool(changed)


def _record_line_error(conn, line_id: str, error: str | None, now: datetime) -> None:
    conn.execute(
        "UPDATE line_reaction_plans SET last_error=?,updated_at=? WHERE id=?",
        (error, now.isoformat(), line_id),
    )
    conn.commit()
