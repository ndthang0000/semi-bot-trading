from __future__ import annotations

import argparse
import json
from pathlib import Path

from .candles import candle_summary, find_gaps
from .chart import build_chart_payload
from .config import DEFAULT_CONFIG_PATH, load_config
from .context import detect_and_store_bias, detect_and_store_regime, latest_contexts
from .db import DEFAULT_DB_PATH, connect, init_db
from .importer import import_data_dir
from .replay import replay_candles
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


def resolve_db_path(args: argparse.Namespace) -> Path:
    if args.db is not None:
        return args.db
    try:
        return load_config(args.config).database
    except FileNotFoundError:
        return DEFAULT_DB_PATH


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
    timeframe = args.timeframe
    sr_config = config.support_resistance
    lifecycle_config = config.zone_lifecycle
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
            close_break_buffer=lifecycle_config.close_break_buffer,
            recent_touch_lookback_candles=lifecycle_config.recent_touch_lookback_candles,
            age_decay_per_100_candles=lifecycle_config.age_decay_per_100_candles,
            freshness_bonus=lifecycle_config.freshness_bonus,
            invalidation_weight_multiplier=lifecycle_config.invalidation_weight_multiplier,
        )
    print(f"Stored {count} support/resistance zones for {symbol} {timeframe}")


def cmd_apply_zone_lifecycle(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    symbol = args.symbol or config.symbol
    timeframe = args.timeframe
    lifecycle_config = config.zone_lifecycle
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="semi-bot")
    subparsers = parser.add_subparsers(dest="command", required=True)

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

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
