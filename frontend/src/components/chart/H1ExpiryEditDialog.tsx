import { Clock3, Loader2, X } from "lucide-react";
import { useState } from "react";
import { updateManualAiPlanExpiry } from "../../api/manualAi";

type Props = {
  planId: string;
  initialHours: number;
  onClose: () => void;
  onUpdated: (requiresBrokerReplace: boolean) => void;
};

export function H1ExpiryEditDialog({ planId, initialHours, onClose, onUpdated }: Props) {
  const [hours, setHours] = useState(() => clampHours(initialHours));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const expiresAt = new Date(Date.now() + hours * 3_600_000);

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await updateManualAiPlanExpiry(planId, hours * 60);
      onUpdated(result.requires_broker_replace);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Không thể cập nhật expiry.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[115] grid place-items-center bg-black/75 p-3 backdrop-blur-sm" onPointerDown={(event) => event.stopPropagation()}>
      <section className="w-full max-w-md rounded-2xl border border-cyan-400/30 bg-ink-950 p-5 shadow-2xl">
        <header className="flex items-start gap-3">
          <Clock3 className="mt-0.5 text-cyan-300" size={19} />
          <div className="min-w-0 flex-1"><h2 className="font-bold text-slate-100">Edit pending-order expiry</h2><p className="mt-1 text-xs text-slate-400">TTL mới tính từ lúc xác nhận thay đổi.</p></div>
          <button className="text-slate-500 hover:text-white" type="button" onClick={onClose}><X size={18} /></button>
        </header>
        <div className="mt-4 flex flex-wrap gap-1.5">{[6, 12, 18, 24, 48].map((value) => <button key={value} className={`rounded border px-2.5 py-1.5 text-xs ${hours === value ? "border-cyan-300 bg-cyan-300/15 text-cyan-100" : "border-ink-600 text-slate-400"}`} type="button" onClick={() => setHours(value)}>{value}h</button>)}</div>
        <label className="mt-3 flex items-center gap-2 text-xs text-slate-400"><span>Custom</span><input className="w-20 rounded border border-ink-600 bg-ink-900 px-2 py-1.5 font-mono text-slate-100" max={48} min={1} type="number" value={hours} onChange={(event) => setHours(clampHours(Number(event.target.value)))} /><span>hours</span></label>
        <div className="mt-3 rounded border border-ink-700 bg-ink-900/60 p-3 text-xs text-slate-300">New expiry: <strong>{expiresAt.toLocaleString()}</strong></div>
        <p className="mt-2 text-[11px] text-amber-200/80">Nếu order đã armed, worker sẽ cancel & replace an toàn rồi tính lại broker expiration.</p>
        {error ? <div className="mt-3 rounded border border-rose-400/30 bg-rose-400/10 p-2 text-xs text-rose-200">{error}</div> : null}
        <div className="mt-5 flex justify-end gap-2"><button className="rounded border border-ink-600 px-3 py-2 text-sm text-slate-300" disabled={busy} type="button" onClick={onClose}>Cancel</button><button className="inline-flex items-center gap-2 rounded bg-cyan-300 px-3 py-2 text-sm font-bold text-ink-950 disabled:opacity-40" disabled={busy} type="button" onClick={() => { void submit(); }}>{busy ? <Loader2 className="animate-spin" size={14} /> : <Clock3 size={14} />}Update expiry</button></div>
      </section>
    </div>
  );
}

function clampHours(value: number): number {
  if (!Number.isFinite(value)) return 1;
  return Math.min(48, Math.max(1, Math.round(value)));
}
