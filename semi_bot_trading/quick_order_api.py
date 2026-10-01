from __future__ import annotations

from contextlib import closing
from datetime import UTC, datetime, timedelta
import json
import uuid
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

from .db import connect, init_db
from .quick_order import DEFAULT_RISK_REWARD, build_quick_order_geometry, latest_closed_h1_atr
from .spread import latest_spread_snapshot


class QuickOrderRequest(BaseModel):
    client_request_id: str = Field(min_length=8, max_length=100)
    symbol: str = Field(default="XAUUSD", min_length=1, max_length=32)
    account_labels: list[str] = Field(min_length=1, max_length=20)
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit"]
    entry_price: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    risk_reward: float = Field(default=DEFAULT_RISK_REWARD, ge=1.0, le=4.0)
    expires_in_minutes: int = Field(default=60, ge=5, le=2_880)


class QuickOrderPreviewRequest(BaseModel):
    symbol: str = Field(default="XAUUSD", min_length=1, max_length=32)
    account_labels: list[str] = Field(min_length=1, max_length=20)
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit"]
    entry_price: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    risk_reward: float = Field(default=DEFAULT_RISK_REWARD, ge=1.0, le=4.0)


class QuickOrderLevelsUpdate(BaseModel):
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)


def _accounts(conn, labels: list[str]):
    unique = list(dict.fromkeys(label.strip() for label in labels if label.strip()))
    if not unique:
        raise HTTPException(422, "Select at least one account")
    placeholders = ",".join("?" for _ in unique)
    rows = conn.execute(
        f"""SELECT account_label, effective_enabled, hard_enabled, worker_status, heartbeat_at, broker_symbol
            FROM account_execution_controls WHERE account_label IN ({placeholders})""",
        unique,
    ).fetchall()
    by_label = {str(row["account_label"]): row for row in rows}
    missing = [label for label in unique if label not in by_label]
    if missing:
        raise HTTPException(422, "Account worker is not registered: " + ", ".join(missing))
    return unique, by_label


