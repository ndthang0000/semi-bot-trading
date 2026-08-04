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
import { ArrowDown, ArrowUp, Newspaper } from "lucide-react";
import { type PointerEvent as ReactPointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createManualZone, updateZoneOverride, type NewsResponse } from "../api/chart";
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
import type { M15TriggerMarker, StructureDot, SwingDot, ZoneBox, ZoneDragMode, ZoneDragState } from "./chart/chartTypes";
import { CandleCountdown, NewsTimelineTooltip, type NewsTimelineMarker } from "./chart/chartWidgets";
import {
  clampNumber,
  compactTradeGroupSummary,
  groupTradeBoxesByCandidate,
  interpolateChartX,
  readObject,
  tradeGroupSummary,
  tradeToBox,
  type CandleDatum,
  type TradeBox,
} from "./chart/tradeOverlay";
import type {
  AddEntityKind,
  ChartPayload,
  M15TriggerOverlay,
  PriceZone,
  SetupCandidate,
  SpreadSummary,
  StructurePoint,
  TradeOrder,
  ZoneTypeVisibility,
} from "../types";

type TradingChartProps = {
  payload: ChartPayload;
  spread?: SpreadSummary | null;
  newsData?: NewsResponse | null;
  onEntityCreated: () => void;
  onZonePersisted?: (zone: PriceZone) => void;
};

type ManualDrawState = {
  kind: AddEntityKind;
  startPointerPrice: number;
  startPointerTime: number;
};

const MIN_ZONE_HEIGHT = 0.01;
const MIN_ZONE_DURATION_SECONDS = 60;


