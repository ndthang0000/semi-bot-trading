from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone as _tz
UTC = _tz.utc
from pathlib import Path


DEFAULT_DB_PATH = Path("var/trading.sqlite3")


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS candles (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    open_time TEXT NOT NULL,
    close_time TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, timeframe, open_time)
);

CREATE INDEX IF NOT EXISTS idx_candles_symbol_tf_time
ON candles(symbol, timeframe, open_time);

CREATE TABLE IF NOT EXISTS market_contexts (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    context_type TEXT NOT NULL,
    bot_value TEXT NOT NULL,
    primary_value TEXT NOT NULL,
    secondary_value TEXT,
    bot_confidence REAL NOT NULL DEFAULT 0,
    effective_value TEXT NOT NULL,
    effective_confidence REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_until TEXT,
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_market_contexts_lookup
ON market_contexts(symbol, timeframe, context_type, status, valid_from);

CREATE TABLE IF NOT EXISTS price_zones (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    detector TEXT NOT NULL DEFAULT 'unknown',
    zone_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    price_low REAL NOT NULL,
    price_high REAL NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,
    valid_from TEXT NOT NULL,
    valid_until TEXT,
    invalidated_at TEXT,
    invalidated_by_structure_point_id TEXT,
    detected_at TEXT NOT NULL,
    bot_confidence REAL NOT NULL DEFAULT 0,
    bot_weight REAL NOT NULL DEFAULT 0,
    effective_confidence REAL NOT NULL DEFAULT 0,
    effective_weight REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_price_zones_lookup
ON price_zones(symbol, timeframe, detector, status, start_time, end_time);

CREATE TABLE IF NOT EXISTS structure_points (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    detector TEXT NOT NULL DEFAULT 'unknown',
    status TEXT NOT NULL DEFAULT 'confirmed',
    point_type TEXT NOT NULL,
    price REAL NOT NULL,
    event_time TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    related_zone_ids_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_structure_points_lookup
ON structure_points(symbol, timeframe, detector, point_type, event_time);

CREATE TABLE IF NOT EXISTS overrides (
    id TEXT PRIMARY KEY,
    target_entity_type TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    override_type TEXT NOT NULL,
    patch_json TEXT NOT NULL,
    reason TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT,
    status TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_overrides_target
ON overrides(target_entity_type, target_entity_id, status, expires_at);

CREATE TABLE IF NOT EXISTS trade_ideas (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    playbook TEXT NOT NULL,
    status TEXT NOT NULL,
    entry_zone_id TEXT,
    related_zone_ids_json TEXT NOT NULL DEFAULT '[]',
    context_snapshot_json TEXT NOT NULL DEFAULT '{}',
    suggested_entry REAL,
    suggested_stop_loss REAL NOT NULL,
    suggested_take_profit_json TEXT NOT NULL DEFAULT '[]',
    risk_reward REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_trade_ideas_lookup
ON trade_ideas(symbol, status, created_at);

CREATE TABLE IF NOT EXISTS trade_orders (
    id TEXT PRIMARY KEY,
    trade_idea_id TEXT NOT NULL,
    account_label TEXT NOT NULL DEFAULT 'Default',
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    status TEXT NOT NULL,
    entry_price REAL,
    stop_loss REAL NOT NULL,
    take_profit_json TEXT NOT NULL DEFAULT '[]',
    quantity REAL NOT NULL,
    opened_at TEXT,
    closed_at TEXT,
    close_price REAL,
    pnl REAL,
    pnl_r REAL,
    hidden_on_chart INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(trade_idea_id) REFERENCES trade_ideas(id)
);

CREATE INDEX IF NOT EXISTS idx_trade_orders_lookup
ON trade_orders(symbol, status, opened_at, closed_at);

CREATE TABLE IF NOT EXISTS trade_fills (
    id TEXT PRIMARY KEY,
    trade_order_id TEXT NOT NULL,
    fill_time TEXT NOT NULL,
    fill_price REAL NOT NULL,
    quantity REAL NOT NULL,
    fee REAL,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(trade_order_id) REFERENCES trade_orders(id)
);

CREATE INDEX IF NOT EXISTS idx_trade_fills_order
ON trade_fills(trade_order_id, fill_time);

CREATE TABLE IF NOT EXISTS trade_reviews (
    id TEXT PRIMARY KEY,
    trade_order_id TEXT NOT NULL UNIQUE,
    grade TEXT,
    verdict TEXT NOT NULL DEFAULT 'unreviewed',
    mistake_tags_json TEXT NOT NULL DEFAULT '[]',
    should_trade_again TEXT NOT NULL DEFAULT 'unknown',
    comment TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    reviewer TEXT NOT NULL DEFAULT 'human',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(trade_order_id) REFERENCES trade_orders(id)
);

CREATE INDEX IF NOT EXISTS idx_trade_reviews_lookup
ON trade_reviews(verdict, updated_at);

CREATE TABLE IF NOT EXISTS trade_review_attachments (
    id TEXT PRIMARY KEY,
    trade_order_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    file_path TEXT NOT NULL,
    caption TEXT NOT NULL DEFAULT '',
    chart_symbol TEXT,
    chart_timeframe TEXT,
    chart_start TEXT,
    chart_end TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(trade_order_id) REFERENCES trade_orders(id)
);

CREATE INDEX IF NOT EXISTS idx_trade_review_attachments_lookup
ON trade_review_attachments(trade_order_id, created_at);

CREATE TABLE IF NOT EXISTS weekly_journals (
    id TEXT PRIMARY KEY,
    week_start TEXT NOT NULL UNIQUE,
    week_end TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    content_format TEXT NOT NULL DEFAULT 'plain_text',
    icon TEXT NOT NULL DEFAULT '📝',
    discipline_score INTEGER NOT NULL CHECK (discipline_score BETWEEN 1 AND 10),
    fomo_score INTEGER NOT NULL CHECK (fomo_score BETWEEN 1 AND 10),
    revenge_score INTEGER NOT NULL CHECK (revenge_score BETWEEN 1 AND 10),
    achieved_r REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_weekly_journals_week
ON weekly_journals(week_start DESC);

CREATE TABLE IF NOT EXISTS alert_events (
    id TEXT PRIMARY KEY,
    account_label TEXT NOT NULL DEFAULT 'Default',
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    entity_ids_json TEXT NOT NULL DEFAULT '[]',
    message_payload_json TEXT NOT NULL DEFAULT '{}',
    dedupe_key TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sent_at TEXT,
    status TEXT NOT NULL,
    failure_reason TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    chart_snapshot_path TEXT
);

CREATE INDEX IF NOT EXISTS idx_alert_events_lookup
ON alert_events(symbol, timeframe, event_type, status, created_at);

CREATE TABLE IF NOT EXISTS system_alert_claims (
    dedupe_key TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    claimed_by TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS live_candles (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    open_time TEXT NOT NULL,
    close_time TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL,
    source TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol, timeframe)
);

CREATE INDEX IF NOT EXISTS idx_live_candles_lookup
ON live_candles(symbol, timeframe, open_time);

CREATE TABLE IF NOT EXISTS execution_requests (
    id TEXT PRIMARY KEY,
    trade_idea_id TEXT NOT NULL,
    account_label TEXT NOT NULL DEFAULT 'Default',
    symbol TEXT NOT NULL,
    broker_symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    quantity REAL NOT NULL,
    entry_price REAL,
    stop_loss REAL NOT NULL,
    take_profit_json TEXT NOT NULL DEFAULT '[]',
    risk_snapshot_json TEXT NOT NULL DEFAULT '{}',
    context_snapshot_json TEXT NOT NULL DEFAULT '{}',
    requested_by TEXT NOT NULL,
    status TEXT NOT NULL,
    broker_order_id TEXT,
    broker_result_json TEXT NOT NULL DEFAULT '{}',
    failure_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(trade_idea_id) REFERENCES trade_ideas(id)
);

CREATE INDEX IF NOT EXISTS idx_execution_requests_lookup
ON execution_requests(symbol, status, created_at);

CREATE TABLE IF NOT EXISTS manual_ai_plans (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    account_label TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    execution_state TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit REAL NOT NULL,
    risk_pct REAL NOT NULL DEFAULT 1.0,
    risk_reward REAL NOT NULL,
    expires_at TEXT NOT NULL,
    partial_take_profit_json TEXT NOT NULL DEFAULT '{}',
    cancel_conditions_json TEXT NOT NULL DEFAULT '[]',
    questionnaire_json TEXT NOT NULL DEFAULT '{}',
    context_snapshot_json TEXT NOT NULL DEFAULT '{}',
    raw_payload_json TEXT NOT NULL DEFAULT '{}',
    source TEXT NOT NULL DEFAULT 'ai_import',
    trade_idea_id TEXT,
    execution_request_id TEXT,
    replacement_levels_json TEXT NOT NULL DEFAULT '{}',
    replacement_error TEXT,
    approved_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(trade_idea_id) REFERENCES trade_ideas(id),
    FOREIGN KEY(execution_request_id) REFERENCES execution_requests(id)
);

CREATE INDEX IF NOT EXISTS idx_manual_ai_plans_lookup
ON manual_ai_plans(account_label, symbol, status, created_at);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    strategy_timeframe TEXT NOT NULL,
    context_timeframe TEXT NOT NULL,
    candle_limit INTEGER NOT NULL,
    evaluated_candles INTEGER NOT NULL DEFAULT 0,
    trade_count INTEGER NOT NULL DEFAULT 0,
    spread REAL NOT NULL DEFAULT 0,
    slippage REAL NOT NULL DEFAULT 0,
    max_hold_candles INTEGER NOT NULL DEFAULT 0,
    warmup_candles INTEGER NOT NULL DEFAULT 0,
    auto_accept INTEGER NOT NULL DEFAULT 1,
    engine TEXT NOT NULL DEFAULT 'incremental',
    lookahead_guard TEXT NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'completed',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_lookup
ON backtest_runs(symbol, created_at);

CREATE TABLE IF NOT EXISTS auth_refresh_tokens (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_auth_tokens_hash
ON auth_refresh_tokens(token_hash);

-- Economic calendar events fetched from ForexFactory.
-- Only USD High-impact events that affect XAUUSD are stored.
-- tier 1 = Supreme Red (±30min blackout), tier 2 = Regular Red (±15min blackout)
CREATE TABLE IF NOT EXISTS news_events (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    country TEXT NOT NULL,
    impact TEXT NOT NULL,
    tier INTEGER,
    scheduled_at TEXT NOT NULL,
    blackout_before_min INTEGER NOT NULL DEFAULT 0,
    blackout_after_min INTEGER NOT NULL DEFAULT 0,
    forecast TEXT,
    previous TEXT,
    url TEXT,
    fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_news_events_scheduled
ON news_events(scheduled_at, tier);

-- One row per account label: upserted by the worker each cycle.
-- account_label is the human-readable name (e.g. "Exness Personal", "FTMO Challenge").
-- Designed for multi-account: future workers for other accounts INSERT their own label.
CREATE TABLE IF NOT EXISTS account_snapshots (
    account_label TEXT PRIMARY KEY,
    broker        TEXT,
    login         INTEGER,
    server        TEXT,
    balance       REAL,
    equity        REAL,
    margin        REAL,
    free_margin   REAL,
    profit        REAL,
    currency      TEXT NOT NULL DEFAULT 'USD',
    snapshot_at   TEXT NOT NULL
);

-- Per-account operator switch. hard_enabled mirrors EXECUTION_ENABLED from the
-- worker; requested_enabled is the reversible UI switch. Both must be true.
CREATE TABLE IF NOT EXISTS account_execution_controls (
    account_label       TEXT PRIMARY KEY,
    requested_enabled   INTEGER NOT NULL DEFAULT 0,
    effective_enabled   INTEGER NOT NULL DEFAULT 0,
    hard_enabled        INTEGER NOT NULL DEFAULT 0,
    worker_status       TEXT NOT NULL DEFAULT 'offline',
    broker_symbol       TEXT,
    open_bot_positions  INTEGER NOT NULL DEFAULT 0,
    pending_bot_orders  INTEGER NOT NULL DEFAULT 0,
    partial_take_profit_enabled INTEGER,
    partial_take_profit_r REAL,
    partial_take_profit_fraction REAL NOT NULL DEFAULT 0.4,
    manual_lock_requested_enabled INTEGER NOT NULL DEFAULT 0,
    manual_lock_effective_enabled INTEGER NOT NULL DEFAULT 0,
    manual_lock_baseline_positions_json TEXT NOT NULL DEFAULT '[]',
    manual_lock_baseline_orders_json TEXT NOT NULL DEFAULT '[]',
    manual_lock_requested_at TEXT,
    manual_lock_acknowledged_at TEXT,
    manual_lock_last_action_at TEXT,
    manual_lock_last_error TEXT,
    requested_by        TEXT,
    requested_at        TEXT,
    acknowledged_at     TEXT,
    heartbeat_at        TEXT,
    last_error          TEXT,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS account_execution_commands (
    id              TEXT PRIMARY KEY,
    account_label   TEXT NOT NULL,
    command_type    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    requested_by    TEXT,
    requested_at    TEXT NOT NULL,
    claimed_at      TEXT,
    completed_at    TEXT,
    result_json     TEXT NOT NULL DEFAULT '{}',
    payload_json    TEXT NOT NULL DEFAULT '{}',
    error           TEXT,
    idempotency_key TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_account_commands_pending
ON account_execution_commands(account_label, status, requested_at);

-- One up-to-date FTMO-style result per Prague trading day. The baseline is the
-- balance at CE(S)T midnight; current equity includes open P/L.
CREATE TABLE IF NOT EXISTS account_daily_metrics (
    account_label        TEXT NOT NULL,
    trading_day          TEXT NOT NULL,
    timezone             TEXT NOT NULL,
    day_start_utc        TEXT NOT NULL,
    balance_at_midnight  REAL NOT NULL,
    current_balance      REAL NOT NULL,
    current_equity       REAL NOT NULL,
    daily_profit         REAL NOT NULL,
    daily_profit_pct     REAL,
    initial_balance      REAL,
    baseline_source      TEXT NOT NULL,
    snapshot_at          TEXT NOT NULL,
    PRIMARY KEY (account_label, trading_day)
);

-- Bid/ask spread observations captured by the live worker.
-- Spread is stored in price units (e.g. XAUUSD dollars), matching MAX_SPREAD_PRICE.
CREATE TABLE IF NOT EXISTS spread_snapshots (
    id            TEXT PRIMARY KEY,
    account_label TEXT NOT NULL DEFAULT 'Default',
    symbol        TEXT NOT NULL,
    broker_symbol TEXT NOT NULL,
    bid           REAL NOT NULL,
    ask           REAL NOT NULL,
    spread        REAL NOT NULL,
    snapshot_at   TEXT NOT NULL,
    source        TEXT NOT NULL DEFAULT 'mt5',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_spread_snapshots_symbol_time
ON spread_snapshots(symbol, snapshot_at);

-- Human chart annotations are deliberately isolated from price_zones and
-- strategy entities. They are visual research aids and must never arm trades.
CREATE TABLE IF NOT EXISTS chart_drawings (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    drawing_type TEXT NOT NULL,
    origin_timeframe TEXT NOT NULL,
    visible_timeframes_json TEXT NOT NULL DEFAULT '["H1","M15","M5"]',
    anchors_json TEXT NOT NULL,
    properties_json TEXT NOT NULL DEFAULT '{}',
    content TEXT,
    locked INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 1,
    created_by TEXT NOT NULL DEFAULT 'human',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_chart_drawings_lookup
ON chart_drawings(symbol, deleted_at, updated_at);

-- Quote-driven state for the Liquidity Sweep Reclaim playbook. State is scoped
-- per account because broker Bid/Ask and spread can differ.
CREATE TABLE IF NOT EXISTS liquidity_sweep_states (
    zone_id            TEXT NOT NULL,
    account_label      TEXT NOT NULL,
    symbol             TEXT NOT NULL,
    zone_updated_at    TEXT NOT NULL,
    state              TEXT NOT NULL,
    trade_direction    TEXT NOT NULL DEFAULT 'long',
    touched_edge_at    TEXT,
    touched_lower_at   TEXT,
    deadline_at        TEXT,
    atr_at_touch       REAL,
    extreme_price      REAL,
    deepest_bid        REAL,
    invalidation_price REAL,
    reclaimed_at       TEXT,
    terminal_reason    TEXT,
    updated_at         TEXT NOT NULL,
    PRIMARY KEY (zone_id, account_label),
    FOREIGN KEY(zone_id) REFERENCES price_zones(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_liquidity_sweep_states_lookup
ON liquidity_sweep_states(account_label, symbol, state, updated_at);

"""


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=2.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 2000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    ensure_column(conn, "structure_points", "detector", "TEXT NOT NULL DEFAULT 'unknown'")
    ensure_column(conn, "structure_points", "status", "TEXT NOT NULL DEFAULT 'confirmed'")
    ensure_column(conn, "price_zones", "detector", "TEXT NOT NULL DEFAULT 'unknown'")
    ensure_column(conn, "backtest_runs", "engine", "TEXT NOT NULL DEFAULT 'incremental'")
    ensure_column(conn, "execution_requests", "account_label", "TEXT NOT NULL DEFAULT 'Default'")
    ensure_column(conn, "trade_orders", "account_label", "TEXT NOT NULL DEFAULT 'Default'")
    ensure_column(conn, "trade_orders", "updated_at", "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP")
    ensure_column(conn, "trade_orders", "hidden_on_chart", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "trade_reviews", "metadata_json", "TEXT NOT NULL DEFAULT '{}'")
    ensure_column(conn, "weekly_journals", "achieved_r", "REAL NOT NULL DEFAULT 0")
    ensure_column(conn, "weekly_journals", "content_format", "TEXT NOT NULL DEFAULT 'plain_text'")
    ensure_column(conn, "weekly_journals", "icon", "TEXT NOT NULL DEFAULT '📝'")
    ensure_column(conn, "spread_snapshots", "account_label", "TEXT NOT NULL DEFAULT 'Default'")
    ensure_column(conn, "alert_events", "account_label", "TEXT NOT NULL DEFAULT 'Default'")
    ensure_column(conn, "alert_events", "attempt_count", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "alert_events", "next_attempt_at", "TEXT")
    ensure_column(conn, "account_execution_commands", "payload_json", "TEXT NOT NULL DEFAULT '{}'")
    ensure_column(conn, "account_execution_controls", "partial_take_profit_enabled", "INTEGER")
    ensure_column(conn, "account_execution_controls", "partial_take_profit_r", "REAL")
    ensure_column(conn, "account_execution_controls", "partial_take_profit_fraction", "REAL")
    # One-time policy migration for account rows created before fraction was
    # persisted: enable 40% at 1R consistently across every worker account.
    conn.execute(
        """
        UPDATE account_execution_controls
        SET partial_take_profit_enabled = 1,
            partial_take_profit_r = 1.0,
            partial_take_profit_fraction = 0.4
        WHERE partial_take_profit_fraction IS NULL
        """
    )
    ensure_column(conn, "account_execution_controls", "manual_lock_requested_enabled", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "account_execution_controls", "manual_lock_effective_enabled", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "account_execution_controls", "manual_lock_baseline_positions_json", "TEXT NOT NULL DEFAULT '[]'")
    ensure_column(conn, "account_execution_controls", "manual_lock_baseline_orders_json", "TEXT NOT NULL DEFAULT '[]'")
    ensure_column(conn, "account_execution_controls", "manual_lock_requested_at", "TEXT")
    ensure_column(conn, "account_execution_controls", "manual_lock_acknowledged_at", "TEXT")
    ensure_column(conn, "account_execution_controls", "manual_lock_last_action_at", "TEXT")
    ensure_column(conn, "account_execution_controls", "manual_lock_last_error", "TEXT")
    ensure_column(conn, "liquidity_sweep_states", "trade_direction", "TEXT NOT NULL DEFAULT 'long'")
    ensure_column(conn, "liquidity_sweep_states", "touched_edge_at", "TEXT")
    ensure_column(conn, "liquidity_sweep_states", "extreme_price", "REAL")
    ensure_column(conn, "manual_ai_plans", "replacement_levels_json", "TEXT NOT NULL DEFAULT '{}'")
    ensure_column(conn, "manual_ai_plans", "replacement_error", "TEXT")
    backfill_liquidity_sweep_state_columns(conn)
    migrate_alert_event_indexes(conn)
    ensure_account_scoped_indexes(conn)
    remove_non_h1_price_zones(conn)
    backfill_price_zone_expiry(conn)
    expire_price_zones(conn)
    conn.commit()


def ensure_account_scoped_indexes(conn: sqlite3.Connection) -> None:
    """Create indexes that depend on migrated account_label columns."""
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_trade_orders_account_lookup
        ON trade_orders(account_label, symbol, status, opened_at, closed_at)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_execution_requests_account_lookup
        ON execution_requests(account_label, symbol, status, created_at)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_spread_snapshots_account_symbol_time
        ON spread_snapshots(account_label, symbol, snapshot_at)
        """
    )


def migrate_alert_event_indexes(conn: sqlite3.Connection) -> None:
    """Scope alert dedupe by account after legacy single-account deployments."""
    rows = conn.execute(
        "SELECT id, message_payload_json FROM alert_events WHERE account_label = 'Default'"
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["message_payload_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        account_label = str(payload.get("account") or "").strip()
        if account_label:
            conn.execute(
                "UPDATE alert_events SET account_label = ? WHERE id = ?",
                (account_label, row["id"]),
            )
    index_columns = [
        row["name"]
        for row in conn.execute("PRAGMA index_info(idx_alert_events_dedupe)").fetchall()
    ]
    if index_columns == ["account_label", "dedupe_key"]:
        return
    conn.execute("DROP INDEX IF EXISTS idx_alert_events_dedupe")
    conn.execute(
        """
        CREATE UNIQUE INDEX idx_alert_events_dedupe
        ON alert_events(account_label, dedupe_key)
        """
    )


def backfill_liquidity_sweep_state_columns(conn: sqlite3.Connection) -> None:
    """Migrate the original Buy-only runtime fields without losing live state."""
    conn.execute(
        """
        UPDATE liquidity_sweep_states
        SET touched_edge_at = COALESCE(touched_edge_at, touched_lower_at),
            extreme_price = COALESCE(extreme_price, deepest_bid)
        WHERE touched_edge_at IS NULL OR extreme_price IS NULL
        """
    )


def ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        try:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise


def remove_non_h1_price_zones(conn: sqlite3.Connection) -> None:
    """Hard-delete legacy lower-timeframe zones.

    H1 is the only trade/context zone timeframe. M15 data remains available in
    candles, structure, and price_action for triggers, but price_zones below H1
    are intentionally removed so they cannot be displayed or traded later.
    """
    conn.execute("DELETE FROM price_zones WHERE UPPER(timeframe) != 'H1'")


def backfill_price_zone_expiry(conn: sqlite3.Connection) -> None:
    """Give legacy active zones a finite validity window.

    Older human/manual zones could keep valid_until NULL forever. That is unsafe
    for live strategy evaluation, so init_db performs a small idempotent backfill.
    """
    now = datetime.now(UTC)
    rows = conn.execute(
        """
        SELECT id, timeframe, zone_type, source, start_time, detected_at, created_at,
               updated_at, end_time, metadata_json
        FROM price_zones
        WHERE status = 'active'
          AND valid_until IS NULL
        """
    ).fetchall()
    for row in rows:
        metadata = json_loads(row["metadata_json"], {})
        if row["source"] == "bot" and row["zone_type"] in {"support", "resistance"}:
            base = first_parseable_datetime(row["detected_at"], row["start_time"], row["created_at"], row["updated_at"]) or now
        else:
            base = first_parseable_datetime(row["updated_at"], row["created_at"], row["detected_at"], row["start_time"]) or now
        expiry = base + default_price_zone_expiry(row["zone_type"], row["timeframe"])
        expiry_iso = expiry.replace(microsecond=0).isoformat()
        metadata["expired_rule"] = "default_expiry_backfill"
        metadata["default_expiry_backfill"] = {
            "base_time": base.replace(microsecond=0).isoformat(),
            "zone_type": row["zone_type"],
            "timeframe": row["timeframe"],
        }
        status = "expired" if expiry <= now else "active"
        end_time = row["end_time"] or expiry_iso
        if status == "expired":
            end_time = expiry_iso
        conn.execute(
            """
            UPDATE price_zones
            SET valid_until = ?,
                end_time = ?,
                status = ?,
                metadata_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (expiry_iso, end_time, status, json.dumps(metadata, sort_keys=True), row["id"]),
        )
    repair_bot_sr_default_expiry_backfill(conn, now)


def repair_bot_sr_default_expiry_backfill(conn: sqlite3.Connection, now: datetime) -> None:
    rows = conn.execute(
        """
        SELECT id, timeframe, zone_type, start_time, detected_at, valid_until, metadata_json
        FROM price_zones
        WHERE status = 'active'
          AND source = 'bot'
          AND zone_type IN ('support', 'resistance')
          AND valid_until IS NOT NULL
        """
    ).fetchall()
    for row in rows:
        metadata = json_loads(row["metadata_json"], {})
        if metadata.get("expired_rule") != "default_expiry_backfill":
            continue
        base = first_parseable_datetime(row["detected_at"], row["start_time"])
        if base is None:
            continue
        expiry = base + default_price_zone_expiry(row["zone_type"], row["timeframe"])
        expiry_iso = expiry.replace(microsecond=0).isoformat()
        try:
            current_expiry = parse_datetime_utc(str(row["valid_until"]))
        except ValueError:
            current_expiry = None
        if current_expiry is not None and current_expiry <= expiry:
            continue
        metadata["expired_rule"] = "default_expiry_backfill"
        metadata["default_expiry_repaired"] = {
            "base_time": base.replace(microsecond=0).isoformat(),
            "previous_valid_until": row["valid_until"],
            "zone_type": row["zone_type"],
            "timeframe": row["timeframe"],
        }
        status = "expired" if expiry <= now else "active"
        conn.execute(
            """
            UPDATE price_zones
            SET valid_until = ?,
                end_time = ?,
                status = ?,
                metadata_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (expiry_iso, expiry_iso, status, json.dumps(metadata, sort_keys=True), row["id"]),
        )


def expire_price_zones(conn: sqlite3.Connection) -> None:
    now = datetime.now(UTC)
    rows = conn.execute(
        """
        SELECT id, valid_until, metadata_json
        FROM price_zones
        WHERE status = 'active'
          AND valid_until IS NOT NULL
        """
    ).fetchall()
    for row in rows:
        try:
            expiry = parse_datetime_utc(str(row["valid_until"]))
        except ValueError:
            continue
        if expiry > now:
            continue
        metadata = json_loads(row["metadata_json"], {})
        metadata["expired_rule"] = metadata.get("expired_rule") or "valid_until"
        metadata["expired_at"] = row["valid_until"]
        conn.execute(
            """
            UPDATE price_zones
            SET status = 'expired',
                end_time = COALESCE(end_time, valid_until),
                metadata_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (json.dumps(metadata, sort_keys=True), row["id"]),
        )


def default_price_zone_expiry(zone_type: str, timeframe: str) -> timedelta:
    zone = zone_type.lower()
    tf = timeframe.upper()
    if zone == "fvg":
        return timedelta(days=1 if tf == "M15" else 2)
    if zone == "order_block":
        return timedelta(days=2 if tf == "M15" else 3)
    return timedelta(hours=24)


def first_parseable_datetime(*values: object) -> datetime | None:
    for value in values:
        if not value:
            continue
        try:
            return parse_datetime_utc(str(value))
        except ValueError:
            continue
    return None


def parse_datetime_utc(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def json_loads(value: str | None, default: dict[str, object]) -> dict[str, object]:
    if not value:
        return default
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return default
    return parsed if isinstance(parsed, dict) else default
