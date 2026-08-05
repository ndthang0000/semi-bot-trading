import type { CandleDatum } from "./tradeOverlay";

export type CandleSeriesChange = "none" | "last-candle" | "single-append" | "full-reload";

export function candleSeriesKey(candles: CandleDatum[]): string {
  return candles
    .map((candle) => [Number(candle.time), candle.open, candle.high, candle.low, candle.close].join(":"))
    .join("|");
}

export function classifyCandleSeriesChange(previous: CandleDatum[], next: CandleDatum[]): CandleSeriesChange {
  if (previous.length === 0 || next.length === 0) return "full-reload";

  if (previous.length === next.length) {
    if (sameCandles(previous, next)) return "none";
    const stableHistory = sameCandles(previous.slice(0, -1), next.slice(0, -1));
    const sameLastTime = Number(previous.at(-1)?.time) === Number(next.at(-1)?.time);
    return stableHistory && sameLastTime ? "last-candle" : "full-reload";
  }

  if (next.length === previous.length + 1) {
    const stableHistory = sameCandles(previous.slice(0, -1), next.slice(0, -2));
    const previousLastTime = Number(previous.at(-1)?.time);
    const finalizedPreviousTime = Number(next.at(-2)?.time);
    return stableHistory && previousLastTime === finalizedPreviousTime ? "single-append" : "full-reload";
  }

  return "full-reload";
}

function sameCandles(left: CandleDatum[], right: CandleDatum[]): boolean {
  if (left.length !== right.length) return false;
  return left.every((candle, index) => {
    const other = right[index];
    return Boolean(other)
      && Number(candle.time) === Number(other.time)
      && candle.open === other.open
      && candle.high === other.high
      && candle.low === other.low
      && candle.close === other.close;
  });
}
