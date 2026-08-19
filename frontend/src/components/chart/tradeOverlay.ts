import type { IChartApi, ISeriesApi } from "lightweight-charts";
import { toUnixTime } from "../../lib/time";
import type { SetupCandidate, TradeOrder } from "../../types";

export type CandleDatum = {
  time: ReturnType<typeof toUnixTime>;
  open: number;
  high: number;
  low: number;
  close: number;
};

export type BoxRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type TradeBox = {
  trade: TradeOrder;
  trades: TradeOrder[];
  x: number;
  y: number;
  width: number;
  height: number;
  profit: BoxRect;
  loss: BoxRect;
};

export type SetupBox = {
  candidate: SetupCandidate;
  x: number;
  y: number;
  width: number;
  height: number;
  profit: BoxRect;
  loss: BoxRect;
  entryY: number;
  stopY: number;
  takeProfitY: number;
};

export function setupToBox(
  candidate: SetupCandidate,
  rangeStart: string,
  rangeEnd: string,
  candles: CandleDatum[],
  chartWidth: number,
  chartHeight: number,
  timeScale: ReturnType<IChartApi["timeScale"]>,
  series: ISeriesApi<"Candlestick">,
): SetupBox | null {
  const entry = candidate.entry;
  const stop = candidate.stop_loss;
  const takeProfit = candidate.take_profit[0];
  if (entry === null || stop === null || typeof takeProfit !== "number") return null;
  const createdAt = readString(candidate.metadata.created_at) ?? readString(candidate.metadata.as_of) ?? rangeEnd;
  const expiresAt = candidate.expires_at ?? rangeEnd;
  const startX = chartXForTradeTime(timeScale, createdAt, rangeStart, rangeEnd, candles, chartWidth);
  const rawEndX = chartXForTradeTime(timeScale, expiresAt, rangeStart, rangeEnd, candles, chartWidth);
  if (startX === null || rawEndX === null) return null;
  const left = clampNumber(Math.min(startX, rawEndX), 0, chartWidth);
  const right = clampNumber(Math.max(rawEndX, startX + 44), 0, chartWidth);
  if (right - left < 2) return null;
  const entryY = series.priceToCoordinate(entry);
  const stopY = series.priceToCoordinate(stop);
  const takeProfitY = series.priceToCoordinate(takeProfit);
  if (entryY === null || stopY === null || takeProfitY === null) return null;
  const profit = clipBoxRect({ x: left, y: Math.min(entryY, takeProfitY), width: right - left, height: Math.abs(takeProfitY - entryY) }, chartWidth, chartHeight);
  const loss = clipBoxRect({ x: left, y: Math.min(entryY, stopY), width: right - left, height: Math.abs(stopY - entryY) }, chartWidth, chartHeight);
  if (!profit || !loss) return null;
  const y = Math.min(profit.y, loss.y);
  const bottom = Math.max(profit.y + profit.height, loss.y + loss.height);
  return {
    candidate,
    x: left,
    y,
    width: right - left,
    height: Math.max(2, bottom - y),
    profit,
    loss,
    entryY,
    stopY,
    takeProfitY,
  };
}

