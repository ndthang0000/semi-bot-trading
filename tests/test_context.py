from __future__ import annotations

import json
import unittest
from pathlib import Path
from tests.helpers import TemporaryDirectory

from semi_bot_trading.context import detect_bias_context, detect_regime_context, replace_active_context, score_macro_trend
from semi_bot_trading.db import connect, init_db


def macro_candles(closes: list[float]) -> list[dict[str, object]]:
    return [
        {
            "open_time": f"2026-01-{(index // 24) + 1:02d}T{index % 24:02d}:00:00+00:00",
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
        }
        for index, close in enumerate(closes)
    ]


class MacroTrendTest(unittest.TestCase):
    def test_rising_closes_produce_up_trend(self) -> None:
        candles = macro_candles([100.0 + index for index in range(40)])
        score = score_macro_trend(candles, lookback_candles=20, flat_threshold_atr=0.0, atr_period=14)
        self.assertEqual("up", score["value"])
        self.assertGreater(score["momentum_atr"], 0)

    def test_falling_closes_produce_down_trend(self) -> None:
        candles = macro_candles([200.0 - index for index in range(40)])
        score = score_macro_trend(candles, lookback_candles=20, flat_threshold_atr=0.0, atr_period=14)
        self.assertEqual("down", score["value"])
        self.assertLess(score["momentum_atr"], 0)

    def test_small_momentum_below_threshold_is_flat(self) -> None:
        closes = [100.0, 100.5] * 20
        candles = macro_candles(closes)
        score = score_macro_trend(candles, lookback_candles=20, flat_threshold_atr=2.0, atr_period=14)
        self.assertEqual("flat", score["value"])

    def test_insufficient_history_is_unknown(self) -> None:
        candles = macro_candles([100.0 + index for index in range(10)])
        score = score_macro_trend(candles, lookback_candles=720, flat_threshold_atr=0.0, atr_period=14)
        self.assertEqual("unknown", score["value"])
        self.assertIsNone(score["momentum_atr"])


