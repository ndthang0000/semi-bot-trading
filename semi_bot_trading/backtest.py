from __future__ import annotations

import json
import sys
import uuid
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import UTC, datetime
from sqlite3 import Connection
from typing import Any

from .chart import load_chart_zones
from .config import AppConfig
from .price_action import detect_price_action_patterns
from .replay_chart import (
    build_realtime_replay_payload,
    build_replay_contexts,
    chart_candles_to_slices,
    chart_candles_to_views,
    structure_point_to_chart,
    structure_points_to_swing_levels,
    structure_points_to_zone_swings,
    zone_to_chart,
)
from .smc_zones import detect_smc_zones
from .strategy import allowed_zone_types_for_playbooks, build_setup_candidates
from .structure import StructurePoint, detect_break_structure, detect_swing_structure
from .zones import PriceZone, apply_lifecycle_to_zones, detect_support_resistance_zones


STRATEGY_EVALUATION_WINDOW = 240
STRATEGY_POINT_WINDOW = 120
INCREMENTAL_CHUNK_SIZE = 10_000
INCREMENTAL_CHUNK_OVERLAP = 500


@dataclass(frozen=True)
class BacktestTrade:
    playbook: str
    direction: str
    status: str
    signal_time: str
    entry_time: str
    exit_time: str
    entry_price: float
    stop_loss: float
    take_profit: float
    exit_price: float
    pnl_r: float
    setup_id: str
    score: float
    risk_reward: float | None
    primary_zone_id: str | None
    related_zone_ids: list[str]
    trigger_point_ids: list[str]
    reason: list[str]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class BacktestResult:
    trades: list[BacktestTrade]
    timeline_count: int
    evaluated_candles: int
    lookahead_guard: str
    spread: float
    slippage: float
    auto_accept: bool
    max_hold_candles: int
    warmup_candles: int
    symbol: str
    strategy_timeframe: str
    context_timeframe: str
    engine: str
    run_id: str | None = None

    def summary_by_playbook(self) -> list[dict[str, Any]]:
        grouped: dict[str, list[BacktestTrade]] = {}
        for trade in self.trades:
            grouped.setdefault(trade.playbook, []).append(trade)

        rows: list[dict[str, Any]] = []
        for playbook, trades in sorted(grouped.items()):
            wins = [trade for trade in trades if trade.pnl_r > 0]
            losses = [trade for trade in trades if trade.pnl_r <= 0]
            total_r = sum(trade.pnl_r for trade in trades)
            rows.append(
                {
                    "playbook": playbook,
                    "trades": len(trades),
                    "wins": len(wins),
                    "losses": len(losses),
                    "win_rate": round(len(wins) / len(trades), 4) if trades else 0,
                    "total_r": round(total_r, 4),
                    "avg_r": round(total_r / len(trades), 4) if trades else 0,
                }
            )
        return rows


def run_strategy_backtest(
    conn: Connection,
    config: AppConfig,
    symbol: str,
    limit: int,
    spread: float | None = None,
    slippage: float | None = None,
    max_hold_candles: int | None = None,
    warmup_candles: int | None = None,
    auto_accept: bool | None = None,
    engine: str = "incremental",
    include_human_zones: bool = False,
    allowed_playbooks: set[str] | None = None,
    allowed_zone_types: set[str] | None = None,
) -> BacktestResult:
    if engine == "replay":
        return run_strategy_backtest_replay(
            conn,
            config,
            symbol,
            limit,
            spread=spread,
            slippage=slippage,
            max_hold_candles=max_hold_candles,
            warmup_candles=warmup_candles,
            auto_accept=auto_accept,
            include_human_zones=include_human_zones,
            allowed_playbooks=allowed_playbooks,
            allowed_zone_types=allowed_zone_types,
        )
    if engine != "incremental":
        raise ValueError("engine must be incremental or replay")
    return run_strategy_backtest_incremental(
        conn,
        config,
        symbol,
        limit,
        spread=spread,
        slippage=slippage,
        max_hold_candles=max_hold_candles,
        warmup_candles=warmup_candles,
        auto_accept=auto_accept,
        include_human_zones=include_human_zones,
        allowed_playbooks=allowed_playbooks,
        allowed_zone_types=allowed_zone_types,
    )


