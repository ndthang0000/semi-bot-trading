import { Crosshair, ChevronDown } from "lucide-react";
import type { IntradayMap } from "../../types";
import { intradayGuidance, levelStatusLabel } from "./intradayMap";

export function IntradayMapPanel({ map, bias }: { map: IntradayMap; bias: string }) {
  const above = map.levels.find((level) => level.id === map.nearest_above_id);
  const below = map.levels.find((level) => level.id === map.nearest_below_id);
  return (
    <details className="group pointer-events-auto absolute left-2 top-2 z-[24] max-w-[calc(100%-5rem)] rounded-lg border border-amber-300/25 bg-ink-950/90 text-[10px] text-slate-300 shadow-xl backdrop-blur md:left-3 md:top-3 md:w-[292px]">
      <summary className="flex min-h-9 cursor-pointer list-none items-center gap-2 px-2.5 py-1.5 select-none">
        <Crosshair className="shrink-0 text-amber-300" size={14} />
        <span className="font-semibold text-slate-100">Intraday Map</span>
        <span className="rounded bg-ink-800 px-1.5 py-0.5 text-[9px] uppercase text-cyan-200">{map.current_session}</span>
        <span className="ml-auto hidden tabular-nums text-slate-500 sm:inline">M15 ATR {map.atr_m15?.toFixed(2) ?? "--"}</span>
        <ChevronDown className="transition group-open:rotate-180" size={13} />
      </summary>
      <div className="border-t border-ink-700/80 px-2.5 py-2">
        <div className="grid grid-cols-[54px_minmax(0,1fr)_auto] gap-x-2 gap-y-1 tabular-nums">
          <span className="text-slate-500">Above</span>
          <span className="truncate text-rose-200">{above?.label ?? "--"}</span>
          <span>{above ? `+${above.distance.toFixed(2)} · ${levelStatusLabel(above.status)}` : "--"}</span>
          <span className="text-slate-500">Below</span>
          <span className="truncate text-emerald-200">{below?.label ?? "--"}</span>
          <span>{below ? `${below.distance.toFixed(2)} · ${levelStatusLabel(below.status)}` : "--"}</span>
          <span className="text-slate-500">Bias</span>
          <span className={bias === "bullish" ? "text-emerald-200" : bias === "bearish" ? "text-rose-200" : "text-slate-300"}>{bias}</span>
          <span>UTC</span>
        </div>
        <p className="mt-2 border-t border-ink-700/70 pt-2 leading-relaxed text-amber-100/80">{intradayGuidance(bias, map)}</p>
        <p className="mt-1 text-[9px] text-slate-500">Levels identify where to watch—not automatic entries.</p>
      </div>
    </details>
  );
}
