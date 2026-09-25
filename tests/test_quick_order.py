from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from semi_bot_trading.db import connect, init_db
from semi_bot_trading.quick_order import build_quick_order_geometry, latest_closed_h1_atr


class QuickOrderGeometryTests(unittest.TestCase):
    def test_buy_stop_is_expanded_to_one_h1_atr_and_tp_defaults_to_1_5r(self) -> None:
        result = build_quick_order_geometry(
            side="buy", entry=4300, requested_stop=4295, atr_h1=20, risk_reward=1.5
        )
        self.assertEqual(result.stop_loss, 4280)
        self.assertEqual(result.take_profit, 4330)
        self.assertEqual(result.stop_atr, 1)
        self.assertTrue(result.stop_was_adjusted)

    def test_sell_keeps_a_wider_human_stop_and_recomputes_target(self) -> None:
        result = build_quick_order_geometry(
            side="sell", entry=4300, requested_stop=4330, atr_h1=20, risk_reward=2
        )
        self.assertEqual(result.stop_loss, 4330)
        self.assertEqual(result.take_profit, 4240)
        self.assertEqual(result.stop_atr, 1.5)
        self.assertFalse(result.stop_was_adjusted)

    def test_missing_stop_uses_exactly_one_atr(self) -> None:
        result = build_quick_order_geometry(side="buy", entry=100, requested_stop=None, atr_h1=8)
        self.assertEqual(result.stop_loss, 92)
        self.assertEqual(result.take_profit, 112)

    def test_rejects_stop_on_wrong_side(self) -> None:
        with self.assertRaisesRegex(ValueError, "below entry"):
            build_quick_order_geometry(side="buy", entry=100, requested_stop=101, atr_h1=8)


class QuickOrderAtrTests(unittest.TestCase):
    def test_atr_uses_closed_h1_candles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.db"
            with closing(connect(path)) as conn:
                init_db(conn)
                start = datetime.now(UTC) - timedelta(hours=20)
                for index in range(15):
                    opened = start + timedelta(hours=index)
                    closed = opened + timedelta(hours=1)
                    conn.execute(
                        """INSERT INTO candles
                           (id,symbol,timeframe,open_time,close_time,open,high,low,close,volume,source)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            f"c{index}", "XAUUSD", "H1", opened.isoformat(), closed.isoformat(),
                            100.0, 105.0, 95.0, 100.0, 1.0, "test",
                        ),
                    )
                conn.commit()
                atr, candle_time = latest_closed_h1_atr(conn, "XAUUSD")
            self.assertEqual(atr, 10)
            self.assertEqual(candle_time, (start + timedelta(hours=15)).isoformat())


if __name__ == "__main__":
    unittest.main()
