from __future__ import annotations

import sqlite3
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
    source TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
"""


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    ensure_column(conn, "structure_points", "detector", "TEXT NOT NULL DEFAULT 'unknown'")
    ensure_column(conn, "structure_points", "status", "TEXT NOT NULL DEFAULT 'confirmed'")
    ensure_column(conn, "price_zones", "detector", "TEXT NOT NULL DEFAULT 'unknown'")
    ensure_column(conn, "backtest_runs", "engine", "TEXT NOT NULL DEFAULT 'incremental'")
    conn.commit()


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
