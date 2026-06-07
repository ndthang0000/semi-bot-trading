import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { CandlestickSeries, ColorType, createChart, CrosshairMode, LineSeries, LineStyle, } from "lightweight-charts";
import { ArrowDown, ArrowUp } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createManualZone } from "../api/chart";
import { toUnixTime } from "../lib/time";
import { useChartStore } from "../store/chartStore";
const MIN_ZONE_HEIGHT = 0.01;
const MIN_ZONE_DURATION_SECONDS = 60;
const RIGHT_OFFSET_BARS = 18;
const REPLAY_VISIBLE_BARS = 120;
const VERTICAL_FOCUS_BARS = 14;
const SR_EXTENSION_DAYS = 7;
export function TradingChart({ payload, onEntityCreated }) {
    const containerRef = useRef(null);
    const chartRef = useRef(null);
    const candleSeriesRef = useRef(null);
    const scaleAnchorSeriesRef = useRef(null);
    const zigzagSeriesRef = useRef(null);
    const setSelected = useChartStore((state) => state.setSelected);
    const selected = useChartStore((state) => state.selected);
    const showZones = useChartStore((state) => state.showZones);
    const zoneTypeVisibility = useChartStore((state) => state.zoneTypeVisibility);
    const showStructure = useChartStore((state) => state.showStructure);
    const importantZonesOnly = useChartStore((state) => state.importantZonesOnly);
    const maxVisibleZones = useChartStore((state) => state.maxVisibleZones);
    const addEntityKind = useChartStore((state) => state.addEntityKind);
    const zoneFocusRequest = useChartStore((state) => state.zoneFocusRequest);
    const tradeFocusRequest = useChartStore((state) => state.tradeFocusRequest);
    const setAddEntityKind = useChartStore((state) => state.setAddEntityKind);
    const [zoneBoxes, setZoneBoxes] = useState([]);
    const [structureDots, setStructureDots] = useState([]);
    const [swingDots, setSwingDots] = useState([]);
    const [tradeBoxes, setTradeBoxes] = useState([]);
    const [hoveredZoneId, setHoveredZoneId] = useState(null);
    const [drawPreviewZone, setDrawPreviewZone] = useState(null);
    const [drawError, setDrawError] = useState(null);
    const scheduledRecalcRef = useRef(null);
    const interactionRecalcRef = useRef(null);
    const wheelStopRef = useRef(null);
    const draftZoneRef = useRef(null);
    const zoneDragRef = useRef(null);
    const manualDrawRef = useRef(null);
    const payloadRef = useRef(payload);
    const showZonesRef = useRef(showZones);
    const zoneTypeVisibilityRef = useRef(zoneTypeVisibility);
    const showStructureRef = useRef(showStructure);
    const importantZonesOnlyRef = useRef(importantZonesOnly);
    const maxVisibleZonesRef = useRef(maxVisibleZones);
    const addEntityKindRef = useRef(addEntityKind);
    const handledZoneFocusRequestRef = useRef(null);
    const handledTradeFocusRequestRef = useRef(null);
    const drawPreviewZoneRef = useRef(drawPreviewZone);
    const candleDataRef = useRef([]);
    const appliedCandleKeyRef = useRef(null);
    const appliedViewKeyRef = useRef(null);
    const replayPriceRangeRef = useRef(null);
    const lockedViewportRef = useRef(null);
    const lastViewportRef = useRef(null);
    const manualViewportRef = useRef(false);
    const candleData = useMemo(() => normalizeCandleData(payload.layers.candles.map((candle) => ({
        time: toUnixTime(candle.time),
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
    }))), [payload.layers.candles]);
    const candleKey = useMemo(() => {
        const first = payload.layers.candles.at(0)?.time ?? "";
        const last = payload.layers.candles.at(-1)?.time ?? "";
        return `${payload.symbol}:${payload.timeframe}:${payload.layers.candles.length}:${first}:${last}`;
    }, [payload.layers.candles, payload.symbol, payload.timeframe]);
    const viewKey = `${payload.symbol}:${payload.timeframe}:${payload.range.limit}:${payload.range.start_index ?? "latest"}`;
    const setupStateByZone = useMemo(() => buildSetupStateByZone(payload.layers.setup_candidates), [payload.layers.setup_candidates]);
    showZonesRef.current = showZones;
    zoneTypeVisibilityRef.current = zoneTypeVisibility;
    showStructureRef.current = showStructure;
    importantZonesOnlyRef.current = importantZonesOnly;
    maxVisibleZonesRef.current = maxVisibleZones;
    addEntityKindRef.current = addEntityKind;
    drawPreviewZoneRef.current = drawPreviewZone;
    candleDataRef.current = candleData;
    const recalcOverlays = useCallback(() => {
        const chart = chartRef.current;
        const series = candleSeriesRef.current;
        const container = containerRef.current;
        const currentPayload = payloadRef.current;
        const lastCandle = currentPayload.layers.candles.at(-1);
        if (!chart || !series || !container || !lastCandle)
            return;
        const width = container.clientWidth;
        const plotWidth = chartPlotWidth(chart, width);
        const height = container.clientHeight;
        const timeScale = chart.timeScale();
        const draftZone = draftZoneRef.current;
        const previewZone = drawPreviewZoneRef.current;
        const zoneCandidates = (previewZone ? [...currentPayload.layers.zones, previewZone] : currentPayload.layers.zones).filter((zone) => isZoneTypeVisible(zone, zoneTypeVisibilityRef.current));
        const currentSelected = useChartStore.getState().selected;
        const selectedZoneId = currentSelected?.kind === "zone" ? currentSelected.entity.id : null;
        const visibleZoneCandidates = filterVisibleZones(zoneCandidates, lastCandle.close, lastCandle.time, importantZonesOnlyRef.current, maxVisibleZonesRef.current, selectedZoneId);
        const zones = (showZonesRef.current || previewZone)
            ? visibleZoneCandidates.flatMap((zone) => {
                const effectiveZone = draftZone?.id === zone.id ? draftZone : zone;
                const start = zoneStartCoordinate(timeScale, effectiveZone, currentPayload.layers.candles);
                const end = zoneEndCoordinate(chart, timeScale, effectiveZone, currentPayload.layers.candles, lastCandle.time, plotWidth);
                const top = series.priceToCoordinate(effectiveZone.price_high);
                const bottom = series.priceToCoordinate(effectiveZone.price_low);
                if (start === null)
                    return [];
                if (top === null || bottom === null)
                    return [];
                if ((top < 0 && bottom < 0) || (top > height && bottom > height))
                    return [];
                const x1 = start;
                const x2 = end ?? width;
                const left = Math.max(0, Math.min(x1, x2));
                const right = Math.min(plotWidth, Math.max(x1, x2));
                const y1 = Math.max(0, Math.min(top, bottom));
                const y2 = Math.min(height, Math.max(top, bottom));
                if (right <= 0 || left >= plotWidth || y2 <= 0 || y1 >= height)
                    return [];
                return [{ zone: effectiveZone, x: left, y: y1, width: Math.max(2, right - left), height: Math.max(2, y2 - y1) }];
            })
            : [];
        const structurePoints = showStructureRef.current
            ? currentPayload.layers.structure.flatMap((point) => {
                if (!isStructurePointAvailable(point, currentPayload.range.end, currentPayload.replay?.as_of))
                    return [];
                const x = timeScale.timeToCoordinate(toUnixTime(point.time));
                const y = series.priceToCoordinate(point.price);
                if (x === null || y === null)
                    return [];
                return [{ point, x, y }];
            })
            : [];
        const allSwings = structurePoints.flatMap((dot) => {
            const swingType = readSwingType(dot.point);
            if (!swingType)
                return [];
            return [{ ...dot, swingType, label: swingLabel(dot.point, swingType) }];
        });
        const visibleStructurePoints = structurePoints.filter(({ x, y }) => x >= -12 && x <= plotWidth + 12 && y >= -12 && y <= height + 12);
        const visibleSwings = allSwings.filter(({ x, y }) => x >= -12 && x <= plotWidth + 12 && y >= -12 && y <= height + 12);
        const trades = currentPayload.layers.trades.flatMap((trade) => {
            const box = tradeToBox(trade, currentPayload.range.start, currentPayload.range.end, candleDataRef.current, plotWidth, height, timeScale, series);
            return box ? [box] : [];
        });
        setZoneBoxes(zones);
        setStructureDots(visibleStructurePoints.filter((dot) => !readSwingType(dot.point)));
        setSwingDots(visibleSwings);
        setTradeBoxes(trades);
    }, []);
    const scheduleOverlayRecalc = useCallback(() => {
        if (scheduledRecalcRef.current !== null)
            return;
        scheduledRecalcRef.current = requestAnimationFrame(() => {
            scheduledRecalcRef.current = null;
            recalcOverlays();
        });
    }, [recalcOverlays]);
    const startOverlayInteractionSync = useCallback(() => {
        if (interactionRecalcRef.current !== null)
            return;
        const sync = () => {
            recalcOverlays();
            interactionRecalcRef.current = requestAnimationFrame(sync);
        };
        interactionRecalcRef.current = requestAnimationFrame(sync);
    }, [recalcOverlays]);
    const stopOverlayInteractionSync = useCallback(() => {
        if (interactionRecalcRef.current === null)
            return;
        cancelAnimationFrame(interactionRecalcRef.current);
        interactionRecalcRef.current = null;
        scheduleOverlayRecalc();
    }, [scheduleOverlayRecalc]);
    const priceFromClientY = useCallback((clientY) => {
        const container = containerRef.current;
        const series = candleSeriesRef.current;
        if (!container || !series)
            return null;
        const rect = container.getBoundingClientRect();
        const price = series.coordinateToPrice(clientY - rect.top);
        return typeof price === "number" ? price : null;
    }, []);
    const timeFromClientX = useCallback((clientX) => {
        const container = containerRef.current;
        const chart = chartRef.current;
        if (!container || !chart)
            return null;
        const rect = container.getBoundingClientRect();
        const time = chart.timeScale().coordinateToTime(clientX - rect.left);
        return chartTimeToUnix(time);
    }, []);
    const updateDraftZone = useCallback((zone) => {
        lockCurrentViewport(chartRef.current, lockedViewportRef);
        draftZoneRef.current = zone;
        setSelected({ kind: "zone", entity: zone });
        restoreLockedViewport(chartRef.current, lockedViewportRef);
        scheduleOverlayRecalc();
    }, [scheduleOverlayRecalc, setSelected]);
    const updateDrawPreview = useCallback((zone) => {
        drawPreviewZoneRef.current = zone;
        setDrawPreviewZone(zone);
        scheduleOverlayRecalc();
    }, [scheduleOverlayRecalc]);
    const beginManualDraw = useCallback((event) => {
        const kind = addEntityKindRef.current;
        if (!kind)
            return;
        const pointerPrice = priceFromClientY(event.clientY);
        const pointerTime = timeFromClientX(event.clientX);
        if (pointerPrice === null || pointerTime === null)
            return;
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
    }, [priceFromClientY, setSelected, startOverlayInteractionSync, timeFromClientX, updateDrawPreview]);
    const handleManualDrawMove = useCallback((event) => {
        const draw = manualDrawRef.current;
        if (!draw)
            return;
        const pointerPrice = priceFromClientY(event.clientY);
        const pointerTime = timeFromClientX(event.clientX);
        if (pointerPrice === null || pointerTime === null)
            return;
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
            direction: spec.direction,
            detector: "human_manual_v1",
            status: "active",
            source: "human",
            price_low: roundPrice(low),
            price_high: roundPrice(safeHigh),
            visual_start: unixToIso(startTime),
            visual_end: isoForZoneEnd(endTime, lastCandleTime),
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
    }, [priceFromClientY, timeFromClientX, updateDrawPreview]);
    const finishManualDraw = useCallback(async () => {
        const draw = manualDrawRef.current;
        if (!draw)
            return;
        manualDrawRef.current = null;
        stopOverlayInteractionSync();
        const preview = drawPreviewZoneRef.current;
        if (!preview)
            return;
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
                weight: preview.weight,
                confidence: preview.confidence,
                status: "active",
                client_kind: draw.kind,
                no_expiry: true,
                reason: `manual ${manualZoneSpec(draw.kind).label} drawn on chart`,
            });
            updateDrawPreview(null);
            setAddEntityKind(null);
            setSelected({ kind: "zone", entity: created });
            restoreLockedViewport(chartRef.current, lockedViewportRef);
            onEntityCreated();
        }
        catch (err) {
            updateDrawPreview(null);
            setDrawError(err instanceof Error ? err.message : "Could not create entity.");
        }
    }, [onEntityCreated, setAddEntityKind, setSelected, stopOverlayInteractionSync, updateDrawPreview]);
    const beginZoneDrag = useCallback((event, box, mode) => {
        const pointerPrice = priceFromClientY(event.clientY);
        const pointerTime = timeFromClientX(event.clientX);
        if (pointerPrice === null || pointerTime === null)
            return;
        event.preventDefault();
        event.stopPropagation();
        zoneDragRef.current = {
            mode,
            zone: box.zone,
            startPointerPrice: pointerPrice,
            startPointerTime: pointerTime,
            startLow: box.zone.price_low,
            startHigh: box.zone.price_high,
            startVisualStart: box.zone.visual_start,
            startVisualEnd: box.zone.visual_end,
        };
        updateDraftZone(box.zone);
        startOverlayInteractionSync();
    }, [priceFromClientY, startOverlayInteractionSync, timeFromClientX, updateDraftZone]);
    const handleZoneDragMove = useCallback((event) => {
        const drag = zoneDragRef.current;
        if (!drag)
            return;
        const pointerPrice = priceFromClientY(event.clientY);
        const pointerTime = timeFromClientX(event.clientX);
        if (pointerPrice === null || pointerTime === null)
            return;
        event.preventDefault();
        const priceDelta = pointerPrice - drag.startPointerPrice;
        const timeDelta = pointerTime - drag.startPointerTime;
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
            nextVisualEnd = isoForZoneEnd(endTime + timeDelta, lastCandleTime);
        }
        else if (drag.mode === "resize-top") {
            nextHigh = Math.max(pointerPrice, drag.startLow + MIN_ZONE_HEIGHT);
        }
        else if (drag.mode === "resize-bottom") {
            nextLow = Math.min(pointerPrice, drag.startHigh - MIN_ZONE_HEIGHT);
        }
        else if (drag.mode === "resize-left") {
            nextVisualStart = unixToIso(Math.min(pointerTime, endTime - MIN_ZONE_DURATION_SECONDS));
        }
        else {
            nextVisualEnd = isoForZoneEnd(Math.max(pointerTime, startTime + MIN_ZONE_DURATION_SECONDS), lastCandleTime);
        }
        updateDraftZone({
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
        });
    }, [priceFromClientY, timeFromClientX, updateDraftZone]);
    const finishZoneDrag = useCallback(() => {
        if (!zoneDragRef.current)
            return;
        zoneDragRef.current = null;
        stopOverlayInteractionSync();
        scheduleOverlayRecalc();
    }, [scheduleOverlayRecalc, stopOverlayInteractionSync]);
    const clearSelection = useCallback(() => {
        if (addEntityKindRef.current)
            return;
        lockCurrentViewport(chartRef.current, lockedViewportRef);
        draftZoneRef.current = null;
        setSelected(null);
        restoreLockedViewport(chartRef.current, lockedViewportRef);
        scheduleOverlayRecalc();
    }, [scheduleOverlayRecalc, setSelected]);
    const selectStructurePoint = useCallback((point) => {
        lockCurrentViewport(chartRef.current, lockedViewportRef);
        setSelected({ kind: "structure", entity: point });
        restoreLockedViewport(chartRef.current, lockedViewportRef);
        scheduleOverlayRecalc();
    }, [scheduleOverlayRecalc, setSelected]);
    const selectTrade = useCallback((trade) => {
        lockCurrentViewport(chartRef.current, lockedViewportRef);
        setSelected({ kind: "trade", entity: trade });
        restoreLockedViewport(chartRef.current, lockedViewportRef);
        scheduleOverlayRecalc();
    }, [scheduleOverlayRecalc, setSelected]);
    useEffect(() => {
        if (selected?.kind === "zone") {
            draftZoneRef.current = selected.entity;
        }
        else {
            draftZoneRef.current = null;
        }
        scheduleOverlayRecalc();
    }, [scheduleOverlayRecalc, selected]);
    useEffect(() => {
        scheduleOverlayRecalc();
    }, [importantZonesOnly, maxVisibleZones, payload, scheduleOverlayRecalc, showStructure, showZones]);
    useEffect(() => {
        zigzagSeriesRef.current?.setData(buildZigZagSeriesData(payload.layers.structure, payload.range.end, payload.replay?.as_of, showStructure));
    }, [payload.layers.structure, payload.range.end, payload.replay?.as_of, showStructure]);
    useEffect(() => {
        if (!zoneFocusRequest || handledZoneFocusRequestRef.current === zoneFocusRequest.id)
            return;
        handledZoneFocusRequestRef.current = zoneFocusRequest.id;
        focusZoneOnChart(chartRef.current, zoneFocusRequest.zone, payloadRef.current.layers.candles, scheduleOverlayRecalc);
    }, [scheduleOverlayRecalc, zoneFocusRequest]);
    useEffect(() => {
        if (!tradeFocusRequest || handledTradeFocusRequestRef.current === tradeFocusRequest.id)
            return;
        setSelected({ kind: "trade", entity: tradeFocusRequest.trade });
        if (focusTradeOnChart(chartRef.current, tradeFocusRequest.trade, payloadRef.current.layers.candles, scheduleOverlayRecalc)) {
            handledTradeFocusRequestRef.current = tradeFocusRequest.id;
        }
    }, [payload.range.end, payload.range.start, scheduleOverlayRecalc, setSelected, tradeFocusRequest]);
    useEffect(() => {
        const container = containerRef.current;
        if (!container)
            return;
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
        scaleAnchorSeries.setData(buildScaleAnchorData(candleDataRef.current));
        zigzagSeries.setData(buildZigZagSeriesData(payload.layers.structure, payload.range.end, payload.replay?.as_of, showStructureRef.current));
        payloadRef.current = payload;
        appliedCandleKeyRef.current = candleKey;
        appliedViewKeyRef.current = viewKey;
        manualViewportRef.current = false;
        if (payloadRef.current.replay?.enabled) {
            applyReplayTimeViewport(chart, candleDataRef.current, payloadRef.current.range.limit);
            replayPriceRangeRef.current = applyReplayPriceViewport(chart, candleDataRef.current, true);
        }
        else {
            applyInitialViewport(chart, candleDataRef.current, payloadRef.current.range.limit);
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
        if (!chart || !series)
            return;
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
        series.setData(candleData);
        scaleAnchorSeriesRef.current?.setData(buildScaleAnchorData(candleData));
        zigzagSeriesRef.current?.setData(buildZigZagSeriesData(payload.layers.structure, payload.range.end, payload.replay?.as_of, showStructureRef.current));
        payloadRef.current = payload;
        appliedCandleKeyRef.current = candleKey;
        appliedViewKeyRef.current = viewKey;
        if (isReplay) {
            if (previousViewKey !== viewKey || visiblePriceRange === null) {
                manualViewportRef.current = false;
                applyReplayTimeViewport(chart, candleData, payload.range.limit);
                replayPriceRangeRef.current = applyReplayPriceViewport(chart, candleData, true);
            }
            else {
                if (visibleRange) {
                    chart.timeScale().setVisibleLogicalRange(visibleRange);
                }
                chart.priceScale("right").setAutoScale(false);
                chart.priceScale("right").setVisibleRange(visiblePriceRange);
                replayPriceRangeRef.current = visiblePriceRange;
            }
        }
        else if (previousViewKey !== viewKey) {
            lockedViewportRef.current = null;
            manualViewportRef.current = false;
            replayPriceRangeRef.current = null;
            applyInitialViewport(chart, candleData, payload.range.limit);
            replayPriceRangeRef.current = applyInitialPriceViewport(chart, candleData);
        }
        else {
            if (visibleRange) {
                chart.timeScale().setVisibleLogicalRange(visibleRange);
            }
            if (visiblePriceRange) {
                chart.priceScale("right").setVisibleRange(visiblePriceRange);
                replayPriceRangeRef.current = visiblePriceRange;
            }
        }
        if (lockedViewportRef.current) {
            restoreLockedViewport(chart, lockedViewportRef);
        }
        lastViewportRef.current = readCurrentViewport(chart);
        scheduleOverlayRecalc();
    }, [candleData, candleKey, payload.range.limit, payload.range.start_index, payload.replay?.enabled, scheduleOverlayRecalc, viewKey]);
    return (_jsxs("div", { className: "relative h-full min-h-[540px] overflow-hidden bg-[#080b10]", children: [_jsx("div", { ref: containerRef, className: "absolute inset-0", onClick: clearSelection }), addEntityKind ? (_jsx("div", { className: "absolute inset-0 z-40 cursor-crosshair", onClick: (event) => event.stopPropagation(), onPointerDown: beginManualDraw })) : null, addEntityKind ? (_jsxs("div", { className: "pointer-events-none absolute left-4 top-4 z-50 rounded-md border border-cyan-400/40 bg-ink-900/90 px-3 py-2 text-xs text-cyan-100 shadow-lg", children: ["Drag to add ", manualZoneSpec(addEntityKind).label] })) : null, drawError ? (_jsx("div", { className: "pointer-events-none absolute left-4 top-4 z-40 max-w-sm rounded-md border border-rose-500/40 bg-rose-950/90 px-3 py-2 text-xs text-rose-100 shadow-lg", children: drawError })) : null, _jsxs("div", { className: "pointer-events-none absolute inset-0", children: [zoneBoxes.map((box) => {
                        const isSelected = selected?.kind === "zone" && selected.entity.id === box.zone.id;
                        const isHovered = hoveredZoneId === box.zone.id;
                        const setupStatus = setupStateByZone.get(box.zone.id);
                        const zoneClasses = zoneVisualClasses(box.zone);
                        const showLabel = isSelected ||
                            isHovered ||
                            (importantZonesOnly
                                ? box.width > 220 && box.height > 18 && box.zone.weight >= 0.7
                                : box.width > 170 && box.height > 18 && box.zone.weight >= 0.55);
                        return (_jsxs("div", { className: compactClassName(`pointer-events-auto absolute select-none overflow-hidden border transition ${zoneClasses.box} ${box.zone.status === "active" ? "" : "border-dashed opacity-45"} ${setupStatus === "eligible" ? "ring-2 ring-cyan-300/80" : ""} ${setupStatus === "waiting_confirmation" ? "ring-2 ring-yellow-300/70" : ""} ${box.zone.id === "__manual_zone_preview__" ? "z-40 border-dashed ring-1 ring-cyan-200" : ""} ${isSelected || isHovered ? "opacity-100" : "opacity-70"} ${isSelected ? "z-30 cursor-move ring-1 ring-cyan-300" : "z-10 cursor-pointer"}`), style: {
                                left: box.x,
                                top: box.y,
                                width: box.width,
                                height: box.height,
                            }, title: `${box.zone.type} ${box.zone.status} ${box.zone.price_low.toFixed(2)}-${box.zone.price_high.toFixed(2)}`, role: "button", onMouseEnter: () => setHoveredZoneId(box.zone.id), onMouseLeave: () => setHoveredZoneId(null), onClick: (event) => {
                                event.preventDefault();
                                event.stopPropagation();
                                if (box.zone.id !== "__manual_zone_preview__" && !isSelected) {
                                    updateDraftZone(box.zone);
                                }
                            }, onPointerDown: (event) => {
                                event.preventDefault();
                                event.stopPropagation();
                                if (box.zone.id === "__manual_zone_preview__")
                                    return;
                                if (isSelected) {
                                    beginZoneDrag(event, box, "move");
                                }
                            }, children: [isSelected ? (_jsxs(_Fragment, { children: [_jsx("button", { className: "absolute left-0 top-0 z-40 h-2.5 w-full cursor-ns-resize border-t border-cyan-200/90 bg-cyan-300/20", title: "Drag to resize zone high", type: "button", onClick: (event) => event.stopPropagation(), onPointerDown: (event) => beginZoneDrag(event, box, "resize-top") }), _jsx("button", { className: "absolute bottom-0 left-0 z-40 h-2.5 w-full cursor-ns-resize border-b border-cyan-200/90 bg-cyan-300/20", title: "Drag to resize zone low", type: "button", onClick: (event) => event.stopPropagation(), onPointerDown: (event) => beginZoneDrag(event, box, "resize-bottom") }), _jsx("button", { className: "absolute left-0 top-0 z-50 h-full w-2.5 cursor-ew-resize border-l border-cyan-200/90 bg-cyan-300/20", title: "Drag to resize zone start", type: "button", onClick: (event) => event.stopPropagation(), onPointerDown: (event) => beginZoneDrag(event, box, "resize-left") }), _jsx("button", { className: "absolute right-0 top-0 z-50 h-full w-2.5 cursor-ew-resize border-r border-cyan-200/90 bg-cyan-300/20", title: "Drag to resize zone end", type: "button", onClick: (event) => event.stopPropagation(), onPointerDown: (event) => beginZoneDrag(event, box, "resize-right") })] })) : null, showLabel ? (_jsxs("span", { className: `absolute left-1 top-1 max-w-[220px] truncate rounded px-1.5 py-0.5 text-[10px] font-medium ${zoneClasses.label}`, children: [zoneDisplayName(box.zone), " \u00B7 ", box.zone.weight.toFixed(2), " \u00B7 ", formatZoneDate(box.zone.visual_start)] })) : null] }, box.zone.id));
                    }), swingDots.map((dot) => {
                        const isHigh = dot.swingType === "high";
                        const isSelected = selected?.kind === "structure" && selected.entity.id === dot.point.id;
                        return (_jsxs("button", { className: `pointer-events-auto absolute z-30 flex h-5 w-5 -translate-x-1/2 items-center justify-center rounded-full border shadow-[0_0_6px_rgba(0,0,0,0.55)] transition hover:scale-110 ${isHigh
                                ? "-translate-y-[calc(100%+4px)] border-rose-300/80 bg-rose-950/90 text-rose-300"
                                : "translate-y-[4px] border-emerald-300/80 bg-emerald-950/90 text-emerald-300"} ${isSelected ? "ring-1 ring-cyan-200" : ""}`, style: { left: dot.x, top: dot.y }, title: `${isHigh ? "Swing High" : "Swing Low"} ${dot.point.type} ${dot.point.price.toFixed(2)}`, type: "button", onClick: () => selectStructurePoint(dot.point), children: [isHigh ? _jsx(ArrowDown, { size: 14, strokeWidth: 3 }) : _jsx(ArrowUp, { size: 14, strokeWidth: 3 }), _jsx("span", { className: "sr-only", children: dot.label })] }, dot.point.id));
                    }), structureDots.map((dot) => (_jsx("button", { className: `pointer-events-auto absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border border-slate-950 ${dot.point.direction === "down" || ["LH", "LL"].includes(dot.point.type) ? "bg-rose-300" : "bg-emerald-300"}`, style: { left: dot.x, top: dot.y }, title: `${dot.point.type} ${dot.point.price.toFixed(2)}`, type: "button", onClick: () => selectStructurePoint(dot.point) }, dot.point.id))), tradeBoxes.map((box) => {
                        const trade = box.trade;
                        const isLong = trade.direction === "long" || trade.side === "buy";
                        const isSelected = selected?.kind === "trade" && selected.entity.id === trade.id;
                        const label = `${trade.playbook} ${trade.direction} ${trade.status} ${trade.pnl_r?.toFixed(2) ?? "--"}R`;
                        return (_jsxs("button", { className: `pointer-events-auto absolute z-[35] overflow-hidden border border-dashed bg-transparent text-left transition hover:brightness-125 ${isSelected ? "border-white ring-1 ring-cyan-200/80" : "border-white/60"}`, style: {
                                left: box.x,
                                top: box.y,
                                width: box.width,
                                height: box.height,
                                boxShadow: isSelected
                                    ? "0 0 14px rgba(34,211,238,0.48)"
                                    : "0 0 10px rgba(56,189,248,0.25)",
                            }, title: label, type: "button", onClick: (event) => {
                                event.preventDefault();
                                event.stopPropagation();
                                selectTrade(trade);
                            }, children: [_jsx("span", { className: "absolute border border-dashed border-cyan-200/90 bg-cyan-400/22", style: {
                                        left: box.profit.x - box.x,
                                        top: box.profit.y - box.y,
                                        width: box.profit.width,
                                        height: box.profit.height,
                                        boxShadow: "inset 0 0 16px rgba(34,211,238,0.25)",
                                    } }), _jsx("span", { className: "absolute border border-dashed border-fuchsia-200/90 bg-fuchsia-500/24", style: {
                                        left: box.loss.x - box.x,
                                        top: box.loss.y - box.y,
                                        width: box.loss.width,
                                        height: box.loss.height,
                                        boxShadow: "inset 0 0 16px rgba(217,70,239,0.25)",
                                    } }), _jsxs("span", { className: `absolute left-1 top-1 rounded border px-1.5 py-0.5 text-[10px] font-black tracking-wide shadow-lg ${isLong
                                        ? "border-cyan-200/90 bg-cyan-950/95 text-cyan-100"
                                        : "border-fuchsia-200/90 bg-fuchsia-950/95 text-fuchsia-100"}`, children: [isLong ? "LONG" : "SHORT", " \u00B7 ", trade.pnl_r?.toFixed(2) ?? "--", "R"] })] }, trade.id));
                    })] })] }));
}
function manualZoneSpec(kind) {
    const specs = {
        support: { label: "Support", zoneType: "support", direction: "bullish", weight: 0.8, confidence: 1 },
        resistance: { label: "Resistance", zoneType: "resistance", direction: "bearish", weight: 0.8, confidence: 1 },
        demand_order_block: { label: "Demand OB", zoneType: "order_block", direction: "bullish", weight: 0.78, confidence: 1 },
        supply_order_block: { label: "Supply OB", zoneType: "order_block", direction: "bearish", weight: 0.78, confidence: 1 },
        bullish_fvg: { label: "Bullish FVG", zoneType: "fvg", direction: "bullish", weight: 0.72, confidence: 1 },
        bearish_fvg: { label: "Bearish FVG", zoneType: "fvg", direction: "bearish", weight: 0.72, confidence: 1 },
        consolidation: { label: "Consolidation", zoneType: "consolidation", direction: "neutral", weight: 0.65, confidence: 1 },
        buy_side_liquidity: { label: "Buy-side Liquidity", zoneType: "liquidity_pool", direction: "neutral", weight: 0.68, confidence: 1 },
        sell_side_liquidity: { label: "Sell-side Liquidity", zoneType: "liquidity_pool", direction: "neutral", weight: 0.68, confidence: 1 },
    };
    return specs[kind];
}
function zoneDisplayName(zone) {
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
    if (zone.type === "liquidity_pool")
        return "Liquidity Pool";
    return zone.type;
}
function tradeToBox(trade, rangeStart, rangeEnd, candles, chartWidth, chartHeight, timeScale, series) {
    const entry = trade.entry_price;
    const stop = trade.stop_loss;
    const takeProfit = firstTakeProfitPrice(trade.take_profit);
    if (entry === null || stop === null || takeProfit === null || !trade.opened_at)
        return null;
    const startX = chartXForTradeTime(timeScale, trade.opened_at, rangeStart, rangeEnd, candles, chartWidth);
    const endX = chartXForTradeTime(timeScale, trade.closed_at ?? rangeEnd, rangeStart, rangeEnd, candles, chartWidth);
    if (startX === null || endX === null)
        return null;
    const x1 = Math.min(startX, endX);
    const x2 = Math.max(startX, endX);
    const clippedX1 = clampNumber(x1, 0, chartWidth);
    const clippedX2 = clampNumber(x2, 0, chartWidth);
    if (clippedX2 - clippedX1 < 2)
        return null;
    const entryY = series.priceToCoordinate(entry);
    const stopY = series.priceToCoordinate(stop);
    const takeProfitY = series.priceToCoordinate(takeProfit);
    if (entryY === null || stopY === null || takeProfitY === null)
        return null;
    const profit = clipBoxRect({
        x: clippedX1,
        y: Math.min(entryY, takeProfitY),
        width: clippedX2 - clippedX1,
        height: Math.abs(takeProfitY - entryY),
    }, chartWidth, chartHeight);
    const loss = clipBoxRect({
        x: clippedX1,
        y: Math.min(entryY, stopY),
        width: clippedX2 - clippedX1,
        height: Math.abs(stopY - entryY),
    }, chartWidth, chartHeight);
    if (!profit || !loss)
        return null;
    const x = Math.min(profit.x, loss.x);
    const y = Math.min(profit.y, loss.y);
    const right = Math.max(profit.x + profit.width, loss.x + loss.width);
    const bottom = Math.max(profit.y + profit.height, loss.y + loss.height);
    return {
        trade,
        x,
        y,
        width: Math.max(2, right - x),
        height: Math.max(2, bottom - y),
        profit,
        loss,
    };
}
function chartPlotWidth(chart, containerWidth) {
    const priceScaleWidth = chart.priceScale("right").width();
    return Math.max(0, containerWidth - priceScaleWidth);
}
function firstTakeProfitPrice(values) {
    const first = values.at(0);
    if (typeof first === "number")
        return first;
    if (first && typeof first.price === "number")
        return first.price;
    return null;
}
function chartXForTradeTime(timeScale, time, rangeStart, rangeEnd, candles, chartWidth) {
    const x = timeScale.timeToCoordinate(toUnixTime(time));
    if (x !== null)
        return x;
    const timestamp = toUnixTime(time);
    const interpolated = interpolateChartX(timeScale, timestamp, candles);
    if (interpolated !== null)
        return interpolated;
    const timeMs = timestamp * 1000;
    const startMs = Date.parse(rangeStart);
    const endMs = Date.parse(rangeEnd);
    if (Number.isNaN(timeMs) || Number.isNaN(startMs) || Number.isNaN(endMs))
        return null;
    if (timeMs <= startMs)
        return 0;
    if (timeMs >= endMs)
        return chartWidth;
    return null;
}
function interpolateChartX(timeScale, timestamp, candles) {
    if (candles.length < 2)
        return null;
    const first = candles[0];
    const last = candles[candles.length - 1];
    if (timestamp <= first.time)
        return timeScale.timeToCoordinate(first.time);
    if (timestamp >= last.time)
        return timeScale.timeToCoordinate(last.time);
    for (let index = 1; index < candles.length; index += 1) {
        const previous = candles[index - 1];
        const next = candles[index];
        if (timestamp < previous.time || timestamp > next.time)
            continue;
        const previousX = timeScale.timeToCoordinate(previous.time);
        const nextX = timeScale.timeToCoordinate(next.time);
        if (previousX === null || nextX === null || next.time === previous.time)
            return null;
        const ratio = (timestamp - previous.time) / (next.time - previous.time);
        return previousX + (nextX - previousX) * ratio;
    }
    return null;
}
function clipBoxRect(rect, chartWidth, chartHeight) {
    const x1 = clampNumber(rect.x, 0, chartWidth);
    const y1 = clampNumber(rect.y, 0, chartHeight);
    const x2 = clampNumber(rect.x + rect.width, 0, chartWidth);
    const y2 = clampNumber(rect.y + rect.height, 0, chartHeight);
    if (x2 - x1 < 2 || y2 - y1 < 2)
        return null;
    return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
}
function clampNumber(value, min, max) {
    return Math.min(Math.max(value, min), max);
}
function zoneVisualClasses(zone) {
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
function isAddEntityKind(value) {
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
function compactClassName(value) {
    return value.replace(/\s+/g, " ").trim();
}
function readSwingType(point) {
    const value = point.metadata.swing_type;
    return value === "high" || value === "low" ? value : null;
}
function isStructurePointAvailable(point, rangeEnd, replayAsOf) {
    const upperBound = replayAsOf ?? rangeEnd;
    if (point.time > upperBound)
        return false;
    const confirmedAt = point.metadata.confirmed_at;
    return typeof confirmedAt !== "string" || confirmedAt <= upperBound;
}
function swingLabel(point, swingType) {
    const metadataLabel = point.metadata.structure_label;
    if (typeof metadataLabel === "string" && metadataLabel.length > 0) {
        return metadataLabel;
    }
    if (point.type === "swing_high")
        return "SH";
    if (point.type === "swing_low")
        return "SL";
    return swingType === "high" ? "SH" : "SL";
}
function buildZigZagSeriesData(points, rangeEnd, replayAsOf, enabled) {
    if (!enabled)
        return [];
    const swings = points
        .filter((point) => isStructurePointAvailable(point, rangeEnd, replayAsOf))
        .flatMap((point) => {
        const swingType = readSwingType(point);
        return swingType ? [{ point, swingType }] : [];
    });
    const collapsed = [];
    for (const swing of swings.slice().sort((a, b) => toUnixTime(a.point.time) - toUnixTime(b.point.time))) {
        const previous = collapsed.at(-1);
        if (!previous || previous.swingType !== swing.swingType) {
            collapsed.push(swing);
            continue;
        }
        const shouldReplace = swing.swingType === "high" ? swing.point.price > previous.point.price : swing.point.price < previous.point.price;
        if (shouldReplace) {
            collapsed[collapsed.length - 1] = swing;
        }
    }
    return normalizeLineSeriesData(collapsed.map((swing) => ({ time: toUnixTime(swing.point.time), value: swing.point.price })));
}
function normalizeCandleData(candles) {
    const byTime = new Map();
    for (const candle of candles) {
        byTime.set(Number(candle.time), candle);
    }
    return Array.from(byTime.values()).sort((a, b) => Number(a.time) - Number(b.time));
}
function normalizeLineSeriesData(items) {
    const byTime = new Map();
    for (const item of items) {
        byTime.set(Number(item.time), item);
    }
    return Array.from(byTime.values()).sort((a, b) => Number(a.time) - Number(b.time));
}
function buildSetupStateByZone(candidates) {
    const rank = {
        eligible: 4,
        waiting_confirmation: 3,
        watching: 2,
        blocked: 1,
        expired: 0,
    };
    const result = new Map();
    for (const candidate of candidates) {
        const zoneId = candidate.primary_zone_id;
        if (!zoneId)
            continue;
        const current = result.get(zoneId);
        if (!current || rank[candidate.status] > rank[current]) {
            result.set(zoneId, candidate.status);
        }
    }
    return result;
}
function roundPrice(price) {
    return Math.round(price * 100) / 100;
}
function filterVisibleZones(zones, currentPrice, lastCandleTime, importantOnly, maxZones, selectedZoneId) {
    if (!importantOnly)
        return zones;
    const pinned = zones.filter((zone) => zone.id === selectedZoneId || zone.id === "__manual_zone_preview__");
    const pinnedIds = new Set(pinned.map((zone) => zone.id));
    const ranked = zones
        .filter((zone) => !pinnedIds.has(zone.id))
        .map((zone) => ({ zone, score: zoneImportanceScore(zone, currentPrice, lastCandleTime) }))
        .sort((a, b) => b.score - a.score);
    const selected = [...pinned];
    const targetCount = Math.max(maxZones, pinned.length);
    for (const candidate of ranked) {
        if (selected.length >= targetCount)
            break;
        if (candidate.zone.weight < 0.45 && !isHumanZone(candidate.zone))
            continue;
        const overlapsBetterZone = selected.some((zone) => !isHumanZone(candidate.zone) && zone.id !== selectedZoneId && zonesVisuallyOverlap(zone, candidate.zone));
        if (!overlapsBetterZone) {
            selected.push(candidate.zone);
        }
    }
    if (selected.length < targetCount) {
        const selectedIds = new Set(selected.map((zone) => zone.id));
        for (const candidate of ranked) {
            if (selected.length >= targetCount)
                break;
            if (selectedIds.has(candidate.zone.id))
                continue;
            selected.push(candidate.zone);
            selectedIds.add(candidate.zone.id);
        }
    }
    return selected;
}
function isZoneTypeVisible(zone, visibility) {
    if (zone.id === "__manual_zone_preview__")
        return true;
    if (zone.type === "support")
        return visibility.support;
    if (zone.type === "resistance")
        return visibility.resistance;
    if (zone.type === "order_block")
        return visibility.order_block;
    if (zone.type === "fvg")
        return visibility.fvg;
    if (zone.type === "liquidity_pool")
        return visibility.liquidity_pool;
    if (zone.type === "consolidation")
        return visibility.consolidation;
    return true;
}
function focusZoneOnChart(chart, zone, candles, scheduleOverlayRecalc) {
    if (!chart || candles.length === 0)
        return;
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
    }
    else {
        requestAnimationFrame(scheduleOverlayRecalc);
    }
}
function focusTradeOnChart(chart, trade, candles, scheduleOverlayRecalc) {
    if (!chart || candles.length === 0 || !trade.opened_at)
        return false;
    const openedTime = toUnixTime(trade.opened_at);
    const firstTime = toUnixTime(candles[0].time);
    const lastTime = toUnixTime(candles[candles.length - 1].time);
    if (openedTime < firstTime || openedTime > lastTime)
        return false;
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
    }
    else {
        requestAnimationFrame(scheduleOverlayRecalc);
    }
    return true;
}
function zoneFocusTime(zone) {
    const candidates = [zone.detected_at, zone.valid_from, zone.visual_start, zone.visual_end].flatMap((value) => {
        if (!value)
            return [];
        const time = toUnixTime(value);
        return Number.isFinite(time) ? [time] : [];
    });
    return candidates[0] ?? 0;
}
function nearestCandleIndex(candles, targetTime) {
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
function zoneImportanceScore(zone, currentPrice, lastCandleTime) {
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
function zonesVisuallyOverlap(a, b) {
    if (a.type !== b.type || a.direction !== b.direction)
        return false;
    const overlap = Math.min(a.price_high, b.price_high) - Math.max(a.price_low, b.price_low);
    if (overlap <= 0)
        return false;
    const smallerWidth = Math.max(Math.min(a.price_high - a.price_low, b.price_high - b.price_low), 0.01);
    return overlap / smallerWidth >= 0.45;
}
function isHumanZone(zone) {
    return zone.source === "human" || zone.metadata.human_created === true;
}
function zoneStartCoordinate(timeScale, zone, candles) {
    const startUnix = toUnixTime(zone.visual_start);
    const firstCandle = candles.at(0);
    const lastCandle = candles.at(-1);
    if (!firstCandle || !lastCandle)
        return null;
    // Do not fake an old zone start at the left edge. If the real creation time
    // is outside the loaded candle window, hide it until that creation point is visible.
    if (startUnix < toUnixTime(firstCandle.time) || startUnix > toUnixTime(lastCandle.time)) {
        return null;
    }
    const directCoordinate = timeScale.timeToCoordinate(startUnix);
    if (directCoordinate !== null)
        return directCoordinate;
    const candleIndex = candles.findIndex((candle) => toUnixTime(candle.time) >= startUnix);
    if (candleIndex < 0)
        return null;
    return timeScale.logicalToCoordinate(candleIndex);
}
function zoneEndCoordinate(chart, timeScale, zone, candles, lastCandleTime, width) {
    if (zone.visual_end) {
        return projectedTimeCoordinate(timeScale, candles, toUnixTime(zone.visual_end));
    }
    if (zone.status === "active" && isSupportResistanceZone(zone)) {
        const lastUnix = toUnixTime(lastCandleTime);
        const futureUnix = lastUnix + SR_EXTENSION_DAYS * 86_400;
        const futureCoordinate = projectedTimeCoordinate(timeScale, candles, futureUnix);
        if (futureCoordinate !== null)
            return futureCoordinate;
        const lastCoordinate = timeScale.timeToCoordinate(lastUnix);
        const previousCandle = candles.at(-2);
        const previousCoordinate = previousCandle ? timeScale.timeToCoordinate(toUnixTime(previousCandle.time)) : null;
        const spacing = lastCoordinate !== null && previousCoordinate !== null ? Math.max(lastCoordinate - previousCoordinate, 1) : 8;
        const timeframeSeconds = candles.length >= 2 ? Math.max(lastUnix - toUnixTime(candles.at(-2)?.time ?? lastCandleTime), 1) : 3600;
        const futureBars = (SR_EXTENSION_DAYS * 86_400) / timeframeSeconds;
        return lastCoordinate !== null ? lastCoordinate + spacing * futureBars : width;
    }
    return timeScale.timeToCoordinate(toUnixTime(lastCandleTime));
}
function projectedTimeCoordinate(timeScale, candles, targetTime) {
    const directCoordinate = timeScale.timeToCoordinate(targetTime);
    if (directCoordinate !== null)
        return directCoordinate;
    if (candles.length === 0)
        return null;
    const candleTimes = candles.map((candle) => toUnixTime(candle.time));
    const targetUnix = Number(targetTime);
    let anchorIndex = -1;
    for (let index = candleTimes.length - 1; index >= 0; index -= 1) {
        if (Number(candleTimes[index]) <= targetUnix) {
            anchorIndex = index;
            break;
        }
    }
    if (anchorIndex < 0)
        anchorIndex = 0;
    const anchorCoordinate = timeScale.timeToCoordinate(candleTimes[anchorIndex]);
    if (anchorCoordinate === null)
        return null;
    const nextIndex = Math.min(anchorIndex + 1, candles.length - 1);
    const previousIndex = Math.max(anchorIndex - 1, 0);
    const neighborIndex = nextIndex !== anchorIndex ? nextIndex : previousIndex;
    if (neighborIndex === anchorIndex)
        return anchorCoordinate;
    const neighborCoordinate = timeScale.timeToCoordinate(candleTimes[neighborIndex]);
    if (neighborCoordinate === null)
        return anchorCoordinate;
    const timeDelta = Number(candleTimes[neighborIndex]) - Number(candleTimes[anchorIndex]);
    if (timeDelta === 0)
        return anchorCoordinate;
    const pixelsPerSecond = (neighborCoordinate - anchorCoordinate) / timeDelta;
    return anchorCoordinate + (targetUnix - Number(candleTimes[anchorIndex])) * pixelsPerSecond;
}
function isSupportResistanceZone(zone) {
    return zone.type === "support" || zone.type === "resistance";
}
function lockCurrentViewport(chart, targetRef) {
    if (!chart)
        return;
    targetRef.current = readCurrentViewport(chart);
}
function restoreLockedViewport(chart, targetRef) {
    if (!chart || !targetRef.current)
        return;
    restoreViewport(chart, targetRef.current);
    requestAnimationFrame(() => {
        restoreViewport(chart, targetRef.current);
        requestAnimationFrame(() => restoreViewport(chart, targetRef.current));
    });
    window.setTimeout(() => restoreViewport(chart, targetRef.current), 80);
}
function readCurrentViewport(chart) {
    return {
        logicalRange: chart.timeScale().getVisibleLogicalRange(),
        priceRange: chart.priceScale("right").getVisibleRange(),
    };
}
function restoreViewport(chart, viewport) {
    if (!viewport)
        return;
    if (viewport.logicalRange) {
        chart.timeScale().setVisibleLogicalRange(viewport.logicalRange);
    }
    if (viewport.priceRange) {
        chart.priceScale("right").setAutoScale(false);
        chart.priceScale("right").setVisibleRange(viewport.priceRange);
    }
}
function applyInitialViewport(chart, candles, requestedBars) {
    if (candles.length === 0)
        return;
    const visibleBars = Math.min(candles.length, Math.max(50, requestedBars));
    const to = Math.max(candles.length - 1 + RIGHT_OFFSET_BARS, 0);
    const from = Math.max(0, to - visibleBars);
    chart.timeScale().setVisibleLogicalRange({ from, to });
}
function applyReplayTimeViewport(chart, candles, requestedBars) {
    if (candles.length === 0)
        return;
    const visibleBars = Math.min(Math.max(REPLAY_VISIBLE_BARS, requestedBars), 220);
    const to = candles.length - 1 + RIGHT_OFFSET_BARS;
    const from = to - visibleBars;
    chart.timeScale().setVisibleLogicalRange({ from, to });
}
function applyReplayPriceViewport(chart, candles, reset) {
    if (candles.length === 0)
        return null;
    chart.priceScale("right").setAutoScale(false);
    const nextRange = reset ? buildReplayPriceRange(candles) : chart.priceScale("right").getVisibleRange() ?? buildReplayPriceRange(candles);
    chart.priceScale("right").setVisibleRange(nextRange);
    return nextRange;
}
function applyInitialPriceViewport(chart, candles) {
    if (candles.length === 0)
        return null;
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
function buildReplayPriceRange(candles) {
    return buildFocusedPriceRange(candles, {
        focusBars: VERTICAL_FOCUS_BARS,
        averageRangeMultiplier: 6,
        priceMultiplier: 0.0075,
        minimumAbsoluteRange: 20,
        paddingMultiplier: 1.18,
    });
}
function buildFocusedPriceRange(candles, options) {
    const last = candles.at(-1);
    if (!last)
        return { from: 0, to: 1 };
    const focusCandles = candles.slice(-options.focusBars);
    const high = Math.max(...focusCandles.map((candle) => candle.high), last.close);
    const low = Math.min(...focusCandles.map((candle) => candle.low), last.close);
    const averageRange = focusCandles.reduce((sum, candle) => sum + Math.max(candle.high - candle.low, 0), 0) / Math.max(focusCandles.length, 1);
    const minimumHalfRange = Math.max(averageRange * options.averageRangeMultiplier, last.close * options.priceMultiplier, options.minimumAbsoluteRange);
    const halfRange = Math.max(high - last.close, last.close - low, minimumHalfRange) * options.paddingMultiplier;
    return {
        from: last.close - halfRange,
        to: last.close + halfRange,
    };
}
function buildScaleAnchorData(candles) {
    const last = candles.at(-1);
    if (!last)
        return [];
    const focusCandles = candles.slice(-96);
    const high = Math.max(...focusCandles.map((candle) => candle.high), last.close);
    const low = Math.min(...focusCandles.map((candle) => candle.low), last.close);
    const averageRange = focusCandles.reduce((sum, candle) => sum + Math.max(candle.high - candle.low, 0), 0) / Math.max(focusCandles.length, 1);
    const minimumHalfRange = Math.max(averageRange * 5, last.close * 0.0045, 1);
    const halfRange = Math.max(high - last.close, last.close - low, minimumHalfRange) * 1.08;
    const previousTime = candles.at(-2)?.time ?? (last.time - 1);
    return [
        { time: previousTime, value: last.close + halfRange },
        { time: last.time, value: last.close - halfRange },
    ];
}
function chartTimeToUnix(time) {
    if (typeof time === "number")
        return time;
    if (typeof time === "string") {
        const parsed = Date.parse(time);
        return Number.isNaN(parsed) ? null : Math.floor(parsed / 1000);
    }
    if (time && typeof time === "object" && "year" in time && "month" in time && "day" in time) {
        const businessDay = time;
        return Math.floor(Date.UTC(businessDay.year, businessDay.month - 1, businessDay.day) / 1000);
    }
    return null;
}
function unixToIso(timestamp) {
    return new Date(Math.round(timestamp) * 1000).toISOString().replace(".000Z", "+00:00");
}
function isoForZoneEnd(timestamp, lastCandleTime) {
    if (!lastCandleTime)
        return unixToIso(timestamp);
    const lastTime = toUnixTime(lastCandleTime);
    if (timestamp >= lastTime)
        return null;
    return unixToIso(timestamp);
}
function formatZoneDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime()))
        return "--";
    return `${String(date.getDate()).padStart(2, "0")}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}
