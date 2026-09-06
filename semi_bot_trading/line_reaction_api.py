from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import uuid

from fastapi import Depends, HTTPException
from .db import connect
from .line_reaction import LineConfig, LineCreate, dt
from .trading_sessions import session_catalog_api


def row_api(row):
    result = dict(row)
    result["config"] = LineConfig.model_validate(json.loads(result.pop("config_json"))).model_dump()
    result["signal"] = json.loads(result.pop("signal_json") or "null")
    return result


def _group_rows(rows):
    groups = {}
    for raw in rows:
        row = row_api(raw)
        group_id = row.get("client_group_id") or row["id"]
        groups.setdefault(group_id, []).append(row)
    status_order = ("open", "executing", "pending", "cancel_requested", "armed", "draft", "failed", "expired", "cancelled", "closed")
    priority = {name: index for index, name in enumerate(status_order)}
    plans = []
    for group_id, members in groups.items():
        representative = dict(members[0])
        representative["id"] = group_id
        representative["client_group_id"] = group_id
        representative["member_ids"] = [member["id"] for member in members]
        representative["account_labels"] = sorted(member["account_label"] for member in members)
        representative["status"] = min((member["status"] for member in members), key=lambda value: priority.get(value, 99))
        representative["account_statuses"] = {member["account_label"]: member["status"] for member in members}
        errors = [member["last_error"] for member in members if member.get("last_error")]
        representative["last_error"] = " · ".join(dict.fromkeys(errors)) or None
        plans.append(representative)
    return plans


def _fetch_group(conn, identifier):
    return conn.execute(
        "SELECT * FROM line_reaction_plans WHERE (client_group_id=? OR id=?) AND removed_at IS NULL ORDER BY created_at, id",
        (identifier, identifier),
    ).fetchall()


def _group_api(rows):
    plans = _group_rows(rows)
    return plans[0] if plans else None


def _validate_accounts(conn, labels):
    placeholders = ",".join("?" * len(labels))
    registered = {row[0] for row in conn.execute(
        f"SELECT account_label FROM account_execution_controls WHERE account_label IN ({placeholders})", labels
    ).fetchall()}
    missing = [label for label in labels if label not in registered]
    if missing:
        raise HTTPException(422, "Account worker must register before creating a line: " + ", ".join(missing))


def _expiry(body, now):
    if body.expires_in_minutes is not None:
        expires = now + timedelta(minutes=body.expires_in_minutes)
    elif body.visual_end is not None:
        expires = dt(body.visual_end)
    else:
        expires = now + timedelta(minutes=body.expires_in_minutes or 360)
    if expires <= now:
        raise HTTPException(422, "Line end must be in the future")
    return expires.isoformat()


