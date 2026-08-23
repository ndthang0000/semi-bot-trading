from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path("config/trading.toml")


@dataclass(frozen=True)
class SwingConfig:
    window: int
    tolerance: float


@dataclass(frozen=True)
class BreakConfig:
    close_break_buffer: float


@dataclass(frozen=True)
class BiasConfig:
    timeframe: str
    recent_swings: int
    recent_breaks: int


@dataclass(frozen=True)
class MacroTrendConfig:
    timeframe: str
    lookback_candles: int
    flat_threshold_atr: float
    atr_period: int


@dataclass(frozen=True)
class RegimeConfig:
    timeframe: str
    atr_period: int
    lookback: int
    atr_high_percentile: float
    atr_low_percentile: float
    expansion_atr_ratio: float
    contraction_atr_ratio: float
    trend_break_ratio: float
    trend_min_bos: int
    range_efficiency_max: float


@dataclass(frozen=True)
class SupportResistanceConfig:
    tolerance_pct: float
    min_zone_width: float
    atr_width_multiplier: float
    min_touches: int
    lookback_swings: int
    max_zones: int


@dataclass(frozen=True)
class ZoneLifecycleConfig:
    close_break_buffer: float
    close_break_buffer_atr_multiplier: float
    recent_touch_lookback_candles: int
    age_decay_per_100_candles: float
    freshness_bonus: float
    invalidation_weight_multiplier: float
    false_break_refine_enabled: bool
    false_break_refine_max_width_atr_multiplier: float
    false_break_parent_weight_multiplier: float


@dataclass(frozen=True)
class ZoneReactionConfig:
    reaction_window_candles: int
    min_reaction_atr: float
    strong_reaction_atr: float
    recent_reaction_count: int
    follow_through_close_required: bool


@dataclass(frozen=True)
class ZoneDecayConfig:
    max_healthy_touches: int
    weak_touch_penalty: float
    too_many_touches_penalty: float
    linger_penalty: float


@dataclass(frozen=True)
class SmcZoneConfig:
    max_candles: int
    lookback_swings: int
    fvg_middle_candle_atr_multiplier: float
    fvg_gap_atr_ratio: float
    fvg_min_width_atr_ratio: float
    fvg_max_width_atr_ratio: float
    fvg_third_candle_follow_through_required: bool
    fvg_third_candle_min_body_ratio: float
    fvg_h1_max_active_days: float
    fvg_h1_decay_start_days: float
    fvg_m15_max_active_days: float
    fvg_m15_decay_start_days: float
    ob_displacement_atr_multiplier: float
    ob_min_body_ratio: float
    ob_min_width_atr_ratio: float
    ob_max_width_atr_ratio: float
    ob_require_structure_break: bool
    ob_merge_overlap_ratio: float
    ob_h1_max_active_days: float
    ob_h1_decay_start_days: float
    ob_m15_max_active_days: float
    ob_m15_decay_start_days: float
    max_fvg_zones: int
    max_order_block_zones: int
    max_liquidity_zones: int
    max_consolidation_zones: int

    def fvg_max_active_days_for(self, timeframe: str) -> float:
        return self.fvg_m15_max_active_days if timeframe.upper() == "M15" else self.fvg_h1_max_active_days

    def fvg_decay_start_days_for(self, timeframe: str) -> float:
        return self.fvg_m15_decay_start_days if timeframe.upper() == "M15" else self.fvg_h1_decay_start_days

    def ob_max_active_days_for(self, timeframe: str) -> float:
        return self.ob_m15_max_active_days if timeframe.upper() == "M15" else self.ob_h1_max_active_days

    def ob_decay_start_days_for(self, timeframe: str) -> float:
        return self.ob_m15_decay_start_days if timeframe.upper() == "M15" else self.ob_h1_decay_start_days


