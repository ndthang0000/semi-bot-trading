from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException

from .api_models import TradeReviewRequest
from .db import default_price_zone_expiry
from .strategy import PLAYBOOK_ZONE_TYPES


class ValueErrorForApi(ValueError):
    pass


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def parse_playbooks(value: str | None) -> set[str] | None:
    if value is None:
        return None
    playbooks = {item.strip() for item in value.split(",") if item.strip()}
    if playbooks == {"__none__"}:
        return set()
    unknown = sorted(playbooks - set(PLAYBOOK_ZONE_TYPES))
    if unknown:
        known = ", ".join(sorted(PLAYBOOK_ZONE_TYPES))
        raise HTTPException(status_code=422, detail=f"Unknown playbook(s): {', '.join(unknown)}. Known playbooks: {known}")
    return playbooks


def resolve_override_expiry(now_iso: str, no_expiry: bool, expires_at: str | None) -> str | None:
    if no_expiry:
        return None
    if expires_at:
        return expires_at
    now = datetime.fromisoformat(now_iso)
    return (now + timedelta(hours=4)).replace(microsecond=0).isoformat()


def resolve_price_zone_expiry(now_iso: str, zone_type: str, timeframe: str, expires_at: str | None) -> str:
    if expires_at:
        return expires_at
    now = datetime.fromisoformat(now_iso)
    return (now + default_price_zone_expiry(zone_type, timeframe)).replace(microsecond=0).isoformat()


def json_loads(value: str | None, default: Any) -> Any:
    if value in (None, ""):
        return default
    return json.loads(value)


def normalize_trade_review_request(request: TradeReviewRequest) -> dict[str, Any]:
    grade = request.grade.strip().upper() if isinstance(request.grade, str) and request.grade.strip() else None
    if grade is not None and grade not in {"A", "B", "C", "D"}:
        raise HTTPException(status_code=422, detail="grade must be A, B, C, D, or empty")

    verdict = request.verdict.strip().lower()
    allowed_verdicts = {"unreviewed", "good_trade", "bad_trade", "should_skip", "missed_context"}
    if verdict not in allowed_verdicts:
        raise HTTPException(status_code=422, detail=f"verdict must be one of: {', '.join(sorted(allowed_verdicts))}")

    should_trade_again = request.should_trade_again.strip().lower()
    allowed_should_trade_again = {"unknown", "yes", "no", "conditional"}
    if should_trade_again not in allowed_should_trade_again:
        raise HTTPException(
            status_code=422,
            detail=f"should_trade_again must be one of: {', '.join(sorted(allowed_should_trade_again))}",
        )

    tags = []
    seen_tags = set()
    for tag in request.mistake_tags:
        normalized_tag = tag.strip().lower()
        if not normalized_tag or normalized_tag in seen_tags:
            continue
        seen_tags.add(normalized_tag)
        tags.append(normalized_tag)
    if len(tags) > 20:
        raise HTTPException(status_code=422, detail="mistake_tags supports at most 20 tags")

    reviewer = request.reviewer.strip() or "human"
    if len(reviewer) > 80:
        raise HTTPException(status_code=422, detail="reviewer is too long")
    comment = request.comment.strip()
    if len(comment) > 5000:
        raise HTTPException(status_code=422, detail="comment is too long")

    strategy_review = normalize_structured_review(
        request.strategy_review,
        allowed_fields={
            "setup_grade",
            "setup_validity",
            "zone_quality",
            "entry_quality",
            "sl_quality",
            "tp_quality",
            "market_context",
            "should_bot_trade_again",
            "strategy_tags",
        },
        tag_field="strategy_tags",
        score_fields=set(),
    )
    operator_review = normalize_structured_review(
        request.operator_review,
        allowed_fields={
            "operator_state",
            "operator_action",
            "intervention_result",
            "followed_plan",
            "emotion_score",
            "confidence_before",
            "confidence_after",
            "operator_tags",
        },
        tag_field="operator_tags",
        score_fields={"emotion_score", "confidence_before", "confidence_after"},
    )

    return {
        "grade": grade,
        "verdict": verdict,
        "mistake_tags": tags,
        "should_trade_again": should_trade_again,
        "comment": comment,
        "reviewer": reviewer,
        "metadata": {
            "strategy_review": strategy_review,
            "operator_review": operator_review,
        },
    }


