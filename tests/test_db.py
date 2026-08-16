from __future__ import annotations

import json
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tests.helpers import TemporaryDirectory

from semi_bot_trading.db import connect, init_db


class DbMigrationTest(unittest.TestCase):
    def test_alert_events_migrate_to_account_scoped_retry_queue(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "legacy.sqlite3"
            with closing(connect(db_path)) as conn:
                conn.executescript(
                    """
                    CREATE TABLE alert_events (
                        id TEXT PRIMARY KEY,
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
                        chart_snapshot_path TEXT
                    );
                    CREATE UNIQUE INDEX idx_alert_events_dedupe ON alert_events(dedupe_key);
                    INSERT INTO alert_events (
                        id, symbol, timeframe, event_type, severity, message_payload_json,
                        dedupe_key, status
                    ) VALUES (
                        'legacy-alert', 'XAUUSD', 'M15', 'system', 'info',
                        '{"account":"FTMO"}', 'legacy-key', 'pending'
                    );
                    """
                )
                init_db(conn)
                columns = {
                    row["name"] for row in conn.execute("PRAGMA table_info(alert_events)").fetchall()
                }
                row = conn.execute(
                    "SELECT account_label, attempt_count, next_attempt_at FROM alert_events"
                ).fetchone()
                index_columns = [
                    item["name"]
                    for item in conn.execute("PRAGMA index_info(idx_alert_events_dedupe)").fetchall()
                ]

        self.assertIn("account_label", columns)
        self.assertIn("attempt_count", columns)
        self.assertIn("next_attempt_at", columns)
        self.assertEqual("FTMO", row["account_label"])
        self.assertEqual(0, row["attempt_count"])
        self.assertEqual(["account_label", "dedupe_key"], index_columns)

    def test_partial_take_profit_control_columns_migrate_existing_account_table(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "legacy.sqlite3"
            with closing(connect(db_path)) as conn:
                conn.execute(
                    "CREATE TABLE account_execution_controls (account_label TEXT PRIMARY KEY)"
                )
                init_db(conn)
                columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(account_execution_controls)").fetchall()
                }

        self.assertIn("partial_take_profit_enabled", columns)
        self.assertIn("partial_take_profit_r", columns)
        self.assertIn("manual_lock_requested_enabled", columns)
        self.assertIn("manual_lock_effective_enabled", columns)
        self.assertIn("manual_lock_baseline_positions_json", columns)
        self.assertIn("manual_lock_baseline_orders_json", columns)

    def test_account_label_indexes_are_created_after_legacy_columns_migrate(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "legacy.sqlite3"
            with closing(connect(db_path)) as conn:
                conn.executescript(
                    """
                    CREATE TABLE trade_orders (
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
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE execution_requests (
                        id TEXT PRIMARY KEY,
                        trade_idea_id TEXT NOT NULL,
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
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE spread_snapshots (
                        id TEXT PRIMARY KEY,
                        symbol TEXT NOT NULL,
                        broker_symbol TEXT NOT NULL,
                        bid REAL NOT NULL,
                        ask REAL NOT NULL,
                        spread REAL NOT NULL,
                        snapshot_at TEXT NOT NULL,
                        source TEXT NOT NULL DEFAULT 'mt5',
                        metadata_json TEXT NOT NULL DEFAULT '{}'
                    );
                    """
                )
                init_db(conn)
                migrated_columns = {
                    table: {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                    for table in ("trade_orders", "execution_requests", "spread_snapshots")
                }
                indexes = {
                    row["name"]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'index'"
                    ).fetchall()
                }

        self.assertIn("account_label", migrated_columns["trade_orders"])
        self.assertIn("account_label", migrated_columns["execution_requests"])
        self.assertIn("account_label", migrated_columns["spread_snapshots"])
        self.assertIn("idx_trade_orders_account_lookup", indexes)
        self.assertIn("idx_execution_requests_account_lookup", indexes)
        self.assertIn("idx_spread_snapshots_account_symbol_time", indexes)

    def test_bot_sr_default_expiry_uses_detected_at_not_updated_at(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with closing(connect(db_path)) as conn:
                init_db(conn)
                detected_at = (datetime.now(UTC) - timedelta(days=10)).replace(microsecond=0).isoformat()
                updated_at = (datetime.now(UTC) - timedelta(minutes=5)).replace(microsecond=0).isoformat()
                conn.execute(
                    """
                    INSERT INTO price_zones (
                        id, symbol, timeframe, detector, zone_type, direction,
                        price_low, price_high, start_time, end_time, valid_from, valid_until,
                        invalidated_at, invalidated_by_structure_point_id, detected_at,
                        bot_confidence, bot_weight, effective_confidence, effective_weight,
                        status, source, metadata_json, created_at, updated_at
                    )
                    VALUES ('bot-sr', 'XAUUSD', 'H1', 'sr_v2', 'support', 'bullish',
                            4010, 4030, ?, NULL, ?, NULL,
                            NULL, NULL, ?,
                            0.8, 0.8, 0.8, 0.8,
                            'active', 'bot', ?, ?, ?)
                    """,
                    (detected_at, detected_at, detected_at, json.dumps({}), detected_at, updated_at),
                )
                init_db(conn)
                row = conn.execute(
                    """
                    SELECT status, end_time, valid_until, metadata_json
                    FROM price_zones
                    WHERE id = 'bot-sr'
                    """
                ).fetchone()

        self.assertEqual(row["status"], "expired")
        self.assertEqual(row["valid_until"], (datetime.fromisoformat(detected_at) + timedelta(hours=24)).isoformat())
        self.assertEqual(row["end_time"], row["valid_until"])
        metadata = json.loads(row["metadata_json"])
        self.assertEqual(metadata["default_expiry_backfill"]["base_time"], detected_at)


if __name__ == "__main__":
    unittest.main()
