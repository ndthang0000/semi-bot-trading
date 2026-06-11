from __future__ import annotations

import unittest

from semi_bot_trading.zone_materializer import dedupe_materialized_sr_zones
from semi_bot_trading.zones import PriceZone, SR_DETECTOR


def sr_zone(
    zone_id_seed: str,
    low: float,
    high: float,
    weight: float,
    status: str = "active",
    swing_times: list[str] | None = None,
    seen_count: int = 1,
) -> PriceZone:
    return PriceZone(
        symbol="XAUUSD",
        timeframe="H1",
        detector=SR_DETECTOR,
        zone_type="support",
        direction="bullish",
        price_low=low,
        price_high=high,
        start_time=zone_id_seed,
        end_time=None,
        valid_from=zone_id_seed,
        valid_until=None,
        invalidated_at=None,
        invalidated_by_structure_point_id=None,
        detected_at=zone_id_seed,
        bot_confidence=0.7,
        bot_weight=weight,
        effective_confidence=0.7,
        effective_weight=weight,
        status=status,
        source="bot",
        metadata={
            "swing_point_times": swing_times or [],
            "materialized_first_seen": zone_id_seed,
            "materialized_last_seen": zone_id_seed,
            "materialized_seen_count": seen_count,
        },
    )


class ZoneMaterializerTest(unittest.TestCase):
    def test_dedupe_materialized_sr_keeps_stronger_overlapping_zone(self) -> None:
        weak_duplicate = sr_zone(
            "2025-12-08T15:00:00+00:00",
            4171.93,
            4179.08,
            0.09,
            status="invalidated",
            swing_times=["2025-12-04T05:00:00+00:00", "2025-12-08T15:00:00+00:00"],
            seen_count=10,
        )
        stronger_duplicate = sr_zone(
            "2025-12-09T06:00:00+00:00",
            4167.66,
            4177.31,
            0.26,
            status="invalidated",
            swing_times=["2025-12-04T05:00:00+00:00", "2025-12-09T06:00:00+00:00"],
            seen_count=1,
        )

        deduped = dedupe_materialized_sr_zones([weak_duplicate, stronger_duplicate])

        self.assertEqual(1, len(deduped))
        self.assertEqual(stronger_duplicate.price_low, deduped[0].price_low)
        self.assertEqual(stronger_duplicate.price_high, deduped[0].price_high)
        self.assertEqual(1, deduped[0].metadata["deduped_materialized_zone_count"])
        self.assertIn(weak_duplicate.id, deduped[0].metadata["deduped_materialized_zone_ids"])

    def test_dedupe_materialized_sr_does_not_merge_distant_zones(self) -> None:
        first = sr_zone("2025-12-08T15:00:00+00:00", 4171.93, 4179.08, 0.3)
        second = sr_zone("2025-12-10T10:00:00+00:00", 4185.64, 4191.51, 0.2)

        deduped = dedupe_materialized_sr_zones([first, second])

        self.assertEqual(2, len(deduped))


if __name__ == "__main__":
    unittest.main()
