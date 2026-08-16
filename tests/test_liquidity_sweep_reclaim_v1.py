from __future__ import annotations

import json
import sqlite3
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from semi_bot_trading.config import load_config
from semi_bot_trading.chart import attach_liquidity_sweep_states
from semi_bot_trading.db import init_db
from semi_bot_trading.strategy.liquidity_sweep_reclaim_v1 import (
    LiquiditySweepState,
    evaluate_live_buy_liquidity_zones,
    evaluate_live_liquidity_zones,
    liquidity_sweep_rr_for_stop,
    transition_buy_liquidity_sweep,
    transition_liquidity_sweep,
)


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


class LiquiditySweepTransitionTests(unittest.TestCase):
    def touch(self) -> LiquiditySweepState:
        result = transition_buy_liquidity_sweep(
            LiquiditySweepState(), now=NOW, bid=100.0, ask=100.2,
            price_low=100.0, price_high=105.0, atr=2.0,
            timeout_minutes=15, max_sweep_atr=1.0,
        )
        self.assertEqual("waiting_reclaim", result.state.state)
        return result.state

    def test_reclaim_before_deadline_is_eligible(self) -> None:
        result = transition_buy_liquidity_sweep(
            self.touch(), now=NOW + timedelta(minutes=14, seconds=59), bid=104.9, ask=105.0,
            price_low=100.0, price_high=105.0, atr=9.0,
            timeout_minutes=15, max_sweep_atr=2.0,
        )
        self.assertTrue(result.became_eligible)
        self.assertEqual("reclaimed", result.state.state)
        self.assertEqual(2.0, result.state.atr_at_touch)  # snapshot does not move

    def test_touch_and_reclaim_require_separate_quote_observations(self) -> None:
        result = transition_buy_liquidity_sweep(
            LiquiditySweepState(), now=NOW, bid=100.0, ask=105.0,
            price_low=100.0, price_high=105.0, atr=2.0,
            timeout_minutes=15, max_sweep_atr=2.0,
        )

        self.assertFalse(result.became_eligible)
        self.assertEqual("waiting_reclaim", result.state.state)

    def test_reclaim_at_deadline_times_out(self) -> None:
        result = transition_buy_liquidity_sweep(
            self.touch(), now=NOW + timedelta(minutes=15), bid=104.9, ask=105.0,
            price_low=100.0, price_high=105.0, atr=2.0,
            timeout_minutes=15, max_sweep_atr=2.0,
        )
        self.assertFalse(result.became_eligible)
        self.assertEqual("timed_out", result.state.state)

    def test_exactly_one_atr_is_allowed_but_more_invalidates(self) -> None:
        state = self.touch()
        exact = transition_buy_liquidity_sweep(
            state, now=NOW + timedelta(minutes=1), bid=98.0, ask=98.2,
            price_low=100.0, price_high=105.0, atr=2.0,
            timeout_minutes=15, max_sweep_atr=1.0,
        )
        self.assertEqual("waiting_reclaim", exact.state.state)
        deeper = transition_buy_liquidity_sweep(
            exact.state, now=NOW + timedelta(minutes=2), bid=97.99, ask=98.19,
            price_low=100.0, price_high=105.0, atr=2.0,
            timeout_minutes=15, max_sweep_atr=1.0,
        )
        self.assertEqual("invalidated_breakout", deeper.state.state)

    def test_terminal_state_does_not_rearm(self) -> None:
        terminal = replace(self.touch(), state="timed_out", terminal_reason="reclaim_timeout")
        result = transition_buy_liquidity_sweep(
            terminal, now=NOW + timedelta(hours=1), bid=99.0, ask=106.0,
            price_low=100.0, price_high=105.0, atr=2.0,
            timeout_minutes=15, max_sweep_atr=2.0,
        )
        self.assertEqual("timed_out", result.state.state)
        self.assertFalse(result.became_eligible)

    def test_reclaimed_state_can_retry_before_original_deadline(self) -> None:
        reclaimed = transition_buy_liquidity_sweep(
            self.touch(), now=NOW + timedelta(minutes=5), bid=104.9, ask=105.0,
            price_low=100.0, price_high=105.0, atr=2.0,
            timeout_minutes=15, max_sweep_atr=2.0,
        ).state
        retry = transition_buy_liquidity_sweep(
            reclaimed, now=NOW + timedelta(minutes=6), bid=104.8, ask=105.1,
            price_low=100.0, price_high=105.0, atr=9.0,
            timeout_minutes=15, max_sweep_atr=2.0,
        )

        self.assertTrue(retry.became_eligible)
        self.assertEqual("reclaimed", retry.state.state)
        self.assertEqual(NOW + timedelta(minutes=15), retry.state.deadline_at)
        self.assertEqual(2.0, retry.state.atr_at_touch)


