import { describe, expect, it } from "vitest";
import type { SetupCandidate } from "../../types";
import { reviewH1Execution } from "./h1ExecutionReview";

function candidate(overrides: Partial<SetupCandidate> = {}): SetupCandidate {
  return {
    id: "h1-review",
    symbol: "XAUUSD",
    timeframe: "H1",
    playbook: "h1_impulse_retest_v1",
    direction: "long",
    status: "blocked",
    zone_reaction_state: "BLOCKED",
    score: 0,
    entry: 105,
    stop_loss: 99,
    take_profit: [117],
    risk_reward: 2,
    primary_zone_id: null,
    related_zone_ids: [],
    trigger_point_ids: [],
    reason: [],
    blocked_reason: ["Body/range below minimum"],
    expires_at: "2026-08-24T12:00:00+00:00",
    metadata: {
      original_status: "blocked",
      soft_blocked_reasons: ["Body/range below minimum"],
      hard_blocked_reasons: [],
      atr: 10,
      reference_price: 110,
      limit_expires_at: "2026-08-24T12:00:00+00:00",
      parameters: { min_stop_atr: 0.5, max_stop_atr: 1.2 },
    },
    ...overrides,
  };
}

describe("H1 execution review", () => {
  it("allows a geometry-safe setup to reach the soft override workflow", () => {
    const review = reviewH1Execution(candidate());

    expect(review.originalBlocked).toBe(true);
    expect(review.softBlockedReasons).toEqual(["Body/range below minimum"]);
    expect(review.hardBlockedReasons).toEqual([]);
  });

  it("recalculates hard blocks from edited levels", () => {
    const review = reviewH1Execution(
      candidate({ entry: 100, stop_loss: 99, take_profit: [102] }),
    );

    expect(review.hardBlockedReasons.some((reason) => reason.includes("SL size"))).toBe(true);
  });

  it("does not treat the old broker TTL as signal invalidation", () => {
    const review = reviewH1Execution(candidate());

    expect(review.hardBlockedReasons).not.toContain("Signal has expired.");
  });
});