export function tradeToBox(
  trade: TradeOrder,
  rangeStart: string,
  rangeEnd: string,
  candles: CandleDatum[],
  chartWidth: number,
  chartHeight: number,
  timeScale: ReturnType<IChartApi["timeScale"]>,
  series: ISeriesApi<"Candlestick">,
): TradeBox | null {
  const entry = trade.entry_price;
  const stop = tradeVisualStopLoss(trade);
  const takeProfit = firstTakeProfitPrice(trade.take_profit);
  if (entry === null || stop === null || takeProfit === null || !trade.opened_at) return null;

  const startX = chartXForTradeTime(timeScale, trade.opened_at, rangeStart, rangeEnd, candles, chartWidth);
  const MIN_TRADE_CANDLES = 5;
  const openedUnix = toUnixTime(trade.opened_at);
  const candleInterval =
    candles.length >= 2 ? candles[candles.length - 1].time - candles[candles.length - 2].time : 3600;
  const closedUnix = trade.closed_at ? toUnixTime(trade.closed_at) : toUnixTime(rangeEnd);
  const minVisualEndUnix = openedUnix + MIN_TRADE_CANDLES * candleInterval;
  const visualEndUnix = Math.max(closedUnix, minVisualEndUnix);
  const visualEndIso = new Date(visualEndUnix * 1000).toISOString().replace(".000Z", "Z");
  const endX = chartXForTradeTime(timeScale, visualEndIso, rangeStart, rangeEnd, candles, chartWidth);
  if (startX === null || endX === null) return null;

  const x1 = Math.min(startX, endX);
  const x2 = Math.max(startX, endX);
  const clippedX1 = clampNumber(x1, 0, chartWidth);
  const clippedX2 = clampNumber(x2, 0, chartWidth);
  if (clippedX2 - clippedX1 < 2) return null;

  const entryY = series.priceToCoordinate(entry);
  const stopY = series.priceToCoordinate(stop);
  const takeProfitY = series.priceToCoordinate(takeProfit);
  if (entryY === null || stopY === null || takeProfitY === null) return null;

  const profit = clipBoxRect(
    {
      x: clippedX1,
      y: Math.min(entryY, takeProfitY),
      width: clippedX2 - clippedX1,
      height: Math.abs(takeProfitY - entryY),
    },
    chartWidth,
    chartHeight,
  );
  const loss = clipBoxRect(
    {
      x: clippedX1,
      y: Math.min(entryY, stopY),
      width: clippedX2 - clippedX1,
      height: Math.abs(stopY - entryY),
    },
    chartWidth,
    chartHeight,
  );
  if (!profit || !loss) return null;

  const x = Math.min(profit.x, loss.x);
  const y = Math.min(profit.y, loss.y);
  const right = Math.max(profit.x + profit.width, loss.x + loss.width);
  const bottom = Math.max(profit.y + profit.height, loss.y + loss.height);
  return {
    trade,
    trades: [trade],
    x,
    y,
    width: Math.max(2, right - x),
    height: Math.max(2, bottom - y),
    profit,
    loss,
  };
}

export function groupTradeBoxesByCandidate(boxes: TradeBox[]): TradeBox[] {
  const grouped = new Map<string, TradeBox[]>();
  const result: TradeBox[] = [];

  boxes.forEach((box) => {
    const candidateId = tradeCandidateId(box.trade);
    if (!candidateId) {
      result.push(box);
      return;
    }
    const group = grouped.get(candidateId) ?? [];
    group.push(box);
    grouped.set(candidateId, group);
  });

  for (const group of grouped.values()) {
    if (group.length === 1) {
      result.push(group[0]);
    } else {
      result.push(mergeTradeBoxGroup(group));
    }
  }

  return result.sort((a, b) => {
    const aTime = Date.parse(a.trade.opened_at ?? "") || 0;
    const bTime = Date.parse(b.trade.opened_at ?? "") || 0;
    return aTime - bTime;
  });
}

export function tradeGroupSummary(trades: TradeOrder[]): string {
  return trades.map((trade) => `${trade.account_label}: ${formatTradeR(trade.pnl_r)} ${trade.status}`).join("; ");
}

export function compactTradeGroupSummary(trades: TradeOrder[]): string {
  return trades.map((trade) => `${shortAccountLabel(trade.account_label)} ${formatTradeR(trade.pnl_r)}`).join(" / ");
}

export function readObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

export function interpolateChartX(timeScale: ReturnType<IChartApi["timeScale"]>, timestamp: number, candles: CandleDatum[]): number | null {
  const directCoordinate = timeScale.timeToCoordinate(timestamp as ReturnType<typeof toUnixTime>);
  if (directCoordinate !== null) return directCoordinate;
  if (candles.length === 0) return null;

  const candleTimes = candles.map((candle) => Number(candle.time));
  let nextIndex = candleTimes.findIndex((time) => time >= timestamp);
  if (nextIndex < 0) nextIndex = candleTimes.length - 1;
  const prevIndex = Math.max(0, nextIndex - 1);
  const prevTime = candleTimes[prevIndex];
  const nextTime = candleTimes[nextIndex];
  const prevX = timeScale.timeToCoordinate(candles[prevIndex].time);
  const nextX = timeScale.timeToCoordinate(candles[nextIndex].time);
  if (prevX === null && nextX === null) return null;
  if (prevIndex === nextIndex || nextTime === prevTime || nextX === null) return prevX ?? nextX;
  if (prevX === null) return nextX;
  const ratio = (timestamp - prevTime) / (nextTime - prevTime);
  return prevX + (nextX - prevX) * ratio;
}

