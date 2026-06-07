from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from semi_bot_trading.api import create_app
from semi_bot_trading.db import connect, init_db


class ApiTest(unittest.TestCase):
    def test_chart_endpoint_returns_payload(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)

            client = TestClient(create_app(config_path))
            response = client.get("/api/chart?symbol=XAUUSD&timeframe=M15&limit=2")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["symbol"], "XAUUSD")
        self.assertEqual(payload["timeframe"], "M15")
        self.assertEqual(len(payload["layers"]["candles"]), 2)
        self.assertEqual(payload["layers"]["structure_timeframe"], "H1")
        self.assertEqual(payload["layers"]["structure"][0]["id"], "h1-s1")

    def test_chart_endpoint_supports_start_index_window(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)

            client = TestClient(create_app(config_path))
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

            client = TestClient(create_app(config_path))
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

            client = TestClient(create_app(config_path))
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

            client = TestClient(create_app(config_path))
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

            client = TestClient(create_app(config_path))
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

            client = TestClient(create_app(config_path))
            save_response = client.put(
                "/api/trades/order-1/review",
                json={
                    "grade": "B",
                    "verdict": "should_skip",
                    "mistake_tags": ["weak_breakout", "weak_breakout", "bad_entry"],
                    "should_trade_again": "conditional",
                    "comment": "Breakout qua zone qua yeu.",
                },
            )
            history_response = client.get("/api/trades?symbol=XAUUSD&timeframe=M15&limit=5&backtest=true")

        self.assertEqual(save_response.status_code, 200)
        review = save_response.json()
        self.assertEqual(review["grade"], "B")
        self.assertEqual(review["verdict"], "should_skip")
        self.assertEqual(review["mistake_tags"], ["weak_breakout", "bad_entry"])

        self.assertEqual(history_response.status_code, 200)
        trade = history_response.json()["trades"][0]
        self.assertEqual(trade["review"]["verdict"], "should_skip")
        self.assertEqual(trade["review"]["comment"], "Breakout qua zone qua yeu.")

    def test_chart_replay_recomputes_from_replay_start(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)

            client = TestClient(create_app(config_path))
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

            client = TestClient(create_app(config_path))
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
        self.assertEqual(payload["visual_end"], "2026-01-01T00:30:00+00:00")
        self.assertEqual(payload["weight"], 0.91)
        self.assertEqual(payload["confidence"], 0.88)
        self.assertEqual(payload["source"], "mixed")
        self.assertEqual(payload["valid_until"], None)
        self.assertEqual(override_count, 1)
        self.assertEqual(zone["source"], "mixed")
        self.assertEqual(zone["start_time"], "2026-01-01T00:15:00+00:00")
        self.assertEqual(zone["end_time"], "2026-01-01T00:30:00+00:00")

    def test_disabled_zone_without_end_uses_latest_candle_time(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            seed_zone(db_path)

            client = TestClient(create_app(config_path))
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
                    "no_expiry": False,
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "disabled")
        self.assertEqual(payload["visual_end"], "2026-01-01T00:15:00+00:00")

    def test_create_manual_zone_persists_human_entity_and_audit_trail(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)

            client = TestClient(create_app(config_path))
            response = client.post(
                "/api/zones",
                json={
                    "symbol": "XAUUSD",
                    "timeframe": "M15",
                    "zone_type": "fvg",
                    "direction": "bullish",
                    "price_low": 1996.5,
                    "price_high": 1999.5,
                    "visual_start": "2026-01-01T00:00:00+00:00",
                    "visual_end": "2026-01-01T00:15:00+00:00",
                    "weight": 0.72,
                    "confidence": 0.9,
                    "no_expiry": True,
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
        self.assertEqual(payload["metadata"]["human_created"], True)
        self.assertEqual(zone_count, 1)
        self.assertEqual(override_count, 1)

    def test_delete_zone_marks_deleted_and_hides_from_chart(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            seed_zone(db_path)

            client = TestClient(create_app(config_path))
            response = client.delete("/api/zones/z1?reason=manual%20delete")
            chart_response = client.get("/api/chart?symbol=XAUUSD&timeframe=M15&limit=2")

            with connect(db_path) as conn:
                override_count = conn.execute("SELECT COUNT(*) AS count FROM overrides").fetchone()["count"]
                zone = conn.execute("SELECT * FROM price_zones WHERE id = 'z1'").fetchone()

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "deleted")
        self.assertEqual(payload["visual_end"], "2026-01-01T00:15:00+00:00")
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

            client = TestClient(create_app(config_path))
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

            client = TestClient(create_app(config_path))
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
database = "{db_path}"

[structure.swing.timeframes]
H1 = {{ window = 5 }}
M15 = {{ window = 3 }}
"""
    )


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
            VALUES ('z1', 'XAUUSD', 'M15', 'sr_v1', 'support', 'bullish', 1990, 1995,
                    '2026-01-01T00:00:00+00:00', NULL, '2026-01-01T00:00:00+00:00',
                    NULL, NULL, NULL, '2026-01-01T00:00:00+00:00',
                    0.8, 0.7, 0.8, 0.7, 'active', 'bot', '{}')
            """
        )
        conn.commit()


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
