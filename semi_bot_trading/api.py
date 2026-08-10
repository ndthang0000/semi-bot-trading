from __future__ import annotations

import base64
import binascii
import json
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .api_models import (
    AccountCloseAllRequest,
    AccountExecutionControlRequest,
    AccountManualTradingLockRequest,
    AccountPartialTakeProfitRequest,
    ChartDrawingCreateRequest,
    ChartDrawingUpdateRequest,
    ContextOverrideRequest,
    LoginRequest,
    LogoutRequest,
    ManualAiApproveRequest,
    ManualAiPlanImportRequest,
    RefreshRequest,
    TradeReviewAttachmentRequest,
    TradeReviewRequest,
    TradeVisibilityRequest,
    WeeklyJournalRequest,
    ZoneActivationRequest,
    ZoneCreateRequest,
    ZoneImportRequest,
    ZoneOverrideRequest,
)
from .api_utils import (
    ValueErrorForApi,
    json_loads,
    normalize_trade_review_request,
    parse_playbooks,
    resolve_override_expiry,
    resolve_price_zone_expiry,
    trade_review_row_to_api,
    utc_now_iso,
    validate_context_value,
    validate_regime_overlays,
    validate_zone_type,
)
from .auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    is_refresh_token_valid,
    purge_expired_refresh_tokens,
    revoke_refresh_token,
    store_refresh_token,
    verify_password,
)
from .chart import build_chart_payload, trade_order_row_to_chart
from .config import DEFAULT_CONFIG_PATH, load_config
from .context import MarketContext, detect_bias_context, detect_regime_context
from .db import connect, init_db
from .news_calendar import active_news_blackout, upcoming_news_events
from .replay_chart import build_realtime_replay_payload
from .runtime_env import load_runtime_env
from .smc_zones import apply_persisted_fvg_mitigation
from .spread import spread_summary
from .strategy.types import DEFAULT_TRADE_MODES_BY_ZONE_TYPE, TRADE_MODES


MAX_CHART_LIMIT = 15_000
MAX_REVIEW_ATTACHMENT_BYTES = 5 * 1024 * 1024
REVIEW_ATTACHMENT_KINDS = {"entry", "exit", "review", "manual"}

_http_bearer = HTTPBearer(auto_error=False)


def require_timezone_aware_iso(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field_name} must be an ISO-8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HTTPException(status_code=422, detail=f"{field_name} must include a timezone")
    return parsed


def zone_is_duplicate_eligible(row: Any, latest_m15_time: str | None, watch_bars: int) -> bool:
    if row["status"] in {"active", "draft"}:
        return True
    if row["status"] != "mitigated" or row["zone_type"] != "fvg" or latest_m15_time is None:
        return False
    fill_time = row["invalidated_at"] or row["valid_until"]
    if fill_time is None:
        return False
    try:
        latest = datetime.fromisoformat(latest_m15_time)
        filled = datetime.fromisoformat(fill_time)
    except ValueError:
        return False
    return filled >= latest - timedelta(minutes=15 * max(watch_bars, 1))


def zones_are_duplicates(candidate: Any, existing: Any) -> bool:
    if candidate["symbol"] != existing["symbol"] or candidate["timeframe"] != existing["timeframe"]:
        return False
    if candidate["zone_type"] != existing["zone_type"] or candidate["direction"] != existing["direction"]:
        return False
    candidate_low = float(candidate["price_low"])
    candidate_high = float(candidate["price_high"])
    existing_low = float(existing["price_low"])
    existing_high = float(existing["price_high"])
    candidate_width = max(candidate_high - candidate_low, 1e-9)
    existing_width = max(existing_high - existing_low, 1e-9)
    overlap = max(0.0, min(candidate_high, existing_high) - max(candidate_low, existing_low))
    overlap_smaller = overlap / min(candidate_width, existing_width)
    center_distance = abs((candidate_low + candidate_high) / 2 - (existing_low + existing_high) / 2)
    exact = abs(candidate_low - existing_low) <= 0.01 and abs(candidate_high - existing_high) <= 0.01
    return exact or overlap_smaller >= 0.70 or center_distance <= max(candidate_width, existing_width) * 0.65


def validate_chart_drawing(request: ChartDrawingCreateRequest | ChartDrawingUpdateRequest, drawing_type: str) -> None:
    anchors = request.anchors
    if anchors is None:
        return
    expected = 2 if drawing_type == "fib_retracement" else 1
    if len(anchors) != expected:
        raise HTTPException(status_code=422, detail=f"{drawing_type} requires exactly {expected} anchor(s)")
    for index, anchor in enumerate(anchors):
        require_timezone_aware_iso(anchor.time, f"anchors[{index}].time")
    if drawing_type == "fib_retracement" and anchors[0].time == anchors[1].time and anchors[0].price == anchors[1].price:
        raise HTTPException(status_code=422, detail="Fib anchors must not be identical")
    if drawing_type == "note" and isinstance(request, ChartDrawingCreateRequest) and not (request.content or "").strip():
        raise HTTPException(status_code=422, detail="Note content must not be empty")


