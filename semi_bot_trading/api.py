from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

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
from .db import connect, default_price_zone_expiry, init_db
from .replay_chart import build_realtime_replay_payload
from .runtime_env import load_runtime_env
from .strategy import PLAYBOOK_ZONE_TYPES


MAX_CHART_LIMIT = 15_000

_http_bearer = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ZoneOverrideRequest(BaseModel):
    price_low: float
    price_high: float
    visual_start: str | None = None
    visual_end: str | None = None
    weight: float = Field(ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: str = "active"
    expires_at: str | None = None
    reason: str | None = None
    trade_modes: list[str] | None = None


class ZoneCreateRequest(BaseModel):
    symbol: str | None = None
    timeframe: str = "H1"
    zone_type: str
    direction: str
    price_low: float
    price_high: float
    visual_start: str
    visual_end: str | None = None
    weight: float = Field(default=0.75, ge=0, le=1)
    confidence: float = Field(default=1.0, ge=0, le=1)
    status: str = "active"
    client_kind: str | None = None
    expires_at: str | None = None
    reason: str | None = None


class ContextOverrideRequest(BaseModel):
    value: str | None = None
    secondary_value: str | None = None
    overlays: list[str] | None = None
    confidence: float | None = Field(default=1.0, ge=0, le=1)
    no_expiry: bool = False
    expires_at: str | None = None
    reason: str | None = None
    use_bot: bool = False


class TradeReviewRequest(BaseModel):
    grade: str | None = None
    verdict: str = "unreviewed"
    mistake_tags: list[str] = Field(default_factory=list)
    should_trade_again: str = "unknown"
    comment: str = ""
    reviewer: str = "human"


def create_app(config_path: Path | str = DEFAULT_CONFIG_PATH):
    from fastapi import Body, FastAPI, HTTPException, Query
    from fastapi.middleware.cors import CORSMiddleware

    config = load_config(config_path)
    env = load_runtime_env()

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
            import jwt as _jwt

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
            import jwt as _jwt

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
        timeframe: str = Query(default="M15"),
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
        timeframe: str = Query(default="M15"),
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

    @app.get("/api/trades")
    def trades(
        symbol: str = Query(default=None),
        timeframe: str = Query(default="H1"),
        limit: int = Query(default=200, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        playbooks: str | None = None,
        status: str | None = None,
        side: str | None = None,
        outcome: str | None = Query(default=None),
        zone_type: str | None = Query(default=None),
        reaction: str | None = Query(default=None),
        trade_id: str | None = Query(default=None),
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
            allowed_reactions = {"reject", "fakeout", "waiting_bos", "retest_reject", "slow_reaction", "clean_breakout"}
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
        if backtest is not None:
            where.append("json_extract(trade_orders.metadata_json, '$.backtest') = ?")
            params.append(1 if backtest else 0)

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
                    should_trade_again, comment, reviewer, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trade_order_id) DO UPDATE SET
                    grade = excluded.grade,
                    verdict = excluded.verdict,
                    mistake_tags_json = excluded.mistake_tags_json,
                    should_trade_again = excluded.should_trade_again,
                    comment = excluded.comment,
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

    @app.patch("/api/zones/{zone_id}")
    def update_zone(zone_id: str, request: ZoneOverrideRequest = Body(...), _: str = Depends(require_auth)) -> dict[str, Any]:
        if request.price_low >= request.price_high:
            raise HTTPException(status_code=422, detail="price_low must be lower than price_high")
        if request.status not in {"active", "disabled"}:
            raise HTTPException(status_code=422, detail="status must be active or disabled")
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

            fields_set = request.model_fields_set if hasattr(request, "model_fields_set") else request.__fields_set__
            start_time = request.visual_start if "visual_start" in fields_set and request.visual_start else row["start_time"]
            requested_end_time = request.visual_end if "visual_end" in fields_set else row["end_time"]
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
            current_status = "disabled" if row["status"] == "disabled" else "active"
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

            expires_at = resolve_price_zone_expiry(now, row["zone_type"], row["timeframe"], expiry_input)
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

    @app.post("/api/zones")
    def create_zone(request: ZoneCreateRequest = Body(...), _: str = Depends(require_auth)) -> dict[str, Any]:
        if request.price_low >= request.price_high:
            raise HTTPException(status_code=422, detail="price_low must be lower than price_high")
        if request.status not in {"active", "disabled"}:
            raise HTTPException(status_code=422, detail="status must be active or disabled")
        try:
            validate_zone_type(request.zone_type, request.direction)
        except ValueErrorForApi as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        symbol = request.symbol or config.symbol
        timeframe = request.timeframe.upper()
        now = utc_now_iso()
        expiry_input = request.expires_at
        if request.status == "active" and expiry_input is None:
            expiry_input = request.visual_end
        expires_at = resolve_price_zone_expiry(now, request.zone_type, timeframe, expiry_input)
        start_time = request.visual_start
        end_time = expires_at if request.status == "active" else request.visual_end
        if request.status == "disabled":
            end_time = end_time or latest_candle_time_for_create(symbol, timeframe, config.database) or now
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
            "last_human_override_id": override_id,
            "last_human_override_at": now,
            "last_human_override_reason": request.reason,
        }
        valid_until = end_time if request.status == "disabled" else expires_at
        with connect(config.database) as conn:
            init_db(conn)
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
                    zone_id,
                    symbol,
                    timeframe,
                    request.zone_type,
                    request.direction,
                    request.price_low,
                    request.price_high,
                    start_time,
                    end_time,
                    start_time,
                    valid_until,
                    start_time,
                    request.confidence,
                    request.weight,
                    request.confidence,
                    request.weight,
                    request.status,
                    json.dumps(metadata, sort_keys=True),
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
                    override_id,
                    zone_id,
                    json.dumps(
                        {
                            "after": {
                                "zone_type": request.zone_type,
                                "direction": request.direction,
                                "price_low": request.price_low,
                                "price_high": request.price_high,
                                "start_time": start_time,
                                "end_time": end_time,
                                "effective_weight": request.weight,
                                "effective_confidence": request.confidence,
                                "status": request.status,
                                "source": "human",
                                "valid_until": valid_until,
                            },
                        },
                        sort_keys=True,
                    ),
                    request.reason,
                    now,
                    expires_at,
                ),
            )
            row = conn.execute("SELECT * FROM price_zones WHERE id = ?", (zone_id,)).fetchone()
            conn.commit()
            return zone_row_to_chart(row)

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


