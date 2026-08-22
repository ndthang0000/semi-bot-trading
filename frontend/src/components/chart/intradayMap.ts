import type { IntradayLevel, IntradayMap } from "../../types";

const ACTIONABLE_STATUS = new Set(["live", "unswept", "testing", "reclaimed", "testing_flip"]);
export const BROKEN_LEVEL_MAX_DISTANCE_ATR = 3;

export function selectIntradayLevels(map: IntradayMap, compact: boolean, showBroken = false): IntradayLevel[] {
  const maximum = compact ? 6 : 10;
  return map.levels
    .filter((level) => {
      if (level.status === "stale") return false;
      if (level.status !== "broken") return true;
      return showBroken && level.distance_atr !== null && Math.abs(level.distance_atr) <= BROKEN_LEVEL_MAX_DISTANCE_ATR;
    })
    .sort((left, right) => {
      const leftNearest = left.id === map.nearest_above_id || left.id === map.nearest_below_id ? 1 : 0;
      const rightNearest = right.id === map.nearest_above_id || right.id === map.nearest_below_id ? 1 : 0;
      if (leftNearest !== rightNearest) return rightNearest - leftNearest;
      const leftActionable = ACTIONABLE_STATUS.has(left.status) ? 1 : 0;
      const rightActionable = ACTIONABLE_STATUS.has(right.status) ? 1 : 0;
      if (leftActionable !== rightActionable) return rightActionable - leftActionable;
      if (left.priority !== right.priority) return right.priority - left.priority;
      return Math.abs(left.distance) - Math.abs(right.distance);
    })
    .slice(0, maximum);
}

export function intradayGuidance(bias: string, map: IntradayMap): string {
  const nearestAbove = map.levels.find((level) => level.id === map.nearest_above_id);
  const nearestBelow = map.levels.find((level) => level.id === map.nearest_below_id);
  if (bias === "bullish") {
    return nearestBelow
      ? `Bullish: wait for a pullback/reclaim near ${nearestBelow.label}; do not sell a high blindly.`
      : "Bullish: prefer pullback/reclaim longs; do not chase or sell a high blindly.";
  }
  if (bias === "bearish") {
    return nearestAbove
      ? `Bearish: wait for a rejection/retest near ${nearestAbove.label}; avoid blind counter-trend buys.`
      : "Bearish: prefer rejection/retest shorts; avoid blind counter-trend buys.";
  }
  return "Neutral: wait for sweep + reclaim or a confirmed breakout/retest before choosing direction.";
}

export function levelStatusLabel(status: IntradayLevel["status"]): string {
  if (status === "live") return "LIVE";
  if (status === "broken") return "BROKEN · FLIP?";
  if (status === "testing_flip") return "TESTING FLIP";
  return status.toUpperCase();
}
