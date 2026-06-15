from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .config import StrategyConfig
from .zones import CandleSlice, latest_atr


BULLISH_PA = {"pinbar_bullish", "engulfing_bullish", "marubozu_bullish", "morning_star", "displacement_bullish"}
BEARISH_PA = {"pinbar_bearish", "engulfing_bearish", "marubozu_bearish", "evening_star", "displacement_bearish"}
BULLISH_BREAKS = {"BOS", "CHOCH"}
BEARISH_BREAKS = {"BOS", "CHOCH"}
PLAYBOOK_ZONE_TYPES: dict[str, set[str]] = {
    "zone_reaction_v2": {"support", "resistance", "fvg"},
    "sr_breakout_v1": {"support", "resistance"},
}
TRADE_MODES = {"reject", "internal_reject", "breakout"}
DEFAULT_TRADE_MODES_BY_ZONE_TYPE: dict[str, tuple[str, ...]] = {
    "support": ("reject","internal_reject"),
    "resistance": ("reject","internal_reject"),
    "fvg": ("reject", "internal_reject"),
    "consolidation": ("breakout",),
    "order_block": (),
}


@dataclass(frozen=True)
class ReactionResult:
    state: str
    direction: str | None
    touched: bool
    candle_time: str | None
    reason: list[str]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SetupCandidate:
    symbol: str
    timeframe: str
    playbook: str
    direction: str
    status: str
    zone_reaction_state: str
    score: float
    entry: float | None
    stop_loss: float | None
    take_profit: list[float]
    risk_reward: float | None
    primary_zone_id: str | None
    related_zone_ids: list[str]
    trigger_point_ids: list[str]
    reason: list[str]
    blocked_reason: list[str]
    expires_at: str | None
    metadata: dict[str, Any]

    @property
    def id(self) -> str:
        raw = (
            f"{self.symbol}|{self.timeframe}|{self.playbook}|{self.direction}|"
            f"{self.primary_zone_id}|{self.zone_reaction_state}|{self.metadata.get('as_of')}"
        )
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def to_chart(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "playbook": self.playbook,
            "direction": self.direction,
            "status": self.status,
            "zone_reaction_state": self.zone_reaction_state,
            "score": round(self.score, 4),
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_reward": self.risk_reward,
            "primary_zone_id": self.primary_zone_id,
            "related_zone_ids": self.related_zone_ids,
            "trigger_point_ids": self.trigger_point_ids,
            "reason": self.reason,
            "blocked_reason": self.blocked_reason,
            "expires_at": self.expires_at,
            "metadata": self.metadata,
        }


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
                    macro_trend=macro_trend_value,
                    bias=bias_value,
                    regime=regime_value,
                    config=config,
                )
            )

    if allowed_playbooks is not None:
        candidates = [candidate for candidate in candidates if candidate.playbook in allowed_playbooks]

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


def evaluate_zone_reaction_v2(
    symbol: str,
    zone: dict[str, Any],
    reaction: ReactionResult,
    last_close: float,
    atr: float,
    bias: str,
    secondary_bias: Any,
    regime: str,
    overlays: set[str],
    structure_points: list[dict[str, Any]],
    zones: list[dict[str, Any]],
    config: StrategyConfig,
    as_of: str,
    macro_trend: str = "unknown",
) -> list[SetupCandidate]:
    if not config.zone_reaction_v2_enabled:
        return []
    if str(zone.get("type")) not in PLAYBOOK_ZONE_TYPES["zone_reaction_v2"]:
        return []

    direction = reaction.direction
    if direction not in {"long", "short"}:
        return []

    # trade_modes governs which reaction families a zone may trade. Defaults come
    # from the zone type; an explicit human list both restricts the families and
    # bypasses every context gate (bias/regime/news/macro) for the ones it names.
    required_mode = "internal_reject" if reaction.state == "internal_reject" else "reject"
    if required_mode not in zone_trade_modes(zone):
        return []
    context_bypass = zone_has_explicit_trade_mode(zone, required_mode)

    trigger_ids = trigger_points_for_direction(structure_points, direction, as_of, not_before=reaction.candle_time)
    structure_trigger_ids = trigger_points_for_direction(
        structure_points,
        direction,
        as_of,
        not_before=reaction.candle_time,
        trigger_kind="structure",
    )
    price_action_trigger_ids = trigger_points_for_direction(
        structure_points,
        direction,
        as_of,
        not_before=reaction.candle_time,
        trigger_kind="price_action",
    )
    trigger_types = trigger_types_for_ids(structure_points, trigger_ids)
    structure_trigger_types = trigger_types_for_ids(structure_points, structure_trigger_ids)
    price_action_trigger_types = trigger_types_for_ids(structure_points, price_action_trigger_ids)

    # Internal reject reads a short reaction window inside wide zones. A BOS/CHOCH
    # and PA often do not print on the exact same M15 candle, but at least one of
    # them must be current so stale signals cannot promote every later candle.
    internal_window_start = str(reaction.metadata.get("internal_reject_trigger_window_start") or reaction.candle_time)
    recent_structure_trigger_ids = trigger_points_for_direction(
        structure_points,
        direction,
        as_of,
        not_before=internal_window_start,
        trigger_kind="structure",
    )
    recent_price_action_trigger_ids = trigger_points_for_direction(
        structure_points,
        direction,
        as_of,
        not_before=internal_window_start,
        trigger_kind="price_action",
    )
    current_has_internal_trigger = bool(structure_trigger_ids or price_action_trigger_ids)
    reaction = promote_internal_reject_if_confirmed(
        zone,
        reaction,
        atr,
        config,
        has_structure_trigger=bool(recent_structure_trigger_ids),
        has_price_action_trigger=bool(recent_price_action_trigger_ids),
        has_current_trigger=current_has_internal_trigger,
    )
    if reaction.state == "internal_reject":
        trigger_ids = unique_ids([*recent_structure_trigger_ids, *recent_price_action_trigger_ids])
        structure_trigger_ids = recent_structure_trigger_ids
        price_action_trigger_ids = recent_price_action_trigger_ids
        trigger_types = trigger_types_for_ids(structure_points, trigger_ids)
        structure_trigger_types = trigger_types_for_ids(structure_points, structure_trigger_ids)
        price_action_trigger_types = trigger_types_for_ids(structure_points, price_action_trigger_ids)
    confluence = zone_confluence_metadata(zone, zones, atr, config.zone_reaction_v2_confluence_score_bonus)
    status, blocked, reasons = zone_reaction_v2_status(
        direction,
        reaction,
        bool(trigger_ids),
        bias,
        secondary_bias,
        regime,
        config,
        has_structure_trigger=bool(structure_trigger_ids),
        has_price_action_trigger=bool(price_action_trigger_ids),
        macro_trend=macro_trend,
        context_bypass=context_bypass,
        zone_type=str(zone.get("type", "")),
    )
    entry, stop, take_profit, rr = compute_zone_reaction_v2_levels(zone, direction, reaction, last_close, atr, config)
    stop_distance = abs(entry - stop) if entry is not None and stop is not None else None
    if reaction.state != "approaching":
        # Approaching zones stay "watching": entry/stop are placeholders until the
        # first touch, so RR/stop-distance/blocked checks would only add noise.
        if rr is None or rr < config.zone_reaction_v2_rr_minimum:
            blocked.append(f"RR {rr or 0:.2f} is below Zone Reaction V2 minimum {config.zone_reaction_v2_rr_minimum:.2f}.")
            status = "blocked"
        if (
            stop_distance is not None
            and config.zone_reaction_v2_max_stop_distance > 0
            and stop_distance > config.zone_reaction_v2_max_stop_distance
        ):
            blocked.append(
                f"Stop distance {stop_distance:.2f} exceeds Zone Reaction V2 maximum "
                f"{config.zone_reaction_v2_max_stop_distance:.2f}."
            )
            status = "blocked"
        if blocked:
            status = "blocked"

    score = score_zone_reaction_v2(zone, reaction, direction, bias, regime, overlays, rr, bool(trigger_ids), status, confluence, config)
    candidate = SetupCandidate(
        symbol=symbol,
        timeframe=config.timeframe,
        playbook="zone_reaction_v2",
        direction=direction,
        status=status,
        zone_reaction_state=reaction.state,
        score=score,
        entry=entry,
        stop_loss=stop,
        take_profit=take_profit,
        risk_reward=rr,
        primary_zone_id=str(zone.get("id")) if zone.get("id") else None,
        related_zone_ids=[str(zone.get("id"))] + list(confluence["confluence_zone_ids"]),
        trigger_point_ids=trigger_ids,
        reason=reasons + reaction.reason,
        blocked_reason=blocked,
        expires_at=None,
        metadata={
            "as_of": as_of,
            "zone_type": zone.get("type"),
            "zone_direction": zone.get("direction"),
            "zone_detector": zone.get("detector"),
            "zone_source": zone.get("source"),
            "zone_status": zone.get("status"),
            "zone_weight": zone.get("weight"),
            "zone_confidence": zone.get("confidence"),
            "zone_price_low": zone.get("price_low"),
            "zone_price_high": zone.get("price_high"),
            "zone_width": round(float(zone["price_high"]) - float(zone["price_low"]), 5),
            "zone_width_atr": round(zone_width_atr_ratio(zone, atr), 4),
            "zone_detected_at": zone.get("detected_at"),
            "zone_visual_start": zone.get("visual_start"),
            "zone_touch_count": zone_touch_count(zone),
            "zone_mitigation_ratio": zone.get("metadata", {}).get("mitigation_ratio") if isinstance(zone.get("metadata"), dict) else None,
            "zone_fill_ratio": zone.get("metadata", {}).get("fill_ratio") if isinstance(zone.get("metadata"), dict) else None,
            "h1_bias": bias,
            "h1_regime": regime,
            "macro_trend": macro_trend,
            "context_bypass": context_bypass,
            "trade_modes": zone_trade_modes(zone),
            "overlays": sorted(overlays),
            "trigger_types": trigger_types,
            "structure_trigger_ids": structure_trigger_ids,
            "structure_trigger_types": structure_trigger_types,
            "price_action_trigger_ids": price_action_trigger_ids,
            "price_action_trigger_types": price_action_trigger_types,
            "atr": round(atr, 5),
            "reaction_v2": reaction.state,
            "state_machine": zone_reaction_v2_state_machine(reaction, status, blocked, bool(trigger_ids)),
            "confluence_count": confluence["confluence_count"],
            "confluence_types": confluence["confluence_types"],
            "confluence_score_bonus": confluence["confluence_score_bonus"],
            **reaction.metadata,
        },
    )
    return [candidate]


