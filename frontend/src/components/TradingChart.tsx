import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  LineSeries,
  LineStyle,
} from "lightweight-charts";
import { ArrowDown, ArrowUp, Newspaper, Star } from "lucide-react";
import { type PointerEvent as ReactPointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createManualZone, updateZoneOverride, type NewsResponse } from "../api/chart";
import { createChartDrawing, deleteChartDrawing, updateChartDrawing } from "../api/chartDrawings";
import { h1ImpulsePreviewToSetupCandidate, previewH1Impulse, type H1ImpulsePreview, type H1ImpulseTargetMode } from "../api/h1Impulse";
import { updateManualAiPlanLevels } from "../api/manualAi";
import { isEditableHotkeyTarget } from "../lib/appHotkeys";
import { copyTextToClipboard } from "../lib/clipboard";
import { toUnixTime } from "../lib/time";
import { isMobileChartWidth, visibleChartBars } from "../lib/mobileChart";
import { useChartStore } from "../store/chartStore";
import {
  applyInitialPriceViewport,
  applyInitialViewport,
  applyReplayPriceViewport,
  applyReplayTimeViewport,
  buildNewsTimelineMarkers,
  buildScaleAnchorData,
  buildSetupStateByZone,
  buildZigZagSeriesData,
  chartPlotWidth,
  chartTimeToUnix,
  compactClassName,
  defaultTradeModesForZone,
  filterVisibleZones,
  formatZoneDate,
  focusTradeOnChart,
  focusZoneOnChart,
  isStructurePointAvailable,
  isZoneTypeVisible,
  isZoneVisibleForPlaybooks,
  isoForZoneEnd,
  lockCurrentViewport,
  manualZoneSpec,
  normalizeCandleData,
  projectedTimeFromCoordinate,
  readCurrentViewport,
  readSwingType,
  restoreLockedViewport,
  restoreViewport,
  roundPrice,
  swingLabel,
  unixToIso,
  zoneDisplayName,
  zoneDragModeFromPointer,
  zoneEndCoordinate,
  zoneStartCoordinate,
  zoneVisualClasses,
  type PriceRange,
  type ViewportState,
} from "./chart/chartCore";
import type { H1ImpulseChartMarker, M15TriggerMarker, StructureDot, SwingDot, ZoneBox, ZoneDragMode, ZoneDragState } from "./chart/chartTypes";
import { CandleCountdown, NewsTimelineTooltip, type NewsTimelineMarker } from "./chart/chartWidgets";
import { ChartDrawingControls, type PendingChartNote } from "./chart/ChartDrawingControls";
import { CandleInfoCard } from "./chart/CandleInfoCard";
import { isCandleShapeHit } from "./chart/candleInfo";
import { ManualAiLevelEditDialog, type ManualAiEditableLevels } from "./chart/ManualAiLevelEditDialog";
import { IntradayMapPanel } from "./chart/IntradayMapPanel";
import { WaveStrengthBadge } from "./chart/WaveStrengthBadge";
import { levelStatusLabel, selectIntradayLevels } from "./chart/intradayMap";
import { formatWaveDuration, formatWaveLegLabel } from "./chart/waveMetrics";
import { type DrawingPoint, type MeasurePreview, type PriceGuide, type RenderedChartDrawing } from "./chart/ChartDrawingLayer";
import { candleSeriesKey, classifyCandleSeriesChange } from "./chart/candleUpdates";
import {
  clampNumber,
  compactTradeGroupSummary,
  groupTradeBoxesByCandidate,
  interpolateChartX,
  readObject,
  setupToBox,
  tradeAccountCount,
  tradeGroupSummary,
  tradeToBox,
  type CandleDatum,
  type SetupBox,
  type TradeBox,
} from "./chart/tradeOverlay";
import type {
  AddEntityKind,
  ChartCandle,
  ChartDrawing,
  ChartDrawingAnchor,
  ChartDrawingTool,
  ChartPayload,
  IntradayLevel,
  M15TriggerOverlay,
  PriceZone,
  SetupCandidate,
  SpreadSummary,
  StructurePoint,
  TradeOrder,
  WaveLeg,
  ZoneTypeVisibility,
} from "../types";

type TradingChartProps = {
  payload: ChartPayload;
  drawings?: ChartDrawing[];
  spread?: SpreadSummary | null;
  newsData?: NewsResponse | null;
  onEntityCreated: () => void;
  onZonePersisted?: (zone: PriceZone) => void;
  onDrawingsChanged?: () => void;
};

type ManualDrawState = {
  kind: AddEntityKind;
  startPointerPrice: number;
  startPointerTime: number;
};

type ManualAiLevel = "entry" | "stopLoss" | "takeProfit";

type ManualAiLevelEditState = {
  candidate: SetupCandidate;
  level: ManualAiLevel;
  original: ManualAiEditableLevels;
  levels: ManualAiEditableLevels;
  entrySource: string;
  previewBox: SetupBox;
  status: string;
  dragging: boolean;
  saving: boolean;
  error: string | null;
};

const MIN_ZONE_HEIGHT = 0.01;
const MIN_ZONE_DURATION_SECONDS = 60;


