from __future__ import annotations

import copy
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from semi_bot_trading.db import connect
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
            payload["playbook"] = "h1_impulse_retest_v1"
            payload["candidates"][0]["entry_source"] = "fib_0.5"
            payload["candidates"][0]["entry_options"] = [
                {"source": "fib_0.5", "label": "Fib 0.5", "price": 2000.0}
            ]

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

            edited = client.patch(
                f"/api/manual-ai/plans/{plan['id']}/levels",
                json={
                    "entry_price": 2001,
                    "stop_loss": 1991,
                    "take_profit": 2031,
                    "entry_source": "previous_h1_high",
                },
            )
            self.assertEqual(200, edited.status_code, edited.text)
            self.assertEqual("previous_h1_high", edited.json()["plans"][0]["entry_source"])

            accepted_rr = client.patch(
                f"/api/manual-ai/plans/{plan['id']}/levels",
                json={"entry_price": 2001, "stop_loss": 1991, "take_profit": 2041, "entry_source": "human_custom"},
            )
            self.assertEqual(200, accepted_rr.status_code, accepted_rr.text)

            rejected_rr = client.patch(
                f"/api/manual-ai/plans/{plan['id']}/levels",
                json={"entry_price": 2001, "stop_loss": 1991, "take_profit": 2042, "entry_source": "human_custom"},
            )
            self.assertEqual(422, rejected_rr.status_code)

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