def run_api_server(config_path: Path | str, host: str, port: int, reload: bool = False) -> None:
    import uvicorn

    if reload:
        uvicorn.run(
            "semi_bot_trading.api:create_app",
            factory=True,
            host=host,
            port=port,
            reload=True,
        )
        return

    uvicorn.run(create_app(config_path), host=host, port=port)


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def parse_playbooks(value: str | None) -> set[str] | None:
    if value is None:
        return None
    playbooks = {item.strip() for item in value.split(",") if item.strip()}
    if playbooks == {"__none__"}:
        return set()
    unknown = sorted(playbooks - set(PLAYBOOK_ZONE_TYPES))
    if unknown:
        known = ", ".join(sorted(PLAYBOOK_ZONE_TYPES))
        raise HTTPException(status_code=422, detail=f"Unknown playbook(s): {', '.join(unknown)}. Known playbooks: {known}")
    return playbooks


def resolve_override_expiry(now_iso: str, no_expiry: bool, expires_at: str | None) -> str | None:
    if no_expiry:
        return None
    if expires_at:
        return expires_at
    now = datetime.fromisoformat(now_iso)
    return (now + timedelta(hours=4)).replace(microsecond=0).isoformat()


def resolve_price_zone_expiry(now_iso: str, zone_type: str, timeframe: str, expires_at: str | None) -> str:
    if expires_at:
        return expires_at
    now = datetime.fromisoformat(now_iso)
    return (now + default_price_zone_expiry(zone_type, timeframe)).replace(microsecond=0).isoformat()


def json_loads(value: str | None, default: Any) -> Any:
    if value in (None, ""):
        return default
    return json.loads(value)


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