def evaluate_sr_breakout_v1(
    symbol: str,
    zone: dict[str, Any],
    candles: list[dict[str, Any]],
    atr: float,
    macro_trend: str,
    bias: str,
    regime: str,
    config: StrategyConfig,
) -> list[SetupCandidate]:
    if not config.sr_breakout_v1_enabled or len(candles) < 2:
        return []
    zone_type = str(zone.get("type"))
    if zone_type not in PLAYBOOK_ZONE_TYPES["sr_breakout_v1"]:
        return []
    if not zone_allows_breakout(zone, config):
        return []

    direction, context_bypass = sr_breakout_direction(zone, macro_trend)
    if direction is None:
        return []
    reaction = classify_sr_breakout_v1(zone, candles, atr, direction, config)
    if reaction.state == "far":
        return []

    last = candles[-1]
    entry, stop, take_profit, rr = compute_sr_breakout_v1_levels(direction, last, atr, config, zone)
    blocked: list[str] = []
    reasons = [
        "SR Breakout V1 uses H1 close outside support/resistance.",
        f"Breakout model: {reaction.state}.",
    ]
    if context_bypass:
        reasons.append("Human breakout mode bypasses all context gates including macro trend.")
    else:
        reasons.append(f"Macro trend {macro_trend} allows {direction} breakout.")
    stop_distance = abs(entry - stop) if entry is not None and stop is not None else None
    if stop_distance is not None and stop_distance > config.sr_breakout_v1_max_stop_distance:
        blocked.append(
            f"Stop distance {stop_distance:.2f} exceeds SR Breakout V1 maximum {config.sr_breakout_v1_max_stop_distance:.2f}."
        )
    allowed_entries = set(config.sr_breakout_v1_allowed_entries)
    if blocked:
        status = "blocked"
    elif reaction.state in {"breakout_close", "retest_breakout"} and reaction.state in allowed_entries:
        status = "eligible"
    else:
        status = "waiting_confirmation"
        if reaction.state in {"breakout_close", "retest_breakout"}:
            # Detected but disabled entries stay visible for UI/alerts/research.
            # breakout_close backtested at -5.24R/45 trades (buying the top of the
            # move); retest entries are the configured default.
            reasons.append(f"Entry {reaction.state} is disabled for SR Breakout V1; waiting for allowed entry.")
    score = score_sr_breakout_v1(zone, reaction, direction, macro_trend, status)
    candidate = SetupCandidate(
        symbol=symbol,
        timeframe="H1",
        playbook="sr_breakout_v1",
        direction=direction,
        status=status,
        zone_reaction_state=reaction.state,
        score=score,
        entry=entry,
        stop_loss=stop,
        take_profit=take_profit,
        risk_reward=rr,
        primary_zone_id=str(zone.get("id")) if zone.get("id") else None,
        related_zone_ids=[str(zone.get("id"))] if zone.get("id") else [],
        trigger_point_ids=[],
        reason=[*reasons, *reaction.reason],
        blocked_reason=blocked,
        expires_at=None,
        metadata={
            "as_of": last.get("time"),
            "zone_type": zone_type,
            "zone_direction": zone.get("direction"),
            "zone_detector": zone.get("detector"),
            "zone_source": zone.get("source"),
            "zone_status": zone.get("status"),
            "zone_weight": zone.get("weight"),
            "zone_confidence": zone.get("confidence"),
            "zone_price_low": zone.get("price_low"),
            "zone_price_high": zone.get("price_high"),
            "zone_width": round(float(zone["price_high"]) - float(zone["price_low"]), 5),
            "zone_width_atr": round(zone_width_atr_ratio(zone, atr), 4),
            "zone_detected_at": zone.get("detected_at"),
            "zone_visual_start": zone.get("visual_start"),
            "h1_bias": bias,
            "h1_regime": regime,
            "macro_trend": macro_trend,
            "atr": round(atr, 5),
            "entry_model": reaction.metadata.get("entry_model"),
            "breakout_close_distance_atr": reaction.metadata.get("breakout_close_distance_atr"),
            "context_bypass": context_bypass,
            "trade_modes": zone_trade_modes(zone),
            "reaction_v2": reaction.state,
            "state_machine": sr_breakout_v1_state_machine(reaction, status),
            **reaction.metadata,
        },
    )
    return [candidate]


