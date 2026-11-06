from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from sqlite3 import Connection
from statistics import median
from typing import Any

from .context import score_macro_trend
from .indicators import latest_rsi_snapshot
from .intraday_levels import build_intraday_map
from .strategy import average_body, build_setup_candidates, candle_body
from .strategy.h1_impulse_retest_v1 import (
    build_h1_impulse_markers,
    h1_impulse_preview_config_from_strategy,
)
from .zones import CandleSlice, latest_atr


CHART_PAYLOAD_VERSION = 1
CHART_INDICATOR_WARMUP_CANDLES = 1_000
MAX_TOUCH_ONLY_M15_TRIGGER_OVERLAYS = 500
WAVE_METRIC_LEG_LIMIT = 12
WAVE_STRENGTH_SAMPLE_SIZE = 4


def build_wave_metrics(
    structure_points: list[dict[str, Any]],
    candles: list[dict[str, Any]],
    *,
    as_of: str,
    leg_limit: int = WAVE_METRIC_LEG_LIMIT,
) -> dict[str, Any]:
    """Measure confirmed ZigZag legs without leaking unconfirmed replay swings."""
    if leg_limit < 1:
        raise ValueError("leg_limit must be >= 1")

    available: list[tuple[dict[str, Any], str]] = []
    for point in structure_points:
        metadata = point.get("metadata") if isinstance(point.get("metadata"), dict) else {}
        swing_type = metadata.get("swing_type")
        if swing_type not in {"high", "low"}:
            swing_type = _fallback_swing_type(str(point.get("type") or ""))
        confirmed_at = metadata.get("confirmed_at")
        if swing_type is None or str(point.get("time") or "") > as_of:
            continue
        if isinstance(confirmed_at, str) and confirmed_at > as_of:
            continue
        available.append((point, swing_type))

    collapsed: list[tuple[dict[str, Any], str]] = []
    for point, swing_type in sorted(available, key=lambda item: str(item[0]["time"])):
        if not collapsed or collapsed[-1][1] != swing_type:
            collapsed.append((point, swing_type))
            continue
        previous_point = collapsed[-1][0]
        replaces_previous = (
            float(point["price"]) > float(previous_point["price"])
            if swing_type == "high"
            else float(point["price"]) < float(previous_point["price"])
        )
        if replaces_previous:
            collapsed[-1] = (point, swing_type)

    ordered_candles = sorted(
        (candle for candle in candles if str(candle.get("time") or "") <= as_of),
        key=lambda candle: str(candle["time"]),
    )
    candle_times = [str(candle["time"]) for candle in ordered_candles]
    legs: list[dict[str, Any]] = []
    for (start_point, _), (end_point, _) in zip(collapsed, collapsed[1:]):
        start_price = float(start_point["price"])
        end_price = float(end_point["price"])
        if math.isclose(start_price, end_price):
            continue
        start_time = str(start_point["time"])
        end_time = str(end_point["time"])
        start_index = _last_time_index_at_or_before(candle_times, start_time)
        end_index = _last_time_index_at_or_before(candle_times, end_time)
        price_move = abs(end_price - start_price)
        bars = max(1, end_index - start_index) if start_index is not None and end_index is not None else None
        duration_hours = max(
            0.0,
            (datetime.fromisoformat(end_time) - datetime.fromisoformat(start_time)).total_seconds() / 3600,
        )
        midpoint = datetime.fromisoformat(start_time) + (
            datetime.fromisoformat(end_time) - datetime.fromisoformat(start_time)
        ) / 2
        legs.append(
            {
                "id": f"{start_point['id']}:{end_point['id']}",
                "direction": "up" if end_price > start_price else "down",
                "start_time": start_time,
                "end_time": end_time,
                "start_price": start_price,
                "end_price": end_price,
                "mid_time": midpoint.isoformat(),
                "mid_price": (start_price + end_price) / 2,
                "price_move": round(price_move, 5),
                "bars": bars,
                "duration_hours": round(duration_hours, 2),
                "confirmed": True,
            }
        )

    recent_legs = legs[-leg_limit:]
    all_up_legs = [leg for leg in recent_legs if leg["direction"] == "up"]
    all_down_legs = [leg for leg in recent_legs if leg["direction"] == "down"]
    up_legs = all_up_legs[-(WAVE_STRENGTH_SAMPLE_SIZE + 1):-1]
    down_legs = all_down_legs[-(WAVE_STRENGTH_SAMPLE_SIZE + 1):-1]
    up_price = [float(leg["price_move"]) for leg in up_legs]
    down_price = [float(leg["price_move"]) for leg in down_legs]
    up_bars = [float(leg["bars"]) for leg in up_legs if leg["bars"] is not None]
    down_bars = [float(leg["bars"]) for leg in down_legs if leg["bars"] is not None]
    up_speed = [
        float(leg["price_move"]) / float(leg["bars"])
        for leg in up_legs
        if leg["bars"]
    ]
    down_speed = [
        float(leg["price_move"]) / float(leg["bars"])
        for leg in down_legs
        if leg["bars"]
    ]
    up_median_price = median(up_price) if up_price else None
    down_median_price = median(down_price) if down_price else None
    ratio = up_median_price / down_median_price if up_median_price is not None and down_median_price else None
    control = "unknown"
    if ratio is not None:
        control = "buy" if ratio > 1.25 else "sell" if ratio < 0.8 else "balanced"

    latest = recent_legs[-1] if recent_legs else None
    previous = recent_legs[-2] if len(recent_legs) >= 2 else None
    latest_to_previous = (
        float(latest["price_move"]) / float(previous["price_move"])
        if latest is not None and previous is not None and previous["price_move"]
        else None
    )
    efficiency_legs = recent_legs[-6:]
    total_path = sum(float(leg["price_move"]) for leg in efficiency_legs)
    net_move = (
        float(efficiency_legs[-1]["end_price"]) - float(efficiency_legs[0]["start_price"])
        if efficiency_legs
        else 0.0
    )
    efficiency = abs(net_move) / total_path if total_path else None
    efficiency_direction = "up" if net_move > 0 else "down" if net_move < 0 else "flat"
    if efficiency is None:
        market_state = "unknown"
    elif efficiency <= 0.25:
        market_state = "choppy"
    elif efficiency >= 0.55:
        market_state = "trending_up" if net_move > 0 else "trending_down" if net_move < 0 else "choppy"
    else:
        market_state = "rotational"

    up_change_pct = _latest_direction_change_pct(recent_legs, "up", WAVE_STRENGTH_SAMPLE_SIZE)
    down_change_pct = _latest_direction_change_pct(recent_legs, "down", WAVE_STRENGTH_SAMPLE_SIZE)
    return {
        "legs": recent_legs,
        "strength": {
            "up_median_price": round(up_median_price, 5) if up_median_price is not None else None,
            "down_median_price": round(down_median_price, 5) if down_median_price is not None else None,
            "up_median_bars": round(median(up_bars), 1) if up_bars else None,
            "down_median_bars": round(median(down_bars), 1) if down_bars else None,
            "up_median_speed": round(median(up_speed), 5) if up_speed else None,
            "down_median_speed": round(median(down_speed), 5) if down_speed else None,
            "ratio": round(ratio, 4) if ratio is not None else None,
            "control": control,
            "up_samples": len(up_legs),
            "down_samples": len(down_legs),
            "latest": {
                "direction": latest["direction"],
                "price_move": latest["price_move"],
                "bars": latest["bars"],
                "speed": round(float(latest["price_move"]) / float(latest["bars"]), 5) if latest["bars"] else None,
            }
            if latest is not None
            else None,
            "latest_to_previous_ratio": round(latest_to_previous, 4) if latest_to_previous is not None else None,
            "up_change_pct": round(up_change_pct, 1) if up_change_pct is not None else None,
            "down_change_pct": round(down_change_pct, 1) if down_change_pct is not None else None,
            "efficiency": round(efficiency, 4) if efficiency is not None else None,
            "efficiency_direction": efficiency_direction,
            "market_state": market_state,
            "efficiency_samples": len(efficiency_legs),
        },
    }


