import { describe, expect, it } from "vitest";
import { candleSecondsForTimeframe, remainingCandleSeconds } from "./chartWidgets";

describe("candle countdown timeframe", () => {
  it("uses five minutes for M5 instead of the H1 fallback", () => {
    expect(candleSecondsForTimeframe("M5")).toBe(300);
    expect(candleSecondsForTimeframe("H1")).toBe(3600);
  });

  it("calculates the remaining M5 candle time", () => {
    expect(remainingCandleSeconds("M5", Date.parse("2026-08-10T08:02:30Z"))).toBe(150);
    expect(remainingCandleSeconds("H1", Date.parse("2026-08-10T08:02:30Z"))).toBe(3450);
  });
});
