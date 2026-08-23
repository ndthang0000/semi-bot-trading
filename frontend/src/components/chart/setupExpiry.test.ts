import { describe, expect, it } from "vitest";
import type { SetupCandidate } from "../../types";
import { h1SetupExpiryDuration } from "./setupExpiry";

describe("H1 setup expiry duration", () => {
  it("uses the calculator expiry snapshot", () => {
    expect(h1SetupExpiryDuration(candidate({ expiry_hours: 6 }))).toBe("6h");
  });

  it("falls back to the signal snapshot for persisted execution plans", () => {
    expect(h1SetupExpiryDuration(candidate({ as_of: "2026-08-13T00:00:00+00:00" }))).toBe("6h");
  });

  it("does not add an H1 duration to another playbook", () => {
    expect(h1SetupExpiryDuration({ ...candidate({ expiry_hours: 6 }), playbook: "manual_ai_v1" })).toBeNull();
  });
});

function candidate(metadata: Record<string, unknown>): SetupCandidate {
  return {
    id: "h1-setup",
    symbol: "XAUUSD",
    timeframe: "H1",
    playbook: "h1_impulse_retest_v1",
    direction: "long",
    status: "eligible",
    zone_reaction_state: "UNFILLED",
    score: 1,
    entry: 100,
    stop_loss: 90,
    take_profit: [120],
    risk_reward: 2,
    primary_zone_id: null,
    related_zone_ids: [],
    trigger_point_ids: [],
    reason: [],
    blocked_reason: [],
    expires_at: "2026-08-13T06:00:00+00:00",
    metadata,
  };
}
