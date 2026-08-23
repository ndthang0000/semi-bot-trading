import { AlertTriangle, Loader2, Send, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { approveManualAiPlan, fetchManualAiWorkers, importManualAiPlans, type ManualAiWorker } from "../../api/manualAi";
import type { SetupCandidate } from "../../types";

type Props = {
  candidate: SetupCandidate;
  onClose: () => void;
  onSubmitted: (planId: string) => void;
};

export function H1ImpulseExecuteModal({ candidate, onClose, onSubmitted }: Props) {
  const [workers, setWorkers] = useState<ManualAiWorker[]>([]);
  const [selectedWorkers, setSelectedWorkers] = useState<string[]>([]);
  const [calm, setCalm] = useState(false);
  const [acceptRisk, setAcceptRisk] = useState(false);
  const [dynamicLot, setDynamicLot] = useState(false);
  const [competingExposure, setCompetingExposure] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [draftPlanId, setDraftPlanId] = useState<string | null>(null);
  const expiryHours = Number(candidate.metadata.expiry_hours ?? 6);
  const signalClose = String(candidate.metadata.created_at ?? new Date().toISOString());
  const entrySource = String(candidate.metadata.entry_source ?? "strategy_calculated");
  const expired = useMemo(() => {
    const value = candidate.metadata.limit_expires_at;
    return typeof value === "string" && Date.parse(value) <= Date.now();
  }, [candidate.metadata.limit_expires_at]);

  useEffect(() => {
    let active = true;
    void fetchManualAiWorkers()
      .then((items) => {
        if (!active) return;
        setWorkers(items);
        setSelectedWorkers(items.map((item) => item.label));
      })
      .catch((caught) => {
        if (active) setError(caught instanceof Error ? caught.message : "Không thể tải worker.");
      });
    return () => { active = false; };
  }, []);

  const submit = async () => {
    if (candidate.entry === null || candidate.stop_loss === null || typeof candidate.take_profit[0] !== "number") return;
    setBusy(true);
    setError("");
    try {
      let planId = draftPlanId;
      if (!planId) {
        const result = await importManualAiPlans({
          schema_version: 1,
          as_of: signalClose,
          symbol: candidate.symbol,
          playbook: "h1_impulse_retest_v1",
          analysis_timeframes: { context: "H1", structure: "M15", execution: "M5" },
          market_context: {
            source: "h1_impulse_preview",
            signal_candle_time: candidate.metadata.signal_candle_time,
            atr: candidate.metadata.atr,
            entry_options: candidate.metadata.entry_options,
          },
          candidates: [{
            client_id: `h1-impulse-${Date.now()}`,
            priority: 1,
            execution_state: "primary",
            side: candidate.direction === "long" ? "buy" : "sell",
            order_type: "limit",
            entry_price: candidate.entry,
            stop_loss: candidate.stop_loss,
            take_profit: candidate.take_profit[0],
            risk_pct: 1,
            expires_in_minutes: expiryHours * 60,
            partial_take_profit: { enabled: true, trigger_r: 1.25, close_fraction: 0.5, move_stop_to: "breakeven", breakeven_buffer: 0 },
            cancel_conditions: [
              { type: candidate.direction === "long" ? "m5_close_below" : "m5_close_above", price: candidate.stop_loss },
              { type: "price_reached_target_without_fill" },
              { type: "news_blackout_started" },
            ],
            entry_source: entrySource,
            entry_options: candidate.metadata.entry_options,
            entry_reason: `H1 impulse entry from ${entrySource}`,
            stop_reason: "H1 wick invalidation plus ATR buffer; human-confirmed levels",
            target_reason: `${candidate.risk_reward?.toFixed(2) ?? "--"}R target selected by trader`,
            confidence: candidate.status === "eligible" ? 0.8 : 0.4,
          }],
        }, "manual");
        planId = result.plans[0]?.id ?? null;
        if (!planId) throw new Error("Backend không trả về H1 draft plan.");
        setDraftPlanId(planId);
      }
      const approved = await approveManualAiPlan(planId, {
        account_labels: selectedWorkers,
        questionnaire: {
          short_term_trend: candidate.direction === "long" ? "bullish" : "bearish",
          medium_term_trend: "neutral",
          invalidation_source: "volatility_buffer",
          limit_reason: "pullback",
          emotion_state: calm ? "calm" : "uncertain",
          accepts_one_percent_risk: acceptRisk,
          confirms_lot_not_fixed: dynamicLot,
          competing_exposure: competingExposure,
          comment: `Approved H1 Impulse Retest; entry source=${entrySource}`,
        },
      });
      onSubmitted(approved.plans[0]?.id ?? planId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Không thể gửi H1 limit plan.");
    } finally {
      setBusy(false);
    }
  };

  const ready = !expired && calm && acceptRisk && dynamicLot && !competingExposure && selectedWorkers.length > 0;
  return (
    <div className="fixed inset-0 z-[110] grid place-items-center bg-black/75 p-3 backdrop-blur-sm" onPointerDown={(event) => event.stopPropagation()}>
      <section className="max-h-[94vh] w-full max-w-xl overflow-y-auto rounded-2xl border border-cyan-400/30 bg-ink-950 p-5 shadow-2xl">
        <header className="flex items-start gap-3">
          <Send className="mt-1 text-cyan-300" size={20} />
          <div className="min-w-0 flex-1"><h2 className="text-lg font-bold text-slate-100">Send H1 Impulse limit to MT5</h2><p className="mt-1 text-xs text-slate-400">Tạo approved plan; worker vẫn kiểm tra spread, news, position limit và tự tính lot.</p></div>
          <button className="text-slate-500 hover:text-white" type="button" onClick={onClose}><X size={19} /></button>
        </header>
        <div className="mt-4 grid grid-cols-4 gap-2 text-center font-mono text-xs">
          <Level label="ENTRY" value={candidate.entry} /><Level label="SL" value={candidate.stop_loss} /><Level label="TP" value={candidate.take_profit[0]} /><Level label="EXPIRY" value={`${expiryHours}h`} />
        </div>
        <div className="mt-3 rounded-lg border border-cyan-400/20 bg-cyan-400/[0.06] px-3 py-2 text-xs text-cyan-100">Entry source: <strong>{entrySource.replace(/_/g, " ")}</strong></div>
        {expired ? <div className="mt-3 rounded-lg border border-rose-400/35 bg-rose-400/10 p-3 text-xs text-rose-200"><AlertTriangle className="mr-2 inline" size={14} />Signal đã hết expiry; không thể gửi MT5.</div> : null}
        <div className="mt-4 grid gap-2 rounded-lg border border-ink-700 p-3">
          <div className="text-xs font-bold uppercase tracking-wide text-slate-400">Worker accounts</div>
          {workers.map((worker) => <label key={worker.label} className="flex items-center justify-between text-sm text-slate-200"><span className="flex items-center gap-2"><input checked={selectedWorkers.includes(worker.label)} className="accent-cyan-400" type="checkbox" onChange={(event) => setSelectedWorkers((current) => event.target.checked ? [...current, worker.label] : current.filter((item) => item !== worker.label))} />{worker.label}</span><span className="text-xs text-slate-500">{worker.execution.worker_status}</span></label>)}
        </div>
        <div className="mt-4 grid gap-2 text-sm text-slate-200">
          <Check checked={calm} label="Tôi đang bình tĩnh và quyết định cuối cùng là gửi signal này." onChange={setCalm} />
          <Check checked={acceptRisk} label="Tôi chấp nhận risk theo account profile (quỹ 0.75%, thường 1.5%)." onChange={setAcceptRisk} />
          <Check checked={dynamicLot} label="Tôi không cố định lot; worker tính lot theo SL hiện tại." onChange={setDynamicLot} />
          <Check checked={competingExposure} label="Đang có exposure XAUUSD cạnh tranh (phải bỏ chọn để gửi)." onChange={setCompetingExposure} danger />
        </div>
        {error ? <div className="mt-3 rounded-lg border border-rose-400/30 bg-rose-400/10 p-3 text-xs text-rose-200">{error}</div> : null}
        <div className="mt-5 flex justify-end gap-2"><button className="rounded-lg border border-ink-600 px-4 py-2 text-sm text-slate-300" disabled={busy} type="button" onClick={onClose}>Cancel</button><button className="inline-flex items-center gap-2 rounded-lg bg-emerald-400 px-4 py-2 text-sm font-bold text-ink-950 disabled:opacity-35" disabled={busy || !ready} type="button" onClick={() => { void submit(); }}>{busy ? <Loader2 className="animate-spin" size={15} /> : <Send size={15} />}Approve & arm</button></div>
      </section>
    </div>
  );
}

function Level({ label, value }: { label: string; value: number | string | null | undefined }) { return <div className="rounded border border-ink-700 bg-ink-900 p-2"><div className="text-[9px] text-slate-500">{label}</div><div className="mt-1 font-bold text-slate-100">{typeof value === "number" ? value.toFixed(2) : value ?? "--"}</div></div>; }
function Check({ checked, label, onChange, danger = false }: { checked: boolean; label: string; onChange: (value: boolean) => void; danger?: boolean }) { return <label className={danger ? "text-rose-200" : "text-slate-200"}><input checked={checked} className="mr-2 accent-cyan-400" type="checkbox" onChange={(event) => onChange(event.target.checked)} />{label}</label>; }
