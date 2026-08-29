from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from sqlite3 import Connection
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .alerts import queue_alert, queue_system_alert, send_pending_telegram_alerts
from .candles import upsert_candles, upsert_live_candle
from .chart import build_chart_payload
from .config import AppConfig
from .context import MarketContext, detect_and_store_bias, detect_and_store_macro_trend, detect_and_store_regime
from .db import connect, init_db
from .mt5_client import MT5BrokerClient, MT5Credentials, MT5OrderRequest
from .news_calendar import active_ftmo_news_window, active_news_blackout, news_calendar_is_fresh, should_notify_news
from .price_action import detect_and_store_price_action_patterns
from .risk_manager import build_risk_manager
from .runtime_env import RuntimeEnv
from .smc_zones import apply_persisted_fvg_mitigation, detect_and_store_smc_zones
from .spread import record_spread_snapshot
from .structure import SWING_DETECTOR, detect_and_store_break_structure, detect_and_store_swing_structure
from .strategy.helpers import close_extreme_recovery_metrics
from .strategy.h1_impulse_retest_v1 import (
    build_h1_impulse_preview,
    h1_impulse_preview_config_from_strategy,
)
from .strategy.liquidity_sweep_reclaim_v1 import evaluate_live_liquidity_zones
from .zones import CandleSlice, apply_and_store_zone_lifecycle, detect_and_store_support_resistance_zones, latest_atr

logger = logging.getLogger(__name__)


@dataclass
class LiveWorkerState:
    broker_symbol: str | None = None
    last_closed_m15: str | None = None
    last_closed_h1: str | None = None
    loop_count: int = 0


@dataclass(frozen=True)
class ExecutionPricingPlan:
    order_type: str
    entry_price: float
    stop_loss: float
    take_profit: list[float]
    expires_at: str | None
    current_price: float
    signal_entry: float
    signal_stop_loss: float
    signal_take_profit: list[float]
    drift: float
    adverse_drift: float
    drift_action: str


def run_live_worker(config: AppConfig, env: RuntimeEnv, *, once: bool = False) -> None:
    if env.mt5_login is None or not env.mt5_password or not env.mt5_server:
        raise RuntimeError("MT5_LOGIN, MT5_PASSWORD, and MT5_SERVER are required")
    credentials = MT5Credentials(
        login=env.mt5_login,
        password=env.mt5_password,
        server=env.mt5_server,
        path=env.mt5_path,
        server_utc_offset_hours=env.mt5_server_utc_offset_hours,
    )
    client = MT5BrokerClient(credentials)

    # MT5 may not be running yet (e.g. service starts before MT5 on reboot).
    # Retry the connection with backoff instead of crashing immediately.
    _connect_with_retry(client, once=once)

    # Initialise DB schema once at startup, not on every poll iteration.
    with closing(connect(config.database)) as conn:
        init_db(conn)
        initial_closed_h1 = latest_closed_candle_time(conn, config.symbol, "H1")
    broker_symbol = client.resolve_symbol(env.mt5_symbol, config.symbol)
    validate_live_account_startup(env, client, broker_symbol)
    state = LiveWorkerState(broker_symbol=broker_symbol, last_closed_h1=initial_closed_h1)
    try:
        while True:
            try:
                run_live_iteration(config, env, client, state)
            except Exception as exc:
                if once:
                    raise  # propagate in one-shot / test mode so callers see the error
                logger.exception("Live iteration error — retrying next cycle")
                if _is_recoverable_mt5_session_error(exc):
                    try:
                        state.broker_symbol = _recover_mt5_session(client, env, config)
                    except Exception:
                        logger.exception("MT5 session recovery failed for %s", env.account_label)
            if once:
                return
            wait_seconds = _seconds_until_next_poll(env.poll_at_seconds, fallback_seconds=env.poll_seconds)
            state.broker_symbol = _wait_with_manual_trade_guard(
                config, env, client, state.broker_symbol, wait_seconds
            )
    finally:
        client.shutdown()


def _seconds_until_next_poll(poll_at_seconds: tuple[int, ...], *, fallback_seconds: float) -> float:
    """Sleep until the next configured second mark, e.g. :01, :16, :45.

    The fallback keeps old deployments working if LIVE_POLL_AT_SECONDS is
    intentionally cleared or invalidated before env parsing.
    """
    if not poll_at_seconds:
        return max(float(fallback_seconds), 0.1)
    marks = tuple(sorted({second for second in poll_at_seconds if 0 <= second <= 59}))
    if not marks:
        return max(float(fallback_seconds), 0.1)
    now = datetime.now()
    for second in marks:
        target = now.replace(second=second, microsecond=0)
        if target > now:
            return max((target - now).total_seconds(), 0.1)
    target = (now + timedelta(minutes=1)).replace(second=marks[0], microsecond=0)
    return max((target - now).total_seconds(), 0.1)


def _wait_with_manual_trade_guard(
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    broker_symbol: str,
    wait_seconds: float,
) -> str:
    """Run the discipline guard at its own cadence between strategy polls.

    Calls remain sequential on the same MT5 client. This avoids concurrent
    MetaTrader5 access while keeping manual-trade enforcement near one second.
    """
    deadline = time.monotonic() + max(wait_seconds, 0.0)
    guard_seconds = max(float(env.manual_trade_guard_seconds), 0.25)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return broker_symbol
        time.sleep(min(guard_seconds, remaining))
        if time.monotonic() >= deadline:
            return broker_symbol
        try:
            run_manual_trade_guard_iteration(config, env, client, broker_symbol)
        except Exception as exc:
            logger.exception("Manual trading lock guard failed for %s", env.account_label)
            if _is_recoverable_mt5_session_error(exc):
                try:
                    broker_symbol = _recover_mt5_session(client, env, config)
                except Exception:
                    logger.exception("MT5 session recovery failed for %s", env.account_label)


def _is_recoverable_mt5_session_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "mt5 symbol not found",
            "mt5 symbol_select failed",
            "mt5 initialize failed",
            "ipc initialize failed",
            "no ipc connection",
        )
    )


def _recover_mt5_session(client: MT5BrokerClient, env: RuntimeEnv, config: AppConfig) -> str:
    """Reconnect after a terminal restart and resolve the broker symbol again."""
    try:
        client.shutdown()
    except Exception:
        logger.debug("MT5 shutdown during recovery failed", exc_info=True)
    client.connect()
    broker_symbol = client.resolve_symbol(env.mt5_symbol, config.symbol)
    validate_live_account_startup(env, client, broker_symbol)
    logger.info("MT5 session recovered for %s with symbol %s", env.account_label, broker_symbol)
    return broker_symbol


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


def validate_live_account_startup(env: RuntimeEnv, client: MT5BrokerClient, broker_symbol: str) -> None:
    """Validate account/symbol metadata before the worker can evaluate execution."""
    account = client.get_account_info()
    trade_info: dict[str, Any] = {}
    if hasattr(client, "get_symbol_trade_info"):
        trade_info = dict(client.get_symbol_trade_info(broker_symbol))
    else:
        trade_info = {"trade_contract_size": client.get_symbol_contract_size(broker_symbol)}

    contract_size = float(trade_info.get("trade_contract_size") or 0.0)
    if contract_size <= 0:
        raise RuntimeError(f"Invalid MT5 contract size for {broker_symbol}: {contract_size}")
    if env.account_profile.lower().startswith("ftmo") and contract_size < 10:
        raise RuntimeError(f"Refusing FTMO startup with suspicious contract size for {broker_symbol}: {contract_size}")
    if env.account_profile.lower().startswith("ftmo") and env.account_balance_scale not in (None, 1.0):
        raise RuntimeError("FTMO profile must use ACCOUNT_BALANCE_SCALE=1.0 or leave it unset")
    if env.account_profile.lower().startswith("ftmo"):
        ftmo_phase = env.ftmo_phase.strip().lower()
        ftmo_account_type = env.ftmo_account_type.strip().lower()
        if ftmo_phase not in {"evaluation", "challenge", "verification", "funded"}:
            raise RuntimeError(
                "FTMO_PHASE must be evaluation, challenge, verification, or funded"
            )
        if ftmo_account_type not in {"standard", "swing"}:
            raise RuntimeError("FTMO_ACCOUNT_TYPE must be standard or swing")
        if ftmo_phase == "funded" and ftmo_account_type == "standard" and env.ftmo_news_buffer_minutes < 4:
            raise RuntimeError("Funded Standard FTMO requires FTMO_NEWS_BUFFER_MINUTES >= 4")

    logger.info(
        "Live account validated label=%s profile=%s login=%s server=%s broker_symbol=%s "
        "balance=%.2f equity=%.2f currency=%s contract_size=%.4f volume_min=%s volume_max=%s volume_step=%s "
        "execution_enabled=%s server_utc_offset_hours=%s ftmo_phase=%s ftmo_account_type=%s",
        env.account_label,
        env.account_profile,
        env.mt5_login,
        env.mt5_server,
        broker_symbol,
        float(account.get("balance") or 0.0),
        float(account.get("equity") or 0.0),
        account.get("currency"),
        contract_size,
        trade_info.get("volume_min"),
        trade_info.get("volume_max"),
        trade_info.get("volume_step"),
        env.execution_enabled,
        env.mt5_server_utc_offset_hours,
        env.ftmo_phase,
        env.ftmo_account_type,
    )


def _ftmo_day_window(now: datetime, timezone_name: str) -> tuple[str, datetime]:
    zone = ZoneInfo(timezone_name)
    local_now = now.astimezone(zone)
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_now.date().isoformat(), local_midnight.astimezone(UTC)


def _resolved_initial_balance(env: RuntimeEnv) -> float | None:
    if env.account_initial_balance and env.account_initial_balance > 0:
        return env.account_initial_balance
    if env.account_profile.lower().startswith("ftmo"):
        match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*[kK](?!\w)", env.account_label)
        if match:
            return float(match.group(1)) * 1_000.0
    return None


def update_account_daily_metric(
    conn: Connection,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    info: dict[str, Any],
    now: datetime,
) -> None:
    """Persist FTMO-style daily P/L: current equity minus Prague-midnight balance."""
    trading_day, day_start_utc = _ftmo_day_window(now, env.daily_reset_timezone)
    balance = float(info["balance"])
    equity = float(info["equity"])
    baseline_source = "mt5_deal_history"
    try:
        balance_at_midnight = balance - float(client.balance_change_since(day_start_utc))
    except (AttributeError, RuntimeError):
        existing = conn.execute(
            "SELECT balance_at_midnight FROM account_daily_metrics WHERE account_label = ? AND trading_day = ?",
            (env.account_label, trading_day),
        ).fetchone()
        balance_at_midnight = float(existing["balance_at_midnight"]) if existing else balance
        baseline_source = "first_snapshot_fallback"
    daily_profit = equity - balance_at_midnight
    initial_balance = _resolved_initial_balance(env)
    pct_denominator = initial_balance if initial_balance and initial_balance > 0 else balance_at_midnight
    daily_profit_pct = (daily_profit / pct_denominator * 100.0) if pct_denominator > 0 else None
    conn.execute(
        """
        INSERT INTO account_daily_metrics (
            account_label, trading_day, timezone, day_start_utc, balance_at_midnight,
            current_balance, current_equity, daily_profit, daily_profit_pct,
            initial_balance, baseline_source, snapshot_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_label, trading_day) DO UPDATE SET
            timezone = excluded.timezone,
            day_start_utc = excluded.day_start_utc,
            balance_at_midnight = excluded.balance_at_midnight,
            current_balance = excluded.current_balance,
            current_equity = excluded.current_equity,
            daily_profit = excluded.daily_profit,
            daily_profit_pct = excluded.daily_profit_pct,
            initial_balance = excluded.initial_balance,
            baseline_source = excluded.baseline_source,
            snapshot_at = excluded.snapshot_at
        """,
        (
            env.account_label, trading_day, env.daily_reset_timezone, day_start_utc.isoformat(),
            balance_at_midnight, balance, equity, daily_profit, daily_profit_pct,
            initial_balance, baseline_source, now.isoformat(),
        ),
    )


def snapshot_account(conn: Connection, env: RuntimeEnv, client: MT5BrokerClient) -> None:
    """Upsert the latest MT5 account metrics into account_snapshots (one row per label)."""
    try:
        info = client.get_account_info()
    except Exception:
        logger.warning("Could not fetch MT5 account info for snapshot", exc_info=True)
        return
    now_dt = datetime.now(UTC)
    now = now_dt.isoformat()
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
    update_account_daily_metric(conn, env, client, info, now_dt)
    conn.commit()


def refresh_account_execution_control(
    conn: Connection,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    broker_symbol: str,
) -> None:
    now = utc_now_iso()
    open_positions = 0
    pending_orders = 0
    if broker_symbol:
        try:
            open_positions, pending_orders = client.bot_order_counts(broker_symbol, magic=env.mt5_magic)
        except AttributeError:
            pass
    conn.execute(
        """
        INSERT OR IGNORE INTO account_execution_controls (
            account_label, requested_enabled, effective_enabled, hard_enabled,
            worker_status, broker_symbol, partial_take_profit_enabled,
            partial_take_profit_r, heartbeat_at, acknowledged_at, updated_at
        ) VALUES (?, ?, ?, ?, 'online', ?, ?, ?, ?, ?, ?)
        """,
        (
            env.account_label,
            int(env.execution_enabled),
            int(env.execution_enabled),
            int(env.execution_enabled),
            broker_symbol,
            int(env.partial_take_profit_enabled),
            float(env.partial_take_profit_r),
            now,
            now,
            now,
        ),
    )
    row = conn.execute(
        "SELECT requested_enabled FROM account_execution_controls WHERE account_label = ?",
        (env.account_label,),
    ).fetchone()
    requested = bool(row and row["requested_enabled"])
    conn.execute(
        """
        UPDATE account_execution_controls
        SET effective_enabled = ?, hard_enabled = ?, worker_status = 'online', broker_symbol = ?,
            open_bot_positions = ?, pending_bot_orders = ?, heartbeat_at = ?,
            partial_take_profit_enabled = COALESCE(partial_take_profit_enabled, ?),
            partial_take_profit_r = COALESCE(partial_take_profit_r, ?),
            acknowledged_at = ?, last_error = NULL, updated_at = ?
        WHERE account_label = ?
        """,
        (
            int(env.execution_enabled and requested), int(env.execution_enabled), broker_symbol,
            open_positions,
            pending_orders,
            now,
            int(env.partial_take_profit_enabled),
            float(env.partial_take_profit_r),
            now,
            now,
            env.account_label,
        ),
    )
    conn.commit()


def account_execution_is_enabled(conn: Connection, env: RuntimeEnv) -> bool:
    if not env.execution_enabled:
        return False
    row = conn.execute(
        "SELECT requested_enabled, effective_enabled FROM account_execution_controls WHERE account_label = ?",
        (env.account_label,),
    ).fetchone()
    # Backward compatible for direct unit calls before the worker heartbeat.
    return True if row is None else bool(row["requested_enabled"] and row["effective_enabled"])


def account_partial_take_profit_settings(conn: Connection, env: RuntimeEnv) -> tuple[bool, float]:
    row = conn.execute(
        """
        SELECT partial_take_profit_enabled, partial_take_profit_r
        FROM account_execution_controls
        WHERE account_label = ?
        """,
        (env.account_label,),
    ).fetchone()
    if row is None:
        return bool(env.partial_take_profit_enabled), float(env.partial_take_profit_r)
    enabled_value = row["partial_take_profit_enabled"]
    trigger_value = row["partial_take_profit_r"]
    enabled = bool(env.partial_take_profit_enabled) if enabled_value is None else bool(enabled_value)
    trigger_r = float(env.partial_take_profit_r) if trigger_value is None else float(trigger_value)
    return enabled, min(max(trigger_r, 0.5), 2.0)


