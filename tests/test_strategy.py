from __future__ import annotations

import unittest
from dataclasses import replace

from semi_bot_trading.config import StrategyConfig
from semi_bot_trading.strategy import build_setup_candidates, classify_zone_reaction


def candle(time: str, open_: float, high: float, low: float, close: float) -> dict[str, object]:
    return {
        "time": f"2026-01-01T{time}:00+00:00",
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": 100,
    }


def zone(zone_type: str, direction: str, low: float, high: float, zone_id: str = "z1") -> dict[str, object]:
    return {
        "id": zone_id,
        "type": zone_type,
        "direction": direction,
        "detector": "test",
        "status": "active",
        "source": "bot",
        "price_low": low,
        "price_high": high,
        "visual_start": "2026-01-01T00:00:00+00:00",
        "visual_end": None,
        "valid_from": "2026-01-01T00:00:00+00:00",
        "valid_until": None,
        "invalidated_at": None,
        "invalidated_by_structure_point_id": None,
        "detected_at": "2026-01-01T00:00:00+00:00",
        "weight": 0.8,
        "confidence": 0.8,
        "metadata": {},
    }


def contexts(bias: str = "bullish", regime: str = "trending", secondary: str | None = None) -> dict[str, dict[str, dict[str, object]]]:
    return {
        "H1": {
            "bias": {
                "effective_value": bias,
                "secondary_value": secondary,
                "metadata": {},
            },
            "regime": {
                "effective_value": regime,
                "secondary_value": "expansion" if regime == "trending" else None,
                "metadata": {"overlays": ["expansion"] if regime == "trending" else []},
            },
        }
    }


def point(point_type: str, direction: str, time: str = "00:45", point_id: str = "p1") -> dict[str, object]:
    return {
        "id": point_id,
        "time": f"2026-01-01T{time}:00+00:00",
        "type": point_type,
        "price": 101,
        "detector": "price_action_v1",
        "status": "confirmed",
        "confidence": 1,
        "direction": direction,
        "related_zone_ids": [],
        "metadata": {"direction": direction},
    }


CONFIG = StrategyConfig(
    timeframe="M15",
    atr_period=3,
    approach_atr_multiplier=0.5,
    breakout_buffer_atr_multiplier=0.15,
    waiting_candles=4,
    min_risk_reward=2.0,
    max_eligible=3,
    max_waiting=5,
    trend_pullback_fvg_min_width_atr=1.5,
    trend_pullback_fvg_max_width_atr=4.0,
)


class StrategyTest(unittest.TestCase):
    def test_support_breakdown_close_below_buffer(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 112, 113, 100, 100.5),
        ]

        reaction = classify_zone_reaction(zone("support", "bullish", 105, 107), candles, atr=4, config=CONFIG)

        self.assertEqual("breakout_confirmed", reaction.state)

    def test_support_close_inside_waits(self) -> None:
        candles = [candle("00:30", 108, 109, 104, 106)]

        reaction = classify_zone_reaction(zone("support", "bullish", 105, 107), candles, atr=4, config=CONFIG)

        self.assertEqual("inside_wait", reaction.state)

    def test_support_rejection(self) -> None:
        candles = [candle("00:30", 108, 110, 104, 108.5)]

        reaction = classify_zone_reaction(zone("support", "bullish", 105, 107), candles, atr=4, config=CONFIG)

        self.assertEqual("rejected", reaction.state)

    def test_trend_pullback_eligible_with_rejection_and_pa(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 112, 113, 104, 108.5),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bullish", "trending"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
        )

        self.assertTrue(any(candidate["playbook"] == "trend_pullback" and candidate["status"] == "eligible" for candidate in candidates))

    def test_old_price_action_before_zone_reaction_does_not_confirm_entry(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 112, 113, 104, 108.5),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bullish", "trending"),
            candles,
            [point("pinbar_bullish", "up", "00:15")],
            CONFIG,
        )

        trend = next(candidate for candidate in candidates if candidate["playbook"] == "trend_pullback")
        self.assertEqual("waiting_confirmation", trend["status"])

    def test_fvg_fill_go_waits_when_close_inside(self) -> None:
        candles = [candle("00:30", 108, 109, 104, 106)]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("fvg", "bullish", 105, 107)],
            contexts("bullish", "trending"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
        )

        fvg = next(candidate for candidate in candidates if candidate["playbook"] == "fvg_fill_go")
        self.assertEqual("waiting_confirmation", fvg["status"])

    def test_trend_pullback_blocks_fvg_that_is_too_narrow(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 112, 113, 106, 108.5),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("fvg", "bullish", 106.5, 107.0)],
            contexts("bullish", "trending"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
            allowed_playbooks={"trend_pullback"},
        )

        trend = next(candidate for candidate in candidates if candidate["playbook"] == "trend_pullback")
        self.assertEqual("blocked", trend["status"])
        self.assertIn("below Trend Pullback minimum", " ".join(trend["blocked_reason"]))

    def test_allowed_playbooks_filters_candidates_before_ranking(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 112, 113, 104, 108.5),
        ]

        trend_only = build_setup_candidates(
            "XAUUSD",
            [zone("fvg", "bullish", 105, 107)],
            contexts("bullish", "trending"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
            allowed_playbooks={"trend_pullback"},
        )
        fvg_only = build_setup_candidates(
            "XAUUSD",
            [zone("fvg", "bullish", 105, 107)],
            contexts("bullish", "trending"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
            allowed_playbooks={"fvg_fill_go"},
        )

        self.assertEqual({"trend_pullback"}, {candidate["playbook"] for candidate in trend_only})
        self.assertEqual({"fvg_fill_go"}, {candidate["playbook"] for candidate in fvg_only})

    def test_countertrend_sweep_blocks_without_secondary_bias(self) -> None:
        candles = [candle("00:30", 108, 110, 104, 104.5)]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("liquidity_pool", "neutral", 105, 107)],
            contexts("bearish", "ranging"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
        )

        self.assertTrue(any(candidate["playbook"] == "liquidity_sweep_reversal" and candidate["status"] == "blocked" for candidate in candidates))

    def test_failed_breakout_trap_does_not_also_emit_breakout_retest(self) -> None:
        candles = [candle("00:30", 106, 112, 104, 108)]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("consolidation", "neutral", 100, 110)],
            contexts("neutral", "ranging"),
            candles,
            [point("pinbar_bearish", "down", "00:30")],
            CONFIG,
        )
        playbooks = {candidate["playbook"] for candidate in candidates}

        self.assertIn("failed_breakout_trap", playbooks)
        self.assertNotIn("breakout_retest", playbooks)

    def test_rr_below_config_minimum_blocks_candidate(self) -> None:
        strict_config = replace(CONFIG, min_risk_reward=2.5)
        candles = [candle("00:30", 112, 113, 104, 108.5)]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bullish", "trending"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            strict_config,
        )

        self.assertTrue(any(candidate["status"] == "blocked" and "RR" in " ".join(candidate["blocked_reason"]) for candidate in candidates))


if __name__ == "__main__":
    unittest.main()