class SellLiquiditySweepTransitionTests(unittest.TestCase):
    def touch(self) -> LiquiditySweepState:
        result = transition_liquidity_sweep(
            LiquiditySweepState(trade_direction="short"), trade_direction="short",
            now=NOW, bid=104.8, ask=105.0,
            price_low=100.0, price_high=105.0, atr=2.0,
            timeout_minutes=15, max_sweep_atr=1.0,
        )
        self.assertEqual("waiting_reclaim", result.state.state)
        return result.state

    def test_reclaim_lower_edge_emits_short_candidate_signal(self) -> None:
        result = transition_liquidity_sweep(
            self.touch(), trade_direction="short",
            now=NOW + timedelta(minutes=5), bid=100.0, ask=100.2,
            price_low=100.0, price_high=105.0, atr=9.0,
            timeout_minutes=15, max_sweep_atr=2.0,
        )

        self.assertTrue(result.became_eligible)
        self.assertEqual("reclaimed", result.state.state)
        self.assertEqual(2.0, result.state.atr_at_touch)

    def test_touch_and_reclaim_require_separate_quote_observations(self) -> None:
        result = transition_liquidity_sweep(
            LiquiditySweepState(trade_direction="short"), trade_direction="short",
            now=NOW, bid=100.0, ask=105.0,
            price_low=100.0, price_high=105.0, atr=2.0,
            timeout_minutes=15, max_sweep_atr=2.0,
        )

        self.assertFalse(result.became_eligible)
        self.assertEqual("waiting_reclaim", result.state.state)

    def test_exactly_one_atr_is_allowed_but_higher_invalidates(self) -> None:
        exact = transition_liquidity_sweep(
            self.touch(), trade_direction="short",
            now=NOW + timedelta(minutes=1), bid=106.8, ask=107.0,
            price_low=100.0, price_high=105.0, atr=2.0,
            timeout_minutes=15, max_sweep_atr=1.0,
        )
        self.assertEqual("waiting_reclaim", exact.state.state)
        higher = transition_liquidity_sweep(
            exact.state, trade_direction="short",
            now=NOW + timedelta(minutes=2), bid=106.81, ask=107.01,
            price_low=100.0, price_high=105.0, atr=2.0,
            timeout_minutes=15, max_sweep_atr=1.0,
        )
        self.assertEqual("invalidated_breakout", higher.state.state)


class LiquiditySweepRiskRewardTests(unittest.TestCase):
    def test_dynamic_rr_boundaries(self) -> None:
        self.assertEqual(4.0, liquidity_sweep_rr_for_stop(1.5))
        self.assertEqual(3.0, liquidity_sweep_rr_for_stop(1.50001))
        self.assertEqual(3.0, liquidity_sweep_rr_for_stop(2.25))
        self.assertEqual(2.0, liquidity_sweep_rr_for_stop(2.25001))
        self.assertEqual(2.0, liquidity_sweep_rr_for_stop(3.0))
        self.assertIsNone(liquidity_sweep_rr_for_stop(3.00001))
        self.assertIsNone(liquidity_sweep_rr_for_stop(0.0))


class LiquiditySweepPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)
        for index in range(16):
            opened = NOW - timedelta(minutes=15 * (16 - index))
            self.conn.execute(
                """
                INSERT INTO candles (id, symbol, timeframe, open_time, close_time, open, high, low, close, source)
                VALUES (?, 'XAUUSD', 'M15', ?, ?, 101, 102, 100, 101, 'test')
                """,
                (f"c-{index}", opened.isoformat(), (opened + timedelta(minutes=15)).isoformat()),
            )
        self.conn.execute(
            """
            INSERT INTO price_zones (
                id, symbol, timeframe, detector, zone_type, direction, price_low, price_high,
                start_time, valid_from, valid_until, detected_at, bot_confidence, bot_weight,
                effective_confidence, effective_weight, status, source, metadata_json, updated_at
            ) VALUES (
                'buy-liq', 'XAUUSD', 'H1', 'human_manual_v1', 'liquidity_pool', 'bullish', 100, 105,
                ?, ?, ?, ?, 1, 0.8, 1, 0.8, 'active', 'human', ?, ?
            )
            """,
            (
                (NOW - timedelta(days=1)).isoformat(),
                (NOW - timedelta(days=1)).isoformat(),
                (NOW + timedelta(days=1)).isoformat(),
                NOW.isoformat(),
                json.dumps({"trade_modes": ["liquidity_sweep"]}),
                NOW.isoformat(),
            ),
        )
        self.conn.commit()
        self.config = load_config().strategy

    def tearDown(self) -> None:
        self.conn.close()

    def evaluate(self, *, bid: float, ask: float, now: datetime, account_label: str = "FTMO") -> list[dict[str, object]]:
        return evaluate_live_buy_liquidity_zones(
            self.conn, symbol="XAUUSD", timeframe="M15", account_label=account_label,
            bid=bid, ask=ask, spread=ask - bid, now=now, config=self.config,
        )

    def evaluate_both(self, *, bid: float, ask: float, now: datetime, account_label: str = "FTMO") -> list[dict[str, object]]:
        return evaluate_live_liquidity_zones(
            self.conn, symbol="XAUUSD", timeframe="M15", account_label=account_label,
            bid=bid, ask=ask, spread=ask - bid, now=now, config=self.config,
        )

    def insert_sell_zone(self) -> None:
        self.conn.execute(
            """
            INSERT INTO price_zones (
                id, symbol, timeframe, detector, zone_type, direction, price_low, price_high,
                start_time, valid_from, valid_until, detected_at, bot_confidence, bot_weight,
                effective_confidence, effective_weight, status, source, metadata_json, updated_at
            ) VALUES (
                'sell-liq', 'XAUUSD', 'H1', 'human_manual_v1', 'liquidity_pool', 'bearish', 110, 115,
                ?, ?, ?, ?, 1, 0.8, 1, 0.8, 'active', 'human', ?, ?
            )
            """,
            (
                (NOW - timedelta(days=1)).isoformat(),
                (NOW - timedelta(days=1)).isoformat(),
                (NOW + timedelta(days=1)).isoformat(),
                NOW.isoformat(),
                json.dumps({"trade_modes": ["liquidity_sweep"]}),
                NOW.isoformat(),
            ),
        )
        self.conn.commit()

    def test_persists_touch_and_emits_one_candidate_on_reclaim(self) -> None:
        self.assertEqual([], self.evaluate(bid=100.0, ask=100.2, now=NOW))
        row = self.conn.execute("SELECT * FROM liquidity_sweep_states").fetchone()
        self.assertEqual("waiting_reclaim", row["state"])

        candidates = self.evaluate(bid=104.9, ask=105.0, now=NOW + timedelta(minutes=5))
        self.assertEqual(1, len(candidates))
        self.assertEqual("liquidity_sweep_reclaim_v1", candidates[0]["playbook"])
        self.assertEqual("long", candidates[0]["direction"])
        self.assertGreater(candidates[0]["entry"], candidates[0]["stop_loss"])
        self.assertEqual(2.0, candidates[0]["risk_reward"])
        self.assertEqual(2.7, candidates[0]["metadata"]["stop_distance_atr"])
        self.assertEqual(
            {
                "enabled": True,
                "close_fraction": 0.5,
                "move_stop_to": "breakeven",
                "breakeven_buffer": 0.0,
            },
            candidates[0]["metadata"]["partial_take_profit"],
        )

        retry = self.evaluate(bid=105.0, ask=105.2, now=NOW + timedelta(minutes=6))
        self.assertEqual(1, len(retry))
        self.assertEqual(candidates[0]["id"], retry[0]["id"])

    def test_stop_wider_than_three_atr_is_terminal_and_not_emitted(self) -> None:
        self.assertEqual([], self.evaluate(bid=100.0, ask=100.2, now=NOW))

        candidates = self.evaluate(bid=106.9, ask=107.0, now=NOW + timedelta(minutes=5))

        self.assertEqual([], candidates)
        row = self.conn.execute("SELECT * FROM liquidity_sweep_states").fetchone()
        self.assertEqual("invalidated_risk", row["state"])
        self.assertEqual("stop_distance_exceeded_3_atr", row["terminal_reason"])

    def test_zone_without_explicit_mode_is_inert(self) -> None:
        self.conn.execute("UPDATE price_zones SET metadata_json = '{}' WHERE id = 'buy-liq'")
        self.conn.commit()
        self.assertEqual([], self.evaluate(bid=99.0, ask=99.2, now=NOW))
        count = self.conn.execute("SELECT COUNT(*) AS count FROM liquidity_sweep_states").fetchone()["count"]
        self.assertEqual(0, count)

    def test_bearish_zone_sweeps_upper_edge_and_emits_short_candidate(self) -> None:
        self.insert_sell_zone()
        self.assertEqual([], self.evaluate_both(bid=114.8, ask=115.0, now=NOW))

        candidates = self.evaluate_both(bid=110.0, ask=110.2, now=NOW + timedelta(minutes=5))

        self.assertEqual(1, len(candidates))
        candidate = candidates[0]
        self.assertEqual("sell-liq", candidate["primary_zone_id"])
        self.assertEqual("short", candidate["direction"])
        self.assertGreater(candidate["stop_loss"], candidate["entry"])
        self.assertLess(candidate["take_profit"][0], candidate["entry"])
        row = self.conn.execute(
            "SELECT * FROM liquidity_sweep_states WHERE zone_id = 'sell-liq'"
        ).fetchone()
        self.assertEqual("short", row["trade_direction"])
        self.assertEqual(115.0, row["extreme_price"])
        self.assertIsNone(row["deepest_bid"])

    def test_chart_metadata_keeps_runtime_state_for_each_account(self) -> None:
        self.evaluate(bid=100.0, ask=100.2, now=NOW, account_label="FTMO")
        self.evaluate(bid=99.9, ask=100.1, now=NOW, account_label="Exness")
        zones = [{"id": "buy-liq", "type": "liquidity_pool", "metadata": {}}]

        attach_liquidity_sweep_states(self.conn, zones)

        states = zones[0]["metadata"]["liquidity_sweep_states"]
        self.assertEqual({"FTMO", "Exness"}, {state["account_label"] for state in states})


