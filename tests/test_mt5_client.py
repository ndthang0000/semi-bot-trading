from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from semi_bot_trading.mt5_client import MT5BrokerClient, MT5Credentials, mt5_server_timestamp_to_utc


class MT5TimestampNormalizationTest(unittest.TestCase):
    def test_subtracts_positive_broker_server_offset(self) -> None:
        encoded_ftmo_time = int(datetime(2026, 7, 17, 15, 43, 4, tzinfo=UTC).timestamp())

        actual_utc = mt5_server_timestamp_to_utc(encoded_ftmo_time, 3)

        self.assertEqual(datetime(2026, 7, 17, 12, 43, 4, tzinfo=UTC), actual_utc)

    def test_closed_deal_uses_configured_server_offset(self) -> None:
        encoded_ftmo_time = int(datetime(2026, 7, 17, 15, 43, 4, tzinfo=UTC).timestamp())
        mt5 = MagicMock()
        mt5.history_deals_get.return_value = [
            SimpleNamespace(
                entry=1,
                volume=0.57,
                price=3969.39,
                profit=-983.69,
                swap=0.0,
                commission=0.0,
                time=encoded_ftmo_time,
                ticket=12345,
            )
        ]
        client = MT5BrokerClient.__new__(MT5BrokerClient)
        client.mt5 = mt5
        client.credentials = MT5Credentials(123, "secret", "FTMO-Demo", server_utc_offset_hours=3)

        deal = client.get_closed_deal_for_position("498045241")

        self.assertIsNotNone(deal)
        self.assertEqual("2026-07-17T12:43:04+00:00", deal["time_iso"])


if __name__ == "__main__":
    unittest.main()
