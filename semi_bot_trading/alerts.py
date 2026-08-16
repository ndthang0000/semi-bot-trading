from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from sqlite3 import Connection, IntegrityError
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)
MAX_SEND_ATTEMPTS = 5
RETRY_BASE_SECONDS = 30


@dataclass(frozen=True)
class AlertEvent:
    id: str
    account_label: str
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
    attempt_count: int
    next_attempt_at: str | None


def queue_alert(
    conn: Connection,
    *,
    account_label: str,
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
                id, account_label, symbol, timeframe, event_type, severity, entity_ids_json,
                message_payload_json, dedupe_key, created_at, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                f"alert-{uuid.uuid4()}",
                account_label,
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
    except IntegrityError as exc:
        if "alert_events.account_label, alert_events.dedupe_key" not in str(exc):
            raise
        return False


def pending_alerts(conn: Connection, account_label: str, limit: int = 20) -> list[AlertEvent]:
    rows = conn.execute(
        """
        SELECT *
        FROM alert_events
        WHERE account_label = ?
          AND status = 'pending'
          AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
        ORDER BY created_at
        LIMIT ?
        """,
        (account_label, utc_now_iso(), limit),
    ).fetchall()
    return [row_to_alert(row) for row in rows]


def mark_alert_sent(conn: Connection, alert_id: str) -> None:
    conn.execute(
        """
        UPDATE alert_events
        SET status = 'sent', sent_at = ?, failure_reason = NULL, next_attempt_at = NULL
        WHERE id = ?
        """,
        (utc_now_iso(), alert_id),
    )
    conn.commit()


def schedule_alert_retry(conn: Connection, alert: AlertEvent, reason: str) -> bool:
    attempt_count = alert.attempt_count + 1
    if attempt_count >= MAX_SEND_ATTEMPTS:
        conn.execute(
            """
            UPDATE alert_events
            SET status = 'failed', failure_reason = ?, attempt_count = ?, next_attempt_at = NULL
            WHERE id = ?
            """,
            (reason[:1000], attempt_count, alert.id),
        )
        conn.commit()
        return False
    delay_seconds = RETRY_BASE_SECONDS * (2 ** (attempt_count - 1))
    next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay_seconds)
    conn.execute(
        """
        UPDATE alert_events
        SET failure_reason = ?, attempt_count = ?, next_attempt_at = ?
        WHERE id = ? AND status = 'pending'
        """,
        (reason[:1000], attempt_count, next_attempt_at.replace(microsecond=0).isoformat(), alert.id),
    )
    conn.commit()
    return True


def send_pending_telegram_alerts(
    conn: Connection,
    *,
    token: str | None,
    chat_id: str | None,
    account_label: str,
    limit: int = 20,
) -> int:
    if not token or not chat_id:
        return 0
    sent = 0
    for alert in pending_alerts(conn, account_label, limit=limit):
        try:
            text = format_alert_message(alert)
            text = f"[{alert.account_label}] {text}"
            send_telegram_message(token, chat_id, text)
            mark_alert_sent(conn, alert.id)
            sent += 1
        except Exception as exc:
            will_retry = schedule_alert_retry(conn, alert, str(exc))
            logger.warning(
                "Telegram alert send failed account=%s alert_id=%s event_type=%s attempt=%d retry=%s: %s",
                alert.account_label,
                alert.id,
                alert.event_type,
                alert.attempt_count + 1,
                will_retry,
                exc,
            )
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
    if et == "new_swing":
        return _fmt_swing(alert)
    if et == "m15_recovery":
        return _fmt_recovery(alert)
    if et == "news_alert":
        return _fmt_news(alert)
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
# Swing point alert
# ---------------------------------------------------------------------------

_SWING_ICON: dict[str, str] = {
    "HH": "[HH]",
    "LH": "[LH]",
    "HL": "[HL]",
    "LL": "[LL]",
    "swing_high": "[SH]",
    "swing_low": "[SL]",
}


def _fmt_swing(alert: AlertEvent) -> str:
    p = alert.payload
    swing = p.get("swing") or {}
    point_type = str(swing.get("point_type", "?"))
    swing_type = str(swing.get("swing_type", ""))
    price = swing.get("price", "?")
    event_time = str(swing.get("event_time", ""))[:16].replace("T", " ")

    is_high = swing_type == "high"
    icon = _SWING_ICON.get(point_type, "[SW]")
    direction = "High" if is_high else "Low"
    sym_tf = "[" + alert.symbol + " " + alert.timeframe + "]"
    return "\n".join([
        sym_tf + " " + icon + " Swing " + direction,
        "Price: " + str(price) + "  At: " + event_time,
    ])


