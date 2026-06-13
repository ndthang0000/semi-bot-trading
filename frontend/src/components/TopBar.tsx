import { Activity, ChevronDown, ChevronLeft, ChevronRight, Eye, Layers, LogOut, Pause, Play, Plus, RefreshCw, Rows3, Target, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { clearStoredRefreshToken, getStoredRefreshToken, logout } from "../api/auth";
import { useAuthStore } from "../store/authStore";
import { playbookLayerRequirements, useChartStore } from "../store/chartStore";
import type { AddEntityKind, PlaybookKey, Timeframe, ZoneVisibilityKey } from "../types";

type TopBarProps = {
  isFetching: boolean;
  mode: "dashboard" | "replay";
  onRefresh: () => void;
};

export function TopBar({ isFetching, mode, onRefresh }: TopBarProps) {
  const timeframe = useChartStore((state) => state.timeframe);
  const limit = useChartStore((state) => state.limit);
  const startIndex = useChartStore((state) => state.startIndex);
  const autoRefreshEnabled = useChartStore((state) => state.autoRefreshEnabled);
  const addEntityKind = useChartStore((state) => state.addEntityKind);
  const setTimeframe = useChartStore((state) => state.setTimeframe);
  const setLimit = useChartStore((state) => state.setLimit);
  const setStartIndex = useChartStore((state) => state.setStartIndex);
  const shiftStartIndex = useChartStore((state) => state.shiftStartIndex);
  const setAutoRefreshEnabled = useChartStore((state) => state.setAutoRefreshEnabled);
  const setAddEntityKind = useChartStore((state) => state.setAddEntityKind);
  const autoRefreshActive = mode === "dashboard" && autoRefreshEnabled && startIndex === null;

  return (
    <header className="flex h-14 items-center justify-between gap-4 border-b border-ink-700 bg-ink-900 px-4">
      <div className="flex items-center gap-3 font-semibold text-slate-100">
        <span className="flex h-8 w-8 items-center justify-center rounded-md border border-slate-700 bg-ink-800 text-cyan-300">
          <Activity size={18} />
        </span>
        <span className="whitespace-nowrap">XAUUSD Control</span>
      </div>

      <div className="flex min-w-0 items-center gap-2">
        <div className="flex h-9 items-center overflow-hidden rounded-md border border-ink-700 bg-ink-850">
          <span className="flex h-full items-center px-2 text-cyan-300">
            <Plus size={15} />
          </span>
          <select
            className="h-full min-w-[150px] bg-transparent pr-2 text-sm text-slate-100 outline-none"
            title="Add entity: select a type, then drag a box on the chart"
            value={addEntityKind ?? ""}
            onChange={(event) => setAddEntityKind((event.target.value || null) as AddEntityKind | null)}
          >
            <option value="">Add entity</option>
            <option value="support">Support</option>
            <option value="resistance">Resistance</option>
            <option value="demand_order_block">Demand OB</option>
            <option value="supply_order_block">Supply OB</option>
            <option value="bullish_fvg">Bullish FVG</option>
            <option value="bearish_fvg">Bearish FVG</option>
            <option value="consolidation">Consolidation</option>
            <option value="buy_side_liquidity">Buy-side Liq</option>
            <option value="sell_side_liquidity">Sell-side Liq</option>
          </select>
          {addEntityKind ? (
            <button
              className="flex h-full w-8 items-center justify-center border-l border-ink-700 text-slate-400 hover:text-slate-100"
              title="Cancel add mode"
              type="button"
              onClick={() => setAddEntityKind(null)}
            >
              <X size={14} />
            </button>
          ) : null}
        </div>
        <nav className="flex items-center rounded-md border border-ink-700 bg-ink-850 p-0.5 text-sm">
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
          max={15000}
          step={50}
          type="number"
          value={limit}
          onChange={(event) => setLimit(Number(event.target.value))}
        />
        <WindowMenu
          limit={limit}
          startIndex={startIndex}
          onLatest={() => setStartIndex(null)}
          onFirst={() => setStartIndex(0)}
          onShift={shiftStartIndex}
          onStartIndexChange={setStartIndex}
        />
        <PlaybookMenu />
        <LayerMenu />
        <button
          className={`inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm transition ${
            autoRefreshActive
              ? "border-cyan-500/60 bg-cyan-400/10 text-cyan-100"
              : "border-ink-700 bg-ink-800 text-slate-300 hover:border-cyan-500"
          }`}
          title={startIndex === null ? "Toggle auto refresh every 60 seconds" : "Auto refresh is paused while viewing historical windows"}
          type="button"
          onClick={() => setAutoRefreshEnabled(!autoRefreshEnabled)}
        >
          {autoRefreshEnabled ? <Pause size={15} /> : <Play size={15} />}
          <span>{autoRefreshEnabled ? "Auto 60s" : "Manual"}</span>
          {autoRefreshEnabled && startIndex !== null ? <span className="text-[11px] text-slate-500">paused</span> : null}
        </button>
        <button
          className="inline-flex h-9 items-center gap-2 rounded-md border border-ink-700 bg-ink-800 px-3 text-sm text-slate-100 hover:border-cyan-500"
          type="button"
          onClick={onRefresh}
        >
          <RefreshCw className={isFetching ? "animate-spin" : ""} size={15} />
          Reload
        </button>
        <LogoutButton />
      </div>
    </header>
  );
}

function LogoutButton() {
  const { accessToken, username, clearAuth } = useAuthStore();

  const handleLogout = async () => {
    const refreshToken = getStoredRefreshToken();
    if (accessToken && refreshToken) {
      await logout(accessToken, refreshToken);
    }
    clearStoredRefreshToken();
    clearAuth();
  };

  return (
    <button
      className="inline-flex h-9 items-center gap-2 rounded-md border border-ink-700 bg-ink-800 px-3 text-sm text-slate-400 hover:border-rose-500/50 hover:text-rose-300"
      title={`Signed in as ${username ?? "unknown"} — click to sign out`}
      type="button"
      onClick={handleLogout}
    >
      <LogOut size={15} />
    </button>
  );
}

type WindowMenuProps = {
  limit: number;
  startIndex: number | null;
  onLatest: () => void;
  onFirst: () => void;
  onShift: (delta: number) => void;
  onStartIndexChange: (startIndex: number | null) => void;
};

function WindowMenu({ limit, startIndex, onLatest, onFirst, onShift, onStartIndexChange }: WindowMenuProps) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  return (
    <div ref={menuRef} className="relative">
      <button
        className={`inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm transition ${
          open ? "border-cyan-400/70 bg-cyan-400/10 text-cyan-100" : "border-ink-700 bg-ink-800 text-slate-100 hover:border-cyan-500"
        }`}
        title="Candle window"
        type="button"
        onClick={() => setOpen((value) => !value)}
      >
        <Rows3 size={15} />
        <span>{startIndex === null ? "Latest" : `Start ${startIndex}`}</span>
        <ChevronDown className={open ? "rotate-180 transition" : "transition"} size={14} />
      </button>

      {open ? (
        <div className="absolute right-0 top-11 z-50 w-72 rounded-md border border-ink-700 bg-ink-900 p-3 text-sm text-slate-200 shadow-2xl shadow-black/40">
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2 font-semibold text-slate-100">
              <Rows3 size={15} className="text-cyan-300" />
              Candle window
            </div>
            <span className="text-xs text-slate-500">limit {limit}</span>
          </div>

          <label className="grid gap-1 text-xs text-slate-500">
            Start index
            <input
              className="h-9 rounded-md border border-ink-700 bg-ink-850 px-3 text-sm text-slate-100 outline-none placeholder:text-slate-600"
              min={0}
              placeholder="latest"
              title="Blank = latest candles, 0 = first candle window"
              type="number"
              value={startIndex ?? ""}
              onChange={(event) => {
                const value = event.target.value.trim();
                onStartIndexChange(value === "" ? null : Number(value));
              }}
            />
          </label>

          <div className="mt-3 grid grid-cols-2 gap-2">
            <button
              className="inline-flex h-9 items-center justify-center gap-1 rounded-md border border-ink-700 bg-ink-850 text-slate-200 hover:border-cyan-500 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={startIndex === null || startIndex <= 0}
              type="button"
              onClick={() => onShift(-limit)}
            >
              <ChevronLeft size={15} />
              Prev
            </button>
            <button
              className="inline-flex h-9 items-center justify-center gap-1 rounded-md border border-ink-700 bg-ink-850 text-slate-200 hover:border-cyan-500"
              type="button"
              onClick={() => onShift(limit)}
            >
              Next
              <ChevronRight size={15} />
            </button>
            <button
              className="h-9 rounded-md border border-ink-700 bg-ink-850 text-slate-200 hover:border-cyan-500"
              type="button"
              onClick={onFirst}
            >
              First
            </button>
            <button
              className="h-9 rounded-md border border-ink-700 bg-ink-850 text-slate-200 hover:border-cyan-500"
              type="button"
              onClick={onLatest}
            >
              Latest
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function PlaybookMenu() {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const selectedPlaybooks = useChartStore((state) => state.selectedPlaybooks);
  const toggleSelectedPlaybook = useChartStore((state) => state.toggleSelectedPlaybook);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  return (
    <div ref={menuRef} className="relative">
      <button
        className={`inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm transition ${
          open ? "border-cyan-400/70 bg-cyan-400/10 text-cyan-100" : "border-ink-700 bg-ink-800 text-slate-100 hover:border-cyan-500"
        }`}
        type="button"
        onClick={() => setOpen((value) => !value)}
      >
        <Target size={15} />
        Playbooks
        <span className="rounded bg-ink-950 px-1.5 py-0.5 text-[11px] text-slate-400">{selectedPlaybooks.length}</span>
        <ChevronDown className={open ? "rotate-180 transition" : "transition"} size={14} />
      </button>

      {open ? (
        <div className="absolute right-0 top-11 z-50 w-80 rounded-md border border-ink-700 bg-ink-900 p-3 text-sm text-slate-200 shadow-2xl shadow-black/40">
          <div className="mb-2 flex items-center justify-between">
            <div className="flex items-center gap-2 font-semibold text-slate-100">
              <Target size={15} className="text-cyan-300" />
              Running playbooks
            </div>
            <span className="text-xs text-cyan-200">Auto layers</span>
          </div>

          <div className="grid gap-1">
            {PLAYBOOK_ITEMS.map((item) => (
              <label key={item.key} className="grid cursor-pointer gap-0.5 rounded px-1.5 py-1.5 hover:bg-ink-800/70">
                <span className="flex items-center gap-2">
                  <input
                    checked={selectedPlaybooks.includes(item.key)}
                    className="accent-cyan-400"
                    onChange={(event) => toggleSelectedPlaybook(item.key, event.target.checked)}
                    type="checkbox"
                  />
                  <span className="font-medium text-slate-100">{item.label}</span>
                </span>
                <span className="pl-6 text-[11px] text-slate-500">{playbookRequirementLabel(item.key)}</span>
              </label>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function LayerMenu() {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const activeZonesOnly = useChartStore((state) => state.activeZonesOnly);
  const showZones = useChartStore((state) => state.showZones);
  const zoneTypeVisibility = useChartStore((state) => state.zoneTypeVisibility);
  const showStructure = useChartStore((state) => state.showStructure);
  const importantZonesOnly = useChartStore((state) => state.importantZonesOnly);
  const maxVisibleZones = useChartStore((state) => state.maxVisibleZones);
  const setActiveZonesOnly = useChartStore((state) => state.setActiveZonesOnly);
  const setShowZones = useChartStore((state) => state.setShowZones);
  const setZoneTypeVisible = useChartStore((state) => state.setZoneTypeVisible);
  const setAllZoneTypesVisible = useChartStore((state) => state.setAllZoneTypesVisible);
  const setShowStructure = useChartStore((state) => state.setShowStructure);
  const setImportantZonesOnly = useChartStore((state) => state.setImportantZonesOnly);
  const setMaxVisibleZones = useChartStore((state) => state.setMaxVisibleZones);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const visibleZoneCount = Object.values(zoneTypeVisibility).filter(Boolean).length;
  const totalVisibleCount = visibleZoneCount + (showStructure ? 1 : 0);
  const allZonesVisible = visibleZoneCount === LAYER_ITEMS.length;

  return (
    <div ref={menuRef} className="relative">
      <button
        className={`inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm transition ${
          open ? "border-cyan-400/70 bg-cyan-400/10 text-cyan-100" : "border-ink-700 bg-ink-800 text-slate-100 hover:border-cyan-500"
        }`}
        type="button"
        onClick={() => setOpen((value) => !value)}
      >
        <Layers size={15} />
        Layers
        <span className="rounded bg-ink-950 px-1.5 py-0.5 text-[11px] text-slate-400">{totalVisibleCount}</span>
        <ChevronDown className={open ? "rotate-180 transition" : "transition"} size={14} />
      </button>

      {open ? (
        <div className="absolute right-0 top-11 z-50 w-72 rounded-md border border-ink-700 bg-ink-900 p-3 text-sm text-slate-200 shadow-2xl shadow-black/40">
          <div className="mb-2 flex items-center justify-between">
            <div className="flex items-center gap-2 font-semibold text-slate-100">
              <Eye size={15} className="text-cyan-300" />
              Visible layers
            </div>
            <button
              className="text-xs text-cyan-200 hover:text-cyan-100"
              type="button"
              onClick={() => setAllZoneTypesVisible(!allZonesVisible)}
            >
              {allZonesVisible ? "Hide zones" : "Show zones"}
            </button>
          </div>

          <div className="grid gap-1">
            <MenuCheck checked={activeZonesOnly} label="Active zones only" onChange={setActiveZonesOnly} />
            <div className="flex items-center gap-2 rounded px-1.5 py-1 text-slate-300">
              <input
                checked={importantZonesOnly}
                className="accent-cyan-400"
                type="checkbox"
                onChange={(event) => setImportantZonesOnly(event.target.checked)}
              />
              <span className="flex-1">Important zones</span>
              <input
                className="h-7 w-14 rounded border border-ink-700 bg-ink-850 px-2 text-xs text-slate-100 outline-none"
                max={40}
                min={1}
                title="Max visible zones when Important is enabled"
                type="number"
                value={maxVisibleZones}
                onChange={(event) => setMaxVisibleZones(Number(event.target.value))}
              />
            </div>
          </div>

          <div className="my-2 h-px bg-ink-700" />

          <div className="grid gap-1">
            <MenuCheck checked={showZones} label="All price zones" onChange={setShowZones} />
            {LAYER_ITEMS.map((item) => (
              <MenuCheck
                key={item.key}
                checked={zoneTypeVisibility[item.key]}
                colorClass={item.colorClass}
                disabled={!showZones}
                label={item.label}
                onChange={(checked) => setZoneTypeVisible(item.key, checked)}
              />
            ))}
            <MenuCheck checked={showStructure} colorClass="bg-blue-400" label="Structure + ZigZag" onChange={setShowStructure} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function MenuCheck({
  checked,
  colorClass,
  disabled = false,
  label,
  onChange,
}: {
  checked: boolean;
  colorClass?: string;
  disabled?: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className={`flex items-center gap-2 rounded px-1.5 py-1 ${disabled ? "opacity-40" : "hover:bg-ink-800"}`}>
      <input
        checked={checked}
        className="accent-cyan-400"
        disabled={disabled}
        type="checkbox"
        onChange={(event) => onChange(event.target.checked)}
      />
      {colorClass ? <span className={`h-2.5 w-2.5 rounded-full ${colorClass}`} /> : null}
      <span>{label}</span>
    </label>
  );
}

const LAYER_ITEMS: Array<{ key: ZoneVisibilityKey; label: string; colorClass: string }> = [
  { key: "support", label: "Support", colorClass: "bg-emerald-400" },
  { key: "resistance", label: "Resistance", colorClass: "bg-rose-400" },
  { key: "order_block", label: "Order Blocks", colorClass: "bg-cyan-300" },
  { key: "fvg", label: "Fair Value Gaps", colorClass: "bg-lime-300" },
  { key: "liquidity_pool", label: "Liquidity Pools", colorClass: "bg-yellow-300" },
  { key: "consolidation", label: "Consolidation", colorClass: "bg-sky-300" },
];

const PLAYBOOK_ITEMS: Array<{ key: PlaybookKey; label: string }> = [
  { key: "zone_reaction_v2", label: "Zone Reaction V2" },
  { key: "sr_breakout_v1", label: "SR Breakout V1" },
];

function playbookRequirementLabel(playbook: PlaybookKey): string {
  const labels: Record<ZoneVisibilityKey, string> = {
    support: "Support",
    resistance: "Resistance",
    order_block: "OB",
    fvg: "FVG",
    liquidity_pool: "Liquidity",
    consolidation: "Consolidation",
  };
  const requirements = playbookLayerRequirements[playbook];
  const zoneLabels = requirements.zones.map((zoneType) => labels[zoneType]).join(", ");
  return `Layers: ${zoneLabels}${requirements.structure ? " + Structure" : ""}`;
}
