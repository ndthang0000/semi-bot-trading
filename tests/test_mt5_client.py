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

    def test_closed_position_costs_include_open_and_close_deals(self) -> None:
        encoded_open_time = int(datetime(2026, 7, 23, 1, 15, 1, tzinfo=UTC).timestamp())
        encoded_close_time = int(datetime(2026, 7, 23, 3, 11, 52, tzinfo=UTC).timestamp())
        mt5 = MagicMock()
        mt5.history_deals_get.return_value = [
            SimpleNamespace(
                entry=0,
                volume=0.46,
                price=4125.13,
                profit=0.0,
                swap=0.0,
                commission=-1.33,
                fee=-0.10,
                time=encoded_open_time,
                ticket=1001,
            ),
            SimpleNamespace(
                entry=1,
                volume=0.46,
                price=4127.08,
                profit=89.70,
                swap=0.0,
                commission=-1.33,
                fee=-0.15,
                time=encoded_close_time,
                ticket=1002,
            ),
        ]
        client = MT5BrokerClient.__new__(MT5BrokerClient)
        client.mt5 = mt5
        client.credentials = MT5Credentials(123, "secret", "FTMO-Server3", server_utc_offset_hours=3)

        deal = client.get_closed_deal_for_position("169691716")

        self.assertIsNotNone(deal)
        self.assertAlmostEqual(89.70, deal["profit"])
        self.assertAlmostEqual(-2.66, deal["commission"])
        self.assertAlmostEqual(-0.25, deal["fee"])


class MT5BotOwnershipTest(unittest.TestCase):
    def test_counts_only_matching_magic(self) -> None:
        mt5 = MagicMock()
        mt5.positions_get.return_value = [SimpleNamespace(magic=7), SimpleNamespace(magic=0), SimpleNamespace(magic=7)]
        mt5.orders_get.return_value = [SimpleNamespace(magic=0), SimpleNamespace(magic=7)]
        client = MT5BrokerClient.__new__(MT5BrokerClient)
        client.mt5 = mt5

        self.assertEqual((2, 1), client.bot_order_counts("XAUUSD", magic=7))

    def test_cancel_pending_orders_leaves_manual_orders_untouched(self) -> None:
        mt5 = MagicMock()
        mt5.TRADE_ACTION_REMOVE = 8
        mt5.TRADE_RETCODE_DONE = 10009
        mt5.orders_get.return_value = [
            SimpleNamespace(ticket=11, magic=0),
            SimpleNamespace(ticket=22, magic=7),
        ]
        send_result = MagicMock()
        send_result._asdict.return_value = {"retcode": 10009, "order": 22}
        mt5.order_send.return_value = send_result
        client = MT5BrokerClient.__new__(MT5BrokerClient)
        client.mt5 = mt5
        client.ensure_symbol = MagicMock()

        results = client.cancel_pending_orders("XAUUSD", magic=7)

        self.assertEqual(1, len(results))
        self.assertEqual(22, mt5.order_send.call_args.args[0]["order"])

    def test_close_positions_with_no_magic_includes_human(self) -> None:
        mt5 = MagicMock()
        mt5.POSITION_TYPE_BUY = 0
        mt5.ORDER_TYPE_SELL = 1
        mt5.ORDER_TYPE_BUY = 0
        mt5.TRADE_ACTION_DEAL = 1
        mt5.ORDER_TIME_GTC = 0
        mt5.TRADE_RETCODE_DONE = 10009
        mt5.positions_get.return_value = [
            SimpleNamespace(ticket=11, magic=0, type=0, volume=0.1),
            SimpleNamespace(ticket=22, magic=7, type=0, volume=0.2),
        ]
        send_result = MagicMock()
        send_result._asdict.return_value = {"retcode": 10009}
        mt5.order_send.return_value = send_result
        client = MT5BrokerClient.__new__(MT5BrokerClient)
        client.mt5 = mt5
        client.ensure_symbol = MagicMock()
        client.order_filling_mode = MagicMock(return_value=0)
        client.current_price_for_side = MagicMock(return_value=4000.0)

        results = client.close_open_positions("XAUUSD", magic=None)

        self.assertEqual(2, len(results))
        self.assertEqual([11, 22], [call.args[0]["position"] for call in mt5.order_send.call_args_list])


if __name__ == "__main__":
    unittest.main()
