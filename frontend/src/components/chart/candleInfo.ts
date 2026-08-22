import type { ChartCandle } from "../../types";

export type CandleDirection = "bullish" | "bearish" | "doji";

export type CandleMetrics = {
  direction: CandleDirection;
  range: number;
  body: number;
  bodyPercent: number;
  upperWick: number;
  lowerWick: number;
  rangeAtr: number | null;
};

export type CandleHitGeometry = {
  pointerX: number;
  pointerY: number;
  candleX: number;
  openY: number;
  highY: number;
  lowY: number;
  closeY: number;
  bodyWidth: number;
};

export function candleMetrics(candle: ChartCandle, atr: number | null): CandleMetrics {
  const range = Math.max(0, candle.high - candle.low);
  const body = Math.abs(candle.close - candle.open);
  const upperWick = Math.max(0, candle.high - Math.max(candle.open, candle.close));
  const lowerWick = Math.max(0, Math.min(candle.open, candle.close) - candle.low);
  return {
    direction: candle.close > candle.open ? "bullish" : candle.close < candle.open ? "bearish" : "doji",
    range,
    body,
    bodyPercent: range > 0 ? body / range * 100 : 0,
    upperWick,
    lowerWick,
    rangeAtr: atr !== null && atr > 0 ? range / atr : null,
  };
}

export function formatCandleTime(value: string, timezone: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  try {
    return `${new Intl.DateTimeFormat("vi-VN", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: timezone,
    }).format(date)} ${timezone}`;
  } catch {
    return `${date.toISOString().slice(0, 16).replace("T", " ")} UTC`;
  }
}

export function isCandleShapeHit(geometry: CandleHitGeometry): boolean {
  const verticalTolerance = 2;
  const bodyHalfWidth = Math.max(2, geometry.bodyWidth / 2);
  const wickHalfWidth = 3;
  const bodyTop = Math.min(geometry.openY, geometry.closeY) - verticalTolerance;
  const bodyBottom = Math.max(geometry.openY, geometry.closeY) + verticalTolerance;
  const wickTop = Math.min(geometry.highY, geometry.lowY) - verticalTolerance;
  const wickBottom = Math.max(geometry.highY, geometry.lowY) + verticalTolerance;
  const horizontalDistance = Math.abs(geometry.pointerX - geometry.candleX);
  const hitsBody = horizontalDistance <= bodyHalfWidth
    && geometry.pointerY >= bodyTop
    && geometry.pointerY <= bodyBottom;
  const hitsWick = horizontalDistance <= wickHalfWidth
    && geometry.pointerY >= wickTop
    && geometry.pointerY <= wickBottom;
  return hitsBody || hitsWick;
}