def _latest_direction_change_pct(
    legs: list[dict[str, Any]],
    direction: str,
    sample_size: int,
) -> float | None:
    direction_legs = [leg for leg in legs if leg["direction"] == direction]
    if len(direction_legs) < 2:
        return None
    latest_move = float(direction_legs[-1]["price_move"])
    baseline_moves = [float(leg["price_move"]) for leg in direction_legs[-(sample_size + 1):-1]]
    baseline = median(baseline_moves) if baseline_moves else None
    return (latest_move / baseline - 1) * 100 if baseline else None


def _fallback_swing_type(point_type: str) -> str | None:
    if point_type in {"HH", "LH", "EQH", "swing_high"}:
        return "high"
    if point_type in {"HL", "LL", "EQL", "swing_low"}:
        return "low"
    return None


def _last_time_index_at_or_before(times: list[str], target: str) -> int | None:
    result: int | None = None
    for index, value in enumerate(times):
        if value > target:
            break
        result = index
    return result


def load_manual_ai_setup_candidates(
    conn: Connection,
    symbol: str,
    allowed_playbooks: set[str] | None,
    as_of: str,
    h1_max_signal_age_hours: int = 48,
) -> list[dict[str, Any]]:
    """Expose unfilled Manual AI plans through the normal setup layer."""
    rows = conn.execute(
        """
        SELECT * FROM manual_ai_plans
        WHERE symbol = ?
          AND execution_state IN ('primary', 'watch_only')
          AND status IN ('draft', 'approved', 'arming', 'armed', 'replace_requested', 'expired', 'cancelled')
        ORDER BY created_at ASC
        """,
        (symbol,),
    ).fetchall()
    candidates: list[dict[str, Any]] = []
    grouped_rows: dict[str, list[Any]] = {}
    for row in rows:
        grouped_rows.setdefault(str(row["client_id"]), []).append(row)
    for row in rows:
        client_id = str(row["client_id"])
        group = grouped_rows.pop(client_id, None)
        if group is None:
            continue
        display_group = [item for item in group if str(item["status"]) != "cancelled"]
        if not display_group:
            continue
        row = display_group[0]
        raw_payload = json.loads(row["raw_payload_json"] or "{}")
        plan_playbook = str(raw_payload.get("playbook") or "manual_ai_v1")
        if allowed_playbooks is not None and plan_playbook not in allowed_playbooks:
            continue
        raw_candidates = raw_payload.get("candidates") if isinstance(raw_payload, dict) else []
        raw_candidate = next(
            (
                item
                for item in raw_candidates or []
                if isinstance(item, dict) and item.get("client_id") == client_id
            ),
            {},
        )
        status_order = {"expired": -1, "draft": 0, "approved": 1, "arming": 2, "armed": 3, "replace_requested": 4}
        plan_status = max((str(item["status"]) for item in display_group), key=lambda value: status_order.get(value, -1))
        if all(str(item["expires_at"]) <= as_of for item in display_group):
            plan_status = "expired"
        market_context = raw_payload.get("market_context") if isinstance(raw_payload.get("market_context"), dict) else {}
        target_plan = market_context.get("target_plan") if isinstance(market_context.get("target_plan"), dict) else {}
        target_mode = str(market_context.get("target_mode") or "custom")
        target_options = target_plan.get("options") if isinstance(target_plan.get("options"), list) else []
        target_option = next(
            (
                option for option in target_options
                if isinstance(option, dict) and str(option.get("mode")) == target_mode
            ),
            {},
        )
        signal_candle_time = str(market_context.get("signal_candle_time") or "")
        if plan_status == "expired":
            if plan_playbook != "h1_impulse_retest_v1" or not signal_candle_time:
                continue
            try:
                signal_open = datetime.fromisoformat(signal_candle_time)
                chart_as_of = datetime.fromisoformat(as_of)
                signal_age_hours = (chart_as_of - signal_open).total_seconds() / 3600 - 1
            except ValueError:
                continue
            if signal_age_hours < 0 or signal_age_hours > h1_max_signal_age_hours:
                continue
        account_labels = sorted(str(item["account_label"]) for item in display_group if item["account_label"])
        account_statuses = [
            {"account_label": str(item["account_label"] or "Default"), "status": str(item["status"])}
            for item in sorted(group, key=lambda item: str(item["account_label"] or "Default"))
        ]
        replacement_errors = [
            {"account_label": item["account_label"], "error": item["replacement_error"]}
            for item in group
            if item["replacement_error"]
        ]
        replacement = next(
            (
                json.loads(item["replacement_levels_json"] or "{}")
                for item in group
                if str(item["status"]) == "replace_requested"
            ),
            {},
        )
        target_mode = str(replacement.get("target_mode") or target_mode)
        target_option = next(
            (
                option for option in target_options
                if isinstance(option, dict) and str(option.get("mode")) == target_mode
            ),
            target_option,
        )
        entry_price = float(replacement.get("entry_price", row["entry_price"]))
        stop_loss = float(replacement.get("stop_loss", row["stop_loss"]))
        take_profit = float(replacement.get("take_profit", row["take_profit"]))
        risk_reward = float(replacement.get("risk_reward", row["risk_reward"]))
        entry_source = str(replacement.get("entry_source") or raw_candidate.get("entry_source") or "strategy_calculated")
        candidates.append(
            {
                "id": str(row["id"]),
                "symbol": str(row["symbol"]),
                "timeframe": "H1" if plan_playbook == "h1_impulse_retest_v1" else "M5",
                "playbook": plan_playbook,
                "direction": "long" if row["side"] == "buy" else "short",
                "status": "expired" if plan_status == "expired" else "waiting_confirmation",
                "zone_reaction_state": "expired" if plan_status == "expired" else "limit_pending",
                "score": float(raw_candidate.get("confidence") or 0.5),
                "entry": entry_price,
                "stop_loss": stop_loss,
                "take_profit": [take_profit],
                "risk_reward": risk_reward,
                "primary_zone_id": None,
                "related_zone_ids": [],
                "trigger_point_ids": [],
                "reason": [
                    str(raw_candidate.get("entry_reason") or f"{plan_playbook} {plan_status} limit plan")
                ],
                "blocked_reason": [],
                "expires_at": str(row["expires_at"]),
                "metadata": {
                    "manual_ai": True,
                    "execution_plan": True,
                    "h1_impulse_preview": plan_playbook == "h1_impulse_retest_v1",
                    "manual_ai_plan_status": plan_status,
                    "manual_ai_replace_pending": plan_status == "replace_requested",
                    "manual_ai_replace_error": row["replacement_error"],
                    "manual_ai_replace_errors": replacement_errors,
                    "execution_state": str(row["execution_state"]),
                    "created_at": str(row["created_at"]),
                    "as_of": raw_payload.get("as_of"),
                    "signal_candle_time": signal_candle_time,
                    "atr": market_context.get("atr"),
                    "parameters": market_context.get("parameters") or {},
                    "limit_expires_at": str(row["expires_at"]),
                    "account_label": row["account_label"],
                    "account_labels": account_labels,
                    "account_statuses": account_statuses,
                    "order_type": "limit",
                    "entry_source": entry_source,
                    "target_mode": target_mode,
                    "target_plan": target_plan,
                    "target_reward_distance": target_option.get("reward_distance"),
                    "target_warning": target_plan.get("fallback_reason"),
                    "entry_options": raw_candidate.get("entry_options") or [],
                    "original_status": raw_candidate.get("original_status"),
                    "original_blocked_reasons": raw_candidate.get("original_blocked_reasons") or [],
                    "soft_blocked_reasons": raw_candidate.get("soft_blocked_reasons") or [],
                    "hard_blocked_reasons": raw_candidate.get("hard_blocked_reasons") or [],
                    "human_override": bool(raw_candidate.get("human_override")),
                    "override_reason": raw_candidate.get("override_reason") or "",
                    "renewed_from_plan_id": raw_candidate.get("renewed_from_plan_id"),
                    "renewal_count": int(raw_candidate.get("renewal_count") or 0),
                    "expiry_hours": (
                        float(raw_candidate["expires_in_minutes"]) / 60
                        if plan_playbook == "h1_impulse_retest_v1"
                        and isinstance(raw_candidate.get("expires_in_minutes"), (int, float))
                        else None
                    ),
                    "partial_take_profit": json.loads(row["partial_take_profit_json"] or "{}"),
                    "cancel_conditions": json.loads(row["cancel_conditions_json"] or "[]"),
                },
            }
        )
    return candidates


