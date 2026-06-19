from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from sqlite3 import Connection
from typing import Any

from .alerts import queue_alert, send_pending_telegram_alerts
from .candles import upsert_candles, upsert_live_candle
from .chart import build_chart_payload
from .config import AppConfig
from .context import detect_and_store_bias, detect_and_store_macro_trend, detect_and_store_regime
from .db import connect, init_db
from .mt5_client import MT5BrokerClient, MT5Credentials, MT5OrderRequest
from .price_action import detect_and_store_price_action_patterns
from .risk_manager import build_risk_manager
from .runtime_env import RuntimeEnv
from .smc_zones import detect_and_store_smc_zones
from .structure import SWING_DETECTOR, detect_and_store_break_structure, detect_and_store_swing_structure
from .zones import apply_and_store_zone_lifecycle, detect_and_store_support_resistance_zones

logger = logging.getLogger(__name__)


@dataclass
class LiveWorkerState:
    broker_symbol: str | None = None
    last_closed_m15: str | None = None
    loop_count: int = 0


def run_live_worker(config: AppConfig, env: RuntimeEnv, *, once: bool = False) -> None:
    if env.mt5_login is None or not env.mt5_password or not env.mt5_server:
        raise RuntimeError("MT5_LOGIN, MT5_PASSWORD, and MT5_SERVER are required")
    credentials = MT5Credentials(env.mt5_login, env.mt5_password, env.mt5_server, env.mt5_path)
    client = MT5BrokerClient(credentials)

    # MT5 may not be running yet (e.g. service starts before MT5 on reboot).
    # Retry the connection with backoff instead of crashing immediately.
    _connect_with_retry(client, once=once)

    # Initialise DB schema once at startup, not on every poll iteration.
    with closing(connect(config.database)) as conn:
        init_db(conn)
    state = LiveWorkerState(broker_symbol=client.resolve_symbol(env.mt5_symbol, config.symbol))
    try:
        while True:
            try:
                run_live_iteration(config, env, client, state)
            except Exception:
                if once:
                    raise  # propagate in one-shot / test mode so callers see the error
                logger.exception("Live iteration error — retrying next cycle")
            if once:
                return
            time.sleep(env.poll_seconds)
    finally:
        client.shutdown()


def _connect_with_retry(client: MT5BrokerClient, *, once: bool = False) -> None:
    """Try to connect to MT5, retrying every 30 s for up to 10 minutes.

    MT5 is often not yet running when the Windows service starts on boot.
    Retrying avoids a crash-restart loop logged in BotWorker.err.log.
    In once/test mode the first failure raises immediately (no waiting).
    """
    max_attempts = 20   # 20 × 30 s = 10 minutes
    delay_seconds = 30
    for attempt in range(1, max_attempts + 1):
        try:
            client.connect()
            return  # success
        except Exception as exc:
            if once:
                raise
            if attempt >= max_attempts:
                logger.error("MT5 connect failed after %d attempts — giving up: %s", max_attempts, exc)
                raise
            logger.warning(
                "MT5 connect failed (attempt %d/%d): %s — retrying in %ds",
                attempt, max_attempts, exc, delay_seconds,
            )
            time.sleep(delay_seconds)


def snapshot_account(conn: Connection, env: RuntimeEnv, client: MT5BrokerClient) -> None:
    """Upsert the latest MT5 account metrics into account_snapshots (one row per label)."""
    try:
        info = client.get_account_info()
    except Exception:
        logger.warning("Could not fetch MT5 account info for snapshot", exc_info=True)
        return
    now = utc_now_iso()
    conn.execute(
        """
        INSERT INTO account_snapshots
            (account_label, broker, login, server, balance, equity, margin, free_margin, profit, currency, snapshot_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_label) DO UPDATE SET
            broker      = excluded.broker,
            login       = excluded.login,
            server      = excluded.server,
            balance     = excluded.balance,
            equity      = excluded.equity,
            margin      = excluded.margin,
            free_margin = excluded.free_margin,
            profit      = excluded.profit,
            currency    = excluded.currency,
            snapshot_at = excluded.snapshot_at
        """,
        (
            env.account_label,
            env.mt5_server,
            env.mt5_login,
            env.mt5_server,
            info["balance"],
            info["equity"],
            info["margin"],
            info["free_margin"],
            info["profit"],
            info["currency"],
            now,
        ),
    )
    conn.commit()


