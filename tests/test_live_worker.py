"""Unit tests for semi_bot_trading.live_worker.

Coverage targets:
  - build_execution_pricing_plan  (drift cases, direction, validation)
  - execute_candidate             (market, limit, MT5 failure, pending intent, no pricing_plan)
  - maybe_execute_candidates      (all gate checks, score sort, end-to-end path)
  - live_candidate_already_executed (pending/sent/failed)
  - live_trade_count_today        (trade_orders source, statuses, dates)
  - sync_closed_positions         (open skip, closed pnl, missing broker IDs)
  - candidates_after_live_fvg_trade_count (FVG limit, non-FVG pass-through)
  - _seconds_until_next_poll      (timing marks)
  - trading_session               (hour buckets)
"""

from __future__ import annotations

import json
import unittest
import uuid
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone as _tz
from zoneinfo import ZoneInfoNotFoundError
UTC = _tz.utc
from pathlib import Path
from tests.helpers import TemporaryDirectory
from unittest.mock import MagicMock, call, patch

from semi_bot_trading.config import load_config
from semi_bot_trading.db import connect, init_db
from semi_bot_trading.live_worker import (
    ExecutionPricingPlan,
    LiveWorkerState,
    _ftmo_day_window,
    _resolved_initial_balance,
    _seconds_until_next_poll,
    build_execution_pricing_plan,
    candidates_after_live_fvg_trade_count,
    execute_candidate,
    ftmo_news_guard_state,
    is_weekend_flatten_window,
    is_weekend_no_new_trade_window,
    live_candidate_already_executed,
    live_fvg_trade_count_for_zone,
    live_trade_count_today,
    manage_open_trade_partial_take_profit,
    maybe_ftmo_news_flatten,
    maybe_weekend_flatten,
    maybe_execute_candidates,
    run_live_iteration,
    sync_closed_positions,
    trading_session,
    validate_live_account_startup,
)
from semi_bot_trading.mt5_client import MT5OrderRequest
from semi_bot_trading.runtime_env import RuntimeEnv


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_env(**overrides) -> RuntimeEnv:
    """Build a RuntimeEnv with safe test defaults."""
    defaults = dict(
        mt5_login=None,
        mt5_password=None,
        mt5_server=None,
        mt5_path=None,
        mt5_symbol="XAUUSDm",
        mt5_magic=260612,
        telegram_token=None,
        telegram_chat_id=None,
        execution_enabled=True,
        live_order_volume=0.01,
        max_open_positions_per_symbol=1,
        max_trades_per_day=10,
        poll_seconds=15.0,
        poll_at_seconds=(1, 16, 31, 46),
        max_entry_drift_price=2.0,
        max_spread_price=2.0,
        live_sync_candles=True,
        live_run_detectors=True,
        live_evaluate_intrabar=False,
        chart_url_base="http://127.0.0.1:5173",
        account_label="Test",
        account_profile="personal",
        account_balance_scale=None,
        risk_per_trade_pct=None,
        secret_key="",
        admin_username="admin",
        admin_password_hash=None,
        allowed_origins=[],
        environment="development",
        weekend_flatten_enabled=False,
        weekend_flatten_timezone="America/New_York",
        weekend_no_new_trades_time="12:00",
        weekend_flatten_time="15:30",
        partial_take_profit_enabled=True,
        partial_take_profit_r=1.25,
        partial_take_profit_fraction=0.5,
        partial_take_profit_be_buffer=0.0,
    )
    defaults.update(overrides)
    return RuntimeEnv(**defaults)


def _make_candidate(**overrides) -> dict:
    base = dict(
        id="cand-abc123",
        playbook="zone_reaction_v2",
        direction="long",
        status="eligible",
        entry=3000.0,
        stop_loss=2980.0,
        take_profit=[3040.0, 3060.0],
        risk_reward=2.0,
        score=0.75,
        primary_zone_id="zone-1",
        related_zone_ids=[],
        metadata={"zone_type": "support", "macro_trend": "up"},
    )
    base.update(overrides)
    return base


def _make_pricing_plan(**overrides) -> ExecutionPricingPlan:
    defaults = dict(
        order_type="market",
        entry_price=3000.0,
        stop_loss=2980.0,
        take_profit=[3040.0],
        expires_at=None,
        current_price=3000.0,
        signal_entry=3000.0,
        signal_stop_loss=2980.0,
        signal_take_profit=[3040.0],
        drift=0.0,
        adverse_drift=0.0,
        drift_action="market_favorable_or_flat",
    )
    defaults.update(overrides)
    return ExecutionPricingPlan(**defaults)


def _setup_db(tmp_dir: str) -> tuple[Path, object]:
    db_path = Path(tmp_dir) / "test.sqlite3"
    conn = connect(db_path)
    init_db(conn)
    return db_path, conn


def _fake_client(
    current_price: float = 3000.0,
    positions: int = 0,
    place_market_result: dict | None = None,
    place_limit_result: dict | None = None,
    place_market_raises: Exception | None = None,
    place_limit_raises: Exception | None = None,
    open_tickets: set | None = None,
    closed_deal: dict | None = None,
    contract_size: float = 100.0,
    spread: float = 0.3,
) -> MagicMock:
    client = MagicMock()
    client.current_price_for_side.return_value = current_price
    client.positions_count.return_value = positions
    client.get_current_spread.return_value = spread
    if place_market_raises:
        client.place_market_order.side_effect = place_market_raises
    else:
        client.place_market_order.return_value = place_market_result or {
            "order": "11111", "deal": "22222", "price": current_price, "retcode": 10009
        }
    if place_limit_raises:
        client.place_limit_order.side_effect = place_limit_raises
    else:
        client.place_limit_order.return_value = place_limit_result or {
            "order": "33333", "deal": "0", "price": 0, "retcode": 10008
        }
    client.get_open_position_tickets.return_value = open_tickets or set()
    client.get_open_positions.return_value = [
        {"ticket": ticket, "side": "buy", "volume": 0.01, "price_open": 3000.0, "sl": 2980.0, "tp": 3040.0}
        for ticket in (open_tickets or set())
    ]
    client.get_closed_deal_for_position.return_value = closed_deal
    client.get_symbol_contract_size.return_value = contract_size
    client.close_partial_position.return_value = {"order": "partial-order", "deal": "partial-deal", "price": current_price, "retcode": 10009}
    client.modify_position_sltp.return_value = {"order": "modify-order", "retcode": 10009}
    return client


def _fake_risk_manager(allowed: bool = True, lot_size: float = 0.01, reason: str = "") -> MagicMock:
    rm = MagicMock()
    assessment = MagicMock()
    assessment.allowed = allowed
    assessment.lot_size = lot_size
    assessment.reason = reason
    rm.assess_trade.return_value = assessment
    return rm