def run_strategy_backtest_replay(
    conn: Connection,
    config: AppConfig,
    symbol: str,
    limit: int,
    spread: float | None = None,
    slippage: float | None = None,
    max_hold_candles: int | None = None,
    warmup_candles: int | None = None,
    auto_accept: bool | None = None,
    include_human_zones: bool = False,
    allowed_playbooks: set[str] | None = None,
    allowed_zone_types: set[str] | None = None,  # not yet threaded into replay engine
) -> BacktestResult:
    effective_spread = config.backtest.spread if spread is None else spread
    effective_slippage = config.backtest.slippage if slippage is None else slippage
    effective_max_hold = config.backtest.max_hold_candles if max_hold_candles is None else max_hold_candles
    effective_warmup = config.backtest.warmup_candles if warmup_candles is None else warmup_candles
    effective_auto_accept = config.backtest.auto_accept if auto_accept is None else auto_accept
    zone_loss_cooldown_candles = config.backtest.zone_loss_cooldown_candles

    candles = load_backtest_candles(conn, symbol, config.strategy.timeframe, limit)
    if len(candles) < effective_warmup + 2:
        return BacktestResult(
            trades=[],
            timeline_count=len(candles),
            evaluated_candles=0,
            lookahead_guard="not enough candles after warmup",
            spread=effective_spread,
            slippage=effective_slippage,
            auto_accept=effective_auto_accept,
            max_hold_candles=effective_max_hold,
            warmup_candles=effective_warmup,
            symbol=symbol,
            strategy_timeframe=config.strategy.timeframe,
            context_timeframe=config.bias.timeframe,
            engine="replay",
        )

    replay_start = candle_decision_time(candles[0])
    next_available_index: dict[str, int] = {}
    zone_loss_cooldown_until: dict[str, int] = {}
    fvg_trade_counts: dict[str, int] = {}
    fvg_max_trades_per_zone = config.strategy.zone_reaction_v2_fvg_max_trades_per_zone
    trades: list[BacktestTrade] = []
    for signal_index in range(effective_warmup, len(candles) - 1):
        signal_time = candle_decision_time(candles[signal_index])
        payload = build_realtime_replay_payload(
            conn,
            config,
            symbol=symbol,
            timeframe=config.bias.timeframe,
            limit=max(limit, effective_warmup + 2),
            replay_start=replay_start,
            replay_at=signal_time,
            active_zones_only=True,
            include_human_zones=include_human_zones,
            allowed_playbooks=allowed_playbooks,
        )
        candidates = []
        if effective_auto_accept:
            candidates = candidates_for_backtest_execution(
                payload["layers"].get("setup_candidates", []),
                {"eligible"},
            )
        candidates = candidates_after_zone_loss_cooldown(candidates, zone_loss_cooldown_until, signal_index)
        candidates = candidates_after_fvg_trade_count(candidates, fvg_trade_counts, fvg_max_trades_per_zone)
        best_by_playbook = best_candidates_by_playbook(candidates)
        for candidate in best_by_playbook:
            playbook = str(candidate["playbook"])
            if signal_index < next_available_index.get(playbook, 0):
                continue
            trade = simulate_trade(
                candidate,
                candles,
                signal_index,
                effective_spread,
                effective_slippage,
                effective_max_hold,
            )
            if trade is None:
                continue
            trades.append(trade)
            exit_index = candle_index_by_time(candles, trade.exit_time)
            next_available_index[playbook] = max(exit_index + 1, signal_index + 1)
            apply_fvg_trade_count(fvg_trade_counts, trade, fvg_max_trades_per_zone)
            apply_zone_loss_cooldown(zone_loss_cooldown_until, trade, exit_index, zone_loss_cooldown_candles)

    return BacktestResult(
        trades=trades,
        timeline_count=len(candles),
        evaluated_candles=max(len(candles) - effective_warmup - 1, 0),
        lookahead_guard="signals use only closed candles up to signal candle close; entries fill on next M15 candle open",
        spread=effective_spread,
        slippage=effective_slippage,
        auto_accept=effective_auto_accept,
        max_hold_candles=effective_max_hold,
        warmup_candles=effective_warmup,
        symbol=symbol,
        strategy_timeframe=config.strategy.timeframe,
        context_timeframe=config.bias.timeframe,
        engine="replay",
    )


def run_strategy_backtest_incremental(
    conn: Connection,
    config: AppConfig,
    symbol: str,
    limit: int,
    spread: float | None = None,
    slippage: float | None = None,
    max_hold_candles: int | None = None,
    warmup_candles: int | None = None,
    auto_accept: bool | None = None,
    include_human_zones: bool = False,
    allowed_playbooks: set[str] | None = None,
    allowed_zone_types: set[str] | None = None,
) -> BacktestResult:
    effective_spread = config.backtest.spread if spread is None else spread
    effective_slippage = config.backtest.slippage if slippage is None else slippage
    effective_max_hold = config.backtest.max_hold_candles if max_hold_candles is None else max_hold_candles
    effective_warmup = config.backtest.warmup_candles if warmup_candles is None else warmup_candles
    effective_auto_accept = config.backtest.auto_accept if auto_accept is None else auto_accept
    zone_loss_cooldown_candles = config.backtest.zone_loss_cooldown_candles

    candles = load_backtest_candles(conn, symbol, config.strategy.timeframe, limit)
    if len(candles) < effective_warmup + 2:
        return BacktestResult(
            trades=[],
            timeline_count=len(candles),
            evaluated_candles=0,
            lookahead_guard="not enough candles after warmup",
            spread=effective_spread,
            slippage=effective_slippage,
            auto_accept=effective_auto_accept,
            max_hold_candles=effective_max_hold,
            warmup_candles=effective_warmup,
            symbol=symbol,
            strategy_timeframe=config.strategy.timeframe,
            context_timeframe=config.bias.timeframe,
            engine="incremental",
        )

    if len(candles) > INCREMENTAL_CHUNK_SIZE:
        trades = run_incremental_backtest_chunks(
            conn,
            config,
            symbol,
            candles,
            effective_spread,
            effective_slippage,
            effective_max_hold,
            effective_warmup,
            effective_auto_accept,
            include_human_zones,
            allowed_playbooks,
            allowed_zone_types,
        )
        return BacktestResult(
            trades=trades,
            timeline_count=len(candles),
            evaluated_candles=max(len(candles) - effective_warmup - 1, 0),
            lookahead_guard=(
                "chunked incremental engine uses closed-candle zone snapshots and only exposes candles, "
                "contexts, and confirmed structure with time/confirmed_at <= signal candle close; entries fill on next M15 candle open"
            ),
            spread=effective_spread,
            slippage=effective_slippage,
            auto_accept=effective_auto_accept,
            max_hold_candles=effective_max_hold,
            warmup_candles=effective_warmup,
            symbol=symbol,
            strategy_timeframe=config.strategy.timeframe,
            context_timeframe=config.bias.timeframe,
            engine="incremental",
        )

    timeline = build_incremental_timeline(conn, config, symbol, candles, include_human_zones=include_human_zones, allowed_playbooks=allowed_playbooks, allowed_zone_types=allowed_zone_types)
    next_available_index: dict[str, int] = {}
    zone_loss_cooldown_until: dict[str, int] = {}
    fvg_trade_counts: dict[str, int] = {}
    fvg_max_trades_per_zone = config.strategy.zone_reaction_v2_fvg_max_trades_per_zone
    trades: list[BacktestTrade] = []
    for signal_index in range(effective_warmup, len(candles) - 1):
        signal_time = candle_decision_time(candles[signal_index])
        if not effective_auto_accept:
            continue
        emit_backtest_progress(signal_index, len(candles), len(trades))
        last_close = float(candles[signal_index]["close"])
        candidate_zones = rank_active_zones(timeline.zones_at(signal_time), last_close)
        candidates = candidates_for_backtest_execution(
            timeline.setup_candidates_at(signal_time, signal_index, candidate_zones),
            {"eligible"},
        )
        candidates = candidates_after_zone_loss_cooldown(candidates, zone_loss_cooldown_until, signal_index)
        candidates = candidates_after_fvg_trade_count(candidates, fvg_trade_counts, fvg_max_trades_per_zone)
        best_by_playbook = best_candidates_by_playbook(candidates)
        for candidate in best_by_playbook:
            playbook = str(candidate["playbook"])
            if signal_index < next_available_index.get(playbook, 0):
                continue
            trade = simulate_trade(
                candidate,
                candles,
                signal_index,
                effective_spread,
                effective_slippage,
                effective_max_hold,
            )
            if trade is None:
                continue
            trades.append(trade)
            exit_index = candle_index_by_time(candles, trade.exit_time)
            next_available_index[playbook] = max(exit_index + 1, signal_index + 1)
            apply_fvg_trade_count(fvg_trade_counts, trade, fvg_max_trades_per_zone)
            apply_zone_loss_cooldown(zone_loss_cooldown_until, trade, exit_index, zone_loss_cooldown_candles)

    return BacktestResult(
        trades=trades,
        timeline_count=len(candles),
        evaluated_candles=max(len(candles) - effective_warmup - 1, 0),
        lookahead_guard=(
            "incremental engine uses closed-candle zone snapshots and only exposes candles, contexts, "
            "and confirmed structure with time/confirmed_at <= signal candle close; entries fill on next M15 candle open"
        ),
        spread=effective_spread,
        slippage=effective_slippage,
        auto_accept=effective_auto_accept,
        max_hold_candles=effective_max_hold,
        warmup_candles=effective_warmup,
        symbol=symbol,
        strategy_timeframe=config.strategy.timeframe,
        context_timeframe=config.bias.timeframe,
        engine="incremental",
    )


