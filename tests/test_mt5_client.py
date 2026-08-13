from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from semi_bot_trading.mt5_client import (
    MT5BrokerClient,
    MT5Credentials,
    MT5OrderRequest,
    mt5_server_timestamp_to_utc,
    utc_datetime_to_mt5_server_time,
)


class MT5TimestampNormalizationTest(unittest.TestCase):
    def test_subtracts_positive_broker_server_offset(self) -> None:
        encoded_ftmo_time = int(datetime(2026, 7, 17, 15, 43, 4, tzinfo=UTC).timestamp())

        actual_utc = mt5_server_timestamp_to_utc(encoded_ftmo_time, 3)

        self.assertEqual(datetime(2026, 7, 17, 12, 43, 4, tzinfo=UTC), actual_utc)

    def test_history_boundary_adds_ftmo_server_offset(self) -> None:
        real_utc = datetime(2026, 8, 13, 13, 40, 16, tzinfo=UTC)

        actual = utc_datetime_to_mt5_server_time(real_utc, 3)

        self.assertEqual(datetime(2026, 8, 13, 16, 40, 16, tzinfo=UTC), actual)

    def test_history_boundary_keeps_exness_utc_unchanged(self) -> None:
        real_utc = datetime(2026, 8, 13, 13, 40, 16, tzinfo=UTC)

        actual = utc_datetime_to_mt5_server_time(real_utc, 0)

        self.assertEqual(real_utc, actual)

    def test_balance_history_query_uses_account_server_clock(self) -> None:
        mt5 = MagicMock()
        mt5.history_deals_get.return_value = []
        client = MT5BrokerClient.__new__(MT5BrokerClient)
        client.mt5 = mt5
        client.credentials = MT5Credentials(123, "secret", "FTMO-Server3", server_utc_offset_hours=3)
        start = datetime(2026, 8, 12, 22, 0, tzinfo=UTC)

        client.balance_change_since(start)

        history_start, history_end = mt5.history_deals_get.call_args.args
        self.assertEqual(datetime(2026, 8, 13, 1, 0, tzinfo=UTC), history_start)
        self.assertAlmostEqual(
            3 * 60 * 60,
            (history_end - datetime.now(UTC)).total_seconds(),
            delta=2,
        )

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
    def test_pending_order_state_prefers_active_order_book(self) -> None:
        mt5 = MagicMock()
        mt5.orders_get.return_value = [SimpleNamespace(ticket=22)]
        client = MT5BrokerClient.__new__(MT5BrokerClient)
        client.mt5 = mt5
        client.ensure_symbol = MagicMock()

        self.assertEqual("pending", client.get_pending_order_state("XAUUSD", order_ticket="22"))
        mt5.history_orders_get.assert_not_called()

    def test_pending_order_state_distinguishes_fill_from_broker_expiry(self) -> None:
        mt5 = MagicMock()
        mt5.ORDER_STATE_FILLED = 4
        mt5.ORDER_STATE_CANCELED = 2
        mt5.ORDER_STATE_EXPIRED = 6
        mt5.ORDER_STATE_REJECTED = 3
        mt5.orders_get.return_value = []
        mt5.history_orders_get.return_value = [SimpleNamespace(ticket=22, state=4, time_done_msc=100)]
        client = MT5BrokerClient.__new__(MT5BrokerClient)
        client.mt5 = mt5
        client.ensure_symbol = MagicMock()

        self.assertEqual("filled", client.get_pending_order_state("XAUUSD", order_ticket="22"))

        mt5.history_orders_get.return_value = [SimpleNamespace(ticket=22, state=6, time_done_msc=200)]
        self.assertEqual("cancelled", client.get_pending_order_state("XAUUSD", order_ticket="22"))

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


