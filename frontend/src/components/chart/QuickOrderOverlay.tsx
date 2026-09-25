import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { ArrowDown, ArrowUp, Check, LoaderCircle, X } from "lucide-react";
import { fetchAccountLabels } from "../../api/accounts";
import { createQuickOrder, previewQuickOrder, type QuickOrderPreview, type QuickOrderSide, type QuickOrderType } from "../../api/quickOrder";
import { useQuickOrderStore } from "../../store/quickOrderStore";

type Level = "entry" | "stop" | "target";

type Props = {
  symbol: string;
  chartPrice: number;
  plotWidth: number;
  priceToY: (price: number) => number | null;
  clientYToPrice: (clientY: number) => number | null;
};

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);
const round = (value: number) => Math.round(value * 100) / 100;
const RR_OPTIONS = Array.from({ length: 13 }, (_, index) => 1 + index * 0.25);
const EXPIRY_OPTIONS = [
  { value: 15, label: "15 phút" },
  { value: 30, label: "30 phút" },
  { value: 60, label: "1 giờ" },
  { value: 120, label: "2 giờ" },
  { value: 240, label: "4 giờ" },
  { value: 480, label: "8 giờ" },
  { value: 720, label: "12 giờ" },
  { value: 1_440, label: "24 giờ" },
  { value: 2_880, label: "48 giờ" },
];