def run_incremental_backtest_chunks(
    conn: Connection,
    config: AppConfig,
    symbol: str,
    candles: list[dict[str, Any]],
    spread: float,
    slippage: float,
    max_hold_candles: int,
    warmup_candles: int,
    auto_accept: bool,
    include_human_zones: bool,
    allowed_playbooks: set[str] | None = None,
    allowed_zone_types: set[str] | None = None,
) -> list[BacktestTrade]:
    trades: list[BacktestTrade] = []
    next_available_index: dict[str, int] = {}
    zone_loss_cooldown_until: dict[str, int] = {}
    zone_loss_cooldown_candles = config.backtest.zone_loss_cooldown_candles
    fvg_trade_counts: dict[str, int] = {}
    fvg_max_trades_per_zone = config.strategy.zone_reaction_v2_fvg_max_trades_per_zone
    segment_start = warmup_candles
    while segment_start < len(candles) - 1:
        segment_end = min(len(candles) - 1, segment_start + INCREMENTAL_CHUNK_SIZE)
        chunk_start = max(0, segment_start - max(INCREMENTAL_CHUNK_OVERLAP, warmup_candles))
        chunk_end = min(len(candles), segment_end + max_hold_candles + 2)
        chunk_candles = candles[chunk_start:chunk_end]
        detector_candles = candles[chunk_start:segment_end]
        timeline = build_incremental_timeline(
            conn,
            config,
            symbol,
            detector_candles,
            include_human_zones=include_human_zones,
            allowed_playbooks=allowed_playbooks,
            allowed_zone_types=allowed_zone_types,
        )
        local_eval_start = segment_start - chunk_start
        local_eval_end = segment_end - chunk_start
        for local_signal_index in range(local_eval_start, local_eval_end):
            global_signal_index = chunk_start + local_signal_index
            signal_time = candle_decision_time(chunk_candles[local_signal_index])
            if not auto_accept:
                continue
            if global_signal_index < 0 or global_signal_index >= len(candles) - 1:
                continue
            emit_backtest_progress(global_signal_index, len(candles), len(trades))
            last_close = float(chunk_candles[local_signal_index]["close"])
            candidate_zones = rank_active_zones(timeline.zones_at(signal_time), last_close)
            candidates = candidates_for_backtest_execution(
                timeline.setup_candidates_at(signal_time, local_signal_index, candidate_zones),
                {"eligible"},
            )
            candidates = candidates_after_zone_loss_cooldown(candidates, zone_loss_cooldown_until, global_signal_index)
            candidates = candidates_after_fvg_trade_count(candidates, fvg_trade_counts, fvg_max_trades_per_zone)
            for candidate in best_candidates_by_playbook(candidates):
                playbook = str(candidate["playbook"])
                if global_signal_index < next_available_index.get(playbook, 0):
                    continue
                trade = simulate_trade(candidate, chunk_candles, local_signal_index, spread, slippage, max_hold_candles)
                if trade is None:
                    continue
                trades.append(trade)
                local_exit_index = candle_index_by_time(chunk_candles, trade.exit_time)
                next_available_index[playbook] = max(chunk_start + local_exit_index + 1, global_signal_index + 1)
                apply_fvg_trade_count(fvg_trade_counts, trade, fvg_max_trades_per_zone)
                apply_zone_loss_cooldown(
                    zone_loss_cooldown_until,
                    trade,
                    chunk_start + local_exit_index,
                    zone_loss_cooldown_candles,
                )
        segment_start = segment_end
    return trades


def candidates_after_zone_loss_cooldown(
    candidates: list[dict[str, Any]],
    zone_loss_cooldown_until: dict[str, int],
    signal_index: int,
) -> list[dict[str, Any]]:
    if not zone_loss_cooldown_until:
        return candidates
    return [
        candidate
        for candidate in candidates
        if signal_index >= zone_loss_cooldown_until.get(str(candidate.get("primary_zone_id") or ""), 0)
    ]


def apply_zone_loss_cooldown(
    zone_loss_cooldown_until: dict[str, int],
    trade: BacktestTrade,
    exit_index: int,
    cooldown_candles: int,
) -> None:
    if cooldown_candles <= 0 or trade.pnl_r >= 0 or not trade.primary_zone_id:
        return
    zone_loss_cooldown_until[trade.primary_zone_id] = max(
        zone_loss_cooldown_until.get(trade.primary_zone_id, 0),
        exit_index + 1 + cooldown_candles,
    )


def candidates_after_fvg_trade_count(
    candidates: list[dict[str, Any]],
    fvg_trade_counts: dict[str, int],
    max_trades_per_zone: int,
) -> list[dict[str, Any]]:
    if max_trades_per_zone <= 0 or not fvg_trade_counts:
        return candidates
    return [
        candidate
        for candidate in candidates
        if not (
            candidate_zone_type(candidate) == "fvg"
            and str(candidate.get("primary_zone_id") or "") in fvg_trade_counts
            and fvg_trade_counts[str(candidate.get("primary_zone_id") or "")] >= max_trades_per_zone
        )
    ]