def run_live_iteration(config: AppConfig, env: RuntimeEnv, client: MT5BrokerClient, state: LiveWorkerState) -> None:
    state.loop_count += 1
    broker_symbol: str = state.broker_symbol or ""
    with closing(connect(config.database)) as conn:
        # init_db is called once at startup in run_live_worker; skip here.
        snapshot_account(conn, env, client)
        sync_mt5_candles(conn, config, client, broker_symbol)
        if broker_symbol:
            sync_closed_positions(conn, config, env, client, broker_symbol)
        latest_m15 = latest_closed_candle_time(conn, config.symbol, config.strategy.timeframe)
        has_new_closed_m15 = latest_m15 is not None and latest_m15 != state.last_closed_m15
        if has_new_closed_m15:
            before_zone_ids = current_zone_ids(conn, config.symbol)
            run_live_detectors(conn, config, config.symbol)
            after_zones = new_zone_rows(conn, config.symbol, before_zone_ids)
            queue_zone_alerts(conn, config, env, after_zones)
            state.last_closed_m15 = latest_m15
        if latest_m15 is not None:
            # Closed M15 updates drive detectors, but setup evaluation must run
            # every poll. Otherwise a worker that has already processed the
            # latest closed candle can miss a setup that becomes eligible after
            # a human zone edit or a delayed DB sync; restarting the worker would
            # reset last_closed_m15 and execute the same setup, which is unsafe.
            payload = build_chart_payload(
                conn,
                symbol=config.symbol,
                timeframe=config.strategy.timeframe,
                limit=500,
                active_zones_only=True,
                structure_timeframe=config.bias.timeframe,
                strategy_config=config.strategy,
                macro_trend_config=config.macro_trend,
            )
            queue_setup_alerts(conn, config, env, payload["layers"].get("setup_candidates", []))
            maybe_execute_candidates(conn, config, env, client, payload["layers"].get("setup_candidates", []), broker_symbol)
    with closing(connect(config.database)) as conn:
        send_pending_telegram_alerts(conn, token=env.telegram_token, chat_id=env.telegram_chat_id, environment=env.environment)


def sync_mt5_candles(conn: Connection, config: AppConfig, client: MT5BrokerClient, broker_symbol: str) -> None:
    # broker_symbol is resolved once at startup and passed in — no redundant MT5 call.
    for timeframe, count in ((config.bias.timeframe, 800), (config.strategy.timeframe, 1200)):
        candles = client.copy_rates(broker_symbol, config.symbol, timeframe, count)
        # The last candle from MT5 is the still-forming live candle; exclude it from
        # the closed-candle store.  When MT5 returns ≤1 candle (unexpected) treat
        # everything as live so we never write an open candle into the closed table.
        closed_candles = candles[:-1] if len(candles) > 1 else []
        upsert_candles(conn, closed_candles)
        live_candle = candles[-1] if candles else None
        upsert_live_candle(conn, live_candle)


def _load_swing_ids(conn: Connection, symbol: str, timeframe: str) -> set[str]:
    rows = conn.execute(
        "SELECT id FROM structure_points WHERE symbol = ? AND timeframe = ? AND detector = ?",
        (symbol, timeframe, SWING_DETECTOR),
    ).fetchall()
    return {row["id"] for row in rows}


def _queue_new_swing_alerts(
    conn: Connection, config: AppConfig, symbol: str, timeframe: str, new_ids: set[str]
) -> None:
    placeholders = ",".join("?" * len(new_ids))
    rows = conn.execute(
        f"""
        SELECT id, point_type, price, event_time, metadata_json
        FROM structure_points
        WHERE symbol = ? AND timeframe = ? AND detector = ?
        AND id IN ({placeholders})
        """,
        (symbol, timeframe, SWING_DETECTOR, *new_ids),
    ).fetchall()
    for row in rows:
        meta = json.loads(row["metadata_json"])
        swing_type = str(meta.get("swing_type", ""))   # "high" | "low"
        point_type = str(row["point_type"])             # HH | LH | HL | LL | swing_high | swing_low
        price = round(float(row["price"]), 5)
        event_time = str(row["event_time"])
        queue_alert(
            conn,
            symbol=symbol,
            timeframe=timeframe,
            event_type="new_swing",
            severity="info",
            entity_ids=[str(row["id"])],
            payload={
                "swing": {
                    "id": str(row["id"]),
                    "point_type": point_type,
                    "swing_type": swing_type,
                    "price": price,
                    "event_time": event_time,
                },
            },
            dedupe_key=f"new-swing:{row['id']}",
        )


