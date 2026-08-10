import { describe, expect, it } from "vitest";
import { fibRetracementValue } from "./ChartDrawingLayer";

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