export function QuickOrderOverlay({ symbol, chartPrice, plotWidth, priceToY, clientYToPrice }: Props) {
  const open = useQuickOrderStore((state) => state.open);
  const setOpen = useQuickOrderStore((state) => state.setOpen);
  const [accounts, setAccounts] = useState<string[]>([]);
  const [selectedAccounts, setSelectedAccounts] = useState<string[]>([]);
  const [side, setSide] = useState<QuickOrderSide>("buy");
  const [orderType, setOrderType] = useState<QuickOrderType>("market");
  const [entry, setEntry] = useState(chartPrice);
  const [stop, setStop] = useState(chartPrice - 10);
  const [rr, setRr] = useState(1.5);
  const [expiryMinutes, setExpiryMinutes] = useState(60);
  const [atr, setAtr] = useState<number | null>(null);
  const [preview, setPreview] = useState<QuickOrderPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [placed, setPlaced] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dragging = useRef<Level | null>(null);

  const geometry = useMemo(() => {
    const minimum = atr ?? 0;
    const effectiveStop = side === "buy" ? Math.min(stop, entry - minimum) : Math.max(stop, entry + minimum);
    const distance = Math.abs(entry - effectiveStop);
    const target = side === "buy" ? entry + distance * rr : entry - distance * rr;
    return { stop: round(effectiveStop), target: round(target), distance };
  }, [atr, entry, rr, side, stop]);

  const loadPreview = async (nextAccounts = selectedAccounts) => {
    if (nextAccounts.length === 0) return null;
    setLoading(true);
    setError(null);
    try {
      const result = await previewQuickOrder({
        symbol, account_labels: nextAccounts, side, order_type: orderType,
        entry_price: orderType === "limit" ? entry : null, stop_loss: atr === null ? null : stop, risk_reward: rr,
      });
      const first = result.accounts[0];
      setAtr(result.atr_h1);
      setEntry(first.entry);
      setStop(first.stop_loss);
      setPreview(result);
      return result;
    } catch (reason) {
      setPreview(null);
      setError(reason instanceof Error ? reason.message : "Không thể preview Quick Order.");
      return null;
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    setPlaced(false);
    setPreview(null);
    setError(null);
    void fetchAccountLabels().then((labels) => {
      setAccounts(labels);
      setSelectedAccounts(labels);
      if (labels.length > 0) void loadPreview(labels);
    }).catch((reason) => setError(reason instanceof Error ? reason.message : "Không thể tải account."));
    // Initial quote/ATR load only; later changes require an explicit Review.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const quoteEntry = (nextSide: QuickOrderSide) => {
    const first = preview?.accounts[0];
    if (!first) return entry;
    return nextSide === "buy" ? first.quote.ask : first.quote.bid;
  };

  const changeSide = (nextSide: QuickOrderSide) => {
    if (nextSide === side) return;
    const nextEntry = orderType === "market" ? quoteEntry(nextSide) : entry;
    setSide(nextSide);
    setEntry(round(nextEntry));
    if (atr !== null) setStop(round(nextSide === "buy" ? nextEntry - atr : nextEntry + atr));
    setPreview(null);
  };

  const changeOrderType = (nextType: QuickOrderType) => {
    if (nextType === orderType) return;
    const marketEntry = quoteEntry(side);
    const nextEntry = nextType === "market"
      ? marketEntry
      : side === "buy" ? marketEntry - (atr ?? 0) * 0.25 : marketEntry + (atr ?? 0) * 0.25;
    setOrderType(nextType);
    setEntry(round(nextEntry));
    if (atr !== null) setStop(round(side === "buy" ? nextEntry - atr : nextEntry + atr));
    setPreview(null);
  };

  useEffect(() => {
    const move = (event: PointerEvent) => {
      const level = dragging.current;
      if (!level) return;
      const price = clientYToPrice(event.clientY);
      if (price === null || atr === null) return;
      event.preventDefault();
      setPreview(null);
      if (level === "entry") {
        const next = round(price);
        if (orderType === "market") setOrderType("limit");
        setEntry(next);
        setStop((current) => round(side === "buy" ? Math.min(current, next - atr) : Math.max(current, next + atr)));
      } else if (level === "stop") {
        setStop(round(side === "buy" ? Math.min(price, entry - atr) : Math.max(price, entry + atr)));
      } else if (level === "target" && geometry.distance > 0) {
        const nextRr = side === "buy" ? (price - entry) / geometry.distance : (entry - price) / geometry.distance;
        setRr(Math.round(clamp(nextRr, 1, 4) * 100) / 100);
      }
    };
    const end = () => { dragging.current = null; };
    window.addEventListener("pointermove", move, { passive: false });
    window.addEventListener("pointerup", end);
    window.addEventListener("blur", end);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("blur", end);
    };
  }, [atr, clientYToPrice, entry, geometry.distance, orderType, side]);

  if (!open) return null;
  const beginDrag = (level: Level) => (event: ReactPointerEvent) => {
    event.preventDefault();
    event.stopPropagation();
    dragging.current = level;
  };
  const levels = [
    { level: "entry" as const, value: entry, label: orderType === "market" ? "MARKET" : "ENTRY", line: "border-cyan-300/55", badge: "border-cyan-300/45 text-cyan-100 bg-cyan-950/70" },
    { level: "stop" as const, value: geometry.stop, label: "SL · 1R", line: "border-rose-300/55", badge: "border-rose-300/45 text-rose-100 bg-rose-950/70" },
    { level: "target" as const, value: geometry.target, label: `TP · ${rr.toFixed(1)}R`, line: "border-emerald-300/55", badge: "border-emerald-300/45 text-emerald-100 bg-emerald-950/70" },
  ];

  const place = async () => {
    if (!preview) {
      await loadPreview();
      return;
    }
    const checked = preview;
    if (loading) return;
    if (checked.accounts.some((account) => !account.execution_ready)) {
      setError("Có account chưa online hoặc execution đang tắt.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await createQuickOrder({
        client_request_id: crypto.randomUUID(), expires_in_minutes: expiryMinutes,
        symbol, account_labels: selectedAccounts, side, order_type: orderType,
        entry_price: orderType === "limit" ? entry : null, stop_loss: stop, risk_reward: rr,
      });
      setPlaced(true);
      setPreview(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không thể gửi Quick Order.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="pointer-events-none absolute inset-0 z-[72]">
      {levels.map(({ level, value, label, line, badge }) => {
        const y = priceToY(value);
        return y === null ? null : (
          <div key={level} className="pointer-events-auto absolute left-0 h-7 -translate-y-1/2 cursor-ns-resize touch-none"
            style={{ top: y, width: Math.max(plotWidth, 160) }} title={`Kéo để chỉnh ${label}`} onPointerDown={beginDrag(level)}>
            <span className={`pointer-events-none absolute left-0 top-1/2 w-full border-t ${line}`} />
            <span className={`pointer-events-none absolute right-0 top-1/2 -translate-y-1/2 rounded border px-2 py-1 text-[10px] font-black shadow ${badge}`}>{label} {value.toFixed(2)}</span>
          </div>
        );
      })}
      <aside className="pointer-events-auto absolute right-3 top-3 w-[min(28rem,calc(100%-1.5rem))] rounded-xl border border-cyan-400/35 bg-ink-950/95 p-3 shadow-2xl backdrop-blur">
        <div className="flex items-center justify-between">
          <div><div className="font-bold text-cyan-100">Quick Order</div><div className="text-[10px] text-slate-400">Min SL 1 ATR H1 · risk do worker tính</div></div>
          <button className="rounded p-1 text-slate-400 hover:bg-ink-800 hover:text-white" type="button" onClick={() => setOpen(false)}><X size={17} /></button>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <div className="grid grid-cols-2 rounded-lg border border-ink-700 bg-ink-900 p-1">
            {(["buy", "sell"] as const).map((value) => <button key={value} type="button" onClick={() => changeSide(value)} className={`flex items-center justify-center gap-1.5 rounded py-1.5 text-xs font-black ${side === value ? value === "buy" ? "bg-emerald-500/25 text-emerald-200" : "bg-rose-500/25 text-rose-200" : "text-slate-500"}`}>{value === "buy" ? <ArrowUp size={14} strokeWidth={2.8} /> : <ArrowDown size={14} strokeWidth={2.8} />}{value.toUpperCase()}</button>)}
          </div>
          <div className="grid grid-cols-2 rounded-lg border border-ink-700 bg-ink-900 p-1">
            {(["market", "limit"] as const).map((value) => <button key={value} type="button" onClick={() => changeOrderType(value)} className={`rounded py-1.5 text-xs font-bold ${orderType === value ? "bg-cyan-400/20 text-cyan-100" : "text-slate-500"}`}>{value.toUpperCase()}</button>)}
          </div>
        </div>
        <div className={`mt-3 grid gap-2 text-[10px] ${orderType === "limit" ? "grid-cols-[1.35fr_1.35fr_0.9fr_0.9fr]" : "grid-cols-[1.35fr_1.35fr_0.9fr]"}`}>
          <label className="text-slate-400">Entry<input disabled={orderType === "market"} value={entry} onChange={(e) => { setEntry(Number(e.target.value)); setPreview(null); }} type="number" step="0.1" className="mt-1 w-full rounded border border-ink-700 bg-ink-900 px-2 py-1.5 text-xs text-slate-100 disabled:text-slate-500" /></label>
          <label className="text-slate-400">Stop<input value={stop} onChange={(e) => { setStop(Number(e.target.value)); setPreview(null); }} type="number" step="0.1" className="mt-1 w-full rounded border border-ink-700 bg-ink-900 px-2 py-1.5 text-xs text-slate-100" /></label>
          <label className="text-slate-400">R:R<select value={rr} onChange={(e) => { setRr(Number(e.target.value)); setPreview(null); }} className="mt-1 w-full rounded border border-ink-700 bg-ink-900 px-2 py-1.5 text-xs text-slate-100">{!RR_OPTIONS.some((value) => Math.abs(value - rr) < 0.001) ? <option value={rr}>{rr.toFixed(2)}R</option> : null}{RR_OPTIONS.map((value) => <option key={value} value={value}>{value.toFixed(2)}R</option>)}</select></label>
          {orderType === "limit" ? <label className="text-slate-400">Expiry<select value={expiryMinutes} onChange={(e) => setExpiryMinutes(Number(e.target.value))} className="mt-1 w-full rounded border border-ink-700 bg-ink-900 px-2 py-1.5 text-xs text-slate-100">{EXPIRY_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label> : null}
        </div>
        <div className="mt-3 max-h-24 space-y-1 overflow-auto rounded-lg border border-ink-800 bg-ink-900/60 p-2">
          {accounts.map((account) => {
            const accountPreview = preview?.accounts.find((item) => item.account_label === account);
            return <label key={account} className="flex items-center gap-2 text-xs text-slate-300"><input type="checkbox" checked={selectedAccounts.includes(account)} onChange={() => { setSelectedAccounts((current) => current.includes(account) ? current.filter((item) => item !== account) : [...current, account]); setPreview(null); }} /><span className="min-w-0 flex-1 truncate">{account}</span>{accountPreview ? <span className={accountPreview.execution_ready ? "text-emerald-300" : "text-rose-300"}>{accountPreview.execution_ready ? "READY" : accountPreview.worker_status.toUpperCase()}</span> : null}</label>;
          })}
          {accounts.length === 0 ? <span className="text-xs text-slate-500">Chưa có worker account.</span> : null}
        </div>
        {atr !== null ? <div className="mt-2 text-[10px] text-slate-400">ATR H1 {atr.toFixed(2)} · SL hiệu lực {geometry.stop.toFixed(2)} · TP {geometry.target.toFixed(2)}</div> : null}
        {preview ? <div className="mt-2 rounded border border-emerald-400/25 bg-emerald-500/10 px-2 py-1.5 text-[10px] text-emerald-100"><Check className="mr-1 inline" size={12} />Server validated {preview.accounts.length} account · quote/ATR mới nhất</div> : null}
        {placed ? <div className="mt-2 rounded border border-cyan-400/30 bg-cyan-400/10 px-2 py-2 text-xs text-cyan-100">Đã xếp lệnh vào worker. Có thể đóng bảng này.</div> : null}
        {error ? <div className="mt-2 rounded border border-rose-400/30 bg-rose-500/10 px-2 py-2 text-xs text-rose-200">{error}</div> : null}
        <button disabled={loading || selectedAccounts.length === 0 || placed} className="mt-3 flex w-full items-center justify-center rounded-lg border border-cyan-300/50 bg-cyan-400/20 py-2.5 text-xs font-black text-cyan-100 disabled:opacity-40" type="button" onClick={() => void place()}>{loading ? <LoaderCircle className="animate-spin" size={15} /> : placed ? "SENT" : preview ? "PLACE ORDER" : "REVIEW ORDER"}</button>
      </aside>
    </div>
  );
}
