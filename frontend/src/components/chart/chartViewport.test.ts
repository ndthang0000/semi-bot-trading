import { describe, expect, it } from "vitest";
import { buildScaleAnchorData } from "./chartCore";
import type { CandleDatum } from "./tradeOverlay";

function candles(intervalSeconds: number): CandleDatum[] {
  return [0, 1, 2].map((index) => ({
    time: (1_700_000_000 + index * intervalSeconds) as CandleDatum["time"],
    open: 2_000 + index,
    high: 2_002 + index,
    low: 1_998 + index,
    close: 2_001 + index,
  }));
}

describe("buildScaleAnchorData", () => {
  it.each([
    ["H1", 3_600],
    ["M15", 900],
    ["M5", 300],
  ])("limits %s future whitespace to 18 timeframe bars", (_timeframe, intervalSeconds) => {
    const input = candles(intervalSeconds);
    const lastTime = Number(input.at(-1)?.time);
    const farFutureNews = [{
      id: "future-news",
      scheduled_at: new Date((lastTime + 7 * 24 * 3_600) * 1_000).toISOString(),
    }];

    const anchors = buildScaleAnchorData(input, farFutureNews as never[]);
    const finalAnchorTime = Number(anchors.at(-1)?.time);

    expect(finalAnchorTime).toBe(lastTime + 18 * intervalSeconds);
    expect(anchors).toHaveLength(20);
  });
});