def run_live_detectors(conn: Connection, config: AppConfig, symbol: str) -> None:
    for timeframe in (config.bias.timeframe, config.strategy.timeframe):
        swing_config = config.swing_for(timeframe)
        before_ids = _load_swing_ids(conn, symbol, timeframe)
        detect_and_store_swing_structure(conn, symbol, timeframe, swing_config.window, swing_config.tolerance)
        after_ids = _load_swing_ids(conn, symbol, timeframe)
        new_ids = after_ids - before_ids
        if new_ids:
            _queue_new_swing_alerts(conn, config, symbol, timeframe, new_ids)
        detect_and_store_break_structure(conn, symbol, timeframe, config.breaks.close_break_buffer)

    detect_and_store_bias(
        conn,
        symbol=symbol,
        timeframe=config.bias.timeframe,
        recent_swings=config.bias.recent_swings,
        recent_breaks=config.bias.recent_breaks,
    )
    detect_and_store_macro_trend(
        conn,
        symbol=symbol,
        timeframe=config.macro_trend.timeframe,
        lookback_candles=config.macro_trend.lookback_candles,
        flat_threshold_atr=config.macro_trend.flat_threshold_atr,
        atr_period=config.macro_trend.atr_period,
    )
    detect_and_store_regime(
        conn,
        symbol=symbol,
        timeframe=config.regime.timeframe,
        atr_period=config.regime.atr_period,
        lookback=config.regime.lookback,
        atr_high_percentile=config.regime.atr_high_percentile,
        atr_low_percentile=config.regime.atr_low_percentile,
        expansion_atr_ratio=config.regime.expansion_atr_ratio,
        contraction_atr_ratio=config.regime.contraction_atr_ratio,
        trend_break_ratio=config.regime.trend_break_ratio,
        trend_min_bos=config.regime.trend_min_bos,
        range_efficiency_max=config.regime.range_efficiency_max,
    )
    for timeframe in (config.bias.timeframe, config.strategy.timeframe):
        detect_and_store_support_resistance_zones(
            conn,
            symbol=symbol,
            timeframe=timeframe,
            tolerance_pct=config.support_resistance.tolerance_pct,
            min_zone_width=config.support_resistance.min_zone_width,
            min_touches=config.support_resistance.min_touches,
            lookback_swings=config.support_resistance.lookback_swings,
            max_zones=config.support_resistance.max_zones,
            atr_width_multiplier=config.support_resistance.atr_width_multiplier,
            close_break_buffer=config.zone_lifecycle.close_break_buffer,
            close_break_buffer_atr_multiplier=config.zone_lifecycle.close_break_buffer_atr_multiplier,
            recent_touch_lookback_candles=config.zone_lifecycle.recent_touch_lookback_candles,
            age_decay_per_100_candles=config.zone_lifecycle.age_decay_per_100_candles,
            freshness_bonus=config.zone_lifecycle.freshness_bonus,
            invalidation_weight_multiplier=config.zone_lifecycle.invalidation_weight_multiplier,
            reaction_window_candles=config.zone_reaction.reaction_window_candles,
            min_reaction_atr=config.zone_reaction.min_reaction_atr,
            strong_reaction_atr=config.zone_reaction.strong_reaction_atr,
            recent_reaction_count=config.zone_reaction.recent_reaction_count,
            max_healthy_touches=config.zone_decay.max_healthy_touches,
            weak_touch_penalty=config.zone_decay.weak_touch_penalty,
            too_many_touches_penalty=config.zone_decay.too_many_touches_penalty,
            linger_penalty=config.zone_decay.linger_penalty,
            false_break_refine_enabled=config.zone_lifecycle.false_break_refine_enabled,
            false_break_refine_max_width_atr_multiplier=config.zone_lifecycle.false_break_refine_max_width_atr_multiplier,
            false_break_parent_weight_multiplier=config.zone_lifecycle.false_break_parent_weight_multiplier,
        )
        apply_and_store_zone_lifecycle(
            conn,
            symbol=symbol,
            timeframe=timeframe,
            close_break_buffer=config.zone_lifecycle.close_break_buffer,
            close_break_buffer_atr_multiplier=config.zone_lifecycle.close_break_buffer_atr_multiplier,
            recent_touch_lookback_candles=config.zone_lifecycle.recent_touch_lookback_candles,
            age_decay_per_100_candles=config.zone_lifecycle.age_decay_per_100_candles,
            freshness_bonus=config.zone_lifecycle.freshness_bonus,
            invalidation_weight_multiplier=config.zone_lifecycle.invalidation_weight_multiplier,
            reaction_window_candles=config.zone_reaction.reaction_window_candles,
            min_reaction_atr=config.zone_reaction.min_reaction_atr,
            strong_reaction_atr=config.zone_reaction.strong_reaction_atr,
            recent_reaction_count=config.zone_reaction.recent_reaction_count,
            max_healthy_touches=config.zone_decay.max_healthy_touches,
            weak_touch_penalty=config.zone_decay.weak_touch_penalty,
            too_many_touches_penalty=config.zone_decay.too_many_touches_penalty,
            linger_penalty=config.zone_decay.linger_penalty,
            false_break_refine_enabled=config.zone_lifecycle.false_break_refine_enabled,
            false_break_refine_max_width_atr_multiplier=config.zone_lifecycle.false_break_refine_max_width_atr_multiplier,
            false_break_parent_weight_multiplier=config.zone_lifecycle.false_break_parent_weight_multiplier,
        )
        detect_and_store_smc_zones(
            conn,
            symbol=symbol,
            timeframe=timeframe,
            max_candles=config.smc_zones.max_candles,
            lookback_swings=config.smc_zones.lookback_swings,
            fvg_middle_candle_atr_multiplier=config.smc_zones.fvg_middle_candle_atr_multiplier,
            fvg_gap_atr_ratio=config.smc_zones.fvg_gap_atr_ratio,
            fvg_min_width_atr_ratio=config.smc_zones.fvg_min_width_atr_ratio,
            fvg_max_width_atr_ratio=config.smc_zones.fvg_max_width_atr_ratio,
            fvg_third_candle_follow_through_required=config.smc_zones.fvg_third_candle_follow_through_required,
            fvg_third_candle_min_body_ratio=config.smc_zones.fvg_third_candle_min_body_ratio,
            fvg_max_active_days=config.smc_zones.fvg_max_active_days_for(timeframe),
            fvg_decay_start_days=config.smc_zones.fvg_decay_start_days_for(timeframe),
            ob_displacement_atr_multiplier=config.smc_zones.ob_displacement_atr_multiplier,
            ob_min_body_ratio=config.smc_zones.ob_min_body_ratio,
            ob_min_width_atr_ratio=config.smc_zones.ob_min_width_atr_ratio,
            ob_max_width_atr_ratio=config.smc_zones.ob_max_width_atr_ratio,
            ob_require_structure_break=config.smc_zones.ob_require_structure_break,
            ob_merge_overlap_ratio=config.smc_zones.ob_merge_overlap_ratio,
            ob_max_active_days=config.smc_zones.ob_max_active_days_for(timeframe),
            ob_decay_start_days=config.smc_zones.ob_decay_start_days_for(timeframe),
            max_fvg_zones=config.smc_zones.max_fvg_zones,
            max_order_block_zones=config.smc_zones.max_order_block_zones,
            max_liquidity_zones=config.smc_zones.max_liquidity_zones,
            max_consolidation_zones=config.smc_zones.max_consolidation_zones,
        )
    detect_and_store_price_action_patterns(
        conn,
        symbol=symbol,
        timeframe=config.strategy.timeframe,
        atr_period=config.price_action.atr_period,
        displacement_atr_multiplier=config.price_action.displacement_atr_multiplier,
        displacement_body_ratio=config.price_action.displacement_body_ratio,
        pinbar_wick_body_ratio=config.price_action.pinbar_wick_body_ratio,
        pinbar_min_wick_ratio=config.price_action.pinbar_min_wick_ratio,
        engulfing_min_body_ratio=config.price_action.engulfing_min_body_ratio,
        marubozu_min_body_ratio=config.price_action.marubozu_min_body_ratio,
        star_large_body_ratio=config.price_action.star_large_body_ratio,
        star_small_body_ratio=config.price_action.star_small_body_ratio,
    )


