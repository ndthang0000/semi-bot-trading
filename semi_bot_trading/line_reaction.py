"""Human-authored Line Reaction plans and a pure closed-candle evaluator."""
from datetime import datetime, timedelta, timezone
from typing import Literal
import math
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator

from .strategy.helpers import close_extreme_recovery_metrics
from .strategy.h1_impulse_retest_v1 import apply_h1_impulse_target_mode
from .trading_sessions import SESSION_NAMES

PLAYBOOK = "line_reaction_v1"
SESSION_ENDED_BEFORE_EXECUTION = "Selected Line trading session ended before broker execution"
AUTO_LIMIT_RECOVERY_THRESHOLD = 3.0
AUTO_LIMIT_BASE_RETRACE = 0.20
AUTO_LIMIT_RETRACE_PER_RATIO = 0.10
AUTO_LIMIT_MAX_RETRACE = 0.45
AUTO_LIMIT_MAX_M15_ATR = 0.50


class LineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    recovery_ratio: float = Field(default=2.0, ge=1, le=10)
    body_period: int = Field(default=20, ge=5, le=100)
    stop_buffer_atr: float = Field(default=0.1, ge=0, le=1)
    max_stop_h1_atr: float = Field(default=1.2, ge=0.01, le=1.2)
    limit_offset: float = Field(default=0, ge=0, le=50)
    limit_ttl_minutes: int = Field(default=120, ge=5, le=1440)
    risk_reward: Literal[1.5, 2.0, 2.5, 3.0] = 2.0
    target_mode: Literal["fixed_rr", "wave_safe", "wave_base"] = "fixed_rr"
    partial_enabled: bool = False
    partial_trigger_r: float = Field(default=1, ge=0.5, le=1.5)
    partial_fraction: float = Field(default=0.4, ge=0, le=0.5)
    trade_sessions: list[str] = Field(
        default_factory=lambda: list(SESSION_NAMES), min_length=1, max_length=5
    )

    @field_validator("trade_sessions")
    @classmethod
    def unique_sessions(cls, value):
        unique = list(dict.fromkeys(value))
        invalid = [name for name in unique if name not in SESSION_NAMES]
        if invalid:
            raise ValueError("Unknown trading session: " + ", ".join(invalid))
        return unique


class LineCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    symbol: str = Field(default="XAUUSD", min_length=1, max_length=30)
    account_labels: list[str] = Field(default_factory=list, max_length=20)
    # Kept for older API clients; new clients send account_labels.
    account_label: str | None = Field(default=None, min_length=1, max_length=100)
    client_request_id: str | None = Field(default=None, min_length=8, max_length=100)
    direction: Literal["long", "short"]
    price: float = Field(gt=0)
    expires_in_minutes: int | None = Field(default=None, ge=15, le=10080)
    config: LineConfig = Field(default_factory=LineConfig)
    visual_start: str | None = None
    visual_end: str | None = None

    @model_validator(mode="after")
    def validate_visual_span(self):
        labels = self.account_labels or ([self.account_label] if self.account_label else [])
        labels = list(dict.fromkeys(label.strip() for label in labels if label.strip()))
        if not labels:
            raise ValueError("At least one account is required")
        self.account_labels = labels
        if (self.visual_start is None) != (self.visual_end is None):
            raise ValueError("Both visual endpoints are required")
        if self.visual_start is not None:
            span_minutes = (dt(self.visual_end) - dt(self.visual_start)).total_seconds() / 60
            if span_minutes <= 0:
                raise ValueError("Visual end must follow visual start")
            if not 15 <= span_minutes <= 10080:
                raise ValueError("Line duration must be between 15 minutes and 7 days")
        return self


