import { Activity, ChevronDown, ChevronLeft, ChevronRight, Eye, Layers, LogOut, MoreHorizontal, PanelBottomOpen, Pause, Play, Plus, RefreshCw, Rows3, Target, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { clearStoredRefreshToken, getStoredRefreshToken, logout } from "../api/auth";
import type { NewsResponse } from "../api/chart";
import { useAuthStore } from "../store/authStore";
import { playbookLayerRequirements, useChartStore } from "../store/chartStore";
import type { AddEntityKind, PlaybookKey, Timeframe, TradeVisibilityMode, ZoneVisibilityKey } from "../types";
import { MobileBottomSheet } from "./mobile/MobileBottomSheet";
import { ManualAiModal } from "./ManualAiModal";
import { NewsPill } from "./NewsWidget";

type TopBarProps = {
  isFetching: boolean;
  mode: "dashboard" | "replay";
  currentPrice?: number | null;
  priceChangePercent?: number | null;
  onOpenInspector: () => void;
  onRefresh: () => void;
  newsData?: NewsResponse | null;
};

type MobilePanel = "layers" | "draw" | "more" | null;

export function TopBar({ currentPrice, isFetching, mode, onOpenInspector, onRefresh, priceChangePercent, newsData }: TopBarProps) {
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
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>(null);
  const [manualAiOpen, setManualAiOpen] = useState(false);
  // H1 is the only zone/context timeframe; manual zones on M15 are rejected by
  // the API (422), so the draw entry point is disabled while viewing M15 to
  // avoid a dead-end UX (draw -> submit -> error).
  const canAddEntity = timeframe === "H1";
  const canCreateManualAi = mode === "dashboard" && startIndex === null;

  useEffect(() => {
    if (!canCreateManualAi) {
      setManualAiOpen(false);
    }
  }, [canCreateManualAi]);

  const priceTone = (priceChangePercent ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300";

  return (
    <>
    <header className="flex h-12 items-center justify-between border-b border-ink-700 bg-ink-900/95 px-3 backdrop-blur lg:hidden">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold tracking-wide text-slate-100">XAUUSD</span>
          <span className={`text-xs font-semibold tabular-nums ${priceTone}`}>
            {typeof currentPrice === "number" ? currentPrice.toFixed(2) : "--"}
          </span>
          {typeof priceChangePercent === "number" ? (
            <span className={`text-[10px] tabular-nums ${priceTone}`}>
              {priceChangePercent > 0 ? "+" : ""}{priceChangePercent.toFixed(2)}%
            </span>
          ) : null}
        </div>
        <div className="mt-0.5 text-[10px] text-slate-500">
          {mode === "replay" ? "Replay" : startIndex === null ? "Realtime · Latest" : `History · ${startIndex}`}
        </div>
      </div>
      <div className="flex items-center gap-1.5">
        <button
          className="h-10 min-w-12 rounded-lg border border-cyan-400/35 bg-cyan-400/10 px-3 text-sm font-bold text-cyan-100 active:bg-cyan-400/20"
          type="button"
          onClick={() => setTimeframe(timeframe === "H1" ? "M15" : "H1")}
        >
          {timeframe}
        </button>
        <button
          aria-label="Reload chart"
          className="grid h-10 w-10 place-items-center rounded-lg border border-ink-700 bg-ink-800 text-slate-300 active:border-cyan-400"
          type="button"
          onClick={onRefresh}
        >
          <RefreshCw className={isFetching ? "animate-spin" : ""} size={18} />
        </button>
      </div>
    </header>

    <header className="hidden h-14 items-center justify-between gap-4 border-b border-ink-700 bg-ink-900 px-4 lg:flex">
      <div className="flex items-center gap-3 font-semibold text-slate-100">
        <span className="flex h-8 w-8 items-center justify-center rounded-md border border-slate-700 bg-ink-800 text-cyan-300">
          <Activity size={18} />
        </span>
        <span className="whitespace-nowrap">XAUUSD Control</span>
      </div>

      <div className="flex min-w-0 items-center gap-2">
        <div
          className="flex h-9 items-center overflow-hidden rounded-md border border-ink-700 bg-ink-850"
        >
          <span className="flex h-full items-center px-2 text-cyan-300">
            <Plus size={15} />
          </span>
          <select
            className="h-full min-w-[150px] bg-transparent pr-2 text-sm text-slate-100 outline-none disabled:cursor-not-allowed"
            title={canCreateManualAi ? "Add a chart zone or create a Manual AI trade plan" : "Manual AI is only available in Realtime · Latest"}
            value={addEntityKind ?? ""}
            onChange={(event) => {
              if (event.target.value === "manual_ai") {
                setAddEntityKind(null);
                setManualAiOpen(true);
                return;
              }
              setAddEntityKind((event.target.value || null) as AddEntityKind | null);
            }}
          >
            <option value="">Add entity</option>
            <option disabled={!canCreateManualAi} value="manual_ai">Manual AI trade…</option>
            <option disabled={!canAddEntity} value="support">Support</option>
            <option disabled={!canAddEntity} value="resistance">Resistance</option>
            <option disabled={!canAddEntity} value="demand_order_block">Demand OB</option>
            <option disabled={!canAddEntity} value="supply_order_block">Supply OB</option>
            <option disabled={!canAddEntity} value="bullish_fvg">Bullish FVG</option>
            <option disabled={!canAddEntity} value="bearish_fvg">Bearish FVG</option>
            <option disabled={!canAddEntity} value="consolidation">Consolidation</option>
            <option disabled={!canAddEntity} value="buy_side_liquidity">Buy Liquidity Zone</option>
            <option disabled={!canAddEntity} value="sell_side_liquidity">Sell Liquidity Zone</option>
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
          <option value="H1">H1</option>
          <option value="M15">M15</option>
          <option value="M5">M5</option>
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
        {newsData && <NewsPill data={newsData} />}
        <LogoutButton />
      </div>
    </header>

    <nav className="fixed inset-x-0 bottom-0 z-[65] grid h-[calc(3.75rem+env(safe-area-inset-bottom))] grid-cols-5 border-t border-ink-600 bg-ink-900/95 px-1 pb-[env(safe-area-inset-bottom)] shadow-[0_-8px_30px_rgba(0,0,0,0.35)] backdrop-blur lg:hidden">
      <MobileDockButton label={timeframe} icon={<Activity size={19} />} onClick={() => setTimeframe(timeframe === "H1" ? "M15" : "H1")} active />
      <MobileDockButton label="Layers" icon={<Layers size={19} />} onClick={() => setMobilePanel("layers")} />
      <MobileDockButton label="Add" icon={<Plus size={20} />} onClick={() => setMobilePanel("draw")} active={Boolean(addEntityKind)} />
      <MobileDockButton label="Inspect" icon={<PanelBottomOpen size={19} />} onClick={onOpenInspector} />
      <MobileDockButton label="More" icon={<MoreHorizontal size={20} />} onClick={() => setMobilePanel("more")} />
    </nav>

    <MobileBottomSheet open={mobilePanel === "layers"} onClose={() => setMobilePanel(null)} title="Chart layers">
      <MobileLayersPanel />
    </MobileBottomSheet>
    <MobileBottomSheet open={mobilePanel === "draw"} onClose={() => setMobilePanel(null)} title="Draw on H1 chart">
      <MobileDrawPanel
        selected={addEntityKind}
        canDrawZones={canAddEntity}
        canCreateManualAi={canCreateManualAi}
        onManualAi={() => { setMobilePanel(null); setManualAiOpen(true); }}
        onSelect={(kind) => {
          setAddEntityKind(kind);
          setMobilePanel(null);
        }}
      />
    </MobileBottomSheet>
    <ManualAiModal currentPrice={currentPrice ?? null} open={manualAiOpen} onChanged={onRefresh} onClose={() => setManualAiOpen(false)} />
    <MobileBottomSheet open={mobilePanel === "more"} onClose={() => setMobilePanel(null)} title="Chart settings">
      <MobileMorePanel
        autoRefreshActive={autoRefreshActive}
        isFetching={isFetching}
        limit={limit}
        mode={mode}
        newsData={newsData}
        onClose={() => setMobilePanel(null)}
        onRefresh={onRefresh}
        startIndex={startIndex}
      />
    </MobileBottomSheet>
    </>
  );
}

function MobileDockButton({
  active = false,
  disabled = false,
  icon,
  label,
  onClick,
}: {
  active?: boolean;
  disabled?: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      className={`flex min-w-0 flex-col items-center justify-center gap-0.5 text-[10px] font-semibold transition active:bg-ink-700 ${
        active ? "text-cyan-300" : "text-slate-400"
      } disabled:opacity-35`}
      disabled={disabled}
      type="button"
      onClick={onClick}
    >
      {icon}
      <span className="truncate">{label}</span>
    </button>
  );
}

function MobileLayersPanel() {
  const activeZonesOnly = useChartStore((state) => state.activeZonesOnly);
  const showZones = useChartStore((state) => state.showZones);
  const zoneTypeVisibility = useChartStore((state) => state.zoneTypeVisibility);
  const showStructure = useChartStore((state) => state.showStructure);
  const tradeVisibilityMode = useChartStore((state) => state.tradeVisibilityMode);
  const importantZonesOnly = useChartStore((state) => state.importantZonesOnly);
  const maxVisibleZones = useChartStore((state) => state.maxVisibleZones);
  const selectedPlaybooks = useChartStore((state) => state.selectedPlaybooks);
  const setActiveZonesOnly = useChartStore((state) => state.setActiveZonesOnly);
  const setShowZones = useChartStore((state) => state.setShowZones);
  const setZoneTypeVisible = useChartStore((state) => state.setZoneTypeVisible);
  const setShowStructure = useChartStore((state) => state.setShowStructure);
  const setTradeVisibilityMode = useChartStore((state) => state.setTradeVisibilityMode);
  const setImportantZonesOnly = useChartStore((state) => state.setImportantZonesOnly);
  const setMaxVisibleZones = useChartStore((state) => state.setMaxVisibleZones);
  const requiredZones = new Set(selectedPlaybooks.flatMap((playbook) => playbookLayerRequirements[playbook].zones));
  const structureRequired = selectedPlaybooks.some((playbook) => playbookLayerRequirements[playbook].structure);

  return (
    <div className="grid gap-2 p-4">
      <MobileToggleRow checked={importantZonesOnly} label="Important zones only" onChange={setImportantZonesOnly} />
      <label className="flex min-h-12 items-center gap-3 rounded-xl border border-ink-700 bg-ink-850 px-3 text-sm text-slate-200">
        <span className="flex-1">Maximum visible zones</span>
        <input
          className="h-10 w-20 rounded-lg border border-ink-600 bg-ink-950 px-2 text-center text-sm tabular-nums outline-none"
          max={40}
          min={1}
          type="number"
          value={maxVisibleZones}
          onChange={(event) => setMaxVisibleZones(Number(event.target.value))}
        />
      </label>
      <MobileToggleRow checked={activeZonesOnly} label="Active zones only" onChange={setActiveZonesOnly} />
      <MobileToggleRow checked={showZones} label="Price zones" onChange={setShowZones} />
      <div className="grid grid-cols-2 gap-2">
        {LAYER_ITEMS.map((item) => (
          <MobileToggleRow
            key={item.key}
            checked={zoneTypeVisibility[item.key]}
            compact
            disabled={!showZones || requiredZones.has(item.key)}
            label={item.label}
            onChange={(checked) => setZoneTypeVisible(item.key, checked)}
          />
        ))}
      </div>
      <MobileToggleRow checked={showStructure} disabled={structureRequired} label="Structure + ZigZag" onChange={setShowStructure} />
      <label className="flex min-h-12 items-center gap-3 rounded-xl border border-ink-700 bg-ink-850 px-3 text-sm text-slate-200">
        <span className="flex-1">Trades</span>
        <select
          className="h-10 rounded-lg border border-ink-600 bg-ink-950 px-2 text-sm outline-none"
          value={tradeVisibilityMode}
          onChange={(event) => setTradeVisibilityMode(event.target.value as TradeVisibilityMode)}
        >
          <option value="visible">Visible</option>
          <option value="hidden">Hidden</option>
          <option value="all">All</option>
          <option value="off">Off</option>
        </select>
      </label>
      <p className="px-1 text-[11px] leading-relaxed text-slate-500">
        Layers required by an active playbook stay enabled automatically.
      </p>
    </div>
  );
}

function MobileToggleRow({
  checked,
  compact = false,
  disabled = false,
  label,
  onChange,
}: {
  checked: boolean;
  compact?: boolean;
  disabled?: boolean;
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className={`flex min-h-12 items-center gap-2 rounded-xl border border-ink-700 bg-ink-850 px-3 text-sm ${disabled ? "opacity-50" : "text-slate-200"}`}>
      <span className={`min-w-0 flex-1 ${compact ? "text-xs" : ""}`}>{label}</span>
      <input
        checked={checked}
        className="h-5 w-5 accent-cyan-400"
        disabled={disabled}
        type="checkbox"
        onChange={(event) => onChange(event.target.checked)}
      />
    </label>
  );
}

const MOBILE_DRAW_ITEMS: Array<{ kind: AddEntityKind; label: string; description: string }> = [
  { kind: "support", label: "Support", description: "Manual H1 support zone" },
  { kind: "resistance", label: "Resistance", description: "Manual H1 resistance zone" },
  { kind: "demand_order_block", label: "Demand OB", description: "Bullish order block" },
  { kind: "supply_order_block", label: "Supply OB", description: "Bearish order block" },
  { kind: "bullish_fvg", label: "Bullish FVG", description: "Bullish imbalance" },
  { kind: "bearish_fvg", label: "Bearish FVG", description: "Bearish imbalance" },
  { kind: "consolidation", label: "Consolidation", description: "Range or compression box" },
  { kind: "buy_side_liquidity", label: "Buy liquidity", description: "Liquidity above highs" },
  { kind: "sell_side_liquidity", label: "Sell liquidity", description: "Liquidity below lows" },
];

function MobileDrawPanel({ canCreateManualAi, canDrawZones, onManualAi, selected, onSelect }: { canCreateManualAi: boolean; canDrawZones: boolean; onManualAi: () => void; selected: AddEntityKind | null; onSelect: (kind: AddEntityKind) => void }) {
  return (
    <div className="grid grid-cols-2 gap-2 p-4">
      <button className="col-span-2 min-h-16 rounded-xl border border-cyan-400/40 bg-cyan-400/10 p-3 text-left disabled:cursor-not-allowed disabled:opacity-35" disabled={!canCreateManualAi} type="button" onClick={onManualAi}>
        <span className="block text-sm font-semibold text-cyan-100">Manual AI trade</span>
        <span className="mt-1 block text-[11px] text-cyan-200/60">Import AI JSON hoặc nhập limit plan thủ công</span>
      </button>
      {MOBILE_DRAW_ITEMS.map((item) => (
        <button
          key={item.kind}
          className={`min-h-20 rounded-xl border p-3 text-left active:scale-[0.99] ${
            selected === item.kind ? "border-cyan-400 bg-cyan-400/10" : "border-ink-700 bg-ink-850"
          } disabled:opacity-35`}
          disabled={!canDrawZones}
          type="button"
          onClick={() => onSelect(item.kind)}
        >
          <span className="block text-sm font-semibold text-slate-100">{item.label}</span>
          <span className="mt-1 block text-[11px] leading-snug text-slate-500">{item.description}</span>
        </button>
      ))}
    </div>
  );
}

function MobileMorePanel({
  autoRefreshActive,
  isFetching,
  limit,
  mode,
  newsData,
  onClose,
  onRefresh,
  startIndex,
}: {
  autoRefreshActive: boolean;
  isFetching: boolean;
  limit: number;
  mode: "dashboard" | "replay";
  newsData?: NewsResponse | null;
  onClose: () => void;
  onRefresh: () => void;
  startIndex: number | null;
}) {
  const autoRefreshEnabled = useChartStore((state) => state.autoRefreshEnabled);
  const selectedPlaybooks = useChartStore((state) => state.selectedPlaybooks);
  const setAutoRefreshEnabled = useChartStore((state) => state.setAutoRefreshEnabled);
  const setLimit = useChartStore((state) => state.setLimit);
  const setStartIndex = useChartStore((state) => state.setStartIndex);
  const shiftStartIndex = useChartStore((state) => state.shiftStartIndex);
  const toggleSelectedPlaybook = useChartStore((state) => state.toggleSelectedPlaybook);

  return (
    <div className="grid gap-4 p-4">
      <div className="grid grid-cols-2 gap-2">
        <a className={`grid h-12 place-items-center rounded-xl border text-sm font-semibold ${mode === "dashboard" ? "border-cyan-400 bg-cyan-400/10 text-cyan-100" : "border-ink-700 bg-ink-850 text-slate-300"}`} href="/">
          Realtime
        </a>
        <a className={`grid h-12 place-items-center rounded-xl border text-sm font-semibold ${mode === "replay" ? "border-cyan-400 bg-cyan-400/10 text-cyan-100" : "border-ink-700 bg-ink-850 text-slate-300"}`} href="/replay-chart">
          Replay
        </a>
      </div>

      <section className="grid gap-2">
        <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">Candle window</div>
        <div className="grid grid-cols-2 gap-2">
          <label className="grid gap-1 text-xs text-slate-500">
            Limit
            <input className="h-11 rounded-xl border border-ink-700 bg-ink-850 px-3 text-sm text-slate-100 outline-none" min={50} max={15000} step={50} type="number" value={limit} onChange={(event) => setLimit(Number(event.target.value))} />
          </label>
          <label className="grid gap-1 text-xs text-slate-500">
            Start index
            <input className="h-11 rounded-xl border border-ink-700 bg-ink-850 px-3 text-sm text-slate-100 outline-none" min={0} placeholder="Latest" type="number" value={startIndex ?? ""} onChange={(event) => setStartIndex(event.target.value === "" ? null : Number(event.target.value))} />
          </label>
        </div>
        <div className="grid grid-cols-4 gap-2">
          <MobileSmallButton label="Prev" disabled={startIndex === null || startIndex <= 0} onClick={() => shiftStartIndex(-limit)} />
          <MobileSmallButton label="Next" onClick={() => shiftStartIndex(limit)} />
          <MobileSmallButton label="First" onClick={() => setStartIndex(0)} />
          <MobileSmallButton label="Latest" onClick={() => setStartIndex(null)} />
        </div>
      </section>

      <section className="grid gap-2">
        <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">Playbooks</div>
        {PLAYBOOK_ITEMS.map((item) => (
          <MobileToggleRow
            key={item.key}
            checked={selectedPlaybooks.includes(item.key)}
            label={item.label}
            onChange={(checked) => toggleSelectedPlaybook(item.key, checked)}
          />
        ))}
      </section>

      <MobileToggleRow checked={autoRefreshEnabled} label={autoRefreshActive ? "Auto refresh every 60s" : "Auto refresh (paused in history)"} onChange={setAutoRefreshEnabled} />
      <button className="flex h-12 items-center justify-center gap-2 rounded-xl border border-ink-700 bg-ink-850 text-sm font-semibold text-slate-200" type="button" onClick={() => { onRefresh(); onClose(); }}>
        <RefreshCw className={isFetching ? "animate-spin" : ""} size={17} /> Reload chart
      </button>
      {newsData ? <div className="flex justify-center"><NewsPill data={newsData} /></div> : null}
      <div className="flex justify-end"><LogoutButton /></div>
    </div>
  );
}

function MobileSmallButton({ disabled = false, label, onClick }: { disabled?: boolean; label: string; onClick: () => void }) {
  return <button className="h-11 rounded-xl border border-ink-700 bg-ink-850 text-xs font-semibold text-slate-300 disabled:opacity-35" disabled={disabled} type="button" onClick={onClick}>{label}</button>;
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
  const tradeVisibilityMode = useChartStore((state) => state.tradeVisibilityMode);
  const importantZonesOnly = useChartStore((state) => state.importantZonesOnly);
  const maxVisibleZones = useChartStore((state) => state.maxVisibleZones);
  const setActiveZonesOnly = useChartStore((state) => state.setActiveZonesOnly);
  const setShowZones = useChartStore((state) => state.setShowZones);
  const setZoneTypeVisible = useChartStore((state) => state.setZoneTypeVisible);
  const setAllZoneTypesVisible = useChartStore((state) => state.setAllZoneTypesVisible);
  const setShowStructure = useChartStore((state) => state.setShowStructure);
  const setTradeVisibilityMode = useChartStore((state) => state.setTradeVisibilityMode);
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
  const totalVisibleCount = visibleZoneCount + (showStructure ? 1 : 0) + (tradeVisibilityMode === "off" ? 0 : 1);
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
            <label className="flex items-center gap-2 rounded px-1.5 py-1 text-slate-300">
              <span className="h-2.5 w-2.5 rounded-sm bg-fuchsia-400" />
              <span className="flex-1">Trades</span>
              <select
                className="h-7 rounded border border-ink-700 bg-ink-850 px-2 text-xs text-slate-100 outline-none"
                value={tradeVisibilityMode}
                onChange={(event) => setTradeVisibilityMode(event.target.value as TradeVisibilityMode)}
              >
                <option value="visible">Visible trades</option>
                <option value="hidden">Hidden trades</option>
                <option value="all">All trades</option>
                <option value="off">Off</option>
              </select>
            </label>
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
  { key: "manual_ai_v1", label: "Manual AI" },
  { key: "liquidity_sweep_reclaim_v1", label: "Liquidity Sweep V1" },
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
  const parts = [...(zoneLabels ? [zoneLabels] : []), ...(requirements.structure ? ["Structure + ZigZag"] : [])];
  return `Layers: ${parts.join(" + ") || "None"}`;
}