export function TradingChart({ payload, spread, newsData, onEntityCreated, onZonePersisted }: TradingChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const scaleAnchorSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const zigzagSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const setSelected = useChartStore((state) => state.setSelected);
  const selected = useChartStore((state) => state.selected);
  const showZones = useChartStore((state) => state.showZones);
  const zoneTypeVisibility = useChartStore((state) => state.zoneTypeVisibility);
  const showStructure = useChartStore((state) => state.showStructure);
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
  const [m15TriggerMarkers, setM15TriggerMarkers] = useState<M15TriggerMarker[]>([]);
  const [newsTimelineMarkers, setNewsTimelineMarkers] = useState<NewsTimelineMarker[]>([]);
  const [hoveredNewsMarker, setHoveredNewsMarker] = useState<NewsTimelineMarker | null>(null);
  const [hoveredZoneId, setHoveredZoneId] = useState<string | null>(null);
  const [drawPreviewZone, setDrawPreviewZone] = useState<PriceZone | null>(null);
  const [drawError, setDrawError] = useState<string | null>(null);
  const [candleLabel, setCandleLabel] = useState<{ priceY: number; scaleWidth: number; isUp: boolean; chartHeight: number } | null>(null);
  const [pointerY, setPointerY] = useState<number | null>(null);
  const scheduledRecalcRef = useRef<number | null>(null);
  const interactionRecalcRef = useRef<number | null>(null);
  const wheelStopRef = useRef<number | null>(null);
  const draftZoneRef = useRef<PriceZone | null>(null);
  const zoneDragRef = useRef<ZoneDragState | null>(null);
  const manualDrawRef = useRef<ManualDrawState | null>(null);
  const payloadRef = useRef(payload);
  const showZonesRef = useRef(showZones);
  const zoneTypeVisibilityRef = useRef(zoneTypeVisibility);
  const showStructureRef = useRef(showStructure);
  const tradeVisibilityModeRef = useRef(tradeVisibilityMode);
  const importantZonesOnlyRef = useRef(importantZonesOnly);
  const maxVisibleZonesRef = useRef(maxVisibleZones);
  const addEntityKindRef = useRef(addEntityKind);
  const onEntityCreatedRef = useRef(onEntityCreated);
  const onZonePersistedRef = useRef(onZonePersisted);
  const newsDataRef = useRef(newsData);
  const handledZoneFocusRequestRef = useRef<number | null>(null);
  const handledTradeFocusRequestRef = useRef<number | null>(null);
  const drawPreviewZoneRef = useRef<PriceZone | null>(drawPreviewZone);
  const persistedZoneDraftRef = useRef<PriceZone | null>(null);
  const candleDataRef = useRef<CandleDatum[]>([]);
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
  const candleKey = useMemo(() => {
    const first = payload.layers.candles.at(0)?.time ?? "";
    const lastCandle = payload.layers.candles.at(-1);
    const lastTime = lastCandle?.time ?? "";
    // Include last candle's close price so live-candle price updates
    // (same open_time, different close) also trigger a chart series update.
    const lastClose = lastCandle?.close?.toFixed(5) ?? "";
    return `${payload.symbol}:${payload.timeframe}:${payload.layers.candles.length}:${first}:${lastTime}:${lastClose}`;
  }, [payload.layers.candles, payload.symbol, payload.timeframe]);
  const viewKey = `${payload.symbol}:${payload.timeframe}:${payload.range.limit}:${payload.range.start_index ?? "latest"}`;
  const setupStateByZone = useMemo(() => buildSetupStateByZone(payload.layers.setup_candidates), [payload.layers.setup_candidates]);

  showZonesRef.current = showZones;
  zoneTypeVisibilityRef.current = zoneTypeVisibility;
  showStructureRef.current = showStructure;
  tradeVisibilityModeRef.current = tradeVisibilityMode;
  importantZonesOnlyRef.current = importantZonesOnly;
  maxVisibleZonesRef.current = maxVisibleZones;
  addEntityKindRef.current = addEntityKind;
  onEntityCreatedRef.current = onEntityCreated;
  onZonePersistedRef.current = onZonePersisted;
  newsDataRef.current = newsData;
  drawPreviewZoneRef.current = drawPreviewZone;
  candleDataRef.current = candleData;

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
    const zoneCandidates = (previewZone ? [...currentPayload.layers.zones, previewZone] : currentPayload.layers.zones).filter((zone) =>
      isZoneTypeVisible(zone, zoneTypeVisibilityRef.current),
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
    const visibleM15Triggers = filterVisibleM15Triggers(currentPayload.layers.m15_triggers ?? []);
    const m15Triggers = visibleM15Triggers.flatMap((trigger) => {
      const x = interpolateChartX(timeScale, toUnixTime(trigger.time), candleDataRef.current);
      const y = series.priceToCoordinate(trigger.close);
      if (x === null || y === null) return [];
      if (x < -12 || x > plotWidth + 12 || y < -12 || y > height + 12) return [];
      return [{ trigger, x, y }];
    });
    const newsMarkers = buildNewsTimelineMarkers(newsDataRef.current?.events ?? [], toUnixTime(lastCandle.time), plotWidth, height, timeScale);

    setZoneBoxes(zones);
    setStructureDots(visibleStructurePoints.filter((dot) => !readSwingType(dot.point)));
    setSwingDots(visibleSwings);
    setTradeBoxes(trades);
    setM15TriggerMarkers(m15Triggers);
    setNewsTimelineMarkers(newsMarkers);

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

  const timeFromClientX = useCallback((clientX: number): number | null => {
    const container = containerRef.current;
    const chart = chartRef.current;
    if (!container || !chart) return null;
    const rect = container.getBoundingClientRect();
    const coordinate = clientX - rect.left;
    const time = chart.timeScale().coordinateToTime(coordinate);
    return chartTimeToUnix(time) ?? projectedTimeFromCoordinate(chart, candleDataRef.current, coordinate);
  }, []);

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
    lockCurrentViewport(chartRef.current, lockedViewportRef);
    draftZoneRef.current = null;
    setSelected(null);
    restoreLockedViewport(chartRef.current, lockedViewportRef);
    scheduleOverlayRecalc();
  }, [scheduleOverlayRecalc, setSelected]);

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
      setSelected({ kind: "trade", entity: trade });
      restoreLockedViewport(chartRef.current, lockedViewportRef);
      scheduleOverlayRecalc();
    },
    [scheduleOverlayRecalc, setSelected],
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
  }, [importantZonesOnly, maxVisibleZones, payload, scheduleOverlayRecalc, showStructure, showZones, tradeVisibilityMode]);

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
      lineWidth: 2,
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
      scheduleOverlayRecalc();
      return;
    }

    const previousViewKey = appliedViewKeyRef.current;
    const lockedViewport = lockedViewportRef.current;
    const savedViewport = lockedViewport ?? lastViewportRef.current;
    const visibleRange = savedViewport?.logicalRange ?? chart.timeScale().getVisibleLogicalRange();
    const visiblePriceRange = savedViewport?.priceRange ?? chart.priceScale("right").getVisibleRange();
    const isReplay = Boolean(payload.replay?.enabled);

    // Detect incremental update: same view window, last candle updated OR one new candle added.
    // Works for both growing windows and sliding fixed-limit windows (oldest bar drops, new bar appends).
    // Use series.update() instead of setData() to avoid resetting the viewport.
    const prevData = candleDataRef.current;
    const isSameView = previousViewKey === viewKey;
    const lastCandleTimeNew = Number(candleData.at(-1)?.time ?? 0);
    const lastCandleTimePrev = Number(prevData.at(-1)?.time ?? 0);
    const isIncremental =
      !isReplay &&
      isSameView &&
      prevData.length > 0 &&
      candleData.length >= prevData.length &&
      candleData.length <= prevData.length + 1 &&
      lastCandleTimeNew >= lastCandleTimePrev; // last candle same or newer (not a full window shift)

    if (isIncremental) {
      // Snapshot viewport BEFORE update — series.update() with a new timestamp triggers
      // shiftVisibleRangeOnNewBar (default true) and can scroll the chart unexpectedly.
      const rangeBeforeUpdate = visibleRange;
      const priceRangeBeforeUpdate = visiblePriceRange;
      const wasManual = manualViewportRef.current;

      if (candleData.length > prevData.length) {
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
        chart.priceScale("right").setAutoScale(false);
        chart.priceScale("right").setVisibleRange(visiblePriceRange);
        replayPriceRangeRef.current = visiblePriceRange;
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
        {tradeBoxes.map((box) => {
          const trade = box.trade;
          const isLong = trade.direction === "long" || trade.side === "buy";
          const isSelected = selected?.kind === "trade" && box.trades.some((item) => item.id === selected.entity.id);
          const partialDone = box.trades.some((item) => readObject(item.metadata.partial_take_profit).done === true);
          const breakevenApplied = box.trades.some((item) => readObject(item.metadata.partial_take_profit).breakeven_applied === true);
          const isGroup = box.trades.length > 1;
          const label = isGroup
            ? `${trade.playbook} ${trade.direction} ${box.trades.length} accounts: ${tradeGroupSummary(box.trades)}`
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
                {isGroup ? `${box.trades.length} acct` : `${trade.pnl_r?.toFixed(2) ?? "--"}R`}
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

function filterVisibleM15Triggers(triggers: M15TriggerOverlay[]): M15TriggerOverlay[] {
  return triggers.filter((trigger) => trigger.candidate_id !== null);
}

function scaleEventsForViewport<T>(width: number, events: T[]): T[] {
  return isMobileChartWidth(width) ? [] : events;
}
