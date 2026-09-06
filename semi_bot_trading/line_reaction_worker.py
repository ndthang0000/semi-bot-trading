"""Account-scoped line processing. A unique DB claim survives worker restarts."""
import json
import sqlite3
from datetime import timedelta
from .line_reaction import PLAYBOOK, evaluate_line, price_line, dt
from .line_reaction_api import row_api
from .chart import load_chart_candles, load_chart_structure, build_wave_metrics
from .zones import latest_atr
from .strategy.helpers import chart_candles_to_slices
from .trading_sessions import selected_session_end


def process_line_reactions(conn, config, env, client, broker_symbol, now):
    from .live_worker import maybe_execute_candidates, live_trade_idea_id, manual_ai_risk_pct
    if not env.execution_enabled:
        return
    rows = conn.execute("""SELECT * FROM line_reaction_plans
        WHERE account_label=? AND symbol=? AND status IN ('armed','executing','pending','open','cancel_requested')
        ORDER BY created_at,id""", (env.account_label,config.symbol)).fetchall()
    for raw in rows:
        line = row_api(raw)
        idea = live_trade_idea_id(line["id"], account_label=env.account_label)
        order = conn.execute("SELECT * FROM trade_orders WHERE trade_idea_id=? ORDER BY created_at DESC LIMIT 1", (idea,)).fetchone()
        if order is not None:
            if order["status"] == "filled":
                _status(conn,line,"open",now)
                continue
            if order["status"] not in {"pending_fill"}:
                _status(conn,line,"closed" if order["status"] == "closed" else "cancelled",now)
                continue
            expiry = dt(line["expires_at"])
            if line["signal"]:
                expiry = min(expiry, dt(line["signal"]["signal_close_time"])+timedelta(minutes=line["config"]["limit_ttl_minutes"]))
            outside_session = selected_session_end(line["config"]["trade_sessions"], now.isoformat()) is None
            if now >= expiry or line["status"] == "cancel_requested" or outside_session:
                metadata = json.loads(order["metadata_json"])
                ticket = str(metadata.get("broker_order_id") or "")
                try:
                    state = client.get_pending_order_state(broker_symbol, order_ticket=ticket)
                    if state == "pending":
                        client.cancel_pending_order(broker_symbol, order_ticket=ticket, comment="Line session ended" if outside_session else "Line expired")
                    elif state not in {"cancelled", "expired"}:
                        continue
                except Exception as exc:
                    conn.execute("UPDATE line_reaction_plans SET last_error=? WHERE id=?", (str(exc),line["id"]))
                    conn.commit()
                    continue
                conn.execute("UPDATE trade_orders SET status='cancelled',closed_at=?,updated_at=? WHERE id=? AND status='pending_fill'",
                             (now.isoformat(),now.isoformat(),order["id"]))
                _status(conn,line,"cancelled" if line["status"]=="cancel_requested" or outside_session else "expired",now)
            else:
                _status(conn,line,"pending",now)
            continue
        request = conn.execute("SELECT status FROM execution_requests WHERE trade_idea_id=? ORDER BY created_at DESC LIMIT 1", (idea,)).fetchone()
        if request:
            # Unknown/sent intents without an order remain reserved for reconciliation.
            if request["status"] in {"failed", "cancelled"}:
                _status(conn,line,"failed",now)
            continue
        if now >= dt(line["expires_at"]) or line["status"] == "cancel_requested":
            _status(conn,line,"cancelled" if line["status"]=="cancel_requested" else "expired",now)
            continue
        if not config.strategy.line_reaction_v1_enabled:
            continue
        session_close = selected_session_end(line["config"]["trade_sessions"], now.isoformat())
        if session_close is None:
            if line["signal"] is not None and line["status"] == "executing":
                conn.execute("""UPDATE line_reaction_plans SET status='armed',signal_json=NULL,
                    last_error='Signal cleared because its selected trading session ended',updated_at=? WHERE id=?""",
                    (now.isoformat(), line["id"]))
                conn.commit()
            continue
        signal = line["signal"]
        if signal is None:
            candles = load_chart_candles(conn,config.symbol,"M15",line["config"]["body_period"]+15,end=now.isoformat())
            candles = [c for c in candles if dt(c["time"])+timedelta(minutes=15)<=now]
            h1 = load_chart_candles(conn,config.symbol,"H1",500,end=now.isoformat())
            h1 = [c for c in h1 if dt(c["time"])+timedelta(hours=1)<=now]
            atr = latest_atr(chart_candles_to_slices(candles),14)
            h1_atr = latest_atr(chart_candles_to_slices(h1),14)
            if atr is None or h1_atr is None:
                continue
            signal = evaluate_line(line,candles,atr,h1_atr,now)
            if signal is None:
                continue
            wave = build_wave_metrics(
                load_chart_structure(conn,config.symbol,"H1",h1[0]["time"],signal["signal_close_time"]),
                h1,as_of=signal["signal_close_time"])
            signal["wave_metrics"] = wave
            try:
                conn.commit()
                conn.execute("BEGIN IMMEDIATE")
                changed = conn.execute("""UPDATE line_reaction_plans SET status='executing',signal_json=?,updated_at=?
                    WHERE id=? AND status='armed'""", (json.dumps(signal),now.isoformat(),line["id"])).rowcount
                conn.commit()
            except sqlite3.IntegrityError:
                conn.rollback()
                continue
            if not changed:
                continue
            line["signal"] = signal
        if now >= dt(signal["signal_close_time"])+timedelta(minutes=15):
            _status(conn,line,"expired",now)
            continue
        try:
            broker_price = client.current_price_for_side(broker_symbol,"buy" if line["direction"]=="long" else "sell")
            levels = price_line(line,signal,broker_price,signal.get("wave_metrics"))
            levels["expires_at"] = min(dt(levels["expires_at"]), session_close).isoformat()
            candidate = {"id":line["id"],"symbol":config.symbol,"timeframe":"M15","playbook":PLAYBOOK,
                "direction":line["direction"],"status":"eligible","score":1,
                "reason":["Closed M15 single-ended recovery touched armed line"],
                "related_zone_ids":[],"primary_zone_id":None,**levels}
            maybe_execute_candidates(conn,config,env,client,[candidate],broker_symbol,
                                     risk_pct_override=manual_ai_risk_pct(env.account_profile))
            execution = conn.execute("SELECT status FROM execution_requests WHERE trade_idea_id=? ORDER BY created_at DESC LIMIT 1", (idea,)).fetchone()
            conn.execute("UPDATE line_reaction_plans SET last_error=? WHERE id=?",
                         (None if execution and execution["status"] == "sent" else
                          "Entry deferred/rejected: check spread, account, news and risk execution events.",line["id"]))
            conn.commit()
        except Exception as exc:
            conn.execute("UPDATE line_reaction_plans SET last_error=?,updated_at=? WHERE id=?",
                         (str(exc),now.isoformat(),line["id"]))
            conn.commit()


def _status(conn,line,status,now):
    conn.execute("UPDATE line_reaction_plans SET status=?,updated_at=? WHERE id=?", (status,now.isoformat(),line["id"]))
    conn.commit()
