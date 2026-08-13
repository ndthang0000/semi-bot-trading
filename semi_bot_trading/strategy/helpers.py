from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..config import StrategyConfig
from ..zones import CandleSlice, latest_atr  # noqa: F401 – re-exported for builder
from .types import (
    BEARISH_BREAKS,
    BEARISH_PA,
    BULLISH_BREAKS,
    BULLISH_PA,
    DEFAULT_TRADE_MODES_BY_ZONE_TYPE,
    PLAYBOOK_ZONE_TYPES,
    TRADE_MODES,
    ReactionResult,
    RecoveryMetrics,
)


# ---------------------------------------------------------------------------
# Reaction constructors
# ---------------------------------------------------------------------------

def reaction(
    state: str,
    direction: str | None,
    touched: bool,
    candle: dict[str, Any],
    reason: list[str],
    buffer: float,
) -> ReactionResult:
    return ReactionResult(
        state=state,
        direction=direction,
        touched=touched,
        candle_time=str(candle.get("time")),
        reason=reason,
        metadata={"reaction_candle_time": candle.get("time"), "breakout_buffer": round(buffer, 5)},
    )


def reaction_v2(
    state: str,
    direction: str | None,
    touched: bool,
    candle: dict[str, Any],
    reason: list[str],
    buffer: float,
    metadata: dict[str, Any] | None = None,
) -> ReactionResult:
    base: dict[str, Any] = {
        "reaction_candle_time": candle.get("time"),
        "breakout_buffer": round(buffer, 5),
        "reaction_v2": state,
        "reaction_open": candle.get("open"),
        "reaction_high": candle.get("high"),
        "reaction_low": candle.get("low"),
        "reaction_close": candle.get("close"),
        "reaction_body": round(candle_body(candle), 5) if candle else 0.0,
    }
    if metadata:
        base.update(metadata)
    return ReactionResult(
        state=state,
        direction=direction,
        touched=touched,
        candle_time=str(candle.get("time")),
        reason=reason,
        metadata=base,
    )


# ---------------------------------------------------------------------------
# Candle utilities
# ---------------------------------------------------------------------------

def candle_body(candle: dict[str, Any]) -> float:
    return abs(float(candle.get("close", 0.0)) - float(candle.get("open", 0.0)))


def average_body(candles: list[dict[str, Any]], period: int) -> float:
    window = candles[-max(period, 1):]
    bodies = [candle_body(candle) for candle in window]
    return sum(bodies) / len(bodies) if bodies else 0.0


def close_extreme_recovery_metrics(
    candles: list[dict[str, Any]],
    direction: str,
    period: int,
    minimum_ratio: float,
) -> RecoveryMetrics:
    """Measure trigger close-to-extreme recovery against preceding M15 bodies."""
    normalized_period = max(period, 1)
    trigger = candles[-1]
    baseline = candles[:-1][-normalized_period:]
    ready = len(baseline) == normalized_period
    average = average_body(baseline, normalized_period) if ready else 0.0
    close = float(trigger["close"])
    size = close - float(trigger["low"]) if direction == "long" else float(trigger["high"]) - close
    ratio = size / average if average > 0 else 0.0
    return RecoveryMetrics(
        size=size,
        ratio=ratio,
        average_body=average,
        period=normalized_period,
        sample_count=len(baseline),
        ready=ready,
        minimum_ratio=minimum_ratio,
    )


def chart_candles_to_slices(candles: list[dict[str, Any]]) -> list[CandleSlice]:
    return [
        CandleSlice(
            open_time=str(candle["time"]),
            open=float(candle["open"]),
            high=float(candle["high"]),
            low=float(candle["low"]),
            close=float(candle["close"]),
        )
        for candle in candles
    ]


def latest_range(candles: list[dict[str, Any]]) -> float | None:
    if not candles:
        return None
    candle = candles[-1]
    return float(candle["high"]) - float(candle["low"])


