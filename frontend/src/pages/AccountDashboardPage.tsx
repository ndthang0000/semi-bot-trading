import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { authFetch } from "../api/auth";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TradeMeta {
  // top-level shortcuts (new trades)
  session?: string;
  macro_trend?: string;
  zone_type?: string;
  zone_source?: string;
  zone_detector?: string;
  h1_bias?: string;
  h1_regime?: string;
  confluence_count?: number;
  atr?: number;
  // nested fallback (older trades)
  candidate_metadata?: {
    macro_trend?: string;
    zone_type?: string;
    zone_source?: string;
    zone_detector?: string;
    h1_bias?: string;
    h1_regime?: string;
    confluence_count?: number;
    atr?: number;
  };
}

interface TradeOrder {
  id: string;
  playbook: string;
  direction: string;
  side: string;
  status: string;
  entry_price: number | null;
  stop_loss: number | null;
  opened_at: string | null;
  closed_at: string | null;
  pnl: number | null;
  pnl_r: number | null;
  source: string;
  metadata: TradeMeta;
}

interface TradesResponse {
  trades: TradeOrder[];
  total: number;
}

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

const ACCOUNT_TRADES_LIMIT = 1000;

async function fetchAllTrades(): Promise<TradeOrder[]> {
  const res = await authFetch(`/api/trades?limit=${ACCOUNT_TRADES_LIMIT}&backtest=false`);
  if (!res.ok) throw new Error("Failed to fetch trades");
  const data: TradesResponse = await res.json();
  return data.trades ?? [];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Read a metadata field — prefer top-level shortcut, fall back to nested candidate_metadata. */
function metaField(t: TradeOrder, key: keyof NonNullable<TradeMeta["candidate_metadata"]>): string {
  const top = (t.metadata as Record<string, unknown>)?.[key];
  if (top !== undefined && top !== null) return String(top);
  const nested = t.metadata?.candidate_metadata?.[key];
  if (nested !== undefined && nested !== null) return String(nested);
  return "unknown";
}

function getSession(openedAt: string | null): string {
  if (!openedAt) return "Unknown";
  const h = new Date(openedAt).getUTCHours();
  if (h < 7) return "Asian";
  if (h < 12) return "London";
  if (h < 17) return "London-NY";
  if (h < 21) return "New York";
  return "Off-hours";
}

function groupBy<T>(arr: T[], key: (item: T) => string): Record<string, T[]> {
  return arr.reduce(
    (acc, item) => {
      const k = key(item);
      (acc[k] ??= []).push(item);
      return acc;
    },
    {} as Record<string, T[]>,
  );
}

function winRate(trades: TradeOrder[]): string {
  const closed = trades.filter((t) => t.pnl_r !== null);
  if (!closed.length) return "—";
  const wins = closed.filter((t) => (t.pnl_r ?? 0) > 0).length;
  return `${Math.round((wins / closed.length) * 100)}%`;
}

function totalR(trades: TradeOrder[]): number {
  return trades.reduce((sum, t) => sum + (t.pnl_r ?? 0), 0);
}

function expectancy(trades: TradeOrder[]): string {
  const closed = trades.filter((t) => t.pnl_r !== null);
  if (!closed.length) return "—";
  return (totalR(closed) / closed.length).toFixed(2) + "R";
}

function maxDrawdown(trades: TradeOrder[]): string {
  const closed = trades.filter((t) => t.pnl_r !== null).sort((a, b) => (a.opened_at ?? "").localeCompare(b.opened_at ?? ""));
  let peak = 0, equity = 0, maxDD = 0;
  for (const t of closed) {
    equity += t.pnl_r ?? 0;
    if (equity > peak) peak = equity;
    const dd = peak - equity;
    if (dd > maxDD) maxDD = dd;
  }
  return maxDD === 0 ? "0R" : `-${maxDD.toFixed(2)}R`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-900 p-4">
      <div className="mb-1 text-xs text-slate-500">{label}</div>
      <div className={`text-2xl font-bold ${color ?? "text-slate-100"}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-600">{sub}</div>}
    </div>
  );
}

function EquityCurve({ trades }: { trades: TradeOrder[] }) {
  const closed = [...trades]
    .filter((t) => t.pnl_r !== null && t.opened_at)
    .sort((a, b) => (a.opened_at ?? "").localeCompare(b.opened_at ?? ""));

  if (closed.length < 2) return <div className="flex h-32 items-center justify-center text-sm text-slate-600">Not enough data</div>;

  let equity = 0;
  const points: number[] = [0];
  for (const t of closed) {
    equity += t.pnl_r ?? 0;
    points.push(equity);
  }

  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const w = 600, h = 120, pad = 8;

  const coords = points.map((v, i) => {
    const x = pad + (i / (points.length - 1)) * (w - pad * 2);
    const y = h - pad - ((v - min) / range) * (h - pad * 2);
    return `${x},${y}`;
  });

  const lastVal = points[points.length - 1];
  const lineColor = lastVal >= 0 ? "#4ade80" : "#f87171";

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" preserveAspectRatio="none">
      {/* Zero line */}
      {min < 0 && max > 0 && (
        <line
          x1={pad} x2={w - pad}
          y1={h - pad - ((0 - min) / range) * (h - pad * 2)}
          y2={h - pad - ((0 - min) / range) * (h - pad * 2)}
          stroke="#334155" strokeWidth="1" strokeDasharray="4,4"
        />
      )}
      <polyline points={coords.join(" ")} fill="none" stroke={lineColor} strokeWidth="1.5" />
      {/* Fill under curve */}
      <polygon
        points={`${pad},${h - pad} ${coords.join(" ")} ${w - pad},${h - pad}`}
        fill={lineColor} fillOpacity="0.08"
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// PnL Bar Chart
// ---------------------------------------------------------------------------

type PeriodMode = "week" | "month" | "year";

/** Get Monday of the ISO week containing `date` (UTC) */
function weekMonday(date: Date): Date {
  const d = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  const dow = (d.getUTCDay() + 6) % 7; // Mon=0
  d.setUTCDate(d.getUTCDate() - dow);
  return d;
}

function addDays(d: Date, n: number): Date {
  return new Date(d.getTime() + n * 86400000);
}

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/** Build the fixed set of slots + labels for each mode */
function buildSlots(mode: PeriodMode, anchor: Date, trades: TradeOrder[]): {
  slots: { key: string; label: string }[];
  nav: boolean;
} {
  if (mode === "week") {
    const mon = weekMonday(anchor);
    const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri"];
    const slots = Array.from({ length: 5 }, (_, i) => {
      const d = addDays(mon, i);
      const key = isoDate(d);
      const label = `${DAY_NAMES[i]} ${d.getUTCDate()}`;
      return { key, label };
    });
    return { slots, nav: true };
  }

  if (mode === "month") {
    const y = anchor.getUTCFullYear();
    const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    const slots = MONTHS.map((label, i) => ({ key: `${y}-${String(i + 1).padStart(2, "0")}`, label }));
    return { slots, nav: true };
  }

  // year — dynamic: all years in data
  const years = [...new Set(
    trades
      .filter((t) => t.opened_at)
      .map((t) => String(new Date(t.opened_at!).getUTCFullYear()))
  )].sort();
  if (years.length === 0) years.push(String(anchor.getUTCFullYear()));
  const slots = years.map((y) => ({ key: y, label: y }));
  return { slots, nav: false };
}

/** Map each trade to a slot key */
function tradeSlotKey(t: TradeOrder, mode: PeriodMode): string {
  const d = new Date(t.opened_at!);
  if (mode === "week") return isoDate(d);
  if (mode === "month") {
    const y = d.getUTCFullYear();
    const m = String(d.getUTCMonth() + 1).padStart(2, "0");
    return `${y}-${m}`;
  }
  return String(d.getUTCFullYear());
}

function PnlBarChart({ trades }: { trades: TradeOrder[] }) {
  const [mode, setMode] = useState<PeriodMode>("month");
  const [anchor, setAnchor] = useState<Date>(() => new Date());

  const closed = trades.filter((t) => t.pnl_r !== null && t.opened_at);
  const { slots, nav } = buildSlots(mode, anchor, closed);

  // Aggregate per slot
  const buckets: Record<string, { profit: number; loss: number }> = {};
  for (const { key } of slots) buckets[key] = { profit: 0, loss: 0 };
  for (const t of closed) {
    const key = tradeSlotKey(t, mode);
    if (buckets[key]) {
      const r = t.pnl_r ?? 0;
      if (r >= 0) buckets[key].profit += r;
      else buckets[key].loss += r;
    }
  }

  const totalProfit = Object.values(buckets).reduce((s, b) => s + b.profit, 0);
  const totalLoss = Object.values(buckets).reduce((s, b) => s + b.loss, 0);
  const net = totalProfit + totalLoss;

  // SVG
  const W = 600, H = 160, padX = 8, padY = 12, labelH = 22;
  const chartH = H - padY - labelH;
  const maxAbsSlot = Math.max(...slots.map((s) => Math.max(buckets[s.key].profit, Math.abs(buckets[s.key].loss))), 0.01);
  const slotW = (W - padX * 2) / slots.length;
  const barW = Math.max(4, slotW * 0.55);
  const zeroY = padY + chartH / 2;
  const half = chartH / 2;

  // Nav helpers
  const prev = () => {
    if (mode === "week") setAnchor((a) => addDays(weekMonday(a), -7));
    else if (mode === "month") setAnchor((a) => new Date(Date.UTC(a.getUTCFullYear() - 1, 0, 1)));
  };
  const next = () => {
    if (mode === "week") setAnchor((a) => addDays(weekMonday(a), 7));
    else if (mode === "month") setAnchor((a) => new Date(Date.UTC(a.getUTCFullYear() + 1, 0, 1)));
  };

  // Nav label
  const navLabel = mode === "week"
    ? (() => { const m = weekMonday(anchor); return `Week of ${m.toLocaleString("en", { month: "short", day: "numeric", timeZone: "UTC" })}`; })()
    : mode === "month" ? String(anchor.getUTCFullYear())
    : "";

  return (
    <div>
      {/* Header row */}
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <div className="text-xs text-slate-500">Profit / Loss (R)</div>
          <div className={`text-xl font-bold ${net >= 0 ? "text-green-400" : "text-red-400"}`}>
            {net >= 0 ? "+" : ""}{net.toFixed(2)}R
          </div>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          {/* Mode toggle */}
          <div className="flex rounded-lg border border-ink-700 p-0.5">
            {(["week", "month", "year"] as PeriodMode[]).map((p) => (
              <button
                key={p}
                onClick={() => { setMode(p); setAnchor(new Date()); }}
                className={[
                  "rounded px-2.5 py-0.5 text-xs capitalize transition-colors",
                  mode === p ? "bg-blue-600 text-white" : "text-slate-500 hover:text-slate-300",
                ].join(" ")}
              >
                {p.charAt(0).toUpperCase() + p.slice(1)}
              </button>
            ))}
          </div>
          {/* Period nav */}
          {nav && (
            <div className="flex items-center gap-1">
              <button onClick={prev} className="rounded px-1.5 py-0.5 text-xs text-slate-500 hover:text-slate-300 border border-ink-700 hover:border-slate-500">‹</button>
              <span className="text-xs text-slate-400 min-w-[80px] text-center">{navLabel}</span>
              <button onClick={next} className="rounded px-1.5 py-0.5 text-xs text-slate-500 hover:text-slate-300 border border-ink-700 hover:border-slate-500">›</button>
            </div>
          )}
        </div>
      </div>

      {/* SVG bars */}
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" preserveAspectRatio="none">
        {/* Zero line */}
        <line x1={padX} x2={W - padX} y1={zeroY} y2={zeroY} stroke="#334155" strokeWidth="1" />

        {slots.map(({ key, label }, i) => {
          const { profit, loss } = buckets[key];
          const cx = padX + i * slotW + slotW / 2;
          const profitH = (profit / maxAbsSlot) * half;
          const lossH = (Math.abs(loss) / maxAbsSlot) * half;

          return (
            <g key={key}>
              {profit > 0 && (
                <rect x={cx - barW / 2} y={zeroY - profitH} width={barW} height={profitH} fill="#4ade80" fillOpacity="0.85" rx="1.5" />
              )}
              {loss < 0 && (
                <rect x={cx - barW / 2} y={zeroY} width={barW} height={lossH} fill="#f87171" fillOpacity="0.85" rx="1.5" />
              )}
              {/* Empty slot indicator */}
              {profit === 0 && loss === 0 && (
                <rect x={cx - 1} y={zeroY - 2} width={2} height={4} fill="#334155" />
              )}
              <text x={cx} y={H - 4} textAnchor="middle" fontSize="8" fill="#475569">{label}</text>
            </g>
          );
        })}
      </svg>

      {/* Legend */}
      <div className="mt-1 flex gap-4 text-xs text-slate-500">
        <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-green-400" />Profit +{totalProfit.toFixed(2)}R</span>
        <span><span className="mr-1 inline-block h-2 w-2 rounded-sm bg-red-400" />Loss {totalLoss.toFixed(2)}R</span>
      </div>
    </div>
  );
}

function BreakdownTable({ title, groups }: { title: string; groups: Record<string, TradeOrder[]> }) {
  const rows = Object.entries(groups)
    .map(([key, trades]) => ({
      key,
      count: trades.filter((t) => t.pnl_r !== null).length,
      r: totalR(trades),
      wr: winRate(trades),
    }))
    .sort((a, b) => b.r - a.r);

  return (
    <div>
      <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">{title}</div>
      <div className="overflow-hidden rounded-lg border border-ink-700">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-ink-700 bg-ink-900">
              <th className="px-3 py-2 text-left text-slate-500 font-normal">{title}</th>
              <th className="px-3 py-2 text-right text-slate-500 font-normal">Trades</th>
              <th className="px-3 py-2 text-right text-slate-500 font-normal">Win%</th>
              <th className="px-3 py-2 text-right text-slate-500 font-normal">Total R</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} className="border-b border-ink-700/50 bg-ink-950 last:border-0">
                <td className="px-3 py-2 text-slate-300">{row.key}</td>
                <td className="px-3 py-2 text-right text-slate-400">{row.count}</td>
                <td className="px-3 py-2 text-right text-slate-400">{row.wr}</td>
                <td className={`px-3 py-2 text-right font-semibold ${row.r >= 0 ? "text-green-400" : "text-red-400"}`}>
                  {row.r >= 0 ? "+" : ""}{row.r.toFixed(2)}R
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Account Balance Bar (MT5 live data)
// ---------------------------------------------------------------------------

interface AccountSnapshot {
  label: string;
  broker: string | null;
  login: number | null;
  server: string | null;
  balance: number;
  equity: number;
  margin: number;
  free_margin: number;
  profit: number;
  currency: string;
  snapshot_at: string;
}

async function fetchAccounts(): Promise<AccountSnapshot[]> {
  const res = await authFetch("/api/accounts");
  if (!res.ok) return [];
  const data: { accounts: AccountSnapshot[] } = await res.json();
  return data.accounts ?? [];
}

function staleness(snapshotAt: string): { stale: boolean; label: string } {
  const ageMs = Date.now() - new Date(snapshotAt).getTime();
  const ageSec = Math.floor(ageMs / 1000);
  if (ageSec < 120) return { stale: false, label: `${ageSec}s ago` };
  if (ageSec < 3600) return { stale: true, label: `${Math.floor(ageSec / 60)}m ago` };
  return { stale: true, label: `${Math.floor(ageSec / 3600)}h ago` };
}

function AccountCard({ acc }: { acc: AccountSnapshot }) {
  const drawdownPct = acc.balance > 0 ? ((acc.balance - acc.equity) / acc.balance) * 100 : 0;
  const marginPct = acc.equity > 0 ? (acc.margin / acc.equity) * 100 : 0;
  const { stale, label: staleLabel } = staleness(acc.snapshot_at);
  const cur = acc.currency;

  return (
    <div className={`rounded-lg border bg-ink-900 p-4 ${stale ? "border-yellow-600/40" : "border-ink-700"}`}>
      {/* Header */}
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <div className="text-sm font-semibold text-slate-100">{acc.label}</div>
          <div className="text-xs text-slate-500">
            {acc.login} · {acc.server ?? acc.broker ?? "MT5"}
          </div>
        </div>
        <div className={`flex items-center gap-1 text-xs ${stale ? "text-yellow-500" : "text-green-500"}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${stale ? "bg-yellow-500" : "bg-green-500"}`} />
          {staleLabel}
        </div>
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-4">
        <div>
          <div className="text-slate-500">Balance</div>
          <div className="font-semibold text-slate-100">{acc.balance.toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} {cur}</div>
        </div>
        <div>
          <div className="text-slate-500">Equity</div>
          <div className={`font-semibold ${acc.equity >= acc.balance ? "text-green-400" : "text-red-400"}`}>
            {acc.equity.toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} {cur}
          </div>
        </div>
        <div>
          <div className="text-slate-500">Free Margin</div>
          <div className="font-semibold text-slate-100">{acc.free_margin.toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} {cur}</div>
        </div>
        <div>
          <div className="text-slate-500">Open P&L</div>
          <div className={`font-semibold ${acc.profit >= 0 ? "text-green-400" : "text-red-400"}`}>
            {acc.profit >= 0 ? "+" : ""}{acc.profit.toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} {cur}
          </div>
        </div>
      </div>

      {/* Progress bars */}
      <div className="mt-3 space-y-1.5">
        {/* Drawdown */}
        <div>
          <div className="mb-0.5 flex justify-between text-xs">
            <span className="text-slate-500">Drawdown</span>
            <span className={drawdownPct > 5 ? "text-red-400" : "text-slate-400"}>{drawdownPct.toFixed(2)}%</span>
          </div>
          <div className="h-1 w-full rounded-full bg-ink-700">
            <div
              className={`h-1 rounded-full transition-all ${drawdownPct > 10 ? "bg-red-500" : drawdownPct > 5 ? "bg-yellow-500" : "bg-green-500"}`}
              style={{ width: `${Math.min(drawdownPct, 100)}%` }}
            />
          </div>
        </div>
        {/* Margin used */}
        <div>
          <div className="mb-0.5 flex justify-between text-xs">
            <span className="text-slate-500">Margin used</span>
            <span className="text-slate-400">{marginPct.toFixed(1)}%</span>
          </div>
          <div className="h-1 w-full rounded-full bg-ink-700">
            <div
              className="h-1 rounded-full bg-blue-500 transition-all"
              style={{ width: `${Math.min(marginPct, 100)}%` }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function AccountBalanceBar() {
  const { data: accounts = [], isLoading } = useQuery({
    queryKey: ["accounts"],
    queryFn: fetchAccounts,
    refetchInterval: 30_000,
    staleTime: 25_000,
  });

  if (isLoading) return null;
  if (accounts.length === 0) {
    return (
      <div className="mb-6 rounded-lg border border-ink-700 bg-ink-900 px-4 py-3 text-xs text-slate-600">
        No MT5 account data yet — worker will populate this on the next cycle.
      </div>
    );
  }

  return (
    <div className={`mb-6 grid gap-3 ${accounts.length === 1 ? "" : "md:grid-cols-2"}`}>
      {accounts.map((acc) => <AccountCard key={acc.label} acc={acc} />)}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function AccountDashboardPage() {
  const { data: trades = [], isLoading, isError } = useQuery({
    queryKey: ["all-trades"],
    queryFn: fetchAllTrades,
    staleTime: 30_000,
  });

  const closed = trades.filter((t) => t.pnl_r !== null);
  const wins = closed.filter((t) => (t.pnl_r ?? 0) > 0);
  const total = totalR(closed);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-500">Loading trades...</div>
    );
  }

  if (isError) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-red-400">Failed to load trades.</div>
    );
  }

  return (
    <div className="h-full overflow-y-auto bg-ink-950 p-6 text-slate-100">
      <h1 className="mb-6 text-lg font-semibold text-slate-100">Account Dashboard</h1>

      {/* MT5 live account balance */}
      <AccountBalanceBar />

      {/* Stats row */}
      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
        <StatCard
          label="Total R"
          value={`${total >= 0 ? "+" : ""}${total.toFixed(2)}R`}
          sub={`${closed.length} closed trades`}
          color={total >= 0 ? "text-green-400" : "text-red-400"}
        />
        <StatCard label="Win Rate" value={winRate(closed)} sub={`${wins.length} wins`} color="text-blue-400" />
        <StatCard label="Expectancy" value={expectancy(closed)} color="text-slate-100" />
        <StatCard label="Max Drawdown" value={maxDrawdown(closed)} color="text-orange-400" />
        <StatCard label="Total Trades" value={String(trades.length)} sub={`${closed.length} closed`} />
        <StatCard
          label="Open"
          value={String(trades.length - closed.length)}
          color="text-yellow-400"
        />
      </div>

      {/* Charts row */}
      <div className="mb-6 grid gap-4 lg:grid-cols-2">
        <div className="rounded-lg border border-ink-700 bg-ink-900 p-4">
          <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-slate-500">Equity Curve (R)</div>
          <EquityCurve trades={trades} />
        </div>
        <div className="rounded-lg border border-ink-700 bg-ink-900 p-4">
          <PnlBarChart trades={trades} />
        </div>
      </div>

      {/* Breakdowns */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <BreakdownTable title="Playbook" groups={groupBy(closed, (t) => t.playbook ?? "unknown")} />
        <BreakdownTable title="Direction" groups={groupBy(closed, (t) => t.direction ?? t.side)} />
        <BreakdownTable title="Session" groups={groupBy(closed, (t) => {
          // prefer stored session field, fall back to deriving from opened_at
          const s = (t.metadata as Record<string, unknown>)?.session;
          return s ? String(s) : getSession(t.opened_at);
        })} />
        <BreakdownTable title="Macro Trend" groups={groupBy(closed, (t) => metaField(t, "macro_trend"))} />
        <BreakdownTable title="Zone Type" groups={groupBy(closed, (t) => metaField(t, "zone_type"))} />
        <BreakdownTable title="Zone Source" groups={groupBy(closed, (t) => metaField(t, "zone_source"))} />
        <BreakdownTable title="H1 Bias" groups={groupBy(closed, (t) => metaField(t, "h1_bias"))} />
        <BreakdownTable title="H1 Regime" groups={groupBy(closed, (t) => metaField(t, "h1_regime"))} />
      </div>
    </div>
  );
}
