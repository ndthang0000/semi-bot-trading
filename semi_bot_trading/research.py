from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
from html import escape
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from .backtest import (
    INCREMENTAL_CHUNK_OVERLAP,
    INCREMENTAL_CHUNK_SIZE,
    build_incremental_timeline,
    candle_decision_time,
    candle_open_time,
    candidates_for_backtest_execution,
    load_backtest_candles,
    rank_active_zones,
    simulate_trade,
)
from .config import AppConfig


DEFAULT_RESEARCH_STATUSES = {"eligible", "waiting_confirmation"}
RESEARCH_LOOKAHEAD_GUARD = (
    "Research events use incremental closed-candle snapshots. Candidate context, zones, "
    "structure, and triggers are only exposed up to the signal candle close; outcome is "
    "measured from the next M15 candle open."
)


RESEARCH_COLUMNS = [
    "event_id",
    "split",
    "signal_year",
    "signal_time",
    "entry_time",
    "exit_time",
    "playbook",
    "direction",
    "candidate_status",
    "exit_status",
    "pnl_r",
    "mfe_r",
    "mae_r",
    "risk_reward",
    "score",
    "zone_reaction_state",
    "reaction_v2",
    "confluence_count",
    "confluence_types",
    "confluence_score_bonus",
    "zone_type",
    "zone_direction",
    "zone_detector",
    "zone_source",
    "zone_weight",
    "zone_confidence",
    "zone_width_atr",
    "zone_touch_count",
    "zone_fill_ratio",
    "zone_mitigation_ratio",
    "h1_bias",
    "h1_regime",
    "overlays",
    "trigger_types",
    "primary_zone_id",
    "blocked_reason",
    "reason",
]


@dataclass(frozen=True)
class ResearchRunResult:
    rows: list[dict[str, Any]]
    evaluated_candles: int
    timeline_count: int
    output: Path
    lookahead_guard: str = RESEARCH_LOOKAHEAD_GUARD


@dataclass(frozen=True)
class ResearchSummaryRow:
    key: str
    samples: int
    wins: int
    losses: int
    win_rate: float
    total_r: float
    avg_r: float
    profit_factor: float | None
    avg_mfe_r: float
    avg_mae_r: float


def run_research_events(
    conn: Connection,
    config: AppConfig,
    symbol: str,
    limit: int,
    output: Path,
    statuses: set[str] | None = None,
    allowed_playbooks: set[str] | None = None,
    spread: float | None = None,
    slippage: float | None = None,
    max_hold_candles: int | None = None,
    warmup_candles: int | None = None,
    include_human_zones: bool = False,
    train_end_year: int = 2024,
    validation_year: int = 2025,
) -> ResearchRunResult:
    effective_statuses = statuses or DEFAULT_RESEARCH_STATUSES
    effective_spread = config.backtest.spread if spread is None else spread
    effective_slippage = config.backtest.slippage if slippage is None else slippage
    effective_max_hold = config.backtest.max_hold_candles if max_hold_candles is None else max_hold_candles
    effective_warmup = config.backtest.warmup_candles if warmup_candles is None else warmup_candles

    candles = load_backtest_candles(conn, symbol, config.strategy.timeframe, limit)
    research_config = replace(
        config,
        strategy=replace(config.strategy, max_eligible=500, max_waiting=500),
    )
    rows: list[dict[str, Any]] = []
    if len(candles) < effective_warmup + 2:
        write_research_csv(output, rows)
        return ResearchRunResult(rows=rows, evaluated_candles=0, timeline_count=len(candles), output=output)

    segment_start = effective_warmup
    while segment_start < len(candles) - 1:
        segment_end = min(len(candles) - 1, segment_start + INCREMENTAL_CHUNK_SIZE)
        chunk_start = max(0, segment_start - max(INCREMENTAL_CHUNK_OVERLAP, effective_warmup))
        chunk_end = min(len(candles), segment_end + effective_max_hold + 2)
        chunk_candles = candles[chunk_start:chunk_end]
        detector_candles = candles[chunk_start:segment_end]
        timeline = build_incremental_timeline(
            conn,
            research_config,
            symbol,
            detector_candles,
            include_human_zones=include_human_zones,
            allowed_playbooks=allowed_playbooks,
        )
        local_eval_start = segment_start - chunk_start
        local_eval_end = segment_end - chunk_start
        for local_signal_index in range(local_eval_start, local_eval_end):
            global_signal_index = chunk_start + local_signal_index
            if global_signal_index < 0 or global_signal_index >= len(candles) - 1:
                continue
            if global_signal_index % 1000 == 0:
                print(f"Research progress: {global_signal_index}/{len(candles) - 1} candles evaluated, events={len(rows)}")
            signal_time = candle_decision_time(chunk_candles[local_signal_index])
            last_close = float(chunk_candles[local_signal_index]["close"])
            candidate_zones = rank_active_zones(timeline.zones_at(signal_time), last_close)
            candidates = candidates_for_backtest_execution(
                timeline.setup_candidates_at(signal_time, local_signal_index, candidate_zones),
                effective_statuses,
            )
            for candidate in candidates:
                trade = simulate_trade(
                    candidate,
                    chunk_candles,
                    local_signal_index,
                    effective_spread,
                    effective_slippage,
                    effective_max_hold,
                )
                if trade is None:
                    continue
                outcome = compute_future_excursion(candidate, chunk_candles, local_signal_index, effective_spread, effective_slippage, effective_max_hold)
                rows.append(
                    research_row_from_candidate(
                        candidate,
                        trade,
                        outcome,
                        split_for_time(trade.signal_time, train_end_year, validation_year),
                    )
                )
        segment_start = segment_end

    write_research_csv(output, rows)
    return ResearchRunResult(
        rows=rows,
        evaluated_candles=max(len(candles) - effective_warmup - 1, 0),
        timeline_count=len(candles),
        output=output,
    )


