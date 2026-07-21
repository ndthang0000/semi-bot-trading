from __future__ import annotations

import json
import os
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tests.helpers import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from semi_bot_trading.api import create_app
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
        self.assertIsNotNone(payload["valid_until"])
        self.assertEqual(payload["metadata"]["human_created"], True)
        self.assertEqual(payload["metadata"]["trade_modes"], ["reject", "internal_reject"])
        self.assertEqual(zone_count, 1)
        self.assertEqual(override_count, 1)

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

            with connect(db_path) as conn:
                row = conn.execute("SELECT metadata_json FROM price_zones").fetchone()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["metadata"]["trade_modes"], ["reject"])
        self.assertEqual(json.loads(row["metadata_json"])["trade_modes"], ["reject"])

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