def dt(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp requires timezone")
    return parsed.astimezone(timezone.utc)


def evaluate_line(line, candles, atr, h1_atr, now):
    cfg = LineConfig.model_validate(line["config"])
    if not candles or not all(math.isfinite(x) and x > 0 for x in (atr, h1_atr)):
        return None
    candle = candles[-1]
    opened = dt(candle["time"])
    closed = opened + timedelta(minutes=15)
    if opened < dt(line["armed_at"]) or closed > now or now >= dt(line["expires_at"]):
        return None
    # Never execute an old candle after restart or an extended entry gate.
    if now >= closed + timedelta(minutes=15):
        return None
    if not candle["low"] <= line["price"] <= candle["high"]:
        return None
    sign = 1 if line["direction"] == "long" else -1
    if sign * (candle["close"] - candle["open"]) <= 0 or sign * (candle["close"] - line["price"]) <= 0:
        return None
    up = close_extreme_recovery_metrics(candles, "long", cfg.body_period, cfg.recovery_ratio)
    down = close_extreme_recovery_metrics(candles, "short", cfg.body_period, cfg.recovery_ratio)
    # Both ends use the shared baseline and threshold, including equality.
    if (up.passed and down.passed) or not (up.passed if sign == 1 else down.passed):
        return None
    structural = (candle["low"] - cfg.stop_buffer_atr * atr) if sign == 1 else (candle["high"] + cfg.stop_buffer_atr * atr)
    return {
        "signal_time": candle["time"], "signal_close_time": closed.isoformat(),
        "reference_price": candle["close"], "structural_stop": structural,
        "max_distance": cfg.max_stop_h1_atr * h1_atr,
        "atr": atr, "h1_atr": h1_atr,
        "recovery_long": up.ratio, "recovery_short": down.ratio,
        "recovery_long_size": up.size, "recovery_short_size": down.size,
        "recovery_average_body": up.average_body,
    }


def _entry_discount_plan(cfg: LineConfig, signal: dict, direction: str) -> dict:
    ratio_key = "recovery_long" if direction == "long" else "recovery_short"
    size_key = "recovery_long_size" if direction == "long" else "recovery_short_size"
    ratio = float(signal.get(ratio_key) or 0)
    atr = float(signal.get("atr") or 0)
    recovery_size = signal.get(size_key)
    if recovery_size is None and atr > 0:
        reference = float(signal.get("reference_price") or 0)
        structural = float(signal.get("structural_stop") or 0)
        wick = (
            structural + cfg.stop_buffer_atr * atr
            if direction == "long"
            else structural - cfg.stop_buffer_atr * atr
        )
        recovery_size = reference - wick if direction == "long" else wick - reference
    recovery_size = float(recovery_size or 0)
    values = (ratio, atr, recovery_size)
    if not all(math.isfinite(value) and value >= 0 for value in values):
        ratio = atr = recovery_size = 0

    retracement = 0.0
    auto_offset = 0.0
    if ratio >= AUTO_LIMIT_RECOVERY_THRESHOLD and recovery_size > 0 and atr > 0:
        retracement = min(
            AUTO_LIMIT_BASE_RETRACE
            + (ratio - AUTO_LIMIT_RECOVERY_THRESHOLD) * AUTO_LIMIT_RETRACE_PER_RATIO,
            AUTO_LIMIT_MAX_RETRACE,
        )
        auto_offset = min(recovery_size * retracement, atr * AUTO_LIMIT_MAX_M15_ATR)

    manual_offset = float(cfg.limit_offset)
    effective_offset = max(manual_offset, auto_offset)
    source = (
        "market"
        if effective_offset <= 0
        else "auto_recovery"
        if auto_offset > manual_offset
        else "manual"
    )
    return {
        "source": source,
        "manual_offset": round(manual_offset, 5),
        "auto_offset": round(auto_offset, 5),
        "effective_offset": round(effective_offset, 5),
        "recovery_ratio": round(ratio, 4),
        "recovery_size": round(recovery_size, 5),
        "retracement_fraction": round(retracement, 4),
        "auto_threshold": AUTO_LIMIT_RECOVERY_THRESHOLD,
        "max_m15_atr_fraction": AUTO_LIMIT_MAX_M15_ATR,
    }


def price_line(line, signal, broker_price, wave_metrics=None):
    cfg = LineConfig.model_validate(line["config"])
    sign = 1 if line["direction"] == "long" else -1
    structural, cap = signal["structural_stop"], signal["max_distance"]
    distance = sign * (broker_price - structural)
    if distance <= 0:
        raise ValueError("Broker price has crossed structural invalidation")
    discount = _entry_discount_plan(cfg, signal, line["direction"])
    kind = "market" if discount["effective_offset"] <= 0 else "limit"
    entry = (
        broker_price
        if kind == "market"
        else signal["reference_price"] - sign * discount["effective_offset"]
    )
    if kind == "limit" and sign * (broker_price - entry) <= 0:
        raise ValueError("Discount limit is no longer on the valid side of broker price")
    natural_distance = sign * (entry - structural)
    if natural_distance <= 0:
        raise ValueError("Discount entry crosses the reaction wick stop")
    distance = min(natural_distance, cap)
    stop = entry - sign * distance
    reward = distance * cfg.risk_reward
    target_detail = {"mode": "fixed_rr"}
    if cfg.target_mode != "fixed_rr":
        preview = apply_h1_impulse_target_mode(
            {"direction": line["direction"], "entry": entry, "stop_loss": stop,
             "risk_reward": cfg.risk_reward, "parameters": {"wave_safe_fraction": 0.625, "min_wave_samples": 3}},
            wave_metrics or {}, requested_mode=cfg.target_mode,
        )
        # Explicit wave mode must have enough evidence and at least 2R.
        option = next(x for x in preview["target_plan"]["options"] if x["mode"] == cfg.target_mode)
        if not option["available"]:
            raise ValueError(option["reason"])
        wave_reward = abs(float(option["price"]) - entry)
        if wave_reward < 2 * distance:
            raise ValueError("Wave target does not support minimum 2R")
        reward = min(wave_reward, cfg.risk_reward * distance)
        target_detail = option
    expiry = min(dt(line["expires_at"]), dt(signal["signal_close_time"]) + timedelta(minutes=cfg.limit_ttl_minutes))
    return {
        "entry": entry, "stop_loss": stop, "take_profit": [entry + sign * reward],
        "risk_reward": reward / distance, "expires_at": expiry.isoformat(),
        "metadata": {
            "order_type": kind, "entry_model": "line_reaction_" + kind,
            "line_id": line["id"], "line_price": line["price"], "line_signal": signal,
            "entry_discount": discount,
            "stop_source": "atr_cap" if natural_distance > cap else "reaction_wick",
            "target_detail": target_detail, "line_config": cfg.model_dump(),
            "partial_take_profit": {"enabled": cfg.partial_enabled,
                "trigger_r": cfg.partial_trigger_r, "close_fraction": cfg.partial_fraction,
                "move_stop_to": "breakeven", "breakeven_buffer": 0},
        },
    }
