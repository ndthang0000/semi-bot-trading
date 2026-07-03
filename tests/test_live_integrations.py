from __future__ import annotations

import os
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from datetime import timezone as _timezone
UTC = _timezone.utc
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from semi_bot_trading.candles import Candle, upsert_candles
from semi_bot_trading.config import load_config
from semi_bot_trading.alerts import format_alert_message, pending_alerts, queue_alert
from semi_bot_trading.db import connect, init_db
from semi_bot_trading.live_worker import (
    LiveWorkerState,
    _queue_new_swing_alerts,
    queue_setup_alerts,
    run_live_detectors,
    run_live_iteration,
)
from semi_bot_trading.runtime_env import RuntimeEnv
from semi_bot_trading.runtime_env import load_runtime_env


class LiveIntegrationTest(unittest.TestCase):
    def test_alert_queue_dedupes_by_key(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            conn = connect(db_path)
            try:
                init_db(conn)
                first = queue_alert(
                    conn,
                    symbol="XAUUSD",
                    timeframe="M15",
                    event_type="new_zone",
                    severity="watch",
                    entity_ids=["z1"],
                    payload={"title": "New zone"},
                    dedupe_key="new-zone:z1",
                )
                second = queue_alert(
                    conn,
                    symbol="XAUUSD",
                    timeframe="M15",
                    event_type="new_zone",
                    severity="watch",
                    entity_ids=["z1"],
                    payload={"title": "New zone"},
                    dedupe_key="new-zone:z1",
                )
                alerts = pending_alerts(conn)
            finally:
                conn.close()

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(1, len(alerts))
        self.assertEqual(["z1"], alerts[0].entity_ids)

    def test_m15_swing_detection_does_not_queue_telegram_alert(self) -> None:
        config = load_config()
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            conn = connect(db_path)
            try:
                init_db(conn)
                event_time = datetime(2026, 6, 23, 8, 0, tzinfo=UTC).isoformat()
                for timeframe, point_id in (("M15", "m15-swing"), ("H1", "h1-swing")):
                    conn.execute(
                        """
                        INSERT INTO structure_points (
                            id, symbol, timeframe, detector, status, point_type, price, event_time,
                            confidence, related_zone_ids_json, metadata_json
                        ) VALUES (?, ?, ?, 'swing_v1', 'confirmed', 'LL', 4114.615, ?, 1.0, '[]', ?)
                        """,
                        (point_id, config.symbol, timeframe, event_time, '{"swing_type":"low"}'),
                    )
                conn.commit()

                _queue_new_swing_alerts(conn, config, config.symbol, "M15", {"m15-swing"})
                self.assertEqual([], pending_alerts(conn))

                _queue_new_swing_alerts(conn, config, config.symbol, "H1", {"h1-swing"})
                alerts = pending_alerts(conn)
            finally:
                conn.close()

        self.assertEqual(1, len(alerts))
        self.assertEqual("H1", alerts[0].timeframe)

    def test_setup_alert_title_uses_h1_context_not_m15_trigger(self) -> None:
        config = load_config()
        env = RuntimeEnv(
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
            live_evaluate_intrabar=False,
            chart_url_base="http://127.0.0.1:5173",
            account_label="Test",
            account_profile="personal",
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
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            conn = connect(db_path)
            try:
                init_db(conn)
                queue_setup_alerts(
                    conn,
                    config,
                    env,
                    [
                        {
                            "id": "candidate-m15-trigger",
                            "timeframe": "M15",
                            "playbook": "zone_reaction_v2",
                            "direction": "long",
                            "status": "waiting_confirmation",
                            "entry": 4112.791,
                            "stop_loss": 4085.95656,
                            "take_profit": [4179.8771],
                            "metadata": {"zone_type": "fvg"},
                            "reason": ["Reaction V2: slow_reaction."],
                        }
                    ],
                )
                alerts = pending_alerts(conn)
                message = format_alert_message(alerts[0])
            finally:
                conn.close()

        self.assertEqual(1, len(alerts))
        self.assertEqual("H1", alerts[0].timeframe)
        self.assertTrue(message.startswith("[XAUUSD H1] [WAIT] zone-reaction-v2 LONG"))
        self.assertIn("Zone type: FVG", message)
        self.assertIn("Context H1 / trigger M15", message)

    def test_blocked_setup_alert_includes_block_reason(self) -> None:
        config = load_config()
        env = RuntimeEnv(
            mt5_login=None,
            mt5_password=None,
            mt5_server=None,
            mt5_path=None,
            mt5_symbol="XAUUSDm",
            mt5_magic=260612,
            telegram_token=None,
            telegram_chat_id=None,
            execution_enabled=False,
            live_order_volume=0.01,
            max_open_positions_per_symbol=1,
            max_trades_per_day=10,
            poll_seconds=15.0,
            poll_at_seconds=(1, 16, 31, 46),
            max_entry_drift_price=2.0,
            max_spread_price=2.0,
            live_evaluate_intrabar=False,
            chart_url_base="http://127.0.0.1:5173",
            account_label="Test",
            account_profile="personal",
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
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            conn = connect(db_path)
            try:
                init_db(conn)
                queue_setup_alerts(
                    conn,
                    config,
                    env,
                    [
                        {
                            "id": "candidate-blocked-macro",
                            "timeframe": "M15",
                            "playbook": "zone_reaction_v2",
                            "direction": "long",
                            "status": "blocked",
                            "entry": 4024.95,
                            "stop_loss": 3997.59,
                            "take_profit": [4093.36],
                            "reason": ["Reaction V2: reject."],
                            "blocked_reason": ["Macro trend down blocks Zone Reaction V2 long."],
                        }
                    ],
                )
                alerts = pending_alerts(conn)
                message = format_alert_message(alerts[0])
            finally:
                conn.close()

        self.assertEqual(1, len(alerts))
        self.assertEqual("watch", alerts[0].severity)
        self.assertTrue(message.startswith("[XAUUSD H1] [BLOCK] zone-reaction-v2 LONG"))
        self.assertIn("Macro trend down blocks Zone Reaction V2 long.", message)

    def test_runtime_env_reads_dotenv_without_overwriting_process_env(self) -> None:
        previous_symbol = os.environ.get("MT5_SYMBOL")
        os.environ["MT5_SYMBOL"] = "XAUUSDcustom"
        try:
            with TemporaryDirectory() as temp_dir:
                env_path = Path(temp_dir) / ".env"
                env_path.write_text(
                    "\n".join(
                        [
                            'MT5_LOGIN="123"',
                            'MT5_PASSWORD="secret"',
                            'MT5_SERVER="Exness-Test"',
                            'MT5_PATH="C:\\Program Files\\MetaTrader 5 EXNESS\\terminal64.exe"',
                            'MT5_SYMBOL="XAUUSDm"',
                            'EXECUTION_ENABLED="true"',
                            'LIVE_ORDER_VOLUME="0.02"',
                            'LIVE_EVALUATE_INTRABAR="true"',
                        ]
                    )
                )

                env = load_runtime_env(env_path)

            self.assertEqual(123, env.mt5_login)
            self.assertEqual("secret", env.mt5_password)
            self.assertEqual("Exness-Test", env.mt5_server)
            self.assertEqual(r"C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe", env.mt5_path)
            self.assertEqual("XAUUSDcustom", env.mt5_symbol)
            self.assertTrue(env.execution_enabled)
            self.assertEqual(0.02, env.live_order_volume)
            self.assertTrue(env.live_evaluate_intrabar)
        finally:
            if previous_symbol is None:
                os.environ.pop("MT5_SYMBOL", None)
            else:
                os.environ["MT5_SYMBOL"] = previous_symbol

    def test_live_worker_evaluates_setups_even_without_new_closed_candle(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            config = replace(load_config(), database=db_path)
            closed_at = datetime(2026, 6, 19, 5, 15, tzinfo=UTC)
            conn = connect(db_path)
            try:
                init_db(conn)
                upsert_candles(
                    conn,
                    [
                        Candle(
                            symbol=config.symbol,
                            timeframe=config.strategy.timeframe,
                            open_time=closed_at,
                            close_time=closed_at + timedelta(minutes=15),
                            open=4220,
                            high=4230,
                            low=4210,
                            close=4225,
                            volume=1,
                            source="test",
                        )
                    ],
                )
            finally:
                conn.close()

            env = RuntimeEnv(
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
                live_evaluate_intrabar=False,
                chart_url_base="http://127.0.0.1:5173",
                account_label="Test",
                account_profile="personal",
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
            state = LiveWorkerState(
                broker_symbol="XAUUSDm",
                last_closed_m15=closed_at.isoformat(),
            )
            execute_calls: list[list[dict[str, object]]] = []

            class FakeClient:
                pass

            with (
                patch("semi_bot_trading.live_worker.sync_mt5_candles"),
                patch("semi_bot_trading.live_worker.sync_closed_positions"),
                patch("semi_bot_trading.live_worker.run_live_detectors") as detectors,
                patch(
                    "semi_bot_trading.live_worker.build_chart_payload",
                    return_value={"layers": {"setup_candidates": [{"id": "candidate-1", "status": "eligible"}]}},
                ) as build_payload,
                patch("semi_bot_trading.live_worker.queue_setup_alerts"),
                patch("semi_bot_trading.live_worker.send_pending_telegram_alerts"),
                patch(
                    "semi_bot_trading.live_worker.maybe_execute_candidates",
                    side_effect=lambda _conn, _config, _env, _client, candidates, _symbol: execute_calls.append(candidates),
                ),
            ):
                run_live_iteration(config, env, FakeClient(), state)

            detectors.assert_not_called()
            build_payload.assert_called_once()
            self.assertEqual({"H1"}, build_payload.call_args.kwargs["candidate_zone_timeframes"])
            self.assertFalse(build_payload.call_args.kwargs["include_live_strategy_candle"])
            self.assertEqual([[{"id": "candidate-1", "status": "eligible"}]], execute_calls)

    def test_live_worker_passes_intrabar_flag_to_setup_evaluation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            config = replace(load_config(), database=db_path)
            closed_at = datetime(2026, 1, 1, 0, 15, tzinfo=UTC)
            conn = connect(db_path)
            try:
                init_db(conn)
                upsert_candles(
                    conn,
                    [
                        Candle(
                            symbol=config.symbol,
                            timeframe=config.strategy.timeframe,
                            open_time=closed_at,
                            close_time=closed_at + timedelta(minutes=15),
                            open=4220,
                            high=4230,
                            low=4210,
                            close=4225,
                            volume=1,
                            source="test",
                        )
                    ],
                )
            finally:
                conn.close()

            env = RuntimeEnv(
                mt5_login=None,
                mt5_password=None,
                mt5_server=None,
                mt5_path=None,
                mt5_symbol="XAUUSDm",
                mt5_magic=260612,
                telegram_token=None,
                telegram_chat_id=None,
                execution_enabled=False,
                live_order_volume=0.01,
                max_open_positions_per_symbol=1,
                max_trades_per_day=10,
                poll_seconds=15,
                poll_at_seconds=(1, 16, 31, 46),
                max_entry_drift_price=2.0,
                max_spread_price=2.0,
                live_evaluate_intrabar=True,
                chart_url_base="http://127.0.0.1:5173",
                account_label="Test",
                account_profile="personal",
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
            state = LiveWorkerState(broker_symbol="XAUUSDm", last_closed_m15=closed_at.isoformat())

            class FakeClient:
                pass

            with (
                patch("semi_bot_trading.live_worker.sync_mt5_candles"),
                patch("semi_bot_trading.live_worker.sync_closed_positions"),
                patch("semi_bot_trading.live_worker.run_live_detectors"),
                patch("semi_bot_trading.live_worker.snapshot_account"),
                patch("semi_bot_trading.live_worker.snapshot_spread"),
                patch("semi_bot_trading.live_worker.build_chart_payload", return_value={"layers": {"setup_candidates": []}}) as build_payload,
                patch("semi_bot_trading.live_worker.queue_setup_alerts"),
                patch("semi_bot_trading.live_worker.send_pending_telegram_alerts"),
            ):
                run_live_iteration(config, env, FakeClient(), state)

        self.assertTrue(build_payload.call_args.kwargs["include_live_strategy_candle"])

    def test_run_live_detectors_only_builds_zones_for_bias_timeframe(self) -> None:
        # H1 is the only zone/context timeframe. M15 must still get swing/break
        # structure (it remains the strategy trigger timeframe) but must never
        # get SR or SMC price_zones generated for it.
        config = load_config()
        self.assertEqual("H1", config.bias.timeframe)
        self.assertEqual("M15", config.strategy.timeframe)

        with (
            patch("semi_bot_trading.live_worker.detect_and_store_swing_structure") as swing,
            patch("semi_bot_trading.live_worker.detect_and_store_break_structure") as breaks,
            patch("semi_bot_trading.live_worker.detect_and_store_bias"),
            patch("semi_bot_trading.live_worker.detect_and_store_macro_trend"),
            patch("semi_bot_trading.live_worker.detect_and_store_regime"),
            patch("semi_bot_trading.live_worker.detect_and_store_support_resistance_zones") as sr_zones,
            patch("semi_bot_trading.live_worker.apply_and_store_zone_lifecycle") as lifecycle,
            patch("semi_bot_trading.live_worker.detect_and_store_smc_zones") as smc_zones,
            patch("semi_bot_trading.live_worker.detect_and_store_price_action_patterns"),
            patch("semi_bot_trading.live_worker._load_swing_ids", return_value=set()),
        ):
            run_live_detectors(conn=None, config=config, symbol=config.symbol)

            swing_timeframes = {call.args[2] for call in swing.call_args_list}
            break_timeframes = {call.args[2] for call in breaks.call_args_list}
            self.assertEqual({"H1", "M15"}, swing_timeframes)
            self.assertEqual({"H1", "M15"}, break_timeframes)

            sr_timeframes = {call.kwargs["timeframe"] for call in sr_zones.call_args_list}
            lifecycle_timeframes = {call.kwargs["timeframe"] for call in lifecycle.call_args_list}
            smc_timeframes = {call.kwargs["timeframe"] for call in smc_zones.call_args_list}
            self.assertEqual({"H1"}, sr_timeframes)
            self.assertEqual({"H1"}, lifecycle_timeframes)
            self.assertEqual({"H1"}, smc_timeframes)


    def test_init_db_removes_legacy_m15_price_zones_but_keeps_m15_candles(self) -> None:
        # H1 is the only zone/context timeframe. init_db's migration must
        # hard-delete any legacy M15 price_zones row, while leaving M15
        # candles/structure_points untouched (M15 remains the trigger timeframe).
        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            conn = connect(db_path)
            try:
                init_db(conn)
                now = datetime.now(UTC).isoformat()
                conn.execute(
                    """
                    INSERT INTO price_zones (
                        id, symbol, timeframe, detector, zone_type, direction,
                        price_low, price_high, start_time, valid_from, detected_at, status, source
                    ) VALUES (?, 'XAUUSD', 'M15', 'sr_v2', 'support', 'bullish', 100, 102, ?, ?, ?, 'active', 'bot')
                    """,
                    ("legacy-m15-zone", now, now, now),
                )
                conn.execute(
                    """
                    INSERT INTO price_zones (
                        id, symbol, timeframe, detector, zone_type, direction,
                        price_low, price_high, start_time, valid_from, detected_at, status, source
                    ) VALUES (?, 'XAUUSD', 'H1', 'sr_v2', 'support', 'bullish', 100, 102, ?, ?, ?, 'active', 'bot')
                    """,
                    ("h1-zone", now, now, now),
                )
                conn.execute(
                    """
                    INSERT INTO structure_points (
                        id, symbol, timeframe, detector, status, point_type, price, event_time,
                        confidence, related_zone_ids_json, metadata_json
                    ) VALUES ('m15-swing', 'XAUUSD', 'M15', 'swing_v1', 'confirmed', 'swing_high', 101, ?, 1.0, '[]', '{}')
                    """,
                    (now,),
                )
                upsert_candles(
                    conn,
                    [
                        Candle(
                            symbol="XAUUSD",
                            timeframe="M15",
                            open_time=datetime(2026, 6, 1, tzinfo=UTC),
                            close_time=datetime(2026, 6, 1, 0, 15, tzinfo=UTC),
                            open=100,
                            high=102,
                            low=99,
                            close=101,
                            volume=1,
                            source="test",
                        )
                    ],
                )
                conn.commit()

                # Re-running init_db (as the worker does on every startup) must be
                # idempotent and must not touch M15 candles/structure.
                init_db(conn)

                zone_rows = conn.execute("SELECT id, timeframe FROM price_zones ORDER BY id").fetchall()
                candle_count = conn.execute(
                    "SELECT COUNT(*) AS c FROM candles WHERE symbol = 'XAUUSD' AND timeframe = 'M15'"
                ).fetchone()["c"]
                structure_count = conn.execute(
                    "SELECT COUNT(*) AS c FROM structure_points WHERE symbol = 'XAUUSD' AND timeframe = 'M15'"
                ).fetchone()["c"]
            finally:
                conn.close()

        self.assertEqual([("h1-zone", "H1")], [(row["id"], row["timeframe"]) for row in zone_rows])
        self.assertEqual(1, candle_count)
        self.assertEqual(1, structure_count)


if __name__ == "__main__":
    unittest.main()
