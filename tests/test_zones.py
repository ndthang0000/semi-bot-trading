from __future__ import annotations

from contextlib import closing
from tempfile import TemporaryDirectory
import json
import unittest
from pathlib import Path

from semi_bot_trading.db import connect, init_db
from semi_bot_trading.zones import (
    CandleSlice,
    PriceZone,
    SwingPoint,
    apply_and_store_zone_lifecycle,
    apply_lifecycle_to_zones,
    apply_lifecycle_to_zone,
    detect_support_resistance_zones,
    replace_price_zones,
)


class ZoneDetectorTest(unittest.TestCase):
    def test_replace_price_zones_rejects_m15_zones(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with closing(connect(db_path)) as conn:
                init_db(conn)
                with self.assertRaisesRegex(ValueError, "H1-context only"):
                    replace_price_zones(conn, "XAUUSD", "M15", "fvg_v1", [])

    def test_replace_price_zones_preserves_human_adjusted_bot_zone(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with connect(db_path) as conn:
                init_db(conn)
                original_bot_zone = PriceZone(
                    symbol="XAUUSD",
                    timeframe="H1",
                    detector="fvg_v1",
                    zone_type="fvg",
                    direction="bearish",
                    price_low=90,
                    price_high=120,
                    start_time="2026-01-01T00:00:00+00:00",
                    end_time="2026-01-03T00:00:00+00:00",
                    valid_from="2026-01-01T00:00:00+00:00",
                    valid_until=None,
                    invalidated_at=None,
                    invalidated_by_structure_point_id=None,
                    detected_at="2026-01-01T00:00:00+00:00",
                    bot_confidence=0.8,
                    bot_weight=0.7,
                    effective_confidence=0.8,
                    effective_weight=0.7,
                    status="active",
                    source="bot",
                    metadata={},
                )
                conn.execute(
                    """
                    INSERT INTO price_zones (
                        id, symbol, timeframe, detector, zone_type, direction,
                        price_low, price_high, start_time, end_time, valid_from, valid_until,
                        invalidated_at, invalidated_by_structure_point_id, detected_at,
                        bot_confidence, bot_weight, effective_confidence, effective_weight,
                        status, source, metadata_json
                    )
                    VALUES (
                        ?, 'XAUUSD', 'H1', 'fvg_v1', 'fvg', 'bearish',
                        100, 110, '2026-01-01T00:00:00+00:00', '2026-01-03T00:00:00+00:00',
                        '2026-01-01T00:00:00+00:00', NULL, NULL, NULL,
                        '2026-01-01T00:00:00+00:00', 0.8, 0.7, 0.9, 0.9,
                        'active', 'mixed', '{"human_adjusted": true}'
                    )
                    """,
                    (original_bot_zone.id,),
                )
                conn.commit()

                count = replace_price_zones(
                    conn,
                    "XAUUSD",
                    "H1",
                    "fvg_v1",
                    [original_bot_zone],
                )
                row = conn.execute("SELECT * FROM price_zones WHERE id = ?", (original_bot_zone.id,)).fetchone()
                row_count = conn.execute("SELECT COUNT(*) AS count FROM price_zones").fetchone()["count"]

        self.assertEqual(1, count)
        self.assertEqual(1, row_count)
        self.assertEqual("mixed", row["source"])
        self.assertEqual(100, row["price_low"])
        self.assertEqual(110, row["price_high"])

    def test_replace_price_zones_skips_bot_duplicate_when_human_zone_id_changed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with connect(db_path) as conn:
                init_db(conn)
                human_adjusted_zone_id = "human-adjusted-fvg"
                conn.execute(
                    """
                    INSERT INTO price_zones (
                        id, symbol, timeframe, detector, zone_type, direction,
                        price_low, price_high, start_time, end_time, valid_from, valid_until,
                        invalidated_at, invalidated_by_structure_point_id, detected_at,
                        bot_confidence, bot_weight, effective_confidence, effective_weight,
                        status, source, metadata_json
                    )
                    VALUES (
                        ?, 'XAUUSD', 'H1', 'fvg_v1', 'fvg', 'bearish',
                        100, 110, '2026-01-01T00:00:00+00:00', '2026-01-03T00:00:00+00:00',
                        '2026-01-01T00:00:00+00:00', NULL, NULL, NULL,
                        '2026-01-01T00:00:00+00:00', 0.8, 0.7, 0.9, 0.9,
                        'active', 'mixed', '{"human_adjusted": true}'
                    )
                    """,
                    (human_adjusted_zone_id,),
                )
                conn.commit()

                count = replace_price_zones(
                    conn,
                    "XAUUSD",
                    "H1",
                    "fvg_v1",
                    [
                        PriceZone(
                            symbol="XAUUSD",
                            timeframe="H1",
                            detector="fvg_v1",
                            zone_type="fvg",
                            direction="bearish",
                            price_low=90,
                            price_high=120,
                            start_time="2026-01-01T00:00:00+00:00",
                            end_time="2026-01-03T00:00:00+00:00",
                            valid_from="2026-01-01T00:00:00+00:00",
                            valid_until=None,
                            invalidated_at=None,
                            invalidated_by_structure_point_id=None,
                            detected_at="2026-01-01T00:00:00+00:00",
                            bot_confidence=0.8,
                            bot_weight=0.7,
                            effective_confidence=0.8,
                            effective_weight=0.7,
                            status="active",
                            source="bot",
                            metadata={},
                        )
                    ],
                )
                row_count = conn.execute("SELECT COUNT(*) AS count FROM price_zones").fetchone()["count"]
                row = conn.execute("SELECT * FROM price_zones WHERE id = ?", (human_adjusted_zone_id,)).fetchone()

        self.assertEqual(1, count)
        self.assertEqual(1, row_count)
        self.assertEqual("mixed", row["source"])
        self.assertEqual(100, row["price_low"])
        self.assertEqual(110, row["price_high"])

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

    def test_store_lifecycle_invalidates_human_sr_after_creation_breakout(self) -> None:
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
                        ("c1", "2026-01-01T10:00:00+00:00", "2026-01-01T11:00:00+00:00", 103, 105, 101, 103),
                        ("c2", "2026-01-01T11:00:00+00:00", "2026-01-01T12:00:00+00:00", 103, 104, 94, 95),
                    ],
                )
                conn.execute(
                    """
                    INSERT INTO price_zones (
                        id, symbol, timeframe, detector, zone_type, direction,
                        price_low, price_high, start_time, end_time, valid_from, valid_until,
                        invalidated_at, invalidated_by_structure_point_id, detected_at,
                        bot_confidence, bot_weight, effective_confidence, effective_weight,
                        status, source, metadata_json, created_at
                    )
                    VALUES (
                        'human-support', 'XAUUSD', 'H1', 'human_manual_v1', 'support', 'bullish',
                        100, 105, '2026-01-01T00:00:00+00:00', '2026-01-03T00:00:00+00:00',
                        '2026-01-01T00:00:00+00:00', '2026-01-03T00:00:00+00:00',
                        NULL, NULL, '2026-01-01T00:00:00+00:00',
                        1.0, 0.8, 1.0, 0.8, 'active', 'human',
                        '{"human_created": true, "last_human_override_at": "2026-01-01T10:30:00+00:00"}',
                        '2026-01-01 10:30:00'
                    )
                    """
                )

                updates = apply_and_store_zone_lifecycle(
                    conn,
                    "XAUUSD",
                    "H1",
                    close_break_buffer=0.0,
                    recent_touch_lookback_candles=10,
                    age_decay_per_100_candles=0.08,
                    freshness_bonus=0.15,
                    invalidation_weight_multiplier=0.15,
                )
                row = conn.execute("SELECT * FROM price_zones WHERE id = 'human-support'").fetchone()

        metadata = json.loads(row["metadata_json"])
        self.assertGreaterEqual(updates, 1)
        self.assertEqual("invalidated", row["status"])
        self.assertEqual("2026-01-01T11:00:00+00:00", row["invalidated_at"])
        self.assertEqual(row["invalidated_at"], row["end_time"])
        self.assertEqual(row["invalidated_at"], row["valid_until"])
        self.assertEqual("human", metadata["sr_lifecycle_applied_to_source"])
        self.assertEqual("2026-01-01T10:30:00+00:00", metadata["sr_lifecycle_start"])

    def test_store_lifecycle_does_not_backdate_human_sr_invalidation_before_creation(self) -> None:
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
                        ("c1", "2026-01-01T09:00:00+00:00", "2026-01-01T10:00:00+00:00", 103, 104, 94, 95),
                        ("c2", "2026-01-01T10:00:00+00:00", "2026-01-01T11:00:00+00:00", 103, 105, 101, 103),
                    ],
                )
                conn.execute(
                    """
                    INSERT INTO price_zones (
                        id, symbol, timeframe, detector, zone_type, direction,
                        price_low, price_high, start_time, end_time, valid_from, valid_until,
                        invalidated_at, invalidated_by_structure_point_id, detected_at,
                        bot_confidence, bot_weight, effective_confidence, effective_weight,
                        status, source, metadata_json, created_at
                    )
                    VALUES (
                        'human-support', 'XAUUSD', 'H1', 'human_manual_v1', 'support', 'bullish',
                        100, 105, '2026-01-01T00:00:00+00:00', '2026-01-03T00:00:00+00:00',
                        '2026-01-01T00:00:00+00:00', '2026-01-03T00:00:00+00:00',
                        NULL, NULL, '2026-01-01T00:00:00+00:00',
                        1.0, 0.8, 1.0, 0.8, 'active', 'human',
                        '{"human_created": true, "last_human_override_at": "2026-01-01T10:30:00+00:00"}',
                        '2026-01-01 10:30:00'
                    )
                    """
                )

                apply_and_store_zone_lifecycle(
                    conn,
                    "XAUUSD",
                    "H1",
                    close_break_buffer=0.0,
                    recent_touch_lookback_candles=10,
                    age_decay_per_100_candles=0.08,
                    freshness_bonus=0.15,
                    invalidation_weight_multiplier=0.15,
                )
                row = conn.execute("SELECT * FROM price_zones WHERE id = 'human-support'").fetchone()

        self.assertEqual("active", row["status"])
        self.assertIsNone(row["invalidated_at"])

    def test_false_break_refines_support_and_disables_parent_for_trade(self) -> None:
        swings = [
            SwingPoint("l1", "HL", 100, "2026-01-01T01:00:00+00:00", "low"),
            SwingPoint("l2", "HL", 101, "2026-01-01T04:00:00+00:00", "low"),
        ]
        zone = detect_support_resistance_zones(
            swings,
            symbol="XAUUSD",
            timeframe="H1",
            tolerance_pct=0.001,
            min_zone_width=1.0,
            min_touches=2,
            max_zones=10,
            atr_value=4.0,
            atr_width_multiplier=0.25,
        )[0]
        candles = [
            CandleSlice("2026-01-01T04:00:00+00:00", open=103, high=104, low=101, close=103),
            CandleSlice("2026-01-01T05:00:00+00:00", open=102, high=105, low=97, close=103),
            CandleSlice("2026-01-01T06:00:00+00:00", open=103, high=106, low=102, close=105),
        ]

        updated = apply_lifecycle_to_zones(
            [zone],
            candles,
            close_break_buffer=0.0,
            recent_touch_lookback_candles=10,
            age_decay_per_100_candles=0.08,
            freshness_bonus=0.15,
            invalidation_weight_multiplier=0.15,
            false_break_refine_enabled=True,
            false_break_refine_max_width_atr_multiplier=0.8,
            false_break_parent_weight_multiplier=0.35,
        )

        parent = next(item for item in updated if item.id == zone.id)
        children = [item for item in updated if item.metadata.get("parent_zone_id") == zone.id]
        self.assertTrue(parent.metadata["trade_disabled_after_sweep"])
        self.assertEqual(parent.metadata["false_break_count"], 1)
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0].zone_type, "support")
        self.assertEqual(children[0].metadata["refined_from_false_break"], True)
        self.assertEqual(children[0].price_low, 97)
        self.assertLess(children[0].price_high, zone.price_high)


if __name__ == "__main__":
    unittest.main()
