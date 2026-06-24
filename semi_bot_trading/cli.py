from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path

from .backtest import persist_backtest_result, run_strategy_backtest
from .backtest_report import render_backtest_html, render_backtest_report
from .candles import candle_summary, find_gaps
from .chart import build_chart_payload
from .config import DEFAULT_CONFIG_PATH, load_config
from .context import detect_and_store_bias, detect_and_store_macro_trend, detect_and_store_regime, latest_contexts
from .db import DEFAULT_DB_PATH, connect, init_db
from .importer import import_data_dir
from .price_action import detect_and_store_price_action_patterns
from .research import read_research_csv, render_research_html, render_research_report, run_research_events
from .replay import replay_candles
from .smc_zones import detect_and_store_smc_zones
from .strategy import PLAYBOOK_ZONE_TYPES
from .server import run_chart_server
from .structure import (
    detect_and_store_break_structure,
    detect_and_store_swing_structure,
    latest_structure_points,
    structure_summary,
)
from .zones import (
    apply_and_store_zone_lifecycle,
    detect_and_store_support_resistance_zones,
    zone_summary,
)
from .zone_materializer import materialize_incremental_zones


INCREMENTAL_ZONE_DETECTOR_ALIASES = {
    "sr": "sr_v2",
    "sr_v2": "sr_v2",
    "support_resistance": "sr_v2",
    "fvg": "fvg_v1",
    "fvg_v1": "fvg_v1",
}


def normalize_report_output_path(path: Path | None) -> Path | None:
    if path is None:
        return None

    raw = str(path)
    if "\\" in raw:
        return Path(raw.replace("\\", "/"))

    # macOS/zsh can swallow unquoted Windows separators, turning
    # `var\reports\foo.html` into `varreportsfoo.html`. Recover the common
    # report-output typo so generated HTML lands in the expected folder.
    if path.parent == Path(".") and path.name.startswith("varreports"):
        filename = path.name.removeprefix("varreports")
        if filename:
            return Path("var") / "reports" / filename

    return path


def write_html_report(path: Path | None, html: str) -> None:
    output_path = normalize_report_output_path(path)
    if output_path is None:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)
    print(f"HTML report: {output_path}")


def add_common_db_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help=f"SQLite database path. Default comes from {DEFAULT_CONFIG_PATH}",
    )


def add_common_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Config path. Default: {DEFAULT_CONFIG_PATH}",
    )


def add_common_env_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--env", type=Path, default=Path(".env"), help="Runtime .env path. Default: .env")


def resolve_db_path(args: argparse.Namespace) -> Path:
    if args.db is not None:
        return args.db
    try:
        return load_config(args.config).database
    except FileNotFoundError:
        return DEFAULT_DB_PATH


def parse_incremental_zone_detectors(raw_value: str | None) -> set[str]:
    if not raw_value:
        return {"sr_v2", "fvg_v1"}
    detectors: set[str] = set()
    invalid: list[str] = []
    for item in raw_value.split(","):
        key = item.strip().lower()
        if not key:
            continue
        detector = INCREMENTAL_ZONE_DETECTOR_ALIASES.get(key)
        if detector is None:
            invalid.append(item.strip())
            continue
        detectors.add(detector)
    if invalid or not detectors:
        valid = ", ".join(sorted(INCREMENTAL_ZONE_DETECTOR_ALIASES))
        raise SystemExit(f"Invalid detector(s): {', '.join(invalid)}. Valid values: {valid}")
    return detectors