# ─────────────────────────────────────────────────────────────────────────────
# build_execution_pricing_plan
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildExecutionPricingPlan(unittest.TestCase):
    """All drift cases for build_execution_pricing_plan."""

    def _make(self, current_price: float, direction: str = "long", max_drift: float = 2.0,
              entry: float = 3000.0, stop: float = 2980.0, tp: list | None = None):
        candidate = _make_candidate(
            direction=direction, entry=entry, stop_loss=stop,
            take_profit=tp or [3040.0],
        )
        client = _fake_client(current_price=current_price)
        return build_execution_pricing_plan(client, "XAUUSDm", candidate, max_drift)

    # ── no drift ─────────────────────────────────────────────────────────────
    def test_no_drift_market_at_signal(self):
        plan = self._make(current_price=3000.0)
        self.assertEqual("market", plan.order_type)
        self.assertEqual(3000.0, plan.entry_price)
        self.assertEqual(2980.0, plan.stop_loss)
        self.assertEqual([3040.0], plan.take_profit)
        self.assertEqual("market_favorable_or_flat", plan.drift_action)

    def test_favorable_drift_long_market_at_signal(self):
        """Price moved down (favorable for long) — still market at signal."""
        plan = self._make(current_price=2998.0)
        self.assertEqual("market", plan.order_type)
        self.assertEqual(3000.0, plan.entry_price)
        self.assertEqual(2980.0, plan.stop_loss)
        self.assertEqual("market_favorable_or_flat", plan.drift_action)
        self.assertLess(plan.drift, 0)
        self.assertEqual(0.0, plan.adverse_drift)

    def test_favorable_drift_short_market_at_signal(self):
        """Price moved up (favorable for short) — still market at signal."""
        plan = self._make(current_price=3002.0, direction="short",
                          entry=3000.0, stop=3020.0, tp=[2960.0])
        self.assertEqual("market", plan.order_type)
        self.assertEqual(3000.0, plan.entry_price)
        self.assertEqual("market_favorable_or_flat", plan.drift_action)
        self.assertEqual(0.0, plan.adverse_drift)

    # ── small adverse drift → reprice market ─────────────────────────────────
    def test_small_adverse_drift_long_repriced(self):
        """Adverse drift 1.5 < max_drift 2.0 → market at current, SL/TP shifted."""
        plan = self._make(current_price=3001.5)
        self.assertEqual("market", plan.order_type)
        self.assertEqual(3001.5, plan.entry_price)
        self.assertEqual("market_repriced_adverse", plan.drift_action)
        # risk preserved: original 20 pts
        self.assertAlmostEqual(2981.5, plan.stop_loss, places=5)
        # TP preserved: original 40 pts → new entry + 40
        self.assertAlmostEqual(3041.5, plan.take_profit[0], places=5)

    def test_small_adverse_drift_short_repriced(self):
        """Short: price moved down 1 pt adverse → repriced."""
        plan = self._make(current_price=2999.0, direction="short",
                          entry=3000.0, stop=3020.0, tp=[2960.0])
        self.assertEqual("market", plan.order_type)
        self.assertEqual(2999.0, plan.entry_price)
        # risk = 20 pts → SL above entry
        self.assertAlmostEqual(3019.0, plan.stop_loss, places=5)
        # TP 40 pts below entry
        self.assertAlmostEqual(2959.0, plan.take_profit[0], places=5)

    def test_small_adverse_drift_multi_tp_all_repriced(self):
        """All TP levels are repriced, not just the first."""
        plan = self._make(current_price=3001.0, tp=[3040.0, 3060.0])
        self.assertEqual(2, len(plan.take_profit))
        # TP1 RR=2.0, TP2 RR=3.0
        self.assertAlmostEqual(3041.0, plan.take_profit[0], places=5)
        self.assertAlmostEqual(3061.0, plan.take_profit[1], places=5)

    # ── large adverse drift → limit ──────────────────────────────────────────
    def test_large_adverse_drift_limit_order(self):
        """Adverse drift 3.0 > max_drift 2.0 → limit at signal entry."""
        plan = self._make(current_price=3003.0)
        self.assertEqual("limit", plan.order_type)
        self.assertEqual(3000.0, plan.entry_price)  # signal preserved
        self.assertEqual(2980.0, plan.stop_loss)
        self.assertEqual([3040.0], plan.take_profit)
        self.assertEqual("limit_after_adverse_drift", plan.drift_action)

    def test_large_adverse_drift_short_limit_order(self):
        """Short large adverse (price falls) → limit."""
        plan = self._make(current_price=2996.0, direction="short",
                          entry=3000.0, stop=3020.0, tp=[2960.0])
        self.assertEqual("limit", plan.order_type)
        self.assertEqual(3000.0, plan.entry_price)

    def test_strategy_limit_order_is_preserved(self):
        candidate = _make_candidate(
            metadata={
                "zone_type": "support",
                "order_type": "limit",
                "entry_model": "impulse_retest_limit",
                "limit_order_expires_at": "2026-01-01T03:00:00+00:00",
            },
            expires_at="2026-01-01T03:00:00+00:00",
        )
        client = _fake_client(current_price=3020.0)

        plan = build_execution_pricing_plan(client, "XAUUSDm", candidate, 2.0)

        self.assertEqual("limit", plan.order_type)
        self.assertEqual(3000.0, plan.entry_price)
        self.assertEqual(2980.0, plan.stop_loss)
        self.assertEqual([3040.0, 3060.0], plan.take_profit)
        self.assertEqual("2026-01-01T03:00:00+00:00", plan.expires_at)
        self.assertEqual("impulse_retest_limit", plan.drift_action)

    # ── max_entry_drift_price = 0 disables all drift logic ───────────────────
    def test_drift_disabled_when_max_zero(self):
        """max_entry_drift_price=0 → always market at signal, no reprice."""
        plan = self._make(current_price=3005.0, max_drift=0.0)
        self.assertEqual("market", plan.order_type)
        self.assertEqual(3000.0, plan.entry_price)
        self.assertEqual("market_favorable_or_flat", plan.drift_action)

    # ── validation errors ─────────────────────────────────────────────────────
    def test_missing_entry_raises(self):
        candidate = _make_candidate(entry=0)
        client = _fake_client()
        with self.assertRaises(ValueError):
            build_execution_pricing_plan(client, "XAUUSDm", candidate, 2.0)

    def test_missing_stop_raises(self):
        candidate = _make_candidate(stop_loss=0)
        client = _fake_client()
        with self.assertRaises(ValueError):
            build_execution_pricing_plan(client, "XAUUSDm", candidate, 2.0)

    def test_missing_tp_raises(self):
        candidate = _make_candidate(take_profit=[])
        client = _fake_client()
        with self.assertRaises(ValueError):
            build_execution_pricing_plan(client, "XAUUSDm", candidate, 2.0)


# ─────────────────────────────────────────────────────────────────────────────
# execute_candidate
# ─────────────────────────────────────────────────────────────────────────────

