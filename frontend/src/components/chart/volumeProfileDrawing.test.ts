import { describe, expect, it } from "vitest";
import type { ChartDrawing } from "../../types";
import { findVolumeProfileForRange } from "./volumeProfileDrawing";

function drawing(overrides: Partial<ChartDrawing> = {}): ChartDrawing {
  return {
    id: "profile-1",
    symbol: "XAUUSD",
    drawing_type: "volume_profile_fixed_range",
    origin_timeframe: "H1",
    visible_timeframes: ["H1", "M15", "M5"],
    anchors: [
      { time: "2026-11-20T22:00:00Z", price: 4000 },
      { time: "2026-11-21T22:00:00Z", price: 4000 },
    ],
    properties: {},
    content: null,
    locked: false,
    hidden: false,
    revision: 1,
    created_by: "human",
    created_at: "2026-11-22T00:00:00Z",
    updated_at: "2026-11-22T00:00:00Z",
    ...overrides,
  };
}

describe("findVolumeProfileForRange", () => {
  it("finds an existing profile for the same symbol and broker-day range", () => {
    const existing = drawing();

    expect(findVolumeProfileForRange(
      [existing],
      "XAUUSD",
      "2026-11-20T22:00:00+00:00",
      "2026-11-21T22:00:00+00:00",
    )).toBe(existing);
  });

  it("does not reuse a hidden or different-range profile", () => {
    expect(findVolumeProfileForRange(
      [drawing({ hidden: true }), drawing({ id: "other", anchors: [
        { time: "2026-11-19T22:00:00Z", price: 4000 },
        { time: "2026-11-20T22:00:00Z", price: 4000 },
      ] })],
      "XAUUSD",
      "2026-11-20T22:00:00Z",
      "2026-11-21T22:00:00Z",
    )).toBeNull();
  });
});
