from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, replace
from sqlite3 import Connection

from .config import AppConfig
from .smc_zones import FVG_DETECTOR, detect_smc_zones
from .structure import CandleView, StructurePoint, detect_swing_structure
from .zones import (
    SR_DETECTOR,
    CandleSlice,
    PriceZone,
    SwingPoint,
    apply_lifecycle_to_zones,
    detect_support_resistance_zones,
    load_candle_slices,
    replace_price_zones,
)


@dataclass
class MaterializedZone:
    zone: PriceZone
    first_seen: str
    last_seen: str
    seen_count: int


def materialize_incremental_zones(
    conn: Connection,
    config: AppConfig,
    symbol: str,
    timeframe: str,
    limit: int | None = None,
    detectors: set[str] | None = None,
    progress_every: int = 0,
) -> dict[str, int]:
    """Persist zones from the same closed-candle snapshot logic used by backtest.

    Normal detector commands store only the latest global detector output. This
    materializer walks the H1 timeline and records when a zone first/last appears
    in point-in-time snapshots, so realtime mode can render historical bot zones
    without using future information.
    """

    wanted = detectors or {SR_DETECTOR, FVG_DETECTOR}
    candles = load_candle_slices(conn, symbol, timeframe)
    if limit and limit > 0:
        candles = candles[-limit:]
    if not candles:
        return {detector: 0 for detector in wanted}

    views = [CandleView(open_time=c.open_time, high=c.high, low=c.low, close=c.close) for c in candles]
    swing_config = config.swing_for(timeframe)
    structure_swings = sorted(
        detect_swing_structure(views, symbol, timeframe, swing_config.window, swing_config.tolerance),
        key=lambda point: (point_confirmed_at(point), point.event_time, point.id),
    )
    confirm_times = [point_confirmed_at(point) for point in structure_swings]

    materialized: dict[str, MaterializedZone] = {}
    snapshot_candles = min(config.smc_zones.max_candles, config.backtest.zone_snapshot_candles)
    if snapshot_candles <= 0:
        snapshot_candles = config.backtest.zone_snapshot_candles
    final_time = candles[-1].open_time

    for slice_end in range(1, len(candles) + 1):
        as_of = candles[slice_end - 1].open_time
        window_start = max(0, slice_end - snapshot_candles)
        window_start_time = candles[window_start].open_time
        available_slices = candles[window_start:slice_end]
        available_swings = [
            point
            for point in structure_swings[: bisect_right(confirm_times, as_of)]
            if point.metadata.get("swing_type") in {"high", "low"} and point.event_time >= window_start_time
        ]
        zone_swings = structure_points_to_zone_swings(available_swings)
        if not available_slices or not zone_swings:
            continue

        snapshot: list[PriceZone] = []
        if SR_DETECTOR in wanted:
            snapshot.extend(
                detect_incremental_sr_zones(
                    config,
                    symbol,
                    timeframe,
                    available_slices,
                    zone_swings,
                )
            )
        if FVG_DETECTOR in wanted:
            snapshot.extend(
                detect_incremental_fvg_zones(
                    config,
                    symbol,
                    timeframe,
                    available_slices,
                    zone_swings,
                )
            )

        for zone in snapshot:
            if zone.detector not in wanted or zone.status != "active":
                continue
            previous = materialized.get(zone.id)
            if previous is None:
                materialized[zone.id] = MaterializedZone(zone=zone, first_seen=as_of, last_seen=as_of, seen_count=1)
            else:
                previous.zone = merge_zone_state(previous.zone, zone)
                previous.last_seen = as_of
                previous.seen_count += 1

        if progress_every > 0 and slice_end % progress_every == 0:
            print(f"Materialize zones progress: {slice_end}/{len(candles)} candles, zones={len(materialized)}")

    zones_by_detector: dict[str, list[PriceZone]] = {detector: [] for detector in wanted}
    for item in materialized.values():
        zones_by_detector.setdefault(item.zone.detector, []).append(finalize_materialized_zone(item, final_time))

    counts: dict[str, int] = {}
    for detector, zones in zones_by_detector.items():
        if detector == SR_DETECTOR:
            zones = dedupe_materialized_sr_zones(zones)
        zones.sort(key=lambda zone: (zone.detected_at, zone.id))
        counts[detector] = replace_price_zones(conn, symbol, timeframe, detector, zones)
    return counts