def queue_zone_alerts(conn: Connection, config: AppConfig, env: RuntimeEnv, zones: list[Any]) -> None:
    for zone in zones:
        weight = float(zone["effective_weight"])
        if zone["zone_type"] not in {"support", "resistance", "fvg", "order_block"} and weight < 0.7:
            continue
        payload = {
            "title": f"New {zone['zone_type']} zone detected",
            "zone": {
                "id": zone["id"],
                "type": zone["zone_type"],
                "price_low": round(float(zone["price_low"]), 5),
                "price_high": round(float(zone["price_high"]), 5),
                "weight": round(weight, 4),
            },
            "reason": [f"Detector {zone['detector']} created a {zone['status']} zone."],
            "action": "Observe reaction on chart.",
            "chart_url": env.chart_url_base,
        }
        queue_alert(
            conn,
            symbol=config.symbol,
            timeframe=zone["timeframe"],
            event_type="new_zone",
            severity="watch" if weight < 0.8 else "important",
            entity_ids=[zone["id"]],
            payload=payload,
            dedupe_key=f"new-zone:{zone['id']}",
        )


def queue_setup_alerts(conn: Connection, config: AppConfig, env: RuntimeEnv, candidates: list[dict[str, Any]]) -> None:
    for candidate in candidates:
        if candidate.get("status") not in {"eligible", "waiting_confirmation"}:
            continue
        payload = {
            "title": "Setup candidate",
            "setup": {
                "id": candidate.get("id"),
                "playbook": candidate.get("playbook"),
                "direction": candidate.get("direction"),
                "status": candidate.get("status"),
                "entry": candidate.get("entry"),
                "stop_loss": candidate.get("stop_loss"),
                "take_profit": candidate.get("take_profit"),
            },
            "reason": list(candidate.get("reason") or [])[:5],
            "action": "Auto execution is enabled." if env.execution_enabled else "Execution is disabled; observe manually.",
            "chart_url": env.chart_url_base,
        }
        queue_alert(
            conn,
            symbol=config.symbol,
            timeframe=str(candidate.get("timeframe") or config.strategy.timeframe),
            event_type="setup_candidate",
            severity="important" if candidate.get("status") == "eligible" else "watch",
            entity_ids=[str(candidate.get("id"))],
            payload=payload,
            dedupe_key=f"setup:{candidate.get('id')}:{candidate.get('status')}",
        )


