import json
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from dataclasses import replace
from unittest.mock import Mock, patch
from pathlib import Path
from semi_bot_trading.db import connect, init_db
from semi_bot_trading.line_reaction import evaluate_line, price_line, LineConfig, LineCreate
from semi_bot_trading.config import load_config
from semi_bot_trading.trading_sessions import SESSION_NAMES, selected_session_end


class TestLineReaction(unittest.TestCase):
    def setUp(self):
        self.line = {"id":"line1","price":100,"direction":"long","armed_at":"2026-09-06T00:00:00+00:00",
                     "expires_at":"2026-09-07T00:00:00+00:00","config":LineConfig(min_stop_price=0).model_dump()}
        self.candles = [{"time":"2026-09-06T00:00:00+00:00","open":100,"high":102,"low":99,"close":101} for _ in range(20)]
        self.candles.append({"time":"2026-09-06T12:00:00+00:00","open":100,"high":103.5,"low":99,"close":103})
        self.now = datetime(2026,9,6,12,15,tzinfo=timezone.utc)

    def signal(self):
        return evaluate_line(self.line,self.candles,2,5,self.now)

    def test_price_recovery_threshold_and_manual_only_discount(self):
        self.assertEqual("average_body", LineConfig().recovery_mode)
        self.assertEqual(8, LineConfig().recovery_price)
        self.line["config"].update(recovery_mode="price", recovery_price=8)
        for direction in ("long", "short"):
            with self.subTest(direction=direction):
                self.line["direction"] = direction
                candle = self.candles[-1]
                candle.update(open=100, low=99, close=107, high=108) if direction == "long" else candle.update(open=100, high=101, close=93, low=92)
                signal = self.signal()
                self.assertIsNotNone(signal)
                plan = price_line(self.line, signal, candle["close"])
                self.assertEqual("market", plan["metadata"]["order_type"])
                self.line["config"]["limit_offset"] = 1
                plan = price_line(self.line, signal, candle["close"])
                self.assertEqual(0, plan["metadata"]["entry_discount"]["auto_offset"])
                self.assertEqual(1, plan["metadata"]["entry_discount"]["effective_offset"])
                self.line["config"]["limit_offset"] = 0
                self.line["config"]["recovery_price"] = 8.5
                self.assertIsNone(self.signal())
                self.line["config"]["recovery_price"] = 8
                candle.update(high=115) if direction == "long" else candle.update(low=85)
                self.assertIsNone(self.signal())

    def test_price_mode_does_not_require_body_baseline(self):
        self.line["config"].update(recovery_mode="price", recovery_price=4)
        self.assertIsNotNone(evaluate_line(self.line, self.candles[-1:], 2, 5, self.now))
        self.line["config"]["recovery_mode"] = "average_body"
        self.assertIsNone(evaluate_line(self.line, self.candles[-1:], 2, 5, self.now))

    def test_default_stop_floor_applies_after_cap_for_both_sides_and_entry_types(self):
        self.assertEqual(8, LineConfig().min_stop_price)
        for direction in ("long", "short"):
            sign = 1 if direction == "long" else -1
            for offset in (0, 1):
                for natural, cap in ((5, 20), (12, 6), (8, 20), (12, 20)):
                    with self.subTest(direction=direction, offset=offset, natural=natural, cap=cap):
                        self.line.update(direction=direction, config=LineConfig(limit_offset=offset).model_dump())
                        entry = 100 - sign * offset
                        signal = {"reference_price":100, "structural_stop":entry-sign*natural,
                            "max_distance":cap, "recovery_long":2, "recovery_short":2,
                            "signal_close_time":"2026-09-06T12:15:00+00:00"}
                        plan = price_line(self.line, signal, 100)
                        distance = max(8, min(natural, cap))
                        self.assertEqual(entry-sign*distance, plan["stop_loss"])
                        self.assertEqual([entry+sign*distance*2], plan["take_profit"])
                        self.assertEqual(distance, plan["metadata"]["stop_distance_floor"]["after"])

    def test_large_recovery_uses_automatic_limit_and_wick_stop(self):
        signal = self.signal()
        self.assertIsNotNone(signal)
        plan = price_line(self.line,signal,103)
        self.assertEqual("limit",plan["metadata"]["order_type"])
        self.assertEqual(101.8,plan["entry"])
        self.assertAlmostEqual(98.8,plan["stop_loss"])
        self.assertAlmostEqual(107.8,plan["take_profit"][0])
        self.assertEqual("auto_recovery", plan["metadata"]["entry_discount"]["source"])
        self.assertEqual(1.2, plan["metadata"]["entry_discount"]["auto_offset"])

    def test_recovery_below_3x_with_zero_offset_uses_market(self):
        self.candles[-1].update(high=102, close=101.5)
        signal = self.signal()
        self.assertIsNotNone(signal)
        plan = price_line(self.line, signal, 101.5)
        self.assertEqual("market", plan["metadata"]["order_type"])
        self.assertEqual(101.5, plan["entry"])
        self.assertAlmostEqual(98.8, plan["stop_loss"])
        self.assertAlmostEqual(106.9, plan["take_profit"][0])
        self.assertEqual(0, plan["metadata"]["entry_discount"]["effective_offset"])

    def test_positive_manual_offset_forces_limit_below_3x(self):
        self.candles[-1].update(high=102, close=101.5)
        self.line["config"]["limit_offset"] = 1
        plan = price_line(self.line, self.signal(), 101.75)
        self.assertEqual("limit", plan["metadata"]["order_type"])
        self.assertEqual(100.5, plan["entry"])
        self.assertEqual("manual", plan["metadata"]["entry_discount"]["source"])

    def test_auto_limit_geometry_is_stable_across_account_quotes(self):
        signal = self.signal()
        first = price_line(self.line, signal, 103)
        second = price_line(self.line, signal, 104)
        self.assertEqual(first["entry"], second["entry"])
        self.assertEqual(first["stop_loss"], second["stop_loss"])
        self.assertEqual(first["take_profit"], second["take_profit"])

    def test_double_ended_recovery_rejected(self):
        self.candles[-1]["high"] = 105
        self.assertIsNone(self.signal())

    def test_wrong_color_or_no_reclaim_or_no_touch(self):
        for change in ({"open":104},{"close":100},{"low":101}):
            with self.subTest(change=change):
                original = self.candles[-1].copy()
                self.candles[-1].update(change)
                self.assertIsNone(self.signal())
                self.candles[-1] = original

    def test_lookahead_stale_and_prearm(self):
        self.assertIsNone(evaluate_line(self.line,self.candles,2,5,self.now.replace(minute=14)))
        self.assertIsNone(evaluate_line(self.line,self.candles,2,5,self.now.replace(minute=30)))
        for armed_at in ("2026-09-06T12:15:00+00:00", "2026-09-06T12:16:00+00:00"):
            with self.subTest(armed_at=armed_at):
                self.line["armed_at"] = armed_at
                # Still fresh at evaluation, but already closed when armed.
                self.assertIsNone(evaluate_line(
                    self.line, self.candles, 2, 5, self.now.replace(minute=17)
                ))

    def test_candle_forming_at_arm_waits_for_close_and_still_expires(self):
        for direction in ("long", "short"):
            with self.subTest(direction=direction):
                self.line["direction"] = direction
                if direction == "short":
                    self.candles[-1].update(open=100, close=97, low=96.5, high=101)
                self.line["armed_at"] = "2026-09-06T12:14:59.999999+00:00"
                self.assertIsNone(evaluate_line(
                    self.line, self.candles, 2, 5, self.now - timedelta(microseconds=1)
                ))
                self.assertIsNotNone(self.signal())
                self.assertIsNotNone(evaluate_line(
                    self.line, self.candles, 2, 5,
                    self.now + timedelta(minutes=15) - timedelta(microseconds=1)
                ))
                self.assertIsNone(evaluate_line(
                    self.line, self.candles, 2, 5, self.now + timedelta(minutes=15)
                ))

    def test_expired_line_rejects_candle_forming_at_arm(self):
        self.line["armed_at"] = "2026-09-06T12:10:00+00:00"
        self.line["expires_at"] = self.now.isoformat()
        self.assertIsNone(self.signal())

    def test_limit_capped_and_rr_recomputed(self):
        self.line["config"]["limit_offset"] = 5
        self.candles[-1].update(low=80)
        signal = self.signal()
        signal["recovery_long"] = 2
        plan = price_line(self.line,signal,103)
        self.assertEqual("limit",plan["metadata"]["order_type"])
        self.assertEqual(98,plan["entry"])
        self.assertEqual(92,plan["stop_loss"])
        self.assertEqual([110],plan["take_profit"])

    def test_short_symmetry(self):
        self.line.update(direction="short")
        self.candles[-1].update(open=100,close=97,low=96.5,high=101)
        signal = self.signal()
        plan = price_line(self.line,signal,97)
        self.assertEqual(98.2, plan["entry"])
        self.assertAlmostEqual(101.2,plan["stop_loss"])
        self.assertAlmostEqual(92.2,plan["take_profit"][0])
        self.line["config"]["limit_offset"] = 5
        self.candles[-1]["high"] = 120
        plan = price_line(self.line,self.signal(),97)
        self.assertEqual(107.35,plan["entry"])
        self.assertEqual(113.35,plan["stop_loss"])
        self.assertEqual([95.35],plan["take_profit"])

    def test_auto_offset_scales_with_recovery_and_is_capped_at_45_percent(self):
        signal = {
            "reference_price": 100, "structural_stop": 70, "max_distance": 36,
            "atr": 30, "recovery_long_size": 20,
            "signal_close_time": "2026-09-06T12:15:00+00:00",
        }
        offsets = []
        for ratio in (3, 4, 5):
            signal["recovery_long"] = ratio
            plan = price_line(self.line, signal, 105)
            offsets.append(plan["metadata"]["entry_discount"]["auto_offset"])
        self.assertEqual([4, 6, 8], offsets)

        signal.update(atr=0.01, recovery_long=6, recovery_long_size=40)
        capped = price_line(self.line, signal, 105)
        discount = capped["metadata"]["entry_discount"]
        self.assertEqual(18, discount["auto_offset"])
        self.assertEqual(0.45, discount["retracement_fraction"])
        self.assertNotIn("max_m15_atr_fraction", discount)

    def test_real_large_recovery_is_not_capped_by_m15_atr(self):
        self.line.update(direction="short")
        self.line["config"]["limit_offset"] = 7
        signal = {
            "reference_price": 4416.479,
            "structural_stop": 4435.774107142857,
            "max_distance": 20.528485714285775,
            "atr": 7.70107142857153,
            "recovery_short": 5.134636972158016,
            "recovery_short_size": 18.524999999999636,
            "signal_close_time": "2026-09-10T06:15:00+00:00",
        }
        plan = price_line(self.line, signal, 4416.17)
        discount = plan["metadata"]["entry_discount"]
        self.assertEqual("auto_recovery", discount["source"])
        self.assertEqual(7.65941, discount["auto_offset"])
        self.assertEqual(7.65941, discount["effective_offset"])
        self.assertAlmostEqual(4424.13841, plan["entry"])

    def test_manual_offset_is_the_minimum_discount(self):
        self.line["config"]["limit_offset"] = 3
        plan = price_line(self.line, self.signal(), 103)
        discount = plan["metadata"]["entry_discount"]
        self.assertEqual("manual", discount["source"])
        self.assertEqual(3, discount["effective_offset"])
        self.assertEqual(100, plan["entry"])

    def test_discount_rejects_invalid_limit_side_and_structural_stop(self):
        self.line["config"]["limit_offset"] = 1
        with self.assertRaisesRegex(ValueError, "valid side"):
            price_line(self.line, self.signal(), 101)
        self.line["config"]["limit_offset"] = 5
        with self.assertRaisesRegex(ValueError, "reaction wick stop"):
            price_line(self.line, self.signal(), 103)

    def test_wave_insufficient_blocks(self):
        self.line["config"]["target_mode"] = "wave_base"
        with self.assertRaises(ValueError):
            price_line(self.line,self.signal(),103,{})

    def test_wave_target_capped_at_selected_rr(self):
        self.line["config"]["target_mode"] = "wave_base"
        plan = price_line(self.line,self.signal(),103,{"strength":{"up_samples":4,"up_median_price":30}})
        self.assertAlmostEqual(2,plan["risk_reward"])

    def test_missing_baseline_and_atr(self):
        self.assertIsNone(evaluate_line(self.line,self.candles[-20:],2,5,self.now))
        self.assertIsNone(evaluate_line(self.line,self.candles,0,5,self.now))

    def test_unique_account_claim(self):
        with TemporaryDirectory() as tmp:
            conn = connect(Path(tmp)/"test.db");init_db(conn)
            for i,account in (("a","Fund"),("b","Fund"),("c","Personal")):
                conn.execute("""INSERT INTO line_reaction_plans
                    (id,symbol,account_label,direction,price,config_json,expires_at,created_at,updated_at)
                    VALUES (?,'XAUUSD',?,'long',100,'{}','later','now','now')""",(i,account))
            conn.execute("UPDATE line_reaction_plans SET status='pending' WHERE id='a'")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE line_reaction_plans SET status='executing' WHERE id='b'")
            conn.execute("UPDATE line_reaction_plans SET status='open' WHERE id='c'")
            conn.close()

    def test_validation(self):
        self.assertEqual(1.5, LineConfig(risk_reward=1.5).risk_reward)
        self.assertEqual(3, LineConfig(risk_reward=3).risk_reward)
        self.assertEqual(1.2, LineConfig(recovery_ratio=1.2).recovery_ratio)
        self.assertEqual(0, LineConfig().limit_offset)
        self.assertEqual(0, LineConfig(partial_fraction=0).partial_fraction)
        self.assertEqual(["asian", "london", "london_ny", "new_york", "off_hours"], LineConfig().trade_sessions)
        self.assertEqual(["london", "new_york"], LineConfig(trade_sessions=["london", "new_york", "london"]).trade_sessions)
        for change in ({"recovery_ratio":0.9},{"max_stop_h1_atr":2},{"limit_offset":-0.01},{"limit_offset":float("nan")}):
            with self.assertRaises(ValueError):
                LineConfig(**change)
        with self.assertRaises(ValueError):
            LineConfig(risk_reward=1.75)
        with self.assertRaises(ValueError):
            LineConfig(trade_sessions=["unknown"])
        with self.assertRaises(ValueError):
            LineConfig(partial_fraction=-0.01)

    def test_adjacent_selected_sessions_form_one_continuous_window(self):
        self.assertEqual(datetime.max.replace(tzinfo=timezone.utc), selected_session_end(
            list(SESSION_NAMES), "2026-09-06T11:59:00+00:00"
        ))
        self.assertEqual(
            datetime(2026, 9, 6, 17, 0, tzinfo=timezone.utc),
            selected_session_end(["london", "london_ny"], "2026-09-06T11:59:00+00:00"),
        )
        self.assertEqual(
            datetime(2026, 9, 7, 7, 0, tzinfo=timezone.utc),
            selected_session_end(["off_hours", "asian"], "2026-09-06T23:59:00+00:00"),
        )

class TestLineIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name)/"test.db"
        self.conn = connect(self.path); init_db(self.conn)
        self.config = replace(load_config(),database=self.path)
        self.conn.execute("INSERT INTO account_execution_controls(account_label,requested_enabled,effective_enabled,hard_enabled,updated_at) VALUES ('Test',1,1,1,'now')")
        self.conn.execute("INSERT INTO account_execution_controls(account_label,requested_enabled,effective_enabled,hard_enabled,updated_at) VALUES ('Second',1,1,1,'now')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close(); self.tmp.cleanup()

    def test_api_draft_arm_cancel_and_validation(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from semi_bot_trading.line_reaction_api import register_line_routes
        app = FastAPI(); register_line_routes(app,self.config,lambda: "test")
        client = TestClient(app)
        body = {"account_labels":["Test", "Second"],"direction":"long","price":3000}
        created = client.post("/api/line-reactions",json=body)
        self.assertEqual(200,created.status_code)
        plan = created.json()
        self.assertEqual("draft",plan["status"])
        self.assertEqual(["Second", "Test"], plan["account_labels"])
        self.assertEqual(2, self.conn.execute("SELECT COUNT(*) FROM line_reaction_plans").fetchone()[0])
        self.assertIsNone(plan["armed_at"])
        now = datetime.now(timezone.utc)
        visual_start = (now + timedelta(hours=1)).isoformat()
        visual_end = (now + timedelta(hours=5)).isoformat()
        edited = client.patch("/api/line-reactions/"+plan["id"],json={**body,
            "visual_start":visual_start,"visual_end":visual_end,
            "config":{"risk_reward":2.5}})
        self.assertEqual(200,edited.status_code)
        self.assertEqual(2.5,edited.json()["config"]["risk_reward"])
        self.assertEqual(visual_start,edited.json()["visual_start"])
        self.assertEqual(datetime.fromisoformat(visual_end), datetime.fromisoformat(edited.json()["expires_at"]))
        self.assertEqual(422, client.patch("/api/line-reactions/"+plan["id"], json={**body,
            "direction":"short", "visual_start":visual_start, "visual_end":visual_end}).status_code)
        armed = client.post("/api/line-reactions/"+plan["id"]+"/arm",json={})
        self.assertEqual("armed",armed.json()["status"])
        self.assertEqual(2, self.conn.execute("SELECT COUNT(*) FROM line_reaction_plans WHERE status='armed'").fetchone()[0])
        self.assertIsNotNone(armed.json()["armed_at"])
        armed_edit = client.patch("/api/line-reactions/"+plan["id"], json={**body,
            "visual_start":visual_start, "visual_end":visual_end,
            "expires_in_minutes":180, "config":{"recovery_ratio":3}})
        self.assertEqual(200, armed_edit.status_code)
        self.assertEqual("armed", armed_edit.json()["status"])
        self.assertEqual(3, armed_edit.json()["config"]["recovery_ratio"])
        self.assertEqual(armed.json()["armed_at"], armed_edit.json()["armed_at"])
        repriced = client.patch("/api/line-reactions/"+plan["id"], json={**body,
            "price":3000.5, "visual_start":visual_start, "visual_end":visual_end})
        self.assertEqual(200, repriced.status_code)
        self.assertGreater(repriced.json()["armed_at"], armed.json()["armed_at"])
        rows = self.conn.execute("SELECT price,armed_at,signal_json FROM line_reaction_plans").fetchall()
        self.assertEqual({3000.5}, {row["price"] for row in rows})
        self.assertEqual({repriced.json()["armed_at"]}, {row["armed_at"] for row in rows})
        self.assertTrue(all(row["signal_json"] is None for row in rows))
        from semi_bot_trading.line_reaction_worker import _claim_line_signal
        member_id = self.conn.execute("SELECT id FROM line_reaction_plans LIMIT 1").fetchone()[0]
        self.assertFalse(_claim_line_signal(self.conn, member_id, {}, now,
            expected_updated_at=armed_edit.json()["updated_at"]))
        self.assertEqual(409,client.post("/api/line-reactions/"+plan["id"]+"/arm",json={}).status_code)
        self.assertEqual("cancelled",client.post("/api/line-reactions/"+plan["id"]+"/cancel",json={}).json()["status"])
        self.assertEqual(2, self.conn.execute("SELECT COUNT(*) FROM line_reaction_plans WHERE status='cancelled'").fetchone()[0])
        self.assertEqual(422,client.post("/api/line-reactions",json={**body,"account_labels":["Other"]}).status_code)
        self.assertEqual(422,client.post("/api/line-reactions",json={**body,"config":{"max_stop_h1_atr":3}}).status_code)

    def test_create_is_idempotent_and_account_removal_keeps_audit_row(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from semi_bot_trading.line_reaction_api import register_line_routes
        app = FastAPI(); register_line_routes(app,self.config,lambda: "test")
        client = TestClient(app)
        body = {"client_request_id":"request-1234","account_labels":["Test", "Second"],"direction":"long","price":3000}
        first = client.post("/api/line-reactions",json=body)
        second = client.post("/api/line-reactions",json=body)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(2, self.conn.execute("SELECT COUNT(*) FROM line_reaction_plans").fetchone()[0])

        edited = client.patch("/api/line-reactions/"+first.json()["id"], json={**body,"account_labels":["Test"]})
        self.assertEqual(["Test"], edited.json()["account_labels"])
        removed = self.conn.execute(
            "SELECT status,removed_at FROM line_reaction_plans WHERE account_label='Second'"
        ).fetchone()
        self.assertEqual("cancelled", removed["status"])
        self.assertIsNotNone(removed["removed_at"])
        self.assertEqual("armed", client.post("/api/line-reactions/"+first.json()["id"]+"/arm", json={}).json()["status"])
        self.assertEqual(
            "cancelled",
            self.conn.execute("SELECT status FROM line_reaction_plans WHERE account_label='Second'").fetchone()[0],
        )

    def test_list_returns_twenty_newest_groups_without_truncating_accounts(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from semi_bot_trading.line_reaction_api import register_line_routes

        now = datetime.now(timezone.utc)
        config_json = LineConfig().model_dump_json()
        for index in range(21):
            group_id = f"group-{index:02d}"
            created_at = (now + timedelta(minutes=index)).isoformat()
            accounts = ("Test", "Second") if index == 20 else ("Test",)
            for account in accounts:
                self.conn.execute(
                    """INSERT INTO line_reaction_plans
                    (id,client_group_id,symbol,account_label,direction,price,status,config_json,
                     expires_at,created_at,updated_at)
                    VALUES (?,?,'XAUUSD',?,'long',?,'draft',?,?,?,?)""",
                    (f"{group_id}-{account}", group_id, account, 3000 + index, config_json,
                     (now + timedelta(days=2)).isoformat(), created_at, created_at),
                )
        self.conn.commit()
        app = FastAPI(); register_line_routes(app, self.config, lambda: "test")

        plans = TestClient(app).get("/api/line-reactions").json()["plans"]

        self.assertEqual(20, len(plans))
        self.assertEqual("group-20", plans[0]["id"])
        self.assertEqual(["Second", "Test"], plans[0]["account_labels"])
        self.assertNotIn("group-00", {plan["id"] for plan in plans})

    def test_list_keeps_non_terminal_group_ahead_of_newer_history(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from semi_bot_trading.line_reaction_api import register_line_routes

        now = datetime.now(timezone.utc)
        for index in range(21):
            status = "armed" if index == 0 else "closed"
            created_at = (now + timedelta(minutes=index)).isoformat()
            self.conn.execute(
                """INSERT INTO line_reaction_plans
                (id,client_group_id,symbol,account_label,direction,price,status,config_json,
                 expires_at,created_at,updated_at)
                VALUES (?,?, 'XAUUSD','Test','long',?,?,?, ?,?,?)""",
                (f"priority-{index:02d}", f"priority-{index:02d}", 3000 + index, status,
                 LineConfig().model_dump_json(), (now + timedelta(days=2)).isoformat(),
                 created_at, created_at),
            )
        self.conn.commit()
        app = FastAPI(); register_line_routes(app, self.config, lambda: "test")

        plans = TestClient(app).get("/api/line-reactions").json()["plans"]

        self.assertEqual(20, len(plans))
        self.assertEqual("priority-00", plans[0]["id"])
        self.assertNotIn("priority-01", {plan["id"] for plan in plans})

    def _seed_triggered(self, identifier="test-line"):
        now = datetime.now(timezone.utc)
        from datetime import timedelta
        signal = {"signal_time": (now-timedelta(minutes=16)).isoformat(),
                  "signal_close_time": (now-timedelta(minutes=1)).isoformat(),
                  "reference_price":3000, "structural_stop":2995,
                  "max_distance":10, "atr":5,"h1_atr":10}
        self.conn.execute("""INSERT INTO line_reaction_plans
            (id,symbol,account_label,direction,price,status,config_json,armed_at,expires_at,created_at,updated_at,signal_json)
            VALUES (?,'XAUUSD','Test','long',2998,'executing',?,?,?,?,?,?)""",
            (identifier,LineConfig().model_dump_json(),(now-timedelta(hours=1)).isoformat(),
             (now+timedelta(hours=1)).isoformat(),now.isoformat(),now.isoformat(),json.dumps(signal)))
        self.conn.commit()
        return now

    def test_worker_market_once_applies_stop_floor_and_recomputes_tp(self):
        from semi_bot_trading.line_reaction_worker import process_line_reactions
        from tests.test_live_worker import _make_env,_fake_client,_fake_risk_manager
        now = self._seed_triggered()
        broker = _fake_client(current_price=3000)
        with patch("semi_bot_trading.live_worker.build_risk_manager",return_value=_fake_risk_manager()), patch(
            "semi_bot_trading.live_worker.is_weekend_no_new_trade_window",return_value=False
        ):
            process_line_reactions(self.conn,self.config,_make_env(),broker,"XAUUSDm",now)
            process_line_reactions(self.conn,self.config,_make_env(),broker,"XAUUSDm",now)
        broker.place_market_order.assert_called_once()
        order = self.conn.execute("SELECT * FROM trade_orders").fetchone()
        self.assertIsNotNone(order)
        self.assertEqual(2992,order["stop_loss"])
        self.assertEqual([3016], json.loads(order["take_profit_json"]))
        self.assertFalse(json.loads(order["metadata_json"])["partial_take_profit"]["enabled"])
        self.assertEqual("open",self.conn.execute("SELECT status FROM line_reaction_plans").fetchone()["status"])

    def test_signal_claim_reserves_the_same_group_for_every_account(self):
        from semi_bot_trading.line_reaction_worker import _claim_line_signal

        now = datetime.now(timezone.utc)
        config_json = LineConfig(risk_reward=3).model_dump_json()
        signal = {
            "signal_time": (now - timedelta(minutes=15)).isoformat(),
            "signal_close_time": now.isoformat(),
            "reference_price": 3000,
            "structural_stop": 2995,
            "max_distance": 10,
            "atr": 5,
            "h1_atr": 10,
        }
        for account in ("Test", "Second"):
            self.conn.execute(
                """INSERT INTO line_reaction_plans
                (id,client_group_id,symbol,account_label,direction,price,status,config_json,
                 armed_at,expires_at,created_at,updated_at)
                VALUES (?, 'shared-3r','XAUUSD',?,'long',2998,'armed',?,?,?,?,?)""",
                (
                    f"shared-3r-{account}", account, config_json,
                    (now - timedelta(hours=1)).isoformat(),
                    (now + timedelta(hours=1)).isoformat(), now.isoformat(), now.isoformat(),
                ),
            )
        self.conn.commit()

        self.assertTrue(_claim_line_signal(self.conn, "shared-3r-Test", signal, now))
        rows = self.conn.execute(
            "SELECT status,config_json,signal_json FROM line_reaction_plans WHERE client_group_id='shared-3r'"
        ).fetchall()
        self.assertEqual(2, len(rows))
        self.assertEqual({"executing"}, {row["status"] for row in rows})
        self.assertEqual({3.0}, {json.loads(row["config_json"])["risk_reward"] for row in rows})
        self.assertEqual(
            {signal["signal_close_time"]},
            {json.loads(row["signal_json"])["signal_close_time"] for row in rows},
        )

    def test_signal_claim_blocks_the_whole_group_when_one_account_is_busy(self):
        from semi_bot_trading.line_reaction_worker import _claim_line_signal

        now = datetime.now(timezone.utc)
        signal = {"signal_close_time": now.isoformat()}
        self.conn.execute(
            """INSERT INTO line_reaction_plans
            (id,client_group_id,symbol,account_label,direction,price,status,config_json,
             armed_at,expires_at,created_at,updated_at)
            VALUES ('active','active-group','XAUUSD','Test','long',2998,'open',?,?,?,?,?)""",
            (
                LineConfig().model_dump_json(), (now - timedelta(hours=1)).isoformat(),
                (now + timedelta(hours=1)).isoformat(), now.isoformat(), now.isoformat(),
            ),
        )
        for account in ("Test", "Second"):
            self.conn.execute(
                """INSERT INTO line_reaction_plans
                (id,client_group_id,symbol,account_label,direction,price,status,config_json,
                 armed_at,expires_at,created_at,updated_at)
                VALUES (?, 'waiting-group','XAUUSD',?,'long',2998,'armed',?,?,?,?,?)""",
                (
                    f"waiting-{account}", account, LineConfig(risk_reward=3).model_dump_json(),
                    (now - timedelta(hours=1)).isoformat(), (now + timedelta(hours=1)).isoformat(),
                    now.isoformat(), now.isoformat(),
                ),
            )
        self.conn.commit()

        self.assertFalse(_claim_line_signal(self.conn, "waiting-Test", signal, now))
        self.assertEqual(
            {"armed"},
            {row[0] for row in self.conn.execute(
                "SELECT status FROM line_reaction_plans WHERE client_group_id='waiting-group'"
            )},
        )

    def test_worker_high_spread_does_not_send(self):
        from semi_bot_trading.line_reaction_worker import process_line_reactions
        from tests.test_live_worker import _make_env,_fake_client
        now = self._seed_triggered()
        broker = _fake_client(current_price=3000,spread=3)
        with patch("semi_bot_trading.live_worker.is_weekend_no_new_trade_window",return_value=False):
            process_line_reactions(self.conn,self.config,_make_env(),broker,"XAUUSDm",now)
        broker.place_market_order.assert_not_called()
        self.assertEqual(0,self.conn.execute("SELECT COUNT(*) FROM execution_requests").fetchone()[0])

    def test_worker_clears_unexecuted_signal_outside_selected_sessions(self):
        from semi_bot_trading.line_reaction_worker import process_line_reactions
        from semi_bot_trading.live_worker import trading_session
        from tests.test_live_worker import _make_env, _fake_client
        now = self._seed_triggered()
        names = {"Asian":"asian", "London":"london", "London-NY":"london_ny", "New York":"new_york", "Off-hours":"off_hours"}
        active = names[trading_session(now.isoformat())]
        blocked = next(name for name in names.values() if name != active)
        self.conn.execute("UPDATE line_reaction_plans SET config_json=?", (LineConfig(trade_sessions=[blocked]).model_dump_json(),))
        self.conn.commit()
        broker = _fake_client(current_price=3000)
        process_line_reactions(self.conn,self.config,_make_env(),broker,"XAUUSDm",now)
        row = self.conn.execute("SELECT status,signal_json FROM line_reaction_plans").fetchone()
        self.assertEqual("armed", row["status"])
        self.assertIsNone(row["signal_json"])
        broker.place_market_order.assert_not_called()

    def test_limit_expiry_never_cancels_filled_or_unknown_position(self):
        from datetime import timedelta
        from semi_bot_trading.line_reaction_worker import process_line_reactions
        from tests.test_live_worker import _make_env,_fake_client,_fake_risk_manager
        now = self._seed_triggered()
        signal = json.loads(self.conn.execute("SELECT signal_json FROM line_reaction_plans").fetchone()[0])
        signal["structural_stop"] = 2950
        config_json = LineConfig(limit_offset=5).model_dump_json()
        self.conn.execute(
            "UPDATE line_reaction_plans SET signal_json=?,config_json=?",
            (json.dumps(signal), config_json),
        )
        self.conn.commit()
        broker = _fake_client(current_price=3000)
        with patch("semi_bot_trading.live_worker.build_risk_manager",return_value=_fake_risk_manager()), patch(
            "semi_bot_trading.live_worker.is_weekend_no_new_trade_window",return_value=False
        ):
            process_line_reactions(self.conn,self.config,_make_env(),broker,"XAUUSDm",now)
        broker.place_limit_order.assert_called_once()
        late = now+timedelta(hours=3)
        for state in (None,"filled"):
            broker.get_pending_order_state.return_value = state
            process_line_reactions(self.conn,self.config,_make_env(),broker,"XAUUSDm",late)
            broker.cancel_pending_order.assert_not_called()
        broker.get_pending_order_state.return_value = "pending"
        process_line_reactions(self.conn,self.config,_make_env(),broker,"XAUUSDm",late)
        broker.cancel_pending_order.assert_called_once()
        self.assertEqual("expired",self.conn.execute("SELECT status FROM line_reaction_plans").fetchone()[0])

    def test_line_intent_reservation_required_for_direct_execution(self):
        from semi_bot_trading.live_worker import execute_candidate, build_execution_pricing_plan
        from tests.test_live_worker import _make_env, _fake_client
        from semi_bot_trading.line_reaction_api import row_api
        self._seed_triggered()
        line = row_api(self.conn.execute("SELECT * FROM line_reaction_plans").fetchone())
        levels = price_line(line,line["signal"],3000)
        candidate = {"id":line["id"],"direction":"long","playbook":"line_reaction_v1",**levels}
        broker = _fake_client(current_price=3000)
        pricing = build_execution_pricing_plan(broker,"XAUUSDm",candidate,2)
        self.conn.execute("UPDATE line_reaction_plans SET status='cancel_requested'")
        self.conn.commit()
        execute_candidate(self.conn,self.config,_make_env(),broker,candidate,"XAUUSDm",pricing_plan=pricing)
        broker.place_market_order.assert_not_called()

    def test_execution_rechecks_selected_session_before_mt5(self):
        from semi_bot_trading.live_worker import execute_candidate, build_execution_pricing_plan
        from tests.test_live_worker import _make_env, _fake_client
        from semi_bot_trading.line_reaction_api import row_api
        self._seed_triggered()
        line = row_api(self.conn.execute("SELECT * FROM line_reaction_plans").fetchone())
        levels = price_line(line,line["signal"],3000)
        candidate = {"id":line["id"],"direction":"long","playbook":"line_reaction_v1",**levels}
        broker = _fake_client(current_price=3000)
        pricing = build_execution_pricing_plan(broker,"XAUUSDm",candidate,2)
        with patch("semi_bot_trading.live_worker.selected_session_end", side_effect=[datetime.now(timezone.utc)+timedelta(hours=1), None]):
            execute_candidate(self.conn,self.config,_make_env(),broker,candidate,"XAUUSDm",lot_size=0.1,pricing_plan=pricing)
        broker.place_market_order.assert_not_called()
        self.assertEqual("cancelled", self.conn.execute("SELECT status FROM execution_requests").fetchone()[0])
        row = self.conn.execute("SELECT status,signal_json FROM line_reaction_plans").fetchone()
        self.assertEqual("armed", row["status"])
        self.assertIsNone(row["signal_json"])

        from semi_bot_trading.line_reaction_worker import process_line_reactions
        process_line_reactions(
            self.conn, self.config, _make_env(), broker, "XAUUSDm", datetime.now(timezone.utc)
        )
        self.assertEqual(
            "armed", self.conn.execute("SELECT status FROM line_reaction_plans").fetchone()[0]
        )

    def _seed_stale_pending_intent(self):
        from semi_bot_trading.live_worker import live_trade_idea_id

        now = self._seed_triggered()
        idea_id = live_trade_idea_id("test-line", account_label="Test")
        grace = timedelta(minutes=self.config.strategy.line_reaction_v1_pending_intent_grace_minutes)
        created_at = (now - grace - timedelta(seconds=1)).isoformat()
        self.conn.execute(
            """INSERT INTO trade_ideas
            (id,symbol,direction,playbook,status,related_zone_ids_json,context_snapshot_json,
             suggested_entry,suggested_stop_loss,suggested_take_profit_json,risk_reward,
             created_at,expires_at)
            VALUES (?,'XAUUSD','long','line_reaction_v1','approved','[]','{}',3000,2995,
                    '[3010]',2,?,?)""",
            (idea_id, created_at, (now + timedelta(hours=1)).isoformat()),
        )
        self.conn.execute(
            """INSERT INTO execution_requests
            (id,trade_idea_id,account_label,symbol,broker_symbol,side,order_type,quantity,
             entry_price,stop_loss,take_profit_json,risk_snapshot_json,context_snapshot_json,
             requested_by,status,created_at,updated_at)
            VALUES ('stale-request',?,'Test','XAUUSD','XAUUSDm','buy','market',0.1,3000,
                    2995,'[3010]','{}','{}','strategy','pending',?,?)""",
            (idea_id, created_at, created_at),
        )
        self.conn.commit()
        return now

    def test_stale_pending_intent_fails_without_retry_when_broker_has_no_exposure(self):
        from tests.test_live_worker import _fake_client, _make_env
        from semi_bot_trading.line_reaction_worker import process_line_reactions

        now = self._seed_stale_pending_intent()
        broker = _fake_client()
        broker.bot_order_counts.return_value = (0, 0)

        process_line_reactions(
            self.conn, self.config, replace(_make_env(), execution_enabled=False),
            broker, "XAUUSDm", now,
        )

        request = self.conn.execute(
            "SELECT status,failure_reason FROM execution_requests WHERE id='stale-request'"
        ).fetchone()
        self.assertEqual("failed", request["status"])
        self.assertIn("no active bot", request["failure_reason"])
        line = self.conn.execute(
            "SELECT status,last_error FROM line_reaction_plans WHERE id='test-line'"
        ).fetchone()
        self.assertEqual("failed", line["status"])
        broker.place_market_order.assert_not_called()
        self.conn.execute(
            """INSERT INTO line_reaction_plans
            (id,symbol,account_label,direction,price,status,config_json,expires_at,created_at,updated_at)
            VALUES ('released','XAUUSD','Test','long',3010,'executing',?,?,?,?)""",
            (LineConfig().model_dump_json(), (now + timedelta(hours=1)).isoformat(),
             now.isoformat(), now.isoformat()),
        )
        self.conn.rollback()

    def test_stale_pending_intent_requires_reconciliation_when_broker_has_exposure(self):
        from tests.test_live_worker import _fake_client, _make_env
        from semi_bot_trading.line_reaction_worker import process_line_reactions

        now = self._seed_stale_pending_intent()
        broker = _fake_client()
        broker.bot_order_counts.return_value = (1, 0)

        process_line_reactions(
            self.conn, self.config, _make_env(), broker, "XAUUSDm", now,
        )

        request = self.conn.execute(
            "SELECT status,failure_reason FROM execution_requests WHERE id='stale-request'"
        ).fetchone()
        self.assertEqual("reconciliation_required", request["status"])
        self.assertIn("Check MT5", request["failure_reason"])
        line = self.conn.execute(
            "SELECT status,last_error FROM line_reaction_plans WHERE id='test-line'"
        ).fetchone()
        self.assertEqual("reconciliation_required", line["status"])
        self.assertIn("Check MT5", line["last_error"])
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """INSERT INTO line_reaction_plans
                (id,symbol,account_label,direction,price,status,config_json,expires_at,created_at,updated_at)
                VALUES ('blocked','XAUUSD','Test','long',3010,'executing',?,?,?,?)""",
                (LineConfig().model_dump_json(), (now + timedelta(hours=1)).isoformat(),
                 now.isoformat(), now.isoformat()),
            )
        self.conn.rollback()

        broker.bot_order_counts.return_value = (0, 0)
        process_line_reactions(
            self.conn, self.config, _make_env(), broker, "XAUUSDm", now + timedelta(minutes=1),
        )
        self.assertEqual(
            "failed", self.conn.execute(
                "SELECT status FROM line_reaction_plans WHERE id='test-line'"
            ).fetchone()[0],
        )

    def test_line_transition_rejects_unexpected_source_status(self):
        from semi_bot_trading.line_reaction_worker import transition_line
        now = datetime.now(timezone.utc)
        self.conn.execute(
            """INSERT INTO line_reaction_plans
            (id,symbol,account_label,direction,price,status,config_json,expires_at,created_at,updated_at)
            VALUES ('guarded','XAUUSD','Test','long',3000,'draft',?,?,?,?)""",
            (LineConfig().model_dump_json(), (now+timedelta(hours=1)).isoformat(), now.isoformat(), now.isoformat()),
        )
        self.conn.commit()
        self.assertFalse(transition_line(self.conn, "guarded", {"armed"}, "executing", now))
        self.assertEqual("draft", self.conn.execute(
            "SELECT status FROM line_reaction_plans WHERE id='guarded'"
        ).fetchone()[0])
        self.assertTrue(transition_line(self.conn, "guarded", {"draft"}, "armed", now))

    def test_full_app_routes_precede_spa_and_api_misses_are_json(self):
        from tests.test_api import authenticated_test_client, write_test_config
        root = Path(self.tmp.name)
        config_path = root / 'api.toml'
        write_test_config(config_path, self.path)
        # Force registration of SPA fallback even in a clean checkout without dist.
        original_exists = Path.exists
        def exists(path):
            if path.name == 'dist' and path.parent.name == 'frontend':
                return True
            return original_exists(path)
        with patch.object(Path, 'exists', exists):
            client = authenticated_test_client(root, config_path)
        try:
            response = client.get('/api/line-reactions')
            self.assertEqual(200, response.status_code)
            self.assertEqual([], response.json()["plans"])
            self.assertEqual(list(SESSION_NAMES), [item["value"] for item in response.json()["sessions"]])
            missing = client.get('/api/nonexistent-line-route')
            self.assertEqual(404, missing.status_code)
            self.assertEqual('API route not found', missing.json()['detail'])
            client.headers.pop('Authorization', None)
            self.assertIn(client.get('/api/line-reactions').status_code, (401, 403))
        finally:
            client.close()
            client._semi_bot_env_patch.stop()
