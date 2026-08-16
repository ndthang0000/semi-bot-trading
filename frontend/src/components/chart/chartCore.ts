import type { IChartApi, Logical } from "lightweight-charts";
import type { PointerEvent as ReactPointerEvent } from "react";
import type { NewsEvent } from "../../api/chart";
import { toUnixTime } from "../../lib/time";
import type {
  AddEntityKind,
  ChartPayload,
  PlaybookKey,
  PriceZone,
  SetupCandidate,
  StructurePoint,
  TradeOrder,
  ZoneTradeMode,
  ZoneTypeVisibility,
} from "../../types";
import { clampNumber, type CandleDatum } from "./tradeOverlay";
import type { NewsTimelineMarker } from "./chartWidgets";

export type ZoneBox = {
  zone: PriceZone;
  x: number;
  y: number;
  width: number;
  height: number;
};

export type PriceRange = {
  from: number;
  to: number;
};

type LogicalRange = {
  from: number;
  to: number;
};

export type ViewportState = {
  logicalRange: LogicalRange | null;
  priceRange: PriceRange | null;
};

export type ZoneDragMode = "move" | "resize-top" | "resize-bottom" | "resize-left" | "resize-right";

type ManualZoneSpec = {
  label: string;
  zoneType: string;
  direction: string;
  weight: number;
  confidence: number;
};

const RIGHT_OFFSET_BARS = 18;
const NEWS_AXIS_HORIZON_HOURS = 168;
const REPLAY_VISIBLE_BARS = 120;
const VERTICAL_FOCUS_BARS = 14;

export function manualZoneSpec(kind: AddEntityKind): ManualZoneSpec {
  const specs: Record<AddEntityKind, ManualZoneSpec> = {
    support: { label: "Support", zoneType: "support", direction: "bullish", weight: 0.8, confidence: 1 },
    resistance: { label: "Resistance", zoneType: "resistance", direction: "bearish", weight: 0.8, confidence: 1 },
    demand_order_block: { label: "Demand OB", zoneType: "order_block", direction: "bullish", weight: 0.78, confidence: 1 },
    supply_order_block: { label: "Supply OB", zoneType: "order_block", direction: "bearish", weight: 0.78, confidence: 1 },
    bullish_fvg: { label: "Bullish FVG", zoneType: "fvg", direction: "bullish", weight: 0.72, confidence: 1 },
    bearish_fvg: { label: "Bearish FVG", zoneType: "fvg", direction: "bearish", weight: 0.72, confidence: 1 },
    consolidation: { label: "Consolidation", zoneType: "consolidation", direction: "neutral", weight: 0.65, confidence: 1 },
    buy_side_liquidity: { label: "Buy Liquidity Zone", zoneType: "liquidity_pool", direction: "bullish", weight: 0.68, confidence: 1 },
    sell_side_liquidity: { label: "Sell Liquidity Zone", zoneType: "liquidity_pool", direction: "bearish", weight: 0.68, confidence: 1 },
  };
  return specs[kind];
}

export function zoneDisplayName(zone: PriceZone): string {
  if (isHistoricalLiquiditySweep(zone)) return "Historical Liquidity Sweep";
  const kind = zone.metadata.add_entity_kind;
  if (typeof kind === "string" && isAddEntityKind(kind)) {
    return manualZoneSpec(kind).label;
  }
  if (zone.type === "order_block") {
    return zone.direction === "bullish" ? "Demand OB" : "Supply OB";
  }
  if (zone.type === "fvg") {
    return zone.direction === "bullish" ? "Bullish FVG" : "Bearish FVG";
  }
  if (zone.type === "liquidity_pool") {
    return zone.direction === "bullish" ? "Buy Liquidity Zone" : zone.direction === "bearish" ? "Sell Liquidity Zone" : "Liquidity Pool";
  }
  return zone.type;
}

export function chartPlotWidth(chart: IChartApi, containerWidth: number): number {
  const priceScaleWidth = chart.priceScale("right").width();
  return Math.max(0, containerWidth - priceScaleWidth);
}

