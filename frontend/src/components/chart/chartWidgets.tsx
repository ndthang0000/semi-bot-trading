import { useEffect, useState } from "react";
import type { NewsEvent } from "../../api/chart";
import type { SpreadSummary } from "../../types";
import { clampNumber } from "./tradeOverlay";

export type NewsTimelineMarker = {
  event: NewsEvent;
  x: number;
  y: number;
  chartWidth: number;
  chartHeight: number;
};

const TIMEFRAME_SECONDS: Record<string, number> = { M5: 300, M15: 900, H1: 3600 };

export function candleSecondsForTimeframe(timeframe: string): number {
  return TIMEFRAME_SECONDS[timeframe] ?? 3600;
}

export function remainingCandleSeconds(timeframe: string, nowMs = Date.now()): number {
  const tfSecs = candleSecondsForTimeframe(timeframe);
  const nowSecs = Math.floor(nowMs / 1000);
  const remaining = tfSecs - (nowSecs % tfSecs);
  return remaining === tfSecs ? 0 : remaining;
}

export function CandleCountdown({
  timeframe,
  priceY,
  scaleWidth,
  isUp,
  chartHeight,
  pointerY,
  spread,
}: {
  timeframe: string;
  priceY: number;
  scaleWidth: number;
  isUp: boolean;
  chartHeight: number;
  pointerY: number | null;
  spread?: SpreadSummary | null;
}) {
  const tfSecs = candleSecondsForTimeframe(timeframe);
  const calc = () => remainingCandleSeconds(timeframe);

  const [secs, setSecs] = useState(calc);

  useEffect(() => {
    const id = setInterval(() => setSecs(calc()), 1000);
    return () => clearInterval(id);
  }, [tfSecs]);

  const mm = Math.floor(secs / 60).toString().padStart(2, "0");
  const ss = (secs % 60).toString().padStart(2, "0");
  const bg = isUp ? "#2fbd85" : "#e35d68";

  const currentSpread = spread?.latest?.spread ?? null;
  const labelHeight = 20;
  const cursorLabelHalfHeight = 14;
  const defaultTop = priceY + 10;
  let top = defaultTop;
  if (
    pointerY !== null &&
    defaultTop < pointerY + cursorLabelHalfHeight &&
    defaultTop + labelHeight > pointerY - cursorLabelHalfHeight
  ) {
    const aboveTop = priceY - labelHeight - 12;
    const belowTop = priceY + 32;
    top = pointerY >= priceY ? aboveTop : belowTop;
  }
  top = clampNumber(top, 0, Math.max(0, chartHeight - labelHeight));

  return (
    <div className="pointer-events-none absolute z-20 flex items-stretch justify-end gap-1" style={{ right: 0, top, height: labelHeight }}>
      {currentSpread !== null ? <SpreadBadge spread={currentSpread} /> : null}
      <div
        className="flex items-center justify-center font-mono text-[11px] font-semibold text-white"
        style={{
          width: scaleWidth,
          backgroundColor: bg,
        }}
      >
        {mm}:{ss}
      </div>
    </div>
  );
}

export function NewsTimelineTooltip({ marker }: { marker: NewsTimelineMarker }) {
  const { event, x, y } = marker;
  const left = clampNumber(x - 132, 8, Math.max(8, marker.chartWidth - 272));
  const top = clampNumber(y - 152, 8, Math.max(8, marker.chartHeight - 150));
  const tierClass = event.tier === 1 ? "border-red-400/70 bg-red-500/15 text-red-200" : "border-red-400/40 bg-red-500/10 text-red-300";
  const rows = [
    { label: "Impact", value: event.impact },
    { label: "Forecast", value: event.forecast },
    { label: "Previous", value: event.previous },
    { label: "Blackout", value: `${event.blackout_before_min}/${event.blackout_after_min}m` },
  ].filter((row) => row.value !== null && row.value !== "");

  return (
    <div
      className="pointer-events-none absolute z-[70] w-[264px] rounded-md border border-ink-600 bg-ink-950/95 p-3 text-xs text-slate-200 shadow-2xl shadow-black/60"
      style={{ left, top }}
    >
      <div className="mb-2 flex items-start gap-2">
        <span className={`mt-0.5 rounded border px-1.5 py-0.5 text-[10px] font-bold uppercase ${tierClass}`}>
          T{event.tier}
        </span>
        <div className="min-w-0">
          <div className="truncate font-semibold text-slate-50">{event.title}</div>
          <div className="mt-0.5 text-[10px] text-slate-500">
            {event.country} - {formatNewsEventDateTime(event.scheduled_at)}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-x-2 gap-y-1">
        {rows.map((row) => (
          <div key={row.label} className="contents">
            <span className="text-slate-500">{row.label}</span>
            <span className="min-w-0 truncate text-slate-200">{row.value}</span>
          </div>
        ))}
      </div>
      {event.is_active_blackout ? (
        <div className="mt-2 rounded border border-red-500/40 bg-red-500/10 px-2 py-1 text-[10px] font-semibold uppercase text-red-200">
          Active blackout
        </div>
      ) : null}
    </div>
  );
}

function SpreadBadge({ spread }: { spread: number }) {
  const colorClass = spread >= 1.5 ? "text-fuchsia-300" : spread >= 0.8 ? "text-yellow-300" : "text-white";
  return (
    <div className={`flex items-center border border-white/10 bg-ink-950/90 px-1.5 font-mono text-[10px] font-bold ${colorClass}`}>
      S {spread.toFixed(2)}
    </div>
  );
}

function formatNewsEventDateTime(isoString: string): string {
  const scheduled = new Date(isoString);
  return scheduled.toLocaleString([], {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
