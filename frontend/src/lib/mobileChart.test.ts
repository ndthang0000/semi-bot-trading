import { describe, expect, it } from "vitest";
import { isMobileChartWidth, visibleChartBars } from "./mobileChart";

describe("mobile chart sizing", () => {
  it("keeps portrait and phone landscape widths in the mobile layout", () => {
    expect(isMobileChartWidth(360)).toBe(true);
    expect(isMobileChartWidth(844)).toBe(true);
    expect(isMobileChartWidth(1024)).toBe(false);
  });

  it("limits initial candle density without changing desktop requests", () => {
    expect(visibleChartBars(393, "H1", 300)).toBe(72);
    expect(visibleChartBars(844, "M15", 300)).toBe(90);
    expect(visibleChartBars(1280, "H1", 300)).toBe(300);
  });
});
