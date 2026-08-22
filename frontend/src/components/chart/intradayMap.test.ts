import { describe, expect, it } from "vitest";
import type { IntradayLevel, IntradayMap } from "../../types";
import { intradayGuidance, selectIntradayLevels } from "./intradayMap";

const level = (id: string, distance: number, priority: number, status: IntradayLevel["status"] = "unswept"): IntradayLevel => ({
  id,
  kind: "asia",
  label: id,
  side: distance > 0 ? "high" : "low",
  price: 4600 + distance,
  period_start: "2026-08-21T00:00:00+00:00",
  period_end: "2026-08-21T07:00:00+00:00",
  status,
  priority,
  live: false,
  distance,
  distance_atr: distance / 10,
  approach_low: 4599,
  approach_high: 4601,
});

const map = (levels: IntradayLevel[]): IntradayMap => ({
  as_of: "2026-08-21T12:00:00+00:00",
  timezone: "UTC",
  current_price: 4600,
  current_session: "New York",
  atr_m15: 10,
  approach_allowance: 2.5,
  nearest_above_id: "nearest-up",
  nearest_below_id: "nearest-down",
  levels,
});

describe("intraday map presentation", () => {
  it("keeps nearest liquidity visible on compact charts", () => {
    const levels = [level("nearest-up", 2, 10), level("nearest-down", -3, 10), ...Array.from({ length: 8 }, (_, index) => level(`p${index}`, 20 + index, 100))];
    const selected = selectIntradayLevels(map(levels), true);
    expect(selected).toHaveLength(6);
    expect(selected.map((item) => item.id)).toContain("nearest-up");
    expect(selected.map((item) => item.id)).toContain("nearest-down");
  });

  it("does not turn a bullish high into an automatic sell instruction", () => {
    expect(intradayGuidance("bullish", map([level("nearest-down", -3, 80)]))).toContain("do not sell a high blindly");
  });

  it("hides broken historical levels from the default chart layer", () => {
    const selected = selectIntradayLevels(map([level("broken", 1, 100, "broken"), level("active", 2, 80)]), false);
    expect(selected.map((item) => item.id)).toEqual(["active"]);
  });

  it("shows only nearby broken levels when the optional layer is enabled", () => {
    const nearby = level("nearby", 20, 100, "broken");
    const far = level("far", 40, 100, "broken");
    const selected = selectIntradayLevels(map([nearby, far]), false, true);
    expect(selected.map((item) => item.id)).toEqual(["nearby"]);
  });

  it("always keeps an active flip retest visible", () => {
    const selected = selectIntradayLevels(map([level("flip", 1, 100, "testing_flip")]), false);
    expect(selected.map((item) => item.id)).toEqual(["flip"]);
  });
});
