import { describe, expect, it } from "vitest";
import type { ChartCandle } from "../../types";
import { candleMetrics, formatCandleTime, isCandleShapeHit } from "./candleInfo";

const candle: ChartCandle = {
  time: "2026-08-21T20:00:00+00:00",
  open: 4590,
  high: 4610,
  low: 4585,
  close: 4605,
  volume: 123,
};

describe("candleMetrics", () => {
  it("calculates body, wicks, range, and ATR ratio", () => {
    expect(candleMetrics(candle, 10)).toEqual({
      direction: "bullish",
      range: 25,
      body: 15,
      bodyPercent: 60,
      upperWick: 5,
      lowerWick: 5,
      rangeAtr: 2.5,
    });
  });

  it("handles a zero-range doji without invalid ratios", () => {
    const flat = { ...candle, open: 4600, high: 4600, low: 4600, close: 4600 };
    expect(candleMetrics(flat, 0)).toEqual({
      direction: "doji",
      range: 0,
      body: 0,
      bodyPercent: 0,
      upperWick: 0,
      lowerWick: 0,
      rangeAtr: null,
    });
  });
});

describe("formatCandleTime", () => {
  it("formats a valid UTC timestamp with its timezone", () => {
    expect(formatCandleTime(candle.time, "UTC")).toContain("UTC");
  });

  it("falls back safely for an invalid timezone", () => {
    expect(formatCandleTime(candle.time, "not-a-timezone")).toBe("2026-08-21 20:00 UTC");
  });
});

describe("isCandleShapeHit", () => {
  const geometry = {
    candleX: 100,
    openY: 80,
    highY: 60,
    lowY: 120,
    closeY: 95,
    bodyWidth: 10,
  };

  it("accepts clicks inside the candle body", () => {
    expect(isCandleShapeHit({ ...geometry, pointerX: 104, pointerY: 90 })).toBe(true);
  });

  it("accepts a narrow tolerance around the wick", () => {
    expect(isCandleShapeHit({ ...geometry, pointerX: 102.5, pointerY: 68 })).toBe(true);
  });

  it("rejects a click in the same time column but outside the visible candle", () => {
    expect(isCandleShapeHit({ ...geometry, pointerX: 108, pointerY: 68 })).toBe(false);
  });

  it("rejects a click beyond the candle high or low", () => {
    expect(isCandleShapeHit({ ...geometry, pointerX: 100, pointerY: 130 })).toBe(false);
  });
});
