import { describe, expect, it } from "vitest";
import type { WaveLeg } from "../../types";
import { formatWaveLegLabel } from "./waveMetrics";

const leg = (direction: "up" | "down"): WaveLeg => ({
  id: "a:b",
  direction,
  start_time: "2026-08-28T00:00:00+00:00",
  end_time: "2026-08-28T06:00:00+00:00",
  start_price: 4500,
  end_price: direction === "up" ? 4542.6 : 4457.4,
  mid_time: "2026-08-28T03:00:00+00:00",
  mid_price: 4521.3,
  price_move: 42.6,
  bars: 6,
  duration_hours: 6,
  confirmed: true,
});

describe("wave metric labels", () => {
  it("formats subtle up and down ZigZag labels", () => {
    expect(formatWaveLegLabel(leg("up"))).toBe("+42.6 · 6H");
    expect(formatWaveLegLabel(leg("down"))).toBe("−42.6 · 6H");
  });
});
