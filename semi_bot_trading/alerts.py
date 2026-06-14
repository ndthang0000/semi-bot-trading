from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from sqlite3 import Connection
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class AlertEvent:
    id: str
    symbol: str
    timeframe: str
    event_type: str
    severity: str
    entity_ids: list[str]
    payload: dict[str, Any]
    dedupe_key: str
    created_at: str
    sent_at: str | None
    status: str
    failure_reason: str | None


def queue_alert(
    conn: Connection,
    *,
    symbol: str,
    timeframe: str,
    event_type: str,
    severity: str,
    entity_ids: list[str],
    payload: dict[str, Any],
    dedupe_key: str,
) -> bool:
    try:
        conn.execute(
            """
            INSERT INTO alert_events (
                id, symbol, timeframe, event_type, severity, entity_ids_json,
                message_payload_json, dedupe_key, created_at, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                f"alert-{uuid.uuid4()}",
                symbol,
                timeframe,
                event_type,
                severity,
                json.dumps(entity_ids, sort_keys=True),
                json.dumps(payload, sort_keys=True),
                dedupe_key,
                utc_now_iso(),
            ),
        )
        conn.commit()
        return True
    except Exception as exc:
        if "UNIQUE constraint failed" not in str(exc):
            raise
        return False


def pending_alerts(conn: Connection, limit: int = 20) -> list[AlertEvent]:
    rows = conn.execute(
        """
        SELECT *
        FROM alert_events
        WHERE status = 'pending'
        ORDER BY created_at
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [row_to_alert(row) for row in rows]


def mark_alert_sent(conn: Connection, alert_id: str) -> None:
    conn.execute(
        """
        UPDATE alert_events
        SET status = 'sent', sent_at = ?, failure_reason = NULL
        WHERE id = ?
        """,
        (utc_now_iso(), alert_id),
    )
    conn.commit()


def mark_alert_failed(conn: Connection, alert_id: str, reason: str) -> None:
    conn.execute(
        """
        UPDATE alert_events
        SET status = 'failed', failure_reason = ?
        WHERE id = ?
        """,
        (reason[:1000], alert_id),
    )
    conn.commit()


def send_pending_telegram_alerts(
    conn: Connection,
    *,
    token: str | None,
    chat_id: str | None,
    limit: int = 20,
) -> int:
    if not token or not chat_id:
        return 0
    sent = 0
    for alert in pending_alerts(conn, limit=limit):
        try:
            send_telegram_message(token, chat_id, format_alert_message(alert))
            mark_alert_sent(conn, alert.id)
            sent += 1
        except Exception as exc:
            mark_alert_failed(conn, alert.id, str(exc))
    return sent


def send_telegram_message(token: str, chat_id: str, text: str, timeout: float = 10.0) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    request = Request(url, data=body, method="POST")
    with urlopen(request, timeout=timeout) as response:
        if response.status >= 400:
            raise RuntimeError(
                f"Telegram sendMessage failed with status {response.status}"
            )


# ---------------------------------------------------------------------------
# Public formatter
# ---------------------------------------------------------------------------

def format_alert_message(alert: AlertEvent) -> str:
    et = alert.event_type
    if et == "new_zone":
        return _fmt_zone(alert)
    if et == "setup_candidate":
        return _fmt_setup(alert)
    if et == "execution_event":
        return _fmt_execution(alert)
    return _fmt_generic(alert)


# ---------------------------------------------------------------------------
# Noise filter – strips debug/research lines from reason lists
# ---------------------------------------------------------------------------

_REASON_NOISE = (
    "debug",
    "research",
    "temporarily disabled",
    "keeping it for",
    "direction gate",
)


def _clean_reasons(reasons: object, limit: int = 3) -> list[str]:
    if not isinstance(reasons, list):
        return []
    out: list[str] = []
    for r in reasons:
        s = str(r)
        if any(noise in s.lower() for noise in _REASON_NOISE):
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


def _tp_str(tp_raw: object) -> str:
    if isinstance(tp_raw, list):
        return str(tp_raw[0]) if tp_raw else "?"
    return str(tp_raw) if tp_raw is not None else "?"


# ---------------------------------------------------------------------------
# Zone alert
# ---------------------------------------------------------------------------

_ZONE_ICON: dict[str, str] = {
    "resistance": "[R]",
    "support": "[S]",
    "fvg": "[FVG]",
    "order_block": "[OB]",
}


def _fmt_zone(alert: AlertEvent) -> str:
    p = alert.payload
    zone = p.get("zone") or {}
    ztype = str(zone.get("type", "zone"))
    lo = zone.get("price_low", "?")
    hi = zone.get("price_high", "?")
    w = zone.get("weight")
    tag = _ZONE_ICON.get(ztype, "[Z]")
    sym_tf = "[" + alert.symbol + " " + alert.timeframe + "]"
    weight_str = ("  w=" + f"{w:.2f}") if w is not None else ""
    lines = [
        sym_tf + " " + tag + " New " + ztype,
        str(lo) + " - " + str(hi) + weight_str,
    ]
    chart = p.get("chart_url")
    if chart:
        lines.append(str(chart))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Setup candidate alert
# ---------------------------------------------------------------------------

def _fmt_setup(alert: AlertEvent) -> str:
    p = alert.payload
    setup = p.get("setup") or {}
    playbook = str(setup.get("playbook", "")).replace("_", "-")
    direction = str(setup.get("direction", "")).upper()
    status = str(setup.get("status", ""))
    entry = setup.get("entry", "?")
    sl = setup.get("stop_loss", "?")
    tp = _tp_str(setup.get("take_profit"))

    status_tag = "[READY]" if status == "eligible" else "[WAIT]"
    sym_tf = "[" + alert.symbol + " " + alert.timeframe + "]"
    lines = [
        sym_tf + " " + status_tag + " " + playbook + " " + direction,
        "Entry " + str(entry) + "  SL " + str(sl) + "  TP " + tp,
    ]
    reasons = _clean_reasons(p.get("reason"))
    if reasons:
        lines.append("- " + "\n- ".join(reasons))
    chart = p.get("chart_url")
    if chart:
        lines.append(str(chart))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Execution event alert
# ---------------------------------------------------------------------------

def _fmt_execution(alert: AlertEvent) -> str:
    p = alert.payload
    title = str(p.get("title", "Execution event"))
    setup = p.get("setup") or {}
    direction = str(setup.get("direction", "") or p.get("direction", "")).upper()
    entry = p.get("entry") or setup.get("entry")
    sl = p.get("stop_loss") or setup.get("stop_loss")
    tp = _tp_str(p.get("take_profit") or setup.get("take_profit"))
    lots = p.get("lots") or p.get("quantity")
    pnl_r = p.get("pnl_r")

    t_lower = title.lower()
    if "opened" in t_lower or "executed" in t_lower:
        tag = "[OPEN]"
    elif "closed" in t_lower or " tp" in t_lower:
        tag = "[TP]"
    elif "sl" in t_lower or "stop" in t_lower or "loss" in t_lower:
        tag = "[SL]"
    elif "blocked" in t_lower or "failed" in t_lower:
        tag = "[BLOCK]"
    else:
        tag = "[INFO]"

    sym = "[" + alert.symbol + "]"
    lines = [sym + " " + tag + " " + title]

    if direction and entry:
        price_line = direction + " @ " + str(entry)
        if sl:
            price_line += "  SL " + str(sl)
        if tp and tp != "?":
            price_line += "  TP " + tp
        if lots:
            price_line += "  " + str(lots) + " lots"
        lines.append(price_line)

    if pnl_r is not None:
        sign = "+" if float(pnl_r) >= 0 else ""
        lines.append("P&L: " + sign + f"{float(pnl_r):.2f}" + "R")

    reasons = _clean_reasons(p.get("reason"), limit=2)
    if reasons:
        lines.append("- " + "\n- ".join(reasons))

    chart = p.get("chart_url")
    if chart:
        lines.append(str(chart))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Generic fallback
# ---------------------------------------------------------------------------

def _fmt_generic(alert: AlertEvent) -> str:
    p = alert.payload
    title = str(p.get("title") or alert.event_type.replace("_", " ").title())
    sym_tf = "[" + alert.symbol + " " + alert.timeframe + "]"
    lines = [sym_tf + " " + title]
    reasons = _clean_reasons(p.get("reason"))
    if reasons:
        lines.append("- " + "\n- ".join(reasons))
    chart = p.get("chart_url")
    if chart:
        lines.append(str(chart))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def row_to_alert(row: Any) -> AlertEvent:
    return AlertEvent(
        id=row["id"],
        symbol=row["symbol"],
        timeframe=row["timeframe"],
        event_type=row["event_type"],
        severity=row["severity"],
        entity_ids=json.loads(row["entity_ids_json"]),
        payload=json.loads(row["message_payload_json"]),
        dedupe_key=row["dedupe_key"],
        created_at=row["created_at"],
        sent_at=row["sent_at"],
        status=row["status"],
        failure_reason=row["failure_reason"],
    )


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