@dataclass(frozen=True)
class PriceActionConfig:
    timeframe: str
    atr_period: int
    displacement_atr_multiplier: float
    displacement_body_ratio: float
    pinbar_wick_body_ratio: float
    pinbar_min_wick_ratio: float
    engulfing_min_body_ratio: float
    marubozu_min_body_ratio: float
    star_large_body_ratio: float
    star_small_body_ratio: float


@dataclass(frozen=True)
class StrategyConfig:
    timeframe: str
    atr_period: int
    approach_atr_multiplier: float
    breakout_buffer_atr_multiplier: float
    waiting_candles: int
    min_risk_reward: float
    max_eligible: int
    max_waiting: int
    zone_reaction_v2_enabled: bool
    zone_reaction_v2_allowed_reactions: tuple[str, ...]
    zone_reaction_v2_fakeout_max_atr: float
    zone_reaction_v2_reject_recovery_min_avg_body_ratio: float
    zone_reaction_v2_reject_avg_body_period: int
    zone_reaction_v2_reject_h1_touch_required: bool
    zone_reaction_v2_reject_h1_touch_lookback_bars: int
    zone_reaction_v2_slow_min_bars: int
    zone_reaction_v2_slow_max_bars: int
    zone_reaction_v2_slow_body_max_ratio: float
    zone_reaction_v2_reject_stop_mode: str
    zone_reaction_v2_rr_minimum: float
    zone_reaction_v2_stop_buffer_atr: float
    zone_reaction_v2_min_stop_price: float
    zone_reaction_v2_min_stop_atr: float
    zone_reaction_v2_max_stop_distance: float
    zone_reaction_v2_reject_wide_stop_fallback: str
    zone_reaction_v2_reject_atr_stop: float
    zone_reaction_v2_impulse_limit_extension_atr: float
    zone_reaction_v2_impulse_limit_expiry_bars: int
    zone_reaction_v2_require_trigger_for_fakeout: bool
    zone_reaction_v2_fakeout_max_reaction_depth_atr: float
    zone_reaction_v2_internal_reject_enabled: bool
    zone_reaction_v2_internal_reject_requires_structure: bool
    zone_reaction_v2_internal_reject_sr_requires_structure: bool
    zone_reaction_v2_internal_reject_requires_price_action: bool
    zone_reaction_v2_internal_reject_watch_after_fvg_fill_bars: int
    zone_reaction_v2_internal_reject_min_fill_ratio: float
    zone_reaction_v2_internal_reject_deep_fvg_fill_ratio: float
    zone_reaction_v2_internal_reject_stop_buffer_atr: float
    zone_reaction_v2_allow_neutral_range_trade: bool
    zone_reaction_v2_block_news_or_risk_off: bool
    zone_reaction_v2_macro_gate_enabled: bool
    zone_reaction_v2_fvg_macro_gate_enabled: bool  # separate gate for FVG zones
    zone_reaction_v2_fvg_max_trades_per_zone: int
    zone_reaction_v2_confluence_score_bonus: float
    sr_breakout_v1_enabled: bool
    sr_breakout_v1_allowed_entries: tuple[str, ...]
    sr_breakout_v1_allow_bot_sr_breakout: bool
    sr_breakout_v1_breakout_buffer_atr: float
    sr_breakout_v1_market_entry_max_distance_atr: float
    sr_breakout_v1_retest_max_bars: int
    sr_breakout_v1_min_body_atr: float
    sr_breakout_v1_sl_mode: str
    sr_breakout_v1_sl_zone_buffer_atr: float
    sr_breakout_v1_sl_min_atr: float
    sr_breakout_v1_sl_atr: float
    sr_breakout_v1_rr: float
    sr_breakout_v1_max_stop_distance: float
    liquidity_sweep_reclaim_v1_enabled: bool = True
    liquidity_sweep_reclaim_v1_timeout_minutes: int = 15
    liquidity_sweep_reclaim_v1_max_sweep_atr: float = 1.0
    liquidity_sweep_reclaim_v1_sl_buffer_atr: float = 0.2
    h1_impulse_retest_v1_atr_period: int = 14
    h1_impulse_retest_v1_stop_buffer_atr: float = 0.1
    h1_impulse_retest_v1_min_stop_atr: float = 0.5
    h1_impulse_retest_v1_max_stop_atr: float = 1.2
    h1_impulse_retest_v1_min_body_atr: float = 0.8
    h1_impulse_retest_v1_min_range_atr: float = 0.9
    h1_impulse_retest_v1_max_range_atr: float = 2.5
    h1_impulse_retest_v1_min_body_range_ratio: float = 0.6
    h1_impulse_retest_v1_min_close_location: float = 0.75
    h1_impulse_retest_v1_max_close_side_wick_ratio: float = 0.2
    h1_impulse_retest_v1_expiry_medium_body_atr: float = 1.2
    h1_impulse_retest_v1_expiry_large_body_atr: float = 1.6
    h1_impulse_retest_v1_expiry_hours_small: int = 6
    h1_impulse_retest_v1_expiry_hours_medium: int = 12
    h1_impulse_retest_v1_expiry_hours_large: int = 18


