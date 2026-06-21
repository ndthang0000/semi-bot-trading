from __future__ import annotations

import unittest
from pathlib import Path

from semi_bot_trading.cli import normalize_report_output_path


class CliTest(unittest.TestCase):
    def test_normalizes_windows_style_html_report_path(self) -> None:
        path = normalize_report_output_path(Path(r"var\reports\zone_reaction.html"))

        self.assertEqual(Path("var/reports/zone_reaction.html"), path)

    def test_recovers_zsh_collapsed_report_path(self) -> None:
        path = normalize_report_output_path(Path("varreportszone_reaction.html"))

        self.assertEqual(Path("var/reports/zone_reaction.html"), path)


if __name__ == "__main__":
    unittest.main()