def load_quick_order_setup_candidates(
    conn: Connection,
    symbol: str,
    allowed_playbooks: set[str] | None,
) -> list[dict[str, Any]]:
    """Expose active Quick Order limits through the pending setup layer."""
    if allowed_playbooks is not None and "quick_order_v1" not in allowed_playbooks:
        return []
    rows = conn.execute(
        """
        SELECT * FROM quick_order_requests
        WHERE symbol = ?
          AND order_type = 'limit'
          AND status IN ('queued', 'executing', 'pending', 'cancel_requested', 'replace_requested')
        ORDER BY created_at ASC, account_label ASC
        """,
        (symbol,),
    ).fetchall()
    grouped_rows: dict[str, list[Any]] = {}
    for row in rows:
        grouped_rows.setdefault(str(row["client_group_id"]), []).append(row)

    candidates: list[dict[str, Any]] = []
    status_order = {"queued": 0, "executing": 1, "pending": 2, "replace_requested": 3, "cancel_requested": 4}
    for group_id, group in grouped_rows.items():
        row = max(group, key=lambda item: status_order.get(str(item["status"]), -1))
        group_status = str(row["status"])
        replacement = {}
        if group_status == "replace_requested":
            try:
                parsed_replacement = json.loads(row["replacement_levels_json"] or "{}")
                replacement = parsed_replacement if isinstance(parsed_replacement, dict) else {}
            except (TypeError, ValueError):
                replacement = {}
        entry = float(replacement.get("entry_price", row["effective_entry"]))
        stop_loss = float(replacement.get("stop_loss", row["effective_stop"]))
        take_profit = float(replacement.get("take_profit", row["take_profit"]))
        risk_reward = float(replacement.get("risk_reward", row["risk_reward"]))
        replacement_errors = [
            str(item["replacement_error"])
            for item in group
            if item["replacement_error"]
        ]
        account_labels = sorted(str(item["account_label"]) for item in group)
        account_statuses = [
            {"account_label": str(item["account_label"]), "status": str(item["status"])}
            for item in sorted(group, key=lambda item: str(item["account_label"]))
        ]
        candidates.append(
            {
                "id": group_id,
                "symbol": str(row["symbol"]),
                "timeframe": "H1",
                "playbook": "quick_order_v1",
                "direction": "long" if row["side"] == "buy" else "short",
                "status": "waiting_confirmation",
                "zone_reaction_state": "limit_pending",
                "score": 1.0,
                "entry": entry,
                "stop_loss": stop_loss,
                "take_profit": [take_profit],
                "risk_reward": risk_reward,
                "primary_zone_id": None,
                "related_zone_ids": [],
                "trigger_point_ids": [],
                "reason": [f"Quick Order {group_status} limit"],
                "blocked_reason": [],
                "expires_at": str(row["expires_at"]),
                "metadata": {
                    "quick_order": True,
                    "quick_order_group_id": group_id,
                    "quick_order_status": group_status,
                    "quick_order_replace_pending": group_status == "replace_requested",
                    "quick_order_replace_errors": replacement_errors,
                    "created_at": str(row["created_at"]),
                    "limit_expires_at": str(row["expires_at"]),
                    "account_label": row["account_label"],
                    "account_labels": account_labels,
                    "account_statuses": account_statuses,
                    "order_type": "limit",
                    "entry_source": "quick_order",
                    "atr": float(row["atr_h1"]),
                    "atr_candle_time": str(row["atr_candle_time"]),
                },
            }
        )
    return candidates