def run_manual_trade_guard_iteration(
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    broker_symbol: str,
) -> bool:
    """Run one fast manual-trading-lock pass and promptly flush its alerts."""
    if not broker_symbol:
        return False
    with closing(connect(config.database)) as conn:
        acted = process_manual_trading_lock(conn, config, env, client, broker_symbol)
    if acted:
        with closing(connect(config.database)) as conn:
            send_pending_telegram_alerts(
                conn,
                token=env.telegram_token,
                chat_id=env.telegram_chat_id,
                account_label=env.account_label,
            )
    return acted


def process_manual_trading_lock(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    broker_symbol: str,
) -> bool:
    """Cancel/close only new MT5 manual exposure while preserving bot orders.

    Manual MT5 trades use magic=0. Existing manual tickets are snapshotted when
    the lock becomes effective and are grandfathered until the user disables
    the lock. Non-zero magic numbers, including this bot's magic, are untouched.
    """
    row = conn.execute(
        """
        SELECT manual_lock_requested_enabled, manual_lock_effective_enabled,
               manual_lock_baseline_positions_json, manual_lock_baseline_orders_json,
               manual_lock_requested_at, manual_lock_last_error
        FROM account_execution_controls
        WHERE account_label = ?
        """,
        (env.account_label,),
    ).fetchone()
    if row is None:
        return False
    if not bool(row["manual_lock_requested_enabled"]):
        if bool(row["manual_lock_effective_enabled"]):
            conn.execute(
                """
                UPDATE account_execution_controls
                SET manual_lock_effective_enabled = 0,
                    manual_lock_baseline_positions_json = '[]',
                    manual_lock_baseline_orders_json = '[]',
                    manual_lock_acknowledged_at = ?, manual_lock_last_error = NULL,
                    updated_at = ?
                WHERE account_label = ?
                """,
                (utc_now_iso(), utc_now_iso(), env.account_label),
            )
            conn.commit()
        return False

    now = utc_now_iso()
    try:
        positions = [
            position
            for position in client.get_open_positions(broker_symbol)
            if int(position.get("magic", 0) or 0) == 0
        ]
        orders = [
            order
            for order in client.get_pending_orders(broker_symbol)
            if int(order.get("magic", 0) or 0) == 0
        ]
    except Exception as exc:
        conn.execute(
            """
            UPDATE account_execution_controls
            SET manual_lock_last_error = ?, updated_at = ?
            WHERE account_label = ?
            """,
            (str(exc)[:1000], now, env.account_label),
        )
        conn.commit()
        raise

    position_by_ticket = {str(item["ticket"]): item for item in positions}
    order_by_ticket = {str(item["ticket"]): item for item in orders}
    if not bool(row["manual_lock_effective_enabled"]):
        baseline_positions = sorted(position_by_ticket)
        baseline_orders = sorted(order_by_ticket)
        conn.execute(
            """
            UPDATE account_execution_controls
            SET manual_lock_effective_enabled = 1,
                manual_lock_baseline_positions_json = ?, manual_lock_baseline_orders_json = ?,
                manual_lock_acknowledged_at = ?, manual_lock_last_error = NULL,
                updated_at = ?
            WHERE account_label = ? AND manual_lock_requested_enabled = 1
            """,
            (json.dumps(baseline_positions), json.dumps(baseline_orders), now, now, env.account_label),
        )
        conn.commit()
        queue_alert(
            conn,
            account_label=env.account_label,
            symbol=config.symbol,
            timeframe=config.strategy.timeframe,
            event_type="execution_event",
            severity="important",
            entity_ids=[],
            payload={
                "title": "Manual trading lock enabled",
                "outcome": "info",
                "account": env.account_label,
                "reason": [
                    f"Guard cadence: {env.manual_trade_guard_seconds:g}s",
                    f"Grandfathered manual positions: {len(baseline_positions)}",
                    f"Grandfathered manual pending orders: {len(baseline_orders)}",
                ],
            },
            dedupe_key=f"manual-lock-enabled:{env.account_label}:{row['manual_lock_requested_at'] or now}",
        )
        return True

    baseline_positions = _ticket_set(row["manual_lock_baseline_positions_json"])
    baseline_orders = _ticket_set(row["manual_lock_baseline_orders_json"])
    violating_orders = [item for ticket, item in order_by_ticket.items() if ticket not in baseline_orders]
    violating_positions = [
        item
        for ticket, item in position_by_ticket.items()
        if ticket not in baseline_positions and ticket not in baseline_orders
    ]
    acted = False
    errors: list[str] = []

    for order in violating_orders:
        ticket = str(order["ticket"])
        try:
            client.cancel_pending_order(
                broker_symbol,
                order_ticket=ticket,
                comment="Manual trading lock",
            )
            acted = True
            _queue_manual_lock_action_alert(conn, config, env, "cancelled", "pending order", ticket, order)
        except Exception as exc:
            errors.append(f"pending {ticket}: {exc}")
            _queue_manual_lock_action_alert(conn, config, env, "failed to cancel", "pending order", ticket, order, exc)

    for position in violating_positions:
        ticket = str(position["ticket"])
        try:
            client.close_position(
                broker_symbol,
                position_ticket=ticket,
                side=str(position["side"]),
                volume=float(position["volume"]),
                magic=env.mt5_magic,
                comment="Manual trading lock",
            )
            acted = True
            _queue_manual_lock_action_alert(conn, config, env, "closed", "position", ticket, position)
        except Exception as exc:
            errors.append(f"position {ticket}: {exc}")
            _queue_manual_lock_action_alert(conn, config, env, "failed to close", "position", ticket, position, exc)

    if violating_orders or violating_positions:
        conn.execute(
            """
            UPDATE account_execution_controls
            SET manual_lock_last_action_at = ?, manual_lock_last_error = ?, updated_at = ?
            WHERE account_label = ?
            """,
            (now, "; ".join(errors)[:1000] if errors else None, now, env.account_label),
        )
        conn.commit()
    elif row["manual_lock_last_error"]:
        conn.execute(
            """
            UPDATE account_execution_controls
            SET manual_lock_last_error = NULL, updated_at = ?
            WHERE account_label = ?
            """,
            (now, env.account_label),
        )
        conn.commit()
    return acted or bool(errors)


def _ticket_set(raw: str | None) -> set[str]:
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return set()
    if not isinstance(parsed, list):
        return set()
    return {str(ticket) for ticket in parsed}


def _queue_manual_lock_action_alert(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    action: str,
    exposure_type: str,
    ticket: str,
    exposure: dict[str, Any],
    error: Exception | None = None,
) -> None:
    details = [
        f"Account: {env.account_label}",
        f"Ticket: {ticket}",
        f"Magic: {int(exposure.get('magic', 0) or 0)}",
    ]
    if exposure_type == "position":
        details.append(f"Side/volume: {exposure.get('side')} {exposure.get('volume')}")
    else:
        details.append(f"Volume/price: {exposure.get('volume')} @ {exposure.get('price_open')}")
    if error is not None:
        details.append(f"Error: {error}")
    queue_alert(
        conn,
        account_label=env.account_label,
        symbol=config.symbol,
        timeframe=config.strategy.timeframe,
        event_type="execution_event",
        severity="critical" if error is not None else "important",
        entity_ids=[ticket],
        payload={
            "title": f"Manual {exposure_type} {action} by discipline lock",
            "outcome": "failed" if error is not None else "info",
            "account": env.account_label,
            "reason": details,
        },
        dedupe_key=f"manual-lock:{env.account_label}:{exposure_type}:{ticket}:{action}",
    )


def process_account_execution_commands(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    broker_symbol: str,
) -> None:
    row = conn.execute(
        """
        SELECT id, command_type, payload_json FROM account_execution_commands
        WHERE account_label = ?
          AND command_type IN (
              'close_all_positions', 'close_all_bot_orders',
              'close_trade_position', 'partial_trade_position', 'break_even_trade_position'
          )
          AND status = 'pending'
        ORDER BY requested_at LIMIT 1
        """,
        (env.account_label,),
    ).fetchone()
    if row is None:
        return
    command_id = str(row["id"])
    command_type = str(row["command_type"])
    payload = json.loads(row["payload_json"] or "{}")
    include_manual_positions = bool(payload.get("include_manual_positions", False))
    now = utc_now_iso()
    conn.execute(
        "UPDATE account_execution_commands SET status = 'processing', claimed_at = ? WHERE id = ? AND status = 'pending'",
        (now, command_id),
    )
    conn.commit()
    try:
        if command_type in {"close_all_positions", "close_all_bot_orders"}:
            cancelled = client.cancel_pending_orders(broker_symbol, magic=env.mt5_magic, comment="Dashboard close all")
            closed = client.close_open_positions(
                broker_symbol,
                magic=None if include_manual_positions else env.mt5_magic,
                comment="Dashboard close all",
            )
            if closed:
                sync_closed_positions(conn, config, env, client, broker_symbol)
            result = {
                "cancelled_bot_orders": len(cancelled),
                "closed_positions": len(closed),
                "manual_positions_included": include_manual_positions,
                "manual_pending_orders_untouched": True,
            }
        else:
            result = _execute_trade_management_command(
                conn,
                config,
                env,
                client,
                broker_symbol,
                command_id=command_id,
                command_type=command_type,
                payload=payload,
            )
        conn.execute(
            "UPDATE account_execution_commands SET status = 'succeeded', completed_at = ?, result_json = ? WHERE id = ?",
            (utc_now_iso(), json.dumps(result, sort_keys=True), command_id),
        )
    except Exception as exc:
        logger.exception("Dashboard execution command %s failed for %s", command_type, env.account_label)
        conn.execute(
            "UPDATE account_execution_commands SET status = 'failed', completed_at = ?, error = ? WHERE id = ?",
            (utc_now_iso(), str(exc), command_id),
        )
    conn.commit()
    refresh_account_execution_control(conn, env, client, broker_symbol)