def compute_future_excursion(
    candidate: dict[str, Any],
    candles: list[dict[str, Any]],
    signal_index: int,
    spread: float,
    slippage: float,
    max_hold_candles: int,
) -> dict[str, float]:
    entry_index = signal_index + 1
    if entry_index >= len(candles):
        return {"mfe_r": 0.0, "mae_r": 0.0}
    direction = str(candidate["direction"])
    stop_loss = candidate.get("stop_loss")
    if stop_loss is None:
        return {"mfe_r": 0.0, "mae_r": 0.0}
    raw_open = float(candles[entry_index]["open"])
    half_spread = spread / 2
    if direction == "long":
        entry_price = raw_open + half_spread + slippage
        risk = entry_price - float(stop_loss)
    else:
        entry_price = raw_open - half_spread - slippage
        risk = float(stop_loss) - entry_price
    if risk <= 0:
        return {"mfe_r": 0.0, "mae_r": 0.0}

    max_favorable = 0.0
    max_adverse = 0.0
    end_index = min(len(candles) - 1, entry_index + max_hold_candles)
    for candle in candles[entry_index : end_index + 1]:
        high = float(candle["high"])
        low = float(candle["low"])
        if direction == "long":
            favorable = (high - half_spread - entry_price) / risk
            adverse = (low - half_spread - entry_price) / risk
        else:
            favorable = (entry_price - (low + half_spread)) / risk
            adverse = (entry_price - (high + half_spread)) / risk
        max_favorable = max(max_favorable, favorable)
        max_adverse = min(max_adverse, adverse)
    return {"mfe_r": round(max_favorable, 5), "mae_r": round(max_adverse, 5)}


def research_row_from_candidate(
    candidate: dict[str, Any],
    trade: Any,
    outcome: dict[str, float],
    split: str,
) -> dict[str, Any]:
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
    signal_year = parse_year(trade.signal_time)
    return {
        "event_id": candidate.get("id") or trade.setup_id,
        "split": split,
        "signal_year": signal_year,
        "signal_time": trade.signal_time,
        "entry_time": candle_open_time({"open_time": trade.entry_time}),
        "exit_time": trade.exit_time,
        "playbook": candidate.get("playbook"),
        "direction": candidate.get("direction"),
        "candidate_status": candidate.get("status"),
        "exit_status": trade.status,
        "pnl_r": trade.pnl_r,
        "mfe_r": outcome["mfe_r"],
        "mae_r": outcome["mae_r"],
        "risk_reward": candidate.get("risk_reward"),
        "score": candidate.get("score"),
        "zone_reaction_state": candidate.get("zone_reaction_state"),
        "reaction_v2": metadata.get("reaction_v2"),
        "confluence_count": metadata.get("confluence_count"),
        "confluence_types": list_to_key(metadata.get("confluence_types")),
        "confluence_score_bonus": metadata.get("confluence_score_bonus"),
        "zone_type": metadata.get("zone_type"),
        "zone_direction": metadata.get("zone_direction"),
        "zone_detector": metadata.get("zone_detector"),
        "zone_source": metadata.get("zone_source"),
        "zone_weight": metadata.get("zone_weight"),
        "zone_confidence": metadata.get("zone_confidence"),
        "zone_width_atr": metadata.get("zone_width_atr"),
        "zone_touch_count": metadata.get("zone_touch_count"),
        "zone_fill_ratio": metadata.get("zone_fill_ratio"),
        "zone_mitigation_ratio": metadata.get("zone_mitigation_ratio"),
        "h1_bias": metadata.get("h1_bias"),
        "h1_regime": metadata.get("h1_regime"),
        "overlays": list_to_key(metadata.get("overlays")),
        "trigger_types": list_to_key(metadata.get("trigger_types")),
        "primary_zone_id": candidate.get("primary_zone_id"),
        "blocked_reason": list_to_key(candidate.get("blocked_reason")),
        "reason": list_to_key(candidate.get("reason")),
    }


