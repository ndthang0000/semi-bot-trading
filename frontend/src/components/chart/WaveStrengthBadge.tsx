import { useState, type MouseEvent } from "react";
import { Activity, ChevronDown } from "lucide-react";
import type { WaveMetrics } from "../../types";

const price = (value: number | null) => value === null ? "--" : value.toFixed(1);
const bars = (value: number | null) => value === null ? "--" : `${value.toFixed(Number.isInteger(value) ? 0 : 1)}H`;
const speed = (value: number | null) => value === null ? "--" : `${value.toFixed(1)}/H`;
const signed = (value: number, direction: "up" | "down") => `${direction === "up" ? "+" : "−"}${value.toFixed(1)}`;
const change = (value: number | null) => value === null ? "--" : `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(0)}%`;

function changeLabel(direction: "UP" | "DOWN", value: number | null): string {
  if (value === null || Math.abs(value) < 5) return `${direction} stable`;
  return `${direction} ${value > 0 ? "expansion" : "contraction"}`;
}

function stateLabel(state: WaveMetrics["strength"]["market_state"]): string {
  if (state === "trending_up") return "TREND UP";
  if (state === "trending_down") return "TREND DOWN";
  if (state === "choppy") return "CHOPPY";
  if (state === "rotational") return "ROTATIONAL";
  return "BUILDING";
}

function stateDescription(strength: WaveMetrics["strength"]): string {
  if (strength.market_state === "trending_up") return "Recent waves retain efficient upside displacement.";
  if (strength.market_state === "trending_down") return "Recent waves retain efficient downside displacement.";
  if (strength.market_state === "choppy") return "Price travels far but retains little net displacement; two-way rotation dominates.";
  if (strength.market_state === "rotational") return "Directional movement exists, but recent waves still overlap materially.";
  return "More confirmed waves are needed before classifying the path.";
}

export function WaveStrengthBadge({ metrics }: { metrics?: WaveMetrics }) {
  const [expanded, setExpanded] = useState(false);
  if (!metrics || metrics.legs.length === 0) return null;
  const { strength } = metrics;
  const latest = strength.latest;
  const controlClass = strength.control === "buy"
    ? "text-emerald-300"
    : strength.control === "sell"
      ? "text-rose-300"
      : "text-slate-300";
  const controlLabel = strength.control === "buy"
    ? "Bull pressure"
    : strength.control === "sell"
      ? "Bear pressure"
      : strength.control === "balanced"
        ? "Balanced"
        : "Building";
  const latestClass = latest?.direction === "up" ? "text-emerald-300" : "text-rose-300";
  const latestSign = latest ? signed(latest.price_move, latest.direction) : "--";
  const efficiency = strength.efficiency === null ? "--" : `${(strength.efficiency * 100).toFixed(0)}%`;
  const ratioLabel = strength.ratio === null ? "--" : `${strength.ratio.toFixed(2)}×`;

  const toggle = (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    setExpanded((value) => !value);
  };

  return (
    <div className="absolute right-16 top-3 z-[55] hidden font-mono text-[9px] tabular-nums sm:block">
      <button
        className="pointer-events-auto flex items-center gap-1.5 rounded-md border border-slate-600/35 bg-ink-950/82 px-2 py-1 text-slate-400 shadow-sm backdrop-blur-sm hover:border-cyan-400/40"
        title="Click to inspect recent confirmed ZigZag waves"
        type="button"
        onClick={toggle}
      >
        <Activity className="text-cyan-300/75" size={11} />
        <span>Wave</span>
        <span className={latestClass}>Last {latestSign}/{bars(latest?.bars ?? null)}</span>
        <span className="text-emerald-300/80">U {price(strength.up_median_price)}</span>
        <span className="text-rose-300/80">D {price(strength.down_median_price)}</span>
        <span>{ratioLabel}</span>
        <span className={controlClass}>{controlLabel}</span>
        <ChevronDown className={`transition-transform ${expanded ? "rotate-180" : ""}`} size={10} />
      </button>

      {expanded ? (
        <div
          className="pointer-events-auto absolute right-0 top-full mt-2 w-80 rounded-lg border border-slate-600/45 bg-ink-950/95 p-3 text-[10px] text-slate-300 shadow-xl backdrop-blur-md"
          onClick={(event) => event.stopPropagation()}
        >
          <div className="mb-2 flex items-center justify-between border-b border-ink-700 pb-2">
            <span className="font-sans text-xs font-semibold text-slate-100">Recent wave behavior</span>
            <span className={`rounded border px-1.5 py-0.5 ${controlClass}`}>{stateLabel(strength.market_state)}</span>
          </div>

          <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-3 gap-y-1.5">
            <span className="text-slate-500">Sample</span>
            <span className="text-right text-slate-500">Move</span>
            <span className="text-right text-slate-500">Time</span>
            <span className="text-right text-slate-500">Speed</span>

            <span>Latest {latest?.direction ?? "--"}</span>
            <span className={`text-right ${latestClass}`}>{latestSign}</span>
            <span className="text-right">{bars(latest?.bars ?? null)}</span>
            <span className="text-right">{speed(latest?.speed ?? null)}</span>

            <span>Baseline UP <span className="text-slate-600">n={strength.up_samples}</span></span>
            <span className="text-right text-emerald-300">+{price(strength.up_median_price)}</span>
            <span className="text-right">{bars(strength.up_median_bars)}</span>
            <span className="text-right">{speed(strength.up_median_speed)}</span>

            <span>Baseline DOWN <span className="text-slate-600">n={strength.down_samples}</span></span>
            <span className="text-right text-rose-300">−{price(strength.down_median_price)}</span>
            <span className="text-right">{bars(strength.down_median_bars)}</span>
            <span className="text-right">{speed(strength.down_median_speed)}</span>
          </div>

          <div className="my-2 h-px bg-ink-700" />
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
            <span className="text-slate-500">Latest / previous</span>
            <span className="text-right">{strength.latest_to_previous_ratio?.toFixed(2) ?? "--"}×</span>
            <span className="text-slate-500">{changeLabel("UP", strength.up_change_pct)}</span>
            <span className={`text-right ${(strength.up_change_pct ?? 0) >= 0 ? "text-emerald-300" : "text-slate-300"}`}>{change(strength.up_change_pct)}</span>
            <span className="text-slate-500">{changeLabel("DOWN", strength.down_change_pct)}</span>
            <span className={`text-right ${(strength.down_change_pct ?? 0) >= 0 ? "text-rose-300" : "text-slate-300"}`}>{change(strength.down_change_pct)}</span>
            <span className="text-slate-500">6-wave efficiency</span>
            <span className="text-right">{efficiency} {strength.efficiency_direction}</span>
            <span className="text-slate-500">UP / DOWN</span>
            <span className={`text-right ${controlClass}`}>{ratioLabel} · {controlLabel}</span>
          </div>

          <p className="mt-2 border-t border-ink-700 pt-2 font-sans text-[10px] leading-4 text-slate-400">
            {stateDescription(strength)} Metrics describe confirmed waves—not an automatic entry signal.
          </p>
        </div>
      ) : null}
    </div>
  );
}