def maybe_execute_candidates(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    candidates: list[dict[str, Any]],
    broker_symbol: str,
) -> None:
    if not env.execution_enabled:
        return
    if client.positions_count(broker_symbol) >= env.max_open_positions_per_symbol:
        return
    if live_trade_count_today(conn, config.symbol) >= env.max_trades_per_day:
        return
    eligible = [candidate for candidate in candidates if candidate.get("status") == "eligible"]
    if not eligible:
        return
    candidate = sorted(eligible, key=lambda item: float(item.get("score") or 0.0), reverse=True)[0]
    if live_candidate_already_executed(conn, str(candidate["id"])):
        return
    # Risk check: compute lot size and verify daily loss limit
    risk_manager = build_risk_manager(client, env.account_profile, env.risk_per_trade_pct)
    assessment = risk_manager.assess_trade(
        conn=conn,
        symbol=config.symbol,
        entry=candidate.get("entry"),
        stop_loss=candidate.get("stop_loss"),
        broker_symbol=broker_symbol,
    )
    if not assessment.allowed:
        queue_alert(
            conn,
            symbol=config.symbol,
            timeframe=config.strategy.timeframe,
            event_type="execution_event",
            severity="important",
            entity_ids=[str(candidate.get("id"))],
            payload={
                "title": "Trade blocked by risk manager",
                "reason": [assessment.reason],
                "setup": {"playbook": candidate.get("playbook"), "direction": candidate.get("direction")},
            },
            dedupe_key=f"risk-block:{candidate.get('id')}:{datetime.now(UTC).date().isoformat()}",
        )
        return
    execute_candidate(conn, config, env, client, candidate, broker_symbol, lot_size=assessment.lot_size)


