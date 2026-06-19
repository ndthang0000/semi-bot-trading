import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useState } from "react";
import { authFetch } from "../api/auth";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TradeReview {
  id: string | null;
  grade: string | null;
  verdict: string;
  mistake_tags: string[];
  should_trade_again: string;
  comment: string;
}

interface TradeOrder {
  id: string;
  playbook: string;
  direction: string;
  side: string;
  status: string;
  entry_price: number | null;
  stop_loss: number | null;
  take_profit: number[];
  quantity: number;
  opened_at: string | null;
  closed_at: string | null;
  close_price: number | null;
  pnl: number | null;
  pnl_r: number | null;
  source: string;
  metadata: Record<string, unknown>;
  review: TradeReview | null;
}

interface TradesResponse {
  trades: TradeOrder[];
  total: number;
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

async function fetchTrades(params: URLSearchParams): Promise<TradesResponse> {
  const res = await authFetch(`/api/trades?${params}`);
  if (!res.ok) throw new Error("Failed to fetch trades");
  return res.json();
}

async function saveReview(tradeId: string, body: Partial<TradeReview>): Promise<TradeReview> {
  const res = await authFetch(`/api/trades/${tradeId}/review`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Failed to save review");
  return res.json();
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC", hour12: false,
  });
}

function metaVal(m: Record<string, unknown>, key: string): string {
  const top = m?.[key];
  if (top !== undefined && top !== null) return String(top);
  const nested = (m?.candidate_metadata as Record<string, unknown> | undefined)?.[key];
  if (nested !== undefined && nested !== null) return String(nested);
  return "—";
}

const GRADES = ["A", "B", "C", "D"];
const VERDICTS = ["good_trade", "bad_trade", "missed_entry", "unreviewed"];
const MISTAKE_OPTIONS = [
  "early_entry", "late_entry", "wrong_direction", "ignored_bias",
  "ignored_regime", "overtraded", "moved_sl", "sized_wrong", "fomo",
];
const SHOULD_TRADE_AGAIN = ["yes", "no", "maybe", "unknown"];

// ---------------------------------------------------------------------------
// Detail Panel
// ---------------------------------------------------------------------------

