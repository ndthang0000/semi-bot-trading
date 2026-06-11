from __future__ import annotations

import unittest
from dataclasses import replace

from semi_bot_trading.config import StrategyConfig
from semi_bot_trading.strategy import (
    ReactionResult,
    build_setup_candidates,
    classify_zone_reaction_v2,
    compute_zone_reaction_v2_levels,
)


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
    zone_reaction_v2_enabled=True,
    zone_reaction_v2_allowed_reactions=("reject",),
    zone_reaction_v2_fakeout_max_atr=0.5,
    zone_reaction_v2_reject_body_min_ratio=1.5,
    zone_reaction_v2_reject_avg_body_period=20,
    zone_reaction_v2_slow_min_bars=3,
    zone_reaction_v2_slow_max_bars=8,
    zone_reaction_v2_slow_body_max_ratio=0.8,
    zone_reaction_v2_breakout_min_body_atr=0.8,
    zone_reaction_v2_breakout_min_close_outside_atr=0.75,
    zone_reaction_v2_consolidation_breakout_body_atr=1.2,
    zone_reaction_v2_retest_max_bars=8,
    zone_reaction_v2_rr_minimum=2.0,
    zone_reaction_v2_stop_buffer_atr=0.2,
    zone_reaction_v2_min_stop_price=4.0,
    zone_reaction_v2_min_stop_atr=1.2,
    zone_reaction_v2_max_stop_distance=30.0,
    zone_reaction_v2_require_trigger_for_fakeout=True,
    zone_reaction_v2_fakeout_max_reaction_depth_atr=1.5,
    zone_reaction_v2_allow_neutral_range_trade=True,
    zone_reaction_v2_block_news_or_risk_off=True,
    zone_reaction_v2_confluence_score_bonus=0.08,
)


