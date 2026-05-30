from __future__ import annotations

import unittest

from semi_bot_trading.server import bool_query_value, first_query_value, int_query_value


class ServerQueryParsingTest(unittest.TestCase):
    def test_reads_first_query_value(self) -> None:
        self.assertEqual(first_query_value({"timeframe": ["M15", "H1"]}, "timeframe"), "M15")
        self.assertEqual(first_query_value({}, "symbol", "XAUUSD"), "XAUUSD")

    def test_reads_boolean_query_value(self) -> None:
        self.assertTrue(bool_query_value({"active_zones_only": ["true"]}, "active_zones_only"))
        self.assertTrue(bool_query_value({"active_zones_only": ["1"]}, "active_zones_only"))
        self.assertFalse(bool_query_value({"active_zones_only": ["false"]}, "active_zones_only"))
        self.assertFalse(bool_query_value({}, "active_zones_only"))

    def test_reads_integer_query_value(self) -> None:
        self.assertEqual(int_query_value({"limit": ["300"]}, "limit", 100), 300)
        self.assertEqual(int_query_value({}, "limit", 100), 100)


if __name__ == "__main__":
    unittest.main()