class TestExecuteCandidate(unittest.TestCase):

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._db_path, self._conn = _setup_db(self._tmp.name)
        self._config = replace(load_config(), database=self._db_path)
        self._env = _make_env()

    def tearDown(self):
        self._conn.close()
        self._tmp.cleanup()

    def _run(self, client, candidate=None, pricing_plan=None, lot_size=0.01):
        execute_candidate(
            self._conn,
            self._config,
            self._env,
            client,
            candidate or _make_candidate(),
            broker_symbol="XAUUSDm",
            lot_size=lot_size,
            pricing_plan=pricing_plan,
        )

    def _er_row(self, conn=None):
        c = conn or self._conn
        return c.execute("SELECT * FROM execution_requests").fetchone()

    def _order_rows(self, conn=None):
        c = conn or self._conn
        return c.execute("SELECT * FROM trade_orders").fetchall()

    # ── successful market order ───────────────────────────────────────────────
    def test_market_order_success_db_state(self):
        client = _fake_client(current_price=3000.0, place_market_result={
            "order": "111", "deal": "222", "price": 3000.5, "retcode": 10009
        })
        plan = _make_pricing_plan(order_type="market", entry_price=3000.0,
                                  stop_loss=2980.0, take_profit=[3040.0])
        self._run(client, pricing_plan=plan)

        er = self._er_row()
        self.assertIsNotNone(er)
        self.assertEqual("sent", er["status"])
        self.assertEqual("market", er["order_type"])

        orders = self._order_rows()
        self.assertEqual(1, len(orders))
        self.assertEqual("filled", orders[0]["status"])
        self.assertEqual("market", orders[0]["order_type"])
        self.assertAlmostEqual(3000.5, orders[0]["entry_price"], places=2)
        self.assertAlmostEqual(2980.0, orders[0]["stop_loss"], places=2)
        self.assertEqual("live", orders[0]["source"])

    def test_market_order_calls_place_market_not_limit(self):
        client = _fake_client()
        plan = _make_pricing_plan(order_type="market")
        self._run(client, pricing_plan=plan)
        client.place_market_order.assert_called_once()
        client.place_limit_order.assert_not_called()

    # ── successful limit order ────────────────────────────────────────────────
    def test_limit_order_success_db_state(self):
        client = _fake_client(place_limit_result={
            "order": "333", "deal": "0", "price": 0, "retcode": 10008
        })
        plan = _make_pricing_plan(order_type="limit", entry_price=3000.0,
                                  stop_loss=2980.0, take_profit=[3040.0])
        self._run(client, pricing_plan=plan)

        client.place_limit_order.assert_called_once()
        client.place_market_order.assert_not_called()

        er = self._er_row()
        self.assertEqual("sent", er["status"])
        self.assertEqual("limit", er["order_type"])

        orders = self._order_rows()
        self.assertEqual(1, len(orders))
        self.assertEqual("pending_fill", orders[0]["status"])
        self.assertEqual("limit", orders[0]["order_type"])
        # price=0 in result → fallback to exec_entry
        self.assertAlmostEqual(3000.0, orders[0]["entry_price"], places=2)

    # ── MT5 failure ───────────────────────────────────────────────────────────
    def test_mt5_failure_execution_request_marked_failed(self):
        client = _fake_client(
            place_market_raises=RuntimeError("MT5 broker rejected")
        )
        plan = _make_pricing_plan()
        self._run(client, pricing_plan=plan)

        er = self._er_row()
        self.assertIsNotNone(er)
        self.assertEqual("failed", er["status"])
        self.assertIn("MT5 broker rejected", er["failure_reason"])

        # No trade_orders row on failure
        self.assertEqual(0, len(self._order_rows()))

    # ── pending intent persisted before MT5 call ─────────────────────────────
    def test_pending_intent_committed_before_mt5(self):
        """execution_requests row with status='pending' must exist before MT5 call."""
        committed_statuses: list[str] = []

        original_place_market = None

        def capture_status(*args, **kwargs):
            # Read what's committed to DB at the moment MT5 is called
            with closing(connect(self._db_path)) as check_conn:
                row = check_conn.execute(
                    "SELECT status FROM execution_requests"
                ).fetchone()
                if row:
                    committed_statuses.append(row["status"])
            # Simulate successful MT5 response
            return {"order": "999", "deal": "888", "price": 3000.0, "retcode": 10009}

        client = _fake_client()
        client.place_market_order.side_effect = capture_status

        plan = _make_pricing_plan()
        self._run(client, pricing_plan=plan)

        self.assertEqual(["pending"], committed_statuses,
                         "execution_request must be committed as 'pending' before MT5 call")

    # ── no pricing_plan fallback ──────────────────────────────────────────────
    def test_no_pricing_plan_uses_candidate_values(self):
        """pricing_plan=None → falls back to candidate's stop_loss/take_profit."""
        client = _fake_client()
        candidate = _make_candidate(entry=3000.0, stop_loss=2985.0, take_profit=[3030.0])
        self._run(client, candidate=candidate, pricing_plan=None)

        orders = self._order_rows()
        self.assertEqual(1, len(orders))
        self.assertAlmostEqual(2985.0, orders[0]["stop_loss"], places=2)

    # ── SL/TP from pricing_plan, not candidate ────────────────────────────────
    def test_uses_repriced_sl_tp_not_candidate_signal(self):
        client = _fake_client()
        # candidate says SL=2980, but pricing_plan has SL=2981.5 (repriced)
        candidate = _make_candidate(stop_loss=2980.0, take_profit=[3040.0])
        plan = _make_pricing_plan(stop_loss=2981.5, take_profit=[3041.5],
                                  entry_price=3001.5, order_type="market")
        self._run(client, candidate=candidate, pricing_plan=plan)

        orders = self._order_rows()
        self.assertEqual(1, len(orders))
        self.assertAlmostEqual(2981.5, orders[0]["stop_loss"], places=4)
        tp = json.loads(orders[0]["take_profit_json"])
        self.assertAlmostEqual(3041.5, tp[0], places=4)

    # ── already_executed guard works after pending commit ────────────────────
    def test_already_executed_blocks_after_pending(self):
        client = _fake_client()
        plan = _make_pricing_plan()
        candidate = _make_candidate()
        self._run(client, candidate=candidate, pricing_plan=plan)
        # Check that live_candidate_already_executed returns True
        self.assertTrue(live_candidate_already_executed(self._conn, candidate["id"], account_label="Test"))

    # ── idempotent: second call for same candidate skipped by caller ──────────
    def test_multi_tp_stored_correctly(self):
        client = _fake_client()
        plan = _make_pricing_plan(take_profit=[3040.0, 3060.0])
        self._run(client, pricing_plan=plan)
        orders = self._order_rows()
        tp = json.loads(orders[0]["take_profit_json"])
        self.assertEqual([3040.0, 3060.0], tp)