def _execute_trade_management_command(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    broker_symbol: str,
    *,
    command_id: str,
    command_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    trade_order_id = str(payload.get("trade_order_id") or "")
    if not trade_order_id:
        raise RuntimeError("Trade management command is missing trade_order_id")
    row = conn.execute(
        """
        SELECT id, account_label, symbol, side, status, source, entry_price,
               stop_loss, take_profit_json, quantity, metadata_json
        FROM trade_orders
        WHERE id = ? AND account_label = ?
        """,
        (trade_order_id, env.account_label),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Trade {trade_order_id} does not belong to account {env.account_label}")
    if str(row["source"]) != "live" or str(row["status"]) != "filled":
        raise RuntimeError("Trade is no longer an open live position")

    metadata = json.loads(row["metadata_json"] or "{}")
    if not isinstance(metadata, dict):
        metadata = {}
    open_positions = client.get_open_positions(broker_symbol)
    position = _find_trade_position(metadata, open_positions)
    if position is None:
        raise RuntimeError("Broker position for this trade is not open")
    position_magic = int(position.get("magic") or 0)
    if position_magic != env.mt5_magic:
        raise RuntimeError("Broker position magic does not match this bot worker")
    side = str(row["side"]).lower()
    if str(position.get("side") or "").lower() != side:
        raise RuntimeError("Broker position side does not match the trade")
    ticket = str(position.get("ticket") or "")
    volume = float(position.get("volume") or 0.0)
    if not ticket or volume <= 0:
        raise RuntimeError("Broker position ticket or volume is invalid")

    entry = float(position.get("price_open") or metadata.get("broker_position_entry_price") or row["entry_price"])
    current_stop = float(position.get("sl") or row["stop_loss"] or 0.0)
    take_profits = json.loads(row["take_profit_json"] or "[]")
    fallback_tp = float(take_profits[0]) if take_profits else 0.0
    current_tp = float(position.get("tp") or fallback_tp)
    action = {
        "close_trade_position": "close_now",
        "partial_trade_position": "partial_50_be",
        "break_even_trade_position": "break_even",
    }[command_type]
    now = utc_now_iso()
    result: dict[str, Any] = {
        "trade_order_id": trade_order_id,
        "account_label": env.account_label,
        "action": action,
        "position_ticket": ticket,
    }

    if command_type == "close_trade_position":
        close_result = client.close_position(
            broker_symbol,
            position_ticket=ticket,
            side=side,
            volume=volume,
            magic=env.mt5_magic,
            comment="Dashboard close trade",
        )
        result.update({"closed_volume": volume, "close_result": close_result})
    elif command_type == "partial_trade_position":
        partial = metadata.get("partial_take_profit")
        partial = partial if isinstance(partial, dict) else {}
        if partial.get("done") is True:
            raise RuntimeError("This trade has already taken a partial profit")
        close_volume = _round_lot_volume(volume * 0.5)
        if close_volume <= 0 or close_volume >= volume:
            raise RuntimeError(f"Position volume {volume:g} is too small to close 50% safely")
        close_result = client.close_partial_position(
            broker_symbol,
            position_ticket=ticket,
            side=side,
            volume=close_volume,
            magic=env.mt5_magic,
            comment="Dashboard partial 50pct",
        )
        already_protected = _position_stop_is_at_break_even(side, current_stop, entry)
        if already_protected:
            modify_result, modify_error = None, None
        else:
            modify_result, modify_error = _try_apply_break_even(
                client,
                broker_symbol=broker_symbol,
                position_ticket=ticket,
                stop_loss=entry,
                take_profit=current_tp,
                magic=env.mt5_magic,
                comment="Dashboard partial BE",
            )
        partial.update({
            "enabled": True,
            "fraction": 0.5,
            "move_stop_to": "breakeven",
            "done": True,
            "done_at": now,
            "manual_action": True,
            "closed_volume": close_volume,
            "remaining_volume_estimate": round(max(volume - close_volume, 0.0), 4),
            "breakeven_stop": entry,
            "breakeven_applied": modify_error is None,
            "breakeven_already_protected": already_protected,
            "close_result": close_result,
            "modify_result": modify_result,
            "modify_error": modify_error,
        })
        metadata["partial_take_profit"] = partial
        metadata["stop_management_state"] = "partial_taken_be" if modify_error is None else "partial_taken_be_failed"
        result.update({
            "closed_volume": close_volume,
            "remaining_volume_estimate": round(max(volume - close_volume, 0.0), 4),
            "break_even_applied": modify_error is None,
            "already_protected": already_protected,
            "break_even_error": modify_error,
            "close_result": close_result,
            "modify_result": modify_result,
        })
        if modify_error is None and not already_protected:
            current_stop = entry
    else:
        already_protected = _position_stop_is_at_break_even(side, current_stop, entry)
        modify_result: dict[str, Any] | None = None
        if not already_protected:
            modify_result = client.modify_position_sltp(
                broker_symbol,
                position_ticket=ticket,
                stop_loss=entry,
                take_profit=current_tp,
                magic=env.mt5_magic,
                comment="Dashboard break even",
            )
            current_stop = entry
        metadata["stop_management_state"] = "manual_breakeven"
        result.update({
            "break_even_applied": True,
            "already_protected": already_protected,
            "stop_loss": current_stop,
            "modify_result": modify_result,
        })

    metadata.setdefault("initial_stop_loss", float(row["stop_loss"]))
    metadata["current_stop_loss"] = current_stop
    management = metadata.get("trade_management")
    management = management if isinstance(management, dict) else {}
    history = management.get("history")
    history = history if isinstance(history, list) else []
    history.append({
        "command_id": command_id,
        "action": action,
        "executed_at": now,
        "position_ticket": ticket,
        "closed_volume": result.get("closed_volume"),
        "break_even_applied": result.get("break_even_applied"),
        "break_even_error": result.get("break_even_error"),
    })
    management.update({"last_action": action, "last_command_id": command_id, "last_executed_at": now, "history": history[-20:]})
    metadata["trade_management"] = management
    conn.execute(
        "UPDATE trade_orders SET stop_loss = ?, metadata_json = ?, updated_at = ? WHERE id = ?",
        (current_stop, json.dumps(metadata, sort_keys=True, default=str), now, trade_order_id),
    )
    conn.commit()
    if command_type == "close_trade_position":
        sync_closed_positions(conn, config, env, client, broker_symbol)

    queue_alert(
        conn,
        account_label=env.account_label,
        symbol=config.symbol,
        timeframe=config.strategy.timeframe,
        event_type="execution_event",
        severity="critical" if result.get("break_even_error") else "important",
        entity_ids=[trade_order_id],
        payload={
            "title": {
                "close_now": "Trade closed from dashboard",
                "partial_50_be": "Manual partial 50% + break-even",
                "break_even": "Trade moved to break-even",
            }[action],
            "outcome": "failed" if result.get("break_even_error") else "info",
            "account": env.account_label,
            "reason": [
                f"Trade: {trade_order_id}",
                f"Position: {ticket}",
                *([f"Break-even failed: {result['break_even_error']}"] if result.get("break_even_error") else []),
            ],
        },
        dedupe_key=f"trade-management:{command_id}",
    )
    conn.commit()
    result["trade_patch"] = _trade_management_patch(conn, trade_order_id)
    return result


def _find_trade_position(metadata: dict[str, Any], positions: list[dict[str, Any]]) -> dict[str, Any] | None:
    tickets = {
        str(metadata.get(key) or "")
        for key in ("broker_position_id", "broker_order_id", "broker_deal_id")
    }
    tickets.discard("")
    return next((position for position in positions if str(position.get("ticket") or "") in tickets), None)


def _position_stop_is_at_break_even(side: str, stop_loss: float, entry: float) -> bool:
    if stop_loss <= 0:
        return False
    return stop_loss >= entry - 1e-9 if side == "buy" else stop_loss <= entry + 1e-9


def _trade_management_patch(conn: Connection, trade_order_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT status, stop_loss, closed_at, close_price, pnl, pnl_r, metadata_json FROM trade_orders WHERE id = ?",
        (trade_order_id,),
    ).fetchone()
    if row is None:
        return {}
    return {
        "status": row["status"],
        "stop_loss": float(row["stop_loss"]) if row["stop_loss"] is not None else None,
        "closed_at": row["closed_at"],
        "close_price": float(row["close_price"]) if row["close_price"] is not None else None,
        "pnl": float(row["pnl"]) if row["pnl"] is not None else None,
        "pnl_r": float(row["pnl_r"]) if row["pnl_r"] is not None else None,
        "metadata": json.loads(row["metadata_json"] or "{}"),
    }


def snapshot_spread(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    broker_symbol: str,
    now: datetime | None = None,
) -> None:
    try:
        quote = client.get_current_quote(broker_symbol)
    except AttributeError:
        logger.debug("Broker client does not expose get_current_quote; skipping spread snapshot")
        return
    except Exception:
        logger.warning("Could not fetch MT5 spread snapshot", exc_info=True)
        return
    record_spread_snapshot(
        conn,
        symbol=config.symbol,
        broker_symbol=broker_symbol,
        account_label=env.account_label,
        bid=quote["bid"],
        ask=quote["ask"],
        spread=quote["spread"],
        snapshot_at=now,
    )


def run_live_iteration(config: AppConfig, env: RuntimeEnv, client: MT5BrokerClient, state: LiveWorkerState) -> None:
    state.loop_count += 1
    now = datetime.now(UTC)
    broker_symbol: str = state.broker_symbol or ""
    with closing(connect(config.database)) as conn:
        # Queue Telegram alerts for tier-1/2 events arriving in ~10 minutes.
        _maybe_queue_news_alerts(conn, config, env, now)
        _expire_news_regimes(conn, config, now)

        # init_db is called once at startup in run_live_worker; skip here.
        snapshot_account(conn, env, client)
        refresh_account_execution_control(conn, env, client, broker_symbol)
        if broker_symbol:
            process_manual_trading_lock(conn, config, env, client, broker_symbol)
        ftmo_news_guard = ftmo_news_guard_state(conn, env, now)
        if broker_symbol and ftmo_news_guard is None:
            process_account_execution_commands(conn, config, env, client, broker_symbol)
        if broker_symbol:
            snapshot_spread(conn, config, env, client, broker_symbol, now)
        if env.live_sync_candles:
            sync_mt5_candles(conn, config, client, broker_symbol)
        if broker_symbol:
            sync_filled_pending_orders(conn, config, env, client, broker_symbol)
            process_manual_ai_plans(conn, config, env, client, broker_symbol, now)
        if broker_symbol:
            sync_closed_positions(conn, config, env, client, broker_symbol)
            if ftmo_news_guard is None:
                manage_open_trade_partial_take_profit(conn, config, env, client, broker_symbol)
            elif ftmo_news_guard["phase"] == "prepare":
                maybe_ftmo_news_flatten(conn, config, env, client, broker_symbol, ftmo_news_guard)
            else:
                queue_ftmo_news_guard_alert(conn, config, env, client, broker_symbol, ftmo_news_guard, now)
            if ftmo_news_guard is None or ftmo_news_guard["phase"] == "stale":
                maybe_weekend_flatten(conn, config, env, client, broker_symbol, now)
            try:
                quote = client.get_current_quote(broker_symbol)
                liquidity_candidates = evaluate_live_liquidity_zones(
                    conn,
                    symbol=config.symbol,
                    timeframe=config.strategy.timeframe,
                    account_label=env.account_label,
                    bid=float(quote["bid"]),
                    ask=float(quote["ask"]),
                    spread=float(quote["spread"]),
                    now=now,
                    config=config.strategy,
                )
            except AttributeError:
                liquidity_candidates = []
                logger.debug("Broker client does not expose quote data; skipping liquidity sweep evaluation")
            except Exception:
                liquidity_candidates = []
                logger.warning("Could not evaluate live liquidity sweep zones", exc_info=True)
            if liquidity_candidates:
                queue_setup_alerts(conn, config, env, liquidity_candidates)
                maybe_execute_candidates(conn, config, env, client, liquidity_candidates, broker_symbol)
        latest_m15 = latest_closed_candle_time(conn, config.symbol, config.strategy.timeframe)
        has_new_closed_m15 = latest_m15 is not None and latest_m15 != state.last_closed_m15
        if env.live_run_detectors and has_new_closed_m15:
            before_zone_ids = current_zone_ids(conn, config.symbol)
            run_live_detectors(conn, config, config.symbol, env.account_label)
            apply_persisted_fvg_mitigation(conn, config.symbol, config.bias.timeframe)
            after_zones = new_zone_rows(conn, config.symbol, before_zone_ids)
            queue_zone_alerts(conn, config, env, after_zones)
            state.last_closed_m15 = latest_m15
        elif has_new_closed_m15:
            state.last_closed_m15 = latest_m15
        if has_new_closed_m15:
            queue_m15_recovery_alert(conn, config, env)
        queue_new_h1_impulse_alert(conn, config, env, state)

        # Override H1 regime to "news" during active blackout windows so that
        # strategy evaluation and the UI both reflect the news state.
        blackout = active_news_blackout(conn, now)
        if blackout:
            _upsert_news_regime(conn, config, blackout)

        if latest_m15 is not None:
            # Closed M15 updates drive detectors, but setup evaluation must run
            # every poll. Otherwise a worker that has already processed the
            # latest closed candle can miss a setup that becomes eligible after
            # a human zone edit or a delayed DB sync; restarting the worker would
            # reset last_closed_m15 and execute the same setup, which is unsafe.
            apply_persisted_fvg_mitigation(conn, config.symbol, config.bias.timeframe)
            payload = build_chart_payload(
                conn,
                symbol=config.symbol,
                timeframe=config.strategy.timeframe,
                limit=500,
                active_zones_only=True,
                structure_timeframe=config.bias.timeframe,
                strategy_config=config.strategy,
                candidate_zone_timeframes={config.bias.timeframe},
                macro_trend_config=config.macro_trend,
                include_live_strategy_candle=env.live_evaluate_intrabar,
                traded_account_label=env.account_label,
            )
            queue_setup_alerts(conn, config, env, payload["layers"].get("setup_candidates", []))
            maybe_execute_candidates(conn, config, env, client, payload["layers"].get("setup_candidates", []), broker_symbol)
    with closing(connect(config.database)) as conn:
        send_pending_telegram_alerts(
            conn,
            token=env.telegram_token,
            chat_id=env.telegram_chat_id,
            account_label=env.account_label,
        )


def _maybe_queue_news_alerts(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    now: datetime,
) -> None:
    """Queue a Telegram alert for tier-1/2 events arriving in ~10 minutes."""
    if not env.live_run_detectors or not env.telegram_token or not env.telegram_chat_id:
        return
    events = should_notify_news(conn, now, notify_minutes_before=10)
    for ev in events:
        tier = int(ev["tier"])
        tier_label = "🔴🔴 Tin Đỏ Tối Cao" if tier == 1 else "🔴 Tin Đỏ"
        before = int(ev["blackout_before_min"])
        after = int(ev["blackout_after_min"])
        lines = [
            f"[{config.symbol}] Tin tức sắp ra trong ~10 phút",
            f"{tier_label}: {ev['title']}",
            f"USD · Blackout ±{before}/{after} phút",
        ]
        if ev.get("forecast"):
            lines.append(f"Forecast: {ev['forecast']}  |  Previous: {ev.get('previous', '?')}")
        queue_alert(
            conn,
            account_label=env.account_label,
            symbol=config.symbol,
            timeframe=config.regime.timeframe,
            event_type="news_alert",
            severity="important",
            entity_ids=[ev["id"]],
            payload={"title": "\n".join(lines[:1]), "reason": lines[1:]},
            dedupe_key=f"news-alert:{ev['id']}",
        )


def ftmo_news_compliance_enabled(env: RuntimeEnv) -> bool:
    """Return whether funded-Standard FTMO news restrictions apply."""
    return (
        env.account_profile.strip().lower().startswith("ftmo")
        and env.ftmo_phase.strip().lower() == "funded"
        and env.ftmo_account_type.strip().lower() == "standard"
    )


def ftmo_news_guard_state(
    conn: Connection,
    env: RuntimeEnv,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Return stale-calendar or active restricted-event guard state."""
    if not ftmo_news_compliance_enabled(env):
        return None
    now = now or datetime.now(UTC)
    if not news_calendar_is_fresh(
        conn,
        now,
        max_age_hours=env.ftmo_news_calendar_max_age_hours,
    ):
        return {
            "id": "calendar-stale",
            "title": "FTMO economic calendar stale",
            "phase": "stale",
        }
    return active_ftmo_news_window(
        conn,
        now,
        buffer_minutes=env.ftmo_news_buffer_minutes,
    )


def queue_ftmo_news_guard_alert(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    broker_symbol: str,
    guard: dict[str, Any],
    now: datetime,
) -> None:
    """Alert without sending MT5 actions during hard restriction/stale data."""
    phase = str(guard["phase"])
    if phase == "cooldown":
        return
    if phase == "stale":
        title = "FTMO news calendar stale — automation frozen"
        reason = [
            f"No successful calendar refresh within {env.ftmo_news_calendar_max_age_hours} hours.",
            "New entries, dashboard close commands, partial TP and break-even management are paused.",
        ]
        dedupe_key = f"ftmo-news-calendar-stale:{env.account_label}:{now.date().isoformat()}"
    else:
        try:
            open_positions, pending_orders = client.bot_order_counts(broker_symbol, magic=env.mt5_magic)
        except Exception as exc:
            open_positions, pending_orders = -1, -1
            exposure_note = f"Exposure check failed: {exc}"
        else:
            exposure_note = f"Open bot positions: {open_positions}; pending bot orders: {pending_orders}."
        if open_positions == 0 and pending_orders == 0:
            return
        title = "FTMO restricted news window — no MT5 action sent"
        reason = [str(guard["title"]), exposure_note]
        dedupe_key = f"ftmo-news-hard-window:{env.account_label}:{guard['id']}"
    queue_alert(
        conn,
        account_label=env.account_label,
        symbol=config.symbol,
        timeframe=config.strategy.timeframe,
        event_type="execution_event",
        severity="critical",
        entity_ids=[str(guard["id"])],
        payload={"title": title, "outcome": "blocked", "reason": reason, "ftmo_news_guard": guard},
        dedupe_key=dedupe_key,
    )
    conn.commit()


def _upsert_news_regime(
    conn: Connection,
    config: AppConfig,
    blackout: dict[str, Any],
) -> None:
    """Push a bounded 'news' regime overlay without replacing the bot regime."""
    regime_tf = config.regime.timeframe
    ctx = MarketContext(
        symbol=config.symbol,
        timeframe=regime_tf,
        context_type="regime",
        bot_value="news",
        primary_value="news",
        secondary_value=str(blackout["title"]),
        bot_confidence=1.0,
        effective_value="news",
        effective_confidence=1.0,
        source="news_calendar",
        valid_from=str(blackout["blackout_from"]),
        valid_until=str(blackout["blackout_until"]),
        status="active",
        metadata={
            "news_event_id": blackout["id"],
            "news_title": blackout["title"],
            "tier": blackout["tier"],
            "blackout_from": blackout["blackout_from"],
            "blackout_until": blackout["blackout_until"],
        },
    )
    conn.execute(
        """
        INSERT INTO market_contexts (
            id, symbol, timeframe, context_type, bot_value, primary_value, secondary_value,
            bot_confidence, effective_value, effective_confidence, source,
            valid_from, valid_until, status, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            secondary_value = excluded.secondary_value,
            valid_from = excluded.valid_from,
            valid_until = excluded.valid_until,
            status = 'active',
            metadata_json = excluded.metadata_json,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            ctx.id,
            ctx.symbol,
            ctx.timeframe,
            ctx.context_type,
            ctx.bot_value,
            ctx.primary_value,
            ctx.secondary_value,
            ctx.bot_confidence,
            ctx.effective_value,
            ctx.effective_confidence,
            ctx.source,
            ctx.valid_from,
            ctx.valid_until,
            ctx.status,
            json.dumps(ctx.metadata, sort_keys=True),
        ),
    )
    conn.commit()


def _expire_news_regimes(conn: Connection, config: AppConfig, now: datetime) -> None:
    """Expire bounded news overlays once their blackout window has passed."""
    now_iso = now.replace(microsecond=0).isoformat()
    conn.execute(
        """
        UPDATE market_contexts
        SET status = 'expired', updated_at = CURRENT_TIMESTAMP
        WHERE symbol = ?
          AND timeframe = ?
          AND context_type = 'regime'
          AND source = 'news_calendar'
          AND status = 'active'
          AND valid_until IS NOT NULL
          AND valid_until <= ?
        """,
        (config.symbol, config.regime.timeframe, now_iso),
    )
    conn.commit()


def sync_mt5_candles(conn: Connection, config: AppConfig, client: MT5BrokerClient, broker_symbol: str) -> None:
    # broker_symbol is resolved once at startup and passed in — no redundant MT5 call.
    timeframe_counts = {config.bias.timeframe: 800, config.strategy.timeframe: 1200, "M5": 1800}
    for timeframe, count in timeframe_counts.items():
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
    conn: Connection,
    config: AppConfig,
    symbol: str,
    timeframe: str,
    new_ids: set[str],
    account_label: str,
) -> None:
    # M15 swing structure is still stored for trigger/debug data, but it is not
    # a trade-context signal. Only notify humans about the H1 context swings.
    if timeframe.upper() != config.bias.timeframe.upper():
        return
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
            account_label=account_label,
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


def run_live_detectors(conn: Connection, config: AppConfig, symbol: str, account_label: str) -> None:
    for timeframe in (config.bias.timeframe, config.strategy.timeframe):
        swing_config = config.swing_for(timeframe)
        before_ids = _load_swing_ids(conn, symbol, timeframe)
        detect_and_store_swing_structure(conn, symbol, timeframe, swing_config.window, swing_config.tolerance)
        after_ids = _load_swing_ids(conn, symbol, timeframe)
        new_ids = after_ids - before_ids
        if new_ids:
            _queue_new_swing_alerts(conn, config, symbol, timeframe, new_ids, account_label)
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
    for timeframe in (config.bias.timeframe,):
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
    if not env.live_run_detectors:
        return
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
            account_label=env.account_label,
            symbol=config.symbol,
            timeframe=zone["timeframe"],
            event_type="new_zone",
            severity="watch" if weight < 0.8 else "important",
            entity_ids=[zone["id"]],
            payload=payload,
            dedupe_key=f"new-zone:{zone['id']}",
        )