class LiquiditySweepMigrationTests(unittest.TestCase):
    def test_init_db_backfills_original_buy_only_runtime_columns(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE liquidity_sweep_states (
                zone_id TEXT NOT NULL,
                account_label TEXT NOT NULL,
                symbol TEXT NOT NULL,
                zone_updated_at TEXT NOT NULL,
                state TEXT NOT NULL,
                touched_lower_at TEXT,
                deadline_at TEXT,
                atr_at_touch REAL,
                deepest_bid REAL,
                invalidation_price REAL,
                reclaimed_at TEXT,
                terminal_reason TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (zone_id, account_label)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO liquidity_sweep_states (
                zone_id, account_label, symbol, zone_updated_at, state,
                touched_lower_at, atr_at_touch, deepest_bid, updated_at
            ) VALUES ('legacy-buy', 'FTMO', 'XAUUSD', 'v1', 'waiting_reclaim', ?, 2, 99, ?)
            """,
            (NOW.isoformat(), NOW.isoformat()),
        )

        init_db(conn)
        row = conn.execute(
            "SELECT * FROM liquidity_sweep_states WHERE zone_id = 'legacy-buy'"
        ).fetchone()

        self.assertEqual("long", row["trade_direction"])
        self.assertEqual(NOW.isoformat(), row["touched_edge_at"])
        self.assertEqual(99.0, row["extreme_price"])
        conn.close()


if __name__ == "__main__":
    unittest.main()
