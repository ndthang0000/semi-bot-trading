from __future__ import annotations

import unittest

from semi_bot_trading.zones import (
    CandleSlice,
    SwingPoint,
    apply_lifecycle_to_zone,
    detect_support_resistance_zones,
)


class ZoneDetectorTest(unittest.TestCase):
    def test_clusters_support_and_resistance_from_swings(self) -> None:
        swings = [
            SwingPoint("h1", "HH", 2010, "2026-01-01T00:00:00+00:00", "high"),
            SwingPoint("h2", "LH", 2011, "2026-01-01T03:00:00+00:00", "high"),
            SwingPoint("l1", "HL", 1990, "2026-01-01T01:00:00+00:00", "low"),
            SwingPoint("l2", "LL", 1989, "2026-01-01T04:00:00+00:00", "low"),
            SwingPoint("l3", "HL", 1991, "2026-01-01T05:00:00+00:00", "low"),
        ]

        zones = detect_support_resistance_zones(
            swings,
            symbol="XAUUSD",
            timeframe="H1",
            tolerance_pct=0.001,
            min_zone_width=1.0,
            min_touches=2,
            max_zones=10,
        )

        zone_types = {zone.zone_type for zone in zones}
        self.assertIn("support", zone_types)
        self.assertIn("resistance", zone_types)
        support = next(zone for zone in zones if zone.zone_type == "support")
        self.assertEqual(support.metadata["touch_count"], 3)
        self.assertIsNone(support.end_time)

    def test_uses_atr_width_when_wider_than_percentage_width(self) -> None:
        swings = [
            SwingPoint("h1", "HH", 2010, "2026-01-01T00:00:00+00:00", "high"),
            SwingPoint("h2", "LH", 2012, "2026-01-01T03:00:00+00:00", "high"),
        ]

        zone = detect_support_resistance_zones(
            swings,
            symbol="XAUUSD",
            timeframe="H1",
            tolerance_pct=0.0001,
            min_zone_width=1.0,
            min_touches=2,
            max_zones=10,
            atr_value=20.0,
            atr_width_multiplier=0.5,
        )[0]

        self.assertEqual(zone.price_low, 2000)
        self.assertEqual(zone.price_high, 2022)
        self.assertEqual(zone.metadata["half_width"], 10)
        self.assertEqual(zone.metadata["atr_at_detection"], 20)

    def test_atr_width_is_frozen_at_zone_detection_time(self) -> None:
        swings = [
            SwingPoint("l1", "HL", 4660, "2026-01-19T11:00:00+00:00", "low"),
            SwingPoint("l2", "HL", 4658, "2026-01-19T14:00:00+00:00", "low"),
        ]
        early_candles = [
            CandleSlice("2026-01-19T10:00:00+00:00", high=4672, low=4662, close=4668, open=4666),
            CandleSlice("2026-01-19T11:00:00+00:00", high=4668, low=4660, close=4665, open=4667),
            CandleSlice("2026-01-19T12:00:00+00:00", high=4670, low=4661, close=4667, open=4664),
            CandleSlice("2026-01-19T13:00:00+00:00", high=4669, low=4660, close=4662, open=4668),
            CandleSlice("2026-01-19T14:00:00+00:00", high=4666, low=4658, close=4664, open=4661),
        ]
        later_candles = [
            *early_candles,
            CandleSlice("2026-01-19T15:00:00+00:00", high=4720, low=4650, close=4710, open=4665),
            CandleSlice("2026-01-19T16:00:00+00:00", high=4780, low=4700, close=4770, open=4710),
        ]

        early_zone = detect_support_resistance_zones(
            swings,
            symbol="XAUUSD",
            timeframe="H1",
            tolerance_pct=0.0001,
            min_zone_width=1.0,
            min_touches=2,
            max_zones=10,
            atr_candles=early_candles,
            atr_width_multiplier=0.45,
        )[0]
        later_zone = detect_support_resistance_zones(
            swings,
            symbol="XAUUSD",
            timeframe="H1",
            tolerance_pct=0.0001,
            min_zone_width=1.0,
            min_touches=2,
            max_zones=10,
            atr_candles=later_candles,
            atr_width_multiplier=0.45,
        )[0]

        self.assertEqual(later_zone.price_low, early_zone.price_low)
        self.assertEqual(later_zone.price_high, early_zone.price_high)
        self.assertEqual(later_zone.metadata["atr_at_detection"], early_zone.metadata["atr_at_detection"])

    def test_rejects_support_candidate_broken_before_detection(self) -> None:
        swings = [
            SwingPoint("l1", "HL", 1922.34, "2023-09-06T08:00:00+00:00", "low"),
            SwingPoint("l2", "HL", 1922.35, "2023-09-15T19:00:00+00:00", "low"),
            SwingPoint("l3", "HL", 1922.72, "2023-09-18T14:00:00+00:00", "low"),
        ]
        candles = [
            CandleSlice("2023-09-06T08:00:00+00:00", open=1922.78, high=1924.87, low=1922.34, close=1924.68),
            CandleSlice("2023-09-06T14:00:00+00:00", open=1928.07, high=1928.07, low=1915.15, close=1918.10),
            CandleSlice("2023-09-15T19:00:00+00:00", open=1923.99, high=1924.45, low=1922.35, close=1922.45),
            CandleSlice("2023-09-18T14:00:00+00:00", open=1923.90, high=1927.54, low=1922.72, close=1926.84),
        ]

        zones = detect_support_resistance_zones(
            swings,
            symbol="XAUUSD",
            timeframe="H1",
            tolerance_pct=0.0005,
            min_zone_width=1.0,
            min_touches=3,
            max_zones=10,
            atr_candles=candles,
            atr_width_multiplier=0.25,
            candidate_close_break_buffer_atr_multiplier=0.15,
        )

        self.assertEqual(zones, [])

    def test_scores_reaction_quality_after_touch(self) -> None:
        swings = [
            SwingPoint("l1", "HL", 1990, "2026-01-01T01:00:00+00:00", "low"),
            SwingPoint("l2", "LL", 1989, "2026-01-01T04:00:00+00:00", "low"),
        ]
        zone = detect_support_resistance_zones(
            swings,
            symbol="XAUUSD",
            timeframe="H1",
            tolerance_pct=0.001,
            min_zone_width=1.0,
            min_touches=2,
            max_zones=10,
        )[0]
        candles = [
            CandleSlice("2026-01-01T04:00:00+00:00", open=1994, high=1995, low=1989, close=1994),
            CandleSlice("2026-01-01T05:00:00+00:00", open=1994, high=2003, low=1993, close=2002),
            CandleSlice("2026-01-01T06:00:00+00:00", open=2002, high=2007, low=2001, close=2006),
        ]

        updated = apply_lifecycle_to_zone(
            zone,
            candles,
            close_break_buffer=0.0,
            recent_touch_lookback_candles=10,
            age_decay_per_100_candles=0.06,
            freshness_bonus=0.12,
            invalidation_weight_multiplier=0.15,
            reaction_window_candles=2,
            min_reaction_atr=0.5,
            strong_reaction_atr=1.0,
        )

        self.assertEqual(updated.status, "active")
        self.assertEqual(updated.metadata["touch_count_after_detection"], 1)
        self.assertGreater(updated.metadata["avg_reaction_score"], 0)
        self.assertGreater(updated.metadata["clean_rejection_count"], 0)
        self.assertIn("weight_components", updated.metadata)

    def test_invalidates_support_when_close_breaks_below_zone(self) -> None:
        swings = [
            SwingPoint("l1", "HL", 1990, "2026-01-01T01:00:00+00:00", "low"),
            SwingPoint("l2", "LL", 1989, "2026-01-01T04:00:00+00:00", "low"),
        ]
        zone = detect_support_resistance_zones(
            swings,
            symbol="XAUUSD",
            timeframe="H1",
            tolerance_pct=0.001,
            min_zone_width=1.0,
            min_touches=2,
            max_zones=10,
        )[0]
        candles = [
            CandleSlice("2026-01-01T04:00:00+00:00", high=1995, low=1989, close=1992),
            CandleSlice("2026-01-01T05:00:00+00:00", high=1993, low=1985, close=1986),
        ]

        updated = apply_lifecycle_to_zone(
            zone,
            candles,
            close_break_buffer=0.0,
            recent_touch_lookback_candles=10,
            age_decay_per_100_candles=0.08,
            freshness_bonus=0.15,
            invalidation_weight_multiplier=0.15,
        )

        self.assertEqual(updated.status, "invalidated")
        self.assertEqual(updated.end_time, "2026-01-01T05:00:00+00:00")
        self.assertLess(updated.effective_weight, zone.effective_weight)


if __name__ == "__main__":
    unittest.main()
