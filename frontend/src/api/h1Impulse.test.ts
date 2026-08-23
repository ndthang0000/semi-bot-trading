import { describe, expect, it } from "vitest";
import { h1ImpulsePreviewToSetupCandidate, type H1ImpulsePreview } from "./h1Impulse";

describe("h1 impulse preview adapter", () => {
  it("turns a read-only preview into a chart setup with outcome metadata", () => {
    const preview = {
      schema_version: 1,
      playbook: "h1_impulse_retest_v1",
      preview_only: true,
      symbol: "XAUUSD",
      as_of: "2026-08-21T16:00:00+00:00",
      status: "eligible",
      direction: "long",
      signal_candle_time: "2026-08-20T10:00:00+00:00",
      signal_candle_close_time: "2026-08-20T11:00:00+00:00",
      expires_at: "2026-08-20T17:00:00+00:00",
      expiry_hours: 6,
      previous_candle_time: "2026-08-20T09:00:00+00:00",
      atr: 10,
      atr_period: 14,
      atr_as_of: "2026-08-20T10:00:00+00:00",
      reference_price: 110,
      risk_reward: 2.5,
      entry: 105,
      entry_source: "previous_h1_high",
      entry_options: [{ source: "previous_h1_high", label: "Previous H1 high", price: 105 }],
      previous_edge_entry: 105,
      fib_0_5_entry: 104,
      stop_loss: 99,
      stop_buffer: 1,
      stop_distance: 6,
      stop_distance_atr: 0.6,
      min_stop_distance: 5,
      max_stop_distance: 12,
      take_profit: 120,
      limit_placement_valid: true,
      broke_previous_edge: true,
      blocked_reason: [],
      soft_blocked_reason: [],
      hard_blocked_reason: [],
      outcome: { status: "win", filled_at: "fill", exited_at: "exit", bars_to_fill: 2, bars_held: 4, result_r: 2.5 },
      signal: { open: 100, high: 112, low: 100, close: 111, range: 12, body: 11, upper_wick: 1, lower_wick: 0, body_atr_ratio: 1.1, range_atr_ratio: 1.2, body_range_ratio: 0.92, close_location: 0.92, close_side_wick_ratio: 0.08, opposite_wick_ratio: 0 },
      previous: { open: 100, high: 105, low: 98, close: 102, entry_stop_distance: 6, entry_stop_distance_atr: 0.6 },
      parameters: { atr_period: 14, stop_buffer_atr: 0.1, min_stop_atr: 0.5, max_stop_atr: 1.2, min_body_atr: 0.8, min_range_atr: 0.9, max_range_atr: 2.5, min_body_range_ratio: 0.6, min_close_location: 0.75, max_close_side_wick_ratio: 0.2, expiry_medium_body_atr: 1.2, expiry_large_body_atr: 1.6, expiry_hours_small: 6, expiry_hours_medium: 12, expiry_hours_large: 18 },
    } satisfies H1ImpulsePreview;

    const candidate = h1ImpulsePreviewToSetupCandidate(preview);

    expect(candidate.playbook).toBe("h1_impulse_retest_v1");
    expect(candidate.entry).toBe(105);
    expect(candidate.expires_at).toBe(preview.expires_at);
    expect(candidate.metadata.outcome).toEqual(preview.outcome);
    expect(candidate.metadata.original_status).toBe("eligible");
  });
});
