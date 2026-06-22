from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..config import StrategyConfig
from ..indicators import latest_rsi_snapshot
from ..zones import latest_atr
from .helpers import (
    allowed_zone_types_for_playbooks,
    chart_candles_to_slices,
    latest_range,
    parse_overlays,
    playbook_allowed,
    status_rank,
    zone_eligible_for_sr_breakout_v1,
    zone_eligible_for_zone_reaction_v2,
    zone_trade_disabled_after_sweep,
)
from .sr_breakout_v1 import evaluate_sr_breakout_v1
from .types import SetupCandidate
from .zone_reaction_v2 import classify_zone_reaction_v2, evaluate_zone_reaction_v2


def build_setup_candidates(
    symbol: str,
    zones: list[dict[str, Any]],
    contexts: dict[str, dict[str, dict[str, Any]]],
    candles: list[dict[str, Any]],
    structure_points: list[dict[str, Any]],
    config: StrategyConfig,
    context_timeframe: str = "H1",
    allowed_playbooks: set[str] | None = None,
    context_candles: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not candles:
        return []
    candle_slices = chart_candles_to_slices(candles)
    atr = latest_atr(candle_slices, period=config.atr_period) or latest_range(candles) or 1.0
    context_slices = chart_candles_to_slices(context_candles or [])
    context_atr = (
        latest_atr(context_slices, period=config.atr_period)
        or latest_range(context_candles or [])
        or atr
    )
    context_atr_timeframe = context_timeframe if context_candles else config.timeframe
    last_candle = candles[-1]
    last_close = float(last_candle["close"])
    bias = contexts.get(context_timeframe, {}).get("bias", {})
    regime = contexts.get(context_timeframe, {}).get("regime", {})
    macro = contexts.get(context_timeframe, {}).get("macro_trend", {})
    bias_value = str(bias.get("effective_value") or "neutral")
    secondary_bias = bias.get("secondary_value")
    regime_value = str(regime.get("effective_value") or "unknown")
    macro_trend_value = str(macro.get("effective_value") or "unknown")
    overlays = parse_overlays(regime)

    recent_points = [point for point in structure_points if point.get("time") <= last_candle["time"]]
    candidates: list[SetupCandidate] = []
    allowed_zone_types = allowed_zone_types_for_playbooks(allowed_playbooks)
    playable_zones = [
        zone
        for zone in zones
        if (allowed_zone_types is None or str(zone.get("type")) in allowed_zone_types)
        and str(zone.get("timeframe") or context_timeframe).upper() == context_timeframe.upper()
        and not zone_trade_disabled_after_sweep(zone)
    ]

    active_reaction_zones = [
        zone for zone in playable_zones if zone_eligible_for_zone_reaction_v2(zone, candles, config)
    ]
    for zone in active_reaction_zones:
        # Zone Reaction V2 remains the reject-family playbook; breakout setups
        # are emitted by sr_breakout_v1 below so the two ideas stay isolated.
        if not playbook_allowed("zone_reaction_v2", allowed_playbooks):
            continue
        reaction_v2 = classify_zone_reaction_v2(zone, candles, atr, config)
        if reaction_v2.state == "far":
            continue
        candidates.extend(
            evaluate_zone_reaction_v2(
                symbol,
                zone,
                reaction_v2,
                last_close,
                atr,
                bias_value,
                secondary_bias,
                regime_value,
                overlays,
                recent_points,
                active_reaction_zones,
                config,
                as_of=str(last_candle["time"]),
                macro_trend=macro_trend_value,
                stop_fallback_atr=context_atr,
                stop_fallback_atr_timeframe=context_atr_timeframe,
            )
        )

    if playbook_allowed("sr_breakout_v1", allowed_playbooks):
        breakout_candles = context_candles or candles
        breakout_slices = chart_candles_to_slices(breakout_candles)
        breakout_atr = latest_atr(breakout_slices, period=config.atr_period) or latest_range(breakout_candles) or atr
        for zone in playable_zones:
            if not zone_eligible_for_sr_breakout_v1(zone, breakout_candles, config):
                continue
            candidates.extend(
                evaluate_sr_breakout_v1(
                    symbol=symbol,
                    zone=zone,
                    candles=breakout_candles,
                    atr=breakout_atr,
                    stop_atr=atr,
                    macro_trend=macro_trend_value,
                    bias=bias_value,
                    regime=regime_value,
                    config=config,
                )
            )

    if allowed_playbooks is not None:
        candidates = [candidate for candidate in candidates if candidate.playbook in allowed_playbooks]

    rsi_metadata = _h1_rsi_metadata(context_timeframe, context_candles)
    if rsi_metadata:
        candidates = [
            replace(candidate, metadata={**candidate.metadata, **rsi_metadata})
            for candidate in candidates
        ]

    ranked = sorted(candidates, key=lambda item: (status_rank(item.status), item.score), reverse=True)
    selected: list[SetupCandidate] = []
    eligible_count = 0
    waiting_count = 0
    blocked_count = 0
    for candidate in ranked:
        if candidate.status == "eligible":
            if eligible_count >= config.max_eligible:
                continue
            eligible_count += 1
        elif candidate.status in {"watching", "waiting_confirmation"}:
            if waiting_count >= config.max_waiting:
                continue
            waiting_count += 1
        elif candidate.status == "blocked":
            if blocked_count >= config.max_waiting:
                continue
            blocked_count += 1
        selected.append(candidate)

    return [candidate.to_chart() for candidate in selected]


def _h1_rsi_metadata(context_timeframe: str, context_candles: list[dict[str, Any]] | None) -> dict[str, Any]:
    if context_timeframe != "H1" or not context_candles:
        return {}
    snapshot = latest_rsi_snapshot(context_candles, period=14, slope_periods=(3, 5))
    return {
        "rsi_h1": snapshot.get("value"),
        "rsi_h1_slope_3": snapshot.get("slope_3"),
        "rsi_h1_slope_5": snapshot.get("slope_5"),
        "rsi_h1_as_of": snapshot.get("as_of"),
    }
