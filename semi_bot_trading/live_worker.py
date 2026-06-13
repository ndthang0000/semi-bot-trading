from __future__ import annotations

import json
import time
import uuid
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
from .runtime_env import RuntimeEnv
from .smc_zones import detect_and_store_smc_zones
from .structure import detect_and_store_break_structure, detect_and_store_swing_structure
from .zones import apply_and_store_zone_lifecycle, detect_and_store_support_resistance_zones


@dataclass
class LiveWorkerState:
    broker_symbol: str | None = None
    last_closed_m15: str | None = None
    loop_count: int = 0


def run_live_worker(config: AppConfig, env: RuntimeEnv, *, once: bool = False) -> None:
    if env.mt5_login is None or not env.mt5_password or not env.mt5_server:
        raise RuntimeError("MT5_LOGIN, MT5_PASSWORD, and MT5_SERVER are required")
    credentials = MT5Credentials(env.mt5_login, env.mt5_password, env.mt5_server)
    client = MT5BrokerClient(credentials)
    client.connect()
    state = LiveWorkerState(broker_symbol=client.resolve_symbol(env.mt5_symbol, config.symbol))
    try:
        while True:
            run_live_iteration(config, env, client, state)
            if once:
                return
            time.sleep(env.poll_seconds)
    finally:
        client.shutdown()


def run_live_iteration(config: AppConfig, env: RuntimeEnv, client: MT5BrokerClient, state: LiveWorkerState) -> None:
    state.loop_count += 1
    with connect(config.database) as conn:
        init_db(conn)
        sync_mt5_candles(conn, config, env, client)
        latest_m15 = latest_closed_candle_time(conn, config.symbol, config.strategy.timeframe)
        if latest_m15 is not None and latest_m15 != state.last_closed_m15:
            before_zone_ids = current_zone_ids(conn, config.symbol)
            run_live_detectors(conn, config, config.symbol)
            after_zones = new_zone_rows(conn, config.symbol, before_zone_ids)
            queue_zone_alerts(conn, config, env, after_zones)
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
            maybe_execute_candidates(conn, config, env, client, payload["layers"].get("setup_candidates", []))
            state.last_closed_m15 = latest_m15
    with connect(config.database) as conn:
        send_pending_telegram_alerts(conn, token=env.telegram_token, chat_id=env.telegram_chat_id)


def sync_mt5_candles(conn: Connection, config: AppConfig, env: RuntimeEnv, client: MT5BrokerClient) -> None:
    broker_symbol = client.resolve_symbol(env.mt5_symbol, config.symbol)
    for timeframe, count in ((config.bias.timeframe, 800), (config.strategy.timeframe, 1200)):
        candles = client.copy_rates(broker_symbol, config.symbol, timeframe, count)
        closed_candles = candles[:-1] if len(candles) > 1 else candles
        upsert_candles(conn, closed_candles)
        live_candle = candles[-1] if len(candles) > 1 else None
        upsert_live_candle(conn, live_candle)


def run_live_detectors(conn: Connection, config: AppConfig, symbol: str) -> None:
    for timeframe in (config.bias.timeframe, config.strategy.timeframe):
        swing_config = config.swing_for(timeframe)
        detect_and_store_swing_structure(conn, symbol, timeframe, swing_config.window, swing_config.tolerance)
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
) -> None:
    if not env.execution_enabled:
        return
    broker_symbol = client.resolve_symbol(env.mt5_symbol, config.symbol)
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
    execute_candidate(conn, config, env, client, candidate, broker_symbol)


def execute_candidate(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    candidate: dict[str, Any],
    broker_symbol: str,
) -> None:
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
            env.live_order_volume,
            stop_loss,
            json.dumps(take_profit),
            json.dumps({"execution_enabled": True, "volume": env.live_order_volume}, sort_keys=True),
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
                volume=env.live_order_volume,
                stop_loss=float(stop_loss),
                take_profit=float(take_profit[0]),
                comment=f"{candidate['playbook']} {candidate['id'][:8]}",
                magic=env.mt5_magic,
            )
        )
        broker_order_id = str(result.get("order") or result.get("deal") or "")
        fill_price = float(result.get("price") or candidate.get("entry") or 0)
        conn.execute(
            """
            UPDATE execution_requests
            SET status = 'sent', broker_order_id = ?, broker_result_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (broker_order_id, json.dumps(result, sort_keys=True, default=str), now, request_id),
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
                env.live_order_volume,
                now,
                json.dumps({"candidate_id": candidate["id"], "broker_order_id": broker_order_id}, sort_keys=True),
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
    row = conn.execute(
        """
        SELECT id
        FROM trade_ideas
        WHERE id = ?
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
