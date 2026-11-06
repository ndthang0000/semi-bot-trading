import type { LineData } from "lightweight-charts";
import type { CandleDatum } from "./tradeOverlay";

export function buildEmaSeriesData(
  candles: CandleDatum[],
  period: number,
  visibleFrom?: CandleDatum["time"],
): LineData[] {
  if (!Number.isInteger(period) || period <= 0 || candles.length === 0) return [];

  const multiplier = 2 / (period + 1);
  let ema = candles[0].close;
  const data: LineData[] = [{ time: candles[0].time, value: ema }];

  for (let index = 1; index < candles.length; index += 1) {
    ema = ((candles[index].close - ema) * multiplier) + ema;
    data.push({ time: candles[index].time, value: ema });
  }

  if (visibleFrom === undefined) return data;
  return data.filter((point) => Number(point.time) >= Number(visibleFrom));
}
