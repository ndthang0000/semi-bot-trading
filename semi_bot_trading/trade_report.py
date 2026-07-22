from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection, Row
from typing import Any
from zoneinfo import ZoneInfo

from .config import AppConfig


REPORT_SCHEMA_VERSION = "zone-trade-report-v1"


@dataclass(frozen=True)
class ZoneTradeReport:
    zone_id: str
    generated_at: str
    database: str
    code_commit: str
    timezone: str
    zone: dict[str, Any] | None
    historical_zone: dict[str, Any] | None
    trades: list[dict[str, Any]]
    stats: dict[str, Any]
    warnings: list[str]
    raw: dict[str, Any]


def build_zone_trade_report(
    conn: Connection,
    config: AppConfig,
    zone_id: str,
    *,
    database: str,
    code_commit: str = "unknown",
    timezone: str = "Asia/Ho_Chi_Minh",
    generated_at: str | None = None,
) -> ZoneTradeReport:
    """Build a read-only report from persisted historical trade snapshots."""
    zone_row = conn.execute("SELECT * FROM price_zones WHERE id = ?", (zone_id,)).fetchone()
    idea_rows = conn.execute(
        "SELECT * FROM trade_ideas WHERE entry_zone_id = ? ORDER BY created_at, id",
        (zone_id,),
    ).fetchall()
    if zone_row is None and not idea_rows:
        raise ValueError(f"Zone not found and no trade ideas reference it: {zone_id}")

    idea_ids = [str(row["id"]) for row in idea_rows]
    order_rows = _rows_for_ids(conn, "trade_orders", "trade_idea_id", idea_ids, "created_at, id")
    execution_rows = _rows_for_ids(conn, "execution_requests", "trade_idea_id", idea_ids, "created_at, id")
    order_ids = [str(row["id"]) for row in order_rows]
    fill_rows = _rows_for_ids(conn, "trade_fills", "trade_order_id", order_ids, "fill_time, id")
    review_rows = _rows_for_ids(conn, "trade_reviews", "trade_order_id", order_ids, "created_at, id")

    ideas = {str(row["id"]): _row_dict(row) for row in idea_rows}
    executions_by_idea = _group_rows(execution_rows, "trade_idea_id")
    fills_by_order = _group_rows(fill_rows, "trade_order_id")
    reviews_by_order = _group_rows(review_rows, "trade_order_id")
    account_labels = sorted(
        {
            str(row["account_label"])
            for row in [*order_rows, *execution_rows]
            if row["account_label"]
        }
    )
    account_rows = _rows_for_ids(conn, "account_snapshots", "account_label", account_labels, "account_label")
    account_currency = {str(row["account_label"]): str(row["currency"] or "UNKNOWN") for row in account_rows}
    current_zone = _zone_dict(zone_row)
    historical_zone = _historical_zone_snapshot(idea_rows)

    trades = [
        _build_trade(
            conn,
            config,
            _row_dict(order),
            ideas.get(str(order["trade_idea_id"]), {}),
            executions_by_idea.get(str(order["trade_idea_id"]), []),
            fills_by_order.get(str(order["id"]), []),
            reviews_by_order.get(str(order["id"]), []),
            timezone,
            account_currency,
        )
        for order in order_rows
    ]
    # Ideas can exist without an order (blocked/rejected execution). Keep them visible.
    ordered_idea_ids = {str(row["trade_idea_id"]) for row in order_rows}
    for idea_row in idea_rows:
        idea_id = str(idea_row["id"])
        if idea_id in ordered_idea_ids:
            continue
        trades.append(
            _build_trade(
                conn,
                config,
                {},
                _row_dict(idea_row),
                executions_by_idea.get(idea_id, []),
                [],
                [],
                timezone,
                account_currency,
            )
        )

    warnings = _report_warnings(current_zone, historical_zone, trades)
    stats = _aggregate_stats(trades)
    generated = generated_at or datetime.now(UTC).replace(microsecond=0).isoformat()
    return ZoneTradeReport(
        zone_id=zone_id,
        generated_at=generated,
        database=database,
        code_commit=code_commit,
        timezone=timezone,
        zone=current_zone,
        historical_zone=historical_zone,
        trades=trades,
        stats=stats,
        warnings=warnings,
        raw={
            "zone": current_zone,
            "trade_ideas": [_row_dict(row) for row in idea_rows],
            "trade_orders": [_row_dict(row) for row in order_rows],
            "execution_requests": [_row_dict(row) for row in execution_rows],
            "trade_fills": [_row_dict(row) for row in fill_rows],
            "trade_reviews": [_row_dict(row) for row in review_rows],
            "account_snapshots": [_row_dict(row) for row in account_rows],
        },
    )


