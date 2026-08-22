from __future__ import annotations

import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from semi_bot_trading.db import connect, init_db
from semi_bot_trading.intraday_levels import _make_level, build_intraday_map
from tests.helpers import TemporaryDirectory


class IntradayLevelsTest(unittest.TestCase):
    def test_broken_level_becomes_testing_flip_near_retest(self) -> None:
        level = _make_level(
            "test", "asia", "Asia H", "high", 100.0,
            "2026-08-24T00:00:00+00:00", "2026-08-24T07:00:00+00:00",
            [{"high": 102.0, "low": 99.0, "close": 100.4}],
            current_price=100.4, atr=2.0, allowance=0.6, priority=85, live=False,
        )
        self.assertEqual(level["status"], "testing_flip")

    def test_distant_broken_level_becomes_stale(self) -> None:
        level = _make_level(
            "test", "asia", "Asia H", "high", 100.0,
            "2026-08-24T00:00:00+00:00", "2026-08-24T07:00:00+00:00",
            [{"high": 102.0, "low": 99.0, "close": 112.0}],
            current_price=112.0, atr=2.0, allowance=0.6, priority=85, live=False,
        )
        self.assertEqual(level["status"], "stale")

    def test_overlap_keeps_both_london_and_new_york_ranges_live(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with closing(connect(Path(temp_dir) / "test.sqlite3")) as conn:
                init_db(conn)
                self._seed_day(conn, datetime(2026, 8, 21, tzinfo=UTC), 48, 4500.0)
                self._seed_day(conn, datetime(2026, 8, 24, tzinfo=UTC), 52, 4610.0)
                result = build_intraday_map(conn, "XAUUSD", "2026-08-24T13:00:00+00:00")

        live_labels = {level["label"] for level in result["levels"] if level["status"] == "live"}
        self.assertEqual(result["current_session"], "London-NY")
        self.assertTrue({"London H", "London L", "New York H", "New York L"}.issubset(live_labels))

    def test_previous_day_skips_short_sunday_reopen(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with closing(connect(Path(temp_dir) / "test.sqlite3")) as conn:
                init_db(conn)
                self._seed_day(conn, datetime(2026, 8, 21, tzinfo=UTC), 48, 4500.0)
                self._seed_day(conn, datetime(2026, 8, 23, 22, tzinfo=UTC), 8, 4600.0)
                self._seed_day(conn, datetime(2026, 8, 24, tzinfo=UTC), 4, 4610.0)
                result = build_intraday_map(conn, "XAUUSD", "2026-08-24T01:00:00+00:00")

        pdh = next(level for level in result["levels"] if level["id"] == "previous_day_high")
        self.assertEqual(pdh["period_start"], "2026-08-21T00:00:00+00:00")
        self.assertLess(pdh["price"], 4600.0)

    @staticmethod
    def _seed_day(conn, start: datetime, count: int, base: float) -> None:
        rows = []
        for index in range(count):
            opened = start + timedelta(minutes=15 * index)
            closed = opened + timedelta(minutes=15)
            price = base + index * 0.1
            rows.append(
                (
                    f"{opened.isoformat()}-{base}",
                    opened.isoformat(),
                    closed.isoformat(),
                    price,
                    price + 1.0,
                    price - 1.0,
                    price + 0.2,
                )
            )
        conn.executemany(
            """
            INSERT INTO candles (
                id, symbol, timeframe, open_time, close_time, open, high, low, close, volume, source
            ) VALUES (?, 'XAUUSD', 'M15', ?, ?, ?, ?, ?, ?, 100, 'test')
            """,
            rows,
        )
        conn.commit()


if __name__ == "__main__":
    unittest.main()
