from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from semi_bot_trading.candles import Candle, upsert_candles
from semi_bot_trading.db import connect, init_db
from semi_bot_trading.live_worker import sync_mt5_candles
from semi_bot_trading.volume_profile import MAX_SOURCE_BARS, VolumeProfileError, calculate_fixed_range_profile, normalize_volume_profile_settings
from tests.helpers import TemporaryDirectory


def candle(at: datetime, *, low: float, high: float, open_price: float, close: float, volume: float | None, timeframe: str = "M1") -> Candle:
    delta = timedelta(days=1) if timeframe == "D1" else timedelta(minutes=1)
    return Candle("XAUUSD", timeframe, at, at + delta, open_price, high, low, close, volume, "test")


class VolumeProfileTest(unittest.TestCase):
    def test_defaults_use_left_placement_and_30_percent_width(self) -> None:
        settings = normalize_volume_profile_settings(None)

        self.assertEqual("left", settings["placement"])
        self.assertEqual(30.0, settings["width_pct"])

    def test_distributes_volume_and_preserves_total(self) -> None:
        with connect(":memory:") as conn:
            init_db(conn)
            start = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
            upsert_candles(conn, [
                candle(start, low=100, high=102, open_price=100, close=102, volume=100),
                candle(start + timedelta(minutes=1), low=101, high=103, open_price=103, close=101, volume=50),
                candle(start + timedelta(minutes=2), low=102, high=102, open_price=102, close=102, volume=25),
            ])
            profile = calculate_fixed_range_profile(
                conn,
                symbol="XAUUSD",
                start=start,
                end=start + timedelta(minutes=3),
                settings={"rows": 10, "value_area_pct": 70, "mode": "up_down"},
            )

        self.assertEqual(3, profile["source_bar_count"])
        self.assertAlmostEqual(175, profile["total_volume"])
        self.assertAlmostEqual(175, sum(row["total_volume"] for row in profile["rows"]))
        self.assertAlmostEqual(125, sum(row["up_volume"] for row in profile["rows"]))
        self.assertAlmostEqual(50, sum(row["down_volume"] for row in profile["rows"]))
        self.assertTrue(any(row["in_value_area"] for row in profile["rows"]))

    def test_poc_tie_prefers_higher_price_row_and_modes_are_retained(self) -> None:
        with connect(":memory:") as conn:
            init_db(conn)
            start = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
            upsert_candles(conn, [
                candle(start, low=100, high=100, open_price=100, close=100, volume=10),
                candle(start + timedelta(minutes=1), low=109, high=109, open_price=110, close=109, volume=10),
            ])
            profile = calculate_fixed_range_profile(
                conn,
                symbol="XAUUSD",
                start=start,
                end=start + timedelta(minutes=2),
                settings={"rows": 10, "mode": "delta"},
            )
        self.assertGreater(profile["poc"], 108)
        self.assertEqual("delta", profile["settings"]["mode"])
        self.assertTrue(all("delta" in row for row in profile["rows"]))

    def test_rejects_missing_volume_no_data_and_more_than_bar_cap(self) -> None:
        with connect(":memory:") as conn:
            init_db(conn)
            start = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)
            with self.assertRaisesRegex(VolumeProfileError, "not ready"):
                calculate_fixed_range_profile(conn, symbol="XAUUSD", start=start, end=start + timedelta(minutes=1))
            upsert_candles(conn, [candle(start, low=100, high=101, open_price=100, close=101, volume=None)])
            with self.assertRaisesRegex(VolumeProfileError, "missing"):
                calculate_fixed_range_profile(conn, symbol="XAUUSD", start=start, end=start + timedelta(minutes=1))

        with connect(":memory:") as conn:
            init_db(conn)
            upsert_candles(conn, [candle(start, low=100, high=101, open_price=100, close=101, volume=0)])
            with self.assertRaisesRegex(VolumeProfileError, "zero"):
                calculate_fixed_range_profile(conn, symbol="XAUUSD", start=start, end=start + timedelta(minutes=1))

        with connect(":memory:") as conn:
            init_db(conn)
            upsert_candles(conn, [
                candle(start + timedelta(minutes=index), low=100, high=101, open_price=100, close=101, volume=1)
                for index in range(MAX_SOURCE_BARS + 1)
            ])
            with self.assertRaisesRegex(VolumeProfileError, "exceeds"):
                calculate_fixed_range_profile(
                    conn,
                    symbol="XAUUSD",
                    start=start,
                    end=start + timedelta(minutes=MAX_SOURCE_BARS + 1),
                )

    def test_worker_backfills_m1_and_d1_without_duplicate_rows(self) -> None:
        now = datetime.now(UTC).replace(second=0, microsecond=0)
        calls: list[tuple[str, int]] = []

        class FakeClient:
            def get_symbol_trade_info(self, _: str) -> dict[str, float]:
                return {"digits": 2, "point": 0.01, "trade_tick_size": 0.01}

            def copy_rates(self, _broker_symbol: str, _symbol: str, timeframe: str, count: int) -> list[Candle]:
                calls.append((timeframe, count))
                if timeframe == "M1":
                    return [candle(now - timedelta(minutes=2), low=100, high=101, open_price=100, close=101, volume=5)]
                if timeframe == "D1":
                    return [candle(now - timedelta(days=2), low=90, high=110, open_price=95, close=100, volume=50, timeframe="D1")]
                return []

        config = SimpleNamespace(
            symbol="XAUUSD",
            bias=SimpleNamespace(timeframe="H1"),
            strategy=SimpleNamespace(timeframe="M15"),
        )
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "worker.sqlite3"
            with connect(path) as conn:
                init_db(conn)
                sync_mt5_candles(conn, config, FakeClient(), "XAUUSDm")
                sync_mt5_candles(conn, config, FakeClient(), "XAUUSDm")
                counts = dict(conn.execute("SELECT timeframe, COUNT(*) count FROM candles GROUP BY timeframe").fetchall())
                metadata = conn.execute("SELECT * FROM instrument_metadata WHERE symbol = 'XAUUSD'").fetchone()

        self.assertEqual(1, counts["M1"])
        self.assertEqual(1, counts["D1"])
        self.assertEqual(30 * 24 * 60 + 1, next(count for timeframe, count in calls if timeframe == "M1"))
        self.assertEqual(0.01, metadata["trade_tick_size"])


if __name__ == "__main__":
    unittest.main()
