import unittest
from dataclasses import replace
from unittest.mock import Mock, patch
from semi_bot_trading.config import load_config
from semi_bot_trading.trading_sessions import parse_sessions, session_end
from semi_bot_trading.live_worker import execute_candidate
from semi_bot_trading.strategy.zone_reaction_v2 import evaluate_zone_reaction_v2, maybe_apply_impulse_retest_limit
from types import SimpleNamespace


class TestTradingSessions(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_config_and_boundaries(self):
        strategy = self.config.strategy
        self.assertTrue(strategy.zone_reaction_v2_session_filter_enabled)
        for timestamp, allowed in [
            ("2026-09-06T11:59:59+00:00", False),
            ("2026-09-06T12:00:00+00:00", True),
            ("2026-09-06T16:59:59+00:00", True),
            ("2026-09-06T17:00:00+00:00", False),
            ("2026-09-06T19:00:00+07:00", True),
            ("2026-09-07T00:00:00+07:00", False),
        ]:
            with self.subTest(timestamp=timestamp):
                self.assertEqual(allowed, session_end(strategy, timestamp) is not None)

    def test_custom_overnight_and_disabled_sessions(self):
        strategy = replace(self.config.strategy, zone_reaction_v2_sessions=parse_sessions({
            "night": {"enabled": True, "start_utc": "22:30", "end_utc": "02:15"},
            "day": {"enabled": False, "start_utc": "12:00", "end_utc": "17:00"},
        }))
        self.assertEqual("2026-09-07T02:15:00+00:00", session_end(strategy, "2026-09-07T01:00:00Z").isoformat())
        self.assertIsNone(session_end(strategy, "2026-09-07T02:15:00Z"))
        self.assertIsNone(session_end(strategy, "2026-09-07T12:00:00Z"))

    def test_invalid_config(self):
        for value in ("25:00", "12:60", "noon"):
            with self.assertRaises(ValueError):
                parse_sessions({"x": {"start_utc": value, "end_utc": "17:00"}})

    def test_signal_blocked_outside_session(self):
        self.assertEqual([], evaluate_zone_reaction_v2(
            "XAUUSD", {}, None, 0, 0, "", None, "", set(), [], [],
            self.config.strategy, "2026-09-06T17:00:00Z",
        ))

    def test_live_execution_rechecks_clock_before_broker_or_db_write(self):
        conn, client = Mock(), Mock()
        with patch("semi_bot_trading.live_worker.account_execution_is_enabled", return_value=True), patch(
            "semi_bot_trading.live_worker.utc_now_iso", return_value="2026-09-06T17:00:00+00:00"
        ):
            self.assertIsNone(execute_candidate(conn, self.config, Mock(), client,
                {"playbook": "zone_reaction_v2"}, "XAUUSD"))
        self.assertEqual([], client.mock_calls)
        self.assertEqual([], conn.mock_calls)

    def test_limit_expiry_capped_at_session_end(self):
        result = maybe_apply_impulse_retest_limit(
            zone={"price_high": 3000, "price_low": 2990},
            direction="long", reaction=SimpleNamespace(state="reject", metadata={}),
            entry=3050, stop=2980, atr=10, as_of="2026-09-06T16:45:00+00:00",
            config=self.config.strategy,
        )
        self.assertIsNotNone(result)
        self.assertEqual("2026-09-06T17:00:00+00:00", result["limit_order_expires_at"])

    def test_cancellation_only_for_confirmed_pending_zone_orders(self):
        from tests.test_live_worker import _setup_db, _make_env
        from tempfile import TemporaryDirectory
        from semi_bot_trading.live_worker import cancel_zone_reaction_session_orders
        with TemporaryDirectory() as directory:
            _, conn = _setup_db(directory)
            try:
                conn.execute("""INSERT INTO trade_ideas
                    (id,symbol,direction,playbook,status,suggested_stop_loss)
                    VALUES ('session-idea','XAUUSD','long','zone_reaction_v2','approved',2900)""")
                conn.execute("""INSERT INTO trade_orders
                    (id,trade_idea_id,account_label,symbol,side,order_type,status,
                     stop_loss,quantity,source,metadata_json)
                    VALUES ('session-order','session-idea','Test','XAUUSD','buy','limit',
                    'pending_fill',2900,0.1,'live','{"broker_order_id":"123"}')""")
                client = Mock()
                env = _make_env()
                for state in ("filled", None, "pending"):
                    client.get_pending_order_state.return_value = state
                    with patch("semi_bot_trading.live_worker.utc_now_iso", return_value="2026-09-06T17:00:00+00:00"):
                        cancel_zone_reaction_session_orders(conn, self.config, env, client, "XAUUSD")
                    status = conn.execute("SELECT status FROM trade_orders").fetchone()["status"]
                    self.assertEqual("cancelled" if state == "pending" else "pending_fill", status)
                client.cancel_pending_order.assert_called_once()
            finally:
                conn.close()
