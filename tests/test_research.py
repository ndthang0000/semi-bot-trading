from __future__ import annotations

import unittest

from semi_bot_trading.research import potential_condition_sets, split_for_time, summarize_research


class ResearchTest(unittest.TestCase):
    def test_split_for_time_uses_train_validation_test_years(self) -> None:
        self.assertEqual("train", split_for_time("2024-12-31T23:00:00+00:00", 2024, 2025))
        self.assertEqual("validation", split_for_time("2025-06-01T00:00:00+00:00", 2024, 2025))
        self.assertEqual("test", split_for_time("2026-01-01T00:00:00+00:00", 2024, 2025))

    def test_summarize_research_groups_rows_and_computes_r_metrics(self) -> None:
        rows = [
            {"playbook": "trend_pullback", "pnl_r": "2", "mfe_r": "2.5", "mae_r": "-0.5"},
            {"playbook": "trend_pullback", "pnl_r": "-1", "mfe_r": "0.4", "mae_r": "-1.1"},
            {"playbook": "fvg_fill_go", "pnl_r": "1", "mfe_r": "1.2", "mae_r": "-0.2"},
        ]

        summary = summarize_research(rows, lambda row: row["playbook"])
        by_key = {row.key: row for row in summary}

        self.assertEqual(2, by_key["trend_pullback"].samples)
        self.assertEqual(1, by_key["trend_pullback"].wins)
        self.assertEqual(1, by_key["trend_pullback"].losses)
        self.assertEqual(1.0, by_key["trend_pullback"].total_r)
        self.assertEqual(2.0, by_key["trend_pullback"].profit_factor)

    def test_potential_condition_sets_respects_min_samples(self) -> None:
        rows = [
            {
                "split": "train",
                "playbook": "trend_pullback",
                "direction": "long",
                "h1_bias": "bullish",
                "h1_regime": "trending",
                "zone_type": "support",
                "zone_reaction_state": "rejected",
                "trigger_types": "engulfing_bullish",
                "zone_width_atr": "2.0",
                "overlays": "expansion",
                "pnl_r": "1",
                "mfe_r": "1",
                "mae_r": "-0.2",
            }
            for _ in range(3)
        ]

        self.assertEqual([], potential_condition_sets(rows, min_samples=4))
        self.assertTrue(potential_condition_sets(rows, min_samples=3))


if __name__ == "__main__":
    unittest.main()
