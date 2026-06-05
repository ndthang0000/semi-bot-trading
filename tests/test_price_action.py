from __future__ import annotations

import unittest

from semi_bot_trading.price_action import PRICE_ACTION_DETECTOR, detect_price_action_patterns
from semi_bot_trading.zones import CandleSlice


def candle(time: str, open_: float, high: float, low: float, close: float) -> CandleSlice:
    return CandleSlice(f"2026-01-01T{time}:00+00:00", open=open_, high=high, low=low, close=close)


class PriceActionTest(unittest.TestCase):
    def test_detects_bullish_pinbar(self) -> None:
        candles = [candle("00:00", 100, 102, 90, 101)]

        points = detect_price_action_patterns(candles, "XAUUSD", "M15")

        self.assertIn("pinbar_bullish", [point.point_type for point in points])
        pinbar = next(point for point in points if point.point_type == "pinbar_bullish")
        self.assertEqual(PRICE_ACTION_DETECTOR, pinbar.detector)
        self.assertEqual("up", pinbar.metadata["direction"])

    def test_detects_bearish_engulfing(self) -> None:
        candles = [
            candle("00:00", 100, 106, 99, 105),
            candle("00:15", 106, 107, 97, 98),
        ]

        points = detect_price_action_patterns(candles, "XAUUSD", "M15")

        self.assertIn("engulfing_bearish", [point.point_type for point in points])

    def test_detects_bullish_marubozu(self) -> None:
        candles = [candle("00:00", 100, 110.5, 99.8, 110)]

        points = detect_price_action_patterns(candles, "XAUUSD", "M15")

        self.assertIn("marubozu_bullish", [point.point_type for point in points])

    def test_detects_morning_star(self) -> None:
        candles = [
            candle("00:00", 110, 111, 99, 100),
            candle("00:15", 100, 102, 98, 100.8),
            candle("00:30", 101, 109, 100, 108),
        ]

        points = detect_price_action_patterns(candles, "XAUUSD", "M15")

        self.assertIn("morning_star", [point.point_type for point in points])

    def test_detects_displacement_candle_with_atr_filter(self) -> None:
        candles = [
            candle("00:00", 100, 102, 99, 101),
            candle("00:15", 101, 103, 100, 102),
            candle("00:30", 102, 104, 101, 103),
            candle("00:45", 103, 116, 102, 115),
        ]

        points = detect_price_action_patterns(candles, "XAUUSD", "M15", atr_period=3)

        displacement = next(point for point in points if point.point_type == "displacement_bullish")
        self.assertGreaterEqual(displacement.metadata["range_atr"], 1.5)


if __name__ == "__main__":
    unittest.main()