def write_research_csv(output: Path, rows: list[dict[str, Any]]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESEARCH_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: csv_value(row.get(column)) for column in RESEARCH_COLUMNS})


def read_research_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def render_research_report(rows: list[dict[str, str]], max_rows: int = 20, min_samples: int = 20) -> str:
    lines: list[str] = []
    lines.append(f"Research report: {len(rows)} setup events")
    lines.append(f"Lookahead guard: {RESEARCH_LOOKAHEAD_GUARD}")
    lines.append("")
    if not rows:
        lines.append("No research events found.")
        return "\n".join(lines)
    append_research_section(lines, "By split", summarize_research(rows, lambda row: row.get("split", "--")), max_rows)
    append_research_section(lines, "Potential condition sets", potential_condition_sets(rows, min_samples), max_rows)
    for title, dimension in research_sections():
        append_research_section(lines, title, summarize_research(rows, dimension), max_rows)
    return "\n".join(lines)


def render_research_html(rows: list[dict[str, str]], max_rows: int = 20, min_samples: int = 20) -> str:
    sections = [("Potential condition sets", potential_condition_sets(rows, min_samples))]
    sections.extend((title, summarize_research(rows, dimension)) for title, dimension in research_sections())
    total_r = sum(float_value(row.get("pnl_r")) for row in rows)
    wins = [row for row in rows if float_value(row.get("pnl_r")) > 0]
    losses = [row for row in rows if float_value(row.get("pnl_r")) <= 0]
    gross_win = sum(float_value(row.get("pnl_r")) for row in wins)
    gross_loss = abs(sum(float_value(row.get("pnl_r")) for row in losses))
    profit_factor = gross_win / gross_loss if gross_loss > 0 else None
    split_rows = summarize_research(rows, lambda row: row.get("split", "--"))

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Research Edge Report</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg:#071017; --panel:#0c1621; --panel2:#111d2a; --line:#213348;
      --text:#eef4fb; --muted:#8fa1b7; --cyan:#42d8ef; --green:#58d69b;
      --red:#ff778b; --yellow:#ffd35f;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    header {{ position:sticky; top:0; z-index:4; padding:22px 28px; background:rgba(7,16,23,.92); border-bottom:1px solid var(--line); backdrop-filter:blur(10px); }}
    h1 {{ margin:0; font-size:28px; }}
    main {{ max-width:1480px; margin:0 auto; padding:24px 28px 44px; }}
    .sub {{ color:var(--muted); margin-top:6px; }}
    .grid {{ display:grid; gap:14px; }}
    .kpis {{ grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); margin-bottom:18px; }}
    .card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }}
    .label {{ color:var(--muted); font-size:13px; }}
    .value {{ margin-top:8px; font-size:26px; font-weight:750; }}
    .positive {{ color:var(--green); }} .negative {{ color:var(--red); }} .neutral {{ color:var(--yellow); }}
    .note {{ color:var(--muted); background:rgba(66,216,239,.06); border:1px solid rgba(66,216,239,.25); border-radius:8px; padding:14px 16px; margin-bottom:18px; }}
    .section-grid {{ grid-template-columns:repeat(auto-fit,minmax(560px,1fr)); }}
    h2 {{ margin:0 0 12px; font-size:18px; }}
    table {{ width:100%; border-collapse:collapse; font-size:14px; }}
    th,td {{ padding:9px 10px; border-bottom:1px solid rgba(143,161,183,.16); text-align:right; vertical-align:top; }}
    th:first-child,td:first-child {{ text-align:left; }}
    th {{ color:var(--muted); font-weight:650; }}
    tr:hover td {{ background:rgba(66,216,239,.05); }}
    @media(max-width:760px) {{ header,main {{ padding-left:14px; padding-right:14px; }} .section-grid {{ grid-template-columns:1fr; }} table {{ font-size:12px; }} }}
  </style>