class MT5LimitOrderExpirationTest(unittest.TestCase):
    def _client(self, *, expiration_mode: int) -> tuple[MT5BrokerClient, MagicMock]:
        mt5 = MagicMock()
        mt5.TRADE_ACTION_PENDING = 5
        mt5.ORDER_TYPE_BUY_LIMIT = 2
        mt5.ORDER_TYPE_SELL_LIMIT = 3
        mt5.ORDER_TIME_GTC = 0
        mt5.ORDER_TIME_SPECIFIED = 2
        mt5.SYMBOL_EXPIRATION_SPECIFIED = 4
        mt5.TRADE_RETCODE_DONE = 10009
        mt5.TRADE_RETCODE_PLACED = 10008
        mt5.TRADE_RETCODE_INVALID_EXPIRATION = 10022
        mt5.symbol_info.return_value = SimpleNamespace(visible=True, expiration_mode=expiration_mode)
        client = MT5BrokerClient.__new__(MT5BrokerClient)
        client.mt5 = mt5
        client.ensure_symbol = MagicMock()
        client.order_filling_mode = MagicMock(return_value=0)
        return client, mt5

    @staticmethod
    def _request() -> MT5OrderRequest:
        return MT5OrderRequest(
            broker_symbol="XAUUSD",
            side="buy",
            volume=0.57,
            entry_price=4341.8,
            stop_loss=4324.5,
            take_profit=4370.5,
            comment="manual_ai_v1 test",
            magic=260720,
            expires_at="2099-08-07T15:54:54+00:00",
        )

    def test_uses_specified_expiration_when_symbol_supports_it(self) -> None:
        client, mt5 = self._client(expiration_mode=4)
        result = MagicMock()
        result._asdict.return_value = {"retcode": 10009, "order": 123}
        mt5.order_send.return_value = result

        client.place_limit_order(self._request())

        payload = mt5.order_send.call_args.args[0]
        self.assertEqual(2, payload["type_time"])
        self.assertEqual(int(datetime(2099, 8, 7, 15, 54, 54, tzinfo=UTC).timestamp()), payload["expiration"])

    def test_uses_gtc_when_symbol_does_not_support_specified_expiration(self) -> None:
        client, mt5 = self._client(expiration_mode=1)
        result = MagicMock()
        result._asdict.return_value = {"retcode": 10009, "order": 123}
        mt5.order_send.return_value = result

        client.place_limit_order(self._request())

        payload = mt5.order_send.call_args.args[0]
        self.assertEqual(0, payload["type_time"])
        self.assertNotIn("expiration", payload)
        mt5.order_send.assert_called_once()

    def test_retries_invalid_specified_expiration_once_as_gtc(self) -> None:
        client, mt5 = self._client(expiration_mode=4)
        rejected = MagicMock()
        rejected._asdict.return_value = {"retcode": 10022, "order": 0, "deal": 0}
        placed = MagicMock()
        placed._asdict.return_value = {"retcode": 10009, "order": 456}
        mt5.order_send.side_effect = [rejected, placed]

        data = client.place_limit_order(self._request())

        self.assertEqual(2, mt5.order_send.call_count)
        first_payload = mt5.order_send.call_args_list[0].args[0]
        second_payload = mt5.order_send.call_args_list[1].args[0]
        self.assertEqual(2, first_payload["type_time"])
        self.assertIn("expiration", first_payload)
        self.assertEqual(0, second_payload["type_time"])
        self.assertNotIn("expiration", second_payload)
        self.assertEqual("gtc", data["expiration_fallback"])

    def test_does_not_retry_other_broker_rejections(self) -> None:
        client, mt5 = self._client(expiration_mode=4)
        rejected = MagicMock()
        rejected._asdict.return_value = {"retcode": 10016, "order": 0, "deal": 0}
        mt5.order_send.return_value = rejected

        with self.assertRaisesRegex(RuntimeError, "retcode=10016"):
            client.place_limit_order(self._request())

        mt5.order_send.assert_called_once()

    def test_does_not_fallback_to_gtc_after_plan_expired(self) -> None:
        client, mt5 = self._client(expiration_mode=4)
        rejected = MagicMock()
        rejected._asdict.return_value = {"retcode": 10022, "order": 0, "deal": 0}
        mt5.order_send.return_value = rejected
        request = self._request()
        request = MT5OrderRequest(**{**request.__dict__, "expires_at": "2020-01-01T00:00:00+00:00"})

        with self.assertRaisesRegex(ValueError, "at least 30 seconds"):
            client.place_limit_order(request)

        mt5.order_send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