# ---------------------------------------------------------------------------
# Zone utilities
# ---------------------------------------------------------------------------

def zone_trade_modes(zone: dict[str, Any]) -> list[str]:
    metadata = zone.get("metadata") if isinstance(zone.get("metadata"), dict) else {}
    raw = metadata.get("trade_modes")
    if isinstance(raw, list):
        # An explicit empty list means human disabled all trade modes for this
        # zone; only fall back to defaults when metadata has no trade_modes key.
        modes = [str(item) for item in raw if str(item) in TRADE_MODES]
        return modes
    return list(DEFAULT_TRADE_MODES_BY_ZONE_TYPE.get(str(zone.get("type")), ()))


def zone_has_explicit_trade_mode(zone: dict[str, Any], mode: str) -> bool:
    metadata = zone.get("metadata") if isinstance(zone.get("metadata"), dict) else {}
    raw = metadata.get("trade_modes")
    return isinstance(raw, list) and mode in {str(item) for item in raw}


def zone_is_human_thesis(zone: dict[str, Any]) -> bool:
    metadata = zone.get("metadata") if isinstance(zone.get("metadata"), dict) else {}
    return (
        str(zone.get("source")) in {"human", "mixed"}
        or metadata.get("human_created") is True
        or metadata.get("human_adjusted") is True
    )


def parse_utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def zone_human_activation_time(zone: dict[str, Any]) -> datetime | None:
    if not zone_is_human_thesis(zone):
        return None
    return parse_utc_datetime(zone.get("created_at"))


def zone_can_use_signal_candle(zone: dict[str, Any], candle: dict[str, Any]) -> bool:
    activation_time = zone_human_activation_time(zone)
    if activation_time is None:
        return True
    candle_time = parse_utc_datetime(candle.get("time"))
    if candle_time is None:
        return True
    return candle_time >= activation_time


def zone_allows_breakout(zone: dict[str, Any], config: StrategyConfig) -> bool:
    if zone_has_explicit_trade_mode(zone, "breakout"):
        return True
    return bool(config.sr_breakout_v1_allow_bot_sr_breakout and str(zone.get("source")) == "bot")


def zone_trade_disabled_after_sweep(zone: dict[str, Any]) -> bool:
    metadata = zone.get("metadata")
    return bool(isinstance(metadata, dict) and metadata.get("trade_disabled_after_sweep"))


def zone_valid_at(zone: dict[str, Any], as_of: str) -> bool:
    valid_until = zone.get("valid_until")
    # SR zones generated in point-in-time backtests do not carry a fixed
    # expiry; lifecycle status is the source of truth for whether they are
    # still tradeable. FVG/OB zones usually have valid_until because their
    # expiry/mitigation window is time-bounded.
    if valid_until in (None, ""):
        return True
    return isinstance(valid_until, str) and valid_until > as_of


def zone_eligible_for_zone_reaction_v2(
    zone: dict[str, Any],
    candles: list[dict[str, Any]],
    config: StrategyConfig,
) -> bool:
    if not candles:
        return False
    status = str(zone.get("status"))
    zone_type = str(zone.get("type"))
    if status == "active":
        return zone_valid_at(zone, str(candles[-1]["time"]))
    if status != "mitigated" or zone_type != "fvg":
        return False
    if not config.zone_reaction_v2_internal_reject_enabled:
        return False
    fill_ratio = zone_fill_ratio(zone, candles[-1] if candles else None)
    if fill_ratio < config.zone_reaction_v2_internal_reject_min_fill_ratio:
        return False
    # visual_end is presentation geometry and must never decide strategy
    # eligibility. Persisted FVG lifecycle fields are the source of truth.
    fill_time = first_text(zone.get("invalidated_at"), zone.get("valid_until"))
    if not fill_time or not candles:
        return candle_touches_zone(candles[-1], zone) if candles else False
    lookback = max(config.zone_reaction_v2_internal_reject_watch_after_fvg_fill_bars, 1)
    watch_start = str(candles[max(0, len(candles) - lookback - 1)]["time"])
    current_time = str(candles[-1]["time"])
    return watch_start <= str(fill_time) <= current_time


