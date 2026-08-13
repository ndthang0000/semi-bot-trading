from __future__ import annotations

from typing import Any

from ..config import StrategyConfig
from .helpers import close_inside_zone, inside_zone_close_position, reaction_v2, zone_fill_ratio, zone_width_atr_ratio
from .types import ReactionResult


INTERNAL_REJECT_ZONE_TYPES = {"support", "resistance", "fvg"}


def promote_internal_reject_if_confirmed(
    zone: dict[str, Any],
    base_reaction: ReactionResult,
    atr: float,
    config: StrategyConfig,
    has_structure_trigger: bool,
    has_price_action_trigger: bool,
    has_current_trigger: bool,
) -> ReactionResult:
    """Promote an in-zone reaction after recovery and trigger gates pass.

    Classic and internal rejects share the close-to-extreme recovery metric and
    the exact preceding-body baseline. Their only geometric distinction is the
    close: classic reject reclaims the far zone edge; internal reject remains
    inside the zone and therefore needs PA/structure policy plus minimum fill.
    """
    if base_reaction.state in {"reject", "fakeout", "far", "invalid"}:
        return base_reaction
    if not config.zone_reaction_v2_internal_reject_enabled or not base_reaction.touched:
        return base_reaction
    if not has_current_trigger:
        return base_reaction

    direction = base_reaction.direction
    zone_type = str(zone.get("type"))
    if direction not in {"long", "short"} or zone_type not in INTERNAL_REJECT_ZONE_TYPES:
        return base_reaction

    threshold = config.zone_reaction_v2_reject_recovery_min_avg_body_ratio
    baseline_ready = base_reaction.metadata.get("reaction_avg_body_ready") is True
    recovery_ratio = _float(base_reaction.metadata.get("reaction_rejection_avg_ratio"))
    recovery_metadata = {
        "internal_reject_recovery_min_ratio": threshold,
        "internal_reject_recovery_gate_passed": bool(
            baseline_ready and recovery_ratio is not None and recovery_ratio >= threshold
        ),
    }
    if not baseline_ready:
        return internal_reject_gate_failure(
            base_reaction,
            recovery_metadata,
            "Internal reject requires a complete preceding M15 body baseline.",
        )
    if recovery_ratio is None or recovery_ratio < threshold:
        shown_ratio = recovery_ratio if recovery_ratio is not None else 0.0
        return internal_reject_gate_failure(
            base_reaction,
            recovery_metadata,
            f"Internal reject recovery {shown_ratio:.2f}x is below required {threshold:.2f}x.",
        )

    requires_structure = internal_reject_requires_structure(zone_type, config)
    trigger_metadata = {
        "internal_reject_requires_structure": requires_structure,
        "internal_reject_requires_price_action": config.zone_reaction_v2_internal_reject_requires_price_action,
        "internal_reject_structure_gate_passed": not requires_structure or has_structure_trigger,
        "internal_reject_price_action_gate_passed": (
            not config.zone_reaction_v2_internal_reject_requires_price_action or has_price_action_trigger
        ),
    }
    if requires_structure and not has_structure_trigger:
        return internal_reject_gate_failure(
            base_reaction,
            {**recovery_metadata, **trigger_metadata},
            "Internal reject requires M15 BOS/CHOCH confirmation.",
        )
    if config.zone_reaction_v2_internal_reject_requires_price_action and not has_price_action_trigger:
        return internal_reject_gate_failure(
            base_reaction,
            {**recovery_metadata, **trigger_metadata},
            "Internal reject requires a directional M15 price-action trigger.",
        )

    candle = _reaction_candle(base_reaction)
    if not close_inside_zone(candle, zone):
        return base_reaction

    metadata: dict[str, Any] = {
        "inside_zone_close_position": round(inside_zone_close_position(candle, zone), 4),
        "zone_width_atr": round(zone_width_atr_ratio(zone, atr), 4),
        **recovery_metadata,
        **trigger_metadata,
        "internal_reject_gate_passed": True,
    }
    fill_ratio = zone_fill_ratio(zone, candle)
    metadata["fill_ratio"] = round(fill_ratio, 4)
    if fill_ratio < config.zone_reaction_v2_internal_reject_min_fill_ratio:
        return internal_reject_gate_failure(
            base_reaction,
            metadata,
            (
                f"Internal reject fill {fill_ratio:.0%} is below required "
                f"{config.zone_reaction_v2_internal_reject_min_fill_ratio:.0%}."
            ),
        )

    reason = _internal_reject_reason(zone_type, direction, fill_ratio, config)
    metadata["internal_reject_reason"] = reason
    confirmation = (
        "M15 BOS/CHOCH and price action confirmed inside zone."
        if requires_structure
        else "M15 price action confirmed inside zone."
    )
    return reaction_v2(
        "internal_reject",
        direction,
        True,
        candle,
        [reason, confirmation],
        float(base_reaction.metadata.get("breakout_buffer", 0.0)),
        {
            **base_reaction.metadata,
            **metadata,
            "reaction_v2": "internal_reject",
            "previous_reaction_v2": base_reaction.state,
        },
    )


def internal_reject_requires_structure(zone_type: str, config: StrategyConfig) -> bool:
    if zone_type in {"support", "resistance"}:
        return config.zone_reaction_v2_internal_reject_sr_requires_structure
    return config.zone_reaction_v2_internal_reject_requires_structure


def internal_reject_gate_failure(
    base_reaction: ReactionResult,
    metadata: dict[str, Any],
    reason: str,
) -> ReactionResult:
    """Keep the pre-promotion state while recording the failed quality gate."""
    return ReactionResult(
        state=base_reaction.state,
        direction=base_reaction.direction,
        touched=base_reaction.touched,
        candle_time=base_reaction.candle_time,
        reason=[*base_reaction.reason, reason],
        metadata={
            **base_reaction.metadata,
            **metadata,
            "internal_reject_gate_passed": False,
        },
    )


def _reaction_candle(reaction: ReactionResult) -> dict[str, Any]:
    return {
        "time": reaction.metadata.get("reaction_candle_time"),
        "open": reaction.metadata.get("reaction_open"),
        "high": reaction.metadata.get("reaction_high"),
        "low": reaction.metadata.get("reaction_low"),
        "close": reaction.metadata.get("reaction_close"),
    }


def _internal_reject_reason(
    zone_type: str,
    direction: str,
    fill_ratio: float,
    config: StrategyConfig,
) -> str:
    if zone_type == "fvg":
        depth = "deep " if fill_ratio >= config.zone_reaction_v2_internal_reject_deep_fvg_fill_ratio else ""
        side = "bullish FVG" if direction == "long" else "bearish FVG"
        return f"Internal reject inside {side} after {depth}{fill_ratio:.0%} fill."
    side = "support" if direction == "long" else "resistance"
    return f"Internal reject inside {side} after {fill_ratio:.0%} fill."


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
