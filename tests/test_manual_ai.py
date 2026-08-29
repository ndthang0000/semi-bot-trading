from __future__ import annotations

import copy
import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from semi_bot_trading.db import connect, init_db
from tests.helpers import TemporaryDirectory
from tests.test_api import authenticated_test_client, seed_candles, write_test_config


def envelope(*, rr: float = 2.0, execution_state: str = "primary", client_id: str = "manual-ai-test-1", expires_in_minutes: int = 120) -> dict:
    now = datetime.now(UTC)
    return {
        "schema_version": 1,
        "as_of": now.isoformat(),
        "symbol": "XAUUSD",
        "playbook": "manual_ai_v1",
        "analysis_timeframes": {"context": "H1", "structure": "M15", "execution": "M5"},
        "market_context": {"h1_bias": "bullish"},
        "candidates": [
            {
                "client_id": client_id,
                "priority": 1,
                "execution_state": execution_state,
                "side": "buy",
                "order_type": "limit",
                "entry_price": 2000,
                "stop_loss": 1990,
                "take_profit": 2000 + 10 * rr,
                "risk_pct": 1.0,
                "risk_reward": rr,
                "expires_in_minutes": expires_in_minutes,
                "partial_take_profit": {
                    "enabled": True,
                    "trigger_r": 1.0,
                    "close_fraction": 0.5,
                    "move_stop_to": "breakeven",
                    "breakeven_buffer": 0,
                },
                "cancel_conditions": [
                    {"type": "m5_close_below", "price": 1990},
                    {"type": "price_reached_target_without_fill"},
                ],
                "entry_reason": "M5 pullback",
                "stop_reason": "Structural invalidation",
                "target_reason": "M15 liquidity",
                "confidence": 0.75,
            }
        ],
    }


def seed_recent_h1_signal(db_path: Path) -> str:
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    signal_open = now - timedelta(hours=2)
    signal_close = signal_open + timedelta(hours=1)
    m5_open = signal_close
    with connect(db_path) as conn:
        init_db(conn)
        conn.execute(
            """
            INSERT INTO candles (id, symbol, timeframe, open_time, close_time, open, high, low, close, volume, source)
            VALUES ('recent-h1-signal', 'XAUUSD', 'H1', ?, ?, 2010, 2025, 2005, 2020, 100, 'test')
            """,
            (signal_open.isoformat(), signal_close.isoformat()),
        )
        conn.execute(
            """
            INSERT INTO candles (id, symbol, timeframe, open_time, close_time, open, high, low, close, volume, source)
            VALUES ('recent-m5-after-signal', 'XAUUSD', 'M5', ?, ?, 2015, 2018, 2005, 2012, 100, 'test')
            """,
            (m5_open.isoformat(), (m5_open + timedelta(minutes=5)).isoformat()),
        )
        conn.commit()
    return signal_open.isoformat()


def prepare_h1_payload(payload: dict, db_path: Path) -> None:
    payload["playbook"] = "h1_impulse_retest_v1"
    payload["market_context"]["atr"] = 20
    payload["market_context"]["signal_candle_time"] = seed_recent_h1_signal(db_path)


