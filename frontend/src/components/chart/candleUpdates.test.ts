import { describe, expect, it } from "vitest";
import { candleSeriesKey, classifyCandleSeriesChange } from "./candleUpdates";
import type { CandleDatum } from "./tradeOverlay";

function candle(time: number, close = time): CandleDatum {
  return { time: time as CandleDatum["time"], open: close - 1, high: close + 1, low: close - 2, close };
}

describe("classifyCandleSeriesChange", () => {
  it("uses an incremental update when only the live candle changes", () => {
    expect(classifyCandleSeriesChange([candle(1), candle(2)], [candle(1), candle(2, 20)])).toBe("last-candle");
  });

  it("finalizes the previous candle and appends exactly one new candle", () => {
    expect(classifyCandleSeriesChange(
      [candle(1), candle(2)],
      [candle(1), candle(2, 20), candle(3)],
    )).toBe("single-append");
  });

  it("fully reloads a sliding fixed-size window", () => {
    expect(classifyCandleSeriesChange(
      [candle(1), candle(2), candle(3)],
      [candle(2), candle(3), candle(4)],
    )).toBe("full-reload");
  });

  it("fully reloads when a historical candle was corrected", () => {
    expect(classifyCandleSeriesChange(
      [candle(1), candle(2), candle(3)],
      [candle(1), candle(2, 200), candle(3)],
    )).toBe("full-reload");
  });

  it("includes historical OHLC changes in the series key", () => {
    expect(candleSeriesKey([candle(1), candle(2)])).not.toBe(candleSeriesKey([candle(1, 10), candle(2)]));
  });
});
