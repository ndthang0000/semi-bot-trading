from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from semi_bot_trading.context import detect_bias_context, detect_regime_context, replace_active_context
from semi_bot_trading.db import connect, init_db


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