def render_zone_trade_report_html(report: ZoneTradeReport) -> str:
    zone = report.historical_zone or report.zone or {}
    stats = report.stats
    zone_title = f"{str(zone.get('direction') or '').upper()} {str(zone.get('zone_type') or 'zone').upper()}"
    warnings = "".join(f"<li>{_e(item)}</li>" for item in report.warnings) or "<li>No data-quality warnings.</li>"
    trade_sections = "".join(_render_trade(trade) for trade in report.trades)
    if not trade_sections:
        trade_sections = '<section class="panel"><h2>Trades</h2><p>No persisted trade orders or ideas for this zone.</p></section>'
    raw_json = json.dumps(report.raw, indent=2, sort_keys=True, default=str)
    zone_rows = [
        ("Zone ID", report.zone_id),
        ("Type", zone.get("zone_type")),
        ("Direction", zone.get("direction")),
        ("Timeframe", zone.get("timeframe")),
        ("Detector", zone.get("detector")),
        ("Source at trade", zone.get("source")),
        ("Low", _number(zone.get("price_low"), 5)),
        ("High", _number(zone.get("price_high"), 5)),
        ("Width", _number(_difference(zone.get("price_high"), zone.get("price_low")), 5)),
        ("Status", zone.get("status")),
        ("Detected", _time_pair(zone.get("detected_at"), report.timezone)),
        ("Valid until", _time_pair(zone.get("valid_until"), report.timezone)),
        ("Trade modes", ", ".join(zone.get("trade_modes") or []) or "--"),
        ("Confidence", _number(zone.get("confidence"), 4)),
        ("Weight", _number(zone.get("weight"), 4)),
        ("Fill ratio", _percent(zone.get("fill_ratio"))),
    ]
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trade report · {_e(report.zone_id)}</title>
<style>
:root{{--bg:#080d13;--panel:#101821;--panel2:#151f2b;--line:#263648;--text:#e7edf5;--muted:#8fa1b5;--cyan:#35c7d9;--green:#36d399;--red:#fb7185;--amber:#fbbf24}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 Inter,ui-sans-serif,system-ui,sans-serif}}
main{{max-width:1180px;margin:auto;padding:28px}} h1{{font-size:28px;margin:4px 0}} h2{{font-size:19px;margin:0 0 16px}} h3{{font-size:16px;margin:20px 0 10px}} p{{margin:6px 0}} .muted{{color:var(--muted)}}
.eyebrow{{color:var(--cyan);font-size:12px;letter-spacing:.16em;text-transform:uppercase}} .grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0}}
.stat,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:12px}} .stat{{padding:15px}} .stat strong{{display:block;font-size:22px;margin-top:3px}} .panel{{padding:20px;margin:14px 0}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:14px}} table{{width:100%;border-collapse:collapse}} td,th{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}} th{{color:var(--muted);font-weight:600}} td:first-child{{color:var(--muted);width:34%}}
.badge{{display:inline-block;padding:3px 8px;border-radius:999px;background:#1a2a37;color:var(--cyan);font-weight:700;font-size:12px}} .good{{color:var(--green)}} .bad{{color:var(--red)}} .warn{{color:var(--amber)}}
.timeline{{border-left:2px solid var(--line);padding-left:16px}} .event{{margin:10px 0}} code,pre{{font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}} pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#080d13;padding:14px;border-radius:9px;border:1px solid var(--line)}}
details summary{{cursor:pointer;color:var(--cyan);font-weight:700}} ul{{margin:8px 0;padding-left:22px}} .decision{{padding:10px 12px;background:var(--panel2);border-left:3px solid var(--cyan);margin:8px 0}}
@media(max-width:800px){{.grid{{grid-template-columns:1fr 1fr}}.two{{grid-template-columns:1fr}}main{{padding:16px}}}}
@media print{{body{{background:white;color:#111}}.panel,.stat{{border-color:#ccc;background:white}}details{{display:none}}}}
</style>
</head>
<body><main>
<div class="eyebrow">{REPORT_SCHEMA_VERSION}</div>
<h1>{_e(zone_title)} trade report</h1>
<p class="muted">Zone {_e(report.zone_id)} · generated {_e(_time_pair(report.generated_at, report.timezone))}</p>
<div class="grid">
  {_stat("Trades", stats.get("trade_count", 0))}
  {_stat("Net P&L", _aggregate_money(stats), _pnl_class(stats.get("total_pnl")))}
  {_stat("Total R", _signed(stats.get("total_r"), 3), _pnl_class(stats.get("total_r")))}
  {_stat("Win rate", _percent(stats.get("win_rate")))}
</div>
<section class="panel"><h2>Executive summary</h2><p>{_e(_executive_summary(report))}</p></section>
<div class="two">
  <section class="panel"><h2>Historical zone snapshot</h2>{_table(zone_rows)}</section>
  <section class="panel"><h2>Report provenance</h2>{_table([
      ("Schema", REPORT_SCHEMA_VERSION), ("Code commit", report.code_commit),
      ("Database", report.database), ("Display timezone", report.timezone),
      ("Evidence rule", "Persisted candidate/execution snapshot first; current zone second."),
  ])}</section>
</div>
<section class="panel"><h2>Data-quality notes</h2><ul>{warnings}</ul></section>
{trade_sections}
<section class="panel"><details><summary>Raw persisted metadata</summary><pre>{_e(raw_json)}</pre></details></section>
</main></body></html>"""


def write_zone_trade_report(path: Path, report: ZoneTradeReport) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_zone_trade_report_html(report), encoding="utf-8")
    return path


def _build_trade(
    conn: Connection,
    config: AppConfig,
    order: dict[str, Any],
    idea: dict[str, Any],
    executions: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    timezone: str,
    account_currency: dict[str, str],
) -> dict[str, Any]:
    execution = executions[-1] if executions else {}
    idea_context = _json_object(idea.get("context_snapshot_json"))
    execution_context = _json_object(execution.get("context_snapshot_json"))
    order_meta = _json_object(order.get("metadata_json"))
    candidate = (
        idea_context.get("candidate")
        or execution_context.get("candidate")
        or order_meta.get("candidate")
        or {}
    )
    candidate_meta = candidate.get("metadata") or order_meta.get("candidate_metadata") or {}
    pricing = idea_context.get("pricing_plan") or execution_context.get("pricing_plan") or {}
    side = str(order.get("side") or idea.get("direction") or execution.get("side") or "unknown").lower()
    signal_entry = _float(candidate.get("entry"), idea.get("suggested_entry"))
    actual_entry = _float(order.get("entry_price"), execution.get("entry_price"), pricing.get("entry_price"), signal_entry)
    initial_stop = _float(
        order_meta.get("initial_stop_loss"),
        execution.get("stop_loss"),
        pricing.get("stop_loss"),
        candidate.get("stop_loss"),
        idea.get("suggested_stop_loss"),
        order.get("stop_loss"),
    )
    take_profits = _json_list(order.get("take_profit_json")) or _json_list(execution.get("take_profit_json"))
    if not take_profits:
        take_profits = candidate.get("take_profit") or []
    risk = abs(actual_entry - initial_stop) if actual_entry is not None and initial_stop is not None else None
    excursion = _trade_excursion(conn, order, side, actual_entry, risk)
    partial = order_meta.get("partial_take_profit") if isinstance(order_meta.get("partial_take_profit"), dict) else {}
    sl_trace = _stop_trace(config, side, signal_entry, initial_stop, candidate_meta)
    opened_at = order.get("opened_at") or execution.get("created_at") or idea.get("created_at")
    closed_at = order.get("closed_at")
    account_label = order.get("account_label") or execution.get("account_label") or idea_context.get("account_label")
    return {
        "idea_id": idea.get("id"),
        "order_id": order.get("id"),
        "execution_id": execution.get("id"),
        "account_label": account_label,
        "currency": account_currency.get(str(account_label), "UNKNOWN"),
        "broker_symbol": execution.get("broker_symbol") or idea_context.get("broker_symbol"),
        "side": side,
        "playbook": idea.get("playbook") or candidate.get("playbook"),
        "reaction": candidate.get("zone_reaction_state") or candidate_meta.get("reaction_v2") or order_meta.get("zone_reaction_state"),
        "status": order.get("status") or execution.get("status") or idea.get("status"),
        "score": candidate.get("score"),
        "risk_reward": candidate.get("risk_reward") or idea.get("risk_reward"),
        "signal_time": candidate_meta.get("as_of") or candidate_meta.get("reaction_candle_time"),
        "opened_at": opened_at,
        "closed_at": closed_at,
        "signal_time_display": _time_pair(candidate_meta.get("as_of"), timezone),
        "opened_at_display": _time_pair(opened_at, timezone),
        "closed_at_display": _time_pair(closed_at, timezone),
        "timezone": timezone,
        "signal_entry": signal_entry,
        "actual_entry": actual_entry,
        "initial_stop": initial_stop,
        "current_stop": order.get("stop_loss"),
        "take_profits": take_profits,
        "quantity": order.get("quantity") or execution.get("quantity"),
        "close_price": order.get("close_price"),
        "pnl": order.get("pnl"),
        "pnl_r": order.get("pnl_r"),
        "risk_distance": risk,
        "entry_drift": _signed_difference(actual_entry, signal_entry),
        "context": {
            "h1_bias": candidate_meta.get("h1_bias") or order_meta.get("h1_bias"),
            "h1_regime": candidate_meta.get("h1_regime") or order_meta.get("h1_regime"),
            "macro_trend": candidate_meta.get("macro_trend") or order_meta.get("macro_trend"),
            "rsi_h1": candidate_meta.get("rsi_h1") or order_meta.get("rsi_h1"),
            "overlays": candidate_meta.get("overlays") or [],
            "context_bypass": candidate_meta.get("context_bypass"),
        },
        "trigger": {
            "reaction_open": candidate_meta.get("reaction_open"),
            "reaction_high": candidate_meta.get("reaction_high"),
            "reaction_low": candidate_meta.get("reaction_low"),
            "reaction_close": candidate_meta.get("reaction_close"),
            "reaction_body": candidate_meta.get("reaction_body"),
            "structure_types": candidate_meta.get("structure_trigger_types") or [],
            "price_action_types": candidate_meta.get("price_action_trigger_types") or [],
            "fill_ratio": candidate_meta.get("zone_fill_ratio") or candidate_meta.get("fill_ratio"),
        },
        "reason": candidate.get("reason") or [],
        "blocked_reason": candidate.get("blocked_reason") or [],
        "sl_trace": sl_trace,
        "partial": partial,
        "excursion": excursion,
        "execution_status": execution.get("status"),
        "failure_reason": execution.get("failure_reason"),
        "broker_order_id": execution.get("broker_order_id") or order_meta.get("broker_order_id"),
        "fills": fills,
        "reviews": reviews,
        "raw": {"idea": idea, "order": order, "execution": execution, "candidate": candidate},
    }


def _stop_trace(
    config: AppConfig,
    side: str,
    entry: float | None,
    initial_stop: float | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    atr = _float(metadata.get("atr"))
    fallback_atr = _float(metadata.get("stop_fallback_atr"))
    multiplier = _float(metadata.get("stop_fallback_atr_multiplier"), config.strategy.zone_reaction_v2_reject_atr_stop)
    zone_low = _float(metadata.get("zone_price_low"))
    zone_high = _float(metadata.get("zone_price_high"))
    reaction_low = _float(metadata.get("reaction_low"))
    reaction_high = _float(metadata.get("reaction_high"))
    buffer = atr * config.strategy.zone_reaction_v2_stop_buffer_atr if atr is not None else None
    full_zone_stop = None
    wick_stop = None
    if side in {"long", "buy"}:
        if buffer is not None and zone_low is not None:
            full_zone_stop = min(zone_low, reaction_low if reaction_low is not None else zone_low) - buffer
        if buffer is not None and reaction_low is not None:
            wick_stop = reaction_low - buffer
    elif side in {"short", "sell"}:
        if buffer is not None and zone_high is not None:
            full_zone_stop = max(zone_high, reaction_high if reaction_high is not None else zone_high) + buffer
        if buffer is not None and reaction_high is not None:
            wick_stop = reaction_high + buffer
    fallback_distance = fallback_atr * multiplier if fallback_atr is not None and multiplier is not None else None
    return {
        "selected_source": metadata.get("stop_source"),
        "reject_stop_mode": metadata.get("reject_stop_mode"),
        "initial_stop": initial_stop,
        "risk_distance": abs(entry - initial_stop) if entry is not None and initial_stop is not None else metadata.get("stop_distance"),
        "m15_atr": atr,
        "buffer": buffer,
        "full_zone_stop_estimate": full_zone_stop,
        "reaction_wick_stop_estimate": wick_stop,
        "max_stop_distance": config.strategy.zone_reaction_v2_max_stop_distance,
        "fallback_atr": fallback_atr,
        "fallback_atr_timeframe": metadata.get("stop_fallback_atr_timeframe"),
        "fallback_multiplier": multiplier,
        "fallback_distance": fallback_distance,
        "calculation_note": "Counterfactual stop estimates use the report code config; persisted initial_stop/source remain historical truth.",
    }


def _trade_excursion(
    conn: Connection,
    order: dict[str, Any],
    side: str,
    entry: float | None,
    risk: float | None,
) -> dict[str, Any]:
    start = order.get("opened_at")
    end = order.get("closed_at")
    symbol = order.get("symbol")
    if not start or not end or not symbol or entry is None:
        return {}
    rows = conn.execute(
        """
        SELECT MIN(low) AS min_low, MAX(high) AS max_high, COUNT(*) AS candles
        FROM candles
        WHERE symbol = ? AND timeframe = 'M15'
          AND close_time >= ? AND open_time <= ?
        """,
        (symbol, start, end),
    ).fetchone()
    if rows is None or not rows["candles"]:
        return {}
    min_low = float(rows["min_low"])
    max_high = float(rows["max_high"])
    if side in {"long", "buy"}:
        mfe = max(max_high - entry, 0.0)
        mae = max(entry - min_low, 0.0)
    else:
        mfe = max(entry - min_low, 0.0)
        mae = max(max_high - entry, 0.0)
    return {
        "mfe_price": round(mfe, 5),
        "mae_price": round(mae, 5),
        "mfe_r": round(mfe / risk, 4) if risk else None,
        "mae_r": round(mae / risk, 4) if risk else None,
        "candle_count": int(rows["candles"]),
        "note": "MFE/MAE use M15 high/low and do not model intrabar ordering or spread.",
    }


def _aggregate_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [trade for trade in trades if trade.get("pnl") is not None]
    pnl_values = [float(trade["pnl"]) for trade in closed]
    r_values = [float(trade["pnl_r"]) for trade in closed if trade.get("pnl_r") is not None]
    wins = sum(value > 0 for value in pnl_values)
    losses = sum(value < 0 for value in pnl_values)
    pnl_by_currency: dict[str, float] = {}
    for trade in closed:
        currency = str(trade.get("currency") or "UNKNOWN")
        pnl_by_currency[currency] = pnl_by_currency.get(currency, 0.0) + float(trade["pnl"])
    mixed_currencies = len(pnl_by_currency) > 1
    return {
        "trade_count": len(trades),
        "closed_count": len(closed),
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(closed) if closed else None,
        "total_pnl": None if mixed_currencies else round(sum(pnl_values), 2),
        "pnl_by_currency": {key: round(value, 2) for key, value in sorted(pnl_by_currency.items())},
        "mixed_currencies": mixed_currencies,
        "total_r": round(sum(r_values), 4),
        "average_pnl": round(sum(pnl_values) / len(closed), 2) if closed and not mixed_currencies else None,
        "average_r": round(sum(r_values) / len(r_values), 4) if r_values else None,
    }


def _historical_zone_snapshot(rows: list[Row]) -> dict[str, Any] | None:
    for row in rows:
        context = _json_object(row["context_snapshot_json"])
        candidate = context.get("candidate") or {}
        metadata = candidate.get("metadata") or {}
        if not metadata:
            continue
        return {
            "id": candidate.get("primary_zone_id") or row["entry_zone_id"],
            "zone_type": metadata.get("zone_type"),
            "timeframe": metadata.get("zone_timeframe"),
            "direction": metadata.get("zone_direction"),
            "detector": metadata.get("zone_detector"),
            "source": metadata.get("zone_source"),
            "status": metadata.get("zone_status"),
            "price_low": metadata.get("zone_price_low"),
            "price_high": metadata.get("zone_price_high"),
            "detected_at": metadata.get("zone_detected_at"),
            "valid_until": metadata.get("zone_valid_until"),
            "confidence": metadata.get("zone_confidence"),
            "weight": metadata.get("zone_weight"),
            "fill_ratio": metadata.get("zone_fill_ratio"),
            "trade_modes": metadata.get("trade_modes") or [],
        }
    return None


def _zone_dict(row: Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = _row_dict(row)
    metadata = _json_object(result.pop("metadata_json", None))
    result["metadata"] = metadata
    result["trade_modes"] = metadata.get("trade_modes") or []
    result["fill_ratio"] = metadata.get("fill_ratio")
    result["confidence"] = result.get("effective_confidence")
    result["weight"] = result.get("effective_weight")
    return result


def _report_warnings(
    current: dict[str, Any] | None,
    historical: dict[str, Any] | None,
    trades: list[dict[str, Any]],
) -> list[str]:
    warnings: list[str] = []
    if current is None:
        warnings.append("The current price_zones row is missing; the report relies on persisted trade snapshots.")
    if historical and current:
        changed: list[str] = []
        for key in ("source", "status", "price_low", "price_high", "trade_modes"):
            if historical.get(key) != current.get(key):
                changed.append(key)
        if changed:
            warnings.append(
                "Current zone differs from the historical trade snapshot in: " + ", ".join(changed) + "."
            )
    if any(not trade.get("order_id") for trade in trades):
        warnings.append("At least one trade idea has no persisted trade order; execution may have been blocked or failed.")
    if any(trade.get("failure_reason") for trade in trades):
        warnings.append("At least one execution request failed; see its execution section.")
    currencies = {str(trade.get("currency")) for trade in trades if trade.get("pnl") is not None}
    if len(currencies) > 1:
        warnings.append("Closed trades use multiple account currencies; P&L is grouped by currency and is not summed.")
    if not trades:
        warnings.append("No persisted trade ideas or orders reference this zone.")
    warnings.append("Historical candidate/execution metadata is authoritative; current code is used only for labeled calculations.")
    return warnings


def _render_trade(trade: dict[str, Any]) -> str:
    pnl = trade.get("pnl")
    currency = trade.get("currency")
    reaction = str(trade.get("reaction") or "unknown")
    context = trade["context"]
    trigger = trade["trigger"]
    sl = trade["sl_trace"]
    partial = trade.get("partial") or {}
    excursion = trade.get("excursion") or {}
    reason = "".join(f"<li>{_e(item)}</li>" for item in trade.get("reason") or []) or "<li>--</li>"
    timeline = [
        ("Signal", trade.get("signal_time_display")),
        ("Order opened", trade.get("opened_at_display")),
    ]
    if partial.get("done"):
        timeline.append(("Partial TP", _time_pair(partial.get("done_at"), trade.get("timezone") or "UTC")))
    if trade.get("closed_at"):
        timeline.append(("Order closed", trade.get("closed_at_display")))
    timeline_html = "".join(
        f'<div class="event"><span class="badge">{_e(label)}</span> {_e(value or "--")}</div>'
        for label, value in timeline
    )
    stop_decision = _stop_decision(sl, trade.get("side"))
    return f"""
<section class="panel">
  <div class="eyebrow">{_e(str(trade.get('account_label') or 'Unassigned account'))}</div>
  <h2>{_e(str(trade.get('side') or '').upper())} · {_e(reaction)} · {_e(str(trade.get('status') or 'unknown'))}</h2>
  <div class="grid">
    {_stat("Entry", _number(trade.get("actual_entry"), 5))}
    {_stat("Initial SL", _number(trade.get("initial_stop"), 5))}
    {_stat("Final TP", _number((trade.get("take_profits") or [None])[0], 5))}
    {_stat("P&L", _currency_money(pnl, currency), _pnl_class(pnl))}
  </div>
  <div class="two">
    <div><h3>Setup & context</h3>{_table([
        ("Idea / order", f"{trade.get('idea_id') or '--'} / {trade.get('order_id') or '--'}"),
        ("Reaction family", reaction), ("Playbook", trade.get("playbook")),
        ("Score", _number(trade.get("score"), 4)), ("RR", _number(trade.get("risk_reward"), 2)),
        ("H1 bias", context.get("h1_bias")), ("H1 regime", context.get("h1_regime")),
        ("Macro trend", context.get("macro_trend")), ("RSI H1", _number(context.get("rsi_h1"), 2)),
        ("Overlays", ", ".join(context.get("overlays") or []) or "--"),
    ])}</div>
    <div><h3>Trigger candle</h3>{_table([
        ("Open", _number(trigger.get("reaction_open"), 5)), ("High", _number(trigger.get("reaction_high"), 5)),
        ("Low", _number(trigger.get("reaction_low"), 5)), ("Close", _number(trigger.get("reaction_close"), 5)),
        ("Body", _number(trigger.get("reaction_body"), 5)), ("Zone fill", _percent(trigger.get("fill_ratio"))),
        ("Structure", ", ".join(trigger.get("structure_types") or []) or "--"),
        ("Price action", ", ".join(trigger.get("price_action_types") or []) or "--"),
    ])}</div>
  </div>
  <h3>Why eligible</h3><ul>{reason}</ul>
  <h3>Stop-loss decision trace</h3>
  <div class="decision">{_e(stop_decision)}</div>
  {_table([
      ("Selected source", sl.get("selected_source")), ("Persisted initial SL", _number(sl.get("initial_stop"), 5)),
      ("Risk distance", _number(sl.get("risk_distance"), 5)), ("M15 ATR / buffer", f"{_number(sl.get('m15_atr'), 5)} / {_number(sl.get('buffer'), 5)}"),
      ("Full-zone estimate", _number(sl.get("full_zone_stop_estimate"), 5)),
      ("Reaction-wick estimate", _number(sl.get("reaction_wick_stop_estimate"), 5)),
      ("Fallback", f"{_number(sl.get('fallback_multiplier'), 2)} × {sl.get('fallback_atr_timeframe') or '--'} ATR {_number(sl.get('fallback_atr'), 5)} = {_number(sl.get('fallback_distance'), 5)}"),
  ])}
  <div class="two">
    <div><h3>Execution & management</h3>{_table([
        ("Broker symbol", trade.get("broker_symbol")), ("Volume", _number(trade.get("quantity"), 2)),
        ("Signal entry", _number(trade.get("signal_entry"), 5)), ("Broker entry", _number(trade.get("actual_entry"), 5)),
        ("Entry drift", _signed(trade.get("entry_drift"), 5)), ("Broker order", trade.get("broker_order_id")),
        ("Partial enabled", partial.get("enabled")), ("Partial done", partial.get("done")),
        ("Partial trigger", _number(partial.get("trigger_price"), 5)), ("Partial close", _number(partial.get("close_price"), 5)),
        ("Closed volume", _number(partial.get("closed_volume"), 2)), ("BE applied", partial.get("breakeven_applied")),
        ("Close price", _number(trade.get("close_price"), 5)), ("P&L / R", f"{_currency_money(pnl, currency)} / {_signed(trade.get('pnl_r'), 3)}R"),
    ])}</div>
    <div><h3>Timeline & excursion</h3><div class="timeline">{timeline_html}</div>{_table([
        ("MFE", f"{_number(excursion.get('mfe_price'), 5)} / {_signed(excursion.get('mfe_r'), 3)}R"),
        ("MAE", f"{_number(excursion.get('mae_price'), 5)} / {_signed(excursion.get('mae_r'), 3)}R"),
        ("M15 candles", excursion.get("candle_count")),
    ])}</div>
  </div>
  {f'<p class="bad"><strong>Execution failure:</strong> {_e(trade.get("failure_reason"))}</p>' if trade.get("failure_reason") else ''}
</section>"""


def _stop_decision(trace: dict[str, Any], side: str | None) -> str:
    source = trace.get("selected_source") or "unknown"
    if source == "atr_fallback":
        return (
            "The persisted setup selected ATR fallback. The full-zone stop exceeded the configured wide-stop "
            "threshold or the wick alternative remained invalid inside the zone; the final distance used the "
            f"persisted {trace.get('fallback_atr_timeframe') or 'context'} ATR × {trace.get('fallback_multiplier') or '--'}."
        )
    if source == "zone":
        return "The persisted setup placed the stop beyond the complete zone plus the M15 ATR buffer."
    if source == "reaction_wick":
        return "The persisted setup placed the stop beyond the reaction wick plus the M15 ATR buffer."
    return f"Persisted stop source: {source}; inspect raw metadata for this historical code version."


def _executive_summary(report: ZoneTradeReport) -> str:
    stats = report.stats
    zone = report.historical_zone or report.zone or {}
    if not report.trades:
        return f"{zone.get('direction', '')} {zone.get('zone_type', 'zone')} has no persisted trades."
    reactions = sorted({str(trade.get("reaction") or "unknown") for trade in report.trades})
    sources = sorted({str(trade.get("sl_trace", {}).get("selected_source") or "unknown") for trade in report.trades})
    return (
        f"{len(report.trades)} setup/trade record(s), reaction={', '.join(reactions)}, "
        f"SL source={', '.join(sources)}. Closed result: {_aggregate_money(stats)} "
        f"({_signed(stats.get('total_r'), 3)}R), win rate {_percent(stats.get('win_rate'))}."
    )


def _rows_for_ids(
    conn: Connection,
    table: str,
    column: str,
    ids: list[str],
    order_by: str,
) -> list[Row]:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return conn.execute(
        f"SELECT * FROM {table} WHERE {column} IN ({placeholders}) ORDER BY {order_by}",
        ids,
    ).fetchall()


def _group_rows(rows: list[Row], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row[key]), []).append(_row_dict(row))
    return grouped


def _row_dict(row: Row) -> dict[str, Any]:
    return dict(row)


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _float(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _difference(high: Any, low: Any) -> float | None:
    high_value = _float(high)
    low_value = _float(low)
    return high_value - low_value if high_value is not None and low_value is not None else None


def _signed_difference(left: Any, right: Any) -> float | None:
    left_value = _float(left)
    right_value = _float(right)
    return left_value - right_value if left_value is not None and right_value is not None else None


def _time_pair(value: Any, timezone: str) -> str:
    if not value:
        return "--"
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        utc_value = parsed.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
        local_value = parsed.astimezone(ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M")
        return f"{utc_value} · {local_value} {timezone}"
    except (ValueError, TypeError, KeyError):
        return text


def _e(value: Any) -> str:
    return html.escape("--" if value is None else str(value), quote=True)


def _number(value: Any, digits: int = 2) -> str:
    number = _float(value)
    return "--" if number is None else f"{number:.{digits}f}"


def _money(value: Any) -> str:
    number = _float(value)
    if number is None:
        return "--"
    sign = "-" if number < 0 else ""
    return f"{sign}${abs(number):,.2f}"


def _currency_money(value: Any, currency: Any) -> str:
    number = _float(value)
    if number is None:
        return "--"
    code = str(currency or "UNKNOWN")
    if code == "USD":
        sign = "-" if number < 0 else ""
        return f"{sign}${abs(number):,.2f} USD"
    return f"{number:,.2f} {code}"


def _aggregate_money(stats: dict[str, Any]) -> str:
    grouped = stats.get("pnl_by_currency") or {}
    if not grouped:
        return "--"
    return " · ".join(_currency_money(value, currency) for currency, value in grouped.items())


def _signed(value: Any, digits: int = 2) -> str:
    number = _float(value)
    return "--" if number is None else f"{number:+.{digits}f}"


def _percent(value: Any) -> str:
    number = _float(value)
    return "--" if number is None else f"{number:.1%}"


def _pnl_class(value: Any) -> str:
    number = _float(value)
    if number is None or number == 0:
        return ""
    return "good" if number > 0 else "bad"


def _stat(label: str, value: Any, css_class: str = "") -> str:
    return f'<div class="stat"><span class="muted">{_e(label)}</span><strong class="{_e(css_class)}">{_e(value)}</strong></div>'


def _table(rows: list[tuple[Any, Any]]) -> str:
    body = "".join(f"<tr><td>{_e(label)}</td><td>{_e(value)}</td></tr>" for label, value in rows)
    return f"<table><tbody>{body}</tbody></table>"