class TestPartialTakeProfit(unittest.TestCase):

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._db_path, self._conn = _setup_db(self._tmp.name)
        self._config = replace(load_config(), database=self._db_path)
        self._env = _make_env()

    def tearDown(self):
        self._conn.close()
        self._tmp.cleanup()

    def _insert_open_order(self, *, side: str = "buy", done: bool = False) -> None:
        now = "2026-07-03T10:00:00+00:00"
        metadata = {
            "broker_order_id": "11111",
            "broker_deal_id": "22222",
            "initial_stop_loss": 2980.0,
            "initial_quantity": 0.02,
            "partial_take_profit": {
                "enabled": True,
                "trigger_r": 1.25,
                "trigger_price": 3025.0 if side == "buy" else 2975.0,
                "fraction": 0.5,
                "breakeven_stop": 3000.0,
                "final_take_profit": 3050.0 if side == "buy" else 2950.0,
                "done": done,
            },
        }
        self._conn.execute(
            """INSERT INTO trade_ideas
               (id, symbol, direction, playbook, status, entry_zone_id,
                related_zone_ids_json, context_snapshot_json, suggested_entry,
                suggested_stop_loss, suggested_take_profit_json, risk_reward, created_at)
               VALUES ('idea-partial', 'XAUUSD', ?, 'zone_reaction_v2', 'approved', NULL,
                       '[]', '{}', 3000, 2980, '[3050]', 2.5, ?)""",
            ("long" if side == "buy" else "short", now),
        )
        self._conn.execute(
            """INSERT INTO trade_orders
               (id, trade_idea_id, account_label, symbol, side, order_type, status,
                entry_price, stop_loss, take_profit_json, quantity,
                opened_at, source, metadata_json, created_at)
               VALUES ('order-partial', 'idea-partial', 'Test', 'XAUUSD', ?, 'market', 'filled',
                       3000, 2980, '[3050]', 0.02, ?, 'live', ?, ?)""",
            (side, now, json.dumps(metadata), now),
        )
        self._conn.commit()

    def _metadata(self) -> dict:
        row = self._conn.execute("SELECT metadata_json FROM trade_orders WHERE id = 'order-partial'").fetchone()
        return json.loads(row["metadata_json"])

    def test_partial_take_profit_waits_until_trigger_price(self):
        self._insert_open_order()
        client = _fake_client(current_price=3024.0, open_tickets={"11111"})
        client.get_open_positions.return_value = [
            {"ticket": "11111", "side": "buy", "volume": 0.02, "price_open": 3000.0, "sl": 2980.0, "tp": 3050.0}
        ]

        manage_open_trade_partial_take_profit(self._conn, self._config, self._env, client, "XAUUSDm")

        client.close_partial_position.assert_not_called()
        client.modify_position_sltp.assert_not_called()

    def test_account_ui_settings_disable_then_rearm_open_trade_at_one_r(self):
        self._insert_open_order()
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            INSERT INTO account_execution_controls (
                account_label, requested_enabled, effective_enabled, hard_enabled,
                partial_take_profit_enabled, partial_take_profit_r, updated_at
            ) VALUES ('Test', 1, 1, 1, 0, 1.0, ?)
            """,
            (now,),
        )
        self._conn.commit()
        disabled_client = _fake_client(current_price=3021.0, open_tickets={"11111"})
        disabled_client.get_open_positions.return_value = [
            {"ticket": "11111", "side": "buy", "volume": 0.02, "price_open": 3000.0, "sl": 2980.0, "tp": 3040.0}
        ]

        manage_open_trade_partial_take_profit(
            self._conn, self._config, self._env, disabled_client, "XAUUSDm"
        )

        disabled_client.close_partial_position.assert_not_called()
        disabled_plan = self._metadata()["partial_take_profit"]
        self.assertFalse(disabled_plan["enabled"])
        self.assertEqual(1.0, disabled_plan["trigger_r"])
        self.assertEqual(3020.0, disabled_plan["trigger_price"])

        self._conn.execute(
            "UPDATE account_execution_controls SET partial_take_profit_enabled = 1 WHERE account_label = 'Test'"
        )
        self._conn.commit()
        enabled_client = _fake_client(current_price=3021.0, open_tickets={"11111"})
        enabled_client.get_open_positions.return_value = disabled_client.get_open_positions.return_value

        manage_open_trade_partial_take_profit(
            self._conn, self._config, self._env, enabled_client, "XAUUSDm"
        )

        enabled_client.close_partial_position.assert_called_once_with(
            "XAUUSDm",
            position_ticket="11111",
            side="buy",
            volume=0.01,
            magic=self._env.mt5_magic,
            comment="partial 1R",
        )
        self.assertTrue(self._metadata()["partial_take_profit"]["done"])

    def test_partial_take_profit_closes_half_and_moves_stop_to_entry(self):
        self._insert_open_order()
        client = _fake_client(current_price=3025.5, open_tickets={"11111"})
        client.get_open_positions.return_value = [
            {"ticket": "11111", "side": "buy", "volume": 0.02, "price_open": 3000.0, "sl": 2980.0, "tp": 3050.0}
        ]

        manage_open_trade_partial_take_profit(self._conn, self._config, self._env, client, "XAUUSDm")

        client.close_partial_position.assert_called_once_with(
            "XAUUSDm",
            position_ticket="11111",
            side="buy",
            volume=0.01,
            magic=self._env.mt5_magic,
            comment="partial 1.25R",
        )
        client.modify_position_sltp.assert_called_once_with(
            "XAUUSDm",
            position_ticket="11111",
            stop_loss=3000.0,
            take_profit=3050.0,
            magic=self._env.mt5_magic,
            comment="BE after partial",
        )
        row = self._conn.execute("SELECT stop_loss, metadata_json FROM trade_orders WHERE id = 'order-partial'").fetchone()
        self.assertEqual(3000.0, row["stop_loss"])
        metadata = json.loads(row["metadata_json"])
        self.assertTrue(metadata["partial_take_profit"]["done"])
        self.assertEqual(0.01, metadata["partial_take_profit"]["closed_volume"])

    def test_partial_take_profit_does_not_repeat_after_done(self):
        self._insert_open_order(done=True)
        client = _fake_client(current_price=3026.0, open_tickets={"11111"})

        manage_open_trade_partial_take_profit(self._conn, self._config, self._env, client, "XAUUSDm")

        client.close_partial_position.assert_not_called()

    def test_partial_take_profit_infers_done_when_position_volume_already_reduced(self):
        self._insert_open_order()
        client = _fake_client(current_price=3026.0, open_tickets={"11111"})
        client.get_open_positions.return_value = [
            {"ticket": "11111", "side": "buy", "volume": 0.01, "price_open": 3000.0, "sl": 2980.0, "tp": 3050.0}
        ]

        manage_open_trade_partial_take_profit(self._conn, self._config, self._env, client, "XAUUSDm")

        client.close_partial_position.assert_not_called()
        client.modify_position_sltp.assert_called_once()
        metadata = self._metadata()
        self.assertTrue(metadata["partial_take_profit"]["done"])
        self.assertTrue(metadata["partial_take_profit"]["inferred_from_position_volume"])

    def test_partial_take_profit_retries_break_even_after_previous_modify_failure(self):
        self._insert_open_order(done=True)
        metadata = self._metadata()
        metadata["partial_take_profit"]["breakeven_applied"] = False
        metadata["partial_take_profit"]["modify_error"] = "temporary failure"
        self._conn.execute(
            "UPDATE trade_orders SET metadata_json = ? WHERE id = 'order-partial'",
            (json.dumps(metadata),),
        )
        self._conn.commit()
        client = _fake_client(current_price=3026.0, open_tickets={"11111"})
        client.get_open_positions.return_value = [
            {"ticket": "11111", "side": "buy", "volume": 0.01, "price_open": 3000.0, "sl": 2980.0, "tp": 3050.0}
        ]

        manage_open_trade_partial_take_profit(self._conn, self._config, self._env, client, "XAUUSDm")

        client.close_partial_position.assert_not_called()
        client.modify_position_sltp.assert_called_once()
        metadata = self._metadata()
        self.assertTrue(metadata["partial_take_profit"]["breakeven_applied"])
        self.assertIsNone(metadata["partial_take_profit"]["modify_error"])


# ─────────────────────────────────────────────────────────────────────────────
# live_candidate_already_executed
# ─────────────────────────────────────────────────────────────────────────────

class TestLiveCandidateAlreadyExecuted(unittest.TestCase):

    def setUp(self):
        self._tmp = TemporaryDirectory()
        _, self._conn = _setup_db(self._tmp.name)

    def tearDown(self):
        self._conn.close()
        self._tmp.cleanup()

    def _insert_er(self, candidate_id: str, status: str) -> None:
        idea_id = f"live-idea-{candidate_id}"
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            """INSERT OR IGNORE INTO trade_ideas
               (id, symbol, direction, playbook, status, entry_zone_id,
                related_zone_ids_json, context_snapshot_json, suggested_entry,
                suggested_stop_loss, suggested_take_profit_json, risk_reward, created_at)
               VALUES (?, 'XAUUSD', 'long', 'test', 'approved', NULL, '[]', '{}',
                       3000, 2980, '[3040]', 2.0, ?)""",
            (idea_id, now),
        )
        self._conn.execute(
            """INSERT INTO execution_requests
               (id, trade_idea_id, symbol, broker_symbol, side, order_type,
                quantity, entry_price, stop_loss, take_profit_json,
                risk_snapshot_json, context_snapshot_json, requested_by, status,
                created_at, updated_at)
               VALUES (?, ?, 'XAUUSD', 'XAUUSDm', 'buy', 'market',
                       0.01, 3000, 2980, '[3040]', '{}', '{}', 'strategy', ?, ?, ?)""",
            (f"er-{candidate_id}", idea_id, status, now, now),
        )
        self._conn.commit()

    def test_no_record_returns_false(self):
        self.assertFalse(live_candidate_already_executed(self._conn, "new-cand"))

    def test_pending_returns_true(self):
        self._insert_er("cand-1", "pending")
        self.assertTrue(live_candidate_already_executed(self._conn, "cand-1"))

    def test_sent_returns_true(self):
        self._insert_er("cand-2", "sent")
        self.assertTrue(live_candidate_already_executed(self._conn, "cand-2"))

    def test_failed_returns_false_allows_retry(self):
        self._insert_er("cand-3", "failed")
        self.assertFalse(live_candidate_already_executed(self._conn, "cand-3"))


# ─────────────────────────────────────────────────────────────────────────────
# live_trade_count_today
# ─────────────────────────────────────────────────────────────────────────────

class TestLiveTradeCountToday(unittest.TestCase):

    def setUp(self):
        self._tmp = TemporaryDirectory()
        _, self._conn = _setup_db(self._tmp.name)

    def tearDown(self):
        self._conn.close()
        self._tmp.cleanup()

    def _insert_order(self, status: str, source: str = "live",
                      opened_at: str | None = None) -> None:
        now = opened_at or datetime.now(UTC).isoformat()
        idea_id = f"idea-{status}-{source}-{now}"
        self._conn.execute(
            """INSERT OR IGNORE INTO trade_ideas
               (id, symbol, direction, playbook, status, entry_zone_id,
                related_zone_ids_json, context_snapshot_json, suggested_entry,
                suggested_stop_loss, suggested_take_profit_json, risk_reward, created_at)
               VALUES (?, 'XAUUSD', 'long', 'test', 'approved', NULL, '[]', '{}',
                       3000, 2980, '[3040]', 2.0, ?)""",
            (idea_id, now),
        )
        self._conn.execute(
            """INSERT INTO trade_orders
               (id, trade_idea_id, symbol, side, order_type, status,
                entry_price, stop_loss, take_profit_json, quantity,
                opened_at, source, metadata_json, created_at)
               VALUES (?, ?, 'XAUUSD', 'buy', 'market', ?, 3000, 2980, '[3040]',
                       0.01, ?, ?, '{}', ?)""",
            (f"ord-{status}-{now}", idea_id, status, now, source, now),
        )
        self._conn.commit()

    def test_empty_db_returns_zero(self):
        self.assertEqual(0, live_trade_count_today(self._conn, "XAUUSD"))

    def test_filled_today_counts(self):
        self._insert_order("filled")
        self.assertEqual(1, live_trade_count_today(self._conn, "XAUUSD"))

    def test_pending_fill_today_counts(self):
        self._insert_order("pending_fill")
        self.assertEqual(1, live_trade_count_today(self._conn, "XAUUSD"))

    def test_closed_today_counts(self):
        self._insert_order("closed")
        self.assertEqual(1, live_trade_count_today(self._conn, "XAUUSD"))

    def test_backtest_source_not_counted(self):
        self._insert_order("filled", source="backtest")
        self.assertEqual(0, live_trade_count_today(self._conn, "XAUUSD"))

    def test_yesterday_not_counted(self):
        yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        self._insert_order("filled", opened_at=yesterday)
        self.assertEqual(0, live_trade_count_today(self._conn, "XAUUSD"))

    def test_multiple_orders_today(self):
        self._insert_order("filled")
        self._insert_order("closed")
        self.assertEqual(2, live_trade_count_today(self._conn, "XAUUSD"))

    def test_failed_execution_request_not_counted(self):
        """Ghost 'sent' execution_requests without trade_orders must not count."""
        now = datetime.now(UTC).isoformat()
        idea_id = "ghost-idea"
        self._conn.execute(
            """INSERT OR IGNORE INTO trade_ideas
               (id, symbol, direction, playbook, status, entry_zone_id,
                related_zone_ids_json, context_snapshot_json, suggested_entry,
                suggested_stop_loss, suggested_take_profit_json, risk_reward, created_at)
               VALUES (?, 'XAUUSD', 'long', 'test', 'approved', NULL, '[]', '{}',
                       3000, 2980, '[3040]', 2.0, ?)""",
            (idea_id, now),
        )
        self._conn.execute(
            """INSERT INTO execution_requests
               (id, trade_idea_id, symbol, broker_symbol, side, order_type,
                quantity, entry_price, stop_loss, take_profit_json,
                risk_snapshot_json, context_snapshot_json, requested_by, status,
                created_at, updated_at)
               VALUES ('ghost-er', ?, 'XAUUSD', 'XAUUSDm', 'buy', 'market',
                       0.01, 3000, 2980, '[3040]', '{}', '{}', 'strategy', 'sent', ?, ?)""",
            (idea_id, now, now),
        )
        self._conn.commit()
        # No trade_orders row — must NOT count
        self.assertEqual(0, live_trade_count_today(self._conn, "XAUUSD"))


# ─────────────────────────────────────────────────────────────────────────────
# maybe_execute_candidates
# ─────────────────────────────────────────────────────────────────────────────

class TestMaybeExecuteCandidates(unittest.TestCase):

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._db_path, self._conn = _setup_db(self._tmp.name)
        self._config = replace(load_config(), database=self._db_path)

    def tearDown(self):
        self._conn.close()
        self._tmp.cleanup()

    def _run(self, candidates, env=None, client=None, rm_allowed=True):
        env = env or _make_env()
        client = client or _fake_client()
        rm = _fake_risk_manager(allowed=rm_allowed)
        with patch("semi_bot_trading.live_worker.build_risk_manager", return_value=rm):
            maybe_execute_candidates(
                self._conn, self._config, env, client, candidates, "XAUUSDm"
            )
        return client

    def _order_count(self):
        return self._conn.execute("SELECT COUNT(*) AS c FROM trade_orders").fetchone()["c"]

    # ── gates ─────────────────────────────────────────────────────────────────
    def test_execution_disabled_no_trade(self):
        env = _make_env(execution_enabled=False)
        self._run([_make_candidate()], env=env)
        self.assertEqual(0, self._order_count())

    def test_funded_standard_ftmo_fails_closed_when_calendar_is_stale(self):
        env = _make_env(
            account_profile="ftmo_challenge",
            ftmo_phase="funded",
            ftmo_account_type="standard",
        )
        client = self._run([_make_candidate()], env=env)
        self.assertEqual(0, self._order_count())
        client.place_market_order.assert_not_called()

    def test_weekend_no_new_trade_cutoff_blocks_execution(self):
        env = _make_env(weekend_flatten_enabled=True)
        cutoff_now = datetime(2026, 6, 26, 16, 0, tzinfo=UTC)  # Friday 12:00 New York during DST
        client = _fake_client()
        with (
            patch("semi_bot_trading.live_worker.datetime") as dt,
            patch("semi_bot_trading.live_worker.build_risk_manager", return_value=_fake_risk_manager()),
        ):
            dt.now.return_value = cutoff_now
            maybe_execute_candidates(self._conn, self._config, env, client, [_make_candidate()], "XAUUSDm")
        self.assertEqual(0, self._order_count())
        client.place_market_order.assert_not_called()

    def test_empty_broker_symbol_no_trade(self):
        env = _make_env()
        client = _fake_client()
        rm = _fake_risk_manager()
        with patch("semi_bot_trading.live_worker.build_risk_manager", return_value=rm):
            maybe_execute_candidates(
                self._conn, self._config, env, client, [_make_candidate()], ""
            )
        client.place_market_order.assert_not_called()

    # ── spread guard ──────────────────────────────────────────────────────────
    def test_spread_within_limit_allows_trade(self):
        """spread=0.3 < max=2.0 → execution proceeds normally."""
        env = _make_env(max_spread_price=2.0)
        client = _fake_client(spread=0.3)
        self._run([_make_candidate()], env=env, client=client)
        self.assertEqual(1, self._order_count())

    def test_spread_too_wide_skips_cycle(self):
        """spread=5.0 > max=2.0 → whole cycle skipped, no order placed."""
        env = _make_env(max_spread_price=2.0)
        client = _fake_client(spread=5.0)
        self._run([_make_candidate()], env=env, client=client)
        self.assertEqual(0, self._order_count())
        client.positions_count.assert_not_called()  # returned before positions check

    def test_spread_exactly_at_limit_allows_trade(self):
        """spread == max_spread_price is NOT over the limit → trade proceeds."""
        env = _make_env(max_spread_price=2.0)
        client = _fake_client(spread=2.0)
        self._run([_make_candidate()], env=env, client=client)
        self.assertEqual(1, self._order_count())

    def test_spread_guard_disabled_when_zero(self):
        """max_spread_price=0 → spread check skipped entirely, always trades."""
        env = _make_env(max_spread_price=0.0)
        client = _fake_client(spread=99.0)
        self._run([_make_candidate()], env=env, client=client)
        client.get_current_spread.assert_not_called()
        self.assertEqual(1, self._order_count())

    def test_max_positions_reached_no_trade(self):
        env = _make_env(max_open_positions_per_symbol=1)
        client = _fake_client(positions=1)
        self._run([_make_candidate()], env=env, client=client)
        self.assertEqual(0, self._order_count())

    def test_max_trades_today_reached_no_trade(self):
        env = _make_env(max_trades_per_day=0)
        self._run([_make_candidate()], env=env)
        self.assertEqual(0, self._order_count())

    def test_no_eligible_candidates_no_trade(self):
        candidates = [_make_candidate(status="waiting_confirmation")]
        self._run(candidates)
        self.assertEqual(0, self._order_count())

    # ── already executed guard ────────────────────────────────────────────────
    def test_already_executed_pending_not_re_traded(self):
        candidate = _make_candidate()
        # First execution
        client = self._run([candidate])
        client.place_market_order.assert_called_once()
        # Second call — should be blocked
        client2 = _fake_client()
        rm = _fake_risk_manager()
        with patch("semi_bot_trading.live_worker.build_risk_manager", return_value=rm):
            maybe_execute_candidates(
                self._conn, self._config, _make_env(), client2, [candidate], "XAUUSDm"
            )
        client2.place_market_order.assert_not_called()

    # ── score selection ───────────────────────────────────────────────────────
    def test_highest_score_candidate_selected(self):
        low = _make_candidate(id="low-score", score=0.3)
        high = _make_candidate(id="high-score", score=0.9)
        client = self._run([low, high])
        # Only one order should be placed
        self.assertEqual(1, self._order_count())
        # The trade idea should be for the high-score candidate
        idea = self._conn.execute("SELECT * FROM trade_ideas").fetchone()
        self.assertIn("high-score", idea["id"])

    # ── pricing plan failure ──────────────────────────────────────────────────
    def test_pricing_failure_queues_alert_no_trade(self):
        with patch(
            "semi_bot_trading.live_worker.build_execution_pricing_plan",
            side_effect=ValueError("bad entry"),
        ):
            self._run([_make_candidate()])
        self.assertEqual(0, self._order_count())
        alerts = self._conn.execute("SELECT * FROM alert_events").fetchall()
        self.assertTrue(any("pricing" in a["event_type"] or "execution_event" == a["event_type"]
                            for a in alerts))

    # ── risk manager blocks ───────────────────────────────────────────────────
    def test_risk_manager_block_queues_alert_no_trade(self):
        self._run([_make_candidate()], rm_allowed=False)
        self.assertEqual(0, self._order_count())
        alerts = self._conn.execute("SELECT * FROM alert_events").fetchall()
        self.assertTrue(len(alerts) > 0)

    # ── successful end-to-end ─────────────────────────────────────────────────
    def test_successful_execution_end_to_end(self):
        self._run([_make_candidate()])
        self.assertEqual(1, self._order_count())
        er = self._conn.execute("SELECT * FROM execution_requests").fetchone()
        self.assertEqual("sent", er["status"])


# ─────────────────────────────────────────────────────────────────────────────
# FTMO news compliance
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


class TestFtmoNewsCompliance(unittest.TestCase):

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._db_path, self._conn = _setup_db(self._tmp.name)
        self._config = replace(load_config(), database=self._db_path)
        self._env = _make_env(
            account_profile="ftmo_challenge",
            ftmo_phase="funded",
            ftmo_account_type="standard",
        )

    def tearDown(self):
        self._conn.close()
        self._tmp.cleanup()

    def test_evaluation_and_swing_accounts_do_not_activate_compliance_guard(self):
        now = datetime(2026, 8, 7, 12, 30, tzinfo=UTC)
        evaluation = replace(self._env, ftmo_phase="evaluation")
        swing = replace(self._env, ftmo_account_type="swing")
        self.assertIsNone(ftmo_news_guard_state(self._conn, evaluation, now))
        self.assertIsNone(ftmo_news_guard_state(self._conn, swing, now))

    def test_startup_rejects_unsafe_funded_standard_news_config(self):
        client = _fake_client()
        client.get_account_info.return_value = {
            "balance": 100000,
            "equity": 100000,
            "currency": "USD",
        }
        client.get_symbol_trade_info.return_value = {"trade_contract_size": 100.0}
        unsafe = replace(self._env, ftmo_news_buffer_minutes=3)
        with self.assertRaisesRegex(RuntimeError, "FTMO_NEWS_BUFFER_MINUTES"):
            validate_live_account_startup(unsafe, client, "XAUUSD")

    def test_prepare_phase_cancels_pending_and_closes_bot_positions(self):
        client = _fake_client()
        client.cancel_pending_orders.return_value = [{"order": 111, "retcode": 10009}]
        client.close_open_positions.return_value = [{"order": 222, "deal": 333, "retcode": 10009}]
        now = "2026-08-07T12:25:00+00:00"
        self._conn.execute(
            """INSERT INTO trade_ideas
               (id, symbol, direction, playbook, status, entry_zone_id,
                related_zone_ids_json, context_snapshot_json, suggested_entry,
                suggested_stop_loss, suggested_take_profit_json, risk_reward, created_at)
               VALUES ('idea-ftmo-pending', 'XAUUSD', 'long', 'test', 'approved', NULL, '[]', '{}',
                       3000, 2980, '[3040]', 2.0, ?)""",
            (now,),
        )
        self._conn.execute(
            """INSERT INTO trade_orders
               (id, trade_idea_id, account_label, symbol, side, order_type, status,
                entry_price, stop_loss, take_profit_json, quantity,
                opened_at, source, metadata_json, created_at)
               VALUES ('order-ftmo-pending', 'idea-ftmo-pending', 'Test', 'XAUUSD', 'buy', 'limit', 'pending_fill',
                       3000, 2980, '[3040]', 0.01, ?, 'live', '{}', ?)""",
            (now, now),
        )
        self._conn.commit()
        guard = {
            "id": "nfp",
            "title": "Non-Farm Employment Change",
            "phase": "prepare",
            "scheduled_at": "2026-08-07T12:30:00+00:00",
        }

        did_flatten = maybe_ftmo_news_flatten(
            self._conn, self._config, self._env, client, "XAUUSDm", guard,
        )

        self.assertTrue(did_flatten)
        client.cancel_pending_orders.assert_called_once_with(
            "XAUUSDm", magic=self._env.mt5_magic, comment="FTMO news flatten",
        )
        client.close_open_positions.assert_called_once_with(
            "XAUUSDm", magic=self._env.mt5_magic, comment="FTMO news flatten",
        )
        row = self._conn.execute(
            "SELECT status FROM trade_orders WHERE id = 'order-ftmo-pending'"
        ).fetchone()
        self.assertEqual("cancelled", row["status"])

    def test_hard_window_never_sends_flatten_actions(self):
        client = _fake_client()
        guard = {"id": "nfp", "title": "NFP", "phase": "restricted"}
        self.assertFalse(
            maybe_ftmo_news_flatten(self._conn, self._config, self._env, client, "XAUUSDm", guard)
        )
        client.cancel_pending_orders.assert_not_called()
        client.close_open_positions.assert_not_called()

    def test_live_iteration_suppresses_partial_tp_and_dashboard_commands_in_hard_window(self):
        client = _fake_client()
        state = LiveWorkerState(broker_symbol="XAUUSDm")
        guard = {"id": "nfp", "title": "NFP", "phase": "restricted"}
        with (
            patch("semi_bot_trading.live_worker.snapshot_account"),
            patch("semi_bot_trading.live_worker.refresh_account_execution_control"),
            patch("semi_bot_trading.live_worker.snapshot_spread"),
            patch("semi_bot_trading.live_worker.sync_mt5_candles"),
            patch("semi_bot_trading.live_worker.sync_closed_positions"),
            patch("semi_bot_trading.live_worker.ftmo_news_guard_state", return_value=guard),
            patch("semi_bot_trading.live_worker.process_account_execution_commands") as commands,
            patch("semi_bot_trading.live_worker.manage_open_trade_partial_take_profit") as partial_tp,
            patch("semi_bot_trading.live_worker.maybe_ftmo_news_flatten") as news_flatten,
            patch("semi_bot_trading.live_worker.queue_ftmo_news_guard_alert"),
            patch("semi_bot_trading.live_worker.maybe_weekend_flatten") as weekend_flatten,
            patch("semi_bot_trading.live_worker.send_pending_telegram_alerts"),
        ):
            run_live_iteration(self._config, self._env, client, state)

        commands.assert_not_called()
        partial_tp.assert_not_called()
        news_flatten.assert_not_called()
        weekend_flatten.assert_not_called()


# weekend flatten guard
# ─────────────────────────────────────────────────────────────────────────────

class TestWeekendFlatten(unittest.TestCase):

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._db_path, self._conn = _setup_db(self._tmp.name)
        self._config = replace(load_config(), database=self._db_path)

    def tearDown(self):
        self._conn.close()
        self._tmp.cleanup()

    def test_no_new_trade_window_starts_friday_noon_new_york(self):
        env = _make_env(weekend_flatten_enabled=True)
        before = datetime(2026, 6, 26, 15, 59, tzinfo=UTC)  # 11:59 New York
        at_cutoff = datetime(2026, 6, 26, 16, 0, tzinfo=UTC)  # 12:00 New York
        self.assertFalse(is_weekend_no_new_trade_window(env, before))
        self.assertTrue(is_weekend_no_new_trade_window(env, at_cutoff))
        sunday_before_reopen = datetime(2026, 6, 28, 20, 59, tzinfo=UTC)  # 16:59 New York
        sunday_reopen = datetime(2026, 6, 28, 21, 0, tzinfo=UTC)  # 17:00 New York
        self.assertTrue(is_weekend_no_new_trade_window(env, sunday_before_reopen))
        self.assertFalse(is_weekend_no_new_trade_window(env, sunday_reopen))

    def test_flatten_window_starts_friday_1530_new_york(self):
        env = _make_env(weekend_flatten_enabled=True)
        before = datetime(2026, 6, 26, 19, 29, tzinfo=UTC)  # 15:29 New York
        at_cutoff = datetime(2026, 6, 26, 19, 30, tzinfo=UTC)  # 15:30 New York
        self.assertFalse(is_weekend_flatten_window(env, before))
        self.assertTrue(is_weekend_flatten_window(env, at_cutoff))

    def test_flatten_window_uses_new_york_fallback_when_tzdata_missing(self):
        env = _make_env(weekend_flatten_enabled=True)
        deploy_time = datetime(2026, 6, 26, 17, 50, tzinfo=UTC)  # 13:50 New York, before flatten
        flatten_time = datetime(2026, 6, 26, 19, 30, tzinfo=UTC)  # 15:30 New York
        with patch("semi_bot_trading.live_worker.ZoneInfo", side_effect=ZoneInfoNotFoundError):
            self.assertFalse(is_weekend_flatten_window(env, deploy_time))
            self.assertTrue(is_weekend_flatten_window(env, flatten_time))

    def test_weekend_flatten_cancels_pending_and_closes_positions(self):
        env = _make_env(weekend_flatten_enabled=True)
        client = _fake_client()
        client.cancel_pending_orders.return_value = [{"order": 111, "retcode": 10009}]
        client.close_open_positions.return_value = [{"order": 222, "deal": 333, "retcode": 10009}]
        now = "2026-06-26T18:00:00+00:00"
        self._conn.execute(
            """INSERT INTO trade_ideas
               (id, symbol, direction, playbook, status, entry_zone_id,
                related_zone_ids_json, context_snapshot_json, suggested_entry,
                suggested_stop_loss, suggested_take_profit_json, risk_reward, created_at)
               VALUES ('idea-pending', 'XAUUSD', 'long', 'test', 'approved', NULL, '[]', '{}',
                       3000, 2980, '[3040]', 2.0, ?)""",
            (now,),
        )
        self._conn.execute(
            """INSERT INTO trade_orders
               (id, trade_idea_id, account_label, symbol, side, order_type, status,
                entry_price, stop_loss, take_profit_json, quantity,
                opened_at, source, metadata_json, created_at)
               VALUES ('order-pending', 'idea-pending', 'Test', 'XAUUSD', 'buy', 'limit', 'pending_fill',
                       3000, 2980, '[3040]', 0.01, ?, 'live', '{}', ?)""",
            (now, now),
        )
        self._conn.commit()

        did_flatten = maybe_weekend_flatten(
            self._conn,
            self._config,
            env,
            client,
            "XAUUSDm",
            datetime(2026, 6, 26, 19, 30, tzinfo=UTC),
        )

        self.assertTrue(did_flatten)
        client.cancel_pending_orders.assert_called_once_with("XAUUSDm", magic=env.mt5_magic, comment="Friday flatten")
        client.close_open_positions.assert_called_once_with("XAUUSDm", magic=env.mt5_magic, comment="Friday flatten")
        row = self._conn.execute("SELECT status FROM trade_orders WHERE id = 'order-pending'").fetchone()
        self.assertEqual("cancelled", row["status"])


# ─────────────────────────────────────────────────────────────────────────────
# sync_closed_positions
# ─────────────────────────────────────────────────────────────────────────────

class TestSyncClosedPositions(unittest.TestCase):

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._db_path, self._conn = _setup_db(self._tmp.name)
        self._config = replace(load_config(), database=self._db_path)
        self._env = _make_env()

    def tearDown(self):
        self._conn.close()
        self._tmp.cleanup()

    def _insert_order(self, order_id: str, broker_order_id: str = "111",
                      broker_deal_id: str = "222", status: str = "filled") -> None:
        now = datetime.now(UTC).isoformat()
        idea_id = f"idea-{order_id}"
        self._conn.execute(
            """INSERT OR IGNORE INTO trade_ideas
               (id, symbol, direction, playbook, status, entry_zone_id,
                related_zone_ids_json, context_snapshot_json, suggested_entry,
                suggested_stop_loss, suggested_take_profit_json, risk_reward, created_at)
               VALUES (?, 'XAUUSD', 'long', 'test', 'approved', NULL, '[]', '{}',
                       3000, 2980, '[3040]', 2.0, ?)""",
            (idea_id, now),
        )
        metadata = json.dumps({
            "broker_order_id": broker_order_id,
            "broker_deal_id": broker_deal_id,
        })
        self._conn.execute(
            """INSERT INTO trade_orders
               (id, trade_idea_id, account_label, symbol, side, order_type, status,
                entry_price, stop_loss, take_profit_json, quantity,
                opened_at, source, metadata_json, created_at)
               VALUES (?, ?, 'Test', 'XAUUSD', 'buy', 'market', ?, 3000, 2980, '[3040]',
                       0.01, ?, 'live', ?, ?)""",
            (order_id, idea_id, status, now, metadata, now),
        )
        self._conn.commit()

    def _run(self, client):
        sync_closed_positions(self._conn, self._config, self._env, client, "XAUUSDm")

    def test_no_open_orders_returns_cleanly(self):
        client = _fake_client()
        self._run(client)  # No exception, no queries needed
        client.get_open_position_tickets.assert_not_called()

    def test_position_still_open_not_closed(self):
        self._insert_order("ord-1", broker_order_id="111")
        client = _fake_client(open_tickets={"111"})
        self._run(client)
        row = self._conn.execute("SELECT status FROM trade_orders WHERE id='ord-1'").fetchone()
        self.assertEqual("filled", row["status"])

    def test_position_closed_no_deal_yet_skipped(self):
        self._insert_order("ord-2")
        client = _fake_client(open_tickets=set(), closed_deal=None)
        self._run(client)
        row = self._conn.execute("SELECT status FROM trade_orders WHERE id='ord-2'").fetchone()
        self.assertEqual("filled", row["status"])

    def test_position_closed_updates_pnl(self):
        self._insert_order("ord-3", broker_order_id="111", broker_deal_id="222")
        closed_deal = {
            "profit": 40.0, "profit_raw": 40.0, "swap": -0.5, "commission": -1.0,
            "fee": -0.25,
            "price": 3040.0, "time_iso": datetime.now(UTC).isoformat(),
        }
        client = _fake_client(open_tickets=set(), closed_deal=closed_deal, contract_size=100.0)
        self._run(client)

        row = self._conn.execute("SELECT * FROM trade_orders WHERE id='ord-3'").fetchone()
        self.assertEqual("closed", row["status"])
        self.assertAlmostEqual(38.25, row["pnl"], places=2)   # 40 - 0.5 - 1 - 0.25
        self.assertIsNotNone(row["pnl_r"])
        costs = json.loads(row["metadata_json"])["broker_close_costs"]
        self.assertEqual(
            {
                "gross_profit": 40.0,
                "commission": -1.0,
                "swap": -0.5,
                "fee": -0.25,
                "net_profit": 38.25,
            },
            costs,
        )

    def test_existing_closed_order_backfills_full_costs_without_new_alert(self):
        self._insert_order("ord-old", broker_order_id="111", status="closed")
        closed_deal = {
            "profit": 89.70, "profit_raw": 89.70, "swap": 0.0, "commission": -2.66,
            "fee": 0.0,
            "price": 4127.08, "time_iso": datetime.now(UTC).isoformat(),
        }
        client = _fake_client(open_tickets=set(), closed_deal=closed_deal, contract_size=100.0)

        self._run(client)

        row = self._conn.execute("SELECT * FROM trade_orders WHERE id='ord-old'").fetchone()
        self.assertAlmostEqual(87.04, row["pnl"], places=2)
        costs = json.loads(row["metadata_json"])["broker_close_costs"]
        self.assertEqual(-2.66, costs["commission"])
        alert_count = self._conn.execute(
            "SELECT COUNT(*) count FROM alert_events WHERE entity_ids_json LIKE '%ord-old%'"
        ).fetchone()["count"]
        self.assertEqual(0, alert_count)

    def test_missing_broker_ids_skipped(self):
        self._insert_order("ord-4", broker_order_id="", broker_deal_id="")
        client = _fake_client(open_tickets=set())
        self._run(client)
        client.get_closed_deal_for_position.assert_not_called()

    def test_pending_fill_order_also_synced(self):
        """Limit orders with status=pending_fill must also be checked for closure."""
        self._insert_order("ord-5", broker_order_id="555", status="pending_fill")
        closed_deal = {
            "profit": 20.0, "profit_raw": 20.0, "swap": 0.0, "commission": 0.0,
            "price": 3020.0, "time_iso": datetime.now(UTC).isoformat(),
        }
        client = _fake_client(open_tickets=set(), closed_deal=closed_deal)
        self._run(client)
        row = self._conn.execute("SELECT status FROM trade_orders WHERE id='ord-5'").fetchone()
        self.assertEqual("closed", row["status"])

    def test_pnl_r_calculated_correctly(self):
        """pnl_r = pnl / risk_amount; risk = stop_distance × qty × contract_size."""
        self._insert_order("ord-6", broker_order_id="666")
        # entry=3000, stop=2980 → stop_distance=20, qty=0.01, cs=100
        # risk_amount = 20 × 0.01 × 100 = 20
        # profit_raw=40 → price_delta=40, qty=0.01, cs = 40/(40×0.01)=100 ✓
        # pnl = 40 - 0 - 0 = 40
        # pnl_r = 40 / 20 = 2.0
        closed_deal = {
            "profit": 40.0, "profit_raw": 40.0, "swap": 0.0, "commission": 0.0,
            "price": 3040.0, "time_iso": datetime.now(UTC).isoformat(),
        }
        client = _fake_client(open_tickets=set(), closed_deal=closed_deal, contract_size=100.0)
        self._run(client)
        row = self._conn.execute("SELECT pnl_r FROM trade_orders WHERE id='ord-6'").fetchone()
        self.assertAlmostEqual(2.0, row["pnl_r"], places=2)


# ─────────────────────────────────────────────────────────────────────────────
# candidates_after_live_fvg_trade_count
# ─────────────────────────────────────────────────────────────────────────────

class TestCandidatesAfterFvgTradeCount(unittest.TestCase):

    def setUp(self):
        self._tmp = TemporaryDirectory()
        _, self._conn = _setup_db(self._tmp.name)

    def tearDown(self):
        self._conn.close()
        self._tmp.cleanup()

    def _insert_fvg_trade(self, zone_id: str) -> None:
        now = datetime.now(UTC).isoformat()
        idea_id = f"idea-fvg-{zone_id}"
        self._conn.execute(
            """INSERT OR IGNORE INTO trade_ideas
               (id, symbol, direction, playbook, status, entry_zone_id,
                related_zone_ids_json, context_snapshot_json, suggested_entry,
                suggested_stop_loss, suggested_take_profit_json, risk_reward, created_at)
               VALUES (?, 'XAUUSD', 'long', 'test', 'approved', NULL, '[]', '{}',
                       3000, 2980, '[3040]', 2.0, ?)""",
            (idea_id, now),
        )
        metadata = json.dumps({"primary_zone_id": zone_id, "zone_type": "fvg"})
        self._conn.execute(
            """INSERT INTO trade_orders
               (id, trade_idea_id, symbol, side, order_type, status,
                entry_price, stop_loss, take_profit_json, quantity,
                opened_at, source, metadata_json, created_at)
               VALUES (?, ?, 'XAUUSD', 'buy', 'market', 'filled', 3000, 2980, '[3040]',
                       0.01, ?, 'live', ?, ?)""",
            (f"ord-fvg-{zone_id}-{uuid.uuid4()}", idea_id, now, metadata, now),
        )
        self._conn.commit()

    def test_max_zero_passes_all_through(self):
        fvg = _make_candidate(metadata={"zone_type": "fvg"}, primary_zone_id="fvg-1")
        result = candidates_after_live_fvg_trade_count(self._conn, "XAUUSD", [fvg], 0)
        self.assertEqual(1, len(result))

    def test_non_fvg_always_passes(self):
        sr = _make_candidate(metadata={"zone_type": "support"}, primary_zone_id="sr-1")
        result = candidates_after_live_fvg_trade_count(self._conn, "XAUUSD", [sr], 1)
        self.assertEqual(1, len(result))

    def test_fvg_under_limit_passes(self):
        self._insert_fvg_trade("fvg-zone-1")
        fvg = _make_candidate(metadata={"zone_type": "fvg"}, primary_zone_id="fvg-zone-1")
        result = candidates_after_live_fvg_trade_count(self._conn, "XAUUSD", [fvg], 2)
        self.assertEqual(1, len(result))

    def test_fvg_at_limit_blocked(self):
        self._insert_fvg_trade("fvg-zone-2")
        self._insert_fvg_trade("fvg-zone-2")
        fvg = _make_candidate(metadata={"zone_type": "fvg"}, primary_zone_id="fvg-zone-2")
        result = candidates_after_live_fvg_trade_count(self._conn, "XAUUSD", [fvg], 2)
        self.assertEqual(0, len(result))

    def test_mixed_candidates(self):
        self._insert_fvg_trade("fvg-zone-3")
        self._insert_fvg_trade("fvg-zone-3")
        fvg_blocked = _make_candidate(id="fvg-blocked", metadata={"zone_type": "fvg"},
                                      primary_zone_id="fvg-zone-3")
        fvg_ok = _make_candidate(id="fvg-ok", metadata={"zone_type": "fvg"},
                                 primary_zone_id="fvg-zone-clean")
        sr = _make_candidate(id="sr-ok", metadata={"zone_type": "support"})
        result = candidates_after_live_fvg_trade_count(
            self._conn, "XAUUSD", [fvg_blocked, fvg_ok, sr], 2
        )
        ids = [c["id"] for c in result]
        self.assertNotIn("fvg-blocked", ids)
        self.assertIn("fvg-ok", ids)
        self.assertIn("sr-ok", ids)


# ─────────────────────────────────────────────────────────────────────────────
# _seconds_until_next_poll
# ─────────────────────────────────────────────────────────────────────────────

class TestSecondsUntilNextPoll(unittest.TestCase):

    def test_empty_marks_returns_fallback(self):
        result = _seconds_until_next_poll((), fallback_seconds=15.0)
        self.assertAlmostEqual(15.0, result, places=0)

    def test_invalid_marks_returns_fallback(self):
        result = _seconds_until_next_poll((), fallback_seconds=10.0)
        self.assertAlmostEqual(10.0, result, places=0)

    def test_sleep_less_than_60_seconds(self):
        result = _seconds_until_next_poll((1, 16, 31, 46), fallback_seconds=15.0)
        self.assertGreater(result, 0.0)
        self.assertLessEqual(result, 60.0)

    def test_minimum_sleep_is_positive(self):
        result = _seconds_until_next_poll((1, 16, 31, 46), fallback_seconds=15.0)
        self.assertGreaterEqual(result, 0.1)

    def test_single_mark_wraps_to_next_minute(self):
        """A single mark that's already past → waits up to ~60s."""
        result = _seconds_until_next_poll((0,), fallback_seconds=15.0)
        self.assertGreater(result, 0.0)
        self.assertLessEqual(result, 60.0)


