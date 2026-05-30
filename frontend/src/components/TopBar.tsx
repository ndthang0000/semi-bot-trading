import { Activity, RefreshCw } from "lucide-react";
import { useChartStore } from "../store/chartStore";
import type { Timeframe } from "../types";

type TopBarProps = {
  isFetching: boolean;
  mode: "dashboard" | "replay";
  onRefresh: () => void;
};

export function TopBar({ isFetching, mode, onRefresh }: TopBarProps) {
  const timeframe = useChartStore((state) => state.timeframe);
  const limit = useChartStore((state) => state.limit);
  const activeZonesOnly = useChartStore((state) => state.activeZonesOnly);
  const showZones = useChartStore((state) => state.showZones);
  const showStructure = useChartStore((state) => state.showStructure);
  const setTimeframe = useChartStore((state) => state.setTimeframe);
  const setLimit = useChartStore((state) => state.setLimit);
  const setActiveZonesOnly = useChartStore((state) => state.setActiveZonesOnly);
  const setShowZones = useChartStore((state) => state.setShowZones);
  const setShowStructure = useChartStore((state) => state.setShowStructure);

  return (
    <header className="flex h-14 items-center justify-between border-b border-ink-700 bg-ink-900 px-4">
      <div className="flex items-center gap-3 font-semibold text-slate-100">
        <span className="flex h-8 w-8 items-center justify-center rounded-md border border-slate-700 bg-ink-800 text-cyan-300">
          <Activity size={18} />
        </span>
        <span>XAUUSD Control</span>
      </div>

      <div className="flex items-center gap-2">
        <nav className="mr-2 flex items-center rounded-md border border-ink-700 bg-ink-850 p-0.5 text-sm">
          <a
            className={`rounded px-3 py-1.5 transition ${
              mode === "dashboard" ? "bg-cyan-400/15 font-semibold text-cyan-100" : "text-slate-400 hover:text-slate-100"
            }`}
            href="/"
          >
            Realtime
          </a>
          <a
            className={`rounded px-3 py-1.5 transition ${
              mode === "replay" ? "bg-cyan-400/15 font-semibold text-cyan-100" : "text-slate-400 hover:text-slate-100"
            }`}
            href="/replay-chart"
          >
            Replay
          </a>
        </nav>
        <select
          className="h-9 rounded-md border border-ink-700 bg-ink-850 px-3 text-sm text-slate-100 outline-none"
          value={timeframe}
          onChange={(event) => setTimeframe(event.target.value as Timeframe)}
        >
          <option value="M15">M15</option>
          <option value="H1">H1</option>
        </select>
        <input
          className="h-9 w-24 rounded-md border border-ink-700 bg-ink-850 px-3 text-sm text-slate-100 outline-none"
          min={50}
          max={1500}
          step={50}
          type="number"
          value={limit}
          onChange={(event) => setLimit(Number(event.target.value))}
        />
        <label className="flex h-9 items-center gap-2 px-2 text-sm text-slate-400">
          <input
            checked={activeZonesOnly}
            className="accent-cyan-400"
            type="checkbox"
            onChange={(event) => setActiveZonesOnly(event.target.checked)}
          />
          Active zones
        </label>
        <label className="flex h-9 items-center gap-2 px-2 text-sm text-slate-400">
          <input checked={showZones} className="accent-cyan-400" type="checkbox" onChange={(event) => setShowZones(event.target.checked)} />
          Zones
        </label>
        <label className="flex h-9 items-center gap-2 px-2 text-sm text-slate-400">
          <input
            checked={showStructure}
            className="accent-cyan-400"
            type="checkbox"
            onChange={(event) => setShowStructure(event.target.checked)}
          />
          Structure
        </label>
        <button
          className="inline-flex h-9 items-center gap-2 rounded-md border border-ink-700 bg-ink-800 px-3 text-sm text-slate-100 hover:border-cyan-500"
          type="button"
          onClick={onRefresh}
        >
          <RefreshCw className={isFetching ? "animate-spin" : ""} size={15} />
          Reload
        </button>
      </div>
    </header>
  );
}
