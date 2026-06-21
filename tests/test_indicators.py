from __future__ import annotations

import unittest

from semi_bot_trading.indicators import latest_rsi_snapshot, rsi_series
from semi_bot_trading.strategy.builder import _h1_rsi_metadata


class RsiIndicatorTest(unittest.TestCase):
    def test_flat_market_rsi_is_neutral(self) -> None:
        values = rsi_series([100.0] * 20, period=14)
        self.assertEqual(values[-1], 50.0)

    def test_snapshot_includes_h1_slopes(self) -> None:
        candles = [
            {
                "time": f"2026-01-01T{index:02d}:00:00+00:00",
                "close": 100.0 + index,
            }
            for index in range(20)
        ]
        snapshot = latest_rsi_snapshot(candles, period=14, slope_periods=(3, 5))
        self.assertEqual(snapshot["period"], 14)
        self.assertEqual(snapshot["as_of"], "2026-01-01T19:00:00+00:00")
        self.assertEqual(snapshot["value"], 100.0)
        self.assertEqual(snapshot["slope_3"], 0.0)
        self.assertEqual(snapshot["slope_5"], 0.0)

    def test_strategy_rsi_metadata_uses_h1_context_candles(self) -> None:
        candles = [
            {
                "time": f"2026-01-01T{index:02d}:00:00+00:00",
                "close": 100.0 + index,
            }
            for index in range(20)
        ]
        metadata = _h1_rsi_metadata("H1", candles)
        self.assertEqual(metadata["rsi_h1"], 100.0)
        self.assertEqual(metadata["rsi_h1_slope_3"], 0.0)
        self.assertEqual(metadata["rsi_h1_slope_5"], 0.0)
        self.assertEqual(metadata["rsi_h1_as_of"], "2026-01-01T19:00:00+00:00")

    def test_strategy_rsi_metadata_ignores_non_h1_context(self) -> None:
        metadata = _h1_rsi_metadata("M15", [{"time": "2026-01-01T00:00:00+00:00", "close": 100.0}])
        self.assertEqual(metadata, {})


if __name__ == "__main__":
    unittest.main()