def execute_candidate(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    candidate: dict[str, Any],
    broker_symbol: str,
    lot_size: float | None = None,
) -> None:
    # lot_size from risk manager takes precedence; fall back to env fixed volume
    volume = lot_size if lot_size is not None else env.live_order_volume
    stop_loss = candidate.get("stop_loss")
    take_profit = candidate.get("take_profit") or []
    if stop_loss is None or not take_profit:
        return
    direction = str(candidate["direction"])
    side = "buy" if direction == "long" else "sell"
    now = utc_now_iso()
    idea_id = f"live-idea-{candidate['id']}"
    request_id = f"exec-{uuid.uuid4()}"
    order_id = f"live-order-{uuid.uuid4()}"
    context_snapshot = {
        "source": "live",
        "setup_id": candidate["id"],
        "candidate": candidate,
    }
    conn.execute(
        """
        INSERT OR IGNORE INTO trade_ideas (
            id, symbol, direction, playbook, status, entry_zone_id,
            related_zone_ids_json, context_snapshot_json, suggested_entry,
            suggested_stop_loss, suggested_take_profit_json, risk_reward,
            created_at, expires_at
        )
        VALUES (?, ?, ?, ?, 'approved', ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            idea_id,
            config.symbol,
            direction,
            candidate["playbook"],
            candidate.get("primary_zone_id"),
            json.dumps(candidate.get("related_zone_ids") or []),
            json.dumps(context_snapshot, sort_keys=True),
            candidate.get("entry"),
            stop_loss,
            json.dumps(take_profit),
            candidate.get("risk_reward") or 0,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO execution_requests (
            id, trade_idea_id, symbol, broker_symbol, side, order_type, quantity,
            entry_price, stop_loss, take_profit_json, risk_snapshot_json,
            context_snapshot_json, requested_by, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, 'market', ?, NULL, ?, ?, ?, ?, 'strategy', 'approved', ?, ?)
        """,
        (
            request_id,
            idea_id,
            config.symbol,
            broker_symbol,
            side,
            volume,
            stop_loss,
            json.dumps(take_profit),
            json.dumps({"execution_enabled": True, "volume": volume, "account_profile": env.account_profile}, sort_keys=True),
            json.dumps(context_snapshot, sort_keys=True),
            now,
            now,
        ),
    )
    try:
        result = client.place_market_order(
            MT5OrderRequest(
                broker_symbol=broker_symbol,
                side=side,
                volume=volume,
                stop_loss=float(stop_loss),
                take_profit=float(take_profit[0]),
                comment=f"{candidate['playbook']} {candidate['id'][:8]}",
                magic=env.mt5_magic,
            )
        )
        # Store both the order ticket and the deal ticket.  In hedging mode the
        # order ticket becomes the position_id; in netting mode the deal ticket
        # may differ.  Persisting both lets sync_closed_positions fall back to
        # the deal ticket when the order-ticket lookup returns nothing.
        broker_order_id = str(result.get("order") or "")
        broker_deal_id = str(result.get("deal") or "")
        fill_price = float(result.get("price") or candidate.get("entry") or 0)
        conn.execute(
            """
            UPDATE execution_requests
            SET status = 'sent', broker_order_id = ?, broker_result_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (broker_order_id or broker_deal_id, json.dumps(result, sort_keys=True, default=str), now, request_id),
        )
        conn.execute(
            """
            INSERT INTO trade_orders (
                id, trade_idea_id, symbol, side, order_type, status, entry_price,
                stop_loss, take_profit_json, quantity, opened_at, source,
                metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, 'market', 'filled', ?, ?, ?, ?, ?, 'live', ?, ?)
            """,
            (
                order_id,
                idea_id,
                config.symbol,
                side,
                fill_price,
                stop_loss,
                json.dumps(take_profit),
                volume,
                now,
                json.dumps(
                    _build_trade_metadata(candidate, broker_order_id, broker_deal_id, now),
                    sort_keys=True,
                ),
                now,
            ),
        )
        conn.commit()
        queue_alert(
            conn,
            symbol=config.symbol,
            timeframe=config.strategy.timeframe,
            event_type="execution_event",
            severity="critical",
            entity_ids=[idea_id, order_id],
            payload={
                "title": "Live order sent",
                "setup": {
                    "playbook": candidate["playbook"],
                    "direction": direction,
                    "entry": fill_price,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                },
                "reason": [f"MT5 broker order id: {broker_order_id}"],
            },
            dedupe_key=f"live-order:{candidate['id']}",
        )
    except Exception as exc:
        conn.execute(
            """
            UPDATE execution_requests
            SET status = 'failed', failure_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (str(exc)[:1000], utc_now_iso(), request_id),
        )
        conn.commit()
        queue_alert(
            conn,
            symbol=config.symbol,
            timeframe=config.strategy.timeframe,
            event_type="execution_event",
            severity="critical",
            entity_ids=[idea_id],
            payload={"title": "Live order failed", "reason": [str(exc)]},
            dedupe_key=f"live-order-failed:{candidate['id']}:{request_id}",
        )


