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
            raise RuntimeError(f"Telegram sendMessage failed with status {response.status}")


def format_alert_message(alert: AlertEvent) -> str:
    payload = alert.payload
    title = str(payload.get("title") or alert.event_type.replace("_", " ").title())
    lines = [f"[{alert.symbol}][{alert.timeframe}] {title}"]
    price = payload.get("price")
    if price is not None:
        lines.append(f"Price: {price}")
    zone = payload.get("zone")
    if isinstance(zone, dict):
        lines.append(f"Zone: {zone.get('type')} {zone.get('price_low')} - {zone.get('price_high')}")
    setup = payload.get("setup")
    if isinstance(setup, dict):
        lines.append(f"Setup: {setup.get('playbook')} {setup.get('direction')} {setup.get('status')}")
        lines.append(f"Entry/SL/TP: {setup.get('entry')} / {setup.get('stop_loss')} / {setup.get('take_profit')}")
    reason = payload.get("reason")
    if isinstance(reason, list) and reason:
        lines.append("")
        lines.append("Reason:")
        lines.extend(f"- {item}" for item in reason[:5])
    action = payload.get("action")
    if action:
        lines.append("")
        lines.append(f"Action: {action}")
    chart_url = payload.get("chart_url")
    if chart_url:
        lines.append("")
        lines.append(f"Open chart: {chart_url}")
    return "\n".join(lines)


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
