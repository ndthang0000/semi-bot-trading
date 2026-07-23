from __future__ import annotations

import json
import unittest

from semi_bot_trading.config import load_config
from semi_bot_trading.db import connect, init_db
from semi_bot_trading.trade_report import build_zone_trade_report, render_zone_trade_report_html


class TradeReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect(":memory:")
        init_db(self.conn)
        self.config = load_config()
        self.zone_id = "zone-report-test"
        self.conn.execute(
            """
            INSERT INTO price_zones (
                id, symbol, timeframe, detector, zone_type, direction,
                price_low, price_high, start_time, valid_from, detected_at,
                bot_confidence, bot_weight, effective_confidence, effective_weight,
                status, source, metadata_json
            ) VALUES (?, 'XAUUSD', 'H1', 'fvg_v1', 'fvg', 'bearish',
                      100, 120, '2030-01-01T00:00:00+00:00', '2030-01-01T00:00:00+00:00',
                      '2030-01-01T00:00:00+00:00', .8, .7, .8, .7, 'active', 'human', ?)
            """,
            (self.zone_id, json.dumps({"trade_modes": [], "fill_ratio": 0.5})),
        )
        candidate = {
            "id": "candidate-1",
            "playbook": "zone_reaction_v2",
            "direction": "short",
            "status": "eligible",
            "zone_reaction_state": "reject",
            "entry": 90.0,
            "stop_loss": 102.0,
            "take_profit": [60.0],
            "risk_reward": 2.5,
            "score": 0.75,
            "reason": ["Strong bearish rejection from <zone>."],
            "metadata": {
                "as_of": "2030-01-01T01:00:00+00:00",
                "reaction_candle_time": "2030-01-01T01:15:00+00:00",
                "reaction_v2": "reject",
                "reaction_open": 110.0,
                "reaction_high": 115.0,
                "reaction_low": 88.0,
                "reaction_close": 90.0,
                "reaction_body": 20.0,
                "atr": 5.0,
                "stop_source": "atr_fallback",
                "stop_fallback_atr": 10.0,
                "stop_fallback_atr_multiplier": 1.2,
                "stop_fallback_atr_timeframe": "H1",
                "zone_type": "fvg",
                "zone_timeframe": "H1",
                "zone_direction": "bearish",
                "zone_detector": "fvg_v1",
                "zone_source": "bot",
                "zone_status": "active",
                "zone_price_low": 100.0,
                "zone_price_high": 120.0,
                "zone_detected_at": "2030-01-01T00:00:00+00:00",
                "zone_confidence": 0.8,
                "zone_weight": 0.7,
                "zone_fill_ratio": 0.25,
                "trade_modes": ["reject", "internal_reject"],
                "h1_bias": "bearish",
                "h1_regime": "trending",
                "macro_trend": "down",
            },
        }
        context = {"candidate": candidate, "pricing_plan": {"entry_price": 90.0, "stop_loss": 102.0}}
        self.conn.execute(
            """
            INSERT INTO trade_ideas (
                id, symbol, direction, playbook, status, entry_zone_id,
                related_zone_ids_json, context_snapshot_json, suggested_entry,
                suggested_stop_loss, suggested_take_profit_json, risk_reward, created_at
            ) VALUES ('idea-1', 'XAUUSD', 'short', 'zone_reaction_v2', 'approved', ?,
                      ?, ?, 90, 102, '[60]', 2.5, '2030-01-01T01:15:00+00:00')
            """,
            (self.zone_id, json.dumps([self.zone_id]), json.dumps(context)),
        )
        order_meta = {
            "initial_stop_loss": 102.0,
            "partial_take_profit": {"enabled": True, "done": True, "trigger_price": 75.0},
        }
        self.conn.execute(
            """
            INSERT INTO trade_orders (
                id, trade_idea_id, account_label, symbol, side, order_type, status,
                entry_price, stop_loss, take_profit_json, quantity, opened_at, closed_at,
                close_price, pnl, pnl_r, source, metadata_json
            ) VALUES ('order-1', 'idea-1', 'Test Account', 'XAUUSD', 'sell', 'market', 'closed',
                      90, 90, '[60]', .5, '2030-01-01T01:15:01+00:00',
                      '2030-01-01T02:00:00+00:00', 80, 500, .5, 'live', ?)
            """,
            (json.dumps(order_meta),),
        )
        self.conn.execute(
            """
            INSERT INTO execution_requests (
                id, trade_idea_id, account_label, symbol, broker_symbol, side,
                order_type, quantity, entry_price, stop_loss, take_profit_json,
                risk_snapshot_json, context_snapshot_json, requested_by, status,
                broker_result_json, created_at, updated_at
            ) VALUES ('exec-1', 'idea-1', 'Test Account', 'XAUUSD', 'XAUUSD', 'sell',
                      'market', .5, 90, 102, '[60]', '{}', ?, 'strategy', 'sent', '{}',
                      '2030-01-01T01:15:01+00:00', '2030-01-01T01:15:01+00:00')
            """,
            (json.dumps(context),),
        )
        self.conn.execute(
            """
            INSERT INTO candles (
                id, symbol, timeframe, open_time, close_time, open, high, low, close, source
            ) VALUES ('candle-1', 'XAUUSD', 'M15', '2030-01-01T01:15:00+00:00',
                      '2030-01-01T01:30:00+00:00', 90, 95, 70, 80, 'test')
            """
        )
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()

    def test_builds_historical_report_without_confusing_be_stop(self) -> None:
        report = build_zone_trade_report(
            self.conn,
            self.config,
            self.zone_id,
            database=":memory:",
            code_commit="abc123",
            generated_at="2030-01-02T00:00:00+00:00",
        )

        self.assertEqual(1, report.stats["trade_count"])
        self.assertEqual(500.0, report.stats["total_pnl"])
        self.assertEqual("bot", report.historical_zone["source"])
        self.assertEqual(102.0, report.trades[0]["initial_stop"])
        self.assertEqual(90.0, report.trades[0]["current_stop"])
        self.assertEqual("atr_fallback", report.trades[0]["sl_trace"]["selected_source"])
        self.assertEqual(20.0, report.trades[0]["excursion"]["mfe_price"])
        self.assertEqual(10.0, report.trades[0]["trigger"]["body_average"])
        self.assertEqual(2.0, report.trades[0]["trigger"]["body_average_ratio"])
        self.assertTrue(report.trades[0]["trigger"]["strength_gate_passed"])
        self.assertTrue(report.trades[0]["trigger"]["direction_aligned"])
        self.assertTrue(report.trades[0]["trigger"]["touches_zone"])
        self.assertTrue(report.trades[0]["trigger"]["reclaim_passed"])
        self.assertTrue(any("Current zone differs" in warning for warning in report.warnings))

    def test_renders_self_contained_escaped_html(self) -> None:
        report = build_zone_trade_report(
            self.conn,
            self.config,
            self.zone_id,
            database=":memory:",
            generated_at="2030-01-02T00:00:00+00:00",
        )

        output = render_zone_trade_report_html(report)

        self.assertIn("<!doctype html>", output)
        self.assertIn("zone-trade-report-v1", output)
        self.assertIn("Stop-loss decision trace", output)
        self.assertIn("Strength gate", output)
        self.assertIn("Body / average", output)
        self.assertIn("Classic reject: directional body", output)
        self.assertIn("Strong bearish rejection from &lt;zone&gt;.", output)
        self.assertNotIn("Strong bearish rejection from <zone>.", output)

    def test_pinbar_strength_uses_wick_recovery_not_body_ratio(self) -> None:
        from semi_bot_trading.trade_report import _trigger_quality

        trigger = _trigger_quality(
            self.conn,
            self.config,
            symbol="XAUUSD",
            side="buy",
            reaction="reject",
            metadata={
                "reaction_candle_time": "2030-01-01T01:15:00+00:00",
                "reaction_open": 90.0,
                "reaction_high": 93.0,
                "reaction_low": 70.0,
                "reaction_close": 92.0,
                "reaction_body": 2.0,
                "zone_price_low": 70.0,
                "zone_price_high": 91.0,
            },
            reasons=["Bullish pinbar rejection at zone."],
        )

        self.assertEqual("pinbar_reject", trigger["validation_method"])
        self.assertEqual(0.2, trigger["body_average_ratio"])
        self.assertEqual(2.2, trigger["strength_ratio"])
        self.assertTrue(trigger["strength_gate_passed"])
        self.assertTrue(trigger["wick_body_gate_passed"])
        self.assertTrue(trigger["wick_range_gate_passed"])

    def test_missing_zone_and_ideas_is_an_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Zone not found"):
            build_zone_trade_report(
                self.conn,
                self.config,
                "missing-zone",
                database=":memory:",
            )

    def test_open_trade_has_no_realized_pnl_or_r(self) -> None:
        self.conn.execute(
            "UPDATE trade_orders SET status = 'filled', closed_at = NULL, close_price = NULL, pnl = NULL, pnl_r = NULL"
        )
        self.conn.commit()

        report = build_zone_trade_report(
            self.conn,
            self.config,
            self.zone_id,
            database=":memory:",
        )

        self.assertEqual(0, report.stats["closed_count"])
        self.assertIsNone(report.stats["total_pnl"])
        self.assertIsNone(report.stats["total_r"])

    def test_mixed_currencies_are_grouped_without_cross_currency_average(self) -> None:
        self.conn.execute(
            "INSERT INTO account_snapshots (account_label, currency, snapshot_at) VALUES ('Test Account', 'USD', '2030-01-01T00:00:00+00:00')"
        )
        self.conn.execute(
            """
            INSERT INTO account_snapshots (account_label, currency, snapshot_at)
            VALUES ('Cent Account', 'USC', '2030-01-01T00:00:00+00:00')
            """
        )
        self.conn.execute(
            """
            INSERT INTO trade_ideas (
                id, symbol, direction, playbook, status, entry_zone_id,
                related_zone_ids_json, context_snapshot_json, suggested_entry,
                suggested_stop_loss, suggested_take_profit_json, risk_reward, created_at
            ) SELECT 'idea-2', symbol, direction, playbook, status, entry_zone_id,
                     related_zone_ids_json, context_snapshot_json, suggested_entry,
                     suggested_stop_loss, suggested_take_profit_json, risk_reward,
                     '2030-01-01T03:00:00+00:00'
            FROM trade_ideas WHERE id = 'idea-1'
            """
        )
        self.conn.execute(
            """
            INSERT INTO trade_orders (
                id, trade_idea_id, account_label, symbol, side, order_type, status,
                entry_price, stop_loss, take_profit_json, quantity, opened_at, closed_at,
                close_price, pnl, pnl_r, source, metadata_json
            ) SELECT 'order-2', 'idea-2', 'Cent Account', symbol, side, order_type, status,
                     entry_price, stop_loss, take_profit_json, quantity,
                     '2030-01-01T03:15:00+00:00', '2030-01-01T04:00:00+00:00',
                     close_price, 2000, 0.5, source, metadata_json
            FROM trade_orders WHERE id = 'order-1'
            """
        )
        self.conn.commit()

        report = build_zone_trade_report(
            self.conn,
            self.config,
            self.zone_id,
            database=":memory:",
        )

        self.assertTrue(report.stats["mixed_currencies"])
        self.assertIsNone(report.stats["total_pnl"])
        self.assertIsNone(report.stats["average_pnl"])
        self.assertEqual({"USC": 2000.0, "USD": 500.0}, report.stats["pnl_by_currency"])


if __name__ == "__main__":
    unittest.main()
