from __future__ import annotations

import argparse
import csv
import html
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable


HORIZONS = (1, 3, 6, 12, 24)
SIDEWAY_ATR = 0.25


@dataclass(frozen=True)
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research XAUUSD daily/weekend gap behavior from H1 candles.")
    parser.add_argument("--db", default="var/trading.sqlite3")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--output", default="var/reports/gap-behavior-research.html")
    parser.add_argument("--csv-output", default="var/reports/gap-behavior-events.csv")
    return parser.parse_args()


def percentile(values: Iterable[float], q: float) -> float | None:
    ordered = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def pct(part: float, total: float) -> float | None:
    return part / total if total else None


def fmt_number(value: Any, digits: int = 2) -> str:
    if value is None:
        return "--"
    return f"{float(value):,.{digits}f}"


def fmt_pct(value: Any, digits: int = 1) -> str:
    if value is None:
        return "--"
    return f"{float(value) * 100:.{digits}f}%"


def html_table(headers: list[str], rows: list[list[Any]], numeric_columns: set[int] | None = None) -> str:
    numeric_columns = numeric_columns or set()
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body_rows = []
    for row in rows:
        cells = []
        for index, value in enumerate(row):
            css = ' class="num"' if index in numeric_columns else ""
            cells.append(f"<td{css}>{html.escape(str(value))}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<div class=\"table-wrap\"><table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>"


def load_candles(database: str, symbol: str) -> list[Candle]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT open_time, open, high, low, close
            FROM candles
            WHERE symbol = ? AND timeframe = 'H1'
            ORDER BY open_time
            """,
            (symbol,),
        ).fetchall()
    finally:
        connection.close()
    return [
        Candle(
            time=datetime.fromisoformat(str(row["open_time"]).replace("Z", "+00:00")),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for row in rows
    ]


def true_ranges(candles: list[Candle]) -> list[float]:
    values: list[float] = []
    for index, candle in enumerate(candles):
        if index == 0:
            values.append(candle.high - candle.low)
            continue
        previous_close = candles[index - 1].close
        values.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        )
    return values


def closure_type(hours: float) -> str | None:
    if 1.5 <= hours <= 6.0:
        return "daily"
    if 6.0 < hours < 36.0:
        return "holiday"
    if 36.0 <= hours <= 96.0:
        return "weekly"
    return None


def direction_label(value: float) -> str:
    return "up" if value > 0 else "down" if value < 0 else "flat"


def aligned_label(move: float, direction: int, atr: float, neutral_atr: float = 0.05) -> str:
    if abs(move) < atr * neutral_atr:
        return "neutral"
    return "same" if move * direction > 0 else "opposite"


def path_class(directional_move_atr: float) -> str:
    if directional_move_atr >= SIDEWAY_ATR:
        return "follow"
    if directional_move_atr <= -SIDEWAY_ATR:
        return "reverse"
    return "sideway"


def gap_filled(candle: Candle, previous_close: float, direction: int) -> bool:
    return candle.low <= previous_close if direction > 0 else candle.high >= previous_close


def build_events(candles: list[Candle]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranges = true_ranges(candles)
    events: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for index in range(1, len(candles)):
        current = candles[index]
        previous = candles[index - 1]
        closure_hours = (current.time - previous.time).total_seconds() / 3600.0
        if closure_hours < 1.5:
            continue
        event_type = closure_type(closure_hours)
        gap = current.open - previous.close
        if event_type is None:
            excluded.append(
                {
                    "open_time": current.time.isoformat(),
                    "previous_time": previous.time.isoformat(),
                    "closure_hours": closure_hours,
                    "gap": gap,
                    "reason": "data outage / unsupported closure length",
                }
            )
            continue
        if abs(gap) < 1e-9:
            continue

        atr_window = ranges[max(0, index - 14):index]
        atr = mean(atr_window) if atr_window else ranges[index]
        if atr <= 0:
            continue
        direction = 1 if gap > 0 else -1
        opening_body = current.close - current.open
        prior_start = max(0, index - 7)
        prior_move = previous.close - candles[prior_start].close
        event: dict[str, Any] = {
            "type": event_type,
            "open_time": current.time.isoformat(),
            "previous_time": previous.time.isoformat(),
            "weekday": current.time.strftime("%A"),
            "closure_hours": closure_hours,
            "previous_close": previous.close,
            "gap_open": current.open,
            "gap": gap,
            "direction": direction_label(gap),
            "gap_size": abs(gap),
            "gap_pct": abs(gap) / previous.close,
            "atr14_pre": atr,
            "gap_atr": abs(gap) / atr,
            "opening_body": abs(opening_body),
            "opening_alignment": aligned_label(opening_body, direction, atr),
            "prior_6h_move_atr": prior_move / atr,
            "prior_alignment": aligned_label(prior_move, direction, atr, neutral_atr=0.25),
        }

        first_fill_bar: int | None = None
        for offset in range(0, min(48, len(candles) - index)):
            if gap_filled(candles[index + offset], previous.close, direction):
                first_fill_bar = offset + 1
                break
        event["fill_bar"] = first_fill_bar

        for horizon in HORIZONS:
            end_index = index + horizon - 1
            if end_index >= len(candles):
                event[f"close_{horizon}h"] = None
                event[f"dir_move_{horizon}h"] = None
                event[f"dir_move_atr_{horizon}h"] = None
                event[f"path_{horizon}h"] = None
                event[f"fill_{horizon}h"] = None
                event[f"mfe_atr_{horizon}h"] = None
                event[f"mae_atr_{horizon}h"] = None
                continue
            window = candles[index:end_index + 1]
            close_value = candles[end_index].close
            directional_move = direction * (close_value - current.open)
            directional_move_atr = directional_move / atr
            if direction > 0:
                mfe = max(candle.high for candle in window) - current.open
                mae = current.open - min(candle.low for candle in window)
            else:
                mfe = current.open - min(candle.low for candle in window)
                mae = max(candle.high for candle in window) - current.open
            event[f"close_{horizon}h"] = close_value
            event[f"dir_move_{horizon}h"] = directional_move
            event[f"dir_move_atr_{horizon}h"] = directional_move_atr
            event[f"path_{horizon}h"] = path_class(directional_move_atr)
            event[f"fill_{horizon}h"] = first_fill_bar is not None and first_fill_bar <= horizon
            event[f"mfe_atr_{horizon}h"] = mfe / atr
            event[f"mae_atr_{horizon}h"] = mae / atr
        events.append(event)
    return events, excluded


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(events)
    result: dict[str, Any] = {
        "n": count,
        "up_rate": pct(sum(event["direction"] == "up" for event in events), count),
        "median_gap": median(event["gap_size"] for event in events) if events else None,
        "p75_gap": percentile((event["gap_size"] for event in events), 0.75),
        "p90_gap": percentile((event["gap_size"] for event in events), 0.90),
        "p95_gap": percentile((event["gap_size"] for event in events), 0.95),
        "p99_gap": percentile((event["gap_size"] for event in events), 0.99),
        "median_gap_atr": median(event["gap_atr"] for event in events) if events else None,
        "p90_gap_atr": percentile((event["gap_atr"] for event in events), 0.90),
        "opening_same": pct(sum(event["opening_alignment"] == "same" for event in events), count),
        "opening_opposite": pct(sum(event["opening_alignment"] == "opposite" for event in events), count),
        "opening_neutral": pct(sum(event["opening_alignment"] == "neutral" for event in events), count),
        "median_fill_bar": median(
            event["fill_bar"] for event in events if event["fill_bar"] is not None
        ) if any(event["fill_bar"] is not None for event in events) else None,
    }
    for horizon in HORIZONS:
        available = [event for event in events if event[f"path_{horizon}h"] is not None]
        n_available = len(available)
        result[f"fill_{horizon}h"] = pct(
            sum(event[f"fill_{horizon}h"] is True for event in available),
            n_available,
        )
        for path in ("follow", "reverse", "sideway"):
            result[f"{path}_{horizon}h"] = pct(
                sum(event[f"path_{horizon}h"] == path for event in available),
                n_available,
            )
        moves = [event[f"dir_move_atr_{horizon}h"] for event in available]
        result[f"median_move_atr_{horizon}h"] = median(moves) if moves else None
        result[f"median_mfe_atr_{horizon}h"] = (
            median(event[f"mfe_atr_{horizon}h"] for event in available) if available else None
        )
        result[f"median_mae_atr_{horizon}h"] = (
            median(event[f"mae_atr_{horizon}h"] for event in available) if available else None
        )
    return result


def group_by(events: list[dict[str, Any]], key: str) -> list[tuple[str, list[dict[str, Any]]]]:
    values: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        values.setdefault(str(event[key]), []).append(event)
    return sorted(values.items(), key=lambda item: item[0])


def assign_size_bands(events: list[dict[str, Any]]) -> None:
    for event_type, typed_events in group_by(events, "type"):
        del event_type
        p50 = percentile((event["gap_size"] for event in typed_events), 0.50) or 0.0
        p75 = percentile((event["gap_size"] for event in typed_events), 0.75) or 0.0
        p90 = percentile((event["gap_size"] for event in typed_events), 0.90) or 0.0
        for event in typed_events:
            size = event["gap_size"]
            if size >= p90:
                event["size_band"] = "P90+ (large)"
            elif size >= p75:
                event["size_band"] = "P75–P90"
            elif size >= p50:
                event["size_band"] = "P50–P75"
            else:
                event["size_band"] = "<P50"


def summary_row(label: str, stats: dict[str, Any]) -> list[Any]:
    return [
        label,
        stats["n"],
        fmt_number(stats["median_gap"]),
        fmt_number(stats["p90_gap"]),
        fmt_number(stats["p95_gap"]),
        fmt_number(stats["median_gap_atr"], 2),
        fmt_number(stats["p90_gap_atr"], 2),
        fmt_pct(stats["opening_same"]),
        fmt_pct(stats["fill_3h"]),
        fmt_pct(stats["fill_6h"]),
        fmt_pct(stats["fill_24h"]),
        fmt_pct(stats["follow_6h"]),
        fmt_pct(stats["reverse_6h"]),
        fmt_pct(stats["follow_24h"]),
        fmt_pct(stats["reverse_24h"]),
    ]


def path_rows(groups: list[tuple[str, list[dict[str, Any]]]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for label, events in groups:
        stats = summarize(events)
        rows.append(
            [
                label,
                stats["n"],
                fmt_number(stats["median_gap"]),
                fmt_number(stats["median_gap_atr"]),
                fmt_pct(stats["opening_same"]),
                fmt_pct(stats["fill_6h"]),
                fmt_pct(stats["fill_24h"]),
                fmt_pct(stats["follow_6h"]),
                fmt_pct(stats["reverse_6h"]),
                fmt_pct(stats["sideway_6h"]),
                fmt_pct(stats["follow_24h"]),
                fmt_pct(stats["reverse_24h"]),
                fmt_pct(stats["sideway_24h"]),
                fmt_number(stats["median_move_atr_24h"]),
            ]
        )
    return rows


def insight_list(events: list[dict[str, Any]]) -> list[str]:
    insights: list[str] = []
    for event_type in ("daily", "weekly"):
        typed = [event for event in events if event["type"] == event_type]
        if not typed:
            continue
        all_stats = summarize(typed)
        threshold = all_stats["p90_gap"] or 0.0
        large = [event for event in typed if event["gap_size"] >= threshold]
        large_stats = summarize(large)
        same = [event for event in large if event["opening_alignment"] == "same"]
        opposite = [event for event in large if event["opening_alignment"] == "opposite"]
        same_stats = summarize(same)
        opposite_stats = summarize(opposite)
        insights.append(
            f"<strong>{event_type.title()} gap lớn</strong> được định nghĩa theo top 10% mẫu: "
            f"từ <strong>${threshold:.2f}</strong> trở lên. Nhóm này fill trong 6H "
            f"<strong>{fmt_pct(large_stats['fill_6h'])}</strong> và trong 24H "
            f"<strong>{fmt_pct(large_stats['fill_24h'])}</strong>."
        )
        insights.append(
            f"Với {event_type} P90+, nếu opening candle cùng hướng gap thì follow-through 6H là "
            f"<strong>{fmt_pct(same_stats['follow_6h'])}</strong> (n={same_stats['n']}); "
            f"nếu opening candle ngược hướng là <strong>{fmt_pct(opposite_stats['follow_6h'])}</strong> "
            f"(n={opposite_stats['n']})."
        )
        insights.append(
            f"{event_type.title()} P90+ sau 24H: follow "
            f"<strong>{fmt_pct(large_stats['follow_24h'])}</strong>, reverse "
            f"<strong>{fmt_pct(large_stats['reverse_24h'])}</strong>, sideway "
            f"<strong>{fmt_pct(large_stats['sideway_24h'])}</strong>; median directional return "
            f"<strong>{fmt_number(large_stats['median_move_atr_24h'])} ATR</strong>."
        )
        years = sorted({event["open_time"][:4] for event in typed})
        latest_year_events = [event for event in typed if event["open_time"].startswith(years[-1])]
        latest_year_p90 = percentile((event["gap_size"] for event in latest_year_events), 0.90)
        latest_year_atr_p90 = percentile((event["gap_atr"] for event in latest_year_events), 0.90)
        insights.append(
            f"Ngưỡng USD drift theo regime: riêng <strong>{years[-1]}</strong>, P90 {event_type} là "
            f"<strong>${fmt_number(latest_year_p90)}</strong> / <strong>{fmt_number(latest_year_atr_p90)} ATR</strong>. "
            f"Ưu tiên ATR percentile khi biến insight thành rule."
        )
    return insights


def render_report(
    candles: list[Candle],
    events: list[dict[str, Any]],
    excluded: list[dict[str, Any]],
    symbol: str,
    database: str,
) -> str:
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    type_groups = [(name, [event for event in events if event["type"] == name]) for name in ("daily", "weekly", "holiday")]
    overview_rows = [summary_row(label.title(), summarize(group)) for label, group in type_groups if group]
    overview = html_table(
        [
            "Type", "N", "Median $", "P90 $", "P95 $", "Median ATR", "P90 ATR", "Open same",
            "Fill 3H", "Fill 6H", "Fill 24H", "Follow 6H", "Reverse 6H",
            "Follow 24H", "Reverse 24H",
        ],
        overview_rows,
        set(range(1, 15)),
    )

    horizon_rows: list[list[Any]] = []
    for label, group in type_groups[:2]:
        stats = summarize(group)
        for horizon in HORIZONS:
            horizon_rows.append(
                [
                    label.title(),
                    f"{horizon}H",
                    fmt_pct(stats[f"fill_{horizon}h"]),
                    fmt_pct(stats[f"follow_{horizon}h"]),
                    fmt_pct(stats[f"reverse_{horizon}h"]),
                    fmt_pct(stats[f"sideway_{horizon}h"]),
                    fmt_number(stats[f"median_move_atr_{horizon}h"]),
                    fmt_number(stats[f"median_mfe_atr_{horizon}h"]),
                    fmt_number(stats[f"median_mae_atr_{horizon}h"]),
                ]
            )
    horizon_table = html_table(
        ["Type", "Horizon", "Gap fill", "Follow", "Reverse", "Sideway", "Median move ATR", "Median MFE ATR", "Median MAE ATR"],
        horizon_rows,
        set(range(2, 9)),
    )

    band_sections: list[str] = []
    for event_type in ("daily", "weekly"):
        typed = [event for event in events if event["type"] == event_type]
        ordering = {"<P50": 0, "P50–P75": 1, "P75–P90": 2, "P90+ (large)": 3}
        groups = sorted(group_by(typed, "size_band"), key=lambda item: ordering[item[0]])
        band_sections.append(
            f"<h3>{event_type.title()} gap theo size percentile</h3>"
            + html_table(
                [
                    "Band", "N", "Median $", "Median ATR", "Open same", "Fill 6H", "Fill 24H",
                    "Follow 6H", "Reverse 6H", "Sideway 6H", "Follow 24H",
                    "Reverse 24H", "Sideway 24H", "Median move 24H ATR",
                ],
                path_rows(groups),
                set(range(1, 14)),
            )
        )

    yearly_rows: list[list[Any]] = []
    normalized_large_rows: list[list[Any]] = []
    for event_type in ("daily", "weekly"):
        typed = [event for event in events if event["type"] == event_type]
        years = sorted({event["open_time"][:4] for event in typed})
        for year in years:
            yearly = [event for event in typed if event["open_time"].startswith(year)]
            yearly_stats = summarize(yearly)
            yearly_rows.append(
                [
                    event_type.title(),
                    year,
                    yearly_stats["n"],
                    fmt_number(yearly_stats["median_gap"]),
                    fmt_number(yearly_stats["p90_gap"]),
                    fmt_number(yearly_stats["p95_gap"]),
                    fmt_number(yearly_stats["median_gap_atr"]),
                    fmt_number(yearly_stats["p90_gap_atr"]),
                ]
            )
        dollar_threshold = percentile((event["gap_size"] for event in typed), 0.90) or 0.0
        atr_threshold = percentile((event["gap_atr"] for event in typed), 0.90) or 0.0
        normalized_groups = [
            ("All", typed),
            (f"Dollar P90+ (≥${dollar_threshold:.2f})", [event for event in typed if event["gap_size"] >= dollar_threshold]),
            (f"ATR P90+ (≥{atr_threshold:.2f} ATR)", [event for event in typed if event["gap_atr"] >= atr_threshold]),
        ]
        normalized_large_rows.extend(
            [[event_type.title(), *row] for row in path_rows(normalized_groups)]
        )
    yearly_table = html_table(
        ["Type", "Year", "N", "Median $", "P90 $", "P95 $", "Median ATR", "P90 ATR"],
        yearly_rows,
        set(range(2, 8)),
    )
    normalized_large_table = html_table(
        [
            "Type", "Large definition", "N", "Median $", "Median ATR", "Open same",
            "Fill 6H", "Fill 24H", "Follow 6H", "Reverse 6H", "Sideway 6H",
            "Follow 24H", "Reverse 24H", "Sideway 24H", "Median move 24H ATR",
        ],
        normalized_large_rows,
        set(range(2, 15)),
    )

    large_condition_sections: list[str] = []
    for event_type in ("daily", "weekly"):
        typed = [event for event in events if event["type"] == event_type]
        threshold = percentile((event["gap_size"] for event in typed), 0.90) or 0.0
        large = [event for event in typed if event["gap_size"] >= threshold]
        alignment_groups = group_by(large, "opening_alignment")
        prior_groups = group_by(large, "prior_alignment")
        direction_groups = group_by(large, "direction")
        large_condition_sections.append(
            f"<h3>{event_type.title()} P90+ — opening candle</h3>"
            + html_table(
                [
                    "Opening alignment", "N", "Median $", "Median ATR", "Open same", "Fill 6H", "Fill 24H",
                    "Follow 6H", "Reverse 6H", "Sideway 6H", "Follow 24H",
                    "Reverse 24H", "Sideway 24H", "Median move 24H ATR",
                ],
                path_rows(alignment_groups),
                set(range(1, 14)),
            )
            + f"<h3>{event_type.title()} P90+ — prior 6H momentum</h3>"
            + html_table(
                [
                    "Prior alignment", "N", "Median $", "Median ATR", "Open same", "Fill 6H", "Fill 24H",
                    "Follow 6H", "Reverse 6H", "Sideway 6H", "Follow 24H",
                    "Reverse 24H", "Sideway 24H", "Median move 24H ATR",
                ],
                path_rows(prior_groups),
                set(range(1, 14)),
            )
            + f"<h3>{event_type.title()} P90+ — gap direction</h3>"
            + html_table(
                [
                    "Direction", "N", "Median $", "Median ATR", "Open same", "Fill 6H", "Fill 24H",
                    "Follow 6H", "Reverse 6H", "Sideway 6H", "Follow 24H",
                    "Reverse 24H", "Sideway 24H", "Median move 24H ATR",
                ],
                path_rows(direction_groups),
                set(range(1, 14)),
            )
        )

    top_events = sorted(events, key=lambda event: event["gap_size"], reverse=True)[:40]
    top_rows = [
        [
            event["open_time"].replace("+00:00", "Z"),
            event["type"],
            event["direction"],
            fmt_number(event["gap_size"]),
            fmt_number(event["gap_atr"]),
            event["opening_alignment"],
            event["fill_bar"] or "--",
            event["path_3h"] or "--",
            event["path_6h"] or "--",
            event["path_24h"] or "--",
            fmt_number(event["dir_move_atr_24h"]),
            fmt_number(event["mfe_atr_24h"]),
            fmt_number(event["mae_atr_24h"]),
        ]
        for event in top_events
    ]
    top_table = html_table(
        ["Open UTC", "Type", "Dir", "Gap $", "Gap ATR", "Open candle", "Fill bar", "3H", "6H", "24H", "Move 24H ATR", "MFE 24H", "MAE 24H"],
        top_rows,
        {3, 4, 6, 10, 11, 12},
    )

    exclusion_rows = [
        [
            item["open_time"],
            item["previous_time"],
            fmt_number(item["closure_hours"], 1),
            fmt_number(item["gap"]),
            item["reason"],
        ]
        for item in excluded
    ]
    exclusions = html_table(
        ["Open", "Previous", "Hours", "Gap $", "Reason"],
        exclusion_rows,
        {2, 3},
    ) if exclusion_rows else "<p>None.</p>"

    insights = "".join(f"<li>{item}</li>" for item in insight_list(events))
    data_start = candles[0].time.isoformat() if candles else "--"
    data_end = candles[-1].time.isoformat() if candles else "--"
    daily_count = sum(event["type"] == "daily" for event in events)
    weekly_count = sum(event["type"] == "weekly" for event in events)
    holiday_count = sum(event["type"] == "holiday" for event in events)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(symbol)} H1 Gap Behavior Research</title>
<style>
:root {{ color-scheme: dark; --bg:#071018; --panel:#0d1822; --line:#223446; --text:#e7eef7; --muted:#91a3b7; --cyan:#58d6e8; --green:#5ee0a0; --red:#ff879b; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.55 Inter,ui-sans-serif,system-ui,sans-serif; }}
main {{ max-width:1500px; margin:auto; padding:28px; }} h1 {{ margin:0 0 6px; font-size:30px; }} h2 {{ margin:32px 0 12px; font-size:21px; }} h3 {{ margin:22px 0 10px; color:#cfeaf0; }}
.muted {{ color:var(--muted); }} .cards {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:22px 0; }}
.card,.note {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px; }} .card b {{ display:block; font-size:24px; color:var(--cyan); }}
.note {{ margin:14px 0; }} ul {{ padding-left:21px; }} li {{ margin:8px 0; }} code {{ color:#b9f4fb; }}
.table-wrap {{ overflow:auto; border:1px solid var(--line); border-radius:10px; margin:10px 0 18px; }}
table {{ width:100%; border-collapse:collapse; white-space:nowrap; }} th,td {{ padding:9px 10px; border-bottom:1px solid #192a38; text-align:left; }}
th {{ position:sticky; top:0; background:#12212d; color:#a9c1d2; font-size:12px; }} td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
tr:hover td {{ background:#0e1d28; }} .good {{ color:var(--green); }} .bad {{ color:var(--red); }}
@media(max-width:850px) {{ main {{ padding:16px; }} .cards {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
</style>
</head>
<body><main>
<h1>{html.escape(symbol)} H1 Gap Behavior Research</h1>
<div class="muted">Generated {html.escape(generated_at)} · DB {html.escape(database)} · {html.escape(data_start)} → {html.escape(data_end)}</div>
<div class="cards">
  <div class="card"><span>Daily reopen gaps</span><b>{daily_count}</b></div>
  <div class="card"><span>Weekly/weekend gaps</span><b>{weekly_count}</b></div>
  <div class="card"><span>Holiday gaps</span><b>{holiday_count}</b></div>
  <div class="card"><span>Sideway threshold</span><b>{SIDEWAY_ATR:.2f} ATR</b></div>
</div>

<h2>Executive findings</h2><div class="note"><ul>{insights}</ul></div>

<h2>Definitions</h2>
<div class="note">
<ul>
<li><strong>Gap</strong> = current reopen H1 open − previous available H1 close. Positive is gap-up, negative is gap-down.</li>
<li><strong>Daily</strong> = 1.5–6 hour closure; <strong>Weekly</strong> = 36–96 hour closure; 6–36 hour holiday closures are separate. A 656-hour data outage is excluded.</li>
<li><strong>ATR14 pre-gap</strong> uses the 14 completed H1 true ranges before the reopen candle, avoiding look-ahead.</li>
<li><strong>Follow/reverse</strong> measures close relative to gap open in gap direction. At least +{SIDEWAY_ATR:.2f} ATR = follow, at most −{SIDEWAY_ATR:.2f} ATR = reverse, otherwise sideway.</li>
<li><strong>Gap fill</strong> uses wick touch of the previous close. Horizon 1H includes the opening candle; 24H means 24 subsequent trading candles.</li>
<li><strong>MFE/MAE</strong> are maximum favorable/adverse excursions from gap open, normalized by pre-gap ATR.</li>
</ul></div>

<h2>Overall comparison</h2>{overview}
<h2>Behavior by horizon</h2>{horizon_table}
<h2>Threshold drift by year</h2>
<div class="note">USD gap size is non-stationary as gold price and volatility change. ATR-normalized thresholds are more portable across years.</div>
{yearly_table}
<h2>Large gap: dollar vs ATR definition</h2>{normalized_large_table}
<h2>Does gap size matter?</h2>{''.join(band_sections)}
<h2>Deep dive: largest 10%</h2>{''.join(large_condition_sections)}
<h2>Top 40 largest gaps</h2>{top_table}
<h2>Excluded data gaps</h2>{exclusions}
<div class="note muted">Statistical research only. Small conditional samples—especially weekly P90+—should be treated as hypotheses for backtesting, not standalone entry rules.</div>
</main></body></html>"""


def write_csv(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(events[0].keys()) if events else []
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(events)


def main() -> None:
    args = parse_args()
    candles = load_candles(args.db, args.symbol)
    if not candles:
        raise SystemExit(f"No H1 candles found for {args.symbol} in {args.db}")
    events, excluded = build_events(candles)
    assign_size_bands(events)
    output = Path(args.output)
    csv_output = Path(args.csv_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(candles, events, excluded, args.symbol, args.db), encoding="utf-8")
    write_csv(csv_output, events)
    print(f"HTML: {output.resolve()}")
    print(f"CSV:  {csv_output.resolve()}")
    print(f"Events: {len(events)}; excluded closures: {len(excluded)}")


if __name__ == "__main__":
    main()
