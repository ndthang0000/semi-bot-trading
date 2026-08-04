import type { Timeframe } from "../types";

export const MOBILE_CHART_MAX_WIDTH = 1023;

export function isMobileChartWidth(width: number): boolean {
  return width <= MOBILE_CHART_MAX_WIDTH;
}

export function visibleChartBars(width: number, timeframe: Timeframe, requestedBars: number): number {
  if (!isMobileChartWidth(width)) return requestedBars;
  return Math.min(requestedBars, timeframe === "M15" ? 90 : 72);
}
