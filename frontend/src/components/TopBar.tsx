import { Activity, Check, ChevronDown, ChevronLeft, ChevronRight, Eye, Layers, LogOut, MoreHorizontal, PanelBottomOpen, Pause, Play, Plus, RefreshCw, Rows3, Target, UserRound, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { clearStoredRefreshToken, getStoredRefreshToken, logout } from "../api/auth";
import type { NewsResponse } from "../api/chart";
import { allowedAddEntityKinds, type AddEntityMenuKind } from "../lib/playbookEntities";
import { accountBadgeClass } from "../lib/accountPresentation";
import { formatUtcClock, tradingSessionAt } from "../lib/tradingSession";
import { useAuthStore } from "../store/authStore";
import { enabledPlaybookKeys, playbookLayerRequirements, useChartStore } from "../store/chartStore";
import type { AddEntityKind, PlaybookKey, Timeframe, TradeVisibilityMode, ZoneVisibilityKey } from "../types";
import { MobileBottomSheet } from "./mobile/MobileBottomSheet";
import { ManualAiModal } from "./ManualAiModal";
import { NewsPill } from "./NewsWidget";

type TopBarProps = {
  accountLabels?: string[];
  isFetching: boolean;
  mode: "dashboard" | "replay";
  currentPrice?: number | null;
  priceChangePercent?: number | null;
  onOpenInspector: () => void;
  onRefresh: () => void;
  newsData?: NewsResponse | null;
};

type MobilePanel = "layers" | "draw" | "more" | null;

const MANUAL_AI_V1_ENABLED = false;

export function TopBar({ accountLabels = [], currentPrice, isFetching, mode, onOpenInspector, onRefresh, priceChangePercent, newsData }: TopBarProps) {
  const timeframe = useChartStore((state) => state.timeframe);
  const limit = useChartStore((state) => state.limit);
  const startIndex = useChartStore((state) => state.startIndex);
  const autoRefreshEnabled = useChartStore((state) => state.autoRefreshEnabled);
  const addEntityKind = useChartStore((state) => state.addEntityKind);
  const selectedPlaybooks = useChartStore((state) => state.selectedPlaybooks);
  const setTimeframe = useChartStore((state) => state.setTimeframe);
  const setLimit = useChartStore((state) => state.setLimit);
  const setStartIndex = useChartStore((state) => state.setStartIndex);
  const shiftStartIndex = useChartStore((state) => state.shiftStartIndex);
  const setAutoRefreshEnabled = useChartStore((state) => state.setAutoRefreshEnabled);
  const setAddEntityKind = useChartStore((state) => state.setAddEntityKind);
  const autoRefreshActive = mode === "dashboard" && autoRefreshEnabled && startIndex === null;
  const autoRefreshLabel = autoRefreshEnabled
    ? startIndex === null ? "Auto" : "Paused"
    : "Manual";
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>(null);
  const [manualAiOpen, setManualAiOpen] = useState(false);
  const [clockNow, setClockNow] = useState(() => new Date());
  // H1 is the only zone/context timeframe; manual zones on M15 are rejected by
  // the API (422), so the draw entry point is disabled while viewing M15 to
  // avoid a dead-end UX (draw -> submit -> error).
  const allowedEntityKinds = allowedAddEntityKinds(selectedPlaybooks);
  const zoneEntityOptions = ADD_ENTITY_OPTIONS.filter((option) => allowedEntityKinds.has(option.kind));
  const canAddEntity = timeframe === "H1";
  const canCreateManualAi =
    MANUAL_AI_V1_ENABLED && allowedEntityKinds.has("manual_ai") && mode === "dashboard" && startIndex === null;

  useEffect(() => {
    if (!canCreateManualAi) {
      setManualAiOpen(false);
    }
  }, [canCreateManualAi]);

  useEffect(() => {
    const timer = window.setInterval(() => setClockNow(new Date()), 30_000);
    return () => window.clearInterval(timer);
  }, []);

  const priceTone = (priceChangePercent ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300";
  const currentSession = tradingSessionAt(clockNow);
  const utcClock = formatUtcClock(clockNow);

  return (
    <>
    <header className="relative z-[80] flex h-12 items-center justify-between border-b border-ink-700 bg-ink-900/95 px-3 backdrop-blur lg:hidden">
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
        <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-slate-500">
          <span>{mode === "replay" ? "Replay" : startIndex === null ? "Realtime · Latest" : `History · ${startIndex}`}</span>
          <span aria-hidden="true">·</span>
          <span className={currentSession.textClass}>{currentSession.label}</span>
          <span>{utcClock} UTC</span>
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

    <header className="relative z-[80] hidden h-14 items-center justify-between gap-4 border-b border-ink-700 bg-ink-900 px-4 lg:flex">
      <div className="flex shrink-0 items-center gap-2.5 text-slate-100">
        <span className="whitespace-nowrap text-base font-semibold">XAUUSD</span>
        <span
          className={`inline-flex h-7 items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 text-[11px] font-medium ${currentSession.badgeClass}`}
          title={`${currentSession.label}: ${currentSession.startUtc}–${currentSession.endUtc} UTC`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${currentSession.dotClass}`} aria-hidden="true" />
          <span>{currentSession.label}</span>
          <span className="opacity-60">{utcClock} UTC</span>
        </span>
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
            title={MANUAL_AI_V1_ENABLED
              ? (canCreateManualAi ? "Add a chart zone or create a Manual AI trade plan" : "Manual AI is only available in Realtime · Latest")
              : "Manual AI V1 is temporarily paused"}
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
            {allowedEntityKinds.has("manual_ai") ? (
              <option disabled={!canCreateManualAi} value="manual_ai">Manual AI trade…</option>
            ) : null}
            {zoneEntityOptions.map((option) => (
              <option disabled={option.kind.startsWith("line_") ? mode !== "dashboard" || startIndex !== null : !canAddEntity} key={option.kind} value={option.kind}>{option.label}</option>
            ))}
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
          className="h-9 w-20 rounded-md border border-ink-700 bg-ink-850 px-3 text-sm text-slate-100 outline-none"
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
        <TradeAccountSelect accountLabels={accountLabels} />
        <button
          className={`inline-flex h-9 w-[92px] shrink-0 items-center justify-center gap-2 rounded-md border px-2 text-sm transition ${
            autoRefreshActive
              ? "border-cyan-500/60 bg-cyan-400/10 text-cyan-100"
              : "border-ink-700 bg-ink-800 text-slate-300 hover:border-cyan-500"
          }`}
          title={startIndex === null ? "Toggle auto refresh every 60 seconds" : "Auto refresh is paused while viewing historical windows"}
          type="button"
          onClick={() => setAutoRefreshEnabled(!autoRefreshEnabled)}
        >
          {autoRefreshEnabled ? <Pause size={15} /> : <Play size={15} />}
          <span>{autoRefreshLabel}</span>
        </button>
        <button
          aria-label="Reload chart"
          className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-ink-700 bg-ink-800 text-slate-100 hover:border-cyan-500"
          title="Reload chart"
          type="button"
          onClick={onRefresh}
        >
          <RefreshCw className={isFetching ? "animate-spin" : ""} size={15} />
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
      <MobileLayersPanel accountLabels={accountLabels} />
    </MobileBottomSheet>
    <MobileBottomSheet open={mobilePanel === "draw"} onClose={() => setMobilePanel(null)} title="Draw on H1 chart">
      <MobileDrawPanel
        selected={addEntityKind}
        canDrawZones={canAddEntity}
        canCreateManualAi={canCreateManualAi}
        allowedEntityKinds={allowedEntityKinds}
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

function MobileLayersPanel({ accountLabels }: { accountLabels: string[] }) {
  const timeframe = useChartStore((state) => state.timeframe);
  const activeZonesOnly = useChartStore((state) => state.activeZonesOnly);
  const showZones = useChartStore((state) => state.showZones);
  const zoneTypeVisibility = useChartStore((state) => state.zoneTypeVisibility);
  const showStructure = useChartStore((state) => state.showStructure);
  const showIntradayLevels = useChartStore((state) => state.showIntradayLevels);
  const showBrokenIntradayLevels = useChartStore((state) => state.showBrokenIntradayLevels);
  const showH1ImpulseCandidates = useChartStore((state) => state.showH1ImpulseCandidates);
  const h1ImpulseEligibleOnly = useChartStore((state) => state.h1ImpulseEligibleOnly);
  const tradeVisibilityMode = useChartStore((state) => state.tradeVisibilityMode);
  const importantZonesOnly = useChartStore((state) => state.importantZonesOnly);
  const maxVisibleZones = useChartStore((state) => state.maxVisibleZones);
  const selectedPlaybooks = useChartStore((state) => state.selectedPlaybooks);
  const showHistoricalLiquiditySweeps = useChartStore((state) => state.showHistoricalLiquiditySweeps);
  const setActiveZonesOnly = useChartStore((state) => state.setActiveZonesOnly);
  const setShowZones = useChartStore((state) => state.setShowZones);
  const setZoneTypeVisible = useChartStore((state) => state.setZoneTypeVisible);
  const setShowStructure = useChartStore((state) => state.setShowStructure);
  const setShowIntradayLevels = useChartStore((state) => state.setShowIntradayLevels);
  const setShowBrokenIntradayLevels = useChartStore((state) => state.setShowBrokenIntradayLevels);
  const setShowH1ImpulseCandidates = useChartStore((state) => state.setShowH1ImpulseCandidates);
  const setH1ImpulseEligibleOnly = useChartStore((state) => state.setH1ImpulseEligibleOnly);
  const setTradeVisibilityMode = useChartStore((state) => state.setTradeVisibilityMode);
  const setImportantZonesOnly = useChartStore((state) => state.setImportantZonesOnly);
  const setMaxVisibleZones = useChartStore((state) => state.setMaxVisibleZones);
  const setShowHistoricalLiquiditySweeps = useChartStore((state) => state.setShowHistoricalLiquiditySweeps);
  const requiredZones = new Set(selectedPlaybooks.flatMap((playbook) => playbookLayerRequirements[playbook].zones));
  const structureRequired = selectedPlaybooks.some((playbook) => playbookLayerRequirements[playbook].structure);
  const h1ImpulseSelected = selectedPlaybooks.includes("h1_impulse_retest_v1");

  return (
    <div className="grid gap-2 p-4">
      <label className="flex min-h-12 items-center gap-3 rounded-xl border border-cyan-400/30 bg-cyan-400/5 px-3 text-sm text-cyan-100">
        <span className="flex-1 font-semibold">Trade account</span>
        <TradeAccountSelect accountLabels={accountLabels} mobile />
      </label>
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
      {selectedPlaybooks.includes("liquidity_sweep_reclaim_v1") ? (
        <MobileToggleRow
          checked={showHistoricalLiquiditySweeps}
          label="Show historical sweeps"
          onChange={setShowHistoricalLiquiditySweeps}
        />
      ) : null}
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
      <MobileToggleRow checked={showIntradayLevels} label="Intraday liquidity levels" onChange={setShowIntradayLevels} />
      <MobileToggleRow
        checked={showBrokenIntradayLevels}
        disabled={!showIntradayLevels}
        label="Nearby broken levels (≤3 ATR)"
        onChange={setShowBrokenIntradayLevels}
      />
      {h1ImpulseSelected ? (
        <>
          <MobileToggleRow
            checked={showH1ImpulseCandidates}
            disabled={timeframe !== "H1"}
            label="H1 impulse candidates"
            onChange={setShowH1ImpulseCandidates}
          />
          <MobileToggleRow
            checked={h1ImpulseEligibleOnly}
            disabled={timeframe !== "H1" || !showH1ImpulseCandidates}
            label="Eligible H1 signals only"
            onChange={setH1ImpulseEligibleOnly}
          />
        </>
      ) : null}
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

function TradeAccountSelect({ accountLabels, mobile = false }: { accountLabels: string[]; mobile?: boolean }) {
  const selectedAccount = useChartStore((state) => state.tradeAccountLabel);
  const setSelectedAccount = useChartStore((state) => state.setTradeAccountLabel);
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const options = selectedAccount && !accountLabels.includes(selectedAccount)
    ? [selectedAccount, ...accountLabels]
    : accountLabels;

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  if (!mobile) {
    const selectedTone = selectedAccount
      ? accountBadgeClass(selectedAccount)
      : "border-ink-700 bg-ink-800 text-slate-300";
    return (
      <div ref={menuRef} className="relative">
        <button
          aria-expanded={open}
          aria-label={`Trade account: ${selectedAccount ?? "All accounts"}`}
          className={`inline-flex h-9 items-center gap-1.5 rounded-md border px-2 text-sm font-semibold transition hover:brightness-125 ${selectedTone}`}
          title={`Trade account · ${selectedAccount ?? "All accounts"}`}
          type="button"
          onClick={() => setOpen((value) => !value)}
        >
          <UserRound size={14} />
          <span>Acc</span>
          <ChevronDown className={open ? "rotate-180 transition" : "transition"} size={13} />
        </button>
        {open ? (
          <div className="absolute right-0 top-11 z-50 grid w-60 gap-1 rounded-md border border-ink-700 bg-ink-900 p-2 shadow-2xl shadow-black/40">
            <button
              className={`flex items-center gap-2 rounded-md border px-2.5 py-2 text-left text-xs transition ${selectedAccount === null ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-100" : "border-transparent text-slate-400 hover:bg-ink-800 hover:text-slate-100"}`}
              type="button"
              onClick={() => { setSelectedAccount(null); setOpen(false); }}
            >
              <span className="flex-1">All accounts</span>
              {selectedAccount === null ? <Check size={13} /> : null}
            </button>
            {options.map((label) => (
              <button
                className={`flex items-center gap-2 rounded-md border px-2.5 py-2 text-left text-xs font-semibold transition hover:brightness-125 ${accountBadgeClass(label)}`}
                key={label}
                title={label}
                type="button"
                onClick={() => { setSelectedAccount(label); setOpen(false); }}
              >
                <span className="min-w-0 flex-1 truncate">{label}</span>
                {selectedAccount === label ? <Check size={13} /> : null}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <select
      aria-label="Trade account"
      className={`h-10 min-w-0 max-w-[12rem] rounded-lg border px-2 text-sm outline-none ${selectedAccount ? accountBadgeClass(selectedAccount) : "border-ink-600 bg-ink-950 text-slate-100"}`}
      title="Filter chart trades and Trade History by account"
      value={selectedAccount ?? ""}
      onChange={(event) => setSelectedAccount(event.target.value || null)}
    >
      <option value="">All accounts</option>
      {options.map((label) => <option key={label} value={label}>{label}</option>)}
    </select>
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
  { kind: "line_buy", label: "Add line buy", description: "Click hai điểm để vẽ line Long" },
  { kind: "line_sell", label: "Add line sell", description: "Click hai điểm để vẽ line Short" },
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

function MobileDrawPanel({ allowedEntityKinds, canCreateManualAi, canDrawZones, onManualAi, selected, onSelect }: { allowedEntityKinds: Set<AddEntityMenuKind>; canCreateManualAi: boolean; canDrawZones: boolean; onManualAi: () => void; selected: AddEntityKind | null; onSelect: (kind: AddEntityKind) => void }) {
  const drawItems = MOBILE_DRAW_ITEMS.filter((item) => allowedEntityKinds.has(item.kind));
  return (
    <div className="grid grid-cols-2 gap-2 p-4">
      {allowedEntityKinds.has("manual_ai") ? (
        <button className="col-span-2 min-h-16 rounded-xl border border-cyan-400/40 bg-cyan-400/10 p-3 text-left disabled:cursor-not-allowed disabled:opacity-35" disabled={!canCreateManualAi} type="button" onClick={onManualAi}>
          <span className="block text-sm font-semibold text-cyan-100">Manual AI trade</span>
          <span className="mt-1 block text-[11px] text-cyan-200/60">Import AI JSON hoặc nhập limit plan thủ công</span>
        </button>
      ) : null}
      {drawItems.map((item) => (
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
            disabled={item.disabled}
            label={`${item.label}${item.disabled ? " · Paused" : ""}`}
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
  const showHistoricalLiquiditySweeps = useChartStore((state) => state.showHistoricalLiquiditySweeps);
  const setShowHistoricalLiquiditySweeps = useChartStore((state) => state.setShowHistoricalLiquiditySweeps);
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
              <label key={item.key} className={`grid gap-0.5 rounded px-1.5 py-1.5 ${item.disabled ? "cursor-not-allowed opacity-45" : "cursor-pointer hover:bg-ink-800/70"}`}>
                <span className="flex items-center gap-2">
                  <input
                    checked={selectedPlaybooks.includes(item.key)}
                    className="accent-cyan-400"
                    disabled={item.disabled}
                    onChange={(event) => toggleSelectedPlaybook(item.key, event.target.checked)}
                    type="checkbox"
                  />
                  <span className="font-medium text-slate-100">{item.label}{item.disabled ? " · Paused" : ""}</span>
                </span>
                <span className="pl-6 text-[11px] text-slate-500">{playbookRequirementLabel(item.key)}</span>
              </label>
            ))}
          </div>
          {selectedPlaybooks.includes("liquidity_sweep_reclaim_v1") ? (
            <label className="mt-2 flex cursor-pointer items-center gap-2 rounded border border-yellow-300/20 bg-yellow-300/5 px-2 py-2 text-yellow-100">
              <input
                checked={showHistoricalLiquiditySweeps}
                className="accent-yellow-300"
                type="checkbox"
                onChange={(event) => setShowHistoricalLiquiditySweeps(event.target.checked)}
              />
              <span>
                <span className="block text-xs font-semibold">Show historical sweeps</span>
                <span className="block text-[10px] text-yellow-100/55">Research only · includes swept detector zones</span>
              </span>
            </label>
          ) : null}
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
  const showIntradayLevels = useChartStore((state) => state.showIntradayLevels);
  const showBrokenIntradayLevels = useChartStore((state) => state.showBrokenIntradayLevels);
  const showH1ImpulseCandidates = useChartStore((state) => state.showH1ImpulseCandidates);
  const h1ImpulseEligibleOnly = useChartStore((state) => state.h1ImpulseEligibleOnly);
  const timeframe = useChartStore((state) => state.timeframe);
  const tradeVisibilityMode = useChartStore((state) => state.tradeVisibilityMode);
  const importantZonesOnly = useChartStore((state) => state.importantZonesOnly);
  const maxVisibleZones = useChartStore((state) => state.maxVisibleZones);
  const setActiveZonesOnly = useChartStore((state) => state.setActiveZonesOnly);
  const setShowZones = useChartStore((state) => state.setShowZones);
  const setZoneTypeVisible = useChartStore((state) => state.setZoneTypeVisible);
  const setAllZoneTypesVisible = useChartStore((state) => state.setAllZoneTypesVisible);
  const setShowStructure = useChartStore((state) => state.setShowStructure);
  const setShowIntradayLevels = useChartStore((state) => state.setShowIntradayLevels);
  const setShowBrokenIntradayLevels = useChartStore((state) => state.setShowBrokenIntradayLevels);
  const setShowH1ImpulseCandidates = useChartStore((state) => state.setShowH1ImpulseCandidates);
  const setH1ImpulseEligibleOnly = useChartStore((state) => state.setH1ImpulseEligibleOnly);
  const setTradeVisibilityMode = useChartStore((state) => state.setTradeVisibilityMode);
  const setImportantZonesOnly = useChartStore((state) => state.setImportantZonesOnly);
  const setMaxVisibleZones = useChartStore((state) => state.setMaxVisibleZones);
  const selectedPlaybooks = useChartStore((state) => state.selectedPlaybooks);

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
  const h1ImpulseSelected = selectedPlaybooks.includes("h1_impulse_retest_v1");
  const structureRequired = selectedPlaybooks.some((playbook) => playbookLayerRequirements[playbook].structure);
  const totalVisibleCount = visibleZoneCount + (showStructure ? 1 : 0) + (showIntradayLevels ? 1 : 0) + (h1ImpulseSelected && showH1ImpulseCandidates && timeframe === "H1" ? 1 : 0) + (tradeVisibilityMode === "off" ? 0 : 1);
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
        <span className="inline-flex w-6 shrink-0 justify-center rounded bg-ink-950 py-0.5 text-[11px] tabular-nums text-slate-400">
          {totalVisibleCount}
        </span>
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
            <MenuCheck checked={showStructure} colorClass="bg-blue-400" disabled={structureRequired} label="Structure + ZigZag" onChange={setShowStructure} />
            <MenuCheck checked={showIntradayLevels} colorClass="bg-amber-300" label="Intraday liquidity levels" onChange={setShowIntradayLevels} />
            <MenuCheck
              checked={showBrokenIntradayLevels}
              colorClass="bg-slate-500"
              disabled={!showIntradayLevels}
              label="Nearby broken levels (≤3 ATR)"
              onChange={setShowBrokenIntradayLevels}
            />
            {h1ImpulseSelected ? (
              <>
                <MenuCheck
                  checked={showH1ImpulseCandidates}
                  colorClass="bg-amber-300"
                  disabled={timeframe !== "H1"}
                  label="H1 impulse candidates"
                  onChange={setShowH1ImpulseCandidates}
                />
                <MenuCheck
                  checked={h1ImpulseEligibleOnly}
                  disabled={timeframe !== "H1" || !showH1ImpulseCandidates}
                  label="Eligible signals only"
                  onChange={setH1ImpulseEligibleOnly}
                />
              </>
            ) : null}
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

const PLAYBOOK_ITEMS: Array<{ key: PlaybookKey; label: string; disabled?: boolean }> = [
  { key: "zone_reaction_v2", label: "Zone Reaction V2", disabled: !enabledPlaybookKeys.has("zone_reaction_v2") },
  { key: "sr_breakout_v1", label: "SR Breakout V1", disabled: !enabledPlaybookKeys.has("sr_breakout_v1") },
  { key: "manual_ai_v1", label: "Manual AI", disabled: !MANUAL_AI_V1_ENABLED || !enabledPlaybookKeys.has("manual_ai_v1") },
  { key: "liquidity_sweep_reclaim_v1", label: "Liquidity Sweep V1", disabled: !enabledPlaybookKeys.has("liquidity_sweep_reclaim_v1") },
  { key: "h1_impulse_retest_v1", label: "H1 Impulse Retest V1", disabled: !enabledPlaybookKeys.has("h1_impulse_retest_v1") },
  { key: "line_reaction_v1", label: "Line Reaction V1", disabled: !enabledPlaybookKeys.has("line_reaction_v1") },
];

const ADD_ENTITY_OPTIONS: Array<{ kind: AddEntityKind; label: string }> = [
  { kind: "line_buy", label: "Add line buy" },
  { kind: "line_sell", label: "Add line sell" },
  { kind: "support", label: "Support" },
  { kind: "resistance", label: "Resistance" },
  { kind: "demand_order_block", label: "Demand OB" },
  { kind: "supply_order_block", label: "Supply OB" },
  { kind: "bullish_fvg", label: "Bullish FVG" },
  { kind: "bearish_fvg", label: "Bearish FVG" },
  { kind: "consolidation", label: "Consolidation" },
  { kind: "buy_side_liquidity", label: "Buy Liquidity Zone" },
  { kind: "sell_side_liquidity", label: "Sell Liquidity Zone" },
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
  const structureLabel = requirements.structure
    ? "Structure + ZigZag"
    : requirements.structureDefaultOn
      ? "Structure + ZigZag (default)"
      : null;
  const parts = [...(zoneLabels ? [zoneLabels] : []), ...(structureLabel ? [structureLabel] : [])];
  return `Layers: ${parts.join(" + ") || "None"}`;
}