def dedupe_materialized_sr_zones(zones: list[PriceZone]) -> list[PriceZone]:
    """Collapse near-identical SR rows created by rolling snapshot materialization.

    Incremental SR snapshots can move the same conceptual cluster by a few ticks
    because ATR/window/lifecycle inputs change candle by candle. PriceZone.id is
    intentionally price-bound based, so those tiny boundary changes become
    different DB rows unless we merge them before persisting realtime zones.
    """

    kept: list[PriceZone] = []
    for zone in sorted(zones, key=materialized_sr_rank, reverse=True):
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(kept)
                if is_duplicate_materialized_sr_zone(zone, existing)
            ),
            None,
        )
        if duplicate_index is None:
            kept.append(zone)
            continue
        kept[duplicate_index] = merge_materialized_duplicates(kept[duplicate_index], zone)
    return kept


def materialized_sr_rank(zone: PriceZone) -> tuple[int, float, int, float, str]:
    seen_count = int(zone.metadata.get("materialized_seen_count") or 0)
    # Prefer the strongest, most persistent row; if tied, keep the tighter zone.
    return (
        1 if zone.status == "active" else 0,
        zone.effective_weight,
        seen_count,
        -zone_width(zone),
        zone.detected_at,
    )


def is_duplicate_materialized_sr_zone(candidate: PriceZone, existing: PriceZone) -> bool:
    if candidate.detector != SR_DETECTOR or existing.detector != SR_DETECTOR:
        return False
    if (
        candidate.symbol,
        candidate.timeframe,
        candidate.zone_type,
        candidate.direction,
    ) != (
        existing.symbol,
        existing.timeframe,
        existing.zone_type,
        existing.direction,
    ):
        return False
    if same_swing_cluster(candidate, existing):
        return True

    overlap_ratio = zone_overlap_ratio(candidate, existing)
    center_distance = abs(zone_center(candidate) - zone_center(existing))
    max_width = max(zone_width(candidate), zone_width(existing), 0.00001)
    return overlap_ratio >= 0.70 or center_distance <= max_width * 0.65


def same_swing_cluster(left: PriceZone, right: PriceZone) -> bool:
    left_times = set(metadata_list(left, "swing_point_times"))
    right_times = set(metadata_list(right, "swing_point_times"))
    if not left_times or not right_times:
        return False
    return left_times == right_times or len(left_times & right_times) >= min(len(left_times), len(right_times))


def metadata_list(zone: PriceZone, key: str) -> list[object]:
    value = zone.metadata.get(key)
    return list(value) if isinstance(value, list) else []


def zone_width(zone: PriceZone) -> float:
    return max(zone.price_high - zone.price_low, 0.0)


def zone_center(zone: PriceZone) -> float:
    return (zone.price_low + zone.price_high) / 2


def zone_overlap_ratio(left: PriceZone, right: PriceZone) -> float:
    overlap = max(min(left.price_high, right.price_high) - max(left.price_low, right.price_low), 0.0)
    smaller_width = max(min(zone_width(left), zone_width(right)), 0.00001)
    return overlap / smaller_width


def merge_materialized_duplicates(primary: PriceZone, duplicate: PriceZone) -> PriceZone:
    duplicate_ids = list(primary.metadata.get("deduped_materialized_zone_ids") or [])
    duplicate_ids.append(duplicate.id)
    duplicate_count = int(primary.metadata.get("deduped_materialized_zone_count") or 0) + 1
    first_seen = min(
        str(primary.metadata.get("materialized_first_seen") or primary.detected_at),
        str(duplicate.metadata.get("materialized_first_seen") or duplicate.detected_at),
    )
    last_seen = max(
        str(primary.metadata.get("materialized_last_seen") or primary.detected_at),
        str(duplicate.metadata.get("materialized_last_seen") or duplicate.detected_at),
    )
    seen_count = int(primary.metadata.get("materialized_seen_count") or 0) + int(
        duplicate.metadata.get("materialized_seen_count") or 0
    )
    metadata = {
        **primary.metadata,
        "materialized_first_seen": first_seen,
        "materialized_last_seen": last_seen,
        "materialized_seen_count": seen_count,
        "deduped_materialized_zone_count": duplicate_count,
        "deduped_materialized_zone_ids": duplicate_ids,
    }
    return replace(
        primary,
        metadata=metadata,
        effective_weight=max(primary.effective_weight, duplicate.effective_weight),
        effective_confidence=max(primary.effective_confidence, duplicate.effective_confidence),
    )