def queue_setup_alerts(conn: Connection, config: AppConfig, env: RuntimeEnv, candidates: list[dict[str, Any]]) -> None:
    # Setup geometry is shared by every account worker. Only the primary data
    # worker (LIVE_RUN_DETECTORS=true) announces it; each account still runs its
    # own risk checks and execution lifecycle alerts below this layer.
    if not env.live_run_detectors:
        return
    for candidate in candidates:
        if candidate.get("playbook") in {"manual_ai_v1", "h1_impulse_retest_v1"}:
            continue
        if candidate.get("status") not in {"eligible", "waiting_confirmation", "blocked"}:
            continue
        trigger_timeframe = str(candidate.get("timeframe") or config.strategy.timeframe).upper()
        context_timeframe = config.bias.timeframe.upper()
        status = str(candidate.get("status") or "")
        reasons = list(candidate.get("blocked_reason") or candidate.get("reason") or [])[:5]
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        zone_type = candidate.get("zone_type") or metadata.get("zone_type")
        payload = {
            "title": "Setup blocked" if status == "blocked" else "Setup candidate",
            "setup": {
                "id": candidate.get("id"),
                "playbook": candidate.get("playbook"),
                "direction": candidate.get("direction"),
                "zone_type": zone_type,
                "status": status,
                "entry": candidate.get("entry"),
                "stop_loss": candidate.get("stop_loss"),
                "take_profit": candidate.get("take_profit"),
                "order_type": metadata.get("order_type") or "market",
                "expires_at": candidate.get("expires_at") or metadata.get("limit_order_expires_at"),
                "context_timeframe": context_timeframe,
                "trigger_timeframe": trigger_timeframe,
            },
            "reason": reasons,
            "action": "Signal only; account workers still apply execution, position, spread, news, and risk gates.",
            "chart_url": env.chart_url_base,
        }
        queue_alert(
            conn,
            account_label=env.account_label,
            symbol=config.symbol,
            timeframe=context_timeframe,
            event_type="setup_candidate",
            severity="important" if status == "eligible" else "watch",
            entity_ids=[str(candidate.get("id"))],
            payload=payload,
            dedupe_key=f"setup:{candidate.get('id')}:{status}",
        )


def queue_m15_recovery_alert(conn: Connection, config: AppConfig, env: RuntimeEnv) -> bool:
    if not env.live_run_detectors:
        return False
    period = config.strategy.zone_reaction_v2_reject_avg_body_period
    threshold = config.strategy.zone_reaction_v2_reject_recovery_min_avg_body_ratio
    rows = conn.execute(
        """
        SELECT open_time, close_time, open, high, low, close
        FROM candles
        WHERE symbol = ? AND timeframe = ?
        ORDER BY open_time DESC
        LIMIT ?
        """,
        (config.symbol, config.strategy.timeframe, period + 1),
    ).fetchall()
    if len(rows) != period + 1:
        return False
    candles = [dict(row) for row in reversed(rows)]
    bullish = close_extreme_recovery_metrics(candles, "long", period, threshold)
    bearish = close_extreme_recovery_metrics(candles, "short", period, threshold)
    directions = [
        direction
        for direction, metrics in (("bullish", bullish), ("bearish", bearish))
        if metrics.passed
    ]
    if not directions:
        return False
    trigger = candles[-1]
    return queue_alert(
        conn,
        account_label=env.account_label,
        symbol=config.symbol,
        timeframe=config.strategy.timeframe,
        event_type="m15_recovery",
        severity="important",
        entity_ids=[str(trigger["open_time"])],
        payload={
            "account": env.account_label,
            "recovery": {
                "directions": directions,
                "close": round(float(trigger["close"]), 5),
                "event_time": str(trigger["close_time"]),
                "bullish_ratio": round(bullish.ratio, 4) if bullish.passed else None,
                "bearish_ratio": round(bearish.ratio, 4) if bearish.passed else None,
                "minimum_ratio": threshold,
                "average_body": round(bullish.average_body, 5),
            },
        },
        dedupe_key=f"m15-recovery:{env.account_label}:{config.symbol}:{trigger['close_time']}",
    )


def queue_h1_impulse_body_alert(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    signal_open_time: str | None = None,
) -> bool:
    """Classify and notify once when a closed H1 qualifies for a chart star."""
    if not env.live_run_detectors:
        return False
    period = config.strategy.h1_impulse_retest_v1_atr_period
    rows = conn.execute(
        """
        SELECT open_time, close_time, open, high, low, close
        FROM candles
        WHERE symbol = ? AND timeframe = 'H1' AND close_time <= ?
          AND (? IS NULL OR open_time <= ?)
        ORDER BY open_time DESC
        LIMIT ?
        """,
        (config.symbol, utc_now_iso(), signal_open_time, signal_open_time, period + 2),
    ).fetchall()
    if len(rows) < period:
        return False
    candles = [dict(row) for row in reversed(rows)]
    atr = latest_atr(
        [
            CandleSlice(
                open_time=str(candle["open_time"]),
                open=float(candle["open"]),
                high=float(candle["high"]),
                low=float(candle["low"]),
                close=float(candle["close"]),
            )
            for candle in candles
        ],
        period=period,
    )
    if atr is None or atr <= 0:
        return False
    signal = candles[-1]
    body = abs(float(signal["close"]) - float(signal["open"]))
    body_atr = body / atr
    minimum = config.strategy.h1_impulse_retest_v1_min_body_atr
    if body_atr < minimum:
        return False
    preview_config = h1_impulse_preview_config_from_strategy(config.strategy)
    normalized_candles = [
        {
            "time": str(candle["open_time"]),
            "close_time": str(candle["close_time"]),
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
        }
        for candle in candles
    ]
    preview = build_h1_impulse_preview(
        signal=normalized_candles[-1],
        previous=normalized_candles[-2],
        atr=float(atr),
        reference_price=float(signal["close"]),
        config=preview_config,
    )
    classification = "eligible" if preview["status"] == "eligible" else "needs_review"
    dedupe_key = f"h1-impulse:{config.symbol}:{signal['close_time']}"
    return queue_system_alert(
        conn,
        account_label=env.account_label,
        symbol=config.symbol,
        timeframe="H1",
        event_type="h1_impulse_signal",
        severity="important",
        entity_ids=[str(signal["open_time"])],
        payload={
            "classification": classification,
            "direction": preview["direction"],
            "body": preview["signal"]["body"],
            "body_atr_ratio": preview["signal"]["body_atr_ratio"],
            "range_atr_ratio": preview["signal"]["range_atr_ratio"],
            "body_range_ratio": preview["signal"]["body_range_ratio"],
            "entry_source": preview["entry_source"],
            "expiry_hours": preview["expiry_hours"],
            "blocked_reason": preview["blocked_reason"],
            "ohlc": preview["signal"],
            "chart_url": env.chart_url_base,
        },
        dedupe_key=dedupe_key,
    )


def queue_new_h1_impulse_alert(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    state: LiveWorkerState,
) -> bool:
    latest_h1 = latest_closed_candle_time(conn, config.symbol, "H1")
    if latest_h1 is None:
        return False
    if state.last_closed_h1 is None:
        # Direct/test callers may not have run the startup baseline. Do not
        # treat an arbitrary historical candle as a newly closed H1.
        state.last_closed_h1 = latest_h1
        return False
    if latest_h1 == state.last_closed_h1:
        return False
    queued = queue_h1_impulse_body_alert(conn, config, env, signal_open_time=latest_h1)
    state.last_closed_h1 = latest_h1
    return queued


def queue_manual_ai_lifecycle_alert(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    row: Any,
    status: str,
) -> bool:
    normalized_status = status.lower()
    if normalized_status != "expired":
        return False
    playbook, entry_source = plan_playbook_and_entry_source(row)
    return queue_alert(
        conn,
        account_label=env.account_label,
        symbol=config.symbol,
        timeframe=config.strategy.timeframe,
        event_type="execution_event",
        severity="critical" if normalized_status == "filled" else "important",
        entity_ids=[str(row["id"])],
        payload={
            "title": f"{playbook} limit {normalized_status}",
            "outcome": normalized_status,
            "account": env.account_label,
            "direction": "long" if row["side"] == "buy" else "short",
            "entry": float(row["entry_price"]),
            "stop_loss": float(row["stop_loss"]),
            "take_profit": [float(row["take_profit"])],
            "entry_source": entry_source,
        },
        dedupe_key=f"manual-ai-lifecycle:{env.account_label}:{row['id']}:{normalized_status}",
    )


def mark_manual_ai_filled(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    row: Any,
    linked_order: Any | None,
    now_iso: str,
) -> None:
    if linked_order is not None:
        mark_pending_order_filled(
            conn,
            config,
            env,
            str(linked_order["id"]),
            opened_at=now_iso,
        )
        return
    conn.execute(
        "UPDATE manual_ai_plans SET status = 'filled', updated_at = ? WHERE id = ?",
        (now_iso, row["id"]),
    )
    conn.commit()


def plan_playbook_and_entry_source(row: Any, replacement: dict[str, Any] | None = None) -> tuple[str, str]:
    raw_payload = json.loads(row["raw_payload_json"] or "{}")
    playbook = str(raw_payload.get("playbook") or "manual_ai_v1")
    candidates = raw_payload.get("candidates") if isinstance(raw_payload, dict) else []
    raw_candidate = next(
        (
            candidate
            for candidate in (candidates if isinstance(candidates, list) else [])
            if isinstance(candidate, dict) and str(candidate.get("client_id")) == str(row["client_id"])
        ),
        {},
    )
    entry_source = str((replacement or {}).get("entry_source") or raw_candidate.get("entry_source") or "strategy_calculated")
    return playbook, entry_source


def payload_with_plan_entry_source(row: Any, entry_source: str, target_mode: str | None = None) -> str:
    raw_payload = json.loads(row["raw_payload_json"] or "{}")
    candidates = raw_payload.get("candidates") if isinstance(raw_payload, dict) else []
    for candidate in (candidates if isinstance(candidates, list) else []):
        if isinstance(candidate, dict) and str(candidate.get("client_id")) == str(row["client_id"]):
            candidate["entry_source"] = entry_source
            candidate["entry_reason"] = f"Human selected entry source: {entry_source}"
    market_context = raw_payload.get("market_context") if isinstance(raw_payload, dict) else None
    if target_mode and isinstance(market_context, dict):
        market_context["target_mode"] = target_mode
    return json.dumps(raw_payload, sort_keys=True)