# ─────────────────────────────────────────────────────────────────────────────
# trading_session
# ─────────────────────────────────────────────────────────────────────────────

class TestFtmoDailyWindow(unittest.TestCase):
    def test_summer_midnight_uses_cest(self):
        day, start = _ftmo_day_window(datetime(2026, 7, 20, 12, tzinfo=UTC), "Europe/Prague")
        self.assertEqual("2026-07-20", day)
        self.assertEqual(datetime(2026, 7, 19, 22, tzinfo=UTC), start)

    def test_winter_midnight_uses_cet(self):
        day, start = _ftmo_day_window(datetime(2026, 1, 20, 12, tzinfo=UTC), "Europe/Prague")
        self.assertEqual("2026-01-20", day)
        self.assertEqual(datetime(2026, 1, 19, 23, tzinfo=UTC), start)

    def test_infers_ftmo_initial_balance_from_account_label(self):
        env = _make_env(account_profile="ftmo_challenge", account_label="FTMO 100K 2-Step")
        self.assertEqual(100_000.0, _resolved_initial_balance(env))

    def test_explicit_initial_balance_has_priority(self):
        env = _make_env(
            account_profile="ftmo_challenge",
            account_label="FTMO 100K 2-Step",
            account_initial_balance=200_000.0,
        )
        self.assertEqual(200_000.0, _resolved_initial_balance(env))


class TestTradingSession(unittest.TestCase):

    def _ts(self, hour: int) -> str:
        return f"2026-06-22T{hour:02d}:30:00+00:00"

    def test_asian_session(self):
        self.assertEqual("Asian", trading_session(self._ts(3)))
        self.assertEqual("Asian", trading_session(self._ts(6)))

    def test_london_session(self):
        self.assertEqual("London", trading_session(self._ts(8)))
        self.assertEqual("London", trading_session(self._ts(11)))

    def test_london_ny_overlap(self):
        self.assertEqual("London-NY", trading_session(self._ts(13)))
        self.assertEqual("London-NY", trading_session(self._ts(16)))

    def test_new_york_session(self):
        self.assertEqual("New York", trading_session(self._ts(17)))
        self.assertEqual("New York", trading_session(self._ts(20)))

    def test_off_hours(self):
        self.assertEqual("Off-hours", trading_session(self._ts(21)))
        self.assertEqual("Off-hours", trading_session(self._ts(23)))

    def test_invalid_iso_returns_unknown(self):
        self.assertEqual("unknown", trading_session("not-a-date"))


if __name__ == "__main__":
    unittest.main()
