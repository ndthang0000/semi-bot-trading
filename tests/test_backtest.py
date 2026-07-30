from __future__ import annotations

import unittest
from pathlib import Path
from tests.helpers import TemporaryDirectory

from semi_bot_trading.backtest import (
    BacktestResult,
    BacktestTrade,
    apply_fvg_trade_count,
    apply_zone_loss_cooldown,
    candidate_is_carried_forward,
    candidates_for_backtest_execution,
    candidates_after_fvg_trade_count,
    candidates_after_zone_loss_cooldown,
    exit_on_candle,
    load_backtest_candles,
    persist_backtest_result,
    simulate_trade,
)
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
        "playbook": "zone_reaction_v2",
        "direction": direction,
        "score": 0.9,
        "zone_reaction_state": "rejected",
        "stop_loss": 95 if direction == "long" else 105,
        "take_profit": [110 if direction == "long" else 90],
        "risk_reward": 2.0,
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

    def test_long_exit_uses_bid_side_for_trigger_without_extra_exit_slippage(self) -> None:
        hit = exit_on_candle(candle("00:15", 100, 111, 99, 109), "long", stop=95, take_profit=110, half_spread=0.2, slippage=0.1)

        self.assertEqual(("target_hit", 110), hit)

    def test_short_stop_uses_ask_side_for_trigger_without_extra_exit_slippage(self) -> None:
        hit = exit_on_candle(candle("00:15", 100, 106, 90, 95), "short", stop=105, take_profit=90, half_spread=0.2, slippage=0.1)

        self.assertEqual(("stopped", 105), hit)

    def test_take_profit_is_recomputed_from_filled_entry_to_keep_two_r(self) -> None:
        candles = [
            candle("00:00", 100, 102, 98, 101),
            candle("00:15", 102, 104, 99, 103),
            candle("00:30", 103, 118, 102, 116),
        ]

        trade = simulate_trade(candidate("long"), candles, signal_index=0, spread=0.4, slippage=0.1, max_hold_candles=4)

        self.assertIsNotNone(trade)
        assert trade is not None
        self.assertEqual(102.3, trade.entry_price)
        self.assertEqual(116.9, trade.take_profit)
        self.assertEqual(2.0, trade.pnl_r)

    def test_same_candle_stop_and_target_is_conservative(self) -> None:
        hit = exit_on_candle(candle("00:15", 100, 111, 94, 101), "long", stop=95, take_profit=110, half_spread=0.0, slippage=0.0)

        self.assertEqual(("stopped", 95.0), hit)

    def test_backtest_does_not_execute_ui_only_carried_forward_candidate(self) -> None:
        fresh = {**candidate("long"), "status": "eligible", "metadata": {"as_of": "2026-01-01T00:15:00+00:00"}}
        carried = {
            **candidate("long"),
            "id": "setup-carried",
            "status": "eligible",
            "metadata": {
                "as_of": "2026-01-01T00:15:00+00:00",
                "carried_forward": True,
                "carried_forward_current_as_of": "2026-01-01T00:30:00+00:00",
            },
        }

        self.assertFalse(candidate_is_carried_forward(fresh))
        self.assertTrue(candidate_is_carried_forward(carried))
        self.assertEqual([fresh], candidates_for_backtest_execution([carried, fresh], {"eligible"}))
        self.assertIsNone(
            simulate_trade(
                carried,
                [
                    candle("00:00", 100, 102, 98, 101),
                    candle("00:15", 102, 111, 99, 110),
                ],
                signal_index=0,
                spread=0.4,
                slippage=0.1,
                max_hold_candles=4,
            )
        )

    def test_zone_loss_cooldown_blocks_same_zone_for_configured_bars(self) -> None:
        cooldown: dict[str, int] = {}
        trade = backtest_trade(primary_zone_id="zone-a", pnl_r=-1.0)

        apply_zone_loss_cooldown(cooldown, trade, exit_index=10, cooldown_candles=12)

        self.assertEqual(23, cooldown["zone-a"])
        blocked = candidates_after_zone_loss_cooldown([{"primary_zone_id": "zone-a"}], cooldown, signal_index=22)
        allowed = candidates_after_zone_loss_cooldown([{"primary_zone_id": "zone-a"}], cooldown, signal_index=23)
        other_zone = candidates_after_zone_loss_cooldown([{"primary_zone_id": "zone-b"}], cooldown, signal_index=11)
        self.assertEqual([], blocked)
        self.assertEqual([{"primary_zone_id": "zone-a"}], allowed)
        self.assertEqual([{"primary_zone_id": "zone-b"}], other_zone)

    def test_zone_loss_cooldown_ignores_winning_trades(self) -> None:
        cooldown: dict[str, int] = {}

        apply_zone_loss_cooldown(cooldown, backtest_trade(primary_zone_id="zone-a", pnl_r=2.0), exit_index=10, cooldown_candles=12)

        self.assertEqual({}, cooldown)

    def test_fvg_trade_count_blocks_third_trade_for_same_zone(self) -> None:
        counts: dict[str, int] = {}
        fvg_candidate = {"primary_zone_id": "zone-a", "metadata": {"zone_type": "fvg"}}
        support_candidate = {"primary_zone_id": "zone-a", "metadata": {"zone_type": "support"}}
        fvg_trade = backtest_trade(primary_zone_id="zone-a", pnl_r=2.0)
        fvg_trade.metadata["candidate_metadata"] = {"zone_type": "fvg"}

        apply_fvg_trade_count(counts, fvg_trade, max_trades_per_zone=2)
        self.assertEqual([fvg_candidate], candidates_after_fvg_trade_count([fvg_candidate], counts, max_trades_per_zone=2))

        apply_fvg_trade_count(counts, fvg_trade, max_trades_per_zone=2)
        self.assertEqual([], candidates_after_fvg_trade_count([fvg_candidate], counts, max_trades_per_zone=2))
        self.assertEqual(
            [support_candidate],
            candidates_after_fvg_trade_count([support_candidate], counts, max_trades_per_zone=2),
        )

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
        self.assertEqual("zone_reaction_v2", payload["layers"]["trades"][0]["playbook"])

    def test_clear_previous_backtest_trades_removes_reviews_first(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with connect(db_path) as conn:
                init_db(conn)
                seed_candles(conn)
                trade = simulate_trade(
                    candidate("long"),
                    [candle("00:00", 100, 102, 98, 101), candle("00:15", 102, 111, 99, 110)],
                    0,
                    0.4,
                    0.1,
                    4,
                )
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
                persist_backtest_result(conn, result, candle_limit=2)
                old_order_id = conn.execute("SELECT id FROM trade_orders WHERE source = 'backtest'").fetchone()["id"]
                conn.execute(
                    """
                    INSERT INTO trade_reviews (
                        id, trade_order_id, grade, verdict, mistake_tags_json,
                        should_trade_again, comment, reviewer
                    )
                    VALUES ('review-1', ?, 'bad', 'rejected', '[]', 'no', 'old run', 'human')
                    """,
                    (old_order_id,),
                )
                conn.commit()

                persist_backtest_result(conn, result, candle_limit=2, clear_previous=True)

                review_count = conn.execute("SELECT COUNT(*) AS count FROM trade_reviews").fetchone()["count"]
                order_count = conn.execute("SELECT COUNT(*) AS count FROM trade_orders WHERE source = 'backtest'").fetchone()["count"]

        self.assertEqual(0, review_count)
        self.assertEqual(1, order_count)

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


def backtest_trade(primary_zone_id: str | None, pnl_r: float) -> BacktestTrade:
    return BacktestTrade(
        playbook="zone_reaction_v2",
        direction="long",
        status="stopped" if pnl_r < 0 else "target_hit",
        signal_time="2026-01-01T00:00:00+00:00",
        entry_time="2026-01-01T00:15:00+00:00",
        exit_time="2026-01-01T00:30:00+00:00",
        entry_price=100,
        stop_loss=95,
        take_profit=110,
        exit_price=95 if pnl_r < 0 else 110,
        pnl_r=pnl_r,
        setup_id="setup-1",
        score=0.5,
        risk_reward=2.0,
        primary_zone_id=primary_zone_id,
        related_zone_ids=[primary_zone_id] if primary_zone_id else [],
        trigger_point_ids=[],
        reason=[],
        metadata={},
    )


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