def process_manual_ai_plans(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    broker_symbol: str,
    now: datetime,
) -> None:
    """Advance approved Manual AI drafts without trusting client-provided lot size."""
    rows = conn.execute(
        """
        SELECT * FROM manual_ai_plans
        WHERE account_label = ? AND symbol = ?
                    AND status IN ('approved', 'arming', 'armed', 'cancel_requested', 'replace_requested')
        ORDER BY created_at ASC
        """,
        (env.account_label, config.symbol),
    ).fetchall()
    if not rows:
        return

    now_iso = now.isoformat()
    for row in rows:
        plan_id = str(row["id"])
        trade_idea_id = row["trade_idea_id"]
        plan_status = str(row["status"])
        plan_playbook, _entry_source_for_cancel_rules = plan_playbook_and_entry_source(row)
        linked_order = None
        if trade_idea_id:
            linked_order = conn.execute(
                "SELECT id, status FROM trade_orders WHERE trade_idea_id = ? AND account_label = ? ORDER BY created_at DESC LIMIT 1",
                (trade_idea_id, env.account_label),
            ).fetchone()
        request = None
        if row["execution_request_id"]:
            request = conn.execute(
                "SELECT broker_order_id FROM execution_requests WHERE id = ?",
                (row["execution_request_id"],),
            ).fetchone()
        ticket = str(request["broker_order_id"] or "") if request else ""

        # A limit-order acknowledgement is not a fill acknowledgement. Reconcile
        # the exact broker ticket on every poll and never infer cancellation merely
        # because the ticket is absent from the open-position list.
        if linked_order is not None and str(linked_order["status"]) == "pending_fill" and ticket:
            broker_state = client.get_pending_order_state(broker_symbol, order_ticket=ticket)
            if broker_state == "filled":
                plan_status = "filled"
                mark_manual_ai_filled(conn, config, env, row, linked_order, now_iso)
            elif broker_state == "cancelled" and plan_status != "replace_requested":
                expires_at = datetime.fromisoformat(str(row["expires_at"]))
                plan_status = "expired" if expires_at <= now else "cancelled"
                conn.execute(
                    "UPDATE trade_orders SET status = 'cancelled', closed_at = ?, updated_at = ? WHERE id = ? AND status = 'pending_fill'",
                    (now_iso, now_iso, linked_order["id"]),
                )
                conn.execute("UPDATE manual_ai_plans SET status = ?, updated_at = ? WHERE id = ?", (plan_status, now_iso, plan_id))
                conn.commit()
                queue_manual_ai_lifecycle_alert(conn, config, env, row, plan_status)

        if linked_order is not None:
            order_status = str(linked_order["status"])
            mapped = {"pending_fill": "armed", "filled": "filled", "closed": "closed", "cancelled": "cancelled"}.get(order_status)
            # A user-requested cancellation must remain authoritative while the
            # broker order is still pending. Mapping pending_fill back to armed
            # here would skip the broker cancellation branch below and make the
            # limit reappear in the UI on the next refresh.
            if mapped and plan_status not in {"filled", "expired", "cancelled", "cancel_requested", "replace_requested"} and mapped != plan_status:
                conn.execute("UPDATE manual_ai_plans SET status = ?, updated_at = ? WHERE id = ?", (mapped, now_iso, plan_id))
                plan_status = mapped
                conn.commit()

        if plan_status == "replace_requested":
            replacement = json.loads(row["replacement_levels_json"] or "{}")
            required = {"entry_price", "stop_loss", "take_profit", "risk_reward"}
            if not required.issubset(replacement):
                logger.error("Manual AI replacement payload is incomplete plan=%s", plan_id)
                continue
            broker_state = client.get_pending_order_state(broker_symbol, order_ticket=ticket) if ticket else None
            if broker_state == "filled":
                mark_manual_ai_filled(conn, config, env, row, linked_order, now_iso)
                continue
            replacement_entry = float(replacement["entry_price"])
            current_price = float(client.current_price_for_side(broker_symbol, str(row["side"])))
            valid_limit_side = (
                replacement_entry < current_price
                if str(row["side"]) == "buy"
                else replacement_entry > current_price
            )
            if not valid_limit_side:
                message = (
                    f"Replacement {row['side']} limit entry {replacement_entry:.2f} is on the wrong side "
                    f"of broker price {current_price:.2f}; old ticket kept"
                )
                logger.warning("Manual AI %s plan=%s", message, plan_id)
                conn.execute(
                    """
                    UPDATE manual_ai_plans
                    SET status = 'armed', replacement_levels_json = '{}', replacement_error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (message, now_iso, plan_id),
                )
                conn.commit()
                continue
            if broker_state == "pending":
                try:
                    client.cancel_pending_order(broker_symbol, order_ticket=ticket, comment="Manual AI replace")
                except Exception as exc:
                    logger.warning("Manual AI replace cancel failed plan=%s: %s", plan_id, exc)
                    continue
            elif broker_state is None:
                # Never replace until MT5 proves the old ticket did not fill.
                continue
            if linked_order is not None:
                conn.execute(
                    "UPDATE trade_orders SET status = 'cancelled', closed_at = ?, updated_at = ? WHERE id = ? AND status = 'pending_fill'",
                    (now_iso, now_iso, linked_order["id"]),
                )
            if row["execution_request_id"]:
                conn.execute(
                    "UPDATE execution_requests SET status = 'cancelled', updated_at = ? WHERE id = ? AND status IN ('pending', 'sent')",
                    (now_iso, row["execution_request_id"]),
                )
            if trade_idea_id:
                conn.execute(
                    """
                    UPDATE trade_ideas
                    SET suggested_entry = ?, suggested_stop_loss = ?, suggested_take_profit_json = ?,
                        risk_reward = ?
                    WHERE id = ?
                    """,
                    (
                        float(replacement["entry_price"]),
                        float(replacement["stop_loss"]),
                        json.dumps([float(replacement["take_profit"])]),
                        float(replacement["risk_reward"]),
                        trade_idea_id,
                    ),
                )
            cancel_conditions = json.loads(row["cancel_conditions_json"] or "[]")
            for condition in cancel_conditions:
                if condition.get("price") is None:
                    continue
                if abs(float(condition["price"]) - float(row["stop_loss"])) <= 1e-9:
                    condition["price"] = float(replacement["stop_loss"])
            partial_take_profit = json.loads(row["partial_take_profit_json"] or "{}")
            if replacement.get("partial_take_profit_enabled") is not None:
                partial_take_profit["enabled"] = bool(replacement["partial_take_profit_enabled"])
            conn.execute(
                """
                UPDATE manual_ai_plans
                SET status = 'approved', entry_price = ?, stop_loss = ?, take_profit = ?,
                    risk_reward = ?, expires_at = ?, replacement_levels_json = '{}',
                    replacement_error = NULL, cancel_conditions_json = ?, raw_payload_json = ?,
                    partial_take_profit_json = ?,
                    trade_idea_id = NULL, execution_request_id = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    float(replacement["entry_price"]),
                    float(replacement["stop_loss"]),
                    float(replacement["take_profit"]),
                    float(replacement["risk_reward"]),
                    str(replacement.get("expires_at") or row["expires_at"]),
                    json.dumps(cancel_conditions, sort_keys=True),
                    payload_with_plan_entry_source(
                        row,
                        str(replacement.get("entry_source") or "human_custom"),
                        str(replacement.get("target_mode")) if replacement.get("target_mode") else None,
                    ),
                    json.dumps(partial_take_profit, sort_keys=True),
                    now_iso,
                    plan_id,
                ),
            )
            conn.commit()
            # Re-arm on the next poll. This creates a clean broker request and
            # recalculates volume from the new structural SL.
            continue

        if plan_status == "cancel_requested":
            broker_state = client.get_pending_order_state(broker_symbol, order_ticket=ticket) if ticket else None
            if broker_state == "filled":
                mark_manual_ai_filled(conn, config, env, row, linked_order, now_iso)
                continue
            if broker_state == "pending":
                try:
                    client.cancel_pending_order(broker_symbol, order_ticket=ticket, comment="Manual AI cancel")
                except Exception as exc:
                    logger.warning("Manual AI cancel failed plan=%s: %s", plan_id, exc)
                    continue
            elif broker_state is None:
                # MT5 can expose history one poll later. Keep the request pending;
                # guessing here could mark an already-filled live position cancelled.
                continue
            conn.execute("UPDATE manual_ai_plans SET status = 'cancelled', updated_at = ? WHERE id = ?", (now_iso, plan_id))
            if trade_idea_id:
                conn.execute(
                    "UPDATE trade_orders SET status = 'cancelled', closed_at = ?, updated_at = ? WHERE trade_idea_id = ? AND status = 'pending_fill'",
                    (now_iso, now_iso, trade_idea_id),
                )
            conn.commit()
            continue

        if plan_status not in {"approved", "armed"}:
            continue
        expires_at = datetime.fromisoformat(str(row["expires_at"]))
        if expires_at <= now:
            if plan_status == "armed":
                broker_state = client.get_pending_order_state(broker_symbol, order_ticket=ticket) if ticket else None
                if broker_state == "filled":
                    mark_manual_ai_filled(conn, config, env, row, linked_order, now_iso)
                    continue
                if broker_state == "pending":
                    try:
                        client.cancel_pending_order(broker_symbol, order_ticket=ticket, comment="Manual AI expired")
                    except Exception as exc:
                        logger.warning("Manual AI expiry cancel failed plan=%s: %s", plan_id, exc)
                        continue
                elif broker_state is None:
                    continue
                if linked_order is not None:
                    conn.execute(
                        "UPDATE trade_orders SET status = 'cancelled', closed_at = ?, updated_at = ? WHERE id = ? AND status = 'pending_fill'",
                        (now_iso, now_iso, linked_order["id"]),
                    )
            conn.execute("UPDATE manual_ai_plans SET status = 'expired', updated_at = ? WHERE id = ?", (now_iso, plan_id))
            conn.commit()
            queue_manual_ai_lifecycle_alert(conn, config, env, row, "expired")
            continue

        # M5 is a hard execution dependency for this short-horizon playbook.
        latest_m5 = conn.execute(
            "SELECT close_time, close FROM candles WHERE symbol = ? AND timeframe = 'M5' ORDER BY open_time DESC LIMIT 1",
            (config.symbol,),
        ).fetchone()
        if latest_m5 is None:
            continue
        latest_m5_close = datetime.fromisoformat(str(latest_m5["close_time"]))
        if now - latest_m5_close > timedelta(minutes=15):
            continue

        cancel_conditions = json.loads(row["cancel_conditions_json"] or "[]")
        latest_m15 = conn.execute(
            "SELECT close FROM candles WHERE symbol = ? AND timeframe = 'M15' ORDER BY open_time DESC LIMIT 1",
            (config.symbol,),
        ).fetchone()
        current_price = float(client.current_price_for_side(broker_symbol, "buy" if row["side"] == "buy" else "sell"))
        cancelled_reason: str | None = None
        for condition in cancel_conditions:
            condition_type = str(condition.get("type") or "")
            if plan_playbook == "h1_impulse_retest_v1" and condition_type == "price_reached_target_without_fill":
                # H1 Impulse revalidation is advisory after trader approval. A
                # historical/current TP touch before fill is still visible in
                # the saved revalidation audit, but it must not silently delete
                # a discretionary H1 limit before MT5 sees it.
                continue
            condition_price = condition.get("price")
            close_value = float(latest_m5["close"]) if condition_type.startswith("m5_") else float(latest_m15["close"]) if latest_m15 else None
            if condition_type.endswith("close_below") and condition_price is not None and close_value is not None and close_value < float(condition_price):
                cancelled_reason = condition_type
            elif condition_type.endswith("close_above") and condition_price is not None and close_value is not None and close_value > float(condition_price):
                cancelled_reason = condition_type
            elif condition_type == "price_reached_target_without_fill":
                if (row["side"] == "buy" and current_price >= float(row["take_profit"])) or (row["side"] == "sell" and current_price <= float(row["take_profit"])):
                    cancelled_reason = condition_type
            elif condition_type == "news_blackout_started" and active_news_blackout(conn, now):
                cancelled_reason = condition_type
            if cancelled_reason:
                break
        if cancelled_reason:
            if plan_status == "armed":
                broker_state = client.get_pending_order_state(broker_symbol, order_ticket=ticket) if ticket else None
                if broker_state == "filled":
                    mark_manual_ai_filled(conn, config, env, row, linked_order, now_iso)
                    continue
                if broker_state == "pending":
                    try:
                        client.cancel_pending_order(broker_symbol, order_ticket=ticket, comment=f"Manual AI {cancelled_reason}")
                    except Exception as exc:
                        logger.warning("Manual AI invalidation cancel failed plan=%s: %s", plan_id, exc)
                        continue
                elif broker_state is None:
                    continue
                if linked_order is not None:
                    conn.execute(
                        "UPDATE trade_orders SET status = 'cancelled', closed_at = ?, updated_at = ? WHERE id = ? AND status = 'pending_fill'",
                        (now_iso, now_iso, linked_order["id"]),
                    )
            conn.execute("UPDATE manual_ai_plans SET status = 'cancelled', updated_at = ? WHERE id = ?", (now_iso, plan_id))
            conn.commit()
            continue

        if plan_status == "armed":
            continue

        try:
            open_bot_positions, _pending_bot_orders = client.bot_order_counts(broker_symbol, magic=env.mt5_magic)
        except AttributeError:
            open_bot_positions = 0
        if open_bot_positions >= env.max_open_positions_per_symbol:
            # Pending limits are plans, not live risk yet. Capacity only gates
            # already-filled positions; this allows the trader to stage
            # multiple limit ideas while still capping concurrent open risk.
            continue

        partial = json.loads(row["partial_take_profit_json"] or "{}")
        plan_playbook, entry_source = plan_playbook_and_entry_source(row)
        candidate = {
            "id": plan_id,
            "playbook": plan_playbook,
            "status": "eligible",
            "score": 1.0,
            "direction": "long" if row["side"] == "buy" else "short",
            "entry": float(row["entry_price"]),
            "stop_loss": float(row["stop_loss"]),
            "take_profit": [float(row["take_profit"])],
            "risk_reward": float(row["risk_reward"]),
            "expires_at": row["expires_at"],
            "metadata": {
                "order_type": "limit",
                "entry_model": entry_source,
                "entry_source": entry_source,
                "partial_take_profit": partial,
                "cancel_conditions": cancel_conditions,
            },
        }
        maybe_execute_candidates(
            conn,
            config,
            env,
            client,
            [candidate],
            broker_symbol,
            risk_pct_override=manual_ai_risk_pct(env.account_profile),
        )
        idea_id = live_trade_idea_id(plan_id, account_label=env.account_label)
        execution = conn.execute(
            "SELECT id, status FROM execution_requests WHERE trade_idea_id = ? ORDER BY created_at DESC LIMIT 1",
            (idea_id,),
        ).fetchone()
        if execution is not None:
            plan_status = "armed" if execution["status"] == "sent" else "rejected" if execution["status"] == "failed" else "arming"
            conn.execute(
                """
                UPDATE manual_ai_plans
                SET status = ?, trade_idea_id = ?, execution_request_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (plan_status, idea_id, execution["id"], now_iso, plan_id),
            )
            conn.commit()


def maybe_execute_candidates(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    candidates: list[dict[str, Any]],
    broker_symbol: str,
    risk_pct_override: float | None = None,
) -> None:
    if not account_execution_is_enabled(conn, env):
        return
    now = datetime.now(UTC)
    ftmo_news_guard = ftmo_news_guard_state(conn, env, now)
    if ftmo_news_guard is not None:
        logger.warning(
            "maybe_execute_candidates: FTMO news guard phase=%s '%s' — skipping execution",
            ftmo_news_guard["phase"],
            ftmo_news_guard["title"],
        )
        return
    if is_weekend_no_new_trade_window(env, now):
        logger.warning("maybe_execute_candidates: weekend cutoff active — skipping execution")
        return
    # Bug #5: broker_symbol is resolved at startup; if resolution failed the
    # string is empty.  Executing against an empty symbol would query wrong
    # prices and place orders on a random/default instrument.
    if not broker_symbol:
        logger.warning("maybe_execute_candidates: broker_symbol is empty — skipping execution")
        return
    # News blackout guard: skip execution during tier-1/2 news windows.
    # The candidate stays eligible and will retry on the next poll once the
    # blackout window expires. Spread guard below provides a secondary check
    # for unexpected volatility outside defined windows.
    blackout = active_news_blackout(conn, now)
    if blackout:
        tier = blackout["tier"]
        logger.warning(
            "maybe_execute_candidates: news blackout tier=%d '%s' — skipping cycle",
            tier,
            blackout["title"],
        )
        return
    # Spread guard: wide spreads (e.g. during news) mean any fill will be at a
    # significantly worse price than the signal. Skip the whole cycle and retry
    # on the next poll; the candidate stays eligible and drift logic handles any
    # price movement that occurred during the wait.
    if env.max_spread_price > 0:
        current_spread = client.get_current_spread(broker_symbol)
        if current_spread > env.max_spread_price:
            logger.warning(
                "maybe_execute_candidates: spread=%.2f > max=%.2f — skipping cycle",
                current_spread,
                env.max_spread_price,
            )
            return
    eligible = [candidate for candidate in candidates if candidate.get("status") == "eligible"]
    eligible = candidates_after_live_fvg_trade_count(
        conn,
        config.symbol,
        eligible,
        config.strategy.zone_reaction_v2_fvg_max_trades_per_zone,
        account_label=env.account_label,
    )
    if not eligible:
        return
    candidate = sorted(eligible, key=lambda item: float(item.get("score") or 0.0), reverse=True)[0]
    if live_candidate_already_executed(conn, str(candidate["id"]), account_label=env.account_label):
        return
    open_positions = client.positions_count(broker_symbol)
    if open_positions >= env.max_open_positions_per_symbol:
        queue_execution_gate_block(
            conn,
            config,
            env,
            candidate,
            reason_code="position_limit",
            reason=(
                f"Existing {config.symbol} position: {open_positions}/{env.max_open_positions_per_symbol}. "
                "No broker order was created."
            ),
        )
        return
    trades_today = live_trade_count_today(conn, config.symbol, account_label=env.account_label)
    if trades_today >= env.max_trades_per_day:
        queue_execution_gate_block(
            conn,
            config,
            env,
            candidate,
            reason_code="daily_trade_limit",
            reason=(
                f"Daily live trade limit reached: {trades_today}/{env.max_trades_per_day}. "
                "No broker order was created."
            ),
        )
        return
    try:
        pricing_plan = build_execution_pricing_plan(client, broker_symbol, candidate, env.max_entry_drift_price)
    except Exception as exc:
        queue_alert(
            conn,
            account_label=env.account_label,
            symbol=config.symbol,
            timeframe=config.strategy.timeframe,
            event_type="execution_event",
            severity="critical",
            entity_ids=[str(candidate.get("id"))],
            payload={"title": "Trade pricing failed", "outcome": "failed", "reason": [str(exc)]},
            dedupe_key=f"pricing-failed:{candidate.get('id')}:{datetime.now(UTC).date().isoformat()}",
        )
        return
    # Risk check: compute lot size and verify daily loss limit. Zone Reaction V2
    # deliberately uses the same reduced profile risk as human-approved plans;
    # other automated playbooks keep the account-level/default risk policy.
    selected_risk_pct = risk_pct_override
    if selected_risk_pct is None:
        selected_risk_pct = (
            zone_reaction_v2_risk_pct(env.account_profile)
            if str(candidate.get("playbook") or "") == "zone_reaction_v2"
            else env.risk_per_trade_pct
        )
    risk_manager = build_risk_manager(
        client,
        env.account_profile,
        selected_risk_pct,
        env.account_balance_scale,
    )
    assessment = risk_manager.assess_trade(
        conn=conn,
        symbol=config.symbol,
        entry=pricing_plan.entry_price,
        stop_loss=pricing_plan.stop_loss,
        broker_symbol=broker_symbol,
        account_label=env.account_label,
    )
    if not assessment.allowed:
        queue_alert(
            conn,
            account_label=env.account_label,
            symbol=config.symbol,
            timeframe=config.strategy.timeframe,
            event_type="execution_event",
            severity="important",
            entity_ids=[str(candidate.get("id"))],
            payload={
                "title": "Trade blocked by risk manager",
                "outcome": "blocked",
                "reason": [assessment.reason],
                "setup": {"playbook": candidate.get("playbook"), "direction": candidate.get("direction")},
            },
            dedupe_key=f"risk-block:{candidate.get('id')}:{datetime.now(UTC).date().isoformat()}",
        )
        return
    execute_candidate(
        conn,
        config,
        env,
        client,
        candidate,
        broker_symbol,
        lot_size=assessment.lot_size,
        pricing_plan=pricing_plan,
    )


def queue_execution_gate_block(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    candidate: dict[str, Any],
    *,
    reason_code: str,
    reason: str,
) -> bool:
    """Persist and announce an account-specific execution gate without a fake trade."""
    return queue_alert(
        conn,
        account_label=env.account_label,
        symbol=config.symbol,
        timeframe=config.strategy.timeframe,
        event_type="execution_event",
        severity="important",
        entity_ids=[str(candidate.get("id"))],
        payload={
            "title": "Execution blocked",
            "outcome": "blocked",
            "reason_code": reason_code,
            "setup": {
                "playbook": candidate.get("playbook"),
                "direction": candidate.get("direction"),
                "entry": candidate.get("entry"),
                "stop_loss": candidate.get("stop_loss"),
                "take_profit": candidate.get("take_profit"),
            },
            "reason": [reason],
            "chart_url": env.chart_url_base,
        },
        dedupe_key=f"execution-block:{env.account_label}:{candidate.get('id')}:{reason_code}",
    )


def manual_ai_risk_pct(account_profile: str) -> float:
    """Return the playbook-specific risk for a Manual AI order."""
    if account_profile in {"ftmo_challenge", "the5ers"}:
        return 0.75
    return 1.5


def zone_reaction_v2_risk_pct(account_profile: str) -> float:
    """Return the reduced profile risk reserved for Zone Reaction V2."""
    return manual_ai_risk_pct(account_profile)


def maybe_ftmo_news_flatten(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    broker_symbol: str,
    guard: dict[str, Any],
) -> bool:
    """Flatten bot-owned exposure before FTMO's exact restricted window."""
    if (
        not env.execution_enabled
        or not env.ftmo_news_flatten_enabled
        or not broker_symbol
        or guard.get("phase") != "prepare"
    ):
        return False

    cancelled: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        cancelled = client.cancel_pending_orders(
            broker_symbol,
            magic=env.mt5_magic,
            comment="FTMO news flatten",
        )
    except Exception as exc:
        logger.exception("FTMO news pending-order cancellation failed")
        errors.append(f"Pending-order cancellation failed: {exc}")
    try:
        closed = client.close_open_positions(
            broker_symbol,
            magic=env.mt5_magic,
            comment="FTMO news flatten",
        )
    except Exception as exc:
        logger.exception("FTMO news position close failed")
        errors.append(f"Position close failed: {exc}")

    if cancelled:
        _mark_live_pending_orders_cancelled(conn, config.symbol, env.account_label, utc_now_iso())
    if closed:
        sync_closed_positions(conn, config, env, client, broker_symbol)

    did_anything = bool(cancelled or closed)
    if did_anything or errors:
        success_lines = [
            f"Event: {guard['title']}",
            f"Cancelled pending bot orders: {len(cancelled)}",
            f"Closed bot positions: {len(closed)}",
        ]
        queue_alert(
            conn,
            account_label=env.account_label,
            symbol=config.symbol,
            timeframe=config.strategy.timeframe,
            event_type="execution_event",
            severity="critical" if errors else "important",
            entity_ids=[str(guard["id"])],
            payload={
                "title": "FTMO news flatten failed" if errors else "FTMO news flatten completed",
                "outcome": "failed" if errors else "info",
                "reason": success_lines + errors,
                "ftmo_news_guard": guard,
            },
            dedupe_key=f"ftmo-news-flatten:{env.account_label}:{guard['id']}:{'failed' if errors else 'done'}",
        )
        conn.commit()
    return did_anything and not errors


def maybe_weekend_flatten(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    broker_symbol: str,
    now: datetime | None = None,
) -> bool:
    """Flatten every position and pending order for this account's symbol."""
    if not env.execution_enabled or not env.weekend_flatten_enabled or not broker_symbol:
        return False
    now = now or datetime.now(UTC)
    if not is_weekend_flatten_window(env, now):
        return False

    action_date = _local_datetime(env, now).date().isoformat()
    cancelled: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        cancelled = client.cancel_pending_orders(broker_symbol, magic=None, comment="Friday flatten")
    except Exception as exc:
        logger.exception("Weekend pending-order cancellation failed")
        errors.append(f"Pending-order cancellation failed: {exc}")
    try:
        closed = client.close_open_positions(broker_symbol, magic=None, comment="Friday flatten")
    except Exception as exc:
        logger.exception("Weekend position close failed")
        errors.append(f"Position close failed: {exc}")

    did_anything = bool(cancelled or closed)
    if errors:
        queue_alert(
            conn,
            account_label=env.account_label,
            symbol=config.symbol,
            timeframe=config.strategy.timeframe,
            event_type="execution_event",
            severity="critical",
            entity_ids=[],
            payload={
                "title": "Weekend flatten incomplete",
                "outcome": "failed",
                "reason": [
                    f"Cancelled pending orders: {len(cancelled)}",
                    f"Closed positions: {len(closed)}",
                    *errors,
                ],
            },
            dedupe_key=f"weekend-flatten-failed:{env.account_label}:{config.symbol}:{action_date}",
        )

    if cancelled:
        _mark_live_pending_orders_cancelled(conn, config.symbol, env.account_label, utc_now_iso())
    if closed:
        sync_closed_positions(conn, config, env, client, broker_symbol)

    if did_anything and not errors:
        queue_alert(
            conn,
            account_label=env.account_label,
            symbol=config.symbol,
            timeframe=config.strategy.timeframe,
            event_type="execution_event",
            severity="critical",
            entity_ids=[],
            payload={
                "title": "Weekend flatten completed",
                "outcome": "info",
                "reason": [
                    f"Cancelled pending orders: {len(cancelled)}",
                    f"Closed positions: {len(closed)}",
                ],
            },
            dedupe_key=f"weekend-flatten:{env.account_label}:{config.symbol}:{action_date}",
        )
    if did_anything or errors:
        conn.commit()
    return did_anything and not errors


def _mark_live_pending_orders_cancelled(conn: Connection, symbol: str, account_label: str, now: str) -> None:
    conn.execute(
        """
        UPDATE trade_orders
        SET status = 'cancelled',
            closed_at = COALESCE(closed_at, ?),
            updated_at = ?
        WHERE symbol = ?
          AND account_label = ?
          AND source = 'live'
          AND status = 'pending_fill'
        """,
        (now, now, symbol, account_label),
    )


def is_weekend_no_new_trade_window(env: RuntimeEnv, now: datetime | None = None) -> bool:
    if not env.weekend_flatten_enabled:
        return False
    local_now = _local_datetime(env, now or datetime.now(UTC))
    cutoff = _parse_hhmm(env.weekend_no_new_trades_time, "12:00")
    return _is_weekend_risk_window(local_now, cutoff)


def is_weekend_flatten_window(env: RuntimeEnv, now: datetime | None = None) -> bool:
    if not env.weekend_flatten_enabled:
        return False
    local_now = _local_datetime(env, now or datetime.now(UTC))
    cutoff = _parse_hhmm(env.weekend_flatten_time, "15:30")
    return _is_weekend_risk_window(local_now, cutoff)


def _is_weekend_risk_window(local_now: datetime, cutoff: tuple[int, int]) -> bool:
    weekday = local_now.weekday()  # Monday=0, Friday=4
    if weekday == 4:
        return (local_now.hour, local_now.minute) >= cutoff
    if weekday == 5:
        return True
    if weekday == 6:
        return (local_now.hour, local_now.minute) < (17, 0)
    return False


def _local_datetime(env: RuntimeEnv, now: datetime) -> datetime:
    aware = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    try:
        local_tz = ZoneInfo(env.weekend_flatten_timezone)
    except ZoneInfoNotFoundError:
        if env.weekend_flatten_timezone == "America/New_York":
            logger.warning("System timezone database is missing America/New_York; using built-in New York DST rules")
            return _new_york_datetime(aware)
        logger.warning("Unknown WEEKEND_FLATTEN_TIMEZONE=%s; falling back to UTC", env.weekend_flatten_timezone)
        local_tz = UTC
    return aware.astimezone(local_tz)


def _new_york_datetime(now: datetime) -> datetime:
    """Convert an aware datetime to New York time without relying on system tzdata.

    Windows VPS hosts often do not ship the IANA timezone database that
    ZoneInfo("America/New_York") needs.  Using UTC as a fallback would trigger
    Friday flatten several hours early, so keep a small US DST fallback here.
    """
    utc_now = now.astimezone(UTC)
    year = utc_now.year
    dst_start = _nth_weekday_utc(year, month=3, weekday=6, occurrence=2, hour=7)
    dst_end = _nth_weekday_utc(year, month=11, weekday=6, occurrence=1, hour=6)
    offset_hours = -4 if dst_start <= utc_now < dst_end else -5
    return utc_now.astimezone(timezone(timedelta(hours=offset_hours), name="America/New_York"))


def _nth_weekday_utc(year: int, *, month: int, weekday: int, occurrence: int, hour: int) -> datetime:
    current = datetime(year, month, 1, hour, tzinfo=UTC)
    days_until_weekday = (weekday - current.weekday()) % 7
    day = 1 + days_until_weekday + (occurrence - 1) * 7
    return datetime(year, month, day, hour, tzinfo=UTC)


def _parse_hhmm(value: str, fallback: str) -> tuple[int, int]:
    raw = value or fallback
    try:
        hour_text, minute_text = raw.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (TypeError, ValueError):
        hour_text, minute_text = fallback.split(":", 1)
        return int(hour_text), int(minute_text)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        hour_text, minute_text = fallback.split(":", 1)
        return int(hour_text), int(minute_text)
    return hour, minute


def build_execution_pricing_plan(
    client: MT5BrokerClient,
    broker_symbol: str,
    candidate: dict[str, Any],
    max_entry_drift_price: float,
) -> ExecutionPricingPlan:
    signal_entry = float(candidate.get("entry") or 0.0)
    signal_stop = float(candidate.get("stop_loss") or 0.0)
    raw_take_profit = candidate.get("take_profit") or []
    signal_take_profit = [float(value) for value in raw_take_profit if value is not None]
    if signal_entry <= 0 or signal_stop <= 0 or not signal_take_profit:
        raise ValueError("candidate is missing entry, stop_loss, or take_profit")

    direction = str(candidate["direction"])
    side = "buy" if direction == "long" else "sell"
    current_price = client.current_price_for_side(broker_symbol, side)
    direction_sign = 1.0 if direction == "long" else -1.0
    drift = (current_price - signal_entry) * direction_sign
    adverse_drift = max(drift, 0.0)
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    requested_order_type = str(metadata.get("order_type") or "").lower()
    candidate_expires_at = candidate.get("expires_at") or metadata.get("limit_order_expires_at")

    entry_price = signal_entry
    stop_loss = signal_stop
    take_profit = signal_take_profit
    order_type = "market"
    drift_action = "market_favorable_or_flat"

    if requested_order_type == "limit":
        valid_limit_side = signal_entry < current_price if direction == "long" else signal_entry > current_price
        if not valid_limit_side:
            order_name = "BUY LIMIT" if direction == "long" else "SELL LIMIT"
            relation = "below" if direction == "long" else "above"
            raise ValueError(
                f"{order_name} entry {signal_entry:.2f} must be {relation} current broker price {current_price:.2f}"
            )
        order_type = "limit"
        drift_action = str(metadata.get("entry_model") or "limit_from_strategy")
    # Positive drift means price moved against the planned entry. Small adverse
    # drift is still marketable, but risk must be recalculated from the real
    # entry. Large adverse drift becomes a limit order at the original signal.
    elif max_entry_drift_price > 0 and adverse_drift > max_entry_drift_price:
        order_type = "limit"
        drift_action = "limit_after_adverse_drift"
    elif max_entry_drift_price > 0 and adverse_drift > 0:
        entry_price = current_price
        original_risk = abs(signal_entry - signal_stop)
        if original_risk <= 0:
            raise ValueError("candidate stop distance must be positive")
        stop_loss = entry_price - original_risk if direction == "long" else entry_price + original_risk
        # Reprice ALL TP levels, preserving each one's individual RR ratio.
        repriced_tps: list[float] = []
        for tp in signal_take_profit:
            tp_rr = abs(tp - signal_entry) / original_risk if original_risk > 0 else 2.0
            repriced_tp = (
                entry_price + original_risk * tp_rr
                if direction == "long"
                else entry_price - original_risk * tp_rr
            )
            repriced_tps.append(repriced_tp)
        take_profit = repriced_tps if repriced_tps else signal_take_profit
        drift_action = "market_repriced_adverse"

    return ExecutionPricingPlan(
        order_type=order_type,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        expires_at=str(candidate_expires_at) if candidate_expires_at else None,
        current_price=current_price,
        signal_entry=signal_entry,
        signal_stop_loss=signal_stop,
        signal_take_profit=signal_take_profit,
        drift=drift,
        adverse_drift=adverse_drift,
        drift_action=drift_action,
    )


def _candidate_rr(candidate: dict[str, Any], entry: float, stop_loss: float, take_profit: float) -> float:
    try:
        rr = float(candidate.get("risk_reward") or 0.0)
    except (TypeError, ValueError):
        rr = 0.0
    if rr > 0:
        return rr
    risk = abs(entry - stop_loss)
    if risk <= 0:
        return 2.0
    return max(abs(take_profit - entry) / risk, 0.1)


def execute_candidate(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    candidate: dict[str, Any],
    broker_symbol: str,
    lot_size: float | None = None,
    pricing_plan: ExecutionPricingPlan | None = None,
) -> dict[str, str] | None:
    if not account_execution_is_enabled(conn, env):
        return
    # lot_size from risk manager takes precedence; fall back to env fixed volume
    volume = lot_size if lot_size is not None else env.live_order_volume

    # Use repriced values from pricing_plan when available; fall back to raw
    # candidate signal values only if pricing_plan was somehow not built.
    if pricing_plan is not None:
        exec_entry = pricing_plan.entry_price
        exec_stop = pricing_plan.stop_loss
        exec_take_profit = pricing_plan.take_profit
        exec_order_type = pricing_plan.order_type
    else:
        exec_entry = float(candidate.get("entry") or 0)
        exec_stop_raw = candidate.get("stop_loss")
        if exec_stop_raw is None:
            return
        exec_stop = float(exec_stop_raw)
        raw_tp = candidate.get("take_profit") or []
        exec_take_profit = [float(v) for v in raw_tp if v is not None]
        exec_order_type = "market"

    if exec_stop <= 0 or not exec_take_profit:
        return

    direction = str(candidate["direction"])
    side = "buy" if direction == "long" else "sell"
    now = utc_now_iso()
    idea_id = live_trade_idea_id(str(candidate["id"]), account_label=env.account_label)
    request_id = f"exec-{uuid.uuid4()}"
    order_id = f"live-order-{uuid.uuid4()}"
    context_snapshot = {
        "source": "live",
        "account_label": env.account_label,
        "account_profile": env.account_profile,
        "broker_symbol": broker_symbol,
        "setup_id": candidate["id"],
        "candidate": candidate,
        "pricing_plan": {
            "order_type": exec_order_type,
            "entry_price": exec_entry,
            "stop_loss": exec_stop,
            "take_profit": exec_take_profit,
            "expires_at": pricing_plan.expires_at if pricing_plan else candidate.get("expires_at"),
            "drift_action": pricing_plan.drift_action if pricing_plan else "unknown",
            "adverse_drift": pricing_plan.adverse_drift if pricing_plan else 0.0,
        },
    }

    # ── Persist intent BEFORE calling MT5 (Bug #4 guard against double-execution).
    # status='pending' blocks live_candidate_already_executed on the next poll even
    # if the process crashes between MT5 call and the post-execution DB commit.
    conn.execute(
        """
        INSERT OR IGNORE INTO trade_ideas (
            id, symbol, direction, playbook, status, entry_zone_id,
            related_zone_ids_json, context_snapshot_json, suggested_entry,
            suggested_stop_loss, suggested_take_profit_json, risk_reward,
            created_at, expires_at
        )
        VALUES (?, ?, ?, ?, 'approved', ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            exec_stop,
            json.dumps(exec_take_profit),
            candidate.get("risk_reward") or 0,
            now,
            pricing_plan.expires_at if pricing_plan else candidate.get("expires_at"),
        ),
    )
    conn.execute(
        """
        INSERT INTO execution_requests (
            id, trade_idea_id, account_label, symbol, broker_symbol, side, order_type, quantity,
            entry_price, stop_loss, take_profit_json, risk_snapshot_json,
            context_snapshot_json, requested_by, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'strategy', 'pending', ?, ?)
        """,
        (
            request_id,
            idea_id,
            env.account_label,
            config.symbol,
            broker_symbol,
            side,
            exec_order_type,
            volume,
            exec_entry,
            exec_stop,
            json.dumps(exec_take_profit),
            json.dumps(
                {
                    "execution_enabled": True,
                    "volume": volume,
                    "account_label": env.account_label,
                    "account_profile": env.account_profile,
                    "broker_symbol": broker_symbol,
                },
                sort_keys=True,
            ),
            json.dumps(context_snapshot, sort_keys=True),
            now,
            now,
        ),
    )
    # Commit the pending intent before touching MT5.  From this point forward,
    # live_candidate_already_executed will return True and prevent duplicate orders.
    conn.commit()

    try:
        # Recheck immediately before MT5 to close the race with the dashboard switch.
        if not account_execution_is_enabled(conn, env):
            conn.execute(
                "UPDATE execution_requests SET status = 'cancelled', updated_at = ? WHERE id = ?",
                (utc_now_iso(), request_id),
            )
            conn.commit()
            return
        mt5_request = MT5OrderRequest(
            broker_symbol=broker_symbol,
            side=side,
            volume=volume,
            stop_loss=exec_stop,
            take_profit=exec_take_profit[0],
            comment=f"{candidate['playbook']} {candidate['id'][:8]}",
            magic=env.mt5_magic,
            entry_price=exec_entry if exec_order_type == "limit" else None,
            expires_at=pricing_plan.expires_at if pricing_plan else None,
        )
        if exec_order_type == "limit":
            result = client.place_limit_order(mt5_request)
        else:
            result = client.place_market_order(mt5_request)

        # Store both the order ticket and the deal ticket.  In hedging mode the
        # order ticket becomes the position_id; in netting mode the deal ticket
        # may differ.  Persisting both lets sync_closed_positions fall back to
        # the deal ticket when the order-ticket lookup returns nothing.
        broker_order_id = str(result.get("order") or "")
        broker_deal_id = str(result.get("deal") or "")
        # Limit orders report price=0 until filled; fall back to exec_entry.
        fill_price = float(result.get("price") or exec_entry)
        conn.execute(
            """
            UPDATE execution_requests
            SET status = 'sent', broker_order_id = ?, broker_result_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (broker_order_id or broker_deal_id, json.dumps(result, sort_keys=True, default=str), now, request_id),
        )
        order_status = "pending_fill" if exec_order_type == "limit" else "filled"
        opened_at = None if order_status == "pending_fill" else now
        trade_metadata = _build_trade_metadata(candidate, broker_order_id, broker_deal_id, now)
        trade_metadata["account_label"] = env.account_label
        trade_metadata["account_profile"] = env.account_profile
        trade_metadata["broker_symbol"] = broker_symbol
        partial_enabled, partial_trigger_r = account_partial_take_profit_settings(conn, env)
        candidate_metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        candidate_partial = candidate_metadata.get("partial_take_profit")
        locked_partial = candidate_partial if isinstance(candidate_partial, dict) else None
        trade_metadata.update(
            _partial_take_profit_metadata(
                env=env,
                side=side,
                entry_price=fill_price,
                stop_loss=exec_stop,
                take_profit=exec_take_profit[0],
                quantity=volume,
                enabled=bool(locked_partial.get("enabled")) if locked_partial is not None else partial_enabled,
                trigger_r=float(locked_partial.get("trigger_r", partial_trigger_r)) if locked_partial is not None else partial_trigger_r,
                fraction=float(locked_partial.get("close_fraction", env.partial_take_profit_fraction)) if locked_partial is not None else None,
                breakeven_buffer=float(locked_partial.get("breakeven_buffer", env.partial_take_profit_be_buffer)) if locked_partial is not None else None,
                move_stop_to=str(locked_partial.get("move_stop_to", "breakeven")) if locked_partial is not None else "breakeven",
                locked=locked_partial is not None,
            )
        )
        conn.execute(
            """
            INSERT INTO trade_orders (
                id, trade_idea_id, account_label, symbol, side, order_type, status, entry_price,
                stop_loss, take_profit_json, quantity, opened_at, source,
                metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'live', ?, ?)
            """,
            (
                order_id,
                idea_id,
                env.account_label,
                config.symbol,
                side,
                exec_order_type,
                order_status,
                fill_price,
                exec_stop,
                json.dumps(exec_take_profit),
                volume,
                opened_at,
                json.dumps(trade_metadata, sort_keys=True),
                now,
            ),
        )
        conn.commit()
        is_limit = exec_order_type == "limit"
        queue_alert(
            conn,
            account_label=env.account_label,
            symbol=config.symbol,
            timeframe=config.strategy.timeframe,
            event_type="execution_event",
            severity="important" if is_limit else "critical",
            entity_ids=[idea_id, order_id],
            payload={
                "title": "Limit order placed" if is_limit else "Market order opened",
                "outcome": "pending" if is_limit else "opened",
                "account": env.account_label,
                "setup": {
                    "playbook": candidate["playbook"],
                    "direction": direction,
                    "order_type": exec_order_type,
                    "entry": fill_price,
                    "stop_loss": exec_stop,
                    "take_profit": exec_take_profit,
                    "expires_at": pricing_plan.expires_at if pricing_plan else candidate.get("expires_at"),
                    "drift_action": pricing_plan.drift_action if pricing_plan else "unknown",
                },
                "reason": [f"MT5 broker order id: {broker_order_id}"],
                "chart_url": env.chart_url_base,
            },
            dedupe_key=f"live-order:{env.account_label}:{candidate['id']}",
        )
        return {"trade_idea_id": idea_id, "execution_request_id": request_id, "trade_order_id": order_id}
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
            account_label=env.account_label,
            symbol=config.symbol,
            timeframe=config.strategy.timeframe,
            event_type="execution_event",
            severity="critical",
            entity_ids=[idea_id],
            payload={"title": "Live order failed", "outcome": "failed", "reason": [str(exc)]},
            dedupe_key=f"live-order-failed:{env.account_label}:{candidate['id']}:{request_id}",
        )


