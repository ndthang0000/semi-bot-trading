import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
import { CandlestickSeries, ColorType, createChart, CrosshairMode, LineSeries, LineStyle, } from "lightweight-charts";
import { ArrowDown, ArrowUp } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toUnixTime } from "../lib/time";
import { useChartStore } from "../store/chartStore";
const MIN_ZONE_HEIGHT = 0.01;
const MIN_ZONE_DURATION_SECONDS = 60;
const RIGHT_OFFSET_BARS = 18;
const REPLAY_VISIBLE_BARS = 120;
const VERTICAL_FOCUS_BARS = 14;
export function TradingChart({ payload }) {
    const containerRef = useRef(null);
    const chartRef = useRef(null);
    const candleSeriesRef = useRef(null);
    const scaleAnchorSeriesRef = useRef(null);
    const setSelected = useChartStore((state) => state.setSelected);
    const selected = useChartStore((state) => state.selected);
    const showZones = useChartStore((state) => state.showZones);
    const showStructure = useChartStore((state) => state.showStructure);
    const [zoneBoxes, setZoneBoxes] = useState([]);
    const [structureDots, setStructureDots] = useState([]);
    const [swingDots, setSwingDots] = useState([]);
    const [zigzagPoints, setZigzagPoints] = useState([]);
    const [hoveredZoneId, setHoveredZoneId] = useState(null);
    const scheduledRecalcRef = useRef(null);
    const interactionRecalcRef = useRef(null);
    const wheelStopRef = useRef(null);
    const draftZoneRef = useRef(null);
    const zoneDragRef = useRef(null);
    const payloadRef = useRef(payload);
    const showZonesRef = useRef(showZones);
    const showStructureRef = useRef(showStructure);
    const candleDataRef = useRef([]);
    const appliedCandleKeyRef = useRef(null);
    const appliedViewKeyRef = useRef(null);
    const replayPriceRangeRef = useRef(null);
    const candleData = useMemo(() => payload.layers.candles.map((candle) => ({
        time: toUnixTime(candle.time),
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
    })), [payload.layers.candles]);
    const candleKey = useMemo(() => {
        const first = payload.layers.candles.at(0)?.time ?? "";
        const last = payload.layers.candles.at(-1)?.time ?? "";
        return `${payload.symbol}:${payload.timeframe}:${payload.layers.candles.length}:${first}:${last}`;
    }, [payload.layers.candles, payload.symbol, payload.timeframe]);
    const viewKey = `${payload.symbol}:${payload.timeframe}:${payload.range.limit}`;
    payloadRef.current = payload;
    showZonesRef.current = showZones;
    showStructureRef.current = showStructure;
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
        const height = container.clientHeight;
        const timeScale = chart.timeScale();
        const draftZone = draftZoneRef.current;
        const zones = showZonesRef.current
            ? currentPayload.layers.zones.flatMap((zone) => {
                const effectiveZone = draftZone?.id === zone.id ? draftZone : zone;
                const start = timeScale.timeToCoordinate(toUnixTime(effectiveZone.visual_start));
                const end = timeScale.timeToCoordinate(toUnixTime(effectiveZone.visual_end ?? lastCandle.time));
                const top = series.priceToCoordinate(effectiveZone.price_high);
                const bottom = series.priceToCoordinate(effectiveZone.price_low);
                if (top === null || bottom === null)
                    return [];
                if ((top < 0 && bottom < 0) || (top > height && bottom > height))
                    return [];
                const x1 = start ?? 0;
                const x2 = end ?? width;
                const left = Math.max(0, Math.min(x1, x2));
                const right = Math.min(width, Math.max(x1, x2));
                const y1 = Math.max(0, Math.min(top, bottom));
                const y2 = Math.min(height, Math.max(top, bottom));
                if (right <= 0 || left >= width || y2 <= 0 || y1 >= height)
                    return [];
                return [{ zone: effectiveZone, x: left, y: y1, width: Math.max(2, right - left), height: Math.max(2, y2 - y1) }];
            })
            : [];
        const structurePoints = showStructureRef.current
            ? currentPayload.layers.structure.flatMap((point) => {
                const x = timeScale.timeToCoordinate(toUnixTime(point.time));
                const y = series.priceToCoordinate(point.price);
                if (x === null || y === null)
                    return [];
                return [{ point, x, y }];
            })
            : [];
        const visibleStructurePoints = structurePoints.filter(({ x, y }) => x >= -12 && x <= width + 12 && y >= -12 && y <= height + 12);
        const swings = visibleStructurePoints.flatMap((dot) => {
            const swingType = readSwingType(dot.point);
            if (!swingType)
                return [];
            return [{ ...dot, swingType, label: swingLabel(dot.point, swingType) }];
        });
        const zigzag = buildZigZagPoints(swings);
        setZoneBoxes(zones);
        setStructureDots(visibleStructurePoints.filter((dot) => !readSwingType(dot.point)));
        setSwingDots(swings);
        setZigzagPoints(zigzag);
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
        draftZoneRef.current = zone;
        setSelected({ kind: "zone", entity: zone });
        scheduleOverlayRecalc();
    }, [scheduleOverlayRecalc, setSelected]);
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
        draftZoneRef.current = null;
        setSelected(null);
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
    }, [payload, scheduleOverlayRecalc, showStructure, showZones]);
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
            rightPriceScale: {
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
            autoscaleInfoProvider: () => buildCenteredAutoscale(candleDataRef.current, chart.timeScale().getVisibleLogicalRange()),
        });
        const scaleAnchorSeries = chart.addSeries(LineSeries, {
            color: "rgba(0, 0, 0, 0)",
            crosshairMarkerVisible: false,
            lastValueVisible: false,
            priceLineVisible: false,
        });
        chartRef.current = chart;
        candleSeriesRef.current = candleSeries;
        scaleAnchorSeriesRef.current = scaleAnchorSeries;
        candleSeries.setData(candleDataRef.current);
        scaleAnchorSeries.setData(buildScaleAnchorData(candleDataRef.current));
        appliedCandleKeyRef.current = candleKey;
        appliedViewKeyRef.current = viewKey;
        if (payloadRef.current.replay?.enabled) {
            applyReplayTimeViewport(chart, candleDataRef.current, payloadRef.current.range.limit);
            replayPriceRangeRef.current = applyReplayPriceViewport(chart, candleDataRef.current, true);
        }
        else {
            applyInitialViewport(chart, candleDataRef.current, payloadRef.current.range.limit);
            chart.priceScale("right").setAutoScale(true);
        }
        scheduleOverlayRecalc();
        const resizeObserver = new ResizeObserver(scheduleOverlayRecalc);
        resizeObserver.observe(container);
        chart.timeScale().subscribeVisibleTimeRangeChange(scheduleOverlayRecalc);
        chart.timeScale().subscribeVisibleLogicalRangeChange(scheduleOverlayRecalc);
        const syncDuringPointerMove = () => {
            scheduleOverlayRecalc();
        };
        const syncDuringWheel = () => {
            scheduleOverlayRecalc();
            startOverlayInteractionSync();
            if (wheelStopRef.current !== null) {
                window.clearTimeout(wheelStopRef.current);
            }
            wheelStopRef.current = window.setTimeout(() => {
                wheelStopRef.current = null;
                stopOverlayInteractionSync();
            }, 120);
        };
        container.addEventListener("pointerdown", startOverlayInteractionSync);
        container.addEventListener("pointermove", syncDuringPointerMove);
        container.addEventListener("wheel", syncDuringWheel, { passive: true });
        window.addEventListener("pointermove", syncDuringPointerMove);
        window.addEventListener("pointerup", stopOverlayInteractionSync);
        window.addEventListener("blur", stopOverlayInteractionSync);
        window.addEventListener("pointermove", handleZoneDragMove, { passive: false });
        window.addEventListener("pointerup", finishZoneDrag);
        window.addEventListener("blur", finishZoneDrag);
        return () => {
            resizeObserver.disconnect();
            chart.timeScale().unsubscribeVisibleTimeRangeChange(scheduleOverlayRecalc);
            chart.timeScale().unsubscribeVisibleLogicalRangeChange(scheduleOverlayRecalc);
            container.removeEventListener("pointerdown", startOverlayInteractionSync);
            container.removeEventListener("pointermove", syncDuringPointerMove);
            container.removeEventListener("wheel", syncDuringWheel);
            window.removeEventListener("pointermove", syncDuringPointerMove);
            window.removeEventListener("pointerup", stopOverlayInteractionSync);
            window.removeEventListener("blur", stopOverlayInteractionSync);
            window.removeEventListener("pointermove", handleZoneDragMove);
            window.removeEventListener("pointerup", finishZoneDrag);
            window.removeEventListener("blur", finishZoneDrag);
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
        };
    }, [
        finishZoneDrag,
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
            scheduleOverlayRecalc();
            return;
        }
        const previousViewKey = appliedViewKeyRef.current;
        const visibleRange = chart.timeScale().getVisibleLogicalRange();
        const visiblePriceRange = chart.priceScale("right").getVisibleRange();
        const isReplay = Boolean(payload.replay?.enabled);
        series.setData(candleData);
        scaleAnchorSeriesRef.current?.setData(buildScaleAnchorData(candleData));
        appliedCandleKeyRef.current = candleKey;
        appliedViewKeyRef.current = viewKey;
        if (isReplay) {
            applyReplayTimeViewport(chart, candleData, payload.range.limit);
            if (previousViewKey !== viewKey || visiblePriceRange === null) {
                replayPriceRangeRef.current = applyReplayPriceViewport(chart, candleData, true);
            }
            else {
                chart.priceScale("right").setAutoScale(false);
                chart.priceScale("right").setVisibleRange(visiblePriceRange);
                replayPriceRangeRef.current = visiblePriceRange;
            }
        }
        else if (previousViewKey !== viewKey) {
            replayPriceRangeRef.current = null;
            applyInitialViewport(chart, candleData, payload.range.limit);
            chart.priceScale("right").setAutoScale(true);
        }
        else if (visibleRange) {
            chart.timeScale().setVisibleLogicalRange(visibleRange);
            chart.priceScale("right").setAutoScale(true);
        }
        scheduleOverlayRecalc();
    }, [candleData, candleKey, payload.range.limit, payload.replay?.enabled, scheduleOverlayRecalc, viewKey]);
    return (_jsxs("div", { className: "relative h-full min-h-[540px] overflow-hidden bg-[#080b10]", children: [_jsx("div", { ref: containerRef, className: "absolute inset-0", onClick: clearSelection }), _jsxs("div", { className: "pointer-events-none absolute inset-0", children: [zoneBoxes.map((box) => {
                        const isSelected = selected?.kind === "zone" && selected.entity.id === box.zone.id;
                        const isHovered = hoveredZoneId === box.zone.id;
                        const isBullish = box.zone.direction === "bullish";
                        const showLabel = isSelected || isHovered || (box.width > 170 && box.height > 18 && box.zone.weight >= 0.55);
                        return (_jsxs("div", { className: `pointer-events-auto absolute select-none overflow-hidden border transition ${isBullish
                                ? "border-emerald-400/55 bg-emerald-400/[0.08] hover:bg-emerald-400/[0.14]"
                                : "border-rose-400/55 bg-rose-400/[0.08] hover:bg-rose-400/[0.14]"} ${box.zone.status === "active" ? "" : "border-dashed opacity-45"} ${isSelected ? "z-30 cursor-move ring-1 ring-cyan-300" : "z-10 cursor-pointer"}`, style: {
                                left: box.x,
                                top: box.y,
                                width: box.width,
                                height: box.height,
                            }, title: `${box.zone.type} ${box.zone.status} ${box.zone.price_low.toFixed(2)}-${box.zone.price_high.toFixed(2)}`, role: "button", tabIndex: 0, onMouseEnter: () => setHoveredZoneId(box.zone.id), onMouseLeave: () => setHoveredZoneId(null), onClick: () => updateDraftZone(box.zone), onPointerDown: (event) => {
                                if (isSelected) {
                                    beginZoneDrag(event, box, "move");
                                }
                                else {
                                    updateDraftZone(box.zone);
                                }
                            }, children: [isSelected ? (_jsxs(_Fragment, { children: [_jsx("button", { className: "absolute left-0 top-0 z-40 h-2.5 w-full cursor-ns-resize border-t border-cyan-200/90 bg-cyan-300/20", title: "Drag to resize zone high", type: "button", onClick: (event) => event.stopPropagation(), onPointerDown: (event) => beginZoneDrag(event, box, "resize-top") }), _jsx("button", { className: "absolute bottom-0 left-0 z-40 h-2.5 w-full cursor-ns-resize border-b border-cyan-200/90 bg-cyan-300/20", title: "Drag to resize zone low", type: "button", onClick: (event) => event.stopPropagation(), onPointerDown: (event) => beginZoneDrag(event, box, "resize-bottom") }), _jsx("button", { className: "absolute left-0 top-0 z-50 h-full w-2.5 cursor-ew-resize border-l border-cyan-200/90 bg-cyan-300/20", title: "Drag to resize zone start", type: "button", onClick: (event) => event.stopPropagation(), onPointerDown: (event) => beginZoneDrag(event, box, "resize-left") }), _jsx("button", { className: "absolute right-0 top-0 z-50 h-full w-2.5 cursor-ew-resize border-r border-cyan-200/90 bg-cyan-300/20", title: "Drag to resize zone end", type: "button", onClick: (event) => event.stopPropagation(), onPointerDown: (event) => beginZoneDrag(event, box, "resize-right") })] })) : null, showLabel ? (_jsxs("span", { className: `absolute left-1 top-1 max-w-[220px] truncate rounded px-1.5 py-0.5 text-[10px] font-medium ${isBullish ? "bg-emerald-950/80 text-emerald-200" : "bg-rose-950/80 text-rose-200"}`, children: [box.zone.type, " \u00B7 ", box.zone.weight.toFixed(2), " \u00B7 ", formatZoneDate(box.zone.visual_start)] })) : null] }, box.zone.id));
                    }), showStructure && zigzagPoints.length >= 2 ? (_jsx("svg", { className: "absolute inset-0 z-[18] h-full w-full overflow-visible", "aria-hidden": "true", children: _jsx("polyline", { fill: "none", points: zigzagPoints.map((point) => `${point.x},${point.y}`).join(" "), stroke: "#1f6fff", strokeLinecap: "round", strokeLinejoin: "round", strokeWidth: "2.2", style: {
                                filter: "drop-shadow(0 0 3px rgba(31, 111, 255, 0.55))",
                                vectorEffect: "non-scaling-stroke",
                            } }) })) : null, swingDots.map((dot) => {
                        const isHigh = dot.swingType === "high";
                        const isSelected = selected?.kind === "structure" && selected.entity.id === dot.point.id;
                        return (_jsxs("button", { className: `pointer-events-auto absolute z-30 flex h-5 w-5 -translate-x-1/2 items-center justify-center rounded-full border shadow-[0_0_6px_rgba(0,0,0,0.55)] transition hover:scale-110 ${isHigh
                                ? "-translate-y-[calc(100%+4px)] border-rose-300/80 bg-rose-950/90 text-rose-300"
                                : "translate-y-[4px] border-emerald-300/80 bg-emerald-950/90 text-emerald-300"} ${isSelected ? "ring-1 ring-cyan-200" : ""}`, style: { left: dot.x, top: dot.y }, title: `${isHigh ? "Swing High" : "Swing Low"} ${dot.point.type} ${dot.point.price.toFixed(2)}`, type: "button", onClick: () => setSelected({ kind: "structure", entity: dot.point }), children: [isHigh ? _jsx(ArrowDown, { size: 14, strokeWidth: 3 }) : _jsx(ArrowUp, { size: 14, strokeWidth: 3 }), _jsx("span", { className: "sr-only", children: dot.label })] }, dot.point.id));
                    }), structureDots.map((dot) => (_jsx("button", { className: `pointer-events-auto absolute h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border border-slate-950 ${dot.point.direction === "down" || ["LH", "LL"].includes(dot.point.type) ? "bg-rose-300" : "bg-emerald-300"}`, style: { left: dot.x, top: dot.y }, title: `${dot.point.type} ${dot.point.price.toFixed(2)}`, type: "button", onClick: () => setSelected({ kind: "structure", entity: dot.point }) }, dot.point.id)))] })] }));
}
function readSwingType(point) {
    const value = point.metadata.swing_type;
    return value === "high" || value === "low" ? value : null;
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
function buildZigZagPoints(swings) {
    const collapsed = [];
    for (const swing of swings.slice().sort((a, b) => a.x - b.x)) {
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
    return collapsed.map((swing) => ({ x: swing.x, y: swing.y }));
}
function roundPrice(price) {
    return Math.round(price * 100) / 100;
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
function buildReplayPriceRange(candles) {
    const last = candles.at(-1);
    if (!last)
        return { from: 0, to: 1 };
    const focusCandles = candles.slice(-VERTICAL_FOCUS_BARS);
    const high = Math.max(...focusCandles.map((candle) => candle.high), last.close);
    const low = Math.min(...focusCandles.map((candle) => candle.low), last.close);
    const averageRange = focusCandles.reduce((sum, candle) => sum + Math.max(candle.high - candle.low, 0), 0) / Math.max(focusCandles.length, 1);
    const minimumHalfRange = Math.max(averageRange * 6, last.close * 0.0075, 20);
    const halfRange = Math.max(high - last.close, last.close - low, minimumHalfRange) * 1.18;
    return {
        from: last.close - halfRange,
        to: last.close + halfRange,
    };
}
function buildCenteredAutoscale(candles, visibleRange) {
    if (candles.length === 0)
        return null;
    const range = visibleRange ?? { from: Math.max(0, candles.length - 96), to: candles.length - 1 };
    const from = Math.max(0, Math.floor(range.from));
    const to = Math.min(candles.length - 1, Math.ceil(range.to));
    const visibleCandles = candles.slice(from, to + 1);
    if (visibleCandles.length === 0)
        return null;
    const isWatchingLatest = range.to >= candles.length - 1;
    const anchorCandle = isWatchingLatest ? candles.at(-1) : visibleCandles.at(-1);
    const anchor = anchorCandle?.close;
    if (anchor === undefined)
        return null;
    const focusCandles = (isWatchingLatest ? candles : visibleCandles).slice(-VERTICAL_FOCUS_BARS);
    const high = Math.max(...focusCandles.map((candle) => candle.high), anchor);
    const low = Math.min(...focusCandles.map((candle) => candle.low), anchor);
    const averageRange = focusCandles.reduce((sum, candle) => sum + Math.max(candle.high - candle.low, 0), 0) / Math.max(focusCandles.length, 1);
    const minimumHalfRange = Math.max(averageRange * 5, anchor * 0.0045, 1);
    const halfRange = Math.max(high - anchor, anchor - low, minimumHalfRange) * 1.08;
    return {
        priceRange: {
            minValue: anchor - halfRange,
            maxValue: anchor + halfRange,
        },
        margins: {
            above: 18,
            below: 18,
        },
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