def normalize_structured_review(
    value: Any,
    *,
    allowed_fields: set[str],
    tag_field: str,
    score_fields: set[str],
) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail="structured review must be an object")
    unknown = sorted(set(value) - allowed_fields)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown review field(s): {', '.join(unknown)}")

    result: dict[str, Any] = {}
    for key, raw in value.items():
        if raw in (None, "", []):
            continue
        if key == tag_field:
            if not isinstance(raw, list):
                raise HTTPException(status_code=422, detail=f"{tag_field} must be a list")
            result[key] = normalize_review_tags(raw, tag_field)
            continue
        if key in score_fields:
            try:
                score = int(raw)
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail=f"{key} must be an integer from 1 to 5") from None
            if score < 1 or score > 5:
                raise HTTPException(status_code=422, detail=f"{key} must be an integer from 1 to 5")
            result[key] = score
            continue
        if not isinstance(raw, str):
            raise HTTPException(status_code=422, detail=f"{key} must be a string")
        text = raw.strip().lower()
        if len(text) > 80:
            raise HTTPException(status_code=422, detail=f"{key} is too long")
        if text:
            result[key] = text
    return result


def normalize_review_tags(raw_tags: list[Any], field_name: str) -> list[str]:
    tags: list[str] = []
    seen_tags: set[str] = set()
    for raw_tag in raw_tags:
        if not isinstance(raw_tag, str):
            raise HTTPException(status_code=422, detail=f"{field_name} entries must be strings")
        tag = raw_tag.strip().lower()
        if not tag or tag in seen_tags:
            continue
        seen_tags.add(tag)
        tags.append(tag)
    if len(tags) > 30:
        raise HTTPException(status_code=422, detail=f"{field_name} supports at most 30 tags")
    return tags


def trade_review_row_to_api(row: Any | None, trade_order_id: str) -> dict[str, Any]:
    if row is None:
        metadata = {"strategy_review": {}, "operator_review": {}}
        return {
            "id": None,
            "trade_order_id": trade_order_id,
            "grade": None,
            "verdict": "unreviewed",
            "mistake_tags": [],
            "should_trade_again": "unknown",
            "comment": "",
            "reviewer": "human",
            "created_at": None,
            "updated_at": None,
            "metadata": metadata,
            "strategy_review": metadata["strategy_review"],
            "operator_review": metadata["operator_review"],
        }
    metadata = json_loads(row["metadata_json"], {}) if "metadata_json" in row.keys() else {}
    if not isinstance(metadata, dict):
        metadata = {}
    strategy_review = metadata.get("strategy_review") if isinstance(metadata.get("strategy_review"), dict) else {}
    operator_review = metadata.get("operator_review") if isinstance(metadata.get("operator_review"), dict) else {}
    metadata = {**metadata, "strategy_review": strategy_review, "operator_review": operator_review}
    return {
        "id": row["id"],
        "trade_order_id": row["trade_order_id"],
        "grade": row["grade"],
        "verdict": row["verdict"],
        "mistake_tags": json_loads(row["mistake_tags_json"], []),
        "should_trade_again": row["should_trade_again"],
        "comment": row["comment"] or "",
        "reviewer": row["reviewer"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": metadata,
        "strategy_review": strategy_review,
        "operator_review": operator_review,
    }


def validate_context_value(context_type: str, value: str) -> None:
    allowed = {
        "bias": {"bullish", "bearish", "neutral"},
        "regime": {"trending", "ranging", "news", "risk_off"},
    }[context_type]
    if value not in allowed:
        raise ValueErrorForApi(f"{context_type} value must be one of: {', '.join(sorted(allowed))}")


def validate_regime_overlays(overlays: list[str]) -> None:
    allowed = {"expansion", "contraction", "high_volatility", "low_volatility"}
    invalid = sorted(set(overlays) - allowed)
    if invalid:
        raise ValueErrorForApi(f"Invalid regime overlays: {', '.join(invalid)}")


def validate_zone_type(zone_type: str, direction: str) -> None:
    allowed = {
        "support": {"bullish"},
        "resistance": {"bearish"},
        "order_block": {"bullish", "bearish"},
        "fvg": {"bullish", "bearish"},
        "consolidation": {"neutral"},
        "liquidity_pool": {"bullish", "bearish", "neutral"},
    }
    if zone_type not in allowed:
        raise ValueErrorForApi(f"zone_type must be one of: {', '.join(sorted(allowed))}")
    if direction not in allowed[zone_type]:
        valid_directions = ", ".join(sorted(allowed[zone_type]))
        raise ValueErrorForApi(f"direction for {zone_type} must be one of: {valid_directions}")