def _partial_take_profit_metadata(
    *,
    env: RuntimeEnv,
    side: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    quantity: float,
    enabled: bool | None = None,
    trigger_r: float | None = None,
    fraction: float | None = None,
    breakeven_buffer: float | None = None,
    move_stop_to: str = "breakeven",
    locked: bool = False,
) -> dict[str, Any]:
    risk = abs(entry_price - stop_loss)
    resolved_enabled = bool(env.partial_take_profit_enabled if enabled is None else enabled)
    resolved_enabled = bool(resolved_enabled and risk > 0 and quantity > 0)
    resolved_fraction = min(max(float(env.partial_take_profit_fraction if fraction is None else fraction), 0.0), 1.0)
    resolved_trigger_r = min(max(float(env.partial_take_profit_r if trigger_r is None else trigger_r), 0.5), 2.0)
    if side == "buy":
        trigger_price = entry_price + risk * resolved_trigger_r
        breakeven_stop = entry_price + float(env.partial_take_profit_be_buffer if breakeven_buffer is None else breakeven_buffer)
    else:
        trigger_price = entry_price - risk * resolved_trigger_r
        breakeven_stop = entry_price - float(env.partial_take_profit_be_buffer if breakeven_buffer is None else breakeven_buffer)
    return {
        "initial_stop_loss": stop_loss,
        "initial_quantity": quantity,
        "partial_take_profit": {
            "enabled": resolved_enabled,
            "trigger_r": resolved_trigger_r,
            "trigger_price": round(trigger_price, 5),
            "fraction": resolved_fraction,
            "breakeven_stop": round(breakeven_stop, 5),
            "move_stop_to": move_stop_to,
            "locked": locked,
            "final_take_profit": take_profit,
            "done": False,
        },
    }


