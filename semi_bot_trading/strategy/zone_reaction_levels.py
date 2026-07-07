from __future__ import annotations

from typing import Any

from ..config import StrategyConfig
from .types import ReactionResult


def compute_zone_reaction_v2_levels(
    zone: dict[str, Any],
    direction: str,
    reaction: ReactionResult,
    last_close: float,
    atr: float,
    config: StrategyConfig,
    stop_fallback_atr: float | None = None,
    stop_fallback_atr_timeframe: str | None = None,
    level_metadata: dict[str, Any] | None = None,
) -> tuple[float | None, float | None, list[float], float | None]:
    metadata = reaction.metadata
    level_metadata = level_metadata if level_metadata is not None else {}
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    reaction_low = float(metadata.get("reaction_low", zone_low))
    reaction_high = float(metadata.get("reaction_high", zone_high))
    buffer = max(atr * config.zone_reaction_v2_stop_buffer_atr, 0.01)
    min_stop_distance = max(config.zone_reaction_v2_min_stop_price, atr * config.zone_reaction_v2_min_stop_atr)
    target_rr = config.zone_reaction_v2_rr_minimum
    entry = round(last_close, 5)
    wick_stop_states = {"retest_reject", "internal_reject"}
    if config.zone_reaction_v2_reject_stop_mode == "reaction_wick":
        wick_stop_states = wick_stop_states | {"reject"}
    stop_source = "reaction_wick" if reaction.state in wick_stop_states else "zone"
    fallback_atr = stop_fallback_atr if stop_fallback_atr is not None else atr
    fallback_atr_timeframe = stop_fallback_atr_timeframe or "strategy"
    if direction == "long":
        wick_natural_stop = reaction_low - buffer
        zone_natural_stop = min(zone_low, reaction_low) - buffer
        natural_stop = wick_natural_stop if reaction.state in wick_stop_states else zone_natural_stop
        stop = round(min(natural_stop, entry - min_stop_distance), 5)
        if should_fallback_reject_stop_to_wick(reaction, config, entry, stop):
            stop = round(min(wick_natural_stop, entry - min_stop_distance), 5)
            stop_source = "reaction_wick"
        if should_fallback_wide_stop_to_atr(reaction, config, entry, stop) or _wick_stop_inside_zone(
            zone, direction, stop_source, stop
        ):
            stop = round(entry - _reject_atr_stop_distance(fallback_atr, min_stop_distance, config), 5)
            stop_source = "atr_fallback"
        if _should_fallback_fvg_stop_to_atr(zone, config, entry, stop):
            stop = round(entry - _reject_atr_stop_distance(fallback_atr, min_stop_distance, config), 5)
            stop_source = "atr_fallback"
        risk = entry - stop
        if risk <= 0:
            _write_level_metadata(level_metadata, stop_source, fallback_atr, fallback_atr_timeframe, config)
            return entry, stop, [], None
        take_profit = [round(entry + risk * target_rr, 5)]
    else:
        wick_natural_stop = reaction_high + buffer
        zone_natural_stop = max(zone_high, reaction_high) + buffer
        natural_stop = wick_natural_stop if reaction.state in wick_stop_states else zone_natural_stop
        stop = round(max(natural_stop, entry + min_stop_distance), 5)
        if should_fallback_reject_stop_to_wick(reaction, config, entry, stop):
            stop = round(max(wick_natural_stop, entry + min_stop_distance), 5)
            stop_source = "reaction_wick"
        if should_fallback_wide_stop_to_atr(reaction, config, entry, stop) or _wick_stop_inside_zone(
            zone, direction, stop_source, stop
        ):
            stop = round(entry + _reject_atr_stop_distance(fallback_atr, min_stop_distance, config), 5)
            stop_source = "atr_fallback"
        if _should_fallback_fvg_stop_to_atr(zone, config, entry, stop):
            stop = round(entry + _reject_atr_stop_distance(fallback_atr, min_stop_distance, config), 5)
            stop_source = "atr_fallback"
        risk = stop - entry
        if risk <= 0:
            _write_level_metadata(level_metadata, stop_source, fallback_atr, fallback_atr_timeframe, config)
            return entry, stop, [], None
        take_profit = [round(entry - risk * target_rr, 5)]
    _write_level_metadata(level_metadata, stop_source, fallback_atr, fallback_atr_timeframe, config)
    return entry, stop, take_profit, round(target_rr, 4)


def should_fallback_reject_stop_to_wick(
    reaction: ReactionResult,
    config: StrategyConfig,
    entry: float,
    zone_mode_stop: float,
) -> bool:
    return (
        reaction.state == "reject"
        and config.zone_reaction_v2_reject_stop_mode == "zone"
        and config.zone_reaction_v2_max_stop_distance > 0
        and abs(entry - zone_mode_stop) > config.zone_reaction_v2_max_stop_distance
    )


def should_fallback_wide_stop_to_atr(
    reaction: ReactionResult,
    config: StrategyConfig,
    entry: float,
    current_stop: float,
) -> bool:
    return (
        reaction.state in {"reject", "internal_reject", "slow_reaction", "waiting_bos", "retest_reject", "fakeout"}
        and config.zone_reaction_v2_reject_wide_stop_fallback == "atr"
        and config.zone_reaction_v2_max_stop_distance > 0
        and abs(entry - current_stop) > config.zone_reaction_v2_max_stop_distance
    )


should_fallback_reject_stop_to_atr = should_fallback_wide_stop_to_atr


def _write_level_metadata(
    level_metadata: dict[str, Any],
    stop_source: str,
    stop_fallback_atr: float,
    stop_fallback_atr_timeframe: str,
    config: StrategyConfig,
) -> None:
    level_metadata.update(
        {
            "stop_source": stop_source,
            "stop_fallback_atr": round(stop_fallback_atr, 5),
            "stop_fallback_atr_timeframe": stop_fallback_atr_timeframe,
            "stop_fallback_atr_multiplier": config.zone_reaction_v2_reject_atr_stop,
        }
    )


def _should_fallback_fvg_stop_to_atr(
    zone: dict[str, Any],
    config: StrategyConfig,
    entry: float,
    current_stop: float,
) -> bool:
    return (
        str(zone.get("type")) == "fvg"
        and config.zone_reaction_v2_reject_wide_stop_fallback == "atr"
        and config.zone_reaction_v2_max_stop_distance > 0
        and abs(entry - current_stop) > config.zone_reaction_v2_max_stop_distance
    )


def _wick_stop_inside_zone(zone: dict[str, Any], direction: str, stop_source: str, stop: float) -> bool:
    if stop_source != "reaction_wick":
        return False
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    if direction == "long":
        return stop >= zone_low
    return stop <= zone_high


def _reject_atr_stop_distance(atr: float, min_stop_distance: float, config: StrategyConfig) -> float:
    return max(min_stop_distance, atr * config.zone_reaction_v2_reject_atr_stop)
