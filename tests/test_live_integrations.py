from __future__ import annotations

import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from semi_bot_trading.candles import Candle, upsert_candles
from semi_bot_trading.config import load_config
from semi_bot_trading.alerts import pending_alerts, queue_alert
from semi_bot_trading.db import connect, init_db
from semi_bot_trading.live_worker import LiveWorkerState, run_live_iteration
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
                live_evaluate_intrabar=False,
                chart_url_base="http://127.0.0.1:5173",
                account_profile="personal",
                risk_per_trade_pct=None,
                secret_key="",
                admin_username="admin",
                admin_password_hash=None,
                allowed_origins=[],
                environment="development",
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
            self.assertEqual([[{"id": "candidate-1", "status": "eligible"}]], execute_calls)


if __name__ == "__main__":
    unittest.main()