def mark_pending_order_filled(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    trade_order_id: str,
    *,
    opened_at: str,
    fill_price: float | None = None,
    broker_position_id: str | None = None,
) -> bool:
    """Atomically persist one broker-confirmed limit fill and its outbox event."""
    row = conn.execute(
        """
        SELECT o.*, i.playbook
        FROM trade_orders o
        JOIN trade_ideas i ON i.id = o.trade_idea_id
        WHERE o.id = ?
        """,
        (trade_order_id,),
    ).fetchone()
    if row is None or str(row["status"]) != "pending_fill":
        return False

    now = utc_now_iso()
    metadata = json.loads(row["metadata_json"] or "{}")
    actual_entry = float(fill_price) if fill_price is not None else float(row["entry_price"])
    metadata["broker_position_opened_at"] = opened_at
    metadata["broker_position_entry_price"] = actual_entry
    if broker_position_id:
        metadata["broker_position_id"] = broker_position_id

    updated = conn.execute(
        """
        UPDATE trade_orders
        SET status = 'filled', opened_at = ?, metadata_json = ?, updated_at = ?
        WHERE id = ? AND status = 'pending_fill'
        """,
        (opened_at, json.dumps(metadata, sort_keys=True, default=str), now, trade_order_id),
    ).rowcount
    if not updated:
        return False

    conn.execute(
        """
        UPDATE execution_requests
        SET status = 'filled', updated_at = ?
        WHERE trade_idea_id = ? AND account_label = ? AND status IN ('pending', 'sent')
        """,
        (now, row["trade_idea_id"], env.account_label),
    )
    conn.execute(
        """
        UPDATE manual_ai_plans
        SET status = 'filled', updated_at = ?
        WHERE trade_idea_id = ? AND account_label = ?
          AND status IN ('approved', 'arming', 'armed', 'cancel_requested', 'replace_requested')
        """,
        (now, row["trade_idea_id"], env.account_label),
    )

    candidate_metadata = metadata.get("candidate_metadata")
    candidate_metadata = candidate_metadata if isinstance(candidate_metadata, dict) else {}
    entry_source = str(
        metadata.get("entry_source")
        or candidate_metadata.get("entry_source")
        or candidate_metadata.get("entry_model")
        or "strategy_calculated"
    )
    take_profit = json.loads(row["take_profit_json"] or "[]")
    playbook = str(metadata.get("playbook") or row["playbook"] or "unknown")
    broker_order_id = str(metadata.get("broker_order_id") or "")
    broker_deal_id = str(metadata.get("broker_deal_id") or "")
    direction = "long" if str(row["side"]) == "buy" else "short"
    queue_alert(
        conn,
        account_label=env.account_label,
        symbol=config.symbol,
        timeframe=config.strategy.timeframe,
        event_type="execution_event",
        severity="critical",
        entity_ids=[str(row["trade_idea_id"]), trade_order_id],
        payload={
            "title": f"{playbook} limit filled",
            "outcome": "filled",
            "account": env.account_label,
            "direction": direction,
            "entry": actual_entry,
            "planned_entry": float(row["entry_price"]),
            "stop_loss": float(row["stop_loss"]),
            "take_profit": take_profit,
            "quantity": float(row["quantity"]),
            "entry_source": entry_source,
            "filled_at": opened_at,
            "broker_order_id": broker_order_id,
            "broker_deal_id": broker_deal_id,
            "broker_position_id": broker_position_id,
            "setup": {
                "playbook": playbook,
                "direction": direction,
                "order_type": "limit",
                "entry": actual_entry,
                "stop_loss": float(row["stop_loss"]),
                "take_profit": take_profit,
            },
            "chart_url": env.chart_url_base,
        },
        dedupe_key=f"order-lifecycle:{env.account_label}:{trade_order_id}:filled",
        commit=False,
    )
    conn.commit()
    return True


def sync_filled_pending_orders(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    broker_symbol: str,
) -> None:
    """Promote accepted limit orders only after MT5 exposes a real position.

    A pending-order acknowledgement is not an entry fill.  Keeping
    ``trade_orders.opened_at`` empty until this step prevents the chart from
    drawing a trade box at the limit-placement time.
    """
    rows = conn.execute(
        """
        SELECT id, metadata_json, opened_at
        FROM trade_orders
        WHERE symbol = ?
          AND account_label = ?
          AND source = 'live'
          AND status = 'pending_fill'
        """,
        (config.symbol, env.account_label),
    ).fetchall()
    if not rows:
        return
    try:
        open_positions = client.get_open_positions(broker_symbol)
    except AttributeError:
        open_positions = []
    positions_by_ticket = {str(position.get("ticket")): position for position in open_positions}

    now = utc_now_iso()
    for row in rows:
        metadata = json.loads(row["metadata_json"] or "{}")
        broker_order_id = str(metadata.get("broker_order_id") or "")
        broker_deal_id = str(metadata.get("broker_deal_id") or "")
        broker_position_id = str(metadata.get("broker_position_id") or "")
        position = (
            positions_by_ticket.get(broker_position_id)
            or positions_by_ticket.get(broker_order_id)
            or positions_by_ticket.get(broker_deal_id)
        )
        if position is not None:
            opened_at = str(position.get("opened_at") or row["opened_at"] or now)
            position_ticket = str(position.get("ticket") or broker_order_id or broker_deal_id)
            position_price = position.get("price_open")
            mark_pending_order_filled(
                conn,
                config,
                env,
                str(row["id"]),
                opened_at=opened_at,
                fill_price=float(position_price) if position_price is not None else None,
                broker_position_id=position_ticket or None,
            )
            continue
        ticket = broker_order_id or broker_deal_id
        if not ticket:
            continue
        try:
            broker_state = client.get_pending_order_state(broker_symbol, order_ticket=ticket)
        except AttributeError:
            broker_state = None
        if broker_state == "filled":
            # The position may already have closed between polls. Broker history
            # still confirms the fill even though no open position remains.
            mark_pending_order_filled(
                conn,
                config,
                env,
                str(row["id"]),
                opened_at=str(row["opened_at"] or now),
            )


