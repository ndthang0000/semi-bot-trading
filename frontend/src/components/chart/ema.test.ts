import { describe, expect, it } from "vitest";
import { buildEmaSeriesData } from "./ema";
import type { CandleDatum } from "./tradeOverlay";

function candles(closes: number[]): CandleDatum[] {
  return closes.map((close, index) => ({
    time: (index + 1) as CandleDatum["time"],
    open: close,
    high: close,
    low: close,
    close,
  }));
}

describe("buildEmaSeriesData", () => {
  it("starts at the first close so the indicator covers the loaded chart", () => {
    expect(buildEmaSeriesData(candles([1, 2]), 3)).toEqual([
      { time: 1, value: 1 },
      { time: 2, value: 1.5 },
    ]);
  });

  it("applies the EMA multiplier recursively", () => {
    expect(buildEmaSeriesData(candles([1, 2, 3, 6]), 3)).toEqual([
      { time: 1, value: 1 },
      { time: 2, value: 1.5 },
      { time: 3, value: 2.25 },
      { time: 4, value: 4.125 },
    ]);
  });

  it("uses hidden warm-up candles but only returns the visible window", () => {
    expect(buildEmaSeriesData(candles([1, 2, 3, 6]), 3, 3 as CandleDatum["time"])).toEqual([
      { time: 3, value: 2.25 },
      { time: 4, value: 4.125 },
    ]);
  });

  it("rejects invalid periods", () => {
    expect(buildEmaSeriesData(candles([1, 2, 3]), 0)).toEqual([]);
    expect(buildEmaSeriesData(candles([1, 2, 3]), 1.5)).toEqual([]);
  });
});