</head>
<body>
  <header>
    <h1>Research Edge Report</h1>
    <div class="sub">{len(rows)} setup events · train/validation/test split</div>
  </header>
  <main>
    <section class="grid kpis">
      {metric_card("Samples", len(rows))}
      {metric_card("Total R", total_r, "R", signed=True)}
      {metric_card("Win Rate", (len(wins) / len(rows) * 100) if rows else 0, "%")}
      {metric_card("Profit Factor", profit_factor)}
    </section>
    <div class="note">{escape(RESEARCH_LOOKAHEAD_GUARD)}</div>
    <section class="grid section-grid">
      {research_table_card("By split", split_rows, max_rows)}
      {"".join(research_table_card(title, section_rows, max_rows) for title, section_rows in sections)}
    </section>
  </main>
</body>
</html>"""


def research_sections() -> list[tuple[str, Any]]:
    return [
        ("By playbook", lambda row: row.get("playbook", "--")),
        ("By candidate status", lambda row: row.get("candidate_status", "--")),
        ("By direction", lambda row: row.get("direction", "--")),
        ("By H1 bias", lambda row: row.get("h1_bias", "--")),
        ("By H1 regime", lambda row: row.get("h1_regime", "--")),
        ("By overlays", lambda row: row.get("overlays", "--") or "--"),
        ("By zone type", lambda row: row.get("zone_type", "--")),
        ("By zone detector", lambda row: row.get("zone_detector", "--")),
        ("By reaction state", lambda row: row.get("zone_reaction_state", "--")),
        ("By reaction V2", lambda row: row.get("reaction_v2", "--") or "--"),
        ("By confluence count", lambda row: row.get("confluence_count", "--") or "--"),
        ("By confluence types", lambda row: row.get("confluence_types", "--") or "--"),
        ("By trigger type", lambda row: row.get("trigger_types", "--") or "--"),
        ("By score bucket", lambda row: numeric_bucket(float_value(row.get("score")), [0.6, 0.7, 0.8, 0.9])),
        ("By FVG fill ratio bucket", lambda row: numeric_bucket(float_value(row.get("zone_fill_ratio")), [0.5, 0.8])),
        ("By zone width/ATR bucket", lambda row: numeric_bucket(float_value(row.get("zone_width_atr")), [0.5, 1.0, 1.5, 2.5, 4.0])),
        ("By zone weight bucket", lambda row: numeric_bucket(float_value(row.get("zone_weight")), [0.2, 0.4, 0.6, 0.8])),
        ("By signal year", lambda row: row.get("signal_year", "--")),
    ]


def potential_condition_sets(rows: list[dict[str, str]], min_samples: int) -> list[ResearchSummaryRow]:
    candidates: list[ResearchSummaryRow] = []
    dimensions = [
        lambda row: "|".join(
            [
                row.get("split", "--"),
                row.get("playbook", "--"),
                row.get("direction", "--"),
                row.get("h1_bias", "--"),
                row.get("h1_regime", "--"),
                row.get("zone_type", "--"),
                row.get("reaction_v2") or row.get("zone_reaction_state", "--"),
                row.get("trigger_types", "--") or "--",
            ]
        ),
        lambda row: "|".join(
            [
                row.get("split", "--"),
                row.get("playbook", "--"),
                row.get("zone_type", "--"),
                numeric_bucket(float_value(row.get("zone_width_atr")), [0.5, 1.0, 1.5, 2.5, 4.0]),
                row.get("trigger_types", "--") or "--",
            ]
        ),
        lambda row: "|".join(
            [
                row.get("split", "--"),
                row.get("playbook", "--"),
                row.get("h1_regime", "--"),
                row.get("overlays", "--") or "--",
                row.get("zone_type", "--"),
            ]
        ),
    ]
    seen: set[str] = set()
    for dimension in dimensions:
        for item in summarize_research(rows, dimension):
            if item.samples < min_samples or item.key in seen:
                continue
            seen.add(item.key)
            candidates.append(item)
    return sorted(candidates, key=lambda row: (row.avg_r, row.profit_factor or 0, row.samples), reverse=True)


def summarize_research(rows: list[dict[str, str]], dimension: Any) -> list[ResearchSummaryRow]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[str(dimension(row) or "--")].append(row)
    summaries: list[ResearchSummaryRow] = []
    for key, items in grouped.items():
        pnl = [float_value(item.get("pnl_r")) for item in items]
        wins = [value for value in pnl if value > 0]
        losses = [value for value in pnl if value <= 0]
        gross_loss = abs(sum(losses))
        summaries.append(
            ResearchSummaryRow(
                key=key,
                samples=len(items),
                wins=len(wins),
                losses=len(losses),
                win_rate=len(wins) / len(items) if items else 0.0,
                total_r=sum(pnl),
                avg_r=sum(pnl) / len(items) if items else 0.0,
                profit_factor=sum(wins) / gross_loss if gross_loss > 0 else None,
                avg_mfe_r=sum(float_value(item.get("mfe_r")) for item in items) / len(items) if items else 0.0,
                avg_mae_r=sum(float_value(item.get("mae_r")) for item in items) / len(items) if items else 0.0,
            )
        )
    return sorted(summaries, key=lambda row: (row.total_r, row.samples), reverse=True)


def append_research_section(lines: list[str], title: str, rows: list[ResearchSummaryRow], max_rows: int) -> None:
    lines.append(title)
    lines.append("key,samples,wins,losses,win_rate,total_r,avg_r,profit_factor,avg_mfe_r,avg_mae_r")
    for row in rows[:max_rows]:
        pf = "--" if row.profit_factor is None else f"{row.profit_factor:.2f}"
        lines.append(
            f"{csv_safe(row.key)},{row.samples},{row.wins},{row.losses},{row.win_rate:.2%},"
            f"{row.total_r:.2f},{row.avg_r:.2f},{pf},{row.avg_mfe_r:.2f},{row.avg_mae_r:.2f}"
        )
    if len(rows) > max_rows:
        lines.append(f"... {len(rows) - max_rows} more rows")
    lines.append("")


def research_table_card(title: str, rows: list[ResearchSummaryRow], max_rows: int) -> str:
    body = "".join(research_row_html(row) for row in rows[:max_rows])
    if not body:
        body = "<tr><td colspan='9'>No rows</td></tr>"
    return f"""<div class="card">
      <h2>{escape(title)}</h2>
      <table>
        <thead><tr><th>Key</th><th>Samples</th><th>Win</th><th>Total R</th><th>Avg R</th><th>PF</th><th>MFE</th><th>MAE</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
    </div>"""


def research_row_html(row: ResearchSummaryRow) -> str:
    pf = "--" if row.profit_factor is None else f"{row.profit_factor:.2f}"
    return f"""<tr>
      <td>{escape(row.key)}</td>
      <td>{row.samples}</td>
      <td>{row.win_rate:.1%}</td>
      <td class="{signed_class(row.total_r)}">{row.total_r:.2f}R</td>
      <td class="{signed_class(row.avg_r)}">{row.avg_r:.2f}R</td>
      <td>{pf}</td>
      <td>{row.avg_mfe_r:.2f}R</td>
      <td>{row.avg_mae_r:.2f}R</td>
    </tr>"""


def metric_card(label: str, value: Any, suffix: str = "", signed: bool = False) -> str:
    if isinstance(value, float):
        display = f"{value:+.2f}{suffix}" if signed else f"{value:.2f}{suffix}"
        klass = signed_class(value) if signed else ""
    elif value is None:
        display = "--"
        klass = "neutral"
    else:
        display = f"{value}{suffix}"
        klass = ""
    return f"""<div class="card"><div class="label">{escape(label)}</div><div class="value {klass}">{escape(display)}</div></div>"""


def split_for_time(value: str, train_end_year: int, validation_year: int) -> str:
    year = parse_year(value)
    if year <= train_end_year:
        return "train"
    if year == validation_year:
        return "validation"
    return "test"


def parse_year(value: str) -> int:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).year


def list_to_key(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        return "+".join(str(item) for item in value) or ""
    return str(value)


def csv_value(value: Any) -> Any:
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, sort_keys=True)
    if value is None:
        return ""
    return value


def csv_safe(value: str) -> str:
    if any(char in value for char in [",", "\n", '"']):
        return '"' + value.replace('"', '""') + '"'
    return value


def float_value(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def numeric_bucket(value: float, cuts: list[float]) -> str:
    if value == 0:
        return "--"
    previous: float | None = None
    for cut in cuts:
        if value < cut:
            return f"<{cut:g}" if previous is None else f"{previous:g}-{cut:g}"
        previous = cut
    return f">={cuts[-1]:g}" if cuts else "--"


def signed_class(value: float) -> str:
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"
