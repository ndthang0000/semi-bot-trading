import { useQuery } from "@tanstack/react-query";
import { Brain, ChevronRight, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { authFetch } from "../api/auth";
import {
  drawCalmMessage,
  groupClosedTrades,
  readHandledGroupKeys,
  readSeenTradeIds,
  storeHandledGroupKeys,
  storeSeenTradeIds,
  type CalmTradeEvent,
} from "../lib/calmReset";
import { useCalmResetStore } from "../store/calmResetStore";
import { useNavigationStore } from "../store/navigationStore";
import type { TradeHistoryResponse, TradeOrder } from "../types";

type PromptStage = "idle" | "toast" | "modal";

export function CalmResetMonitor() {
  const activePage = useNavigationStore((state) => state.activePage);
  const setPage = useNavigationStore((state) => state.setPage);
  const activeReset = useCalmResetStore((state) => state.event);
  const beginReset = useCalmResetStore((state) => state.begin);
  const previewOutcome = useCalmResetStore((state) => state.previewOutcome);
  const consumePreview = useCalmResetStore((state) => state.consumePreview);
  const initialized = useRef(false);
  const [queue, setQueue] = useState<CalmTradeEvent[]>([]);
  const [current, setCurrent] = useState<CalmTradeEvent | null>(null);
  const [message, setMessage] = useState("");
  const [stage, setStage] = useState<PromptStage>("idle");

  const { data } = useQuery({
    queryKey: ["calm-reset-trade-monitor"],
    queryFn: fetchRecentlyClosedTrades,
    refetchInterval: 15_000,
    staleTime: 5_000,
  });

  useEffect(() => {
    if (!data) return;
    const closedTrades = data.filter(isCompletedLiveTrade);
    const seenIds = readSeenTradeIds();
    const handledGroups = readHandledGroupKeys();

    // The first response is a baseline. Calm Reset only reacts to closures
    // observed after monitoring starts, never to an old database history dump.
    if (!initialized.current) {
      initialized.current = true;
      storeSeenTradeIds([...seenIds, ...closedTrades.map((trade) => trade.id)]);
      storeHandledGroupKeys([
        ...handledGroups,
        ...groupClosedTrades(closedTrades).map((event) => event.groupKey),
      ]);
      return;
    }

    const newlyClosed = closedTrades.filter((trade) => !seenIds.has(trade.id));
    if (newlyClosed.length === 0) return;
    storeSeenTradeIds([...seenIds, ...closedTrades.map((trade) => trade.id)]);

    const newEvents = groupClosedTrades(newlyClosed).filter((event) => !handledGroups.has(event.groupKey));
    if (newEvents.length === 0) return;
    storeHandledGroupKeys([...handledGroups, ...newEvents.map((event) => event.groupKey)]);
    setQueue((existing) => [...existing, ...newEvents]);
  }, [data]);

  useEffect(() => {
    if (activeReset || current || queue.length === 0) return;
    const [next, ...rest] = queue;
    setQueue(rest);
    setCurrent(next);
    setMessage(drawCalmMessage(next.outcome));
    setStage("toast");
  }, [activeReset, current, queue]);

  useEffect(() => {
    if (!previewOutcome) return;
    const now = new Date().toISOString();
    setQueue((existing) => [
      ...existing,
      {
        id: `preview:${previewOutcome}:${now}`,
        groupKey: `preview:${previewOutcome}:${now}`,
        outcome: previewOutcome,
        pnlR: previewOutcome === "win" ? 1 : -1,
        closedAt: now,
        tradeIds: [],
        accountLabels: ["Preview"],
      },
    ]);
    consumePreview();
  }, [consumePreview, previewOutcome]);

  useEffect(() => {
    if (stage !== "toast") return;
    const timer = window.setTimeout(() => setStage("modal"), 2_200);
    return () => window.clearTimeout(timer);
  }, [stage]);

  if (!current || stage === "idle") return null;

  const tone = current.outcome === "win"
    ? {
        label: "TRADE WIN",
        result: "text-emerald-300",
        border: "border-emerald-400/30",
        glow: "shadow-[0_18px_60px_rgba(16,185,129,0.16)]",
        icon: "text-emerald-300",
      }
    : {
        label: "TRADE LOSS",
        result: "text-rose-300",
        border: "border-rose-400/30",
        glow: "shadow-[0_18px_60px_rgba(244,63,94,0.16)]",
        icon: "text-rose-300",
      };

  if (stage === "toast") {
    return (
      <div className={`fixed right-5 top-5 z-[90] w-[360px] rounded-xl border ${tone.border} bg-ink-900/95 p-4 ${tone.glow} backdrop-blur`}>
        <div className="flex items-start gap-3">
          <div className={`rounded-lg bg-ink-950 p-2 ${tone.icon}`}><Sparkles size={18} /></div>
          <div className="min-w-0">
            <div className="text-[10px] font-bold tracking-[0.2em] text-slate-500">CALM RESET · {tone.label}</div>
            <div className={`mt-1 text-xl font-bold ${tone.result}`}>{formatR(current.pnlR)}</div>
            <div className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-400">“{message}”</div>
          </div>
        </div>
      </div>
    );
  }

  const startGame = () => {
    const returnPage = activePage === "calm" ? "chart" : activePage;
    beginReset(current, message, returnPage);
    setCurrent(null);
    setStage("idle");
    setPage("calm");
  };

  return (
    <div className="pointer-events-none fixed inset-0 z-[90] flex items-center justify-end p-5">
      <div className={`pointer-events-auto w-[440px] overflow-hidden rounded-2xl border ${tone.border} bg-ink-900 ${tone.glow}`}>
        <div className="border-b border-ink-700 bg-gradient-to-r from-ink-950 to-ink-900 px-5 py-4">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-2">
              <Brain size={18} className={tone.icon} />
              <span className="text-xs font-bold tracking-[0.18em] text-slate-300">CALM RESET</span>
            </div>
            <span className={`text-sm font-bold ${tone.result}`}>{formatR(current.pnlR)}</span>
          </div>
          <div className="mt-1 text-[10px] uppercase tracking-[0.16em] text-slate-600">
            {tone.label} · {current.accountLabels.length} account{current.accountLabels.length > 1 ? "s" : ""}
          </div>
        </div>

        <div className="p-5">
          <blockquote className="min-h-[104px] border-l-2 border-cyan-400/40 pl-4 text-lg font-medium leading-relaxed text-slate-100">
            “{message}”
          </blockquote>
          <p className="mt-4 text-xs leading-relaxed text-slate-500">
            Modal không khóa chart hay quản lý vị thế. Khi sẵn sàng, dành khoảng 45 giây để reset nhịp thở.
          </p>
          <div className="mt-5 grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => setMessage(drawCalmMessage(current.outcome))}
              className="flex items-center justify-center gap-2 rounded-lg border border-ink-700 bg-ink-950 px-3 py-2.5 text-xs font-semibold text-slate-300 transition hover:border-slate-600 hover:text-white"
            >
              <RefreshCw size={14} />
              Đọc câu khác
            </button>
            <button
              type="button"
              onClick={startGame}
              className="flex items-center justify-center gap-2 rounded-lg border border-cyan-400/40 bg-cyan-400/15 px-3 py-2.5 text-xs font-semibold text-cyan-100 transition hover:bg-cyan-400/25"
            >
              Play mini game
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

async function fetchRecentlyClosedTrades(): Promise<TradeOrder[]> {
  const response = await authFetch(
    "/api/trades?limit=100&backtest=false&status=closed&sort=opened_at_desc",
  );
  if (!response.ok) {
    throw new Error(`Calm Reset trade monitor failed with ${response.status}`);
  }
  const payload: TradeHistoryResponse = await response.json();
  return payload.trades ?? [];
}

function isCompletedLiveTrade(trade: TradeOrder): boolean {
  return (
    trade.source === "live"
    && trade.status === "closed"
    && Boolean(trade.closed_at)
    && typeof trade.pnl_r === "number"
    && Number.isFinite(trade.pnl_r)
  );
}

function formatR(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}R`;
}
