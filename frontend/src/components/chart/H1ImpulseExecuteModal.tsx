import { Loader2, Send, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { approveManualAiPlan, fetchManualAiWorkers, importManualAiPlans, type ManualAiWorker } from "../../api/manualAi";
import { revalidateH1Impulse, type H1ImpulseRevalidation, type H1ImpulseTargetMode } from "../../api/h1Impulse";
import type { SetupCandidate } from "../../types";
import { reviewH1Execution } from "./h1ExecutionReview";

type Props = {
  candidate: SetupCandidate;
  onClose: () => void;
  onSubmitted: (planId: string) => void;
};

export function H1ImpulseExecuteModal({ candidate, onClose, onSubmitted }: Props) {
  const initialPartial = isRecord(candidate.metadata.partial_take_profit) ? candidate.metadata.partial_take_profit : {};
  const finalRiskReward = candidate.risk_reward ?? 0;
  const [workers, setWorkers] = useState<ManualAiWorker[]>([]);
  const [selectedWorkers, setSelectedWorkers] = useState<string[]>([]);
  const [calm, setCalm] = useState(false);
  const [acceptRisk, setAcceptRisk] = useState(false);
  const [dynamicLot, setDynamicLot] = useState(false);
  const [competingExposure, setCompetingExposure] = useState(false);
  const [overrideAccepted, setOverrideAccepted] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [draftPlanId, setDraftPlanId] = useState<string | null>(null);
  const suggestedExpiryHours = Number(candidate.metadata.expiry_hours ?? 6);
  const parameters = isRecord(candidate.metadata.parameters) ? candidate.metadata.parameters : {};
  const configuredMinTtl = Number(parameters.min_order_ttl_hours ?? 1);
  const configuredMaxTtl = Number(parameters.max_order_ttl_hours ?? 48);
  const [expiryHours, setExpiryHours] = useState(() => clampHours(suggestedExpiryHours, configuredMinTtl, configuredMaxTtl));
  const [revalidation, setRevalidation] = useState<H1ImpulseRevalidation | null>(null);
  const [revalidating, setRevalidating] = useState(true);
  const [partialEnabled, setPartialEnabled] = useState(
    typeof initialPartial.enabled === "boolean" ? initialPartial.enabled : finalRiskReward >= 1.5,
  );
  const [partialTriggerR, setPartialTriggerR] = useState(
    typeof initialPartial.trigger_r === "number" ? initialPartial.trigger_r : 1,
  );
  const [partialCloseFraction, setPartialCloseFraction] = useState(
    typeof initialPartial.close_fraction === "number" ? initialPartial.close_fraction : 0.4,
  );
  const [partialMoveStopTo, setPartialMoveStopTo] = useState<"breakeven" | "unchanged">(
    initialPartial.move_stop_to === "unchanged" ? "unchanged" : "breakeven",
  );
  const [partialBreakevenBuffer, setPartialBreakevenBuffer] = useState(
    String(typeof initialPartial.breakeven_buffer === "number" ? initialPartial.breakeven_buffer : 0),
  );
  const signalTime = String(candidate.metadata.signal_candle_time ?? "");
  const entrySource = String(candidate.metadata.entry_source ?? "strategy_calculated");
  const rawTargetMode = candidate.metadata.target_mode;
  const targetMode: H1ImpulseTargetMode = rawTargetMode === "wave_safe" || rawTargetMode === "wave_base"
    ? rawTargetMode
    : "fixed_rr";
  const executionReview = useMemo(() => reviewH1Execution(candidate), [candidate]);
  const requiresOverride = executionReview.softBlockedReasons.length > 0;
  const renewedFromPlanId = candidate.metadata.execution_plan === true
    && candidate.metadata.manual_ai_plan_status === "expired"
    ? candidate.id
    : null;

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

  useEffect(() => {
    let active = true;
    if (!signalTime || candidate.entry === null || candidate.stop_loss === null || typeof candidate.take_profit[0] !== "number") {
      setRevalidating(false);
      setError("Thiếu signal candle hoặc Entry/SL/TP để revalidate.");
      return () => { active = false; };
    }
    setRevalidating(true);
    void revalidateH1Impulse({
      symbol: candidate.symbol,
      signalCandleTime: signalTime,
      direction: candidate.direction,
      entry: candidate.entry,
      stopLoss: candidate.stop_loss,
      takeProfit: candidate.take_profit[0],
      targetMode,
    }).then((result) => {
      if (!active) return;
      setRevalidation(result);
      setExpiryHours((current) => clampHours(current, result.min_order_ttl_hours, result.max_order_ttl_hours));
    }).catch((caught) => {
      if (active) setError(caught instanceof Error ? caught.message : "Không thể revalidate H1 signal.");
    }).finally(() => {
      if (active) setRevalidating(false);
    });
    return () => { active = false; };
  }, [candidate.direction, candidate.entry, candidate.stop_loss, candidate.symbol, candidate.take_profit, signalTime, targetMode]);

  const submit = async () => {
    if (candidate.entry === null || candidate.stop_loss === null || typeof candidate.take_profit[0] !== "number") return;
    setBusy(true);
    setError("");
    try {
      const latestRevalidation = await revalidateH1Impulse({
        symbol: candidate.symbol,
        signalCandleTime: signalTime,
        direction: candidate.direction,
        entry: candidate.entry,
        stopLoss: candidate.stop_loss,
        takeProfit: candidate.take_profit[0],
        targetMode,
      });
      setRevalidation(latestRevalidation);
      let planId = draftPlanId;
      if (!planId) {
        const requestedAt = new Date().toISOString();
        const result = await importManualAiPlans({
          schema_version: 1,
          as_of: requestedAt,
          symbol: candidate.symbol,
          playbook: "h1_impulse_retest_v1",
          analysis_timeframes: { context: "H1", structure: "M15", execution: "M5" },
          market_context: {
            source: "h1_impulse_preview",
            signal_candle_time: candidate.metadata.signal_candle_time,
            atr: candidate.metadata.atr,
            parameters: candidate.metadata.parameters,
            entry_options: candidate.metadata.entry_options,
            target_mode: targetMode,
            target_plan: candidate.metadata.target_plan,
            original_status: candidate.metadata.original_status,
            original_blocked_reasons: candidate.metadata.original_blocked_reasons,
            human_override: requiresOverride,
            override_reason: requiresOverride ? overrideReason.trim() : "",
            order_ttl_hours: expiryHours,
            revalidation: latestRevalidation,
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
            partial_take_profit: {
              enabled: partialEnabled,
              trigger_r: partialTriggerR,
              close_fraction: partialCloseFraction,
              move_stop_to: partialMoveStopTo,
              breakeven_buffer: Number(partialBreakevenBuffer) || 0,
            },
            cancel_conditions: [
              { type: candidate.direction === "long" ? "m5_close_below" : "m5_close_above", price: candidate.stop_loss },
              { type: "price_reached_target_without_fill" },
              { type: "news_blackout_started" },
            ],
            entry_source: entrySource,
            entry_options: candidate.metadata.entry_options,
            original_status: executionReview.originalBlocked ? "blocked" : "eligible",
            original_blocked_reasons: Array.isArray(candidate.metadata.original_blocked_reasons) ? candidate.metadata.original_blocked_reasons : [],
            soft_blocked_reasons: executionReview.softBlockedReasons,
            hard_blocked_reasons: executionReview.hardBlockedReasons,
            human_override: requiresOverride,
            override_reason: requiresOverride ? overrideReason.trim() : "",
            renewed_from_plan_id: renewedFromPlanId,
            renewal_count: Number(candidate.metadata.renewal_count ?? 0) + (renewedFromPlanId ? 1 : 0),
            entry_reason: `H1 impulse entry from ${entrySource}`,
            stop_reason: "H1 wick invalidation plus ATR buffer; human-confirmed levels",
            target_reason: `${targetMode} target · ${candidate.risk_reward?.toFixed(2) ?? "--"}R${partialEnabled ? ` · partial ${Math.round(partialCloseFraction * 100)}% at ${partialTriggerR.toFixed(2)}R` : " · full exit"}`,
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
          comment: requiresOverride
            ? `H1 blocked setup overridden: ${overrideReason.trim()}`
            : `Approved H1 Impulse Retest; entry source=${entrySource}`,
        },
      });
      onSubmitted(approved.plans[0]?.id ?? planId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Không thể gửi H1 limit plan.");
    } finally {
      setBusy(false);
    }
  };

  const overrideReady = !requiresOverride || (
    executionReview.softBlockedReasons.length > 0
    && overrideAccepted
    && overrideReason.trim().length >= 20
  );
  const revalidationHardBlocks = revalidation?.hard_blocked_reasons ?? [];
  const partialBuffer = Number(partialBreakevenBuffer);
  const partialValid = !partialEnabled || (
    partialTriggerR < finalRiskReward
    && Number.isFinite(partialBuffer)
    && partialBuffer >= 0
    && partialBuffer <= 10
  );
  const ready = !revalidating
    && revalidation !== null
    && executionReview.hardBlockedReasons.length === 0
    && overrideReady
    && calm
    && acceptRisk
    && dynamicLot
    && !competingExposure
    && partialValid
    && selectedWorkers.length > 0;
  return (
    <div className="fixed inset-0 z-[110] grid place-items-center bg-black/75 p-3 backdrop-blur-sm" onPointerDown={(event) => event.stopPropagation()}>
      <section className="max-h-[94vh] w-full max-w-xl overflow-y-auto rounded-2xl border border-cyan-400/30 bg-ink-950 p-5 shadow-2xl">
        <header className="flex items-start gap-3">
          <Send className="mt-1 text-cyan-300" size={20} />
          <div className="min-w-0 flex-1"><h2 className="text-lg font-bold text-slate-100">{renewedFromPlanId ? "Revalidate & re-order H1 limit" : "Send H1 Impulse limit to MT5"}</h2><p className="mt-1 text-xs text-slate-400">TTL tính từ lúc arm; worker vẫn kiểm tra spread, news, position limit và tự tính lot.</p></div>
          <button className="text-slate-500 hover:text-white" type="button" onClick={onClose}><X size={19} /></button>
        </header>
        <div className="mt-4 grid grid-cols-4 gap-2 text-center font-mono text-xs">
          <Level label="ENTRY" value={candidate.entry} /><Level label="SL" value={candidate.stop_loss} /><Level label="TP" value={candidate.take_profit[0]} /><Level label="EXPIRY" value={`${expiryHours}h`} />
        </div>
        <div className="mt-3 rounded-lg border border-cyan-400/20 bg-cyan-400/[0.06] px-3 py-2 text-xs text-cyan-100">Entry source: <strong>{entrySource.replace(/_/g, " ")}</strong></div>
        <div className="mt-2 rounded-lg border border-violet-400/20 bg-violet-400/[0.06] px-3 py-2 text-xs text-violet-100">
          TP source: <strong>{targetMode.replace(/_/g, " ")}</strong> · {finalRiskReward.toFixed(2)}R
        </div>
        <section className="mt-3 rounded-xl border border-violet-400/25 bg-violet-400/[0.05] p-3">
          <label className="flex items-center justify-between gap-3 text-sm font-semibold text-violet-100">
            <span><span className="block">Partial TP</span><span className="mt-0.5 block text-[11px] font-normal text-slate-400">Tuỳ chỉnh trước khi arm lệnh.</span></span>
            <input checked={partialEnabled} className="h-4 w-4 accent-violet-400" type="checkbox" onChange={(event) => setPartialEnabled(event.target.checked)} />
          </label>
          <div className={`mt-3 grid gap-3 sm:grid-cols-3 ${partialEnabled ? "" : "pointer-events-none opacity-40"}`}>
            <PartialOptionGroup
              label="Kích hoạt tại"
              options={[0.75, 1, 1.25, 1.5].map((value) => ({ label: `${value.toFixed(2)}R`, value, disabled: value >= finalRiskReward }))}
              selected={partialTriggerR}
              onSelect={setPartialTriggerR}
            />
            <PartialOptionGroup
              label="Khối lượng chốt"
              options={[0.25, 0.33, 0.5].map((value) => ({ label: `${Math.round(value * 100)}%`, value }))}
              selected={partialCloseFraction}
              onSelect={setPartialCloseFraction}
            />
            <div className="grid content-start gap-1.5">
              <span className="text-[11px] text-slate-400">SL sau partial</span>
              <div className="flex flex-wrap gap-1">
                <PartialChoice active={partialMoveStopTo === "breakeven"} label="Dời về BE" onClick={() => setPartialMoveStopTo("breakeven")} />
                <PartialChoice active={partialMoveStopTo === "unchanged"} label="Giữ nguyên" onClick={() => setPartialMoveStopTo("unchanged")} />
              </div>
            </div>
          </div>
          {partialEnabled && partialMoveStopTo === "breakeven" ? (
            <label className="mt-3 grid max-w-52 gap-1 text-xs text-slate-400">BE buffer (giá)<input className="h-9 rounded-lg border border-ink-600 bg-ink-950 px-3 font-mono text-sm text-slate-100 outline-none focus:border-violet-400" min={0} max={10} step={0.1} type="number" value={partialBreakevenBuffer} onChange={(event) => setPartialBreakevenBuffer(event.target.value)} /></label>
          ) : null}
          {partialEnabled && !partialValid ? <p className="mt-2 text-[10px] text-amber-200">Partial trigger phải thấp hơn final TP {finalRiskReward.toFixed(2)}R; BE buffer cho phép 0–10 giá.</p> : null}
        </section>
        <div className="mt-3 rounded-lg border border-ink-700 bg-ink-900/60 p-3">
          <div className="flex items-center justify-between gap-3 text-xs"><span className="font-bold uppercase tracking-wide text-slate-400">Order TTL</span><span className="font-mono font-bold text-cyan-200">{expiryHours}h</span></div>
          <div className="mt-2 flex flex-wrap gap-1.5">{[6, 12, 18, 24, 48].filter((hours) => hours >= configuredMinTtl && hours <= configuredMaxTtl).map((hours) => <button key={hours} className={`rounded border px-2 py-1 text-xs ${expiryHours === hours ? "border-cyan-300 bg-cyan-300/15 text-cyan-100" : "border-ink-600 text-slate-400"}`} type="button" onClick={() => setExpiryHours(hours)}>{hours}h</button>)}</div>
          <label className="mt-2 flex items-center gap-2 text-xs text-slate-400"><span>Custom</span><input className="w-20 rounded border border-ink-600 bg-ink-950 px-2 py-1 font-mono text-slate-100" max={configuredMaxTtl} min={configuredMinTtl} step={1} type="number" value={expiryHours} onChange={(event) => setExpiryHours(clampHours(Number(event.target.value), configuredMinTtl, configuredMaxTtl))} /><span>hours from approval</span></label>
          <div className="mt-2 text-[10px] text-slate-500">Suggested by Body/ATR: {suggestedExpiryHours}h · Allowed {configuredMinTtl}–{configuredMaxTtl}h</div>
        </div>
        {revalidating ? <div className="mt-3 flex items-center gap-2 rounded-lg border border-cyan-400/20 bg-cyan-400/[0.05] p-3 text-xs text-cyan-100"><Loader2 className="animate-spin" size={14} />Revalidating signal age and untouched levels…</div> : null}
        {revalidation ? <div className={`mt-3 rounded-lg border p-3 text-xs ${revalidation.can_reorder ? "border-emerald-400/25 bg-emerald-400/[0.06] text-emerald-100" : "border-amber-400/35 bg-amber-400/[0.08] text-amber-100"}`}><div className="font-bold">{revalidation.can_reorder ? "✓ Signal remains actionable" : "⚠ Signal has renewal warnings"}</div><div className="mt-1 text-slate-400">Age {revalidation.signal_age_hours.toFixed(1)}h / {revalidation.max_signal_age_hours}h · Checked with {revalidation.timeframe_used}</div></div> : null}
        {executionReview.softBlockedReasons.length > 0 ? (
          <ReviewReasons
            icon="⚠"
            reasons={executionReview.softBlockedReasons}
            title="Soft blocks · trader may override"
            tone="amber"
          />
        ) : null}
        {executionReview.hardBlockedReasons.length > 0 ? (
          <ReviewReasons
            icon="⛔"
            reasons={executionReview.hardBlockedReasons}
            title="Hard blocks · must be resolved"
            tone="rose"
          />
        ) : null}
        {revalidationHardBlocks.length > 0 ? <ReviewReasons icon="⚠" reasons={revalidationHardBlocks} title="Renewal warnings · trader decides" tone="amber" /> : null}
        {requiresOverride ? (
          <div className="mt-4 grid gap-2 rounded-lg border border-amber-400/30 bg-amber-400/[0.06] p-3">
            <div className="text-xs font-bold uppercase tracking-wide text-amber-200">Human override audit</div>
            <textarea
              className="min-h-20 rounded-md border border-ink-600 bg-ink-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-amber-300"
              maxLength={2000}
              placeholder="Giải thích vì sao signal vẫn hợp lệ dù bị soft block (tối thiểu 20 ký tự)…"
              value={overrideReason}
              onChange={(event) => setOverrideReason(event.target.value)}
            />
            <div className="text-right text-[10px] text-slate-500">{overrideReason.trim().length}/20 minimum</div>
            <Check checked={overrideAccepted} label="Tôi đã đọc từng soft block và chủ động chấp nhận override." onChange={setOverrideAccepted} />
          </div>
        ) : null}
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
        <div className="mt-5 flex justify-end gap-2"><button className="rounded-lg border border-ink-600 px-4 py-2 text-sm text-slate-300" disabled={busy} type="button" onClick={onClose}>Cancel</button><button className="inline-flex items-center gap-2 rounded-lg bg-emerald-400 px-4 py-2 text-sm font-bold text-ink-950 disabled:opacity-35" disabled={busy || !ready} type="button" onClick={() => { void submit(); }}>{busy ? <Loader2 className="animate-spin" size={15} /> : <Send size={15} />}{renewedFromPlanId ? "Re-order & arm" : requiresOverride ? "Override & arm" : "Approve & arm"}</button></div>
      </section>
    </div>
  );
}

function Level({ label, value }: { label: string; value: number | string | null | undefined }) { return <div className="rounded border border-ink-700 bg-ink-900 p-2"><div className="text-[9px] text-slate-500">{label}</div><div className="mt-1 font-bold text-slate-100">{typeof value === "number" ? value.toFixed(2) : value ?? "--"}</div></div>; }
function Check({ checked, label, onChange, danger = false }: { checked: boolean; label: string; onChange: (value: boolean) => void; danger?: boolean }) { return <label className={danger ? "text-rose-200" : "text-slate-200"}><input checked={checked} className="mr-2 accent-cyan-400" type="checkbox" onChange={(event) => onChange(event.target.checked)} />{label}</label>; }

function PartialOptionGroup({ label, onSelect, options, selected }: { label: string; onSelect: (value: number) => void; options: Array<{ label: string; value: number; disabled?: boolean }>; selected: number }) {
  return <div className="grid content-start gap-1.5"><span className="text-[11px] text-slate-400">{label}</span><div className="flex flex-wrap gap-1">{options.map((option) => <PartialChoice key={option.value} active={selected === option.value} disabled={option.disabled} label={option.label} onClick={() => onSelect(option.value)} />)}</div></div>;
}

function PartialChoice({ active, disabled = false, label, onClick }: { active: boolean; disabled?: boolean; label: string; onClick: () => void }) {
  return <button className={`rounded border px-2 py-1 text-[10px] font-semibold transition disabled:cursor-not-allowed disabled:opacity-30 ${active ? "border-violet-300 bg-violet-400/20 text-violet-100" : "border-ink-600 bg-ink-900 text-slate-400 hover:border-violet-400/60"}`} disabled={disabled} type="button" onClick={onClick}>{label}</button>;
}

function ReviewReasons({ icon, reasons, title, tone }: { icon: string; reasons: string[]; title: string; tone: "amber" | "rose" }) {
  const className = tone === "amber"
    ? "border-amber-400/30 bg-amber-400/[0.06] text-amber-100"
    : "border-rose-400/35 bg-rose-400/[0.08] text-rose-100";
  return <div className={`mt-3 rounded-lg border p-3 text-xs ${className}`}><div className="font-bold">{icon} {title}</div><ul className="mt-2 list-disc space-y-1 pl-4">{reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></div>;
}

function clampHours(value: number, minimum: number, maximum: number): number {
  if (!Number.isFinite(value)) return minimum;
  return Math.min(maximum, Math.max(minimum, Math.round(value)));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