class ManualAiApiTest(unittest.TestCase):
    def test_partial_take_profit_defaults_to_1_25r_half_and_breakeven(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            client = authenticated_test_client(root, config_path)
            payload = copy.deepcopy(envelope(client_id="partial-default-test"))
            del payload["candidates"][0]["partial_take_profit"]

            response = client.post("/api/manual-ai/plans", json=payload)

            self.assertEqual(200, response.status_code, response.text)
            partial = response.json()["plans"][0]["partial_take_profit"]
            self.assertEqual(
                {
                    "enabled": True,
                    "trigger_r": 1.25,
                    "close_fraction": 0.5,
                    "move_stop_to": "breakeven",
                    "breakeven_buffer": 0.0,
                },
                partial,
            )

    def test_h1_impulse_plan_preserves_playbook_entry_source_and_expiry(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            client = authenticated_test_client(root, config_path)
            payload = copy.deepcopy(envelope(client_id="h1-impulse-test", expires_in_minutes=720))
            prepare_h1_payload(payload, db_path)
            payload["candidates"][0]["original_status"] = "eligible"
            payload["candidates"][0]["entry_source"] = "fib_0.5"
            payload["candidates"][0]["entry_options"] = [
                {"source": "fib_0.5", "label": "Fib 0.5", "price": 2000.0}
            ]
            payload["market_context"]["target_mode"] = "wave_safe"
            payload["market_context"]["target_plan"] = {
                "options": [
                    {"mode": "wave_safe", "reward_distance": 12.5},
                    {"mode": "wave_base", "reward_distance": 30.0},
                ]
            }

            created = client.post("/api/manual-ai/plans", json=payload)

            self.assertEqual(200, created.status_code, created.text)
            plan = created.json()["plans"][0]
            self.assertEqual("h1_impulse_retest_v1", plan["playbook"])
            self.assertEqual("fib_0.5", plan["entry_source"])
            self.assertEqual(720, plan["expires_in_minutes"])
            chart = client.get(
                "/api/chart?symbol=XAUUSD&timeframe=H1&limit=20&playbooks=h1_impulse_retest_v1"
            )
            setup = chart.json()["layers"]["setup_candidates"][0]
            self.assertTrue(setup["metadata"]["execution_plan"])
            self.assertEqual("fib_0.5", setup["metadata"]["entry_source"])
            self.assertEqual(payload["candidates"][0]["entry_options"], setup["metadata"]["entry_options"])

            expiry_update = client.patch(
                f"/api/manual-ai/plans/{plan['id']}/expiry",
                json={"expires_in_minutes": 18 * 60},
            )
            self.assertEqual(200, expiry_update.status_code, expiry_update.text)
            self.assertFalse(expiry_update.json()["requires_broker_replace"])
            self.assertEqual(18 * 60, expiry_update.json()["plans"][0]["expires_in_minutes"])

            edited = client.patch(
                f"/api/manual-ai/plans/{plan['id']}/levels",
                json={
                    "entry_price": 2001,
                    "stop_loss": 1991,
                    "take_profit": 2031,
                    "entry_source": "previous_h1_high",
                    "target_mode": "wave_base",
                },
            )
            self.assertEqual(200, edited.status_code, edited.text)
            self.assertEqual("previous_h1_high", edited.json()["plans"][0]["entry_source"])
            refreshed_chart = client.get(
                "/api/chart?symbol=XAUUSD&timeframe=H1&limit=20&playbooks=h1_impulse_retest_v1"
            )
            refreshed_setup = refreshed_chart.json()["layers"]["setup_candidates"][0]
            self.assertEqual("wave_base", refreshed_setup["metadata"]["target_mode"])
            self.assertEqual(30.0, refreshed_setup["metadata"]["target_reward_distance"])

            safe_target = client.patch(
                f"/api/manual-ai/plans/{plan['id']}/levels",
                json={
                    "entry_price": 2001,
                    "stop_loss": 1991,
                    "take_profit": 2013.5,
                    "entry_source": "previous_h1_high",
                    "target_mode": "wave_safe",
                },
            )
            self.assertEqual(200, safe_target.status_code, safe_target.text)
            self.assertFalse(safe_target.json()["plans"][0]["partial_take_profit"]["enabled"])

            accepted_rr = client.patch(
                f"/api/manual-ai/plans/{plan['id']}/levels",
                json={"entry_price": 2001, "stop_loss": 1991, "take_profit": 2041, "entry_source": "human_custom"},
            )
            self.assertEqual(200, accepted_rr.status_code, accepted_rr.text)
            self.assertTrue(accepted_rr.json()["plans"][0]["partial_take_profit"]["enabled"])

            rejected_rr = client.patch(
                f"/api/manual-ai/plans/{plan['id']}/levels",
                json={"entry_price": 2001, "stop_loss": 1991, "take_profit": 2042, "entry_source": "human_custom"},
            )
            self.assertEqual(422, rejected_rr.status_code)

    def test_h1_armed_expiry_edit_requests_safe_broker_replace(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            client = authenticated_test_client(root, config_path)
            payload = copy.deepcopy(envelope(client_id="h1-armed-expiry", expires_in_minutes=360))
            prepare_h1_payload(payload, db_path)
            payload["candidates"][0]["original_status"] = "eligible"
            created = client.post("/api/manual-ai/plans", json=payload)
            self.assertEqual(200, created.status_code, created.text)
            plan_id = created.json()["plans"][0]["id"]
            with connect(db_path) as conn:
                conn.execute("UPDATE manual_ai_plans SET status = 'armed' WHERE id = ?", (plan_id,))
                conn.commit()

            updated = client.patch(
                f"/api/manual-ai/plans/{plan_id}/expiry",
                json={"expires_in_minutes": 24 * 60},
            )

            self.assertEqual(200, updated.status_code, updated.text)
            self.assertTrue(updated.json()["requires_broker_replace"])
            with connect(db_path) as conn:
                row = conn.execute(
                    "SELECT status, replacement_levels_json FROM manual_ai_plans WHERE id = ?",
                    (plan_id,),
                ).fetchone()
            replacement = json.loads(row["replacement_levels_json"])
            self.assertEqual("replace_requested", row["status"])
            self.assertEqual(24 * 60, replacement["expires_in_minutes"])
            self.assertIn("expires_at", replacement)

    def test_h1_blocked_plan_requires_safe_human_override_audit(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            client = authenticated_test_client(root, config_path)
            payload = copy.deepcopy(envelope(client_id="h1-soft-override"))
            prepare_h1_payload(payload, db_path)
            candidate = payload["candidates"][0]
            candidate.update(
                {
                    "original_status": "blocked",
                    "original_blocked_reasons": ["Body/range is below minimum."],
                    "soft_blocked_reasons": ["Body/range is below minimum."],
                    "hard_blocked_reasons": [],
                }
            )

            missing_override = client.post("/api/manual-ai/plans", json=payload)
            self.assertEqual(422, missing_override.status_code, missing_override.text)

            candidate["human_override"] = True
            candidate["override_reason"] = "too short"
            short_reason = client.post("/api/manual-ai/plans", json=payload)
            self.assertEqual(422, short_reason.status_code, short_reason.text)

            candidate["override_reason"] = "Structure and liquidity context support this retest despite the candle ratio."
            accepted = client.post("/api/manual-ai/plans", json=payload)
            self.assertEqual(200, accepted.status_code, accepted.text)
            plan_id = accepted.json()["plans"][0]["id"]
            with connect(db_path) as conn:
                row = conn.execute("SELECT raw_payload_json FROM manual_ai_plans WHERE id = ?", (plan_id,)).fetchone()
            persisted_candidate = json.loads(row["raw_payload_json"])["candidates"][0]
            self.assertTrue(persisted_candidate["human_override"])
            self.assertEqual(candidate["override_reason"], persisted_candidate["override_reason"])

    def test_h1_plan_rejects_hard_blocks_and_stop_outside_atr_limits(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            client = authenticated_test_client(root, config_path)
            payload = copy.deepcopy(envelope(client_id="h1-hard-block"))
            prepare_h1_payload(payload, db_path)
            candidate = payload["candidates"][0]
            candidate["original_status"] = "blocked"
            candidate["soft_blocked_reasons"] = ["Close location is below minimum."]
            candidate["hard_blocked_reasons"] = ["Signal has expired."]
            candidate["human_override"] = True
            candidate["override_reason"] = "I accept the soft candle-quality exception after reviewing context."

            hard_blocked = client.post("/api/manual-ai/plans", json=payload)
            self.assertEqual(422, hard_blocked.status_code, hard_blocked.text)

            candidate["hard_blocked_reasons"] = []
            payload["market_context"]["atr"] = 100
            bad_stop = client.post("/api/manual-ai/plans", json=payload)
            self.assertEqual(422, bad_stop.status_code, bad_stop.text)

            payload["market_context"]["atr"] = 20
            candidate["soft_blocked_reasons"] = []
            candidate["human_override"] = False
            candidate["override_reason"] = ""
            resolved = client.post("/api/manual-ai/plans", json=payload)
            self.assertEqual(200, resolved.status_code, resolved.text)

    def test_h1_expired_plan_can_create_audited_child_when_signal_is_untouched(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            client = authenticated_test_client(root, config_path)
            parent_payload = copy.deepcopy(envelope(client_id="h1-renew-parent", expires_in_minutes=60))
            prepare_h1_payload(parent_payload, db_path)
            parent_payload["candidates"][0]["original_status"] = "eligible"

            parent_response = client.post("/api/manual-ai/plans", json=parent_payload)
            self.assertEqual(200, parent_response.status_code, parent_response.text)
            parent_id = parent_response.json()["plans"][0]["id"]
            with connect(db_path) as conn:
                conn.execute("UPDATE manual_ai_plans SET status = 'expired' WHERE id = ?", (parent_id,))
                conn.commit()

            child_payload = copy.deepcopy(parent_payload)
            child_payload["as_of"] = datetime.now(UTC).isoformat()
            child = child_payload["candidates"][0]
            child["client_id"] = "h1-renew-child"
            child["renewed_from_plan_id"] = parent_id
            # Backend owns the audit counter; callers cannot forge it.
            child["renewal_count"] = 7
            child["expires_in_minutes"] = 12 * 60

            renewed = client.post("/api/manual-ai/plans", json=child_payload)

            self.assertEqual(200, renewed.status_code, renewed.text)
            renewed_plan = renewed.json()["plans"][0]
            self.assertEqual(12 * 60, renewed_plan["expires_in_minutes"])
            with connect(db_path) as conn:
                row = conn.execute(
                    "SELECT raw_payload_json FROM manual_ai_plans WHERE id = ?",
                    (renewed_plan["id"],),
                ).fetchone()
            persisted = json.loads(row["raw_payload_json"])
            self.assertEqual(parent_id, persisted["candidates"][0]["renewed_from_plan_id"])
            self.assertEqual(1, persisted["candidates"][0]["renewal_count"])
            self.assertTrue(persisted["market_context"]["revalidations"]["h1-renew-child"]["can_reorder"])

    def test_h1_revalidation_warns_after_entry_touch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            signal_time = seed_recent_h1_signal(db_path)
            with connect(db_path) as conn:
                signal_close = datetime.fromisoformat(signal_time) + timedelta(hours=1)
                conn.execute(
                    """
                    INSERT INTO candles (id, symbol, timeframe, open_time, close_time, open, high, low, close, volume, source)
                    VALUES ('recent-m5-entry-touch', 'XAUUSD', 'M5', ?, ?, 2006, 2008, 1999, 2004, 100, 'test')
                    """,
                    (
                        (signal_close + timedelta(minutes=5)).isoformat(),
                        (signal_close + timedelta(minutes=10)).isoformat(),
                    ),
                )
                conn.commit()
            client = authenticated_test_client(root, config_path)

            response = client.post(
                "/api/playbooks/h1-impulse-retest/revalidate",
                json={
                    "symbol": "XAUUSD",
                    "signal_candle_time": signal_time,
                    "direction": "long",
                    "entry": 2000,
                    "stop_loss": 1990,
                    "take_profit": 2020,
                },
            )

            self.assertEqual(200, response.status_code, response.text)
            self.assertFalse(response.json()["can_reorder"])
            self.assertTrue(response.json()["entry_touched"])

    def test_h1_plan_allows_revalidation_warnings_and_persists_audit(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            payload = copy.deepcopy(envelope(client_id="h1-entry-touch-warning"))
            prepare_h1_payload(payload, db_path)
            signal_time = payload["market_context"]["signal_candle_time"]
            signal_close = datetime.fromisoformat(signal_time) + timedelta(hours=1)
            with connect(db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO candles (id, symbol, timeframe, open_time, close_time, open, high, low, close, volume, source)
                    VALUES ('recent-m5-entry-touch-warning', 'XAUUSD', 'M5', ?, ?, 2006, 2008, 1999, 2004, 100, 'test')
                    """,
                    (
                        (signal_close + timedelta(minutes=5)).isoformat(),
                        (signal_close + timedelta(minutes=10)).isoformat(),
                    ),
                )
                conn.commit()
            client = authenticated_test_client(root, config_path)

            response = client.post("/api/manual-ai/plans", json=payload)

            self.assertEqual(200, response.status_code, response.text)
            plan_id = response.json()["plans"][0]["id"]
            with connect(db_path) as conn:
                row = conn.execute(
                    "SELECT raw_payload_json FROM manual_ai_plans WHERE id = ?",
                    (plan_id,),
                ).fetchone()
            persisted = json.loads(row["raw_payload_json"])
            revalidation = persisted["market_context"]["revalidations"]["h1-entry-touch-warning"]
            self.assertFalse(revalidation["can_reorder"])
            self.assertTrue(revalidation["entry_touched"])
            self.assertTrue(revalidation["hard_blocked_reasons"])

    def test_import_recalculates_rr_and_approval_requires_discipline(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            client = authenticated_test_client(root, config_path)

            payload = envelope()
            imported = client.post("/api/manual-ai/plans/import", json=payload)
            self.assertEqual(imported.status_code, 200)
            plan = imported.json()["plans"][0]
            self.assertEqual(plan["status"], "draft")
            self.assertEqual(plan["risk_reward"], 2.0)
            self.assertEqual(plan["expires_in_minutes"], 120)
            expected_expiry = datetime.fromisoformat(payload["as_of"]) + timedelta(minutes=120)
            self.assertEqual(datetime.fromisoformat(plan["expires_at"]), expected_expiry)
            chart = client.get("/api/chart?symbol=XAUUSD&timeframe=H1&limit=20&playbooks=manual_ai_v1")
            self.assertEqual(chart.status_code, 200)
            setup = chart.json()["layers"]["setup_candidates"][0]
            self.assertEqual(setup["id"], plan["id"])
            self.assertEqual(setup["status"], "waiting_confirmation")
            self.assertEqual(setup["metadata"]["manual_ai_plan_status"], "draft")
            safety_chart = client.get("/api/chart?symbol=XAUUSD&timeframe=H1&limit=20&playbooks=zone_reaction_v2")
            self.assertEqual(safety_chart.json()["layers"]["setup_candidates"], [])

            blocked = client.post(
                f"/api/manual-ai/plans/{plan['id']}/approve",
                json={"account_label": "FTMO 100K", "questionnaire": questionnaire(accepts=False)},
            )
            self.assertEqual(blocked.status_code, 422)

            approved = client.post(
                f"/api/manual-ai/plans/{plan['id']}/approve",
                json={"account_label": "FTMO 100K", "questionnaire": questionnaire()},
            )
            self.assertEqual(approved.status_code, 200)
            self.assertEqual(approved.json()["status"], "approved")
            with connect(db_path) as conn:
                row = conn.execute("SELECT status, account_label FROM manual_ai_plans WHERE id = ?", (plan["id"],)).fetchone()
            self.assertEqual((row["status"], row["account_label"]), ("approved", "FTMO 100K"))

    def test_import_rejects_bad_rr_and_missing_primary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            client = authenticated_test_client(root, config_path)
            self.assertEqual(client.post("/api/manual-ai/plans/import", json=envelope(rr=1.0)).status_code, 422)
            accepted_max = client.post(
                "/api/manual-ai/plans/import",
                json=envelope(rr=4.0, client_id="manual-ai-max-rr"),
            )
            self.assertEqual(accepted_max.status_code, 200, accepted_max.text)
            self.assertEqual(4.0, accepted_max.json()["plans"][0]["risk_reward"])
            self.assertEqual(
                422,
                client.post(
                    "/api/manual-ai/plans/import",
                    json=envelope(rr=4.01, client_id="manual-ai-over-max-rr"),
                ).status_code,
            )
            self.assertEqual(client.post("/api/manual-ai/plans/import", json=envelope(execution_state="watch_only")).status_code, 422)

    def test_import_accepts_expiry_up_to_48_hours(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            client = authenticated_test_client(root, config_path)

            accepted = client.post(
                "/api/manual-ai/plans/import",
                json=envelope(client_id="manual-ai-48h", expires_in_minutes=2_880),
            )
            self.assertEqual(accepted.status_code, 200, accepted.text)
            self.assertEqual(2_880, accepted.json()["plans"][0]["expires_in_minutes"])
            rejected = client.post(
                "/api/manual-ai/plans/import",
                json=envelope(client_id="manual-ai-over-48h", expires_in_minutes=2_881),
            )
            self.assertEqual(422, rejected.status_code)

    def test_approval_fans_out_to_workers_and_cancel_stops_the_whole_group(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            client = authenticated_test_client(root, config_path)

            imported = client.post("/api/manual-ai/plans/import", json=envelope()).json()["plans"][0]
            approved = client.post(
                f"/api/manual-ai/plans/{imported['id']}/approve",
                json={"account_labels": ["FTMO 100K", "Exness Personal"], "questionnaire": questionnaire()},
            )
            self.assertEqual(approved.status_code, 200)
            plans = approved.json()["plans"]
            self.assertEqual({plan["account_label"] for plan in plans}, {"FTMO 100K", "Exness Personal"})
            self.assertEqual({plan["status"] for plan in plans}, {"approved"})

            chart = client.get("/api/chart?symbol=XAUUSD&timeframe=H1&limit=20&playbooks=manual_ai_v1")
            setups = chart.json()["layers"]["setup_candidates"]
            self.assertEqual(len(setups), 1)
            self.assertEqual(set(setups[0]["metadata"]["account_labels"]), {"FTMO 100K", "Exness Personal"})

            with connect(db_path) as conn:
                conn.execute(
                    "UPDATE manual_ai_plans SET status = 'armed' WHERE client_id = ? AND account_label = ?",
                    (imported["client_id"], "FTMO 100K"),
                )
                conn.commit()
            cancelled = client.post(f"/api/manual-ai/plans/{imported['id']}/cancel")
            self.assertEqual(cancelled.status_code, 200)
            repeated = client.post(f"/api/manual-ai/plans/{imported['id']}/cancel")
            self.assertEqual(repeated.status_code, 200)
            with connect(db_path) as conn:
                statuses = {
                    row["status"]
                    for row in conn.execute(
                        "SELECT status FROM manual_ai_plans WHERE client_id = ?",
                        (imported["client_id"],),
                    ).fetchall()
                }
            self.assertEqual(statuses, {"cancelled", "cancel_requested"})

    def test_multiple_active_limit_plans_can_be_approved_for_the_same_workers(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            client = authenticated_test_client(root, config_path)
            labels = ["FTMO 100K", "Exness Personal"]

            first = client.post(
                "/api/manual-ai/plans/import",
                json=envelope(client_id="manual-ai-first"),
            ).json()["plans"][0]
            second = client.post(
                "/api/manual-ai/plans/import",
                json=envelope(client_id="manual-ai-second"),
            ).json()["plans"][0]

            for plan in (first, second):
                approved = client.post(
                    f"/api/manual-ai/plans/{plan['id']}/approve",
                    json={"account_labels": labels, "questionnaire": questionnaire()},
                )
                self.assertEqual(approved.status_code, 200, approved.text)

            with connect(db_path) as conn:
                active = conn.execute(
                    """
                    SELECT account_label, COUNT(*) AS count
                    FROM manual_ai_plans
                    WHERE status = 'approved'
                    GROUP BY account_label
                    ORDER BY account_label
                    """
                ).fetchall()
            self.assertEqual({row["account_label"]: row["count"] for row in active}, {
                "Exness Personal": 2,
                "FTMO 100K": 2,
            })

    def test_rejecting_an_armed_plan_requests_broker_cancel(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            client = authenticated_test_client(root, config_path)

            imported = client.post("/api/manual-ai/plans/import", json=envelope()).json()["plans"][0]
            approved = client.post(
                f"/api/manual-ai/plans/{imported['id']}/approve",
                json={"account_label": "FTMO 100K", "questionnaire": questionnaire()},
            ).json()
            with connect(db_path) as conn:
                conn.execute("UPDATE manual_ai_plans SET status = 'armed' WHERE id = ?", (approved["id"],))
                conn.commit()

            rejected = client.post(f"/api/manual-ai/plans/{approved['id']}/reject")

            self.assertEqual(rejected.status_code, 200)
            self.assertEqual("cancel_requested", rejected.json()["status"])

    def test_level_edit_updates_draft_immediately_and_recalculates_rr(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            client = authenticated_test_client(root, config_path)
            plan = client.post("/api/manual-ai/plans/import", json=envelope()).json()["plans"][0]

            response = client.patch(
                f"/api/manual-ai/plans/{plan['id']}/levels",
                json={"entry_price": 2002, "stop_loss": 1992, "take_profit": 2032},
            )

            self.assertEqual(200, response.status_code, response.text)
            self.assertFalse(response.json()["requires_broker_replace"])
            updated = response.json()["plans"][0]
            self.assertEqual((2002.0, 1992.0, 2032.0, 3.0), (
                updated["entry_price"], updated["stop_loss"], updated["take_profit"], updated["risk_reward"]
            ))

    def test_level_edit_requests_cancel_replace_for_every_armed_worker(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            seed_candles(db_path)
            client = authenticated_test_client(root, config_path)
            imported = client.post("/api/manual-ai/plans/import", json=envelope()).json()["plans"][0]
            client.post(
                f"/api/manual-ai/plans/{imported['id']}/approve",
                json={"account_labels": ["FTMO 100K", "Exness Personal"], "questionnaire": questionnaire()},
            )
            with connect(db_path) as conn:
                conn.execute("UPDATE manual_ai_plans SET status = 'armed' WHERE client_id = ?", (imported["client_id"],))
                conn.commit()

            response = client.patch(
                f"/api/manual-ai/plans/{imported['id']}/levels",
                json={"entry_price": 2001, "stop_loss": 1991, "take_profit": 2026},
            )

            self.assertEqual(200, response.status_code, response.text)
            self.assertTrue(response.json()["requires_broker_replace"])
            with connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT status, entry_price, replacement_levels_json FROM manual_ai_plans WHERE client_id = ?",
                    (imported["client_id"],),
                ).fetchall()
            self.assertEqual({"replace_requested"}, {row["status"] for row in rows})
            self.assertEqual({2000.0}, {row["entry_price"] for row in rows})
            self.assertTrue(all('"entry_price": 2001.0' in row["replacement_levels_json"] for row in rows))

    def test_level_edit_rejects_invalid_geometry_and_rr(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "test.sqlite3"
            config_path = root / "trading.toml"
            write_test_config(config_path, db_path)
            client = authenticated_test_client(root, config_path)
            plan = client.post("/api/manual-ai/plans/import", json=envelope()).json()["plans"][0]
            invalid_geometry = client.patch(
                f"/api/manual-ai/plans/{plan['id']}/levels",
                json={"entry_price": 2000, "stop_loss": 2010, "take_profit": 2030},
            )
            invalid_rr = client.patch(
                f"/api/manual-ai/plans/{plan['id']}/levels",
                json={"entry_price": 2000, "stop_loss": 1990, "take_profit": 2010},
            )
            self.assertEqual(422, invalid_geometry.status_code)
            self.assertEqual(422, invalid_rr.status_code)


def questionnaire(*, accepts: bool = True) -> dict:
    return {
        "short_term_trend": "bullish",
        "medium_term_trend": "bullish",
        "invalidation_source": "structure",
        "limit_reason": "pullback",
        "emotion_state": "calm",
        "accepts_one_percent_risk": accepts,
        "confirms_lot_not_fixed": True,
        "competing_exposure": False,
        "comment": "test",
    }


if __name__ == "__main__":
    unittest.main()