def classify_sr_breakout_v1(
    zone: dict[str, Any],
    candles: list[dict[str, Any]],
    atr: float,
    direction: str,
    config: StrategyConfig,
) -> ReactionResult:
    last = candles[-1]
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    close = float(last["close"])
    high = float(last["high"])
    low = float(last["low"])
    buffer = atr * config.sr_breakout_v1_breakout_buffer_atr
    near_limit = atr * config.sr_breakout_v1_market_entry_max_distance_atr

    retest = sr_breakout_retest_reaction(zone, candles, atr, direction, config)
    if retest is not None:
        return retest

    # Weak-bodied candles drifting past the zone edge are not real breakouts;
    # they are the group most likely to mean-revert straight back into the zone.
    body_ok = candle_body(last) >= atr * config.sr_breakout_v1_min_body_atr

    if direction == "long":
        distance = close - zone_high
        if distance >= buffer and not body_ok:
            return reaction_v2(
                "waiting_retest",
                "long",
                high >= zone_high,
                last,
                ["Breakout body too small; waiting for retest instead of market entry."],
                buffer,
                {"entry_model": "wait_retest", "breakout_body_atr": round(candle_body(last) / max(atr, 0.00001), 4)},
            )
        if distance >= buffer:
            return reaction_v2(
                "breakout_close" if distance <= near_limit else "waiting_retest",
                "long",
                high >= zone_high,
                last,
                [
                    "H1 closed above resistance breakout buffer."
                    if distance <= near_limit
                    else "H1 breakout closed far above resistance; waiting for retest."
                ],
                buffer,
                {
                    "entry_model": "next_h1_open" if distance <= near_limit else "wait_retest",
                    "breakout_close_distance": round(distance, 5),
                    "breakout_close_distance_atr": round(distance / max(atr, 0.00001), 4),
                },
            )
    else:
        distance = zone_low - close
        if distance >= buffer and not body_ok:
            return reaction_v2(
                "waiting_retest",
                "short",
                low <= zone_low,
                last,
                ["Breakout body too small; waiting for retest instead of market entry."],
                buffer,
                {"entry_model": "wait_retest", "breakout_body_atr": round(candle_body(last) / max(atr, 0.00001), 4)},
            )
        if distance >= buffer:
            return reaction_v2(
                "breakout_close" if distance <= near_limit else "waiting_retest",
                "short",
                low <= zone_low,
                last,
                [
                    "H1 closed below support breakout buffer."
                    if distance <= near_limit
                    else "H1 breakout closed far below support; waiting for retest."
                ],
                buffer,
                {
                    "entry_model": "next_h1_open" if distance <= near_limit else "wait_retest",
                    "breakout_close_distance": round(distance, 5),
                    "breakout_close_distance_atr": round(distance / max(atr, 0.00001), 4),
                },
            )
    return reaction_v2("far", direction, False, last, [], buffer)


def sr_breakout_retest_reaction(
    zone: dict[str, Any],
    candles: list[dict[str, Any]],
    atr: float,
    direction: str,
    config: StrategyConfig,
) -> ReactionResult | None:
    if len(candles) < 3:
        return None
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    buffer = atr * config.sr_breakout_v1_breakout_buffer_atr
    near_limit = atr * config.sr_breakout_v1_market_entry_max_distance_atr
    last = candles[-1]
    lookback = candles[-(config.sr_breakout_v1_retest_max_bars + 1) : -1]
    breakout_candle: dict[str, Any] | None = None
    min_body = atr * config.sr_breakout_v1_min_body_atr
    for candle in reversed(lookback):
        close = float(candle["close"])
        if direction == "long":
            distance = close - zone_high
        else:
            distance = zone_low - close
        if distance > near_limit and candle_body(candle) >= min_body:
            breakout_candle = candle
            break
    if breakout_candle is None:
        return None

    high = float(last["high"])
    low = float(last["low"])
    close = float(last["close"])
    if direction == "long":
        retested = low <= zone_high + buffer
        if retested and close > zone_high:
            return reaction_v2(
                "retest_breakout",
                "long",
                True,
                last,
                ["Far resistance breakout retested and held above zone."],
                buffer,
                {
                    "entry_model": "retest_next_h1_open",
                    "breakout_candle_time": breakout_candle.get("time"),
                    "state_machine_path": "BREAKOUT_CONFIRMED -> WAITING_RETEST -> RETEST_CONFIRMED -> PREPARE_ENTRY",
                },
            )
        if retested:
            return reaction_v2(
                "waiting_retest",
                "long",
                True,
                last,
                ["Retest touched broken resistance; waiting for close back above zone."],
                buffer,
                {"entry_model": "wait_retest", "breakout_candle_time": breakout_candle.get("time")},
            )
    else:
        retested = high >= zone_low - buffer
        if retested and close < zone_low:
            return reaction_v2(
                "retest_breakout",
                "short",
                True,
                last,
                ["Far support breakout retested and held below zone."],
                buffer,
                {
                    "entry_model": "retest_next_h1_open",
                    "breakout_candle_time": breakout_candle.get("time"),
                    "state_machine_path": "BREAKOUT_CONFIRMED -> WAITING_RETEST -> RETEST_CONFIRMED -> PREPARE_ENTRY",
                },
            )
        if retested:
            return reaction_v2(
                "waiting_retest",
                "short",
                True,
                last,
                ["Retest touched broken support; waiting for close back below zone."],
                buffer,
                {"entry_model": "wait_retest", "breakout_candle_time": breakout_candle.get("time")},
            )
    return None


def compute_sr_breakout_v1_levels(
    direction: str,
    signal_candle: dict[str, Any],
    atr: float,
    config: StrategyConfig,
    zone: dict[str, Any] | None = None,
) -> tuple[float | None, float | None, list[float], float | None]:
    entry = round(float(signal_candle["close"]), 5)
    rr = config.sr_breakout_v1_rr
    stop_distance = atr * config.sr_breakout_v1_sl_atr
    if config.sr_breakout_v1_sl_mode == "zone_edge" and zone is not None:
        # Structural stop: the broken edge flips role (resistance -> support),
        # so invalidation is a close back through that edge plus a buffer.
        # A floor keeps the stop from collapsing when entry hugs the edge.
        edge_buffer = atr * config.sr_breakout_v1_sl_zone_buffer_atr
        min_distance = atr * config.sr_breakout_v1_sl_min_atr
        if direction == "long":
            natural = float(zone["price_high"]) - edge_buffer
            stop_distance = max(entry - natural, min_distance)
        else:
            natural = float(zone["price_low"]) + edge_buffer
            stop_distance = max(natural - entry, min_distance)
    if direction == "long":
        stop = round(entry - stop_distance, 5)
        tp = round(entry + stop_distance * rr, 5)
    else:
        stop = round(entry + stop_distance, 5)
        tp = round(entry - stop_distance * rr, 5)
    return entry, stop, [tp], round(rr, 4)


def score_sr_breakout_v1(
    zone: dict[str, Any],
    reaction: ReactionResult,
    direction: str,
    macro_trend: str,
    status: str,
) -> float:
    score = float(zone.get("weight") or 0.0) * 0.35
    score += {"breakout_close": 0.32, "retest_breakout": 0.36, "waiting_retest": 0.16}.get(reaction.state, 0.0)
    if (macro_trend == "up" and direction == "long") or (macro_trend == "down" and direction == "short"):
        score += 0.18
    if str(zone.get("source")) in {"human", "mixed"} or "breakout" in zone_trade_modes(zone):
        score += 0.08
    if status == "blocked":
        score *= 0.5
    return round(min(score, 1.0), 4)


def sr_breakout_v1_state_machine(reaction: ReactionResult, status: str) -> list[dict[str, str]]:
    active = "IDLE"
    if reaction.state == "breakout_close":
        active = "PREPARE_ENTRY" if status == "eligible" else "BREAKOUT_CONFIRMED"
    elif reaction.state == "waiting_retest":
        active = "WAITING_RETEST"
    elif reaction.state == "retest_breakout":
        active = "PREPARE_ENTRY" if status == "eligible" else "RETEST_CONFIRMED"
    elif status == "blocked":
        active = "IDLE"
    steps = [
        ("IDLE", "Wait SR zone"),
        ("BREAKOUT_CONFIRMED", "H1 close outside zone"),
        ("WAITING_RETEST", "Wait retest"),
        ("RETEST_CONFIRMED", "Retest held"),
        ("PREPARE_ENTRY", "Prepare entry"),
    ]
    order = {key: index for index, (key, _) in enumerate(steps)}
    return [
        {
            "key": key,
            "label": label,
            "status": "active" if key == active else "done" if order[key] < order.get(active, 99) else "pending",
        }
        for key, label in steps
    ]


