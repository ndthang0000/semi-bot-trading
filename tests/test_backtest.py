from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from semi_bot_trading.backtest import BacktestResult, persist_backtest_result, exit_on_candle, load_backtest_candles, simulate_trade
from semi_bot_trading.chart import build_chart_payload
from semi_bot_trading.db import connect, init_db


def candle(time: str, open_: float, high: float, low: float, close: float) -> dict[str, object]:
    return {
        "time": f"2026-01-01T{time}:00+00:00",
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": 100,
    }


def db_candle(open_time: str, close_time: str, open_: float, high: float, low: float, close: float) -> dict[str, object]:
    return {
        "time": close_time,
        "open_time": open_time,
        "close_time": close_time,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": 100,
    }


def candidate(direction: str = "long") -> dict[str, object]:
    return {
        "id": "setup-1",
        "playbook": "trend_pullback",
        "direction": direction,
        "score": 0.9,
        "zone_reaction_state": "rejected",
        "stop_loss": 95 if direction == "long" else 105,
        "take_profit": [110 if direction == "long" else 90],
    }


class BacktestTest(unittest.TestCase):
    def test_entry_is_next_candle_with_spread_and_slippage(self) -> None:
        candles = [
            candle("00:00", 100, 102, 98, 101),
            candle("00:15", 102, 104, 99, 103),
            candle("00:30", 103, 111, 102, 110),
        ]

        trade = simulate_trade(candidate("long"), candles, signal_index=0, spread=0.4, slippage=0.1, max_hold_candles=4)

        self.assertIsNotNone(trade)
        assert trade is not None
        self.assertEqual("2026-01-01T00:15:00+00:00", trade.entry_time)
        self.assertEqual(102.3, trade.entry_price)

    def test_backtest_signal_uses_close_time_and_entry_uses_next_open_time(self) -> None:
        candles = [
            db_candle("2026-01-01T00:00:00+00:00", "2026-01-01T00:15:00+00:00", 100, 102, 98, 101),
            db_candle("2026-01-01T00:15:00+00:00", "2026-01-01T00:30:00+00:00", 102, 104, 99, 103),
            db_candle("2026-01-01T00:30:00+00:00", "2026-01-01T00:45:00+00:00", 103, 111, 102, 110),
        ]

        trade = simulate_trade(candidate("long"), candles, signal_index=0, spread=0.4, slippage=0.1, max_hold_candles=4)

        self.assertIsNotNone(trade)
        assert trade is not None
        self.assertEqual("2026-01-01T00:15:00+00:00", trade.signal_time)
        self.assertEqual("2026-01-01T00:15:00+00:00", trade.entry_time)

    def test_long_exit_uses_bid_side_costs(self) -> None:
        hit = exit_on_candle(candle("00:15", 100, 111, 99, 109), "long", stop=95, take_profit=110, half_spread=0.2, slippage=0.1)

        self.assertEqual(("target_hit", 109.9), hit)

    def test_short_stop_uses_ask_side_costs(self) -> None:
        hit = exit_on_candle(candle("00:15", 100, 106, 90, 95), "short", stop=105, take_profit=90, half_spread=0.2, slippage=0.1)

        self.assertEqual(("stopped", 105.1), hit)

    def test_same_candle_stop_and_target_is_conservative(self) -> None:
        hit = exit_on_candle(candle("00:15", 100, 111, 94, 101), "long", stop=95, take_profit=110, half_spread=0.0, slippage=0.0)

        self.assertEqual(("stopped", 95.0), hit)

    def test_persisted_backtest_trade_is_visible_in_chart_payload(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with connect(db_path) as conn:
                init_db(conn)
                seed_candles(conn)
                trade = simulate_trade(candidate("long"), [candle("00:00", 100, 102, 98, 101), candle("00:15", 102, 111, 99, 110)], 0, 0.4, 0.1, 4)
                self.assertIsNotNone(trade)
                assert trade is not None
                result = BacktestResult(
                    trades=[trade],
                    timeline_count=2,
                    evaluated_candles=1,
                    lookahead_guard="test guard",
                    spread=0.4,
                    slippage=0.1,
                    auto_accept=True,
                    max_hold_candles=4,
                    warmup_candles=0,
                    symbol="XAUUSD",
                    strategy_timeframe="M15",
                    context_timeframe="H1",
                    engine="incremental",
                )
                run_id = persist_backtest_result(conn, result, candle_limit=2)
                payload = build_chart_payload(conn, "XAUUSD", "M15", limit=2)
                run_count = conn.execute("SELECT COUNT(*) AS count FROM backtest_runs").fetchone()["count"]

        self.assertTrue(run_id.startswith("backtest-run-"))
        self.assertEqual(1, run_count)
        self.assertEqual(1, len(payload["layers"]["trades"]))
        self.assertEqual("backtest", payload["layers"]["trades"][0]["source"])
        self.assertEqual("trend_pullback", payload["layers"]["trades"][0]["playbook"])

    def test_load_backtest_candles_exposes_close_time_as_decision_time(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with connect(db_path) as conn:
                init_db(conn)
                seed_candles(conn)
                candles = load_backtest_candles(conn, "XAUUSD", "M15", 2)

        self.assertEqual("2026-01-01T00:15:00+00:00", candles[0]["time"])
        self.assertEqual("2026-01-01T00:00:00+00:00", candles[0]["open_time"])
        self.assertEqual("2026-01-01T00:15:00+00:00", candles[0]["close_time"])

def seed_candles(conn) -> None:
    conn.executemany(
        """
        INSERT INTO candles (
            id, symbol, timeframe, open_time, close_time, open, high, low, close, volume, source
        )
        VALUES (?, 'XAUUSD', 'M15', ?, ?, ?, ?, ?, ?, 100, 'test')
        """,
        [
            ("c1", "2026-01-01T00:00:00+00:00", "2026-01-01T00:15:00+00:00", 100, 102, 98, 101),
            ("c2", "2026-01-01T00:15:00+00:00", "2026-01-01T00:30:00+00:00", 102, 111, 99, 110),
        ],
    )
    conn.commit()


if __name__ == "__main__":
    unittest.main()
