from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from semi_bot_trading.candles import Candle, upsert_candles, upsert_live_candle
from semi_bot_trading.db import connect, init_db
from tests.helpers import TemporaryDirectory
from tests.test_api import authenticated_test_client, write_test_config


class ChartDrawingApiTest(unittest.TestCase):
    def test_fixed_range_volume_profile_crud_and_previous_day_preset(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, database)
            client = authenticated_test_client(root, config_path)
            start = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
            with connect(database) as conn:
                init_db(conn)
                upsert_candles(conn, [
                    Candle("XAUUSD", "M1", start + timedelta(minutes=index), start + timedelta(minutes=index + 1), 100, 101, 99, 100.5, 10, "test")
                    for index in range(360)
                ])
                upsert_candles(conn, [
                    Candle("XAUUSD", "D1", start, start + timedelta(days=1), 100, 110, 90, 105, 1000, "test")
                ])
                sunday_start = start + timedelta(days=2)
                upsert_candles(conn, [
                    Candle("XAUUSD", "D1", sunday_start, sunday_start + timedelta(days=1), 105, 108, 103, 107, 100, "test")
                ])
                market_reopen = sunday_start + timedelta(hours=23, minutes=1)
                upsert_candles(conn, [
                    Candle("XAUUSD", "M1", market_reopen + timedelta(minutes=index), market_reopen + timedelta(minutes=index + 1), 107, 108, 106, 107.5, 10, "test")
                    for index in range(180)
                ])
                current_start = start + timedelta(days=3)
                upsert_live_candle(
                    conn,
                    Candle("XAUUSD", "D1", current_start, current_start + timedelta(days=1), 107, 112, 105, 110, 200, "test"),
                )
            try:
                created = client.post("/api/chart-drawings", json={
                    "symbol": "XAUUSD",
                    "drawing_type": "volume_profile_fixed_range",
                    "origin_timeframe": "H1",
                    "anchors": [
                        {"time": start.isoformat(), "price": 100},
                        {"time": (start + timedelta(minutes=5)).isoformat(), "price": 100},
                    ],
                    "properties": {"rows": 24, "value_area_pct": 70, "mode": "up_down"},
                })
                listed = client.get("/api/chart-drawings?symbol=XAUUSD&timeframe=H1")
                updated = client.patch(
                    f"/api/chart-drawings/{created.json()['id']}",
                    json={"revision": created.json()["revision"], "properties": {"rows": 30, "mode": "total"}},
                )
                preset = client.get("/api/volume-profile/presets/previous-broker-day?symbol=XAUUSD")
                today = client.get("/api/volume-profile/presets/current-broker-day?symbol=XAUUSD")
            finally:
                client._semi_bot_env_patch.stop()  # type: ignore[attr-defined]

        self.assertEqual(201, created.status_code)
        self.assertEqual(5, created.json()["volume_profile"]["source_bar_count"])
        self.assertEqual(1, len(listed.json()["drawings"]))
        self.assertEqual(30, updated.json()["volume_profile"]["settings"]["rows"])
        self.assertEqual("total", updated.json()["volume_profile"]["settings"]["mode"])
        self.assertEqual(start.isoformat(), preset.json()["range_start"])
        self.assertEqual(market_reopen.replace(minute=0).isoformat(), today.json()["range_start"])
        self.assertEqual((market_reopen + timedelta(minutes=180)).isoformat(), today.json()["range_end"])
        self.assertEqual(180, today.json()["source_bar_count"])

    def test_chart_drawings_crud_visibility_and_revision(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "trading.toml"
            write_test_config(config_path, root / "test.sqlite3")
            client = authenticated_test_client(root, config_path)
            try:
                created = client.post(
                    "/api/chart-drawings",
                    json={
                        "symbol": "XAUUSD",
                        "drawing_type": "note",
                        "origin_timeframe": "M15",
                        "visible_timeframes": ["M15", "M5"],
                        "anchors": [{"time": "2026-08-10T08:00:00+00:00", "price": 4350.5}],
                        "content": "Wait for retest",
                    },
                )
                drawing = created.json()
                m15 = client.get("/api/chart-drawings?symbol=XAUUSD&timeframe=M15")
                h1 = client.get("/api/chart-drawings?symbol=XAUUSD&timeframe=H1")
                updated = client.patch(
                    f"/api/chart-drawings/{drawing['id']}",
                    json={"revision": drawing["revision"], "locked": True, "content": "Updated note"},
                )
                conflict = client.patch(
                    f"/api/chart-drawings/{drawing['id']}",
                    json={"revision": drawing["revision"], "hidden": True},
                )
                deleted = client.delete(
                    f"/api/chart-drawings/{drawing['id']}?revision={updated.json()['revision']}",
                )
                empty = client.get("/api/chart-drawings?symbol=XAUUSD&timeframe=M15")
            finally:
                client._semi_bot_env_patch.stop()  # type: ignore[attr-defined]

        self.assertEqual(201, created.status_code)
        self.assertEqual(1, len(m15.json()["drawings"]))
        self.assertEqual([], h1.json()["drawings"])
        self.assertEqual(2, updated.json()["revision"])
        self.assertTrue(updated.json()["locked"])
        self.assertEqual(409, conflict.status_code)
        self.assertEqual(200, deleted.status_code)
        self.assertEqual([], empty.json()["drawings"])

    def test_drawing_anchor_validation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "trading.toml"
            write_test_config(config_path, root / "test.sqlite3")
            client = authenticated_test_client(root, config_path)
            try:
                response = client.post(
                    "/api/chart-drawings",
                    json={
                        "drawing_type": "fib_retracement",
                        "origin_timeframe": "H1",
                        "anchors": [{"time": "2026-08-10T08:00:00+00:00", "price": 4350.5}],
                    },
                )
            finally:
                client._semi_bot_env_patch.stop()  # type: ignore[attr-defined]
        self.assertEqual(422, response.status_code)
        self.assertIn("requires exactly 2", response.json()["detail"])

    def test_fib_extension_requires_three_distinct_anchors(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "trading.toml"
            write_test_config(config_path, root / "test.sqlite3")
            client = authenticated_test_client(root, config_path)
            try:
                rejected = client.post(
                    "/api/chart-drawings",
                    json={
                        "drawing_type": "fib_extension",
                        "origin_timeframe": "H1",
                        "anchors": [
                            {"time": "2026-08-10T08:00:00+00:00", "price": 4300},
                            {"time": "2026-08-10T09:00:00+00:00", "price": 4400},
                        ],
                    },
                )
                duplicate = client.post(
                    "/api/chart-drawings",
                    json={
                        "drawing_type": "fib_extension",
                        "origin_timeframe": "H1",
                        "anchors": [
                            {"time": "2026-08-10T08:00:00+00:00", "price": 4300},
                            {"time": "2026-08-10T09:00:00+00:00", "price": 4400},
                            {"time": "2026-08-10T09:00:00+00:00", "price": 4400},
                        ],
                    },
                )
                created = client.post(
                    "/api/chart-drawings",
                    json={
                        "drawing_type": "fib_extension",
                        "origin_timeframe": "H1",
                        "anchors": [
                            {"time": "2026-08-10T08:00:00+00:00", "price": 4300},
                            {"time": "2026-08-10T09:00:00+00:00", "price": 4400},
                            {"time": "2026-08-10T10:00:00+00:00", "price": 4350},
                        ],
                        "properties": {"variant": "trend_based"},
                    },
                )
            finally:
                client._semi_bot_env_patch.stop()  # type: ignore[attr-defined]

        self.assertEqual(422, rejected.status_code)
        self.assertIn("requires exactly 3", rejected.json()["detail"])
        self.assertEqual(422, duplicate.status_code)
        self.assertIn("must not be identical", duplicate.json()["detail"])
        self.assertEqual(201, created.status_code)
        self.assertEqual("fib_extension", created.json()["drawing_type"])


if __name__ == "__main__":
    unittest.main()
