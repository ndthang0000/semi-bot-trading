from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


BULLISH_PA = {"pinbar_bullish", "engulfing_bullish", "marubozu_bullish", "morning_star", "displacement_bullish"}
BEARISH_PA = {"pinbar_bearish", "engulfing_bearish", "marubozu_bearish", "evening_star", "displacement_bearish"}
BULLISH_BREAKS = {"BOS", "CHOCH"}
BEARISH_BREAKS = {"BOS", "CHOCH"}
PLAYBOOK_ZONE_TYPES: dict[str, set[str]] = {
    "zone_reaction_v2": {"support", "resistance", "fvg"},
    "sr_breakout_v1": {"support", "resistance"},
    # Imported/approved directly; the strategy builder must never emit it.
    "manual_ai_v1": set(),
}
TRADE_MODES = {"reject", "internal_reject", "breakout"}
DEFAULT_TRADE_MODES_BY_ZONE_TYPE: dict[str, tuple[str, ...]] = {
    "support": ("reject",),
    "resistance": ("reject",),
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