def register_line_routes(app, config, require_auth):
    @app.get("/api/line-reactions")
    def list_lines(_: str = Depends(require_auth)):
        with closing(connect(config.database)) as conn:
            rows = conn.execute("SELECT * FROM line_reaction_plans WHERE removed_at IS NULL ORDER BY created_at DESC").fetchall()
            return {"plans": _group_rows(rows), "sessions": session_catalog_api()}

    @app.post("/api/line-reactions")
    def create_line(body: LineCreate, _: str = Depends(require_auth)):
        if body.symbol != config.symbol:
            raise HTTPException(422, "Unsupported symbol")
        now = datetime.now(timezone.utc)
        group_id = str(uuid.uuid4())
        with closing(connect(config.database)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if body.client_request_id:
                existing = conn.execute(
                    "SELECT client_group_id,id FROM line_reaction_plans WHERE client_request_id=? ORDER BY created_at LIMIT 1",
                    (body.client_request_id,),
                ).fetchone()
                if existing:
                    identifier = existing["client_group_id"] or existing["id"]
                    conn.rollback()
                    return _group_api(_fetch_group(conn, identifier))
            _validate_accounts(conn, body.account_labels)
            expires_at = _expiry(body, now)
            for label in body.account_labels:
                conn.execute("""INSERT INTO line_reaction_plans
                    (id,client_group_id,symbol,account_label,direction,price,status,config_json,expires_at,created_at,updated_at,visual_start,visual_end,client_request_id)
                    VALUES (?,?,?,?,?,?,'draft',?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()), group_id, body.symbol, label, body.direction, body.price,
                     body.config.model_dump_json(), expires_at, now.isoformat(), now.isoformat(),
                     body.visual_start, body.visual_end, body.client_request_id))
            conn.commit()
            return _group_api(_fetch_group(conn, group_id))

    @app.patch("/api/line-reactions/{identifier}")
    def edit_line(identifier: str, body: LineCreate, _: str = Depends(require_auth)):
        now = datetime.now(timezone.utc)
        with closing(connect(config.database)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = _fetch_group(conn, identifier)
            if not rows:
                raise HTTPException(404, "Line not found")
            statuses = {row["status"] for row in rows}
            if len(statuses) != 1 or not statuses <= {"draft", "armed"}:
                raise HTTPException(409, "Only Draft or Armed lines can be edited")
            if body.symbol != config.symbol:
                raise HTTPException(422, "Unsupported symbol")
            if any(row["direction"] != body.direction for row in rows):
                raise HTTPException(422, "Line direction cannot be changed")
            _validate_accounts(conn, body.account_labels)
            expires_at = _expiry(body, now)
            group_id = rows[0]["client_group_id"] or rows[0]["id"]
            group_status = rows[0]["status"]
            group_armed_at = rows[0]["armed_at"]
            current = {row["account_label"]: row for row in rows}
            wanted = set(body.account_labels)
            for label, row in current.items():
                if label not in wanted:
                    conn.execute(
                        "UPDATE line_reaction_plans SET status='cancelled',removed_at=?,updated_at=? WHERE id=?",
                        (now.isoformat(), now.isoformat(), row["id"]),
                    )
                    continue
                conn.execute("""UPDATE line_reaction_plans SET price=?,config_json=?,expires_at=?,updated_at=?,
                    visual_start=?,visual_end=?,client_group_id=? WHERE id=?""",
                    (body.price, body.config.model_dump_json(), expires_at, now.isoformat(),
                     body.visual_start, body.visual_end, group_id, row["id"]))
            for label in wanted - set(current):
                conn.execute("""INSERT INTO line_reaction_plans
                    (id,client_group_id,symbol,account_label,direction,price,status,config_json,armed_at,expires_at,created_at,updated_at,visual_start,visual_end)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()), group_id, body.symbol, label, body.direction, body.price,
                     group_status, body.config.model_dump_json(), group_armed_at, expires_at, now.isoformat(), now.isoformat(),
                     body.visual_start, body.visual_end))
            conn.commit()
            return _group_api(_fetch_group(conn, group_id))

    @app.post("/api/line-reactions/{identifier}/{action}")
    def change_line(identifier: str, action: str, _: str = Depends(require_auth)):
        if action not in {"arm", "cancel"}:
            raise HTTPException(422, "Unknown action")
        now = datetime.now(timezone.utc)
        with closing(connect(config.database)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = _fetch_group(conn, identifier)
            if not rows:
                raise HTTPException(404, "Line not found")
            group_id = rows[0]["client_group_id"] or rows[0]["id"]
            if action == "arm":
                if any(row["status"] != "draft" or dt(row["expires_at"]) <= now for row in rows):
                    raise HTTPException(409, "Only an unexpired Draft can be armed")
                conn.execute("""UPDATE line_reaction_plans SET status='armed',armed_at=?,updated_at=?
                    WHERE (client_group_id=? OR id=?) AND removed_at IS NULL""",
                    (now.isoformat(), now.isoformat(), group_id, group_id))
            else:
                cancellable = {"draft", "armed", "executing", "pending", "cancel_requested"}
                if not any(row["status"] in cancellable for row in rows):
                    raise HTTPException(409, "This line cannot be cancelled; filled trades keep their SL/TP")
                for row in rows:
                    if row["status"] not in cancellable:
                        continue
                    next_status = "cancel_requested" if row["status"] in {"executing", "pending", "cancel_requested"} else "cancelled"
                    conn.execute("UPDATE line_reaction_plans SET status=?,updated_at=? WHERE id=?",
                                 (next_status, now.isoformat(), row["id"]))
            conn.commit()
            return _group_api(_fetch_group(conn, group_id))
