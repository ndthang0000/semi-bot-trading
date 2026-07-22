from __future__ import annotations

import unittest
from pathlib import Path

from semi_bot_trading.cli import build_parser, normalize_report_output_path


class CliTest(unittest.TestCase):
    def test_normalizes_windows_style_html_report_path(self) -> None:
        path = normalize_report_output_path(Path(r"var\reports\zone_reaction.html"))

        self.assertEqual(Path("var/reports/zone_reaction.html"), path)

    def test_recovers_zsh_collapsed_report_path(self) -> None:
        path = normalize_report_output_path(Path("varreportszone_reaction.html"))

        self.assertEqual(Path("var/reports/zone_reaction.html"), path)

    def test_generate_trade_report_parser(self) -> None:
        args = build_parser().parse_args(
            ["generate-trade-report", "--zone-id", "zone-123", "--output", "var/reports"]
        )

        self.assertEqual("zone-123", args.zone_id)
        self.assertEqual(Path("var/reports"), args.output)
        self.assertEqual("Asia/Ho_Chi_Minh", args.timezone)


if __name__ == "__main__":
    unittest.main()
