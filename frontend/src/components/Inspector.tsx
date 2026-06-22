import { useMutation } from "@tanstack/react-query";
import { useQuery } from "@tanstack/react-query";
import { History, Layers, MousePointer2, RotateCcw, Save, Target, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { deleteManualZone, fetchTradeHistory, updateTradeReview, updateZoneOverride } from "../api/chart";
import { compactTime, price } from "../lib/time";
import { useChartStore } from "../store/chartStore";
import type { ChartPayload, PriceZone, SelectedEntity, SetupCandidate, TradeOrder, TradeReview, ZoneTradeMode, ZoneTypeVisibility } from "../types";

type InspectorProps = {
  payload: ChartPayload | undefined;
  onZoneUpdated: () => void;
};

type InspectorTab = "zones" | "setups" | "trades";
type ToastMessage = {
  id: number;
  kind: "success" | "error";
  text: string;
};

const TRADE_FILTER_STORAGE_KEY = "semi-bot-trade-history-filters";

export function Inspector({ payload, onZoneUpdated }: InspectorProps) {
  const rawSelected = useChartStore((state) => state.selected);
  const setSelected = useChartStore((state) => state.setSelected);
  const focusZone = useChartStore((state) => state.focusZone);
  const focusTrade = useChartStore((state) => state.focusTrade);
  const setStartIndex = useChartStore((state) => state.setStartIndex);
  const symbol = useChartStore((state) => state.symbol);
  const timeframe = useChartStore((state) => state.timeframe);
  const limit = useChartStore((state) => state.limit);
  const selectedPlaybooks = useChartStore((state) => state.selectedPlaybooks);
  const importantZonesOnly = useChartStore((state) => state.importantZonesOnly);
  const maxVisibleZones = useChartStore((state) => state.maxVisibleZones);
  const showZones = useChartStore((state) => state.showZones);
  const zoneTypeVisibility = useChartStore((state) => state.zoneTypeVisibility);
  const zones = payload?.layers.zones ?? [];
  const payloadTrades = payload?.layers.trades ?? [];
  const selected = useMemo(
    () => resolveLatestSelected(rawSelected, zones, payloadTrades),
    [payloadTrades, rawSelected, zones],
  );
  useEffect(() => {
    if (!rawSelected || !selected || selected === rawSelected || !selectedNeedsSync(rawSelected, selected)) return;
    setSelected(selected);
  }, [rawSelected, selected, setSelected]);
  const setupCandidates = payload?.layers.setup_candidates ?? [];
  const layerFilteredZones = showZones ? zones.filter((zone) => isZoneTypeVisible(zone, zoneTypeVisibility)) : [];
  const lastCandle = payload?.layers.candles.at(-1);
  const selectedZoneId = selected?.kind === "zone" ? selected.entity.id : null;
  const visibleZones =
    importantZonesOnly && lastCandle
      ? filterImportantZoneList(layerFilteredZones, lastCandle.close, lastCandle.time, maxVisibleZones, selectedZoneId)
      : layerFilteredZones.slice().sort((a, b) => b.weight - a.weight);
  const [activeTab, setActiveTab] = useState<InspectorTab>("zones");
  const [toast, setToast] = useState<ToastMessage | null>(null);

  const showToast = useCallback((kind: ToastMessage["kind"], text: string) => {
    setToast({ id: Date.now(), kind, text });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timeoutId = window.setTimeout(() => setToast(null), 3200);
    return () => window.clearTimeout(timeoutId);
  }, [toast]);

  return (
    <aside className="relative grid h-full min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden border-l border-ink-700 bg-ink-900">
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
            <span className="rounded bg-ink-900 px-1.5 py-0.5 text-[10px] text-slate-400">{setupCandidates.length}</span>
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
        <SetupsPanel candidates={setupCandidates} zones={zones} />
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
              ["reject", "Reject"],
              ["fakeout", "Fakeout"],
              ["waiting_bos", "Waiting BOS"],
              ["retest_reject", "Retest reject"],
              ["slow_reaction", "Slow reaction"],
              ["clean_breakout", "Clean breakout"],
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
      reaction: typeof parsed.reaction === "string" ? parsed.reaction : defaults.reaction,
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
  return (
    <div className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden">
      <section className="min-h-0 border-b border-ink-700 p-4">
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

      <section className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden p-4">
        <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
          <Layers size={14} />
          Zones
          {importantZonesOnly ? (
            <span className="ml-auto normal-case tracking-normal text-slate-600">
              {visibleZones.length}/{totalZones}
            </span>
          ) : null}
        </div>
        <div className="min-h-0 overflow-y-auto overscroll-contain pr-1">
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
                  <span className={zoneTitleClass(zone)}>{zoneDisplayName(zone)}</span>
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

function SetupsPanel({ candidates, zones }: { candidates: SetupCandidate[]; zones: PriceZone[] }) {
  const focusZone = useChartStore((state) => state.focusZone);
  const [focusedCandidateId, setFocusedCandidateId] = useState<string | null>(null);
  const [watchedIds, setWatchedIds] = useState<Set<string>>(new Set());
  const [rejectedIds, setRejectedIds] = useState<Set<string>>(new Set());
  const [disabledPlaybooks, setDisabledPlaybooks] = useState<Set<string>>(new Set());
  const visibleCandidates = candidates.filter(
    (candidate) => !rejectedIds.has(candidate.id) && !disabledPlaybooks.has(candidate.playbook),
  );
  const grouped = {
    eligible: visibleCandidates.filter((candidate) => candidate.status === "eligible"),
    waiting: visibleCandidates.filter((candidate) => candidate.status === "waiting_confirmation"),
    watching: visibleCandidates.filter((candidate) => candidate.status === "watching" || watchedIds.has(candidate.id)),
    blocked: visibleCandidates.filter((candidate) => candidate.status === "blocked" && !watchedIds.has(candidate.id)),
  };

  const focusCandidate = (candidate: SetupCandidate) => {
    setFocusedCandidateId(candidate.id);
    const zone = zones.find((item) => item.id === candidate.primary_zone_id);
    if (!zone) return;
    focusZone(zone);
  };

  return (
    <section className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden p-4">
      <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
        <Target size={14} />
        Setups
        <span className="ml-auto normal-case tracking-normal text-slate-600">{visibleCandidates.length}/{candidates.length}</span>
      </div>
      {visibleCandidates.length === 0 ? (
        <div className="rounded-md border border-dashed border-ink-700 p-3 text-xs text-slate-500">No active setup candidates</div>
      ) : (
        <div className="min-h-0 min-w-0 overflow-y-auto overflow-x-hidden overscroll-contain pr-1">
          <div className="grid min-w-0 gap-3">
            {Object.entries(grouped).map(([status, items]) =>
              items.length > 0 ? (
                <div key={status} className="grid min-w-0 gap-1.5">
                  <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-600">{statusLabel(status)}</div>
                  {items.map((candidate) => (
                    <div
                      key={candidate.id}
                      className={`min-w-0 overflow-hidden rounded-md border p-3 text-left transition ${
                        focusedCandidateId === candidate.id
                          ? "ring-1 ring-cyan-300"
                          : ""
                      } ${setupCardClass(candidate.status)}`}
                      role="button"
                      tabIndex={0}
                      onClick={() => focusCandidate(candidate)}
                      onKeyDown={(event) => {
                        if (event.key !== "Enter" && event.key !== " ") return;
                        event.preventDefault();
                        focusCandidate(candidate);
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
                      {candidate.entry && candidate.stop_loss ? (
                        <div className="mt-1 flex min-w-0 flex-wrap gap-x-2 gap-y-1 text-[11px] text-slate-500">
                          <span>Entry {price(candidate.entry)}</span>
                          <span>SL {price(candidate.stop_loss)}</span>
                          {candidate.take_profit[0] ? <span>TP {price(candidate.take_profit[0])}</span> : null}
                        </div>
                      ) : null}
                      <div className="mt-1 truncate text-[11px] text-slate-500">
                        {(candidate.blocked_reason[0] ?? candidate.reason[0] ?? "--")}
                      </div>
                      <StateMachine steps={readStateMachine(candidate.metadata.state_machine)} compact />
                      <div className="mt-2 flex min-w-0 flex-wrap gap-1">
                        <SetupAction
                          label={watchedIds.has(candidate.id) ? "Watching" : "Watch"}
                          onClick={() =>
                            setWatchedIds((current) => toggleSetValue(current, candidate.id))
                          }
                        />
                        <SetupAction
                          label="Reject"
                          onClick={() =>
                            setRejectedIds((current) => addSetValue(current, candidate.id))
                          }
                        />
                        <SetupAction
                          label="Disable PB"
                          onClick={() =>
                            setDisabledPlaybooks((current) => addSetValue(current, candidate.playbook))
                          }
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : null,
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function SetupAction({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <span
      className="rounded border border-ink-700 bg-ink-950 px-1.5 py-0.5 text-[10px] text-slate-300 hover:border-cyan-500 hover:text-cyan-100"
      role="button"
      tabIndex={0}
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        event.stopPropagation();
        onClick();
      }}
    >
      {label}
    </span>
  );
}

function TradeMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-xs text-slate-500">{label}</span>
      <strong className="shrink-0 whitespace-nowrap text-right text-sm text-slate-100">{value}</strong>
    </div>
  );
}

function TradeDetails({ trade, showToast }: { trade: TradeOrder; showToast: (kind: ToastMessage["kind"], text: string) => void }) {
  const setSelected = useChartStore((state) => state.setSelected);
  const metadata = trade.metadata ?? {};
  const candidateMetadata = readObject(metadata.candidate_metadata);
  const stateMachine = readStateMachine(candidateMetadata.state_machine);
  const reasons = readStringList(metadata.reason);
  const blockedReasons = readStringList(metadata.blocked_reason);
  const triggerTypes = readStringList(candidateMetadata.trigger_types);
  const takeProfit = firstTakeProfitPrice(trade.take_profit);
  const statusNote = tradeStatusNote(trade.status);
  return (
    <div className="grid gap-3 text-sm">
      <div className="grid gap-2">
        <Detail label="Playbook" value={playbookLabel(trade.playbook)} />
        <Detail label="Side" value={trade.side} />
        <Detail label="Status" value={trade.status} />
        <Detail label="Backtest" value={metadata.backtest === true ? "true" : "--"} />
      </div>

      {statusNote ? (
        <div className="rounded-md border border-yellow-300/25 bg-yellow-300/[0.06] p-2 text-xs leading-relaxed text-yellow-50">
          {statusNote}
        </div>
      ) : null}

      <div className="grid gap-2 rounded-md border border-ink-700 bg-ink-950/60 p-3">
        <TradeMetric label="Entry" value={price(trade.entry_price)} />
        <TradeMetric label="SL" value={price(trade.stop_loss)} />
        <TradeMetric label="TP" value={price(takeProfit)} />
        <TradeMetric label="Exit" value={price(trade.close_price)} />
        <TradeMetric label="PnL R" value={trade.pnl_r === null ? "--" : `${trade.pnl_r.toFixed(2)}R`} />
        <TradeMetric label="Score" value={formatUnknownNumber(metadata.score)} />
      </div>

      <div className="grid gap-2">
        <Detail label="Opened" value={compactTime(trade.opened_at)} />
        <Detail label="Closed" value={compactTime(trade.closed_at)} />
        <Detail label="Reaction" value={String(metadata.zone_reaction_state ?? "--")} />
        <Detail label="Zone" value={String(candidateMetadata.zone_type ?? "--")} />
        <Detail label="Trigger" value={triggerTypes.length > 0 ? triggerTypes.join(" + ") : "--"} />
      </div>

      <StateMachine steps={stateMachine} />

      <div className="grid gap-1">
        <div className="text-xs text-slate-500">Reason</div>
        <div className="rounded-md border border-cyan-400/25 bg-cyan-400/[0.06] p-2 text-xs leading-relaxed text-cyan-50">
          {reasons.length > 0 ? (
            <ul className="grid gap-1">
              {reasons.map((reason, index) => (
                <li key={`${reason}-${index}`}>• {reason}</li>
              ))}
            </ul>
          ) : (
            "--"
          )}
        </div>
      </div>

      {blockedReasons.length > 0 ? (
        <div className="grid gap-1">
          <div className="text-xs text-slate-500">Blocked reason at signal</div>
          <div className="rounded-md border border-rose-400/25 bg-rose-500/[0.06] p-2 text-xs leading-relaxed text-rose-50">
            <ul className="grid gap-1">
              {blockedReasons.map((reason, index) => (
                <li key={`${reason}-${index}`}>• {reason}</li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}

      <TradeReviewEditor
        trade={trade}
        showToast={showToast}
        onSaved={(review) => {
          setSelected({ kind: "trade", entity: { ...trade, review } });
        }}
      />
    </div>
  );
}

const REVIEW_TAGS = [
  ["wrong_bias", "Wrong bias"],
  ["wrong_regime", "Wrong regime"],
  ["weak_zone", "Weak zone"],
  ["zone_already_broken", "Zone broken"],
  ["weak_reaction", "Weak reaction"],
  ["weak_breakout", "Weak breakout"],
  ["bad_entry", "Bad entry"],
  ["sl_too_tight", "SL too tight"],
  ["tp_unrealistic", "TP unrealistic"],
  ["against_momentum", "Against momentum"],
  ["news_risk", "News risk"],
  ["good_context", "Good context"],
] as const;

function TradeReviewEditor({
  trade,
  onSaved,
  showToast,
}: {
  trade: TradeOrder;
  onSaved: (review: TradeReview) => void;
  showToast: (kind: ToastMessage["kind"], text: string) => void;
}) {
  const review = trade.review;
  const [grade, setGrade] = useState(review?.grade ?? "");
  const [verdict, setVerdict] = useState(review?.verdict ?? "unreviewed");
  const [shouldTradeAgain, setShouldTradeAgain] = useState(review?.should_trade_again ?? "unknown");
  const [mistakeTags, setMistakeTags] = useState<Set<string>>(new Set(review?.mistake_tags ?? []));
  const [comment, setComment] = useState(review?.comment ?? "");
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () =>
      updateTradeReview(trade.id, {
        grade: grade || null,
        verdict,
        mistake_tags: Array.from(mistakeTags),
        should_trade_again: shouldTradeAgain,
        comment,
        reviewer: "human",
      }),
    onSuccess: (savedReview) => {
      setError(null);
      onSaved(savedReview);
      showToast("success", "Trade review saved.");
    },
    onError: (err) => {
      const message = err instanceof Error ? err.message : "Could not save trade review.";
      setError(message);
      showToast("error", message);
    },
  });
  const saveReview = useCallback(() => {
    mutation.mutate();
  }, [mutation]);

  useEffect(() => {
    setGrade(review?.grade ?? "");
    setVerdict(review?.verdict ?? "unreviewed");
    setShouldTradeAgain(review?.should_trade_again ?? "unknown");
    setMistakeTags(new Set(review?.mistake_tags ?? []));
    setComment(review?.comment ?? "");
    setError(null);
  }, [review, trade.id]);

  const toggleTag = (tag: string) => {
    setMistakeTags((current) => toggleSetValue(current, tag));
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return;
      if (event.key.toLowerCase() !== "s") return;
      event.preventDefault();
      saveReview();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [saveReview]);

  return (
    <div className="grid gap-3 rounded-md border border-ink-700 bg-ink-950/60 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Human Review</div>
        <div className="flex items-center gap-2">
          {review?.updated_at ? <span className="hidden text-[10px] text-slate-600 sm:inline">{compactTime(review.updated_at)}</span> : null}
          <button
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-cyan-400/60 bg-cyan-400/15 px-2 text-xs font-semibold text-cyan-100 hover:bg-cyan-400/25 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={mutation.isPending}
            title="Save review (S)"
            type="button"
            onClick={saveReview}
          >
            <Save size={13} />
            {mutation.isPending ? "Saving" : "Save"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <ReviewSelect value={grade} onChange={setGrade} options={[["", "No grade"], ["A", "A"], ["B", "B"], ["C", "C"], ["D", "D"]]} />
        <ReviewSelect
          value={verdict}
          onChange={setVerdict}
          options={[
            ["unreviewed", "Unreviewed"],
            ["good_trade", "Good trade"],
            ["bad_trade", "Bad trade"],
            ["should_skip", "Should skip"],
            ["missed_context", "Missed context"],
          ]}
        />
      </div>

      <ReviewSelect
        value={shouldTradeAgain}
        onChange={setShouldTradeAgain}
        options={[
          ["unknown", "Trade again?"],
          ["yes", "Yes"],
          ["no", "No"],
          ["conditional", "Conditional"],
        ]}
      />

      <div className="flex flex-wrap gap-1.5">
        {REVIEW_TAGS.map(([tag, label]) => (
          <button
            key={tag}
            className={`rounded border px-2 py-1 text-[11px] transition ${
              mistakeTags.has(tag)
                ? "border-cyan-300/70 bg-cyan-300/15 text-cyan-100"
                : "border-ink-700 bg-ink-850 text-slate-400 hover:border-slate-500 hover:text-slate-200"
            }`}
            type="button"
            onClick={() => toggleTag(tag)}
          >
            {label}
          </button>
        ))}
      </div>

      <label className="grid gap-1 text-xs text-slate-500">
        Comment
        <textarea
          className="min-h-24 resize-y rounded-md border border-ink-700 bg-ink-850 px-2 py-2 text-sm leading-relaxed text-slate-100 outline-none focus:border-cyan-400"
          placeholder="Ví dụ: Breakout quá yếu, zone đã bị xuyên trước đó, nên bỏ qua lệnh này..."
          value={comment}
          onChange={(event) => setComment(event.target.value)}
        />
      </label>

      {error ? <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-2 text-xs text-rose-100">{error}</div> : null}

      <button
        className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-cyan-400/60 bg-cyan-400/15 text-sm font-semibold text-cyan-100 hover:bg-cyan-400/25 disabled:cursor-not-allowed disabled:opacity-50"
        disabled={mutation.isPending}
        title="Save review (S)"
        type="button"
        onClick={saveReview}
      >
        <Save size={14} />
        {mutation.isPending ? "Saving review" : "Save review (S)"}
      </button>
    </div>
  );
}

function ReviewSelect({
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
      className="h-9 min-w-0 rounded-md border border-ink-700 bg-ink-850 px-2 text-xs text-slate-200 outline-none focus:border-cyan-400"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      {options.map(([optionValue, label]) => (
        <option key={optionValue} value={optionValue}>
          {label}
        </option>
      ))}
    </select>
  );
}

function ZoneEditor({
  zone,
  onZoneUpdated,
  showToast,
}: {
  zone: PriceZone;
  onZoneUpdated: () => void;
  showToast: (kind: ToastMessage["kind"], text: string) => void;
}) {
  const setSelected = useChartStore((state) => state.setSelected);
  const [priceLow, setPriceLow] = useState(String(zone.price_low));
  const [priceHigh, setPriceHigh] = useState(String(zone.price_high));
  const [weight, setWeight] = useState(String(zone.weight));
  const [confidence, setConfidence] = useState(String(zone.confidence));
  const [status, setStatus] = useState<"active" | "disabled">(zone.status === "disabled" ? "disabled" : "active");
  const [tradeModes, setTradeModes] = useState<ZoneTradeMode[]>(defaultTradeModes(zone));
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const isDirty = useMemo(() => {
    const low = Number(priceLow);
    const high = Number(priceHigh);
    const parsedWeight = Number(weight);
    const parsedConfidence = Number(confidence);
    return (
      low !== zone.price_low ||
      high !== zone.price_high ||
      parsedWeight !== zone.weight ||
      parsedConfidence !== zone.confidence ||
      status !== (zone.status === "disabled" ? "disabled" : "active") ||
      !sameTradeModes(tradeModes, defaultTradeModes(zone)) ||
      reason.trim().length > 0
    );
  }, [confidence, priceHigh, priceLow, reason, status, tradeModes, weight, zone]);

  useEffect(() => {
    setPriceLow(String(zone.price_low));
    setPriceHigh(String(zone.price_high));
    setWeight(String(zone.weight));
    setConfidence(String(zone.confidence));
    setStatus(zone.status === "disabled" ? "disabled" : "active");
    setTradeModes(defaultTradeModes(zone));
    setReason("");
    setError(null);
  }, [zone]);

  const reset = () => {
    setPriceLow(String(zone.price_low));
    setPriceHigh(String(zone.price_high));
    setWeight(String(zone.weight));
    setConfidence(String(zone.confidence));
    setStatus(zone.status === "disabled" ? "disabled" : "active");
    setTradeModes(defaultTradeModes(zone));
    setReason("");
    setError(null);
  };

  const save = useCallback(async () => {
    const low = Number(priceLow);
    const high = Number(priceHigh);
    const parsedWeight = Number(weight);
    const parsedConfidence = Number(confidence);
    if (!Number.isFinite(low) || !Number.isFinite(high) || low >= high) {
      setError("Price low must be lower than price high.");
      return;
    }
    if (!Number.isFinite(parsedWeight) || parsedWeight < 0 || parsedWeight > 1) {
      setError("Weight must be between 0 and 1.");
      return;
    }
    if (!Number.isFinite(parsedConfidence) || parsedConfidence < 0 || parsedConfidence > 1) {
      setError("Confidence must be between 0 and 1.");
      return;
    }
    if (!isDirty) {
      showToast("success", "Zone is already up to date.");
      return;
    }

    setIsSaving(true);
    setError(null);
    try {
      const updated = await updateZoneOverride(zone.id, {
        price_low: low,
        price_high: high,
        visual_start: zone.visual_start,
        visual_end: zone.visual_end,
        expires_at: zone.visual_end,
        weight: parsedWeight,
        confidence: parsedConfidence,
        status,
        reason: reason.trim() || undefined,
        trade_modes: tradeModes,
      });
      setSelected({ kind: "zone", entity: updated });
      onZoneUpdated();
      showToast("success", "Zone override saved.");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not save zone override.";
      setError(message);
      showToast("error", message);
    } finally {
      setIsSaving(false);
    }
  }, [confidence, isDirty, onZoneUpdated, priceHigh, priceLow, reason, setSelected, showToast, status, tradeModes, weight, zone]);

  const deleteZone = useCallback(async () => {
    if (isSaving) return;
    const confirmed = window.confirm(`Delete ${zoneDisplayName(zone)} zone from chart? This will hide it from chart payload.`);
    if (!confirmed) return;
    setIsSaving(true);
    setError(null);
    try {
      await deleteManualZone(zone.id, reason.trim() || "hotkey/manual delete");
      setSelected(null);
      onZoneUpdated();
      showToast("success", "Zone deleted from chart.");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not delete zone.";
      setError(message);
      showToast("error", message);
    } finally {
      setIsSaving(false);
    }
  }, [isSaving, onZoneUpdated, reason, setSelected, showToast, zone.id]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return;
      const key = event.key.toLowerCase();
      if (key === "s") {
        event.preventDefault();
        void save();
      } else if (key === "d" || key === "delete" || key === "backspace") {
        event.preventDefault();
        void deleteZone();
      } else if (key === "escape") {
        event.preventDefault();
        setSelected(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [deleteZone, save, setSelected]);

  return (
    <div className="grid gap-3 text-sm">
      <div className="grid gap-2">
        <Detail label="Type" value={zoneDisplayName(zone)} />
        <Detail label="Source" value={zone.source} />
        <Detail label="Start" value={compactTime(zone.visual_start)} />
        <Detail label="End" value={compactTime(zone.visual_end)} />
        <Detail label="Expires" value={compactTime(zone.valid_until)} />
        <Detail label="Touches" value={String(zone.metadata.touch_count_total ?? zone.metadata.touch_count ?? "--")} />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <NumberField label="Low" value={priceLow} onChange={setPriceLow} step="0.01" />
        <NumberField label="High" value={priceHigh} onChange={setPriceHigh} step="0.01" />
        <NumberField label="Weight" value={weight} onChange={setWeight} step="0.01" min="0" max="1" />
        <NumberField label="Confidence" value={confidence} onChange={setConfidence} step="0.01" min="0" max="1" />
      </div>

      <label className="grid gap-1 text-xs text-slate-500">
        Status
        <select
          className="h-9 rounded-md border border-ink-700 bg-ink-850 px-2 text-sm text-slate-100 outline-none"
          value={status}
          onChange={(event) => setStatus(event.target.value === "disabled" ? "disabled" : "active")}
        >
          <option value="active">active</option>
          <option value="disabled">disabled</option>
        </select>
      </label>

      <div className="grid gap-2 rounded-md border border-ink-700 bg-ink-950/50 p-3">
        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Trade modes</div>
        <div className="grid grid-cols-3 gap-2">
          {TRADE_MODE_OPTIONS.map((option) => (
            <label key={option.value} className="inline-flex items-center gap-2 rounded border border-ink-700 bg-ink-850 px-2 py-1.5 text-xs text-slate-200">
              <input
                checked={tradeModes.includes(option.value)}
                className="accent-cyan-400"
                type="checkbox"
                onChange={(event) => {
                  setTradeModes((current) =>
                    event.target.checked
                      ? Array.from(new Set([...current, option.value]))
                      : current.filter((mode) => mode !== option.value),
                  );
                }}
              />
              {option.label}
            </label>
          ))}
        </div>
      </div>

      <label className="grid gap-1 text-xs text-slate-500">
        Reason
        <textarea
          className="min-h-16 resize-none rounded-md border border-ink-700 bg-ink-850 px-2 py-2 text-sm text-slate-100 outline-none"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>

      {error ? <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-2 text-xs text-rose-100">{error}</div> : null}

      <div className="grid grid-cols-3 gap-2">
        <button
          className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-ink-700 bg-ink-800 text-sm text-slate-100 hover:border-slate-500"
          type="button"
          onClick={reset}
        >
          <RotateCcw size={14} />
          Reset
        </button>
        <button
          className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-cyan-400/60 bg-cyan-400/15 text-sm font-semibold text-cyan-100 hover:bg-cyan-400/25 disabled:cursor-not-allowed disabled:opacity-50"
          type="button"
          disabled={isSaving || !isDirty}
          onClick={save}
        >
          <Save size={14} />
          {isSaving ? "Saving" : "Save"}
        </button>
        <button
          className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-rose-400/50 bg-rose-500/10 text-sm font-semibold text-rose-100 hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          type="button"
          disabled={isSaving}
          title="Delete zone (D)"
          onClick={deleteZone}
        >
          <Trash2 size={14} />
          Delete
        </button>
      </div>
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
  step,
  min,
  max,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  step: string;
  min?: string;
  max?: string;
}) {
  return (
    <label className="grid gap-1 text-xs text-slate-500">
      {label}
      <input
        className="h-9 min-w-0 rounded-md border border-ink-700 bg-ink-850 px-2 text-sm text-slate-100 outline-none"
        max={max}
        min={min}
        step={step}
        type="number"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

const TRADE_MODE_OPTIONS: Array<{ value: ZoneTradeMode; label: string }> = [
  { value: "reject", label: "Reject" },
  { value: "internal_reject", label: "Internal" },
  { value: "breakout", label: "Breakout" },
];

function defaultTradeModes(zone: PriceZone): ZoneTradeMode[] {
  const raw = zone.metadata.trade_modes;
  if (Array.isArray(raw)) {
    const modes = raw.filter((mode): mode is ZoneTradeMode => mode === "reject" || mode === "internal_reject" || mode === "breakout");
    return modes;
  }
  if (zone.type === "fvg") return ["reject", "internal_reject"];
  if (zone.type === "consolidation") return ["breakout"];
  if (zone.type === "support" || zone.type === "resistance") return ["reject"];
  return [];
}

function sameTradeModes(first: ZoneTradeMode[], second: ZoneTradeMode[]): boolean {
  if (first.length !== second.length) return false;
  const normalized = new Set(first);
  return second.every((mode) => normalized.has(mode));
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
  const kind = zone.metadata.add_entity_kind;
  if (kind === "demand_order_block") return "Demand OB";
  if (kind === "supply_order_block") return "Supply OB";
  if (kind === "bullish_fvg") return "Bullish FVG";
  if (kind === "bearish_fvg") return "Bearish FVG";
  if (kind === "buy_side_liquidity") return "Buy-side Liquidity";
  if (kind === "sell_side_liquidity") return "Sell-side Liquidity";
  if (zone.type === "order_block") return zone.direction === "bullish" ? "Demand OB" : "Supply OB";
  if (zone.type === "fvg") return zone.direction === "bullish" ? "Bullish FVG" : "Bearish FVG";
  if (zone.type === "liquidity_pool") return "Liquidity Pool";
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
  if (status === "eligible") return "Eligible";
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

function playbookLabel(value: string): string {
  if (value === "sr_breakout_v1") return "SR Breakout V1";
  if (value === "zone_reaction_v2") return "Zone Reaction V2";
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function resolveLatestSelected(selected: SelectedEntity | null, zones: PriceZone[], trades: TradeOrder[]): SelectedEntity | null {
  if (!selected) return null;
  if (selected.kind === "zone") {
    const latest = zones.find((zone) => zone.id === selected.entity.id);
    return latest ? { kind: "zone", entity: latest } : selected;
  }
  if (selected.kind === "trade") {
    const latest = trades.find((trade) => trade.id === selected.entity.id);
    return latest ? { kind: "trade", entity: latest } : selected;
  }
  return selected;
}

function selectedNeedsSync(current: SelectedEntity, latest: SelectedEntity): boolean {
  if (current.kind !== latest.kind) return true;
  if (current.kind === "zone" && latest.kind === "zone") {
    const a = current.entity;
    const b = latest.entity;
    return (
      a.status !== b.status ||
      a.price_low !== b.price_low ||
      a.price_high !== b.price_high ||
      a.visual_start !== b.visual_start ||
      a.visual_end !== b.visual_end ||
      a.valid_until !== b.valid_until
    );
  }
  if (current.kind === "trade" && latest.kind === "trade") {
    const a = current.entity;
    const b = latest.entity;
    return a.status !== b.status || a.close_price !== b.close_price || a.pnl_r !== b.pnl_r;
  }
  return false;
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
