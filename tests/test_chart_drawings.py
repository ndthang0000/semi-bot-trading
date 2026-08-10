from __future__ import annotations

import unittest
from pathlib import Path

from tests.helpers import TemporaryDirectory
from tests.test_api import authenticated_test_client, write_test_config


class ChartDrawingApiTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