def zone_reaction_v2_status(
    direction: str,
    reaction: ReactionResult,
    has_trigger: bool,
    bias: str,
    secondary_bias: Any,
    regime: str,
    config: StrategyConfig,
    has_structure_trigger: bool = False,
    has_price_action_trigger: bool = False,
    macro_trend: str = "unknown",
    context_bypass: bool = False,
    zone_type: str = "",
) -> tuple[str, list[str], list[str]]:
    blocked: list[str] = []
    reasons = ["Zone Reaction V2 single-zone reaction setup.", f"Reaction V2: {reaction.state}."]
    if context_bypass:
        # Human explicitly opted this zone into the reaction family, so every
        # context gate (bias/regime/news/macro) is bypassed: the human thesis
        # outranks bot context. Signal-quality conditions still apply.
        reasons.append("Human trade mode bypasses all context gates including macro trend.")
    if not context_bypass and config.zone_reaction_v2_block_news_or_risk_off and regime in {"news", "risk_off"}:
        blocked.append(f"Regime {regime} blocks Zone Reaction V2.")

    # Macro trend gate: counter-macro trades had a clear negative edge in backtest
    # (resistance shorts during the 2023-2026 gold uptrend). "flat"/"unknown"
    # macro allows both directions so the gate degrades gracefully without history.
    # FVG zones are exempt: FVG fills reverse against macro fine (PA-only edge).
    fvg_macro_exempt = zone_type == "fvg"
    if not context_bypass and config.zone_reaction_v2_macro_gate_enabled and not fvg_macro_exempt:
        if macro_trend == "up" and direction == "short":
            blocked.append("Macro trend up blocks Zone Reaction V2 short.")
        elif macro_trend == "down" and direction == "long":
            blocked.append("Macro trend down blocks Zone Reaction V2 long.")
        else:
            reasons.append(f"Macro trend {macro_trend} allows {direction}.")
    elif fvg_macro_exempt:
        reasons.append(f"FVG zone: macro trend gate skipped (macro={macro_trend}, direction={direction}).")

    # TEMP RESEARCH OVERRIDE:
    # The normal context gate requires bias-aligned trades and only allows
    # two-sided neutral trades when `regime == "ranging"`. That means
    # `neutral + trending` blocks both long and short setups. It is disabled
    # temporarily so backtests can measure raw zone reaction quality.
    #
    # To restore the production gate, uncomment this block:
    #
    # expected = bias_to_direction(bias)
    # if direction != expected:
    #     if bias == "neutral":
    #         if not (config.zone_reaction_v2_allow_neutral_range_trade and regime == "ranging"):
    #             blocked.append("Neutral bias only allows Zone Reaction V2 range trade in ranging regime.")
    #         else:
    #             reasons.append("Neutral+ranging allows two-sided zone reaction.")
    #     elif secondary_allows_direction(secondary_bias, direction):
    #         reasons.append("Countertrend allowed by human secondary bias.")
    #     else:
    #         blocked.append("Zone Reaction V2 requires direction aligned with bias.")
    reasons.append("Bias/regime direction gate temporarily disabled for reaction research.")

    if reaction.state == "approaching":
        reasons.append("Price approaching zone; no touch yet.")
        return "watching", blocked, reasons

    if reaction.state == "fakeout" and config.zone_reaction_v2_require_trigger_for_fakeout and not has_trigger:
        reasons.append("Fakeout requires M15 trigger; waiting for confirmation.")
        status = "waiting_confirmation"
    elif (
        reaction.state == "fakeout"
        and float(reaction.metadata.get("fakeout_reaction_depth_atr", 0.0)) > config.zone_reaction_v2_fakeout_max_reaction_depth_atr
    ):
        reasons.append("Fakeout wick is too deep; waiting for follow-through confirmation.")
        status = "waiting_confirmation"
    elif reaction.state == "internal_reject" and reaction.state not in set(config.zone_reaction_v2_allowed_reactions):
        reasons.append("Internal reject is disabled for Zone Reaction V2; keeping it for debug only.")
        status = "waiting_confirmation"
    elif reaction.state == "internal_reject" and config.zone_reaction_v2_internal_reject_requires_structure and not has_structure_trigger:
        reasons.append("Internal reject requires M15 BOS/CHOCH; waiting for structure confirmation.")
        status = "waiting_confirmation"
    elif reaction.state == "internal_reject" and config.zone_reaction_v2_internal_reject_requires_price_action and not has_price_action_trigger:
        reasons.append("Internal reject requires M15 price action; waiting for PA confirmation.")
        status = "waiting_confirmation"
    elif reaction.state not in set(config.zone_reaction_v2_allowed_reactions):
        # We still surface disabled states in UI/backtest metadata so humans can
        # debug the state machine, but only configured reactions may become trades.
        reasons.append(f"Reaction {reaction.state} is disabled for Zone Reaction V2; keeping it for debug only.")
        status = "waiting_confirmation"
    elif reaction.state in {"reject", "fakeout", "retest_reject", "internal_reject"}:
        status = "eligible"
    elif reaction.state == "waiting_bos" and has_trigger:
        reasons.append("BOS/CHOCH confirmed after slow reaction.")
        status = "eligible"
    elif reaction.state in {"slow_reaction", "waiting_bos", "waiting_retest", "clean_breakout"}:
        status = "waiting_confirmation"
    elif reaction.state == "invalid":
        status = "blocked"
    else:
        status = "blocked"
    return status, blocked, reasons


def zone_reaction_v2_state_machine(
    reaction: ReactionResult,
    status: str,
    blocked: list[str],
    has_trigger: bool,
) -> list[dict[str, str]]:
    active = reaction.state
    if reaction.state == "approaching":
        active = "APPROACHING"
    elif reaction.state == "retest_reject":
        active = "PREPARE_ENTRY"
    elif reaction.state in {"reject", "fakeout", "internal_reject"} and status == "eligible":
        active = "PREPARE_ENTRY"
    elif reaction.state == "fakeout" and status == "waiting_confirmation":
        active = "WAIT_FOR_BOS"
    elif reaction.state == "waiting_bos":
        active = "PREPARE_ENTRY" if has_trigger and status == "eligible" else "WAIT_FOR_BOS"
    elif reaction.state == "slow_reaction":
        active = "WAIT_FOR_BOS"
    elif reaction.state == "clean_breakout":
        active = "WAITING_RETEST" if status != "blocked" else "BIAS_WARNING"
    elif reaction.state == "waiting_retest":
        active = "WAITING_RETEST"
    elif status == "blocked" or blocked:
        active = "BIAS_WARNING" if reaction.state == "clean_breakout" else "IDLE"

    steps = [
        ("IDLE", "Context check"),
        ("APPROACHING", "Approaching zone"),
        ("ZONE_TOUCHED", "Zone touched"),
        ("REACTING_IN_ZONE", "M15 reaction"),
        ("WAIT_FOR_BOS", "Wait BOS/CHOCH"),
        ("WAITING_RETEST", "Wait retest"),
        ("BIAS_WARNING", "Bias warning"),
        ("PREPARE_ENTRY", "Prepare entry"),
    ]
    return [
        {
            "key": key,
            "label": label,
            "status": "active" if key == active else "done" if step_done(key, active) else "pending",
        }
        for key, label in steps
    ]


