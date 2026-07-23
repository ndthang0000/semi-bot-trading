from __future__ import annotations

import unittest
from dataclasses import replace

from semi_bot_trading.config import StrategyConfig
from semi_bot_trading.strategy import (
    ReactionResult,
    build_setup_candidates,
    classify_zone_reaction_v2,
    compute_sr_breakout_v1_levels,
    compute_zone_reaction_v2_levels,
    evaluate_zone_reaction_v2,
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
        "valid_until": "2027-01-01T00:00:00+00:00",
        "invalidated_at": None,
        "invalidated_by_structure_point_id": None,
        "detected_at": "2026-01-01T00:00:00+00:00",
        "weight": 0.8,
        "confidence": 0.8,
        "metadata": {},
    }


def contexts(
    bias: str = "bullish",
    regime: str = "trending",
    secondary: str | None = None,
    macro_trend: str | None = None,
) -> dict[str, dict[str, dict[str, object]]]:
    result: dict[str, dict[str, dict[str, object]]] = {
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
    if macro_trend is not None:
        result["H1"]["macro_trend"] = {
            "effective_value": macro_trend,
            "secondary_value": None,
            "metadata": {},
        }
    return result


def point(point_type: str, direction: str, time: str = "00:45", point_id: str = "p1") -> dict[str, object]:
    return {
        "id": point_id,
        "time": f"2026-01-01T{time}:00+00:00",
        "type": point_type,
        "point_type": point_type,
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
    zone_reaction_v2_allowed_reactions=("reject", "internal_reject"),
    zone_reaction_v2_fakeout_max_atr=0.5,
    zone_reaction_v2_reject_body_min_ratio=1.5,
    zone_reaction_v2_reject_avg_body_period=20,
    zone_reaction_v2_reject_pinbar_enabled=True,
    zone_reaction_v2_reject_pinbar_wick_body_ratio=2.0,
    zone_reaction_v2_reject_pinbar_min_wick_ratio=0.55,
    zone_reaction_v2_slow_min_bars=3,
    zone_reaction_v2_slow_max_bars=8,
    zone_reaction_v2_slow_body_max_ratio=0.8,
    zone_reaction_v2_reject_stop_mode="zone",
    zone_reaction_v2_rr_minimum=2.0,
    zone_reaction_v2_stop_buffer_atr=0.2,
    zone_reaction_v2_min_stop_price=4.0,
    zone_reaction_v2_min_stop_atr=1.5,
    zone_reaction_v2_max_stop_distance=30.0,
    zone_reaction_v2_reject_wide_stop_fallback="atr",
    zone_reaction_v2_reject_atr_stop=1.2,
    zone_reaction_v2_impulse_limit_range_atr=4.0,
    zone_reaction_v2_impulse_limit_extension_atr=1.0,
    zone_reaction_v2_impulse_limit_expiry_bars=8,
    zone_reaction_v2_require_trigger_for_fakeout=True,
    zone_reaction_v2_fakeout_max_reaction_depth_atr=1.5,
    zone_reaction_v2_internal_reject_enabled=True,
    zone_reaction_v2_internal_reject_requires_structure=True,
    zone_reaction_v2_internal_reject_sr_requires_structure=False,
    zone_reaction_v2_internal_reject_requires_price_action=True,
    zone_reaction_v2_internal_reject_watch_after_fvg_fill_bars=8,
    zone_reaction_v2_internal_reject_body_min_ratio=0.0,
    zone_reaction_v2_internal_reject_min_fill_ratio=0.5,
    zone_reaction_v2_internal_reject_deep_fvg_fill_ratio=0.8,
    zone_reaction_v2_allow_neutral_range_trade=True,
    zone_reaction_v2_block_news_or_risk_off=True,
    zone_reaction_v2_macro_gate_enabled=True,
    zone_reaction_v2_fvg_macro_gate_enabled=True,
    zone_reaction_v2_fvg_max_trades_per_zone=2,
    zone_reaction_v2_confluence_score_bonus=0.08,
    sr_breakout_v1_enabled=True,
    sr_breakout_v1_allowed_entries=("breakout_close", "retest_breakout"),
    sr_breakout_v1_allow_bot_sr_breakout=False,
    sr_breakout_v1_breakout_buffer_atr=0.15,
    sr_breakout_v1_market_entry_max_distance_atr=0.5,
    sr_breakout_v1_retest_max_bars=8,
    sr_breakout_v1_min_body_atr=0.5,
    sr_breakout_v1_sl_mode="atr",
    sr_breakout_v1_sl_zone_buffer_atr=0.2,
    sr_breakout_v1_sl_min_atr=0.6,
    sr_breakout_v1_sl_atr=1.5,
    sr_breakout_v1_rr=2.0,
    sr_breakout_v1_max_stop_distance=60.0,
)


class StrategyTest(unittest.TestCase):
    def test_bearish_strong_reject_requires_bearish_candle_body(self) -> None:
        candles = [
            candle("00:00", 4200, 4202, 4199, 4201),
            candle("00:15", 4201, 4203, 4200, 4202),
            candle("00:30", 4201.003, 4221.317, 4200.754, 4211.77),
        ]

        reaction = classify_zone_reaction_v2(
            zone("resistance", "bearish", 4215.48, 4239.33),
            candles,
            atr=11.8,
            config=CONFIG,
        )

        self.assertNotEqual("reject", reaction.state)
        self.assertEqual("waiting_bos", reaction.state)
        self.assertTrue(reaction.metadata.get("wick_reject"))

    def test_bearish_wick_reject_confirms_after_next_bearish_break(self) -> None:
        candles = [
            candle("00:00", 4200, 4202, 4199, 4201),
            candle("00:15", 4201, 4203, 4200, 4202),
            candle("00:30", 4201.003, 4221.317, 4200.754, 4211.77),
            candle("00:45", 4211.5, 4212.0, 4198.5, 4199.0),
        ]

        reaction = classify_zone_reaction_v2(
            zone("resistance", "bearish", 4215.48, 4239.33),
            candles,
            atr=11.8,
            config=CONFIG,
        )

        self.assertEqual("reject", reaction.state)
        self.assertEqual("short", reaction.direction)
        self.assertTrue(reaction.metadata.get("wick_reject_confirmed"))

    def test_bearish_strong_reject_accepts_bearish_candle_body(self) -> None:
        candles = [
            candle("00:00", 4200, 4202, 4199, 4201),
            candle("00:15", 4201, 4203, 4200, 4202),
            candle("00:30", 4220.0, 4221.317, 4200.754, 4211.77),
        ]

        reaction = classify_zone_reaction_v2(
            zone("resistance", "bearish", 4215.48, 4239.33),
            candles,
            atr=11.8,
            config=CONFIG,
        )

        self.assertEqual("reject", reaction.state)
        self.assertEqual("short", reaction.direction)

    def test_bullish_strong_reject_requires_bullish_candle_body(self) -> None:
        candles = [
            candle("00:00", 4200, 4202, 4199, 4201),
            candle("00:15", 4201, 4203, 4200, 4202),
            candle("00:30", 4211.77, 4221.317, 4190.754, 4201.003),
        ]

        reaction = classify_zone_reaction_v2(
            zone("support", "bullish", 4185, 4200),
            candles,
            atr=11.8,
            config=CONFIG,
        )

        self.assertNotEqual("reject", reaction.state)
        self.assertEqual("waiting_bos", reaction.state)
        self.assertTrue(reaction.metadata.get("wick_reject"))

    def test_bullish_wick_reject_confirms_after_next_bullish_break(self) -> None:
        candles = [
            candle("00:00", 4200, 4202, 4199, 4201),
            candle("00:15", 4201, 4203, 4200, 4202),
            candle("00:30", 4211.77, 4221.317, 4190.754, 4201.003),
            candle("00:45", 4201.5, 4222.0, 4200.0, 4221.5),
        ]

        reaction = classify_zone_reaction_v2(
            zone("support", "bullish", 4185, 4200),
            candles,
            atr=11.8,
            config=CONFIG,
        )

        self.assertEqual("reject", reaction.state)
        self.assertEqual("long", reaction.direction)
        self.assertIn("reaction_avg_body", reaction.metadata)
        self.assertIn("reaction_body_avg_ratio", reaction.metadata)
        self.assertTrue(reaction.metadata.get("wick_reject_confirmed"))

    def test_zone_reaction_v2_carries_recent_reject_after_price_leaves_zone(self) -> None:
        candles = [
            candle("00:00", 110, 112, 109, 111),
            candle("00:15", 111, 113, 110, 112),
            candle("00:30", 112, 113, 100, 108),
            candle("00:45", 108, 116, 107, 115),
            candle("01:00", 125, 126, 124, 125),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 100, 105)],
            contexts(),
            candles,
            [],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual("reject", candidates[0]["zone_reaction_state"])
        self.assertEqual("2026-01-01T00:45:00+00:00", candidates[0]["metadata"]["as_of"])
        self.assertTrue(candidates[0]["metadata"]["carried_forward"])
        self.assertEqual("2026-01-01T01:00:00+00:00", candidates[0]["metadata"]["carried_forward_current_as_of"])

    def test_human_zone_does_not_use_signal_candle_opened_before_zone_activation(self) -> None:
        candles = [
            candle("00:00", 110, 112, 109, 111),
            candle("00:15", 111, 113, 110, 112),
            candle("00:30", 100, 116, 99, 115),
        ]
        human_zone = zone("support", "bullish", 100, 105)
        human_zone.update(
            {
                "detector": "human_manual_v1",
                "source": "human",
                "created_at": "2026-01-01 00:44:17",
                "metadata": {
                    "human_created": True,
                    "last_human_override_at": "2026-01-01T00:44:17+00:00",
                    "trade_modes": ["reject"],
                },
            }
        )

        candidates = build_setup_candidates(
            "XAUUSD",
            [human_zone],
            contexts(),
            candles,
            [],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual([], candidates)

    def test_human_zone_can_use_next_signal_candle_after_zone_activation(self) -> None:
        candles = [
            candle("00:00", 110, 112, 109, 111),
            candle("00:15", 111, 113, 110, 112),
            candle("00:30", 112, 113, 110, 111),
            candle("00:45", 100, 116, 99, 115),
        ]
        human_zone = zone("support", "bullish", 100, 105)
        human_zone.update(
            {
                "detector": "human_manual_v1",
                "source": "human",
                "created_at": "2026-01-01 00:44:17",
                "metadata": {
                    "human_created": True,
                    "last_human_override_at": "2026-01-01T00:44:17+00:00",
                    "trade_modes": ["reject"],
                },
            }
        )

        candidates = build_setup_candidates(
            "XAUUSD",
            [human_zone],
            contexts(),
            candles,
            [],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("2026-01-01T00:45:00+00:00", candidates[0]["metadata"]["as_of"])

    def test_human_zone_adjustment_does_not_reset_signal_activation(self) -> None:
        candles = [
            candle("00:00", 110, 112, 109, 111),
            candle("00:15", 111, 113, 110, 112),
            candle("00:30", 100, 116, 99, 115),
        ]
        human_zone = zone("support", "bullish", 100, 105)
        human_zone.update(
            {
                "detector": "human_manual_v1",
                "source": "human",
                "created_at": "2026-01-01 00:10:00",
                "metadata": {
                    "human_adjusted": True,
                    "human_created": True,
                    "last_human_override_at": "2026-01-01T00:44:17+00:00",
                    "trade_modes": ["reject"],
                },
            }
        )

        candidates = build_setup_candidates(
            "XAUUSD",
            [human_zone],
            contexts(),
            candles,
            [],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("2026-01-01T00:30:00+00:00", candidates[0]["metadata"]["as_of"])

    def test_zone_reaction_v2_impulse_reject_uses_limit_at_zone_high(self) -> None:
        candles = [
            candle("00:00", 110, 112, 109, 111),
            candle("00:15", 111, 113, 110, 112),
            candle("00:30", 100, 151, 100, 118),
        ]
        support = zone("support", "bullish", 100, 105)
        reaction = classify_zone_reaction_v2(support, candles, atr=10, config=CONFIG)

        candidates = evaluate_zone_reaction_v2(
            "XAUUSD",
            support,
            reaction,
            last_close=118,
            atr=10,
            bias="bullish",
            secondary_bias=None,
            regime="trending",
            overlays=set(),
            structure_points=[],
            zones=[support],
            config=CONFIG,
            as_of="2026-01-01T00:30:00+00:00",
        )

        self.assertEqual(1, len(candidates))
        candidate = candidates[0].to_chart()
        self.assertEqual("limit", candidate["metadata"]["order_type"])
        self.assertEqual("impulse_retest_limit", candidate["metadata"]["entry_model"])
        self.assertEqual(105, candidate["entry"])
        self.assertEqual("2026-01-01T02:45:00+00:00", candidate["expires_at"])
        self.assertEqual(8, candidate["metadata"]["impulse_limit_expiry_bars"])
        self.assertGreater(candidate["metadata"]["impulse_limit_range_atr"], 4)
        self.assertGreater(candidate["metadata"]["impulse_limit_extension_atr"], 1)

    def test_zone_reaction_v2_does_not_trade_invalidated_sr_zone(self) -> None:
        candles = [
            candle("00:00", 110, 112, 109, 111),
            candle("00:15", 111, 113, 110, 112),
            candle("00:30", 100, 116, 99, 115),
        ]
        invalidated_support = zone("support", "bullish", 100, 105)
        invalidated_support.update(
            {
                "status": "invalidated",
                "invalidated_at": "2026-01-01T00:15:00+00:00",
                "valid_until": "2026-01-01T00:15:00+00:00",
            }
        )

        candidates = build_setup_candidates(
            "XAUUSD",
            [invalidated_support],
            contexts(),
            candles,
            [],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual([], candidates)

    def test_bullish_strong_reject_accepts_bullish_candle_body(self) -> None:
        candles = [
            candle("00:00", 4200, 4202, 4199, 4201),
            candle("00:15", 4201, 4203, 4200, 4202),
            candle("00:30", 4190.0, 4221.317, 4189.754, 4201.003),
        ]

        reaction = classify_zone_reaction_v2(
            zone("support", "bullish", 4185, 4200),
            candles,
            atr=11.8,
            config=CONFIG,
        )

        self.assertEqual("reject", reaction.state)
        self.assertEqual("long", reaction.direction)
        expected_average = (1.0 + 1.0 + 11.003) / 3
        self.assertAlmostEqual(expected_average, reaction.metadata["reaction_avg_body"], places=5)
        self.assertAlmostEqual(
            11.003 / expected_average,
            reaction.metadata["reaction_body_avg_ratio"],
            places=4,
        )

    def test_m15_price_zone_does_not_create_setup_candidate(self) -> None:
        candles = [
            candle("00:00", 4220, 4222, 4218, 4221),
            candle("00:15", 4221, 4223, 4219, 4222),
            candle("00:30", 4220, 4221.5, 4200.75, 4211.77),
        ]
        m15_zone = {
            **zone("resistance", "bearish", 4215.48, 4239.33),
            "timeframe": "M15",
        }

        candidates = build_setup_candidates(
            symbol="XAUUSD",
            zones=[m15_zone],
            contexts=contexts(bias="bearish", regime="ranging", macro_trend="down"),
            candles=candles,
            structure_points=[],
            config=CONFIG,
            context_timeframe="H1",
        )

        self.assertEqual([], candidates)

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
        self.assertIn("reaction_avg_body", candidates[0]["metadata"])
        self.assertIn("reaction_body_avg_ratio", candidates[0]["metadata"])

    def test_active_sr_zone_without_expiry_is_tradeable(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 106, 110, 105.5, 109.5),
        ]
        support = zone("support", "bullish", 105, 107)
        support["valid_until"] = None

        candidates = build_setup_candidates(
            "XAUUSD",
            [support],
            contexts("bullish", "trending"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual("support", candidates[0]["metadata"]["zone_type"])

    def test_price_near_zone_emits_approaching_watch_state(self) -> None:
        candles = [
            candle("00:00", 110, 111, 109, 110),
            candle("00:15", 110, 110.5, 108.5, 109),
            candle("00:30", 109, 109.2, 107.4, 107.5),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bullish", "trending"),
            candles,
            [],
            CONFIG,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("watching", candidates[0]["status"])
        self.assertEqual("approaching", candidates[0]["zone_reaction_state"])
        steps = {step["key"]: step["status"] for step in candidates[0]["metadata"]["state_machine"]}
        self.assertEqual("active", steps["APPROACHING"])
        self.assertEqual("pending", steps["ZONE_TOUCHED"])

    def test_reject_stop_mode_reaction_wick_tightens_stop(self) -> None:
        from dataclasses import replace

        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 106, 110, 105.5, 109.5),
        ]
        zone_wide = zone("support", "bullish", 95, 107)

        zone_mode = build_setup_candidates(
            "XAUUSD", [zone_wide], contexts("bullish", "trending"), candles,
            [point("pinbar_bullish", "up", "00:30")], CONFIG,
        )
        wick_mode = build_setup_candidates(
            "XAUUSD", [zone_wide], contexts("bullish", "trending"), candles,
            [point("pinbar_bullish", "up", "00:30")],
            replace(CONFIG, zone_reaction_v2_reject_stop_mode="reaction_wick"),
        )

        self.assertEqual("reject", wick_mode[0]["zone_reaction_state"])
        # Zone mode anchors below the whole zone (95), wick mode below the
        # reaction wick (105.5); the min-stop floor still applies to both.
        self.assertLess(zone_mode[0]["stop_loss"], 95.5)
        self.assertGreater(wick_mode[0]["stop_loss"], 100.0)
        self.assertLess(wick_mode[0]["stop_loss"], 105.5)

    def test_zone_reject_stop_falls_back_to_h1_atr_when_wick_stop_is_inside_zone(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 106, 110, 105.5, 109.5),
        ]
        context_candles = [
            candle("01:00", 100, 160, 100, 150),
            candle("02:00", 150, 210, 150, 200),
            candle("03:00", 200, 260, 200, 250),
            candle("04:00", 250, 310, 250, 300),
        ]
        zone_too_wide = zone("support", "bullish", 50, 107)

        candidates = build_setup_candidates(
            "XAUUSD", [zone_too_wide], contexts("bullish", "trending"), candles,
            [point("pinbar_bullish", "up", "00:30")], CONFIG,
            context_candles=context_candles,
        )

        self.assertEqual("reject", candidates[0]["zone_reaction_state"])
        self.assertEqual("atr_fallback", candidates[0]["metadata"]["stop_source"])
        self.assertEqual("H1", candidates[0]["metadata"]["stop_fallback_atr_timeframe"])
        self.assertLess(candidates[0]["stop_loss"], 50.0)

    def test_human_reject_mode_bypasses_macro_gate(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 106, 110, 105.5, 109.5),
        ]
        support = zone("support", "bullish", 105, 107)
        support["metadata"] = {"trade_modes": ["reject"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [support],
            contexts("bullish", "trending", macro_trend="down"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("eligible", candidates[0]["status"])
        self.assertTrue(candidates[0]["metadata"]["context_bypass"])
        self.assertIn("bypasses all context gates", " ".join(candidates[0]["reason"]))

    def test_human_created_zone_with_default_reject_mode_bypasses_macro_gate(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 106, 110, 105.5, 109.5),
        ]
        support = zone("support", "bullish", 105, 107)
        support["source"] = "human"
        support["metadata"] = {"human_created": True}

        candidates = build_setup_candidates(
            "XAUUSD",
            [support],
            contexts("bullish", "trending", macro_trend="down"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("eligible", candidates[0]["status"])
        self.assertTrue(candidates[0]["metadata"]["context_bypass"])
        self.assertIn("bypasses all context gates", " ".join(candidates[0]["reason"]))

    def test_expired_human_zone_does_not_trade(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 106, 110, 105.5, 109.5),
        ]
        support = zone("support", "bullish", 105, 107)
        support["source"] = "human"
        support["metadata"] = {"human_created": True, "trade_modes": ["reject"]}
        support["valid_until"] = "2026-01-01T00:20:00+00:00"

        candidates = build_setup_candidates(
            "XAUUSD",
            [support],
            contexts("bullish", "trending", macro_trend="down"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
        )

        self.assertEqual([], candidates)

    def test_explicit_trade_modes_without_reject_disable_reject(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 106, 110, 105.5, 109.5),
        ]
        support = zone("support", "bullish", 105, 107)
        support["metadata"] = {"trade_modes": ["breakout"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [support],
            contexts("bullish", "trending"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual([], candidates)

    def test_human_breakout_mode_bypasses_macro_for_support_short(self) -> None:
        context_candles = [
            candle("12:00", 104, 106, 102, 105),
            candle("13:00", 105, 107, 103, 104),
            candle("14:00", 104, 105, 101, 102),
            candle("15:00", 102, 103, 96, 97.2),
        ]
        support = zone("support", "bullish", 100, 102)
        support["metadata"] = {"trade_modes": ["breakout"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [support],
            contexts("neutral", "ranging", macro_trend="up"),
            [context_candles[-1]],
            [],
            CONFIG,
            allowed_playbooks={"sr_breakout_v1"},
            context_candles=context_candles,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("short", candidates[0]["direction"])
        self.assertTrue(candidates[0]["metadata"]["context_bypass"])
        self.assertIn("bypasses all context gates", " ".join(candidates[0]["reason"]))

    def test_macro_trend_down_blocks_long_reject(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 106, 110, 105.5, 109.5),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bullish", "trending", macro_trend="down"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("blocked", candidates[0]["status"])
        self.assertIn("Macro trend down blocks", " ".join(candidates[0]["blocked_reason"]))
        self.assertEqual("down", candidates[0]["metadata"]["macro_trend"])

    def test_macro_trend_up_blocks_short_reject(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 109),
            candle("00:15", 109, 111, 107, 108),
            candle("00:30", 114, 114.5, 110, 110.5),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("resistance", "bearish", 113, 115)],
            contexts("bearish", "trending", macro_trend="up"),
            candles,
            [point("pinbar_bearish", "down", "00:30")],
            CONFIG,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("short", candidates[0]["direction"])
        self.assertEqual("blocked", candidates[0]["status"])
        self.assertIn("Macro trend up blocks", " ".join(candidates[0]["blocked_reason"]))

    def test_macro_trend_up_allows_long_reject(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 106, 110, 105.5, 109.5),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bullish", "trending", macro_trend="up"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
        )

        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual("up", candidates[0]["metadata"]["macro_trend"])

    def test_bot_bullish_fvg_allows_long_when_h1_bias_supports_but_macro_opposes(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 106, 110, 105.5, 109.5),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("fvg", "bullish", 105, 107)],
            contexts("bullish", "trending", macro_trend="down"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("eligible", candidates[0]["status"])
        self.assertIn("allowed by H1 bias bullish", " ".join(candidates[0]["reason"]))

    def test_bot_bullish_fvg_allows_long_when_macro_supports_but_h1_bias_opposes(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 106, 110, 105.5, 109.5),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("fvg", "bullish", 105, 107)],
            contexts("bearish", "trending", macro_trend="up"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("eligible", candidates[0]["status"])
        self.assertIn("allowed by macro trend up", " ".join(candidates[0]["reason"]))

    def test_bot_fvg_blocks_when_neither_h1_bias_nor_macro_supports_direction(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 111),
            candle("00:15", 111, 113, 109, 112),
            candle("00:30", 106, 110, 105.5, 109.5),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("fvg", "bullish", 105, 107)],
            contexts("bearish", "trending", macro_trend="down"),
            candles,
            [point("pinbar_bullish", "up", "00:30")],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("blocked", candidates[0]["status"])
        self.assertIn(
            "requires H1 bias bullish or macro trend up",
            " ".join(candidates[0]["blocked_reason"]),
        )

    def test_bot_bearish_fvg_allows_short_when_macro_supports(self) -> None:
        candles = [
            candle("00:00", 110, 112, 108, 109),
            candle("00:15", 109, 111, 107, 108),
            candle("00:30", 114, 114.5, 110, 110.5),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("fvg", "bearish", 113, 115)],
            contexts("bullish", "trending", macro_trend="down"),
            candles,
            [point("pinbar_bearish", "down", "00:30")],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("eligible", candidates[0]["status"])
        self.assertIn("allowed by macro trend down", " ".join(candidates[0]["reason"]))

    def test_missing_macro_trend_context_allows_both_directions(self) -> None:
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

        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual("unknown", candidates[0]["metadata"]["macro_trend"])

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

    def test_zone_reaction_v2_fakeout_with_trigger_stays_waiting_when_disabled(self) -> None:
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
        self.assertIn("keeping it for debug", " ".join(candidates[0]["reason"]))
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

    def test_zone_reaction_v2_broken_support_emits_no_candidate_or_carried_reject(self) -> None:
        candles = [
            candle("00:00", 110, 111, 109, 110),
            candle("00:15", 106, 111, 105.5, 110),
            candle("00:30", 103, 104, 98, 99),
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

        self.assertEqual([], candidates)

    def test_zone_reaction_v2_broken_resistance_emits_no_candidate_or_carried_reject(self) -> None:
        candles = [
            candle("00:00", 98, 99, 97, 98),
            candle("00:15", 101, 101.5, 97, 98),
            candle("00:30", 104, 109, 103, 108),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("resistance", "bearish", 100, 102)],
            contexts("bullish", "trending"),
            candles,
            [],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual([], candidates)

    def test_zone_reaction_v2_wide_stop_does_not_block_when_fallback_is_disabled(self) -> None:
        candles = [
            candle("00:00", 108, 109, 107, 108),
            candle("00:15", 108, 108.5, 107.5, 108.1),
            candle("00:30", 106, 106.5, 97, 98),
            candle("00:45", 98, 111, 60, 109),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bearish", "trending"),
            candles,
            [],
            replace(CONFIG, zone_reaction_v2_reject_wide_stop_fallback="block"),
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual([], candidates[0]["blocked_reason"])
        self.assertNotIn("Stop distance", " ".join(candidates[0]["blocked_reason"]))

    def test_zone_reaction_v2_wide_reject_stop_can_fallback_to_h1_atr(self) -> None:
        candles = [
            candle("00:00", 108, 109, 107, 108),
            candle("00:15", 108, 108.5, 107.5, 108.1),
            candle("00:30", 106, 106.5, 97, 98),
            candle("00:45", 98, 111, 60, 109),
        ]
        context_candles = [
            candle("01:00", 100, 160, 100, 150),
            candle("02:00", 150, 210, 150, 200),
            candle("03:00", 200, 260, 200, 250),
            candle("04:00", 250, 310, 250, 300),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 105, 107)],
            contexts("bearish", "trending"),
            candles,
            [],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
            context_candles=context_candles,
        )

        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual("atr_fallback", candidates[0]["metadata"]["stop_source"])
        self.assertEqual("H1", candidates[0]["metadata"]["stop_fallback_atr_timeframe"])
        self.assertGreater(candidates[0]["metadata"]["stop_fallback_atr"], candidates[0]["metadata"]["atr"])
        expected_distance = max(
            CONFIG.zone_reaction_v2_min_stop_price,
            candidates[0]["metadata"]["atr"] * CONFIG.zone_reaction_v2_min_stop_atr,
            candidates[0]["metadata"]["stop_fallback_atr"] * CONFIG.zone_reaction_v2_reject_atr_stop,
        )
        self.assertAlmostEqual(expected_distance, candidates[0]["entry"] - candidates[0]["stop_loss"], places=4)

    def test_zone_reaction_v2_wide_fvg_stop_falls_back_to_h1_atr(self) -> None:
        candles = [
            candle("00:00", 112, 113, 111, 112),
            candle("00:15", 112, 113, 111, 112),
            candle("00:30", 110, 111, 80, 90),
            candle("00:45", 90, 120, 88, 115),
        ]
        context_candles = [
            candle("01:00", 100, 160, 100, 150),
            candle("02:00", 150, 210, 150, 200),
            candle("03:00", 200, 260, 200, 250),
            candle("04:00", 250, 310, 250, 300),
        ]
        fvg = zone("fvg", "bullish", 80, 107)

        candidates = build_setup_candidates(
            "XAUUSD",
            [fvg],
            contexts("bullish", "ranging"),
            candles,
            [point("pinbar_bullish", "up", "00:45")],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
            context_candles=context_candles,
        )

        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual("atr_fallback", candidates[0]["metadata"]["stop_source"])
        self.assertEqual("H1", candidates[0]["metadata"]["stop_fallback_atr_timeframe"])
        self.assertGreater(candidates[0]["metadata"]["stop_fallback_atr"], candidates[0]["metadata"]["atr"])
        expected_distance = max(
            CONFIG.zone_reaction_v2_min_stop_price,
            candidates[0]["metadata"]["atr"] * CONFIG.zone_reaction_v2_min_stop_atr,
            candidates[0]["metadata"]["stop_fallback_atr"] * CONFIG.zone_reaction_v2_reject_atr_stop,
        )
        self.assertAlmostEqual(expected_distance, candidates[0]["entry"] - candidates[0]["stop_loss"], places=4)

    def test_zone_reaction_v2_wide_fvg_stop_falls_back_to_strategy_atr_without_context(self) -> None:
        candles = [
            candle("00:00", 112, 113, 111, 112),
            candle("00:15", 112, 113, 111, 112),
            candle("00:30", 110, 111, 80, 90),
            candle("00:45", 90, 120, 88, 115),
        ]
        fvg = zone("fvg", "bullish", 80, 107)

        candidates = build_setup_candidates(
            "XAUUSD",
            [fvg],
            contexts("bullish", "ranging"),
            candles,
            [point("pinbar_bullish", "up", "00:45")],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual("atr_fallback", candidates[0]["metadata"]["stop_source"])
        self.assertEqual("M15", candidates[0]["metadata"]["stop_fallback_atr_timeframe"])
        self.assertEqual(candidates[0]["metadata"]["atr"], candidates[0]["metadata"]["stop_fallback_atr"])
        expected_distance = max(
            CONFIG.zone_reaction_v2_min_stop_price,
            candidates[0]["metadata"]["atr"] * CONFIG.zone_reaction_v2_min_stop_atr,
            candidates[0]["metadata"]["atr"] * CONFIG.zone_reaction_v2_reject_atr_stop,
        )
        self.assertAlmostEqual(expected_distance, candidates[0]["entry"] - candidates[0]["stop_loss"], places=4)

    def test_zone_reaction_v2_wide_internal_reject_stop_falls_back_to_atr(self) -> None:
        metadata: dict[str, object] = {}

        entry, stop, _take_profit, _rr = compute_zone_reaction_v2_levels(
            zone("support", "bullish", 100, 150),
            "long",
            ReactionResult(
                state="internal_reject",
                direction="long",
                touched=True,
                candle_time="2026-01-01T00:45:00+00:00",
                reason=[],
                metadata={"reaction_high": 148, "reaction_low": 100},
            ),
            last_close=145,
            atr=4,
            config=CONFIG,
            stop_fallback_atr=20,
            stop_fallback_atr_timeframe="H1",
            level_metadata=metadata,
        )

        self.assertEqual(145, entry)
        self.assertEqual(121, stop)
        self.assertEqual("atr_fallback", metadata["stop_source"])
        self.assertEqual("H1", metadata["stop_fallback_atr_timeframe"])

    def test_zone_reaction_v2_wide_slow_reaction_stays_waiting_not_blocked(self) -> None:
        support = zone("support", "bullish", 4097, 4140)
        support["source"] = "human"
        support["metadata"] = {"human_created": True, "trade_modes": ["internal_reject"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [support],
            contexts("bearish", "trending", macro_trend="down"),
            [candle("00:15", 4122, 4125, 4097, 4123)],
            [],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
            context_candles=[
                candle("01:00", 4100, 4120, 4090, 4110),
                candle("02:00", 4110, 4130, 4100, 4120),
                candle("03:00", 4120, 4140, 4110, 4130),
                candle("04:00", 4130, 4150, 4120, 4140),
            ],
        )

        self.assertEqual("waiting_confirmation", candidates[0]["status"])
        self.assertIn(candidates[0]["zone_reaction_state"], {"slow_reaction", "waiting_bos"})
        self.assertEqual("atr_fallback", candidates[0]["metadata"]["stop_source"])
        self.assertEqual([], candidates[0]["blocked_reason"])
        self.assertNotIn("Stop distance", " ".join(candidates[0]["blocked_reason"]))

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

    def test_zone_reaction_v2_bearish_fvg_internal_reject_requires_structure_and_pa(self) -> None:
        candles = [
            candle("00:00", 122, 124, 121, 123),
            candle("00:15", 116, 118, 108, 110),
        ]
        fvg = zone("fvg", "bearish", 100, 120)

        candidates = build_setup_candidates(
            "XAUUSD",
            [fvg],
            contexts("bearish", "trending"),
            candles,
            [
                point("CHOCH", "down", "00:15", "bos1"),
                point("engulfing_bearish", "down", "00:15", "pa1"),
            ],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual("internal_reject", candidates[0]["zone_reaction_state"])
        self.assertEqual("short", candidates[0]["direction"])
        self.assertGreaterEqual(candidates[0]["metadata"]["fill_ratio"], 0.8)
        self.assertEqual(["CHOCH"], candidates[0]["metadata"]["structure_trigger_types"])
        self.assertEqual(["engulfing_bearish"], candidates[0]["metadata"]["price_action_trigger_types"])

    def test_zone_reaction_v2_internal_reject_allows_structure_and_pa_within_watch_window(self) -> None:
        candles = [
            candle("00:00", 118, 119, 110, 112),
            candle("00:15", 116, 118, 108, 110),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("fvg", "bearish", 100, 120)],
            contexts("bearish", "trending"),
            candles,
            [
                point("engulfing_bearish", "down", "00:00", "pa1"),
                point("CHOCH", "down", "00:15", "bos1"),
            ],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual("internal_reject", candidates[0]["zone_reaction_state"])
        self.assertEqual(["CHOCH"], candidates[0]["metadata"]["structure_trigger_types"])
        self.assertEqual(["engulfing_bearish"], candidates[0]["metadata"]["price_action_trigger_types"])

    def test_zone_reaction_v2_internal_reject_does_not_reuse_stale_window_without_current_trigger(self) -> None:
        candles = [
            candle("00:00", 118, 119, 110, 112),
            candle("00:15", 116, 118, 108, 110),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("fvg", "bearish", 100, 120)],
            contexts("bearish", "trending"),
            candles,
            [
                point("engulfing_bearish", "down", "00:00", "pa1"),
                point("CHOCH", "down", "00:00", "bos1"),
            ],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("waiting_confirmation", candidates[0]["status"])
        self.assertEqual("waiting_bos", candidates[0]["zone_reaction_state"])

    def test_zone_reaction_v2_recent_mitigated_fvg_can_internal_reject(self) -> None:
        candles = [
            candle("00:00", 122, 124, 121, 123),
            candle("00:15", 116, 118, 108, 110),
        ]
        fvg = zone("fvg", "bearish", 100, 120)
        fvg["status"] = "mitigated"
        fvg["valid_until"] = "2026-01-01T00:15:00+00:00"
        fvg["visual_end"] = "2026-01-01T00:15:00+00:00"
        fvg["invalidated_at"] = "2026-01-01T00:15:00+00:00"
        fvg["metadata"] = {"fill_ratio": 0.9, "fill_state": "filled"}

        candidates = build_setup_candidates(
            "XAUUSD",
            [fvg],
            contexts("bearish", "trending"),
            candles,
            [
                point("CHOCH", "down", "00:15", "bos1"),
                point("engulfing_bearish", "down", "00:15", "pa1"),
            ],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual("internal_reject", candidates[0]["zone_reaction_state"])

    def test_zone_reaction_v2_internal_reject_waits_without_structure(self) -> None:
        candles = [candle("00:15", 116, 118, 108, 110)]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("fvg", "bearish", 100, 120)],
            contexts("bearish", "trending"),
            candles,
            [point("engulfing_bearish", "down", "00:15", "pa1")],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("waiting_confirmation", candidates[0]["status"])
        self.assertEqual("waiting_bos", candidates[0]["zone_reaction_state"])
        self.assertNotEqual("eligible", candidates[0]["status"])

    def test_zone_reaction_v2_internal_reject_waits_without_price_action(self) -> None:
        candles = [candle("00:15", 116, 118, 108, 110)]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("fvg", "bearish", 100, 120)],
            contexts("bearish", "trending"),
            candles,
            [point("CHOCH", "down", "00:15", "bos1")],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("waiting_confirmation", candidates[0]["status"])
        self.assertEqual("waiting_bos", candidates[0]["zone_reaction_state"])
        self.assertNotEqual("eligible", candidates[0]["status"])

    def test_zone_reaction_v2_support_internal_reject_long(self) -> None:
        candles = [candle("00:15", 102, 109, 101, 108)]
        support = zone("support", "bullish", 100, 110)
        support["metadata"] = {"trade_modes": ["reject", "internal_reject"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [support],
            contexts("bullish", "trending"),
            candles,
            [
                point("BOS", "up", "00:15", "bos1"),
                point("marubozu_bullish", "up", "00:15", "pa1"),
            ],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual("internal_reject", candidates[0]["zone_reaction_state"])
        self.assertEqual("long", candidates[0]["direction"])

    def test_zone_reaction_v2_internal_reject_rejects_weak_directional_body(self) -> None:
        candles = [
            candle("00:00", 95, 96.5, 94.5, 96),
            candle("00:15", 100.4, 106, 99.5, 100.2),
        ]
        resistance = zone("resistance", "bearish", 100, 110)
        resistance["metadata"] = {"trade_modes": ["internal_reject"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [resistance],
            contexts("bearish", "trending"),
            candles,
            [point("pinbar_bearish", "down", "00:15", "pa1")],
            replace(
                CONFIG,
                zone_reaction_v2_internal_reject_body_min_ratio=1.5,
                zone_reaction_v2_internal_reject_min_fill_ratio=0.4,
            ),
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("waiting_confirmation", candidates[0]["status"])
        self.assertEqual("waiting_bos", candidates[0]["zone_reaction_state"])
        self.assertFalse(candidates[0]["metadata"]["internal_reject_body_gate_passed"])
        self.assertIn("below required 1.50x", " ".join(candidates[0]["reason"]))

    def test_zone_reaction_v2_internal_reject_rejects_wrong_color_body(self) -> None:
        candles = [
            candle("00:00", 100, 100.5, 99.5, 100.1),
            candle("00:15", 100.2, 108, 100, 106),
        ]
        resistance = zone("resistance", "bearish", 100, 110)
        resistance["metadata"] = {"trade_modes": ["internal_reject"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [resistance],
            contexts("bearish", "trending"),
            candles,
            [point("pinbar_bearish", "down", "00:15", "pa1")],
            replace(
                CONFIG,
                zone_reaction_v2_internal_reject_body_min_ratio=1.5,
                zone_reaction_v2_internal_reject_min_fill_ratio=0.4,
            ),
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("waiting_confirmation", candidates[0]["status"])
        self.assertFalse(candidates[0]["metadata"]["internal_reject_body_direction_aligned"])
        self.assertIn("SHORT requires a directional reaction body", " ".join(candidates[0]["reason"]))

    def test_zone_reaction_v2_sr_internal_reject_requires_forty_percent_fill(self) -> None:
        candles = [
            candle("00:00", 99, 99.2, 98.8, 99.1),
            candle("00:15", 102.8, 103, 100.8, 101),
        ]
        resistance = zone("resistance", "bearish", 100, 110)
        resistance["metadata"] = {"trade_modes": ["internal_reject"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [resistance],
            contexts("bearish", "trending"),
            candles,
            [point("engulfing_bearish", "down", "00:15", "pa1")],
            replace(
                CONFIG,
                zone_reaction_v2_internal_reject_body_min_ratio=1.5,
                zone_reaction_v2_internal_reject_min_fill_ratio=0.4,
            ),
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("waiting_confirmation", candidates[0]["status"])
        self.assertEqual(0.3, candidates[0]["metadata"]["fill_ratio"])
        self.assertIn("fill 30% is below required 40%", " ".join(candidates[0]["reason"]))

    def test_zone_reaction_v2_sr_internal_reject_accepts_strong_body_at_forty_percent_fill(self) -> None:
        candles = [
            candle("00:00", 99, 99.2, 98.8, 99.1),
            candle("00:15", 103.8, 104, 100.8, 101),
        ]
        resistance = zone("resistance", "bearish", 100, 110)
        resistance["metadata"] = {"trade_modes": ["internal_reject"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [resistance],
            contexts("bearish", "trending"),
            candles,
            [
                point("CHOCH", "down", "00:15", "bos1"),
                point("engulfing_bearish", "down", "00:15", "pa1"),
            ],
            replace(
                CONFIG,
                zone_reaction_v2_internal_reject_body_min_ratio=1.5,
                zone_reaction_v2_internal_reject_min_fill_ratio=0.4,
            ),
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual("internal_reject", candidates[0]["zone_reaction_state"])
        self.assertEqual(0.4, candidates[0]["metadata"]["fill_ratio"])
        self.assertTrue(candidates[0]["metadata"]["internal_reject_body_gate_passed"])
        self.assertGreaterEqual(candidates[0]["metadata"]["reaction_body_avg_ratio"], 1.5)

    def test_zone_reaction_v2_fvg_internal_reject_uses_same_body_gate(self) -> None:
        candles = [
            candle("00:00", 122, 124, 121, 123),
            candle("00:15", 110.2, 118, 108, 110),
        ]
        fvg = zone("fvg", "bearish", 100, 120)

        candidates = build_setup_candidates(
            "XAUUSD",
            [fvg],
            contexts("bearish", "trending"),
            candles,
            [
                point("CHOCH", "down", "00:15", "bos1"),
                point("pinbar_bearish", "down", "00:15", "pa1"),
            ],
            replace(
                CONFIG,
                zone_reaction_v2_internal_reject_body_min_ratio=1.5,
                zone_reaction_v2_internal_reject_min_fill_ratio=0.4,
            ),
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("waiting_confirmation", candidates[0]["status"])
        self.assertFalse(candidates[0]["metadata"]["internal_reject_body_gate_passed"])

    def test_zone_reaction_v2_sr_without_explicit_modes_does_not_internal_reject(self) -> None:
        candles = [candle("00:15", 102, 109, 101, 108)]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("support", "bullish", 100, 110)],
            contexts("bullish", "trending"),
            candles,
            [
                point("BOS", "up", "00:15", "bos1"),
                point("marubozu_bullish", "up", "00:15", "pa1"),
            ],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual([], candidates)

    def test_zone_reaction_v2_support_internal_only_can_promote_from_slow_reaction(self) -> None:
        candles = [candle("00:15", 102, 109, 101, 108)]
        support = zone("support", "bullish", 100, 110)
        support["source"] = "human"
        support["metadata"] = {"human_created": True, "trade_modes": ["internal_reject"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [support],
            contexts("bearish", "trending", macro_trend="down"),
            candles,
            [
                point("BOS", "up", "00:15", "bos1"),
                point("marubozu_bullish", "up", "00:15", "pa1"),
            ],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual("internal_reject", candidates[0]["zone_reaction_state"])
        self.assertEqual(["internal_reject"], candidates[0]["metadata"]["trade_modes"])
        self.assertTrue(candidates[0]["metadata"]["context_bypass"])

    def test_zone_reaction_v2_support_internal_only_surfaces_waiting_state(self) -> None:
        candles = [candle("00:15", 102, 109, 101, 108)]
        support = zone("support", "bullish", 100, 110)
        support["source"] = "human"
        support["metadata"] = {"human_created": True, "trade_modes": ["internal_reject"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [support],
            contexts("bearish", "trending", macro_trend="down"),
            candles,
            [],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("waiting_confirmation", candidates[0]["status"])
        self.assertEqual("waiting_bos", candidates[0]["zone_reaction_state"])
        self.assertEqual(["internal_reject"], candidates[0]["metadata"]["trade_modes"])

    def test_zone_reaction_v2_resistance_internal_reject_short(self) -> None:
        candles = [candle("00:15", 108, 109, 101, 102)]
        resistance = zone("resistance", "bearish", 100, 110)
        resistance["metadata"] = {"trade_modes": ["reject", "internal_reject"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [resistance],
            contexts("bearish", "trending"),
            candles,
            [
                point("BOS", "down", "00:15", "bos1"),
                point("marubozu_bearish", "down", "00:15", "pa1"),
            ],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual("internal_reject", candidates[0]["zone_reaction_state"])
        self.assertEqual("short", candidates[0]["direction"])

    def test_zone_reaction_v2_expired_fvg_does_not_trade_internal_reject(self) -> None:
        expired = zone("fvg", "bearish", 100, 120)
        expired["status"] = "expired"
        expired["metadata"] = {"fill_ratio": 0.95}
        candles = [candle("00:15", 116, 118, 108, 110)]

        candidates = build_setup_candidates(
            "XAUUSD",
            [expired],
            contexts("bearish", "trending"),
            candles,
            [
                point("CHOCH", "down", "00:15", "bos1"),
                point("engulfing_bearish", "down", "00:15", "pa1"),
            ],
            CONFIG,
            allowed_playbooks={"zone_reaction_v2"},
        )

        self.assertEqual([], candidates)

    def test_sr_breakout_v1_recently_invalidated_zone_still_tradeable(self) -> None:
        from dataclasses import replace

        context_candles = [
            candle("12:00", 96, 98, 94, 97),
            candle("13:00", 97, 99, 95, 98),
            candle("14:00", 98, 100, 96, 99),
            candle("15:00", 99, 104, 98, 102.8),
        ]
        resistance = zone("resistance", "bearish", 100, 102)
        resistance["metadata"] = {"trade_modes": ["breakout"]}
        resistance["status"] = "invalidated"
        resistance["invalidated_at"] = context_candles[-1]["time"]

        candidates = build_setup_candidates(
            "XAUUSD",
            [resistance],
            contexts("neutral", "ranging", macro_trend="up"),
            [context_candles[-1]],
            [],
            CONFIG,
            allowed_playbooks={"sr_breakout_v1"},
            context_candles=context_candles,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("sr_breakout_v1", candidates[0]["playbook"])

        stale = dict(resistance)
        stale["invalidated_at"] = "2020-01-01T00:00:00+00:00"
        candidates_stale = build_setup_candidates(
            "XAUUSD",
            [stale],
            contexts("neutral", "ranging", macro_trend="up"),
            [context_candles[-1]],
            [],
            CONFIG,
            allowed_playbooks={"sr_breakout_v1"},
            context_candles=context_candles,
        )
        self.assertEqual([], candidates_stale)

    def test_sr_breakout_v1_small_body_waits_for_retest(self) -> None:
        context_candles = [
            candle("12:00", 96, 98, 94, 97),
            candle("13:00", 97, 99, 95, 98),
            candle("14:00", 98, 100, 96, 99),
            candle("15:00", 102.2, 104, 98, 102.8),
        ]
        resistance = zone("resistance", "bearish", 100, 102)
        resistance["metadata"] = {"trade_modes": ["breakout"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [resistance],
            contexts("neutral", "ranging", macro_trend="up"),
            [context_candles[-1]],
            [],
            CONFIG,
            allowed_playbooks={"sr_breakout_v1"},
            context_candles=context_candles,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("waiting_retest", candidates[0]["zone_reaction_state"])
        self.assertEqual("waiting_confirmation", candidates[0]["status"])

    def test_sr_breakout_v1_zone_edge_stop_mode(self) -> None:
        from dataclasses import replace

        context_candles = [
            candle("12:00", 96, 98, 94, 97),
            candle("13:00", 97, 99, 95, 98),
            candle("14:00", 98, 100, 96, 99),
            candle("15:00", 99, 104, 98, 102.8),
        ]
        resistance = zone("resistance", "bearish", 100, 102)
        resistance["metadata"] = {"trade_modes": ["breakout"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [resistance],
            contexts("neutral", "ranging", macro_trend="up"),
            [context_candles[-1]],
            [],
            CONFIG,
            allowed_playbooks={"sr_breakout_v1"},
            context_candles=context_candles,
        )
        wick_candidates = build_setup_candidates(
            "XAUUSD",
            [resistance],
            contexts("neutral", "ranging", macro_trend="up"),
            [context_candles[-1]],
            [],
            replace(CONFIG, sr_breakout_v1_sl_mode="zone_edge"),
            allowed_playbooks={"sr_breakout_v1"},
            context_candles=context_candles,
        )

        # atr mode: stop = entry - 1.2*ATR. zone_edge mode: stop anchored just
        # below the broken edge (102) instead.
        self.assertLess(candidates[0]["stop_loss"], wick_candidates[0]["stop_loss"])
        self.assertLess(wick_candidates[0]["stop_loss"], 102)

    def test_sr_breakout_v1_wide_zone_edge_stop_falls_back_to_atr(self) -> None:
        context_candles = [
            candle("10:00", 100, 150, 50, 120),
            candle("11:00", 120, 170, 70, 130),
            candle("12:00", 130, 180, 80, 140),
            candle("13:00", 99, 170, 70, 150),
        ]
        resistance = zone("resistance", "bearish", 100, 102)
        resistance["metadata"] = {"trade_modes": ["breakout"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [resistance],
            contexts("neutral", "ranging", macro_trend="up"),
            [context_candles[-1]],
            [],
            replace(CONFIG, sr_breakout_v1_sl_mode="zone_edge", sr_breakout_v1_max_stop_distance=40.0),
            allowed_playbooks={"sr_breakout_v1"},
            context_candles=context_candles,
        )

        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual([], candidates[0]["blocked_reason"])
        self.assertEqual("atr_fallback", candidates[0]["metadata"]["stop_source"])
        self.assertNotIn("Stop distance", " ".join(candidates[0]["blocked_reason"]))

    def test_sr_breakout_v1_stop_can_use_explicit_stop_atr(self) -> None:
        entry, stop, take_profit, rr = compute_sr_breakout_v1_levels(
            "long",
            candle("13:00", 100, 110, 99, 105),
            atr=20,
            config=CONFIG,
            zone=zone("resistance", "bearish", 100, 102),
            stop_atr=10,
        )

        self.assertEqual(105, entry)
        self.assertEqual(90, stop)
        self.assertEqual([135], take_profit)
        self.assertEqual(2.0, rr)

    def test_sr_breakout_v1_disabled_entry_stays_waiting(self) -> None:
        from dataclasses import replace

        context_candles = [
            candle("12:00", 96, 98, 94, 97),
            candle("13:00", 97, 99, 95, 98),
            candle("14:00", 98, 100, 96, 99),
            candle("15:00", 99, 104, 98, 102.8),
        ]
        resistance = zone("resistance", "bearish", 100, 102)
        resistance["metadata"] = {"trade_modes": ["breakout"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [resistance],
            contexts("neutral", "ranging", macro_trend="up"),
            [context_candles[-1]],
            [],
            replace(CONFIG, sr_breakout_v1_allowed_entries=("retest_breakout",)),
            allowed_playbooks={"sr_breakout_v1"},
            context_candles=context_candles,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("breakout_close", candidates[0]["zone_reaction_state"])
        self.assertEqual("waiting_confirmation", candidates[0]["status"])
        self.assertIn("disabled for SR Breakout V1", " ".join(candidates[0]["reason"]))

    def test_sr_breakout_v1_requires_breakout_trade_mode(self) -> None:
        context_candles = [
            candle("12:00", 96, 98, 94, 97),
            candle("13:00", 97, 99, 95, 98),
            candle("14:00", 98, 100, 96, 99),
            candle("15:00", 99, 104, 98, 102.8),
        ]

        candidates = build_setup_candidates(
            "XAUUSD",
            [zone("resistance", "bearish", 100, 102)],
            contexts("neutral", "ranging", macro_trend="up"),
            [context_candles[-1]],
            [],
            CONFIG,
            allowed_playbooks={"sr_breakout_v1"},
            context_candles=context_candles,
        )

        self.assertEqual([], candidates)

    def test_sr_breakout_v1_long_resistance_near_breakout_is_eligible(self) -> None:
        context_candles = [
            candle("12:00", 96, 98, 94, 97),
            candle("13:00", 97, 99, 95, 98),
            candle("14:00", 98, 100, 96, 99),
            candle("15:00", 99, 104, 98, 102.8),
        ]
        resistance = zone("resistance", "bearish", 100, 102)
        resistance["metadata"] = {"trade_modes": ["breakout"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [resistance],
            contexts("neutral", "ranging", macro_trend="up"),
            [context_candles[-1]],
            [],
            CONFIG,
            allowed_playbooks={"sr_breakout_v1"},
            context_candles=context_candles,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("sr_breakout_v1", candidates[0]["playbook"])
        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual("long", candidates[0]["direction"])
        self.assertEqual("breakout_close", candidates[0]["zone_reaction_state"])
        self.assertEqual("next_h1_open", candidates[0]["metadata"]["entry_model"])
        self.assertAlmostEqual(2.0, candidates[0]["risk_reward"])

    def test_sr_breakout_v1_short_support_near_breakout_is_eligible(self) -> None:
        context_candles = [
            candle("12:00", 106, 108, 104, 105),
            candle("13:00", 105, 107, 103, 104),
            candle("14:00", 104, 106, 102, 103),
            candle("15:00", 103, 104, 96, 98.5),
        ]
        support = zone("support", "bullish", 100, 102)
        support["metadata"] = {"trade_modes": ["breakout"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [support],
            contexts("neutral", "ranging", macro_trend="down"),
            [context_candles[-1]],
            [],
            CONFIG,
            allowed_playbooks={"sr_breakout_v1"},
            context_candles=context_candles,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual("short", candidates[0]["direction"])
        self.assertEqual("breakout_close", candidates[0]["zone_reaction_state"])

    def test_sr_breakout_v1_far_breakout_waits_for_retest(self) -> None:
        context_candles = [
            candle("09:00", 96, 98, 94, 97),
            candle("10:00", 97, 99, 95, 98),
            candle("11:00", 98, 100, 96, 99),
            candle("12:00", 99, 108, 98, 106.5),
        ]
        resistance = zone("resistance", "bearish", 100, 102)
        resistance["metadata"] = {"trade_modes": ["breakout"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [resistance],
            contexts("neutral", "ranging", macro_trend="up"),
            [context_candles[-1]],
            [],
            CONFIG,
            allowed_playbooks={"sr_breakout_v1"},
            context_candles=context_candles,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("waiting_confirmation", candidates[0]["status"])
        self.assertEqual("waiting_retest", candidates[0]["zone_reaction_state"])
        self.assertEqual("wait_retest", candidates[0]["metadata"]["entry_model"])

    def test_sr_breakout_v1_retest_after_far_breakout_is_eligible(self) -> None:
        context_candles = [
            candle("09:00", 96, 98, 94, 97),
            candle("10:00", 97, 99, 95, 98),
            candle("11:00", 98, 100, 96, 99),
            candle("12:00", 99, 108, 98, 106.5),
            candle("13:00", 106.5, 107, 101.5, 103.2),
        ]
        resistance = zone("resistance", "bearish", 100, 102)
        resistance["metadata"] = {"trade_modes": ["breakout"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [resistance],
            contexts("neutral", "ranging", macro_trend="up"),
            [context_candles[-1]],
            [],
            CONFIG,
            allowed_playbooks={"sr_breakout_v1"},
            context_candles=context_candles,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual("retest_breakout", candidates[0]["zone_reaction_state"])
        self.assertEqual("retest_next_h1_open", candidates[0]["metadata"]["entry_model"])

    def test_sr_breakout_v1_long_retest_fails_when_close_back_below_resistance_zone(self) -> None:
        context_candles = [
            candle("09:00", 96, 98, 94, 97),
            candle("10:00", 97, 99, 95, 98),
            candle("11:00", 98, 100, 96, 99),
            candle("12:00", 99, 108, 98, 106.5),
            candle("13:00", 106.5, 107, 99.5, 99.8),
        ]
        resistance = zone("resistance", "bearish", 100, 102)
        resistance["metadata"] = {"trade_modes": ["breakout"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [resistance],
            contexts("neutral", "ranging", macro_trend="up"),
            [context_candles[-1]],
            [],
            CONFIG,
            allowed_playbooks={"sr_breakout_v1"},
            context_candles=context_candles,
        )

        self.assertEqual([], candidates)

    def test_sr_breakout_v1_human_breakout_allows_unknown_macro(self) -> None:
        context_candles = [
            candle("12:00", 96, 98, 94, 97),
            candle("13:00", 97, 99, 95, 98),
            candle("14:00", 98, 100, 96, 99),
            candle("15:00", 99, 104, 98, 102.8),
        ]
        resistance = zone("resistance", "bearish", 100, 102)
        resistance["source"] = "human"
        resistance["metadata"] = {"trade_modes": ["breakout"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [resistance],
            contexts("bearish", "news", macro_trend="unknown"),
            [context_candles[-1]],
            [],
            CONFIG,
            allowed_playbooks={"sr_breakout_v1"},
            context_candles=context_candles,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("eligible", candidates[0]["status"])
        self.assertEqual(True, candidates[0]["metadata"]["context_bypass"])

    def test_sr_breakout_v1_human_breakout_bypasses_opposite_macro(self) -> None:
        # Spec change 2026-06-12: human-set trade modes bypass every context
        # gate including macro trend; direction comes from the zone side only.
        context_candles = [
            candle("12:00", 96, 98, 94, 97),
            candle("13:00", 97, 99, 95, 98),
            candle("14:00", 98, 100, 96, 99),
            candle("15:00", 99, 104, 98, 102.8),
        ]
        resistance = zone("resistance", "bearish", 100, 102)
        resistance["source"] = "human"
        resistance["metadata"] = {"trade_modes": ["breakout"]}

        candidates = build_setup_candidates(
            "XAUUSD",
            [resistance],
            contexts("bearish", "news", macro_trend="down"),
            [context_candles[-1]],
            [],
            CONFIG,
            allowed_playbooks={"sr_breakout_v1"},
            context_candles=context_candles,
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("long", candidates[0]["direction"])
        self.assertEqual("eligible", candidates[0]["status"])
        self.assertTrue(candidates[0]["metadata"]["context_bypass"])

if __name__ == "__main__":
    unittest.main()