export function zoneVisualClasses(zone: PriceZone): { box: string; label: string } {
  if (zone.status === "draft") {
    return {
      box: "border-dashed border-amber-300/75 bg-amber-300/[0.06] hover:bg-amber-300/[0.12]",
      label: "bg-amber-950/90 text-amber-100",
    };
  }
  if (zone.type === "order_block") {
    return zone.direction === "bullish"
      ? {
          box: "border-cyan-300/60 bg-cyan-300/[0.08] hover:bg-cyan-300/[0.14]",
          label: "bg-cyan-950/80 text-cyan-100",
        }
      : {
          box: "border-fuchsia-300/60 bg-fuchsia-300/[0.08] hover:bg-fuchsia-300/[0.14]",
          label: "bg-fuchsia-950/80 text-fuchsia-100",
        };
  }
  if (zone.type === "fvg") {
    return zone.direction === "bullish"
      ? {
          box: "border-dashed border-lime-300/65 bg-lime-300/[0.07] hover:bg-lime-300/[0.13]",
          label: "bg-lime-950/80 text-lime-100",
        }
      : {
          box: "border-dashed border-orange-300/65 bg-orange-300/[0.07] hover:bg-orange-300/[0.13]",
          label: "bg-orange-950/80 text-orange-100",
        };
  }
  if (zone.type === "consolidation") {
    return {
      box: "border-sky-300/60 bg-sky-300/[0.07] hover:bg-sky-300/[0.13]",
      label: "bg-sky-950/80 text-sky-100",
    };
  }
  if (zone.type === "liquidity_pool") {
    return {
      box: "border-dashed border-yellow-300/70 bg-yellow-300/[0.07] hover:bg-yellow-300/[0.13]",
      label: "bg-yellow-950/80 text-yellow-100",
    };
  }
  if (zone.direction === "bullish") {
    return {
      box: "border-emerald-400/55 bg-emerald-400/[0.08] hover:bg-emerald-400/[0.14]",
      label: "bg-emerald-950/80 text-emerald-200",
    };
  }
  return {
    box: "border-rose-400/55 bg-rose-400/[0.08] hover:bg-rose-400/[0.14]",
    label: "bg-rose-950/80 text-rose-200",
  };
}