def _preview(conn, body: QuickOrderPreviewRequest) -> dict:
    symbol = body.symbol.strip().upper()
    atr_h1, atr_candle_time = latest_closed_h1_atr(conn, symbol)
    labels, controls = _accounts(conn, body.account_labels)
    results = []
    for label in labels:
        quote = latest_spread_snapshot(conn, symbol, account_label=label)
        if quote is None:
            raise HTTPException(409, f"No broker quote is available for {label}")
        quote_age = datetime.now(UTC) - datetime.fromisoformat(str(quote["snapshot_at"]))
        quote_fresh = quote_age <= timedelta(seconds=60)
        market_entry = float(quote["ask"] if body.side == "buy" else quote["bid"])
        entry = body.entry_price if body.order_type == "limit" else market_entry
        if entry is None:
            raise HTTPException(422, "Limit order requires entry_price")
        if body.order_type == "limit":
            valid = entry < market_entry if body.side == "buy" else entry > market_entry
            if not valid:
                relation = "below" if body.side == "buy" else "above"
                raise HTTPException(422, f"{body.side.upper()} LIMIT entry must be {relation} current {label} price {market_entry:.2f}")
        try:
            geometry = build_quick_order_geometry(
                side=body.side,
                entry=float(entry),
                requested_stop=body.stop_loss,
                atr_h1=atr_h1,
                risk_reward=body.risk_reward,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        control = controls[label]
        heartbeat = datetime.fromisoformat(str(control["heartbeat_at"])) if control["heartbeat_at"] else None
        heartbeat_fresh = heartbeat is not None and datetime.now(UTC) - heartbeat <= timedelta(seconds=60)
        results.append({
            "account_label": label,
            "quote": quote,
            "execution_ready": bool(control["effective_enabled"] and control["hard_enabled"] and control["worker_status"] == "online" and heartbeat_fresh and quote_fresh),
            "worker_status": control["worker_status"] if heartbeat_fresh and quote_fresh else "stale",
            "quote_fresh": quote_fresh,
            **geometry.as_dict(),
        })
    return {"symbol": symbol, "atr_h1": atr_h1, "atr_candle_time": atr_candle_time, "accounts": results}


def _group(conn, group_id: str) -> dict:
    rows = conn.execute(
        "SELECT * FROM quick_order_requests WHERE client_group_id=? ORDER BY account_label", (group_id,)
    ).fetchall()
    return {
        "id": group_id,
        "client_group_id": group_id,
        "account_labels": [row["account_label"] for row in rows],
        "account_statuses": {row["account_label"]: row["status"] for row in rows},
        "orders": [dict(row) for row in rows],
    }


def register_quick_order_routes(app, config, require_auth):
    @app.post("/api/quick-orders/preview")
    def preview_quick_order(body: QuickOrderPreviewRequest, _: str = Depends(require_auth)):
        if body.symbol.strip().upper() != config.symbol:
            raise HTTPException(422, "Unsupported symbol")
        with closing(connect(config.database)) as conn:
            init_db(conn)
            return _preview(conn, body)

    @app.post("/api/quick-orders")
    def create_quick_order(body: QuickOrderRequest, _: str = Depends(require_auth)):
        if body.symbol.strip().upper() != config.symbol:
            raise HTTPException(422, "Unsupported symbol")
        now = datetime.now(UTC)
        with closing(connect(config.database)) as conn:
            init_db(conn)
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT client_group_id FROM quick_order_requests WHERE client_request_id=? LIMIT 1",
                (body.client_request_id,),
            ).fetchone()
            if existing:
                conn.commit()
                return _group(conn, str(existing["client_group_id"]))
            preview = _preview(conn, QuickOrderPreviewRequest(**body.model_dump(exclude={"client_request_id", "expires_in_minutes"})))
            unavailable = [account["account_label"] for account in preview["accounts"] if not account["execution_ready"]]
            if unavailable:
                conn.rollback()
                raise HTTPException(409, "Execution is unavailable for: " + ", ".join(unavailable))
            group_id = str(uuid.uuid4())
            expires_at = now + timedelta(seconds=10 if body.order_type == "market" else body.expires_in_minutes * 60)
            for account in preview["accounts"]:
                conn.execute(
                    """INSERT INTO quick_order_requests (
                        id,client_group_id,client_request_id,account_label,symbol,side,order_type,
                        requested_entry,requested_stop,effective_entry,effective_stop,take_profit,
                        risk_reward,atr_h1,atr_candle_time,status,expires_at,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'queued',?,?,?)""",
                    (
                        str(uuid.uuid4()), group_id, body.client_request_id, account["account_label"],
                        preview["symbol"], body.side, body.order_type, body.entry_price, body.stop_loss,
                        account["entry"], account["stop_loss"], account["take_profit"], body.risk_reward,
                        preview["atr_h1"], preview["atr_candle_time"], expires_at.isoformat(), now.isoformat(), now.isoformat(),
                    ),
                )
            conn.commit()
            return _group(conn, group_id)

    @app.get("/api/quick-orders")
    def list_quick_orders(_: str = Depends(require_auth)):
        with closing(connect(config.database)) as conn:
            init_db(conn)
            groups = conn.execute(
                "SELECT client_group_id,MAX(created_at) AS created_at FROM quick_order_requests GROUP BY client_group_id ORDER BY created_at DESC LIMIT 20"
            ).fetchall()
            return {"orders": [_group(conn, str(row["client_group_id"])) for row in groups]}

    @app.post("/api/quick-orders/{group_id}/cancel")
    def cancel_quick_order(group_id: str, _: str = Depends(require_auth)):
        now = datetime.now(UTC).isoformat()
        with closing(connect(config.database)) as conn:
            init_db(conn)
            rows = conn.execute("SELECT status FROM quick_order_requests WHERE client_group_id=?", (group_id,)).fetchall()
            if not rows:
                raise HTTPException(404, "Quick order not found")
            conn.execute(
                """UPDATE quick_order_requests SET status=CASE
                    WHEN status IN ('pending','replace_requested') THEN 'cancel_requested' ELSE 'cancelled' END,updated_at=?
                    WHERE client_group_id=? AND status IN ('queued','executing','pending','replace_requested')""",
                (now, group_id),
            )
            conn.commit()
            return _group(conn, group_id)

    @app.patch("/api/quick-orders/{group_id}/levels")
    def update_quick_order_levels(
        group_id: str,
        body: QuickOrderLevelsUpdate,
        _: str = Depends(require_auth),
    ):
        now = datetime.now(UTC).isoformat()
        with closing(connect(config.database)) as conn:
            init_db(conn)
            rows = conn.execute(
                "SELECT * FROM quick_order_requests WHERE client_group_id=? ORDER BY account_label",
                (group_id,),
            ).fetchall()
            if not rows:
                raise HTTPException(404, "Quick order not found")
            if any(str(row["order_type"]) != "limit" for row in rows):
                raise HTTPException(422, "Only pending Quick Order Limit levels can be edited")
            active = [row for row in rows if str(row["status"]) not in {"cancelled", "failed", "expired"}]
            if not active:
                raise HTTPException(409, "Quick Order is no longer editable")
            final_statuses = sorted({str(row["status"]) for row in active if str(row["status"]) in {"filled", "closed"}})
            if final_statuses:
                raise HTTPException(409, "Quick Order already filled on at least one account")
            editable_statuses = {"queued", "pending"}
            busy = sorted({str(row["status"]) for row in active if str(row["status"]) not in editable_statuses})
            if busy:
                raise HTTPException(409, f"Quick Order is busy ({', '.join(busy)}); wait for workers and retry")

            row = active[0]
            side = str(row["side"])
            valid_geometry = (
                body.stop_loss < body.entry_price < body.take_profit
                if side == "buy"
                else body.take_profit < body.entry_price < body.stop_loss
            )
            if not valid_geometry:
                raise HTTPException(422, f"{side.upper()} levels must keep SL, Entry and TP in the correct order")
            risk = abs(body.entry_price - body.stop_loss)
            risk_reward = abs(body.take_profit - body.entry_price) / risk if risk > 0 else 0
            if not 1.0 <= risk_reward <= 4.0:
                raise HTTPException(422, f"Quick Order R:R must be between 1.0R and 4.0R; received {risk_reward:.2f}R")
            preview = _preview(
                conn,
                QuickOrderPreviewRequest(
                    symbol=str(row["symbol"]),
                    account_labels=[str(item["account_label"]) for item in active],
                    side=side,
                    order_type="limit",
                    entry_price=body.entry_price,
                    stop_loss=body.stop_loss,
                    risk_reward=risk_reward,
                ),
            )
            geometry = preview["accounts"][0]
            replacement = {
                "entry_price": float(geometry["entry"]),
                "stop_loss": float(geometry["stop_loss"]),
                "take_profit": float(geometry["take_profit"]),
                "risk_reward": float(geometry["risk_reward"]),
                "atr_h1": float(preview["atr_h1"]),
                "atr_candle_time": str(preview["atr_candle_time"]),
                "requested_at": now,
            }
            replacement_json = json.dumps(replacement, sort_keys=True)
            for item in active:
                if str(item["status"]) == "pending":
                    conn.execute(
                        """UPDATE quick_order_requests
                           SET status='replace_requested',replacement_levels_json=?,replacement_error=NULL,updated_at=?
                           WHERE id=?""",
                        (replacement_json, now, item["id"]),
                    )
                else:
                    conn.execute(
                        """UPDATE quick_order_requests
                           SET requested_entry=?,requested_stop=?,effective_entry=?,effective_stop=?,take_profit=?,
                               risk_reward=?,atr_h1=?,atr_candle_time=?,replacement_levels_json='{}',
                               replacement_error=NULL,updated_at=?
                           WHERE id=?""",
                        (
                            body.entry_price,
                            body.stop_loss,
                            replacement["entry_price"],
                            replacement["stop_loss"],
                            replacement["take_profit"],
                            replacement["risk_reward"],
                            replacement["atr_h1"],
                            replacement["atr_candle_time"],
                            now,
                            item["id"],
                        ),
                    )
            conn.commit()
            return {
                **_group(conn, group_id),
                "requires_broker_replace": any(str(item["status"]) == "pending" for item in active),
            }