def step_done(key: str, active: str) -> bool:
    order = {
        "IDLE": 0,
        "APPROACHING": 1,
        "ZONE_TOUCHED": 2,
        "REACTING_IN_ZONE": 3,
        "WAIT_FOR_BOS": 4,
        "WAITING_RETEST": 4,
        "BIAS_WARNING": 5,
        "PREPARE_ENTRY": 6,
    }
    return order.get(key, 99) < order.get(active, 99)


def playbook_allowed(playbook: str, allowed_playbooks: set[str] | None) -> bool:
    return allowed_playbooks is None or playbook in allowed_playbooks


def zone_trade_disabled_after_sweep(zone: dict[str, Any]) -> bool:
    metadata = zone.get("metadata")
    return bool(isinstance(metadata, dict) and metadata.get("trade_disabled_after_sweep"))


def zone_eligible_for_zone_reaction_v2(
    zone: dict[str, Any],
    candles: list[dict[str, Any]],
    config: StrategyConfig,
) -> bool:
    status = str(zone.get("status"))
    if status == "active":
        return True
    if status != "mitigated" or str(zone.get("type")) != "fvg":
        return False
    if not config.zone_reaction_v2_internal_reject_enabled:
        return False
    fill_ratio = fvg_fill_ratio(zone, candles[-1] if candles else None)
    if fill_ratio < config.zone_reaction_v2_internal_reject_min_fvg_fill_ratio:
        return False
    fill_time = first_text(zone.get("valid_until"), zone.get("visual_end"), zone.get("invalidated_at"))
    if not fill_time or not candles:
        return candle_touches_zone(candles[-1], zone) if candles else False
    lookback = max(config.zone_reaction_v2_internal_reject_watch_after_fvg_fill_bars, 1)
    watch_start = str(candles[max(0, len(candles) - lookback - 1)]["time"])
    current_time = str(candles[-1]["time"])
    return watch_start <= str(fill_time) <= current_time


def zone_eligible_for_sr_breakout_v1(zone: dict[str, Any], candles: list[dict[str, Any]], config: StrategyConfig) -> bool:
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
    window = candles[-(config.sr_breakout_v1_retest_max_bars + 1) :]
    return invalidated_at >= str(window[0]["time"])


def zone_trade_modes(zone: dict[str, Any]) -> list[str]:
    metadata = zone.get("metadata") if isinstance(zone.get("metadata"), dict) else {}
    raw = metadata.get("trade_modes")
    if isinstance(raw, list):
        modes = [str(item) for item in raw if str(item) in TRADE_MODES]
        # An explicit empty list means human disabled all trade modes for this
        # zone; only fall back to defaults when metadata has no trade_modes key.
        return modes
    return list(DEFAULT_TRADE_MODES_BY_ZONE_TYPE.get(str(zone.get("type")), ()))


def zone_has_explicit_trade_mode(zone: dict[str, Any], mode: str) -> bool:
    metadata = zone.get("metadata") if isinstance(zone.get("metadata"), dict) else {}
    raw = metadata.get("trade_modes")
    return isinstance(raw, list) and mode in {str(item) for item in raw}


def zone_allows_breakout(zone: dict[str, Any], config: StrategyConfig) -> bool:
    if zone_has_explicit_trade_mode(zone, "breakout"):
        return True
    return bool(config.sr_breakout_v1_allow_bot_sr_breakout and str(zone.get("source")) == "bot")


def sr_breakout_direction(zone: dict[str, Any], macro_trend: str) -> tuple[str | None, bool]:
    zone_type = str(zone.get("type"))
    human_breakout = zone_has_explicit_trade_mode(zone, "breakout")
    # Human breakout mode bypasses every context gate including macro trend:
    # direction comes purely from which side the zone breaks.
    if human_breakout:
        if zone_type == "resistance":
            return "long", True
        if zone_type == "support":
            return "short", True
        return None, True
    # Bot zones stay macro-aligned: long breakouts only in an up trend,
    # short breakouts only in a down trend.
    if macro_trend == "up" and zone_type == "resistance":
        return "long", False
    if macro_trend == "down" and zone_type == "support":
        return "short", False
    return None, False


def allowed_zone_types_for_playbooks(allowed_playbooks: set[str] | None) -> set[str]:
    playbooks = set(PLAYBOOK_ZONE_TYPES) if allowed_playbooks is None else allowed_playbooks
    zone_types: set[str] = set()
    for playbook in playbooks:
        zone_types.update(PLAYBOOK_ZONE_TYPES.get(playbook, set()))
    return zone_types


def classify_zone_reaction_v2(
    zone: dict[str, Any],
    candles: list[dict[str, Any]],
    atr: float,
    config: StrategyConfig,
) -> ReactionResult:
    if not candles:
        return reaction("far", None, False, {}, [], 0.0)
    zone_type = str(zone.get("type"))
    if zone_type == "order_block":
        return reaction("far", None, False, candles[-1], ["Order Block is excluded from Zone Reaction V2."], 0.0)
    if zone_type == "consolidation":
        return classify_consolidation_reaction_v2(zone, candles, atr, config)

    last = candles[-1]
    low = float(last["low"])
    high = float(last["high"])
    close = float(last["close"])
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    touched = high >= zone_low and low <= zone_high
    expected = expected_trade_direction(zone)
    if expected not in {"long", "short"}:
        return reaction("far", None, touched, last, [], 0.0)

    retest = breakout_retest_reaction(zone, candles, atr, config, expected)
    if retest is not None:
        return retest

    body = candle_body(last)
    avg_body = average_body(candles, config.zone_reaction_v2_reject_avg_body_period)
    strong_reject = body >= avg_body * config.zone_reaction_v2_reject_body_min_ratio
    breakout_body = body >= atr * config.zone_reaction_v2_breakout_min_body_atr
    fakeout_limit = atr * config.zone_reaction_v2_fakeout_max_atr
    buffer = atr * config.breakout_buffer_atr_multiplier
    min_close_outside = atr * config.zone_reaction_v2_breakout_min_close_outside_atr

    if expected == "long":
        penetration = max(zone_low - low, 0.0)
        if penetration > 0 and penetration <= fakeout_limit and close >= zone_low:
            reaction_depth = max(close - low, 0.0)
            return reaction_v2(
                "fakeout",
                "long",
                True,
                last,
                ["Fakeout below bullish zone and close reclaimed zone."],
                buffer,
                {
                    "fakeout_distance_atr": round(penetration / max(atr, 0.00001), 4),
                    "fakeout_reaction_depth_atr": round(reaction_depth / max(atr, 0.00001), 4),
                },
            )
        if touched and close > zone_high and strong_reject:
            return reaction_v2("reject", "long", True, last, ["Strong bullish rejection from zone."], buffer)
        if (
            config.zone_reaction_v2_reject_pinbar_enabled
            and low <= zone_high
            and close > zone_high
            and _is_pinbar_reject(
                last, "long",
                config.zone_reaction_v2_reject_pinbar_wick_body_ratio,
                config.zone_reaction_v2_reject_pinbar_min_wick_ratio,
                avg_body=avg_body,
                body_min_ratio=config.zone_reaction_v2_reject_body_min_ratio,
            )
        ):
            return reaction_v2("reject", "long", True, last, ["Bullish pinbar rejection at zone."], buffer)
        close_outside = zone_low - close
        if close_outside >= min_close_outside and breakout_body:
            return reaction_v2(
                "clean_breakout",
                "short",
                touched,
                last,
                ["Clean break below bullish zone."],
                buffer,
                {
                    "bias_phase": "transition_bearish",
                    "breakout_close_outside_atr": round(close_outside / max(atr, 0.00001), 4),
                },
            )
    else:
        penetration = max(high - zone_high, 0.0)
        if penetration > 0 and penetration <= fakeout_limit and close <= zone_high:
            reaction_depth = max(high - close, 0.0)
            return reaction_v2(
                "fakeout",
                "short",
                True,
                last,
                ["Fakeout above bearish zone and close reclaimed zone."],
                buffer,
                {
                    "fakeout_distance_atr": round(penetration / max(atr, 0.00001), 4),
                    "fakeout_reaction_depth_atr": round(reaction_depth / max(atr, 0.00001), 4),
                },
            )
        if touched and close < zone_low and strong_reject:
            return reaction_v2("reject", "short", True, last, ["Strong bearish rejection from zone."], buffer)
        if (
            config.zone_reaction_v2_reject_pinbar_enabled
            and high >= zone_low
            and close < zone_low
            and _is_pinbar_reject(
                last, "short",
                config.zone_reaction_v2_reject_pinbar_wick_body_ratio,
                config.zone_reaction_v2_reject_pinbar_min_wick_ratio,
                avg_body=avg_body,
                body_min_ratio=config.zone_reaction_v2_reject_body_min_ratio,
            )
        ):
            return reaction_v2("reject", "short", True, last, ["Bearish pinbar rejection at zone."], buffer)
        close_outside = close - zone_high
        if close_outside >= min_close_outside and breakout_body:
            return reaction_v2(
                "clean_breakout",
                "long",
                touched,
                last,
                ["Clean break above bearish zone."],
                buffer,
                {
                    "bias_phase": "transition_bullish",
                    "breakout_close_outside_atr": round(close_outside / max(atr, 0.00001), 4),
                },
            )

    internal_window_metadata = internal_reject_window_metadata(candles, config)
    slow = slow_reaction_direction(zone, candles, atr, config)
    if slow:
        return reaction_v2(
            "slow_reaction",
            slow,
            True,
            last,
            ["Slow reaction inside zone; waiting for BOS/CHOCH."],
            buffer,
            internal_window_metadata,
        )
    if touched:
        return reaction_v2(
            "waiting_bos",
            expected,
            True,
            last,
            ["Touched zone; waiting for stronger M15 reaction."],
            buffer,
            internal_window_metadata,
        )
    # Surface zones the price is closing in on so the UI state machine can show
    # an APPROACHING step before the first touch. Distance is measured from the
    # candle close to the nearest zone edge.
    distance = zone_low - close if close < zone_low else close - zone_high if close > zone_high else 0.0
    approach_limit = atr * config.approach_atr_multiplier
    if 0.0 < distance <= approach_limit:
        return reaction_v2(
            "approaching",
            expected,
            False,
            last,
            [f"Price within {config.approach_atr_multiplier:.2f} ATR of zone; watching for touch."],
            buffer,
            {"approach_distance_atr": round(distance / max(atr, 0.00001), 4)},
        )
    return reaction_v2("far", expected, False, last, [], buffer)