def zone_eligible_for_sr_breakout_v1(
    zone: dict[str, Any],
    candles: list[dict[str, Any]],
    config: StrategyConfig,
) -> bool:
    if candles and str(zone.get("status")) == "active" and not zone_valid_at(zone, str(candles[-1]["time"])):
        return False
    if str(zone.get("type")) not in PLAYBOOK_ZONE_TYPES["sr_breakout_v1"]:
        return False
    if not zone_allows_breakout(zone, config):
        return False
    status = str(zone.get("status"))
    if status == "active":
        return True
    # The H1 candle that confirms a breakout is usually the same candle that
    # makes zone lifecycle mark the zone invalidated, so the playbook would race
    # its own zone and lose. Recently-invalidated SR zones therefore stay
    # tradeable for the breakout/retest window.
    if status != "invalidated":
        return False
    invalidated_at = str(zone.get("invalidated_at") or "")
    if not invalidated_at or not candles:
        return False
    window = candles[-(config.sr_breakout_v1_retest_max_bars + 1):]
    return invalidated_at >= str(window[0]["time"])


def allowed_zone_types_for_playbooks(allowed_playbooks: set[str] | None) -> set[str]:
    playbooks = set(PLAYBOOK_ZONE_TYPES) if allowed_playbooks is None else allowed_playbooks
    zone_types: set[str] = set()
    for playbook in playbooks:
        zone_types.update(PLAYBOOK_ZONE_TYPES.get(playbook, set()))
    return zone_types


def playbook_allowed(playbook: str, allowed_playbooks: set[str] | None) -> bool:
    return allowed_playbooks is None or playbook in allowed_playbooks


def zone_mid(zone: dict[str, Any]) -> float:
    return (float(zone["price_low"]) + float(zone["price_high"])) / 2


def zone_width_atr_ratio(zone: dict[str, Any], atr: float) -> float:
    return (float(zone["price_high"]) - float(zone["price_low"])) / max(atr, 0.00001)