def apply_fvg_trade_count(
    fvg_trade_counts: dict[str, int],
    trade: BacktestTrade,
    max_trades_per_zone: int,
) -> None:
    if max_trades_per_zone <= 0 or not trade.primary_zone_id:
        return
    candidate_metadata = trade.metadata.get("candidate_metadata") if isinstance(trade.metadata, dict) else {}
    if isinstance(candidate_metadata, dict) and candidate_metadata.get("zone_type") == "fvg":
        fvg_trade_counts[trade.primary_zone_id] = fvg_trade_counts.get(trade.primary_zone_id, 0) + 1


def candidate_zone_type(candidate: dict[str, Any]) -> str | None:
    metadata = candidate.get("metadata")
    if isinstance(metadata, dict) and metadata.get("zone_type"):
        return str(metadata["zone_type"])
    if candidate.get("zone_type"):
        return str(candidate["zone_type"])
    return None


@dataclass
class IncrementalBacktestTimeline:
    symbol: str
    config: AppConfig
    strategy_candles: list[dict[str, Any]]
    structure_candles: list[dict[str, Any]]
    structure_views: list[Any]
    structure_points: list[StructurePoint]
    structure_point_confirm_times: list[str]
    strategy_points: list[StructurePoint]
    strategy_point_confirm_times: list[str]
    zones: list[dict[str, Any]]
    zone_detected_times: list[str]
    structure_view_times: list[str]
    zone_snapshot_cache: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    allowed_playbooks: set[str] | None = None
    allowed_zone_types: set[str] | None = None

    def setup_candidates_at(self, signal_time: str, signal_index: int, zones: list[dict[str, Any]]) -> list[dict[str, Any]]:
        strategy_start = max(0, signal_index - STRATEGY_EVALUATION_WINDOW + 1)
        strategy_candles = self.strategy_candles[strategy_start : signal_index + 1]
        structure_views = self.structure_views[: bisect_right(self.structure_view_times, signal_time)]
        structure_points = self.structure_points[: bisect_right(self.structure_point_confirm_times, signal_time)]
        strategy_points = self.strategy_points[: bisect_right(self.strategy_point_confirm_times, signal_time)]
        context_view_window = max(self.config.regime.lookback + self.config.regime.atr_period + 2, 80)
        context_views = structure_views[-context_view_window:]
        context_start = context_views[0].open_time if context_views else signal_time
        context_points = [point for point in structure_points if point.event_time >= context_start]
        recent_strategy_points = strategy_points[-STRATEGY_POINT_WINDOW:]
        # Macro trend needs a much longer candle window than bias/regime, so it
        # reads the full point-in-time H1 history available at the signal candle.
        macro_window = self.config.macro_trend.lookback_candles + self.config.macro_trend.atr_period + 2
        contexts = build_replay_contexts(
            self.symbol,
            self.config.bias.timeframe,
            context_points,
            context_views,
            self.config,
            macro_candles=structure_views[-macro_window:],
        )
        return build_setup_candidates(
            symbol=self.symbol,
            zones=zones,
            contexts=contexts,
            candles=strategy_candles,
            structure_points=[structure_point_to_chart(point) for point in recent_strategy_points],
            config=self.config.strategy,
            context_timeframe=self.config.bias.timeframe,
            allowed_playbooks=self.allowed_playbooks,
            context_candles=self.structure_candles[: bisect_right(self.structure_view_times, signal_time)][-STRATEGY_EVALUATION_WINDOW:],
        )

    def zones_at(self, signal_time: str) -> list[dict[str, Any]]:
        slice_end = bisect_right(self.structure_view_times, signal_time)
        if slice_end <= 0:
            return []
        snapshot_key = self.structure_view_times[slice_end - 1]
        cached = self.zone_snapshot_cache.get(snapshot_key)
        if cached is not None:
            return cached

        snapshot_candles = min(self.config.smc_zones.max_candles, self.config.backtest.zone_snapshot_candles)
        window_start = max(0, slice_end - snapshot_candles)
        window_start_time = self.structure_view_times[window_start]
        available_slices = chart_candles_to_slices(self.structure_candles[window_start:slice_end])
        available_points = self.structure_points[: bisect_right(self.structure_point_confirm_times, signal_time)]
        available_swings = [
            point
            for point in available_points
            if point.metadata.get("swing_type") in {"high", "low"} and point.event_time >= window_start_time
        ]
        zone_swings = structure_points_to_zone_swings(available_swings)
        if not available_slices or not zone_swings:
            self.zone_snapshot_cache[snapshot_key] = []
            return []

        # Incremental backtest recomputes point-in-time zones from closed candles
        # only. Realtime chart can read persisted DB zones so human edits survive,
        # but backtest must avoid hindsight from zones generated later.
        use_sr = zone_type_allowed(self.allowed_zone_types, "support") or zone_type_allowed(self.allowed_zone_types, "resistance")
        sr_zones: list[PriceZone] = []
        if use_sr:
            sr_zones = detect_support_resistance_zones(
                zone_swings[-self.config.support_resistance.lookback_swings :],
                self.symbol,
                self.config.bias.timeframe,
                self.config.support_resistance.tolerance_pct,
                self.config.support_resistance.min_zone_width,
                self.config.support_resistance.min_touches,
                self.config.support_resistance.max_zones,
                available_slices,
                self.config.support_resistance.atr_width_multiplier,
                candidate_close_break_buffer=self.config.zone_lifecycle.close_break_buffer,
                candidate_close_break_buffer_atr_multiplier=self.config.zone_lifecycle.close_break_buffer_atr_multiplier,
            )
            sr_zones = apply_lifecycle_to_zones(
                sr_zones,
                available_slices,
                self.config.zone_lifecycle.close_break_buffer,
                self.config.zone_lifecycle.recent_touch_lookback_candles,
                self.config.zone_lifecycle.age_decay_per_100_candles,
                self.config.zone_lifecycle.freshness_bonus,
                self.config.zone_lifecycle.invalidation_weight_multiplier,
                self.config.zone_lifecycle.close_break_buffer_atr_multiplier,
                self.config.zone_reaction.reaction_window_candles,
                self.config.zone_reaction.min_reaction_atr,
                self.config.zone_reaction.strong_reaction_atr,
                self.config.zone_reaction.recent_reaction_count,
                self.config.zone_decay.max_healthy_touches,
                self.config.zone_decay.weak_touch_penalty,
                self.config.zone_decay.too_many_touches_penalty,
                self.config.zone_decay.linger_penalty,
                self.config.zone_lifecycle.false_break_refine_enabled,
                self.config.zone_lifecycle.false_break_refine_max_width_atr_multiplier,
                self.config.zone_lifecycle.false_break_parent_weight_multiplier,
            )
        smc_detected = detect_smc_zones(
            available_slices,
            zone_swings[-self.config.smc_zones.lookback_swings :],
            self.symbol,
            self.config.bias.timeframe,
            fvg_middle_candle_atr_multiplier=self.config.smc_zones.fvg_middle_candle_atr_multiplier,
            fvg_gap_atr_ratio=self.config.smc_zones.fvg_gap_atr_ratio,
            fvg_min_width_atr_ratio=self.config.smc_zones.fvg_min_width_atr_ratio,
            fvg_max_width_atr_ratio=self.config.smc_zones.fvg_max_width_atr_ratio,
            fvg_third_candle_follow_through_required=self.config.smc_zones.fvg_third_candle_follow_through_required,
            fvg_third_candle_min_body_ratio=self.config.smc_zones.fvg_third_candle_min_body_ratio,
            fvg_max_active_days=self.config.smc_zones.fvg_max_active_days_for(self.config.bias.timeframe),
            fvg_decay_start_days=self.config.smc_zones.fvg_decay_start_days_for(self.config.bias.timeframe),
            ob_displacement_atr_multiplier=self.config.smc_zones.ob_displacement_atr_multiplier,
            ob_min_body_ratio=self.config.smc_zones.ob_min_body_ratio,
            ob_min_width_atr_ratio=self.config.smc_zones.ob_min_width_atr_ratio,
            ob_max_width_atr_ratio=self.config.smc_zones.ob_max_width_atr_ratio,
            ob_require_structure_break=self.config.smc_zones.ob_require_structure_break,
            ob_merge_overlap_ratio=self.config.smc_zones.ob_merge_overlap_ratio,
            ob_max_active_days=self.config.smc_zones.ob_max_active_days_for(self.config.bias.timeframe),
            ob_decay_start_days=self.config.smc_zones.ob_decay_start_days_for(self.config.bias.timeframe),
            max_fvg_zones=self.config.smc_zones.max_fvg_zones if zone_type_allowed(self.allowed_zone_types, "fvg") else 0,
            max_order_block_zones=self.config.smc_zones.max_order_block_zones
            if zone_type_allowed(self.allowed_zone_types, "order_block")
            else 0,
            max_liquidity_zones=self.config.smc_zones.max_liquidity_zones
            if zone_type_allowed(self.allowed_zone_types, "liquidity_pool")
            else 0,
            max_consolidation_zones=self.config.smc_zones.max_consolidation_zones
            if zone_type_allowed(self.allowed_zone_types, "consolidation")
            else 0,
        )
        snapshot = [
            zone_to_chart(zone)
            for zone in [*sr_zones, *[zone for zones in smc_detected.values() for zone in zones]]
            # Recently-invalidated SR zones stay in the snapshot because the H1
            # candle that invalidates them is exactly the breakout candle that
            # sr_breakout_v1 trades; eligibility re-checks the recency window.
            if (
                zone.status == "active"
                or (zone.status == "invalidated" and zone.zone_type in ("support", "resistance"))
            )
            and (self.allowed_zone_types is None or zone.zone_type in self.allowed_zone_types)
        ]
        snapshot.sort(key=lambda zone: (zone_detection_time(zone), zone.get("id", "")))
        self.zone_snapshot_cache[snapshot_key] = snapshot
        return snapshot


