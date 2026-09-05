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


class AccountPartialTakeProfitRequest(BaseModel):
    enabled: bool
    trigger_r: float = Field(ge=0.5, le=2.0)
    fraction: float = Field(default=0.4, ge=0.25, le=0.5)


class AccountManualTradingLockRequest(BaseModel):
    enabled: bool
    reason: str = Field(default="", max_length=500)


class AccountCloseAllRequest(BaseModel):
    reason: str = Field(default="", max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=100)
    include_manual_positions: bool = False


TradeManagementAction = Literal["close_now", "partial_50_be", "break_even"]


class TradeManagementActionRequest(BaseModel):
    action: TradeManagementAction
    reason: str = Field(default="", max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=160)


ManualAiSide = Literal["buy", "sell"]
ManualAiExecutionState = Literal["primary", "watch_only"]
ManualAiCancelType = Literal[
    "m5_close_below",
    "m5_close_above",
    "m15_close_below",
    "m15_close_above",
    "news_blackout_started",
    "price_reached_target_without_fill",
]


class ManualAiPartialTakeProfit(BaseModel):
    enabled: bool = True
    trigger_r: float = Field(default=1.0, ge=0.75, le=1.5)
    close_fraction: float = Field(default=0.4, ge=0.25, le=0.5)
    move_stop_to: Literal["breakeven", "unchanged"] = "breakeven"
    breakeven_buffer: float = Field(default=0, ge=0, le=10)


class ManualAiCancelCondition(BaseModel):
    type: ManualAiCancelType
    price: float | None = None


class ManualAiCandidate(BaseModel):
    client_id: str = Field(min_length=1, max_length=100)
    priority: int = Field(ge=1, le=3)
    execution_state: ManualAiExecutionState
    side: ManualAiSide
    order_type: Literal["limit"] = "limit"
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    risk_pct: float = Field(default=1.0, ge=1.0, le=1.0)
    risk_reward: float | None = Field(default=None, ge=0)
    expires_in_minutes: int = Field(ge=5, le=2_880)
    partial_take_profit: ManualAiPartialTakeProfit = Field(default_factory=ManualAiPartialTakeProfit)
    cancel_conditions: list[ManualAiCancelCondition] = Field(default_factory=list, max_length=8)
    entry_reason: str = Field(min_length=1, max_length=2_000)
    stop_reason: str = Field(min_length=1, max_length=2_000)
    target_reason: str = Field(min_length=1, max_length=2_000)
    confidence: float = Field(ge=0, le=1)
    entry_source: str = Field(default="human_custom", min_length=1, max_length=100)
    entry_options: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    original_status: Literal["eligible", "blocked"] | None = None
    original_blocked_reasons: list[str] = Field(default_factory=list, max_length=20)
    soft_blocked_reasons: list[str] = Field(default_factory=list, max_length=20)
    hard_blocked_reasons: list[str] = Field(default_factory=list, max_length=20)
    human_override: bool = False
    override_reason: str = Field(default="", max_length=2_000)
    renewed_from_plan_id: str | None = Field(default=None, max_length=100)
    renewal_count: int = Field(default=0, ge=0, le=10)


class ManualAiPlanImportRequest(BaseModel):
    schema_version: Literal[1]
    as_of: str
    symbol: str = "XAUUSD"
    playbook: Literal["manual_ai_v1", "h1_impulse_retest_v1"]
    analysis_timeframes: dict[str, str]
    market_context: dict[str, Any] = Field(default_factory=dict)
    candidates: list[ManualAiCandidate] = Field(min_length=1, max_length=3)


class ManualAiQuestionnaire(BaseModel):
    short_term_trend: Literal["bullish", "bearish", "neutral"]
    medium_term_trend: Literal["bullish", "bearish", "neutral"]
    invalidation_source: Literal["structure", "liquidity_extreme", "volatility_buffer"]
    limit_reason: Literal["pullback", "retest", "discount_premium", "liquidity_reaction"]
    emotion_state: Literal["calm", "fomo", "revenge", "uncertain"]
    # Legacy wire name kept so older deployed frontends remain compatible.
    # Execution sizing uses the selected worker's account profile, not 1%.
    accepts_one_percent_risk: bool
    confirms_lot_not_fixed: bool
    competing_exposure: bool = False
    comment: str = Field(default="", max_length=2_000)


class ManualAiApproveRequest(BaseModel):
    # `account_label` remains accepted for older clients. The chart UI sends
    # `account_labels` so one approved plan can be fanned out to every worker.
    account_label: str | None = Field(default=None, min_length=1, max_length=100)
    account_labels: list[str] = Field(default_factory=list, max_length=20)
    questionnaire: ManualAiQuestionnaire


class ManualAiLevelsUpdateRequest(BaseModel):
    entry_price: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    entry_source: str = Field(default="human_custom", min_length=1, max_length=100)
    target_mode: str | None = Field(default=None, min_length=1, max_length=100)


class ManualAiExpiryUpdateRequest(BaseModel):
    expires_in_minutes: int = Field(ge=60, le=2_880)


class H1ImpulsePreviewRequest(BaseModel):
    symbol: str = Field(default="XAUUSD", min_length=1, max_length=32)
    signal_candle_time: str = Field(min_length=1, max_length=64)
    as_of: str | None = Field(default=None, max_length=64)
    risk_reward: float = Field(default=2.5, ge=1.5, le=4)
    target_mode: Literal["fixed_rr", "wave_safe", "wave_base"] = "fixed_rr"


class H1ImpulseRevalidateRequest(BaseModel):
    symbol: str = Field(default="XAUUSD", min_length=1, max_length=32)
    signal_candle_time: str = Field(min_length=1, max_length=64)
    direction: Literal["long", "short"]
    entry: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    take_profit: float = Field(gt=0)
    target_mode: Literal["fixed_rr", "wave_safe", "wave_base"] = "fixed_rr"


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


ChartDrawingType = Literal["note", "fib_retracement", "horizontal_line"]
ChartDrawingTimeframe = Literal["M5", "M15", "H1"]


class ChartDrawingAnchor(BaseModel):
    time: str
    price: float = Field(gt=0)


class ChartDrawingCreateRequest(BaseModel):
    symbol: str = Field(default="XAUUSD", min_length=1, max_length=32)
    drawing_type: ChartDrawingType
    origin_timeframe: ChartDrawingTimeframe
    visible_timeframes: list[ChartDrawingTimeframe] = Field(default_factory=lambda: ["H1", "M15", "M5"], min_length=1, max_length=3)
    anchors: list[ChartDrawingAnchor] = Field(min_length=1, max_length=2)
    properties: dict[str, Any] = Field(default_factory=dict)
    content: str | None = Field(default=None, max_length=2_000)
    locked: bool = False
    hidden: bool = False


class ChartDrawingUpdateRequest(BaseModel):
    revision: int = Field(ge=1)
    visible_timeframes: list[ChartDrawingTimeframe] | None = Field(default=None, min_length=1, max_length=3)
    anchors: list[ChartDrawingAnchor] | None = Field(default=None, min_length=1, max_length=2)
    properties: dict[str, Any] | None = None
    content: str | None = Field(default=None, max_length=2_000)
    locked: bool | None = None
    hidden: bool | None = None