export function compactClassName(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

export function readSwingType(point: StructurePoint): "high" | "low" | null {
  const value = point.metadata.swing_type;
  return value === "high" || value === "low" ? value : null;
}

export function isStructurePointAvailable(point: StructurePoint, rangeEnd: string, replayAsOf?: string): boolean {
  const upperBound = replayAsOf ?? rangeEnd;
  if (point.time > upperBound) return false;
  const confirmedAt = point.metadata.confirmed_at;
  return typeof confirmedAt !== "string" || confirmedAt <= upperBound;
}

export function swingLabel(point: StructurePoint, swingType: "high" | "low"): string {
  const metadataLabel = point.metadata.structure_label;
  if (typeof metadataLabel === "string" && metadataLabel.length > 0) {
    return metadataLabel;
  }
  if (point.type === "swing_high") return "SH";
  if (point.type === "swing_low") return "SL";
  return swingType === "high" ? "SH" : "SL";
}

export function buildZigZagSeriesData(
  points: StructurePoint[],
  rangeEnd: string,
  replayAsOf: string | undefined,
  enabled: boolean,
): Array<{ time: ReturnType<typeof toUnixTime>; value: number }> {
  if (!enabled) return [];
  const swings = points
    .filter((point) => isStructurePointAvailable(point, rangeEnd, replayAsOf))
    .flatMap((point) => {
      const swingType = readSwingType(point);
      return swingType ? [{ point, swingType }] : [];
    });

  const collapsed: Array<{ point: StructurePoint; swingType: "high" | "low" }> = [];
  for (const swing of swings.slice().sort((a, b) => toUnixTime(a.point.time) - toUnixTime(b.point.time))) {
    const previous = collapsed.at(-1);
    if (!previous || previous.swingType !== swing.swingType) {
      collapsed.push(swing);
      continue;
    }

    const shouldReplace =
      swing.swingType === "high" ? swing.point.price > previous.point.price : swing.point.price < previous.point.price;
    if (shouldReplace) {
      collapsed[collapsed.length - 1] = swing;
    }
  }
  return normalizeLineSeriesData(collapsed.map((swing) => ({ time: toUnixTime(swing.point.time), value: swing.point.price })));
}

export function normalizeCandleData(candles: CandleDatum[]): CandleDatum[] {
  const byTime = new Map<number, CandleDatum>();
  for (const candle of candles) {
    byTime.set(Number(candle.time), candle);
  }
  return Array.from(byTime.values()).sort((a, b) => Number(a.time) - Number(b.time));
}

export function normalizeLineSeriesData<T extends { time: ReturnType<typeof toUnixTime>; value: number }>(items: T[]): T[] {
  const byTime = new Map<number, T>();
  for (const item of items) {
    byTime.set(Number(item.time), item);
  }
  return Array.from(byTime.values()).sort((a, b) => Number(a.time) - Number(b.time));
}

export function buildSetupStateByZone(candidates: SetupCandidate[]): Map<string, SetupCandidate["status"]> {
  const rank: Record<SetupCandidate["status"], number> = {
    eligible: 4,
    waiting_confirmation: 3,
    watching: 2,
    blocked: 1,
    expired: 0,
  };
  const result = new Map<string, SetupCandidate["status"]>();
  for (const candidate of candidates) {
    const zoneId = candidate.primary_zone_id;
    if (!zoneId) continue;
    const current = result.get(zoneId);
    if (!current || rank[candidate.status] > rank[current]) {
      result.set(zoneId, candidate.status);
    }
  }
  return result;
}

export function roundPrice(price: number): number {
  return Math.round(price * 100) / 100;
}

export function filterVisibleZones(
  zones: PriceZone[],
  currentPrice: number,
  lastCandleTime: string,
  importantOnly: boolean,
  maxZones: number,
  selectedZoneId: string | null,
): PriceZone[] {
  if (!importantOnly) return zones;

  const pinned = zones.filter((zone) => zone.id === selectedZoneId || zone.id === "__manual_zone_preview__");
  const pinnedIds = new Set(pinned.map((zone) => zone.id));
  const ranked = zones
    .filter((zone) => !pinnedIds.has(zone.id))
    .map((zone) => ({ zone, score: zoneImportanceScore(zone, currentPrice, lastCandleTime) }))
    .sort((a, b) => b.score - a.score);

  const selected: PriceZone[] = [...pinned];
  const targetCount = Math.max(maxZones, pinned.length);
  for (const candidate of ranked) {
    if (selected.length >= targetCount) break;
    if (candidate.zone.weight < 0.45 && !isHumanZone(candidate.zone)) continue;
    const overlapsBetterZone = selected.some(
      (zone) => !isHumanZone(candidate.zone) && zone.id !== selectedZoneId && zonesVisuallyOverlap(zone, candidate.zone),
    );
    if (!overlapsBetterZone) {
      selected.push(candidate.zone);
    }
  }

  if (selected.length < targetCount) {
    const selectedIds = new Set(selected.map((zone) => zone.id));
    for (const candidate of ranked) {
      if (selected.length >= targetCount) break;
      if (selectedIds.has(candidate.zone.id)) continue;
      selected.push(candidate.zone);
      selectedIds.add(candidate.zone.id);
    }
  }

  return selected;
}

export function isZoneTypeVisible(zone: PriceZone, visibility: ZoneTypeVisibility): boolean {
  if (zone.id === "__manual_zone_preview__") return true;
  if (zone.type === "support") return visibility.support;
  if (zone.type === "resistance") return visibility.resistance;
  if (zone.type === "order_block") return visibility.order_block;
  if (zone.type === "fvg") return visibility.fvg;
  if (zone.type === "liquidity_pool") return visibility.liquidity_pool;
  if (zone.type === "consolidation") return visibility.consolidation;
  return true;
}

export function isHistoricalLiquiditySweep(zone: PriceZone): boolean {
  return zone.type === "liquidity_pool" && zone.status === "swept";
}

export function isZoneVisibleForPlaybooks(
  zone: PriceZone,
  playbooks: PlaybookKey[],
  showHistoricalLiquiditySweeps = false,
): boolean {
  if (playbooks.includes("liquidity_sweep_reclaim_v1") && isHistoricalLiquiditySweep(zone)) {
    return showHistoricalLiquiditySweeps;
  }
  return true;
}

export function focusZoneOnChart(
  chart: IChartApi | null,
  zone: PriceZone,
  candles: ChartPayload["layers"]["candles"],
  scheduleOverlayRecalc: () => void,
): void {
  if (!chart || candles.length === 0) return;
  const priceRange = chart.priceScale("right").getVisibleRange();
  const currentRange = chart.timeScale().getVisibleLogicalRange();
  const visibleBars = currentRange ? Math.max(currentRange.to - currentRange.from, 24) : Math.min(Math.max(candles.length, 80), 180);
  const focusTime = zoneFocusTime(zone);
  const focusIndex = nearestCandleIndex(candles, focusTime);
  const rightPaddingBars = Math.min(Math.max(visibleBars * 0.30, 12), 40);
  const from = Math.max(focusIndex - visibleBars + rightPaddingBars, -RIGHT_OFFSET_BARS);
  const to = from + visibleBars;

  chart.timeScale().setVisibleLogicalRange({ from, to });
  if (priceRange) {
    chart.priceScale("right").setVisibleRange(priceRange);
    requestAnimationFrame(() => {
      chart.priceScale("right").setVisibleRange(priceRange);
      scheduleOverlayRecalc();
    });
  } else {
    requestAnimationFrame(scheduleOverlayRecalc);
  }
}

export function focusTradeOnChart(
  chart: IChartApi | null,
  trade: TradeOrder,
  candles: ChartPayload["layers"]["candles"],
  scheduleOverlayRecalc: () => void,
): boolean {
  if (!chart || candles.length === 0 || !trade.opened_at) return false;
  const openedTime = toUnixTime(trade.opened_at);
  const firstTime = toUnixTime(candles[0].time);
  const lastTime = toUnixTime(candles[candles.length - 1].time);
  if (openedTime < firstTime || openedTime > lastTime) return false;
  const priceRange = chart.priceScale("right").getVisibleRange();
  const currentRange = chart.timeScale().getVisibleLogicalRange();
  const visibleBars = currentRange ? Math.max(currentRange.to - currentRange.from, 24) : Math.min(Math.max(candles.length, 80), 180);
  const focusIndex = nearestCandleIndex(candles, openedTime);
  const rightPaddingBars = Math.min(Math.max(visibleBars * 0.45, 16), 60);
  const from = Math.max(focusIndex - visibleBars + rightPaddingBars, -RIGHT_OFFSET_BARS);
  const to = from + visibleBars;

  chart.timeScale().setVisibleLogicalRange({ from, to });
  if (priceRange) {
    chart.priceScale("right").setVisibleRange(priceRange);
    requestAnimationFrame(() => {
      chart.priceScale("right").setVisibleRange(priceRange);
      scheduleOverlayRecalc();
    });
  } else {
    requestAnimationFrame(scheduleOverlayRecalc);
  }
  return true;
}

export function zoneStartCoordinate(
  timeScale: ReturnType<IChartApi["timeScale"]>,
  zone: PriceZone,
  candles: ChartPayload["layers"]["candles"],
): number | null {
  const startUnix = toUnixTime(zone.visual_start);
  const firstCandle = candles.at(0);
  const lastCandle = candles.at(-1);
  if (!firstCandle || !lastCandle) return null;

  if (startUnix < toUnixTime(firstCandle.time)) {
    return timeScale.timeToCoordinate(toUnixTime(firstCandle.time));
  }
  if (startUnix > toUnixTime(lastCandle.time)) {
    return null;
  }

  const directCoordinate = timeScale.timeToCoordinate(startUnix);
  if (directCoordinate !== null) return directCoordinate;

  const candleIndex = candles.findIndex((candle) => toUnixTime(candle.time) >= startUnix);
  if (candleIndex < 0) return null;
  return timeScale.logicalToCoordinate(candleIndex as Logical);
}

export function zoneEndCoordinate(
  chart: IChartApi,
  timeScale: ReturnType<IChartApi["timeScale"]>,
  zone: PriceZone,
  candles: ChartPayload["layers"]["candles"],
  lastCandleTime: string,
  width: number,
): number | null {
  if (zone.visual_end) {
    return projectedTimeCoordinate(timeScale, candles, toUnixTime(zone.visual_end));
  }
  return timeScale.timeToCoordinate(toUnixTime(lastCandleTime));
}

export function projectedTimeFromCoordinate(chart: IChartApi, candles: CandleDatum[], coordinate: number): number | null {
  if (candles.length === 0) return null;
  const logical = chart.timeScale().coordinateToLogical(coordinate);
  if (logical === null) return null;

  const logicalNumber = Number(logical);
  const first = candles[0];
  const last = candles[candles.length - 1];
  if (candles.length === 1) return Number(first.time);

  if (logicalNumber <= 0) {
    const step = Number(candles[1].time) - Number(first.time);
    return Math.round(Number(first.time) + logicalNumber * step);
  }

  const lastIndex = candles.length - 1;
  if (logicalNumber >= lastIndex) {
    const step = Number(last.time) - Number(candles[lastIndex - 1].time);
    return Math.round(Number(last.time) + (logicalNumber - lastIndex) * step);
  }

  const lowerIndex = Math.max(0, Math.floor(logicalNumber));
  const upperIndex = Math.min(lastIndex, Math.ceil(logicalNumber));
  if (lowerIndex === upperIndex) return Number(candles[lowerIndex].time);

  const lowerTime = Number(candles[lowerIndex].time);
  const upperTime = Number(candles[upperIndex].time);
  const progress = logicalNumber - lowerIndex;
  return Math.round(lowerTime + (upperTime - lowerTime) * progress);
}

export function zoneDragModeFromPointer(event: ReactPointerEvent<HTMLElement>, box: ZoneBox): ZoneDragMode {
  const rect = event.currentTarget.getBoundingClientRect();
  const y = event.clientY - rect.top;
  const x = event.clientX - rect.left;
  const verticalHandle = Math.min(22, Math.max(12, box.height * 0.42));
  const horizontalHandle = Math.min(16, Math.max(10, box.width * 0.04));

  if (y <= verticalHandle) return "resize-top";
  if (box.height - y <= verticalHandle) return "resize-bottom";
  if (x <= horizontalHandle) return "resize-left";
  if (box.width - x <= horizontalHandle) return "resize-right";
  return "move";
}

export function lockCurrentViewport(chart: IChartApi | null, targetRef: { current: ViewportState | null }): void {
  if (!chart) return;
  targetRef.current = readCurrentViewport(chart);
}

export function restoreLockedViewport(chart: IChartApi | null, targetRef: { current: ViewportState | null }): void {
  if (!chart || !targetRef.current) return;
  restoreViewport(chart, targetRef.current);
  requestAnimationFrame(() => {
    restoreViewport(chart, targetRef.current);
    requestAnimationFrame(() => restoreViewport(chart, targetRef.current));
  });
  window.setTimeout(() => restoreViewport(chart, targetRef.current), 80);
}

export function applyInitialViewport(chart: IChartApi, candles: CandleDatum[], requestedBars: number): void {
  if (candles.length === 0) return;
  const visibleBars = Math.min(candles.length, Math.max(50, requestedBars));
  applyCandleTimeViewport(chart, candles, visibleBars);
}

export function applyReplayTimeViewport(chart: IChartApi, candles: CandleDatum[], requestedBars: number): void {
  if (candles.length === 0) return;
  const visibleBars = Math.min(Math.max(REPLAY_VISIBLE_BARS, requestedBars), 220);
  applyCandleTimeViewport(chart, candles, Math.min(candles.length, visibleBars));
}

function applyCandleTimeViewport(chart: IChartApi, candles: CandleDatum[], visibleBars: number): void {
  const lastIndex = candles.length - 1;
  const fromIndex = Math.max(0, lastIndex - visibleBars + 1);
  const intervalSeconds = inferCandleIntervalSeconds(candles);
  const futureTime = (Number(candles[lastIndex].time) + RIGHT_OFFSET_BARS * intervalSeconds) as CandleDatum["time"];
  chart.timeScale().setVisibleRange({ from: candles[fromIndex].time, to: futureTime });
}

export function applyReplayPriceViewport(
  chart: IChartApi,
  candles: CandleDatum[],
  reset: boolean,
): PriceRange | null {
  if (candles.length === 0) return null;

  chart.priceScale("right").setAutoScale(false);
  const nextRange = reset ? buildReplayPriceRange(candles) : chart.priceScale("right").getVisibleRange() ?? buildReplayPriceRange(candles);
  chart.priceScale("right").setVisibleRange(nextRange);
  return nextRange;
}

export function applyInitialPriceViewport(chart: IChartApi, candles: CandleDatum[]): PriceRange | null {
  if (candles.length === 0) return null;
  chart.priceScale("right").setAutoScale(false);
  const range = buildFocusedPriceRange(candles, {
    focusBars: 48,
    averageRangeMultiplier: 5,
    priceMultiplier: 0.006,
    minimumAbsoluteRange: 12,
    paddingMultiplier: 1.15,
  });
  chart.priceScale("right").setVisibleRange(range);
  return range;
}

export function buildNewsTimelineMarkers(
  events: NewsEvent[],
  lastCandleTime: CandleDatum["time"],
  chartWidth: number,
  chartHeight: number,
  timeScale: ReturnType<IChartApi["timeScale"]>,
): NewsTimelineMarker[] {
  const horizon = Number(lastCandleTime) + NEWS_AXIS_HORIZON_HOURS * 3600;
  const y = clampNumber(chartHeight - 24, 18, Math.max(18, chartHeight - 18));

  return events.flatMap((event) => {
    const timestamp = Number(toUnixTime(event.scheduled_at));
    if (!Number.isFinite(timestamp) || timestamp > horizon) return [];
    const x = timeScale.timeToCoordinate(timestamp as CandleDatum["time"]);
    if (x === null || x < -12 || x > chartWidth + 12) return [];
    return [{ event, x, y, chartWidth, chartHeight }];
  });
}

export function buildScaleAnchorData(candles: CandleDatum[], events: NewsEvent[] = []): Array<{ time: CandleDatum["time"]; value: number }> {
  const last = candles.at(-1);
  if (!last) return [];

  const focusCandles = candles.slice(-96);
  const high = Math.max(...focusCandles.map((candle) => candle.high), last.close);
  const low = Math.min(...focusCandles.map((candle) => candle.low), last.close);
  const averageRange =
    focusCandles.reduce((sum, candle) => sum + Math.max(candle.high - candle.low, 0), 0) / Math.max(focusCandles.length, 1);
  const minimumHalfRange = Math.max(averageRange * 5, last.close * 0.0045, 1);
  const halfRange = Math.max(high - last.close, last.close - low, minimumHalfRange) * 1.08;
  const previousTime = candles.at(-2)?.time ?? ((last.time - 1) as CandleDatum["time"]);
  const intervalSeconds = inferCandleIntervalSeconds(candles);
  // Keep the synthetic series bounded by bars, not wall-clock news horizon.
  // A seven-day news event creates only 168 empty points on H1, but 2,016 on
  // M5. Lightweight Charts may then auto-shift the visible range to those
  // points after setData(), leaving the current candles off-screen.
  const futureEnd = futureAxisEndTime(Number(last.time), intervalSeconds);
  const anchorTimes = new Set<number>([Number(previousTime), Number(last.time)]);

  for (let time = Number(last.time) + intervalSeconds; time <= futureEnd; time += intervalSeconds) {
    anchorTimes.add(time);
  }

  for (const event of events) {
    const timestamp = Number(toUnixTime(event.scheduled_at));
    if (Number.isFinite(timestamp) && timestamp > Number(last.time) && timestamp <= futureEnd) {
      anchorTimes.add(timestamp);
    }
  }

  return [...anchorTimes]
    .sort((a, b) => a - b)
    .map((time, index) => ({
      time: time as CandleDatum["time"],
      value: index % 2 === 0 ? last.close + halfRange : last.close - halfRange,
    }));
}

export function defaultTradeModesForZone(zone: PriceZone): ZoneTradeMode[] {
  const raw = zone.metadata.trade_modes;
  if (Array.isArray(raw)) {
    return raw.filter((mode): mode is ZoneTradeMode => mode === "reject" || mode === "internal_reject" || mode === "breakout" || mode === "liquidity_sweep");
  }
  if (zone.type === "fvg") return ["reject", "internal_reject"];
  if (zone.type === "consolidation") return ["breakout"];
  if (zone.type === "support" || zone.type === "resistance") return ["reject"];
  return [];
}

export function chartTimeToUnix(time: unknown): number | null {
  if (typeof time === "number") return time;
  if (typeof time === "string") {
    const parsed = Date.parse(time);
    return Number.isNaN(parsed) ? null : Math.floor(parsed / 1000);
  }
  if (time && typeof time === "object" && "year" in time && "month" in time && "day" in time) {
    const businessDay = time as { year: number; month: number; day: number };
    return Math.floor(Date.UTC(businessDay.year, businessDay.month - 1, businessDay.day) / 1000);
  }
  return null;
}

export function unixToIso(timestamp: number): string {
  return new Date(Math.round(timestamp) * 1000).toISOString().replace(".000Z", "+00:00");
}

export function isoForZoneEnd(timestamp: number, lastCandleTime: string | undefined): string | null {
  if (!lastCandleTime) return unixToIso(timestamp);
  const lastTime = toUnixTime(lastCandleTime);
  if (timestamp >= lastTime) return null;
  return unixToIso(timestamp);
}

export function formatZoneDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return `${String(date.getDate()).padStart(2, "0")}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function isAddEntityKind(value: string): value is AddEntityKind {
  return [
    "support",
    "resistance",
    "demand_order_block",
    "supply_order_block",
    "bullish_fvg",
    "bearish_fvg",
    "consolidation",
    "buy_side_liquidity",
    "sell_side_liquidity",
  ].includes(value);
}

function zoneFocusTime(zone: PriceZone): number {
  const candidates = [zone.detected_at, zone.valid_from, zone.visual_start, zone.visual_end].flatMap((value) => {
    if (!value) return [];
    const time = toUnixTime(value);
    return Number.isFinite(time) ? [time] : [];
  });
  return candidates[0] ?? 0;
}

function nearestCandleIndex(candles: ChartPayload["layers"]["candles"], targetTime: number): number {
  let bestIndex = 0;
  let bestDistance = Number.POSITIVE_INFINITY;
  candles.forEach((candle, index) => {
    const distance = Math.abs(toUnixTime(candle.time) - targetTime);
    if (distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  return bestIndex;
}

function zoneImportanceScore(zone: PriceZone, currentPrice: number, lastCandleTime: string): number {
  const center = (zone.price_low + zone.price_high) / 2;
  const zoneWidth = Math.max(zone.price_high - zone.price_low, 1);
  const distance = Math.abs(center - currentPrice);
  const proximity = 1 / (1 + distance / Math.max(currentPrice * 0.008, zoneWidth * 3, 1));
  const anchorTime = Date.parse(zone.detected_at || zone.visual_start);
  const lastTime = Date.parse(lastCandleTime);
  const ageDays = Number.isFinite(anchorTime) && Number.isFinite(lastTime) ? Math.max((lastTime - anchorTime) / 86_400_000, 0) : 0;
  const recency = 1 / (1 + ageDays / 21);
  const activeBoost = zone.status === "active" ? 0.12 : 0;
  const humanBoost = isHumanZone(zone) ? 0.18 : 0;

  return zone.weight * 0.48 + proximity * 0.24 + recency * 0.16 + activeBoost + humanBoost;
}

function zonesVisuallyOverlap(a: PriceZone, b: PriceZone): boolean {
  if (a.type !== b.type || a.direction !== b.direction) return false;
  const overlap = Math.min(a.price_high, b.price_high) - Math.max(a.price_low, b.price_low);
  if (overlap <= 0) return false;
  const smallerWidth = Math.max(Math.min(a.price_high - a.price_low, b.price_high - b.price_low), 0.01);
  return overlap / smallerWidth >= 0.45;
}

function isHumanZone(zone: PriceZone): boolean {
  return zone.source === "human" || zone.metadata.human_created === true;
}

function projectedTimeCoordinate(
  timeScale: ReturnType<IChartApi["timeScale"]>,
  candles: ChartPayload["layers"]["candles"],
  targetTime: ReturnType<typeof toUnixTime>,
): number | null {
  const directCoordinate = timeScale.timeToCoordinate(targetTime);
  if (directCoordinate !== null) return directCoordinate;
  if (candles.length === 0) return null;

  const candleTimes = candles.map((candle) => toUnixTime(candle.time));
  const targetUnix = Number(targetTime);
  let anchorIndex = -1;
  for (let index = candleTimes.length - 1; index >= 0; index -= 1) {
    if (Number(candleTimes[index]) <= targetUnix) {
      anchorIndex = index;
      break;
    }
  }
  if (anchorIndex < 0) anchorIndex = 0;

  const anchorCoordinate = timeScale.timeToCoordinate(candleTimes[anchorIndex]);
  if (anchorCoordinate === null) return null;

  const nextIndex = Math.min(anchorIndex + 1, candles.length - 1);
  const previousIndex = Math.max(anchorIndex - 1, 0);
  const neighborIndex = nextIndex !== anchorIndex ? nextIndex : previousIndex;
  if (neighborIndex === anchorIndex) return anchorCoordinate;

  const neighborCoordinate = timeScale.timeToCoordinate(candleTimes[neighborIndex]);
  if (neighborCoordinate === null) return anchorCoordinate;

  const timeDelta = Number(candleTimes[neighborIndex]) - Number(candleTimes[anchorIndex]);
  if (timeDelta === 0) return anchorCoordinate;

  const pixelsPerSecond = (neighborCoordinate - anchorCoordinate) / timeDelta;
  return anchorCoordinate + (targetUnix - Number(candleTimes[anchorIndex])) * pixelsPerSecond;
}

export function readCurrentViewport(chart: IChartApi): ViewportState {
  return {
    logicalRange: chart.timeScale().getVisibleLogicalRange(),
    priceRange: chart.priceScale("right").getVisibleRange(),
  };
}

export function restoreViewport(chart: IChartApi, viewport: ViewportState | null): void {
  if (!viewport) return;
  if (viewport.logicalRange) {
    chart.timeScale().setVisibleLogicalRange(viewport.logicalRange);
  }
  if (viewport.priceRange) {
    chart.priceScale("right").setAutoScale(false);
    chart.priceScale("right").setVisibleRange(viewport.priceRange);
  }
}

function buildReplayPriceRange(candles: CandleDatum[]): PriceRange {
  return buildFocusedPriceRange(candles, {
    focusBars: VERTICAL_FOCUS_BARS,
    averageRangeMultiplier: 6,
    priceMultiplier: 0.0075,
    minimumAbsoluteRange: 20,
    paddingMultiplier: 1.18,
  });
}

function buildFocusedPriceRange(
  candles: CandleDatum[],
  options: {
    focusBars: number;
    averageRangeMultiplier: number;
    priceMultiplier: number;
    minimumAbsoluteRange: number;
    paddingMultiplier: number;
  },
): PriceRange {
  const last = candles.at(-1);
  if (!last) return { from: 0, to: 1 };

  const focusCandles = candles.slice(-options.focusBars);
  const high = Math.max(...focusCandles.map((candle) => candle.high), last.close);
  const low = Math.min(...focusCandles.map((candle) => candle.low), last.close);
  const averageRange =
    focusCandles.reduce((sum, candle) => sum + Math.max(candle.high - candle.low, 0), 0) / Math.max(focusCandles.length, 1);
  const minimumHalfRange = Math.max(
    averageRange * options.averageRangeMultiplier,
    last.close * options.priceMultiplier,
    options.minimumAbsoluteRange,
  );
  const halfRange = Math.max(high - last.close, last.close - low, minimumHalfRange) * options.paddingMultiplier;

  return {
    from: last.close - halfRange,
    to: last.close + halfRange,
  };
}

function inferCandleIntervalSeconds(candles: CandleDatum[]): number {
  const intervals: number[] = [];
  const firstIndex = Math.max(1, candles.length - 32);
  for (let index = firstIndex; index < candles.length; index += 1) {
    const interval = Number(candles[index].time) - Number(candles[index - 1].time);
    if (interval > 0) intervals.push(interval);
  }
  if (intervals.length === 0) return 3600;
  intervals.sort((left, right) => left - right);
  return intervals[Math.floor(intervals.length / 2)];
}

function futureAxisEndTime(lastTime: number, intervalSeconds: number): number {
  return lastTime + RIGHT_OFFSET_BARS * intervalSeconds;
}
