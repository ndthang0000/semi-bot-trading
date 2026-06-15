from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from semi_bot_trading.alerts import pending_alerts, queue_alert
from semi_bot_trading.db import connect, init_db
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
        finally:
            if previous_symbol is None:
                os.environ.pop("MT5_SYMBOL", None)
            else:
                os.environ["MT5_SYMBOL"] = previous_symbol


if __name__ == "__main__":
    unittest.main()
