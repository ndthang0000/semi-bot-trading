from __future__ import annotations

import unittest

from semi_bot_trading.structure import CandleView, SwingLevel, detect_break_structure, detect_swing_structure


class StructureDetectorTest(unittest.TestCase):
    def test_detects_higher_high_and_higher_low(self) -> None:
        candles = [
            CandleView("2026-01-01T00:00:00+00:00", high=10, low=8, close=9),
            CandleView("2026-01-01T00:15:00+00:00", high=12, low=9, close=11),
            CandleView("2026-01-01T00:30:00+00:00", high=9, low=7, close=8),
            CandleView("2026-01-01T00:45:00+00:00", high=11, low=10, close=10.5),
            CandleView("2026-01-01T01:00:00+00:00", high=15, low=11, close=14),
            CandleView("2026-01-01T01:15:00+00:00", high=13, low=10, close=11),
            CandleView("2026-01-01T01:30:00+00:00", high=14, low=12, close=13),
        ]

        points = detect_swing_structure(
            candles,
            symbol="XAUUSD",
            timeframe="M15",
            window=1,
        )

        labels = [(point.event_time, point.point_type) for point in points]
        self.assertIn(("2026-01-01T00:15:00+00:00", "swing_high"), labels)
        self.assertIn(("2026-01-01T00:30:00+00:00", "swing_low"), labels)
        self.assertIn(("2026-01-01T01:00:00+00:00", "HH"), labels)
        self.assertIn(("2026-01-01T01:15:00+00:00", "HL"), labels)

    def test_detects_bos_and_choch_from_confirmed_swings(self) -> None:
        candles = [
            CandleView("2026-01-01T00:00:00+00:00", high=10, low=8, close=9),
            CandleView("2026-01-01T00:15:00+00:00", high=11, low=9, close=10),
            CandleView("2026-01-01T00:30:00+00:00", high=13, low=10, close=12.5),
            CandleView("2026-01-01T00:45:00+00:00", high=12, low=7, close=7.5),
            CandleView("2026-01-01T01:00:00+00:00", high=8, low=5, close=5.5),
        ]
        swings = [
            SwingLevel(
                id="high-1",
                point_type="swing_high",
                swing_type="high",
                price=12,
                event_time="2026-01-01T00:15:00+00:00",
                confirmed_at="2026-01-01T00:15:00+00:00",
            ),
            SwingLevel(
                id="low-1",
                point_type="swing_low",
                swing_type="low",
                price=8,
                event_time="2026-01-01T00:00:00+00:00",
                confirmed_at="2026-01-01T00:00:00+00:00",
            ),
        ]

        points = detect_break_structure(candles, swings, "XAUUSD", "M15")

        labels = [(point.event_time, point.point_type, point.metadata["direction"]) for point in points]
        self.assertEqual(labels[0], ("2026-01-01T00:30:00+00:00", "BOS", "up"))
        self.assertEqual(labels[1], ("2026-01-01T00:45:00+00:00", "CHOCH", "down"))


if __name__ == "__main__":
    unittest.main()