export function clampNumber(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function mergeTradeBoxGroup(group: TradeBox[]): TradeBox {
  const sorted = [...group].sort((a, b) => {
    const aTime = Date.parse(a.trade.opened_at ?? "") || 0;
    const bTime = Date.parse(b.trade.opened_at ?? "") || 0;
    return aTime - bTime;
  });
  const representative = sorted[0];
  const x = Math.min(...sorted.map((box) => box.x));
  const y = Math.min(...sorted.map((box) => box.y));
  const right = Math.max(...sorted.map((box) => box.x + box.width));
  const bottom = Math.max(...sorted.map((box) => box.y + box.height));

  return {
    trade: representative.trade,
    trades: sorted.map((box) => box.trade),
    x,
    y,
    width: Math.max(2, right - x),
    height: Math.max(2, bottom - y),
    profit: mergeBoxRects(sorted.map((box) => box.profit)),
    loss: mergeBoxRects(sorted.map((box) => box.loss)),
  };
}

function mergeBoxRects(rects: BoxRect[]): BoxRect {
  const x = Math.min(...rects.map((rect) => rect.x));
  const y = Math.min(...rects.map((rect) => rect.y));
  const right = Math.max(...rects.map((rect) => rect.x + rect.width));
  const bottom = Math.max(...rects.map((rect) => rect.y + rect.height));
  return {
    x,
    y,
    width: Math.max(2, right - x),
    height: Math.max(2, bottom - y),
  };
}

function tradeCandidateId(trade: TradeOrder): string | null {
  const direct = trade.metadata.candidate_id;
  if (typeof direct === "string" && direct.length > 0) return direct;
  const candidateMetadata = readObject(trade.metadata.candidate_metadata);
  const nested = candidateMetadata.id;
  return typeof nested === "string" && nested.length > 0 ? nested : null;
}

function firstTakeProfitPrice(values: TradeOrder["take_profit"]): number | null {
  const first = values.at(0);
  if (typeof first === "number") return first;
  if (first && typeof first.price === "number") return first.price;
  return null;
}

function tradeVisualStopLoss(trade: TradeOrder): number | null {
  const initialStopLoss = readObject(trade.metadata).initial_stop_loss;
  if (typeof initialStopLoss === "number" && Number.isFinite(initialStopLoss)) return initialStopLoss;
  return trade.stop_loss;
}

export function chartXForTradeTime(
  timeScale: ReturnType<IChartApi["timeScale"]>,
  value: string,
  rangeStart: string,
  rangeEnd: string,
  candles: CandleDatum[],
  chartWidth: number,
): number | null {
  const timestamp = toUnixTime(value);
  const start = toUnixTime(rangeStart);
  const end = toUnixTime(rangeEnd);
  const interpolated = interpolateChartX(timeScale, timestamp, candles);
  if (interpolated !== null) return interpolated;
  if (timestamp <= start) return 0;
  if (timestamp >= end) return chartWidth;
  return null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function clipBoxRect(rect: BoxRect, chartWidth: number, chartHeight: number): BoxRect | null {
  const x1 = clampNumber(rect.x, 0, chartWidth);
  const y1 = clampNumber(rect.y, 0, chartHeight);
  const x2 = clampNumber(rect.x + rect.width, 0, chartWidth);
  const y2 = clampNumber(rect.y + rect.height, 0, chartHeight);
  if (x2 - x1 < 2 || y2 - y1 < 2) return null;
  return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
}

function shortAccountLabel(label: string): string {
  const normalized = label.trim();
  if (/exness/i.test(normalized)) return "Exness";
  if (/ftmo/i.test(normalized)) return "FTMO";
  return normalized.split(/\s+/).slice(0, 2).join(" ") || "Account";
}

function formatTradeR(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "--R";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}R`;
}