class StrategyTest(unittest.TestCase):
    def test_zone_reaction_v2_reject_is_runtime_playbook(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 106, 110, 105.5, 109.5),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bullish", "trending"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
        )

        self.assertEqual(["zone_reaction_v2"], [candidate["playbook"] for candidate in candidates])
        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual("reject", candidates[0]["zone_reaction_state"])

    def test_legacy_playbooks_no_longer_emit_candidates(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 106, 110, 105.5, 109.5),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bullish", "trending"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
            allowed_playbooks={"trend_pullback"},
        )

        self.assertEqual([], candidates)

    def test_zone_reaction_v2_fakeout_waits_without_trigger(self) -> None:
        candles = [
            candle("00:00", 108, 109, 107, 108),
            candle("00:15", 108, 108.5, 107.5, 108.1),
            candle("00:30", 106, 108, 104, 106.5),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bullish", "trending"),
            candles,
            [],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("zone_reaction_v2", candidates[0]["playbook"])
        self.assertEqual("waiting_confirmation", candidates[0]["status"])
        self.assertEqual("fakeout", candidates[0]["zone_reaction_state"])
        self.assertEqual("fakeout", candidates[0]["metadata"]["reaction_v2"])
        self.assertEqual(1, candidates[0]["metadata"]["confluence_count"])
        self.assertIn("Fakeout requires M15 trigger", " ".join(candidates[0]["reason"]))

    def test_zone_reaction_v2_fakeout_with_trigger_stays_waiting_in_reject_only_phase(self) -> None:
        candles = [
            candle("00:00", 108, 109, 107, 108),
            candle("00:15", 108, 108.5, 107.5, 108.1),
            candle("00:30", 106, 108, 104, 106.5),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bullish", "trending"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("waiting_confirmation", candidates[0]["status"])
        self.assertEqual("fakeout", candidates[0]["zone_reaction_state"])
        self.assertIn("reject-only", " ".join(candidates[0]["reason"]))
        self.assertGreaterEqual(candidates[0]["entry"] - candidates[0]["stop_loss"], 4.0)

    def test_zone_reaction_v2_deep_fakeout_waits_even_with_trigger(self) -> None:
        config = replace(CONFIG, zone_reaction_v2_fakeout_max_reaction_depth_atr=0.2)
        candles = [
            candle("00:00", 108, 109, 107, 108),
            candle("00:15", 108, 108.5, 107.5, 108.1),
            candle("00:30", 106, 108, 104, 106.5),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bullish", "trending"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            config,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("waiting_confirmation", candidates[0]["status"])
        self.assertEqual("fakeout", candidates[0]["zone_reaction_state"])
        self.assertIn("Fakeout wick is too deep", " ".join(candidates[0]["reason"]))

    def test_zone_reaction_v2_excludes_order_block(self) -> None:
        candles = [candle("00:30", 106, 108, 104, 106.5)]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("order_block", "bullish", 105, 107)],
            contexts("bullish", "trending"),
            candles,
            [],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual([], candidates)

    def test_zone_reaction_v2_blocks_news_regime(self) -> None:
        candles = [candle("00:30", 106, 108, 104, 106.5)]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bullish", "news"),
            candles,
            [],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("blocked", candidates[0]["status"])
        self.assertIn("Regime news blocks", " ".join(candidates[0]["blocked_reason"]))

    def test_zone_reaction_v2_excludes_consolidation_to_avoid_overtrading(self) -> None:
        candles = [candle("00:30", 103, 107, 99, 101)]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("consolidation", "neutral", 100, 110)],
            contexts("neutral", "ranging"),
            candles,
            [],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual([], candidates)

    def test_zone_reaction_v2_clean_break_against_bias_is_transition_blocked(self) -> None:
        candles = [
            candle("00:00", 108, 109, 107, 108),
            candle("00:15", 108, 108.5, 107.5, 108.1),
            candle("00:30", 106, 106.5, 99, 100),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bullish", "trending"),
            candles,
            [],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("blocked", candidates[0]["status"])
        self.assertEqual("clean_breakout", candidates[0]["zone_reaction_state"])
        self.assertEqual("transition_bearish", candidates[0]["metadata"]["bias_phase"])

    def test_zone_reaction_v2_clean_break_with_bias_waits_for_retest(self) -> None:
        candles = [
            candle("00:00", 108, 109, 107, 108),
            candle("00:15", 108, 108.5, 107.5, 108.1),
            candle("00:30", 106, 106.5, 99, 100),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bearish", "trending"),
            candles,
            [],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("waiting_confirmation", candidates[0]["status"])
        self.assertEqual("clean_breakout", candidates[0]["zone_reaction_state"])

    def test_zone_reaction_v2_clean_break_requires_one_atr_close_outside_zone(self) -> None:
        candles = [
            candle("00:00", 108, 109, 107, 108),
            candle("00:15", 108, 108.5, 107.5, 108.1),
            candle("00:30", 107.5, 107.8, 101, 104),
        ]

        reaction = classify_zone_reaction_v2(zone("support", "bullish", 105, 107), candles, atr=2, config=CONFIG)

        self.assertNotEqual("clean_breakout", reaction.state)
        self.assertEqual("waiting_bos", reaction.state)

    def test_zone_reaction_v2_breakout_retest_reject_stays_waiting_in_reject_only_phase(self) -> None:
        candles = [
            candle("00:00", 108, 109, 107, 108),
            candle("00:15", 108, 108.5, 107.5, 108.1),
            candle("00:30", 106, 106.5, 97, 98),
            candle("00:45", 98, 106.2, 97.5, 103),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bearish", "trending"),
            candles,
            [],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("waiting_confirmation", candidates[0]["status"])
        self.assertEqual("retest_reject", candidates[0]["zone_reaction_state"])
        self.assertEqual("short", candidates[0]["direction"])
        self.assertIn("WAITING_RETEST", candidates[0]["metadata"]["state_machine_path"])

    def test_zone_reaction_v2_retest_stop_uses_retest_wick_not_full_zone(self) -> None:
        entry, stop, take_profit, rr = compute_zone_reaction_v2_levels(
            zone("support", "bullish", 105, 150),
            "short",
            ReactionResult(
                state="retest_reject",
                direction="short",
                touched=True,
                candle_time="2026-01-01T00:45:00+00:00",
                reason=[],
                metadata={"reaction_high": 106, "reaction_low": 97.5},
            ),
            last_close=103,
            atr=4,
            config=CONFIG,
        )

        self.assertEqual(103, entry)
        self.assertEqual(107.8, stop)
        self.assertEqual([93.4], take_profit)
        self.assertEqual(2.0, rr)

    def test_zone_reaction_v2_blocks_stop_distance_above_max(self) -> None:
        candles = [
            candle("00:00", 108, 109, 107, 108),
            candle("00:15", 108, 108.5, 107.5, 108.1),
            candle("00:30", 106, 106.5, 97, 98),
            candle("00:45", 98, 106.2, 60, 103),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bearish", "trending"),
            candles,
            [],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("blocked", candidates[0]["status"])
        self.assertIn("Stop distance", " ".join(candidates[0]["blocked_reason"]))

    def test_zone_reaction_v2_detects_slow_reaction(self) -> None:
        candles = [
            candle("00:00", 106, 106.4, 105.4, 106.1),
            candle("00:15", 106.1, 106.5, 105.5, 106.0),
            candle("00:30", 106.0, 106.3, 105.6, 106.1),
        ]

        reaction = classify_zone_reaction_v2(zone("support", "bullish", 105, 107), candles, atr=4, config=CONFIG)

        self.assertEqual("slow_reaction", reaction.state)
        self.assertEqual("long", reaction.direction)

    def test_zone_reaction_v2_waiting_bos_becomes_eligible_after_trigger(self) -> None:
        candles = [candle("00:30", 106, 107.5, 105.5, 106.4)]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bullish", "trending"),
            candles,
            [point("BOS", "up", "00:30")],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("waiting_confirmation", candidates[0]["status"])
        self.assertEqual("waiting_bos", candidates[0]["zone_reaction_state"])

if __name__ == "__main__":
    unittest.main()
