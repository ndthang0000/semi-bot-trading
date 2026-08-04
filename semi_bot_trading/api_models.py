from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class AccountExecutionControlRequest(BaseModel):
    enabled: bool
    reason: str = Field(default="", max_length=500)


class AccountCloseAllRequest(BaseModel):
    reason: str = Field(default="", max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=100)
    include_manual_positions: bool = False


class ZoneOverrideRequest(BaseModel):
    price_low: float
    price_high: float
    visual_start: str | None = None
    visual_end: str | None = None
    weight: float = Field(ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: str = "active"
    expires_at: str | None = None
    reason: str | None = None
    trade_modes: list[str] | None = None
    direction: str | None = None


class ZoneCreateRequest(BaseModel):
    symbol: str | None = None
    timeframe: str = "H1"
    zone_type: str
    direction: str
    price_low: float
    price_high: float
    visual_start: str
    visual_end: str | None = None
    weight: float = Field(default=0.75, ge=0, le=1)
    confidence: float = Field(default=1.0, ge=0, le=1)
    status: str = "active"
    client_kind: str | None = None
    expires_at: str | None = None
    reason: str | None = None
    trade_modes: list[str] | None = None


class ZoneImportDuplicateAudit(BaseModel):
    safe_to_import: bool
    skipped: list[dict[str, Any]] = Field(default_factory=list)


class ZoneImportRequest(BaseModel):
    as_of: str
    duplicate_audit: ZoneImportDuplicateAudit
    api_endpoint: Literal["POST /api/zones/import"]
    api_payloads: list[ZoneCreateRequest] = Field(min_length=1, max_length=50)


ZoneTrend = Literal["bullish", "bearish", "neutral"]
ZoneSwingLocation = Literal["inside_zone", "near_zone", "none"]
ZoneThesisReason = Literal[
    "value_entry_outside_swing",
    "follow_short_term_trend",
    "follow_medium_term_trend",
    "breakout_retest",
    "structure_flip",
    "range_boundary",
    "repeated_reactions",
    "long_accumulation",
]
ZoneEmotionState = Literal[
    "calm",
    "fomo",
    "revenge",
    "proving_right",
    "fear_missing_price",
    "uncertain",
]


class ZoneActivationRequest(BaseModel):
    short_term_trend: ZoneTrend
    medium_term_trend: ZoneTrend
    swing_location: ZoneSwingLocation
    thesis_reasons: list[ZoneThesisReason] = Field(min_length=1, max_length=3)
    emotion_state: ZoneEmotionState
    comment: str = Field(default="", max_length=2_000)


class ContextOverrideRequest(BaseModel):
    value: str | None = None
    secondary_value: str | None = None
    overlays: list[str] | None = None
    confidence: float | None = Field(default=1.0, ge=0, le=1)
    no_expiry: bool = False
    expires_at: str | None = None
    reason: str | None = None
    use_bot: bool = False


class TradeReviewRequest(BaseModel):
    grade: str | None = None
    verdict: str = "unreviewed"
    mistake_tags: list[str] = Field(default_factory=list)
    should_trade_again: str = "unknown"
    comment: str = ""
    reviewer: str = "human"
    strategy_review: dict[str, Any] = Field(default_factory=dict)
    operator_review: dict[str, Any] = Field(default_factory=dict)


class TradeVisibilityRequest(BaseModel):
    hidden_on_chart: bool


class TradeReviewAttachmentRequest(BaseModel):
    kind: str = "review"
    image_data: str
    caption: str = ""
    chart_symbol: str | None = None
    chart_timeframe: str | None = None
    chart_start: str | None = None
    chart_end: str | None = None


class WeeklyJournalRequest(BaseModel):
    content: str = Field(default="", max_length=2_000_000)
    content_format: Literal["plain_text", "rich_text"] = "plain_text"
    icon: str = Field(default="📝", min_length=1, max_length=32)
    discipline_score: int = Field(ge=1, le=10)
    fomo_score: int = Field(ge=1, le=10)
    revenge_score: int = Field(ge=1, le=10)
    achieved_r: float = Field(default=0, ge=-1_000, le=1_000)