class BiasContextTest(unittest.TestCase):
    def test_detects_bullish_bias_from_structure_and_breaks(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with connect(db_path) as conn:
                init_db(conn)
                seed_structure(conn)
                context = detect_bias_context(
                    conn,
                    symbol="XAUUSD",
                    timeframe="H1",
                    recent_swings=4,
                    recent_breaks=2,
                )
                replace_active_context(conn, context)
                rows = conn.execute("SELECT * FROM market_contexts").fetchall()

        self.assertEqual(context.effective_value, "bullish")
        self.assertGreater(context.effective_confidence, 0)
        self.assertEqual(len(rows), 1)

    def test_opposing_choch_neutralizes_directional_bias(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with connect(db_path) as conn:
                init_db(conn)
                seed_structure_rows(
                    conn,
                    [
                        ("s1", "HH", 101, "2026-01-01T00:00:00+00:00", {}),
                        ("s2", "HL", 95, "2026-01-01T01:00:00+00:00", {}),
                        ("s3", "HH", 105, "2026-01-01T02:00:00+00:00", {}),
                        ("s4", "HL", 99, "2026-01-01T03:00:00+00:00", {}),
                        ("b1", "BOS", 105, "2026-01-01T04:00:00+00:00", {"direction": "up"}),
                        ("b2", "CHOCH", 99, "2026-01-01T05:00:00+00:00", {"direction": "down"}),
                    ],
                )
                context = detect_bias_context(
                    conn,
                    symbol="XAUUSD",
                    timeframe="H1",
                    recent_swings=4,
                    recent_breaks=2,
                )

        self.assertEqual(context.effective_value, "neutral")
        self.assertEqual(context.metadata["neutral_reason"], "opposing_choch_down")
        self.assertTrue(context.metadata["choch_neutralized"])

    def test_weak_directional_score_in_range_becomes_neutral(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with connect(db_path) as conn:
                init_db(conn)
                seed_range_candles(conn)
                seed_structure_rows(
                    conn,
                    [
                        ("s1", "HH", 101, "2026-01-01T00:00:00+00:00", {}),
                        ("s2", "LH", 99, "2026-01-01T01:00:00+00:00", {}),
                        ("s3", "HL", 96, "2026-01-01T02:00:00+00:00", {}),
                    ],
                )
                context = detect_bias_context(
                    conn,
                    symbol="XAUUSD",
                    timeframe="H1",
                    recent_swings=3,
                    recent_breaks=0,
                )

        self.assertEqual(context.effective_value, "neutral")
        self.assertEqual(context.metadata["neutral_reason"], "ranging_structure_weak")
        self.assertTrue(context.metadata["range_neutralized"])

    def test_detects_trending_regime_from_directional_breaks(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with connect(db_path) as conn:
                init_db(conn)
                seed_candles(conn)
                seed_breaks(conn)
                context = detect_regime_context(
                    conn,
                    symbol="XAUUSD",
                    timeframe="H1",
                    atr_period=3,
                    lookback=8,
                    atr_high_percentile=0.8,
                    atr_low_percentile=0.2,
                    expansion_atr_ratio=1.2,
                    contraction_atr_ratio=0.8,
                    trend_break_ratio=0.6,
                    trend_min_bos=2,
                    range_efficiency_max=0.25,
                )

        self.assertEqual(context.effective_value, "trending")
        self.assertIn("overlays", context.metadata)


def seed_structure(conn) -> None:
    rows = [
        ("1", "HH", 101, "2026-01-01T00:00:00+00:00", {}),
        ("2", "HL", 95, "2026-01-01T01:00:00+00:00", {}),
        ("3", "HH", 105, "2026-01-01T02:00:00+00:00", {}),
        ("4", "HL", 99, "2026-01-01T03:00:00+00:00", {}),
        ("5", "BOS", 105, "2026-01-01T04:00:00+00:00", {"direction": "up"}),
    ]
    seed_structure_rows(conn, rows)


def seed_structure_rows(conn, rows) -> None:
    conn.executemany(
        """
        INSERT INTO structure_points (
            id, symbol, timeframe, detector, status, point_type, price, event_time,
            confidence, related_zone_ids_json, metadata_json
        )
        VALUES (?, 'XAUUSD', 'H1', 'test', 'confirmed', ?, ?, ?, 1.0, '[]', ?)
        """,
        [(row_id, point_type, price, event_time, json.dumps(metadata)) for row_id, point_type, price, event_time, metadata in rows],
    )
    conn.commit()


def seed_range_candles(conn) -> None:
    rows = []
    for index in range(20):
        close = 100 + (index % 2)
        rows.append(
            (
                f"range-candle-{index}",
                "XAUUSD",
                "H1",
                f"2026-01-01T{index:02d}:00:00+00:00",
                f"2026-01-01T{index + 1:02d}:00:00+00:00",
                close,
                close + 2,
                close - 2,
                close,
                100,
                "test",
            )
        )
    conn.executemany(
        """
        INSERT INTO candles (
            id, symbol, timeframe, open_time, close_time, open, high, low, close, volume, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def seed_candles(conn) -> None:
    rows = []
    for index in range(12):
        price = 2000 + index * 2
        rows.append(
            (
                f"candle-{index}",
                "XAUUSD",
                "H1",
                f"2026-01-01T{index:02d}:00:00+00:00",
                f"2026-01-01T{index + 1:02d}:00:00+00:00",
                price,
                price + 3,
                price - 1,
                price + 2,
                100,
                "test",
            )
        )
    conn.executemany(
        """
        INSERT INTO candles (
            id, symbol, timeframe, open_time, close_time, open, high, low, close, volume, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


def seed_breaks(conn) -> None:
    rows = [
        ("b1", "BOS", 2005, "2026-01-01T08:00:00+00:00", {"direction": "up"}),
        ("b2", "BOS", 2010, "2026-01-01T09:00:00+00:00", {"direction": "up"}),
        ("b3", "BOS", 2015, "2026-01-01T10:00:00+00:00", {"direction": "up"}),
    ]
    conn.executemany(
        """
        INSERT INTO structure_points (
            id, symbol, timeframe, detector, status, point_type, price, event_time,
            confidence, related_zone_ids_json, metadata_json
        )
        VALUES (?, 'XAUUSD', 'H1', 'break_v1', 'confirmed', ?, ?, ?, 1.0, '[]', ?)
        """,
        [(row_id, point_type, price, event_time, json.dumps(metadata)) for row_id, point_type, price, event_time, metadata in rows],
    )
    conn.commit()


if __name__ == "__main__":
    unittest.main()
