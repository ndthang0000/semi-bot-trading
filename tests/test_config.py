from __future__ import annotations

import unittest
from pathlib import Path
from tests.helpers import TemporaryDirectory

from semi_bot_trading.config import load_config


class ConfigTest(unittest.TestCase):
    def test_default_macro_trend_uses_30_day_h1_lookback(self) -> None:
        config = load_config()

        self.assertEqual(720, config.macro_trend.lookback_candles)
        self.assertEqual(2.0, config.strategy.zone_reaction_v2_rr_minimum)
        self.assertEqual(2.0, config.strategy.sr_breakout_v1_rr)
        self.assertFalse(config.strategy.zone_reaction_v2_enabled)
        self.assertFalse(config.strategy.sr_breakout_v1_enabled)
        self.assertFalse(config.strategy.liquidity_sweep_reclaim_v1_enabled)
        self.assertFalse(config.strategy.manual_ai_v1_enabled)
        self.assertFalse(config.strategy.h1_impulse_retest_v1_enabled)
        self.assertTrue(config.strategy.line_reaction_v1_enabled)

    def test_loads_swing_timeframe_config(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "trading.toml"
            path.write_text(
                """
[app]
symbol = "XAUUSD"

[data]
directory = "data"
database = "var/test.sqlite3"

[structure.swing]
tolerance = 0.25

[structure.breaks]
close_break_buffer = 1.5

[context.regime]
timeframe = "H1"
atr_period = 14
lookback = 50
atr_high_percentile = 0.8
atr_low_percentile = 0.2
expansion_atr_ratio = 1.2
contraction_atr_ratio = 0.8
trend_break_ratio = 0.6
trend_min_bos = 2
range_efficiency_max = 0.25

[zones.support_resistance]
tolerance_pct = 0.002
min_zone_width = 2.0
min_touches = 3
lookback_swings = 100
max_zones = 20

[zones.lifecycle]
close_break_buffer = 0.5
recent_touch_lookback_candles = 40
age_decay_per_100_candles = 0.1
freshness_bonus = 0.2
invalidation_weight_multiplier = 0.2

[structure.swing.timeframes]
H1 = { window = 5 }
M15 = { window = 3, tolerance = 0.1 }
"""
            )

            config = load_config(path)

        self.assertEqual(config.symbol, "XAUUSD")
        self.assertEqual(config.database, Path("var/test.sqlite3"))
        self.assertEqual(config.swing_for("H1").window, 5)
        self.assertEqual(config.swing_for("H1").tolerance, 0.25)
        self.assertEqual(config.swing_for("m15").window, 3)
        self.assertEqual(config.swing_for("M15").tolerance, 0.1)
        self.assertEqual(config.breaks.close_break_buffer, 1.5)
        self.assertEqual(config.regime.lookback, 50)
        self.assertEqual(config.regime.trend_min_bos, 2)
        self.assertEqual(config.support_resistance.tolerance_pct, 0.002)
        self.assertEqual(config.support_resistance.atr_width_multiplier, 0.0)
        self.assertEqual(config.support_resistance.min_touches, 3)
        self.assertEqual(config.zone_lifecycle.close_break_buffer, 0.5)
        self.assertEqual(config.zone_lifecycle.close_break_buffer_atr_multiplier, 0.0)
        self.assertEqual(config.zone_lifecycle.freshness_bonus, 0.2)
        self.assertEqual(config.zone_reaction.reaction_window_candles, 5)
        self.assertEqual(config.zone_decay.max_healthy_touches, 3)
        self.assertEqual(config.smc_zones.fvg_max_active_days_for("H1"), 2.0)
        self.assertEqual(config.smc_zones.fvg_decay_start_days_for("M15"), 0.5)
        self.assertEqual(config.smc_zones.ob_max_active_days_for("H1"), 3.0)
        self.assertEqual(config.smc_zones.ob_decay_start_days_for("M15"), 1.0)
        self.assertEqual(config.strategy.timeframe, "M15")
        self.assertEqual(config.strategy.breakout_buffer_atr_multiplier, 0.15)
        self.assertEqual(config.strategy.min_risk_reward, 2.0)
        self.assertEqual(config.strategy.h1_impulse_retest_v1_wave_safe_fraction, 0.625)
        self.assertEqual(config.strategy.h1_impulse_retest_v1_min_wave_samples, 3)
        self.assertTrue(config.backtest.auto_accept)
        self.assertEqual(config.backtest.spread, 0.3)
        self.assertEqual(config.backtest.slippage, 0.1)
        self.assertEqual(config.backtest.zone_snapshot_candles, 600)


if __name__ == "__main__":
    unittest.main()
