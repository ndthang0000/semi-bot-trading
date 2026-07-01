from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from semi_bot_trading.db import connect, init_db
from semi_bot_trading.smc_zones import (
    FVG_DETECTOR,
    LIQUIDITY_DETECTOR,
    ORDER_BLOCK_DETECTOR,
    apply_persisted_fvg_mitigation,
    detect_consolidation_zones,
    detect_fvg_zones,
    detect_liquidity_sweep_zones,
    detect_order_block_zones,
)
from semi_bot_trading.zones import CandleSlice, SwingPoint


def candle(time: str, open_: float, high: float, low: float, close: float) -> CandleSlice:
    return CandleSlice(f"2026-01-01T{time}:00+00:00", open=open_, high=high, low=low, close=close)


def candle_at(iso_time: str, open_: float, high: float, low: float, close: float) -> CandleSlice:
    return CandleSlice(iso_time, open=open_, high=high, low=low, close=close)


class SmcZoneTest(unittest.TestCase):
    def test_persisted_fvg_mitigates_when_filled_for_all_sources(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with connect(db_path) as conn:
                init_db(conn)
                conn.executemany(
                    """
                    INSERT INTO candles (
                        id, symbol, timeframe, open_time, close_time, open, high, low, close, volume, source
                    )
                    VALUES (?, 'XAUUSD', 'H1', ?, ?, ?, ?, ?, ?, 100, 'test')
                    """,
                    [
                        ("c1", "2026-01-01T00:00:00+00:00", "2026-01-01T01:00:00+00:00", 101, 104, 100, 103),
                        ("c2", "2026-01-01T01:00:00+00:00", "2026-01-01T02:00:00+00:00", 103, 104, 95, 96),
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO price_zones (
                        id, symbol, timeframe, detector, zone_type, direction, price_low, price_high,
                        start_time, end_time, valid_from, valid_until, invalidated_at,
                        invalidated_by_structure_point_id, detected_at, bot_confidence, bot_weight,
                        effective_confidence, effective_weight, status, source, metadata_json
                    )
                    VALUES (?, 'XAUUSD', 'H1', ?, 'fvg', 'bullish', 100, 110,
                            '2026-01-01T00:00:00+00:00', '2026-01-03T00:00:00+00:00',
                            '2026-01-01T00:00:00+00:00', '2026-01-03T00:00:00+00:00',
                            NULL, NULL, '2026-01-01T00:00:00+00:00',
                            0.9, 0.8, 0.9, 0.8, 'active', ?, ?)
                    """,
                    [
                        ("bot-fvg", "fvg_v1", "bot", "{}"),
                        ("human-fvg", "human_manual_v1", "human", '{"human_created": true}'),
                        ("mixed-fvg", "fvg_v1", "mixed", '{"human_adjusted": true}'),
                    ],
                )
                updates = apply_persisted_fvg_mitigation(conn, "XAUUSD", "H1")
                rows = conn.execute("SELECT * FROM price_zones ORDER BY id").fetchall()

        self.assertEqual(3, updates)
        self.assertEqual(["bot-fvg", "human-fvg", "mixed-fvg"], [row["id"] for row in rows])
        for row in rows:
            metadata = json.loads(row["metadata_json"])
            self.assertEqual("mitigated", row["status"])
            self.assertEqual("2026-01-01T01:00:00+00:00", row["end_time"])
            self.assertEqual(row["end_time"], row["valid_until"])
            self.assertEqual(row["end_time"], row["invalidated_at"])
            self.assertEqual("filled", metadata["fill_state"])
            self.assertEqual("fvg_fill_threshold", metadata["mitigated_rule"])
            self.assertEqual(row["source"], metadata["fvg_lifecycle_applied_to_source"])

    def test_detects_bullish_fvg(self) -> None:
        candles = [
            candle("00:00", 100, 101, 99, 100),
            candle("01:00", 100, 101, 99, 100),
            candle("02:00", 100, 101, 99, 100),
            candle("03:00", 100, 102, 99, 101),
            candle("04:00", 101, 111, 100, 110),
            candle("05:00", 112, 115, 112, 114),
        ]

        zones = detect_fvg_zones(candles, "XAUUSD", "H1")

        self.assertEqual(1, len(zones))
        self.assertEqual(FVG_DETECTOR, zones[0].detector)
        self.assertEqual("fvg", zones[0].zone_type)
        self.assertEqual("bullish", zones[0].direction)
        self.assertEqual(102, zones[0].price_low)
        self.assertLess(zones[0].price_high, 112)
        self.assertTrue(zones[0].metadata["shrunk_for_entry"])
        self.assertEqual(102, zones[0].metadata["original_gap_low"])
        self.assertEqual(112, zones[0].metadata["original_gap_high"])
        self.assertGreaterEqual(zones[0].metadata["middle_range_atr"], 2.0)
        self.assertGreaterEqual(zones[0].metadata["gap_atr_ratio"], 0.25)

    def test_can_keep_full_fvg_width_when_max_width_disabled(self) -> None:
        candles = [
            candle("00:00", 100, 101, 99, 100),
            candle("01:00", 100, 101, 99, 100),
            candle("02:00", 100, 101, 99, 100),
            candle("03:00", 100, 102, 99, 101),
            candle("04:00", 101, 111, 100, 110),
            candle("05:00", 112, 115, 112, 114),
        ]

        zones = detect_fvg_zones(candles, "XAUUSD", "H1", max_width_atr_ratio=0)

        self.assertEqual(1, len(zones))
        self.assertEqual(102, zones[0].price_low)
        self.assertEqual(112, zones[0].price_high)
        self.assertFalse(zones[0].metadata["shrunk_for_entry"])

    def test_bearish_fvg_shrinks_from_lower_edge(self) -> None:
        candles = [
            candle("00:00", 100, 101, 99, 100),
            candle("01:00", 100, 101, 99, 100),
            candle("02:00", 100, 101, 99, 100),
            candle("03:00", 100, 102, 99, 101),
            candle("04:00", 101, 102, 90, 91),
            candle("05:00", 89, 89, 85, 86),
        ]

        zones = detect_fvg_zones(candles, "XAUUSD", "H1", max_width_atr_ratio=0.5)

        self.assertEqual(1, len(zones))
        self.assertEqual("bearish", zones[0].direction)
        self.assertGreater(zones[0].price_low, 89)
        self.assertEqual(99, zones[0].price_high)
        self.assertTrue(zones[0].metadata["shrunk_for_entry"])

    def test_fvg_fill_reduces_weight(self) -> None:
        candles = [
            candle("00:00", 100, 101, 99, 100),
            candle("01:00", 100, 101, 99, 100),
            candle("02:00", 100, 101, 99, 100),
            candle("03:00", 100, 102, 99, 101),
            candle("04:00", 101, 111, 100, 110),
            candle("05:00", 112, 115, 112, 114),
            candle("06:00", 114, 115, 101, 104),
        ]

        zones = detect_fvg_zones(candles, "XAUUSD", "H1", max_width_atr_ratio=0)

        self.assertEqual("mitigated", zones[0].status)
        self.assertLess(zones[0].effective_weight, zones[0].bot_weight)
        self.assertEqual("filled", zones[0].metadata["fill_state"])

    def test_fvg_requires_gap_size_relative_to_atr(self) -> None:
        candles = [
            candle("00:00", 100, 101, 99, 100),
            candle("01:00", 100, 101, 99, 100),
            candle("02:00", 100, 101, 99, 100),
            candle("03:00", 100, 102, 99, 101),
            candle("04:00", 101, 111, 100, 110),
            candle("05:00", 102.2, 105, 102.2, 104),
        ]

        zones = detect_fvg_zones(candles, "XAUUSD", "H1")

        self.assertEqual([], zones)

    def test_fvg_requires_third_candle_follow_through_by_default(self) -> None:
        candles = [
            candle("00:00", 100, 101, 99, 100),
            candle("01:00", 100, 101, 99, 100),
            candle("02:00", 100, 101, 99, 100),
            candle("03:00", 100, 102, 99, 101),
            candle("04:00", 101, 102, 90, 91),
            candle("05:00", 92, 96, 90, 95),
        ]

        zones = detect_fvg_zones(candles, "XAUUSD", "H1")
        loose_zones = detect_fvg_zones(
            candles,
            "XAUUSD",
            "H1",
            third_candle_follow_through_required=False,
        )

        self.assertEqual([], zones)
        self.assertEqual(1, len(loose_zones))
        self.assertEqual("bearish", loose_zones[0].direction)

    def test_h1_fvg_expires_after_three_days_before_late_fill(self) -> None:
        candles = [
            candle("00:00", 100, 101, 99, 100),
            candle("01:00", 100, 101, 99, 100),
            candle("02:00", 100, 101, 99, 100),
            candle("03:00", 100, 102, 99, 101),
            candle("04:00", 101, 111, 100, 110),
            candle("05:00", 112, 115, 112, 114),
            candle_at("2026-01-08T04:00:00+00:00", 114, 116, 113, 115),
            candle_at("2026-01-08T06:00:00+00:00", 114, 115, 103, 104),
        ]

        zones = detect_fvg_zones(candles, "XAUUSD", "H1")

        self.assertEqual("expired", zones[0].status)
        self.assertEqual("2026-01-03T05:00:00+00:00", zones[0].end_time)
        self.assertEqual("open", zones[0].metadata["fill_state"])
        self.assertEqual("smc_zone_max_active_days", zones[0].metadata["expired_rule"])

    def test_h1_fvg_weight_decays_before_expiry(self) -> None:
        candles = [
            candle("00:00", 100, 101, 99, 100),
            candle("01:00", 100, 101, 99, 100),
            candle("02:00", 100, 101, 99, 100),
            candle("03:00", 100, 102, 99, 101),
            candle("04:00", 101, 111, 100, 110),
            candle("05:00", 112, 115, 112, 114),
            candle_at("2026-01-02T18:00:00+00:00", 114, 116, 113, 115),
        ]

        zones = detect_fvg_zones(candles, "XAUUSD", "H1")

        self.assertEqual("active", zones[0].status)
        self.assertEqual("2026-01-03T05:00:00+00:00", zones[0].end_time)
        self.assertLess(zones[0].effective_weight, zones[0].bot_weight)
        self.assertEqual(2.0, zones[0].metadata["max_active_days"])
        self.assertEqual(0.75, zones[0].metadata["decay_start_days"])

    def test_detects_bullish_order_block_before_displacement(self) -> None:
        candles = [
            candle("00:00", 100, 103, 99, 102),
            candle("01:00", 102, 103, 98, 99),
            candle("02:00", 99, 113, 98, 112),
            candle("03:00", 112, 114, 111, 113),
        ]
        swings = [
            SwingPoint(
                id="swing-high-1",
                point_type="swing_high",
                price=108,
                event_time="2026-01-01T00:00:00+00:00",
                swing_type="high",
            )
        ]

        zones = detect_order_block_zones(candles, "XAUUSD", "H1", swings=swings, atr_period=2, displacement_atr_multiplier=0.9)

        bullish_zones = [zone for zone in zones if zone.direction == "bullish"]
        self.assertEqual(1, len(bullish_zones))
        self.assertEqual(ORDER_BLOCK_DETECTOR, bullish_zones[0].detector)
        self.assertEqual("order_block", bullish_zones[0].zone_type)
        self.assertEqual(99, bullish_zones[0].price_low)
        self.assertEqual(102, bullish_zones[0].price_high)
        self.assertEqual("swing-high-1", bullish_zones[0].metadata["broken_swing_id"])

    def test_order_block_expires_after_three_days_before_late_invalidation(self) -> None:
        candles = [
            candle("00:00", 100, 103, 99, 102),
            candle("01:00", 102, 103, 98, 99),
            candle("02:00", 99, 113, 98, 112),
            candle_at("2026-01-04T01:00:00+00:00", 112, 114, 111, 113),
            candle_at("2026-01-04T03:00:00+00:00", 101, 102, 96, 98),
        ]
        swings = [
            SwingPoint(
                id="swing-high-1",
                point_type="swing_high",
                price=108,
                event_time="2026-01-01T00:00:00+00:00",
                swing_type="high",
            )
        ]

        zones = detect_order_block_zones(candles, "XAUUSD", "H1", swings=swings, atr_period=2, displacement_atr_multiplier=0.9)

        bullish_zones = [zone for zone in zones if zone.direction == "bullish"]
        self.assertEqual(1, len(bullish_zones))
        self.assertEqual("expired", bullish_zones[0].status)
        self.assertEqual("2026-01-04T02:00:00+00:00", bullish_zones[0].end_time)
        self.assertIsNone(bullish_zones[0].invalidated_at)
        self.assertEqual("smc_zone_max_active_days", bullish_zones[0].metadata["expired_rule"])

    def test_order_block_requires_structure_break(self) -> None:
        candles = [
            candle("00:00", 100, 103, 99, 102),
            candle("01:00", 102, 103, 98, 99),
            candle("02:00", 99, 113, 98, 112),
        ]
        swings = [
            SwingPoint(
                id="swing-high-1",
                point_type="swing_high",
                price=120,
                event_time="2026-01-01T00:00:00+00:00",
                swing_type="high",
            )
        ]

        zones = detect_order_block_zones(candles, "XAUUSD", "H1", swings=swings, atr_period=2, displacement_atr_multiplier=0.9)

        self.assertEqual([], zones)

    def test_order_block_skips_without_opposite_candle(self) -> None:
        candles = [
            candle("00:00", 100, 103, 99, 102),
            candle("01:00", 102, 104, 101, 103),
            candle("02:00", 103, 118, 102, 117),
        ]
        swings = [
            SwingPoint(
                id="swing-high-1",
                point_type="swing_high",
                price=110,
                event_time="2026-01-01T00:00:00+00:00",
                swing_type="high",
            )
        ]

        zones = detect_order_block_zones(candles, "XAUUSD", "H1", swings=swings, atr_period=2, displacement_atr_multiplier=0.9)

        self.assertEqual([], zones)

    def test_detects_liquidity_sweep(self) -> None:
        candles = [
            candle("00:00", 100, 103, 99, 102),
            candle("01:00", 102, 106, 101, 105),
            candle("02:00", 105, 109, 104, 106),
            candle("03:00", 106, 111, 104, 108),
        ]
        swings = [
            SwingPoint(
                id="swing-high-1",
                point_type="swing_high",
                price=110,
                event_time="2026-01-01T02:00:00+00:00",
                swing_type="high",
            )
        ]

        zones = detect_liquidity_sweep_zones(candles, swings, "XAUUSD", "H1", atr_period=2)

        self.assertEqual(1, len(zones))
        self.assertEqual(LIQUIDITY_DETECTOR, zones[0].detector)
        self.assertEqual("liquidity_pool", zones[0].zone_type)
        self.assertEqual("bearish", zones[0].direction)
        self.assertEqual("swept", zones[0].status)

    def test_detects_consolidation_range(self) -> None:
        candles = [
            candle("00:00", 100, 102, 99, 101),
            candle("01:00", 101, 103, 100, 102),
            candle("02:00", 102, 103, 100, 101),
            candle("03:00", 101, 102, 99, 100),
            candle("04:00", 100, 103, 99, 102),
            candle("05:00", 102, 103, 100, 101),
            candle("06:00", 101, 102, 99, 100),
            candle("07:00", 100, 103, 99, 102),
            candle("08:00", 102, 103, 100, 101),
            candle("09:00", 101, 102, 99, 100),
            candle("10:00", 100, 103, 99, 102),
            candle("11:00", 102, 103, 100, 101),
        ]

        zones = detect_consolidation_zones(
            candles,
            "XAUUSD",
            "H1",
            min_candles=12,
            max_candles=12,
            max_width_atr=2.0,
            min_touches=4,
        )

        self.assertEqual(1, len(zones))
        self.assertEqual("consolidation", zones[0].zone_type)
        self.assertEqual("active", zones[0].status)


if __name__ == "__main__":
    unittest.main()