def breakout_retest_reaction(
    zone: dict[str, Any],
    candles: list[dict[str, Any]],
    atr: float,
    config: StrategyConfig,
    expected: str,
) -> ReactionResult | None:
    if len(candles) < 2:
        return None
    last = candles[-1]
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    buffer = atr * config.breakout_buffer_atr_multiplier
    breakout_body_threshold = atr * config.zone_reaction_v2_breakout_min_body_atr
    min_close_outside = atr * config.zone_reaction_v2_breakout_min_close_outside_atr
    lookback = candles[-(config.zone_reaction_v2_retest_max_bars + 1) : -1]
    breakout_candle: dict[str, Any] | None = None
    breakout_direction: str | None = None

    for candle in reversed(lookback):
        body = candle_body(candle)
        close = float(candle["close"])
        if expected == "long" and zone_low - close >= min_close_outside and body >= breakout_body_threshold:
            breakout_candle = candle
            breakout_direction = "short"
            break
        if expected == "short" and close - zone_high >= min_close_outside and body >= breakout_body_threshold:
            breakout_candle = candle
            breakout_direction = "long"
            break
    if breakout_candle is None or breakout_direction is None:
        return None

    high = float(last["high"])
    low = float(last["low"])
    close = float(last["close"])
    body = candle_body(last)
    avg_body = average_body(candles, config.zone_reaction_v2_reject_avg_body_period)
    strong_retest_reject = body >= avg_body
    if breakout_direction == "short":
        retested = high >= zone_low and low <= zone_high
        if retested and close < zone_low and strong_retest_reject:
            return reaction_v2(
                "retest_reject",
                "short",
                True,
                last,
                ["Clean break below zone, retest rejected from underside."],
                buffer,
                {
                    "breakout_candle_time": breakout_candle.get("time"),
                    "breakout_direction": "short",
                    "state_machine_path": "CLEAN_BREAK -> WAITING_RETEST -> RETEST_REJECT -> PREPARE_ENTRY",
                },
            )
        if retested:
            return reaction_v2(
                "waiting_retest",
                "short",
                True,
                last,
                ["Clean break below zone; retest is still waiting for bearish rejection."],
                buffer,
                {"breakout_candle_time": breakout_candle.get("time"), "breakout_direction": "short"},
            )
    else:
        retested = low <= zone_high and high >= zone_low
        if retested and close > zone_high and strong_retest_reject:
            return reaction_v2(
                "retest_reject",
                "long",
                True,
                last,
                ["Clean break above zone, retest rejected from topside."],
                buffer,
                {
                    "breakout_candle_time": breakout_candle.get("time"),
                    "breakout_direction": "long",
                    "state_machine_path": "CLEAN_BREAK -> WAITING_RETEST -> RETEST_REJECT -> PREPARE_ENTRY",
                },
            )
        if retested:
            return reaction_v2(
                "waiting_retest",
                "long",
                True,
                last,
                ["Clean break above zone; retest is still waiting for bullish rejection."],
                buffer,
                {"breakout_candle_time": breakout_candle.get("time"), "breakout_direction": "long"},
            )
    return None


def classify_consolidation_reaction_v2(
    zone: dict[str, Any],
    candles: list[dict[str, Any]],
    atr: float,
    config: StrategyConfig,
) -> ReactionResult:
    last = candles[-1]
    low = float(last["low"])
    high = float(last["high"])
    close = float(last["close"])
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    midpoint = (zone_low + zone_high) / 2
    buffer = atr * config.breakout_buffer_atr_multiplier
    body = candle_body(last)
    breakout_body = body >= atr * config.zone_reaction_v2_consolidation_breakout_body_atr
    fakeout_limit = atr * config.zone_reaction_v2_fakeout_max_atr
    touched = high >= zone_low and low <= zone_high

    upper_fakeout = max(high - zone_high, 0.0)
    lower_fakeout = max(zone_low - low, 0.0)
    if upper_fakeout > 0 and upper_fakeout <= fakeout_limit and close <= zone_high:
        return reaction_v2(
            "fakeout",
            "short",
            True,
            last,
            ["Fakeout above consolidation high and close back inside."],
            buffer,
            {"fakeout_distance_atr": round(upper_fakeout / max(atr, 0.00001), 4)},
        )
    if lower_fakeout > 0 and lower_fakeout <= fakeout_limit and close >= zone_low:
        return reaction_v2(
            "fakeout",
            "long",
            True,
            last,
            ["Fakeout below consolidation low and close back inside."],
            buffer,
            {"fakeout_distance_atr": round(lower_fakeout / max(atr, 0.00001), 4)},
        )
    if close > zone_high + buffer and breakout_body:
        return reaction_v2("clean_breakout", "long", touched, last, ["Clean breakout above consolidation."], buffer)
    if close < zone_low - buffer and breakout_body:
        return reaction_v2("clean_breakout", "short", touched, last, ["Clean breakout below consolidation."], buffer)
    if touched and close > midpoint and body >= average_body(candles, config.zone_reaction_v2_reject_avg_body_period):
        return reaction_v2("reject", "short", True, last, ["Bearish range-bound reaction near consolidation high."], buffer)
    if touched and close <= midpoint and body >= average_body(candles, config.zone_reaction_v2_reject_avg_body_period):
        return reaction_v2("reject", "long", True, last, ["Bullish range-bound reaction near consolidation low."], buffer)
    slow = slow_reaction_direction(zone, candles, atr, config)
    if slow:
        return reaction_v2("slow_reaction", slow, True, last, ["Slow reaction inside consolidation; waiting for BOS/CHOCH."], buffer)
    if touched:
        return reaction_v2("waiting_bos", "short" if close > midpoint else "long", True, last, ["Inside consolidation; waiting for trigger."], buffer)
    return reaction_v2("far", None, False, last, [], buffer)


