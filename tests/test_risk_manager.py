from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from semi_bot_trading.db import connect, init_db
from semi_bot_trading.risk_manager import PROFILES, build_risk_manager
from tests.helpers import TemporaryDirectory


class FtmoDailyEquityRiskGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self._conn = connect(Path(self._tmp.name) / "risk.sqlite3")
        init_db(self._conn)
        self._client = MagicMock()
        self._client.get_account_info.return_value = {"balance": 98_000.0, "equity": 95_000.0}
        self._client.get_symbol_trade_info.return_value = {
            "trade_contract_size": 100.0,
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
        }
        self._manager = build_risk_manager(self._client, "ftmo_challenge", 1.0)

    def tearDown(self) -> None:
        self._conn.close()
        self._tmp.cleanup()

    def _insert_metric(self, daily_profit: float, *, snapshot_at: str | None = None) -> None:
        now = snapshot_at or datetime.now(UTC).isoformat()
        self._conn.execute(
            """
            INSERT INTO account_daily_metrics (
                account_label, trading_day, timezone, day_start_utc,
                balance_at_midnight, current_balance, current_equity,
                daily_profit, daily_profit_pct, initial_balance,
                baseline_source, snapshot_at
            ) VALUES ('FTMO 100K', '2026-08-07', 'Europe/Prague', ?,
                      100000, 98000, 95000, ?, ?, 100000, 'mt5_deal_history', ?)
            """,
            (now, daily_profit, daily_profit / 1000.0, now),
        )
        self._conn.commit()

    def test_blocks_on_floating_loss_at_ftmo_daily_limit(self) -> None:
        self._insert_metric(-5_000.0)

        result = self._manager.assess_trade(
            self._conn, "XAUUSD", 3000.0, 2980.0, "XAUUSDm", account_label="FTMO 100K"
        )

        self.assertFalse(result.allowed)
        self.assertEqual(5_000.0, result.daily_loss)
        self.assertEqual(5_000.0, result.daily_loss_limit)

    def test_uses_remaining_equity_loss_budget_for_position_size(self) -> None:
        self._insert_metric(-4_500.0)

        result = self._manager.assess_trade(
            self._conn, "XAUUSD", 3000.0, 2980.0, "XAUUSDm", account_label="FTMO 100K"
        )

        self.assertTrue(result.allowed)
        self.assertEqual(500.0, result.risk_amount)
        self.assertEqual(0.25, result.lot_size)

    def test_fails_closed_without_fresh_daily_metric(self) -> None:
        result = self._manager.assess_trade(
            self._conn, "XAUUSD", 3000.0, 2980.0, "XAUUSDm", account_label="FTMO 100K"
        )

        self.assertFalse(result.allowed)
        self.assertIn("metric is unavailable", result.reason)


class AccountProfileRiskDefaultsTest(unittest.TestCase):
    def test_prop_firm_and_personal_profiles_use_expected_risk(self) -> None:
        self.assertEqual(1.0, PROFILES["ftmo_challenge"].risk_per_trade_pct)
        self.assertEqual(1.0, PROFILES["the5ers"].risk_per_trade_pct)
        self.assertEqual(2.0, PROFILES["personal"].risk_per_trade_pct)
        self.assertEqual(2.0, PROFILES["personal_cent"].risk_per_trade_pct)


if __name__ == "__main__":
    unittest.main()