@dataclass(frozen=True)
class BacktestConfig:
    spread: float
    slippage: float
    max_hold_candles: int
    warmup_candles: int
    auto_accept: bool
    zone_snapshot_candles: int
    zone_loss_cooldown_candles: int


@dataclass(frozen=True)
class AppConfig:
    path: Path
    symbol: str
    data_dir: Path
    database: Path
    swing_timeframes: dict[str, SwingConfig]
    breaks: BreakConfig
    bias: BiasConfig
    macro_trend: MacroTrendConfig
    regime: RegimeConfig
    support_resistance: SupportResistanceConfig
    zone_lifecycle: ZoneLifecycleConfig
    zone_reaction: ZoneReactionConfig
    zone_decay: ZoneDecayConfig
    smc_zones: SmcZoneConfig
    price_action: PriceActionConfig
    strategy: StrategyConfig
    backtest: BacktestConfig

    def swing_for(self, timeframe: str) -> SwingConfig:
        key = timeframe.upper()
        if key not in self.swing_timeframes:
            known = ", ".join(sorted(self.swing_timeframes))
            raise ValueError(f"No swing config for timeframe {timeframe}. Known: {known}")
        return self.swing_timeframes[key]


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> AppConfig:
    config_path = Path(path)
    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    app = raw.get("app", {})
    data = raw.get("data", {})
    structure = raw.get("structure", {})
    context = raw.get("context", {})
    zones = raw.get("zones", {})
    price_action = raw.get("price_action", {})
    strategy = raw.get("strategy", {})
    strategy_playbooks = strategy.get("playbooks", {})
    zone_reaction_v2 = strategy_playbooks.get("zone_reaction_v2", {}) if isinstance(strategy_playbooks, dict) else {}
    sr_breakout_v1 = strategy_playbooks.get("sr_breakout_v1", {}) if isinstance(strategy_playbooks, dict) else {}
    liquidity_sweep_reclaim_v1 = (
        strategy_playbooks.get("liquidity_sweep_reclaim_v1", {})
        if isinstance(strategy_playbooks, dict)
        else {}
    )
    h1_impulse_retest_v1 = (
        strategy_playbooks.get("h1_impulse_retest_v1", {})
        if isinstance(strategy_playbooks, dict)
        else {}
    )
    backtest = raw.get("backtest", {})
    swing = structure.get("swing", {})
    breaks = structure.get("breaks", {})
    bias = context.get("bias", {})
    macro_trend = context.get("macro_trend", {})
    regime = context.get("regime", {})
    support_resistance = zones.get("support_resistance", {})
    zone_lifecycle = zones.get("lifecycle", {})
    zone_reaction = zones.get("reaction", {})
    zone_decay = zones.get("decay", {})
    smc_zones = zones.get("smc", {})
    swing_timeframes = swing.get("timeframes", {})
    default_tolerance = float(swing.get("tolerance", 0.0))

    return AppConfig(
        path=config_path,
        symbol=str(app.get("symbol", "XAUUSD")),
        data_dir=Path(data.get("directory", "data")),
        database=Path(data.get("database", "var/trading.sqlite3")),
        swing_timeframes=parse_swing_timeframes(swing_timeframes, default_tolerance),
        breaks=BreakConfig(close_break_buffer=float(breaks.get("close_break_buffer", 0.0))),
        bias=BiasConfig(
            timeframe=str(bias.get("timeframe", "H1")).upper(),
            recent_swings=int(bias.get("recent_swings", 6)),
            recent_breaks=int(bias.get("recent_breaks", 3)),
        ),
        macro_trend=MacroTrendConfig(
            timeframe=str(macro_trend.get("timeframe", "H1")).upper(),
            lookback_candles=int(macro_trend.get("lookback_candles", 720)),
            flat_threshold_atr=float(macro_trend.get("flat_threshold_atr", 0.0)),
            atr_period=int(macro_trend.get("atr_period", 14)),
        ),
        regime=RegimeConfig(
            timeframe=str(regime.get("timeframe", "H1")).upper(),
            atr_period=int(regime.get("atr_period", 14)),
            lookback=int(regime.get("lookback", 50)),
            atr_high_percentile=float(regime.get("atr_high_percentile", 0.80)),
            atr_low_percentile=float(regime.get("atr_low_percentile", 0.20)),
            expansion_atr_ratio=float(regime.get("expansion_atr_ratio", 1.20)),
            contraction_atr_ratio=float(regime.get("contraction_atr_ratio", 0.80)),
            trend_break_ratio=float(regime.get("trend_break_ratio", 0.60)),
            trend_min_bos=int(regime.get("trend_min_bos", 2)),
            range_efficiency_max=float(regime.get("range_efficiency_max", 0.25)),
        ),
        support_resistance=SupportResistanceConfig(
            tolerance_pct=float(support_resistance.get("tolerance_pct", 0.0015)),
            min_zone_width=float(support_resistance.get("min_zone_width", 1.0)),
            atr_width_multiplier=float(support_resistance.get("atr_width_multiplier", 0.0)),
            min_touches=int(support_resistance.get("min_touches", 2)),
            lookback_swings=int(support_resistance.get("lookback_swings", 300)),
            max_zones=int(support_resistance.get("max_zones", 40)),
        ),
        zone_lifecycle=ZoneLifecycleConfig(
            close_break_buffer=float(zone_lifecycle.get("close_break_buffer", 0.0)),
            close_break_buffer_atr_multiplier=float(zone_lifecycle.get("close_break_buffer_atr_multiplier", 0.0)),
            recent_touch_lookback_candles=int(zone_lifecycle.get("recent_touch_lookback_candles", 80)),
            age_decay_per_100_candles=float(zone_lifecycle.get("age_decay_per_100_candles", 0.08)),
            freshness_bonus=float(zone_lifecycle.get("freshness_bonus", 0.15)),
            invalidation_weight_multiplier=float(zone_lifecycle.get("invalidation_weight_multiplier", 0.15)),
            false_break_refine_enabled=bool(zone_lifecycle.get("false_break_refine_enabled", True)),
            false_break_refine_max_width_atr_multiplier=float(
                zone_lifecycle.get("false_break_refine_max_width_atr_multiplier", 0.8)
            ),
            false_break_parent_weight_multiplier=float(zone_lifecycle.get("false_break_parent_weight_multiplier", 0.35)),
        ),
        zone_reaction=ZoneReactionConfig(
            reaction_window_candles=int(zone_reaction.get("reaction_window_candles", 5)),
            min_reaction_atr=float(zone_reaction.get("min_reaction_atr", 0.8)),
            strong_reaction_atr=float(zone_reaction.get("strong_reaction_atr", 1.5)),
            recent_reaction_count=int(zone_reaction.get("recent_reaction_count", 3)),
            follow_through_close_required=bool(zone_reaction.get("follow_through_close_required", True)),
        ),
        zone_decay=ZoneDecayConfig(
            max_healthy_touches=int(zone_decay.get("max_healthy_touches", 3)),
            weak_touch_penalty=float(zone_decay.get("weak_touch_penalty", 0.08)),
            too_many_touches_penalty=float(zone_decay.get("too_many_touches_penalty", 0.06)),
            linger_penalty=float(zone_decay.get("linger_penalty", 0.10)),
        ),
        smc_zones=SmcZoneConfig(
            max_candles=int(smc_zones.get("max_candles", 5000)),
            lookback_swings=int(smc_zones.get("lookback_swings", 300)),
            fvg_middle_candle_atr_multiplier=float(smc_zones.get("fvg_middle_candle_atr_multiplier", 2.0)),
            fvg_gap_atr_ratio=float(smc_zones.get("fvg_gap_atr_ratio", 0.25)),
            fvg_min_width_atr_ratio=float(smc_zones.get("fvg_min_width_atr_ratio", 1.0)),
            fvg_max_width_atr_ratio=float(smc_zones.get("fvg_max_width_atr_ratio", 1.5)),
            fvg_third_candle_follow_through_required=bool(
                smc_zones.get("fvg_third_candle_follow_through_required", True)
            ),
            fvg_third_candle_min_body_ratio=float(smc_zones.get("fvg_third_candle_min_body_ratio", 0.20)),
            fvg_h1_max_active_days=float(smc_zones.get("fvg_h1_max_active_days", 2.0)),
            fvg_h1_decay_start_days=float(smc_zones.get("fvg_h1_decay_start_days", 0.75)),
            fvg_m15_max_active_days=float(smc_zones.get("fvg_m15_max_active_days", 1.0)),
            fvg_m15_decay_start_days=float(smc_zones.get("fvg_m15_decay_start_days", 0.5)),
            ob_displacement_atr_multiplier=float(smc_zones.get("ob_displacement_atr_multiplier", 1.5)),
            ob_min_body_ratio=float(smc_zones.get("ob_min_body_ratio", 0.60)),
            ob_min_width_atr_ratio=float(smc_zones.get("ob_min_width_atr_ratio", 0.05)),
            ob_max_width_atr_ratio=float(smc_zones.get("ob_max_width_atr_ratio", 1.0)),
            ob_require_structure_break=bool(smc_zones.get("ob_require_structure_break", True)),
            ob_merge_overlap_ratio=float(smc_zones.get("ob_merge_overlap_ratio", 0.60)),
            ob_h1_max_active_days=float(smc_zones.get("ob_h1_max_active_days", 3.0)),
            ob_h1_decay_start_days=float(smc_zones.get("ob_h1_decay_start_days", 1.0)),
            ob_m15_max_active_days=float(smc_zones.get("ob_m15_max_active_days", 2.0)),
            ob_m15_decay_start_days=float(smc_zones.get("ob_m15_decay_start_days", 1.0)),
            max_fvg_zones=int(smc_zones.get("max_fvg_zones", 80)),
            max_order_block_zones=int(smc_zones.get("max_order_block_zones", 60)),
            max_liquidity_zones=int(smc_zones.get("max_liquidity_zones", 80)),
            max_consolidation_zones=int(smc_zones.get("max_consolidation_zones", 30)),
        ),
        price_action=PriceActionConfig(
            timeframe=str(price_action.get("timeframe", "M15")).upper(),
            atr_period=int(price_action.get("atr_period", 14)),
            displacement_atr_multiplier=float(price_action.get("displacement_atr_multiplier", 1.5)),
            displacement_body_ratio=float(price_action.get("displacement_body_ratio", 0.60)),
            pinbar_wick_body_ratio=float(price_action.get("pinbar_wick_body_ratio", 2.0)),
            pinbar_min_wick_ratio=float(price_action.get("pinbar_min_wick_ratio", 0.55)),
            engulfing_min_body_ratio=float(price_action.get("engulfing_min_body_ratio", 0.45)),
            marubozu_min_body_ratio=float(price_action.get("marubozu_min_body_ratio", 0.75)),
            star_large_body_ratio=float(price_action.get("star_large_body_ratio", 0.45)),
            star_small_body_ratio=float(price_action.get("star_small_body_ratio", 0.35)),
        ),
        strategy=StrategyConfig(
            timeframe=str(strategy.get("timeframe", "M15")).upper(),
            atr_period=int(strategy.get("atr_period", 14)),
            approach_atr_multiplier=float(strategy.get("approach_atr_multiplier", 0.5)),
            breakout_buffer_atr_multiplier=float(strategy.get("breakout_buffer_atr_multiplier", 0.15)),
            waiting_candles=int(strategy.get("waiting_candles", 4)),
            min_risk_reward=float(strategy.get("min_risk_reward", 2.0)),
            max_eligible=int(strategy.get("max_eligible", 3)),
            max_waiting=int(strategy.get("max_waiting", 5)),
            zone_reaction_v2_enabled=bool(zone_reaction_v2.get("enabled", True)),
            zone_reaction_v2_allowed_reactions=tuple(
                str(item)
                for item in zone_reaction_v2.get(
                    "allowed_reactions",
                    ["reject"],
                )
            ),
            zone_reaction_v2_fakeout_max_atr=float(zone_reaction_v2.get("fakeout_max_atr", 0.5)),
            zone_reaction_v2_reject_recovery_min_avg_body_ratio=float(
                zone_reaction_v2.get("reject_recovery_min_avg_body_ratio", 2.0)
            ),
            zone_reaction_v2_reject_avg_body_period=int(zone_reaction_v2.get("reject_avg_body_period", 20)),
            zone_reaction_v2_reject_h1_touch_required=bool(
                zone_reaction_v2.get("reject_h1_touch_required", False)
            ),
            zone_reaction_v2_reject_h1_touch_lookback_bars=max(
                int(zone_reaction_v2.get("reject_h1_touch_lookback_bars", 3)),
                1,
            ),
            zone_reaction_v2_slow_min_bars=int(zone_reaction_v2.get("slow_min_bars", 3)),
            zone_reaction_v2_slow_max_bars=int(zone_reaction_v2.get("slow_max_bars", 8)),
            zone_reaction_v2_slow_body_max_ratio=float(zone_reaction_v2.get("slow_body_max_ratio", 0.8)),
            zone_reaction_v2_reject_stop_mode=str(zone_reaction_v2.get("reject_stop_mode", "zone")).lower(),
            zone_reaction_v2_rr_minimum=float(zone_reaction_v2.get("rr_minimum", 2.0)),
            zone_reaction_v2_stop_buffer_atr=float(zone_reaction_v2.get("stop_buffer_atr", 0.2)),
            zone_reaction_v2_min_stop_price=float(zone_reaction_v2.get("min_stop_price", 4.0)),
            zone_reaction_v2_min_stop_atr=float(zone_reaction_v2.get("min_stop_atr", 1.5)),
            zone_reaction_v2_max_stop_distance=float(zone_reaction_v2.get("max_stop_distance", 25.0)),
            zone_reaction_v2_reject_wide_stop_fallback=str(
                zone_reaction_v2.get("reject_wide_stop_fallback", "atr")
            ).lower(),
            zone_reaction_v2_reject_atr_stop=float(zone_reaction_v2.get("reject_atr_stop", 1.2)),
            zone_reaction_v2_impulse_limit_extension_atr=float(
                zone_reaction_v2.get("impulse_limit_extension_atr", 2.0)
            ),
            zone_reaction_v2_impulse_limit_expiry_bars=int(
                zone_reaction_v2.get("impulse_limit_expiry_bars", 8)
            ),
            zone_reaction_v2_require_trigger_for_fakeout=bool(zone_reaction_v2.get("require_trigger_for_fakeout", True)),
            zone_reaction_v2_fakeout_max_reaction_depth_atr=float(
                zone_reaction_v2.get("fakeout_max_reaction_depth_atr", 1.5)
            ),
            zone_reaction_v2_internal_reject_enabled=bool(zone_reaction_v2.get("internal_reject_enabled", True)),
            zone_reaction_v2_internal_reject_requires_structure=bool(
                zone_reaction_v2.get("internal_reject_requires_structure", True)
            ),
            zone_reaction_v2_internal_reject_sr_requires_structure=bool(
                zone_reaction_v2.get("internal_reject_sr_requires_structure", True)
            ),
            zone_reaction_v2_internal_reject_requires_price_action=bool(
                zone_reaction_v2.get("internal_reject_requires_price_action", True)
            ),
            zone_reaction_v2_internal_reject_watch_after_fvg_fill_bars=int(
                zone_reaction_v2.get("internal_reject_watch_after_fvg_fill_bars", 8)
            ),
            zone_reaction_v2_internal_reject_min_fill_ratio=float(
                zone_reaction_v2.get("internal_reject_min_fill_ratio", 0.4)
            ),
            zone_reaction_v2_internal_reject_deep_fvg_fill_ratio=float(
                zone_reaction_v2.get("internal_reject_deep_fvg_fill_ratio", 0.8)
            ),
            zone_reaction_v2_internal_reject_stop_buffer_atr=float(
                zone_reaction_v2.get("internal_reject_stop_buffer_atr", 0.4)
            ),
            zone_reaction_v2_allow_neutral_range_trade=bool(zone_reaction_v2.get("allow_neutral_range_trade", True)),
            zone_reaction_v2_block_news_or_risk_off=bool(zone_reaction_v2.get("block_news_or_risk_off", True)),
            zone_reaction_v2_macro_gate_enabled=bool(zone_reaction_v2.get("macro_gate_enabled", True)),
            zone_reaction_v2_fvg_macro_gate_enabled=bool(zone_reaction_v2.get("fvg_macro_gate_enabled", True)),
            zone_reaction_v2_fvg_max_trades_per_zone=int(zone_reaction_v2.get("fvg_max_trades_per_zone", 2)),
            zone_reaction_v2_confluence_score_bonus=float(zone_reaction_v2.get("confluence_score_bonus", 0.08)),
            sr_breakout_v1_enabled=bool(sr_breakout_v1.get("enabled", True)),
            sr_breakout_v1_allowed_entries=tuple(
                str(item) for item in sr_breakout_v1.get("allowed_entries", ["retest_breakout"])
            ),
            sr_breakout_v1_allow_bot_sr_breakout=bool(sr_breakout_v1.get("allow_bot_sr_breakout", False)),
            sr_breakout_v1_breakout_buffer_atr=float(sr_breakout_v1.get("breakout_buffer_atr", 0.15)),
            sr_breakout_v1_market_entry_max_distance_atr=float(
                sr_breakout_v1.get("market_entry_max_distance_atr", 0.5)
            ),
            sr_breakout_v1_retest_max_bars=int(sr_breakout_v1.get("retest_max_bars", 8)),
            sr_breakout_v1_min_body_atr=float(sr_breakout_v1.get("min_body_atr", 0.5)),
            sr_breakout_v1_sl_mode=str(sr_breakout_v1.get("sl_mode", "atr")).lower(),
            sr_breakout_v1_sl_zone_buffer_atr=float(sr_breakout_v1.get("sl_zone_buffer_atr", 0.2)),
            sr_breakout_v1_sl_min_atr=float(sr_breakout_v1.get("sl_min_atr", 0.6)),
            sr_breakout_v1_sl_atr=float(sr_breakout_v1.get("sl_atr", 1.5)),
            sr_breakout_v1_rr=float(sr_breakout_v1.get("rr", 2.0)),
            sr_breakout_v1_max_stop_distance=float(sr_breakout_v1.get("max_stop_distance", 60.0)),
            liquidity_sweep_reclaim_v1_enabled=bool(liquidity_sweep_reclaim_v1.get("enabled", True)),
            liquidity_sweep_reclaim_v1_timeout_minutes=int(
                liquidity_sweep_reclaim_v1.get("timeout_minutes", 15)
            ),
            liquidity_sweep_reclaim_v1_max_sweep_atr=float(
                liquidity_sweep_reclaim_v1.get("max_sweep_atr", 1.0)
            ),
            liquidity_sweep_reclaim_v1_sl_buffer_atr=float(
                liquidity_sweep_reclaim_v1.get("sl_buffer_atr", 0.2)
            ),
            h1_impulse_retest_v1_atr_period=int(h1_impulse_retest_v1.get("atr_period", 14)),
            h1_impulse_retest_v1_stop_buffer_atr=float(h1_impulse_retest_v1.get("stop_buffer_atr", 0.1)),
            h1_impulse_retest_v1_min_stop_atr=float(h1_impulse_retest_v1.get("min_stop_atr", 0.5)),
            h1_impulse_retest_v1_max_stop_atr=float(h1_impulse_retest_v1.get("max_stop_atr", 1.2)),
            h1_impulse_retest_v1_min_body_atr=float(h1_impulse_retest_v1.get("min_body_atr", 0.8)),
            h1_impulse_retest_v1_min_range_atr=float(h1_impulse_retest_v1.get("min_range_atr", 0.9)),
            h1_impulse_retest_v1_max_range_atr=float(h1_impulse_retest_v1.get("max_range_atr", 2.5)),
            h1_impulse_retest_v1_min_body_range_ratio=float(
                h1_impulse_retest_v1.get("min_body_range_ratio", 0.6)
            ),
            h1_impulse_retest_v1_min_close_location=float(
                h1_impulse_retest_v1.get("min_close_location", 0.75)
            ),
            h1_impulse_retest_v1_max_close_side_wick_ratio=float(
                h1_impulse_retest_v1.get("max_close_side_wick_ratio", 0.2)
            ),
            h1_impulse_retest_v1_expiry_medium_body_atr=float(
                h1_impulse_retest_v1.get("expiry_medium_body_atr", 1.2)
            ),
            h1_impulse_retest_v1_expiry_large_body_atr=float(
                h1_impulse_retest_v1.get("expiry_large_body_atr", 1.6)
            ),
            h1_impulse_retest_v1_expiry_hours_small=int(h1_impulse_retest_v1.get("expiry_hours_small", 6)),
            h1_impulse_retest_v1_expiry_hours_medium=int(h1_impulse_retest_v1.get("expiry_hours_medium", 12)),
            h1_impulse_retest_v1_expiry_hours_large=int(h1_impulse_retest_v1.get("expiry_hours_large", 18)),
        ),
        backtest=BacktestConfig(
            spread=float(backtest.get("spread", 0.30)),
            slippage=float(backtest.get("slippage", 0.10)),
            max_hold_candles=int(backtest.get("max_hold_candles", 96)),
            warmup_candles=int(backtest.get("warmup_candles", 80)),
            auto_accept=bool(backtest.get("auto_accept", True)),
            zone_snapshot_candles=int(backtest.get("zone_snapshot_candles", 600)),
            zone_loss_cooldown_candles=int(backtest.get("zone_loss_cooldown_candles", 12)),
        ),
    )


def parse_swing_timeframes(raw: dict[str, Any], default_tolerance: float) -> dict[str, SwingConfig]:
    result: dict[str, SwingConfig] = {}
    for tf, cfg in raw.items():
        result[tf.upper()] = SwingConfig(
            window=int(cfg.get("window", 4)),
            tolerance=float(cfg.get("tolerance", default_tolerance)),
        )
    return result