def promote_internal_reject_if_confirmed(
    zone: dict[str, Any],
    base_reaction: ReactionResult,
    atr: float,
    config: StrategyConfig,
    has_structure_trigger: bool,
    has_price_action_trigger: bool,
    has_current_trigger: bool,
) -> ReactionResult:
    if base_reaction.state in {"reject", "fakeout", "retest_reject", "clean_breakout", "far", "invalid"}:
        return base_reaction
    if not config.zone_reaction_v2_internal_reject_enabled or not base_reaction.touched:
        return base_reaction
    if not has_current_trigger:
        return base_reaction

    direction = base_reaction.direction
    if direction not in {"long", "short"}:
        return base_reaction
    zone_type = str(zone.get("type"))
    if zone_type not in {"support", "resistance", "fvg"}:
        return base_reaction

    # SR zones need the stricter structure confirmation: PA alone inside a
    # support/resistance band backtests as knife-catching (-5.5R support longs),
    # while FVG fills reverse fine on PA alone (+7R FVG longs).
    requires_structure = (
        config.zone_reaction_v2_internal_reject_sr_requires_structure
        if zone_type in {"support", "resistance"}
        else config.zone_reaction_v2_internal_reject_requires_structure
    )
    if requires_structure and not has_structure_trigger:
        return base_reaction
    if config.zone_reaction_v2_internal_reject_requires_price_action and not has_price_action_trigger:
        return base_reaction

    candle = {
        "time": base_reaction.metadata.get("reaction_candle_time"),
        "open": base_reaction.metadata.get("reaction_open"),
        "high": base_reaction.metadata.get("reaction_high"),
        "low": base_reaction.metadata.get("reaction_low"),
        "close": base_reaction.metadata.get("reaction_close"),
    }
    if not close_inside_zone(candle, zone):
        return base_reaction

    metadata: dict[str, Any] = {
        "inside_zone_close_position": round(inside_zone_close_position(candle, zone), 4),
        "zone_width_atr": round(zone_width_atr_ratio(zone, atr), 4),
    }
    if zone_type == "fvg":
        fill_ratio = fvg_fill_ratio(zone, candle)
        metadata["fill_ratio"] = round(fill_ratio, 4)
        if fill_ratio < config.zone_reaction_v2_internal_reject_min_fvg_fill_ratio:
            return base_reaction
        depth_label = "deep " if fill_ratio >= config.zone_reaction_v2_internal_reject_deep_fvg_fill_ratio else ""
        side = "bullish FVG" if direction == "long" else "bearish FVG"
        reason = [f"Internal reject inside {side} after {depth_label}{fill_ratio:.0%} fill."]
    else:
        penetration = sr_penetration_atr(zone, candle, direction, atr)
        metadata["sr_penetration_atr"] = round(penetration, 4)
        if penetration < config.zone_reaction_v2_internal_reject_min_sr_penetration_atr:
            return base_reaction
        side = "support" if direction == "long" else "resistance"
        reason = [f"Internal reject inside {side} after {penetration:.2f} ATR penetration."]

    metadata["internal_reject_reason"] = reason[0]
    return reaction_v2(
        "internal_reject",
        direction,
        True,
        candle,
        [
            *reason,
            "M15 BOS/CHOCH and price action confirmed inside zone.",
        ],
        float(base_reaction.metadata.get("breakout_buffer", 0.0)),
        {
            **base_reaction.metadata,
            **metadata,
            # The reaction_v2 helper stamps "reaction_v2" into metadata, so the
            # inherited base value must be overwritten or trades get mislabeled
            # with the pre-promotion state (e.g. slow_reaction).
            "reaction_v2": "internal_reject",
            "previous_reaction_v2": base_reaction.state,
        },
    )


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
    base = {
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
    return ReactionResult(state=state, direction=direction, touched=touched, candle_time=str(candle.get("time")), reason=reason, metadata=base)


def candle_body(candle: dict[str, Any]) -> float:
    return abs(float(candle.get("close", 0.0)) - float(candle.get("open", 0.0)))


def _is_pinbar_reject(
    candle: dict[str, Any],
    direction: str,
    wick_body_ratio: float,
    min_wick_ratio: float,
    avg_body: float = 0.0,
    body_min_ratio: float = 1.5,
) -> bool:
    """
    Bullish pinbar (long): long lower wick, close near top.
      - lower_wick >= body * wick_body_ratio
      - lower_wick_ratio >= min_wick_ratio
      - (close - low) >= avg_body * body_min_ratio  ← size check
    Bearish pinbar (short): long upper wick, close near bottom.
      - upper_wick >= body * wick_body_ratio
      - upper_wick_ratio >= min_wick_ratio
      - (high - close) >= avg_body * body_min_ratio  ← size check
    """
    high = float(candle.get("high", 0.0))
    low = float(candle.get("low", 0.0))
    open_ = float(candle.get("open", 0.0))
    close = float(candle.get("close", 0.0))
    full_range = high - low
    if full_range <= 0:
        return False
    body = abs(close - open_)
    if direction == "long":
        lower_wick = min(open_, close) - low
        lower_wick_ratio = lower_wick / full_range
        rejection_size = close - low  # recovery from wick tip to close
        size_ok = avg_body <= 0 or rejection_size >= avg_body * body_min_ratio
        return (
            lower_wick >= body * wick_body_ratio
            and lower_wick_ratio >= min_wick_ratio
            and size_ok
        )
    else:
        upper_wick = high - max(open_, close)
        upper_wick_ratio = upper_wick / full_range
        rejection_size = high - close  # drop from wick tip to close
        size_ok = avg_body <= 0 or rejection_size >= avg_body * body_min_ratio
        return (
            upper_wick >= body * wick_body_ratio
            and upper_wick_ratio >= min_wick_ratio
            and size_ok
        )


def average_body(candles: list[dict[str, Any]], period: int) -> float:
    window = candles[-max(period, 1) :]
    bodies = [candle_body(candle) for candle in window]
    return sum(bodies) / len(bodies) if bodies else 0.0


def slow_reaction_direction(zone: dict[str, Any], candles: list[dict[str, Any]], atr: float, config: StrategyConfig) -> str | None:
    if len(candles) < config.zone_reaction_v2_slow_min_bars:
        return None
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    window = candles[-config.zone_reaction_v2_slow_max_bars :]
    inside_or_touching = [
        candle for candle in window if float(candle["high"]) >= zone_low and float(candle["low"]) <= zone_high
    ]
    if len(inside_or_touching) < config.zone_reaction_v2_slow_min_bars:
        return None
    avg_body = average_body(inside_or_touching, len(inside_or_touching))
    if avg_body > atr * config.zone_reaction_v2_slow_body_max_ratio:
        return None
    expected = expected_trade_direction(zone)
    if expected in {"long", "short"}:
        return expected
    last_close = float(candles[-1]["close"])
    return "short" if last_close > zone_mid(zone) else "long"


def close_inside_zone(candle: dict[str, Any], zone: dict[str, Any]) -> bool:
    close = float(candle["close"])
    return float(zone["price_low"]) <= close <= float(zone["price_high"])


def candle_touches_zone(candle: dict[str, Any], zone: dict[str, Any]) -> bool:
    return float(candle["high"]) >= float(zone["price_low"]) and float(candle["low"]) <= float(zone["price_high"])


def inside_zone_close_position(candle: dict[str, Any], zone: dict[str, Any]) -> float:
    width = max(float(zone["price_high"]) - float(zone["price_low"]), 0.00001)
    position = (float(candle["close"]) - float(zone["price_low"])) / width
    return min(max(position, 0.0), 1.0)


def fvg_fill_ratio(zone: dict[str, Any], candle: dict[str, Any] | None = None) -> float:
    metadata = zone.get("metadata") if isinstance(zone.get("metadata"), dict) else {}
    value = metadata.get("fill_ratio")
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


def sr_penetration_atr(zone: dict[str, Any], candle: dict[str, Any], direction: str, atr: float) -> float:
    if direction == "long":
        penetration = max(float(zone["price_high"]) - float(candle["low"]), 0.0)
    else:
        penetration = max(float(candle["high"]) - float(zone["price_low"]), 0.0)
    return penetration / max(atr, 0.00001)


def first_text(*values: Any) -> str | None:
    for value in values:
        if value is not None:
            return str(value)
    return None


def compute_zone_reaction_v2_levels(
    zone: dict[str, Any],
    direction: str,
    reaction: ReactionResult,
    last_close: float,
    atr: float,
    config: StrategyConfig,
) -> tuple[float | None, float | None, list[float], float | None]:
    metadata = reaction.metadata
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    reaction_low = float(metadata.get("reaction_low", zone_low))
    reaction_high = float(metadata.get("reaction_high", zone_high))
    # Stops use the reaction wick plus a small ATR buffer, then clamp to a
    # realistic min/max distance so tiny noisy SLs and huge invalid setups are blocked.
    buffer = max(atr * config.zone_reaction_v2_stop_buffer_atr, 0.01)
    min_stop_distance = max(config.zone_reaction_v2_min_stop_price, atr * config.zone_reaction_v2_min_stop_atr)
    target_rr = config.zone_reaction_v2_rr_minimum
    entry = round(last_close, 5)
    # Wick-based stops: invalidate when the reaction extreme is swept instead of
    # the whole zone. Always on for retest/internal rejects. Classic reject prefers
    # zone stops, but can fall back to reaction_wick when the full zone would make
    # the setup exceed max_stop_distance.
    wick_stop_states = {"retest_reject", "internal_reject"}
    if config.zone_reaction_v2_reject_stop_mode == "reaction_wick":
        wick_stop_states = wick_stop_states | {"reject"}
    if direction == "long":
        wick_natural_stop = reaction_low - buffer
        zone_natural_stop = min(zone_low, reaction_low) - buffer
        natural_stop = wick_natural_stop if reaction.state in wick_stop_states else zone_natural_stop
        stop = round(min(natural_stop, entry - min_stop_distance), 5)
        if should_fallback_reject_stop_to_wick(reaction, config, entry, stop):
            stop = round(min(wick_natural_stop, entry - min_stop_distance), 5)
        risk = entry - stop
        if risk <= 0:
            return entry, stop, [], None
        take_profit = [round(entry + risk * target_rr, 5)]
    else:
        wick_natural_stop = reaction_high + buffer
        zone_natural_stop = max(zone_high, reaction_high) + buffer
        natural_stop = wick_natural_stop if reaction.state in wick_stop_states else zone_natural_stop
        stop = round(max(natural_stop, entry + min_stop_distance), 5)
        if should_fallback_reject_stop_to_wick(reaction, config, entry, stop):
            stop = round(max(wick_natural_stop, entry + min_stop_distance), 5)
        risk = stop - entry
        if risk <= 0:
            return entry, stop, [], None
        take_profit = [round(entry - risk * target_rr, 5)]
    return entry, stop, take_profit, round(target_rr, 4)


def should_fallback_reject_stop_to_wick(
    reaction: ReactionResult,
    config: StrategyConfig,
    entry: float,
    zone_mode_stop: float,
) -> bool:
    return (
        reaction.state == "reject"
        and config.zone_reaction_v2_reject_stop_mode == "zone"
        and config.zone_reaction_v2_max_stop_distance > 0
        and abs(entry - zone_mode_stop) > config.zone_reaction_v2_max_stop_distance
    )


def zone_confluence_metadata(zone: dict[str, Any], zones: list[dict[str, Any]], atr: float, bonus: float = 0.0) -> dict[str, Any]:
    zone_id = str(zone.get("id"))
    zone_type = str(zone.get("type"))
    zone_low = float(zone["price_low"])
    zone_high = float(zone["price_high"])
    tolerance = max(atr * 0.25, 0.01)
    types = {zone_type}
    ids: list[str] = []
    for other in zones:
        other_id = str(other.get("id"))
        other_type = str(other.get("type"))
        if other_id == zone_id or other_type == "order_block":
            continue
        if other_type not in PLAYBOOK_ZONE_TYPES["zone_reaction_v2"]:
            continue
        other_low = float(other["price_low"])
        other_high = float(other["price_high"])
        overlaps = other_high >= zone_low - tolerance and other_low <= zone_high + tolerance
        if not overlaps:
            continue
        types.add(other_type)
        ids.append(other_id)
    count = len(types)
    return {
        "confluence_count": count,
        "confluence_types": sorted(types),
        "confluence_zone_ids": ids,
        "confluence_score_bonus": bonus if count > 1 else 0.0,
    }


def score_zone_reaction_v2(
    zone: dict[str, Any],
    reaction: ReactionResult,
    direction: str,
    bias: str,
    regime: str,
    overlays: set[str],
    rr: float | None,
    has_trigger: bool,
    status: str,
    confluence: dict[str, Any],
    config: StrategyConfig,
) -> float:
    score = float(zone.get("weight") or 0.0) * 0.24
    score += {
        "fakeout": 0.32,
        "internal_reject": 0.28,
        "reject": 0.26,
        "slow_reaction": 0.12,
        "waiting_bos": 0.08,
        "clean_breakout": 0.10,
        "waiting_retest": 0.10,
    }.get(reaction.state, 0.0)
    if direction == bias_to_direction(bias):
        score += 0.18
    elif bias == "neutral" and regime == "ranging":
        score += 0.10
    if regime == "ranging" and str(zone.get("type")) == "consolidation":
        score += 0.08
    if "expansion" in overlays and reaction.state == "clean_breakout":
        score += 0.08
    if "contraction" in overlays and reaction.state in {"slow_reaction", "waiting_bos"}:
        score += 0.04
    if has_trigger:
        score += 0.10
    if rr is not None:
        score += min(rr / 8, 0.10)
    if int(confluence.get("confluence_count") or 1) > 1:
        score += config.zone_reaction_v2_confluence_score_bonus
    if status == "blocked":
        score *= 0.5
    return round(min(score, 1.0), 4)


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
    point_by_id = {str(point.get("id")): str(point.get("point_type", ""))
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


def internal_reject_window_metadata(candles: list[dict[str, Any]], config: StrategyConfig) -> dict[str, Any]:
    lookback = max(config.zone_reaction_v2_internal_reject_watch_after_fvg_fill_bars, 1)
    start_index = max(0, len(candles) - lookback)
    return {"internal_reject_trigger_window_start": candles[start_index].get("time")}


def zone_touch_count(zone: dict[str, Any]) -> int | None:
    metadata = zone.get("metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("touch_count_total", metadata.get("touch_count"))
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


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


def zone_mid(zone: dict[str, Any]) -> float:
    return (float(zone["price_low"]) + float(zone["price_high"])) / 2


def zone_width_atr_ratio(zone: dict[str, Any], atr: float) -> float:
    return (float(zone["price_high"]) - float(zone["price_low"])) / max(atr, 0.00001)


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