def build_m15_signal_snapshot(
    candles: list[dict[str, Any]],
    setup_candidates: list[dict[str, Any]],
    avg_body_period: int = 20,
) -> dict[str, Any] | None:
    """Describe the last closed M15 candle and its best zone-trigger candidate.

    The dashboard intentionally receives closed-candle data only. Live/forming
    candles can be useful for chart touch overlays, but they must not look like
    a confirmed strategy trigger before the worker can evaluate them.
    """
    if not candles:
        return None
    candle = candles[-1]
    period = max(int(avg_body_period), 1)
    # Match Zone Reaction V2 exactly: the trigger candle is never part of its
    # own body baseline. The card keeps using the available preceding sample
    # while history is warming up; strategy eligibility still requires all N.
    average = average_body(candles[:-1], period)
    body = candle_body(candle)
    body_ratio = body / average if average > 0 else None
    close = float(candle["close"])
    open_ = float(candle["open"])
    direction = "bullish" if close > open_ else "bearish" if close < open_ else "doji"
    recovery_size = (
        close - float(candle["low"])
        if direction == "bullish"
        else float(candle["high"]) - close
        if direction == "bearish"
        else None
    )
    recovery_ratio = recovery_size / average if recovery_size is not None and average > 0 else None

    status_priority = {
        "eligible": 0,
        "waiting_confirmation": 1,
        "blocked": 2,
        "watching": 3,
        "approaching": 4,
    }
    best_candidate = min(
        setup_candidates,
        key=lambda candidate: (
            status_priority.get(str(candidate.get("status") or ""), 9),
            -float(candidate.get("score") or 0.0),
            str(candidate.get("id") or ""),
        ),
        default=None,
    )
    result: dict[str, Any] = {
        "candle_time": candle["time"],
        "candle_close_time": candle.get("close_time"),
        "candle_closed": True,
        "open": open_,
        "high": float(candle["high"]),
        "low": float(candle["low"]),
        "close": close,
        "candle_direction": direction,
        "avg_body_period": period,
        "avg_body": round(average, 5),
        "body": round(body, 5),
        "body_avg_ratio": round(body_ratio, 4) if body_ratio is not None else None,
        "candidate_count": len(setup_candidates),
        "candidate_id": None,
        "status": "watching",
        "reaction_state": None,
        "trigger_method": "close_extreme_recovery",
        "trigger_candle_time": None,
        "trigger_is_latest_closed_candle": False,
        "trigger_avg_body": None,
        "trigger_body": None,
        "trigger_body_avg_ratio": None,
        "strength_size": round(recovery_size, 5) if recovery_size is not None else None,
        "strength_avg_ratio": round(recovery_ratio, 4) if recovery_ratio is not None else None,
        "zone_id": None,
        "zone_type": None,
        "reason": None,
    }
    if best_candidate is None:
        return result

    metadata = best_candidate.get("metadata") if isinstance(best_candidate.get("metadata"), dict) else {}
    reasons = best_candidate.get("reason") if isinstance(best_candidate.get("reason"), list) else []
    reaction_state = str(best_candidate.get("zone_reaction_state") or metadata.get("reaction_v2") or "")
    trigger_method = str(metadata.get("reaction_trigger_method") or "")
    if not trigger_method:
        if metadata.get("wick_reject_confirmed") is True:
            trigger_method = "confirmed_wick"
        elif reaction_state == "internal_reject":
            trigger_method = "strong_body"
        elif any("strong " in str(reason).lower() and "rejection" in str(reason).lower() for reason in reasons):
            trigger_method = "strong_body"
    trigger_time = str(metadata.get("reaction_candle_time") or "")
    reaction_body = _optional_float(metadata.get("reaction_body"))
    reaction_average = _optional_float(metadata.get("reaction_avg_body"))
    reaction_body_ratio = _optional_float(metadata.get("reaction_body_avg_ratio"))
    rejection_size = _optional_float(metadata.get("reaction_rejection_size"))
    rejection_ratio = _optional_float(metadata.get("reaction_rejection_avg_ratio"))
    if trigger_method in {"pinbar", "close_extreme_recovery"}:
        strength_size = rejection_size
        strength_ratio = rejection_ratio
    elif trigger_method == "confirmed_wick":
        strength_size = _optional_float(metadata.get("wick_reject_rejection_size"))
        strength_ratio = _optional_float(metadata.get("wick_reject_rejection_avg_ratio"))
    else:
        strength_size = reaction_body
        strength_ratio = reaction_body_ratio

    result.update(
        {
            "candidate_id": best_candidate.get("id"),
            "status": best_candidate.get("status"),
            "reaction_state": reaction_state or None,
            "trigger_method": trigger_method or None,
            "trigger_candle_time": trigger_time or None,
            "trigger_is_latest_closed_candle": trigger_time == str(candle["time"]),
            "trigger_avg_body": round(reaction_average, 5) if reaction_average is not None else None,
            "trigger_body": round(reaction_body, 5) if reaction_body is not None else None,
            "trigger_body_avg_ratio": round(reaction_body_ratio, 4) if reaction_body_ratio is not None else None,
            "strength_size": round(strength_size, 5) if strength_size is not None else None,
            "strength_avg_ratio": round(strength_ratio, 4) if strength_ratio is not None else None,
            "zone_id": best_candidate.get("primary_zone_id"),
            "zone_type": metadata.get("zone_type"),
            "reason": str(reasons[0]) if reasons else None,
        }
    )
    return result


def _optional_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def compute_live_macro_trend_context(
    conn: Connection,
    symbol: str,
    macro_trend_config: Any,
    end: str | None = None,
) -> dict[str, Any] | None:
    """Compute a chart-context dict for macro trend straight from candles.

    Used as a fallback so the dashboard always shows a fresh macro trend even
    when no `detect-macro-trend` CLI run has persisted one to market_contexts.
    """
    limit = macro_trend_config.lookback_candles + macro_trend_config.atr_period + 2
    candles = load_chart_candles(conn, symbol, macro_trend_config.timeframe, limit, end=end)
    if not candles:
        return None
    candle_rows = [
        {
            "open_time": candle["time"],
            "high": candle["high"],
            "low": candle["low"],
            "close": candle["close"],
        }
        for candle in candles
    ]
    score = score_macro_trend(
        candle_rows,
        macro_trend_config.lookback_candles,
        macro_trend_config.flat_threshold_atr,
        macro_trend_config.atr_period,
    )
    value = str(score["value"])
    confidence = float(score["confidence"])
    return {
        "bot_value": value,
        "primary_value": value,
        "secondary_value": None,
        "bot_confidence": confidence,
        "effective_value": value,
        "effective_confidence": confidence,
        "source": "bot",
        "valid_from": str(candles[-1]["time"]),
        "valid_until": None,
        "status": "active",
        "metadata": {
            "detector": "macro_trend_v1_live",
            "version": 1,
            "lookback_candles": score["lookback_candles"],
            "momentum": score["momentum"],
            "momentum_atr": score["momentum_atr"],
            "atr": score["atr"],
            "reference_time": score["reference_time"],
        },
    }


def json_loads(value: str | None, default: Any) -> Any:
    if value in (None, ""):
        return default
    return json.loads(value)


def load_live_candle(
    conn: Connection,
    symbol: str,
    timeframe: str,
) -> dict[str, Any] | None:
    """Return the currently forming (live) candle from live_candles, or None."""
    row = conn.execute(
        """
        SELECT open_time, open, high, low, close, volume
        FROM live_candles
        WHERE symbol = ? AND timeframe = ?
        """,
        (symbol, timeframe),
    ).fetchone()
    if row is None:
        return None
    return {
        "time": row["open_time"],
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"]) if row["volume"] is not None else None,
    }


def build_atr_snapshot(
    conn: Connection,
    symbol: str,
    timeframes: list[str],
    period: int = 14,
    end: str | None = None,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for timeframe in timeframes:
        candles = load_chart_candles(conn, symbol, timeframe, period + 2, end=end)
        atr_value = latest_atr(
            [
                CandleSlice(
                    open_time=candle["time"],
                    high=candle["high"],
                    low=candle["low"],
                    close=candle["close"],
                    open=candle["open"],
                )
                for candle in candles
            ],
            period=period,
        )
        result[timeframe] = {
            "period": period,
            "value": round(float(atr_value), 5) if atr_value is not None else None,
            "as_of": candles[-1]["time"] if candles else None,
        }
    return result


def build_h1_impulse_marker_layer(
    conn: Connection,
    symbol: str,
    timeframe: str,
    visible_candles: list[dict[str, Any]],
    strategy_config: Any | None,
) -> list[dict[str, Any]]:
    if timeframe != "H1" or strategy_config is None or not visible_candles:
        return []
    try:
        config = h1_impulse_preview_config_from_strategy(strategy_config)
    except AttributeError:
        # Lightweight test/CLI configs may intentionally omit this research playbook.
        return []
    history = load_chart_candles(
        conn,
        symbol,
        "H1",
        len(visible_candles) + config.atr_period + 2,
        end=str(visible_candles[-1]["time"]),
    )
    return build_h1_impulse_markers(
        history,
        visible_start=str(visible_candles[0]["time"]),
        visible_end=str(visible_candles[-1]["time"]),
        config=config,
    )


def build_rsi_snapshot(
    conn: Connection,
    symbol: str,
    timeframes: list[str],
    period: int = 14,
    slope_periods: tuple[int, ...] = (3, 5),
    end: str | None = None,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    limit = period + max(slope_periods, default=0) + 5
    for timeframe in timeframes:
        candles = load_chart_candles(conn, symbol, timeframe, limit, end=end)
        result[timeframe] = latest_rsi_snapshot(candles, period=period, slope_periods=slope_periods)
    return result


def load_chart_candles(
    conn: Connection,
    symbol: str,
    timeframe: str,
    limit: int,
    start: str | None = None,
    end: str | None = None,
    start_index: int | None = None,
) -> list[dict[str, Any]]:
    if start_index is not None and start is None and end is None:
        rows = conn.execute(
            """
            SELECT open_time, close_time, open, high, low, close, volume
            FROM candles
            WHERE symbol = ? AND timeframe = ?
            ORDER BY open_time
            LIMIT ? OFFSET ?
            """,
            (symbol, timeframe, limit, start_index),
        ).fetchall()
        return chart_candle_rows_to_dicts(rows)

    clauses = ["symbol = ?", "timeframe = ?"]
    params: list[Any] = [symbol, timeframe]
    if start:
        clauses.append("open_time >= ?")
        params.append(start)
    if end:
        clauses.append("open_time <= ?")
        params.append(end)

    rows = conn.execute(
        f"""
        SELECT open_time, close_time, open, high, low, close, volume
        FROM (
            SELECT open_time, close_time, open, high, low, close, volume
            FROM candles
            WHERE {' AND '.join(clauses)}
            ORDER BY open_time DESC
            LIMIT ?
        )
        ORDER BY open_time
        """,
        (*params, limit),
    ).fetchall()
    return chart_candle_rows_to_dicts(rows)


def chart_candle_rows_to_dicts(rows: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "time": row["open_time"],
            "close_time": row["close_time"],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]) if row["volume"] is not None else None,
        }
        for row in rows
    ]