def zone_touch_count(zone: dict[str, Any]) -> int | None:
    metadata = zone.get("metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("touch_count_total", metadata.get("touch_count"))
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Candle / zone geometry
# ---------------------------------------------------------------------------

def close_inside_zone(candle: dict[str, Any], zone: dict[str, Any]) -> bool:
    close = float(candle["close"])
    return float(zone["price_low"]) <= close <= float(zone["price_high"])


def candle_touches_zone(candle: dict[str, Any], zone: dict[str, Any]) -> bool:
    return float(candle["high"]) >= float(zone["price_low"]) and float(candle["low"]) <= float(zone["price_high"])


def inside_zone_close_position(candle: dict[str, Any], zone: dict[str, Any]) -> float:
    width = max(float(zone["price_high"]) - float(zone["price_low"]), 0.00001)
    position = (float(candle["close"]) - float(zone["price_low"])) / width
    return min(max(position, 0.0), 1.0)


def zone_fill_ratio(zone: dict[str, Any], candle: dict[str, Any] | None = None) -> float:
    """Return directional fill through a zone as a normalized 0..1 ratio.

    SR and FVG internal rejects intentionally share this geometry. Persisted
    fill state is only carried forward for FVG lifecycle handling; an SR signal
    is measured from its current reaction candle.
    """
    metadata = zone.get("metadata") if isinstance(zone.get("metadata"), dict) else {}
    value = metadata.get("fill_ratio") if str(zone.get("type")) == "fvg" else None
    try:
        stored = float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        stored = 0.0
    if candle is None:
        return min(max(stored, 0.0), 1.0)

    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    width = max(zone_high - zone_low, 0.00001)
    if str(zone.get("direction")) == "bullish":
        current = (zone_high - max(float(candle["low"]), zone_low)) / width if float(candle["low"]) < zone_high else 0.0
    else:
        current = (min(float(candle["high"]), zone_high) - zone_low) / width if float(candle["high"]) > zone_low else 0.0
    return min(max(max(stored, current), 0.0), 1.0)


def internal_reject_window_metadata(candles: list[dict[str, Any]], config: StrategyConfig) -> dict[str, Any]:
    lookback = max(config.zone_reaction_v2_internal_reject_watch_after_fvg_fill_bars, 1)
    start_index = max(0, len(candles) - lookback)
    return {
        "internal_reject_trigger_window_start": candles[start_index].get("time"),
    }


# ---------------------------------------------------------------------------
# Trigger / structure point utilities
# ---------------------------------------------------------------------------

def trigger_points_for_direction(
    points: list[dict[str, Any]],
    direction: str,
    as_of: str,
    not_before: str | None = None,
    trigger_kind: str | None = None,
) -> list[str]:
    wanted = BULLISH_PA if direction == "long" else BEARISH_PA
    wanted_break_direction = "up" if direction == "long" else "down"
    result: list[str] = []
    for point in reversed(points[-40:]):
        point_time = str(point.get("time"))
        if point_time > as_of:
            continue
        if not_before is not None and point_time < not_before:
            continue
        point_type = str(point.get("type"))
        metadata = point.get("metadata") if isinstance(point.get("metadata"), dict) else {}
        if trigger_kind in {None, "price_action"} and point_type in wanted:
            result.append(str(point.get("id")))
        elif (
            trigger_kind in {None, "structure"}
            and point_type in (BULLISH_BREAKS if direction == "long" else BEARISH_BREAKS)
            and metadata.get("direction") == wanted_break_direction
        ):
            result.append(str(point.get("id")))
        if len(result) >= 3:
            break
    return list(reversed(result))


def trigger_types_for_ids(points: list[dict[str, Any]], trigger_ids: list[str]) -> list[str]:
    point_by_id = {
        str(point.get("id")): str(point.get("point_type") or point.get("type") or "")
        for point in points
    }
    return [point_by_id[tid] for tid in trigger_ids if tid in point_by_id]


def unique_ids(point_ids: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for point_id in point_ids:
        if point_id in seen:
            continue
        seen.add(point_id)
        ordered.append(point_id)
    return ordered


# ---------------------------------------------------------------------------
# Context utilities
# ---------------------------------------------------------------------------

def status_rank(status: str) -> int:
    return {"eligible": 4, "waiting_confirmation": 3, "watching": 2, "blocked": 1, "expired": 0}.get(status, 0)


def expected_trade_direction(zone: dict[str, Any]) -> str:
    zone_type = str(zone.get("type"))
    direction = str(zone.get("direction"))
    if direction == "bullish" or zone_type == "support":
        return "long"
    if direction == "bearish" or zone_type == "resistance":
        return "short"
    return "neutral"


def bias_to_direction(bias: str) -> str:
    if bias == "bullish":
        return "long"
    if bias == "bearish":
        return "short"
    return "neutral"


def secondary_allows_direction(value: Any, direction: str) -> bool:
    if value is None:
        return False
    text = str(value).lower()
    return (direction == "long" and "bull" in text) or (direction == "short" and "bear" in text)


def parse_overlays(regime: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    secondary = regime.get("secondary_value")
    if isinstance(secondary, str):
        values.update(part.strip() for part in secondary.split(",") if part.strip())
    metadata = regime.get("metadata")
    if isinstance(metadata, dict):
        overlays = metadata.get("overlays")
        if isinstance(overlays, list):
            values.update(str(item) for item in overlays)
    return values


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def first_text(*values: Any) -> str | None:
    for value in values:
        if value is not None:
            return str(value)
    return None
