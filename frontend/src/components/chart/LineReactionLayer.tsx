import { useMemo, useState, type PointerEvent as ReactPointerEvent, type RefObject } from "react";
import type { IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts";
import type { ChartCandle } from "../../types";
import { useLineReactionStore, type LinePlan } from "../../store/lineReactionStore";
import { useChartStore } from "../../store/chartStore";
import { updateLineReaction } from "../../api/lineReaction";
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
      const y = series?.priceToCoordinate(p.price), start = coordinate(geometry?.visual_start ?? p.visual_start ?? p.armed_at ?? p.created_at), end = coordinate(geometry?.visual_end ?? p.visual_end ?? p.expires_at);
      if (y == null || start == null || end == null) return null;
      const width = chart ? Number(chart.timeScale().width()) : end;
      const left = Math.max(0, start), right = Math.min(width, end);
      if (right <= left) return null;
      const labels = p.account_labels ?? [p.account_label];
      const selected = p.id === selectedId;
      const editable = selected && ["draft", "armed"].includes(p.status) && p.visual_start && p.visual_end;
      return <div key={p.id} data-line-reaction="true" role="button" tabIndex={0} title={labels.join(", ") + " · " + p.status + " · " + p.expires_at}
        onClick={() => {
          select(p.id);
          useChartStore.getState().setSelected(null);
          useChartStore.getState().setInspectorTab("zones");
        }}
        className={"absolute z-[35] text-left text-[10px] " + (p.status === "draft" ? "border-t border-dashed " : "border-t-2 border-solid ") + (p.direction === "long" ? "border-emerald-400 text-emerald-300" : "border-rose-400 text-rose-300")}
        style={{ top: y, left, width: right-left }}>
        {p.direction === "long" ? "↑ LONG" : "↓ SHORT"} {p.price} · {p.status}
        {editable ? <>
          <button aria-label="Kéo đầu trái Line" className="absolute -left-1.5 -top-1.5 h-3 w-3 cursor-ew-resize rounded-full border border-white/80 bg-ink-900 shadow" onClick={event => event.stopPropagation()} onPointerDown={event => beginResize(event, p, "start")} />
          <button aria-label="Kéo đầu phải Line" className="absolute -right-1.5 -top-1.5 h-3 w-3 cursor-ew-resize rounded-full border border-white/80 bg-ink-900 shadow" onClick={event => event.stopPropagation()} onPointerDown={event => beginResize(event, p, "end")} />
        </> : null}
      </div>;
    })}
    {resizeError ? <div className="pointer-events-none absolute right-4 top-4 z-50 rounded border border-rose-400/40 bg-rose-950/90 px-3 py-2 text-xs text-rose-100">{resizeError}</div> : null}
  </>;
}
