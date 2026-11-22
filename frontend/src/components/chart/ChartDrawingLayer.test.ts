import { describe, expect, it } from "vitest";
import { fibExtensionLineRange, fibExtensionValue, fibRetracementValue, volumeProfileBarWidth } from "./ChartDrawingLayer";

describe("fibRetracementValue", () => {
  it("places level zero at the impulse end and level one at its origin", () => {
    expect(fibRetracementValue(4300, 4400, 0)).toBe(4400);
    expect(fibRetracementValue(4300, 4400, 1)).toBe(4300);
  });

  it("computes the bullish OTE retracement below the impulse end", () => {
    expect(fibRetracementValue(4300, 4400, 0.62)).toBe(4338);
    expect(fibRetracementValue(4300, 4400, 0.79)).toBe(4321);
  });
});

describe("fibExtensionValue", () => {
  it("projects bullish targets from the retracement end", () => {
    expect(fibExtensionValue(4300, 4400, 4350, 0)).toBe(4350);
    expect(fibExtensionValue(4300, 4400, 4350, 1)).toBe(4450);
    expect(fibExtensionValue(4300, 4400, 4350, 1.618)).toBeCloseTo(4511.8);
  });

  it("projects bearish targets below the retracement end", () => {
    expect(fibExtensionValue(4400, 4300, 4350, 1)).toBe(4250);
    expect(fibExtensionValue(4400, 4300, 4350, 1.618)).toBeCloseTo(4188.2);
  });
});

describe("fibExtensionLineRange", () => {
  it("keeps extension levels bounded between B and C", () => {
    expect(fibExtensionLineRange(420, 680)).toEqual({ left: 420, right: 680 });
    expect(fibExtensionLineRange(680, 420)).toEqual({ left: 420, right: 680 });
  });
});

describe("volumeProfileBarWidth", () => {
  it("scales row magnitude inside the selected time range", () => {
    expect(volumeProfileBarWidth(500, 40, 100, 100)).toBe(200);
    expect(volumeProfileBarWidth(500, 40, 25, 100)).toBe(50);
  });

  it("keeps the configured width within supported bounds", () => {
    expect(volumeProfileBarWidth(100, 2, 1, 1)).toBe(10);
    expect(volumeProfileBarWidth(100, 200, 1, 1)).toBe(100);
  });
});