def sync_closed_positions(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    broker_symbol: str,
) -> None:
    """Sync MT5 position closures back to trade_orders.

    Called every live iteration. Finds any 'filled' live orders whose MT5
    position has since been closed (TP / SL / manual) and updates the DB
    with close_price, pnl, pnl_r, and status='closed'. Without this the
    risk manager's daily loss query returns nothing.
    """
    rows = conn.execute(
        """
        SELECT id, side, entry_price, stop_loss, quantity, metadata_json
        FROM trade_orders
        WHERE symbol = ? AND status = 'filled' AND source = 'live'
        """,
        (config.symbol,),
    ).fetchall()
    if not rows:
        return

    open_tickets = client.get_open_position_tickets(broker_symbol)
    now = utc_now_iso()
    closed_any = False

    # Fetch contract size once for the whole batch (needed for accurate pnl_r).
    try:
        contract_size = client.get_symbol_contract_size(broker_symbol)
    except Exception:
        contract_size = 100.0  # safe fallback for XAUUSD

    for row in rows:
        metadata = json.loads(row["metadata_json"] or "{}")
        broker_order_id = str(metadata.get("broker_order_id", ""))
        broker_deal_id = str(metadata.get("broker_deal_id", ""))

        # Skip if we have no reference ticket at all.
        if not broker_order_id and not broker_deal_id:
            continue

        # Skip if either ticket still appears in the open-positions list.
        if broker_order_id in open_tickets or broker_deal_id in open_tickets:
            continue

        # Try the order ticket first (position_id == order ticket in hedging mode).
        # Fall back to the deal ticket for netting-mode brokers.
        deal = client.get_closed_deal_for_position(broker_order_id) if broker_order_id else None
        if deal is None and broker_deal_id and broker_deal_id != broker_order_id:
            deal = client.get_closed_deal_for_position(broker_deal_id)
        if deal is None:
            continue  # MT5 history not yet available

        # Total P&L includes swap and commission
        pnl = round(deal["profit"] + deal.get("swap", 0) + deal.get("commission", 0), 2)
        close_price = deal["price"]
        closed_at = deal["time_iso"]

        # pnl_r: P&L divided by initial dollar risk.
        #
        # We derive the implied contract size from the deal itself rather than
        # trusting broker config (trade_contract_size from MT5 can be 1 on some
        # brokers for XAUUSDm, making the risk amount 100× too small).
        #
        # deal["profit"] = price_delta_in_direction × qty × contract_size
        # → implied_cs   = deal["profit"] / (price_delta × qty)
        # → risk_amount  = stop_distance  × qty × implied_cs
        pnl_r: float | None = None
        try:
            entry = float(row["entry_price"])
            stop  = float(row["stop_loss"])
            qty   = float(row["quantity"])
            close_px = float(deal["price"])
            side = str(row["side"])  # "buy" or "sell"

            # Directional price delta (positive when trade goes in intended direction)
            direction_sign = 1.0 if side == "buy" else -1.0
            price_delta = (close_px - entry) * direction_sign

            # Infer contract size from the deal's own profit figure.
            # deal["profit"] is the raw directional P&L (swap/commission separate).
            raw_profit = float(deal.get("profit_raw", deal["profit"]))
            if abs(price_delta) > 1e-9 and qty > 0 and abs(raw_profit) > 1e-6:
                implied_cs = raw_profit / (price_delta * qty)
            else:
                implied_cs = contract_size  # fall back to MT5 reported value

            logger.debug(
                "pnl_r calc | side=%s entry=%.5f close=%.5f stop=%.5f qty=%.4f "
                "mt5_cs=%.1f implied_cs=%.1f raw_profit=%.4f pnl=%.4f",
                side, entry, close_px, stop, qty, contract_size, implied_cs, raw_profit, pnl,
            )

            stop_distance = abs(entry - stop)
            risk_amount = stop_distance * qty * abs(implied_cs)
            if risk_amount > 0:
                pnl_r = round(pnl / risk_amount, 3)
        except (TypeError, ValueError, ZeroDivisionError):
            pass

        conn.execute(
            """
            UPDATE trade_orders
            SET status = 'closed',
                close_price = ?,
                pnl = ?,
                pnl_r = ?,
                closed_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (close_price, pnl, pnl_r, closed_at, now, row["id"]),
        )
        closed_any = True
        pnl_str = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
        queue_alert(
            conn,
            symbol=config.symbol,
            timeframe=config.strategy.timeframe,
            event_type="execution_event",
            severity="important",
            entity_ids=[row["id"]],
            payload={
                "title": "Live position closed",
                "reason": [f"P&L: ${pnl_str}", f"Close: {close_price}"],
            },
            dedupe_key=f"position-closed:{row['id']}",
        )

    if closed_any:
        conn.commit()


def latest_closed_candle_time(conn: Connection, symbol: str, timeframe: str) -> str | None:
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
    return None if row is None else str(row["open_time"])


def current_zone_ids(conn: Connection, symbol: str) -> set[str]:
    rows = conn.execute("SELECT id FROM price_zones WHERE symbol = ?", (symbol,)).fetchall()
    return {str(row["id"]) for row in rows}


def new_zone_rows(conn: Connection, symbol: str, before_ids: set[str]) -> list[Any]:
    rows = conn.execute(
        """
        SELECT *
        FROM price_zones
        WHERE symbol = ? AND status = 'active'
        ORDER BY detected_at DESC
        """,
        (symbol,),
    ).fetchall()
    return [row for row in rows if str(row["id"]) not in before_ids]


def live_candidate_already_executed(conn: Connection, candidate_id: str) -> bool:
    """Return True only when a *successful* execution request exists for this candidate.

    Checking trade_ideas alone was insufficient: a failed order (status='failed')
    still creates a trade_idea row, which permanently blocked retries on the same
    candidate even though the order was never actually filled.
    """
    row = conn.execute(
        """
        SELECT er.id
        FROM trade_ideas ti
        JOIN execution_requests er ON er.trade_idea_id = ti.id
        WHERE ti.id = ? AND er.status = 'sent'
        """,
        (f"live-idea-{candidate_id}",),
    ).fetchone()
    return row is not None


def live_trade_count_today(conn: Connection, symbol: str) -> int:
    day_prefix = datetime.now(UTC).date().isoformat()
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM execution_requests
        WHERE symbol = ?
          AND status IN ('sent', 'filled')
          AND created_at >= ?
        """,
        (symbol, day_prefix),
    ).fetchone()
    return int(row["count"])


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _build_trade_metadata(
    candidate: dict[str, Any],
    broker_order_id: str,
    broker_deal_id: str,
    now: str,
) -> dict[str, Any]:
    """Build enriched metadata_json for a trade_orders row.

    Top-level shortcut keys (macro_trend, zone_type, etc.) are extracted from
    the candidate so they can be queried via json_extract without going two
    levels deep.
    """
    cm: dict[str, Any] = candidate.get("metadata") or {}
    return {
        # --- broker linkage ---
        "candidate_id": candidate["id"],
        "candidate_metadata": cm,
        "entry_signal": candidate.get("entry"),
        "broker_order_id": broker_order_id,
        "broker_deal_id": broker_deal_id,
        "playbook": candidate.get("playbook"),
        "primary_zone_id": candidate.get("primary_zone_id"),
        "zone_reaction_state": candidate.get("zone_reaction_state"),
        # --- top-level shortcuts for dashboard queries ---
        "session": trading_session(now),
        "macro_trend": cm.get("macro_trend", "unknown"),
        "zone_type": cm.get("zone_type", "unknown"),
        "zone_source": cm.get("zone_source", "unknown"),
        "zone_detector": cm.get("zone_detector", "unknown"),
        "atr": cm.get("atr"),
        "h1_bias": cm.get("h1_bias", "unknown"),
        "h1_regime": cm.get("h1_regime", "unknown"),
        "confluence_count": cm.get("confluence_count"),
    }


def trading_session(iso_time: str) -> str:
    """Return the trading session name for a UTC ISO timestamp."""
    try:
        h = datetime.fromisoformat(iso_time.replace("Z", "+00:00")).hour
    except Exception:
        return "unknown"
    if h < 7:
        return "Asian"
    if h < 12:
        return "London"
    if h < 17:
        return "London-NY"
    if h < 21:
        return "New York"
    return "Off-hours"
