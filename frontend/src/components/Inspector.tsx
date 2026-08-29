import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, History, Layers, Maximize2, Minimize2, MousePointer2, Sigma, Target } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchTradeHistory } from "../api/chart";
import { cancelManualAiPlan, rejectManualAiPlan, updateManualAiPlanLevels } from "../api/manualAi";
import { normalizeTradeReactionFilter, TRADE_REACTION_FILTERS } from "../lib/tradeHistoryFilters";
import { compactTime, localDateTime, price } from "../lib/time";
import { useChartStore } from "../store/chartStore";
import type { ChartPayload, M15TriggerOverlay, PriceZone, SetupCandidate, TradeOrder, ZoneTypeVisibility } from "../types";
import { TradeDetails } from "./inspector/TradeDetails";
import { ZoneEditor } from "./inspector/ZoneEditor";
import { ZoneImportModal } from "./inspector/ZoneImportModal";
import { MysticImportIcon } from "./inspector/MysticImportIcon";
import { isZoneVisibleForPlaybooks } from "./chart/chartCore";
import { canonicalH1EntrySource, h1EntrySourceKind } from "./chart/h1EntrySources";
import { H1ImpulseExecuteModal } from "./chart/H1ImpulseExecuteModal";
import { H1ExpiryEditDialog } from "./chart/H1ExpiryEditDialog";
import { h1SetupExpiryDuration } from "./chart/setupExpiry";

type InspectorProps = {
  payload: ChartPayload | undefined;
  onZoneUpdated: () => void;
};

type ToastMessage = {
  id: number;
  kind: "success" | "error";
  text: string;
};

const TRADE_FILTER_STORAGE_KEY = "semi-bot-trade-history-filters";

export function Inspector({ payload, onZoneUpdated }: InspectorProps) {
  const selected = useChartStore((state) => state.selected);
  const activeTab = useChartStore((state) => state.inspectorTab);
  const setActiveTab = useChartStore((state) => state.setInspectorTab);
  const setSelected = useChartStore((state) => state.setSelected);
  const focusZone = useChartStore((state) => state.focusZone);
  const focusTrade = useChartStore((state) => state.focusTrade);
  const setStartIndex = useChartStore((state) => state.setStartIndex);
  const symbol = useChartStore((state) => state.symbol);
  const timeframe = useChartStore((state) => state.timeframe);
  const limit = useChartStore((state) => state.limit);
  const selectedPlaybooks = useChartStore((state) => state.selectedPlaybooks);
  const h1ImpulsePreviews = useChartStore((state) => state.h1ImpulsePreviews);
  const showHistoricalLiquiditySweeps = useChartStore((state) => state.showHistoricalLiquiditySweeps);
  const importantZonesOnly = useChartStore((state) => state.importantZonesOnly);
  const maxVisibleZones = useChartStore((state) => state.maxVisibleZones);
  const showZones = useChartStore((state) => state.showZones);
  const zoneTypeVisibility = useChartStore((state) => state.zoneTypeVisibility);
  const zones = payload?.layers.zones ?? [];
  const setupCandidates = [
    ...(payload?.layers.setup_candidates ?? []),
    ...(selectedPlaybooks.includes("h1_impulse_retest_v1")
      ? h1ImpulsePreviews.filter((candidate) => candidate.symbol === symbol)
      : []),
  ];
  const activeSetupCount = setupCandidates.filter((candidate) => candidate.status !== "expired").length;
  const layerFilteredZones = showZones
    ? zones.filter(
        (zone) =>
          isZoneTypeVisible(zone, zoneTypeVisibility) &&
          isZoneVisibleForPlaybooks(zone, selectedPlaybooks, showHistoricalLiquiditySweeps),
      )
    : [];
  const lastCandle = payload?.layers.candles.at(-1);
  const selectedZoneId = selected?.kind === "zone" ? selected.entity.id : null;
  const visibleZones =
    importantZonesOnly && lastCandle
      ? filterImportantZoneList(layerFilteredZones, lastCandle.close, lastCandle.time, maxVisibleZones, selectedZoneId)
      : layerFilteredZones.slice().sort((a, b) => b.weight - a.weight);
  const [toast, setToast] = useState<ToastMessage | null>(null);

  useEffect(() => {
    if (selected?.kind === "zone") setActiveTab("zones");
  }, [selected?.kind, setActiveTab]);

  const showToast = useCallback((kind: ToastMessage["kind"], text: string) => {
    setToast({ id: Date.now(), kind, text });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timeoutId = window.setTimeout(() => setToast(null), 3200);
    return () => window.clearTimeout(timeoutId);
  }, [toast]);

  return (
    <aside className="relative grid h-full min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden bg-ink-900 lg:border-l lg:border-ink-700">
      {toast ? <Toast toast={toast} onClose={() => setToast(null)} /> : null}
      <div className="border-b border-ink-700 p-3">
        <div className="grid grid-cols-3 gap-2 rounded-lg border border-ink-700 bg-ink-950 p-1">
          <button
            className={`inline-flex h-9 items-center justify-center gap-2 rounded-md text-sm font-semibold transition ${
              activeTab === "zones" ? "bg-cyan-400/15 text-cyan-100" : "text-slate-400 hover:bg-ink-800 hover:text-slate-100"
            }`}
            type="button"
            onClick={() => setActiveTab("zones")}
          >
            <Layers size={16} />
            Zones
            <span className="rounded bg-ink-900 px-1.5 py-0.5 text-[10px] text-slate-400">{visibleZones.length}</span>
          </button>
          <button
            className={`inline-flex h-9 items-center justify-center gap-2 rounded-md text-sm font-semibold transition ${
              activeTab === "setups" ? "bg-cyan-400/15 text-cyan-100" : "text-slate-400 hover:bg-ink-800 hover:text-slate-100"
            }`}
            type="button"
            onClick={() => setActiveTab("setups")}
          >
            <Target size={16} />
            Setups
            <span className="rounded bg-ink-900 px-1.5 py-0.5 text-[10px] text-slate-400">{activeSetupCount}</span>
          </button>
          <button
            className={`inline-flex h-9 items-center justify-center gap-2 rounded-md text-sm font-semibold transition ${
              activeTab === "trades" ? "bg-cyan-400/15 text-cyan-100" : "text-slate-400 hover:bg-ink-800 hover:text-slate-100"
            }`}
            type="button"
            onClick={() => setActiveTab("trades")}
          >
            <History size={16} />
            Trades
          </button>
        </div>
      </div>

      {activeTab === "zones" ? (
        <ZonesTab
          importantZonesOnly={importantZonesOnly}
          onZoneUpdated={onZoneUpdated}
          selected={selected}
          setSelected={setSelected}
          focusZone={focusZone}
          showToast={showToast}
          visibleZones={visibleZones}
          totalZones={zones.length}
        />
      ) : activeTab === "setups" ? (
        <SetupsPanel candidates={setupCandidates} m15Triggers={payload?.layers.m15_triggers ?? []} zones={zones} onChanged={onZoneUpdated} showToast={showToast} />
      ) : (
        <TradesTab
          focusTrade={focusTrade}
          limit={limit}
          selected={selected}
          selectedPlaybooks={selectedPlaybooks}
          setSelected={setSelected}
          setStartIndex={setStartIndex}
          symbol={symbol}
          timeframe={timeframe}
        />
      )}
    </aside>
  );
}

function Toast({ toast, onClose }: { toast: ToastMessage; onClose: () => void }) {
  return (
    <div className="pointer-events-none absolute right-4 top-4 z-[80]">
      <div
        className={`pointer-events-auto flex max-w-[320px] items-start gap-3 rounded-md border px-3 py-2 text-sm shadow-2xl shadow-black/40 ${
          toast.kind === "success"
            ? "border-emerald-300/50 bg-emerald-950/95 text-emerald-50"
            : "border-rose-300/50 bg-rose-950/95 text-rose-50"
        }`}
      >
        <span className="min-w-0 leading-relaxed">{toast.text}</span>
        <button className="text-slate-400 hover:text-slate-100" type="button" onClick={onClose}>
          x
        </button>
      </div>
    </div>
  );
}

