import { ArrowDownRight, ArrowUpRight, Bot, Check, CheckCircle2, Copy, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { approveManualAiPlan, fetchManualAiWorkers, importManualAiPlans, type ManualAiPlan, type ManualAiWorker } from "../api/manualAi";
import { copyTextToClipboard } from "../lib/clipboard";
import { useChartStore } from "../store/chartStore";

type Props = { currentPrice: number | null; open: boolean; onChanged: () => void; onClose: () => void };
type Mode = "import" | "manual";

const XAUUSD_PIP_SIZE = 0.1;
const MANUAL_AI_MIN_RR = 1.5;
const MANUAL_AI_MAX_RR = 4;
const MANUAL_AI_MAX_EXPIRY_MINUTES = 2_880;
const QUICK_RR_OPTIONS = [1.5, 2, 2.5, 3, 3.5, 4] as const;
const QUICK_EXPIRY_OPTIONS = [
  { label: "1H", minutes: 60 },
  { label: "2H", minutes: 120 },
  { label: "3H", minutes: 180 },
  { label: "4H", minutes: 240 },
  { label: "5H", minutes: 300 },
  { label: "6H", minutes: 360 },
  { label: "8H", minutes: 480 },
  { label: "12H", minutes: 720 },
  { label: "18H", minutes: 1_080 },
  { label: "24H", minutes: 1_440 },
  { label: "48H", minutes: 2_880 },
] as const;
const PARTIAL_TRIGGER_OPTIONS = [0.75, 1, 1.25, 1.5] as const;
const PARTIAL_CLOSE_OPTIONS = [0.25, 0.33, 0.5] as const;

const inputClass = "h-10 rounded-lg border border-ink-600 bg-ink-950 px-3 text-sm text-slate-100 outline-none focus:border-cyan-400";

export function ManualAiModal({ currentPrice, open, onChanged, onClose }: Props) {
  const setSelectedPlaybooks = useChartStore((state) => state.setSelectedPlaybooks);
  const [readGuide, setReadGuide] = useState(false);
  const [mode, setMode] = useState<Mode>("import");
  const [json, setJson] = useState("");
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [entry, setEntry] = useState("");
  const [stop, setStop] = useState("");
  const [target, setTarget] = useState("");
  const [expiresInMinutes, setExpiresInMinutes] = useState("");
  const [reason, setReason] = useState("");
  const [partialEnabled, setPartialEnabled] = useState(true);
  const [partialTriggerR, setPartialTriggerR] = useState(1);
  const [partialCloseFraction, setPartialCloseFraction] = useState(0.5);
  const [partialMoveStopTo, setPartialMoveStopTo] = useState<"breakeven" | "unchanged">("breakeven");
  const [partialBreakevenBuffer, setPartialBreakevenBuffer] = useState("0");
  const [plans, setPlans] = useState<ManualAiPlan[]>([]);
  const [workers, setWorkers] = useState<ManualAiWorker[]>([]);
  const [selectedWorkerLabels, setSelectedWorkerLabels] = useState<string[]>([]);
  const [shortTrend, setShortTrend] = useState("neutral");
  const [mediumTrend, setMediumTrend] = useState("neutral");
  const [invalidationSource, setInvalidationSource] = useState("structure");
  const [limitReason, setLimitReason] = useState("pullback");
  const [emotionState, setEmotionState] = useState("calm");
  const [acceptRisk, setAcceptRisk] = useState(false);
  const [dynamicLot, setDynamicLot] = useState(false);
  const [competingExposure, setCompetingExposure] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [approved, setApproved] = useState<ManualAiPlan | null>(null);
  const [copiedCurrentPrice, setCopiedCurrentPrice] = useState(false);

  const primary = useMemo(() => plans.find((plan) => plan.execution_state === "primary") ?? null, [plans]);
  const stopMetrics = useMemo(() => {
    const entryPrice = Number(entry);
    const stopPrice = Number(stop);
    if (!Number.isFinite(entryPrice) || !Number.isFinite(stopPrice) || !entry.trim() || !stop.trim()) return null;
    const priceDistance = Math.abs(entryPrice - stopPrice);
    const validSide = side === "buy" ? stopPrice < entryPrice : stopPrice > entryPrice;
    return { pips: xauusdPipsForDistance(priceDistance), priceDistance, validSide };
  }, [entry, side, stop]);
  const limitPlacementValid = useMemo(() => {
    const entryPrice = Number(entry);
    if (typeof currentPrice !== "number" || !Number.isFinite(entryPrice) || !entry.trim()) return null;
    return side === "buy" ? entryPrice < currentPrice : entryPrice > currentPrice;
  }, [currentPrice, entry, side]);
  const riskReward = useMemo(() => {
    const entryPrice = Number(entry);
    const stopPrice = Number(stop);
    const targetPrice = Number(target);
    if (![entryPrice, stopPrice, targetPrice].every(Number.isFinite) || !entry.trim() || !stop.trim() || !target.trim()) return null;
    const risk = Math.abs(entryPrice - stopPrice);
    if (risk <= 0) return null;
    const validTarget = side === "buy" ? targetPrice > entryPrice : targetPrice < entryPrice;
    return { value: Math.abs(targetPrice - entryPrice) / risk, validTarget };
  }, [entry, side, stop, target]);
  const riskRewardValid = riskReward !== null
    && riskReward.validTarget
    && riskReward.value >= MANUAL_AI_MIN_RR
    && riskReward.value <= MANUAL_AI_MAX_RR;

  const applyQuickRiskReward = (rr: number) => {
    const entryPrice = Number(entry);
    const stopPrice = Number(stop);
    if (!Number.isFinite(entryPrice) || !Number.isFinite(stopPrice) || !stopMetrics?.validSide) return;
    setTarget(manualAiTargetForRiskReward(side, entryPrice, stopPrice, rr).toFixed(2));
  };

  const resetForm = () => {
    setReadGuide(false);
    setMode("import");
    setJson("");
    setSide("buy");
    setEntry("");
    setStop("");
    setTarget("");
    setExpiresInMinutes("");
    setReason("");
    setPartialEnabled(true);
    setPartialTriggerR(1);
    setPartialCloseFraction(0.5);
    setPartialMoveStopTo("breakeven");
    setPartialBreakevenBuffer("0");
    setPlans([]);
    setSelectedWorkerLabels(workers.map((worker) => worker.label));
    setShortTrend("neutral");
    setMediumTrend("neutral");
    setInvalidationSource("structure");
    setLimitReason("pullback");
    setEmotionState("calm");
    setAcceptRisk(false);
    setDynamicLot(false);
    setCompetingExposure(false);
    setBusy(false);
    setError("");
    setApproved(null);
    setCopiedCurrentPrice(false);
  };

  const closeModal = () => {
    resetForm();
    onClose();
  };
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      closeModal();
    };
    window.addEventListener("keydown", closeOnEscape, true);
    return () => window.removeEventListener("keydown", closeOnEscape, true);
  }, [open, workers]);
  useEffect(() => {
    if (!copiedCurrentPrice) return;
    const timer = window.setTimeout(() => setCopiedCurrentPrice(false), 1800);
    return () => window.clearTimeout(timer);
  }, [copiedCurrentPrice]);
  useEffect(() => {
    if (!open) return;
    let active = true;
    void fetchManualAiWorkers()
      .then((items) => {
        if (!active) return;
        setWorkers(items);
        setSelectedWorkerLabels(items.map((item) => item.label));
      })
      .catch((caught) => {
        if (active) setError(caught instanceof Error ? caught.message : "Không thể tải danh sách worker");
      });
    return () => { active = false; };
  }, [open]);
  if (!open) return null;

  const submitDraft = async () => {
    setBusy(true);
    setError("");
    try {
      let payload: unknown;
      if (mode === "import") {
        payload = JSON.parse(json);
      } else {
        const now = new Date().toISOString();
        payload = {
          schema_version: 1,
          as_of: now,
          symbol: "XAUUSD",
          playbook: "manual_ai_v1",
          analysis_timeframes: { context: "H1", structure: "M15", execution: "M5" },
          market_context: { source: "human_manual" },
          candidates: [{
            client_id: `manual-${Date.now()}`,
            priority: 1,
            execution_state: "primary",
            side,
            order_type: "limit",
            entry_price: Number(entry),
            stop_loss: Number(stop),
            take_profit: Number(target),
            risk_pct: 1,
            expires_in_minutes: Number(expiresInMinutes),
            partial_take_profit: {
              enabled: partialEnabled,
              trigger_r: partialTriggerR,
              close_fraction: partialCloseFraction,
              move_stop_to: partialMoveStopTo,
              breakeven_buffer: Number(partialBreakevenBuffer) || 0,
            },
            cancel_conditions: [],
            entry_reason: reason || "Human-confirmed pullback limit entry",
            stop_reason: "Structural invalidation selected by human",
            target_reason: "Short intraday movement with bounded reward",
            confidence: 0.5,
          }],
        };
      }
      const result = await importManualAiPlans(payload, mode);
      setPlans(result.plans);
      setSelectedPlaybooks(["manual_ai_v1"]);
      onChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Không thể tạo draft");
    } finally {
      setBusy(false);
    }
  };

  const approve = async () => {
    if (!primary) return;
    setBusy(true);
    setError("");
    try {
      const result = await approveManualAiPlan(primary.id, {
        account_labels: selectedWorkerLabels,
        questionnaire: {
          short_term_trend: shortTrend,
          medium_term_trend: mediumTrend,
          invalidation_source: invalidationSource,
          limit_reason: limitReason,
          emotion_state: emotionState,
          accepts_one_percent_risk: acceptRisk,
          confirms_lot_not_fixed: dynamicLot,
          competing_exposure: competingExposure,
          comment: "Approved from Manual AI wizard",
        },
      });
      setApproved(result.plans[0] ?? null);
      setSelectedPlaybooks(["manual_ai_v1"]);
      onChanged();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Không thể approve plan");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[100] grid place-items-center bg-black/75 p-3 backdrop-blur-sm">
      <div className="max-h-[94vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-cyan-400/25 bg-ink-900 shadow-2xl shadow-cyan-950/40">
        <header className="flex items-start gap-3 border-b border-ink-700 p-5">
          <span className="grid h-11 w-11 place-items-center rounded-xl border border-cyan-400/35 bg-cyan-400/10 text-cyan-200"><Bot size={22} /></span>
          <div className="min-w-0 flex-1"><h2 className="text-xl font-bold text-slate-100">Manual AI</h2><p className="mt-1 text-sm text-slate-400">Limit-only · structural SL · backend tính lot theo profile tài khoản.</p></div>
          <button aria-label="Close" className="text-slate-500 hover:text-slate-100" type="button" onClick={closeModal}><X /></button>
        </header>

        <div className="grid gap-5 p-5">
          <section className="rounded-xl border border-amber-400/25 bg-amber-400/5 p-4 text-sm leading-relaxed text-slate-300">
            <div className="font-semibold text-amber-200">Quy trình bắt buộc trước khi vào lệnh</div>
            <ol className="mt-2 list-decimal space-y-1 pl-5"><li>Entry phải là limit ở pullback/retest, không đuổi giá.</li><li>Đặt SL theo invalidation cấu trúc trước; tuyệt đối không cố định lot.</li><li>RR backend tính lại phải từ 1.5 đến 4.0.</li><li>Plan luôn là draft; chỉ worker được tính lot và gửi MT5 sau khi bạn approve.</li></ol>
            <label className="mt-3 flex items-center gap-2 font-medium text-slate-100"><input checked={readGuide} className="h-4 w-4 accent-cyan-400" type="checkbox" onChange={(event) => setReadGuide(event.target.checked)} />Tôi đã đọc và hiểu quy trình</label>
          </section>

          {!plans.length && !approved ? <>
            <div className="grid grid-cols-2 rounded-xl border border-ink-700 bg-ink-950 p-1"><button className={`h-10 rounded-lg text-sm font-semibold ${mode === "import" ? "bg-cyan-400/15 text-cyan-100" : "text-slate-400"}`} type="button" onClick={() => setMode("import")}>Import AI JSON</button><button className={`h-10 rounded-lg text-sm font-semibold ${mode === "manual" ? "bg-cyan-400/15 text-cyan-100" : "text-slate-400"}`} type="button" onClick={() => setMode("manual")}>Manual input</button></div>
            {mode === "import" ? (
              <textarea className="min-h-72 rounded-xl border border-ink-600 bg-ink-950 p-4 font-mono text-xs leading-relaxed text-slate-200 outline-none focus:border-cyan-400" placeholder="Paste JSON từ skill plan-xauusd-manual-ai" value={json} onChange={(event) => setJson(event.target.value)} />
            ) : (
              <div className="grid gap-4">
                <div className="grid gap-2">
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Chọn chiều lệnh</div>
                  <div className="grid grid-cols-2 gap-3">
                    <button
                      className={`flex min-h-16 items-center justify-center gap-3 rounded-xl border-2 text-left transition ${side === "buy" ? "border-emerald-300 bg-emerald-400/15 text-emerald-100 shadow-[0_0_22px_rgba(52,211,153,0.12)]" : "border-ink-700 bg-ink-950 text-slate-500 hover:border-emerald-500/50"}`}
                      type="button"
                      onClick={() => setSide("buy")}
                    >
                      <ArrowUpRight size={24} />
                      <span><span className="block text-base font-extrabold">BUY LIMIT</span><span className="block text-[11px] opacity-70">Mua ở giá thấp hơn</span></span>
                    </button>
                    <button
                      className={`flex min-h-16 items-center justify-center gap-3 rounded-xl border-2 text-left transition ${side === "sell" ? "border-rose-300 bg-rose-400/15 text-rose-100 shadow-[0_0_22px_rgba(251,113,133,0.12)]" : "border-ink-700 bg-ink-950 text-slate-500 hover:border-rose-500/50"}`}
                      type="button"
                      onClick={() => setSide("sell")}
                    >
                      <ArrowDownRight size={24} />
                      <span><span className="block text-base font-extrabold">SELL LIMIT</span><span className="block text-[11px] opacity-70">Bán ở giá cao hơn</span></span>
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3 rounded-xl border border-ink-700 bg-ink-950/70 p-3 sm:grid-cols-4">
                  <div>
                    <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">Current price</div>
                    <div className="mt-1 flex items-center gap-1.5">
                      <span className="text-sm font-bold tabular-nums text-slate-100">{typeof currentPrice === "number" ? currentPrice.toFixed(2) : "--"}</span>
                      <button
                        aria-label="Copy current price"
                        className="grid h-6 w-6 place-items-center rounded-md text-slate-500 hover:bg-cyan-400/10 hover:text-cyan-200 disabled:opacity-30"
                        disabled={typeof currentPrice !== "number"}
                        title="Copy current price"
                        type="button"
                        onClick={() => {
                          if (typeof currentPrice !== "number") return;
                          void copyTextToClipboard(currentPrice.toFixed(2))
                            .then(() => setCopiedCurrentPrice(true))
                            .catch(() => setError("Browser không cho phép copy current price."));
                        }}
                      >
                        {copiedCurrentPrice ? <Check size={13} /> : <Copy size={13} />}
                      </button>
                    </div>
                  </div>
                  <Metric label="SL distance" value={stopMetrics ? `${stopMetrics.priceDistance.toFixed(2)} giá` : "--"} />
                  <Metric
                    label="SL pips"
                    tone={stopMetrics ? (stopMetrics.validSide ? "good" : "bad") : "neutral"}
                    value={stopMetrics ? `${Math.round(stopMetrics.pips).toLocaleString()} pips` : "--"}
                  />
                  <Metric
                    label="Risk : Reward"
                    tone={riskReward ? (riskRewardValid ? "good" : "bad") : "neutral"}
                    value={riskReward ? `1 : ${riskReward.value.toFixed(2)}` : "--"}
                  />
                </div>
                {limitPlacementValid === false ? <div className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-200">{side === "buy" ? "BUY LIMIT cần Entry thấp hơn current price." : "SELL LIMIT cần Entry cao hơn current price."}</div> : null}
                {stopMetrics && !stopMetrics.validSide ? <div className="rounded-lg border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-xs text-rose-200">SL sai phía: BUY cần SL dưới Entry, SELL cần SL trên Entry.</div> : null}
                {riskReward && !riskReward.validTarget ? <div className="rounded-lg border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-xs text-rose-200">TP sai phía: BUY cần TP trên Entry, SELL cần TP dưới Entry.</div> : null}
                {riskReward && riskReward.validTarget && !riskRewardValid ? <div className="rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-200">Manual AI yêu cầu R:R từ 1.5 đến 4.0.</div> : null}

                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="grid gap-1 text-xs text-slate-400">Entry<input className={inputClass} inputMode="decimal" value={entry} onChange={(event) => setEntry(event.target.value)} /></label>
                  <label className="grid gap-1 text-xs text-slate-400">Structural SL<input className={inputClass} inputMode="decimal" value={stop} onChange={(event) => setStop(event.target.value)} /></label>
                  <label className="grid gap-1 text-xs text-slate-400">
                    <span>Take profit · chọn nhanh R:R</span>
                    <span className="flex flex-wrap gap-1">{QUICK_RR_OPTIONS.map((rr) => <button key={rr} className="rounded border border-ink-600 bg-ink-800 px-2 py-1 text-[10px] font-semibold text-cyan-200 hover:border-cyan-400/60 disabled:cursor-not-allowed disabled:opacity-35" disabled={!stopMetrics?.validSide} type="button" onClick={() => applyQuickRiskReward(rr)}>{rr.toFixed(1)}R</button>)}</span>
                    <input className={inputClass} inputMode="decimal" value={target} onChange={(event) => setTarget(event.target.value)} />
                  </label>
                  <label className="grid gap-1 text-xs text-slate-400">
                    <span>Expire sau · nhập phút hoặc chọn nhanh</span>
                    <span className="flex flex-wrap gap-1">{QUICK_EXPIRY_OPTIONS.map((option) => <button key={option.minutes} className={`rounded border px-2 py-1 text-[10px] font-semibold transition ${Number(expiresInMinutes) === option.minutes ? "border-amber-300 bg-amber-400/15 text-amber-100" : "border-ink-600 bg-ink-800 text-slate-300 hover:border-amber-400/60"}`} type="button" onClick={() => setExpiresInMinutes(String(option.minutes))}>{option.label}</button>)}</span>
                    <input className={inputClass} min={5} max={MANUAL_AI_MAX_EXPIRY_MINUTES} placeholder="Nhập số phút" step={5} type="number" value={expiresInMinutes} onChange={(event) => setExpiresInMinutes(event.target.value)} />
                  </label>
                  <section className="grid gap-3 rounded-xl border border-violet-400/25 bg-violet-400/5 p-3 sm:col-span-2">
                    <label className="flex items-center justify-between gap-3 text-sm font-semibold text-violet-100">
                      <span><span className="block">Partial TP</span><span className="mt-0.5 block text-[11px] font-normal text-slate-400">Chốt một phần vị thế khi đạt mức R đã chọn.</span></span>
                      <input checked={partialEnabled} className="h-4 w-4 accent-violet-400" type="checkbox" onChange={(event) => setPartialEnabled(event.target.checked)} />
                    </label>
                    <div className={`grid gap-3 sm:grid-cols-3 ${partialEnabled ? "" : "pointer-events-none opacity-40"}`}>
                      <QuickOptionGroup label="Kích hoạt tại" options={PARTIAL_TRIGGER_OPTIONS.map((value) => ({ label: `${value.toFixed(2)}R`, value }))} selected={partialTriggerR} onSelect={setPartialTriggerR} />
                      <QuickOptionGroup label="Khối lượng chốt" options={PARTIAL_CLOSE_OPTIONS.map((value) => ({ label: `${Math.round(value * 100)}%`, value }))} selected={partialCloseFraction} onSelect={setPartialCloseFraction} />
                      <div className="grid content-start gap-1.5">
                        <span className="text-[11px] text-slate-400">SL sau partial</span>
                        <div className="flex flex-wrap gap-1">
                          <ChoiceButton active={partialMoveStopTo === "breakeven"} label="Dời về BE" onClick={() => setPartialMoveStopTo("breakeven")} />
                          <ChoiceButton active={partialMoveStopTo === "unchanged"} label="Giữ nguyên" onClick={() => setPartialMoveStopTo("unchanged")} />
                        </div>
                      </div>
                    </div>
                    {partialEnabled && partialMoveStopTo === "breakeven" ? <label className="grid gap-1 text-xs text-slate-400 sm:max-w-52">BE buffer (giá)<input className={inputClass} min={0} max={10} step={0.1} type="number" value={partialBreakevenBuffer} onChange={(event) => setPartialBreakevenBuffer(event.target.value)} /></label> : null}
                  </section>
                  <label className="grid gap-1 text-xs text-slate-400 sm:col-span-2">Entry reason<input className={inputClass} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
                </div>
              </div>
            )}
            <button className="h-11 rounded-xl bg-cyan-400 font-bold text-ink-950 disabled:opacity-40" disabled={!readGuide || busy || (mode === "import" ? !json.trim() : !entry || !stop || !target || stopMetrics?.validSide === false || limitPlacementValid === false || !riskRewardValid || Number(expiresInMinutes) < 5 || Number(expiresInMinutes) > MANUAL_AI_MAX_EXPIRY_MINUTES)} type="button" onClick={submitDraft}>{busy ? "Validating…" : "Validate & create draft"}</button>
          </> : null}

          {primary && !approved ? <section className="grid gap-4 rounded-xl border border-cyan-400/25 bg-cyan-400/5 p-4"><div><div className="font-semibold text-cyan-100">Draft đã validate</div><div className="mt-2 grid gap-2">{plans.map((plan) => <div key={plan.id} className="rounded-lg border border-ink-700 bg-ink-950/60 p-2 text-sm tabular-nums text-slate-300"><span className={`mr-2 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${plan.execution_state === "primary" ? "bg-cyan-400/15 text-cyan-200" : "bg-slate-700 text-slate-400"}`}>{plan.execution_state}</span>{plan.side.toUpperCase()} limit {plan.entry_price} · SL {plan.stop_loss} · TP {plan.take_profit} · {plan.risk_reward.toFixed(2)}R · {plan.expires_in_minutes} phút</div>)}</div></div><div className="grid gap-2"><div><div className="text-xs font-medium text-slate-300">Worker nhận lệnh</div><div className="mt-0.5 text-[11px] text-slate-500">Mỗi worker tính lot theo profile: tài khoản quỹ 0.75%, tài khoản thường 1.5%.</div></div>{workers.length ? <div className="grid gap-2 rounded-lg border border-ink-700 bg-ink-950/50 p-3">{workers.map((worker) => <label key={worker.label} className="flex items-center justify-between gap-3 text-sm text-slate-200"><span className="flex items-center gap-2"><input checked={selectedWorkerLabels.includes(worker.label)} className="accent-cyan-400" type="checkbox" onChange={(event) => setSelectedWorkerLabels((current) => event.target.checked ? [...current, worker.label] : current.filter((label) => label !== worker.label))} />{worker.label}</span><span className={worker.execution.worker_status === "online" ? "text-xs text-emerald-300" : "text-xs text-amber-300"}>{worker.execution.worker_status}</span></label>)}</div> : <div className="rounded-lg border border-amber-400/25 bg-amber-400/5 p-3 text-xs text-amber-200">Chưa tìm thấy worker nào. Hãy kiểm tra worker heartbeat trên Account Dashboard.</div>}</div><div className="grid gap-3 sm:grid-cols-2"><QuestionSelect label="Short-term trend" value={shortTrend} onChange={setShortTrend} options={["bullish", "bearish", "neutral"]} /><QuestionSelect label="Medium-term trend" value={mediumTrend} onChange={setMediumTrend} options={["bullish", "bearish", "neutral"]} /><QuestionSelect label="Nguồn invalidation" value={invalidationSource} onChange={setInvalidationSource} options={["structure", "liquidity_extreme", "volatility_buffer"]} /><QuestionSelect label="Lý do dùng limit" value={limitReason} onChange={setLimitReason} options={["pullback", "retest", "discount_premium", "liquidity_reaction"]} /><QuestionSelect label="Trạng thái cảm xúc" value={emotionState} onChange={setEmotionState} options={["calm", "uncertain", "fomo", "revenge"]} /></div><div className="grid gap-2 text-sm text-slate-200"><label className="flex gap-2"><input checked={acceptRisk} className="accent-cyan-400" type="checkbox" onChange={(event) => setAcceptRisk(event.target.checked)} />Tôi chấp nhận risk theo profile từng worker (quỹ 0.75% · thường 1.5%).</label><label className="flex gap-2"><input checked={dynamicLot} className="accent-cyan-400" type="checkbox" onChange={(event) => setDynamicLot(event.target.checked)} />Tôi không cố định lot; từng worker tính lot từ SL.</label><label className="flex gap-2"><input checked={competingExposure} className="accent-rose-400" type="checkbox" onChange={(event) => setCompetingExposure(event.target.checked)} />Có worker đang có exposure XAUUSD cạnh tranh.</label></div>{emotionState !== "calm" ? <p className="text-xs text-amber-200">Chỉ trạng thái calm mới được approve; hãy tạm dừng nếu đang FOMO, revenge hoặc chưa chắc chắn.</p> : null}<button className="h-11 rounded-xl bg-emerald-400 font-bold text-ink-950 disabled:opacity-40" disabled={busy || emotionState !== "calm" || !acceptRisk || !dynamicLot || competingExposure || selectedWorkerLabels.length === 0} type="button" onClick={approve}>{busy ? "Approving…" : `Approve & arm ${selectedWorkerLabels.length} worker`}</button></section> : null}
          {approved ? <div className="grid gap-4 rounded-xl border border-emerald-400/30 bg-emerald-400/10 p-4 text-emerald-100"><div className="flex items-center gap-3"><CheckCircle2 /><div><div className="font-bold">Plan đã approved</div><div className="text-sm opacity-80">Worker sẽ kiểm tra live risk rồi mới tính lot và đặt limit order.</div></div></div><div className="grid grid-cols-2 gap-2"><button className="h-10 rounded-lg border border-emerald-300/30 bg-ink-950/40 text-sm font-semibold text-emerald-100 hover:bg-ink-950/70" type="button" onClick={closeModal}>Đóng</button><button className="h-10 rounded-lg bg-emerald-300 text-sm font-bold text-emerald-950" type="button" onClick={resetForm}>Thêm lệnh mới</button></div></div> : null}
          {error ? <div className="rounded-xl border border-rose-400/40 bg-rose-400/10 p-3 text-sm text-rose-200">{error}</div> : null}
        </div>
      </div>
    </div>
  );
}

function QuestionSelect({ label, onChange, options, value }: { label: string; onChange: (value: string) => void; options: string[]; value: string }) {
  return <label className="grid gap-1 text-xs text-slate-400">{label}<select className={inputClass} value={value} onChange={(event) => onChange(event.target.value)}>{options.map((option) => <option key={option} value={option}>{option}</option>)}</select></label>;
}

function Metric({ className = "", label, tone = "neutral", value }: { className?: string; label: string; tone?: "neutral" | "good" | "bad"; value: string }) {
  const valueClass = tone === "good" ? "text-emerald-200" : tone === "bad" ? "text-rose-200" : "text-slate-100";
  return <div className={className}><div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</div><div className={`mt-1 text-sm font-bold tabular-nums ${valueClass}`}>{value}</div></div>;
}

function QuickOptionGroup({ label, onSelect, options, selected }: { label: string; onSelect: (value: number) => void; options: Array<{ label: string; value: number }>; selected: number }) {
  return <div className="grid content-start gap-1.5"><span className="text-[11px] text-slate-400">{label}</span><div className="flex flex-wrap gap-1">{options.map((option) => <ChoiceButton key={option.value} active={selected === option.value} label={option.label} onClick={() => onSelect(option.value)} />)}</div></div>;
}

function ChoiceButton({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return <button className={`rounded border px-2 py-1 text-[10px] font-semibold transition ${active ? "border-violet-300 bg-violet-400/20 text-violet-100" : "border-ink-600 bg-ink-900 text-slate-400 hover:border-violet-400/60"}`} type="button" onClick={onClick}>{label}</button>;
}

export function xauusdPipsForDistance(priceDistance: number): number {
  return Math.abs(priceDistance) / XAUUSD_PIP_SIZE;
}

export function manualAiTargetForRiskReward(side: "buy" | "sell", entry: number, stop: number, riskReward: number): number {
  const reward = Math.abs(entry - stop) * riskReward;
  return side === "buy" ? entry + reward : entry - reward;
}