export function TradingChart({ payload, drawings = [], spread, newsData, onEntityCreated, onZonePersisted, onDrawingsChanged }: TradingChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const scaleAnchorSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const zigzagSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const setSelected = useChartStore((state) => state.setSelected);
  const selected = useChartStore((state) => state.selected);
  const selectedSetupId = useChartStore((state) => state.selectedSetupId);
  const manualAiEditSetupId = useChartStore((state) => state.manualAiEditSetupId);
  const selectSetup = useChartStore((state) => state.selectSetup);
  const setManualAiEditSetupId = useChartStore((state) => state.setManualAiEditSetupId);
  const setInspectorTab = useChartStore((state) => state.setInspectorTab);
  const toggleSelectedPlaybook = useChartStore((state) => state.toggleSelectedPlaybook);
  const h1ImpulsePreviews = useChartStore((state) => state.h1ImpulsePreviews);
  const addH1ImpulsePreview = useChartStore((state) => state.addH1ImpulsePreview);
  const updateH1ImpulsePreviewLevels = useChartStore((state) => state.updateH1ImpulsePreviewLevels);
  const showZones = useChartStore((state) => state.showZones);
  const zoneTypeVisibility = useChartStore((state) => state.zoneTypeVisibility);
  const selectedPlaybooks = useChartStore((state) => state.selectedPlaybooks);
  const showHistoricalLiquiditySweeps = useChartStore((state) => state.showHistoricalLiquiditySweeps);
  const showStructure = useChartStore((state) => state.showStructure);
  const showIntradayLevels = useChartStore((state) => state.showIntradayLevels);
  const showBrokenIntradayLevels = useChartStore((state) => state.showBrokenIntradayLevels);
  const showH1ImpulseCandidates = useChartStore((state) => state.showH1ImpulseCandidates);
  const h1ImpulseEligibleOnly = useChartStore((state) => state.h1ImpulseEligibleOnly);
  const tradeVisibilityMode = useChartStore((state) => state.tradeVisibilityMode);
  const importantZonesOnly = useChartStore((state) => state.importantZonesOnly);
  const maxVisibleZones = useChartStore((state) => state.maxVisibleZones);
  const addEntityKind = useChartStore((state) => state.addEntityKind);
  const zoneFocusRequest = useChartStore((state) => state.zoneFocusRequest);
  const tradeFocusRequest = useChartStore((state) => state.tradeFocusRequest);
  const setAddEntityKind = useChartStore((state) => state.setAddEntityKind);
  const [zoneBoxes, setZoneBoxes] = useState<ZoneBox[]>([]);
  const [structureDots, setStructureDots] = useState<StructureDot[]>([]);
  const [swingDots, setSwingDots] = useState<SwingDot[]>([]);
  const [tradeBoxes, setTradeBoxes] = useState<TradeBox[]>([]);
  const [setupBoxes, setSetupBoxes] = useState<SetupBox[]>([]);
  const [manualAiLevelEdit, setManualAiLevelEdit] = useState<ManualAiLevelEditState | null>(null);
  const [m15TriggerMarkers, setM15TriggerMarkers] = useState<M15TriggerMarker[]>([]);
  const [h1ImpulseChartMarkers, setH1ImpulseChartMarkers] = useState<H1ImpulseChartMarker[]>([]);
  const [waveMetricMarkers, setWaveMetricMarkers] = useState<Array<{ leg: WaveLeg; x: number; y: number }>>([]);
  const [intradayLevelMarkers, setIntradayLevelMarkers] = useState<Array<{ level: IntradayLevel; y: number; bandY: number; bandHeight: number; plotWidth: number }>>([]);
  const [newsTimelineMarkers, setNewsTimelineMarkers] = useState<NewsTimelineMarker[]>([]);
  const [hoveredNewsMarker, setHoveredNewsMarker] = useState<NewsTimelineMarker | null>(null);
  const [hoveredZoneId, setHoveredZoneId] = useState<string | null>(null);
  const [drawPreviewZone, setDrawPreviewZone] = useState<PriceZone | null>(null);
  const [drawError, setDrawError] = useState<string | null>(null);
  const [drawingTool, setDrawingTool] = useState<ChartDrawingTool>("cursor");
  const [renderedDrawings, setRenderedDrawings] = useState<RenderedChartDrawing[]>([]);
  const [measurePreview, setMeasurePreview] = useState<MeasurePreview | null>(null);
  const [copyPriceGuide, setCopyPriceGuide] = useState<PriceGuide | null>(null);
  const [selectedDrawingId, setSelectedDrawingId] = useState<string | null>(null);
  const [drawingPlotWidth, setDrawingPlotWidth] = useState(0);
  const [drawingMessage, setDrawingMessage] = useState<string | null>(null);
  const [pendingNote, setPendingNote] = useState<PendingChartNote | null>(null);
  const [noteContent, setNoteContent] = useState("");
  const [candleLabel, setCandleLabel] = useState<{ priceY: number; scaleWidth: number; isUp: boolean; chartHeight: number } | null>(null);
  const [selectedCandle, setSelectedCandle] = useState<ChartCandle | null>(null);
  const [selectedCandleMarker, setSelectedCandleMarker] = useState<{ x: number; y: number; width: number; height: number } | null>(null);
  const [h1PreviewLoading, setH1PreviewLoading] = useState(false);
  const [h1PreviewError, setH1PreviewError] = useState<string | null>(null);
  const [h1TargetQuote, setH1TargetQuote] = useState<H1ImpulsePreview | null>(null);
  const [h1TargetQuoteLoading, setH1TargetQuoteLoading] = useState(false);
  const [pointerY, setPointerY] = useState<number | null>(null);
  const scheduledRecalcRef = useRef<number | null>(null);
  const interactionRecalcRef = useRef<number | null>(null);
  const wheelStopRef = useRef<number | null>(null);
  const draftZoneRef = useRef<PriceZone | null>(null);
  const zoneDragRef = useRef<ZoneDragState | null>(null);
  const manualDrawRef = useRef<ManualDrawState | null>(null);
  const manualAiLevelDragRef = useRef<{ candidateId: string; level: ManualAiLevel; moved: boolean } | null>(null);
  const drawingInteractionRef = useRef<{ tool: "fib_standard" | "fib_ote"; start: DrawingPoint } | null>(null);
  const measureStartRef = useRef<DrawingPoint | null>(null);
  const drawingMoveRef = useRef<{ drawing: ChartDrawing; startX: number; startY: number; moved: boolean } | null>(null);
  const drawingDraftAnchorRef = useRef<{ id: string; anchor: ChartDrawingAnchor } | null>(null);
  const payloadRef = useRef(payload);
  const showZonesRef = useRef(showZones);
  const zoneTypeVisibilityRef = useRef(zoneTypeVisibility);
  const selectedPlaybooksRef = useRef(selectedPlaybooks);
  const showHistoricalLiquiditySweepsRef = useRef(showHistoricalLiquiditySweeps);
  const showStructureRef = useRef(showStructure);
  const showIntradayLevelsRef = useRef(showIntradayLevels);
  const showBrokenIntradayLevelsRef = useRef(showBrokenIntradayLevels);
  const showH1ImpulseCandidatesRef = useRef(showH1ImpulseCandidates);
  const h1ImpulseEligibleOnlyRef = useRef(h1ImpulseEligibleOnly);
  const drawingToolRef = useRef(drawingTool);
  const selectedCandleRef = useRef(selectedCandle);
  const selectedSetupIdRef = useRef(selectedSetupId);
  const h1ImpulsePreviewsRef = useRef(h1ImpulsePreviews);
  const tradeVisibilityModeRef = useRef(tradeVisibilityMode);
  const importantZonesOnlyRef = useRef(importantZonesOnly);
  const maxVisibleZonesRef = useRef(maxVisibleZones);
  const addEntityKindRef = useRef(addEntityKind);
  const onEntityCreatedRef = useRef(onEntityCreated);
  const onZonePersistedRef = useRef(onZonePersisted);
  const newsDataRef = useRef(newsData);
  const drawingsRef = useRef(drawings);
  const handledZoneFocusRequestRef = useRef<number | null>(null);
  const handledTradeFocusRequestRef = useRef<number | null>(null);
  const drawPreviewZoneRef = useRef<PriceZone | null>(drawPreviewZone);
  const persistedZoneDraftRef = useRef<PriceZone | null>(null);
  const candleDataRef = useRef<CandleDatum[]>([]);
  const appliedCandleDataRef = useRef<CandleDatum[]>([]);
  const appliedCandleKeyRef = useRef<string | null>(null);
  const appliedViewKeyRef = useRef<string | null>(null);
  const replayPriceRangeRef = useRef<PriceRange | null>(null);
  const lockedViewportRef = useRef<ViewportState | null>(null);
  const lastViewportRef = useRef<ViewportState | null>(null);
  const manualViewportRef = useRef(false);

  const candleData = useMemo(
    () => normalizeCandleData(
      payload.layers.candles.map((candle) => ({
        time: toUnixTime(candle.time),
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      })),
    ),
    [payload.layers.candles],
  );
  // Include every OHLC value. MT5 can finalize/correct a candle after the tab
  // was backgrounded, so tracking only the latest close leaves stale history.
  const candleKey = useMemo(
    () => `${payload.symbol}:${payload.timeframe}:${candleSeriesKey(candleData)}`,
    [candleData, payload.symbol, payload.timeframe],
  );
  const viewKey = `${payload.symbol}:${payload.timeframe}:${payload.range.limit}:${payload.range.start_index ?? "latest"}`;
  const setupStateByZone = useMemo(() => buildSetupStateByZone(payload.layers.setup_candidates), [payload.layers.setup_candidates]);

  showZonesRef.current = showZones;
  zoneTypeVisibilityRef.current = zoneTypeVisibility;
  selectedPlaybooksRef.current = selectedPlaybooks;
  showHistoricalLiquiditySweepsRef.current = showHistoricalLiquiditySweeps;
  showStructureRef.current = showStructure;
  showIntradayLevelsRef.current = showIntradayLevels;
  showBrokenIntradayLevelsRef.current = showBrokenIntradayLevels;
  showH1ImpulseCandidatesRef.current = showH1ImpulseCandidates;
  h1ImpulseEligibleOnlyRef.current = h1ImpulseEligibleOnly;
  drawingToolRef.current = drawingTool;
  selectedCandleRef.current = selectedCandle;
  selectedSetupIdRef.current = selectedSetupId;
  h1ImpulsePreviewsRef.current = h1ImpulsePreviews;
  tradeVisibilityModeRef.current = tradeVisibilityMode;
  importantZonesOnlyRef.current = importantZonesOnly;
  maxVisibleZonesRef.current = maxVisibleZones;
  addEntityKindRef.current = addEntityKind;
  onEntityCreatedRef.current = onEntityCreated;
  onZonePersistedRef.current = onZonePersisted;
  newsDataRef.current = newsData;
  drawingsRef.current = drawings;
  drawPreviewZoneRef.current = drawPreviewZone;
  candleDataRef.current = candleData;

  useEffect(() => {
    if (!selectedSetupId) return;
    const stillVisible = payload.layers.setup_candidates.some((candidate) => candidate.id === selectedSetupId)
      || h1ImpulsePreviews.some((candidate) => candidate.id === selectedSetupId);
    if (!stillVisible) selectSetup(null);
  }, [h1ImpulsePreviews, payload.layers.setup_candidates, selectSetup, selectedSetupId]);

  useEffect(() => {
    if (!selectedCandle) return;
    const refreshed = payload.layers.candles.find((candle) => candle.time === selectedCandle.time);
    if (!refreshed) {
      setSelectedCandle(null);
      return;
    }
    if (
      refreshed.open !== selectedCandle.open
      || refreshed.high !== selectedCandle.high
      || refreshed.low !== selectedCandle.low
      || refreshed.close !== selectedCandle.close
      || refreshed.volume !== selectedCandle.volume
    ) {
      setSelectedCandle(refreshed);
    }
  }, [payload.layers.candles, selectedCandle]);

  useEffect(() => {
    if (selected || selectedSetupId || manualAiEditSetupId || addEntityKind) {
      setSelectedCandle(null);
    }
  }, [addEntityKind, manualAiEditSetupId, selected, selectedSetupId]);

  const recalcOverlays = useCallback(() => {
    const chart = chartRef.current;
    const series = candleSeriesRef.current;
    const container = containerRef.current;
    const currentPayload = payloadRef.current;
    const lastCandle = currentPayload.layers.candles.at(-1);
    if (!chart || !series || !container || !lastCandle) return;

    const width = container.clientWidth;
    const plotWidth = chartPlotWidth(chart, width);
    const height = container.clientHeight;
    const timeScale = chart.timeScale();
    const draftZone = draftZoneRef.current;
    const previewZone = drawPreviewZoneRef.current;
    const zoneCandidates = (previewZone ? [...currentPayload.layers.zones, previewZone] : currentPayload.layers.zones).filter(
      (zone) =>
        isZoneTypeVisible(zone, zoneTypeVisibilityRef.current) &&
        isZoneVisibleForPlaybooks(
          zone,
          selectedPlaybooksRef.current,
          showHistoricalLiquiditySweepsRef.current,
        ),
    );
    const currentSelected = useChartStore.getState().selected;
    const selectedZoneId = currentSelected?.kind === "zone" ? currentSelected.entity.id : null;
    const visibleZoneCandidates = filterVisibleZones(
      zoneCandidates,
      lastCandle.close,
      lastCandle.time,
      importantZonesOnlyRef.current,
      maxVisibleZonesRef.current,
      selectedZoneId,
    );
    const zones = (showZonesRef.current || previewZone)
      ? visibleZoneCandidates.flatMap((zone) => {
          const effectiveZone = draftZone?.id === zone.id ? draftZone : zone;
          const start = zoneStartCoordinate(timeScale, effectiveZone, currentPayload.layers.candles);
          const end = zoneEndCoordinate(chart, timeScale, effectiveZone, currentPayload.layers.candles, lastCandle.time, plotWidth);
          const top = series.priceToCoordinate(effectiveZone.price_high);
          const bottom = series.priceToCoordinate(effectiveZone.price_low);
          if (start === null) return [];
          if (top === null || bottom === null) return [];
          if ((top < 0 && bottom < 0) || (top > height && bottom > height)) return [];

          const x1 = start;
          const x2 = end ?? width;
          const left = Math.max(0, Math.min(x1, x2));
          const right = Math.min(plotWidth, Math.max(x1, x2));
          const y1 = Math.max(0, Math.min(top, bottom));
          const y2 = Math.min(height, Math.max(top, bottom));
          if (right <= 0 || left >= plotWidth || y2 <= 0 || y1 >= height) return [];
          return [{ zone: effectiveZone, x: left, y: y1, width: Math.max(2, right - left), height: Math.max(2, y2 - y1) }];
        })
      : [];

    const structurePoints = showStructureRef.current
      ? currentPayload.layers.structure.flatMap((point) => {
          if (!isStructurePointAvailable(point, currentPayload.range.end, currentPayload.replay?.as_of)) return [];
          const x = timeScale.timeToCoordinate(toUnixTime(point.time));
          const y = series.priceToCoordinate(point.price);
          if (x === null || y === null) return [];
          return [{ point, x, y }];
        })
      : [];
    const allSwings = structurePoints.flatMap((dot) => {
      const swingType = readSwingType(dot.point);
      if (!swingType) return [];
      return [{ ...dot, swingType, label: swingLabel(dot.point, swingType) }];
    });
    const visibleStructurePoints = structurePoints.filter(
      ({ x, y }) => x >= -12 && x <= plotWidth + 12 && y >= -12 && y <= height + 12,
    );
    const visibleSwings = allSwings.filter(({ x, y }) => x >= -12 && x <= plotWidth + 12 && y >= -12 && y <= height + 12);
    const chartTrades =
      tradeVisibilityModeRef.current === "off"
        ? []
        : currentPayload.layers.trades.filter(
            (trade) =>
              tradeVisibilityModeRef.current === "all"
              || (tradeVisibilityModeRef.current === "hidden" ? trade.hidden_on_chart : !trade.hidden_on_chart),
          );
    const tradeBoxes = chartTrades.flatMap((trade) => {
      const box = tradeToBox(trade, currentPayload.range.start, currentPayload.range.end, candleDataRef.current, plotWidth, height, timeScale, series);
      return box ? [box] : [];
    });
    const trades = groupTradeBoxesByCandidate(tradeBoxes);
    const visibleSetupCandidates = [
      ...currentPayload.layers.setup_candidates,
      ...(selectedPlaybooksRef.current.includes("h1_impulse_retest_v1") ? h1ImpulsePreviewsRef.current : []),
    ].filter((candidate) => candidate.status !== "expired" || candidate.id === selectedSetupIdRef.current);
    const chartSetups = visibleSetupCandidates.flatMap((candidate) => {
      const isManualAi = candidate.metadata.manual_ai === true
        && candidate.metadata.execution_state === "primary"
        && candidate.status === "waiting_confirmation";
      const isH1ImpulsePreview = candidate.metadata.h1_impulse_preview === true;
      if (!isManualAi && !isH1ImpulsePreview) return [];
      const box = setupToBox(
        candidate,
        currentPayload.range.start,
        currentPayload.range.end,
        candleDataRef.current,
        plotWidth,
        height,
        timeScale,
        series,
      );
      return box ? [box] : [];
    });
    const visibleM15Triggers = filterVisibleM15Triggers(currentPayload.layers.m15_triggers ?? []);
    const m15Triggers = visibleM15Triggers.flatMap((trigger) => {
      const x = interpolateChartX(timeScale, toUnixTime(trigger.time), candleDataRef.current);
      const y = series.priceToCoordinate(trigger.close);
      if (x === null || y === null) return [];
      if (x < -12 || x > plotWidth + 12 || y < -12 || y > height + 12) return [];
      return [{ trigger, x, y }];
    });
    const h1Markers = selectedPlaybooksRef.current.includes("h1_impulse_retest_v1")
      && showH1ImpulseCandidatesRef.current
      && currentPayload.timeframe === "H1"
      ? (currentPayload.layers.h1_impulse_markers ?? []).flatMap((marker) => {
          if (h1ImpulseEligibleOnlyRef.current && marker.status !== "eligible") return [];
          const candle = currentPayload.layers.candles.find((item) => item.time === marker.time);
          if (!candle) return [];
          const x = timeScale.timeToCoordinate(toUnixTime(marker.time));
          const anchorPrice = marker.direction === "short" ? candle.high : candle.low;
          const y = series.priceToCoordinate(anchorPrice);
          if (x === null || y === null || x < -12 || x > plotWidth + 12 || y < -12 || y > height + 12) return [];
          return [{ marker, x, y }];
        })
      : [];
    const waveLegs = showStructureRef.current
      ? (currentPayload.layers.wave_metrics?.legs ?? []).slice(-12)
      : [];
    const waveMarkers = waveLegs.flatMap((leg) => {
      const endX = timeScale.timeToCoordinate(toUnixTime(leg.end_time));
      const y = series.priceToCoordinate(leg.end_price);
      if (endX === null || y === null || endX < -12 || endX > plotWidth + 12 || y < -12 || y > height + 12) return [];
      const x = clampNumber(endX, 58, Math.max(58, plotWidth - 58));
      return [{ leg, x, y }];
    });
    const rawIntradayLevels = showIntradayLevelsRef.current
      ? selectIntradayLevels(
          currentPayload.layers.intraday_map,
          isMobileChartWidth(width),
          showBrokenIntradayLevelsRef.current,
        ).flatMap((level) => {
          const y = series.priceToCoordinate(level.price);
          const approachTop = series.priceToCoordinate(level.approach_high);
          const approachBottom = series.priceToCoordinate(level.approach_low);
          if (y === null || approachTop === null || approachBottom === null || y < -12 || y > height + 12) return [];
          return [{
            level,
            y,
            bandY: Math.min(approachTop, approachBottom),
            bandHeight: Math.max(2, Math.abs(approachBottom - approachTop)),
            plotWidth,
          }];
        })
      : [];
    const intradayLevels = rawIntradayLevels.reduce<typeof rawIntradayLevels>((visible, marker) => {
      const overlappingIndex = visible.findIndex((other) => Math.abs(other.y - marker.y) < 13);
      if (overlappingIndex < 0) {
        visible.push(marker);
        return visible;
      }
      const existing = visible[overlappingIndex];
      const mergeTolerance = Math.max(0.05, (currentPayload.layers.intraday_map.approach_allowance ?? 0) * 0.1);
      if (Math.abs(existing.level.price - marker.level.price) <= mergeTolerance) {
        const labels = new Set([...existing.level.label.split(" / "), ...marker.level.label.split(" / ")]);
        visible[overlappingIndex] = {
          ...existing,
          level: {
            ...existing.level,
            label: Array.from(labels).join(" / "),
            status: existing.level.live || marker.level.live ? "live" : existing.level.status,
            live: existing.level.live || marker.level.live,
          },
        };
      }
      return visible;
    }, []);
    const newsMarkers = buildNewsTimelineMarkers(newsDataRef.current?.events ?? [], toUnixTime(lastCandle.time), plotWidth, height, timeScale);
    const chartDrawings = drawingsRef.current.flatMap((drawing) => {
      const draftAnchor = drawingDraftAnchorRef.current?.id === drawing.id ? drawingDraftAnchorRef.current.anchor : null;
      const effectiveAnchors = draftAnchor ? [draftAnchor, ...drawing.anchors.slice(1)] : drawing.anchors;
      const points = effectiveAnchors.flatMap((anchor) => {
        const x = interpolateChartX(timeScale, toUnixTime(anchor.time), candleDataRef.current);
        const y = series.priceToCoordinate(anchor.price);
        if (x === null || y === null) return [];
        return [{ x, y, price: anchor.price, time: anchor.time }];
      });
      if (points.length !== effectiveAnchors.length) return [];
      return [{ drawing, points }];
    });
    const selectedCandleValue = selectedCandleRef.current;
    let selectedMarker: { x: number; y: number; width: number; height: number } | null = null;
    if (selectedCandleValue) {
      const selectedTime = toUnixTime(selectedCandleValue.time);
      const x = timeScale.timeToCoordinate(selectedTime);
      const highY = series.priceToCoordinate(selectedCandleValue.high);
      const lowY = series.priceToCoordinate(selectedCandleValue.low);
      if (x !== null && highY !== null && lowY !== null) {
        const selectedIndex = candleDataRef.current.findIndex((candle) => Number(candle.time) === Number(selectedTime));
        const neighbor = selectedIndex > 0
          ? candleDataRef.current[selectedIndex - 1]
          : candleDataRef.current[selectedIndex + 1];
        const neighborX = neighbor ? timeScale.timeToCoordinate(neighbor.time) : null;
        const barWidth = clampNumber(neighborX === null ? 8 : Math.abs(x - neighborX) * 0.72, 4, 16);
        const top = Math.min(highY, lowY) - 3;
        const bottom = Math.max(highY, lowY) + 3;
        if (x >= -barWidth && x <= plotWidth + barWidth && bottom >= 0 && top <= height) {
          selectedMarker = {
            x: x - barWidth / 2,
            y: Math.max(0, top),
            width: barWidth,
            height: Math.max(6, Math.min(height, bottom) - Math.max(0, top)),
          };
        }
      }
    }

    setZoneBoxes(zones);
    setStructureDots(visibleStructurePoints.filter((dot) => !readSwingType(dot.point)));
    setSwingDots(visibleSwings);
    setTradeBoxes(trades);
    setSetupBoxes(chartSetups);
    setM15TriggerMarkers(m15Triggers);
    setH1ImpulseChartMarkers(h1Markers);
    setWaveMetricMarkers(waveMarkers);
    setIntradayLevelMarkers(intradayLevels);
    setNewsTimelineMarkers(newsMarkers);
    setRenderedDrawings(chartDrawings);
    setDrawingPlotWidth(plotWidth);
    setSelectedCandleMarker(selectedMarker);

    const priceY = series.priceToCoordinate(lastCandle.close);
    if (typeof priceY === "number" && priceY >= 0 && priceY <= height) {
      setCandleLabel({
        priceY,
        scaleWidth: chart.priceScale("right").width(),
        isUp: lastCandle.close >= lastCandle.open,
        chartHeight: height,
      });
    }
  }, []);

  const scheduleOverlayRecalc = useCallback(() => {
    if (scheduledRecalcRef.current !== null) return;
    scheduledRecalcRef.current = requestAnimationFrame(() => {
      scheduledRecalcRef.current = null;
      recalcOverlays();
    });
  }, [recalcOverlays]);

  useEffect(() => {
    scheduleOverlayRecalc();
  }, [h1ImpulsePreviews, scheduleOverlayRecalc, selectedCandle, selectedPlaybooks, selectedSetupId]);

  const startOverlayInteractionSync = useCallback(() => {
    if (interactionRecalcRef.current !== null) return;

    const sync = () => {
      recalcOverlays();
      interactionRecalcRef.current = requestAnimationFrame(sync);
    };

    interactionRecalcRef.current = requestAnimationFrame(sync);
  }, [recalcOverlays]);

  const stopOverlayInteractionSync = useCallback(() => {
    if (interactionRecalcRef.current === null) return;
    cancelAnimationFrame(interactionRecalcRef.current);
    interactionRecalcRef.current = null;
    scheduleOverlayRecalc();
  }, [scheduleOverlayRecalc]);

  const priceFromClientY = useCallback((clientY: number): number | null => {
    const container = containerRef.current;
    const series = candleSeriesRef.current;
    if (!container || !series) return null;
    const rect = container.getBoundingClientRect();
    const price = series.coordinateToPrice(clientY - rect.top);
    return typeof price === "number" ? price : null;
  }, []);

  const manualAiPreviewBox = useCallback((candidate: SetupCandidate, levels: ManualAiEditableLevels): SetupBox | null => {
    const chart = chartRef.current;
    const series = candleSeriesRef.current;
    const container = containerRef.current;
    if (!chart || !series || !container) return null;
    const risk = Math.abs(levels.entry - levels.stopLoss);
    const reward = Math.abs(levels.takeProfit - levels.entry);
    return setupToBox(
      {
        ...candidate,
        entry: levels.entry,
        stop_loss: levels.stopLoss,
        take_profit: [levels.takeProfit],
        risk_reward: risk > 0 ? reward / risk : 0,
      },
      payloadRef.current.range.start,
      payloadRef.current.range.end,
      candleDataRef.current,
      chartPlotWidth(chart, container.clientWidth),
      container.clientHeight,
      chart.timeScale(),
      series,
    );
  }, []);

  const beginManualAiLevelDrag = useCallback((event: ReactPointerEvent<HTMLElement>, box: SetupBox, level: ManualAiLevel) => {
    if (manualAiEditSetupId !== box.candidate.id) return;
    const status = typeof box.candidate.metadata.manual_ai_plan_status === "string"
      ? box.candidate.metadata.manual_ai_plan_status
      : "draft";
    const isLocalH1Preview = box.candidate.metadata.h1_impulse_preview === true && box.candidate.metadata.execution_plan !== true;
    if (!isLocalH1Preview && !["draft", "approved", "armed"].includes(status)) {
      setDrawError(`Manual AI đang ở trạng thái ${status}; hãy chờ worker hoàn tất rồi thử lại.`);
      return;
    }
    const takeProfit = box.candidate.take_profit[0];
    if (box.candidate.entry === null || box.candidate.stop_loss === null || typeof takeProfit !== "number") return;
    event.preventDefault();
    event.stopPropagation();
    const original = {
      entry: box.candidate.entry,
      stopLoss: box.candidate.stop_loss,
      takeProfit,
    };
    manualAiLevelDragRef.current = { candidateId: box.candidate.id, level, moved: false };
    setDrawError(null);
    setManualAiLevelEdit((current) => current?.candidate.id === box.candidate.id
      ? { ...current, level, dragging: true, error: null }
      : {
          candidate: box.candidate,
          level,
          original,
          levels: original,
          entrySource: typeof box.candidate.metadata.entry_source === "string" ? box.candidate.metadata.entry_source : "strategy_calculated",
          previewBox: box,
          status,
          dragging: true,
          saving: false,
          error: null,
        });
  }, [manualAiEditSetupId]);

  useEffect(() => {
    const move = (event: PointerEvent) => {
      const dragging = manualAiLevelDragRef.current;
      if (!dragging) return;
      const price = priceFromClientY(event.clientY);
      if (price === null) return;
      event.preventDefault();
      dragging.moved = true;
      setManualAiLevelEdit((current) => {
        if (!current || current.candidate.id !== dragging.candidateId) return current;
        const levels = { ...current.levels, [dragging.level]: roundPrice(price) };
        const previewBox = manualAiPreviewBox(current.candidate, levels);
        return previewBox ? { ...current, levels, entrySource: "human_custom", previewBox, error: null } : current;
      });
    };
    const finish = () => {
      const dragging = manualAiLevelDragRef.current;
      if (!dragging) return;
      manualAiLevelDragRef.current = null;
      setManualAiLevelEdit((current) => {
        if (!current) return null;
        return dragging.moved ? { ...current, dragging: false } : null;
      });
    };
    window.addEventListener("pointermove", move, { passive: false });
    window.addEventListener("pointerup", finish);
    window.addEventListener("blur", finish);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("blur", finish);
    };
  }, [manualAiPreviewBox, priceFromClientY]);

  const updateManualAiEditLevels = useCallback((levels: ManualAiEditableLevels) => {
    setManualAiLevelEdit((current) => {
      if (!current || current.saving) return current;
      const rounded = {
        entry: roundPrice(levels.entry),
        stopLoss: roundPrice(levels.stopLoss),
        takeProfit: roundPrice(levels.takeProfit),
      };
      const previewBox = manualAiPreviewBox(current.candidate, rounded);
      return previewBox ? { ...current, levels: rounded, entrySource: "human_custom", previewBox, error: null } : current;
    });
  }, [manualAiPreviewBox]);

  const selectSetupEntrySource = useCallback((source: string, entry: number) => {
    setManualAiLevelEdit((current) => {
      if (!current || current.saving) return current;
      const roundedEntry = roundPrice(entry);
      const risk = Math.abs(roundedEntry - current.levels.stopLoss);
      const rr = current.candidate.risk_reward ?? 2.5;
      const takeProfit = roundPrice(
        current.candidate.direction === "long"
          ? roundedEntry + risk * rr
          : roundedEntry - risk * rr,
      );
      const levels = { ...current.levels, entry: roundedEntry, takeProfit };
      const previewBox = manualAiPreviewBox(current.candidate, levels);
      return previewBox ? { ...current, levels, entrySource: source, previewBox, error: null } : current;
    });
  }, [manualAiPreviewBox]);

  const exitManualAiSetupInteraction = useCallback(() => {
    manualAiLevelDragRef.current = null;
    setManualAiLevelEdit(null);
    setManualAiEditSetupId(null);
    selectSetup(null);
  }, [selectSetup, setManualAiEditSetupId]);

  useEffect(() => {
    setManualAiLevelEdit((current) => {
      if (!current || current.candidate.id === manualAiEditSetupId) return current;
      manualAiLevelDragRef.current = null;
      return null;
    });
  }, [manualAiEditSetupId]);

  const applyManualAiLevelEdit = useCallback(async () => {
    const edit = manualAiLevelEdit;
    if (!edit || edit.dragging || edit.saving) return;
    const { entry, stopLoss, takeProfit } = edit.levels;
    const isBuy = edit.candidate.direction === "long";
    const validGeometry = isBuy ? stopLoss < entry && entry < takeProfit : takeProfit < entry && entry < stopLoss;
    const risk = Math.abs(entry - stopLoss);
    const rr = risk > 0 ? Math.abs(takeProfit - entry) / risk : 0;
    if (!validGeometry) {
      setManualAiLevelEdit({ ...edit, error: `Mức giá ${isBuy ? "BUY" : "SELL"} không đúng thứ tự Entry/SL/TP.` });
      return;
    }
    const isH1Impulse = edit.candidate.playbook === "h1_impulse_retest_v1";
    const rrMin = isH1Impulse ? 1.0 : 1.5;
    const rrMax = 4;
    if (rr < rrMin || rr > rrMax) {
      setManualAiLevelEdit({ ...edit, error: `R:R mới là ${rr.toFixed(2)}R; playbook chỉ cho phép ${rrMin.toFixed(1)}R–${rrMax.toFixed(1)}R.` });
      return;
    }
    setManualAiLevelEdit({ ...edit, saving: true, error: null });
    try {
      if (isH1Impulse && edit.candidate.metadata.execution_plan !== true) {
        updateH1ImpulsePreviewLevels(edit.candidate.id, entry, stopLoss, takeProfit, edit.entrySource);
        exitManualAiSetupInteraction();
        return;
      }
      await updateManualAiPlanLevels(edit.candidate.id, {
        entry_price: entry,
        stop_loss: stopLoss,
        take_profit: takeProfit,
        entry_source: edit.entrySource,
      });
      exitManualAiSetupInteraction();
      onEntityCreatedRef.current();
    } catch (error) {
      setManualAiLevelEdit((current) => current ? {
        ...current,
        saving: false,
        error: error instanceof Error ? error.message : "Không thể cập nhật Manual AI levels.",
      } : current);
    }
  }, [exitManualAiSetupInteraction, manualAiLevelEdit, updateH1ImpulsePreviewLevels]);

  useEffect(() => {
    const handleManualAiSetupHotkey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && (selectedSetupId || manualAiEditSetupId || manualAiLevelEdit)) {
        event.preventDefault();
        event.stopImmediatePropagation();
        if (!manualAiLevelEdit?.saving) exitManualAiSetupInteraction();
        return;
      }
      if (
        event.key.toLowerCase() !== "e"
        || event.repeat
        || event.ctrlKey
        || event.metaKey
        || event.altKey
        || isEditableHotkeyTarget(event.target)
        || !selectedSetupId
      ) return;
      const candidate = [
        ...payloadRef.current.layers.setup_candidates,
        ...h1ImpulsePreviewsRef.current,
      ].find((item) => item.id === selectedSetupId);
      const status = typeof candidate?.metadata.manual_ai_plan_status === "string"
        ? candidate.metadata.manual_ai_plan_status
        : "draft";
      const editableH1Preview = candidate?.playbook === "h1_impulse_retest_v1"
        && (candidate.metadata.execution_plan !== true || ["draft", "approved", "armed"].includes(status));
      if (!candidate || (candidate.playbook !== "manual_ai_v1" && !editableH1Preview) || (!editableH1Preview && !["draft", "approved", "armed"].includes(status))) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      setManualAiEditSetupId(candidate.id);
    };
    window.addEventListener("keydown", handleManualAiSetupHotkey, { capture: true });
    return () => window.removeEventListener("keydown", handleManualAiSetupHotkey, { capture: true });
  }, [exitManualAiSetupInteraction, manualAiEditSetupId, manualAiLevelEdit, selectedSetupId, setManualAiEditSetupId]);

  const timeFromClientX = useCallback((clientX: number): number | null => {
    const container = containerRef.current;
    const chart = chartRef.current;
    if (!container || !chart) return null;
    const rect = container.getBoundingClientRect();
    const coordinate = clientX - rect.left;
    const time = chart.timeScale().coordinateToTime(coordinate);
    return chartTimeToUnix(time) ?? projectedTimeFromCoordinate(chart, candleDataRef.current, coordinate);
  }, []);

  const drawingPointFromPointer = useCallback((clientX: number, clientY: number): DrawingPoint | null => {
    const container = containerRef.current;
    const price = priceFromClientY(clientY);
    const time = timeFromClientX(clientX);
    if (!container || price === null || time === null) return null;
    const rect = container.getBoundingClientRect();
    return {
      x: clientX - rect.left,
      y: clientY - rect.top,
      price: roundPrice(price),
      time: unixToIso(time),
    };
  }, [priceFromClientY, timeFromClientX]);

  const changeDrawingTool = useCallback((tool: ChartDrawingTool) => {
    setAddEntityKind(null);
    setDrawingTool(tool);
    setSelectedCandle(null);
    setSelectedDrawingId(null);
    setDrawingMessage(null);
    setMeasurePreview(null);
    setCopyPriceGuide(null);
    measureStartRef.current = null;
    drawingInteractionRef.current = null;
  }, [setAddEntityKind]);

  const persistDrawing = useCallback(async (
    drawingType: "note" | "fib_retracement" | "horizontal_line",
    anchors: ChartDrawingAnchor[],
    properties: Record<string, unknown> = {},
    content: string | null = null,
  ) => {
    try {
      const created = await createChartDrawing({
        symbol: payloadRef.current.symbol,
        drawing_type: drawingType,
        origin_timeframe: payloadRef.current.timeframe,
        visible_timeframes: ["H1", "M15", "M5"],
        anchors,
        properties,
        content,
      });
      setSelectedDrawingId(created.id);
      setDrawingTool("cursor");
      setDrawingMessage("Đã lưu drawing.");
      onDrawingsChanged?.();
    } catch (error) {
      setDrawError(error instanceof Error ? error.message : "Could not save chart drawing.");
    }
  }, [onDrawingsChanged]);

  const beginChartDrawing = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (drawingTool === "cursor") return;
    const point = drawingPointFromPointer(event.clientX, event.clientY);
    if (!point) return;
    event.preventDefault();
    event.stopPropagation();
    setSelectedDrawingId(null);
    setDrawError(null);

    if (drawingTool === "copy_price") {
      void copyTextToClipboard(point.price.toFixed(2)).then(() => {
        setDrawingMessage(`Đã copy ${point.price.toFixed(2)}`);
        setDrawingTool("cursor");
        setCopyPriceGuide(null);
      }).catch(() => setDrawError("Browser không cho phép copy giá."));
      return;
    }
    if (drawingTool === "horizontal_line") {
      void persistDrawing("horizontal_line", [{ time: point.time, price: point.price }]);
      return;
    }
    if (drawingTool === "note") {
      setPendingNote({ anchor: { time: point.time, price: point.price }, x: point.x, y: point.y });
      setNoteContent("");
      return;
    }
    if (drawingTool === "measure") {
      const start = measureStartRef.current;
      if (!start) {
        measureStartRef.current = point;
        setMeasurePreview({ start: point, end: point });
      } else {
        measureStartRef.current = null;
        setMeasurePreview({ start, end: point });
        setDrawingTool("cursor");
        setDrawingMessage("Đo xong · đã trở về con trỏ.");
      }
      return;
    }
    drawingInteractionRef.current = { tool: drawingTool, start: point };
    setMeasurePreview({ start: point, end: point });
  }, [drawingPointFromPointer, drawingTool, persistDrawing]);

  const handleDrawingHover = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const point = drawingPointFromPointer(event.clientX, event.clientY);
    if (!point) return;
    if (drawingTool === "copy_price") {
      setCopyPriceGuide({ y: point.y, price: point.price });
    } else if (drawingTool === "measure" && measureStartRef.current) {
      setMeasurePreview({ start: measureStartRef.current, end: point });
    }
  }, [drawingPointFromPointer, drawingTool]);

  useEffect(() => {
    const cancel = () => {
      drawingInteractionRef.current = null;
    };
    const move = (event: PointerEvent) => {
      const interaction = drawingInteractionRef.current;
      if (!interaction) return;
      const point = drawingPointFromPointer(event.clientX, event.clientY);
      if (!point) return;
      event.preventDefault();
      setMeasurePreview({ start: interaction.start, end: point });
    };
    const finish = (event: PointerEvent) => {
      const interaction = drawingInteractionRef.current;
      if (!interaction) return;
      drawingInteractionRef.current = null;
      const point = drawingPointFromPointer(event.clientX, event.clientY);
      if (!point) return;
      const variant = interaction.tool === "fib_ote" ? "ote" : "standard";
      setMeasurePreview(null);
      void persistDrawing(
        "fib_retracement",
        [
          { time: interaction.start.time, price: interaction.start.price },
          { time: point.time, price: point.price },
        ],
        { variant },
      );
    };
    window.addEventListener("pointermove", move, { passive: false });
    window.addEventListener("pointerup", finish);
    window.addEventListener("blur", cancel);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("blur", cancel);
    };
  }, [drawingPointFromPointer, persistDrawing]);

  const removeDrawing = useCallback(async (drawing: ChartDrawing) => {
    try {
      await deleteChartDrawing(drawing);
      setSelectedDrawingId(null);
      onDrawingsChanged?.();
    } catch (error) {
      setDrawError(error instanceof Error ? error.message : "Could not delete chart drawing.");
    }
  }, [onDrawingsChanged]);

  const beginMoveDrawing = useCallback((event: ReactPointerEvent<HTMLButtonElement>, drawing: ChartDrawing) => {
    if (drawing.locked || drawing.drawing_type !== "note") return;
    event.preventDefault();
    event.stopPropagation();
    setSelectedDrawingId(drawing.id);
    drawingMoveRef.current = { drawing, startX: event.clientX, startY: event.clientY, moved: false };
  }, []);

  useEffect(() => {
    const move = (event: PointerEvent) => {
      const moving = drawingMoveRef.current;
      if (!moving) return;
      if (!moving.moved && Math.hypot(event.clientX - moving.startX, event.clientY - moving.startY) < 4) return;
      moving.moved = true;
      const point = drawingPointFromPointer(event.clientX, event.clientY);
      if (!point) return;
      event.preventDefault();
      drawingDraftAnchorRef.current = { id: moving.drawing.id, anchor: { time: point.time, price: point.price } };
      scheduleOverlayRecalc();
    };
    const finish = (event: PointerEvent) => {
      const moving = drawingMoveRef.current;
      if (!moving) return;
      drawingMoveRef.current = null;
      if (!moving.moved) return;
      const point = drawingPointFromPointer(event.clientX, event.clientY);
      if (!point) {
        drawingDraftAnchorRef.current = null;
        scheduleOverlayRecalc();
        return;
      }
      void updateChartDrawing(moving.drawing, { anchors: [{ time: point.time, price: point.price }] })
        .then(() => {
          setDrawingMessage("Đã di chuyển note.");
          onDrawingsChanged?.();
        })
        .catch((error) => setDrawError(error instanceof Error ? error.message : "Could not move note."))
        .finally(() => {
          drawingDraftAnchorRef.current = null;
          scheduleOverlayRecalc();
        });
    };
    window.addEventListener("pointermove", move, { passive: false });
    window.addEventListener("pointerup", finish);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
    };
  }, [drawingPointFromPointer, onDrawingsChanged, scheduleOverlayRecalc]);

  useEffect(() => {
    const hotkeys = (event: KeyboardEvent) => {
      if (isEditableHotkeyTarget(event.target) || event.repeat) return;
      const key = event.key.toLowerCase();
      let tool: ChartDrawingTool | null = null;
      if (event.altKey && key === "c") tool = "copy_price";
      else if (!event.ctrlKey && !event.metaKey && !event.altKey && key === "m") tool = "measure";
      else if (!event.ctrlKey && !event.metaKey && !event.altKey && key === "n") tool = "note";
      else if (!event.ctrlKey && !event.metaKey && !event.altKey && key === "f") tool = event.shiftKey ? "fib_ote" : "fib_standard";
      else if (!event.ctrlKey && !event.metaKey && !event.altKey && key === "h") tool = "horizontal_line";
      else if (event.key === "Escape") tool = "cursor";
      if (tool) {
        event.preventDefault();
        event.stopImmediatePropagation();
        setPendingNote(null);
        changeDrawingTool(tool);
      } else if ((event.key === "Delete" || event.key === "Backspace") && selectedDrawingId) {
        const drawing = drawingsRef.current.find((item) => item.id === selectedDrawingId);
        if (drawing) {
          event.preventDefault();
          void removeDrawing(drawing);
        }
      }
    };
    window.addEventListener("keydown", hotkeys, true);
    return () => window.removeEventListener("keydown", hotkeys, true);
  }, [changeDrawingTool, removeDrawing, selectedDrawingId]);

  useEffect(() => {
    if (!drawingMessage) return;
    const id = window.setTimeout(() => setDrawingMessage(null), 2200);
    return () => window.clearTimeout(id);
  }, [drawingMessage]);

  const updateDraftZone = useCallback(
    (zone: PriceZone, options: { preserveViewport?: boolean } = {}) => {
      const preserveViewport = options.preserveViewport ?? true;
      if (preserveViewport) {
        lockCurrentViewport(chartRef.current, lockedViewportRef);
      }
      draftZoneRef.current = zone;
      setSelected({ kind: "zone", entity: zone });
      if (preserveViewport) {
        restoreLockedViewport(chartRef.current, lockedViewportRef);
      }
      scheduleOverlayRecalc();
    },
    [scheduleOverlayRecalc, setSelected],
  );

  const updateDrawPreview = useCallback(
    (zone: PriceZone | null) => {
      drawPreviewZoneRef.current = zone;
      setDrawPreviewZone(zone);
      scheduleOverlayRecalc();
    },
    [scheduleOverlayRecalc],
  );

  const beginManualDraw = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      const kind = addEntityKindRef.current;
      if (!kind) return;
      const pointerPrice = priceFromClientY(event.clientY);
      const pointerTime = timeFromClientX(event.clientX);
      if (pointerPrice === null || pointerTime === null) return;

      event.preventDefault();
      event.stopPropagation();
      lockCurrentViewport(chartRef.current, lockedViewportRef);
      setDrawError(null);
      setSelected(null);
      manualDrawRef.current = {
        kind,
        startPointerPrice: pointerPrice,
        startPointerTime: pointerTime,
      };
      updateDrawPreview(null);
      startOverlayInteractionSync();
    },
    [priceFromClientY, setSelected, startOverlayInteractionSync, timeFromClientX, updateDrawPreview],
  );

  const handleManualDrawMove = useCallback(
    (event: PointerEvent) => {
      const draw = manualDrawRef.current;
      if (!draw) return;
      const pointerPrice = priceFromClientY(event.clientY);
      const pointerTime = timeFromClientX(event.clientX);
      if (pointerPrice === null || pointerTime === null) return;

      event.preventDefault();
      const spec = manualZoneSpec(draw.kind);
      const low = Math.min(draw.startPointerPrice, pointerPrice);
      const high = Math.max(draw.startPointerPrice, pointerPrice);
      const startTime = Math.min(draw.startPointerTime, pointerTime);
      const endTime = Math.max(draw.startPointerTime, pointerTime);
      const lastCandleTime = payloadRef.current.layers.candles.at(-1)?.time;
      const safeHigh = high - low < MIN_ZONE_HEIGHT ? low + MIN_ZONE_HEIGHT : high;
      updateDrawPreview({
        id: "__manual_zone_preview__",
        type: spec.zoneType,
        timeframe: "H1",
        direction: spec.direction,
        detector: "human_manual_v1",
        status: spec.zoneType === "support" || spec.zoneType === "resistance" ? "draft" : "active",
        source: "human",
        price_low: roundPrice(low),
        price_high: roundPrice(safeHigh),
        visual_start: unixToIso(startTime),
        visual_end: unixToIso(endTime),
        valid_from: unixToIso(startTime),
        valid_until: null,
        invalidated_at: null,
        invalidated_by_structure_point_id: null,
        detected_at: unixToIso(startTime),
        weight: spec.weight,
        confidence: spec.confidence,
        metadata: {
          add_entity_kind: draw.kind,
          human_created: true,
          unsaved_drag: true,
        },
      });
    },
    [priceFromClientY, timeFromClientX, updateDrawPreview],
  );

  const finishManualDraw = useCallback(async () => {
    const draw = manualDrawRef.current;
    if (!draw) return;
    manualDrawRef.current = null;
    stopOverlayInteractionSync();

    const preview = drawPreviewZoneRef.current;
    if (!preview) return;

    lockCurrentViewport(chartRef.current, lockedViewportRef);
    const lastCandleTime = payloadRef.current.layers.candles.at(-1)?.time;
    const endTime = preview.visual_end ? toUnixTime(preview.visual_end) : lastCandleTime ? toUnixTime(lastCandleTime) : toUnixTime(preview.visual_start);
    const duration = endTime - toUnixTime(preview.visual_start);
    if (duration < MIN_ZONE_DURATION_SECONDS) {
      updateDrawPreview(null);
      return;
    }

    try {
      const created = await createManualZone({
        symbol: payloadRef.current.symbol,
        timeframe: payloadRef.current.timeframe,
        zone_type: preview.type,
        direction: preview.direction,
        price_low: preview.price_low,
        price_high: preview.price_high,
        visual_start: preview.visual_start,
        visual_end: preview.visual_end,
        expires_at: preview.visual_end,
        weight: preview.weight,
        confidence: preview.confidence,
        status: preview.type === "support" || preview.type === "resistance" ? "draft" : "active",
        client_kind: draw.kind,
        reason: `manual ${manualZoneSpec(draw.kind).label} drawn on chart`,
        trade_modes: defaultTradeModesForZone(preview),
      });
      updateDrawPreview(null);
      setAddEntityKind(null);
      setSelected({ kind: "zone", entity: created });
      restoreLockedViewport(chartRef.current, lockedViewportRef);
      onEntityCreatedRef.current();
    } catch (err) {
      updateDrawPreview(null);
      setDrawError(err instanceof Error ? err.message : "Could not create entity.");
    }
  }, [setAddEntityKind, setSelected, stopOverlayInteractionSync, updateDrawPreview]);

  const beginZoneDrag = useCallback(
    (event: ReactPointerEvent<HTMLElement>, box: ZoneBox, mode: ZoneDragMode) => {
      const pointerPrice = priceFromClientY(event.clientY);
      const needsPointerTime = mode === "move" || mode === "resize-left" || mode === "resize-right";
      const pointerTime = needsPointerTime ? timeFromClientX(event.clientX) : null;
      if (pointerPrice === null || (needsPointerTime && pointerTime === null)) return;
      event.preventDefault();
      event.stopPropagation();
      zoneDragRef.current = {
        mode,
        zone: box.zone,
        startPointerPrice: pointerPrice,
        startPointerTime: pointerTime ?? toUnixTime(box.zone.visual_start),
        startLow: box.zone.price_low,
        startHigh: box.zone.price_high,
        startVisualStart: box.zone.visual_start,
        startVisualEnd: box.zone.visual_end,
      };
      updateDraftZone(box.zone);
      startOverlayInteractionSync();
    },
    [priceFromClientY, startOverlayInteractionSync, timeFromClientX, updateDraftZone],
  );

  const handleZoneDragMove = useCallback(
    (event: PointerEvent) => {
      const drag = zoneDragRef.current;
      if (!drag) return;
      const pointerPrice = priceFromClientY(event.clientY);
      const needsPointerTime = drag.mode === "move" || drag.mode === "resize-left" || drag.mode === "resize-right";
      const pointerTime = needsPointerTime ? timeFromClientX(event.clientX) : null;
      if (pointerPrice === null || (needsPointerTime && pointerTime === null)) return;

      event.preventDefault();
      const priceDelta = pointerPrice - drag.startPointerPrice;
      const timeDelta = (pointerTime ?? drag.startPointerTime) - drag.startPointerTime;
      let nextLow = drag.startLow;
      let nextHigh = drag.startHigh;
      let nextVisualStart = drag.startVisualStart;
      let nextVisualEnd = drag.startVisualEnd;

      const lastCandleTime = payloadRef.current.layers.candles.at(-1)?.time;
      const startTime = toUnixTime(drag.startVisualStart);
      const endTime = toUnixTime(drag.startVisualEnd ?? lastCandleTime ?? drag.startVisualStart);

      if (drag.mode === "move") {
        nextLow = drag.startLow + priceDelta;
        nextHigh = drag.startHigh + priceDelta;
        nextVisualStart = unixToIso(startTime + timeDelta);
        // Preserve null (open-ended) for zones that were originally open-ended
        nextVisualEnd = drag.startVisualEnd === null ? null : unixToIso(endTime + timeDelta);
      } else if (drag.mode === "resize-top") {
        nextHigh = Math.max(pointerPrice, drag.startLow + MIN_ZONE_HEIGHT);
      } else if (drag.mode === "resize-bottom") {
        nextLow = Math.min(pointerPrice, drag.startHigh - MIN_ZONE_HEIGHT);
      } else if (drag.mode === "resize-left") {
        nextVisualStart = unixToIso(Math.min(pointerTime ?? startTime, endTime - MIN_ZONE_DURATION_SECONDS));
      } else {
        // resize-right: always use cursor position, never null
        nextVisualEnd = unixToIso(Math.max(pointerTime ?? endTime, startTime + MIN_ZONE_DURATION_SECONDS));
      }

      updateDraftZone(
        {
          ...drag.zone,
          price_low: roundPrice(nextLow),
          price_high: roundPrice(nextHigh),
          visual_start: nextVisualStart,
          visual_end: nextVisualEnd,
          metadata: {
            ...drag.zone.metadata,
            human_adjusted: true,
            unsaved_drag: true,
          },
        },
        { preserveViewport: false },
      );
    },
    [priceFromClientY, timeFromClientX, updateDraftZone],
  );

  const persistDraggedZoneOverride = useCallback(
    async (zone: PriceZone) => {
      try {
        const updated = await updateZoneOverride(zone.id, {
          price_low: zone.price_low,
          price_high: zone.price_high,
          visual_start: zone.visual_start,
          visual_end: zone.visual_end,
          expires_at: zone.visual_end,
          weight: zone.weight,
          confidence: zone.confidence,
          status: zone.status === "disabled" ? "disabled" : zone.status === "draft" ? "draft" : "active",
          reason: "chart drag resize/move",
          trade_modes: defaultTradeModesForZone(zone),
        });
        persistedZoneDraftRef.current = updated;
        updateDraftZone(updated, { preserveViewport: false });
        if (onZonePersistedRef.current) {
          onZonePersistedRef.current(updated);
        } else {
          onEntityCreatedRef.current();
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : "Could not save zone drag.";
        setDrawError(message);
      }
    },
    [updateDraftZone],
  );

  const finishZoneDrag = useCallback(() => {
    const drag = zoneDragRef.current;
    if (!drag) return;
    const draftZone = draftZoneRef.current?.id === drag.zone.id ? draftZoneRef.current : null;
    zoneDragRef.current = null;
    stopOverlayInteractionSync();
    scheduleOverlayRecalc();
    if (draftZone) {
      void persistDraggedZoneOverride(draftZone);
    }
  }, [persistDraggedZoneOverride, scheduleOverlayRecalc, stopOverlayInteractionSync]);

  const clearSelection = useCallback(() => {
    if (addEntityKindRef.current) return;
    if (manualAiLevelEdit?.saving) return;
    lockCurrentViewport(chartRef.current, lockedViewportRef);
    draftZoneRef.current = null;
    measureStartRef.current = null;
    setMeasurePreview(null);
    setSelected(null);
    setManualAiLevelEdit(null);
    setManualAiEditSetupId(null);
    selectSetup(null);
    restoreLockedViewport(chartRef.current, lockedViewportRef);
    scheduleOverlayRecalc();
  }, [manualAiLevelEdit?.saving, scheduleOverlayRecalc, selectSetup, setManualAiEditSetupId, setSelected]);

  const selectStructurePoint = useCallback(
    (point: StructurePoint) => {
      lockCurrentViewport(chartRef.current, lockedViewportRef);
      setSelected({ kind: "structure", entity: point });
      restoreLockedViewport(chartRef.current, lockedViewportRef);
      scheduleOverlayRecalc();
    },
    [scheduleOverlayRecalc, setSelected],
  );

  const selectTrade = useCallback(
    (trade: TradeOrder) => {
      lockCurrentViewport(chartRef.current, lockedViewportRef);
      setInspectorTab("zones");
      setSelected({ kind: "trade", entity: trade });
      restoreLockedViewport(chartRef.current, lockedViewportRef);
      scheduleOverlayRecalc();
    },
    [scheduleOverlayRecalc, setInspectorTab, setSelected],
  );

  useEffect(() => {
    if (selected?.kind === "zone") {
      const persistedDraft = persistedZoneDraftRef.current;
      if (persistedDraft?.id === selected.entity.id) {
        const selectedOverrideAt = String(selected.entity.metadata?.last_human_override_at ?? "");
        const draftOverrideAt = String(persistedDraft.metadata?.last_human_override_at ?? "");
        if (!selectedOverrideAt || (draftOverrideAt && selectedOverrideAt < draftOverrideAt)) {
          draftZoneRef.current = persistedDraft;
          scheduleOverlayRecalc();
          return;
        }
        persistedZoneDraftRef.current = null;
      }
      draftZoneRef.current = selected.entity;
    } else {
      persistedZoneDraftRef.current = null;
      draftZoneRef.current = null;
    }
    scheduleOverlayRecalc();
  }, [scheduleOverlayRecalc, selected]);

  useEffect(() => {
    payloadRef.current = payload;
    scheduleOverlayRecalc();
  }, [
    drawings,
    h1ImpulseEligibleOnly,
    importantZonesOnly,
    maxVisibleZones,
    payload,
    scheduleOverlayRecalc,
    selectedPlaybooks,
    showBrokenIntradayLevels,
    showHistoricalLiquiditySweeps,
    showH1ImpulseCandidates,
    showIntradayLevels,
    showStructure,
    showZones,
    tradeVisibilityMode,
    zoneTypeVisibility,
  ]);

  useEffect(() => {
    zigzagSeriesRef.current?.setData(buildZigZagSeriesData(payload.layers.structure, payload.range.end, payload.replay?.as_of, showStructure));
  }, [payload.layers.structure, payload.range.end, payload.replay?.as_of, showStructure]);

  useEffect(() => {
    if (!zoneFocusRequest || handledZoneFocusRequestRef.current === zoneFocusRequest.id) return;
    handledZoneFocusRequestRef.current = zoneFocusRequest.id;
    focusZoneOnChart(chartRef.current, zoneFocusRequest.zone, payloadRef.current.layers.candles, scheduleOverlayRecalc);
  }, [scheduleOverlayRecalc, zoneFocusRequest]);

  useEffect(() => {
    if (!tradeFocusRequest || handledTradeFocusRequestRef.current === tradeFocusRequest.id) return;
    setSelected({ kind: "trade", entity: tradeFocusRequest.trade });
    if (focusTradeOnChart(chartRef.current, tradeFocusRequest.trade, payloadRef.current.layers.candles, scheduleOverlayRecalc)) {
      handledTradeFocusRequestRef.current = tradeFocusRequest.id;
    }
  }, [payload.range.end, payload.range.start, scheduleOverlayRecalc, setSelected, tradeFocusRequest]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#080b10" },
        textColor: "#8d9aab",
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "#101823", style: LineStyle.Solid },
        horzLines: { color: "#101823", style: LineStyle.Solid },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: true,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
      rightPriceScale: {
        autoScale: false,
        borderColor: "#202b3a",
        textColor: "#8d9aab",
        scaleMargins: { top: 0.12, bottom: 0.08 },
      },
      timeScale: {
        borderColor: "#202b3a",
        timeVisible: true,
        secondsVisible: false,
        // Future whitespace is already supplied by the transparent scale-anchor
        // series. A second right offset pushes the latest candle too far left,
        // which is especially costly on narrow mobile charts.
        rightOffset: 0,
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#2fbd85",
      downColor: "#e35d68",
      borderUpColor: "#2fbd85",
      borderDownColor: "#e35d68",
      wickUpColor: "#2fbd85",
      wickDownColor: "#e35d68",
    });
    const scaleAnchorSeries = chart.addSeries(LineSeries, {
      color: "rgba(0, 0, 0, 0)",
      crosshairMarkerVisible: false,
      lastValueVisible: false,
      priceLineVisible: false,
    });
    const zigzagSeries = chart.addSeries(LineSeries, {
      color: "#1f6fff",
      crosshairMarkerVisible: false,
      lastValueVisible: false,
      lineWidth: 1,
      priceLineVisible: false,
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    scaleAnchorSeriesRef.current = scaleAnchorSeries;
    zigzagSeriesRef.current = zigzagSeries;
    candleSeries.setData(candleDataRef.current);
    scaleAnchorSeries.setData(
      buildScaleAnchorData(candleDataRef.current, scaleEventsForViewport(container.clientWidth, newsDataRef.current?.events ?? [])),
    );
    zigzagSeries.setData(buildZigZagSeriesData(payload.layers.structure, payload.range.end, payload.replay?.as_of, showStructureRef.current));
    payloadRef.current = payload;
    appliedCandleKeyRef.current = candleKey;
    appliedCandleDataRef.current = candleDataRef.current;
    appliedViewKeyRef.current = viewKey;
    manualViewportRef.current = false;
    const requestedVisibleBars = visibleChartBars(container.clientWidth, payload.timeframe, payload.range.limit);
    if (payloadRef.current.replay?.enabled) {
      applyReplayTimeViewport(chart, candleDataRef.current, requestedVisibleBars);
      replayPriceRangeRef.current = applyReplayPriceViewport(chart, candleDataRef.current, true);
    } else {
      applyInitialViewport(chart, candleDataRef.current, requestedVisibleBars);
      replayPriceRangeRef.current = applyInitialPriceViewport(chart, candleDataRef.current);
    }
    lastViewportRef.current = readCurrentViewport(chart);
    scheduleOverlayRecalc();

    const resizeObserver = new ResizeObserver(scheduleOverlayRecalc);
    resizeObserver.observe(container);
    const selectCandleAtClick: Parameters<IChartApi["subscribeClick"]>[0] = (param) => {
      if (drawingToolRef.current !== "cursor" || addEntityKindRef.current) return;
      const clickedSeriesData = param.seriesData.get(candleSeries);
      const clickedTime = chartTimeToUnix(param.time);
      if (!clickedSeriesData || clickedTime === null || !param.point) {
        setSelectedCandle(null);
        return;
      }
      const candle = payloadRef.current.layers.candles.find(
        (item) => Number(toUnixTime(item.time)) === Number(clickedTime),
      );
      if (!candle) {
        setSelectedCandle(null);
        return;
      }
      const candleX = chart.timeScale().timeToCoordinate(toUnixTime(candle.time));
      const openY = candleSeries.priceToCoordinate(candle.open);
      const highY = candleSeries.priceToCoordinate(candle.high);
      const lowY = candleSeries.priceToCoordinate(candle.low);
      const closeY = candleSeries.priceToCoordinate(candle.close);
      const candleIndex = candleDataRef.current.findIndex(
        (item) => Number(item.time) === Number(clickedTime),
      );
      const neighbor = candleIndex > 0
        ? candleDataRef.current[candleIndex - 1]
        : candleDataRef.current[candleIndex + 1];
      const neighborX = neighbor ? chart.timeScale().timeToCoordinate(neighbor.time) : null;
      const bodyWidth = clampNumber(
        candleX === null || neighborX === null ? 8 : Math.abs(candleX - neighborX) * 0.72,
        4,
        16,
      );
      if (
        candleX === null
        || openY === null
        || highY === null
        || lowY === null
        || closeY === null
        || !isCandleShapeHit({
          pointerX: param.point.x,
          pointerY: param.point.y,
          candleX,
          openY,
          highY,
          lowY,
          closeY,
          bodyWidth,
        })
      ) {
        setSelectedCandle(null);
        return;
      }
      setSelectedDrawingId(null);
      setSelectedCandle((current) => current?.time === candle.time ? null : candle);
    };
    chart.subscribeClick(selectCandleAtClick);
    const syncViewportAndOverlay = () => {
      lastViewportRef.current = readCurrentViewport(chart);
      scheduleOverlayRecalc();
    };
    chart.timeScale().subscribeVisibleTimeRangeChange(syncViewportAndOverlay);
    chart.timeScale().subscribeVisibleLogicalRangeChange(syncViewportAndOverlay);

    const syncDuringPointerMove = () => {
      lastViewportRef.current = readCurrentViewport(chart);
      scheduleOverlayRecalc();
    };

    const syncDuringWheel = () => {
      manualViewportRef.current = true;
      lastViewportRef.current = readCurrentViewport(chart);
      scheduleOverlayRecalc();
      if (!manualDrawRef.current && !zoneDragRef.current) {
        lockedViewportRef.current = null;
      }
      startOverlayInteractionSync();
      if (wheelStopRef.current !== null) {
        window.clearTimeout(wheelStopRef.current);
      }
      wheelStopRef.current = window.setTimeout(() => {
        wheelStopRef.current = null;
        stopOverlayInteractionSync();
      }, 120);
    };

    const startChartInteraction = () => {
      manualViewportRef.current = true;
      lastViewportRef.current = readCurrentViewport(chart);
      if (!manualDrawRef.current && !zoneDragRef.current) {
        lockedViewportRef.current = null;
      }
      startOverlayInteractionSync();
    };

    container.addEventListener("pointerdown", startChartInteraction);
    container.addEventListener("pointermove", syncDuringPointerMove);
    container.addEventListener("wheel", syncDuringWheel, { passive: true });
    window.addEventListener("pointermove", syncDuringPointerMove);
    window.addEventListener("pointerup", stopOverlayInteractionSync);
    window.addEventListener("blur", stopOverlayInteractionSync);
    window.addEventListener("pointermove", handleZoneDragMove, { passive: false });
    window.addEventListener("pointerup", finishZoneDrag);
    window.addEventListener("blur", finishZoneDrag);
    window.addEventListener("pointermove", handleManualDrawMove, { passive: false });
    window.addEventListener("pointerup", finishManualDraw);
    window.addEventListener("blur", finishManualDraw);

    return () => {
      resizeObserver.disconnect();
      chart.unsubscribeClick(selectCandleAtClick);
      chart.timeScale().unsubscribeVisibleTimeRangeChange(syncViewportAndOverlay);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(syncViewportAndOverlay);
      container.removeEventListener("pointerdown", startChartInteraction);
      container.removeEventListener("pointermove", syncDuringPointerMove);
      container.removeEventListener("wheel", syncDuringWheel);
      window.removeEventListener("pointermove", syncDuringPointerMove);
      window.removeEventListener("pointerup", stopOverlayInteractionSync);
      window.removeEventListener("blur", stopOverlayInteractionSync);
      window.removeEventListener("pointermove", handleZoneDragMove);
      window.removeEventListener("pointerup", finishZoneDrag);
      window.removeEventListener("blur", finishZoneDrag);
      window.removeEventListener("pointermove", handleManualDrawMove);
      window.removeEventListener("pointerup", finishManualDraw);
      window.removeEventListener("blur", finishManualDraw);
      if (scheduledRecalcRef.current !== null) {
        cancelAnimationFrame(scheduledRecalcRef.current);
        scheduledRecalcRef.current = null;
      }
      if (interactionRecalcRef.current !== null) {
        cancelAnimationFrame(interactionRecalcRef.current);
        interactionRecalcRef.current = null;
      }
      if (wheelStopRef.current !== null) {
        window.clearTimeout(wheelStopRef.current);
        wheelStopRef.current = null;
      }
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      scaleAnchorSeriesRef.current = null;
      zigzagSeriesRef.current = null;
    };
  }, [
    finishZoneDrag,
    finishManualDraw,
    handleManualDrawMove,
    handleZoneDragMove,
    scheduleOverlayRecalc,
    startOverlayInteractionSync,
    stopOverlayInteractionSync,
  ]);

  useEffect(() => {
    const chart = chartRef.current;
    const series = candleSeriesRef.current;
    if (!chart || !series) return;
    if (appliedCandleKeyRef.current === candleKey) {
      payloadRef.current = payload;
      zigzagSeriesRef.current?.setData(
        buildZigZagSeriesData(payload.layers.structure, payload.range.end, payload.replay?.as_of, showStructureRef.current),
      );
      scheduleOverlayRecalc();
      return;
    }

    const previousViewKey = appliedViewKeyRef.current;
    const lockedViewport = lockedViewportRef.current;
    const savedViewport = lockedViewport ?? lastViewportRef.current;
    const visibleRange = savedViewport?.logicalRange ?? chart.timeScale().getVisibleLogicalRange();
    const visiblePriceRange = savedViewport?.priceRange ?? chart.priceScale("right").getVisibleRange();
    const isReplay = Boolean(payload.replay?.enabled);

    // Only use update() when stable history is byte-for-byte unchanged. A
    // fixed-size window shift or corrected historical OHLC needs setData().
    const prevData = appliedCandleDataRef.current;
    const isSameView = previousViewKey === viewKey;
    const candleChange = classifyCandleSeriesChange(prevData, candleData);
    const isIncremental =
      !isReplay &&
      isSameView &&
      (candleChange === "last-candle" || candleChange === "single-append");

    if (isIncremental) {
      // Snapshot viewport BEFORE update — series.update() with a new timestamp triggers
      // shiftVisibleRangeOnNewBar (default true) and can scroll the chart unexpectedly.
      const rangeBeforeUpdate = visibleRange;
      const priceRangeBeforeUpdate = visiblePriceRange;
      const wasManual = manualViewportRef.current;

      if (candleChange === "single-append") {
        // New candle: finalize the previous last bar, then append the new one.
        series.update(candleData[candleData.length - 2]);
      }
      series.update(candleData[candleData.length - 1]);

      // If the user has manually scrolled/zoomed, restore their viewport after update
      // so the chart does not auto-scroll to follow the new bar.
      if (wasManual) {
        requestAnimationFrame(() => {
          if (rangeBeforeUpdate) chart.timeScale().setVisibleLogicalRange(rangeBeforeUpdate);
          chart.priceScale("right").setAutoScale(false);
          if (priceRangeBeforeUpdate) chart.priceScale("right").setVisibleRange(priceRangeBeforeUpdate);
        });
      }

      // Do NOT call scaleAnchorSeries.setData() — that resets the price scale.
      zigzagSeriesRef.current?.setData(
        buildZigZagSeriesData(payload.layers.structure, payload.range.end, payload.replay?.as_of, showStructureRef.current),
      );
      payloadRef.current = payload;
      appliedCandleKeyRef.current = candleKey;
      appliedCandleDataRef.current = candleData;
      lastViewportRef.current = readCurrentViewport(chart);
      scheduleOverlayRecalc();
      return;
    }

    // Full reload path (window change, symbol/timeframe change, or replay mode).
    series.setData(candleData);
    scaleAnchorSeriesRef.current?.setData(
      buildScaleAnchorData(
        candleData,
        scaleEventsForViewport(containerRef.current?.clientWidth ?? window.innerWidth, newsDataRef.current?.events ?? []),
      ),
    );
    zigzagSeriesRef.current?.setData(buildZigZagSeriesData(payload.layers.structure, payload.range.end, payload.replay?.as_of, showStructureRef.current));
    payloadRef.current = payload;
    appliedCandleKeyRef.current = candleKey;
    appliedCandleDataRef.current = candleData;
    appliedViewKeyRef.current = viewKey;
    if (isReplay) {
      if (previousViewKey !== viewKey || visiblePriceRange === null) {
        manualViewportRef.current = false;
        applyReplayTimeViewport(
          chart,
          candleData,
          visibleChartBars(containerRef.current?.clientWidth ?? window.innerWidth, payload.timeframe, payload.range.limit),
        );
        replayPriceRangeRef.current = applyReplayPriceViewport(chart, candleData, true);
      } else {
        if (visibleRange) {
          chart.timeScale().setVisibleLogicalRange(visibleRange);
        }
        if (manualViewportRef.current) {
          chart.priceScale("right").setAutoScale(false);
          chart.priceScale("right").setVisibleRange(visiblePriceRange);
          replayPriceRangeRef.current = visiblePriceRange;
        } else {
          replayPriceRangeRef.current = applyReplayPriceViewport(chart, candleData, false);
        }
      }
    } else if (previousViewKey !== viewKey) {
      lockedViewportRef.current = null;
      manualViewportRef.current = false;
      replayPriceRangeRef.current = null;
      applyInitialViewport(
        chart,
        candleData,
        visibleChartBars(containerRef.current?.clientWidth ?? window.innerWidth, payload.timeframe, payload.range.limit),
      );
      replayPriceRangeRef.current = applyInitialPriceViewport(chart, candleData);
    } else {
      // Same view but non-incremental (e.g. many candles changed at once).
      // Restore viewport — defer one frame so setData's internal layout finishes first.
      const restoreRange = visibleRange;
      const restorePriceRange = visiblePriceRange;
      requestAnimationFrame(() => {
        if (restoreRange) chart.timeScale().setVisibleLogicalRange(restoreRange);
        chart.priceScale("right").setAutoScale(false);
        if (restorePriceRange) chart.priceScale("right").setVisibleRange(restorePriceRange);
        replayPriceRangeRef.current = restorePriceRange;
      });
    }
    if (lockedViewportRef.current) {
      restoreLockedViewport(chart, lockedViewportRef);
    }
    lastViewportRef.current = readCurrentViewport(chart);
    scheduleOverlayRecalc();
  }, [candleData, candleKey, payload.range.limit, payload.range.start_index, payload.replay?.enabled, scheduleOverlayRecalc, viewKey]);

  useEffect(() => {
    const chart = chartRef.current;
    const anchorSeries = scaleAnchorSeriesRef.current;
    if (!chart || !anchorSeries) return;

    const viewport = readCurrentViewport(chart);
    anchorSeries.setData(
      buildScaleAnchorData(
        candleDataRef.current,
        scaleEventsForViewport(containerRef.current?.clientWidth ?? window.innerWidth, newsData?.events ?? []),
      ),
    );
    restoreViewport(chart, viewport);
    scheduleOverlayRecalc();
  }, [newsData, scheduleOverlayRecalc]);

  const compactViewport = isMobileChartWidth(containerRef.current?.clientWidth ?? window.innerWidth);
  const selectedCandleAtrTimeframe = payload.layers.atr[payload.timeframe]?.value !== undefined ? payload.timeframe : "M15";
  const selectedCandleAtr = payload.layers.atr[selectedCandleAtrTimeframe]?.value ?? null;
  const selectedH1ImpulseMarker = selectedCandle
    ? (payload.layers.h1_impulse_markers ?? []).find((marker) => marker.time === selectedCandle.time) ?? null
    : null;
  const canPreviewSelectedH1Impulse = payload.timeframe === "H1"
    && selectedPlaybooks.includes("h1_impulse_retest_v1")
    && selectedH1ImpulseMarker !== null;
  useEffect(() => {
    let active = true;
    setH1TargetQuote(null);
    setH1TargetQuoteLoading(false);
    if (!selectedCandle || !canPreviewSelectedH1Impulse) return () => { active = false; };
    setH1TargetQuoteLoading(true);
    void previewH1Impulse({
      symbol: payload.symbol,
      signalCandleTime: selectedCandle.time,
      riskReward: 2.5,
      targetMode: "wave_safe",
      asOf: payload.replay?.as_of ?? payload.range.end,
    }).then((preview) => {
      if (active) setH1TargetQuote(preview);
    }).catch(() => {
      // The explicit Add action still surfaces preview errors to the trader.
    }).finally(() => {
      if (active) setH1TargetQuoteLoading(false);
    });
    return () => { active = false; };
  }, [canPreviewSelectedH1Impulse, payload.range.end, payload.replay?.as_of, payload.symbol, selectedCandle]);
  const addH1SetupPreview = useCallback(async (riskReward: number, targetMode: H1ImpulseTargetMode) => {
    if (!selectedCandle || !canPreviewSelectedH1Impulse) return;
    setH1PreviewLoading(true);
    setH1PreviewError(null);
    try {
      const preview = await previewH1Impulse({
        symbol: payload.symbol,
        signalCandleTime: selectedCandle.time,
        riskReward,
        targetMode,
        asOf: payload.replay?.as_of ?? payload.range.end,
      });
      const candidate = h1ImpulsePreviewToSetupCandidate(preview);
      addH1ImpulsePreview(candidate);
      toggleSelectedPlaybook("h1_impulse_retest_v1", true);
      selectSetup(candidate.id);
      setInspectorTab("setups");
      setSelectedCandle(null);
    } catch (error) {
      setH1PreviewError(error instanceof Error ? error.message : "Không thể dựng H1 setup preview.");
    } finally {
      setH1PreviewLoading(false);
    }
  }, [addH1ImpulsePreview, canPreviewSelectedH1Impulse, payload.range.end, payload.replay?.as_of, payload.symbol, selectSetup, selectedCandle, setInspectorTab, toggleSelectedPlaybook]);
  const displayedSetupBoxes = manualAiLevelEdit
    ? setupBoxes.map((box) => box.candidate.id === manualAiLevelEdit.candidate.id ? manualAiLevelEdit.previewBox : box)
    : setupBoxes;

  return (
    <div
      data-chart-capture-root="true"
      className="relative h-full min-h-0 touch-none overflow-hidden bg-[#080b10] lg:min-h-[540px]"
      onMouseLeave={() => setPointerY(null)}
      onMouseMove={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        setPointerY(event.clientY - rect.top);
      }}
    >
      <div
        ref={containerRef}
        className="absolute inset-0"
        onClick={clearSelection}
      />
      {selectedCandleMarker ? (
        <div
          className="pointer-events-none absolute z-[16] rounded-sm border border-cyan-200/90 bg-cyan-300/10 shadow-[0_0_8px_rgba(103,232,249,0.45)]"
          style={{
            left: selectedCandleMarker.x,
            top: selectedCandleMarker.y,
            width: selectedCandleMarker.width,
            height: selectedCandleMarker.height,
          }}
        />
      ) : null}
      <ChartDrawingControls
        drawings={renderedDrawings}
        measure={measurePreview}
        priceGuide={copyPriceGuide}
        plotWidth={drawingPlotWidth}
        selectedId={selectedDrawingId}
        activeTool={drawingTool}
        measureHasStart={measureStartRef.current !== null}
        pendingNote={pendingNote}
        noteContent={noteContent}
        chartWidth={containerRef.current?.clientWidth ?? 320}
        message={drawingMessage}
        onDelete={(drawing) => void removeDrawing(drawing)}
        onMoveStart={beginMoveDrawing}
        onSelect={(drawing) => {
          setSelectedCandle(null);
          setSelectedDrawingId(drawing.id);
          setSelected(null);
        }}
        onToolChange={changeDrawingTool}
        onPointerDown={beginChartDrawing}
        onPointerMove={handleDrawingHover}
        onPointerLeave={() => {
          if (drawingTool === "copy_price") setCopyPriceGuide(null);
        }}
        onNoteContentChange={setNoteContent}
        onSaveNote={() => {
          const content = noteContent.trim();
          if (!content || !pendingNote) return;
          void persistDrawing("note", [pendingNote.anchor], {}, content);
          setPendingNote(null);
          setNoteContent("");
        }}
        onCancelNote={() => {
          setPendingNote(null);
          changeDrawingTool("cursor");
        }}
      />
      {addEntityKind ? (
        <div
          className="absolute inset-0 z-40 cursor-crosshair"
          onClick={(event) => event.stopPropagation()}
          onPointerDown={beginManualDraw}
        />
      ) : null}
      {addEntityKind ? (
        <div className="pointer-events-none absolute left-4 top-4 z-50 rounded-md border border-cyan-400/40 bg-ink-900/90 px-3 py-2 text-xs text-cyan-100 shadow-lg">
          Drag to add {manualZoneSpec(addEntityKind).label}
        </div>
      ) : null}
      {drawError ? (
        <div className="pointer-events-none absolute left-4 top-4 z-40 max-w-sm rounded-md border border-rose-500/40 bg-rose-950/90 px-3 py-2 text-xs text-rose-100 shadow-lg">
          {drawError}
        </div>
      ) : null}
      {showIntradayLevels && !addEntityKind ? (
        <IntradayMapPanel
          map={payload.layers.intraday_map}
          bias={payload.layers.contexts.H1?.bias?.effective_value ?? "neutral"}
        />
      ) : null}
      {showStructure && !addEntityKind ? (
        <WaveStrengthBadge metrics={payload.layers.wave_metrics} />
      ) : null}
      <div className="pointer-events-none absolute inset-0">
        {zoneBoxes.map((box) => {
          const isSelected = selected?.kind === "zone" && selected.entity.id === box.zone.id;
          const isHovered = hoveredZoneId === box.zone.id;
          const setupStatus = setupStateByZone.get(box.zone.id);
          const zoneClasses = zoneVisualClasses(box.zone);
          const showLabel = compactViewport
            ? isSelected || (box.width > 150 && box.height > 20 && box.zone.weight >= 0.78)
            : isSelected ||
              isHovered ||
              (importantZonesOnly
                ? box.width > 220 && box.height > 18 && box.zone.weight >= 0.7
                : box.width > 170 && box.height > 18 && box.zone.weight >= 0.55);
          return (
            <div
              key={box.zone.id}
              className={compactClassName(`pointer-events-auto absolute select-none overflow-hidden border transition ${
                zoneClasses.box
              } ${box.zone.status === "active" ? "" : "border-dashed opacity-45"} ${
                setupStatus === "eligible" ? "ring-2 ring-cyan-300/80" : ""
              } ${
                setupStatus === "waiting_confirmation" ? "ring-2 ring-yellow-300/70" : ""
              } ${
                box.zone.id === "__manual_zone_preview__" ? "z-40 border-dashed ring-1 ring-cyan-200" : ""
              } ${isSelected || isHovered ? "opacity-100" : "opacity-70"} ${
                isSelected ? "z-30 cursor-move ring-1 ring-cyan-300" : "z-10 cursor-pointer"
              }`)}
              style={{
                left: box.x,
                top: box.y,
                width: box.width,
                height: box.height,
              }}
              title={`${box.zone.type} ${box.zone.status} ${box.zone.price_low.toFixed(2)}-${box.zone.price_high.toFixed(2)}`}
              role="button"
              onMouseEnter={() => setHoveredZoneId(box.zone.id)}
              onMouseLeave={() => setHoveredZoneId(null)}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                if (box.zone.id !== "__manual_zone_preview__" && !isSelected) {
                  updateDraftZone(box.zone);
                }
              }}
              onPointerDown={(event) => {
                event.preventDefault();
                event.stopPropagation();
                if (box.zone.id === "__manual_zone_preview__") return;
                if (isSelected) {
                  beginZoneDrag(event, box, zoneDragModeFromPointer(event, box));
                }
              }}
            >
              {isSelected ? (
                <>
                  <button
                    className="absolute left-0 top-0 z-40 h-4 w-full cursor-ns-resize border-t border-cyan-200/90 bg-cyan-300/20 md:h-2.5"
                    title="Drag to resize zone high"
                    type="button"
                    onClick={(event) => event.stopPropagation()}
                    onPointerDown={(event) => beginZoneDrag(event, box, "resize-top")}
                  />
                  <button
                    className="absolute bottom-0 left-0 z-40 h-4 w-full cursor-ns-resize border-b border-cyan-200/90 bg-cyan-300/20 md:h-2.5"
                    title="Drag to resize zone low"
                    type="button"
                    onClick={(event) => event.stopPropagation()}
                    onPointerDown={(event) => beginZoneDrag(event, box, "resize-bottom")}
                  />
                  <button
                    className="absolute left-0 top-0 z-50 h-full w-4 cursor-ew-resize border-l border-cyan-200/90 bg-cyan-300/20 md:w-2.5"
                    title="Drag to resize zone start"
                    type="button"
                    onClick={(event) => event.stopPropagation()}
                    onPointerDown={(event) => beginZoneDrag(event, box, "resize-left")}
                  />
                  <button
                    className="absolute right-0 top-0 z-50 h-full w-4 cursor-ew-resize border-r border-cyan-200/90 bg-cyan-300/20 md:w-2.5"
                    title="Drag to resize zone end"
                    type="button"
                    onClick={(event) => event.stopPropagation()}
                    onPointerDown={(event) => beginZoneDrag(event, box, "resize-right")}
                  />
                </>
              ) : null}
              {showLabel ? (
                <span
                  className={`absolute left-1 top-1 max-w-[220px] truncate rounded px-1.5 py-0.5 text-[10px] font-medium ${
                    zoneClasses.label
                  }`}
                >
                  {box.zone.status === "draft" ? "DRAFT · " : ""}
                  {box.zone.timeframe} {zoneDisplayName(box.zone)} · {box.zone.weight.toFixed(2)} · {formatZoneDate(box.zone.visual_start)}
                </span>
              ) : null}
            </div>
          );
        })}
        {intradayLevelMarkers.map(({ level, y, bandY, bandHeight, plotWidth }) => {
          const isHigh = level.side === "high";
          const isBroken = level.status === "broken";
          const isReclaimed = level.status === "reclaimed";
          const isTestingFlip = level.status === "testing_flip";
          const isTesting = level.status === "testing" || isTestingFlip;
          const lineColor = isBroken
            ? "rgba(100,116,139,0.45)"
            : isTestingFlip
              ? "rgba(250,204,21,0.88)"
            : isReclaimed
              ? "rgba(34,211,238,0.72)"
              : isHigh
                ? "rgba(251,113,133,0.72)"
                : "rgba(52,211,153,0.72)";
          return (
            <div key={`intraday:${level.id}`} className={`absolute left-0 z-[22] ${isBroken ? "opacity-55" : ""}`} style={{ top: y, width: plotWidth }}>
              {isTesting ? (
                <span
                  className={`absolute left-0 w-full ${isHigh ? "bg-rose-400/[0.07]" : "bg-emerald-400/[0.07]"}`}
                  style={{ top: bandY - y, height: bandHeight }}
                />
              ) : null}
              <span
                className="absolute left-0 top-0 w-full border-t"
                style={{ borderColor: lineColor, borderTopStyle: level.live || isBroken ? "dashed" : "solid" }}
              />
              <span
                className={`absolute right-1 top-0 -translate-y-1/2 whitespace-nowrap rounded border bg-ink-950/92 px-1.5 py-0.5 font-mono text-[9px] font-bold shadow ${
                  isBroken
                    ? "border-slate-600 text-slate-400"
                    : isTestingFlip
                      ? "border-yellow-300/60 text-yellow-200"
                    : isReclaimed
                      ? "border-cyan-400/50 text-cyan-200"
                      : isHigh
                        ? "border-rose-400/45 text-rose-200"
                        : "border-emerald-400/45 text-emerald-200"
                }`}
                title={`${level.label} ${level.price.toFixed(2)} · ${levelStatusLabel(level.status)} · ${level.distance_atr?.toFixed(2) ?? "--"} M15 ATR`}
              >
                {level.label} · {levelStatusLabel(level.status)} · {level.price.toFixed(2)}
              </span>
            </div>
          );
        })}
        {swingDots.map((dot) => {
          const isHigh = dot.swingType === "high";
          const isSelected = selected?.kind === "structure" && selected.entity.id === dot.point.id;
          return (
            <button
              key={dot.point.id}
              className={`pointer-events-auto absolute z-30 flex h-5 w-5 -translate-x-1/2 items-center justify-center rounded-full border shadow-[0_0_6px_rgba(0,0,0,0.55)] transition after:absolute after:-inset-2 after:content-[''] hover:scale-110 ${
                isHigh
                  ? "-translate-y-[calc(100%+4px)] border-rose-300/80 bg-rose-950/90 text-rose-300"
                  : "translate-y-[4px] border-emerald-300/80 bg-emerald-950/90 text-emerald-300"
              } ${isSelected ? "ring-1 ring-cyan-200" : ""}`}
              style={{ left: dot.x, top: dot.y }}
              title={`${isHigh ? "Swing High" : "Swing Low"} ${dot.point.type} ${dot.point.price.toFixed(2)}`}
              type="button"
              onClick={() => selectStructurePoint(dot.point)}
            >
              {isHigh ? <ArrowDown size={14} strokeWidth={3} /> : <ArrowUp size={14} strokeWidth={3} />}
              <span className="sr-only">{dot.label}</span>
            </button>
          );
        })}
        {structureDots.map((dot) => (
          <button
            key={dot.point.id}
            className={`pointer-events-auto absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border border-slate-950 ${
              dot.point.direction === "down" || ["LH", "LL"].includes(dot.point.type) ? "bg-rose-300" : "bg-emerald-300"
            }`}
            style={{ left: dot.x, top: dot.y }}
            title={`${dot.point.type} ${dot.point.price.toFixed(2)}`}
            type="button"
            onClick={() => selectStructurePoint(dot.point)}
          />
        ))}
        {m15TriggerMarkers.map(({ trigger, x, y }) => {
          const className =
            trigger.status === "eligible"
              ? "border-cyan-200 bg-cyan-300 text-cyan-950 shadow-[0_0_10px_rgba(34,211,238,0.6)]"
              : trigger.status === "waiting_confirmation"
                ? "border-yellow-200 bg-yellow-300 text-yellow-950 shadow-[0_0_8px_rgba(250,204,21,0.45)]"
                : "border-slate-300/60 bg-slate-400/75 text-slate-950";
          const label = `${trigger.zone_type} ${trigger.reaction_state} ${trigger.status} ${trigger.open.toFixed(2)}/${trigger.high.toFixed(2)}/${trigger.low.toFixed(2)}/${trigger.close.toFixed(2)}`;
          return (
            <div
              key={`${trigger.zone_id}:${trigger.time}`}
              className={`pointer-events-none absolute z-[25] flex h-4 min-w-4 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded border px-1 text-[9px] font-black leading-none ${className}`}
              style={{ left: x, top: y }}
              title={`${label}\n${trigger.reason[0] ?? ""}`}
            >
              M15
            </div>
          );
        })}
        {waveMetricMarkers.map(({ leg, x, y }) => {
          const up = leg.direction === "up";
          const duration = formatWaveDuration(leg);
          return (
            <span
              key={leg.id}
              className={`absolute z-[23] -translate-x-1/2 whitespace-nowrap rounded-sm bg-ink-950/65 px-1 py-0.5 font-mono text-[9px] font-medium tabular-nums shadow-sm backdrop-blur-[1px] ${
                up ? "-translate-y-[calc(100%+30px)]" : "translate-y-[30px]"
              } ${
                up ? "text-emerald-300/85" : "text-rose-300/85"
              }`}
              style={{ left: x, top: y }}
              title={`${up ? "Up" : "Down"} wave ${leg.price_move.toFixed(2)} · ${duration}H`}
            >
              {formatWaveLegLabel(leg)}
            </span>
          );
        })}
        {h1ImpulseChartMarkers.map(({ marker, x, y }) => {
          const eligible = marker.status === "eligible";
          const short = marker.direction === "short";
          const className = eligible
            ? "text-amber-300 drop-shadow-[0_0_5px_rgba(252,211,77,0.8)]"
            : "text-slate-400 drop-shadow-[0_0_4px_rgba(148,163,184,0.55)]";
          const blocked = marker.blocked_reason.length > 0 ? `\n${marker.blocked_reason.join("\n")}` : "";
          return (
            <button
              key={`${marker.time}:${marker.status}`}
              className={`group pointer-events-auto absolute z-[45] flex h-5 w-5 -translate-x-1/2 items-center justify-center transition hover:z-[70] hover:scale-110 ${
                short ? "-translate-y-[calc(100%+6px)]" : "translate-y-[6px]"
              } ${className}`}
              style={{ left: x, top: y }}
              type="button"
              onClick={() => {
                const candle = payload.layers.candles.find((item) => item.time === marker.time);
                if (!candle) return;
                setSelected(null);
                selectSetup(null);
                setManualAiEditSetupId(null);
                setSelectedDrawingId(null);
                setSelectedCandle(candle);
              }}
            >
              <Star fill="currentColor" size={eligible ? 15 : 13} strokeWidth={2.2} />
              <span className="sr-only">H1 {marker.status} {marker.direction}</span>
              <span
                className={`pointer-events-none absolute left-1/2 z-[60] w-64 -translate-x-1/2 rounded-md border border-ink-600 bg-ink-950/95 px-2.5 py-2 text-left text-[10px] font-normal leading-4 text-slate-200 opacity-0 shadow-xl transition-opacity delay-0 duration-150 group-hover:opacity-100 group-hover:delay-[850ms] ${
                  short ? "bottom-full mb-1.5" : "top-full mt-1.5"
                }`}
                role="tooltip"
              >
                <span className={`block font-bold ${eligible ? "text-amber-200" : "text-slate-300"}`}>
                  H1 {eligible ? "ELIGIBLE" : "NEEDS REVIEW"} · {marker.direction.toUpperCase()}
                </span>
                <span className="mt-0.5 block text-slate-400">
                  Body {marker.body_atr_ratio.toFixed(2)} ATR · Range {marker.range_atr_ratio.toFixed(2)} ATR
                </span>
                {blocked ? <span className="mt-1 block whitespace-pre-line text-rose-200/85">{blocked.trim()}</span> : null}
              </span>
            </button>
          );
        })}
        {newsTimelineMarkers.map((marker) => {
          const { event, x, y } = marker;
          const className =
            event.tier === 1
              ? "border-red-300 bg-red-950/95 text-red-100 shadow-[0_0_10px_rgba(248,113,113,0.45)]"
              : "border-red-400/70 bg-ink-950/95 text-red-200 shadow-[0_0_8px_rgba(248,113,113,0.25)]";
          return (
            <div
              key={event.id}
              className={`pointer-events-auto absolute z-[28] flex h-5 w-5 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border ${className}`}
              style={{ left: x, top: y }}
              onMouseEnter={() => setHoveredNewsMarker(marker)}
              onMouseLeave={() => setHoveredNewsMarker(null)}
            >
              <Newspaper size={11} strokeWidth={2.6} />
              <span className="sr-only">{event.country} news</span>
            </div>
          );
        })}
        {hoveredNewsMarker ? (
          <NewsTimelineTooltip marker={hoveredNewsMarker} />
        ) : null}
        {displayedSetupBoxes.map((box) => {
          const candidate = box.candidate;
          const isH1ImpulsePreview = candidate.metadata.h1_impulse_preview === true;
          const previewOutcome = readObject(candidate.metadata.outcome);
          const outcomeStatus = typeof previewOutcome.status === "string" ? previewOutcome.status : "open";
          const resultR = typeof previewOutcome.result_r === "number" ? previewOutcome.result_r : null;
          const entrySource = setupEntrySourceLabel(candidate);
          const planStatus = typeof candidate.metadata.manual_ai_plan_status === "string"
            ? candidate.metadata.manual_ai_plan_status
            : "pending";
          const statusLabel = isH1ImpulsePreview
            ? `${outcomeStatus.toUpperCase()}${resultR === null ? "" : ` ${resultR > 0 ? "+" : ""}${resultR.toFixed(2)}R`}`
            : planStatus === "draft" ? "DRAFT" : planStatus === "replace_requested" ? "REPLACING" : "PENDING";
          const compactLabel = isH1ImpulsePreview
            ? `${statusLabel} · ${candidate.direction === "long" ? "BUY" : "SELL"}`
            : `${candidate.direction === "long" ? "BUY" : "SELL"} · ${candidate.risk_reward?.toFixed(2) ?? "--"}R`;
          const detailLabel = isH1ImpulsePreview
            ? `${statusLabel} · H1 Impulse · ${candidate.risk_reward?.toFixed(2) ?? "--"}R · ${entrySource}`
            : `${statusLabel} · Manual AI · ${candidate.risk_reward?.toFixed(2) ?? "--"}R · ${entrySource}`;
          const canEdit = isH1ImpulsePreview
            ? candidate.metadata.execution_plan !== true || ["draft", "approved", "armed"].includes(planStatus)
            : ["draft", "approved", "armed"].includes(planStatus);
          const isSelected = selectedSetupId === candidate.id;
          const isEditing = manualAiEditSetupId === candidate.id;
          const isDimmed = selectedSetupId !== null && !isSelected;
          return (
            <div
              key={`setup:${candidate.id}`}
              aria-label={`${detailLabel}. Click để chọn setup.`}
              className={`pointer-events-auto absolute overflow-visible border border-dashed bg-transparent text-left transition ${
                isEditing
                  ? "z-[40] border-cyan-200 shadow-[0_0_12px_rgba(34,211,238,0.28)]"
                  : isSelected
                    ? "z-[38] border-yellow-200 shadow-[0_0_10px_rgba(250,204,21,0.28)]"
                    : isH1ImpulsePreview
                      ? `z-[32] ${h1PreviewBoxClass(outcomeStatus)}`
                      : "z-[32] border-yellow-300/55 shadow-[0_0_4px_rgba(250,204,21,0.12)] hover:border-yellow-200/90"
              } ${isDimmed ? "opacity-35" : "opacity-100"}`}
              style={{ left: box.x, top: box.y, width: box.width, height: box.height }}
              title={`${detailLabel}\nEntry ${candidate.entry} · SL ${candidate.stop_loss} · TP ${candidate.take_profit[0]}\nExpires ${candidate.expires_at ?? "--"}`}
              role="button"
              tabIndex={0}
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                selectSetup(candidate.id);
                setInspectorTab("setups");
              }}
              onKeyDown={(event) => {
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
                event.stopPropagation();
                selectSetup(candidate.id);
                setInspectorTab("setups");
              }}
            >
              {!isSelected ? (
                <span
                  className="pointer-events-none absolute z-10 border-t border-dashed border-cyan-100/75"
                  style={{ top: box.entryY - box.y, left: 0, width: box.width }}
                  title={`Entry ${candidate.entry?.toFixed(2) ?? "--"}`}
                />
              ) : null}
              {isSelected ? (
                <>
                  <span
                    className="pointer-events-none absolute border border-dashed border-cyan-200/70 bg-cyan-400/14"
                    style={{ left: box.profit.x - box.x, top: box.profit.y - box.y, width: box.profit.width, height: box.profit.height }}
                  />
                  <span
                    className="pointer-events-none absolute border border-dashed border-fuchsia-200/70 bg-fuchsia-500/14"
                    style={{ left: box.loss.x - box.x, top: box.loss.y - box.y, width: box.loss.width, height: box.loss.height }}
                  />
                  <span
                    className={`absolute z-20 h-3 -translate-y-1/2 border-t border-cyan-100/90 ${isEditing ? "pointer-events-auto cursor-ns-resize hover:border-t-2 hover:border-white" : "pointer-events-none"}`}
                    style={{ top: box.entryY - box.y, left: 0, width: Math.max(box.width + 112, 160) }}
                    title={isEditing ? "Kéo để dời Entry" : "Entry · chọn Edit levels hoặc nhấn E để chỉnh"}
                    onPointerDown={isEditing ? (event) => beginManualAiLevelDrag(event, box, "entry") : undefined}
                  ><span className="absolute right-0 top-1/2 -translate-y-1/2 rounded border border-cyan-300/50 bg-cyan-950/95 px-1.5 py-0.5 text-[9px] font-black text-cyan-100 shadow">ENTRY {candidate.entry?.toFixed(2)}</span></span>
                  <span
                    className={`absolute z-20 h-3 -translate-y-1/2 border-t border-rose-300/90 ${isEditing ? "pointer-events-auto cursor-ns-resize hover:border-t-2 hover:border-white" : "pointer-events-none"}`}
                    style={{ top: box.stopY - box.y, left: 0, width: Math.max(box.width + 112, 160) }}
                    title={isEditing ? "Kéo để dời Stop Loss" : "Stop Loss · chọn Edit levels hoặc nhấn E để chỉnh"}
                    onPointerDown={isEditing ? (event) => beginManualAiLevelDrag(event, box, "stopLoss") : undefined}
                  ><span className="absolute right-0 top-1/2 -translate-y-1/2 rounded border border-rose-300/50 bg-rose-950/95 px-1.5 py-0.5 text-[9px] font-black text-rose-100 shadow">SL {candidate.stop_loss?.toFixed(2)}</span></span>
                  <span
                    className={`absolute z-20 h-3 -translate-y-1/2 border-t border-emerald-300/90 ${isEditing ? "pointer-events-auto cursor-ns-resize hover:border-t-2 hover:border-white" : "pointer-events-none"}`}
                    style={{ top: box.takeProfitY - box.y, left: 0, width: Math.max(box.width + 112, 160) }}
                    title={isEditing ? "Kéo để dời Take Profit" : "Take Profit · chọn Edit levels hoặc nhấn E để chỉnh"}
                    onPointerDown={isEditing ? (event) => beginManualAiLevelDrag(event, box, "takeProfit") : undefined}
                  ><span className="absolute right-0 top-1/2 -translate-y-1/2 rounded border border-emerald-300/50 bg-emerald-950/95 px-1.5 py-0.5 text-[9px] font-black text-emerald-100 shadow">TP {candidate.take_profit[0]?.toFixed(2)}</span></span>
                </>
              ) : null}
              {isSelected && canEdit ? (
                <span
                  className={`absolute bottom-1 right-1 z-30 rounded border px-1.5 py-0.5 text-[9px] font-black shadow-lg ${
                    isEditing
                      ? "border-cyan-200/80 bg-cyan-950/95 text-cyan-100"
                      : "border-yellow-200/70 bg-yellow-950/95 text-yellow-100 hover:border-cyan-200 hover:text-cyan-100"
                  }`}
                  role="button"
                  tabIndex={0}
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    setManualAiEditSetupId(candidate.id);
                  }}
                  onKeyDown={(event) => {
                    if (event.key !== "Enter" && event.key !== " ") return;
                    event.preventDefault();
                    event.stopPropagation();
                    setManualAiEditSetupId(candidate.id);
                  }}
                >
                  {isEditing ? "EDITING · ESC" : "E · EDIT LEVELS"}
                </span>
              ) : null}
              <span className={`absolute right-0 top-[-24px] z-30 whitespace-nowrap rounded border px-1.5 py-0.5 text-[9px] font-black shadow-lg ${
                isSelected
                  ? isH1ImpulsePreview ? h1PreviewLabelClass(outcomeStatus) : "border-yellow-200/80 bg-yellow-950/95 text-yellow-100"
                  : candidate.direction === "long"
                    ? "border-emerald-300/50 bg-emerald-950/90 text-emerald-100"
                    : "border-rose-300/50 bg-rose-950/90 text-rose-100"
              }`}>
                {isSelected ? detailLabel : compactLabel}
              </span>
            </div>
          );
        })}
        {tradeBoxes.map((box) => {
          const trade = box.trade;
          const isLong = trade.direction === "long" || trade.side === "buy";
          const isSelected = selected?.kind === "trade" && box.trades.some((item) => item.id === selected.entity.id);
          const partialDone = box.trades.some((item) => readObject(item.metadata.partial_take_profit).done === true);
          const breakevenApplied = box.trades.some((item) => readObject(item.metadata.partial_take_profit).breakeven_applied === true);
          const isGroup = box.trades.length > 1;
          const accountCount = tradeAccountCount(box.trades);
          const label = isGroup
            ? `${trade.playbook} ${trade.direction} ${accountCount} accounts: ${tradeGroupSummary(box.trades)}`
            : `${trade.playbook} ${trade.direction} ${trade.status} ${trade.pnl_r?.toFixed(2) ?? "--"}R`;
          return (
            <button
              key={trade.id}
              className={`pointer-events-auto absolute z-[35] overflow-hidden border border-dashed bg-transparent text-left transition hover:brightness-125 ${
                isSelected ? "border-white ring-1 ring-cyan-200/80" : "border-white/60"
              }`}
              style={{
                left: box.x,
                top: box.y,
                width: box.width,
                height: box.height,
                boxShadow: isSelected
                  ? "0 0 14px rgba(34,211,238,0.48)"
                  : "0 0 10px rgba(56,189,248,0.25)",
              }}
              title={label}
              type="button"
              onClick={(event) => {
                event.preventDefault();
                event.stopPropagation();
                selectTrade(trade);
              }}
            >
              <span
                className="absolute border border-dashed border-cyan-200/90 bg-cyan-400/22"
                style={{
                  left: box.profit.x - box.x,
                  top: box.profit.y - box.y,
                  width: box.profit.width,
                  height: box.profit.height,
                  boxShadow: "inset 0 0 16px rgba(34,211,238,0.25)",
                }}
              />
              <span
                className="absolute border border-dashed border-fuchsia-200/90 bg-fuchsia-500/24"
                style={{
                  left: box.loss.x - box.x,
                  top: box.loss.y - box.y,
                  width: box.loss.width,
                  height: box.loss.height,
                  boxShadow: "inset 0 0 16px rgba(217,70,239,0.25)",
                }}
              />
              <span
                className={`absolute left-1 top-1 rounded border px-1 py-0.5 text-[10px] font-black tracking-wide shadow-lg ${
                  isLong
                    ? "border-cyan-200/90 bg-cyan-950/95 text-cyan-100"
                    : "border-fuchsia-200/90 bg-fuchsia-950/95 text-fuchsia-100"
                }`}
              >
                {isGroup ? `${accountCount} acct` : `${trade.pnl_r?.toFixed(2) ?? "--"}R`}
              </span>
              {isGroup && (!compactViewport || isSelected) ? (
                <span className="absolute right-1 top-1 max-w-[calc(100%-4.5rem)] truncate rounded border border-slate-200/70 bg-ink-950/95 px-1 py-0.5 text-[9px] font-black text-slate-100 shadow-lg">
                  {compactTradeGroupSummary(box.trades)}
                </span>
              ) : null}
              {partialDone ? (
                <span className="absolute bottom-1 left-1 rounded border border-emerald-200/80 bg-emerald-950/95 px-1 py-0.5 text-[9px] font-black text-emerald-100 shadow-lg">
                  {breakevenApplied ? "P/BE" : "P"}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
      {selectedCandle && drawingTool === "cursor" && !addEntityKind ? (
        <CandleInfoCard
          atr={selectedCandleAtr}
          atrTimeframe={selectedCandleAtrTimeframe}
          candle={selectedCandle}
          canPreviewH1Impulse={canPreviewSelectedH1Impulse}
          previewError={h1PreviewError}
          previewLoading={h1PreviewLoading}
          targetOptions={h1TargetQuote?.signal_candle_time === selectedCandle.time ? h1TargetQuote.target_plan.options : []}
          targetQuoteLoading={h1TargetQuoteLoading}
          timeframe={payload.timeframe}
          timezone={payload.layers.intraday_map.timezone || "UTC"}
          onPreviewH1Impulse={(riskReward, targetMode) => { void addH1SetupPreview(riskReward, targetMode); }}
          onClose={() => setSelectedCandle(null)}
        />
      ) : null}
      {manualAiLevelEdit && !manualAiLevelEdit.dragging ? (
        <ManualAiLevelEditDialog
          playbook={manualAiLevelEdit.candidate.playbook}
          side={manualAiLevelEdit.candidate.direction === "long" ? "buy" : "sell"}
          status={manualAiLevelEdit.status}
          levels={manualAiLevelEdit.levels}
          original={manualAiLevelEdit.original}
          error={manualAiLevelEdit.error}
          saving={manualAiLevelEdit.saving}
          entrySource={manualAiLevelEdit.entrySource}
          entryOptions={readEntryOptions(manualAiLevelEdit.candidate.metadata.entry_options)}
          rrMin={1.5}
          rrMax={4}
          onEntrySourceSelect={selectSetupEntrySource}
          onLevelsChange={updateManualAiEditLevels}
          onApply={() => { void applyManualAiLevelEdit(); }}
          onCancel={exitManualAiSetupInteraction}
        />
      ) : null}
      {candleLabel !== null && !payload.replay?.enabled ? (
        <CandleCountdown
          timeframe={payload.timeframe}
          priceY={candleLabel.priceY}
          scaleWidth={candleLabel.scaleWidth}
          isUp={candleLabel.isUp}
          chartHeight={candleLabel.chartHeight}
          pointerY={pointerY}
          spread={spread}
        />
      ) : null}
    </div>
  );
}

function h1PreviewBoxClass(status: string): string {
  if (status === "win") return "border-emerald-300/80 shadow-[0_0_10px_rgba(52,211,153,0.24)] hover:border-emerald-200";
  if (status === "loss") return "border-rose-300/80 shadow-[0_0_10px_rgba(251,113,133,0.24)] hover:border-rose-200";
  if (status === "ambiguous") return "border-amber-300/80 shadow-[0_0_10px_rgba(251,191,36,0.24)] hover:border-amber-200";
  return "border-cyan-300/65 shadow-[0_0_8px_rgba(34,211,238,0.18)] hover:border-cyan-200";
}

function h1PreviewLabelClass(status: string): string {
  if (status === "win") return "border-emerald-200/80 bg-emerald-950/95 text-emerald-100";
  if (status === "loss") return "border-rose-200/80 bg-rose-950/95 text-rose-100";
  if (status === "ambiguous") return "border-amber-200/80 bg-amber-950/95 text-amber-100";
  return "border-cyan-200/80 bg-cyan-950/95 text-cyan-100";
}

function readEntryOptions(value: unknown): Array<{ source: string; label: string; price: number }> {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const option = item as Record<string, unknown>;
    if (typeof option.source !== "string" || typeof option.label !== "string" || typeof option.price !== "number") return [];
    return [{ source: option.source, label: option.label, price: option.price }];
  });
}

function setupEntrySourceLabel(candidate: SetupCandidate): string {
  for (const key of ["entry_source", "entry_model", "trigger_method"]) {
    const value = candidate.metadata[key];
    if (typeof value === "string" && value.trim()) return value.replace(/_/g, " ");
  }
  return "strategy calculated";
}

function filterVisibleM15Triggers(triggers: M15TriggerOverlay[]): M15TriggerOverlay[] {
  return triggers.filter((trigger) => trigger.candidate_id !== null);
}

function scaleEventsForViewport<T>(width: number, events: T[]): T[] {
  return isMobileChartWidth(width) ? [] : events;
}
