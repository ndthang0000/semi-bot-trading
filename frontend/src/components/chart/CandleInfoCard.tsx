import { Sparkles, X } from "lucide-react";
import { useState } from "react";
import type { ChartCandle } from "../../types";
import { candleMetrics, formatCandleTime } from "./candleInfo";

type Props = {
  candle: ChartCandle;
  timeframe: string;
  timezone: string;
  atr: number | null;
  atrTimeframe: string;
  canPreviewH1Impulse?: boolean;
  previewLoading?: boolean;
  previewError?: string | null;
  onPreviewH1Impulse?: (riskReward: number) => void;
  onClose: () => void;
};

export function CandleInfoCard({
  candle,
  timeframe,
  timezone,
  atr,
  atrTimeframe,
  canPreviewH1Impulse = false,
  previewLoading = false,
  previewError = null,
  onPreviewH1Impulse,
  onClose,
}: Props) {
  const [riskReward, setRiskReward] = useState(2.5);
  const metrics = candleMetrics(candle, atr);
  const directionClass =
    metrics.direction === "bullish"
      ? "border-emerald-400/35 bg-emerald-400/10 text-emerald-200"
      : metrics.direction === "bearish"
        ? "border-rose-400/35 bg-rose-400/10 text-rose-200"
        : "border-slate-400/35 bg-slate-400/10 text-slate-200";

  return (
    <section
      aria-label="Thông tin nến đã chọn"
      className="absolute bottom-3 left-2 right-2 z-[55] rounded-lg border border-cyan-300/30 bg-ink-950/95 p-3 text-[11px] text-slate-200 shadow-2xl shadow-black/60 backdrop-blur md:bottom-auto md:left-auto md:right-[76px] md:top-3 md:w-[318px]"
      onClick={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-semibold text-slate-100">{timeframe} Candle</span>
            <span className={`rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase ${directionClass}`}>
              {metrics.direction}
            </span>
          </div>
          <div className="mt-0.5 truncate font-mono text-[10px] text-slate-400">{formatCandleTime(candle.time, timezone)}</div>
        </div>
        <button
          aria-label="Đóng thông tin nến"
          className="grid h-7 w-7 shrink-0 place-items-center rounded text-slate-400 hover:bg-white/10 hover:text-white"
          type="button"
          onClick={onClose}
        >
          <X size={15} />
        </button>
      </div>

      <div className="mt-2 grid grid-cols-4 gap-1.5 font-mono tabular-nums">
        <Metric label="O" value={price(candle.open)} />
        <Metric label="H" value={price(candle.high)} tone="text-emerald-200" />
        <Metric label="L" value={price(candle.low)} tone="text-rose-200" />
        <Metric label="C" value={price(candle.close)} />
      </div>
      <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 border-t border-ink-700/80 pt-2 tabular-nums">
        <InfoRow label="Range" value={price(metrics.range)} />
        <InfoRow emphasis label="Body" value={`${price(metrics.body)} · ${metrics.bodyPercent.toFixed(0)}%`} />
        <InfoRow label="Upper wick" value={price(metrics.upperWick)} />
        <InfoRow label="Lower wick" value={price(metrics.lowerWick)} />
        <InfoRow label={`Range/${atrTimeframe} ATR`} value={metrics.rangeAtr === null ? "--" : `${metrics.rangeAtr.toFixed(2)}x`} />
        <InfoRow label="Volume" value={candle.volume === null ? "--" : candle.volume.toLocaleString("en-US")} />
      </div>
      {canPreviewH1Impulse && onPreviewH1Impulse ? (
        <div className="mt-3 border-t border-ink-700/80 pt-2">
          <div className="mb-2 flex items-center gap-1.5">
            <span className="mr-auto text-[10px] text-slate-500">Target RR</span>
            {[1.5, 2, 2.5, 3, 4].map((option) => (
              <button
                key={option}
                className={`h-7 rounded border px-2 font-mono text-[10px] font-bold ${
                  riskReward === option
                    ? "border-cyan-300/60 bg-cyan-300/15 text-cyan-100"
                    : "border-ink-700 text-slate-400 hover:border-slate-500"
                }`}
                type="button"
                onClick={() => setRiskReward(option)}
              >
                {option}R
              </button>
            ))}
          </div>
          <button
            className="flex h-9 w-full items-center justify-center gap-2 rounded-lg border border-cyan-300/40 bg-cyan-300/10 font-semibold text-cyan-100 transition hover:border-cyan-200/70 hover:bg-cyan-300/15 disabled:cursor-wait disabled:opacity-60"
            disabled={previewLoading}
            type="button"
            onClick={() => onPreviewH1Impulse(riskReward)}
          >
            <Sparkles size={14} />
            {previewLoading ? "Đang dựng setup…" : "Add setup preview to chart"}
          </button>
          {previewError ? <div className="mt-2 text-[10px] leading-4 text-rose-300">{previewError}</div> : null}
        </div>
      ) : null}
      <p className="mt-2 text-[9px] text-slate-500">Click lại nến, vùng trống hoặc nhấn Esc để đóng.</p>
    </section>
  );
}

function Metric({ label, value, tone = "text-slate-100" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded border border-ink-700 bg-black/20 px-1.5 py-1">
      <div className="text-[9px] text-slate-500">{label}</div>
      <div className={`truncate ${tone}`}>{value}</div>
    </div>
  );
}

function InfoRow({ label, value, emphasis = false }: { label: string; value: string; emphasis?: boolean }) {
  return (
    <div className={`flex min-w-0 items-center justify-between gap-2 ${
      emphasis ? "-mx-1 rounded border border-amber-300/35 bg-amber-300/10 px-1 py-0.5 shadow-[0_0_8px_rgba(252,211,77,0.08)]" : ""
    }`}>
      <span className={`truncate ${emphasis ? "font-semibold text-amber-200" : "text-slate-500"}`}>{label}</span>
      <span className={`shrink-0 font-mono ${emphasis ? "font-bold text-amber-100" : "text-slate-200"}`}>{value}</span>
    </div>
  );
}

function price(value: number): string {
  return value.toFixed(2);
}