function TradesTab({
  symbol,
  timeframe,
  limit,
  selectedPlaybooks,
  selected,
  setSelected,
  setStartIndex,
  focusTrade,
}: {
  symbol: string;
  timeframe: ChartPayload["timeframe"];
  limit: number;
  selectedPlaybooks: ReturnType<typeof useChartStore.getState>["selectedPlaybooks"];
  selected: ReturnType<typeof useChartStore.getState>["selected"];
  setSelected: (selected: ReturnType<typeof useChartStore.getState>["selected"]) => void;
  setStartIndex: (startIndex: number | null) => void;
  focusTrade: (trade: TradeOrder) => void;
}) {
  const storedFilters = useMemo(() => readTradeHistoryFilters(), []);
  const [status, setStatus] = useState(storedFilters.status);
  const [side, setSide] = useState(storedFilters.side);
  const [outcome, setOutcome] = useState(storedFilters.outcome);
  const [zoneType, setZoneType] = useState(storedFilters.zoneType);
  const [reaction, setReaction] = useState(storedFilters.reaction);
  const [tradeId, setTradeId] = useState(storedFilters.tradeId);
  const [sort, setSort] = useState(storedFilters.sort);
  const [page, setPage] = useState(storedFilters.page);
  const pageSize = 120;
  const offset = page * pageSize;
  const trimmedTradeId = tradeId.trim();
  const query = useQuery({
    queryKey: ["trade-history", symbol, timeframe, selectedPlaybooks, status, side, outcome, zoneType, reaction, trimmedTradeId, sort, offset],
    queryFn: () =>
      fetchTradeHistory({
        symbol,
        timeframe,
        limit: pageSize,
        offset,
        selectedPlaybooks,
        status: status || undefined,
        side: side || undefined,
        outcome,
        zoneType: zoneType || undefined,
        reaction: reaction || undefined,
        tradeId: trimmedTradeId || undefined,
        backtest: null,
        sort,
      }),
    staleTime: 10_000,
  });
  const trades = query.data?.trades ?? [];
  const total = query.data?.total ?? 0;
  const selectedTradeId = selected?.kind === "trade" ? selected.entity.id : null;
  const summary = useMemo(() => {
    const totalR = trades.reduce((sum, trade) => sum + (trade.pnl_r ?? 0), 0);
    const wins = trades.filter((trade) => (trade.pnl_r ?? 0) > 0).length;
    return { totalR, wins };
  }, [trades]);

  useEffect(() => {
    writeTradeHistoryFilters({ status, side, outcome, zoneType, reaction, tradeId, sort, page });
  }, [outcome, page, reaction, side, sort, status, tradeId, zoneType]);

  useEffect(() => {
    setPage((current) => (current === 0 ? current : 0));
  }, [outcome, reaction, side, sort, status, selectedPlaybooks, trimmedTradeId, zoneType]);

  const selectTrade = (trade: TradeOrder) => {
    setSelected({ kind: "trade", entity: trade });
    if (typeof trade.chart_index === "number") {
      const nextStart = Math.max(0, trade.chart_index - Math.floor(limit * 0.55));
      setStartIndex(nextStart);
    }
    focusTrade(trade);
  };

  return (
    <section className="grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden p-4">
      <div className="mb-3 grid gap-3">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
          <History size={14} />
          Trade History
          <span className="ml-auto normal-case tracking-normal text-slate-600">{total}</span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <input
            className="col-span-2 h-9 rounded-md border border-ink-700 bg-ink-850 px-3 text-xs text-slate-200 outline-none placeholder:text-slate-600 focus:border-cyan-400"
            placeholder="Search trade ID, e.g. 00060"
            value={tradeId}
            onChange={(event) => setTradeId(event.target.value)}
          />
          <TradeSelect value={status} onChange={setStatus} options={[["", "All status"], ["target_hit", "Target"], ["stopped", "Stopped"], ["time_exit", "Time exit"]]} />
          <TradeSelect value={outcome} onChange={setOutcome} options={[["all", "All PnL"], ["win", "Wins"], ["loss", "Losses"]]} />
          <TradeSelect value={side} onChange={setSide} options={[["", "Both side"], ["buy", "Buy"], ["sell", "Sell"]]} />
          <TradeSelect
            value={zoneType}
            onChange={setZoneType}
            options={[
              ["", "All zones"],
              ["support", "Support"],
              ["resistance", "Resistance"],
              ["fvg", "FVG"],
              ["order_block", "Order Block"],
              ["liquidity_pool", "Liquidity"],
              ["consolidation", "Consolidation"],
            ]}
          />
          <TradeSelect
            value={reaction}
            onChange={setReaction}
            options={[
              ["", "All reactions"],
              ...TRADE_REACTION_FILTERS.map((value) => [value, reactionFilterLabel(value)] as [string, string]),
            ]}
          />
          <TradeSelect
            value={sort}
            onChange={setSort}
            options={[
              ["opened_at_desc", "Newest"],
              ["opened_at_asc", "Oldest"],
              ["pnl_r_desc", "Best R"],
              ["pnl_r_asc", "Worst R"],
              ["sl_size_desc", "Largest SL"],
              ["sl_size_asc", "Smallest SL"],
            ]}
          />
        </div>
        <div className="flex items-center justify-between rounded-md border border-ink-700 bg-ink-950 px-3 py-2 text-xs text-slate-400">
          <span>{trades.length} shown · {summary.wins} wins</span>
          <span className={summary.totalR >= 0 ? "text-emerald-300" : "text-rose-300"}>{summary.totalR.toFixed(2)}R</span>
        </div>
      </div>

      <div className="min-h-0 overflow-y-auto overscroll-contain pr-1">
        {query.isLoading ? (
          <div className="rounded-md border border-dashed border-ink-700 p-3 text-xs text-slate-500">Loading trades...</div>
        ) : query.isError ? (
          <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-100">
            {query.error instanceof Error ? query.error.message : "Could not load trades."}
          </div>
        ) : trades.length === 0 ? (
          <div className="rounded-md border border-dashed border-ink-700 p-3 text-xs text-slate-500">No trades match current filters</div>
        ) : (
          <div className="grid gap-2">
            {trades.map((trade) => {
              const tradeZoneType = tradeZoneTypeLabel(trade);
              const tradeReaction = tradeReactionLabel(trade);
              const slSize = stopLossSize(trade);
              return (
              <button
                key={trade.id}
                className={`rounded-md border p-3 text-left transition ${
                  selectedTradeId === trade.id ? "border-cyan-400 bg-cyan-400/10" : "border-ink-700 bg-ink-850 hover:border-slate-600"
                }`}
                type="button"
                onClick={() => selectTrade(trade)}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-semibold text-slate-100">{playbookLabel(trade.playbook)}</span>
                  <span className={trade.side === "buy" ? "text-xs text-emerald-300" : "text-xs text-rose-300"}>{trade.side}</span>
                </div>
                <div className="mt-1 flex items-center justify-between gap-2 text-xs text-slate-400">
                  <span>{compactTime(trade.opened_at)}</span>
                  <span className={trade.status === "target_hit" ? "text-emerald-300" : trade.status === "stopped" ? "text-rose-300" : "text-yellow-200"}>
                    {trade.status}
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-[11px] text-slate-500">
                  <span>Entry {price(trade.entry_price)}</span>
                  <span>SL {price(trade.stop_loss)}</span>
                  <span>SL size {slSize === null ? "--" : slSize.toFixed(2)}</span>
                  <span>{tradeZoneType}</span>
                  <span>{tradeReaction}</span>
                  <span className={(trade.pnl_r ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}>{formatR(trade.pnl_r)}</span>
                </div>
              </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2">
        <button
          className="rounded-md border border-ink-700 bg-ink-850 px-3 py-2 text-sm text-slate-300 disabled:opacity-40"
          disabled={page === 0}
          type="button"
          onClick={() => setPage((current) => Math.max(0, current - 1))}
        >
          Prev
        </button>
        <button
          className="rounded-md border border-ink-700 bg-ink-850 px-3 py-2 text-sm text-slate-300 disabled:opacity-40"
          disabled={offset + pageSize >= total}
          type="button"
          onClick={() => setPage((current) => current + 1)}
        >
          Next
        </button>
      </div>
    </section>
  );
}

function TradeSelect({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  options: Array<[string, string]>;
}) {
  return (
    <select
      className="h-9 rounded-md border border-ink-700 bg-ink-850 px-2 text-xs text-slate-200 outline-none focus:border-cyan-400"
      value={value}
      onChange={(event) => {
        onChange(event.target.value);
      }}
    >
      {options.map(([optionValue, label]) => (
        <option key={optionValue} value={optionValue}>
          {label}
        </option>
      ))}
    </select>
  );
}

type TradeHistoryFilters = {
  status: string;
  side: string;
  outcome: string;
  zoneType: string;
  reaction: string;
  tradeId: string;
  sort: string;
  page: number;
};

function reactionFilterLabel(value: (typeof TRADE_REACTION_FILTERS)[number]): string {
  return {
    reject: "Reject",
    fakeout: "Fakeout",
    waiting_bos: "Waiting BOS",
    slow_reaction: "Slow reaction",
  }[value];
}

function readTradeHistoryFilters(): TradeHistoryFilters {
  const defaults = {
    status: "",
    side: "",
    outcome: "all",
    zoneType: "",
    reaction: "",
    tradeId: "",
    sort: "opened_at_desc",
    page: 0,
  };
  if (typeof window === "undefined") return defaults;
  try {
    const raw = window.localStorage.getItem(TRADE_FILTER_STORAGE_KEY);
    if (!raw) return defaults;
    const parsed = JSON.parse(raw) as Partial<TradeHistoryFilters>;
    return {
      status: typeof parsed.status === "string" ? parsed.status : defaults.status,
      side: typeof parsed.side === "string" ? parsed.side : defaults.side,
      outcome: typeof parsed.outcome === "string" ? parsed.outcome : defaults.outcome,
      zoneType: typeof parsed.zoneType === "string" ? parsed.zoneType : defaults.zoneType,
      reaction: normalizeTradeReactionFilter(parsed.reaction),
      tradeId: typeof parsed.tradeId === "string" ? parsed.tradeId : defaults.tradeId,
      sort: typeof parsed.sort === "string" ? parsed.sort : defaults.sort,
      page: Number.isFinite(parsed.page) ? Math.max(0, Math.floor(Number(parsed.page))) : defaults.page,
    };
  } catch {
    return defaults;
  }
}

function writeTradeHistoryFilters(filters: TradeHistoryFilters): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(
    TRADE_FILTER_STORAGE_KEY,
    JSON.stringify({
      status: filters.status,
      side: filters.side,
      outcome: filters.outcome,
      zoneType: filters.zoneType,
      reaction: filters.reaction,
      tradeId: filters.tradeId,
      sort: filters.sort,
      page: Math.max(0, Math.floor(filters.page)),
    }),
  );
}

function ZonesTab({
  selected,
  visibleZones,
  totalZones,
  importantZonesOnly,
  onZoneUpdated,
  setSelected,
  focusZone,
  showToast,
}: {
  selected: ReturnType<typeof useChartStore.getState>["selected"];
  visibleZones: PriceZone[];
  totalZones: number;
  importantZonesOnly: boolean;
  onZoneUpdated: () => void;
  setSelected: (selected: ReturnType<typeof useChartStore.getState>["selected"]) => void;
  focusZone: (zone: PriceZone) => void;
  showToast: (kind: ToastMessage["kind"], text: string) => void;
}) {
  const [isImportOpen, setIsImportOpen] = useState(false);
  return (
    <div className="min-h-0 overflow-y-auto overscroll-contain">
      {isImportOpen ? (
        <ZoneImportModal
          onClose={() => setIsImportOpen(false)}
          onImported={(result) => {
            setIsImportOpen(false);
            onZoneUpdated();
            showToast(
              "success",
              `Imported ${result.created_count} zone${result.created_count === 1 ? "" : "s"}${result.draft_count > 0 ? ` · ${result.draft_count} draft` : ""}.`,
            );
          }}
        />
      ) : null}
      <section className="border-b border-ink-700 p-4">
        <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
          <MousePointer2 size={14} />
          Selected
        </div>
        {!selected ? (
          <div className="rounded-md border border-dashed border-ink-700 p-4 text-sm text-slate-500">Click a zone or marker</div>
        ) : selected.kind === "zone" ? (
          <ZoneEditor zone={selected.entity} onZoneUpdated={onZoneUpdated} showToast={showToast} />
        ) : selected.kind === "structure" ? (
          <div className="grid gap-2 text-sm">
            <Detail label="Type" value={selected.entity.type} />
            <Detail label="Price" value={price(selected.entity.price)} />
            <Detail label="Time" value={compactTime(selected.entity.time)} />
            <Detail label="Detector" value={selected.entity.detector} />
            <Detail label="Direction" value={selected.entity.direction ?? "--"} />
          </div>
        ) : (
          <TradeDetails trade={selected.entity} showToast={showToast} />
        )}
      </section>

      <section className="p-4">
        <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
          <Layers size={14} />
          Zones
          {importantZonesOnly ? (
            <span className="ml-auto normal-case tracking-normal text-slate-600">
              {visibleZones.length}/{totalZones}
            </span>
          ) : <span className="ml-auto" />}
          <button
            aria-label="Import zones từ JSON"
            className="group rounded-lg border border-blue-400/25 bg-gradient-to-br from-blue-500/15 via-sky-400/10 to-cyan-300/5 p-1.5 text-sky-300 shadow-[0_0_14px_rgba(37,99,235,0.12)] transition hover:border-cyan-300/45 hover:text-cyan-100 hover:shadow-[0_0_20px_rgba(56,189,248,0.24)]"
            title="Import zones từ JSON"
            type="button"
            onClick={() => setIsImportOpen(true)}
          >
            <MysticImportIcon size={16} />
          </button>
        </div>
        <div className="pr-1">
          <div className="grid gap-2">
            {visibleZones.map((zone) => (
              <button
                key={zone.id}
                className={`rounded-md border p-3 text-left transition ${
                  selected?.kind === "zone" && selected.entity.id === zone.id
                    ? "border-cyan-400 bg-cyan-400/10"
                    : "border-ink-700 bg-ink-850 hover:border-slate-600"
                }`}
                type="button"
                onClick={() => {
                  setSelected({ kind: "zone", entity: zone });
                  focusZone(zone);
                }}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className={zoneTitleClass(zone)}>{zone.timeframe} {zoneDisplayName(zone)}</span>
                  <span className="text-xs text-slate-400">{zone.status}</span>
                </div>
                <div className="mt-1 text-xs text-slate-400">
                  {price(zone.price_low)} - {price(zone.price_high)} · w {zone.weight.toFixed(2)} · {formatZoneDate(zone.visual_start)}
                </div>
              </button>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

function SetupsPanel({ candidates, m15Triggers, zones, onChanged, showToast }: { candidates: SetupCandidate[]; m15Triggers: M15TriggerOverlay[]; zones: PriceZone[]; onChanged: () => void; showToast: (kind: ToastMessage["kind"], text: string) => void }) {
  const focusZone = useChartStore((state) => state.focusZone);
  const selectedSetupId = useChartStore((state) => state.selectedSetupId);
  const manualAiEditSetupId = useChartStore((state) => state.manualAiEditSetupId);
  const selectSetup = useChartStore((state) => state.selectSetup);
  const setManualAiEditSetupId = useChartStore((state) => state.setManualAiEditSetupId);
  const removeH1ImpulsePreview = useChartStore((state) => state.removeH1ImpulsePreview);
  const updateH1ImpulsePreviewLevels = useChartStore((state) => state.updateH1ImpulsePreviewLevels);
  const [watchedIds, setWatchedIds] = useState<Set<string>>(new Set());
  const [rejectedIds, setRejectedIds] = useState<Set<string>>(new Set());
  const [disabledPlaybooks, setDisabledPlaybooks] = useState<Set<string>>(new Set());
  const [cancellingIds, setCancellingIds] = useState<Set<string>>(new Set());
  const [updatingEntryIds, setUpdatingEntryIds] = useState<Set<string>>(new Set());
  const [updatingTargetIds, setUpdatingTargetIds] = useState<Set<string>>(new Set());
  const [executeCandidate, setExecuteCandidate] = useState<SetupCandidate | null>(null);
  const [expiryCandidate, setExpiryCandidate] = useState<SetupCandidate | null>(null);
  const [showExpired, setShowExpired] = useState(false);
  const visibleCandidates = candidates.filter(
    (candidate) => !rejectedIds.has(candidate.id) && !disabledPlaybooks.has(candidate.playbook),
  );
  const grouped = {
    eligible: visibleCandidates.filter((candidate) => candidate.status === "eligible"),
    waiting: visibleCandidates.filter((candidate) => candidate.status === "waiting_confirmation"),
    watching: visibleCandidates.filter((candidate) => candidate.status === "watching" || watchedIds.has(candidate.id)),
    blocked: visibleCandidates.filter((candidate) => candidate.status === "blocked" && !watchedIds.has(candidate.id)),
    expired: visibleCandidates.filter((candidate) => candidate.status === "expired"),
  };
  const activeCandidateCount = visibleCandidates.length - grouped.expired.length;

  const focusCandidate = (candidate: SetupCandidate) => {
    selectSetup(candidate.id);
    const zone = zones.find((item) => item.id === candidate.primary_zone_id);
    if (!zone) return;
    focusZone(zone);
  };
  const triggerByCandidateId = useMemo(() => {
    const result = new Map<string, M15TriggerOverlay>();
    for (const trigger of m15Triggers) {
      if (trigger.candidate_id) result.set(trigger.candidate_id, trigger);
    }
    return result;
  }, [m15Triggers]);

  const disableCandidatePlaybook = async (candidate: SetupCandidate) => {
    const brokerPlan = candidate.playbook === "manual_ai_v1" || candidate.metadata.execution_plan === true;
    if (!brokerPlan) {
      setDisabledPlaybooks((current) => addSetValue(current, candidate.playbook));
      return;
    }
    setCancellingIds((current) => addSetValue(current, candidate.id));
    try {
      const result = await cancelManualAiPlan(candidate.id);
      showToast(
        "success",
        result.status === "cancel_requested"
          ? "Đã gửi yêu cầu hủy limit tới các worker."
          : "Đã hủy Manual AI limit plan.",
      );
      onChanged();
    } catch (error) {
      showToast("error", error instanceof Error ? error.message : "Không thể hủy Manual AI limit");
    } finally {
      setCancellingIds((current) => removeSetValue(current, candidate.id));
    }
  };

  const rejectCandidate = async (candidate: SetupCandidate) => {
    if (candidate.playbook === "h1_impulse_retest_v1" && candidate.metadata.execution_plan !== true) {
      removeH1ImpulsePreview(candidate.id);
      return;
    }
    if (candidate.playbook !== "manual_ai_v1" && candidate.metadata.execution_plan !== true) {
      setRejectedIds((current) => addSetValue(current, candidate.id));
      return;
    }
    setCancellingIds((current) => addSetValue(current, candidate.id));
    try {
      const result = await rejectManualAiPlan(candidate.id);
      showToast(
        "success",
        result.status === "cancel_requested"
          ? "Đã gửi yêu cầu hủy limit trước khi reject plan."
          : "Đã reject Manual AI plan.",
      );
      onChanged();
    } catch (error) {
      showToast("error", error instanceof Error ? error.message : "Không thể reject Manual AI plan");
    } finally {
      setCancellingIds((current) => removeSetValue(current, candidate.id));
    }
  };

  const selectCandidateEntrySource = async (
    candidate: SetupCandidate,
    option: { source: string; label: string; price: number },
  ) => {
    const currentTakeProfit = candidate.take_profit[0];
    if (candidate.stop_loss === null || candidate.entry === null || typeof currentTakeProfit !== "number") return;
    const oldRisk = Math.abs(candidate.entry - candidate.stop_loss);
    const oldReward = Math.abs(currentTakeProfit - candidate.entry);
    const riskReward = candidate.risk_reward ?? (oldRisk > 0 ? oldReward / oldRisk : 2.5);
    const newRisk = Math.abs(option.price - candidate.stop_loss);
    if (newRisk <= 0) {
      showToast("error", "Entry source tạo SL size bằng 0 nên không thể áp dụng.");
      return;
    }
    const targetMode = typeof candidate.metadata.target_mode === "string" ? candidate.metadata.target_mode : "fixed_rr";
    const waveReward = typeof candidate.metadata.target_reward_distance === "number"
      ? candidate.metadata.target_reward_distance
      : null;
    const rewardDistance = targetMode.startsWith("wave_") && waveReward !== null
      ? waveReward
      : newRisk * riskReward;
    const takeProfit = roundSetupPrice(candidate.direction === "long"
      ? option.price + rewardDistance
      : option.price - rewardDistance);
    if (candidate.metadata.execution_plan !== true) {
      updateH1ImpulsePreviewLevels(candidate.id, option.price, candidate.stop_loss, takeProfit, option.source, targetMode);
      showToast("success", targetMode.startsWith("wave_")
        ? `Đã chọn ${option.label}; TP giữ wave budget ${rewardDistance.toFixed(2)}.`
        : `Đã chọn ${option.label}; TP giữ nguyên ${riskReward.toFixed(2)}R.`);
      return;
    }
    setUpdatingEntryIds((current) => addSetValue(current, candidate.id));
    try {
      const result = await updateManualAiPlanLevels(candidate.id, {
        entry_price: option.price,
        stop_loss: candidate.stop_loss,
        take_profit: takeProfit,
        entry_source: option.source,
      });
      showToast(
        "success",
        result.requires_broker_replace
          ? `Đã yêu cầu cancel & replace theo ${option.label}.`
          : `Đã cập nhật Entry theo ${option.label}.`,
      );
      onChanged();
    } catch (error) {
      showToast("error", error instanceof Error ? error.message : "Không thể đổi Entry source");
    } finally {
      setUpdatingEntryIds((current) => removeSetValue(current, candidate.id));
    }
  };

  const selectCandidateTargetSource = async (
    candidate: SetupCandidate,
    option: SetupTargetOption,
  ) => {
    if (candidate.entry === null || candidate.stop_loss === null) return;
    const risk = Math.abs(candidate.entry - candidate.stop_loss);
    const rewardDistance = option.mode === "fixed_rr"
      ? risk * (option.riskReward ?? 2.5)
      : option.rewardDistance;
    if (rewardDistance === null || rewardDistance <= 0) {
      showToast("error", `${option.label} chưa có wave budget hợp lệ.`);
      return;
    }
    const effectiveRr = rewardDistance / risk;
    if (effectiveRr < 1 || effectiveRr > 4) {
      showToast("error", `${option.label} tạo ${effectiveRr.toFixed(2)}R; H1 Impulse chỉ cho phép 1.00R–4.00R.`);
      return;
    }
    const takeProfit = roundSetupPrice(candidate.direction === "long"
      ? candidate.entry + rewardDistance
      : candidate.entry - rewardDistance);
    const entrySource = typeof candidate.metadata.entry_source === "string"
      ? candidate.metadata.entry_source
      : "human_custom";
    if (candidate.metadata.execution_plan !== true) {
      updateH1ImpulsePreviewLevels(
        candidate.id,
        candidate.entry,
        candidate.stop_loss,
        takeProfit,
        entrySource,
        option.mode,
        option.mode.startsWith("wave_") ? rewardDistance : null,
      );
      showToast("success", `Đã chọn TP ${option.label} · ${effectiveRr.toFixed(2)}R.`);
      return;
    }
    setUpdatingTargetIds((current) => addSetValue(current, candidate.id));
    try {
      const result = await updateManualAiPlanLevels(candidate.id, {
        entry_price: candidate.entry,
        stop_loss: candidate.stop_loss,
        take_profit: takeProfit,
        entry_source: entrySource,
        target_mode: option.mode,
      });
      showToast("success", result.requires_broker_replace
        ? `Đã yêu cầu cancel & replace theo TP ${option.label}.`
        : `Đã cập nhật TP theo ${option.label}.`);
      onChanged();
    } catch (error) {
      showToast("error", error instanceof Error ? error.message : "Không thể đổi TP source");
    } finally {
      setUpdatingTargetIds((current) => removeSetValue(current, candidate.id));
    }
  };

  return (
    <>
      {executeCandidate ? (
        <H1ImpulseExecuteModal
          candidate={executeCandidate}
          onClose={() => setExecuteCandidate(null)}
          onSubmitted={() => {
            removeH1ImpulsePreview(executeCandidate.id);
            setExecuteCandidate(null);
            showToast("success", "Đã duyệt H1 limit plan. Worker sẽ kiểm tra guardrails rồi gửi pending order tới MT5.");
            onChanged();
          }}
        />
      ) : null}
      {expiryCandidate ? (
        <H1ExpiryEditDialog
          planId={expiryCandidate.id}
          initialHours={Number(expiryCandidate.metadata.expiry_hours ?? 6)}
          onClose={() => setExpiryCandidate(null)}
          onUpdated={(requiresBrokerReplace) => {
            setExpiryCandidate(null);
            showToast("success", requiresBrokerReplace ? "Đã yêu cầu cancel & replace với expiry mới." : "Đã cập nhật expiry mới.");
            onChanged();
          }}
        />
      ) : null}
      <section className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden p-4">
      <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
        <Target size={14} />
        Setups
        <span className="ml-auto normal-case tracking-normal text-slate-600">{activeCandidateCount}/{candidates.length}</span>
      </div>
      {activeCandidateCount === 0 && grouped.expired.length === 0 ? (
        <div className="rounded-md border border-dashed border-ink-700 p-3 text-xs text-slate-500">No active setup candidates</div>
      ) : (
        <div className="min-h-0 min-w-0 overflow-y-auto overflow-x-hidden overscroll-contain pr-1">
          <div className="grid min-w-0 gap-3">
            {Object.entries(grouped).filter(([status]) => status !== "expired").map(([status, items]) =>
              items.length > 0 ? (
                <div key={status} className="grid min-w-0 gap-1.5">
                  <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-600">{statusLabel(status)}</div>
                  {items.map((candidate) => (
                    <SetupCard
                      key={candidate.id}
                      candidate={candidate}
                      focused={selectedSetupId === candidate.id}
                      editing={manualAiEditSetupId === candidate.id}
                      trigger={triggerByCandidateId.get(candidate.id) ?? null}
                      watched={watchedIds.has(candidate.id)}
                      onFocus={() => focusCandidate(candidate)}
                      onEdit={() => setManualAiEditSetupId(candidate.id)}
                      onExecute={() => setExecuteCandidate(candidate)}
                      onEditExpiry={() => setExpiryCandidate(candidate)}
                      entryOptions={readSetupEntryOptions(candidate.metadata.entry_options)}
                      entryBusy={updatingEntryIds.has(candidate.id)}
                      onEntrySourceSelect={(option) => { void selectCandidateEntrySource(candidate, option); }}
                      targetOptions={readSetupTargetOptions(candidate.metadata.target_plan)}
                      targetBusy={updatingTargetIds.has(candidate.id)}
                      onTargetSourceSelect={(option) => { void selectCandidateTargetSource(candidate, option); }}
                      onToggleWatch={() => setWatchedIds((current) => toggleSetValue(current, candidate.id))}
                      onReject={() => { void rejectCandidate(candidate); }}
                      disableBusy={cancellingIds.has(candidate.id)}
                      onDisablePlaybook={() => { void disableCandidatePlaybook(candidate); }}
                    />
                  ))}
                </div>
              ) : null,
            )}
            {grouped.expired.length > 0 ? (
              <div className="grid min-w-0 gap-1.5">
                <button
                  className="flex items-center gap-1 text-left text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-600 hover:text-slate-400"
                  type="button"
                  aria-expanded={showExpired}
                  onClick={() => setShowExpired((current) => !current)}
                >
                  {showExpired ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                  Expired ({grouped.expired.length})
                </button>
                {showExpired ? grouped.expired.map((candidate) => (
                  <SetupCard
                    key={candidate.id}
                    candidate={candidate}
                    focused={selectedSetupId === candidate.id}
                    editing={manualAiEditSetupId === candidate.id}
                    trigger={triggerByCandidateId.get(candidate.id) ?? null}
                    watched={watchedIds.has(candidate.id)}
                    onFocus={() => focusCandidate(candidate)}
                    onEdit={() => setManualAiEditSetupId(candidate.id)}
                    onExecute={() => setExecuteCandidate(candidate)}
                    onEditExpiry={() => setExpiryCandidate(candidate)}
                    entryOptions={readSetupEntryOptions(candidate.metadata.entry_options)}
                    entryBusy={updatingEntryIds.has(candidate.id)}
                    onEntrySourceSelect={(option) => { void selectCandidateEntrySource(candidate, option); }}
                    targetOptions={readSetupTargetOptions(candidate.metadata.target_plan)}
                    targetBusy={updatingTargetIds.has(candidate.id)}
                    onTargetSourceSelect={(option) => { void selectCandidateTargetSource(candidate, option); }}
                    onToggleWatch={() => setWatchedIds((current) => toggleSetValue(current, candidate.id))}
                    onReject={() => { void rejectCandidate(candidate); }}
                    disableBusy={cancellingIds.has(candidate.id)}
                    onDisablePlaybook={() => { void disableCandidatePlaybook(candidate); }}
                  />
                )) : null}
              </div>
            ) : null}
          </div>
        </div>
      )}
      </section>
    </>
  );
}

function SetupCard({
  candidate,
  focused,
  editing,
  trigger,
  watched,
  onFocus,
  onEdit,
  onExecute,
  onEditExpiry,
  entryOptions,
  entryBusy,
  onEntrySourceSelect,
  targetOptions,
  targetBusy,
  onTargetSourceSelect,
  onToggleWatch,
  onReject,
  onDisablePlaybook,
  disableBusy,
}: {
  candidate: SetupCandidate;
  focused: boolean;
  editing: boolean;
  trigger: M15TriggerOverlay | null;
  watched: boolean;
  onFocus: () => void;
  onEdit: () => void;
  onExecute: () => void;
  onEditExpiry: () => void;
  entryOptions: Array<{ source: string; label: string; price: number }>;
  entryBusy: boolean;
  onEntrySourceSelect: (option: { source: string; label: string; price: number }) => void;
  targetOptions: SetupTargetOption[];
  targetBusy: boolean;
  onTargetSourceSelect: (option: SetupTargetOption) => void;
  onToggleWatch: () => void;
  onReject: () => void;
  onDisablePlaybook: () => void;
  disableBusy: boolean;
}) {
  const manualAiPlanStatus = typeof candidate.metadata.manual_ai_plan_status === "string"
    ? candidate.metadata.manual_ai_plan_status
    : "draft";
  const isH1ImpulsePreview = candidate.playbook === "h1_impulse_retest_v1";
  const canEditLevels = candidate.playbook === "manual_ai_v1"
    ? ["draft", "approved", "armed"].includes(manualAiPlanStatus)
    : isH1ImpulsePreview && (candidate.metadata.execution_plan !== true || ["draft", "approved", "armed"].includes(manualAiPlanStatus));
  const previewOutcome = readPreviewOutcome(candidate);
  const entrySource = setupEntrySource(candidate);
  const rawEntrySource = typeof candidate.metadata.entry_source === "string" ? candidate.metadata.entry_source : "strategy_calculated";
  const selectedEntryOptionSource = canonicalH1EntrySource(rawEntrySource);
  const selectedTargetMode = String(candidate.metadata.target_mode ?? "fixed_rr");
  const stopSize = candidate.entry !== null && candidate.stop_loss !== null
    ? Math.abs(candidate.entry - candidate.stop_loss)
    : null;
  const atr = typeof candidate.metadata.atr === "number" && candidate.metadata.atr > 0 ? candidate.metadata.atr : null;
  const orderedEntryOptions = candidate.stop_loss === null
    ? entryOptions
    : [...entryOptions].sort((left, right) => {
        const distanceDelta = Math.abs(left.price - candidate.stop_loss!) - Math.abs(right.price - candidate.stop_loss!);
        return distanceDelta !== 0 ? distanceDelta : left.label.localeCompare(right.label);
      });
  const expiryDuration = h1SetupExpiryDuration(candidate);
  const accountStatuses = readAccountStatuses(candidate.metadata.account_statuses);
  return (
    <div
      className={`min-w-0 overflow-hidden rounded-md border p-3 text-left transition ${
        focused ? "ring-1 ring-cyan-300" : ""
      } ${setupCardClass(candidate.status)}`}
      role="button"
      tabIndex={0}
      onClick={onFocus}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        onFocus();
      }}
    >
      <div className="flex min-w-0 items-center justify-between gap-2">
        <span className="min-w-0 truncate text-sm font-semibold text-slate-100">{playbookLabel(candidate.playbook)}</span>
        <span className={candidate.direction === "long" ? "text-xs text-emerald-300" : "text-xs text-rose-300"}>
          {candidate.direction}
        </span>
      </div>
      <div className="mt-1 flex min-w-0 flex-wrap gap-x-2 gap-y-1 text-[11px] text-slate-400">
        <span>score {candidate.score.toFixed(2)}</span>
        <span>{candidate.zone_reaction_state}</span>
        {candidate.risk_reward ? <span>RR {candidate.risk_reward.toFixed(2)}</span> : null}
      </div>
      {candidate.metadata.human_override === true ? (
        <div className="mt-1 inline-flex rounded border border-amber-300/35 bg-amber-300/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-amber-200">
          Human override
        </div>
      ) : null}
      <div className="mt-1 truncate text-[10px] font-medium text-cyan-200/80">Entry source · {entrySource}</div>
      {isH1ImpulsePreview ? (
        <div className="mt-1 text-[10px] font-medium text-violet-200/80">
          TP source · {String(candidate.metadata.target_mode ?? "fixed_rr").replaceAll("_", " ")}
          {String(candidate.metadata.target_mode ?? "").startsWith("wave_") && typeof candidate.metadata.target_reward_distance === "number" ? ` · budget ${price(candidate.metadata.target_reward_distance)}` : ""}
        </div>
      ) : null}
      {typeof candidate.metadata.target_warning === "string" ? (
        <div className="mt-1 rounded border border-amber-300/25 bg-amber-300/10 px-2 py-1 text-[10px] leading-4 text-amber-200">
          Wave TP fallback: {candidate.metadata.target_warning}
        </div>
      ) : null}
      {previewOutcome ? (
        <div className={`mt-2 flex items-center justify-between rounded border px-2 py-1.5 text-[10px] font-bold ${previewOutcomeClass(previewOutcome.status)}`}>
          <span>{previewOutcome.status.toUpperCase()}</span>
          <span>{previewOutcome.resultR === null ? previewOutcome.detail : `${previewOutcome.resultR > 0 ? "+" : ""}${previewOutcome.resultR.toFixed(2)}R`}</span>
        </div>
      ) : null}
      {candidate.entry && candidate.stop_loss ? (
        <div className="mt-1 flex min-w-0 flex-wrap gap-x-2 gap-y-1 text-[11px] text-slate-500">
          <span>Entry {price(candidate.entry)}</span>
          <span>SL {price(candidate.stop_loss)}</span>
          {candidate.take_profit[0] ? <span>TP {price(candidate.take_profit[0])}</span> : null}
        </div>
      ) : null}
      {stopSize !== null ? (
        <div className="mt-1 text-[11px] font-semibold text-amber-200/90">
          SL size {price(stopSize)}{atr ? ` · ${(stopSize / atr).toFixed(2)} ATR` : ""}
        </div>
      ) : null}
      {isH1ImpulsePreview && orderedEntryOptions.length > 0 ? (
        <div className="mt-2 rounded border border-cyan-400/15 bg-black/15 p-2">
          <div className="mb-1 text-[9px] font-bold uppercase tracking-[0.12em] text-cyan-200/70">Quick Entry source</div>
          <div className="flex flex-wrap gap-1">
            {orderedEntryOptions.map((option) => {
              const optionStopSize = candidate.stop_loss === null ? null : Math.abs(option.price - candidate.stop_loss);
              const selected = selectedEntryOptionSource === option.source;
              return (
                <button
                  key={option.source}
                  className={`rounded border px-1.5 py-1 text-left text-[9px] font-semibold transition disabled:cursor-wait disabled:opacity-45 ${
                    selected
                      ? "border-cyan-300 bg-cyan-300/15 text-cyan-100"
                      : "border-ink-700 bg-ink-950 text-slate-400 hover:border-cyan-400/60 hover:text-cyan-100"
                  }`}
                  aria-pressed={selected}
                  disabled={!canEditLevels || entryBusy}
                  title={`${option.label} · Entry ${price(option.price)}${optionStopSize === null ? "" : ` · SL size ${price(optionStopSize)}`}`}
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    onEntrySourceSelect(option);
                  }}
                >
                  <span className="flex items-center gap-1">
                    <EntrySourceIcon source={option.source} />
                    <span>{option.label}</span>
                  </span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-1 font-mono font-normal">
                    <span className={selected ? "text-cyan-100/75" : "text-slate-500"}>E {price(option.price)}</span>
                    {optionStopSize !== null ? (
                      <span className="rounded border border-amber-300/25 bg-amber-300/10 px-1 py-px font-bold text-amber-200">
                        SL {price(optionStopSize)}{atr ? ` · ${(optionStopSize / atr).toFixed(2)} ATR` : ""}
                      </span>
                    ) : null}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
      {isH1ImpulsePreview && targetOptions.length > 0 ? (
        <div className="mt-1.5 rounded border border-violet-400/15 bg-black/15 p-2">
          <div className="mb-1 text-[9px] font-bold uppercase tracking-[0.12em] text-violet-200/70">Quick TP source</div>
          <div className="grid grid-cols-3 gap-1">
            {targetOptions.map((option) => {
              const selected = selectedTargetMode === option.mode;
              const risk = candidate.entry !== null && candidate.stop_loss !== null
                ? Math.abs(candidate.entry - candidate.stop_loss)
                : null;
              const reward = option.mode === "fixed_rr" && risk !== null
                ? risk * (option.riskReward ?? 2.5)
                : option.rewardDistance;
              const targetPrice = candidate.entry === null || reward === null
                ? null
                : candidate.direction === "long" ? candidate.entry + reward : candidate.entry - reward;
              const effectiveRr = risk && reward !== null ? reward / risk : null;
              return (
                <button
                  key={option.mode}
                  aria-pressed={selected}
                  className={`min-w-0 rounded border px-1.5 py-1.5 text-left transition disabled:cursor-wait disabled:opacity-45 ${
                    selected
                      ? "border-violet-300/80 bg-violet-300/15 text-violet-100"
                      : "border-ink-700 bg-ink-950 text-slate-400 hover:border-violet-400/55 hover:text-violet-100"
                  }`}
                  disabled={!canEditLevels || targetBusy || !option.available || targetPrice === null}
                  title={option.reason}
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    onTargetSourceSelect(option);
                  }}
                >
                  <span className="block truncate text-[9px] font-semibold">{shortTargetLabel(option.mode)}</span>
                  <span className="mt-0.5 block truncate font-mono text-[9px] font-bold tabular-nums text-slate-200">TP {targetPrice === null ? "--" : price(targetPrice)}</span>
                  <span className={`mt-0.5 block truncate font-mono text-[8px] tabular-nums ${selected ? "text-violet-200" : "text-slate-500"}`}>
                    {reward === null ? "Unavailable" : `Δ${price(reward)} · ${effectiveRr?.toFixed(2) ?? "--"}R`}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
      {candidate.expires_at ? (
        <div className="mt-1 text-[11px] font-medium text-amber-300/90">
          Hết hạn {localDateTime(candidate.expires_at)}{expiryDuration ? ` (${expiryDuration})` : ""}
        </div>
      ) : null}
      {accountStatuses.length > 0 ? (
        <div className="mt-1 flex min-w-0 flex-wrap gap-x-1 text-[10px] text-slate-500">
          {accountStatuses.map((account, index) => (
            <span key={`${account.accountLabel}:${account.status}`}>
              {index > 0 ? <span className="mr-1 text-slate-700">·</span> : null}
              {account.accountLabel} <span className={account.status === "expired" ? "text-amber-300/80" : account.status === "cancelled" ? "text-slate-400" : "text-cyan-200/80"}>{account.status}</span>
            </span>
          ))}
        </div>
      ) : null}
      {typeof candidate.metadata.manual_ai_replace_error === "string" ? (
        <div className="mt-1 rounded border border-rose-500/30 bg-rose-950/50 px-2 py-1 text-[10px] leading-4 text-rose-200">
          Replace failed: {candidate.metadata.manual_ai_replace_error}
        </div>
      ) : null}
      {trigger ? (
        <div className="mt-2 rounded border border-cyan-400/20 bg-cyan-400/[0.06] px-2 py-1.5 text-[11px] text-cyan-50">
          <div className="flex min-w-0 flex-wrap gap-x-2 gap-y-1">
            <span className="font-semibold">M15 trigger</span>
            <span>{compactTime(trigger.time)}</span>
            <span>O {price(trigger.open)}</span>
            <span>H {price(trigger.high)}</span>
            <span>L {price(trigger.low)}</span>
            <span>C {price(trigger.close)}</span>
          </div>
          <div className="mt-1 truncate text-cyan-100/70">{trigger.reason[0] ?? candidate.reason[0] ?? "--"}</div>
        </div>
      ) : null}
      <div className="mt-1 truncate text-[11px] text-slate-500">
        {setupPrimaryReason(candidate)}
      </div>
      <StateMachine steps={readStateMachine(candidate.metadata.state_machine)} compact />
      <div className="mt-2 flex min-w-0 flex-wrap gap-1">
        {isH1ImpulsePreview && candidate.metadata.execution_plan === true && manualAiPlanStatus === "expired" ? (
          <SetupAction label="Revalidate & re-order" onClick={onExecute} />
        ) : null}
        {isH1ImpulsePreview && candidate.metadata.execution_plan === true && ["draft", "approved", "armed"].includes(manualAiPlanStatus) ? (
          <SetupAction label="Edit expiry" onClick={onEditExpiry} />
        ) : null}
        {isH1ImpulsePreview && candidate.metadata.execution_plan !== true ? (
          <SetupAction label={candidate.status === "blocked" ? "Review blocked setup" : "Send limit to MT5"} onClick={onExecute} />
        ) : null}
        {isH1ImpulsePreview && candidate.metadata.execution_plan !== true ? (
          <SetupAction label="Remove preview" onClick={onReject} />
        ) : null}
        {canEditLevels && focused ? (
          <SetupAction active={editing} label={editing ? "Editing levels" : "Edit levels"} onClick={onEdit} />
        ) : null}
        {!isH1ImpulsePreview ? <SetupAction label={watched ? "Watching" : "Watch"} onClick={onToggleWatch} /> : null}
        {(!isH1ImpulsePreview || candidate.metadata.execution_plan === true) && manualAiPlanStatus !== "expired" ? <SetupAction label="Reject" onClick={onReject} /> : null}
        {(!isH1ImpulsePreview || candidate.metadata.execution_plan === true) && manualAiPlanStatus !== "expired" ? <SetupAction label={candidate.playbook === "manual_ai_v1" || candidate.metadata.execution_plan === true ? (disableBusy ? "Cancelling…" : "Cancel limit") : "Disable PB"} disabled={disableBusy} onClick={onDisablePlaybook} /> : null}
      </div>
    </div>
  );
}

function EntrySourceIcon({ source }: { source: string }) {
  const className = "size-3 shrink-0";
  switch (h1EntrySourceKind(source)) {
    case "previous":
      return <History aria-hidden="true" className={className} />;
    case "fibonacci":
      return <Sigma aria-hidden="true" className={className} />;
    case "minimum":
      return <Minimize2 aria-hidden="true" className={className} />;
    case "maximum":
      return <Maximize2 aria-hidden="true" className={className} />;
    default:
      return <MousePointer2 aria-hidden="true" className={className} />;
  }
}

function SetupAction({ active = false, disabled = false, label, onClick }: { active?: boolean; disabled?: boolean; label: string; onClick: () => void }) {
  return (
    <span
      aria-disabled={disabled}
      className={`rounded border px-1.5 py-0.5 text-[10px] hover:border-cyan-500 hover:text-cyan-100 aria-disabled:cursor-wait aria-disabled:opacity-50 ${
        active ? "border-cyan-400 bg-cyan-400/15 text-cyan-100" : "border-ink-700 bg-ink-950 text-slate-300"
      }`}
      role="button"
      tabIndex={0}
      onClick={(event) => {
        event.stopPropagation();
        if (disabled) return;
        onClick();
      }}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        event.stopPropagation();
        if (disabled) return;
        onClick();
      }}
    >
      {label}
    </span>
  );
}

function filterImportantZoneList(
  zones: PriceZone[],
  currentPrice: number,
  lastCandleTime: string,
  maxZones: number,
  selectedZoneId: string | null,
): PriceZone[] {
  const pinned = zones.filter((zone) => zone.id === selectedZoneId);
  const pinnedIds = new Set(pinned.map((zone) => zone.id));
  const ranked = zones
    .filter((zone) => !pinnedIds.has(zone.id))
    .map((zone) => ({ zone, score: zoneImportanceScore(zone, currentPrice, lastCandleTime) }))
    .sort((a, b) => b.score - a.score);

  const selectedZones: PriceZone[] = [...pinned];
  const targetCount = Math.max(maxZones, pinned.length);
  for (const candidate of ranked) {
    if (selectedZones.length >= targetCount) break;
    selectedZones.push(candidate.zone);
  }
  return selectedZones;
}

function isZoneTypeVisible(zone: PriceZone, visibility: ZoneTypeVisibility): boolean {
  if (zone.type === "support") return visibility.support;
  if (zone.type === "resistance") return visibility.resistance;
  if (zone.type === "order_block") return visibility.order_block;
  if (zone.type === "fvg") return visibility.fvg;
  if (zone.type === "liquidity_pool") return visibility.liquidity_pool;
  if (zone.type === "consolidation") return visibility.consolidation;
  return true;
}

function zoneImportanceScore(zone: PriceZone, currentPrice: number, lastCandleTime: string): number {
  const center = (zone.price_low + zone.price_high) / 2;
  const zoneWidth = Math.max(zone.price_high - zone.price_low, 1);
  const distance = Math.abs(center - currentPrice);
  const proximity = 1 / (1 + distance / Math.max(currentPrice * 0.008, zoneWidth * 3, 1));
  const anchorTime = Date.parse(zone.detected_at || zone.visual_start);
  const lastTime = Date.parse(lastCandleTime);
  const ageDays = Number.isFinite(anchorTime) && Number.isFinite(lastTime) ? Math.max((lastTime - anchorTime) / 86_400_000, 0) : 0;
  const recency = 1 / (1 + ageDays / 21);
  const activeBoost = zone.status === "active" ? 0.12 : 0;
  const humanBoost = isHumanZone(zone) ? 0.18 : 0;

  return zone.weight * 0.48 + proximity * 0.24 + recency * 0.16 + activeBoost + humanBoost;
}

function isHumanZone(zone: PriceZone): boolean {
  return zone.source === "human" || zone.metadata.human_created === true;
}

function zoneDisplayName(zone: PriceZone): string {
  if (zone.type === "liquidity_pool" && zone.status === "swept") return "Historical Liquidity Sweep";
  const kind = zone.metadata.add_entity_kind;
  if (kind === "demand_order_block") return "Demand OB";
  if (kind === "supply_order_block") return "Supply OB";
  if (kind === "bullish_fvg") return "Bullish FVG";
  if (kind === "bearish_fvg") return "Bearish FVG";
  if (kind === "buy_side_liquidity") return "Buy Liquidity Zone";
  if (kind === "sell_side_liquidity") return "Sell Liquidity Zone";
  if (zone.type === "order_block") return zone.direction === "bullish" ? "Demand OB" : "Supply OB";
  if (zone.type === "fvg") return zone.direction === "bullish" ? "Bullish FVG" : "Bearish FVG";
  if (zone.type === "liquidity_pool") {
    return zone.direction === "bullish" ? "Buy Liquidity Zone" : zone.direction === "bearish" ? "Sell Liquidity Zone" : "Liquidity Pool";
  }
  return zone.type;
}

function zoneTitleClass(zone: PriceZone): string {
  if (zone.type === "order_block") {
    return zone.direction === "bullish" ? "font-semibold text-cyan-300" : "font-semibold text-fuchsia-300";
  }
  if (zone.type === "fvg") {
    return zone.direction === "bullish" ? "font-semibold text-lime-300" : "font-semibold text-orange-300";
  }
  if (zone.type === "consolidation") return "font-semibold text-sky-300";
  if (zone.type === "liquidity_pool") return "font-semibold text-yellow-300";
  return zone.direction === "bullish" ? "font-semibold text-emerald-300" : "font-semibold text-rose-300";
}

function statusLabel(status: string): string {
  if (status === "waiting") return "Waiting";
  if (status === "watching") return "Watching";
  if (status === "eligible") return "Signal ready";
  if (status === "blocked") return "Blocked";
  return status;
}

function setupCardClass(status: SetupCandidate["status"]): string {
  if (status === "eligible") return "border-cyan-400/70 bg-cyan-400/10 hover:bg-cyan-400/15";
  if (status === "waiting_confirmation") return "border-yellow-300/50 bg-yellow-300/[0.07] hover:bg-yellow-300/[0.12]";
  if (status === "watching") return "border-slate-600 bg-ink-850 hover:border-slate-500";
  if (status === "blocked") return "border-rose-500/30 bg-rose-500/[0.05] opacity-80 hover:opacity-100";
  return "border-ink-700 bg-ink-850";
}

function readPreviewOutcome(candidate: SetupCandidate): { status: string; resultR: number | null; detail: string } | null {
  const value = candidate.metadata.outcome;
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const outcome = value as Record<string, unknown>;
  if (typeof outcome.status !== "string") return null;
  const barsToFill = typeof outcome.bars_to_fill === "number" ? outcome.bars_to_fill : null;
  const barsHeld = typeof outcome.bars_held === "number" ? outcome.bars_held : null;
  const modified = outcome.status === "modified";
  return {
    status: outcome.status,
    resultR: typeof outcome.result_r === "number" ? outcome.result_r : null,
    detail: modified ? "Levels changed" : barsToFill === null ? "Not filled" : `fill ${barsToFill}h · held ${barsHeld ?? 0}h`,
  };
}

function readSetupEntryOptions(value: unknown): Array<{ source: string; label: string; price: number }> {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const option = item as Record<string, unknown>;
    if (typeof option.source !== "string" || typeof option.label !== "string" || typeof option.price !== "number") return [];
    return [{ source: option.source, label: option.label, price: option.price }];
  });
}

type SetupTargetOption = {
  mode: string;
  label: string;
  available: boolean;
  riskReward: number | null;
  rewardDistance: number | null;
  reason: string;
};

function readSetupTargetOptions(value: unknown): SetupTargetOption[] {
  const plan = readObject(value);
  if (!Array.isArray(plan.options)) return [];
  const options = plan.options.flatMap((item) => {
    const option = readObject(item);
    if (typeof option.mode !== "string" || typeof option.label !== "string") return [];
    return [{
      mode: option.mode,
      label: option.label,
      available: option.available !== false,
      riskReward: typeof option.risk_reward === "number" ? option.risk_reward : null,
      rewardDistance: typeof option.reward_distance === "number" ? option.reward_distance : null,
      reason: typeof option.reason === "string" ? option.reason : option.label,
    }];
  });
  const order = new Map([["wave_safe", 0], ["wave_base", 1], ["fixed_rr", 2]]);
  return options.sort((left, right) => (order.get(left.mode) ?? 99) - (order.get(right.mode) ?? 99));
}

function shortTargetLabel(mode: string): string {
  if (mode === "wave_safe") return "Safe";
  if (mode === "wave_base") return "Base";
  if (mode === "fixed_rr") return "Fixed RR";
  return mode.replaceAll("_", " ");
}

function readAccountStatuses(value: unknown): Array<{ accountLabel: string; status: string }> {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const record = readObject(item);
    const accountLabel = typeof record.account_label === "string" ? record.account_label.trim() : "";
    const status = typeof record.status === "string" ? record.status.trim() : "";
    return accountLabel && status ? [{ accountLabel, status }] : [];
  });
}

function setupPrimaryReason(candidate: SetupCandidate): string {
  if (candidate.blocked_reason[0]) return candidate.blocked_reason[0];
  return candidate.reason.find((reason) => !reason.toLowerCase().startsWith("entry source:")) ?? "--";
}

function roundSetupPrice(value: number): number {
  return Math.round(value * 100_000) / 100_000;
}

function setupEntrySource(candidate: SetupCandidate): string {
  for (const key of ["entry_source", "entry_model", "trigger_method"]) {
    const value = candidate.metadata[key];
    if (typeof value === "string" && value.trim()) return value.replace(/_/g, " ");
  }
  return candidate.reason.find((reason) => reason.toLowerCase().includes("entry")) ?? "strategy calculated";
}

function previewOutcomeClass(status: string): string {
  if (status === "win") return "border-emerald-400/35 bg-emerald-400/10 text-emerald-200";
  if (status === "loss") return "border-rose-400/35 bg-rose-400/10 text-rose-200";
  if (status === "ambiguous") return "border-amber-400/35 bg-amber-400/10 text-amber-200";
  return "border-cyan-400/30 bg-cyan-400/[0.07] text-cyan-200";
}

function playbookLabel(value: string): string {
  if (value === "sr_breakout_v1") return "SR Breakout V1";
  if (value === "zone_reaction_v2") return "Zone Reaction V2";
  if (value === "h1_impulse_retest_v1") return "H1 Impulse Retest V1";
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function toggleSetValue(current: Set<string>, value: string): Set<string> {
  const next = new Set(current);
  if (next.has(value)) {
    next.delete(value);
  } else {
    next.add(value);
  }
  return next;
}

function addSetValue(current: Set<string>, value: string): Set<string> {
  const next = new Set(current);
  next.add(value);
  return next;
}

function removeSetValue(current: Set<string>, value: string): Set<string> {
  const next = new Set(current);
  next.delete(value);
  return next;
}

type StateMachineStep = {
  key: string;
  label: string;
  status: string;
};

function StateMachine({ steps, compact = false }: { steps: StateMachineStep[]; compact?: boolean }) {
  if (steps.length === 0) return null;
  return (
    <div className={compact ? "mt-2 flex min-w-0 flex-wrap gap-1" : "grid min-w-0 gap-1"}>
      {!compact ? <div className="text-xs text-slate-500">State machine</div> : null}
      <div className="flex min-w-0 flex-wrap gap-1 overflow-hidden">
        {steps.map((step) => (
          <span
            key={step.key}
            className={`rounded border px-1.5 py-0.5 text-[10px] ${
              step.status === "active"
                ? "border-cyan-300/70 bg-cyan-300/15 text-cyan-100"
                : step.status === "done"
                  ? "border-emerald-300/30 bg-emerald-300/[0.06] text-emerald-200"
                  : "border-ink-700 bg-ink-950 text-slate-500"
            }`}
            title={step.label}
          >
            {compact ? shortStateLabel(step.key) : step.key}
          </span>
        ))}
      </div>
    </div>
  );
}

function shortStateLabel(value: string): string {
  const labels: Record<string, string> = {
    IDLE: "IDLE",
    ZONE_TOUCHED: "TOUCH",
    REACTING_IN_ZONE: "REACT",
    WAIT_FOR_BOS: "BOS",
    WAITING_RETEST: "RETEST",
    BIAS_WARNING: "WARN",
    PREPARE_ENTRY: "ENTRY",
  };
  return labels[value] ?? value;
}

function readStateMachine(value: unknown): StateMachineStep[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => (item && typeof item === "object" && !Array.isArray(item) ? (item as Record<string, unknown>) : null))
    .filter((item): item is Record<string, unknown> => item !== null)
    .map((item) => ({
      key: typeof item.key === "string" ? item.key : "--",
      label: typeof item.label === "string" ? item.label : "--",
      status: typeof item.status === "string" ? item.status : "pending",
    }));
}

function readObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function readStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.length > 0);
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function firstTakeProfitPrice(values: TradeOrder["take_profit"]): number | null {
  const first = values.at(0);
  if (typeof first === "number") return first;
  if (first && typeof first.price === "number") return first.price;
  return null;
}

function stopLossSize(trade: TradeOrder): number | null {
  if (typeof trade.entry_price !== "number" || typeof trade.stop_loss !== "number") return null;
  return Math.abs(trade.entry_price - trade.stop_loss);
}

function tradeZoneTypeLabel(trade: TradeOrder): string {
  const metadata = readObject(trade.metadata);
  const candidateMetadata = readObject(metadata.candidate_metadata);
  return String(candidateMetadata.zone_type ?? metadata.zone_type ?? "--");
}

function tradeReactionLabel(trade: TradeOrder): string {
  const metadata = readObject(trade.metadata);
  const candidateMetadata = readObject(metadata.candidate_metadata);
  return String(metadata.zone_reaction_state ?? candidateMetadata.zone_reaction_state ?? "--");
}

function formatUnknownNumber(value: unknown): string {
  return typeof value === "number" ? value.toFixed(2) : "--";
}

function formatR(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "--";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}R`;
}

function tradeStatusNote(status: string): string | null {
  if (status === "time_exit") {
    return "Time exit: lệnh chưa chạm SL/TP trong thời gian giữ tối đa của backtest, nên bị đóng ở close của nến hết hạn. Nếu giá chạm TP sau thời điểm Closed thì backtest không tính TP đó.";
  }
  if (status === "target_hit") return "Target hit: giá đã chạm TP trong thời gian giữ lệnh.";
  if (status === "stopped") return "Stopped: giá đã chạm SL trong thời gian giữ lệnh.";
  return null;
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName.toLowerCase();
  return tagName === "input" || tagName === "textarea" || tagName === "select" || target.isContentEditable;
}

function formatZoneDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return `${String(date.getDate()).padStart(2, "0")}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] gap-3">
      <span className="text-slate-500">{label}</span>
      <strong className="min-w-0 break-words text-slate-100">{value}</strong>
    </div>
  );
}
