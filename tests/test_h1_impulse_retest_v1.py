from __future__ import annotations

import unittest

from semi_bot_trading.strategy.h1_impulse_retest_v1 import (
    H1ImpulsePreviewConfig,
    build_h1_impulse_markers,
    build_h1_impulse_preview,
    evaluate_h1_impulse_preview,
    expiry_hours_for_body_atr,
)


def candle(time: str, open_: float, high: float, low: float, close: float) -> dict[str, object]:
    return {
        "time": time,
        "close_time": time,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
    }


class H1ImpulseRetestV1Test(unittest.TestCase):
    def test_marker_layer_separates_body_candidate_from_fully_eligible_signal(self) -> None:
        candles = [
            candle("2026-08-20T09:00:00+00:00", 100, 105, 95, 100),
            candle("2026-08-20T10:00:00+00:00", 100, 106, 98, 102),
            candle("2026-08-20T11:00:00+00:00", 101, 112, 99, 111),
            candle("2026-08-20T12:00:00+00:00", 111, 113, 101, 102),
        ]

        markers = build_h1_impulse_markers(
            candles,
            visible_start="2026-08-20T10:00:00+00:00",
            visible_end="2026-08-20T12:00:00+00:00",
            config=H1ImpulsePreviewConfig(),
        )

        self.assertEqual(["eligible", "candidate"], [marker["status"] for marker in markers])
        self.assertEqual(["long", "short"], [marker["direction"] for marker in markers])
        self.assertEqual([], markers[0]["blocked_reason"])
        self.assertTrue(markers[1]["blocked_reason"])

    def test_default_range_cap_and_expiry_buckets(self) -> None:
        config = H1ImpulsePreviewConfig()

        self.assertEqual(2.5, config.max_range_atr)
        self.assertEqual(6, expiry_hours_for_body_atr(0.81, config))
        self.assertEqual(12, expiry_hours_for_body_atr(1.2, config))
        self.assertEqual(18, expiry_hours_for_body_atr(1.6, config))

    def test_long_uses_previous_high_when_stop_distance_is_in_range(self) -> None:
        previous = candle("2026-08-20T10:00:00+00:00", 100, 106, 98, 102)
        signal = candle("2026-08-20T11:00:00+00:00", 101, 112, 99, 111)

        preview = build_h1_impulse_preview(signal, previous, atr=10, reference_price=111.5, risk_reward=2.5)

        self.assertEqual("previous_h1_high", preview["entry_source"])
        self.assertEqual(106, preview["entry"])
        self.assertEqual(98, preview["stop_loss"])
        self.assertEqual(8, preview["stop_distance"])
        self.assertEqual(126, preview["take_profit"])
        self.assertEqual(6, preview["expiry_hours"])
        self.assertEqual("2026-08-20T17:00:00+00:00", preview["expires_at"])
        self.assertEqual(
            {"previous_h1_high", "fib_0.382", "fib_0.5", "fib_0.618", "min_stop_atr", "max_stop_atr"},
            {option["source"] for option in preview["entry_options"]},
        )

    def test_risk_reward_matches_manual_ai_range(self) -> None:
        previous = candle("2026-08-20T10:00:00+00:00", 100, 106, 98, 102)
        signal = candle("2026-08-20T11:00:00+00:00", 101, 112, 99, 111)

        low_rr = build_h1_impulse_preview(signal, previous, atr=10, reference_price=111.5, risk_reward=1.5)
        high_rr = build_h1_impulse_preview(signal, previous, atr=10, reference_price=111.5, risk_reward=4)

        self.assertEqual(1.5, low_rr["risk_reward"])
        self.assertEqual(4, high_rr["risk_reward"])
        with self.assertRaises(ValueError):
            build_h1_impulse_preview(signal, previous, atr=10, reference_price=111.5, risk_reward=4.01)

    def test_long_opposite_lower_wick_is_measured_but_does_not_block(self) -> None:
        previous = candle("2026-08-20T10:00:00+00:00", 101, 110, 98, 105)
        signal = candle("2026-08-20T11:00:00+00:00", 100, 119, 89, 118)

        preview = build_h1_impulse_preview(signal, previous, atr=15, reference_price=118.5, risk_reward=2.5)

        self.assertGreater(preview["signal"]["opposite_wick_ratio"], 0.35)
        self.assertEqual("eligible", preview["status"])
        self.assertFalse(any("Opposite wick" in reason for reason in preview["blocked_reason"]))

    def test_long_falls_back_to_fib_midpoint_when_previous_high_is_too_close_to_stop(self) -> None:
        previous = candle("2026-08-20T10:00:00+00:00", 98, 101, 96, 100)
        signal = candle("2026-08-20T11:00:00+00:00", 100, 114, 98, 113)

        preview = build_h1_impulse_preview(signal, previous, atr=10, reference_price=114, risk_reward=2)

        self.assertEqual("fib_0.5_min_stop_fallback", preview["entry_source"])
        self.assertEqual(106, preview["entry"])
        self.assertEqual(97, preview["stop_loss"])
        self.assertEqual(9, preview["stop_distance"])

    def test_long_caps_entry_when_previous_high_would_exceed_max_stop(self) -> None:
        previous = candle("2026-08-20T10:00:00+00:00", 105, 112, 100, 108)
        signal = candle("2026-08-20T11:00:00+00:00", 104, 118, 98, 117)

        preview = build_h1_impulse_preview(signal, previous, atr=10, reference_price=118, risk_reward=3)

        self.assertEqual("atr_1.2_max_stop_cap", preview["entry_source"])
        self.assertEqual(109, preview["entry"])
        self.assertEqual(97, preview["stop_loss"])
        self.assertEqual(12, preview["stop_distance"])

    def test_long_caps_fib_fallback_when_midpoint_would_exceed_max_stop(self) -> None:
        previous = candle("2026-08-20T10:00:00+00:00", 89, 91, 88, 90)
        signal = candle("2026-08-20T11:00:00+00:00", 90, 122, 89, 121)

        preview = build_h1_impulse_preview(signal, previous, atr=10, reference_price=122, risk_reward=2)

        self.assertEqual("fib_0.5_then_atr_1.2_cap", preview["entry_source"])
        self.assertEqual(100, preview["entry"])
        self.assertEqual(88, preview["stop_loss"])
        self.assertEqual(12, preview["stop_distance"])

    def test_short_falls_back_to_fib_midpoint_when_previous_low_is_too_close(self) -> None:
        previous = candle("2026-08-20T10:00:00+00:00", 114, 115, 113, 114)
        signal = candle("2026-08-20T11:00:00+00:00", 112, 116, 98, 99)

        preview = build_h1_impulse_preview(signal, previous, atr=10, reference_price=98, risk_reward=2)

        self.assertEqual("fib_0.5_min_stop_fallback", preview["entry_source"])
        self.assertEqual(107, preview["entry"])
        self.assertEqual(117, preview["stop_loss"])
        self.assertEqual(10, preview["stop_distance"])
        self.assertEqual(87, preview["take_profit"])

    def test_preview_blocks_non_breakout_and_invalid_limit_without_hiding_levels(self) -> None:
        previous = candle("2026-08-20T10:00:00+00:00", 100, 112, 98, 105)
        signal = candle("2026-08-20T11:00:00+00:00", 100, 111, 97, 110)

        preview = build_h1_impulse_preview(signal, previous, atr=10, reference_price=105, risk_reward=2.5)

        self.assertEqual("blocked", preview["status"])
        self.assertGreater(preview["entry"], preview["stop_loss"])
        self.assertTrue(any("previous H1 high" in reason for reason in preview["blocked_reason"]))
        self.assertTrue(any("BUY LIMIT" in reason for reason in preview["blocked_reason"]))
        self.assertTrue(any("previous H1 high" in reason for reason in preview["soft_blocked_reason"]))
        self.assertTrue(any("BUY LIMIT" in reason for reason in preview["hard_blocked_reason"]))

    def test_outcome_waits_for_fill_then_records_win(self) -> None:
        preview = {
            "status": "eligible",
            "direction": "long",
            "entry": 100,
            "stop_loss": 95,
            "take_profit": 110,
            "risk_reward": 2,
        }
        candles = [
            candle("2026-08-20T12:00:00+00:00", 104, 108, 101, 103),
            candle("2026-08-20T13:00:00+00:00", 103, 106, 99, 104),
            candle("2026-08-20T14:00:00+00:00", 104, 111, 102, 109),
        ]

        outcome = evaluate_h1_impulse_preview(preview, candles)

        self.assertEqual("win", outcome["status"])
        self.assertEqual(2, outcome["bars_to_fill"])
        self.assertEqual(2, outcome["bars_held"])
        self.assertEqual(2, outcome["result_r"])

    def test_target_on_fill_candle_is_ambiguous_without_lower_timeframe(self) -> None:
        preview = {
            "status": "eligible",
            "direction": "short",
            "entry": 100,
            "stop_loss": 105,
            "take_profit": 90,
            "risk_reward": 2,
        }

        outcome = evaluate_h1_impulse_preview(
            preview,
            [candle("2026-08-20T12:00:00+00:00", 99, 101, 89, 92)],
        )

        self.assertEqual("ambiguous", outcome["status"])
        self.assertIsNone(outcome["result_r"])


if __name__ == "__main__":
    unittest.main()
