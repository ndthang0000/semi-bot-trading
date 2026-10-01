import { AlertTriangle, Loader2 } from "lucide-react";

export type ManualAiEditableLevels = {
  entry: number;
  stopLoss: number;
  takeProfit: number;
};

type Props = {
  playbook?: string;
  side: "buy" | "sell";
  status: string;
  levels: ManualAiEditableLevels;
  original: ManualAiEditableLevels;
  error: string | null;
  saving: boolean;
  entrySource?: string;
  entryOptions?: Array<{ source: string; label: string; price: number }>;
  rrMin?: number;
  rrMax?: number | null;
  onEntrySourceSelect?: (source: string, price: number) => void;
  onLevelsChange: (levels: ManualAiEditableLevels) => void;
  onApply: () => void;
  onCancel: () => void;
};

export function ManualAiLevelEditDialog({ playbook = "manual_ai_v1", side, status, levels, original, error, saving, entrySource, entryOptions = [], rrMin = 1.5, rrMax = 4, onEntrySourceSelect, onLevelsChange, onApply, onCancel }: Props) {
  const risk = Math.abs(levels.entry - levels.stopLoss);
  const reward = Math.abs(levels.takeProfit - levels.entry);
  const rr = risk > 0 ? reward / risk : 0;
  const validGeometry = side === "buy"
    ? levels.stopLoss < levels.entry && levels.entry < levels.takeProfit
    : levels.takeProfit < levels.entry && levels.entry < levels.stopLoss;
  const levelsValid = validGeometry && rr >= rrMin && (rrMax === null || rr <= rrMax);
  const quickOrder = playbook === "quick_order_v1";
  const brokerReplace = status === "armed" || status === "replace_requested" || (quickOrder && status === "pending");
  const h1Impulse = playbook === "h1_impulse_retest_v1";
  const setupLabel = quickOrder ? "Quick Order" : h1Impulse ? "H1 Impulse" : "Manual AI";
  return (
    <div className="pointer-events-auto absolute bottom-4 left-1/2 z-[90] w-[min(720px,calc(100%-2rem))] -translate-x-1/2 rounded-xl border border-yellow-300/40 bg-ink-950/95 p-3 shadow-2xl backdrop-blur" onPointerDown={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div><div className="text-sm font-bold text-yellow-100">Chỉnh {setupLabel} · kéo tiếp hoặc nhập giá</div>
          <p className="mt-0.5 text-[11px] leading-4 text-slate-400">
          {brokerReplace
            ? "Limit đã nằm trên MT5. Worker sẽ hủy ticket cũ, kiểm tra chưa fill, tính lại lot và đặt ticket mới."
            : h1Impulse ? "Preview local: chọn nhanh nguồn Entry hoặc kéo trực tiếp các mức giá." : "Plan chưa có pending order trên broker nên backend có thể cập nhật trực tiếp."}
          </p></div>
          <div className={`shrink-0 rounded border px-2 py-1 text-xs font-black ${levelsValid ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-200" : "border-rose-400/30 bg-rose-400/10 text-rose-200"}`}>{rr.toFixed(2)}R</div>
        </div>
        {!levelsValid ? <div className="mt-2 text-[10px] font-medium text-rose-300">Kiểm tra lại thứ tự giá và giữ R:R {rrMax === null ? `từ ${rrMin.toFixed(1)}R trở lên` : `trong khoảng ${rrMin.toFixed(1)}R–${rrMax.toFixed(1)}R`}.</div> : null}
        {entryOptions.length > 0 && onEntrySourceSelect ? (
          <div className="mt-2">
            <div className="mb-1 text-[10px] font-bold uppercase tracking-wide text-cyan-200">Entry source</div>
            <div className="flex flex-wrap gap-1.5">
              {entryOptions.map((option) => (
                <button
                  key={option.source}
                  className={`rounded border px-2 py-1 text-[10px] ${entrySource === option.source ? "border-cyan-300 bg-cyan-300/15 text-cyan-100" : "border-ink-600 text-slate-400 hover:border-cyan-400/60"}`}
                  disabled={saving}
                  type="button"
                  onClick={() => onEntrySourceSelect(option.source, option.price)}
                >
                  {option.label} · {option.price.toFixed(2)}
                </button>
              ))}
              <button className={`rounded border px-2 py-1 text-[10px] ${entrySource === "human_custom" ? "border-amber-300 bg-amber-300/15 text-amber-100" : "border-ink-600 text-slate-400"}`} type="button" onClick={() => onEntrySourceSelect("human_custom", levels.entry)}>Custom</button>
            </div>
          </div>
        ) : null}
        <div className="mt-2 grid grid-cols-3 gap-2">
          <LevelInput label="Entry" tone="cyan" oldValue={original.entry} value={levels.entry} disabled={saving} onChange={(entry) => onLevelsChange({ ...levels, entry })} />
          <LevelInput label="Stop Loss" tone="rose" oldValue={original.stopLoss} value={levels.stopLoss} disabled={saving} onChange={(stopLoss) => onLevelsChange({ ...levels, stopLoss })} />
          <LevelInput label="Take Profit" tone="emerald" oldValue={original.takeProfit} value={levels.takeProfit} disabled={saving} onChange={(takeProfit) => onLevelsChange({ ...levels, takeProfit })} />
        </div>
        {error ? <div className="mt-3 rounded-lg border border-rose-500/35 bg-rose-950/70 px-3 py-2 text-xs text-rose-100">{error}</div> : null}
        <div className="mt-3 flex items-center gap-2">
          <div className="mr-auto flex items-center gap-1.5 text-[10px] text-amber-100/70"><AlertTriangle size={12} />{side.toUpperCase()} limit · Esc để hủy</div>
          <button className="rounded-lg border border-ink-600 px-3 py-2 text-xs font-semibold text-slate-300 hover:bg-ink-800 disabled:opacity-50" disabled={saving} type="button" onClick={onCancel}>Hủy thay đổi</button>
          <button className="inline-flex items-center gap-2 rounded-lg border border-yellow-300/40 bg-yellow-300/15 px-3 py-2 text-xs font-bold text-yellow-100 hover:bg-yellow-300/25 disabled:cursor-not-allowed disabled:opacity-35" disabled={saving || !levelsValid} type="button" onClick={onApply}>
            {saving ? <Loader2 className="animate-spin" size={14} /> : null}
            {brokerReplace ? "Cancel & replace" : "Lưu mức giá"}
          </button>
        </div>
    </div>
  );
}

function LevelInput({ label, oldValue, value, disabled, onChange, tone }: { label: string; oldValue: number; value: number; disabled: boolean; onChange: (value: number) => void; tone: "cyan" | "rose" | "emerald" }) {
  const toneClass = tone === "cyan" ? "text-cyan-200" : tone === "rose" ? "text-rose-200" : "text-emerald-200";
  return (
    <label className="rounded-lg border border-ink-700 bg-ink-900/80 p-2">
      <span className={`block text-[10px] font-bold uppercase tracking-wide ${toneClass}`}>{label}</span>
      <input
        className="mt-1 h-8 w-full rounded border border-ink-600 bg-ink-950 px-2 text-sm font-semibold text-slate-100 outline-none focus:border-cyan-400"
        disabled={disabled}
        inputMode="decimal"
        step="0.01"
        type="number"
        value={value}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (Number.isFinite(next) && next > 0) onChange(next);
        }}
      />
      <span className="mt-1 block text-[9px] text-slate-500">Cũ {oldValue.toFixed(2)}</span>
    </label>
  );
}
