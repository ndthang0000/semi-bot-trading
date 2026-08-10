import { describe, expect, it } from "vitest";
import { manualAiTargetForRiskReward, xauusdPipsForDistance } from "./ManualAiModal";

describe("Manual AI price metrics", () => {
  it("treats seven XAUUSD price units as seventy pips", () => {
    expect(xauusdPipsForDistance(7)).toBe(70);
  });

  it("calculates quick take-profit presets for both sides", () => {
    expect(manualAiTargetForRiskReward("buy", 4350, 4343, 3)).toBe(4371);
    expect(manualAiTargetForRiskReward("sell", 4350, 4357, 2.5)).toBe(4332.5);
  });
});