def normalize_trade_review_request(request: TradeReviewRequest) -> dict[str, Any]:
    grade = request.grade.strip().upper() if isinstance(request.grade, str) and request.grade.strip() else None
    if grade is not None and grade not in {"A", "B", "C", "D"}:
        raise HTTPException(status_code=422, detail="grade must be A, B, C, D, or empty")

    verdict = request.verdict.strip().lower()
    allowed_verdicts = {"unreviewed", "good_trade", "bad_trade", "should_skip", "missed_context"}
    if verdict not in allowed_verdicts:
        raise HTTPException(status_code=422, detail=f"verdict must be one of: {', '.join(sorted(allowed_verdicts))}")

    should_trade_again = request.should_trade_again.strip().lower()
    allowed_should_trade_again = {"unknown", "yes", "no", "conditional"}
    if should_trade_again not in allowed_should_trade_again:
        raise HTTPException(
            status_code=422,
            detail=f"should_trade_again must be one of: {', '.join(sorted(allowed_should_trade_again))}",
        )

    tags = []
    seen_tags = set()
    for tag in request.mistake_tags:
        normalized_tag = tag.strip().lower()
        if not normalized_tag or normalized_tag in seen_tags:
            continue
        seen_tags.add(normalized_tag)
        tags.append(normalized_tag)
    if len(tags) > 20:
        raise HTTPException(status_code=422, detail="mistake_tags supports at most 20 tags")

    reviewer = request.reviewer.strip() or "human"
    if len(reviewer) > 80:
        raise HTTPException(status_code=422, detail="reviewer is too long")
    comment = request.comment.strip()
    if len(comment) > 5000:
        raise HTTPException(status_code=422, detail="comment is too long")

    return {
        "grade": grade,
        "verdict": verdict,
        "mistake_tags": tags,
        "should_trade_again": should_trade_again,
        "comment": comment,
        "reviewer": reviewer,
    }


def trade_review_row_to_api(row: Any | None, trade_order_id: str) -> dict[str, Any]:
    if row is None:
        return {
            "id": None,
            "trade_order_id": trade_order_id,
            "grade": None,
            "verdict": "unreviewed",
            "mistake_tags": [],
            "should_trade_again": "unknown",
            "comment": "",
            "reviewer": "human",
            "created_at": None,
            "updated_at": None,
        }
    return {
        "id": row["id"],
        "trade_order_id": row["trade_order_id"],
        "grade": row["grade"],
        "verdict": row["verdict"],
        "mistake_tags": json_loads(row["mistake_tags_json"], []),
        "should_trade_again": row["should_trade_again"],
        "comment": row["comment"] or "",
        "reviewer": row["reviewer"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
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


def validate_context_value(context_type: str, value: str) -> None:
    allowed = {
        "bias": {"bullish", "bearish", "neutral"},
        "regime": {"trending", "ranging", "news", "risk_off"},
    }[context_type]
    if value not in allowed:
        raise ValueErrorForApi(f"{context_type} value must be one of: {', '.join(sorted(allowed))}")


def validate_regime_overlays(overlays: list[str]) -> None:
    allowed = {"expansion", "contraction", "high_volatility", "low_volatility"}
    invalid = sorted(set(overlays) - allowed)
    if invalid:
        raise ValueErrorForApi(f"Invalid regime overlays: {', '.join(invalid)}")


def validate_zone_type(zone_type: str, direction: str) -> None:
    allowed = {
        "support": {"bullish"},
        "resistance": {"bearish"},
        "order_block": {"bullish", "bearish"},
        "fvg": {"bullish", "bearish"},
        "consolidation": {"neutral"},
        "liquidity_pool": {"bullish", "bearish", "neutral"},
    }
    if zone_type not in allowed:
        raise ValueErrorForApi(f"zone_type must be one of: {', '.join(sorted(allowed))}")
    if direction not in allowed[zone_type]:
        valid_directions = ", ".join(sorted(allowed[zone_type]))
        raise ValueErrorForApi(f"direction for {zone_type} must be one of: {valid_directions}")


def latest_candle_time_for_create(symbol: str, timeframe: str, database: Path | str) -> str | None:
    with connect(database) as conn:
        init_db(conn)
        return latest_candle_time(conn, symbol, timeframe)


class ValueErrorForApi(ValueError):
    pass


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
