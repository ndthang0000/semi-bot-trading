import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type RefObject } from "react";
import type { IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts";
import type { ChartCandle } from "../../types";
import { useLineReactionStore, type LinePlan } from "../../store/lineReactionStore";
import { useChartStore } from "../../store/chartStore";
import { updateLineReaction, updateLinePrice } from "../../api/lineReaction";
import { chartTimeToUnix, projectedTimeFromCoordinate, unixToIso } from "./chartCore";

type ResizePreview = { id: string; visual_start: string; visual_end: string };

export function LineReactionLayer({ chartRef, seriesRef, candles }: {
  chartRef: RefObject<IChartApi | null>; seriesRef: RefObject<ISeriesApi<"Candlestick"> | null>; candles: ChartCandle[];
}) {
  const plans = useLineReactionStore(s => s.plans);
  const setPlans = useLineReactionStore(s => s.setPlans);
  const select = useLineReactionStore(s => s.select);
  const selectedId = useLineReactionStore(s => s.selectedId);
  const [preview, setPreview] = useState<ResizePreview | null>(null);
  const [resizeError, setResizeError] = useState("");
  const [pricePreview, setPricePreview] = useState<{ id: string; price: number } | null>(null);
  const priceBusy = useRef(false);
  const dragCleanup = useRef<(() => void) | null>(null);
  useEffect(() => () => dragCleanup.current?.(), []);
  const savePrice = async (plan: LinePlan, price: number) => {
    if (priceBusy.current || price === plan.price || !Number.isFinite(price) || price <= 0) { setPricePreview(null); return; }
    priceBusy.current = true;
    setResizeError("");
    try {
      const result = await updateLinePrice(plan, price);
      useLineReactionStore.getState().upsertPlan(result);
    } catch (error) { setResizeError(String(error)); }
    finally { priceBusy.current = false; setPricePreview(null); }
  };
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
      if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
      if (event.target instanceof HTMLElement && event.target.closest("input,textarea,select,[contenteditable='true']")) return;
      const state = useLineReactionStore.getState();
      const plan = state.plans.find(item => item.id === state.selectedId);
      if (!plan || !["draft", "armed"].includes(plan.status)) return;
      event.preventDefault(); event.stopPropagation();
      if (priceBusy.current || dragCleanup.current) return;
      void savePrice(plan, Number((plan.price + (event.key === "ArrowUp" ? 0.5 : -0.5)).toFixed(2)));
    };
    window.addEventListener("keydown", keydown, true);
    return () => window.removeEventListener("keydown", keydown, true);
  }, []);
  const beginPriceDrag = (event: ReactPointerEvent<HTMLDivElement>, plan: LinePlan) => {
    if (plan.id !== selectedId || !["draft", "armed"].includes(plan.status) || !seriesRef.current || priceBusy.current || event.button !== 0) return;
    event.preventDefault(); event.stopPropagation();
    const series = seriesRef.current;
    const startPrice = series.coordinateToPrice(event.clientY - chartRef.current!.chartElement().getBoundingClientRect().top);
    if (startPrice === null) return;
    let price = plan.price;
    const move = (pointer: PointerEvent) => {
      const at = series.coordinateToPrice(pointer.clientY - chartRef.current!.chartElement().getBoundingClientRect().top);
      if (at === null) return;
      price = Math.max(0.01, Number((plan.price + Number(at) - Number(startPrice)).toFixed(2)));
      setPricePreview({ id: plan.id, price });
    };
    const cleanup = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", cancel);
      window.removeEventListener("keydown", escape, true);
      dragCleanup.current = null;
    };
    const cancel = () => { cleanup(); setPricePreview(null); };
    const escape = (key: KeyboardEvent) => { if (key.key === "Escape") { key.preventDefault(); key.stopPropagation(); cancel(); } };
    const finish = () => { cleanup(); void savePrice(plan, price); };
    dragCleanup.current = cleanup;
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish);
    window.addEventListener("pointercancel", cancel);
    window.addEventListener("keydown", escape, true);
  };
  const chart = chartRef.current, series = seriesRef.current;
  const candleData = useMemo(
    () => candles.map(candle => ({ ...candle, time: (Date.parse(candle.time) / 1000) as UTCTimestamp })),
    [candles],
  );
  const coordinate = (iso: string) => {
    if (!chart || candles.length < 2) return null;
    const seconds = Date.parse(iso) / 1000;
    const scale = chart.timeScale();
    const exact = scale.timeToCoordinate(seconds as UTCTimestamp);
    if (exact !== null) return Number(exact);
    const last = candles[candles.length - 1], previous = candles[candles.length - 2];
    const t = Date.parse(last.time) / 1000, prior = Date.parse(previous.time) / 1000;
    const x = scale.timeToCoordinate(t as UTCTimestamp), px = scale.timeToCoordinate(prior as UTCTimestamp);
    return x === null || px === null || t === prior ? null : x + (seconds - t) * (x - px) / (t - prior);
  };

  const timeAtClientX = (clientX: number) => {
    if (!chart) return null;
    const x = clientX - chart.chartElement().getBoundingClientRect().left;
    return chartTimeToUnix(chart.timeScale().coordinateToTime(x)) ?? projectedTimeFromCoordinate(chart, candleData, x);
  };

  const beginResize = (event: ReactPointerEvent<HTMLButtonElement>, plan: LinePlan, edge: "start" | "end") => {
    event.stopPropagation();
    if (priceBusy.current || dragCleanup.current) return;
    if (!chart || !plan.visual_start || !plan.visual_end || !["draft", "armed"].includes(plan.status)) return;
    event.preventDefault(); event.stopPropagation();
    let next: ResizePreview = { id: plan.id, visual_start: plan.visual_start, visual_end: plan.visual_end };
    const move = (pointer: PointerEvent) => {
      const time = timeAtClientX(pointer.clientX);
      if (time === null) return;
      const start = Date.parse(next.visual_start) / 1000;
      const end = Date.parse(next.visual_end) / 1000;
      const bounded = edge === "start"
        ? Math.max(end - 7 * 86400, Math.min(time, end - 900))
        : Math.min(start + 7 * 86400, Math.max(time, start + 900));
      next = edge === "start" ? { ...next, visual_start: unixToIso(bounded) } : { ...next, visual_end: unixToIso(bounded) };
      setPreview(next);
    };
    const finish = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      setResizeError("");
      void updateLineReaction(plan.id, { symbol: plan.symbol ?? "XAUUSD", account_labels: plan.account_labels ?? [plan.account_label],
          direction: plan.direction, price: plan.price, config: plan.config,
          visual_start: next.visual_start, visual_end: next.visual_end })
      .then(data => {
        setPlans(useLineReactionStore.getState().plans.map(item => item.id === plan.id ? data : item));
        setPreview(null);
      }).catch(error => { setPreview(null); setResizeError(String(error)); });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish, { once: true });
  };
  return <>
    {plans.filter(p => !["cancelled","expired","closed","failed"].includes(p.status)).map(p => {
      const geometry = preview?.id === p.id ? preview : null;
      const displayPrice = pricePreview?.id === p.id ? pricePreview.price : p.price;
      const y = series?.priceToCoordinate(displayPrice), start = coordinate(geometry?.visual_start ?? p.visual_start ?? p.armed_at ?? p.created_at), end = coordinate(geometry?.visual_end ?? p.visual_end ?? p.expires_at);
      if (y == null || start == null || end == null) return null;
      const width = chart ? Number(chart.timeScale().width()) : end;
      const left = Math.max(0, start), right = Math.min(width, end);
      if (right <= left) return null;
      const labels = p.account_labels ?? [p.account_label];
      const selected = p.id === selectedId;
      const editable = selected && ["draft", "armed"].includes(p.status) && p.visual_start && p.visual_end;
      return <div key={p.id} data-line-reaction="true" role="button" tabIndex={0} title={labels.join(", ") + " · " + p.status + " · " + p.expires_at}
        onPointerDown={event => beginPriceDrag(event, p)}
        onClick={() => {
          select(p.id);
          useChartStore.getState().setSelected(null);
          useChartStore.getState().setInspectorTab("zones");
        }}
        className={"absolute z-[35] border-t text-left text-[9px] leading-[11px] " + (p.status === "draft" ? "border-dashed " : "border-solid ") + (p.direction === "long" ? "border-emerald-400 text-emerald-300" : "border-rose-400 text-rose-300")}
        style={{ top: y, left, width: right-left, cursor: selected && ["draft", "armed"].includes(p.status) ? (pricePreview ? "grabbing" : "grab") : "pointer", touchAction: "none" }}>
        {p.direction === "long" ? "↑ LONG" : "↓ SHORT"} {displayPrice} · {p.status}
        {editable ? <>
          <button aria-label="Kéo đầu trái Line" className="absolute -left-1.5 -top-1.5 h-3 w-3 cursor-ew-resize rounded-full border border-white/80 bg-ink-900 shadow" onClick={event => event.stopPropagation()} onPointerDown={event => beginResize(event, p, "start")} />
          <button aria-label="Kéo đầu phải Line" className="absolute -right-1.5 -top-1.5 h-3 w-3 cursor-ew-resize rounded-full border border-white/80 bg-ink-900 shadow" onClick={event => event.stopPropagation()} onPointerDown={event => beginResize(event, p, "end")} />
        </> : null}
      </div>;
    })}
    {resizeError ? <div className="pointer-events-none absolute right-4 top-4 z-50 rounded border border-rose-400/40 bg-rose-950/90 px-3 py-2 text-xs text-rose-100">{resizeError}</div> : null}
  </>;
}