def build_incremental_timeline(
    conn: Connection,
    config: AppConfig,
    symbol: str,
    strategy_candles: list[dict[str, Any]],
    include_human_zones: bool = False,
    allowed_playbooks: set[str] | None = None,
    allowed_zone_types: set[str] | None = None,
) -> IncrementalBacktestTimeline:
    start = candle_decision_time(strategy_candles[0])
    end = candle_decision_time(strategy_candles[-1])
    structure_candles = load_backtest_candles_between(conn, symbol, config.bias.timeframe, start, end)
    if not structure_candles:
        structure_candles = load_backtest_candles(conn, symbol, config.bias.timeframe, max(len(strategy_candles) // 4, 1))
    elif structure_candles:
        # Prepend extra context-timeframe history so the slow macro trend detector
        # has its full lookback even at the start of a chunk. Without this, the
        # chunked engine reports macro_trend=unknown for the first ~lookback
        # candles of every chunk and the macro gate silently stops filtering.
        macro_history = config.macro_trend.lookback_candles + config.macro_trend.atr_period + 2
        earlier = load_backtest_candles_before(
            conn,
            symbol,
            config.bias.timeframe,
            structure_candles[0]["close_time"],
            macro_history,
        )
        structure_candles = [*earlier, *structure_candles]
    structure_views = chart_candles_to_views(structure_candles)
    structure_slices = chart_candles_to_slices(structure_candles)
    structure_swing_config = config.swing_for(config.bias.timeframe)
    structure_swings = detect_swing_structure(
        structure_views,
        symbol,
        config.bias.timeframe,
        structure_swing_config.window,
        structure_swing_config.tolerance,
    )
    structure_breaks = detect_break_structure(
        structure_views,
        structure_points_to_swing_levels(structure_swings),
        symbol,
        config.bias.timeframe,
        close_break_buffer=config.breaks.close_break_buffer,
    )
    structure_points = sorted(
        [*structure_swings, *structure_breaks],
        key=lambda point: (point_confirmed_at(point), point.event_time, point.detector, point.point_type),
    )
    chart_zones: list[dict[str, Any]] = []
    # If caller explicitly provides allowed_zone_types, honour that override;
    # otherwise derive from the allowed playbooks as usual.
    allowed_zone_types = (
        allowed_zone_types
        if allowed_zone_types is not None
        else allowed_zone_types_for_playbooks(allowed_playbooks)
    )
    if include_human_zones:
        chart_zones.extend(
            zone
            for zone in load_chart_zones(conn, symbol, config.bias.timeframe, start, end, active_only=False)
            if zone["detector"] == "human_manual_v1" and (allowed_zone_types is None or str(zone.get("type")) in allowed_zone_types)
        )

    strategy_slices = chart_candles_to_slices(strategy_candles)
    strategy_views = chart_candles_to_views(strategy_candles)
    strategy_swing_config = config.swing_for(config.strategy.timeframe)
    strategy_swings = detect_swing_structure(
        strategy_views,
        symbol,
        config.strategy.timeframe,
        strategy_swing_config.window,
        strategy_swing_config.tolerance,
    )
    strategy_breaks = detect_break_structure(
        strategy_views,
        structure_points_to_swing_levels(strategy_swings),
        symbol,
        config.strategy.timeframe,
        close_break_buffer=config.breaks.close_break_buffer,
    )
    strategy_price_action = detect_price_action_patterns(
        strategy_slices,
        symbol,
        config.strategy.timeframe,
        atr_period=config.price_action.atr_period,
        displacement_atr_multiplier=config.price_action.displacement_atr_multiplier,
        displacement_body_ratio=config.price_action.displacement_body_ratio,
        pinbar_wick_body_ratio=config.price_action.pinbar_wick_body_ratio,
        pinbar_min_wick_ratio=config.price_action.pinbar_min_wick_ratio,
        engulfing_min_body_ratio=config.price_action.engulfing_min_body_ratio,
        marubozu_min_body_ratio=config.price_action.marubozu_min_body_ratio,
        star_large_body_ratio=config.price_action.star_large_body_ratio,
        star_small_body_ratio=config.price_action.star_small_body_ratio,
    )
    strategy_points = sorted(
        [*strategy_swings, *strategy_breaks, *strategy_price_action],
        key=lambda point: (point_confirmed_at(point), point.event_time, point.detector, point.point_type),
    )

    chart_zones = sorted(chart_zones, key=lambda zone: (zone_detection_time(zone), zone.get("id", "")))

    return IncrementalBacktestTimeline(
        symbol=symbol,
        config=config,
        strategy_candles=strategy_candles,
        structure_candles=structure_candles,
        structure_views=structure_views,
        structure_points=structure_points,
        structure_point_confirm_times=[point_confirmed_at(point) for point in structure_points],
        strategy_points=strategy_points,
        strategy_point_confirm_times=[point_confirmed_at(point) for point in strategy_points],
        zones=chart_zones,
        zone_detected_times=[zone_detection_time(zone) for zone in chart_zones],
        structure_view_times=[view.open_time for view in structure_views],
        allowed_playbooks=allowed_playbooks,
        allowed_zone_types=allowed_zone_types,
    )


def zone_type_allowed(allowed_zone_types: set[str] | None, zone_type: str) -> bool:
    return allowed_zone_types is None or zone_type in allowed_zone_types


def point_confirmed_at(point: StructurePoint) -> str:
    return str(point.metadata.get("confirmed_at", point.event_time))


def rank_active_zones(zones: list[dict[str, Any]], current_price: float, max_zones: int = 240) -> list[dict[str, Any]]:
    if len(zones) <= max_zones:
        return zones
    return sorted(zones, key=lambda zone: zone_backtest_rank(zone, current_price), reverse=True)[:max_zones]


def normalize_zone_for_backtest(zone: dict[str, Any]) -> dict[str, Any]:
    adjusted = dict(zone)
    adjusted["_backtest_end_time"] = zone_end_time(zone)
    adjusted["status"] = "active"
    adjusted["visual_end"] = None
    adjusted["invalidated_at"] = None
    adjusted["valid_until"] = None
    metadata = dict(zone.get("metadata") or {})
    metadata["backtest_active_projection"] = True
    adjusted["metadata"] = metadata
    return adjusted


def zone_detection_time(zone: dict[str, Any]) -> str:
    return str(zone.get("detected_at") or zone.get("valid_from") or zone.get("visual_start"))


def zone_end_time(zone: dict[str, Any]) -> str | None:
    # Backtest lifecycle must not depend on chart presentation geometry.
    value = zone.get("_backtest_end_time") or zone.get("invalidated_at") or zone.get("valid_until")
    return str(value) if value else None


def zone_is_active_at(zone: dict[str, Any], as_of: str) -> bool:
    end_time = zone_end_time(zone)
    return end_time is None or end_time > as_of


def zone_backtest_rank(zone: dict[str, Any], current_price: float) -> float:
    center = (float(zone["price_low"]) + float(zone["price_high"])) / 2
    width = max(float(zone["price_high"]) - float(zone["price_low"]), 0.01)
    distance = abs(center - current_price)
    proximity = 1 / (1 + distance / max(width * 4, current_price * 0.01, 1))
    return float(zone.get("weight") or 0) * 0.65 + proximity * 0.35


def simulate_trade(
    candidate: dict[str, Any],
    candles: list[dict[str, Any]],
    signal_index: int,
    spread: float,
    slippage: float,
    max_hold_candles: int,
) -> BacktestTrade | None:
    # Carry-forward candidates keep a recent signal visible for UI/live polling
    # after price leaves the zone. They are not new execution events and must
    # never be filled from the current backtest candle.
    if candidate_is_carried_forward(candidate):
        return None
    entry_index = signal_index + 1
    if entry_index >= len(candles):
        return None
    direction = str(candidate["direction"])
    stop_loss = candidate.get("stop_loss")
    take_profit = candidate.get("take_profit") or []
    if stop_loss is None or not take_profit:
        return None

    entry_candle = candles[entry_index]
    half_spread = spread / 2
    raw_open = float(entry_candle["open"])
    if direction == "long":
        entry_price = raw_open + half_spread + slippage
        stop = float(stop_loss)
        initial_risk = entry_price - stop
    else:
        entry_price = raw_open - half_spread - slippage
        stop = float(stop_loss)
        initial_risk = stop - entry_price
    if initial_risk <= 0:
        return None
    target_rr = target_risk_reward(candidate)
    if direction == "long":
        tp = entry_price + initial_risk * target_rr
    else:
        tp = entry_price - initial_risk * target_rr

    end_index = min(len(candles) - 1, entry_index + max_hold_candles)
    exit_status = "time_exit"
    exit_price = float(candles[end_index]["close"])
    exit_time = candle_decision_time(candles[end_index])
    for index in range(entry_index, end_index + 1):
        candle = candles[index]
        hit = exit_on_candle(candle, direction, stop, tp, half_spread, slippage)
        if hit is None:
            continue
        exit_status, exit_price = hit
        exit_time = candle_decision_time(candle)
        break

    if direction == "long":
        pnl_r = (exit_price - entry_price) / initial_risk
    else:
        pnl_r = (entry_price - exit_price) / initial_risk

    return BacktestTrade(
        playbook=str(candidate["playbook"]),
        direction=direction,
        status=exit_status,
        signal_time=candle_decision_time(candles[signal_index]),
        entry_time=candle_open_time(entry_candle),
        exit_time=exit_time,
        entry_price=round(entry_price, 5),
        stop_loss=round(stop, 5),
        take_profit=round(tp, 5),
        exit_price=round(exit_price, 5),
        pnl_r=round(pnl_r, 5),
        setup_id=str(candidate["id"]),
        score=round(float(candidate.get("score", 0)), 5),
        risk_reward=round(float(candidate["risk_reward"]), 5) if candidate.get("risk_reward") is not None else None,
        primary_zone_id=candidate.get("primary_zone_id"),
        related_zone_ids=list(candidate.get("related_zone_ids") or []),
        trigger_point_ids=list(candidate.get("trigger_point_ids") or []),
        reason=list(candidate.get("reason") or []),
        metadata={
            "score": candidate.get("score"),
            "zone_reaction_state": candidate.get("zone_reaction_state"),
            "primary_zone_id": candidate.get("primary_zone_id"),
            "related_zone_ids": candidate.get("related_zone_ids") or [],
            "trigger_point_ids": candidate.get("trigger_point_ids") or [],
            "reason": candidate.get("reason") or [],
            "blocked_reason": candidate.get("blocked_reason") or [],
            "candidate_metadata": candidate.get("metadata") or {},
            "spread": spread,
            "slippage": slippage,
            "target_rr_after_fill": target_rr,
            "cost_model": "entry uses bid/ask plus adverse slippage; exits use bid/ask side without extra exit slippage",
            "conservative_intrabar_order": "SL first when SL and TP are both inside same candle",
        },
    )


def target_risk_reward(candidate: dict[str, Any]) -> float:
    value = candidate.get("risk_reward")
    try:
        target = float(value) if value is not None else 2.0
    except (TypeError, ValueError):
        target = 2.0
    return max(target, 0.01)


def persist_backtest_result(
    conn: Connection,
    result: BacktestResult,
    candle_limit: int,
    clear_previous: bool = False,
) -> str:
    if clear_previous:
        clear_backtest_trades(conn, result.symbol)

    run_id = result.run_id or f"backtest-run-{uuid.uuid4()}"
    now = utc_now_iso()
    summary = result.summary_by_playbook()
    conn.execute(
        """
        INSERT INTO backtest_runs (
            id, symbol, strategy_timeframe, context_timeframe, candle_limit,
            evaluated_candles, trade_count, spread, slippage, max_hold_candles,
            warmup_candles, auto_accept, engine, lookahead_guard, summary_json, status,
            metadata_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)
        """,
        (
            run_id,
            result.symbol,
            result.strategy_timeframe,
            result.context_timeframe,
            candle_limit,
            result.evaluated_candles,
            len(result.trades),
            result.spread,
            result.slippage,
            result.max_hold_candles,
            result.warmup_candles,
            1 if result.auto_accept else 0,
            result.engine,
            result.lookahead_guard,
            json.dumps(summary, sort_keys=True),
            json.dumps({"source": "strategy_backtest_v1"}, sort_keys=True),
            now,
        ),
    )
    for index, trade in enumerate(result.trades, start=1):
        persist_backtest_trade(conn, run_id, result.symbol, trade, now, index)
    conn.commit()
    return run_id


def clear_backtest_trades(conn: Connection, symbol: str) -> None:
    rows = conn.execute(
        """
        SELECT id, trade_idea_id
        FROM trade_orders
        WHERE symbol = ? AND source = 'backtest'
        """,
        (symbol,),
    ).fetchall()
    order_ids = [
        row["id"]
        for row in rows
    ]
    idea_ids = [
        row["trade_idea_id"]
        for row in rows
    ]
    orphan_idea_ids = [
        row["id"]
        for row in conn.execute(
            """
            SELECT id
            FROM trade_ideas
            WHERE symbol = ? AND context_snapshot_json LIKE '%"source": "backtest"%'
            """,
            (symbol,),
        ).fetchall()
    ]
    idea_ids.extend(orphan_idea_ids)
    if order_ids:
        conn.executemany("DELETE FROM trade_reviews WHERE trade_order_id = ?", [(order_id,) for order_id in order_ids])
        conn.executemany("DELETE FROM trade_fills WHERE trade_order_id = ?", [(order_id,) for order_id in order_ids])
        conn.executemany("DELETE FROM trade_orders WHERE id = ?", [(order_id,) for order_id in order_ids])
    if idea_ids:
        conn.executemany("DELETE FROM trade_ideas WHERE id = ?", [(idea_id,) for idea_id in sorted(set(idea_ids))])


def persist_backtest_trade(
    conn: Connection,
    run_id: str,
    symbol: str,
    trade: BacktestTrade,
    created_at: str,
    sequence: int,
) -> None:
    idea_id = f"backtest-idea-{run_id}-{sequence:05d}"
    order_id = f"backtest-order-{run_id}-{sequence:05d}"
    quantity = 1.0
    pnl = trade.pnl_r
    context_snapshot = {
        "source": "backtest",
        "backtest": True,
        "run_id": run_id,
        "setup_id": trade.setup_id,
        "signal_time": trade.signal_time,
        "score": trade.score,
        "risk_reward": trade.risk_reward,
        "primary_zone_id": trade.primary_zone_id,
        "related_zone_ids": trade.related_zone_ids,
        "trigger_point_ids": trade.trigger_point_ids,
        "reason": trade.reason,
        "metadata": trade.metadata,
    }
    conn.execute(
        """
        INSERT INTO trade_ideas (
            id, symbol, direction, playbook, status, entry_zone_id,
            related_zone_ids_json, context_snapshot_json, suggested_entry,
            suggested_stop_loss, suggested_take_profit_json, risk_reward,
            created_at, expires_at
        )
        VALUES (?, ?, ?, ?, 'executed', ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            idea_id,
            symbol,
            trade.direction,
            trade.playbook,
            trade.primary_zone_id,
            json.dumps(trade.related_zone_ids),
            json.dumps(context_snapshot, sort_keys=True),
            trade.entry_price,
            trade.stop_loss,
            json.dumps([trade.take_profit]),
            trade.risk_reward or 0,
            trade.signal_time,
        ),
    )
    conn.execute(
        """
        INSERT INTO trade_orders (
            id, trade_idea_id, symbol, side, order_type, status, entry_price,
            stop_loss, take_profit_json, quantity, opened_at, closed_at,
            close_price, pnl, pnl_r, source, metadata_json, created_at
        )
        VALUES (?, ?, ?, ?, 'market',
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'backtest', ?, ?)
        """,
        (
            order_id,
            idea_id,
            symbol,
            "buy" if trade.direction == "long" else "sell",
            trade.status,
            trade.entry_price,
            trade.stop_loss,
            json.dumps([trade.take_profit]),
            quantity,
            trade.entry_time,
            trade.exit_time,
            trade.exit_price,
            pnl,
            trade.pnl_r,
            json.dumps(
                {
                    **trade.metadata,
                    "backtest": True,
                    "run_id": run_id,
                    "setup_id": trade.setup_id,
                    "signal_time": trade.signal_time,
                    "score": trade.score,
                    "risk_reward": trade.risk_reward,
                    "primary_zone_id": trade.primary_zone_id,
                    "related_zone_ids": trade.related_zone_ids,
                    "trigger_point_ids": trade.trigger_point_ids,
                    "reason": trade.reason,
                },
                sort_keys=True,
            ),
            created_at,
        ),
    )
    conn.executemany(
        """
        INSERT INTO trade_fills (
            id, trade_order_id, fill_time, fill_price, quantity, fee, source, created_at
        )
        VALUES (?, ?, ?, ?, ?, NULL, 'backtest', ?)
        """,
        [
            (f"backtest-fill-{run_id}-{sequence:05d}-entry", order_id, trade.entry_time, trade.entry_price, quantity, created_at),
            (f"backtest-fill-{run_id}-{sequence:05d}-exit", order_id, trade.exit_time, trade.exit_price, -quantity, created_at),
        ],
    )


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def exit_on_candle(
    candle: dict[str, Any],
    direction: str,
    stop: float,
    take_profit: float,
    half_spread: float,
    slippage: float,
) -> tuple[str, float] | None:
    high = float(candle["high"])
    low = float(candle["low"])
    if direction == "long":
        stop_hit = low - half_spread <= stop
        tp_hit = high - half_spread >= take_profit
        if stop_hit:
            return "stopped", stop
        if tp_hit:
            return "target_hit", take_profit
    else:
        stop_hit = high + half_spread >= stop
        tp_hit = low + half_spread <= take_profit
        if stop_hit:
            return "stopped", stop
        if tp_hit:
            return "target_hit", take_profit
    return None


def best_candidates_by_playbook(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        playbook = str(candidate["playbook"])
        current = best.get(playbook)
        if current is None or float(candidate.get("score", 0)) > float(current.get("score", 0)):
            best[playbook] = candidate
    return sorted(best.values(), key=lambda candidate: float(candidate.get("score", 0)), reverse=True)


def candidate_is_carried_forward(candidate: dict[str, Any]) -> bool:
    metadata = candidate.get("metadata")
    return isinstance(metadata, dict) and metadata.get("carried_forward") is True


def candidates_for_backtest_execution(
    candidates: list[dict[str, Any]],
    allowed_statuses: set[str],
) -> list[dict[str, Any]]:
    """Return point-in-time execution events, excluding UI-only carry-forward rows."""
    return [
        candidate
        for candidate in candidates
        if str(candidate.get("status")) in allowed_statuses
        and not candidate_is_carried_forward(candidate)
    ]


def load_backtest_candles(conn: Connection, symbol: str, timeframe: str, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT open_time, close_time, open, high, low, close, volume
        FROM (
            SELECT open_time, close_time, open, high, low, close, volume
            FROM candles
            WHERE symbol = ? AND timeframe = ?
            ORDER BY open_time DESC
            LIMIT ?
        )
        ORDER BY open_time
        """,
        (symbol, timeframe, limit),
    ).fetchall()
    return [
        {
            "time": row["close_time"],
            "open_time": row["open_time"],
            "close_time": row["close_time"],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]) if row["volume"] is not None else None,
        }
        for row in rows
    ]


