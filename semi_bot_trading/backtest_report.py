from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Any

from .backtest import BacktestResult, BacktestTrade


DimensionFunc = Callable[[BacktestTrade], str]


@dataclass(frozen=True)
class ReportRow:
    key: str
    trades: int
    wins: int
    losses: int
    win_rate: float
    total_r: float
    avg_r: float
    profit_factor: float | None


def render_backtest_report(result: BacktestResult, max_rows: int = 20) -> str:
    lines: list[str] = []
    lines.append(
        f"Backtest report {result.symbol} {result.strategy_timeframe}: "
        f"{len(result.trades)} trades, {result.evaluated_candles}/{result.timeline_count} candles evaluated"
    )
    lines.append(f"Costs: spread={result.spread:.2f}, slippage={result.slippage:.2f}, max_hold={result.max_hold_candles}")
    lines.append(f"Engine: {result.engine}")
    lines.append(f"Lookahead guard: {result.lookahead_guard}")
    lines.append("")

    if not result.trades:
        lines.append("No trades to report.")
        return "\n".join(lines)

    for title, dimension in report_sections():
        rows = summarize(result.trades, dimension)
        append_section(lines, title, rows, max_rows=max_rows)
    return "\n".join(lines)


def render_backtest_html(result: BacktestResult, max_rows: int = 20) -> str:
    sections = [(title, summarize(result.trades, dimension)) for title, dimension in report_sections()]
    wins = [trade for trade in result.trades if trade.pnl_r > 0]
    losses = [trade for trade in result.trades if trade.pnl_r <= 0]
    total_r = sum(trade.pnl_r for trade in result.trades)
    gross_win = sum(trade.pnl_r for trade in wins)
    gross_loss = abs(sum(trade.pnl_r for trade in losses))
    profit_factor = gross_win / gross_loss if gross_loss > 0 else None
    win_rate = len(wins) / len(result.trades) if result.trades else 0
    best_rows = sorted(
        [row for _, rows in sections for row in rows if row.trades >= 2],
        key=lambda row: (row.total_r, row.profit_factor or 0, row.trades),
        reverse=True,
    )[:10]
    worst_rows = sorted(
        [row for _, rows in sections for row in rows if row.trades >= 2],
        key=lambda row: (row.total_r, row.avg_r),
    )[:10]
    best_trades = sorted(result.trades, key=lambda trade: trade.pnl_r, reverse=True)[:12]
    worst_trades = sorted(result.trades, key=lambda trade: trade.pnl_r)[:12]

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(result.symbol)} Backtest Report</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #071017;
      --panel: #0c1621;
      --panel-2: #111d2a;
      --line: #213348;
      --text: #eef4fb;
      --muted: #8fa1b7;
      --cyan: #42d8ef;
      --green: #58d69b;
      --red: #ff778b;
      --yellow: #ffd35f;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 10;
      background: rgba(7, 16, 23, 0.92);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(10px);
      padding: 22px 28px;
    }}
    h1 {{ margin: 0; font-size: 28px; }}
    .subtitle {{ margin-top: 6px; color: var(--muted); }}
    main {{ padding: 24px 28px 44px; max-width: 1480px; margin: 0 auto; }}
    .grid {{ display: grid; gap: 14px; }}
    .kpis {{ grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); margin-bottom: 22px; }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
    }}
    .label {{ color: var(--muted); font-size: 13px; }}
    .value {{ margin-top: 8px; font-size: 26px; font-weight: 750; }}
    .positive {{ color: var(--green); }}
    .negative {{ color: var(--red); }}
    .neutral {{ color: var(--yellow); }}
    .section-grid {{ grid-template-columns: repeat(auto-fit, minmax(520px, 1fr)); }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ padding: 9px 10px; border-bottom: 1px solid rgba(143, 161, 183, 0.16); text-align: right; }}
    th:first-child, td:first-child {{ text-align: left; }}
    th {{ color: var(--muted); font-weight: 650; }}
    tr:hover td {{ background: rgba(66, 216, 239, 0.05); }}
    .bar-cell {{ min-width: 120px; }}
    .bar-track {{ height: 8px; border-radius: 999px; background: #182637; overflow: hidden; }}
    .bar {{ height: 100%; background: var(--cyan); }}
    .pill {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 2px 8px;
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--muted);
      font-size: 12px;
    }}
    .two-col {{ grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); margin-bottom: 18px; }}
    .note {{
      color: var(--muted);
      background: rgba(66, 216, 239, 0.06);
      border: 1px solid rgba(66, 216, 239, 0.25);
      border-radius: 8px;
      padding: 14px 16px;
      margin-bottom: 20px;
    }}
    .small {{ font-size: 12px; color: var(--muted); }}
    @media (max-width: 720px) {{
      header, main {{ padding-left: 14px; padding-right: 14px; }}
      .section-grid, .two-col {{ grid-template-columns: 1fr; }}
      table {{ font-size: 12px; }}
      th, td {{ padding: 7px 6px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{escape(result.symbol)} {escape(result.strategy_timeframe)} Backtest Report</h1>
    <div class="subtitle">{len(result.trades)} trades · {result.evaluated_candles}/{result.timeline_count} candles · engine {escape(result.engine)}</div>
  </header>
  <main>
    <section class="grid kpis">
      {metric_card("Total R", total_r, suffix="R", signed=True)}
      {metric_card("Win Rate", win_rate * 100, suffix="%")}
      {metric_card("Profit Factor", profit_factor)}
      {metric_card("Trades", len(result.trades))}
      {metric_card("Avg R", total_r / len(result.trades) if result.trades else 0, suffix="R", signed=True)}
      {metric_card("Costs", result.spread + result.slippage, suffix=" pts")}
    </section>
    <div class="note">
      {escape(result.lookahead_guard)}
      <div class="small">Spread={result.spread:.2f}, slippage={result.slippage:.2f}, max_hold={result.max_hold_candles}, warmup={result.warmup_candles}</div>
    </div>
    <section class="grid two-col">
      {rows_card("Potential Edges", best_rows, max_rows=10)}
      {rows_card("Drag Sources", worst_rows, max_rows=10)}
    </section>
    <section class="grid two-col">
      {trades_card("Best Trades", best_trades)}
      {trades_card("Worst Trades", worst_trades)}
    </section>
    <section class="grid section-grid">
      {"".join(rows_card(title, rows, max_rows=max_rows) for title, rows in sections)}
    </section>
  </main>
</body>
</html>
"""


def summarize(trades: list[BacktestTrade], dimension: DimensionFunc) -> list[ReportRow]:
    grouped: dict[str, list[BacktestTrade]] = {}
    for trade in trades:
        grouped.setdefault(dimension(trade), []).append(trade)

    rows: list[ReportRow] = []
    for key, items in grouped.items():
        wins = [trade.pnl_r for trade in items if trade.pnl_r > 0]
        losses = [trade.pnl_r for trade in items if trade.pnl_r <= 0]
        total_r = sum(wins) + sum(losses)
        gross_loss = abs(sum(losses))
        profit_factor = (sum(wins) / gross_loss) if gross_loss > 0 else None
        rows.append(
            ReportRow(
                key=key or "--",
                trades=len(items),
                wins=len(wins),
                losses=len(losses),
                win_rate=len(wins) / len(items) if items else 0.0,
                total_r=total_r,
                avg_r=total_r / len(items) if items else 0.0,
                profit_factor=profit_factor,
            )
        )
    return sorted(rows, key=lambda row: (row.total_r, row.trades), reverse=True)


def report_sections() -> list[tuple[str, DimensionFunc]]:
    return [
        ("By playbook", lambda trade: trade.playbook),
        ("By direction", lambda trade: trade.direction),
        ("By exit status", lambda trade: trade.status),
        ("By session", signal_session),
        ("By hour (UTC)", signal_hour),
        ("By H1 bias", lambda trade: metadata_value(trade, "h1_bias")),
        ("By H1 regime", lambda trade: metadata_value(trade, "h1_regime")),
        ("By regime overlays", lambda trade: list_value(trade, "overlays")),
        ("By zone type", lambda trade: metadata_value(trade, "zone_type")),
        ("By zone detector", lambda trade: metadata_value(trade, "zone_detector")),
        ("By zone source", lambda trade: metadata_value(trade, "zone_source")),
        ("By reaction state", lambda trade: metadata_value(trade, "zone_reaction_state", fallback=trade.metadata.get("zone_reaction_state"))),
        ("By trigger type", lambda trade: list_value(trade, "trigger_types")),
        ("By score bucket", score_bucket),
        ("By FVG fill ratio bucket", fill_ratio_bucket),
        ("By zone weight bucket", numeric_bucket("zone_weight", [0.2, 0.4, 0.6, 0.8])),
        ("By zone confidence bucket", numeric_bucket("zone_confidence", [0.2, 0.4, 0.6, 0.8])),
        ("By zone width/ATR bucket", numeric_bucket("zone_width_atr", [0.5, 1.0, 1.5, 2.5, 4.0])),
        ("By zone touch count", touch_bucket),
        ("By signal year", signal_year),
    ]


def append_section(lines: list[str], title: str, rows: list[ReportRow], max_rows: int) -> None:
    lines.append(title)
    lines.append("key,trades,wins,losses,win_rate,total_r,avg_r,profit_factor")
    for row in rows[:max_rows]:
        profit_factor = "--" if row.profit_factor is None else f"{row.profit_factor:.2f}"
        lines.append(
            f"{csv_cell(row.key)},{row.trades},{row.wins},{row.losses},"
            f"{row.win_rate:.2%},{row.total_r:.2f},{row.avg_r:.2f},{profit_factor}"
        )
    if len(rows) > max_rows:
        lines.append(f"... {len(rows) - max_rows} more rows")
    lines.append("")


def candidate_metadata(trade: BacktestTrade) -> dict[str, Any]:
    metadata = trade.metadata.get("candidate_metadata")
    return metadata if isinstance(metadata, dict) else {}


def metadata_value(trade: BacktestTrade, key: str, fallback: Any = None) -> str:
    value = candidate_metadata(trade).get(key, fallback)
    if value is None or value == "":
        return "--"
    return str(value)


def list_value(trade: BacktestTrade, key: str) -> str:
    value = candidate_metadata(trade).get(key)
    if isinstance(value, list):
        if not value:
            return "--"
        return "+".join(str(item) for item in value)
    if value is None or value == "":
        return "--"
    return str(value)


def numeric_bucket(key: str, thresholds: list[float]) -> DimensionFunc:
    def bucket(trade: BacktestTrade) -> str:
        value = candidate_metadata(trade).get(key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "--"
        previous = None
        for threshold in thresholds:
            if number < threshold:
                return f"<{threshold:g}" if previous is None else f"{previous:g}-{threshold:g}"
            previous = threshold
        return f">={thresholds[-1]:g}"

    return bucket


def fill_ratio_bucket(trade: BacktestTrade) -> str:
    metadata = candidate_metadata(trade)
    value = metadata.get("fill_ratio", metadata.get("zone_fill_ratio"))
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    return numeric_bucket_value(number, [0.5, 0.8])


def numeric_bucket_value(number: float, thresholds: list[float]) -> str:
    previous = None
    for threshold in thresholds:
        if number < threshold:
            return f"<{threshold:g}" if previous is None else f"{previous:g}-{threshold:g}"
        previous = threshold
    return f">={thresholds[-1]:g}"


def score_bucket(trade: BacktestTrade) -> str:
    score = trade.score
    if score < 0.4:
        return "<0.4"
    if score < 0.5:
        return "0.4-0.5"
    if score < 0.6:
        return "0.5-0.6"
    if score < 0.7:
        return "0.6-0.7"
    if score < 0.8:
        return "0.7-0.8"
    return ">=0.8"


def touch_bucket(trade: BacktestTrade) -> str:
    value = candidate_metadata(trade).get("zone_touch_count")
    try:
        count = int(value)
    except (TypeError, ValueError):
        return "--"
    if count <= 1:
        return "0-1"
    if count <= 3:
        return "2-3"
    if count <= 5:
        return "4-5"
    return ">=6"


def signal_year(trade: BacktestTrade) -> str:
    try:
        return str(datetime.fromisoformat(trade.signal_time).year)
    except ValueError:
        return trade.signal_time[:4] if len(trade.signal_time) >= 4 else "--"


def signal_session(trade: BacktestTrade) -> str:
    """Classify trade signal into XAUUSD trading sessions (UTC)."""
    try:
        dt = datetime.fromisoformat(trade.signal_time)
    except ValueError:
        return "--"
    hour = dt.hour
    if 0 <= hour < 7:
        return "Asian (00-07)"
    if 7 <= hour < 12:
        return "London (07-12)"
    if 12 <= hour < 17:
        return "London-NY (12-17)"
    if 17 <= hour < 21:
        return "New York (17-21)"
    return "Off-hours (21-00)"


def signal_hour(trade: BacktestTrade) -> str:
    try:
        dt = datetime.fromisoformat(trade.signal_time)
    except ValueError:
        return "--"
    return f"{dt.hour:02d}:00"


def csv_cell(value: str) -> str:
    if any(char in value for char in [",", "\n", '"']):
        return '"' + value.replace('"', '""') + '"'
    return value


def metric_card(label: str, value: float | int | None, suffix: str = "", signed: bool = False) -> str:
    if value is None:
        rendered = "--"
        css_class = ""
    elif isinstance(value, int):
        rendered = f"{value:,}"
        css_class = ""
    else:
        rendered = f"{value:+.2f}{suffix}" if signed else f"{value:.2f}{suffix}"
        css_class = " positive" if value > 0 else " negative" if value < 0 else ""
    return f"""
      <article class="card">
        <div class="label">{escape(label)}</div>
        <div class="value{css_class}">{escape(rendered)}</div>
      </article>
    """


def rows_card(title: str, rows: list[ReportRow], max_rows: int) -> str:
    if not rows:
        body = '<tr><td colspan="8" class="small">No rows</td></tr>'
    else:
        max_trade_count = max(row.trades for row in rows[:max_rows]) or 1
        body = "".join(report_row_html(row, max_trade_count) for row in rows[:max_rows])
    return f"""
      <article class="card">
        <h2>{escape(title)}</h2>
        <table>
          <thead>
            <tr>
              <th>Key</th>
              <th>Trades</th>
              <th>Win</th>
              <th>Total R</th>
              <th>Avg R</th>
              <th>PF</th>
              <th class="bar-cell">Size</th>
            </tr>
          </thead>
          <tbody>{body}</tbody>
        </table>
      </article>
    """


def report_row_html(row: ReportRow, max_trade_count: int) -> str:
    total_class = "positive" if row.total_r > 0 else "negative" if row.total_r < 0 else ""
    avg_class = "positive" if row.avg_r > 0 else "negative" if row.avg_r < 0 else ""
    width = max(4, min(100, int(row.trades / max_trade_count * 100)))
    profit_factor = "--" if row.profit_factor is None else f"{row.profit_factor:.2f}"
    return f"""
      <tr>
        <td>{escape(row.key)}</td>
        <td>{row.trades}</td>
        <td>{row.win_rate:.2%}</td>
        <td class="{total_class}">{row.total_r:+.2f}</td>
        <td class="{avg_class}">{row.avg_r:+.2f}</td>
        <td>{profit_factor}</td>
        <td class="bar-cell"><div class="bar-track"><div class="bar" style="width:{width}%"></div></div></td>
      </tr>
    """


def trades_card(title: str, trades: list[BacktestTrade]) -> str:
    if not trades:
        body = '<tr><td colspan="7" class="small">No trades</td></tr>'
    else:
        body = "".join(trade_row_html(trade) for trade in trades)
    return f"""
      <article class="card">
        <h2>{escape(title)}</h2>
        <table>
          <thead>
            <tr>
              <th>Signal</th>
              <th>Dir</th>
              <th>Status</th>
              <th>Zone</th>
              <th>Trigger</th>
              <th>Score</th>
              <th>R</th>
            </tr>
          </thead>
          <tbody>{body}</tbody>
        </table>
      </article>
    """


def trade_row_html(trade: BacktestTrade) -> str:
    metadata = candidate_metadata(trade)
    pnl_class = "positive" if trade.pnl_r > 0 else "negative" if trade.pnl_r < 0 else ""
    zone = f"{metadata.get('zone_type', '--')} · {metadata.get('zone_width_atr', '--')} ATR"
    trigger = list_value(trade, "trigger_types")
    return f"""
      <tr>
        <td>{escape(trade.signal_time)}</td>
        <td><span class="pill">{escape(trade.direction)}</span></td>
        <td>{escape(trade.status)}</td>
        <td>{escape(zone)}</td>
        <td>{escape(trigger)}</td>
        <td>{trade.score:.2f}</td>
        <td class="{pnl_class}">{trade.pnl_r:+.2f}</td>
      </tr>
    """
