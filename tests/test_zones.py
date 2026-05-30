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