def load_backtest_candles_between(conn: Connection, symbol: str, timeframe: str, start: str, end: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT open_time, close_time, open, high, low, close, volume
        FROM candles
        WHERE symbol = ? AND timeframe = ? AND close_time >= ? AND close_time <= ?
        ORDER BY open_time
        """,
        (symbol, timeframe, start, end),
    ).fetchall()
    return [
        {
            "time": row["close_time"],
            "open_time": row["open_time"],
            "close_time": row["close_time"],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]) if row["volume"] is not None else None,
        }
        for row in rows
    ]


def load_backtest_candles_before(
    conn: Connection,
    symbol: str,
    timeframe: str,
    before: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT open_time, close_time, open, high, low, close, volume
        FROM candles
        WHERE symbol = ? AND timeframe = ? AND close_time < ?
        ORDER BY open_time DESC
        LIMIT ?
        """,
        (symbol, timeframe, before, limit),
    ).fetchall()
    return [
        {
            "time": row["close_time"],
            "open_time": row["open_time"],
            "close_time": row["close_time"],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]) if row["volume"] is not None else None,
        }
        for row in reversed(rows)
    ]


def candle_index_by_time(candles: list[dict[str, Any]], time: str) -> int:
    for index, candle in enumerate(candles):
        if candle_decision_time(candle) == time or candle_open_time(candle) == time:
            return index
    return 0


def emit_backtest_progress(index: int, total: int, trade_count: int) -> None:
    if total < 5_000 or index % 1_000 != 0:
        return
    print(
        f"Backtest progress: {index}/{total - 1} candles evaluated, trades={trade_count}",
        file=sys.stderr,
        flush=True,
    )


def candle_decision_time(candle: dict[str, Any]) -> str:
    return str(candle.get("close_time") or candle["time"])


def candle_open_time(candle: dict[str, Any]) -> str:
    return str(candle.get("open_time") or candle["time"])