def _fmt_recovery(alert: AlertEvent) -> str:
    recovery = alert.payload.get("recovery") or {}
    event_time = str(recovery.get("event_time", ""))[:16].replace("T", " ")
    directions = recovery.get("directions") or []
    labels = {"bullish": "Bullish", "bearish": "Bearish"}
    direction_text = " + ".join(labels.get(str(item), str(item).title()) for item in directions)
    lines = [f"[{alert.symbol} {alert.timeframe}] [RECOVERY] {direction_text}"]
    lines.append(f"Close: {recovery.get('close', '?')}  At: {event_time}")
    ratios = []
    if recovery.get("bullish_ratio") is not None:
        ratios.append(f"Bullish {float(recovery['bullish_ratio']):.2f}x")
    if recovery.get("bearish_ratio") is not None:
        ratios.append(f"Bearish {float(recovery['bearish_ratio']):.2f}x")
    if ratios:
        lines.append("Recovery / avg: " + " | ".join(ratios))
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
    zone_type = setup_zone_type_label(setup.get("zone_type"))
    entry = setup.get("entry", "?")
    sl = setup.get("stop_loss", "?")
    tp = _tp_str(setup.get("take_profit"))
    context_tf = str(setup.get("context_timeframe") or alert.timeframe or "").upper()
    trigger_tf = str(setup.get("trigger_timeframe") or "").upper()

    if status == "eligible":
        status_tag = "[READY]"
    elif status == "blocked":
        status_tag = "[BLOCK]"
    else:
        status_tag = "[WAIT]"
    sym_tf = "[" + alert.symbol + " " + alert.timeframe + "]"
    lines = [
        sym_tf + " " + status_tag + " " + playbook + " " + direction,
        "Entry " + str(entry) + "  SL " + str(sl) + "  TP " + tp,
    ]
    if zone_type:
        lines.append("Zone type: " + zone_type)
    if trigger_tf and trigger_tf != context_tf:
        lines.append("Context " + context_tf + " / trigger " + trigger_tf)
    reasons = _clean_reasons(p.get("reason"))
    if reasons:
        lines.append("- " + "\n- ".join(reasons))
    chart = p.get("chart_url")
    if chart:
        lines.append(str(chart))
    return "\n".join(lines)


def setup_zone_type_label(value: object) -> str:
    raw = str(value or "").strip()
    labels = {
        "fvg": "FVG",
        "support": "Support",
        "resistance": "Resistance",
        "order_block": "Order Block",
        "consolidation": "Consolidation",
    }
    return labels.get(raw, raw.replace("_", " ").title() if raw else "")


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

    outcome_tags = {
        "opened": "[OPEN]",
        "filled": "[FILLED]",
        "expired": "[EXPIRED]",
        "take_profit": "[TP]",
        "stop_loss": "[SL]",
        "closed": "[CLOSE]",
        "blocked": "[BLOCK]",
        "failed": "[FAILED]",
        "info": "[INFO]",
    }
    outcome = str(p.get("outcome") or "").lower()
    tag = outcome_tags.get(outcome)
    if tag is None:
        t_lower = title.lower()
        if "blocked" in t_lower:
            tag = "[BLOCK]"
        elif "failed" in t_lower:
            tag = "[FAILED]"
        elif "opened" in t_lower or "executed" in t_lower:
            tag = "[OPEN]"
        elif "closed" in t_lower:
            tag = "[CLOSE]"
        elif " tp" in t_lower:
            tag = "[TP]"
        elif "sl" in t_lower or "stop" in t_lower or "loss" in t_lower:
            tag = "[SL]"
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
# News alert
# ---------------------------------------------------------------------------


def _fmt_news(alert: AlertEvent) -> str:
    p = alert.payload
    title = str(p.get("title", "⚠️ Tin tức sắp ra"))
    reasons = p.get("reason") or []
    lines = [title] + [str(r) for r in reasons if r]
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
        account_label=row["account_label"],
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
        attempt_count=int(row["attempt_count"] or 0),
        next_attempt_at=row["next_attempt_at"],
    )


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
