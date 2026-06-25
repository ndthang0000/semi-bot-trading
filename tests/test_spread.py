from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from semi_bot_trading.db import connect, init_db
from semi_bot_trading.spread import latest_spread_snapshot, record_spread_snapshot, spread_summary


class SpreadSnapshotTest(unittest.TestCase):
    def test_record_latest_and_summary_percentiles(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            now = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)
            with connect(db_path) as conn:
                init_db(conn)
                for i, spread in enumerate([0.2, 0.5, 1.0, 2.0]):
                    record_spread_snapshot(
                        conn,
                        symbol="XAUUSD",
                        broker_symbol="XAUUSDm",
                        bid=4000 + i,
                        ask=4000 + i + spread,
                        snapshot_at=now - timedelta(minutes=4 - i),
                    )

                latest = latest_spread_snapshot(conn, "XAUUSD")
                summary = spread_summary(conn, "XAUUSD", hours=24, now=now)

        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(2.0, latest["spread"])
        self.assertEqual(4, summary["count"])
        self.assertAlmostEqual(0.2, summary["min"])
        self.assertAlmostEqual(2.0, summary["max"])
        self.assertAlmostEqual(0.75, summary["p50"])
        self.assertAlmostEqual(1.7, summary["p90"])

    def test_summary_keeps_latest_even_when_window_empty(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            old = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)
            now = datetime(2026, 6, 25, 12, 0, tzinfo=UTC)
            with connect(db_path) as conn:
                init_db(conn)
                record_spread_snapshot(
                    conn,
                    symbol="XAUUSD",
                    broker_symbol="XAUUSDm",
                    bid=4000,
                    ask=4001,
                    snapshot_at=old,
                )
                summary = spread_summary(conn, "XAUUSD", hours=1, now=now)

        self.assertEqual(0, summary["count"])
        self.assertIsNotNone(summary["latest"])
        self.assertIsNone(summary["avg"])


if __name__ == "__main__":
    unittest.main()
