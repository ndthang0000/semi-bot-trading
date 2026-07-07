"""
strategy package — re-exports all public symbols so that existing callers
using `from .strategy import X` continue to work without any changes.

Internal layout:
  types.py           — constants + ReactionResult + SetupCandidate
  helpers.py         — shared candle / zone / trigger / context utilities
  zone_reaction_v2.py — full ZRV2 playbook (classify → evaluate → score)
  sr_breakout_v1.py  — full SR Breakout V1 playbook
  builder.py         — build_setup_candidates orchestrator
"""

from .builder import build_setup_candidates
from .helpers import (
    _is_pinbar_reject,
    allowed_zone_types_for_playbooks,
    average_body,
    bias_to_direction,
    candle_body,
    candle_touches_zone,
    chart_candles_to_slices,
    close_inside_zone,
    expected_trade_direction,
    first_text,
    fvg_fill_ratio,
    inside_zone_close_position,
    internal_reject_window_metadata,
    latest_range,
    parse_overlays,
    playbook_allowed,
    parse_utc_datetime,
    reaction,
    reaction_v2,
    secondary_allows_direction,
    sr_penetration_atr,
    status_rank,
    trigger_points_for_direction,
    trigger_types_for_ids,
    unique_ids,
    zone_allows_breakout,
    zone_can_use_signal_candle,
    zone_eligible_for_sr_breakout_v1,
    zone_eligible_for_zone_reaction_v2,
    zone_has_explicit_trade_mode,
    zone_human_activation_time,
    zone_is_human_thesis,
    zone_mid,
    zone_touch_count,
    zone_trade_disabled_after_sweep,
    zone_trade_modes,
    zone_width_atr_ratio,
)
from .sr_breakout_v1 import (
    classify_sr_breakout_v1,
    compute_sr_breakout_v1_levels,
    evaluate_sr_breakout_v1,
    score_sr_breakout_v1,
    sr_breakout_direction,
    sr_breakout_retest_reaction,
    sr_breakout_v1_state_machine,
)
from .zone_reaction_levels import (
    compute_zone_reaction_v2_levels,
    should_fallback_reject_stop_to_atr,
    should_fallback_reject_stop_to_wick,
    should_fallback_wide_stop_to_atr,
)
from .types import (
    BEARISH_BREAKS,
    BEARISH_PA,
    BULLISH_BREAKS,
    BULLISH_PA,
    DEFAULT_TRADE_MODES_BY_ZONE_TYPE,
    PLAYBOOK_ZONE_TYPES,
    TRADE_MODES,
    ReactionResult,
    SetupCandidate,
)
from .zone_reaction_v2 import (
    breakout_retest_reaction,
    classify_consolidation_reaction_v2,
    classify_zone_reaction_v2,
    evaluate_zone_reaction_v2,
    promote_internal_reject_if_confirmed,
    score_zone_reaction_v2,
    slow_reaction_direction,
    step_done,
    zone_confluence_metadata,
    zone_reaction_v2_state_machine,
    zone_reaction_v2_status,
)

__all__ = [
    # builder
    "build_setup_candidates",
    # types
    "BULLISH_PA", "BEARISH_PA", "BULLISH_BREAKS", "BEARISH_BREAKS",
    "PLAYBOOK_ZONE_TYPES", "TRADE_MODES", "DEFAULT_TRADE_MODES_BY_ZONE_TYPE",
    "ReactionResult", "SetupCandidate",
    # helpers
    "allowed_zone_types_for_playbooks", "playbook_allowed",
    "candle_body", "average_body", "_is_pinbar_reject",
    "chart_candles_to_slices", "latest_range",
    "zone_trade_modes", "zone_has_explicit_trade_mode", "zone_is_human_thesis", "zone_allows_breakout",
    "zone_trade_disabled_after_sweep", "zone_eligible_for_zone_reaction_v2",
    "zone_eligible_for_sr_breakout_v1", "zone_mid", "zone_width_atr_ratio",
    "zone_touch_count", "close_inside_zone", "candle_touches_zone",
    "inside_zone_close_position", "fvg_fill_ratio", "sr_penetration_atr",
    "internal_reject_window_metadata", "trigger_points_for_direction",
    "trigger_types_for_ids", "unique_ids", "status_rank",
    "expected_trade_direction", "bias_to_direction", "secondary_allows_direction",
    "parse_overlays", "parse_utc_datetime", "first_text", "reaction", "reaction_v2",
    "zone_human_activation_time", "zone_can_use_signal_candle",
    # zone_reaction_v2
    "classify_zone_reaction_v2", "breakout_retest_reaction",
    "classify_consolidation_reaction_v2", "slow_reaction_direction",
    "promote_internal_reject_if_confirmed", "evaluate_zone_reaction_v2",
    "zone_reaction_v2_status", "zone_reaction_v2_state_machine", "step_done",
    "score_zone_reaction_v2", "compute_zone_reaction_v2_levels",
    "should_fallback_reject_stop_to_wick", "should_fallback_reject_stop_to_atr",
    "should_fallback_wide_stop_to_atr",
    "zone_confluence_metadata",
    # sr_breakout_v1
    "sr_breakout_direction", "classify_sr_breakout_v1",
    "sr_breakout_retest_reaction", "compute_sr_breakout_v1_levels",
    "score_sr_breakout_v1", "sr_breakout_v1_state_machine",
    "evaluate_sr_breakout_v1",
]