def detect_incremental_sr_zones(
    config: AppConfig,
    symbol: str,
    timeframe: str,
    candles: list[CandleSlice],
    swings: list[SwingPoint],
) -> list[PriceZone]:
    sr = config.support_resistance
    lifecycle = config.zone_lifecycle
    reaction = config.zone_reaction
    decay = config.zone_decay
    zones = detect_support_resistance_zones(
        swings[-sr.lookback_swings :],
        symbol,
        timeframe,
        sr.tolerance_pct,
        sr.min_zone_width,
        sr.min_touches,
        sr.max_zones,
        candles,
        sr.atr_width_multiplier,
        candidate_close_break_buffer=lifecycle.close_break_buffer,
        candidate_close_break_buffer_atr_multiplier=lifecycle.close_break_buffer_atr_multiplier,
    )
    return apply_lifecycle_to_zones(
        zones,
        candles,
        lifecycle.close_break_buffer,
        lifecycle.recent_touch_lookback_candles,
        lifecycle.age_decay_per_100_candles,
        lifecycle.freshness_bonus,
        lifecycle.invalidation_weight_multiplier,
        lifecycle.close_break_buffer_atr_multiplier,
        reaction.reaction_window_candles,
        reaction.min_reaction_atr,
        reaction.strong_reaction_atr,
        reaction.recent_reaction_count,
        decay.max_healthy_touches,
        decay.weak_touch_penalty,
        decay.too_many_touches_penalty,
        decay.linger_penalty,
        lifecycle.false_break_refine_enabled,
        lifecycle.false_break_refine_max_width_atr_multiplier,
        lifecycle.false_break_parent_weight_multiplier,
    )


def detect_incremental_fvg_zones(
    config: AppConfig,
    symbol: str,
    timeframe: str,
    candles: list[CandleSlice],
    swings: list[SwingPoint],
) -> list[PriceZone]:
    smc = config.smc_zones
    detected = detect_smc_zones(
        candles,
        swings[-smc.lookback_swings :],
        symbol,
        timeframe,
        fvg_middle_candle_atr_multiplier=smc.fvg_middle_candle_atr_multiplier,
        fvg_gap_atr_ratio=smc.fvg_gap_atr_ratio,
        fvg_min_width_atr_ratio=smc.fvg_min_width_atr_ratio,
        fvg_max_width_atr_ratio=smc.fvg_max_width_atr_ratio,
        fvg_third_candle_follow_through_required=smc.fvg_third_candle_follow_through_required,
        fvg_third_candle_min_body_ratio=smc.fvg_third_candle_min_body_ratio,
        fvg_max_active_days=smc.fvg_max_active_days_for(timeframe),
        fvg_decay_start_days=smc.fvg_decay_start_days_for(timeframe),
        max_fvg_zones=smc.max_fvg_zones,
        max_order_block_zones=0,
        max_liquidity_zones=0,
        max_consolidation_zones=0,
    )
    return detected.get(FVG_DETECTOR, [])


def merge_zone_state(old: PriceZone, new: PriceZone) -> PriceZone:
    metadata = {**old.metadata, **new.metadata}
    return replace(
        new,
        metadata=metadata,
        effective_weight=max(old.effective_weight, new.effective_weight),
        effective_confidence=max(old.effective_confidence, new.effective_confidence),
    )


def finalize_materialized_zone(item: MaterializedZone, final_time: str) -> PriceZone:
    metadata = {
        **item.zone.metadata,
        "materialized_from_incremental_snapshots": True,
        "materialized_first_seen": item.first_seen,
        "materialized_last_seen": item.last_seen,
        "materialized_seen_count": item.seen_count,
    }
    if item.last_seen >= final_time:
        return replace(item.zone, metadata=metadata)

    status = "expired" if item.zone.detector == FVG_DETECTOR else "invalidated"
    metadata["materialized_end_reason"] = "not_active_in_later_snapshot"
    return replace(
        item.zone,
        status=status,
        end_time=item.zone.end_time or item.last_seen,
        valid_until=item.zone.valid_until or item.last_seen,
        invalidated_at=item.zone.invalidated_at or (item.last_seen if status == "invalidated" else None),
        effective_weight=round(item.zone.effective_weight * 0.75, 4),
        effective_confidence=round(item.zone.effective_confidence * 0.90, 4),
        metadata=metadata,
    )


def point_confirmed_at(point: StructurePoint) -> str:
    return str(point.metadata.get("confirmed_at", point.event_time))


def structure_points_to_zone_swings(points: list[StructurePoint]) -> list[SwingPoint]:
    swings: list[SwingPoint] = []
    for point in points:
        swing_type = point.metadata.get("swing_type")
        if swing_type not in {"high", "low"}:
            continue
        swings.append(
            SwingPoint(
                id=point.id,
                point_type=point.point_type,
                price=point.price,
                event_time=point.event_time,
                swing_type=str(swing_type),
            )
        )
    return swings