def load_chart_indicator_candles(
    conn: Connection,
    symbol: str,
    timeframe: str,
    visible_candles: list[dict[str, Any]],
    warmup_bars: int = CHART_INDICATOR_WARMUP_CANDLES,
) -> list[dict[str, Any]]:
    if not visible_candles:
        return []
    if warmup_bars <= 0:
        return list(visible_candles)

    # The warm-up history is calculation-only. Include the first visible bar
    # in this query, then de-duplicate it when combining both windows.
    historical = load_chart_candles(
        conn,
        symbol,
        timeframe,
        warmup_bars + 1,
        end=str(visible_candles[0]["time"]),
    )
    by_time = {
        str(candle["time"]): candle
        for candle in [*historical, *visible_candles]
    }
    return [by_time[time] for time in sorted(by_time)]


def load_chart_structure(
    conn: Connection,
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, detector, status, point_type, price, event_time, confidence,
               related_zone_ids_json, metadata_json
        FROM structure_points
        WHERE symbol = ? AND timeframe = ? AND event_time >= ? AND event_time <= ?
        ORDER BY event_time
        """,
        (symbol, timeframe, start, end),
    ).fetchall()
    points: list[dict[str, Any]] = []
    for row in rows:
        metadata = json_loads(row["metadata_json"], {})
        points.append(
            {
                "id": row["id"],
                "time": row["event_time"],
                "type": row["point_type"],
                "price": float(row["price"]),
                "detector": row["detector"],
                "status": row["status"],
                "confidence": float(row["confidence"]),
                "direction": metadata.get("direction"),
                "related_zone_ids": json_loads(row["related_zone_ids_json"], []),
                "metadata": metadata,
            }
        )
    return points


def load_chart_zones(
    conn: Connection,
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    if timeframe.upper() != "H1":
        return []
    clauses = [
        "symbol = ?",
        "timeframe = ?",
        "status != 'deleted'",
        "start_time <= ?",
        "detected_at <= ?",
        "(status = 'draft' OR end_time IS NULL OR end_time >= ?)",
    ]
    params: list[Any] = [symbol, timeframe, end, end, start]
    if active_only:
        # Drafts are deliberately excluded here because live workers request
        # active-only chart payloads for strategy evaluation.
        clauses.append(
            "(status = 'active' OR (status NOT IN ('draft', 'disabled') AND end_time IS NOT NULL AND end_time > ?))"
        )
        clauses.append("(status != 'active' OR valid_until > ?)")
        params.append(end)
        params.append(end)

    rows = conn.execute(
        f"""
        SELECT id, detector, zone_type, direction, price_low, price_high,
               start_time, end_time, valid_from, valid_until, invalidated_at,
               invalidated_by_structure_point_id, detected_at, effective_weight,
               effective_confidence, status, source, metadata_json, created_at, updated_at
        FROM price_zones
        WHERE {' AND '.join(clauses)}
        ORDER BY status ASC, effective_weight DESC, detected_at DESC
        """,
        params,
    ).fetchall()
    zones: list[dict[str, Any]] = []
    for row in rows:
        metadata = json_loads(row["metadata_json"], {})
        is_bot_sr = (
            row["zone_type"] in ("support", "resistance")
            and row["source"] != "human"
            and row["detector"] != "human_manual_v1"
        )
        visual_start = row["detected_at"] if is_bot_sr and row["detected_at"] else row["start_time"]
        projection = project_zone_lifecycle_for_chart(row, metadata, end, is_bot_sr=is_bot_sr)
        status = projection["status"]
        visual_end = projection["visual_end"]
        invalidated_at = projection["invalidated_at"]
        zones.append(
            {
            "id": row["id"],
            "type": row["zone_type"],
            "timeframe": timeframe,
            "direction": row["direction"],
            "detector": row["detector"],
            "status": status,
            "source": row["source"],
            "price_low": float(row["price_low"]),
            "price_high": float(row["price_high"]),
            "visual_start": visual_start,
            "visual_end": visual_end,
            "valid_from": row["valid_from"],
            "valid_until": row["valid_until"],
            "invalidated_at": invalidated_at,
            "invalidated_by_structure_point_id": row["invalidated_by_structure_point_id"] if invalidated_at else None,
            "detected_at": row["detected_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "weight": float(row["effective_weight"]),
            "confidence": float(row["effective_confidence"]),
            "metadata": metadata,
            }
        )
    return zones


def attach_liquidity_sweep_states(conn: Connection, zones: list[dict[str, Any]]) -> None:
    """Attach every account-scoped runtime state for dashboard inspection."""
    liquidity_zone_ids = [zone["id"] for zone in zones if zone["type"] == "liquidity_pool"]
    if not liquidity_zone_ids:
        return
    placeholders = ",".join("?" for _ in liquidity_zone_ids)
    rows = conn.execute(
        f"""
        SELECT * FROM liquidity_sweep_states
        WHERE zone_id IN ({placeholders})
        ORDER BY updated_at DESC
        """,
        liquidity_zone_ids,
    ).fetchall()
    states_by_zone: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        row_keys = set(row.keys())
        touched_edge_at = row["touched_edge_at"] if "touched_edge_at" in row_keys else row["touched_lower_at"]
        extreme_price = row["extreme_price"] if "extreme_price" in row_keys else row["deepest_bid"]
        state = {
            "account_label": row["account_label"],
            "state": row["state"],
            "trade_direction": row["trade_direction"] if "trade_direction" in row_keys else "long",
            "touched_edge_at": touched_edge_at,
            "touched_lower_at": row["touched_lower_at"],
            "deadline_at": row["deadline_at"],
            "atr_at_touch": row["atr_at_touch"],
            "extreme_price": extreme_price,
            "deepest_bid": row["deepest_bid"],
            "invalidation_price": row["invalidation_price"],
            "reclaimed_at": row["reclaimed_at"],
            "terminal_reason": row["terminal_reason"],
            "updated_at": row["updated_at"],
        }
        states_by_zone.setdefault(str(row["zone_id"]), []).append(state)
    for zone in zones:
        states = states_by_zone.get(str(zone["id"]), [])
        if not states:
            continue
        zone["metadata"]["liquidity_sweep_states"] = states
        # Backward-compatible summary for older frontends.
        zone["metadata"]["liquidity_sweep_state"] = states[0]


def project_zone_lifecycle_for_chart(
    row: Any,
    metadata: dict[str, Any],
    range_end: str,
    *,
    is_bot_sr: bool,
) -> dict[str, str | None]:
    """Project persisted lifecycle fields into chart-only presentation values.

    `end_time` is exposed as `visual_end`; strategy code must use status,
    valid_until, and invalidated_at instead of this projection.
    """
    status = str(row["status"])
    visual_end = row["end_time"]
    invalidated_at = row["invalidated_at"]
    deterministic_expiry = metadata.get("expired_rule") == "smc_zone_max_active_days" or (
        metadata.get("max_active_days") is not None and row["valid_until"] == row["end_time"]
    )
    if (
        status != "draft"
        and row["end_time"] is not None
        and row["end_time"] > range_end
        and not deterministic_expiry
    ):
        # A historical chart window may predate the lifecycle event persisted
        # today. At that point in time the zone was still active.
        status = "active"
        invalidated_at = None
        is_human_zone = row["source"] == "human" or metadata.get("human_created") is True
        if is_human_zone:
            visual_end = row["end_time"]
        elif is_bot_sr:
            visual_end = row["valid_until"] or row["end_time"]
        else:
            visual_end = None
    return {
        "status": status,
        "visual_end": visual_end,
        "invalidated_at": invalidated_at,
    }


def merge_zones_by_id(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for zone in group:
            zone_id = str(zone.get("id") or "")
            if zone_id and zone_id in seen:
                continue
            if zone_id:
                seen.add(zone_id)
            merged.append(zone)
    return merged


def build_m15_trigger_overlays(
    conn: Connection,
    symbol: str,
    chart_timeframe: str,
    context_timeframe: str,
    range_start: str,
    range_end: str,
    zones: list[dict[str, Any]],
    setup_candidates: list[dict[str, Any]],
    include_live_candle: bool = False,
) -> list[dict[str, Any]]:
    if chart_timeframe.upper() != context_timeframe.upper() or context_timeframe.upper() != "H1":
        return []
    if not zones:
        return []

    candidates_by_zone_time: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in setup_candidates:
        zone_id = str(candidate.get("primary_zone_id") or "")
        metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        reaction_time = str(metadata.get("reaction_candle_time") or "")
        if zone_id and reaction_time:
            candidates_by_zone_time[(zone_id, reaction_time)] = candidate

    candles = load_chart_candles(conn, symbol, "M15", 5000, start=range_start, end=range_end)
    # In latest mode the still-forming M15 candle is the one most likely to be
    # touching a zone a human just drew, so include it for immediate feedback —
    # otherwise the marker only appears once that M15 candle closes.
    if include_live_candle:
        live_candle = load_live_candle(conn, symbol, "M15")
        if live_candle is not None and (not candles or live_candle["time"] > candles[-1]["time"]):
            candles = [*candles, live_candle]
    candidate_overlays: list[dict[str, Any]] = []
    touch_overlays: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for candle in candles:
        high = float(candle["high"])
        low = float(candle["low"])
        for zone in zones:
            zone_id = str(zone.get("id") or "")
            if not zone_id:
                continue
            if high < float(zone["price_low"]) or low > float(zone["price_high"]):
                continue
            key = (zone_id, str(candle["time"]))
            if key in seen:
                continue
            seen.add(key)
            candidate = candidates_by_zone_time.get(key)
            metadata = candidate.get("metadata", {}) if candidate else {}
            overlay = {
                "time": candle["time"],
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "zone_id": zone_id,
                "zone_type": zone.get("type"),
                "reaction_state": candidate.get("zone_reaction_state") if candidate else "touch",
                "candidate_id": candidate.get("id") if candidate else None,
                "status": candidate.get("status") if candidate else "touch",
                "reason": list(candidate.get("reason") or [])[:3] if candidate else ["M15 candle touched H1 zone."],
                "direction": candidate.get("direction") if candidate else zone.get("direction"),
                "metadata": {
                    "reaction_open": metadata.get("reaction_open"),
                    "reaction_high": metadata.get("reaction_high"),
                    "reaction_low": metadata.get("reaction_low"),
                    "reaction_close": metadata.get("reaction_close"),
                    "trigger_types": metadata.get("trigger_types"),
                },
            }
            if candidate:
                candidate_overlays.append(overlay)
            else:
                touch_overlays.append(overlay)
    capped_touch_overlays = touch_overlays[-MAX_TOUCH_ONLY_M15_TRIGGER_OVERLAYS:]
    return sorted(
        [*capped_touch_overlays, *candidate_overlays],
        key=lambda item: (str(item.get("time") or ""), str(item.get("zone_id") or "")),
    )


def load_chart_contexts(conn: Connection, symbol: str, as_of: str | None = None) -> dict[str, dict[str, dict[str, Any]]]:
    as_of_iso = as_of or datetime.now(UTC).replace(microsecond=0).isoformat()
    rows = conn.execute(
        """
        SELECT timeframe, context_type, bot_value, primary_value, secondary_value,
               bot_confidence, effective_value, effective_confidence, source,
               valid_from, valid_until, status, metadata_json
        FROM market_contexts
        WHERE symbol = ?
          AND status = 'active'
          AND (valid_until IS NULL OR valid_until > ?)
        ORDER BY timeframe, context_type,
                 CASE source WHEN 'bot' THEN 0 WHEN 'human' THEN 1 WHEN 'news_calendar' THEN 2 ELSE 1 END
        """,
        (symbol, as_of_iso),
    ).fetchall()
    contexts: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        timeframe_contexts = contexts.setdefault(row["timeframe"], {})
        timeframe_contexts[row["context_type"]] = {
            "bot_value": row["bot_value"],
            "primary_value": row["primary_value"],
            "secondary_value": row["secondary_value"],
            "bot_confidence": float(row["bot_confidence"]),
            "effective_value": row["effective_value"],
            "effective_confidence": float(row["effective_confidence"]),
            "source": row["source"],
            "valid_from": row["valid_from"],
            "valid_until": row["valid_until"],
            "status": row["status"],
            "metadata": json_loads(row["metadata_json"], {}),
        }
    return contexts


def load_chart_trades(
    conn: Connection,
    symbol: str,
    start: str,
    end: str,
    allowed_playbooks: set[str] | None = None,
) -> list[dict[str, Any]]:
    playbook_clause = ""
    params: list[Any] = [symbol, end, start]
    if allowed_playbooks is not None:
        if not allowed_playbooks:
            return []
        placeholders = ", ".join("?" for _ in allowed_playbooks)
        playbook_clause = f" AND trade_ideas.playbook IN ({placeholders})"
        params.extend(sorted(allowed_playbooks))

    rows = conn.execute(
        f"""
        SELECT trade_orders.id, trade_orders.trade_idea_id, trade_orders.side,
               trade_orders.account_label,
               trade_orders.order_type, trade_orders.status, trade_orders.entry_price,
               trade_orders.stop_loss, trade_orders.take_profit_json,
               trade_orders.quantity, trade_orders.opened_at, trade_orders.closed_at,
               trade_orders.close_price, trade_orders.pnl, trade_orders.pnl_r,
               trade_orders.hidden_on_chart, trade_orders.source, trade_orders.metadata_json,
               trade_ideas.playbook, trade_ideas.direction,
               COALESCE(
                   (
                       SELECT manual_ai_plans.client_id
                       FROM manual_ai_plans
                       WHERE manual_ai_plans.trade_idea_id = trade_orders.trade_idea_id
                       ORDER BY manual_ai_plans.created_at DESC
                       LIMIT 1
                   ),
                   (
                       SELECT COALESCE(line_reaction_plans.client_group_id, line_reaction_plans.id)
                       FROM line_reaction_plans
                       WHERE trade_ideas.playbook = 'line_reaction_v1'
                         AND line_reaction_plans.id = json_extract(trade_orders.metadata_json, '$.candidate_id')
                       LIMIT 1
                   )
               ) AS execution_group_id,
               trade_reviews.id AS review_id,
               trade_reviews.grade AS review_grade,
               trade_reviews.verdict AS review_verdict,
               trade_reviews.mistake_tags_json AS review_mistake_tags_json,
               trade_reviews.should_trade_again AS review_should_trade_again,
               trade_reviews.comment AS review_comment,
               trade_reviews.metadata_json AS review_metadata_json,
               trade_reviews.reviewer AS review_reviewer,
               trade_reviews.created_at AS review_created_at,
               trade_reviews.updated_at AS review_updated_at
        FROM trade_orders
        JOIN trade_ideas ON trade_ideas.id = trade_orders.trade_idea_id
        LEFT JOIN trade_reviews ON trade_reviews.trade_order_id = trade_orders.id
        WHERE trade_orders.symbol = ?
          AND trade_orders.opened_at IS NOT NULL
          AND trade_orders.status IN ('filled', 'closed', 'target_hit', 'stopped', 'time_exit')
          AND trade_orders.opened_at <= ?
          AND (trade_orders.closed_at IS NULL OR trade_orders.closed_at >= ?)
          {playbook_clause}
        ORDER BY COALESCE(trade_orders.opened_at, trade_orders.created_at)
        """,
        params,
    ).fetchall()
    return [trade_order_row_to_chart(row) for row in rows]


def load_live_traded_candidate_refs(
    conn: Connection,
    symbol: str,
    account_label: str | None = None,
) -> tuple[set[str], set[str]]:
    account_clause = ""
    params: list[Any] = [symbol]
    if account_label is not None:
        account_clause = " AND trade_orders.account_label = ?"
        params.append(account_label)
    rows = conn.execute(
        f"""
        SELECT trade_orders.metadata_json, trade_ideas.context_snapshot_json
        FROM trade_orders
        JOIN trade_ideas ON trade_ideas.id = trade_orders.trade_idea_id
        WHERE trade_orders.symbol = ?
          AND trade_orders.source = 'live'
          AND trade_orders.status IN ('filled', 'pending_fill')
          {account_clause}
        """,
        params,
    ).fetchall()
    candidate_ids: set[str] = set()
    zone_ids: set[str] = set()
    for row in rows:
        metadata = json_loads(row["metadata_json"], {})
        candidate_id = metadata.get("candidate_id")
        if candidate_id:
            candidate_ids.add(str(candidate_id))
        candidate_metadata = metadata.get("candidate_metadata")
        if isinstance(candidate_metadata, dict):
            zone_id = candidate_metadata.get("primary_zone_id")
            if zone_id:
                zone_ids.add(str(zone_id))
        snapshot = json_loads(row["context_snapshot_json"], {})
        candidate = snapshot.get("candidate")
        if isinstance(candidate, dict):
            snapshot_candidate_id = candidate.get("id")
            if snapshot_candidate_id:
                candidate_ids.add(str(snapshot_candidate_id))
            snapshot_zone_id = candidate.get("primary_zone_id")
            if snapshot_zone_id:
                zone_ids.add(str(snapshot_zone_id))
    return candidate_ids, zone_ids


def filter_traded_setup_candidates(
    conn: Connection,
    symbol: str,
    candidates: list[dict[str, Any]],
    account_label: str | None = None,
) -> list[dict[str, Any]]:
    if not candidates:
        return candidates
    traded_candidate_ids, traded_zone_ids = load_live_traded_candidate_refs(conn, symbol, account_label=account_label)
    if not traded_candidate_ids and not traded_zone_ids:
        return candidates
    return [
        candidate
        for candidate in candidates
        if str(candidate.get("id")) not in traded_candidate_ids
        and str(candidate.get("primary_zone_id")) not in traded_zone_ids
    ]


def trade_order_row_to_chart(row: Any) -> dict[str, Any]:
    metadata = json_loads(row["metadata_json"], {})
    if not isinstance(metadata, dict):
        metadata = {}
    candidate_metadata = metadata.get("candidate_metadata")
    quick_order_group_id = (
        candidate_metadata.get("quick_order_group_id")
        if isinstance(candidate_metadata, dict)
        else None
    )
    if row_has_key(row, "execution_group_id") and row["execution_group_id"]:
        metadata["execution_group_id"] = str(row["execution_group_id"])
    elif quick_order_group_id:
        # A single Quick Order request fans out into one trade per account.
        # Preserve its client_group_id so chart/history review groups those
        # executions as one discretionary decision.
        metadata["execution_group_id"] = str(quick_order_group_id)
    elif metadata.get("candidate_id"):
        # Live bot orders share the same candidate across account workers. Expose
        # that stable identity so review UIs can treat the executions as one setup.
        metadata["execution_group_id"] = str(metadata["candidate_id"])
    result = {
        "id": row["id"],
        "trade_idea_id": row["trade_idea_id"],
        "account_label": row["account_label"] if row_has_key(row, "account_label") else "Default",
        "playbook": row["playbook"],
        "direction": row["direction"],
        "side": row["side"],
        "order_type": row["order_type"],
        "status": row["status"],
        "entry_price": float(row["entry_price"]) if row["entry_price"] is not None else None,
        "stop_loss": float(row["stop_loss"]) if row["stop_loss"] is not None else None,
        "take_profit": json_loads(row["take_profit_json"], []),
        "quantity": float(row["quantity"]),
        "opened_at": row["opened_at"],
        "closed_at": row["closed_at"],
        "close_price": float(row["close_price"]) if row["close_price"] is not None else None,
        "pnl": float(row["pnl"]) if row["pnl"] is not None else None,
        "pnl_r": float(row["pnl_r"]) if row["pnl_r"] is not None else None,
        "hidden_on_chart": bool(row["hidden_on_chart"]) if row_has_key(row, "hidden_on_chart") else False,
        "source": row["source"],
        "metadata": metadata,
    }
    if row_has_key(row, "manual_ai_plan_status"):
        result["manual_ai_plan_status"] = row["manual_ai_plan_status"]
    if row_has_key(row, "manual_ai_expires_at"):
        result["manual_ai_expires_at"] = row["manual_ai_expires_at"]
    if row_has_key(row, "review_id") and row["review_id"] is not None:
        review_metadata = json_loads(row["review_metadata_json"], {}) if row_has_key(row, "review_metadata_json") else {}
        if not isinstance(review_metadata, dict):
            review_metadata = {}
        strategy_review = review_metadata.get("strategy_review") if isinstance(review_metadata.get("strategy_review"), dict) else {}
        operator_review = review_metadata.get("operator_review") if isinstance(review_metadata.get("operator_review"), dict) else {}
        review_metadata = {**review_metadata, "strategy_review": strategy_review, "operator_review": operator_review}
        result["review"] = {
            "id": row["review_id"],
            "trade_order_id": row["id"],
            "grade": row["review_grade"],
            "verdict": row["review_verdict"],
            "mistake_tags": json_loads(row["review_mistake_tags_json"], []),
            "should_trade_again": row["review_should_trade_again"],
            "comment": row["review_comment"] or "",
            "reviewer": row["review_reviewer"],
            "created_at": row["review_created_at"],
            "updated_at": row["review_updated_at"],
            "metadata": review_metadata,
            "strategy_review": strategy_review,
            "operator_review": operator_review,
        }
    else:
        result["review"] = None
    return result


def row_has_key(row: Any, key: str) -> bool:
    if hasattr(row, "keys"):
        return key in row.keys()
    return key in row


def build_chart_payload(
    conn: Connection,
    symbol: str,
    timeframe: str,
    limit: int,
    start: str | None = None,
    end: str | None = None,
    start_index: int | None = None,
    active_zones_only: bool = False,
    structure_timeframe: str | None = None,
    strategy_config: Any | None = None,
    candidate_zone_timeframes: set[str] | None = None,
    allowed_playbooks: set[str] | None = None,
    macro_trend_config: Any | None = None,
    include_live_strategy_candle: bool = False,
    traded_account_label: str | None = None,
) -> dict[str, Any]:
    candles = load_chart_candles(conn, symbol, timeframe, limit, start, end, start_index)
    if not candles:
        raise ValueError(f"No candles found for {symbol} {timeframe}")

    # In latest mode (no historical window), append the forming candle from live_candles
    # so the UI always shows the in-progress bar even before it closes.
    is_latest_mode = start_index is None and start is None and end is None
    if is_latest_mode:
        live_candle = load_live_candle(conn, symbol, timeframe)
        if live_candle is not None and live_candle["time"] > candles[-1]["time"]:
            candles = [*candles, live_candle]

    range_start = candles[0]["time"]
    range_end = candles[-1]["time"]
    effective_structure_timeframe = structure_timeframe or "H1"
    zones = load_chart_zones(conn, symbol, effective_structure_timeframe, range_start, range_end, active_only=active_zones_only)
    if is_latest_mode:
        attach_liquidity_sweep_states(conn, zones)
    context_as_of = None if is_latest_mode else range_end
    contexts = load_chart_contexts(conn, symbol, as_of=context_as_of)
    if macro_trend_config is not None:
        macro_timeframe = str(macro_trend_config.timeframe)
        # Persisted contexts (including human overrides) win; the live value is a fallback.
        if "macro_trend" not in contexts.get(macro_timeframe, {}):
            live_macro = compute_live_macro_trend_context(conn, symbol, macro_trend_config)
            if live_macro is not None:
                contexts.setdefault(macro_timeframe, {})["macro_trend"] = live_macro
    strategy_end = None if is_latest_mode else range_end
    strategy_timeframe = str(strategy_config.timeframe) if strategy_config is not None else "M15"
    closed_strategy_candles = load_chart_candles(conn, symbol, strategy_timeframe, 240, end=strategy_end)
    strategy_candles = list(closed_strategy_candles)
    raw_setup_candidates: list[dict[str, Any]] = []
    setup_candidates: list[dict[str, Any]] = []
    if strategy_config is not None:
        zone_groups_by_timeframe: dict[str, list[dict[str, Any]]] = {effective_structure_timeframe: zones}
        # H1 is the only zone/context timeframe. M15 remains the strategy
        # trigger timeframe, but it must never contribute price_zones.
        candidate_timeframes = candidate_zone_timeframes or {effective_structure_timeframe}
        for zone_timeframe in sorted(candidate_timeframes):
            if zone_timeframe not in zone_groups_by_timeframe:
                zone_groups_by_timeframe[zone_timeframe] = load_chart_zones(
                    conn,
                    symbol,
                    zone_timeframe,
                    range_start,
                    range_end,
                    active_only=active_zones_only,
                )
        candidate_zones = merge_zones_by_id(
            *[zone_groups_by_timeframe[zone_timeframe] for zone_timeframe in sorted(candidate_timeframes)]
        )
        # Latest chart mode should evaluate setup candidates from the latest closed
        # strategy candle, not from the H1 chart range end. Otherwise M15 touches
        # after the current H1 candle opens are invisible until the next H1 close.
        if include_live_strategy_candle and is_latest_mode:
            live_strategy_candle = load_live_candle(conn, symbol, strategy_config.timeframe)
            if live_strategy_candle is not None and (
                not strategy_candles or live_strategy_candle["time"] > strategy_candles[-1]["time"]
            ):
                strategy_candles = [*strategy_candles, live_strategy_candle]
        context_candles = load_chart_candles(conn, symbol, effective_structure_timeframe, 240, end=range_end)
        if strategy_candles:
            raw_setup_candidates = build_setup_candidates(
                symbol=symbol,
                zones=candidate_zones,
                contexts=contexts,
                candles=strategy_candles,
                structure_points=load_chart_structure(
                    conn,
                    symbol,
                    strategy_config.timeframe,
                    strategy_candles[0]["time"],
                    strategy_candles[-1]["time"],
                ),
                config=strategy_config,
                context_timeframe=effective_structure_timeframe,
                allowed_playbooks=allowed_playbooks,
                context_candles=context_candles,
            )
            setup_candidates = filter_traded_setup_candidates(
                conn,
                symbol,
                raw_setup_candidates,
                account_label=traded_account_label,
            )
    if is_latest_mode:
        setup_candidates = [
            *setup_candidates,
            *load_manual_ai_setup_candidates(
                conn,
                symbol,
                allowed_playbooks,
                datetime.now(UTC).isoformat(),
                int(getattr(strategy_config, "h1_impulse_retest_v1_max_signal_age_hours", 48)),
            ),
            *load_quick_order_setup_candidates(conn, symbol, allowed_playbooks),
        ]
    avg_body_period = (
        int(getattr(strategy_config, "zone_reaction_v2_reject_avg_body_period", 20))
        if strategy_config is not None
        else 20
    )
    m15_signal = build_m15_signal_snapshot(
        closed_strategy_candles,
        raw_setup_candidates,
        avg_body_period=avg_body_period,
    )
    m15_triggers = build_m15_trigger_overlays(
        conn,
        symbol,
        timeframe,
        effective_structure_timeframe,
        range_start,
        range_end,
        zones,
        setup_candidates,
        include_live_candle=is_latest_mode,
    )
    chart_structure = load_chart_structure(conn, symbol, effective_structure_timeframe, range_start, range_end)
    wave_candles = load_chart_candles(conn, symbol, effective_structure_timeframe, 500, end=range_end)
    return {
        "version": CHART_PAYLOAD_VERSION,
        "symbol": symbol,
        "timeframe": timeframe,
        "range": {
            "start": range_start,
            "end": range_end,
            "limit": limit,
            "start_index": start_index,
            "requested_start": start,
            "requested_end": end,
        },
        "layers": {
            "candles": candles,
            "structure": chart_structure,
            "structure_timeframe": effective_structure_timeframe,
            "wave_metrics": build_wave_metrics(chart_structure, wave_candles, as_of=range_end),
            "zones": zones,
            "contexts": contexts,
            "atr": build_atr_snapshot(conn, symbol, ["H1", "M15"], period=14, end=range_end),
            "rsi": build_rsi_snapshot(conn, symbol, ["H1"], period=14, end=range_end),
            "trades": load_chart_trades(conn, symbol, range_start, range_end, allowed_playbooks=allowed_playbooks),
            "setup_candidates": setup_candidates,
            "h1_impulse_markers": build_h1_impulse_marker_layer(
                conn,
                symbol,
                timeframe,
                candles,
                strategy_config,
            ),
            "m15_triggers": m15_triggers,
            "m15_signal": m15_signal,
            "intraday_map": build_intraday_map(
                conn,
                symbol,
                (
                    str(closed_strategy_candles[-1]["close_time"])
                    if is_latest_mode and closed_strategy_candles
                    else str(candles[-1]["close_time"])
                ),
            ),
        },
    }
