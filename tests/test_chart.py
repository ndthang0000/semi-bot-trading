from __future__ import annotations

import json
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from semi_bot_trading.chart import build_chart_payload
from semi_bot_trading.db import connect, init_db


class ChartPayloadTest(unittest.TestCase):
    def test_builds_chart_payload_contract(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with closing(connect(db_path)) as conn:
                init_db(conn)
                seed_chart_data(conn)
                payload = build_chart_payload(conn, "XAUUSD", "M15", limit=2)

        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["symbol"], "XAUUSD")
        self.assertEqual(payload["timeframe"], "M15")
        self.assertEqual(len(payload["layers"]["candles"]), 2)
        self.assertIn("structure", payload["layers"])
        self.assertEqual(payload["layers"]["structure_timeframe"], "M15")
        self.assertIn("zones", payload["layers"])
        self.assertIn("contexts", payload["layers"])
        self.assertIn("trades", payload["layers"])
        self.assertIn("setup_candidates", payload["layers"])
        self.assertEqual(payload["layers"]["setup_candidates"], [])
        self.assertEqual(payload["layers"]["zones"][0]["timeframe"], "M15")
        self.assertEqual(payload["layers"]["contexts"]["H1"]["bias"]["effective_value"], "bullish")
        self.assertEqual(payload["layers"]["contexts"]["M15"]["bias"]["effective_value"], "bullish")
        self.assertEqual(payload["layers"]["zones"][0]["visual_end"], "2026-01-08T00:15:00+00:00")

    def test_can_render_m15_chart_with_h1_structure(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with closing(connect(db_path)) as conn:
                init_db(conn)
                seed_chart_data(conn)
                payload = build_chart_payload(conn, "XAUUSD", "M15", limit=2, structure_timeframe="H1")

        self.assertEqual(payload["timeframe"], "M15")
        self.assertEqual(payload["layers"]["structure_timeframe"], "H1")
        self.assertEqual(payload["layers"]["structure"][0]["id"], "h1-s1")


def seed_chart_data(conn) -> None:
    candles = [
        ("c1", "2026-01-01T00:00:00+00:00", "2026-01-01T00:15:00+00:00", 2000, 2002, 1999, 2001),
        ("c2", "2026-01-01T00:15:00+00:00", "2026-01-01T00:30:00+00:00", 2001, 2004, 2000, 2003),
    ]
    conn.executemany(
        """
        INSERT INTO candles (
            id, symbol, timeframe, open_time, close_time, open, high, low, close, volume, source
        )
        VALUES (?, 'XAUUSD', 'M15', ?, ?, ?, ?, ?, ?, 100, 'test')
        """,
        candles,
    )
    conn.execute(
        """
        INSERT INTO structure_points (
            id, symbol, timeframe, detector, status, point_type, price, event_time,
            confidence, related_zone_ids_json, metadata_json
        )
        VALUES ('s1', 'XAUUSD', 'M15', 'swing_v1', 'confirmed', 'HH', 2004,
                '2026-01-01T00:15:00+00:00', 1.0, '[]', '{}')
        """
    )
    conn.execute(
        """
        INSERT INTO structure_points (
            id, symbol, timeframe, detector, status, point_type, price, event_time,
            confidence, related_zone_ids_json, metadata_json
        )
        VALUES ('h1-s1', 'XAUUSD', 'H1', 'swing_v1', 'confirmed', 'HH', 2005,
                '2026-01-01T00:15:00+00:00', 1.0, '[]', '{}')
        """
    )
    conn.execute(
        """
        INSERT INTO price_zones (
            id, symbol, timeframe, detector, zone_type, direction, price_low, price_high,
            start_time, end_time, valid_from, valid_until, invalidated_at,
            invalidated_by_structure_point_id, detected_at, bot_confidence, bot_weight,
            effective_confidence, effective_weight, status, source, metadata_json
        )
        VALUES ('z1', 'XAUUSD', 'M15', 'sr_v1', 'support', 'bullish', 1990, 1995,
                '2026-01-01T00:00:00+00:00', '2027-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00',
                '2027-01-01T00:00:00+00:00', NULL, NULL, '2026-01-01T00:00:00+00:00',
                0.8, 0.7, 0.8, 0.7, 'active', 'bot', ?)
        """,
        (json.dumps({"touch_count": 2}),),
    )
    conn.execute(
        """
        INSERT INTO market_contexts (
            id, symbol, timeframe, context_type, bot_value, primary_value, secondary_value,
            bot_confidence, effective_value, effective_confidence, source, valid_from,
            valid_until, status, metadata_json
        )
        VALUES ('ctx1', 'XAUUSD', 'M15', 'bias', 'bullish', 'bullish', NULL,
                0.8, 'bullish', 0.8, 'bot', '2026-01-01T00:15:00+00:00',
                NULL, 'active', '{}')
        """
    )
    conn.execute(
        """
        INSERT INTO market_contexts (
            id, symbol, timeframe, context_type, bot_value, primary_value, secondary_value,
            bot_confidence, effective_value, effective_confidence, source, valid_from,
            valid_until, status, metadata_json
        )
        VALUES ('ctx2', 'XAUUSD', 'H1', 'bias', 'bullish', 'bullish', NULL,
                0.9, 'bullish', 0.9, 'bot', '2026-01-01T00:00:00+00:00',
                NULL, 'active', '{}')
        """
    )
    conn.commit()


if __name__ == "__main__":
    unittest.main()
