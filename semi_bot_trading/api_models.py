from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


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