def manage_open_trade_partial_take_profit(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    broker_symbol: str,
) -> None:
    """Partial-close 50% at the configured R milestone and move the rest to BE."""
    if not env.execution_enabled or not broker_symbol:
        return
    account_enabled, account_trigger_r = account_partial_take_profit_settings(conn, env)
    rows = conn.execute(
        """
        SELECT id, side, entry_price, stop_loss, take_profit_json, quantity, metadata_json
        FROM trade_orders
        WHERE symbol = ?
          AND account_label = ?
          AND status IN ('filled', 'pending_fill')
          AND source = 'live'
        """,
        (config.symbol, env.account_label),
    ).fetchall()
    if not rows:
        return
    try:
        open_positions = client.get_open_positions(broker_symbol)
    except AttributeError:
        return
    positions_by_ticket = {str(position.get("ticket")): position for position in open_positions}
    if not positions_by_ticket:
        return

    updated_any = False
    for row in rows:
        metadata = json.loads(row["metadata_json"] or "{}")
        plan = metadata.get("partial_take_profit")
        if not isinstance(plan, dict):
            continue
        if not plan.get("done") and not plan.get("locked"):
            initial_stop = float(metadata.get("initial_stop_loss") or row["stop_loss"])
            entry = float(row["entry_price"])
            trigger_price = (
                entry + abs(entry - initial_stop) * account_trigger_r
                if str(row["side"]).lower() == "buy"
                else entry - abs(entry - initial_stop) * account_trigger_r
            )
            if (
                bool(plan.get("enabled")) != account_enabled
                or abs(float(plan.get("trigger_r") or 0.0) - account_trigger_r) > 1e-9
                or abs(float(plan.get("trigger_price") or 0.0) - trigger_price) > 1e-5
            ):
                plan["enabled"] = account_enabled
                plan["trigger_r"] = account_trigger_r
                plan["trigger_price"] = round(trigger_price, 5)
                metadata["partial_take_profit"] = plan
                conn.execute(
                    "UPDATE trade_orders SET metadata_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(metadata, sort_keys=True, default=str), utc_now_iso(), row["id"]),
                )
                updated_any = True
        if not plan.get("enabled"):
            continue
        broker_order_id = str(metadata.get("broker_order_id") or "")
        broker_deal_id = str(metadata.get("broker_deal_id") or "")
        broker_position_id = str(metadata.get("broker_position_id") or "")
        position = (
            positions_by_ticket.get(broker_position_id)
            or positions_by_ticket.get(broker_order_id)
            or positions_by_ticket.get(broker_deal_id)
        )
        if position is None:
            continue
        side = str(row["side"]).lower()
        close_side = "sell" if side == "buy" else "buy"
        try:
            current_close_price = float(client.current_price_for_side(broker_symbol, close_side))
            entry = float(row["entry_price"])
            trigger_price = float(plan["trigger_price"])
            position_volume = float(position.get("volume") or row["quantity"])
            fraction = min(max(float(plan.get("fraction") or 0.0), 0.0), 1.0)
            initial_quantity = float(metadata.get("initial_quantity") or row["quantity"])
        except (TypeError, ValueError, KeyError):
            continue
        if position_volume <= 0 or fraction <= 0:
            continue
        be_stop = float(plan.get("breakeven_stop") or entry)
        final_tp = float(plan.get("final_take_profit") or (json.loads(row["take_profit_json"] or "[]") or [0])[0])
        move_to_breakeven = plan.get("move_stop_to", "breakeven") == "breakeven"
        ticket = str(position["ticket"])
        if plan.get("done"):
            if not move_to_breakeven or plan.get("breakeven_applied"):
                continue
            modify_result, modify_error = _try_apply_break_even(
                client,
                broker_symbol=broker_symbol,
                position_ticket=ticket,
                stop_loss=be_stop,
                take_profit=final_tp,
                magic=env.mt5_magic,
            )
            if modify_error is not None:
                queue_alert(
                    conn,
                    account_label=env.account_label,
                    symbol=config.symbol,
                    timeframe=config.strategy.timeframe,
                    event_type="execution_event",
                    severity="critical",
                    entity_ids=[row["id"]],
                    payload={"title": "Break-even move retry failed", "outcome": "failed", "reason": [modify_error]},
                    dedupe_key=f"partial-be-retry-failed:{row['id']}:{datetime.now(UTC).date().isoformat()}",
                )
                continue
            now = utc_now_iso()
            plan["breakeven_applied"] = True
            plan["modify_result"] = modify_result
            plan["modify_error"] = None
            metadata["partial_take_profit"] = plan
            metadata["stop_management_state"] = "partial_taken_be"
            metadata["current_stop_loss"] = be_stop
            conn.execute(
                """
                UPDATE trade_orders
                SET stop_loss = ?, metadata_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (be_stop, json.dumps(metadata, sort_keys=True, default=str), now, row["id"]),
            )
            updated_any = True
            continue
        reached = current_close_price >= trigger_price if side == "buy" else current_close_price <= trigger_price
        if not reached:
            continue
        target_remaining_volume = _round_lot_volume(initial_quantity * (1.0 - fraction))
        already_partially_closed = target_remaining_volume > 0 and position_volume <= target_remaining_volume + 1e-9
        close_result: dict[str, Any] | None = None
        close_volume = 0.0
        if already_partially_closed:
            close_volume = _round_lot_volume(max(initial_quantity - position_volume, 0.0))
        else:
            close_volume = _round_lot_volume(position_volume * fraction)
            if close_volume <= 0 or close_volume >= position_volume:
                close_volume = _round_lot_volume(position_volume / 2)
            if close_volume <= 0 or close_volume >= position_volume:
                continue
            try:
                close_result = client.close_partial_position(
                    broker_symbol,
                    position_ticket=ticket,
                    side=side,
                    volume=close_volume,
                    magic=env.mt5_magic,
                    comment=f"partial {float(plan.get('trigger_r') or account_trigger_r):g}R",
                )
            except Exception as exc:
                queue_alert(
                    conn,
                    account_label=env.account_label,
                    symbol=config.symbol,
                    timeframe=config.strategy.timeframe,
                    event_type="execution_event",
                    severity="critical",
                    entity_ids=[row["id"]],
                    payload={"title": "Partial TP failed", "outcome": "failed", "reason": [str(exc)]},
                    dedupe_key=f"partial-tp-failed:{row['id']}:{datetime.now(UTC).date().isoformat()}",
                )
                continue
        modify_result: dict[str, Any] | None = None
        modify_error: str | None = None
        if move_to_breakeven:
            modify_result, modify_error = _try_apply_break_even(
                client,
                broker_symbol=broker_symbol,
                position_ticket=ticket,
                stop_loss=be_stop,
                take_profit=final_tp,
                magic=env.mt5_magic,
            )
        if modify_error is not None:
            queue_alert(
                conn,
                account_label=env.account_label,
                symbol=config.symbol,
                timeframe=config.strategy.timeframe,
                event_type="execution_event",
                severity="critical",
                entity_ids=[row["id"]],
                payload={"title": "Break-even move failed after partial TP", "outcome": "failed", "reason": [modify_error]},
                dedupe_key=f"partial-be-failed:{row['id']}:{datetime.now(UTC).date().isoformat()}",
            )
        now = utc_now_iso()
        plan.update(
            {
                "done": True,
                "done_at": now,
                "closed_volume": close_volume,
                "remaining_volume_estimate": round(max(position_volume - close_volume, 0.0), 4),
                "close_price": current_close_price,
                "breakeven_applied": move_to_breakeven and modify_error is None,
                "close_result": close_result,
                "modify_result": modify_result,
                "modify_error": modify_error,
                "inferred_from_position_volume": already_partially_closed,
            }
        )
        metadata["partial_take_profit"] = plan
        if not move_to_breakeven:
            metadata["stop_management_state"] = "partial_taken_sl_unchanged"
            metadata["current_stop_loss"] = float(row["stop_loss"])
            persisted_stop_loss = float(row["stop_loss"])
        elif modify_error is None:
            metadata["stop_management_state"] = "partial_taken_be"
            metadata["current_stop_loss"] = be_stop
            persisted_stop_loss = be_stop
        else:
            metadata["stop_management_state"] = "partial_taken_be_failed"
            metadata["current_stop_loss"] = float(row["stop_loss"])
            persisted_stop_loss = float(row["stop_loss"])
        conn.execute(
            """
            UPDATE trade_orders
            SET stop_loss = ?, metadata_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (persisted_stop_loss, json.dumps(metadata, sort_keys=True, default=str), now, row["id"]),
        )
        queue_alert(
            conn,
            account_label=env.account_label,
            symbol=config.symbol,
            timeframe=config.strategy.timeframe,
            event_type="execution_event",
            severity="important",
            entity_ids=[row["id"]],
            payload={
                "title": "Partial TP + break-even" if modify_error is None else "Partial TP done; break-even pending",
                "outcome": "take_profit",
                "reason": [
                    f"Closed {close_volume:g} lot at ~{current_close_price:.2f}",
                    f"Moved SL to {be_stop:.2f}" if modify_error is None else f"BE move failed: {modify_error}",
                ],
            },
            dedupe_key=f"partial-tp:{row['id']}",
        )
        updated_any = True
    if updated_any:
        conn.commit()


def _try_apply_break_even(
    client: MT5BrokerClient,
    *,
    broker_symbol: str,
    position_ticket: str,
    stop_loss: float,
    take_profit: float,
    magic: int,
    comment: str = "BE after partial",
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        result = client.modify_position_sltp(
            broker_symbol,
            position_ticket=position_ticket,
            stop_loss=stop_loss,
            take_profit=take_profit,
            magic=magic,
            comment=comment,
        )
    except Exception as exc:
        return None, str(exc)
    return result, None


def _round_lot_volume(value: float) -> float:
    return round(max(value, 0.0), 2)


def sync_closed_positions(
    conn: Connection,
    config: AppConfig,
    env: RuntimeEnv,
    client: MT5BrokerClient,
    broker_symbol: str,
) -> None:
    """Sync MT5 position closures back to trade_orders.

    Called every live iteration. Finds open live orders whose MT5 position has
    closed and repairs historical closed rows that predate the full-cost P&L
    snapshot. Without this the risk manager's daily loss query is incomplete.
    """
    rows = conn.execute(
        """
        SELECT id, side, entry_price, stop_loss, quantity, status, opened_at, metadata_json
        FROM trade_orders
        WHERE symbol = ?
          AND account_label = ?
          AND source = 'live'
          AND (
                status IN ('filled', 'pending_fill')
                OR (
                    status = 'closed'
                    AND json_extract(metadata_json, '$.broker_close_costs') IS NULL
                )
          )
        """,
        (config.symbol, env.account_label),
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
        already_closed = str(row["status"]) == "closed"
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

        # Broker net P&L includes costs from both entry and exit deals. The MT5
        # client aggregates those position-level costs before returning here.
        gross_profit = float(deal["profit"])
        swap = float(deal.get("swap", 0) or 0)
        commission = float(deal.get("commission", 0) or 0)
        fee = float(deal.get("fee", 0) or 0)
        pnl = round(gross_profit + swap + commission + fee, 2)
        close_price = deal["price"]
        closed_at = deal["time_iso"]
        opened_at = str(deal.get("open_time_iso") or row["opened_at"] or metadata.get("placed_at") or "")

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
            stop  = float(metadata.get("initial_stop_loss") or row["stop_loss"])
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

        metadata["broker_close_costs"] = {
            "gross_profit": round(gross_profit, 2),
            "commission": round(commission, 2),
            "swap": round(swap, 2),
            "fee": round(fee, 2),
            "net_profit": pnl,
        }
        if deal.get("open_time_iso"):
            metadata["broker_position_opened_at"] = str(deal["open_time_iso"])
        if deal.get("open_price"):
            metadata["broker_position_entry_price"] = float(deal["open_price"])
        conn.execute(
            """
            UPDATE trade_orders
            SET status = 'closed',
                opened_at = COALESCE(opened_at, ?),
                close_price = ?,
                pnl = ?,
                pnl_r = ?,
                closed_at = ?,
                metadata_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (opened_at or None, close_price, pnl, pnl_r, closed_at, json.dumps(metadata), now, row["id"]),
        )
        closed_any = True
        if not already_closed:
            pnl_str = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
            queue_alert(
                conn,
                account_label=env.account_label,
                symbol=config.symbol,
                timeframe=config.strategy.timeframe,
                event_type="execution_event",
                severity="important",
                entity_ids=[row["id"]],
                payload={
                    "title": "Live position closed",
                    "outcome": "closed",
                    "account": env.account_label,
                    "reason": [f"P&L: ${pnl_str}", f"Close: {close_price}"],
                },
                dedupe_key=f"position-closed:{env.account_label}:{row['id']}",
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


def live_candidate_already_executed(conn: Connection, candidate_id: str, *, account_label: str = "Default") -> bool:
    """Return True when a non-failed execution request exists for this candidate.

    'pending'  — intent committed to DB before MT5 call; process may have crashed
                 mid-flight. Treat as already-in-progress to prevent duplicate orders.
    'sent'     — MT5 accepted the order. Definitive in-flight or filled trade.
    'failed'   — MT5 rejected or an exception occurred; allow a retry on the same
                 candidate (the setup may still be eligible).
    """
    row = conn.execute(
        """
        SELECT er.id
        FROM trade_ideas ti
        JOIN execution_requests er ON er.trade_idea_id = ti.id
        WHERE ti.id = ?
          AND er.account_label = ?
          AND er.status IN ('pending', 'sent')
        """,
        (live_trade_idea_id(candidate_id, account_label=account_label), account_label),
    ).fetchone()
    return row is not None


def live_trade_idea_id(candidate_id: str, *, account_label: str = "Default") -> str:
    if account_label == "Default":
        return f"live-idea-{candidate_id}"
    safe_label = "".join(ch.lower() if ch.isalnum() else "-" for ch in account_label).strip("-")
    safe_label = "-".join(part for part in safe_label.split("-") if part) or "account"
    return f"live-idea-{safe_label}-{candidate_id}"


def live_trade_count_today(conn: Connection, symbol: str, *, account_label: str = "Default") -> int:
    """Count live trades that actually reached MT5 today.

    Counts trade_orders rows (source='live', status in filled/pending_fill/closed)
    instead of execution_requests to avoid ghost counts from 'sent' rows whose
    MT5 fill was later rejected or never confirmed.  'pending_fill' covers limit
    orders that have been placed but not yet filled.
    """
    day_prefix = datetime.now(UTC).date().isoformat()
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM trade_orders
        WHERE symbol = ?
          AND account_label = ?
          AND source = 'live'
          AND status IN ('filled', 'pending_fill', 'closed')
          AND COALESCE(opened_at, created_at) >= ?
        """,
        (symbol, account_label, day_prefix),
    ).fetchone()
    return int(row["count"])


def candidates_after_live_fvg_trade_count(
    conn: Connection,
    symbol: str,
    candidates: list[dict[str, Any]],
    max_trades_per_zone: int,
    *,
    account_label: str = "Default",
) -> list[dict[str, Any]]:
    if max_trades_per_zone <= 0:
        return candidates

    filtered: list[dict[str, Any]] = []
    for candidate in candidates:
        zone_id = str(candidate.get("primary_zone_id") or "")
        if candidate_zone_type(candidate) != "fvg" or not zone_id:
            filtered.append(candidate)
            continue
        if live_fvg_trade_count_for_zone(conn, symbol, zone_id, account_label=account_label) < max_trades_per_zone:
            filtered.append(candidate)
    return filtered


def live_fvg_trade_count_for_zone(
    conn: Connection,
    symbol: str,
    zone_id: str,
    *,
    account_label: str = "Default",
) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM trade_orders
        WHERE symbol = ?
          AND account_label = ?
          AND source = 'live'
          AND json_extract(metadata_json, '$.primary_zone_id') = ?
          AND COALESCE(
                json_extract(metadata_json, '$.candidate_metadata.zone_type'),
                json_extract(metadata_json, '$.zone_type')
              ) = 'fvg'
        """,
        (symbol, account_label, zone_id),
    ).fetchone()
    return int(row["count"] or 0)


def candidate_zone_type(candidate: dict[str, Any]) -> str | None:
    metadata = candidate.get("metadata")
    if isinstance(metadata, dict) and metadata.get("zone_type"):
        return str(metadata["zone_type"])
    if candidate.get("zone_type"):
        return str(candidate["zone_type"])
    return None


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
        "placed_at": now,
        "playbook": candidate.get("playbook"),
        "primary_zone_id": candidate.get("primary_zone_id"),
        "zone_reaction_state": candidate.get("zone_reaction_state"),
        # --- top-level shortcuts for dashboard queries ---
        "session": trading_session(now),
        "macro_trend": cm.get("macro_trend", "unknown"),
        "zone_type": cm.get("zone_type", "unknown"),
        "zone_timeframe": cm.get("zone_timeframe", "unknown"),
        "zone_source": cm.get("zone_source", "unknown"),
        "zone_detector": cm.get("zone_detector", "unknown"),
        "atr": cm.get("atr"),
        "rsi_h1": cm.get("rsi_h1"),
        "rsi_h1_slope_3": cm.get("rsi_h1_slope_3"),
        "rsi_h1_slope_5": cm.get("rsi_h1_slope_5"),
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