def chart_drawing_row_to_api(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "drawing_type": row["drawing_type"],
        "origin_timeframe": row["origin_timeframe"],
        "visible_timeframes": json_loads(row["visible_timeframes_json"], []),
        "anchors": json_loads(row["anchors_json"], []),
        "properties": json_loads(row["properties_json"], {}),
        "content": row["content"],
        "locked": bool(row["locked"]),
        "hidden": bool(row["hidden"]),
        "revision": int(row["revision"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def manual_ai_row_to_api(row: Any) -> dict[str, Any]:
    context_snapshot = json_loads(row["context_snapshot_json"], {})
    expires_in_minutes: int | None = None
    try:
        as_of = datetime.fromisoformat(str(context_snapshot["as_of"]))
        expires_at = datetime.fromisoformat(str(row["expires_at"]))
        expires_in_minutes = round((expires_at - as_of).total_seconds() / 60)
    except (KeyError, TypeError, ValueError):
        pass
    return {
        "id": row["id"],
        "client_id": row["client_id"],
        "account_label": row["account_label"],
        "symbol": row["symbol"],
        "playbook": "manual_ai_v1",
        "side": row["side"],
        "status": row["status"],
        "execution_state": row["execution_state"],
        "order_type": "limit",
        "entry_price": float(row["entry_price"]),
        "stop_loss": float(row["stop_loss"]),
        "take_profit": float(row["take_profit"]),
        "risk_pct": float(row["risk_pct"]),
        "risk_reward": float(row["risk_reward"]),
        "expires_at": row["expires_at"],
        "expires_in_minutes": expires_in_minutes,
        "partial_take_profit": json_loads(row["partial_take_profit_json"], {}),
        "cancel_conditions": json_loads(row["cancel_conditions_json"], []),
        "questionnaire": json_loads(row["questionnaire_json"], {}),
        "market_context": context_snapshot,
        "trade_idea_id": row["trade_idea_id"],
        "execution_request_id": row["execution_request_id"],
        "approved_at": row["approved_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def validate_manual_ai_envelope(request: ManualAiPlanImportRequest) -> list[tuple[Any, float, str]]:
    as_of = require_timezone_aware_iso(request.as_of, "as_of")
    if request.symbol.upper() != "XAUUSD":
        raise HTTPException(status_code=422, detail="Manual AI V1 currently supports XAUUSD only")
    expected_timeframes = {"context": "H1", "structure": "M15", "execution": "M5"}
    if request.analysis_timeframes != expected_timeframes:
        raise HTTPException(status_code=422, detail=f"analysis_timeframes must equal {expected_timeframes}")
    primary_count = sum(candidate.execution_state == "primary" for candidate in request.candidates)
    if primary_count != 1:
        raise HTTPException(status_code=422, detail="Exactly one candidate must have execution_state=primary")
    priorities = [candidate.priority for candidate in request.candidates]
    if len(priorities) != len(set(priorities)):
        raise HTTPException(status_code=422, detail="Candidate priorities must be unique")
    client_ids = [candidate.client_id for candidate in request.candidates]
    if len(client_ids) != len(set(client_ids)):
        raise HTTPException(status_code=422, detail="Candidate client_id values must be unique")

    validated: list[tuple[Any, float, str]] = []
    for index, candidate in enumerate(request.candidates):
        expires_at = as_of + timedelta(minutes=candidate.expires_in_minutes)
        if candidate.side == "buy":
            valid_geometry = candidate.stop_loss < candidate.entry_price < candidate.take_profit
        else:
            valid_geometry = candidate.take_profit < candidate.entry_price < candidate.stop_loss
        if not valid_geometry:
            raise HTTPException(status_code=422, detail=f"candidates[{index}] has invalid {candidate.side} price geometry")
        risk = abs(candidate.entry_price - candidate.stop_loss)
        reward = abs(candidate.take_profit - candidate.entry_price)
        risk_reward = reward / risk
        if not 1.5 <= risk_reward <= 4.0:
            raise HTTPException(
                status_code=422,
                detail=f"candidates[{index}] risk/reward must be between 1.5 and 4.0; calculated={risk_reward:.3f}",
            )
        for condition_index, condition in enumerate(candidate.cancel_conditions):
            if condition.type.endswith(("below", "above")) and condition.price is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"candidates[{index}].cancel_conditions[{condition_index}].price is required",
                )
        validated.append((candidate, risk_reward, expires_at.isoformat()))
    return validated


def create_app(config_path: Path | str = DEFAULT_CONFIG_PATH, env_path: Path | str | None = None):
    from fastapi import Body, FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware

    resolved_config_path = os.environ.get("SEMI_BOT_CONFIG_PATH") or config_path
    resolved_env_path = env_path or os.environ.get("SEMI_BOT_ENV_PATH") or ".env"
    config = load_config(resolved_config_path)
    env = load_runtime_env(resolved_env_path)

    # ------------------------------------------------------------------
    # Startup validation — catch misconfigurations early
    # ------------------------------------------------------------------
    if not env.secret_key:
        raise RuntimeError(
            "SECRET_KEY is not set in .env — JWT auth will not work.\n"
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\"\n"
            "Then add: SECRET_KEY=\"<value>\" to your .env file."
        )
    if len(env.secret_key) < 32:
        import warnings
        warnings.warn(
            f"SECRET_KEY is only {len(env.secret_key)} chars — use at least 32 random hex chars for security.",
            stacklevel=1,
        )
    if not env.admin_password_hash:
        import warnings
        warnings.warn(
            "ADMIN_PASSWORD_HASH is not set — login endpoint will return 503.\n"
            "Run: semi-bot hash-password   to generate a hash.",
            stacklevel=1,
        )

    app = FastAPI(title="Semi Bot Trading API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=env.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Auth dependency — injected into every protected endpoint
    # ------------------------------------------------------------------

    def require_auth(
        credentials: HTTPAuthorizationCredentials | None = Depends(_http_bearer),
    ) -> str:
        """Validate the Bearer access token. Returns the username on success."""
        if credentials is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        try:
            payload = decode_token(credentials.credentials, env.secret_key)
            if payload.get("type") != "access":
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
            return str(payload["sub"])
        except Exception:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    # ------------------------------------------------------------------
    # Auth endpoints (public — no require_auth)
    # ------------------------------------------------------------------

    @app.post("/api/auth/login")
    def auth_login(body: LoginRequest) -> dict[str, Any]:
        if not env.admin_password_hash:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Auth not configured. Set ADMIN_PASSWORD_HASH in .env.",
            )
        if body.username != env.admin_username:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        if not verify_password(body.password, env.admin_password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        access_token = create_access_token(body.username, env.secret_key)
        refresh_token = create_refresh_token(body.username, env.secret_key)
        with connect(config.database) as conn:
            init_db(conn)
            purge_expired_refresh_tokens(conn)
            store_refresh_token(conn, refresh_token, body.username)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": 900,
            "username": body.username,
        }

    @app.post("/api/auth/refresh")
    def auth_refresh(body: RefreshRequest) -> dict[str, Any]:
        try:
            payload = decode_token(body.refresh_token, env.secret_key)
            if payload.get("type") != "refresh":
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
            username = str(payload["sub"])
        except Exception:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
        with connect(config.database) as conn:
            init_db(conn)
            if not is_refresh_token_valid(conn, body.refresh_token):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked or expired")
        access_token = create_access_token(username, env.secret_key)
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": 900,
            "username": username,
        }

    @app.post("/api/auth/logout")
    def auth_logout(
        body: LogoutRequest,
        _username: str = Depends(require_auth),
    ) -> dict[str, Any]:
        with connect(config.database) as conn:
            init_db(conn)
            revoke_refresh_token(conn, body.refresh_token)
        return {"ok": True}

    # ------------------------------------------------------------------
    # Public health (no auth — useful for uptime checks)
    # ------------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "symbol": config.symbol,
            "database": str(config.database),
        }

    @app.get("/api/chart")
    def chart(
        symbol: str = Query(default=None),
        timeframe: str = Query(default="H1"),
        limit: int = Query(default=300, ge=1, le=MAX_CHART_LIMIT),
        start_index: int | None = Query(default=None, ge=0),
        start: str | None = None,
        end: str | None = None,
        replay_at: str | None = None,
        replay_start: str | None = None,
        active_zones_only: bool = False,
        playbooks: str | None = None,
        _: str = Depends(require_auth),
    ) -> dict[str, Any]:
        try:
            allowed_playbooks = parse_playbooks(playbooks)
            with connect(config.database) as conn:
                init_db(conn)
                expire_context_overrides(conn, utc_now_iso())
                apply_persisted_fvg_mitigation(conn, symbol or config.symbol, config.bias.timeframe)
                if replay_at:
                    if replay_start is None:
                        raise HTTPException(status_code=422, detail="replay_start is required when replay_at is provided")
                    return build_realtime_replay_payload(
                        conn,
                        config,
                        symbol=symbol or config.symbol,
                        timeframe=timeframe.upper(),
                        limit=limit,
                        replay_start=replay_start,
                        replay_at=replay_at,
                        active_zones_only=active_zones_only,
                        allowed_playbooks=allowed_playbooks,
                    )
                payload = build_chart_payload(
                    conn,
                    symbol=symbol or config.symbol,
                    timeframe=timeframe.upper(),
                    limit=limit,
                    start_index=start_index,
                    start=start,
                    end=end,
                    active_zones_only=active_zones_only,
                    structure_timeframe=config.bias.timeframe,
                    strategy_config=config.strategy,
                    allowed_playbooks=allowed_playbooks,
                    macro_trend_config=config.macro_trend,
                )
                return payload
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/replay/timeline")
    def replay_timeline(
        symbol: str = Query(default=None),
        timeframe: str = Query(default="H1"),
        limit: int = Query(default=300, ge=1, le=MAX_CHART_LIMIT),
        start_index: int | None = Query(default=None, ge=0),
        _: str = Depends(require_auth),
    ) -> dict[str, Any]:
        with connect(config.database) as conn:
            init_db(conn)
            resolved_symbol = symbol or config.symbol
            resolved_timeframe = timeframe.upper()
            total_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM candles
                    WHERE symbol = ? AND timeframe = ?
                    """,
                    (resolved_symbol, resolved_timeframe),
                ).fetchone()["count"]
            )
            if start_index is None:
                rows = conn.execute(
                    """
                    SELECT open_time
                    FROM (
                        SELECT open_time
                        FROM candles
                        WHERE symbol = ? AND timeframe = ?
                        ORDER BY open_time DESC
                        LIMIT ?
                    )
                    ORDER BY open_time
                    """,
                    (resolved_symbol, resolved_timeframe, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT open_time
                    FROM candles
                    WHERE symbol = ? AND timeframe = ?
                    ORDER BY open_time
                    LIMIT ? OFFSET ?
                    """,
                    (resolved_symbol, resolved_timeframe, limit, start_index),
                ).fetchall()
            times = [row["open_time"] for row in rows]
            return {
                "symbol": resolved_symbol,
                "timeframe": resolved_timeframe,
                "limit": limit,
                "start_index": start_index,
                "total_count": total_count,
                "times": times,
                "start": times[0] if times else None,
                "end": times[-1] if times else None,
                "count": len(times),
            }

    @app.get("/api/accounts")
    def get_accounts(_: str = Depends(require_auth)) -> dict[str, Any]:
        """Return latest account snapshot for every connected MT5 account.

        Response is always a list so the frontend is multi-account-ready from day one.
        Each worker instance upserts its own row keyed by ACCOUNT_LABEL.
        """
        with connect(config.database) as conn:
            rows = conn.execute(
                """
                SELECT a.account_label, a.broker, a.login, a.server,
                       a.balance, a.equity, a.margin, a.free_margin, a.profit, a.currency, a.snapshot_at,
                       d.trading_day, d.timezone AS daily_timezone, d.balance_at_midnight,
                       d.daily_profit, d.daily_profit_pct, d.initial_balance, d.baseline_source,
                       c.requested_enabled, c.effective_enabled, c.hard_enabled, c.worker_status,
                       c.open_bot_positions, c.pending_bot_orders, c.heartbeat_at,
                       c.partial_take_profit_enabled, c.partial_take_profit_r,
                       c.manual_lock_requested_enabled, c.manual_lock_effective_enabled,
                       c.manual_lock_baseline_positions_json, c.manual_lock_baseline_orders_json,
                       c.manual_lock_requested_at, c.manual_lock_acknowledged_at,
                       c.manual_lock_last_action_at, c.manual_lock_last_error
                FROM account_snapshots a
                LEFT JOIN account_daily_metrics d
                  ON d.account_label = a.account_label
                 AND d.trading_day = (
                    SELECT MAX(d2.trading_day) FROM account_daily_metrics d2
                    WHERE d2.account_label = a.account_label
                 )
                LEFT JOIN account_execution_controls c ON c.account_label = a.account_label
                ORDER BY a.account_label
                """
            ).fetchall()
        return {
            "accounts": [
                {
                    "label":       row["account_label"],
                    "broker":      row["broker"],
                    "login":       row["login"],
                    "server":      row["server"],
                    "balance":     row["balance"],
                    "equity":      row["equity"],
                    "margin":      row["margin"],
                    "free_margin": row["free_margin"],
                    "profit":      row["profit"],
                    "currency":    row["currency"],
                    "snapshot_at": row["snapshot_at"],
                    "daily": {
                        "trading_day": row["trading_day"],
                        "timezone": row["daily_timezone"],
                        "balance_at_midnight": row["balance_at_midnight"],
                        "profit": row["daily_profit"],
                        "profit_pct": row["daily_profit_pct"],
                        "initial_balance": row["initial_balance"],
                        "baseline_source": row["baseline_source"],
                    },
                    "execution": {
                        "requested_enabled": bool(row["requested_enabled"]),
                        "effective_enabled": bool(row["effective_enabled"]),
                        "hard_enabled": bool(row["hard_enabled"]),
                        "worker_status": row["worker_status"] or "offline",
                        "open_bot_positions": row["open_bot_positions"] or 0,
                        "pending_bot_orders": row["pending_bot_orders"] or 0,
                        "heartbeat_at": row["heartbeat_at"],
                    },
                    "partial_take_profit": {
                        "enabled": True if row["partial_take_profit_enabled"] is None else bool(row["partial_take_profit_enabled"]),
                        "trigger_r": float(row["partial_take_profit_r"] or 1.25),
                    },
                    "manual_trading_lock": {
                        "requested_enabled": bool(row["manual_lock_requested_enabled"]),
                        "effective_enabled": bool(row["manual_lock_effective_enabled"]),
                        "baseline_position_count": len(json_loads(row["manual_lock_baseline_positions_json"], [])),
                        "baseline_order_count": len(json_loads(row["manual_lock_baseline_orders_json"], [])),
                        "requested_at": row["manual_lock_requested_at"],
                        "acknowledged_at": row["manual_lock_acknowledged_at"],
                        "last_action_at": row["manual_lock_last_action_at"],
                        "last_error": row["manual_lock_last_error"],
                    },
                }
                for row in rows
            ]
        }

    @app.patch("/api/accounts/{account_label}/execution")
    def update_account_execution(
        account_label: str,
        request: AccountExecutionControlRequest = Body(...),
        username: str = Depends(require_auth),
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        with connect(config.database) as conn:
            row = conn.execute(
                "SELECT * FROM account_execution_controls WHERE account_label = ?",
                (account_label,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Account worker has not registered yet")
            if request.enabled:
                heartbeat = datetime.fromisoformat(row["heartbeat_at"]) if row["heartbeat_at"] else None
                fresh = heartbeat is not None and now - heartbeat.astimezone(UTC) <= timedelta(seconds=90)
                if not row["hard_enabled"]:
                    raise HTTPException(status_code=409, detail="EXECUTION_ENABLED is false in the worker environment")
                if not fresh:
                    raise HTTPException(status_code=409, detail="Worker is offline or its heartbeat is stale")
            conn.execute(
                """
                UPDATE account_execution_controls
                SET requested_enabled = ?, effective_enabled = ?, requested_by = ?, last_error = NULL,
                    requested_at = ?, updated_at = ?
                WHERE account_label = ?
                """,
                (int(request.enabled), int(request.enabled and bool(row["hard_enabled"])), username, now_iso, now_iso, account_label),
            )
            conn.commit()
        return {"label": account_label, "requested_enabled": request.enabled, "status": "pending_worker_ack"}

    @app.patch("/api/accounts/{account_label}/manual-trading-lock")
    def update_account_manual_trading_lock(
        account_label: str,
        request: AccountManualTradingLockRequest,
        username: str = Depends(require_auth),
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        now_iso = now.isoformat()
        with connect(config.database) as conn:
            row = conn.execute(
                "SELECT heartbeat_at FROM account_execution_controls WHERE account_label = ?",
                (account_label,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Account worker has not registered yet")
            if request.enabled:
                heartbeat = datetime.fromisoformat(row["heartbeat_at"]) if row["heartbeat_at"] else None
                fresh = heartbeat is not None and now - heartbeat.astimezone(UTC) <= timedelta(seconds=90)
                if not fresh:
                    raise HTTPException(status_code=409, detail="Worker is offline or its heartbeat is stale")
            conn.execute(
                """
                UPDATE account_execution_controls
                SET manual_lock_requested_enabled = ?, manual_lock_effective_enabled = 0,
                    manual_lock_baseline_positions_json = '[]', manual_lock_baseline_orders_json = '[]',
                    manual_lock_requested_at = ?, manual_lock_acknowledged_at = NULL,
                    manual_lock_last_error = NULL, requested_by = ?, updated_at = ?
                WHERE account_label = ?
                """,
                (int(request.enabled), now_iso, username, now_iso, account_label),
            )
            conn.commit()
        return {
            "label": account_label,
            "requested_enabled": request.enabled,
            "effective_enabled": False,
            "status": "pending_worker_ack" if request.enabled else "disabled",
        }

    @app.patch("/api/accounts/{account_label}/partial-take-profit")
    def update_account_partial_take_profit(
        account_label: str,
        request: AccountPartialTakeProfitRequest = Body(...),
        username: str = Depends(require_auth),
    ) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        with connect(config.database) as conn:
            row = conn.execute(
                "SELECT 1 FROM account_execution_controls WHERE account_label = ?",
                (account_label,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Account worker has not registered yet")
            conn.execute(
                """
                UPDATE account_execution_controls
                SET partial_take_profit_enabled = ?, partial_take_profit_r = ?,
                    requested_by = ?, requested_at = ?, updated_at = ?
                WHERE account_label = ?
                """,
                (int(request.enabled), float(request.trigger_r), username, now, now, account_label),
            )
            conn.commit()
        return {
            "label": account_label,
            "partial_take_profit": {
                "enabled": request.enabled,
                "trigger_r": request.trigger_r,
            },
            "status": "saved",
        }

    @app.post("/api/accounts/{account_label}/close-all", status_code=202)
    def close_all_bot_trades(
        account_label: str,
        request: AccountCloseAllRequest = Body(default=AccountCloseAllRequest()),
        username: str = Depends(require_auth),
    ) -> dict[str, Any]:
        command_id = f"account-command-{uuid.uuid4()}"
        idempotency_key = request.idempotency_key or command_id
        now = datetime.now(UTC).isoformat()
        with connect(config.database) as conn:
            account = conn.execute("SELECT 1 FROM account_snapshots WHERE account_label = ?", (account_label,)).fetchone()
            if account is None:
                raise HTTPException(status_code=404, detail="Account not found")
            existing = conn.execute(
                "SELECT id, status FROM account_execution_commands WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                return {"command_id": existing["id"], "status": existing["status"]}
            conn.execute(
                "UPDATE account_execution_controls SET requested_enabled = 0, effective_enabled = 0, requested_by = ?, requested_at = ?, updated_at = ? WHERE account_label = ?",
                (username, now, now, account_label),
            )
            conn.execute(
                """
                INSERT INTO account_execution_commands
                    (id, account_label, command_type, status, requested_by, requested_at, payload_json, idempotency_key)
                VALUES (?, ?, 'close_all_positions', 'pending', ?, ?, ?, ?)
                """,
                (
                    command_id,
                    account_label,
                    username,
                    now,
                    json.dumps({"include_manual_positions": request.include_manual_positions}),
                    idempotency_key,
                ),
            )
            conn.commit()
        return {
            "command_id": command_id,
            "status": "pending",
            "bot_paused": True,
            "include_manual_positions": request.include_manual_positions,
        }

    @app.get("/api/account-commands/{command_id}")
    def get_account_command(command_id: str, _: str = Depends(require_auth)) -> dict[str, Any]:
        with connect(config.database) as conn:
            row = conn.execute("SELECT * FROM account_execution_commands WHERE id = ?", (command_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Command not found")
        return {
            "command_id": row["id"], "account_label": row["account_label"], "status": row["status"],
            "result": json.loads(row["result_json"] or "{}"), "error": row["error"],
        }

    @app.get("/api/news")
    def get_news(
        hours_ahead: int = Query(default=48, ge=1, le=168),
        _: str = Depends(require_auth),
    ) -> dict[str, Any]:
        """Return upcoming tier-1/2 news events and any active blackout."""
        from datetime import UTC, datetime
        now = datetime.now(UTC)
        with connect(config.database) as conn:
            events = upcoming_news_events(conn, now=now, hours_ahead=hours_ahead)
            blackout = active_news_blackout(conn, now=now)
        return {"events": events, "active_blackout": blackout}

    @app.get("/api/spread")
    def get_spread(
        symbol: str | None = Query(default=None),
        account_label: str | None = Query(default=None),
        hours: int = Query(default=24, ge=1, le=168),
        _: str = Depends(require_auth),
    ) -> dict[str, Any]:
        """Return current/latest spread and summary stats in price units."""
        resolved_symbol = symbol or config.symbol
        with connect(config.database) as conn:
            return spread_summary(conn, resolved_symbol, account_label=account_label, hours=hours)

    @app.get("/api/trades")
    def trades(
        symbol: str = Query(default=None),
        timeframe: str = Query(default="H1"),
        limit: int = Query(default=200, ge=1, le=5000),
        offset: int = Query(default=0, ge=0),
        playbooks: str | None = None,
        status: str | None = None,
        side: str | None = None,
        outcome: str | None = Query(default=None),
        zone_type: str | None = Query(default=None),
        reaction: str | None = Query(default=None),
        trade_id: str | None = Query(default=None),
        account_label: str | None = Query(default=None),
        backtest: bool | None = Query(default=None),
        sort: str = Query(default="opened_at_desc"),
        _: str = Depends(require_auth),
    ) -> dict[str, Any]:
        resolved_symbol = symbol or config.symbol
        resolved_timeframe = timeframe.upper()
        allowed_playbooks = parse_playbooks(playbooks)
        where = ["trade_orders.symbol = ?", "trade_orders.opened_at IS NOT NULL"]
        params: list[Any] = [resolved_symbol]
        if allowed_playbooks is not None:
            if not allowed_playbooks:
                return {
                    "symbol": resolved_symbol,
                    "timeframe": resolved_timeframe,
                    "limit": limit,
                    "offset": offset,
                    "total": 0,
                    "trades": [],
                }
            placeholders = ", ".join("?" for _ in allowed_playbooks)
            where.append(f"trade_ideas.playbook IN ({placeholders})")
            params.extend(sorted(allowed_playbooks))
        if status:
            where.append("trade_orders.status = ?")
            params.append(status)
        if side:
            if side not in {"buy", "sell", "long", "short"}:
                raise HTTPException(status_code=422, detail="side must be buy, sell, long, or short")
            where.append("trade_orders.side = ?")
            params.append("buy" if side == "long" else "sell" if side == "short" else side)
        if outcome:
            if outcome == "win":
                where.append("trade_orders.pnl_r > 0")
            elif outcome == "loss":
                where.append("trade_orders.pnl_r <= 0")
            elif outcome != "all":
                raise HTTPException(status_code=422, detail="outcome must be all, win, or loss")
        if zone_type:
            allowed_zone_types = {"support", "resistance", "fvg", "order_block", "liquidity_pool", "consolidation"}
            if zone_type not in allowed_zone_types:
                raise HTTPException(status_code=422, detail=f"zone_type must be one of: {', '.join(sorted(allowed_zone_types))}")
            where.append(
                "COALESCE("
                "json_extract(trade_orders.metadata_json, '$.candidate_metadata.zone_type'), "
                "json_extract(trade_orders.metadata_json, '$.zone_type')"
                ") = ?"
            )
            params.append(zone_type)
        if reaction:
            allowed_reactions = {"reject", "fakeout", "waiting_bos", "slow_reaction"}
            if reaction not in allowed_reactions:
                raise HTTPException(status_code=422, detail=f"reaction must be one of: {', '.join(sorted(allowed_reactions))}")
            where.append(
                "COALESCE("
                "json_extract(trade_orders.metadata_json, '$.zone_reaction_state'), "
                "json_extract(trade_orders.metadata_json, '$.candidate_metadata.zone_reaction_state')"
                ") = ?"
            )
            params.append(reaction)
        if trade_id:
            trade_id_search = trade_id.strip()
            if trade_id_search:
                where.append("(trade_orders.id LIKE ? OR trade_orders.trade_idea_id LIKE ?)")
                params.extend([f"%{trade_id_search}%", f"%{trade_id_search}%"])
        if account_label:
            account_label_search = account_label.strip()
            if account_label_search:
                where.append("trade_orders.account_label = ?")
                params.append(account_label_search)
        if backtest is True:
            where.append("trade_orders.source = 'backtest'")
        elif backtest is False:
            where.append("trade_orders.source = 'live'")

        order_by = {
            "opened_at_desc": "trade_orders.opened_at DESC",
            "opened_at_asc": "trade_orders.opened_at ASC",
            "pnl_r_desc": "trade_orders.pnl_r DESC, trade_orders.opened_at DESC",
            "pnl_r_asc": "trade_orders.pnl_r ASC, trade_orders.opened_at DESC",
            "sl_size_desc": "CASE WHEN trade_orders.entry_price IS NULL OR trade_orders.stop_loss IS NULL THEN 1 ELSE 0 END, ABS(trade_orders.entry_price - trade_orders.stop_loss) DESC, trade_orders.opened_at DESC",
            "sl_size_asc": "CASE WHEN trade_orders.entry_price IS NULL OR trade_orders.stop_loss IS NULL THEN 1 ELSE 0 END, ABS(trade_orders.entry_price - trade_orders.stop_loss) ASC, trade_orders.opened_at DESC",
        }.get(sort)
        if order_by is None:
            raise HTTPException(
                status_code=422,
                detail="sort must be opened_at_desc, opened_at_asc, pnl_r_desc, pnl_r_asc, sl_size_desc, or sl_size_asc",
            )

        where_sql = " AND ".join(where)
        with connect(config.database) as conn:
            init_db(conn)
            total = int(
                conn.execute(
                    f"""
                    SELECT COUNT(*) AS count
                    FROM trade_orders
                    JOIN trade_ideas ON trade_ideas.id = trade_orders.trade_idea_id
                    WHERE {where_sql}
                    """,
                    params,
                ).fetchone()["count"]
            )
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
                       trade_reviews.updated_at AS review_updated_at,
                       (
                         SELECT COUNT(*) - 1
                         FROM candles
                         WHERE candles.symbol = trade_orders.symbol
                           AND candles.timeframe = ?
                           AND candles.open_time <= trade_orders.opened_at
                       ) AS chart_index
                FROM trade_orders
                JOIN trade_ideas ON trade_ideas.id = trade_orders.trade_idea_id
                LEFT JOIN trade_reviews ON trade_reviews.trade_order_id = trade_orders.id
                WHERE {where_sql}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
                """,
                [resolved_timeframe, *params, limit, offset],
            ).fetchall()
        return {
            "symbol": resolved_symbol,
            "timeframe": resolved_timeframe,
            "limit": limit,
            "offset": offset,
            "total": total,
            "trades": [
                {
                    **trade_order_row_to_chart(row),
                    "chart_index": int(row["chart_index"]) if row["chart_index"] is not None and int(row["chart_index"]) >= 0 else None,
                }
                for row in rows
            ],
        }

    @app.patch("/api/trades/{trade_order_id}/visibility")
    def update_trade_visibility(
        trade_order_id: str,
        request: TradeVisibilityRequest = Body(...),
        _: str = Depends(require_auth),
    ) -> dict[str, Any]:
        with connect(config.database) as conn:
            init_db(conn)
            updated = conn.execute(
                """
                UPDATE trade_orders
                SET hidden_on_chart = ?, updated_at = ?
                WHERE id = ?
                """,
                (int(request.hidden_on_chart), utc_now_iso(), trade_order_id),
            )
            if updated.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Trade not found: {trade_order_id}")
            conn.commit()
        return {"id": trade_order_id, "hidden_on_chart": request.hidden_on_chart}

    @app.get("/api/trades/{trade_order_id}/review")
    def get_trade_review(trade_order_id: str, _: str = Depends(require_auth)) -> dict[str, Any]:
        with connect(config.database) as conn:
            init_db(conn)
            ensure_trade_exists(conn, trade_order_id)
            row = conn.execute(
                """
                SELECT *
                FROM trade_reviews
                WHERE trade_order_id = ?
                """,
                (trade_order_id,),
            ).fetchone()
        return trade_review_row_to_api(row, trade_order_id)

    @app.put("/api/trades/{trade_order_id}/review")
    def upsert_trade_review(trade_order_id: str, request: TradeReviewRequest = Body(...), _: str = Depends(require_auth)) -> dict[str, Any]:
        normalized = normalize_trade_review_request(request)
        now = utc_now_iso()
        with connect(config.database) as conn:
            init_db(conn)
            ensure_trade_exists(conn, trade_order_id)
            existing = conn.execute(
                """
                SELECT id, created_at
                FROM trade_reviews
                WHERE trade_order_id = ?
                """,
                (trade_order_id,),
            ).fetchone()
            review_id = existing["id"] if existing is not None else f"trade-review-{uuid.uuid4()}"
            created_at = existing["created_at"] if existing is not None else now
            conn.execute(
                """
                INSERT INTO trade_reviews (
                    id, trade_order_id, grade, verdict, mistake_tags_json,
                    should_trade_again, comment, metadata_json, reviewer, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_order_id) DO UPDATE SET
                    grade = excluded.grade,
                    verdict = excluded.verdict,
                    mistake_tags_json = excluded.mistake_tags_json,
                    should_trade_again = excluded.should_trade_again,
                    comment = excluded.comment,
                    metadata_json = excluded.metadata_json,
                    reviewer = excluded.reviewer,
                    updated_at = excluded.updated_at
                """,
                (
                    review_id,
                    trade_order_id,
                    normalized["grade"],
                    normalized["verdict"],
                    json.dumps(normalized["mistake_tags"], ensure_ascii=False),
                    normalized["should_trade_again"],
                    normalized["comment"],
                    json.dumps(normalized["metadata"], ensure_ascii=False, sort_keys=True),
                    normalized["reviewer"],
                    created_at,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM trade_reviews
                WHERE trade_order_id = ?
                """,
                (trade_order_id,),
            ).fetchone()
            conn.commit()
        return trade_review_row_to_api(row, trade_order_id)

    @app.get("/api/trades/{trade_order_id}/attachments")
    def list_trade_review_attachments(trade_order_id: str, _: str = Depends(require_auth)) -> list[dict[str, Any]]:
        with connect(config.database) as conn:
            init_db(conn)
            ensure_trade_exists(conn, trade_order_id)
            rows = conn.execute(
                """
                SELECT *
                FROM trade_review_attachments
                WHERE trade_order_id = ?
                ORDER BY created_at DESC, id DESC
                """,
                (trade_order_id,),
            ).fetchall()
        return [attachment_row_to_api(row) for row in rows]

    @app.post("/api/trades/{trade_order_id}/attachments")
    def create_trade_review_attachment(
        trade_order_id: str,
        request: TradeReviewAttachmentRequest = Body(...),
        _: str = Depends(require_auth),
    ) -> dict[str, Any]:
        kind = request.kind.strip().lower()
        if kind not in REVIEW_ATTACHMENT_KINDS:
            raise HTTPException(status_code=422, detail=f"kind must be one of: {', '.join(sorted(REVIEW_ATTACHMENT_KINDS))}")
        image_bytes = decode_review_png(request.image_data)
        caption = request.caption.strip()
        if len(caption) > 500:
            raise HTTPException(status_code=422, detail="caption is too long")

        now = utc_now_iso()
        attachment_id = f"trade-attachment-{uuid.uuid4()}"
        relative_path = Path("var") / "journal-screenshots" / safe_segment(trade_order_id) / f"{attachment_id}.png"
        full_path = safe_review_attachment_path(str(relative_path))
        with connect(config.database) as conn:
            init_db(conn)
            ensure_trade_exists(conn, trade_order_id)
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_bytes(image_bytes)
            conn.execute(
                """
                INSERT INTO trade_review_attachments (
                    id, trade_order_id, kind, file_path, caption,
                    chart_symbol, chart_timeframe, chart_start, chart_end, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attachment_id,
                    trade_order_id,
                    kind,
                    str(relative_path),
                    caption,
                    clean_optional_text(request.chart_symbol, 40),
                    clean_optional_text(request.chart_timeframe, 20),
                    clean_optional_text(request.chart_start, 80),
                    clean_optional_text(request.chart_end, 80),
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT *
                FROM trade_review_attachments
                WHERE id = ?
                """,
                (attachment_id,),
            ).fetchone()
            conn.commit()
        return attachment_row_to_api(row)

    @app.get("/api/trades/{trade_order_id}/attachments/{attachment_id}/file")
    def get_trade_review_attachment_file(trade_order_id: str, attachment_id: str, _: str = Depends(require_auth)) -> FileResponse:
        with connect(config.database) as conn:
            init_db(conn)
            ensure_trade_exists(conn, trade_order_id)
            row = conn.execute(
                """
                SELECT *
                FROM trade_review_attachments
                WHERE id = ? AND trade_order_id = ?
                """,
                (attachment_id, trade_order_id),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Attachment not found")
        path = safe_review_attachment_path(row["file_path"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="Attachment file not found")
        return FileResponse(path, media_type="image/png", filename=f"{attachment_id}.png")

    @app.delete("/api/trades/{trade_order_id}/attachments/{attachment_id}")
    def delete_trade_review_attachment(trade_order_id: str, attachment_id: str, _: str = Depends(require_auth)) -> dict[str, Any]:
        with connect(config.database) as conn:
            init_db(conn)
            ensure_trade_exists(conn, trade_order_id)
            row = conn.execute(
                """
                SELECT *
                FROM trade_review_attachments
                WHERE id = ? AND trade_order_id = ?
                """,
                (attachment_id, trade_order_id),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Attachment not found")
            conn.execute("DELETE FROM trade_review_attachments WHERE id = ?", (attachment_id,))
            conn.commit()
        path = safe_review_attachment_path(row["file_path"])
        if path.exists():
            path.unlink()
        return {"deleted": True, "id": attachment_id}

    @app.get("/api/journal/patterns")
    def journal_patterns(backtest: bool | None = Query(default=False), _: str = Depends(require_auth)) -> dict[str, Any]:
        where = ["trade_orders.closed_at IS NOT NULL", "trade_orders.pnl_r IS NOT NULL"]
        params: list[Any] = []
        if backtest is True:
            where.append("trade_orders.source = 'backtest'")
        elif backtest is False:
            where.append("trade_orders.source = 'live'")
        with connect(config.database) as conn:
            init_db(conn)
            rows = conn.execute(
                f"""
                SELECT trade_orders.pnl_r, trade_orders.metadata_json,
                       trade_reviews.metadata_json AS review_metadata_json
                FROM trade_orders
                LEFT JOIN trade_reviews ON trade_reviews.trade_order_id = trade_orders.id
                WHERE {" AND ".join(where)}
                """,
                params,
            ).fetchall()
        return build_journal_patterns(rows)

    @app.get("/api/weekly-journals")
    def list_weekly_journals(
        limit: int = Query(default=104, ge=1, le=260),
        offset: int = Query(default=0, ge=0),
        _: str = Depends(require_auth),
    ) -> dict[str, Any]:
        with connect(config.database) as conn:
            init_db(conn)
            total = int(conn.execute("SELECT COUNT(*) AS count FROM weekly_journals").fetchone()["count"])
            rows = conn.execute(
                """
                SELECT *
                FROM weekly_journals
                ORDER BY week_start DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return {
            "journals": [weekly_journal_row_to_api(row) for row in rows],
            "total": total,
        }

    @app.get("/api/weekly-journals/{week_start}")
    def get_weekly_journal(week_start: str, _: str = Depends(require_auth)) -> dict[str, Any]:
        normalized_start = parse_week_start(week_start)
        with connect(config.database) as conn:
            init_db(conn)
            row = conn.execute(
                "SELECT * FROM weekly_journals WHERE week_start = ?",
                (normalized_start.isoformat(),),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Weekly journal not found: {week_start}")
        return weekly_journal_row_to_api(row)

    @app.put("/api/weekly-journals/{week_start}")
    def upsert_weekly_journal(
        week_start: str,
        request: WeeklyJournalRequest = Body(...),
        _: str = Depends(require_auth),
    ) -> dict[str, Any]:
        normalized_start = parse_week_start(week_start)
        week_start_value = normalized_start.isoformat()
        week_end_value = (normalized_start + timedelta(days=6)).isoformat()
        now = utc_now_iso()
        with connect(config.database) as conn:
            init_db(conn)
            existing = conn.execute(
                "SELECT id FROM weekly_journals WHERE week_start = ?",
                (week_start_value,),
            ).fetchone()
            journal_id = existing["id"] if existing is not None else f"weekly-journal-{uuid.uuid4()}"
            conn.execute(
                """
                INSERT INTO weekly_journals (
                    id, week_start, week_end, content, content_format, icon,
                    discipline_score, fomo_score, revenge_score, achieved_r,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(week_start) DO UPDATE SET
                    week_end = excluded.week_end,
                    content = excluded.content,
                    content_format = excluded.content_format,
                    icon = excluded.icon,
                    discipline_score = excluded.discipline_score,
                    fomo_score = excluded.fomo_score,
                    revenge_score = excluded.revenge_score,
                    achieved_r = excluded.achieved_r,
                    updated_at = excluded.updated_at
                """,
                (
                    journal_id,
                    week_start_value,
                    week_end_value,
                    request.content,
                    request.content_format,
                    request.icon.strip() or "📝",
                    request.discipline_score,
                    request.fomo_score,
                    request.revenge_score,
                    request.achieved_r,
                    now,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM weekly_journals WHERE week_start = ?",
                (week_start_value,),
            ).fetchone()
        return weekly_journal_row_to_api(row)

    @app.patch("/api/zones/{zone_id}")
    def update_zone(zone_id: str, request: ZoneOverrideRequest = Body(...), _: str = Depends(require_auth)) -> dict[str, Any]:
        if request.price_low >= request.price_high:
            raise HTTPException(status_code=422, detail="price_low must be lower than price_high")
        if request.status not in {"active", "draft", "disabled"}:
            raise HTTPException(status_code=422, detail="status must be active, draft, or disabled")
        if request.trade_modes is not None:
            unknown_modes = sorted(set(request.trade_modes) - {"reject", "internal_reject", "breakout"})
            if unknown_modes:
                raise HTTPException(status_code=422, detail=f"Unknown trade mode(s): {', '.join(unknown_modes)}")

        now = utc_now_iso()
        with connect(config.database) as conn:
            init_db(conn)
            row = conn.execute(
                """
                SELECT *
                FROM price_zones
                WHERE id = ?
                """,
                (zone_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Zone not found: {zone_id}")
            if row["status"] == "draft" and request.status == "active":
                raise HTTPException(
                    status_code=409,
                    detail="Draft SR zones must be activated through the confirmation questionnaire",
                )
            if row["status"] != "draft" and request.status == "draft":
                raise HTTPException(status_code=422, detail="Only newly-created human SR zones may use draft status")

            fields_set = request.model_fields_set if hasattr(request, "model_fields_set") else request.__fields_set__
            start_time = request.visual_start if "visual_start" in fields_set and request.visual_start else row["start_time"]
            requested_end_time = request.visual_end if "visual_end" in fields_set else row["end_time"]
            if row["status"] == "draft" and request.status == "draft" and requested_end_time is None:
                raise HTTPException(status_code=422, detail="Draft zone requires a visual_end")
            expiry_input = request.expires_at
            if request.status == "active" and expiry_input is None and "visual_end" in fields_set:
                expiry_input = requested_end_time
            current_metadata = json_loads(row["metadata_json"], {})
            request_modes = sorted(set(request.trade_modes)) if request.trade_modes is not None else None
            current_modes = sorted(
                mode
                for mode in current_metadata.get("trade_modes", [])
                if mode in {"reject", "internal_reject", "breakout"}
            )
            requested_status = request.status
            current_status = row["status"] if row["status"] in {"active", "draft", "disabled"} else "active"
            confidence = request.confidence if request.confidence is not None else float(row["effective_confidence"])
            reason_text = (request.reason or "").strip()
            no_material_change = (
                not reason_text
                and abs(float(row["price_low"]) - request.price_low) < 0.00001
                and abs(float(row["price_high"]) - request.price_high) < 0.00001
                and start_time == row["start_time"]
                and requested_end_time == row["end_time"]
                and abs(float(row["effective_weight"]) - request.weight) < 0.00001
                and abs(float(row["effective_confidence"]) - confidence) < 0.00001
                and requested_status == current_status
                and (request_modes is None or request_modes == current_modes)
            )
            if no_material_change:
                return zone_row_to_chart(row)

            expires_at = (
                None
                if request.status == "draft"
                else resolve_price_zone_expiry(now, row["zone_type"], row["timeframe"], expiry_input)
            )
            before = zone_row_to_chart(row)
            override_id = str(uuid.uuid4())
            end_time = expires_at if request.status == "active" else requested_end_time
            if request.status == "disabled":
                end_time = requested_end_time or latest_candle_time(conn, row["symbol"], row["timeframe"]) or now
            try:
                start_dt = datetime.fromisoformat(start_time)
                end_dt = datetime.fromisoformat(end_time) if end_time else None
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="visual_start and visual_end must be ISO datetimes") from exc
            if end_dt is not None and start_dt >= end_dt:
                raise HTTPException(status_code=422, detail="visual_start must be before visual_end")
            valid_until = end_time if request.status == "disabled" else expires_at
            metadata = current_metadata
            if request.trade_modes is not None:
                metadata["trade_modes"] = sorted(set(request.trade_modes))
            metadata.update(
                {
                    "human_adjusted": True,
                    "last_human_override_id": override_id,
                    "last_human_override_at": now,
                    "last_human_override_reason": request.reason,
                }
            )
            after_patch = {
                "price_low": request.price_low,
                "price_high": request.price_high,
                "start_time": start_time,
                "end_time": end_time,
                "effective_weight": request.weight,
                "effective_confidence": confidence,
                "status": request.status,
                "source": "mixed" if row["source"] == "bot" else "human",
                "valid_until": valid_until,
            }
            conn.execute(
                """
                INSERT INTO overrides (
                    id, target_entity_type, target_entity_id, override_type, patch_json,
                    reason, created_by, created_at, expires_at, status
                )
                VALUES (?, 'price_zone', ?, 'geometry_weight_status', ?, ?, 'human', ?, ?, 'active')
                """,
                (
                    override_id,
                    zone_id,
                    json.dumps(
                        {
                            "before": before,
                            "after": after_patch,
                        },
                        sort_keys=True,
                    ),
                    request.reason,
                    now,
                    expires_at,
                ),
            )
            conn.execute(
                """
                UPDATE price_zones
                SET price_low = ?,
                    price_high = ?,
                    start_time = ?,
                    end_time = ?,
                    effective_weight = ?,
                    effective_confidence = ?,
                    status = ?,
                    source = ?,
                    valid_until = ?,
                    metadata_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    request.price_low,
                    request.price_high,
                    start_time,
                    end_time,
                    request.weight,
                    confidence,
                    request.status,
                    after_patch["source"],
                    valid_until,
                    json.dumps(metadata, sort_keys=True),
                    zone_id,
                ),
            )
            updated = conn.execute(
                """
                SELECT *
                FROM price_zones
                WHERE id = ?
                """,
                (zone_id,),
            ).fetchone()
            conn.commit()
            return zone_row_to_chart(updated)

    @app.post("/api/zones/{zone_id}/confirm")
    def confirm_zone(
        zone_id: str,
        request: ZoneActivationRequest = Body(...),
        username: str = Depends(require_auth),
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with connect(config.database) as conn:
            init_db(conn)
            row = conn.execute("SELECT * FROM price_zones WHERE id = ?", (zone_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Zone not found: {zone_id}")
            if row["detector"] != "human_manual_v1" or row["zone_type"] not in {"support", "resistance"}:
                raise HTTPException(status_code=422, detail="Only human-created Support/Resistance zones require confirmation")
            if row["status"] != "draft":
                raise HTTPException(status_code=409, detail=f"Zone is not draft: {row['status']}")

            review = request.model_dump()
            review["thesis_reasons"] = list(dict.fromkeys(review["thesis_reasons"]))
            if len(review["thesis_reasons"]) != len(request.thesis_reasons):
                raise HTTPException(status_code=422, detail="thesis_reasons must not contain duplicates")

            # The right edge drawn by the human is the planned SR lifetime.
            # Confirmation activates that exact plan instead of silently
            # replacing it with a new default duration.
            expires_at = row["end_time"]
            if not expires_at:
                raise HTTPException(status_code=409, detail="Draft zone requires a visual_end before activation")
            try:
                expiry_dt = datetime.fromisoformat(expires_at)
                now_dt = datetime.fromisoformat(now)
                if expiry_dt.tzinfo is None:
                    expiry_dt = expiry_dt.replace(tzinfo=now_dt.tzinfo)
                if expiry_dt <= now_dt:
                    raise HTTPException(
                        status_code=409,
                        detail="Draft zone visual_end is in the past; extend the zone before activation",
                    )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="Draft zone visual_end must be an ISO datetime") from exc
            before = zone_row_to_chart(row)
            override_id = str(uuid.uuid4())
            metadata = json_loads(row["metadata_json"], {})
            metadata.update(
                {
                    "activation_review": {
                        "version": 1,
                        "swing_type": "swing_low" if row["zone_type"] == "support" else "swing_high",
                        **review,
                        "confirmed_at": now,
                        "confirmed_by": username,
                    },
                    "activated_at": now,
                    "human_adjusted": True,
                    "last_human_override_id": override_id,
                    "last_human_override_at": now,
                    "last_human_override_reason": "Draft questionnaire confirmed",
                }
            )
            after = {
                "status": "active",
                "end_time": expires_at,
                "valid_until": expires_at,
                "activation_review": metadata["activation_review"],
            }
            conn.execute(
                """
                INSERT INTO overrides (
                    id, target_entity_type, target_entity_id, override_type, patch_json,
                    reason, created_by, created_at, expires_at, status
                )
                VALUES (?, 'price_zone', ?, 'activate_draft_zone', ?, ?, ?, ?, ?, 'active')
                """,
                (
                    override_id,
                    zone_id,
                    json.dumps({"before": before, "after": after}, sort_keys=True),
                    "Draft questionnaire confirmed",
                    username,
                    now,
                    expires_at,
                ),
            )
            conn.execute(
                """
                UPDATE price_zones
                SET status = 'active',
                    end_time = ?,
                    valid_until = ?,
                    metadata_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (expires_at, expires_at, json.dumps(metadata, sort_keys=True), zone_id),
            )
            updated = conn.execute("SELECT * FROM price_zones WHERE id = ?", (zone_id,)).fetchone()
            conn.commit()
            return zone_row_to_chart(updated)

    def prepare_zone_create(request: ZoneCreateRequest, conn: Any, now: str) -> dict[str, Any]:
        if request.price_low >= request.price_high:
            raise HTTPException(status_code=422, detail="price_low must be lower than price_high")
        if request.status not in {"active", "draft", "disabled"}:
            raise HTTPException(status_code=422, detail="status must be active, draft, or disabled")
        try:
            validate_zone_type(request.zone_type, request.direction)
        except ValueErrorForApi as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        requested_trade_modes = (
            request.trade_modes
            if request.trade_modes is not None
            else list(DEFAULT_TRADE_MODES_BY_ZONE_TYPE.get(request.zone_type, ()))
        )
        unknown_modes = sorted(set(requested_trade_modes) - TRADE_MODES)
        if unknown_modes:
            raise HTTPException(status_code=422, detail=f"Unknown trade mode(s): {', '.join(unknown_modes)}")
        trade_modes = list(dict.fromkeys(requested_trade_modes))

        symbol = request.symbol or config.symbol
        timeframe = request.timeframe.upper()
        if timeframe != config.bias.timeframe.upper():
            raise HTTPException(status_code=422, detail=f"Manual price zones must use {config.bias.timeframe} timeframe")
        effective_status = "draft" if request.zone_type in {"support", "resistance"} else request.status
        expiry_input = request.expires_at
        if effective_status == "active" and expiry_input is None:
            expiry_input = request.visual_end
        expires_at = (
            None
            if effective_status == "draft"
            else resolve_price_zone_expiry(now, request.zone_type, timeframe, expiry_input)
        )
        start_time = request.visual_start
        end_time = expires_at if effective_status == "active" else request.visual_end
        if effective_status == "draft" and end_time is None:
            end_time = resolve_price_zone_expiry(now, request.zone_type, timeframe, None)
        if effective_status == "disabled":
            end_time = end_time or latest_candle_time(conn, symbol, timeframe) or now
        try:
            start_dt = datetime.fromisoformat(start_time)
            end_dt = datetime.fromisoformat(end_time) if end_time else None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="visual_start and visual_end must be ISO datetimes") from exc
        if end_dt is not None and start_dt >= end_dt:
            raise HTTPException(status_code=422, detail="visual_start must be before visual_end")

        zone_id = f"human-zone-{uuid.uuid4()}"
        override_id = str(uuid.uuid4())
        metadata = {
            "human_created": True,
            "human_adjusted": True,
            "add_entity_kind": request.client_kind,
            "trade_modes": trade_modes,
            "last_human_override_id": override_id,
            "last_human_override_at": now,
            "last_human_override_reason": request.reason,
        }
        if effective_status == "draft":
            metadata["draft_created_at"] = now
            metadata["activation_review_version"] = 1
        valid_until = end_time if effective_status == "disabled" else expires_at
        return {
            "request": request,
            "zone_id": zone_id,
            "override_id": override_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "start_time": start_time,
            "end_time": end_time,
            "expires_at": expires_at,
            "valid_until": valid_until,
            "effective_status": effective_status,
            "trade_modes": trade_modes,
            "metadata": metadata,
            "now": now,
        }

    def insert_prepared_zone(conn: Any, prepared: dict[str, Any]) -> Any:
        request: ZoneCreateRequest = prepared["request"]
        conn.execute(
            """
            INSERT INTO price_zones (
                id, symbol, timeframe, detector, zone_type, direction, price_low, price_high,
                start_time, end_time, valid_from, valid_until, invalidated_at,
                invalidated_by_structure_point_id, detected_at, bot_confidence, bot_weight,
                effective_confidence, effective_weight, status, source, metadata_json
            )
            VALUES (?, ?, ?, 'human_manual_v1', ?, ?, ?, ?,
                    ?, ?, ?, ?, NULL,
                    NULL, ?, ?, ?,
                    ?, ?, ?, 'human', ?)
            """,
            (
                prepared["zone_id"],
                prepared["symbol"],
                prepared["timeframe"],
                request.zone_type,
                request.direction,
                request.price_low,
                request.price_high,
                prepared["start_time"],
                prepared["end_time"],
                prepared["start_time"],
                prepared["valid_until"],
                prepared["start_time"],
                request.confidence,
                request.weight,
                request.confidence,
                request.weight,
                prepared["effective_status"],
                json.dumps(prepared["metadata"], sort_keys=True),
            ),
        )
        conn.execute(
            """
            INSERT INTO overrides (
                id, target_entity_type, target_entity_id, override_type, patch_json,
                reason, created_by, created_at, expires_at, status
            )
            VALUES (?, 'price_zone', ?, 'create_manual_zone', ?, ?, 'human', ?, ?, 'active')
            """,
            (
                prepared["override_id"],
                prepared["zone_id"],
                json.dumps(
                    {
                        "after": {
                            "zone_type": request.zone_type,
                            "direction": request.direction,
                            "price_low": request.price_low,
                            "price_high": request.price_high,
                            "start_time": prepared["start_time"],
                            "end_time": prepared["end_time"],
                            "effective_weight": request.weight,
                            "effective_confidence": request.confidence,
                            "status": prepared["effective_status"],
                            "source": "human",
                            "valid_until": prepared["valid_until"],
                            "trade_modes": prepared["trade_modes"],
                        },
                    },
                    sort_keys=True,
                ),
                request.reason,
                prepared["now"],
                prepared["expires_at"],
            ),
        )
        return conn.execute("SELECT * FROM price_zones WHERE id = ?", (prepared["zone_id"],)).fetchone()

    def duplicate_conflicts(conn: Any, prepared_zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        planned: list[dict[str, Any]] = []
        for index, prepared in enumerate(prepared_zones):
            request: ZoneCreateRequest = prepared["request"]
            existing_rows = conn.execute(
                """
                SELECT id, symbol, timeframe, zone_type, direction, price_low, price_high,
                       status, source, invalidated_at, valid_until
                FROM price_zones
                WHERE symbol = ? AND timeframe = ? AND status IN ('active', 'draft', 'mitigated')
                ORDER BY detected_at DESC
                """,
                (prepared["symbol"], prepared["timeframe"]),
            ).fetchall()
            latest_m15 = latest_candle_time(conn, prepared["symbol"], "M15")
            candidates = [
                row
                for row in existing_rows
                if zone_is_duplicate_eligible(
                    row,
                    latest_m15,
                    config.strategy.zone_reaction_v2_internal_reject_watch_after_fvg_fill_bars,
                )
            ]
            candidate = {
                "id": f"import[{index}]",
                "symbol": prepared["symbol"],
                "timeframe": prepared["timeframe"],
                "zone_type": request.zone_type,
                "direction": request.direction,
                "price_low": request.price_low,
                "price_high": request.price_high,
            }
            for existing in [*candidates, *planned]:
                if not zones_are_duplicates(candidate, existing):
                    continue
                conflicts.append(
                    {
                        "index": index,
                        "existing_zone_id": existing["id"],
                        "existing_status": existing["status"],
                        "existing_price_low": float(existing["price_low"]),
                        "existing_price_high": float(existing["price_high"]),
                    }
                )
            planned.append({**candidate, "status": "planned", "source": "import"})
        return conflicts

    def insert_manual_ai_envelope(request: ManualAiPlanImportRequest, source: str) -> dict[str, Any]:
        validated = validate_manual_ai_envelope(request)
        now = utc_now_iso()
        raw_payload = request.model_dump(mode="json")
        context_snapshot = {
            "as_of": request.as_of,
            "analysis_timeframes": request.analysis_timeframes,
            "market_context": request.market_context,
        }
        with connect(config.database) as conn:
            init_db(conn)
            rows = []
            for candidate, risk_reward, expires_at in validated:
                existing = conn.execute(
                    """
                    SELECT id FROM manual_ai_plans
                    WHERE client_id = ? AND status NOT IN ('cancelled', 'rejected', 'expired')
                    LIMIT 1
                    """,
                    (candidate.client_id,),
                ).fetchone()
                if existing is not None:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Manual AI candidate client_id already exists: {candidate.client_id}",
                    )
                plan_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO manual_ai_plans (
                        id, client_id, symbol, side, status, execution_state,
                        entry_price, stop_loss, take_profit, risk_pct, risk_reward,
                        expires_at, partial_take_profit_json, cancel_conditions_json,
                        context_snapshot_json, raw_payload_json, source, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, 1.0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan_id,
                        candidate.client_id,
                        request.symbol.upper(),
                        candidate.side,
                        candidate.execution_state,
                        candidate.entry_price,
                        candidate.stop_loss,
                        candidate.take_profit,
                        risk_reward,
                        expires_at,
                        json.dumps(candidate.partial_take_profit.model_dump(mode="json"), sort_keys=True),
                        json.dumps([item.model_dump(mode="json") for item in candidate.cancel_conditions], sort_keys=True),
                        json.dumps(context_snapshot, sort_keys=True),
                        json.dumps(raw_payload, sort_keys=True),
                        source,
                        now,
                        now,
                    ),
                )
                rows.append(conn.execute("SELECT * FROM manual_ai_plans WHERE id = ?", (plan_id,)).fetchone())
            conn.commit()
        return {"created_count": len(rows), "plans": [manual_ai_row_to_api(row) for row in rows]}

    @app.post("/api/manual-ai/plans/import")
    def import_manual_ai_plans(
        request: ManualAiPlanImportRequest = Body(...),
        _: str = Depends(require_auth),
    ) -> dict[str, Any]:
        return insert_manual_ai_envelope(request, "ai_import")

    @app.post("/api/manual-ai/plans")
    def create_manual_ai_plans(
        request: ManualAiPlanImportRequest = Body(...),
        _: str = Depends(require_auth),
    ) -> dict[str, Any]:
        return insert_manual_ai_envelope(request, "human_manual")

    @app.get("/api/manual-ai/plans")
    def list_manual_ai_plans(
        status_filter: str | None = Query(default=None, alias="status"),
        _: str = Depends(require_auth),
    ) -> dict[str, Any]:
        with connect(config.database) as conn:
            init_db(conn)
            if status_filter:
                rows = conn.execute(
                    "SELECT * FROM manual_ai_plans WHERE status = ? ORDER BY created_at DESC",
                    (status_filter,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM manual_ai_plans ORDER BY created_at DESC").fetchall()
        return {"plans": [manual_ai_row_to_api(row) for row in rows]}

    @app.get("/api/manual-ai/plans/{plan_id}")
    def get_manual_ai_plan(plan_id: str, _: str = Depends(require_auth)) -> dict[str, Any]:
        with connect(config.database) as conn:
            init_db(conn)
            row = conn.execute("SELECT * FROM manual_ai_plans WHERE id = ?", (plan_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Manual AI plan not found: {plan_id}")
        return manual_ai_row_to_api(row)

    @app.post("/api/manual-ai/plans/{plan_id}/approve")
    def approve_manual_ai_plan(
        plan_id: str,
        request: ManualAiApproveRequest = Body(...),
        _: str = Depends(require_auth),
    ) -> dict[str, Any]:
        answers = request.questionnaire
        if not answers.accepts_one_percent_risk or not answers.confirms_lot_not_fixed:
            raise HTTPException(
                status_code=422,
                detail="Approval requires accepting account-profile risk and lot sizing from structural SL",
            )
        if answers.emotion_state != "calm":
            raise HTTPException(status_code=422, detail="Manual AI approval requires emotion_state=calm")
        if answers.competing_exposure:
            raise HTTPException(status_code=422, detail="Resolve competing XAUUSD exposure before approving Manual AI")
        requested_labels = [label.strip() for label in request.account_labels if label.strip()]
        if request.account_label and request.account_label.strip():
            requested_labels.append(request.account_label.strip())
        account_labels = list(dict.fromkeys(requested_labels))
        if not account_labels:
            raise HTTPException(status_code=422, detail="Select at least one worker account")
        now = utc_now_iso()
        with connect(config.database) as conn:
            init_db(conn)
            row = conn.execute("SELECT * FROM manual_ai_plans WHERE id = ?", (plan_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Manual AI plan not found: {plan_id}")
            if row["status"] != "draft":
                raise HTTPException(status_code=409, detail=f"Only draft plans can be approved; current status={row['status']}")
            if row["execution_state"] != "primary":
                raise HTTPException(status_code=422, detail="watch_only candidates cannot be approved")
            if require_timezone_aware_iso(row["expires_at"], "expires_at") <= datetime.now(UTC):
                conn.execute("UPDATE manual_ai_plans SET status = 'expired', updated_at = ? WHERE id = ?", (now, plan_id))
                conn.commit()
                raise HTTPException(status_code=409, detail="Manual AI plan has expired")
            placeholders = ",".join("?" for _ in account_labels)
            questionnaire_json = json.dumps(answers.model_dump(mode="json"), sort_keys=True)
            primary_account = account_labels[0]
            conn.execute(
                """
                UPDATE manual_ai_plans
                SET account_label = ?, questionnaire_json = ?, status = 'approved',
                    approved_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    primary_account,
                    questionnaire_json,
                    now,
                    now,
                    plan_id,
                ),
            )
            for account_label in account_labels[1:]:
                clone_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO manual_ai_plans (
                        id, client_id, account_label, symbol, side, status, execution_state,
                        entry_price, stop_loss, take_profit, risk_pct, risk_reward,
                        expires_at, partial_take_profit_json, cancel_conditions_json,
                        questionnaire_json, context_snapshot_json, raw_payload_json, source,
                        approved_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'approved', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clone_id,
                        row["client_id"],
                        account_label,
                        row["symbol"],
                        row["side"],
                        row["execution_state"],
                        row["entry_price"],
                        row["stop_loss"],
                        row["take_profit"],
                        row["risk_pct"],
                        row["risk_reward"],
                        row["expires_at"],
                        row["partial_take_profit_json"],
                        row["cancel_conditions_json"],
                        questionnaire_json,
                        row["context_snapshot_json"],
                        row["raw_payload_json"],
                        row["source"],
                        now,
                        row["created_at"],
                        now,
                    ),
                )
            conn.commit()
            updated_rows = conn.execute(
                "SELECT * FROM manual_ai_plans WHERE client_id = ? AND account_label IN (" + placeholders + ") ORDER BY account_label",
                (row["client_id"], *account_labels),
            ).fetchall()
        plans = [manual_ai_row_to_api(updated) for updated in updated_rows]
        if request.account_labels:
            return {"plans": plans}
        return plans[0]

    def transition_manual_ai_plan(plan_id: str, target_status: str) -> dict[str, Any]:
        now = utc_now_iso()
        with connect(config.database) as conn:
            init_db(conn)
            row = conn.execute("SELECT * FROM manual_ai_plans WHERE id = ?", (plan_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Manual AI plan not found: {plan_id}")
            if row["status"] in {"filled", "cancelled", "rejected", "expired"}:
                raise HTTPException(status_code=409, detail=f"Plan is already terminal: {row['status']}")
            group_rows = conn.execute(
                """
                SELECT id, status FROM manual_ai_plans
                WHERE client_id = ? AND symbol = ?
                  AND status NOT IN ('filled', 'cancelled', 'rejected', 'expired')
                """,
                (row["client_id"], row["symbol"]),
            ).fetchall()
            for group_row in group_rows:
                current_status = str(group_row["status"])
                effective_status = (
                    "cancel_requested"
                    if target_status in {"cancelled", "rejected"} and current_status in {"arming", "armed", "cancel_requested"}
                    else target_status
                )
                conn.execute(
                    "UPDATE manual_ai_plans SET status = ?, updated_at = ? WHERE id = ?",
                    (effective_status, now, group_row["id"]),
                )
            conn.commit()
            updated = conn.execute("SELECT * FROM manual_ai_plans WHERE id = ?", (plan_id,)).fetchone()
        return manual_ai_row_to_api(updated)

    @app.post("/api/manual-ai/plans/{plan_id}/reject")
    def reject_manual_ai_plan(plan_id: str, _: str = Depends(require_auth)) -> dict[str, Any]:
        return transition_manual_ai_plan(plan_id, "rejected")

    @app.post("/api/manual-ai/plans/{plan_id}/cancel")
    def cancel_manual_ai_plan(plan_id: str, _: str = Depends(require_auth)) -> dict[str, Any]:
        return transition_manual_ai_plan(plan_id, "cancelled")

    @app.get("/api/chart-drawings")
    def list_chart_drawings(
        symbol: str = Query(default=config.symbol),
        timeframe: str | None = Query(default=None),
        include_hidden: bool = Query(default=False),
        _: str = Depends(require_auth),
    ) -> dict[str, Any]:
        if timeframe is not None and timeframe not in {"M5", "M15", "H1"}:
            raise HTTPException(status_code=422, detail="timeframe must be M5, M15, or H1")
        with connect(config.database) as conn:
            init_db(conn)
            rows = conn.execute(
                "SELECT * FROM chart_drawings WHERE symbol = ? AND deleted_at IS NULL ORDER BY updated_at ASC",
                (symbol,),
            ).fetchall()
        drawings = [chart_drawing_row_to_api(row) for row in rows]
        if timeframe is not None:
            drawings = [item for item in drawings if timeframe in item["visible_timeframes"]]
        if not include_hidden:
            drawings = [item for item in drawings if not item["hidden"]]
        return {"drawings": drawings}

    @app.post("/api/chart-drawings", status_code=201)
    def create_chart_drawing(
        request: ChartDrawingCreateRequest = Body(...),
        username: str = Depends(require_auth),
    ) -> dict[str, Any]:
        validate_chart_drawing(request, request.drawing_type)
        now = utc_now_iso()
        drawing_id = str(uuid.uuid4())
        visible_timeframes = list(dict.fromkeys(request.visible_timeframes))
        with connect(config.database) as conn:
            init_db(conn)
            conn.execute(
                """
                INSERT INTO chart_drawings (
                    id, symbol, drawing_type, origin_timeframe, visible_timeframes_json,
                    anchors_json, properties_json, content, locked, hidden, revision,
                    created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    drawing_id,
                    request.symbol,
                    request.drawing_type,
                    request.origin_timeframe,
                    json.dumps(visible_timeframes),
                    json.dumps([anchor.model_dump() for anchor in request.anchors]),
                    json.dumps(request.properties),
                    (request.content or "").strip() or None,
                    int(request.locked),
                    int(request.hidden),
                    username,
                    now,
                    now,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM chart_drawings WHERE id = ?", (drawing_id,)).fetchone()
        return chart_drawing_row_to_api(row)

    @app.patch("/api/chart-drawings/{drawing_id}")
    def update_chart_drawing(
        drawing_id: str,
        request: ChartDrawingUpdateRequest = Body(...),
        _: str = Depends(require_auth),
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with connect(config.database) as conn:
            init_db(conn)
            row = conn.execute(
                "SELECT * FROM chart_drawings WHERE id = ? AND deleted_at IS NULL",
                (drawing_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Chart drawing not found: {drawing_id}")
            if int(row["revision"]) != request.revision:
                raise HTTPException(status_code=409, detail="Chart drawing was changed by another session")
            validate_chart_drawing(request, row["drawing_type"])
            visible = request.visible_timeframes if request.visible_timeframes is not None else json_loads(row["visible_timeframes_json"], [])
            anchors = [anchor.model_dump() for anchor in request.anchors] if request.anchors is not None else json_loads(row["anchors_json"], [])
            properties = request.properties if request.properties is not None else json_loads(row["properties_json"], {})
            content = request.content if "content" in request.model_fields_set else row["content"]
            locked = request.locked if request.locked is not None else bool(row["locked"])
            hidden = request.hidden if request.hidden is not None else bool(row["hidden"])
            conn.execute(
                """
                UPDATE chart_drawings
                SET visible_timeframes_json = ?, anchors_json = ?, properties_json = ?,
                    content = ?, locked = ?, hidden = ?, revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ?
                """,
                (
                    json.dumps(list(dict.fromkeys(visible))), json.dumps(anchors), json.dumps(properties),
                    content, int(locked), int(hidden), now, drawing_id, request.revision,
                ),
            )
            conn.commit()
            updated = conn.execute("SELECT * FROM chart_drawings WHERE id = ?", (drawing_id,)).fetchone()
        return chart_drawing_row_to_api(updated)

    @app.delete("/api/chart-drawings/{drawing_id}")
    def delete_chart_drawing(
        drawing_id: str,
        revision: int = Query(ge=1),
        _: str = Depends(require_auth),
    ) -> dict[str, Any]:
        now = utc_now_iso()
        with connect(config.database) as conn:
            init_db(conn)
            cursor = conn.execute(
                "UPDATE chart_drawings SET deleted_at = ?, updated_at = ?, revision = revision + 1 WHERE id = ? AND revision = ? AND deleted_at IS NULL",
                (now, now, drawing_id, revision),
            )
            conn.commit()
            if cursor.rowcount == 0:
                exists = conn.execute("SELECT revision FROM chart_drawings WHERE id = ? AND deleted_at IS NULL", (drawing_id,)).fetchone()
                if exists is None:
                    raise HTTPException(status_code=404, detail=f"Chart drawing not found: {drawing_id}")
                raise HTTPException(status_code=409, detail="Chart drawing was changed by another session")
        return {"id": drawing_id, "deleted": True}

    @app.post("/api/zones")
    def create_zone(request: ZoneCreateRequest = Body(...), _: str = Depends(require_auth)) -> dict[str, Any]:
        now = utc_now_iso()
        with connect(config.database) as conn:
            init_db(conn)
            prepared = prepare_zone_create(request, conn, now)
            row = insert_prepared_zone(conn, prepared)
            conn.commit()
            return zone_row_to_chart(row)

    @app.post("/api/zones/import")
    def import_zones(request: ZoneImportRequest = Body(...), _: str = Depends(require_auth)) -> dict[str, Any]:
        if not request.duplicate_audit.safe_to_import:
            raise HTTPException(status_code=422, detail="duplicate_audit.safe_to_import must be true")
        require_timezone_aware_iso(request.as_of, "as_of")
        for index, payload in enumerate(request.api_payloads):
            require_timezone_aware_iso(payload.visual_start, f"api_payloads[{index}].visual_start")
            if payload.visual_end is not None:
                require_timezone_aware_iso(payload.visual_end, f"api_payloads[{index}].visual_end")
            if payload.expires_at is not None:
                require_timezone_aware_iso(payload.expires_at, f"api_payloads[{index}].expires_at")

        now = utc_now_iso()
        with connect(config.database) as conn:
            init_db(conn)
            prepared_zones = [prepare_zone_create(payload, conn, now) for payload in request.api_payloads]
            conflicts = duplicate_conflicts(conn, prepared_zones)
            if conflicts:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Zone import contains duplicate zones; nothing was imported",
                        "conflicts": conflicts,
                    },
                )
            rows = [insert_prepared_zone(conn, prepared) for prepared in prepared_zones]
            conn.commit()
        zones = [zone_row_to_chart(row) for row in rows]
        return {
            "created_count": len(zones),
            "draft_count": sum(1 for zone in zones if zone["status"] == "draft"),
            "zones": zones,
        }

    @app.delete("/api/zones/{zone_id}")
    def delete_zone(zone_id: str, reason: str | None = None, _: str = Depends(require_auth)) -> dict[str, Any]:
        now = utc_now_iso()
        with connect(config.database) as conn:
            init_db(conn)
            row = conn.execute("SELECT * FROM price_zones WHERE id = ?", (zone_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Zone not found: {zone_id}")

            before = zone_row_to_chart(row)
            end_time = row["end_time"] or latest_candle_time(conn, row["symbol"], row["timeframe"]) or now
            override_id = str(uuid.uuid4())
            metadata = json_loads(row["metadata_json"], {})
            metadata.update(
                {
                    "human_deleted": True,
                    "human_adjusted": True,
                    "last_human_override_id": override_id,
                    "last_human_override_at": now,
                    "last_human_override_action": "delete_zone",
                    "last_human_override_reason": reason,
                }
            )
            source = "human" if row["source"] == "human" else "mixed"
            conn.execute(
                """
                INSERT INTO overrides (
                    id, target_entity_type, target_entity_id, override_type, patch_json,
                    reason, created_by, created_at, expires_at, status
                )
                VALUES (?, 'price_zone', ?, 'delete_manual_zone', ?, ?, 'human', ?, ?, 'active')
                """,
                (
                    override_id,
                    zone_id,
                    json.dumps(
                        {
                            "before": before,
                            "after": {
                                "status": "deleted",
                                "end_time": end_time,
                                "source": source,
                                "valid_until": end_time,
                            },
                        },
                        sort_keys=True,
                    ),
                    reason,
                    now,
                    end_time,
                ),
            )
            conn.execute(
                """
                UPDATE price_zones
                SET status = 'deleted',
                    end_time = ?,
                    valid_until = ?,
                    source = ?,
                    metadata_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (end_time, end_time, source, json.dumps(metadata, sort_keys=True), zone_id),
            )
            updated = conn.execute("SELECT * FROM price_zones WHERE id = ?", (zone_id,)).fetchone()
            conn.commit()
            return zone_row_to_chart(updated)

    @app.patch("/api/contexts/{timeframe}/{context_type}")
    def update_context(timeframe: str, context_type: str, request: ContextOverrideRequest = Body(...), _: str = Depends(require_auth)) -> dict[str, Any]:
        timeframe = timeframe.upper()
        context_type = context_type.lower()
        if context_type not in {"bias", "regime"}:
            raise HTTPException(status_code=422, detail="context_type must be bias or regime")

        normalized_value = request.value.lower() if isinstance(request.value, str) else None
        if not request.use_bot:
            if normalized_value is None:
                raise HTTPException(status_code=422, detail="value is required unless use_bot is true")
            try:
                validate_context_value(context_type, normalized_value)
            except ValueErrorForApi as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        now = utc_now_iso()
        expires_at = None if request.use_bot else resolve_override_expiry(now, request.no_expiry, request.expires_at)
        with connect(config.database) as conn:
            init_db(conn)
            row = conn.execute(
                """
                SELECT *
                FROM market_contexts
                WHERE symbol = ? AND timeframe = ? AND context_type = ? AND status = 'active'
                ORDER BY valid_from DESC, created_at DESC
                LIMIT 1
                """,
                (config.symbol, timeframe, context_type),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Context not found: {timeframe} {context_type}")

            before = context_row_to_chart(row)
            override_id = str(uuid.uuid4())
            metadata = json_loads(row["metadata_json"], {})
            secondary_value = request.secondary_value
            if context_type == "regime" and request.overlays is not None:
                overlays = [overlay.lower() for overlay in request.overlays]
                try:
                    validate_regime_overlays(overlays)
                except ValueErrorForApi as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                metadata["overlays"] = overlays
                secondary_value = ",".join(overlays) if overlays else None

            if request.use_bot:
                effective_value = row["bot_value"]
                effective_confidence = float(row["bot_confidence"])
                source = "bot"
                valid_until = None
                secondary_value = row["secondary_value"]
                metadata.update(
                    {
                        "human_adjusted": False,
                        "last_human_override_id": override_id,
                        "last_human_override_at": now,
                        "last_human_override_action": "use_bot",
                        "last_human_override_reason": request.reason,
                    }
                )
            else:
                effective_value = normalized_value
                effective_confidence = request.confidence if request.confidence is not None else 1.0
                source = "human"
                valid_until = expires_at
                metadata.update(
                    {
                        "human_adjusted": True,
                        "last_human_override_id": override_id,
                        "last_human_override_at": now,
                        "last_human_override_action": "override",
                        "last_human_override_reason": request.reason,
                    }
                )

            after_patch = {
                "effective_value": effective_value,
                "effective_confidence": effective_confidence,
                "secondary_value": secondary_value,
                "source": source,
                "valid_until": valid_until,
                "metadata": metadata,
            }
            conn.execute(
                """
                INSERT INTO overrides (
                    id, target_entity_type, target_entity_id, override_type, patch_json,
                    reason, created_by, created_at, expires_at, status
                )
                VALUES (?, 'market_context', ?, ?, ?, ?, 'human', ?, ?, 'active')
                """,
                (
                    override_id,
                    row["id"],
                    "use_bot" if request.use_bot else "context_value",
                    json.dumps(
                        {
                            "before": before,
                            "after": after_patch,
                            "no_expiry": request.no_expiry,
                        },
                        sort_keys=True,
                    ),
                    request.reason,
                    now,
                    expires_at,
                ),
            )
            conn.execute(
                """
                UPDATE market_contexts
                SET effective_value = ?,
                    effective_confidence = ?,
                    secondary_value = ?,
                    source = ?,
                    valid_until = ?,
                    metadata_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    effective_value,
                    effective_confidence,
                    secondary_value,
                    source,
                    valid_until,
                    json.dumps(metadata, sort_keys=True),
                    row["id"],
                ),
            )
            updated = conn.execute(
                """
                SELECT *
                FROM market_contexts
                WHERE id = ?
                """,
                (row["id"],),
            ).fetchone()
            conn.commit()
            return context_row_to_chart(updated)

    # ------------------------------------------------------------------
    # Static file serving — production VPS (frontend/dist built by Vite)
    # In development the Vite dev server (port 5173) proxies /api to here,
    # so this block is skipped when dist/ doesn't exist yet.
    # ------------------------------------------------------------------
    _frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
    if _frontend_dist.exists():
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles

        _assets_dir = _frontend_dist / "assets"
        if _assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def serve_spa(full_path: str) -> Any:
            # Serve real files (favicon.ico, vite.svg, …) if they exist
            candidate = _frontend_dist / full_path
            if candidate.is_file():
                return FileResponse(str(candidate))
            # Everything else → index.html (SPA client-side routing)
            return FileResponse(str(_frontend_dist / "index.html"))

    return app


def run_api_server(
    config_path: Path | str,
    host: str,
    port: int,
    reload: bool = False,
    env_path: Path | str = ".env",
) -> None:
    import uvicorn

    os.environ["SEMI_BOT_CONFIG_PATH"] = str(config_path)
    os.environ["SEMI_BOT_ENV_PATH"] = str(env_path)

    if reload:
        uvicorn.run(
            "semi_bot_trading.api:create_app",
            factory=True,
            host=host,
            port=port,
            reload=True,
        )
        return

    uvicorn.run(create_app(config_path, env_path), host=host, port=port)


def ensure_trade_exists(conn: Any, trade_order_id: str) -> None:
    row = conn.execute(
        """
        SELECT id
        FROM trade_orders
        WHERE id = ?
        """,
        (trade_order_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Trade order not found")


def decode_review_png(image_data: str) -> bytes:
    value = image_data.strip()
    if value.startswith("data:"):
        header, separator, payload = value.partition(",")
        if separator != "," or ";base64" not in header or not header.startswith("data:image/png"):
            raise HTTPException(status_code=422, detail="attachment must be a PNG data URL")
        value = payload
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="attachment image_data is not valid base64") from None
    if not decoded:
        raise HTTPException(status_code=422, detail="attachment image_data is empty")
    if len(decoded) > MAX_REVIEW_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="attachment exceeds 5MB")
    if not decoded.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=422, detail="attachment must be a PNG image")
    return decoded


def safe_segment(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in value.strip())
    return safe[:120] or "unknown"


def safe_review_attachment_path(file_path: str) -> Path:
    root = (Path.cwd() / "var" / "journal-screenshots").resolve()
    path = (Path.cwd() / file_path).resolve()
    if path != root and root not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid attachment path")
    return path


def attachment_row_to_api(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "trade_order_id": row["trade_order_id"],
        "kind": row["kind"],
        "caption": row["caption"] or "",
        "chart_symbol": row["chart_symbol"],
        "chart_timeframe": row["chart_timeframe"],
        "chart_start": row["chart_start"],
        "chart_end": row["chart_end"],
        "created_at": row["created_at"],
        "file_url": f"/api/trades/{row['trade_order_id']}/attachments/{row['id']}/file",
    }


def parse_week_start(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail="week_start must use YYYY-MM-DD format") from None
    if parsed.weekday() != 0:
        raise HTTPException(status_code=422, detail="week_start must be a Monday")
    return parsed


def weekly_journal_row_to_api(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "week_start": row["week_start"],
        "week_end": row["week_end"],
        "content": row["content"] or "",
        "content_format": row["content_format"] or "plain_text",
        "icon": row["icon"] or "📝",
        "discipline_score": int(row["discipline_score"]),
        "fomo_score": int(row["fomo_score"]),
        "revenge_score": int(row["revenge_score"]),
        "achieved_r": float(row["achieved_r"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def clean_optional_text(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:max_length]


def build_journal_patterns(rows: list[Any]) -> dict[str, Any]:
    buckets: dict[str, dict[str, dict[str, Any]]] = {
        "strategy_tags": {},
        "operator_action": {},
        "operator_state": {},
        "followed_plan": {},
        "zone_type": {},
        "reaction_v2": {},
        "stop_source": {},
    }

    for row in rows:
        pnl_r = float(row["pnl_r"])
        trade_metadata = json_loads(row["metadata_json"], {})
        review_metadata = json_loads(row["review_metadata_json"], {}) if row["review_metadata_json"] else {}
        if not isinstance(trade_metadata, dict):
            trade_metadata = {}
        if not isinstance(review_metadata, dict):
            review_metadata = {}
        strategy_review = review_metadata.get("strategy_review") if isinstance(review_metadata.get("strategy_review"), dict) else {}
        operator_review = review_metadata.get("operator_review") if isinstance(review_metadata.get("operator_review"), dict) else {}

        strategy_tags = strategy_review.get("strategy_tags") if isinstance(strategy_review.get("strategy_tags"), list) else []
        for tag in strategy_tags:
            add_pattern_bucket(buckets["strategy_tags"], str(tag), pnl_r)
        add_pattern_bucket(buckets["operator_action"], string_or_unknown(operator_review.get("operator_action")), pnl_r)
        add_pattern_bucket(buckets["operator_state"], string_or_unknown(operator_review.get("operator_state")), pnl_r)
        add_pattern_bucket(buckets["followed_plan"], string_or_unknown(operator_review.get("followed_plan")), pnl_r)
        add_pattern_bucket(buckets["zone_type"], string_or_unknown(metadata_lookup(trade_metadata, "zone_type")), pnl_r)
        add_pattern_bucket(buckets["reaction_v2"], string_or_unknown(metadata_lookup(trade_metadata, "zone_reaction_state")), pnl_r)
        add_pattern_bucket(buckets["stop_source"], string_or_unknown(metadata_lookup(trade_metadata, "stop_source")), pnl_r)

    return {
        "groups": {
            name: [finalize_pattern_bucket(key, value) for key, value in sorted(group.items())]
            for name, group in buckets.items()
        }
    }


def metadata_lookup(metadata: dict[str, Any], key: str) -> Any:
    if key in metadata:
        return metadata.get(key)
    candidate = metadata.get("candidate_metadata")
    if isinstance(candidate, dict) and key in candidate:
        return candidate.get(key)
    return None


def string_or_unknown(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip().lower()
    return "unknown"


def add_pattern_bucket(group: dict[str, dict[str, Any]], key: str, pnl_r: float) -> None:
    bucket = group.setdefault(key, {"trades": 0, "wins": 0, "losses": 0, "total_r": 0.0})
    bucket["trades"] += 1
    bucket["total_r"] += pnl_r
    if pnl_r > 0:
        bucket["wins"] += 1
    elif pnl_r < 0:
        bucket["losses"] += 1


def finalize_pattern_bucket(key: str, bucket: dict[str, Any]) -> dict[str, Any]:
    trades = int(bucket["trades"])
    total_r = float(bucket["total_r"])
    return {
        "key": key,
        "trades": trades,
        "wins": int(bucket["wins"]),
        "losses": int(bucket["losses"]),
        "total_r": round(total_r, 4),
        "avg_r": round(total_r / trades, 4) if trades else 0.0,
        "win_rate": round(int(bucket["wins"]) / trades, 4) if trades else 0.0,
    }


def latest_candle_time(conn: Any, symbol: str, timeframe: str) -> str | None:
    row = conn.execute(
        """
        SELECT open_time
        FROM candles
        WHERE symbol = ? AND timeframe = ?
        ORDER BY open_time DESC
        LIMIT 1
        """,
        (symbol, timeframe),
    ).fetchone()
    return None if row is None else row["open_time"]


def expire_context_overrides(conn: Any, now_iso: str) -> None:
    rows = conn.execute(
        """
        SELECT id, metadata_json
        FROM market_contexts
        WHERE status = 'active'
          AND source = 'human'
          AND valid_until IS NOT NULL
          AND valid_until <= ?
        """,
        (now_iso,),
    ).fetchall()
    for row in rows:
        metadata = json_loads(row["metadata_json"], {})
        metadata.update(
            {
                "human_adjusted": False,
                "human_override_expired_at": now_iso,
            }
        )
        conn.execute(
            """
            UPDATE market_contexts
            SET effective_value = bot_value,
                effective_confidence = bot_confidence,
                source = 'bot',
                valid_until = NULL,
                metadata_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (json.dumps(metadata, sort_keys=True), row["id"]),
        )
    if rows:
        conn.commit()


def context_row_to_chart(row: Any) -> dict[str, Any]:
    return {
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


def market_context_to_chart(context: MarketContext) -> dict[str, Any]:
    return {
        "bot_value": context.bot_value,
        "primary_value": context.primary_value,
        "secondary_value": context.secondary_value,
        "bot_confidence": context.bot_confidence,
        "effective_value": context.effective_value,
        "effective_confidence": context.effective_confidence,
        "source": context.source,
        "valid_from": context.valid_from,
        "valid_until": context.valid_until,
        "status": context.status,
        "metadata": context.metadata,
    }


def build_replay_contexts(conn: Any, symbol: str, as_of: str, config: Any) -> dict[str, dict[str, dict[str, Any]]]:
    contexts: dict[str, dict[str, dict[str, Any]]] = {}
    try:
        bias = detect_bias_context(
            conn,
            symbol,
            config.bias.timeframe,
            config.bias.recent_swings,
            config.bias.recent_breaks,
            end_time=as_of,
        )
        contexts.setdefault(config.bias.timeframe, {})["bias"] = market_context_to_chart(bias)
    except ValueError:
        pass

    try:
        regime = detect_regime_context(
            conn,
            symbol,
            config.regime.timeframe,
            config.regime.atr_period,
            config.regime.lookback,
            config.regime.atr_high_percentile,
            config.regime.atr_low_percentile,
            config.regime.expansion_atr_ratio,
            config.regime.contraction_atr_ratio,
            config.regime.trend_break_ratio,
            config.regime.trend_min_bos,
            config.regime.range_efficiency_max,
            end_time=as_of,
        )
        contexts.setdefault(config.regime.timeframe, {})["regime"] = market_context_to_chart(regime)
    except ValueError:
        pass
    return contexts


def zone_row_to_chart(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "type": row["zone_type"],
        "direction": row["direction"],
        "detector": row["detector"],
        "status": row["status"],
        "source": row["source"],
        "price_low": float(row["price_low"]),
        "price_high": float(row["price_high"]),
        "visual_start": row["start_time"],
        "visual_end": row["end_time"],
        "valid_from": row["valid_from"],
        "valid_until": row["valid_until"],
        "invalidated_at": row["invalidated_at"],
        "invalidated_by_structure_point_id": row["invalidated_by_structure_point_id"],
        "detected_at": row["detected_at"],
        "weight": float(row["effective_weight"]),
        "confidence": float(row["effective_confidence"]),
        "metadata": json_loads(row["metadata_json"], {}),
    }