def git_value(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return "unknown"
    return result.stdout.strip() or "unknown"


def cmd_version(args: argparse.Namespace) -> None:
    from .runtime_env import load_runtime_env

    config = load_config(args.config)
    env = load_runtime_env(args.env)
    commit = git_value("rev-parse", "--short", "HEAD")
    branch = git_value("rev-parse", "--abbrev-ref", "HEAD")
    status = git_value("status", "--porcelain")
    dirty = "unknown" if status == "unknown" else ("yes" if status else "no")
    print(f"commit: {commit}")
    print(f"branch: {branch}")
    print(f"dirty: {dirty}")
    print(f"python: {sys.version.split()[0]} ({platform.platform()})")
    print(f"config: {config.path}")
    print(f"database: {config.database}")
    print(f"symbol: {config.symbol}")
    print(f"mt5_symbol: {env.mt5_symbol}")
    print(f"execution_enabled: {env.execution_enabled}")
    print(f"live_poll_seconds: {env.poll_seconds}")
    print(f"live_evaluate_intrabar: {env.live_evaluate_intrabar}")
    print(f"environment: {env.environment}")


def cmd_init_db(args: argparse.Namespace) -> None:
    db_path = resolve_db_path(args)
    with connect(db_path) as conn:
        init_db(conn)
    print(f"Initialized database: {db_path}")


def cmd_import_data(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    db_path = args.db or config.database
    data_dir = args.data_dir or config.data_dir
    with connect(db_path) as conn:
        init_db(conn)
        results = import_data_dir(conn, data_dir)
    for result in results:
        print(
            f"Imported {result.rows_seen} rows from {result.path} "
            f"as {result.symbol} {result.timeframe}"
        )
    print(f"Database: {db_path}")


def cmd_db_summary(args: argparse.Namespace) -> None:
    db_path = resolve_db_path(args)
    with connect(db_path) as conn:
        init_db(conn)
        summaries = candle_summary(conn)
        if not summaries:
            print("No candles found.")
            return
        for item in summaries:
            print(
                f"{item['symbol']} {item['timeframe']}: "
                f"{item['candle_count']} candles, "
                f"{item['first_open_time']} -> {item['last_open_time']}"
            )
            gaps = find_gaps(conn, str(item["symbol"]), str(item["timeframe"]), limit=5)
            if gaps:
                print(f"  raw gaps: {len(gaps)} shown (often daily maintenance/weekend for XAUUSD)")
                for gap in gaps:
                    print(
                        f"    expected {gap['expected']} but found {gap['actual']} "
                        f"({gap['minutes']} missing minutes)"
                    )
            else:
                print("  raw gaps: none")


def cmd_replay(args: argparse.Namespace) -> None:
    db_path = resolve_db_path(args)
    with connect(db_path) as conn:
        rows = replay_candles(
            conn,
            symbol=args.symbol,
            timeframe=args.timeframe,
            limit=args.limit,
            start=args.start,
        )
    if not rows:
        print("No candles found for replay.")
        return
    for index, row in enumerate(rows, start=1):
        print(
            f"{index:04d} {args.symbol} {args.timeframe} {row['open_time']} "
            f"O={row['open']:.2f} H={row['high']:.2f} "
            f"L={row['low']:.2f} C={row['close']:.2f} V={row['volume']}"
        )


def cmd_detect_structure(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = args.symbol or config.symbol
    swing_config = config.swing_for(args.timeframe)
    window = args.window if args.window is not None else swing_config.window
    tolerance = args.tolerance if args.tolerance is not None else swing_config.tolerance
    db_path = args.db or config.database

    with connect(db_path) as conn:
        init_db(conn)
        count = detect_and_store_swing_structure(
            conn,
            symbol=symbol,
            timeframe=args.timeframe,
            window=window,
            tolerance=tolerance,
        )
    print(
        f"Stored {count} swing structure points for "
        f"{symbol} {args.timeframe} with window={window}, tolerance={tolerance}"
    )


def cmd_detect_breaks(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = args.symbol or config.symbol
    close_break_buffer = (
        args.close_break_buffer
        if args.close_break_buffer is not None
        else config.breaks.close_break_buffer
    )
    db_path = args.db or config.database

    with connect(db_path) as conn:
        init_db(conn)
        count = detect_and_store_break_structure(
            conn,
            symbol=symbol,
            timeframe=args.timeframe,
            close_break_buffer=close_break_buffer,
        )
    print(
        f"Stored {count} BOS/CHOCH points for "
        f"{symbol} {args.timeframe} with close_break_buffer={close_break_buffer}"
    )


def cmd_structure_summary(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = args.symbol or config.symbol
    db_path = args.db or config.database
    with connect(db_path) as conn:
        init_db(conn)
        rows = structure_summary(conn, symbol=symbol, timeframe=args.timeframe)
        latest = latest_structure_points(conn, symbol, args.timeframe, limit=args.limit)
    if not rows:
        print("No structure points found.")
        return
    for row in rows:
        print(
            f"{row['symbol']} {row['timeframe']} {row['detector']} {row['point_type']}: "
            f"{row['point_count']} points, "
            f"{row['first_event_time']} -> {row['last_event_time']}"
        )
    print(f"Latest {len(latest)} points:")
    for row in reversed(latest):
        metadata = json.loads(str(row["metadata_json"]))
        direction = metadata.get("direction")
        suffix = f" {direction}" if direction else ""
        print(f"  {row['event_time']} {row['point_type']}{suffix} @ {row['price']:.2f}")


def cmd_detect_bias(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = args.symbol or config.symbol
    timeframe = args.timeframe or config.bias.timeframe
    recent_swings = args.recent_swings or config.bias.recent_swings
    recent_breaks = args.recent_breaks or config.bias.recent_breaks
    db_path = args.db or config.database

    with connect(db_path) as conn:
        init_db(conn)
        context = detect_and_store_bias(
            conn,
            symbol=symbol,
            timeframe=timeframe,
            recent_swings=recent_swings,
            recent_breaks=recent_breaks,
        )
    print(
        f"Stored {symbol} {timeframe} bias={context.effective_value} "
        f"confidence={context.effective_confidence:.2f} from {context.valid_from}"
    )


def cmd_detect_macro_trend(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = args.symbol or config.symbol
    timeframe = args.timeframe or config.macro_trend.timeframe
    db_path = args.db or config.database

    with connect(db_path) as conn:
        init_db(conn)
        context = detect_and_store_macro_trend(
            conn,
            symbol=symbol,
            timeframe=timeframe,
            lookback_candles=args.lookback_candles or config.macro_trend.lookback_candles,
            flat_threshold_atr=config.macro_trend.flat_threshold_atr,
            atr_period=config.macro_trend.atr_period,
        )
    momentum_atr = context.metadata.get("momentum_atr")
    print(
        f"Stored {symbol} {timeframe} macro_trend={context.effective_value} "
        f"momentum_atr={momentum_atr} confidence={context.effective_confidence:.2f} "
        f"from {context.valid_from}"
    )


def cmd_detect_regime(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = args.symbol or config.symbol
    timeframe = args.timeframe or config.regime.timeframe
    db_path = args.db or config.database

    with connect(db_path) as conn:
        init_db(conn)
        context = detect_and_store_regime(
            conn,
            symbol=symbol,
            timeframe=timeframe,
            atr_period=args.atr_period or config.regime.atr_period,
            lookback=args.lookback or config.regime.lookback,
            atr_high_percentile=config.regime.atr_high_percentile,
            atr_low_percentile=config.regime.atr_low_percentile,
            expansion_atr_ratio=config.regime.expansion_atr_ratio,
            contraction_atr_ratio=config.regime.contraction_atr_ratio,
            trend_break_ratio=config.regime.trend_break_ratio,
            trend_min_bos=config.regime.trend_min_bos,
            range_efficiency_max=config.regime.range_efficiency_max,
        )
    overlays = context.secondary_value or "none"
    print(
        f"Stored {symbol} {timeframe} regime={context.effective_value} "
        f"overlays={overlays} confidence={context.effective_confidence:.2f} "
        f"from {context.valid_from}"
    )


def cmd_context_summary(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = args.symbol or config.symbol
    db_path = args.db or config.database
    with connect(db_path) as conn:
        init_db(conn)
        rows = latest_contexts(
            conn,
            symbol=symbol,
            timeframe=args.timeframe,
            context_type=args.context_type,
        )
    if not rows:
        print("No market contexts found.")
        return
    for row in rows:
        metadata = json.loads(str(row["metadata_json"]))
        detail = metadata.get("raw_score")
        if row["context_type"] == "regime":
            detail = (
                f"overlays={metadata.get('overlays', [])} "
                f"atr_pct={metadata.get('atr_percentile')} "
                f"range_eff={metadata.get('range_efficiency')}"
            )
        print(
            f"{row['symbol']} {row['timeframe']} {row['context_type']}: "
            f"{row['effective_value']} conf={row['effective_confidence']:.2f} "
            f"source={row['source']} status={row['status']} "
            f"valid_from={row['valid_from']} detail={detail}"
        )


def cmd_detect_zones(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = args.symbol or config.symbol
    timeframe = args.timeframe.upper()
    if timeframe != config.bias.timeframe.upper():
        raise SystemExit(f"Price zones are H1-context only; refusing to detect zones for {timeframe}.")
    sr_config = config.support_resistance
    lifecycle_config = config.zone_lifecycle
    reaction_config = config.zone_reaction
    decay_config = config.zone_decay
    db_path = args.db or config.database

    with connect(db_path) as conn:
        init_db(conn)
        count = detect_and_store_support_resistance_zones(
            conn,
            symbol=symbol,
            timeframe=timeframe,
            tolerance_pct=args.tolerance_pct if args.tolerance_pct is not None else sr_config.tolerance_pct,
            min_zone_width=args.min_zone_width if args.min_zone_width is not None else sr_config.min_zone_width,
            min_touches=args.min_touches if args.min_touches is not None else sr_config.min_touches,
            lookback_swings=args.lookback_swings if args.lookback_swings is not None else sr_config.lookback_swings,
            max_zones=args.max_zones if args.max_zones is not None else sr_config.max_zones,
            atr_width_multiplier=sr_config.atr_width_multiplier,
            close_break_buffer=lifecycle_config.close_break_buffer,
            close_break_buffer_atr_multiplier=lifecycle_config.close_break_buffer_atr_multiplier,
            recent_touch_lookback_candles=lifecycle_config.recent_touch_lookback_candles,
            age_decay_per_100_candles=lifecycle_config.age_decay_per_100_candles,
            freshness_bonus=lifecycle_config.freshness_bonus,
            invalidation_weight_multiplier=lifecycle_config.invalidation_weight_multiplier,
            reaction_window_candles=reaction_config.reaction_window_candles,
            min_reaction_atr=reaction_config.min_reaction_atr,
            strong_reaction_atr=reaction_config.strong_reaction_atr,
            recent_reaction_count=reaction_config.recent_reaction_count,
            max_healthy_touches=decay_config.max_healthy_touches,
            weak_touch_penalty=decay_config.weak_touch_penalty,
            too_many_touches_penalty=decay_config.too_many_touches_penalty,
            linger_penalty=decay_config.linger_penalty,
            false_break_refine_enabled=lifecycle_config.false_break_refine_enabled,
            false_break_refine_max_width_atr_multiplier=lifecycle_config.false_break_refine_max_width_atr_multiplier,
            false_break_parent_weight_multiplier=lifecycle_config.false_break_parent_weight_multiplier,
        )
    print(f"Stored {count} support/resistance zones for {symbol} {timeframe}")


def cmd_detect_smc_zones(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = args.symbol or config.symbol
    timeframe = args.timeframe.upper()
    if timeframe != config.bias.timeframe.upper():
        raise SystemExit(f"Price zones are H1-context only; refusing to detect SMC zones for {timeframe}.")
    smc_config = config.smc_zones
    db_path = args.db or config.database

    with connect(db_path) as conn:
        init_db(conn)
        counts = detect_and_store_smc_zones(
            conn,
            symbol=symbol,
            timeframe=timeframe,
            max_candles=args.max_candles if args.max_candles is not None else smc_config.max_candles,
            lookback_swings=args.lookback_swings if args.lookback_swings is not None else smc_config.lookback_swings,
            fvg_middle_candle_atr_multiplier=args.fvg_middle_candle_atr_multiplier
            if args.fvg_middle_candle_atr_multiplier is not None
            else smc_config.fvg_middle_candle_atr_multiplier,
            fvg_gap_atr_ratio=args.fvg_gap_atr_ratio if args.fvg_gap_atr_ratio is not None else smc_config.fvg_gap_atr_ratio,
            fvg_min_width_atr_ratio=args.fvg_min_width_atr_ratio
            if args.fvg_min_width_atr_ratio is not None
            else smc_config.fvg_min_width_atr_ratio,
            fvg_max_width_atr_ratio=args.fvg_max_width_atr_ratio
            if args.fvg_max_width_atr_ratio is not None
            else smc_config.fvg_max_width_atr_ratio,
            fvg_third_candle_follow_through_required=not args.fvg_allow_no_third_candle_follow_through
            if args.fvg_allow_no_third_candle_follow_through
            else smc_config.fvg_third_candle_follow_through_required,
            fvg_third_candle_min_body_ratio=args.fvg_third_candle_min_body_ratio
            if args.fvg_third_candle_min_body_ratio is not None
            else smc_config.fvg_third_candle_min_body_ratio,
            fvg_max_active_days=smc_config.fvg_max_active_days_for(timeframe),
            fvg_decay_start_days=smc_config.fvg_decay_start_days_for(timeframe),
            ob_displacement_atr_multiplier=args.ob_displacement_atr_multiplier
            if args.ob_displacement_atr_multiplier is not None
            else smc_config.ob_displacement_atr_multiplier,
            ob_min_body_ratio=args.ob_min_body_ratio if args.ob_min_body_ratio is not None else smc_config.ob_min_body_ratio,
            ob_min_width_atr_ratio=args.ob_min_width_atr_ratio
            if args.ob_min_width_atr_ratio is not None
            else smc_config.ob_min_width_atr_ratio,
            ob_max_width_atr_ratio=args.ob_max_width_atr_ratio
            if args.ob_max_width_atr_ratio is not None
            else smc_config.ob_max_width_atr_ratio,
            ob_require_structure_break=not args.ob_allow_without_structure_break
            if args.ob_allow_without_structure_break
            else smc_config.ob_require_structure_break,
            ob_merge_overlap_ratio=args.ob_merge_overlap_ratio
            if args.ob_merge_overlap_ratio is not None
            else smc_config.ob_merge_overlap_ratio,
            ob_max_active_days=smc_config.ob_max_active_days_for(timeframe),
            ob_decay_start_days=smc_config.ob_decay_start_days_for(timeframe),
            max_fvg_zones=args.max_fvg_zones if args.max_fvg_zones is not None else smc_config.max_fvg_zones,
            max_order_block_zones=args.max_order_block_zones
            if args.max_order_block_zones is not None
            else smc_config.max_order_block_zones,
            max_liquidity_zones=args.max_liquidity_zones
            if args.max_liquidity_zones is not None
            else smc_config.max_liquidity_zones,
            max_consolidation_zones=args.max_consolidation_zones
            if args.max_consolidation_zones is not None
            else smc_config.max_consolidation_zones,
        )
    summary = ", ".join(f"{detector}={count}" for detector, count in counts.items())
    print(f"Stored SMC zones for {symbol} {timeframe}: {summary}")


def cmd_materialize_zones(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = args.symbol or config.symbol
    timeframe = args.timeframe.upper()
    if timeframe != config.bias.timeframe.upper():
        raise SystemExit(f"Price zones are H1-context only; refusing to materialize zones for {timeframe}.")
    detectors = parse_incremental_zone_detectors(args.detectors)
    db_path = args.db or config.database

    with connect(db_path) as conn:
        init_db(conn)
        counts = materialize_incremental_zones(
            conn,
            config,
            symbol=symbol,
            timeframe=timeframe,
            limit=args.limit,
            detectors=detectors,
            progress_every=args.progress_every,
        )
    summary = ", ".join(f"{detector}={counts.get(detector, 0)}" for detector in sorted(detectors))
    print(f"Materialized incremental zones for {symbol} {timeframe}: {summary}")


def cmd_detect_price_action(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = args.symbol or config.symbol
    timeframe = (args.timeframe or config.price_action.timeframe).upper()
    pa_config = config.price_action
    db_path = args.db or config.database

    with connect(db_path) as conn:
        init_db(conn)
        count = detect_and_store_price_action_patterns(
            conn,
            symbol=symbol,
            timeframe=timeframe,
            atr_period=args.atr_period if args.atr_period is not None else pa_config.atr_period,
            displacement_atr_multiplier=args.displacement_atr_multiplier
            if args.displacement_atr_multiplier is not None
            else pa_config.displacement_atr_multiplier,
            displacement_body_ratio=args.displacement_body_ratio
            if args.displacement_body_ratio is not None
            else pa_config.displacement_body_ratio,
            pinbar_wick_body_ratio=args.pinbar_wick_body_ratio
            if args.pinbar_wick_body_ratio is not None
            else pa_config.pinbar_wick_body_ratio,
            pinbar_min_wick_ratio=args.pinbar_min_wick_ratio
            if args.pinbar_min_wick_ratio is not None
            else pa_config.pinbar_min_wick_ratio,
            engulfing_min_body_ratio=args.engulfing_min_body_ratio
            if args.engulfing_min_body_ratio is not None
            else pa_config.engulfing_min_body_ratio,
            marubozu_min_body_ratio=args.marubozu_min_body_ratio
            if args.marubozu_min_body_ratio is not None
            else pa_config.marubozu_min_body_ratio,
            star_large_body_ratio=args.star_large_body_ratio
            if args.star_large_body_ratio is not None
            else pa_config.star_large_body_ratio,
            star_small_body_ratio=args.star_small_body_ratio
            if args.star_small_body_ratio is not None
            else pa_config.star_small_body_ratio,
        )
    print(f"Stored {count} price action events for {symbol} {timeframe}")


def cmd_apply_zone_lifecycle(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = args.symbol or config.symbol
    timeframe = args.timeframe
    lifecycle_config = config.zone_lifecycle
    reaction_config = config.zone_reaction
    decay_config = config.zone_decay
    db_path = args.db or config.database

    with connect(db_path) as conn:
        init_db(conn)
        count = apply_and_store_zone_lifecycle(
            conn,
            symbol=symbol,
            timeframe=timeframe,
            close_break_buffer=args.close_break_buffer
            if args.close_break_buffer is not None
            else lifecycle_config.close_break_buffer,
            recent_touch_lookback_candles=lifecycle_config.recent_touch_lookback_candles,
            age_decay_per_100_candles=lifecycle_config.age_decay_per_100_candles,
            freshness_bonus=lifecycle_config.freshness_bonus,
            invalidation_weight_multiplier=lifecycle_config.invalidation_weight_multiplier,
            close_break_buffer_atr_multiplier=lifecycle_config.close_break_buffer_atr_multiplier,
            reaction_window_candles=reaction_config.reaction_window_candles,
            min_reaction_atr=reaction_config.min_reaction_atr,
            strong_reaction_atr=reaction_config.strong_reaction_atr,
            recent_reaction_count=reaction_config.recent_reaction_count,
            max_healthy_touches=decay_config.max_healthy_touches,
            weak_touch_penalty=decay_config.weak_touch_penalty,
            too_many_touches_penalty=decay_config.too_many_touches_penalty,
            linger_penalty=decay_config.linger_penalty,
            false_break_refine_enabled=lifecycle_config.false_break_refine_enabled,
            false_break_refine_max_width_atr_multiplier=lifecycle_config.false_break_refine_max_width_atr_multiplier,
            false_break_parent_weight_multiplier=lifecycle_config.false_break_parent_weight_multiplier,
        )
    print(f"Applied lifecycle/scoring to {count} zones for {symbol} {timeframe}")


def cmd_zone_summary(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = args.symbol or config.symbol
    db_path = args.db or config.database
    with connect(db_path) as conn:
        init_db(conn)
        rows = zone_summary(conn, symbol=symbol, timeframe=args.timeframe, limit=args.limit)
    if not rows:
        print("No zones found.")
        return
    for row in rows:
        metadata = json.loads(str(row["metadata_json"]))
        print(
            f"{row['symbol']} {row['timeframe']} {row['zone_type']} "
            f"{row['price_low']:.2f}-{row['price_high']:.2f} "
            f"weight={row['effective_weight']:.2f} conf={row['effective_confidence']:.2f} "
            f"status={row['status']} touches={metadata.get('touch_count_total', metadata.get('touch_count'))} "
            f"end={row['end_time']} start={row['start_time']} detected={row['detected_at']}"
        )


def cmd_export_chart_json(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = args.symbol or config.symbol
    db_path = args.db or config.database
    structure_timeframe = args.structure_timeframe or config.bias.timeframe
    with connect(db_path) as conn:
        init_db(conn)
        payload = build_chart_payload(
            conn,
            symbol=symbol,
            timeframe=args.timeframe,
            limit=args.limit,
            start=args.start,
            end=args.end,
            active_zones_only=args.active_zones_only,
            structure_timeframe=structure_timeframe,
        )

    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
        print(
            f"Wrote chart payload to {args.output} "
            f"({len(payload['layers']['candles'])} candles, "
            f"{len(payload['layers']['structure'])} structure points, "
            f"{len(payload['layers']['zones'])} zones)"
        )
    else:
        print(text)


def cmd_serve_chart(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    run_chart_server(config=config, host=args.host, port=args.port)


def cmd_serve_api(args: argparse.Namespace) -> None:
    from .api import run_api_server

    run_api_server(config_path=args.config, host=args.host, port=args.port, reload=args.reload)


def cmd_hash_password(args: argparse.Namespace) -> None:
    """Interactively prompt for a password and print its bcrypt hash."""
    import getpass

    from .auth import hash_password

    password = getpass.getpass("Enter password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match.")
        raise SystemExit(1)
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        raise SystemExit(1)
    hashed = hash_password(password)
    print("\nAdd this line to your .env file:")
    print(f'ADMIN_PASSWORD_HASH="{hashed}"')


def cmd_telegram_test(args: argparse.Namespace) -> None:
    from .alerts import queue_alert, send_pending_telegram_alerts
    from .runtime_env import load_runtime_env

    config = load_config(args.config)
    env = load_runtime_env(args.env)
    with connect(config.database) as conn:
        init_db(conn)
        queued = queue_alert(
            conn,
            symbol=config.symbol,
            timeframe=config.strategy.timeframe,
            event_type="system",
            severity="info",
            entity_ids=[],
            payload={
                "title": "Telegram connection test",
                "reason": ["Semi Bot Trading can send Telegram notifications."],
                "chart_url": env.chart_url_base,
            },
            dedupe_key=f"telegram-test:{args.message_key}",
        )
        sent = send_pending_telegram_alerts(conn, token=env.telegram_token, chat_id=env.telegram_chat_id, environment=env.environment)
    print(f"Telegram test queued={queued} sent={sent}")


def cmd_fetch_news(args: argparse.Namespace) -> None:
    """Fetch ForexFactory economic calendar and upsert tier-1/2 USD events into DB."""
    from .news_calendar import fetch_and_store_news

    config = load_config(args.config)
    with connect(config.database) as conn:
        init_db(conn)
        n = fetch_and_store_news(conn)
    print(f"fetch-news: upserted {n} tier-1/2 events into {config.database}")


def cmd_live_worker(args: argparse.Namespace) -> None:
    from .live_worker import run_live_worker
    from .runtime_env import load_runtime_env

    config = load_config(args.config)
    env = load_runtime_env(args.env)
    print(
        f"Starting live worker local_symbol={config.symbol} broker_symbol={env.mt5_symbol} "
        f"execution_enabled={env.execution_enabled} poll_seconds={env.poll_seconds} "
        f"intrabar={env.live_evaluate_intrabar}"
    )
    run_live_worker(config, env, once=args.once)


def cmd_backtest_strategies(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = args.symbol or config.symbol
    db_path = args.db or config.database
    allowed_playbooks = parse_playbooks_arg(args.playbook)
    allowed_zone_types = parse_zone_types_arg(getattr(args, "zone_type", None))
    with connect(db_path) as conn:
        init_db(conn)
        result = run_strategy_backtest(
            conn,
            config,
            symbol=symbol,
            limit=args.limit,
            spread=args.spread,
            slippage=args.slippage,
            max_hold_candles=args.max_hold_candles,
            warmup_candles=args.warmup_candles,
            auto_accept=False if args.no_auto_accept else None,
            engine=args.engine,
            include_human_zones=args.include_human_zones,
            allowed_playbooks=allowed_playbooks,
            allowed_zone_types=allowed_zone_types,
        )
        run_id = None
        if args.persist:
            run_id = persist_backtest_result(
                conn,
                result,
                candle_limit=args.limit,
                clear_previous=args.clear_backtest_trades,
            )

    print(
        f"Backtest {symbol} {config.strategy.timeframe}: "
        f"{len(result.trades)} trades, {result.evaluated_candles}/{result.timeline_count} candles evaluated"
    )
    print(f"Costs: spread={result.spread:.2f}, slippage={result.slippage:.2f}")
    print(f"Engine: {result.engine}")
    if allowed_playbooks:
        print(f"Playbooks: {', '.join(sorted(allowed_playbooks))}")
    print(f"Auto accept eligible setups: {result.auto_accept}")
    print(f"Lookahead guard: {result.lookahead_guard}")
    if run_id:
        print(f"Persisted backtest run: {run_id}")
    write_html_report(args.html_output, render_backtest_html(result, max_rows=args.max_rows))
    rows = result.summary_by_playbook()
    if not rows:
        print("No eligible strategy trades found.")
        return
    print("playbook,trades,wins,losses,win_rate,total_r,avg_r")
    for row in rows:
        print(
            f"{row['playbook']},{row['trades']},{row['wins']},{row['losses']},"
            f"{row['win_rate']:.2%},{row['total_r']:.2f},{row['avg_r']:.2f}"
        )


def cmd_backtest_report(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = args.symbol or config.symbol
    db_path = args.db or config.database
    allowed_playbooks = parse_playbooks_arg(args.playbook)
    allowed_zone_types = parse_zone_types_arg(getattr(args, "zone_type", None))
    with connect(db_path) as conn:
        init_db(conn)
        result = run_strategy_backtest(
            conn,
            config,
            symbol=symbol,
            limit=args.limit,
            spread=args.spread,
            slippage=args.slippage,
            max_hold_candles=args.max_hold_candles,
            warmup_candles=args.warmup_candles,
            auto_accept=False if args.no_auto_accept else None,
            engine=args.engine,
            include_human_zones=args.include_human_zones,
            allowed_playbooks=allowed_playbooks,
            allowed_zone_types=allowed_zone_types,
        )
        run_id = None
        if args.persist:
            run_id = persist_backtest_result(
                conn,
                result,
                candle_limit=args.limit,
                clear_previous=args.clear_backtest_trades,
            )
    print(render_backtest_report(result, max_rows=args.max_rows))
    if run_id:
        print(f"Persisted backtest run: {run_id}")
    write_html_report(args.html_output, render_backtest_html(result, max_rows=args.max_rows))


def cmd_research_events(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = args.symbol or config.symbol
    db_path = args.db or config.database
    allowed_playbooks = parse_playbooks_arg(args.playbook)
    statuses = parse_statuses_arg(args.statuses)
    with connect(db_path) as conn:
        init_db(conn)
        result = run_research_events(
            conn,
            config,
            symbol=symbol,
            limit=args.limit,
            output=args.output,
            statuses=statuses,
            allowed_playbooks=allowed_playbooks,
            spread=args.spread,
            slippage=args.slippage,
            max_hold_candles=args.max_hold_candles,
            warmup_candles=args.warmup_candles,
            include_human_zones=args.include_human_zones,
            train_end_year=args.train_end_year,
            validation_year=args.validation_year,
        )
    print(
        f"Research events {symbol} {config.strategy.timeframe}: "
        f"{len(result.rows)} events, {result.evaluated_candles}/{result.timeline_count} candles evaluated"
    )
    print(f"CSV output: {result.output}")
    print(f"Lookahead guard: {result.lookahead_guard}")


def cmd_research_report(args: argparse.Namespace) -> None:
    rows = read_research_csv(args.input)
    print(render_research_report(rows, max_rows=args.max_rows, min_samples=args.min_samples))
    write_html_report(args.html_output, render_research_html(rows, max_rows=args.max_rows, min_samples=args.min_samples))


def parse_zone_types_arg(values: list[str] | None) -> set[str] | None:
    if not values:
        return None
    zone_types: set[str] = set()
    for value in values:
        zone_types.update(item.strip() for item in value.split(",") if item.strip())
    all_known: set[str] = set()
    for types in PLAYBOOK_ZONE_TYPES.values():
        all_known.update(types)
    unknown = sorted(zone_types - all_known)
    if unknown:
        known = ", ".join(sorted(all_known))
        raise SystemExit(f"Unknown zone type(s): {', '.join(unknown)}. Known types: {known}")
    return zone_types or None


def parse_playbooks_arg(values: list[str] | None) -> set[str] | None:
    if not values:
        return None
    playbooks: set[str] = set()
    for value in values:
        playbooks.update(item.strip() for item in value.split(",") if item.strip())
    unknown = sorted(playbooks - set(PLAYBOOK_ZONE_TYPES))
    if unknown:
        known = ", ".join(sorted(PLAYBOOK_ZONE_TYPES))
        raise SystemExit(f"Unknown playbook(s): {', '.join(unknown)}. Known playbooks: {known}")
    return playbooks or None


def parse_statuses_arg(value: str | None) -> set[str] | None:
    if not value:
        return None
    allowed = {"watching", "waiting_confirmation", "eligible", "blocked", "expired"}
    statuses = {item.strip() for item in value.split(",") if item.strip()}
    unknown = sorted(statuses - allowed)
    if unknown:
        raise SystemExit(f"Unknown research status: {', '.join(unknown)}. Known statuses: {', '.join(sorted(allowed))}")
    return statuses or None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="semi-bot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    version_parser = subparsers.add_parser(
        "version",
        help="Print code version, git state, config, and runtime environment summary.",
    )
    add_common_config_arg(version_parser)
    add_common_env_arg(version_parser)
    version_parser.set_defaults(func=cmd_version)

    init_parser = subparsers.add_parser("init-db", help="Create or update the SQLite schema.")
    add_common_config_arg(init_parser)
    add_common_db_arg(init_parser)
    init_parser.set_defaults(func=cmd_init_db)

    import_parser = subparsers.add_parser("import-data", help="Import candle CSV files into SQLite.")
    add_common_config_arg(import_parser)
    add_common_db_arg(import_parser)
    import_parser.add_argument("--data-dir", type=Path)
    import_parser.set_defaults(func=cmd_import_data)

    summary_parser = subparsers.add_parser("db-summary", help="Show imported candle ranges and gaps.")
    add_common_config_arg(summary_parser)
    add_common_db_arg(summary_parser)
    summary_parser.set_defaults(func=cmd_db_summary)

    replay_parser = subparsers.add_parser("replay", help="Print candles in replay order.")
    add_common_config_arg(replay_parser)
    add_common_db_arg(replay_parser)
    replay_parser.add_argument("--symbol", default="XAUUSD")
    replay_parser.add_argument("--timeframe", default="M15")
    replay_parser.add_argument("--limit", type=int, default=10)
    replay_parser.add_argument("--start")
    replay_parser.set_defaults(func=cmd_replay)

    detect_parser = subparsers.add_parser(
        "detect-structure",
        help="Detect confirmed swing structure and HH/HL/LH/LL points.",
    )
    add_common_config_arg(detect_parser)
    add_common_db_arg(detect_parser)
    detect_parser.add_argument("--symbol")
    detect_parser.add_argument("--timeframe", default="M15")
    detect_parser.add_argument(
        "--window",
        type=int,
        help="Override pivot window from config.",
    )
    detect_parser.add_argument("--tolerance", type=float, help="Override pivot tolerance from config.")
    detect_parser.set_defaults(func=cmd_detect_structure)

    break_parser = subparsers.add_parser(
        "detect-breaks",
        help="Detect BOS/CHOCH events from stored confirmed swing structure.",
    )
    add_common_config_arg(break_parser)
    add_common_db_arg(break_parser)
    break_parser.add_argument("--symbol")
    break_parser.add_argument("--timeframe", default="M15")
    break_parser.add_argument(
        "--close-break-buffer",
        type=float,
        help="Override close break buffer from config.",
    )
    break_parser.set_defaults(func=cmd_detect_breaks)

    structure_parser = subparsers.add_parser(
        "structure-summary",
        help="Show stored structure point counts and latest points.",
    )
    add_common_config_arg(structure_parser)
    add_common_db_arg(structure_parser)
    structure_parser.add_argument("--symbol")
    structure_parser.add_argument("--timeframe", default="M15")
    structure_parser.add_argument("--limit", type=int, default=12)
    structure_parser.set_defaults(func=cmd_structure_summary)

    bias_parser = subparsers.add_parser(
        "detect-bias",
        help="Detect market bias from HH/HL/LH/LL plus BOS/CHOCH.",
    )
    add_common_config_arg(bias_parser)
    add_common_db_arg(bias_parser)
    bias_parser.add_argument("--symbol")
    bias_parser.add_argument("--timeframe")
    bias_parser.add_argument("--recent-swings", type=int)
    bias_parser.add_argument("--recent-breaks", type=int)
    bias_parser.set_defaults(func=cmd_detect_bias)

    macro_trend_parser = subparsers.add_parser(
        "detect-macro-trend",
        help="Detect slow macro trend from long-lookback momentum in ATR units.",
    )
    add_common_config_arg(macro_trend_parser)
    add_common_db_arg(macro_trend_parser)
    macro_trend_parser.add_argument("--symbol")
    macro_trend_parser.add_argument("--timeframe")
    macro_trend_parser.add_argument("--lookback-candles", type=int)
    macro_trend_parser.set_defaults(func=cmd_detect_macro_trend)

    regime_parser = subparsers.add_parser(
        "detect-regime",
        help="Detect market regime from ATR/range metrics plus BOS density.",
    )
    add_common_config_arg(regime_parser)
    add_common_db_arg(regime_parser)
    regime_parser.add_argument("--symbol")
    regime_parser.add_argument("--timeframe")
    regime_parser.add_argument("--atr-period", type=int)
    regime_parser.add_argument("--lookback", type=int)
    regime_parser.set_defaults(func=cmd_detect_regime)

    context_parser = subparsers.add_parser(
        "context-summary",
        help="Show stored market context values such as bias/regime.",
    )
    add_common_config_arg(context_parser)
    add_common_db_arg(context_parser)
    context_parser.add_argument("--symbol")
    context_parser.add_argument("--timeframe")
    context_parser.add_argument("--context-type")
    context_parser.set_defaults(func=cmd_context_summary)

    zones_parser = subparsers.add_parser(
        "detect-zones",
        help="Detect support/resistance zones from stored swing points.",
    )
    add_common_config_arg(zones_parser)
    add_common_db_arg(zones_parser)
    zones_parser.add_argument("--symbol")
    zones_parser.add_argument("--timeframe", default="H1")
    zones_parser.add_argument("--tolerance-pct", type=float)
    zones_parser.add_argument("--min-zone-width", type=float)
    zones_parser.add_argument("--min-touches", type=int)
    zones_parser.add_argument("--lookback-swings", type=int)
    zones_parser.add_argument("--max-zones", type=int)
    zones_parser.set_defaults(func=cmd_detect_zones)

    smc_zones_parser = subparsers.add_parser(
        "detect-smc-zones",
        help="Detect FVG, Order Block, Liquidity Sweep, and Consolidation zones.",
    )
    add_common_config_arg(smc_zones_parser)
    add_common_db_arg(smc_zones_parser)
    smc_zones_parser.add_argument("--symbol")
    smc_zones_parser.add_argument("--timeframe", default="H1")
    smc_zones_parser.add_argument("--max-candles", type=int)
    smc_zones_parser.add_argument("--lookback-swings", type=int)
    smc_zones_parser.add_argument("--fvg-middle-candle-atr-multiplier", type=float)
    smc_zones_parser.add_argument("--fvg-gap-atr-ratio", type=float)
    smc_zones_parser.add_argument("--fvg-min-width-atr-ratio", type=float)
    smc_zones_parser.add_argument("--fvg-max-width-atr-ratio", type=float)
    smc_zones_parser.add_argument("--fvg-allow-no-third-candle-follow-through", action="store_true")
    smc_zones_parser.add_argument("--fvg-third-candle-min-body-ratio", type=float)
    smc_zones_parser.add_argument("--ob-displacement-atr-multiplier", type=float)
    smc_zones_parser.add_argument("--ob-min-body-ratio", type=float)
    smc_zones_parser.add_argument("--ob-min-width-atr-ratio", type=float)
    smc_zones_parser.add_argument("--ob-max-width-atr-ratio", type=float)
    smc_zones_parser.add_argument("--ob-allow-without-structure-break", action="store_true")
    smc_zones_parser.add_argument("--ob-merge-overlap-ratio", type=float)
    smc_zones_parser.add_argument("--max-fvg-zones", type=int)
    smc_zones_parser.add_argument("--max-order-block-zones", type=int)
    smc_zones_parser.add_argument("--max-liquidity-zones", type=int)
    smc_zones_parser.add_argument("--max-consolidation-zones", type=int)
    smc_zones_parser.set_defaults(func=cmd_detect_smc_zones)

    materialize_zones_parser = subparsers.add_parser(
        "materialize-zones",
        help="Persist replay/backtest-style incremental SR/FVG zone snapshots into price_zones.",
    )
    add_common_config_arg(materialize_zones_parser)
    add_common_db_arg(materialize_zones_parser)
    materialize_zones_parser.add_argument("--symbol")
    materialize_zones_parser.add_argument("--timeframe", default="H1")
    materialize_zones_parser.add_argument(
        "--detectors",
        default="sr,fvg",
        help="Comma-separated detector aliases: sr, fvg. Default: sr,fvg.",
    )
    materialize_zones_parser.add_argument(
        "--limit",
        type=int,
        help="Use the latest N candles. Omit to walk the full timeframe history.",
    )
    materialize_zones_parser.add_argument(
        "--progress-every",
        type=int,
        default=1000,
        help="Print progress every N candles. Use 0 to disable.",
    )
    materialize_zones_parser.set_defaults(func=cmd_materialize_zones)

    price_action_parser = subparsers.add_parser(
        "detect-price-action",
        help="Detect M15 price action confirmations such as pinbar, engulfing, marubozu, stars, and displacement candles.",
    )
    add_common_config_arg(price_action_parser)
    add_common_db_arg(price_action_parser)
    price_action_parser.add_argument("--symbol")
    price_action_parser.add_argument("--timeframe")
    price_action_parser.add_argument("--atr-period", type=int)
    price_action_parser.add_argument("--displacement-atr-multiplier", type=float)
    price_action_parser.add_argument("--displacement-body-ratio", type=float)
    price_action_parser.add_argument("--pinbar-wick-body-ratio", type=float)
    price_action_parser.add_argument("--pinbar-min-wick-ratio", type=float)
    price_action_parser.add_argument("--engulfing-min-body-ratio", type=float)
    price_action_parser.add_argument("--marubozu-min-body-ratio", type=float)
    price_action_parser.add_argument("--star-large-body-ratio", type=float)
    price_action_parser.add_argument("--star-small-body-ratio", type=float)
    price_action_parser.set_defaults(func=cmd_detect_price_action)

    lifecycle_parser = subparsers.add_parser(
        "apply-zone-lifecycle",
        help="Apply invalidation and freshness scoring to existing zones.",
    )
    add_common_config_arg(lifecycle_parser)
    add_common_db_arg(lifecycle_parser)
    lifecycle_parser.add_argument("--symbol")
    lifecycle_parser.add_argument("--timeframe", default="H1")
    lifecycle_parser.add_argument("--close-break-buffer", type=float)
    lifecycle_parser.set_defaults(func=cmd_apply_zone_lifecycle)

    zone_summary_parser = subparsers.add_parser(
        "zone-summary",
        help="Show stored price zones.",
    )
    add_common_config_arg(zone_summary_parser)
    add_common_db_arg(zone_summary_parser)
    zone_summary_parser.add_argument("--symbol")
    zone_summary_parser.add_argument("--timeframe")
    zone_summary_parser.add_argument("--limit", type=int, default=20)
    zone_summary_parser.set_defaults(func=cmd_zone_summary)

    chart_parser = subparsers.add_parser(
        "export-chart-json",
        help="Export chart-ready JSON payload for candles, structure, zones, contexts, and trades.",
    )
    add_common_config_arg(chart_parser)
    add_common_db_arg(chart_parser)
    chart_parser.add_argument("--symbol")
    chart_parser.add_argument("--timeframe", default="M15")
    chart_parser.add_argument("--limit", type=int, default=300)
    chart_parser.add_argument("--start")
    chart_parser.add_argument("--end")
    chart_parser.add_argument(
        "--structure-timeframe",
        help="Timeframe used for market structure overlays. Defaults to context.bias.timeframe from config.",
    )
    chart_parser.add_argument("--active-zones-only", action="store_true")
    chart_parser.add_argument("--output", type=Path)
    chart_parser.set_defaults(func=cmd_export_chart_json)

    backtest_parser = subparsers.add_parser(
        "backtest-strategies",
        help="Auto-accept eligible setup candidates in replay-safe backtest mode.",
    )
    add_common_config_arg(backtest_parser)
    add_common_db_arg(backtest_parser)
    backtest_parser.add_argument("--symbol")
    backtest_parser.add_argument("--limit", type=int, default=500)
    backtest_parser.add_argument("--spread", type=float)
    backtest_parser.add_argument("--slippage", type=float)
    backtest_parser.add_argument("--max-hold-candles", type=int)
    backtest_parser.add_argument("--warmup-candles", type=int)
    backtest_parser.add_argument("--no-auto-accept", action="store_true")
    backtest_parser.add_argument("--engine", choices=["incremental", "replay"], default="incremental")
    backtest_parser.add_argument(
        "--playbook",
        action="append",
        help="Only evaluate selected playbook. Repeat or comma-separate values, e.g. --playbook zone_reaction_v2.",
    )
    backtest_parser.add_argument(
        "--zone-type",
        action="append",
        help="Only evaluate zones of this type. Repeat or comma-separate values, e.g. --zone-type fvg.",
    )
    backtest_parser.add_argument(
        "--include-human-zones",
        action="store_true",
        help="Include manually drawn historical zones. Disabled by default to avoid hindsight in bot-only backtests.",
    )
    backtest_parser.add_argument("--persist", action="store_true", help="Store run/trades so they appear in chart payload.")
    backtest_parser.add_argument(
        "--clear-backtest-trades",
        action="store_true",
        help="Delete previous persisted backtest trades for this symbol before storing the new run.",
    )
    backtest_parser.add_argument("--max-rows", type=int, default=20)
    backtest_parser.add_argument(
        "--html-output",
        type=Path,
        help="Write a visual HTML report to this file.",
    )
    backtest_parser.set_defaults(func=cmd_backtest_strategies)

    report_parser = subparsers.add_parser(
        "backtest-report",
        help="Run strict strategy backtest and print edge breakdown by zone, regime, trigger, and score buckets.",
    )
    add_common_config_arg(report_parser)
    add_common_db_arg(report_parser)
    report_parser.add_argument("--symbol")
    report_parser.add_argument("--limit", type=int, default=500)
    report_parser.add_argument("--spread", type=float)
    report_parser.add_argument("--slippage", type=float)
    report_parser.add_argument("--max-hold-candles", type=int)
    report_parser.add_argument("--warmup-candles", type=int)
    report_parser.add_argument("--no-auto-accept", action="store_true")
    report_parser.add_argument("--engine", choices=["incremental", "replay"], default="incremental")
    report_parser.add_argument(
        "--playbook",
        action="append",
        help="Only evaluate selected playbook. Repeat or comma-separate values, e.g. --playbook zone_reaction_v2.",
    )
    report_parser.add_argument(
        "--zone-type",
        action="append",
        help="Only evaluate zones of this type. Repeat or comma-separate values, e.g. --zone-type fvg.",
    )
    report_parser.add_argument(
        "--include-human-zones",
        action="store_true",
        help="Include manually drawn historical zones. Disabled by default to avoid hindsight in bot-only reports.",
    )
    report_parser.add_argument("--persist", action="store_true", help="Store run/trades so they appear in chart payload.")
    report_parser.add_argument(
        "--clear-backtest-trades",
        action="store_true",
        help="Delete previous persisted backtest trades for this symbol before storing the new report run.",
    )
    report_parser.add_argument("--max-rows", type=int, default=20)
    report_parser.add_argument(
        "--html-output",
        type=Path,
        help="Write a visual HTML report to this file.",
    )
    report_parser.set_defaults(func=cmd_backtest_report)

    research_events_parser = subparsers.add_parser(
        "research-events",
        help="Generate setup-level research samples for edge discovery.",
    )
    add_common_config_arg(research_events_parser)
    add_common_db_arg(research_events_parser)
    research_events_parser.add_argument("--symbol")
    research_events_parser.add_argument("--limit", type=int, default=30000)
    research_events_parser.add_argument("--output", type=Path, default=Path("var/research_events.csv"))
    research_events_parser.add_argument("--spread", type=float)
    research_events_parser.add_argument("--slippage", type=float)
    research_events_parser.add_argument("--max-hold-candles", type=int)
    research_events_parser.add_argument("--warmup-candles", type=int)
    research_events_parser.add_argument(
        "--playbook",
        action="append",
        help="Only evaluate selected playbook. Repeat or comma-separate values, e.g. --playbook zone_reaction_v2.",
    )
    research_events_parser.add_argument(
        "--statuses",
        default="eligible,waiting_confirmation",
        help="Candidate statuses to sample. Default: eligible,waiting_confirmation.",
    )
    research_events_parser.add_argument(
        "--include-human-zones",
        action="store_true",
        help="Include manually drawn historical zones. Disabled by default to avoid hindsight in research.",
    )
    research_events_parser.add_argument("--train-end-year", type=int, default=2024)
    research_events_parser.add_argument("--validation-year", type=int, default=2025)
    research_events_parser.set_defaults(func=cmd_research_events)

    research_report_parser = subparsers.add_parser(
        "research-report",
        help="Summarize setup-level research CSV and optionally render an HTML edge report.",
    )
    research_report_parser.add_argument("--input", type=Path, default=Path("var/research_events.csv"))
    research_report_parser.add_argument("--max-rows", type=int, default=20)
    research_report_parser.add_argument("--min-samples", type=int, default=20)
    research_report_parser.add_argument("--html-output", type=Path)
    research_report_parser.set_defaults(func=cmd_research_report)

    serve_parser = subparsers.add_parser(
        "serve-chart",
        help="Serve the local dark chart UI and chart JSON API.",
    )
    add_common_config_arg(serve_parser)
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.set_defaults(func=cmd_serve_chart)

    api_parser = subparsers.add_parser(
        "serve-api",
        help="Serve the FastAPI backend for the React frontend.",
    )
    add_common_config_arg(api_parser)
    api_parser.add_argument("--host", default="127.0.0.1")
    api_parser.add_argument("--port", type=int, default=8000)
    api_parser.add_argument("--reload", action="store_true")
    api_parser.set_defaults(func=cmd_serve_api)

    telegram_test_parser = subparsers.add_parser(
        "telegram-test",
        help="Queue and send a Telegram system test message using .env credentials.",
    )
    add_common_config_arg(telegram_test_parser)
    add_common_env_arg(telegram_test_parser)
    telegram_test_parser.add_argument("--message-key", default="default")
    telegram_test_parser.set_defaults(func=cmd_telegram_test)

    live_worker_parser = subparsers.add_parser(
        "live-worker",
        help="Sync closed candles from MT5, refresh detectors, send Telegram alerts, and optionally auto-execute.",
    )
    add_common_config_arg(live_worker_parser)
    add_common_env_arg(live_worker_parser)
    live_worker_parser.add_argument("--once", action="store_true", help="Run one iteration and exit.")
    live_worker_parser.set_defaults(func=cmd_live_worker)

    fetch_news_parser = subparsers.add_parser(
        "fetch-news",
        help="Fetch ForexFactory economic calendar and upsert tier-1/2 USD events into DB. Run weekly via cron.",
    )
    add_common_config_arg(fetch_news_parser)
    fetch_news_parser.set_defaults(func=cmd_fetch_news)

    hash_pw_parser = subparsers.add_parser(
        "hash-password",
        help="Generate a bcrypt password hash to set as ADMIN_PASSWORD_HASH in .env.",
    )
    hash_pw_parser.set_defaults(func=cmd_hash_password)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
