from __future__ import annotations

import json
import os
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tests.helpers import TemporaryDirectory
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from semi_bot_trading.api import create_app, validate_manual_ai_levels
from semi_bot_trading.auth import create_access_token
from semi_bot_trading.db import connect, init_db


ONE_PIXEL_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def authenticated_test_client(root: Path, config_path: Path) -> TestClient:
    env_path = root / ".env"
    secret_key = write_test_env(env_path)
    env_patch = patch.dict(
        os.environ,
        {"SECRET_KEY": secret_key, "ADMIN_PASSWORD_HASH": "unused-test-hash"},
        clear=False,
    )
    env_patch.start()
    client = TestClient(create_app(config_path, env_path=env_path))
    client.headers.update(auth_headers(secret_key))
    client._semi_bot_env_patch = env_patch  # type: ignore[attr-defined]
    return client


class ApiTest(unittest.TestCase):
    def test_h1_wave_target_accepts_rr_below_fixed_rr_floor(self) -> None:
        rr = validate_manual_ai_levels(
            "sell",
            entry_price=4554.61,
            stop_loss=4585.67,
            take_profit=4514.26812,
            playbook="h1_impulse_retest_v1",
        )

        self.assertAlmostEqual(1.29884, rr, places=5)

    def test_h1_wave_target_accepts_rr_above_fixed_rr_ceiling(self) -> None:
        rr = validate_manual_ai_levels(
            "sell",
            entry_price=4412.046,
            stop_loss=4421.98508,
            take_profit=4347.499,
            playbook="h1_impulse_retest_v1",
            target_mode="wave_base",
        )

        self.assertAlmostEqual(6.49426, rr, places=5)
        with self.assertRaises(HTTPException):
            validate_manual_ai_levels(
                "sell",
                entry_price=4412.046,
                stop_loss=4421.98508,
                take_profit=4347.499,
                playbook="h1_impulse_retest_v1",
                target_mode="fixed_rr",
            )

    def test_h1_impulse_preview_is_read_only_and_uses_historical_atr(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_h1_impulse_preview_candles(db_path)
            client = authenticated_test_client(root, config_path)
            try:
                response = client.post(
                    "/api/playbooks/h1-impulse-retest/preview",
                    json={
                        "symbol": "XAUUSD",
                        "signal_candle_time": "2026-08-20T15:00:00+00:00",
                        "as_of": "2026-08-20T16:00:00+00:00",
                        "risk_reward": 2.5,
                    },
                )
            finally:
                client._semi_bot_env_patch.stop()  # type: ignore[attr-defined]

            with connect(db_path) as conn:
                idea_count = conn.execute("SELECT COUNT(*) AS count FROM trade_ideas").fetchone()["count"]

        payload = response.json()
        self.assertEqual(200, response.status_code)
        self.assertTrue(payload["preview_only"])
        self.assertEqual("h1_impulse_retest_v1", payload["playbook"])
        self.assertEqual("eligible", payload["status"])
        self.assertEqual("previous_h1_high", payload["entry_source"])
        self.assertEqual("fixed_rr", payload["target_mode"])
        self.assertEqual("fixed_rr", payload["target_plan"]["applied_mode"])
        self.assertEqual("2026-08-20T15:00:00+00:00", payload["signal_candle_time"])
        self.assertEqual(14, payload["atr_period"])
        self.assertEqual("unfilled", payload["outcome"]["status"])
        self.assertGreater(payload["atr"], 0)
        self.assertEqual(0, idea_count)

    def test_account_daily_profit_controls_and_close_all_command(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            now = datetime.now(UTC).isoformat()
            with connect(db_path) as conn:
                init_db(conn)
                conn.execute(
                    "INSERT INTO account_snapshots (account_label, balance, equity, currency, snapshot_at) VALUES ('FTMO 100K', 99000, 99500, 'USD', ?)",
                    (now,),
                )
                conn.execute(
                    """
                    INSERT INTO account_execution_controls
                        (account_label, requested_enabled, effective_enabled, hard_enabled, worker_status, heartbeat_at, updated_at)
                    VALUES ('FTMO 100K', 1, 1, 1, 'online', ?, ?)
                    """,
                    (now, now),
                )
                conn.execute(
                    """
                    INSERT INTO account_daily_metrics VALUES
                        ('FTMO 100K', '2026-08-02', 'Europe/Prague', '2026-08-01T22:00:00+00:00',
                         99000, 99000, 99500, 500, 0.5, 100000, 'mt5_deal_history', ?)
                    """,
                    (now,),
                )
                conn.commit()
            client = authenticated_test_client(root, config_path)
            try:
                listing = client.get("/api/accounts")
                disabled = client.patch("/api/accounts/FTMO%20100K/execution", json={"enabled": False})
                enabled = client.patch("/api/accounts/FTMO%20100K/execution", json={"enabled": True})
                partial = client.patch(
                    "/api/accounts/FTMO%20100K/partial-take-profit",
                    json={"enabled": True, "trigger_r": 1.0},
                )
                manual_lock = client.patch(
                    "/api/accounts/FTMO%20100K/manual-trading-lock",
                    json={"enabled": True, "reason": "discipline"},
                )
                listing_after_partial = client.get("/api/accounts")
                manual_unlock = client.patch(
                    "/api/accounts/FTMO%20100K/manual-trading-lock",
                    json={"enabled": False},
                )
                close_all = client.post(
                    "/api/accounts/FTMO%20100K/close-all",
                    json={"idempotency_key": "close-ftmo-once", "include_manual_positions": True},
                )
                duplicate = client.post(
                    "/api/accounts/FTMO%20100K/close-all",
                    json={"idempotency_key": "close-ftmo-once"},
                )
            finally:
                client._semi_bot_env_patch.stop()  # type: ignore[attr-defined]
            with connect(db_path) as conn:
                command = conn.execute(
                    "SELECT command_type, payload_json FROM account_execution_commands WHERE id = ?",
                    (close_all.json()["command_id"],),
                ).fetchone()
                execution_after_close = conn.execute(
                    "SELECT requested_enabled, effective_enabled FROM account_execution_controls WHERE account_label = 'FTMO 100K'"
                ).fetchone()

        account = listing.json()["accounts"][0]
        self.assertEqual(200, listing.status_code)
        self.assertEqual(500, account["daily"]["profit"])
        self.assertEqual(0.5, account["daily"]["profit_pct"])
        self.assertTrue(account["execution"]["effective_enabled"])
        self.assertTrue(account["partial_take_profit"]["enabled"])
        self.assertEqual(1.25, account["partial_take_profit"]["trigger_r"])
        self.assertEqual(200, disabled.status_code)
        self.assertEqual(200, enabled.status_code)
        self.assertEqual(200, partial.status_code)
        self.assertEqual(1.0, partial.json()["partial_take_profit"]["trigger_r"])
        self.assertEqual(1.0, listing_after_partial.json()["accounts"][0]["partial_take_profit"]["trigger_r"])
        self.assertEqual(200, manual_lock.status_code)
        self.assertTrue(manual_lock.json()["requested_enabled"])
        self.assertTrue(listing_after_partial.json()["accounts"][0]["manual_trading_lock"]["requested_enabled"])
        self.assertFalse(listing_after_partial.json()["accounts"][0]["manual_trading_lock"]["effective_enabled"])
        self.assertEqual(200, manual_unlock.status_code)
        self.assertFalse(manual_unlock.json()["requested_enabled"])
        self.assertEqual(202, close_all.status_code)
        self.assertTrue(close_all.json()["include_manual_positions"])
        self.assertEqual(close_all.json()["command_id"], duplicate.json()["command_id"])
        self.assertEqual("close_all_positions", command["command_type"])
        self.assertTrue(json.loads(command["payload_json"])["include_manual_positions"])
        self.assertTrue(execution_after_close["requested_enabled"])
        self.assertTrue(execution_after_close["effective_enabled"])

    def test_trade_management_action_queues_exact_account_command(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            now = datetime.now(UTC).isoformat()
            with connect(db_path) as conn:
                init_db(conn)
                conn.execute(
                    """
                    INSERT INTO trade_ideas (
                        id, symbol, direction, playbook, status, related_zone_ids_json,
                        context_snapshot_json, suggested_stop_loss, suggested_take_profit_json,
                        risk_reward, created_at
                    ) VALUES ('managed-idea', 'XAUUSD', 'long', 'h1_impulse_retest_v1',
                              'filled', '[]', '{}', 2990, '[3020]', 2, ?)
                    """,
                    (now,),
                )
                conn.execute(
                    """
                    INSERT INTO trade_orders (
                        id, trade_idea_id, account_label, symbol, side, order_type, status,
                        entry_price, stop_loss, take_profit_json, quantity, opened_at,
                        source, metadata_json, created_at, updated_at
                    ) VALUES ('managed-order', 'managed-idea', 'Exness Personal', 'XAUUSD',
                              'buy', 'market', 'filled', 3000, 2990, '[3020]', 0.2, ?,
                              'live', '{"broker_position_id":"11111"}', ?, ?)
                    """,
                    (now, now, now),
                )
                conn.commit()
            client = authenticated_test_client(root, config_path)
            try:
                queued = client.post(
                    "/api/trades/managed-order/actions",
                    json={"action": "partial_50_be", "idempotency_key": "managed-order-partial-once"},
                )
                duplicate = client.post(
                    "/api/trades/managed-order/actions",
                    json={"action": "partial_50_be", "idempotency_key": "managed-order-partial-once"},
                )
            finally:
                client._semi_bot_env_patch.stop()  # type: ignore[attr-defined]
            with connect(db_path) as conn:
                command = conn.execute(
                    "SELECT account_label, command_type, payload_json FROM account_execution_commands WHERE id = ?",
                    (queued.json()["command_id"],),
                ).fetchone()

        self.assertEqual(202, queued.status_code)
        self.assertEqual(queued.json()["command_id"], duplicate.json()["command_id"])
        self.assertEqual("Exness Personal", command["account_label"])
        self.assertEqual("partial_trade_position", command["command_type"])
        self.assertEqual("managed-order", json.loads(command["payload_json"])["trade_order_id"])

    def test_trade_management_action_rejects_closed_or_backtest_trade(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_trade_filter_data(db_path)
            client = authenticated_test_client(root, config_path)
            try:
                response = client.post("/api/trades/order-narrow/actions", json={"action": "close_now"})
            finally:
                client._semi_bot_env_patch.stop()  # type: ignore[attr-defined]

        self.assertEqual(409, response.status_code)
        self.assertIn("live trades", response.json()["detail"])

    def test_init_db_preserves_legacy_weekly_journal_content(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with connect(db_path) as conn:
                conn.executescript(
                    """
                    CREATE TABLE weekly_journals (
                        id TEXT PRIMARY KEY,
                        week_start TEXT NOT NULL UNIQUE,
                        week_end TEXT NOT NULL,
                        content TEXT NOT NULL DEFAULT '',
                        discipline_score INTEGER NOT NULL,
                        fomo_score INTEGER NOT NULL,
                        revenge_score INTEGER NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    INSERT INTO weekly_journals (
                        id, week_start, week_end, content,
                        discipline_score, fomo_score, revenge_score,
                        created_at, updated_at
                    )
                    VALUES (
                        'legacy-week', '2026-07-20', '2026-07-26',
                        'Noi dung nhat ky cu khong duoc mat.',
                        8, 4, 2, '2026-07-26T00:00:00+00:00', '2026-07-26T00:00:00+00:00'
                    );
                    """
                )
                conn.commit()
                init_db(conn)
                row = conn.execute(
                    "SELECT content, content_format, icon, achieved_r FROM weekly_journals WHERE id = 'legacy-week'"
                ).fetchone()

        self.assertEqual(row["content"], "Noi dung nhat ky cu khong duoc mat.")
        self.assertEqual(row["content_format"], "plain_text")
        self.assertEqual(row["icon"], "📝")
        self.assertEqual(row["achieved_r"], 0)

    def test_weekly_journal_can_create_update_and_list_old_weeks(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            client = authenticated_test_client(root, config_path)

            old_week = client.put(
                "/api/weekly-journals/2026-06-01",
                json={
                    "content": "Tuan cu: toi da giu dung ke hoach.",
                    "content_format": "rich_text",
                    "icon": "🎯",
                    "discipline_score": 7,
                    "fomo_score": 4,
                    "revenge_score": 2,
                    "achieved_r": 1.75,
                },
            )
            newer_week = client.put(
                "/api/weekly-journals/2026-07-20",
                json={
                    "content": "Tuan nay.",
                    "discipline_score": 6,
                    "fomo_score": 5,
                    "revenge_score": 3,
                    "achieved_r": -0.5,
                },
            )
            updated_week = client.put(
                "/api/weekly-journals/2026-06-01",
                json={
                    "content": "Noi dung da sua.",
                    "discipline_score": 8,
                    "fomo_score": 3,
                    "revenge_score": 1,
                    "achieved_r": 2.35,
                },
            )
            listing = client.get("/api/weekly-journals")
            fetched = client.get("/api/weekly-journals/2026-06-01")

            with connect(db_path) as conn:
                count = conn.execute("SELECT COUNT(*) AS count FROM weekly_journals").fetchone()["count"]

        self.assertEqual(old_week.status_code, 200)
        self.assertEqual(old_week.json()["content_format"], "rich_text")
        self.assertEqual(old_week.json()["icon"], "🎯")
        self.assertEqual(old_week.json()["week_end"], "2026-06-07")
        self.assertEqual(newer_week.status_code, 200)
        self.assertEqual(updated_week.status_code, 200)
        self.assertEqual(updated_week.json()["id"], old_week.json()["id"])
        self.assertEqual(updated_week.json()["discipline_score"], 8)
        self.assertEqual(updated_week.json()["achieved_r"], 2.35)
        self.assertEqual(fetched.json()["content"], "Noi dung da sua.")
        self.assertEqual(listing.json()["total"], 2)
        self.assertEqual(
            [journal["week_start"] for journal in listing.json()["journals"]],
            ["2026-07-20", "2026-06-01"],
        )
        self.assertEqual(count, 2)

    def test_weekly_journal_rejects_non_monday_and_invalid_scores(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            client = authenticated_test_client(root, config_path)
            payload = {
                "content": "",
                "discipline_score": 7,
                "fomo_score": 4,
                "revenge_score": 2,
                "achieved_r": 0,
            }

            non_monday = client.put("/api/weekly-journals/2026-07-21", json=payload)
            invalid_score = client.put(
                "/api/weekly-journals/2026-07-20",
                json={**payload, "fomo_score": 11},
            )

        self.assertEqual(non_monday.status_code, 422)
        self.assertEqual(non_monday.json()["detail"], "week_start must be a Monday")
        self.assertEqual(invalid_score.status_code, 422)

    def test_init_db_backfills_old_null_valid_until_zone_as_expired(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with connect(db_path) as conn:
                init_db(conn)
                insert_legacy_null_expiry_zone(conn, created_at="2026-01-01T00:00:00+00:00")
                conn.commit()
                init_db(conn)
                row = conn.execute("SELECT * FROM price_zones WHERE id = 'legacy-null'").fetchone()

        self.assertEqual(row["status"], "expired")
        self.assertIsNotNone(row["valid_until"])
        self.assertEqual(row["end_time"], row["valid_until"])

    def test_init_db_backfills_recent_null_valid_until_zone_as_active(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            created_at = (datetime.now(UTC) - timedelta(hours=1)).replace(microsecond=0).isoformat()
            with connect(db_path) as conn:
                init_db(conn)
                insert_legacy_null_expiry_zone(conn, created_at=created_at)
                conn.commit()
                init_db(conn)
                row = conn.execute("SELECT * FROM price_zones WHERE id = 'legacy-null'").fetchone()

        self.assertEqual(row["status"], "active")
        self.assertIsNotNone(row["valid_until"])
        self.assertEqual(row["end_time"], row["valid_until"])

    def test_init_db_hard_deletes_m15_price_zones_only(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with connect(db_path) as conn:
                init_db(conn)
                insert_price_zone(conn, zone_id="m15-zone", timeframe="M15")
                insert_price_zone(conn, zone_id="h1-zone", timeframe="H1")
                conn.execute(
                    """
                    INSERT INTO candles (
                        id, symbol, timeframe, open_time, close_time, open, high, low, close, volume, source
                    )
                    VALUES ('m15-candle', 'XAUUSD', 'M15', '2026-01-01T00:00:00+00:00',
                            '2026-01-01T00:15:00+00:00', 2000, 2002, 1999, 2001, 100, 'test')
                    """
                )
                conn.commit()
                init_db(conn)
                zones = conn.execute("SELECT id FROM price_zones ORDER BY id").fetchall()
                candles = conn.execute("SELECT COUNT(*) AS count FROM candles WHERE timeframe = 'M15'").fetchone()

        self.assertEqual([row["id"] for row in zones], ["h1-zone"])
        self.assertEqual(candles["count"], 1)

    def test_chart_endpoint_returns_payload(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)

            client = authenticated_test_client(root, config_path)
            response = client.get("/api/chart?symbol=XAUUSD&timeframe=M15&limit=2")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["symbol"], "XAUUSD")
        self.assertEqual(payload["timeframe"], "M15")
        self.assertEqual(len(payload["layers"]["candles"]), 2)
        self.assertEqual(payload["layers"]["structure_timeframe"], "H1")
        self.assertEqual(payload["layers"]["structure"][0]["id"], "h1-s1")
        self.assertEqual(payload["layers"]["m15_triggers"], [])

    def test_h1_chart_returns_m15_trigger_overlay_for_h1_zone_touch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            seed_zone(db_path)

            client = authenticated_test_client(root, config_path)
            response = client.get("/api/chart?symbol=XAUUSD&timeframe=H1&limit=2")

        self.assertEqual(response.status_code, 200)
        triggers = response.json()["layers"]["m15_triggers"]
        self.assertEqual(len(triggers), 2)
        self.assertEqual(triggers[0]["zone_id"], "z1")
        self.assertEqual(triggers[0]["status"], "touch")
        self.assertEqual(triggers[0]["time"], "2026-01-01T00:00:00+00:00")

    def test_chart_endpoint_supports_start_index_window(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)

            client = authenticated_test_client(root, config_path)
            response = client.get("/api/chart?symbol=XAUUSD&timeframe=M15&limit=1&start_index=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["range"]["start_index"], 1)
        self.assertEqual(len(payload["layers"]["candles"]), 1)
        self.assertEqual(payload["layers"]["candles"][0]["time"], "2026-01-01T00:15:00+00:00")

    def test_health_endpoint(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "trading.toml"
            write_test_config(config_path, root / "test.sqlite3")

            client = authenticated_test_client(root, config_path)
            response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_replay_timeline_endpoint_returns_ordered_candle_times(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)

            client = authenticated_test_client(root, config_path)
            response = client.get("/api/replay/timeline?symbol=XAUUSD&timeframe=M15&limit=2")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(
            payload["times"],
            ["2026-01-01T00:00:00+00:00", "2026-01-01T00:15:00+00:00"],
        )

    def test_replay_timeline_supports_start_index_window(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)

            client = authenticated_test_client(root, config_path)
            response = client.get("/api/replay/timeline?symbol=XAUUSD&timeframe=M15&limit=1&start_index=1")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["start_index"], 1)
        self.assertEqual(payload["total_count"], 2)
        self.assertEqual(payload["times"], ["2026-01-01T00:15:00+00:00"])

    def test_replay_timeline_accepts_large_limit(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)

            client = authenticated_test_client(root, config_path)
            response = client.get("/api/replay/timeline?symbol=XAUUSD&timeframe=M15&limit=10000")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["limit"], 10000)
        self.assertEqual(payload["count"], 2)

    def test_trade_review_can_be_saved_and_returned_with_history(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            seed_trade(db_path)

            client = authenticated_test_client(root, config_path)
            save_response = client.put(
                "/api/trades/order-1/review",
                json={
                    "grade": "B",
                    "verdict": "should_skip",
                    "mistake_tags": ["weak_breakout", "weak_breakout", "bad_entry"],
                    "should_trade_again": "conditional",
                    "comment": "Breakout qua zone qua yeu.",
                    "strategy_review": {
                        "setup_validity": "weak",
                        "entry_quality": "late",
                        "strategy_tags": ["weak_zone", "late_entry", "weak_zone"],
                    },
                    "operator_review": {
                        "operator_state": "calm",
                        "operator_action": "no_intervention",
                        "followed_plan": "yes",
                        "emotion_score": 2,
                        "operator_tags": ["trusted_bot"],
                    },
                },
            )
            history_response = client.get("/api/trades?symbol=XAUUSD&timeframe=M15&limit=5&backtest=true")

        self.assertEqual(save_response.status_code, 200)
        review = save_response.json()
        self.assertEqual(review["grade"], "B")
        self.assertEqual(review["verdict"], "should_skip")
        self.assertEqual(review["mistake_tags"], ["weak_breakout", "bad_entry"])
        self.assertEqual(review["strategy_review"]["setup_validity"], "weak")
        self.assertEqual(review["strategy_review"]["strategy_tags"], ["weak_zone", "late_entry"])
        self.assertEqual(review["operator_review"]["operator_action"], "no_intervention")
        self.assertEqual(review["operator_review"]["emotion_score"], 2)

        self.assertEqual(history_response.status_code, 200)
        trade = history_response.json()["trades"][0]
        self.assertEqual(trade["review"]["verdict"], "should_skip")
        self.assertEqual(trade["review"]["comment"], "Breakout qua zone qua yeu.")
        self.assertEqual(trade["review"]["strategy_review"]["entry_quality"], "late")
        self.assertEqual(trade["review"]["operator_review"]["followed_plan"], "yes")

    def test_trade_history_includes_manual_ai_plan_lifecycle(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            seed_trade(db_path)
            with connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO manual_ai_plans (
                        id, client_id, account_label, symbol, side, status, execution_state,
                        entry_price, stop_loss, take_profit, risk_pct, risk_reward, expires_at,
                        trade_idea_id, created_at, updated_at
                    )
                    VALUES (
                        'plan-1', 'client-1', 'Default', 'XAUUSD', 'buy', 'expired', 'expired',
                        2001, 1995, 2013, 1, 2, '2026-01-01T00:45:00+00:00',
                        'idea-1', '2026-01-01T00:00:00+00:00', '2026-01-01T00:45:00+00:00'
                    )
                    """
                )
                conn.commit()

            client = authenticated_test_client(root, config_path)
            history_response = client.get("/api/trades?symbol=XAUUSD&timeframe=M15&limit=5&backtest=true")

        self.assertEqual(history_response.status_code, 200)
        trade = history_response.json()["trades"][0]
        self.assertEqual(trade["manual_ai_plan_status"], "expired")
        self.assertEqual(trade["manual_ai_expires_at"], "2026-01-01T00:45:00+00:00")

    def test_trade_visibility_can_be_hidden_and_restored(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            seed_trade(db_path)

            client = authenticated_test_client(root, config_path)
            initial = client.get("/api/trades?symbol=XAUUSD&timeframe=M15&limit=5")
            hide = client.patch("/api/trades/order-1/visibility", json={"hidden_on_chart": True})
            hidden_history = client.get("/api/trades?symbol=XAUUSD&timeframe=M15&limit=5")
            hidden_chart = client.get("/api/chart?symbol=XAUUSD&timeframe=M15&limit=2")
            restore = client.patch("/api/trades/order-1/visibility", json={"hidden_on_chart": False})
            restored_history = client.get("/api/trades?symbol=XAUUSD&timeframe=M15&limit=5")
            missing = client.patch("/api/trades/missing/visibility", json={"hidden_on_chart": True})

        self.assertFalse(initial.json()["trades"][0]["hidden_on_chart"])
        self.assertEqual(hide.status_code, 200)
        self.assertTrue(hide.json()["hidden_on_chart"])
        self.assertTrue(hidden_history.json()["trades"][0]["hidden_on_chart"])
        self.assertTrue(hidden_chart.json()["layers"]["trades"][0]["hidden_on_chart"])
        self.assertEqual(restore.status_code, 200)
        self.assertFalse(restored_history.json()["trades"][0]["hidden_on_chart"])
        self.assertEqual(missing.status_code, 404)

    def test_trade_review_attachment_upload_list_file_and_delete(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            seed_trade(db_path)

            old_cwd = Path.cwd()
            os.chdir(root)
            try:
                client = authenticated_test_client(root, config_path)
                upload_response = client.post(
                    "/api/trades/order-1/attachments",
                    json={
                        "kind": "review",
                        "image_data": ONE_PIXEL_PNG_DATA_URL,
                        "caption": "entry review",
                        "chart_symbol": "XAUUSD",
                        "chart_timeframe": "H1",
                    },
                )
                attachment = upload_response.json()
                list_response = client.get("/api/trades/order-1/attachments")
                file_response = client.get(f"/api/trades/order-1/attachments/{attachment['id']}/file")
                delete_response = client.delete(f"/api/trades/order-1/attachments/{attachment['id']}")
                list_after_delete = client.get("/api/trades/order-1/attachments")
            finally:
                os.chdir(old_cwd)

        self.assertEqual(upload_response.status_code, 200)
        self.assertEqual(attachment["kind"], "review")
        self.assertEqual(attachment["caption"], "entry review")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.json()), 1)
        self.assertEqual(file_response.status_code, 200)
        self.assertEqual(file_response.content[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(delete_response.status_code, 200)
        self.assertEqual(list_after_delete.json(), [])

    def test_journal_patterns_aggregates_structured_review_and_trade_metadata(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            seed_trade_filter_data(db_path)

            client = authenticated_test_client(root, config_path)
            client.put(
                "/api/trades/order-wide/review",
                json={
                    "grade": "A",
                    "verdict": "good_trade",
                    "mistake_tags": [],
                    "should_trade_again": "yes",
                    "comment": "",
                    "strategy_review": {"strategy_tags": ["clean_reject"]},
                    "operator_review": {"operator_action": "no_intervention", "operator_state": "calm", "followed_plan": "yes"},
                },
            )
            response = client.get("/api/journal/patterns?backtest=true")

        self.assertEqual(response.status_code, 200)
        groups = response.json()["groups"]
        clean_reject = next(row for row in groups["strategy_tags"] if row["key"] == "clean_reject")
        support = next(row for row in groups["zone_type"] if row["key"] == "support")
        no_intervention = next(row for row in groups["operator_action"] if row["key"] == "no_intervention")
        self.assertEqual(clean_reject["trades"], 1)
        self.assertEqual(clean_reject["total_r"], 2.0)
        self.assertEqual(support["trades"], 2)
        self.assertEqual(support["total_r"], 1.0)
        self.assertEqual(no_intervention["trades"], 1)

    def test_trade_history_supports_zone_reaction_and_sl_size_filters(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            seed_trade_filter_data(db_path)

            client = authenticated_test_client(root, config_path)
            filtered_response = client.get(
                "/api/trades?symbol=XAUUSD&timeframe=M15&limit=10&backtest=true"
                "&zone_type=support&reaction=reject&sort=sl_size_desc"
            )
            fvg_response = client.get(
                "/api/trades?symbol=XAUUSD&timeframe=M15&limit=10&backtest=true&zone_type=fvg"
            )

        self.assertEqual(filtered_response.status_code, 200)
        filtered = filtered_response.json()["trades"]
        self.assertEqual([trade["id"] for trade in filtered], ["order-wide", "order-narrow"])
        self.assertEqual([abs(trade["entry_price"] - trade["stop_loss"]) for trade in filtered], [10, 2])

        self.assertEqual(fvg_response.status_code, 200)
        fvg = fvg_response.json()["trades"]
        self.assertEqual([trade["id"] for trade in fvg], ["order-fvg"])

    def test_trade_history_supports_trade_id_search(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            seed_trade_filter_data(db_path)

            client = authenticated_test_client(root, config_path)
            response = client.get(
                "/api/trades?symbol=XAUUSD&timeframe=M15&limit=10&backtest=true&trade_id=narrow"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual([trade["id"] for trade in payload["trades"]], ["order-narrow"])

    def test_trade_history_supports_account_label_filter(self) -> None:
        with TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            env_path = root / ".env"
            secret_key = write_test_env(env_path)
            seed_candles(db_path)
            seed_live_account_trade_data(db_path)

            headers = auth_headers(secret_key)
            with patch.dict(os.environ, {"SECRET_KEY": secret_key, "ADMIN_PASSWORD_HASH": "unused-test-hash"}, clear=False):
                with TestClient(create_app(config_path, env_path=env_path)) as client:
                    all_response = client.get("/api/trades?symbol=XAUUSD&timeframe=M15&limit=10&backtest=false", headers=headers)
                    exness_response = client.get(
                        "/api/trades?symbol=XAUUSD&timeframe=M15&limit=10&backtest=false"
                        "&account_label=Exness%20Personal",
                        headers=headers,
                    )
                    ftmo_response = client.get(
                        "/api/trades?symbol=XAUUSD&timeframe=M15&limit=10&backtest=false"
                        "&account_label=FTMO%20Demo",
                        headers=headers,
                    )

        self.assertEqual(all_response.status_code, 200)
        all_payload = all_response.json()
        self.assertEqual(all_payload["total"], 2)
        self.assertEqual(
            {trade["account_label"] for trade in all_payload["trades"]},
            {"Exness Personal", "FTMO Demo"},
        )

        self.assertEqual(exness_response.status_code, 200)
        exness_payload = exness_response.json()
        self.assertEqual(exness_payload["total"], 1)
        self.assertEqual(exness_payload["trades"][0]["id"], "order-exness")
        self.assertEqual(exness_payload["trades"][0]["account_label"], "Exness Personal")

        self.assertEqual(ftmo_response.status_code, 200)
        ftmo_payload = ftmo_response.json()
        self.assertEqual(ftmo_payload["total"], 1)
        self.assertEqual(ftmo_payload["trades"][0]["id"], "order-ftmo")
        self.assertEqual(ftmo_payload["trades"][0]["account_label"], "FTMO Demo")

    def test_trade_history_includes_live_pending_and_never_filled_limits(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            now = "2026-08-28T14:30:00+00:00"
            with connect(db_path) as conn:
                init_db(conn)
                conn.execute(
                    """
                    INSERT INTO trade_ideas (
                        id, symbol, direction, playbook, status, related_zone_ids_json,
                        context_snapshot_json, suggested_stop_loss, suggested_take_profit_json,
                        risk_reward, created_at
                    ) VALUES ('pending-idea', 'XAUUSD', 'long', 'zone_reaction_v2',
                              'approved', '[]', '{}', 4525, '[4605]', 2, ?)
                    """,
                    (now,),
                )
                conn.execute(
                    """
                    INSERT INTO trade_orders (
                        id, trade_idea_id, account_label, symbol, side, order_type,
                        status, entry_price, stop_loss, take_profit_json, quantity,
                        opened_at, source, metadata_json, created_at, updated_at
                    ) VALUES ('pending-order', 'pending-idea', 'Exness Personal',
                              'XAUUSD', 'buy', 'limit', 'pending_fill', 4551, 4525,
                              '[4605]', 0.4, NULL, 'live', '{}', ?, ?)
                    """,
                    (now, now),
                )
                conn.commit()
            client = authenticated_test_client(root, config_path)
            pending = client.get("/api/trades?symbol=XAUUSD&backtest=false&sort=opened_at_desc")
            with connect(db_path) as conn:
                conn.execute(
                    "UPDATE trade_orders SET status = 'cancelled', closed_at = ?, updated_at = ? WHERE id = 'pending-order'",
                    ("2026-08-28T15:00:00+00:00", "2026-08-28T15:00:00+00:00"),
                )
                conn.commit()
            cancelled = client.get("/api/trades?symbol=XAUUSD&backtest=false&sort=opened_at_desc")
            backtest = client.get("/api/trades?symbol=XAUUSD&backtest=true")

        self.assertEqual(200, pending.status_code)
        self.assertEqual(1, pending.json()["total"])
        self.assertEqual("pending_fill", pending.json()["trades"][0]["status"])
        self.assertIsNone(pending.json()["trades"][0]["opened_at"])
        self.assertIsNone(pending.json()["trades"][0]["chart_index"])
        self.assertEqual("cancelled", cancelled.json()["trades"][0]["status"])
        self.assertEqual(0, backtest.json()["total"])

    def test_chart_replay_recomputes_from_replay_start(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)

            client = authenticated_test_client(root, config_path)
            response = client.get(
                "/api/chart?symbol=XAUUSD&timeframe=M15&limit=2"
                "&replay_start=2026-01-01T00:00:00%2B00:00"
                "&replay_at=2026-01-01T00:00:00%2B00:00"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["layers"]["candles"]), 1)
        self.assertEqual(payload["layers"]["candles"][0]["time"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(payload["replay"]["as_of"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(payload["replay"]["start"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(payload["layers"]["zones"], [])

    def test_zone_override_updates_effective_zone_and_audit_trail(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            seed_zone(db_path)

            client = authenticated_test_client(root, config_path)
            response = client.patch(
                "/api/zones/z1",
                json={
                    "price_low": 1991.5,
                    "price_high": 1994.5,
                    "visual_start": "2026-01-01T00:15:00+00:00",
                    "visual_end": "2026-01-01T00:30:00+00:00",
                    "weight": 0.91,
                    "confidence": 0.88,
                    "status": "active",
                    "no_expiry": True,
                    "reason": "tighten by human",
                },
            )

            with connect(db_path) as conn:
                override_count = conn.execute("SELECT COUNT(*) AS count FROM overrides").fetchone()["count"]
                zone = conn.execute("SELECT * FROM price_zones WHERE id = 'z1'").fetchone()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["price_low"], 1991.5)
        self.assertEqual(payload["price_high"], 1994.5)
        self.assertEqual(payload["visual_start"], "2026-01-01T00:15:00+00:00")
        self.assertEqual(payload["weight"], 0.91)
        self.assertEqual(payload["confidence"], 0.88)
        self.assertEqual(payload["source"], "mixed")
        self.assertIsNotNone(payload["valid_until"])
        self.assertEqual(payload["visual_end"], payload["valid_until"])
        self.assertEqual(override_count, 1)
        self.assertEqual(zone["source"], "mixed")
        self.assertEqual(zone["start_time"], "2026-01-01T00:15:00+00:00")
        self.assertEqual(zone["end_time"], payload["valid_until"])

    def test_disabled_zone_without_end_uses_latest_candle_time(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            seed_zone(db_path)

            client = authenticated_test_client(root, config_path)
            response = client.patch(
                "/api/zones/z1",
                json={
                    "price_low": 1990,
                    "price_high": 1995,
                    "visual_start": "2026-01-01T00:00:00+00:00",
                    "visual_end": None,
                    "weight": 0.7,
                    "confidence": 0.8,
                    "status": "disabled",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "disabled")
        self.assertEqual(payload["visual_end"], "2026-01-01T01:00:00+00:00")

    def test_create_manual_zone_persists_human_entity_and_audit_trail(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)

            client = authenticated_test_client(root, config_path)
            response = client.post(
                "/api/zones",
                json={
                    "symbol": "XAUUSD",
                    "timeframe": "H1",
                    "zone_type": "fvg",
                    "direction": "bullish",
                    "price_low": 1996.5,
                    "price_high": 1999.5,
                    "visual_start": "2026-01-01T00:00:00+00:00",
                    "visual_end": "2026-01-01T01:00:00+00:00",
                    "weight": 0.72,
                    "confidence": 0.9,
                    "reason": "manual replay note",
                },
            )

            with connect(db_path) as conn:
                override_count = conn.execute("SELECT COUNT(*) AS count FROM overrides").fetchone()["count"]
                zone_count = conn.execute("SELECT COUNT(*) AS count FROM price_zones").fetchone()["count"]

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["type"], "fvg")
        self.assertEqual(payload["direction"], "bullish")
        self.assertEqual(payload["source"], "human")
        self.assertEqual(payload["detector"], "human_manual_v1")
        self.assertEqual(payload["weight"], 0.72)
        self.assertEqual(payload["status"], "active")
        self.assertIsNotNone(payload["valid_until"])
        self.assertEqual(payload["metadata"]["human_created"], True)
        self.assertEqual(payload["metadata"]["trade_modes"], ["reject", "internal_reject"])
        self.assertEqual(zone_count, 1)
        self.assertEqual(override_count, 1)

    def test_liquidity_sweep_mode_requires_directional_liquidity_zone(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            client = authenticated_test_client(root, config_path)
            payload = {
                "symbol": "XAUUSD",
                "timeframe": "H1",
                "zone_type": "liquidity_pool",
                "direction": "bullish",
                "price_low": 1980.0,
                "price_high": 1990.0,
                "visual_start": "2026-01-01T00:00:00+00:00",
                "visual_end": "2026-01-02T00:00:00+00:00",
                "weight": 0.8,
                "confidence": 0.9,
                "trade_modes": ["liquidity_sweep"],
            }

            accepted = client.post("/api/zones", json=payload)
            accepted_sell = client.post(
                "/api/zones",
                json={**payload, "direction": "bearish", "price_low": 2000.0, "price_high": 2010.0},
            )
            rejected = client.post(
                "/api/zones",
                json={**payload, "zone_type": "support"},
            )

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted_sell.status_code, 200)
        self.assertEqual(accepted.json()["metadata"]["trade_modes"], ["liquidity_sweep"])
        self.assertEqual(rejected.status_code, 422)
        self.assertIn("bullish or bearish liquidity_pool", rejected.json()["detail"])

    def test_create_manual_sr_zone_persists_reject_only_default(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)

            client = authenticated_test_client(root, config_path)
            response = client.post(
                "/api/zones",
                json={
                    "symbol": "XAUUSD",
                    "timeframe": "H1",
                    "zone_type": "resistance",
                    "direction": "bearish",
                    "price_low": 2001.0,
                    "price_high": 2005.0,
                    "visual_start": "2026-01-01T00:00:00+00:00",
                    "visual_end": "2026-01-01T01:00:00+00:00",
                    "weight": 0.8,
                    "confidence": 1.0,
                },
            )
            chart = client.get("/api/chart?symbol=XAUUSD&timeframe=M15&limit=2")
            active_chart = client.get("/api/chart?symbol=XAUUSD&timeframe=M15&limit=2&active_zones_only=true")

            with connect(db_path) as conn:
                row = conn.execute("SELECT metadata_json FROM price_zones").fetchone()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "draft")
        self.assertIsNone(response.json()["valid_until"])
        self.assertEqual(response.json()["metadata"]["activation_review_version"], 1)
        self.assertEqual(response.json()["metadata"]["trade_modes"], ["reject"])
        self.assertEqual(json.loads(row["metadata_json"])["trade_modes"], ["reject"])
        self.assertEqual(chart.json()["layers"]["zones"][0]["status"], "draft")
        self.assertEqual(chart.json()["layers"]["zones"][0]["visual_end"], "2026-01-01T01:00:00+00:00")
        self.assertEqual(active_chart.json()["layers"]["zones"], [])

    def test_import_zones_creates_all_payloads_as_one_request(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            client = authenticated_test_client(root, config_path)

            response = client.post(
                "/api/zones/import",
                json=zone_import_envelope(
                    [
                        zone_import_payload("support", "bullish", 1980.0, 1985.0),
                        zone_import_payload("resistance", "bearish", 2010.0, 2015.0),
                    ]
                ),
            )
            with connect(db_path) as conn:
                zone_count = conn.execute("SELECT COUNT(*) AS count FROM price_zones").fetchone()["count"]
                override_count = conn.execute("SELECT COUNT(*) AS count FROM overrides").fetchone()["count"]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["created_count"], 2)
        self.assertEqual(response.json()["draft_count"], 2)
        self.assertEqual([zone["status"] for zone in response.json()["zones"]], ["draft", "draft"])
        self.assertEqual(zone_count, 2)
        self.assertEqual(override_count, 2)

    def test_import_zones_rejects_database_duplicate_without_creating_anything(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            client = authenticated_test_client(root, config_path)
            existing = client.post(
                "/api/zones",
                json=zone_import_payload("support", "bullish", 1990.0, 1995.0),
            )

            response = client.post(
                "/api/zones/import",
                json=zone_import_envelope(
                    [
                        zone_import_payload("resistance", "bearish", 2010.0, 2015.0),
                        zone_import_payload("support", "bullish", 1991.0, 1994.0),
                    ]
                ),
            )
            with connect(db_path) as conn:
                rows = conn.execute("SELECT id FROM price_zones ORDER BY id").fetchall()

        self.assertEqual(existing.status_code, 200)
        self.assertEqual(response.status_code, 409)
        self.assertIn("duplicate zones", response.json()["detail"]["message"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], existing.json()["id"])

    def test_import_zones_validation_is_atomic(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            client = authenticated_test_client(root, config_path)

            response = client.post(
                "/api/zones/import",
                json=zone_import_envelope(
                    [
                        zone_import_payload("support", "bullish", 1980.0, 1985.0),
                        zone_import_payload("resistance", "bearish", 2015.0, 2010.0),
                    ]
                ),
            )
            with connect(db_path) as conn:
                zone_count = conn.execute("SELECT COUNT(*) AS count FROM price_zones").fetchone()["count"]

        self.assertEqual(response.status_code, 422)
        self.assertEqual(zone_count, 0)

    def test_draft_sr_zone_requires_questionnaire_before_activation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            client = authenticated_test_client(root, config_path)
            created = client.post(
                "/api/zones",
                json={
                    "symbol": "XAUUSD",
                    "timeframe": "H1",
                    "zone_type": "support",
                    "direction": "bullish",
                    "price_low": 1990.0,
                    "price_high": 1995.0,
                    "visual_start": "2026-01-01T00:00:00+00:00",
                    "visual_end": "2026-01-01T01:00:00+00:00",
                    "weight": 0.8,
                    "confidence": 1.0,
                    "status": "active",
                },
            )
            zone_id = created.json()["id"]
            bypass = client.patch(
                f"/api/zones/{zone_id}",
                json={
                    "price_low": 1990.0,
                    "price_high": 1995.0,
                    "visual_start": "2026-01-01T00:00:00+00:00",
                    "visual_end": "2026-01-01T01:00:00+00:00",
                    "weight": 0.8,
                    "confidence": 1.0,
                    "status": "active",
                },
            )
            incomplete = client.post(
                f"/api/zones/{zone_id}/confirm",
                json={
                    "short_term_trend": "bullish",
                },
            )

        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json()["status"], "draft")
        self.assertEqual(bypass.status_code, 409)
        self.assertEqual(incomplete.status_code, 422)

    def test_confirm_draft_sr_zone_persists_review_and_activates(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            client = authenticated_test_client(root, config_path)
            created = client.post(
                "/api/zones",
                json={
                    "symbol": "XAUUSD",
                    "timeframe": "H1",
                    "zone_type": "resistance",
                    "direction": "bearish",
                    "price_low": 2001.0,
                    "price_high": 2005.0,
                    "visual_start": "2026-01-01T00:00:00+00:00",
                    "visual_end": "2027-01-01T01:00:00+00:00",
                    "weight": 0.8,
                    "confidence": 1.0,
                },
            )
            zone_id = created.json()["id"]
            confirmed = client.post(
                f"/api/zones/{zone_id}/confirm",
                json={
                    "short_term_trend": "bearish",
                    "medium_term_trend": "neutral",
                    "swing_location": "inside_zone",
                    "thesis_reasons": ["value_entry_outside_swing", "structure_flip"],
                    "emotion_state": "calm",
                    "comment": "Wait for price; do not chase.",
                },
            )
            with connect(db_path) as conn:
                row = conn.execute("SELECT status, valid_until, metadata_json FROM price_zones WHERE id = ?", (zone_id,)).fetchone()
                audit = conn.execute(
                    "SELECT override_type FROM overrides WHERE target_entity_id = ? AND override_type = 'activate_draft_zone'",
                    (zone_id,),
                ).fetchone()

        self.assertEqual(confirmed.status_code, 200)
        payload = confirmed.json()
        self.assertEqual(payload["status"], "active")
        self.assertEqual(payload["valid_until"], "2027-01-01T01:00:00+00:00")
        self.assertEqual(payload["visual_end"], "2027-01-01T01:00:00+00:00")
        review = payload["metadata"]["activation_review"]
        self.assertEqual(review["swing_type"], "swing_high")
        self.assertEqual(review["thesis_reasons"], ["value_entry_outside_swing", "structure_flip"])
        self.assertNotIn("fomo_score", review)
        self.assertNotIn("revenge_score", review)
        self.assertEqual(row["status"], "active")
        self.assertIsNotNone(row["valid_until"])
        self.assertEqual(json.loads(row["metadata_json"])["activation_review"]["emotion_state"], "calm")
        self.assertEqual(audit["override_type"], "activate_draft_zone")

    def test_confirm_rejects_draft_whose_visual_end_is_in_the_past(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            client = authenticated_test_client(root, config_path)
            created = client.post(
                "/api/zones",
                json={
                    "symbol": "XAUUSD",
                    "timeframe": "H1",
                    "zone_type": "support",
                    "direction": "bullish",
                    "price_low": 1990.0,
                    "price_high": 1995.0,
                    "visual_start": "2026-01-01T00:00:00+00:00",
                    "visual_end": "2026-01-01T01:00:00+00:00",
                },
            )
            response = client.post(
                f"/api/zones/{created.json()['id']}/confirm",
                json={
                    "short_term_trend": "bullish",
                    "medium_term_trend": "neutral",
                    "swing_location": "near_zone",
                    "thesis_reasons": ["follow_short_term_trend"],
                    "emotion_state": "calm",
                    "comment": "",
                },
            )

        self.assertEqual(response.status_code, 409)
        self.assertIn("visual_end is in the past", response.json()["detail"])

    def test_delete_zone_marks_deleted_and_hides_from_chart(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            seed_zone(db_path)

            client = authenticated_test_client(root, config_path)
            response = client.delete("/api/zones/z1?reason=manual%20delete")
            chart_response = client.get("/api/chart?symbol=XAUUSD&timeframe=M15&limit=2")

            with connect(db_path) as conn:
                override_count = conn.execute("SELECT COUNT(*) AS count FROM overrides").fetchone()["count"]
                zone = conn.execute("SELECT * FROM price_zones WHERE id = 'z1'").fetchone()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "deleted")
        self.assertEqual(payload["visual_end"], "2027-01-01T00:00:00+00:00")
        self.assertEqual(payload["source"], "mixed")
        self.assertEqual(override_count, 1)
        self.assertEqual(zone["status"], "deleted")
        self.assertEqual(chart_response.status_code, 200)
        self.assertEqual(chart_response.json()["layers"]["zones"], [])

    def test_context_override_updates_effective_context_and_audit_trail(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_context(db_path)

            client = authenticated_test_client(root, config_path)
            response = client.patch(
                "/api/contexts/H1/bias",
                json={
                    "value": "bullish",
                    "confidence": 0.92,
                    "no_expiry": True,
                    "reason": "manual market read",
                },
            )

            with connect(db_path) as conn:
                override_count = conn.execute("SELECT COUNT(*) AS count FROM overrides").fetchone()["count"]
                context = conn.execute("SELECT * FROM market_contexts WHERE id = 'ctx-bias'").fetchone()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["bot_value"], "bearish")
        self.assertEqual(payload["effective_value"], "bullish")
        self.assertEqual(payload["effective_confidence"], 0.92)
        self.assertEqual(payload["source"], "human")
        self.assertEqual(payload["valid_until"], None)
        self.assertEqual(payload["metadata"]["human_adjusted"], True)
        self.assertEqual(override_count, 1)
        self.assertEqual(context["effective_value"], "bullish")
        self.assertEqual(context["source"], "human")

    def test_context_override_can_reset_to_bot(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_context(db_path, source="human", effective_value="bullish", valid_until=None)

            client = authenticated_test_client(root, config_path)
            response = client.patch(
                "/api/contexts/H1/bias",
                json={
                    "use_bot": True,
                    "reason": "return control",
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["effective_value"], "bearish")
        self.assertEqual(payload["effective_confidence"], 0.77)
        self.assertEqual(payload["source"], "bot")
        self.assertEqual(payload["valid_until"], None)


def write_test_config(config_path: Path, db_path: Path) -> None:
    config_path.write_text(
        f"""
[app]
symbol = "XAUUSD"

[data]
directory = "data"
database = "{db_path.as_posix()}"

[structure.swing.timeframes]
H1 = {{ window = 5 }}
M15 = {{ window = 3 }}
"""
    )


def zone_import_payload(
    zone_type: str,
    direction: str,
    price_low: float,
    price_high: float,
) -> dict[str, object]:
    return {
        "symbol": "XAUUSD",
        "timeframe": "H1",
        "zone_type": zone_type,
        "direction": direction,
        "price_low": price_low,
        "price_high": price_high,
        "visual_start": "2026-07-31T20:00:00+00:00",
        "visual_end": "2027-01-08T20:00:00+00:00",
        "expires_at": "2027-01-08T20:00:00+00:00",
        "weight": 0.8,
        "confidence": 0.8,
        "status": "draft",
        "client_kind": zone_type,
        "reason": "Weekly plan import test",
        "trade_modes": ["reject"],
    }


def zone_import_envelope(payloads: list[dict[str, object]]) -> dict[str, object]:
    return {
        "as_of": "2026-08-01T00:00:00+00:00",
        "duplicate_audit": {"safe_to_import": True, "skipped": []},
        "api_endpoint": "POST /api/zones/import",
        "api_payloads": payloads,
    }


def write_test_env(env_path: Path) -> str:
    secret_key = "test-secret-key-for-api-tests-000000000000"
    env_path.write_text(
        f"""
SECRET_KEY="{secret_key}"
ADMIN_USERNAME="admin"
ADMIN_PASSWORD_HASH="unused-test-hash"
"""
    )
    return secret_key


def auth_headers(secret_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token('admin', secret_key)}"}


def seed_candles(db_path: Path) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        conn.executemany(
            """
            INSERT INTO candles (
                id, symbol, timeframe, open_time, close_time, open, high, low, close, volume, source
            )
            VALUES (?, 'XAUUSD', 'M15', ?, ?, ?, ?, ?, ?, 100, 'test')
            """,
            [
                ("c1", "2026-01-01T00:00:00+00:00", "2026-01-01T00:15:00+00:00", 2000, 2002, 1999, 2001),
                ("c2", "2026-01-01T00:15:00+00:00", "2026-01-01T00:30:00+00:00", 2001, 2004, 2000, 2003),
            ],
        )
        conn.executemany(
            """
            INSERT INTO candles (
                id, symbol, timeframe, open_time, close_time, open, high, low, close, volume, source
            )
            VALUES (?, 'XAUUSD', 'H1', ?, ?, ?, ?, ?, ?, 100, 'test')
            """,
            [
                ("h1-c1", "2026-01-01T00:00:00+00:00", "2026-01-01T01:00:00+00:00", 2000, 2004, 1999, 2003),
                ("h1-c2", "2026-01-01T01:00:00+00:00", "2026-01-01T02:00:00+00:00", 2003, 2005, 2001, 2002),
            ],
        )
        conn.execute(
            """
            INSERT INTO structure_points (
                id, symbol, timeframe, detector, status, point_type, price, event_time,
                confidence, related_zone_ids_json, metadata_json
            )
            VALUES ('h1-s1', 'XAUUSD', 'H1', 'swing_v1', 'confirmed', 'HH', 2005,
                    '2026-01-01T00:15:00+00:00', 1.0, '[]', '{}')
            """
        )
        conn.commit()


def seed_h1_impulse_preview_candles(db_path: Path) -> None:
    start = datetime(2026, 8, 20, tzinfo=UTC)
    rows: list[tuple[object, ...]] = []
    for index in range(14):
        opened = start + timedelta(hours=index)
        rows.append(
            (
                f"preview-base-{index}",
                opened.isoformat(),
                (opened + timedelta(hours=1)).isoformat(),
                100,
                105,
                95,
                100,
            )
        )
    rows.extend(
        [
            (
                "preview-previous",
                (start + timedelta(hours=14)).isoformat(),
                (start + timedelta(hours=15)).isoformat(),
                100,
                106,
                98,
                102,
            ),
            (
                "preview-signal",
                (start + timedelta(hours=15)).isoformat(),
                (start + timedelta(hours=16)).isoformat(),
                101,
                112,
                99,
                111,
            ),
        ]
    )
    with connect(db_path) as conn:
        init_db(conn)
        conn.executemany(
            """
            INSERT INTO candles (
                id, symbol, timeframe, open_time, close_time, open, high, low, close, volume, source
            )
            VALUES (?, 'XAUUSD', 'H1', ?, ?, ?, ?, ?, ?, 100, 'test')
            """,
            rows,
        )
        conn.commit()


def seed_zone(db_path: Path) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        conn.execute(
            """
            INSERT INTO price_zones (
                id, symbol, timeframe, detector, zone_type, direction, price_low, price_high,
                start_time, end_time, valid_from, valid_until, invalidated_at,
                invalidated_by_structure_point_id, detected_at, bot_confidence, bot_weight,
                effective_confidence, effective_weight, status, source, metadata_json
            )
            VALUES ('z1', 'XAUUSD', 'H1', 'sr_v1', 'support', 'bullish', 1999, 2004,
                    '2026-01-01T00:00:00+00:00', '2027-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00',
                    '2027-01-01T00:00:00+00:00', NULL, NULL, '2026-01-01T00:00:00+00:00',
                    0.8, 0.7, 0.8, 0.7, 'active', 'bot', '{}')
            """
        )
        conn.commit()


def insert_price_zone(conn, zone_id: str, timeframe: str) -> None:
    conn.execute(
        """
        INSERT INTO price_zones (
            id, symbol, timeframe, detector, zone_type, direction, price_low, price_high,
            start_time, end_time, valid_from, valid_until, invalidated_at,
            invalidated_by_structure_point_id, detected_at, bot_confidence, bot_weight,
            effective_confidence, effective_weight, status, source, metadata_json
        )
        VALUES (?, 'XAUUSD', ?, 'sr_v1', 'support', 'bullish', 1999, 2004,
                '2026-01-01T00:00:00+00:00', '2027-01-01T00:00:00+00:00',
                '2026-01-01T00:00:00+00:00', '2027-01-01T00:00:00+00:00',
                NULL, NULL, '2026-01-01T00:00:00+00:00',
                0.8, 0.7, 0.8, 0.7, 'active', 'bot', '{}')
        """,
        (zone_id, timeframe),
    )


def insert_legacy_null_expiry_zone(conn, created_at: str) -> None:
    conn.execute(
        """
        INSERT INTO price_zones (
            id, symbol, timeframe, detector, zone_type, direction, price_low, price_high,
            start_time, end_time, valid_from, valid_until, invalidated_at,
            invalidated_by_structure_point_id, detected_at, bot_confidence, bot_weight,
            effective_confidence, effective_weight, status, source, metadata_json, created_at, updated_at
        )
        VALUES ('legacy-null', 'XAUUSD', 'H1', 'human_manual_v1', 'support', 'bullish', 1990, 1995,
                ?, NULL, ?, NULL, NULL, NULL, ?,
                0.8, 0.7, 0.8, 0.7, 'active', 'human', '{}', ?, ?)
        """,
        (created_at, created_at, created_at, created_at, created_at),
    )


def seed_trade(db_path: Path) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        conn.execute(
            """
            INSERT INTO trade_ideas (
                id, symbol, direction, playbook, status, entry_zone_id, related_zone_ids_json,
                context_snapshot_json, suggested_entry, suggested_stop_loss,
                suggested_take_profit_json, risk_reward, created_at, expires_at
            )
            VALUES ('idea-1', 'XAUUSD', 'long', 'zone_reaction_v2', 'filled', NULL, '[]',
                    '{}', 2001, 1995, '[2013]', 2.0, '2026-01-01T00:00:00+00:00', NULL)
            """
        )
        conn.execute(
            """
            INSERT INTO trade_orders (
                id, trade_idea_id, symbol, side, order_type, status, entry_price, stop_loss,
                take_profit_json, quantity, opened_at, closed_at, close_price,
                pnl, pnl_r, source, metadata_json, created_at
            )
            VALUES ('order-1', 'idea-1', 'XAUUSD', 'buy', 'market', 'target_hit',
                    2001, 1995, '[2013]', 1, '2026-01-01T00:15:00+00:00',
                    '2026-01-01T01:00:00+00:00', 2013, 2.0, 2.0, 'backtest',
                    '{"backtest": true}', '2026-01-01T00:15:00+00:00')
            """
        )
        conn.commit()


def seed_trade_filter_data(db_path: Path) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        conn.executemany(
            """
            INSERT INTO trade_ideas (
                id, symbol, direction, playbook, status, entry_zone_id, related_zone_ids_json,
                context_snapshot_json, suggested_entry, suggested_stop_loss,
                suggested_take_profit_json, risk_reward, created_at, expires_at
            )
            VALUES (?, 'XAUUSD', ?, 'zone_reaction_v2', 'filled', NULL, '[]',
                    '{}', ?, ?, ?, 2.0, ?, NULL)
            """,
            [
                ("idea-wide", "long", 2000, 1990, "[2020]", "2026-01-01T00:00:00+00:00"),
                ("idea-narrow", "long", 2000, 1998, "[2004]", "2026-01-01T00:15:00+00:00"),
                ("idea-fvg", "short", 2000, 2004, "[1992]", "2026-01-01T00:30:00+00:00"),
            ],
        )
        conn.executemany(
            """
            INSERT INTO trade_orders (
                id, trade_idea_id, symbol, side, order_type, status, entry_price, stop_loss,
                take_profit_json, quantity, opened_at, closed_at, close_price,
                pnl, pnl_r, source, metadata_json, created_at
            )
            VALUES (?, ?, 'XAUUSD', ?, 'market', ?, ?, ?, ?, 1, ?, ?, ?,
                    ?, ?, 'backtest', ?, ?)
            """,
            [
                (
                    "order-wide",
                    "idea-wide",
                    "buy",
                    "target_hit",
                    2000,
                    1990,
                    "[2020]",
                    "2026-01-01T00:15:00+00:00",
                    "2026-01-01T01:00:00+00:00",
                    2020,
                    2.0,
                    2.0,
                    '{"backtest": true, "zone_reaction_state": "reject", "candidate_metadata": {"zone_type": "support"}}',
                    "2026-01-01T00:15:00+00:00",
                ),
                (
                    "order-narrow",
                    "idea-narrow",
                    "buy",
                    "stopped",
                    2000,
                    1998,
                    "[2004]",
                    "2026-01-01T00:30:00+00:00",
                    "2026-01-01T01:15:00+00:00",
                    1998,
                    -1.0,
                    -1.0,
                    '{"backtest": true, "zone_reaction_state": "reject", "candidate_metadata": {"zone_type": "support"}}',
                    "2026-01-01T00:30:00+00:00",
                ),
                (
                    "order-fvg",
                    "idea-fvg",
                    "sell",
                    "target_hit",
                    2000,
                    2004,
                    "[1992]",
                    "2026-01-01T00:45:00+00:00",
                    "2026-01-01T01:30:00+00:00",
                    1992,
                    2.0,
                    2.0,
                    '{"backtest": true, "zone_reaction_state": "fakeout", "candidate_metadata": {"zone_type": "fvg"}}',
                    "2026-01-01T00:45:00+00:00",
                ),
            ],
        )
        conn.commit()


def seed_live_account_trade_data(db_path: Path) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        conn.execute(
            """
            INSERT INTO trade_ideas (
                id, symbol, direction, playbook, status, entry_zone_id, related_zone_ids_json,
                context_snapshot_json, suggested_entry, suggested_stop_loss,
                suggested_take_profit_json, risk_reward, created_at, expires_at
            )
            VALUES ('idea-shared', 'XAUUSD', 'long', 'zone_reaction_v2', 'filled', NULL, '[]',
                    '{}', 2000, 1990, '[2020]', 2.0, '2026-01-01T00:00:00+00:00', NULL)
            """
        )
        conn.executemany(
            """
            INSERT INTO trade_orders (
                id, trade_idea_id, account_label, symbol, side, order_type, status,
                entry_price, stop_loss, take_profit_json, quantity, opened_at,
                closed_at, close_price, pnl, pnl_r, source, metadata_json, created_at
            )
            VALUES (?, 'idea-shared', ?, 'XAUUSD', 'buy', 'market', 'closed',
                    2000, 1990, '[2020]', ?, ?, ?, 2020, ?, ?, 'live', ?, ?)
            """,
            [
                (
                    "order-exness",
                    "Exness Personal",
                    1.0,
                    "2026-01-01T00:15:00+00:00",
                    "2026-01-01T01:00:00+00:00",
                    20.0,
                    2.0,
                    '{"candidate_id": "candidate-shared"}',
                    "2026-01-01T00:15:00+00:00",
                ),
                (
                    "order-ftmo",
                    "FTMO Demo",
                    0.5,
                    "2026-01-01T00:30:00+00:00",
                    "2026-01-01T01:15:00+00:00",
                    -10.0,
                    -1.0,
                    '{"candidate_id": "candidate-shared"}',
                    "2026-01-01T00:30:00+00:00",
                ),
            ],
        )
        conn.commit()


def seed_context(
    db_path: Path,
    source: str = "bot",
    effective_value: str = "bearish",
    valid_until: str | None = None,
) -> None:
    with connect(db_path) as conn:
        init_db(conn)
        conn.execute(
            """
            INSERT INTO market_contexts (
                id, symbol, timeframe, context_type, bot_value, primary_value, secondary_value,
                bot_confidence, effective_value, effective_confidence, source,
                valid_from, valid_until, status, metadata_json
            )
            VALUES ('ctx-bias', 'XAUUSD', 'H1', 'bias', 'bearish', 'bearish', NULL,
                    0.77, ?, 0.66, ?, '2026-01-01T00:00:00+00:00',
                    ?, 'active', '{}')
            """,
            (effective_value, source, valid_until),
        )
        conn.commit()


if __name__ == "__main__":
    unittest.main()
