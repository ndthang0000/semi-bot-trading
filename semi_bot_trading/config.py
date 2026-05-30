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
    min_touches: int
    lookback_swings: int
    max_zones: int


@dataclass(frozen=True)
class ZoneLifecycleConfig:
    close_break_buffer: float
    recent_touch_lookback_candles: int
    age_decay_per_100_candles: float
    freshness_bonus: float
    invalidation_weight_multiplier: float


@dataclass(frozen=True)
class AppConfig:
    path: Path
    symbol: str
    data_dir: Path
    database: Path
    swing_timeframes: dict[str, SwingConfig]
    breaks: BreakConfig
    bias: BiasConfig
    regime: RegimeConfig
    support_resistance: SupportResistanceConfig
    zone_lifecycle: ZoneLifecycleConfig

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
    swing = structure.get("swing", {})
    breaks = structure.get("breaks", {})
    bias = context.get("bias", {})
    regime = context.get("regime", {})
    support_resistance = zones.get("support_resistance", {})
    zone_lifecycle = zones.get("lifecycle", {})
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
            min_touches=int(support_resistance.get("min_touches", 2)),
            lookback_swings=int(support_resistance.get("lookback_swings", 300)),
            max_zones=int(support_resistance.get("max_zones", 40)),
        ),
        zone_lifecycle=ZoneLifecycleConfig(
            close_break_buffer=float(zone_lifecycle.get("close_break_buffer", 0.0)),
            recent_touch_lookback_candles=int(zone_lifecycle.get("recent_touch_lookback_candles", 80)),
            age_decay_per_100_candles=float(zone_lifecycle.get("age_decay_per_100_candles", 0.08)),
            freshness_bonus=float(zone_lifecycle.get("freshness_bonus", 0.15)),
            invalidation_weight_multiplier=float(zone_lifecycle.get("invalidation_weight_multiplier", 0.15)),
        ),
    )


def parse_swing_timeframes(raw: dict[str, Any], default_tolerance: float) -> dict[str, SwingConfig]:
    result: dict[str, SwingConfig] = {}
    for timeframe, values in raw.items():
        if not isinstance(values, dict):
            raise ValueError(f"Invalid swing timeframe config for {timeframe}")
        result[timeframe.upper()] = SwingConfig(
            window=int(values["window"]),
            tolerance=float(values.get("tolerance", default_tolerance)),
        )
    return result