function DetailPanel({ trade, onClose, onSaved }: {
  trade: TradeOrder;
  onClose: () => void;
  onSaved: () => void;
}) {
  const qc = useQueryClient();
  const existing = trade.review;
  const [grade, setGrade] = useState<string>(existing?.grade ?? "");
  const [verdict, setVerdict] = useState(existing?.verdict ?? "unreviewed");
  const [tags, setTags] = useState<string[]>(existing?.mistake_tags ?? []);
  const [shouldTrade, setShouldTrade] = useState(existing?.should_trade_again ?? "unknown");
  const [comment, setComment] = useState(existing?.comment ?? "");
  const [dirty, setDirty] = useState(false);

  const mutation = useMutation({
    mutationFn: () => saveReview(trade.id, { grade: grade || null, verdict, mistake_tags: tags, should_trade_again: shouldTrade, comment }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["journal-trades"] });
      setDirty(false);
      onSaved();
    },
  });

  const toggleTag = (tag: string) => {
    setTags((prev) => prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]);
    setDirty(true);
  };

  const m = trade.metadata ?? {};
  const rr = trade.take_profit[0] && trade.entry_price && trade.stop_loss
    ? Math.abs((trade.take_profit[0] - trade.entry_price) / (trade.entry_price - trade.stop_loss))
    : null;

  return (
    <div className="flex h-full flex-col border-l border-ink-700 bg-ink-900 text-slate-100">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-ink-700 px-4 py-3">
        <div>
          <div className="text-sm font-semibold">{trade.playbook}</div>
          <div className="text-xs text-slate-500">{trade.id.slice(0, 24)}…</div>
        </div>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-300">
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-5">
        {/* Trade info */}
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Trade Info</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            {[
              ["Direction", trade.direction ?? trade.side],
              ["Entry", trade.entry_price?.toFixed(2) ?? "—"],
              ["Stop Loss", trade.stop_loss?.toFixed(2) ?? "—"],
              ["Take Profit", trade.take_profit[0]?.toFixed(2) ?? "—"],
              ["R:R", rr ? `1:${rr.toFixed(2)}` : "—"],
              ["PnL (R)", trade.pnl_r !== null ? `${trade.pnl_r >= 0 ? "+" : ""}${trade.pnl_r.toFixed(2)}R` : "—"],
              ["Opened", fmt(trade.opened_at)],
              ["Closed", fmt(trade.closed_at)],
              ["Status", trade.status],
              ["Quantity", trade.quantity],
            ].map(([k, v]) => (
              <div key={String(k)} className="flex justify-between py-0.5">
                <span className="text-slate-500">{k}</span>
                <span className={`font-medium ${String(k) === "PnL (R)" ? (trade.pnl_r ?? 0) >= 0 ? "text-green-400" : "text-red-400" : "text-slate-300"}`}>{v}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Context metadata */}
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Context</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            {[
              ["Session", metaVal(m, "session")],
              ["Macro Trend", metaVal(m, "macro_trend")],
              ["H1 Bias", metaVal(m, "h1_bias")],
              ["H1 Regime", metaVal(m, "h1_regime")],
              ["Zone Type", metaVal(m, "zone_type")],
              ["Zone Source", metaVal(m, "zone_source")],
              ["Zone Detector", metaVal(m, "zone_detector")],
              ["ATR", metaVal(m, "atr")],
              ["Confluence", metaVal(m, "confluence_count")],
              ["Zone State", String(trade.metadata?.zone_reaction_state ?? "—")],
            ].map(([k, v]) => (
              <div key={String(k)} className="flex justify-between py-0.5">
                <span className="text-slate-500">{k}</span>
                <span className="text-slate-300 font-medium">{v}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Review */}
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Review</div>

          {/* Grade */}
          <div className="mb-3">
            <div className="mb-1 text-xs text-slate-500">Grade</div>
            <div className="flex gap-1">
              {GRADES.map((g) => (
                <button
                  key={g}
                  onClick={() => { setGrade(grade === g ? "" : g); setDirty(true); }}
                  className={[
                    "h-8 w-8 rounded text-xs font-bold transition-colors",
                    grade === g
                      ? g === "A" ? "bg-green-600 text-white"
                        : g === "B" ? "bg-blue-600 text-white"
                        : g === "C" ? "bg-yellow-600 text-white"
                        : "bg-red-600 text-white"
                      : "border border-ink-700 text-slate-500 hover:border-slate-500",
                  ].join(" ")}
                >
                  {g}
                </button>
              ))}
            </div>
          </div>

          {/* Verdict */}
          <div className="mb-3">
            <div className="mb-1 text-xs text-slate-500">Verdict</div>
            <div className="flex flex-wrap gap-1">
              {VERDICTS.map((v) => (
                <button
                  key={v}
                  onClick={() => { setVerdict(v); setDirty(true); }}
                  className={[
                    "rounded px-2 py-1 text-xs transition-colors",
                    verdict === v ? "bg-blue-600/30 text-blue-300 ring-1 ring-blue-500" : "border border-ink-700 text-slate-500 hover:border-slate-500",
                  ].join(" ")}
                >
                  {v.replace(/_/g, " ")}
                </button>
              ))}
            </div>
          </div>

          {/* Mistake tags */}
          <div className="mb-3">
            <div className="mb-1 text-xs text-slate-500">Mistake Tags</div>
            <div className="flex flex-wrap gap-1">
              {MISTAKE_OPTIONS.map((tag) => (
                <button
                  key={tag}
                  onClick={() => toggleTag(tag)}
                  className={[
                    "rounded px-2 py-0.5 text-xs transition-colors",
                    tags.includes(tag) ? "bg-red-600/30 text-red-300 ring-1 ring-red-500" : "border border-ink-700 text-slate-500 hover:border-slate-500",
                  ].join(" ")}
                >
                  {tag.replace(/_/g, " ")}
                </button>
              ))}
            </div>
          </div>

          {/* Should trade again */}
          <div className="mb-3">
            <div className="mb-1 text-xs text-slate-500">Trade again?</div>
            <div className="flex gap-1">
              {SHOULD_TRADE_AGAIN.map((v) => (
                <button
                  key={v}
                  onClick={() => { setShouldTrade(v); setDirty(true); }}
                  className={[
                    "rounded px-2 py-1 text-xs capitalize transition-colors",
                    shouldTrade === v ? "bg-slate-600 text-slate-100 ring-1 ring-slate-400" : "border border-ink-700 text-slate-500 hover:border-slate-500",
                  ].join(" ")}
                >
                  {v}
                </button>
              ))}
            </div>
          </div>

          {/* Comment */}
          <div className="mb-3">
            <div className="mb-1 text-xs text-slate-500">Comment</div>
            <textarea
              rows={3}
              value={comment}
              onChange={(e) => { setComment(e.target.value); setDirty(true); }}
              placeholder="Notes about this trade…"
              className="w-full rounded border border-ink-700 bg-ink-950 px-3 py-2 text-xs text-slate-200 placeholder-slate-600 focus:border-blue-500 focus:outline-none resize-none"
            />
          </div>

          <button
            onClick={() => mutation.mutate()}
            disabled={!dirty || mutation.isPending}
            className="w-full rounded bg-blue-600 px-3 py-2 text-xs font-semibold text-white hover:bg-blue-500 disabled:opacity-40 transition-colors"
          >
            {mutation.isPending ? "Saving…" : "Save Review"}
          </button>
          {mutation.isError && <div className="mt-1 text-xs text-red-400">Failed to save.</div>}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Filter bar
// ---------------------------------------------------------------------------

interface Filters {
  outcome: string;
  playbook: string;
  direction: string;
  reviewed: string;
}

function FilterBar({ filters, onChange }: { filters: Filters; onChange: (f: Filters) => void }) {
  const set = (key: keyof Filters, val: string) => onChange({ ...filters, [key]: val });
  const btnCls = (active: boolean) =>
    `px-2 py-1 text-xs rounded transition-colors ${active ? "bg-blue-600/30 text-blue-300 ring-1 ring-blue-500" : "text-slate-500 hover:text-slate-300"}`;

  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-ink-700 bg-ink-900 px-4 py-2">
      <div className="flex items-center gap-1">
        <span className="text-xs text-slate-600">Outcome</span>
        {[["all", "All"], ["win", "Win"], ["loss", "Loss"]].map(([v, l]) => (
          <button key={v} className={btnCls(filters.outcome === v)} onClick={() => set("outcome", v)}>{l}</button>
        ))}
      </div>
      <div className="flex items-center gap-1">
        <span className="text-xs text-slate-600">Direction</span>
        {[["all", "All"], ["long", "Long"], ["short", "Short"]].map(([v, l]) => (
          <button key={v} className={btnCls(filters.direction === v)} onClick={() => set("direction", v)}>{l}</button>
        ))}
      </div>
      <div className="flex items-center gap-1">
        <span className="text-xs text-slate-600">Reviewed</span>
        {[["all", "All"], ["yes", "Yes"], ["no", "No"]].map(([v, l]) => (
          <button key={v} className={btnCls(filters.reviewed === v)} onClick={() => set("reviewed", v)}>{l}</button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trade row
// ---------------------------------------------------------------------------

function TradeRow({ trade, selected, onClick }: { trade: TradeOrder; selected: boolean; onClick: () => void }) {
  const r = trade.pnl_r;
  const hasReview = !!trade.review?.grade;
  return (
    <tr
      onClick={onClick}
      className={[
        "cursor-pointer border-b border-ink-700/50 text-xs transition-colors",
        selected ? "bg-blue-600/10" : "hover:bg-ink-800",
      ].join(" ")}
    >
      <td className="px-3 py-2 text-slate-400 whitespace-nowrap">{fmt(trade.opened_at)}</td>
      <td className="px-3 py-2 text-slate-300">{trade.playbook}</td>
      <td className={`px-3 py-2 font-medium ${trade.direction === "long" || trade.side === "buy" ? "text-green-400" : "text-red-400"}`}>
        {trade.direction ?? trade.side}
      </td>
      <td className="px-3 py-2 text-slate-400">{trade.entry_price?.toFixed(2) ?? "—"}</td>
      <td className="px-3 py-2 text-slate-400">{trade.stop_loss?.toFixed(2) ?? "—"}</td>
      <td className={`px-3 py-2 font-semibold text-right ${r !== null ? r >= 0 ? "text-green-400" : "text-red-400" : "text-slate-500"}`}>
        {r !== null ? `${r >= 0 ? "+" : ""}${r.toFixed(2)}R` : "open"}
      </td>
      <td className="px-3 py-2 text-center">
        {hasReview ? (
          <span className={`rounded px-1.5 py-0.5 text-xs font-bold ${
            trade.review!.grade === "A" ? "bg-green-600/30 text-green-300"
            : trade.review!.grade === "B" ? "bg-blue-600/30 text-blue-300"
            : trade.review!.grade === "C" ? "bg-yellow-600/30 text-yellow-300"
            : "bg-red-600/30 text-red-300"
          }`}>
            {trade.review!.grade}
          </span>
        ) : (
          <span className="text-slate-700">—</span>
        )}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function JournalPage() {
  const [filters, setFilters] = useState<Filters>({ outcome: "all", playbook: "", direction: "all", reviewed: "all" });
  const [selected, setSelected] = useState<TradeOrder | null>(null);
  const qc = useQueryClient();

  const params = new URLSearchParams({ limit: "500", backtest: "false" });
  if (filters.outcome !== "all") params.set("outcome", filters.outcome);
  if (filters.direction !== "all") params.set("side", filters.direction);

  const { data, isLoading } = useQuery({
    queryKey: ["journal-trades", params.toString()],
    queryFn: () => fetchTrades(params),
    staleTime: 15_000,
  });

  const trades = (data?.trades ?? []).filter((t) => {
    if (filters.reviewed === "yes" && !t.review?.grade) return false;
    if (filters.reviewed === "no" && t.review?.grade) return false;
    return true;
  });

  // Keep selected trade in sync after review save
  const selectedFresh = selected ? (trades.find((t) => t.id === selected.id) ?? selected) : null;

  return (
    <div className="flex h-full overflow-hidden bg-ink-950 text-slate-100">
      {/* Left: list */}
      <div className={`flex flex-col ${selectedFresh ? "w-[60%]" : "w-full"} min-w-0 transition-all`}>
        <div className="border-b border-ink-700 bg-ink-900 px-4 py-3">
          <h1 className="text-sm font-semibold">Trade Journal</h1>
          <div className="text-xs text-slate-500">{trades.length} trades</div>
        </div>
        <FilterBar filters={filters} onChange={setFilters} />

        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex h-32 items-center justify-center text-sm text-slate-500">Loading…</div>
          ) : trades.length === 0 ? (
            <div className="flex h-32 items-center justify-center text-sm text-slate-600">No trades found</div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="border-b border-ink-700 bg-ink-900 text-xs text-slate-500">
                  <th className="px-3 py-2 text-left font-normal">Date (UTC)</th>
                  <th className="px-3 py-2 text-left font-normal">Playbook</th>
                  <th className="px-3 py-2 text-left font-normal">Dir</th>
                  <th className="px-3 py-2 text-left font-normal">Entry</th>
                  <th className="px-3 py-2 text-left font-normal">SL</th>
                  <th className="px-3 py-2 text-right font-normal">PnL</th>
                  <th className="px-3 py-2 text-center font-normal">Grade</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <TradeRow
                    key={t.id}
                    trade={t}
                    selected={selectedFresh?.id === t.id}
                    onClick={() => setSelected(selectedFresh?.id === t.id ? null : t)}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Right: detail panel */}
      {selectedFresh && (
        <div className="w-[40%] min-w-[320px] flex-shrink-0">
          <DetailPanel
            trade={selectedFresh}
            onClose={() => setSelected(null)}
            onSaved={() => qc.invalidateQueries({ queryKey: ["journal-trades"] })}
          />
        </div>
      )}
    </div>
  );
}
