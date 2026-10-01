from __future__ import annotations

import json
import unittest
from contextlib import closing
from pathlib import Path
from tests.helpers import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from semi_bot_trading.chart import (
    MAX_TOUCH_ONLY_M15_TRIGGER_OVERLAYS,
    build_chart_payload,
    build_m15_signal_snapshot,
    build_m15_trigger_overlays,
    build_wave_metrics,
    filter_traded_setup_candidates,
    load_manual_ai_setup_candidates,
    load_quick_order_setup_candidates,
    load_chart_trades,
)
from semi_bot_trading.db import connect, init_db


class ChartPayloadTest(unittest.TestCase):
    def test_quick_order_limit_is_exposed_as_one_pending_setup_per_group(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with closing(connect(db_path)) as conn:
                init_db(conn)
                conn.executemany(
                    """
                    INSERT INTO quick_order_requests (
                        id, client_group_id, client_request_id, account_label, symbol,
                        side, order_type, requested_entry, requested_stop, effective_entry,
                        effective_stop, take_profit, risk_reward, atr_h1, atr_candle_time,
                        status, expires_at, created_at, updated_at
                    ) VALUES (?, 'quick-group', 'quick-request-123', ?, 'XAUUSD',
                              'buy', 'limit', 4300, 4286, 4300, 4286, 4321, 1.5,
                              14, '2026-09-25T13:00:00+00:00', ?,
                              '2026-09-25T16:00:00+00:00',
                              '2026-09-25T14:00:00+00:00',
                              '2026-09-25T14:00:00+00:00')
                    """,
                    [
                        ("quick-ftmo", "FTMO 100K 2-Step", "pending"),
                        ("quick-exness", "Exness Personal", "executing"),
                    ],
                )
                candidates = load_quick_order_setup_candidates(
                    conn,
                    "XAUUSD",
                    {"quick_order_v1"},
                )
                hidden = load_quick_order_setup_candidates(
                    conn,
                    "XAUUSD",
                    {"line_reaction_v1"},
                )
                conn.execute(
                    """UPDATE quick_order_requests
                       SET status='replace_requested',replacement_levels_json=?
                       WHERE id='quick-ftmo'""",
                    (json.dumps({"entry_price": 4295, "stop_loss": 4280, "take_profit": 4325, "risk_reward": 2}),),
                )
                replacement_candidates = load_quick_order_setup_candidates(conn, "XAUUSD", {"quick_order_v1"})

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate["id"], "quick-group")
        self.assertEqual(candidate["playbook"], "quick_order_v1")
        self.assertEqual(candidate["entry"], 4300)
        self.assertEqual(candidate["stop_loss"], 4286)
        self.assertEqual(candidate["take_profit"], [4321])
        self.assertTrue(candidate["metadata"]["quick_order"])
        self.assertEqual(
            candidate["metadata"]["account_statuses"],
            [
                {"account_label": "Exness Personal", "status": "executing"},
                {"account_label": "FTMO 100K 2-Step", "status": "pending"},
            ],
        )
        self.assertEqual(hidden, [])
        self.assertEqual(4295, replacement_candidates[0]["entry"])
        self.assertEqual(4280, replacement_candidates[0]["stop_loss"])
        self.assertEqual([4325], replacement_candidates[0]["take_profit"])
        self.assertTrue(replacement_candidates[0]["metadata"]["quick_order_replace_pending"])

    def test_expired_h1_setup_keeps_account_terminal_statuses_but_cancelled_only_group_is_hidden(self) -> None:
        raw_payload = json.dumps(
            {
                "playbook": "h1_impulse_retest_v1",
                "market_context": {
                    "signal_candle_time": "2026-08-24T01:00:00+00:00",
                    "atr": 20.0,
                },
                "candidates": [
                    {
                        "client_id": "mixed-client",
                        "confidence": 0.4,
                        "entry_source": "human_custom",
                    }
                ],
            }
        )
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with closing(connect(db_path)) as conn:
                init_db(conn)
                for plan_id, client_id, account_label, status in (
                    ("mixed-expired", "mixed-client", "FTMO", "expired"),
                    ("mixed-cancelled", "mixed-client", "Exness", "cancelled"),
                    ("cancelled-only", "cancelled-client", "FTMO", "cancelled"),
                ):
                    conn.execute(
                        """
                        INSERT INTO manual_ai_plans (
                            id, client_id, account_label, symbol, side, status, execution_state,
                            entry_price, stop_loss, take_profit, risk_reward, expires_at,
                            raw_payload_json, created_at, updated_at
                        ) VALUES (?, ?, ?, 'XAUUSD', 'sell', ?, 'primary', 4666.2, 4681.8,
                                  4605.0, 3.92, '2026-08-24T22:04:00+00:00', ?,
                                  '2026-08-24T02:04:00+00:00', '2026-08-24T22:04:00+00:00')
                        """,
                        (plan_id, client_id, account_label, status, raw_payload),
                    )
                candidates = load_manual_ai_setup_candidates(
                    conn,
                    "XAUUSD",
                    {"h1_impulse_retest_v1"},
                    "2026-08-25T02:00:00+00:00",
                )

        self.assertEqual(["mixed-expired"], [candidate["id"] for candidate in candidates])
        self.assertEqual(candidates[0]["status"], "expired")
        self.assertEqual(
            candidates[0]["metadata"]["account_statuses"],
            [
                {"account_label": "Exness", "status": "cancelled"},
                {"account_label": "FTMO", "status": "expired"},
            ],
        )

    def test_builds_chart_payload_contract(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with closing(connect(db_path)) as conn:
                init_db(conn)
                seed_chart_data(conn)
                payload = build_chart_payload(conn, "XAUUSD", "M15", limit=2)

        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["symbol"], "XAUUSD")
        self.assertEqual(payload["timeframe"], "M15")
        self.assertEqual(len(payload["layers"]["candles"]), 2)
        self.assertIn("structure", payload["layers"])
        self.assertEqual(payload["layers"]["structure_timeframe"], "H1")
        self.assertIn("wave_metrics", payload["layers"])
        self.assertIn("zones", payload["layers"])
        self.assertIn("contexts", payload["layers"])
        self.assertIn("trades", payload["layers"])
        self.assertIn("setup_candidates", payload["layers"])
        self.assertIn("h1_impulse_markers", payload["layers"])
        self.assertIn("m15_signal", payload["layers"])
        self.assertIn("intraday_map", payload["layers"])
        self.assertEqual(payload["layers"]["intraday_map"]["current_session"], "Asia")
        self.assertTrue(any(level["label"] == "Asia H" for level in payload["layers"]["intraday_map"]["levels"]))
        self.assertEqual(payload["layers"]["setup_candidates"], [])
        signal = payload["layers"]["m15_signal"]
        self.assertTrue(signal["candle_closed"])
        self.assertEqual(signal["candle_time"], "2026-01-01T00:15:00+00:00")
        self.assertEqual(signal["candle_close_time"], "2026-01-01T00:30:00+00:00")
        self.assertAlmostEqual(signal["avg_body"], 1.0)
        self.assertAlmostEqual(signal["body"], 2.0)
        self.assertAlmostEqual(signal["body_avg_ratio"], 2.0, places=4)
        self.assertEqual(signal["trigger_method"], "close_extreme_recovery")
        self.assertAlmostEqual(signal["strength_size"], 3.0)
        self.assertAlmostEqual(signal["strength_avg_ratio"], 3.0)
        self.assertEqual(payload["layers"]["zones"][0]["timeframe"], "H1")
        self.assertEqual(payload["layers"]["contexts"]["H1"]["bias"]["effective_value"], "bullish")
        self.assertEqual(payload["layers"]["contexts"]["M15"]["bias"]["effective_value"], "bullish")
        self.assertEqual(payload["layers"]["zones"][0]["visual_start"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(payload["layers"]["zones"][0]["visual_end"], "2027-01-01T00:00:00+00:00")

    def test_wave_metrics_measure_confirmed_zigzag_legs_and_strength(self) -> None:
        candles = [
            {
                "time": f"2026-01-{1 + hour // 24:02d}T{hour % 24:02d}:00:00+00:00",
                "high": 105.0,
                "low": 95.0,
                "close": 100.0,
            }
            for hour in range(24)
        ]
        prices = [100.0, 130.0, 110.0, 140.0, 120.0, 150.0, 130.0]
        hours = [12, 14, 16, 18, 20, 22, 23]
        points = [
            {
                "id": f"swing-{index}",
                "time": f"2026-01-01T{hour:02d}:00:00+00:00",
                "type": "swing_low" if index % 2 == 0 else "swing_high",
                "price": price,
                "metadata": {
                    "swing_type": "low" if index % 2 == 0 else "high",
                    "confirmed_at": f"2026-01-01T{hour:02d}:00:00+00:00",
                },
            }
            for index, (hour, price) in enumerate(zip(hours, prices))
        ]
        points.append(
            {
                "id": "future-confirmation",
                "time": "2026-01-01T23:00:00+00:00",
                "type": "swing_high",
                "price": 170.0,
                "metadata": {
                    "swing_type": "high",
                    "confirmed_at": "2026-01-02T01:00:00+00:00",
                },
            }
        )

        metrics = build_wave_metrics(
            points,
            candles,
            as_of="2026-01-01T23:00:00+00:00",
        )

        self.assertEqual(6, len(metrics["legs"]))
        self.assertEqual(["up", "down", "up", "down", "up", "down"], [leg["direction"] for leg in metrics["legs"]])
        self.assertEqual(30.0, metrics["legs"][0]["price_move"])
        self.assertEqual(2.0, metrics["legs"][0]["duration_hours"])
        self.assertEqual(1.5, metrics["strength"]["ratio"])
        self.assertEqual("buy", metrics["strength"]["control"])
        self.assertEqual(2, metrics["strength"]["up_samples"])
        self.assertEqual(2, metrics["strength"]["down_samples"])
        self.assertEqual(30.0, metrics["strength"]["up_median_price"])
        self.assertEqual(20.0, metrics["strength"]["down_median_price"])
        self.assertEqual(15.0, metrics["strength"]["up_median_speed"])
        self.assertEqual(10.0, metrics["strength"]["down_median_speed"])
        self.assertEqual("down", metrics["strength"]["latest"]["direction"])
        self.assertEqual(20.0, metrics["strength"]["latest"]["speed"])
        self.assertEqual(0.6667, metrics["strength"]["latest_to_previous_ratio"])
        self.assertEqual(0.0, metrics["strength"]["up_change_pct"])
        self.assertEqual(0.0, metrics["strength"]["down_change_pct"])
        self.assertEqual(0.2, metrics["strength"]["efficiency"])
        self.assertEqual("up", metrics["strength"]["efficiency_direction"])
        self.assertEqual("choppy", metrics["strength"]["market_state"])

    def test_wave_metrics_keep_twelve_recent_legs(self) -> None:
        candles = [
            {
                "time": f"2026-01-{1 + hour // 24:02d}T{hour % 24:02d}:00:00+00:00",
                "high": 125.0,
                "low": 95.0,
                "close": 110.0,
            }
            for hour in range(40)
        ]
        points = [
            {
                "id": f"swing-{index}",
                "time": f"2026-01-{1 + hour // 24:02d}T{hour % 24:02d}:00:00+00:00",
                "type": "swing_low" if index % 2 == 0 else "swing_high",
                "price": 100.0 if index % 2 == 0 else 120.0,
                "metadata": {
                    "swing_type": "low" if index % 2 == 0 else "high",
                    "confirmed_at": f"2026-01-{1 + hour // 24:02d}T{hour % 24:02d}:00:00+00:00",
                },
            }
            for index, hour in enumerate(range(14, 29))
        ]

        metrics = build_wave_metrics(points, candles, as_of="2026-01-02T15:00:00+00:00")

        self.assertEqual(12, len(metrics["legs"]))
        self.assertEqual("swing-2:swing-3", metrics["legs"][0]["id"])
        self.assertEqual("swing-13:swing-14", metrics["legs"][-1]["id"])
        self.assertEqual(4, metrics["strength"]["up_samples"])
        self.assertEqual(4, metrics["strength"]["down_samples"])

    def test_can_render_m15_chart_with_h1_structure(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with closing(connect(db_path)) as conn:
                init_db(conn)
                seed_chart_data(conn)
                payload = build_chart_payload(conn, "XAUUSD", "M15", limit=2, structure_timeframe="H1")

        self.assertEqual(payload["timeframe"], "M15")
        self.assertEqual(payload["layers"]["structure_timeframe"], "H1")
        self.assertEqual(payload["layers"]["structure"][0]["id"], "h1-s1")

    def test_closed_live_order_does_not_hide_new_setup_for_same_zone(self) -> None:
        candidate = {"id": "candidate-new", "primary_zone_id": "z1"}
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with closing(connect(db_path)) as conn:
                init_db(conn)
                seed_live_order(conn, status="closed", zone_id="z1")

                filtered = filter_traded_setup_candidates(conn, "XAUUSD", [candidate])

        self.assertEqual([candidate], filtered)

    def test_open_live_order_hides_setup_for_same_zone(self) -> None:
        candidate = {"id": "candidate-new", "primary_zone_id": "z1"}
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with closing(connect(db_path)) as conn:
                init_db(conn)
                seed_live_order(conn, status="filled", zone_id="z1")

                filtered = filter_traded_setup_candidates(conn, "XAUUSD", [candidate])

        self.assertEqual([], filtered)

    def test_open_live_order_only_hides_setup_for_matching_account(self) -> None:
        candidate = {"id": "candidate-new", "primary_zone_id": "z1"}
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with closing(connect(db_path)) as conn:
                init_db(conn)
                seed_live_order(conn, status="filled", zone_id="z1", account_label="FTMO Demo")

                exness_filtered = filter_traded_setup_candidates(
                    conn,
                    "XAUUSD",
                    [candidate],
                    account_label="Exness Personal",
                )
                ftmo_filtered = filter_traded_setup_candidates(
                    conn,
                    "XAUUSD",
                    [candidate],
                    account_label="FTMO Demo",
                )

        self.assertEqual([candidate], exness_filtered)
        self.assertEqual([], ftmo_filtered)

    def test_pending_limit_without_opened_at_still_hides_matching_setup(self) -> None:
        candidate = {"id": "candidate-old", "primary_zone_id": "z1"}
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with closing(connect(db_path)) as conn:
                init_db(conn)
                seed_live_order(conn, status="pending_fill", zone_id="z1", account_label="FTMO Demo")
                conn.execute("UPDATE trade_orders SET opened_at = NULL WHERE id = 'order-1'")
                filtered = filter_traded_setup_candidates(
                    conn,
                    "XAUUSD",
                    [candidate],
                    account_label="FTMO Demo",
                )

        self.assertEqual([], filtered)

    def test_unfilled_manual_ai_limit_is_never_a_chart_trade(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with closing(connect(db_path)) as conn:
                init_db(conn)
                seed_live_order(conn, status="pending_fill", zone_id="z1", playbook="manual_ai_v1")
                pending_trades = load_chart_trades(
                    conn,
                    "XAUUSD",
                    "2025-12-31T00:00:00+00:00",
                    "2026-01-02T00:00:00+00:00",
                    allowed_playbooks={"manual_ai_v1"},
                )
                conn.execute(
                    "UPDATE trade_orders SET status = 'cancelled', closed_at = '2026-01-01T02:00:00+00:00' WHERE id = 'order-1'"
                )
                cancelled_trades = load_chart_trades(
                    conn,
                    "XAUUSD",
                    "2025-12-31T00:00:00+00:00",
                    "2026-01-02T00:00:00+00:00",
                    allowed_playbooks={"manual_ai_v1"},
                )
                conn.execute("UPDATE trade_orders SET status = 'filled' WHERE id = 'order-1'")
                filled_trades = load_chart_trades(
                    conn,
                    "XAUUSD",
                    "2025-12-31T00:00:00+00:00",
                    "2026-01-02T00:00:00+00:00",
                    allowed_playbooks={"manual_ai_v1"},
                )

        self.assertEqual(pending_trades, [])
        self.assertEqual(cancelled_trades, [])
        self.assertEqual(len(filled_trades), 1)
        self.assertEqual(filled_trades[0]["status"], "filled")

    def test_h1_limit_lifecycle_only_exposes_filled_trade_with_shared_execution_group(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with closing(connect(db_path)) as conn:
                init_db(conn)
                seed_live_order(conn, status="pending_fill", zone_id="z1", playbook="h1_impulse_retest_v1")
                conn.execute(
                    """
                    INSERT INTO manual_ai_plans (
                        id, client_id, account_label, symbol, side, status, execution_state,
                        entry_price, stop_loss, take_profit, risk_reward, expires_at,
                        trade_idea_id, created_at, updated_at
                    ) VALUES (
                        'h1-plan', 'h1-shared-client', 'Default', 'XAUUSD', 'buy', 'armed', 'primary',
                        100, 95, 110, 2.0, '2026-01-02T00:00:00+00:00',
                        'idea-1', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'
                    )
                    """
                )
                pending_trades = load_chart_trades(
                    conn,
                    "XAUUSD",
                    "2025-12-31T00:00:00+00:00",
                    "2026-01-02T00:00:00+00:00",
                    allowed_playbooks={"h1_impulse_retest_v1"},
                )
                conn.execute(
                    """
                    UPDATE trade_orders
                    SET status = 'cancelled', closed_at = '2026-01-01T01:00:00+00:00'
                    WHERE id = 'order-1'
                    """
                )
                cancelled_trades = load_chart_trades(
                    conn,
                    "XAUUSD",
                    "2025-12-31T00:00:00+00:00",
                    "2026-01-02T00:00:00+00:00",
                    allowed_playbooks={"h1_impulse_retest_v1"},
                )
                conn.execute("UPDATE trade_orders SET status = 'filled', closed_at = NULL WHERE id = 'order-1'")
                filled_trades = load_chart_trades(
                    conn,
                    "XAUUSD",
                    "2025-12-31T00:00:00+00:00",
                    "2026-01-02T00:00:00+00:00",
                    allowed_playbooks={"h1_impulse_retest_v1"},
                )

        self.assertEqual([], pending_trades)
        self.assertEqual([], cancelled_trades)
        self.assertEqual(1, len(filled_trades))
        self.assertEqual("h1-shared-client", filled_trades[0]["metadata"]["execution_group_id"])

    def test_live_strategy_candle_is_opt_in_for_setup_evaluation(self) -> None:
        captured_lengths: list[int] = []

        def fake_build_setup_candidates(**kwargs):
            captured_lengths.append(len(kwargs["candles"]))
            return []

        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with closing(connect(db_path)) as conn:
                init_db(conn)
                seed_chart_data(conn)
                seed_live_candle(conn)
                strategy_config = SimpleNamespace(timeframe="M15")

                with patch("semi_bot_trading.chart.build_setup_candidates", side_effect=fake_build_setup_candidates):
                    closed_payload = build_chart_payload(
                        conn,
                        "XAUUSD",
                        "M15",
                        limit=2,
                        strategy_config=strategy_config,
                        structure_timeframe="H1",
                    )
                    live_payload = build_chart_payload(
                        conn,
                        "XAUUSD",
                        "M15",
                        limit=2,
                        strategy_config=strategy_config,
                        structure_timeframe="H1",
                        include_live_strategy_candle=True,
                    )

        self.assertEqual([2, 3], captured_lengths)
        self.assertEqual(
            closed_payload["layers"]["m15_signal"]["candle_time"],
            live_payload["layers"]["m15_signal"]["candle_time"],
        )
        self.assertEqual(
            live_payload["layers"]["m15_signal"]["candle_time"],
            "2026-01-01T00:15:00+00:00",
        )

    def test_m15_signal_uses_pinbar_rejection_as_trigger_strength(self) -> None:
        candles = [
            {
                "time": "2026-07-25T00:00:00+00:00",
                "open": 4068.0,
                "high": 4075.0,
                "low": 4067.0,
                "close": 4074.0,
            },
            {
                "time": "2026-07-25T00:15:00+00:00",
                "open": 4074.0,
                "high": 4082.0,
                "low": 4073.0,
                "close": 4081.0,
            },
            {
                "time": "2026-07-25T00:30:00+00:00",
                "open": 4074.495,
                "high": 4082.12,
                "low": 4071.766,
                "close": 4074.912,
            },
        ]
        average = (6.0 + 7.0 + 0.417) / 3
        rejection_size = 7.208
        candidate = {
            "id": "candidate-pinbar",
            "primary_zone_id": "zone-resistance",
            "status": "eligible",
            "score": 1.0,
            "zone_reaction_state": "reject",
            "reason": ["Bearish pinbar rejection at zone."],
            "metadata": {
                "zone_type": "resistance",
                "reaction_trigger_method": "pinbar",
                "reaction_candle_time": candles[-1]["time"],
                "reaction_avg_body": average,
                "reaction_body": 0.417,
                "reaction_body_avg_ratio": 0.417 / average,
                "reaction_rejection_size": rejection_size,
                "reaction_rejection_avg_ratio": rejection_size / average,
            },
        }

        signal = build_m15_signal_snapshot(candles, [candidate], avg_body_period=20)

        self.assertEqual(signal["trigger_method"], "pinbar")
        self.assertEqual(signal["strength_size"], rejection_size)
        self.assertAlmostEqual(signal["strength_avg_ratio"], rejection_size / average, places=4)
        self.assertEqual(signal["trigger_body"], 0.417)
        self.assertTrue(signal["trigger_is_latest_closed_candle"])

    def test_m15_signal_uses_close_extreme_recovery_as_trigger_strength(self) -> None:
        candles = [
            {
                "time": "2026-08-13T14:15:00+00:00",
                "open": 4371.0,
                "high": 4378.0,
                "low": 4367.5,
                "close": 4367.75,
            },
            {
                "time": "2026-08-13T14:30:00+00:00",
                "open": 4367.7,
                "high": 4381.883,
                "low": 4357.346,
                "close": 4381.084,
            },
        ]
        candidate = {
            "id": "candidate-recovery",
            "primary_zone_id": "zone-support",
            "status": "eligible",
            "score": 1.0,
            "zone_reaction_state": "reject",
            "reason": ["Bullish close-to-low recovery rejected the zone."],
            "metadata": {
                "zone_type": "support",
                "reaction_trigger_method": "close_extreme_recovery",
                "reaction_candle_time": candles[-1]["time"],
                "reaction_avg_body": 4.0602,
                "reaction_body": 13.384,
                "reaction_body_avg_ratio": 3.2964,
                "reaction_rejection_size": 23.738,
                "reaction_rejection_avg_ratio": 5.8465,
            },
        }

        signal = build_m15_signal_snapshot(candles, [candidate], avg_body_period=20)

        self.assertEqual("close_extreme_recovery", signal["trigger_method"])
        self.assertEqual(23.738, signal["strength_size"])
        self.assertEqual(5.8465, signal["strength_avg_ratio"])

    def test_m15_trigger_overlay_caps_touch_only_rows_but_keeps_candidates(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with closing(connect(db_path)) as conn:
                init_db(conn)
                rows = []
                for index in range(MAX_TOUCH_ONLY_M15_TRIGGER_OVERLAYS + 100):
                    minute = index * 15
                    open_time = f"2026-01-{1 + minute // 1440:02d}T{(minute % 1440) // 60:02d}:{minute % 60:02d}:00+00:00"
                    close_time = f"2026-01-{1 + (minute + 15) // 1440:02d}T{((minute + 15) % 1440) // 60:02d}:{(minute + 15) % 60:02d}:00+00:00"
                    rows.append((f"m15-{index}", open_time, close_time))
                conn.executemany(
                    """
                    INSERT INTO candles (
                        id, symbol, timeframe, open_time, close_time, open, high, low, close, volume, source
                    )
                    VALUES (?, 'XAUUSD', 'M15', ?, ?, 100, 105, 95, 101, 100, 'test')
                    """,
                    rows,
                )
                overlays = build_m15_trigger_overlays(
                    conn,
                    "XAUUSD",
                    "H1",
                    "H1",
                    rows[0][1],
                    rows[-1][1],
                    [
                        {
                            "id": "zone-1",
                            "type": "support",
                            "direction": "bullish",
                            "price_low": 90,
                            "price_high": 110,
                        }
                    ],
                    [
                        {
                            "id": "candidate-1",
                            "primary_zone_id": "zone-1",
                            "zone_reaction_state": "reject",
                            "status": "eligible",
                            "direction": "long",
                            "reason": ["candidate"],
                            "metadata": {"reaction_candle_time": rows[0][1]},
                        }
                    ],
                )

        self.assertEqual(MAX_TOUCH_ONLY_M15_TRIGGER_OVERLAYS + 1, len(overlays))
        self.assertEqual("candidate-1", overlays[0]["candidate_id"])
        self.assertEqual(MAX_TOUCH_ONLY_M15_TRIGGER_OVERLAYS, sum(1 for item in overlays if item["status"] == "touch"))


def seed_chart_data(conn) -> None:
    candles = [
        ("c1", "2026-01-01T00:00:00+00:00", "2026-01-01T00:15:00+00:00", 2000, 2002, 1999, 2001),
        ("c2", "2026-01-01T00:15:00+00:00", "2026-01-01T00:30:00+00:00", 2001, 2004, 2000, 2003),
    ]
    conn.executemany(
        """
        INSERT INTO candles (
            id, symbol, timeframe, open_time, close_time, open, high, low, close, volume, source
        )
        VALUES (?, 'XAUUSD', 'M15', ?, ?, ?, ?, ?, ?, 100, 'test')
        """,
        candles,
    )
    conn.execute(
        """
        INSERT INTO structure_points (
            id, symbol, timeframe, detector, status, point_type, price, event_time,
            confidence, related_zone_ids_json, metadata_json
        )
        VALUES ('s1', 'XAUUSD', 'M15', 'swing_v1', 'confirmed', 'HH', 2004,
                '2026-01-01T00:15:00+00:00', 1.0, '[]', '{}')
        """
    )
    conn.execute(
        """
        INSERT INTO structure_points (
            id, symbol, timeframe, detector, status, point_type, price, event_time,
            confidence, related_zone_ids_json, metadata_json
        )
        VALUES ('h1-s1', 'XAUUSD', 'H1', 'swing_v1', 'confirmed', 'HH', 2005,
                '2026-01-01T00:15:00+00:00', 1.0, '[]', '{}')
        """
    )
    conn.execute(
        """
        INSERT INTO price_zones (
            id, symbol, timeframe, detector, zone_type, direction, price_low, price_high,
            start_time, end_time, valid_from, valid_until, invalidated_at,
            invalidated_by_structure_point_id, detected_at, bot_confidence, bot_weight,
            effective_confidence, effective_weight, status, source, metadata_json
        )
        VALUES ('z1', 'XAUUSD', 'H1', 'sr_v1', 'support', 'bullish', 1990, 1995,
                '2026-01-01T00:00:00+00:00', '2027-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00',
                '2027-01-01T00:00:00+00:00', NULL, NULL, '2026-01-01T00:00:00+00:00',
                0.8, 0.7, 0.8, 0.7, 'active', 'bot', ?)
        """,
        (json.dumps({"touch_count": 2}),),
    )
    conn.execute(
        """
        INSERT INTO market_contexts (
            id, symbol, timeframe, context_type, bot_value, primary_value, secondary_value,
            bot_confidence, effective_value, effective_confidence, source, valid_from,
            valid_until, status, metadata_json
        )
        VALUES ('ctx1', 'XAUUSD', 'M15', 'bias', 'bullish', 'bullish', NULL,
                0.8, 'bullish', 0.8, 'bot', '2026-01-01T00:15:00+00:00',
                NULL, 'active', '{}')
        """
    )
    conn.execute(
        """
        INSERT INTO market_contexts (
            id, symbol, timeframe, context_type, bot_value, primary_value, secondary_value,
            bot_confidence, effective_value, effective_confidence, source, valid_from,
            valid_until, status, metadata_json
        )
        VALUES ('ctx2', 'XAUUSD', 'H1', 'bias', 'bullish', 'bullish', NULL,
                0.9, 'bullish', 0.9, 'bot', '2026-01-01T00:00:00+00:00',
                NULL, 'active', '{}')
        """
    )
    conn.commit()


def seed_live_candle(conn) -> None:
    conn.execute(
        """
        INSERT INTO live_candles (
            id, symbol, timeframe, open_time, close_time, open, high, low, close, volume, source
        )
        VALUES (
            'live-m15', 'XAUUSD', 'M15', '2026-01-01T00:30:00+00:00',
            '2026-01-01T00:45:00+00:00', 2003, 2006, 2002, 2005, 50, 'test'
        )
        """
    )
    conn.commit()


def seed_live_order(
    conn,
    status: str,
    zone_id: str,
    account_label: str = "Default",
    playbook: str = "zone_reaction_v2",
) -> None:
    candidate = {"id": "candidate-old", "primary_zone_id": zone_id}
    conn.execute(
        """
        INSERT INTO trade_ideas (
            id, symbol, direction, playbook, status, entry_zone_id,
            related_zone_ids_json, context_snapshot_json, suggested_entry,
            suggested_stop_loss, suggested_take_profit_json, risk_reward,
            created_at, expires_at
        )
        VALUES ('idea-1', 'XAUUSD', 'long', ?, 'approved',
                ?, '[]', ?, 100, 95, '[110]', 2.0,
                '2026-01-01T00:00:00+00:00', NULL)
        """,
        (playbook, zone_id, json.dumps({"candidate": candidate})),
    )
    conn.execute(
        """
        INSERT INTO trade_orders (
            id, trade_idea_id, account_label, symbol, side, order_type, status, entry_price,
            stop_loss, take_profit_json, quantity, opened_at, closed_at,
            source, metadata_json, created_at
        )
        VALUES ('order-1', 'idea-1', ?, 'XAUUSD', 'buy', 'market', ?, 100,
                95, '[110]', 0.01, '2026-01-01T00:00:00+00:00',
                CASE WHEN ? = 'closed' THEN '2026-01-01T01:00:00+00:00' ELSE NULL END,
                'live', ?, '2026-01-01T00:00:00+00:00')
        """,
        (account_label, status, status, json.dumps({"candidate_id": "candidate-old"})),
    )
    conn.commit()


if __name__ == "__main__":
    unittest.main()
