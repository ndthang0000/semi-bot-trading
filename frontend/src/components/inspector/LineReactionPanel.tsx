import { useEffect, useRef, useState } from "react";
import { Save, ShieldCheck, Trash2, X } from "lucide-react";
import { useLineReactionStore, type LineConfig as Config, type LinePlan as Plan } from "../../store/lineReactionStore";
import { useChartStore } from "../../store/chartStore";
import {
  armLineReaction, cancelLineReaction, createLineReaction, fetchLineAccounts,
  fetchLineReactions, updateLineReaction, type LineAccount, type LineSession,
} from "../../api/lineReaction";

const defaults: Config = {
  recovery_ratio: 2, body_period: 20, stop_buffer_atr: 0.1, max_stop_h1_atr: 1.2,
  limit_offset: 5, limit_ttl_minutes: 120, risk_reward: 2, target_mode: "fixed_rr",
  partial_enabled: false, partial_trigger_r: 1, partial_fraction: 0.4,
  trade_sessions: []
};

const planAccounts = (plan: Plan) => plan.account_labels ?? [plan.account_label];
const sorted = (values: string[]) => [...values].sort();
const remainingHours = (iso: string) => Math.max(0, (Date.parse(iso) - Date.now()) / 3_600_000);
const hoursLabel = (iso: string) => {
  const hours = remainingHours(iso);
  if (hours === 0) return "Đã hết hạn";
  const rounded = hours < 10 ? Math.ceil(hours * 10) / 10 : Math.ceil(hours);
  return `${rounded.toLocaleString("vi-VN", { maximumFractionDigits: 1 })} giờ`;
};
const statusBadgeClass = (status: string) => {
  if (status === "draft") return "border-amber-400/30 bg-amber-400/10 text-amber-200";
  if (status === "armed") return "border-emerald-400/30 bg-emerald-400/10 text-emerald-200";
  if (["executing", "pending", "cancel_requested"].includes(status)) return "border-cyan-400/30 bg-cyan-400/10 text-cyan-200";
  if (status === "reconciliation_required") return "border-rose-400/40 bg-rose-400/10 text-rose-200";
  return "border-ink-700 bg-ink-950 text-slate-400";
};
export function LineReactionPanel({ symbol }: { symbol: string }) {
  const plans = useLineReactionStore(s => s.plans);
  const setPlans = useLineReactionStore(s => s.setPlans);
  const upsertPlan = useLineReactionStore(s => s.upsertPlan);
  const draft = useLineReactionStore(s => s.draft);
  const selectedId = useLineReactionStore(s => s.selectedId);
  const selected = plans.find(p => p.id === selectedId);
  const consumed = useRef<unknown>(null);
  const [accounts, setAccounts] = useState<LineAccount[]>([]);
  const [sessions, setSessions] = useState<LineSession[]>([]);
  const [selectedAccounts, setSelectedAccounts] = useState<string[]>([]);
  const [config, setConfig] = useState<Config>(defaults);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const data = await fetchLineReactions();
        if (active) { setPlans(data.plans); setSessions(data.sessions); setError(""); }
      } catch (e) { if (active) setError(String(e)); }
    };
    void refresh();
    void fetchLineAccounts().then(items => {
      const online = items.filter(account => account.execution?.worker_status === "online").map(account => account.label);
      if (active) { setAccounts(items); setSelectedAccounts(online); }
    }).catch(e => { if (active) setError(String(e)); });
    const poll = window.setInterval(() => void refresh(), 5000);
    return () => { active = false; clearInterval(poll); };
  }, [setPlans]);

  const act = async (operation: () => Promise<Plan>, clearSelection = false) => {
    setBusy(true); setError("");
    try {
      const plan = await operation();
      upsertPlan(plan);
      if (clearSelection) useLineReactionStore.getState().select(null);
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  };

  useEffect(() => {
    if (!selected) return;
    setSelectedAccounts(planAccounts(selected));
    setConfig(selected.config);
  }, [selectedId, selected?.status, selected?.updated_at]);

  useEffect(() => {
    const availableAccounts = accounts.filter(account => account.execution?.worker_status === "online").map(account => account.label);
    if (!draft || !availableAccounts.length || !sessions.length || consumed.current === draft) return;
    consumed.current = draft;
    setBusy(true); setError("");
    void createLineReaction({
      symbol, ...draft, account_labels: availableAccounts,
      config: { ...defaults, trade_sessions: sessions.map(session => session.value) },
    }).then((created: Plan) => {
      upsertPlan(created);
      useLineReactionStore.getState().select(created.id);
      useLineReactionStore.getState().setDraft(null);
    }).catch(e => { setError(String(e)); consumed.current = null; })
      .finally(() => setBusy(false));
  }, [draft, accounts, sessions, symbol, upsertPlan]);

  const field = (key: keyof Config, label: string, step = "0.1", min?: number, max?: number) => (
    <label className="grid gap-1 text-xs text-slate-300">{label}
      <input className="rounded bg-ink-950 p-2" type="number" step={step} min={min} max={max} value={Number(config[key])}
        onChange={event => setConfig({ ...config, [key]: Number(event.target.value) })} />
    </label>
  );
  const activePlans = plans
    .filter(plan => !["cancelled", "expired", "closed", "failed"].includes(plan.status))
    .sort((left, right) => right.price - left.price);
  const selectedDirty = Boolean(selected && (
    JSON.stringify(config) !== JSON.stringify(selected.config) ||
    JSON.stringify(sorted(selectedAccounts)) !== JSON.stringify(sorted(planAccounts(selected)))
  ));
  const toggleAccount = (label: string) => setSelectedAccounts(current =>
    current.includes(label) ? current.filter(value => value !== label) : [...current, label]
  );
  const toggleSession = (value: string) => setConfig(current => {
    const selected = current.trade_sessions.includes(value)
      ? current.trade_sessions.filter(session => session !== value)
      : [...current.trade_sessions, value];
    return selected.length ? { ...current, trade_sessions: selected } : current;
  });
  const canCancelSelected = Boolean(selected && Object.values(
    selected.account_statuses ?? Object.fromEntries(planAccounts(selected).map(label => [label, selected.status]))
  ).some(status => ["draft", "armed", "executing", "pending", "cancel_requested"].includes(status)));

  return <section className="border-b border-ink-700 p-4 text-slate-100" onPointerDown={event => event.stopPropagation()}>
    <div className="mb-3 flex items-center justify-between gap-2">
      <div><strong className="text-sm">Line Prices</strong><p className="mt-0.5 text-[11px] text-slate-500">Reaction Lines · M15</p></div>
      <span className="rounded-full border border-ink-700 bg-ink-950 px-2 py-0.5 text-[10px] text-slate-400">{activePlans.length}</span>
    </div>
    {draft && !accounts.some(account => account.execution?.worker_status === "online") && <p className="text-xs text-amber-300">Chưa có worker online. Line chưa được lưu; khởi động worker rồi thử lại.</p>}
    {error && <p role="alert" className="mb-2 text-xs text-rose-300">{error}</p>}
    <div className="grid gap-1.5">
      {activePlans.length === 0 ? <div className="rounded-md border border-dashed border-ink-700 px-3 py-2 text-xs text-slate-500">Add Entity → Add line buy / sell</div> : null}
      {activePlans.map(plan => {
        const isSelected = plan.id === selectedId;
        const isLong = plan.direction === "long";
        const labels = planAccounts(plan);
        return <button key={plan.id} type="button"
          className={`flex w-full items-center gap-2 rounded-md border px-2.5 py-2 text-left transition ${isSelected ? "border-cyan-400 bg-cyan-400/10" : "border-ink-700 bg-ink-850 hover:border-slate-600"}`}
          onClick={() => {
            useChartStore.getState().setSelected(null);
            useLineReactionStore.getState().select(isSelected ? null : plan.id);
          }}>
          <span className={`grid h-7 w-7 shrink-0 place-items-center rounded ${isLong ? "bg-emerald-400/10 text-emerald-300" : "bg-rose-400/10 text-rose-300"}`}>{isLong ? "↑" : "↓"}</span>
          <span className="min-w-0 flex-1">
            <span className="flex items-center gap-2"><strong className={`font-mono text-sm tabular-nums ${isLong ? "text-emerald-200" : "text-rose-200"}`}>{plan.price.toFixed(2)}</strong><span className={`rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase ${statusBadgeClass(plan.status)}`}>{plan.status}</span></span>
            <span className="block truncate text-[10px] text-slate-500">{labels.length} account · còn {hoursLabel(plan.expires_at)}</span>
          </span>
          <span className="text-xs text-slate-600">{isSelected ? "▴" : "▾"}</span>
        </button>;
      })}
    </div>

    {selected ? <div className="mt-3 rounded-lg border border-cyan-400/25 bg-cyan-400/5 p-3">
      <div className="mb-3 flex items-center justify-between gap-2">
        <strong className="text-xs uppercase tracking-wider text-cyan-200">Line detail</strong>
        <button aria-label="Đóng Line detail" title="Đóng" type="button" className="rounded p-1 text-slate-400 hover:bg-white/5 hover:text-slate-100" onClick={() => useLineReactionStore.getState().select(null)}><X size={17} /></button>
      </div>
      <div className={`mb-3 rounded-lg border p-3 ${selected.direction === "long" ? "border-emerald-400/30 bg-emerald-400/10" : "border-rose-400/30 bg-rose-400/10"}`}>
        <div className="flex items-center justify-between gap-3">
          <div><p className="text-[10px] uppercase tracking-widest text-slate-400">Giá Line</p><strong className="font-mono text-2xl tabular-nums">{selected.price.toFixed(2)}</strong></div>
          <span className={`rounded-full px-3 py-1 text-xs font-bold ${selected.direction === "long" ? "bg-emerald-400/15 text-emerald-200" : "bg-rose-400/15 text-rose-200"}`}>{selected.direction === "long" ? "↑ LONG" : "↓ SHORT"}</span>
        </div>
      </div>
      {["draft", "armed"].includes(selected.status) ? <form className="grid gap-3" onSubmit={event => {
        event.preventDefault();
        void act(() => updateLineReaction(selected.id, {
            symbol, account_labels: selectedAccounts, direction: selected.direction, price: selected.price, config,
            visual_start: selected.visual_start, visual_end: selected.visual_end,
            ...(selected.visual_end ? {} : { expires_in_minutes: Math.max(15, Math.ceil(remainingHours(selected.expires_at) * 60)) }),
          }));
      }}>
        <fieldset className="grid gap-1.5">
          <legend className="mb-1 text-xs text-slate-300">Accounts <span className="text-slate-500">· {selectedAccounts.length}/{accounts.length} đã chọn</span></legend>
          <div className="grid gap-1 rounded-md border border-ink-700 bg-ink-950 p-2">
            {accounts.map(account => <label key={account.label} className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-xs hover:bg-white/5">
              <input type="checkbox" checked={selectedAccounts.includes(account.label)} onChange={() => toggleAccount(account.label)} />
              <span className="min-w-0 flex-1 truncate">{account.label}</span>
              <span className={account.execution?.worker_status === "online" ? "text-[9px] text-emerald-300" : "text-[9px] text-amber-300"}>{account.execution?.worker_status ?? "offline"}</span>
            </label>)}
          </div>
        </fieldset>
        <fieldset className="grid gap-1.5">
          <legend className="mb-1 text-xs text-slate-300">Phiên giao dịch <span className="text-slate-500">· {config.trade_sessions.length}/{sessions.length} đã chọn</span></legend>
          <div className="grid grid-cols-2 gap-1 rounded-md border border-ink-700 bg-ink-950 p-2">
            {sessions.map(session => <label key={session.value} className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-xs hover:bg-white/5">
              <input type="checkbox" checked={config.trade_sessions.includes(session.value)} onChange={() => toggleSession(session.value)} />
              <span><span className="block">{session.label}</span><span className="text-[9px] text-slate-500">{session.start_utc}–{session.end_utc} UTC</span></span>
            </label>)}
          </div>
          <p className="text-[10px] text-slate-500">Mặc định tất cả phiên · giờ cố định UTC.</p>
        </fieldset>
        <div className="rounded-md border border-ink-700 bg-ink-950/70 px-3 py-2">
          <div className="flex items-center justify-between gap-2 text-xs"><span className="text-slate-400">Hết hạn</span><strong>{hoursLabel(selected.expires_at)}</strong></div>
          <p className="mt-1 text-[10px] text-slate-500">{new Date(selected.expires_at).toLocaleString()}</p>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {field("recovery_ratio", "Recovery / body")}
          {field("body_period", "Số nến baseline", "1")}
          {field("stop_buffer_atr", "Buffer ATR M15")}
          {field("max_stop_h1_atr", "Max SL / ATR H1")}
          {field("limit_offset", "Trả giá từ close")}
          {field("limit_ttl_minutes", "Limit TTL (phút)", "1")}
        </div>
        <label className="grid gap-1 text-xs">TP tối đa<select className="bg-ink-950 p-2" value={config.risk_reward} onChange={event => setConfig({ ...config, risk_reward: Number(event.target.value) })}>
          <option value="1.5">1,5R</option><option value="2">2R</option><option value="2.5">2,5R</option><option value="3">3R</option></select></label>
        <label className="grid gap-1 text-xs">Cách chọn TP<select className="bg-ink-950 p-2" value={config.target_mode} onChange={event => setConfig({ ...config, target_mode: event.target.value })}>
          <option value="fixed_rr">Fixed RR</option><option value="wave_safe">Wave Safe</option><option value="wave_base">Wave Base</option></select></label>
        <label className="text-xs"><input type="checkbox" checked={config.partial_enabled} onChange={event => setConfig({ ...config, partial_enabled: event.target.checked })} /> Quản lý tại R + BE</label>
        {config.partial_enabled && <div className="grid gap-1.5"><div className="grid grid-cols-2 gap-2">{field("partial_trigger_r", "Trigger R", "0.1", 0.5, 1.5)}{field("partial_fraction", "Tỷ lệ chốt (0–0,5)", "0.05", 0, 0.5)}</div><p className="text-[10px] text-slate-500">Đặt tỷ lệ chốt = 0 để chỉ dời SL về hòa vốn.</p></div>}
        <p className="text-[11px] text-slate-400">Risk: quỹ 0,75%; cá nhân 1,5%. Một lệnh đồng thời/account. SL bị cap có thể nằm trong râu. Wave thiếu dữ liệu hoặc dưới 2R sẽ không vào lệnh.</p>
        <div className="grid grid-cols-3 gap-2">
          <button disabled={busy || selectedAccounts.length === 0} className="flex items-center justify-center gap-1 rounded bg-cyan-700 p-2 text-xs disabled:opacity-40"><Save size={14} /> Save</button>
          <button type="button" disabled={busy || selected.status === "armed" || selectedDirty} title={selected.status === "armed" ? "Setup đã Armed; bạn vẫn có thể chỉnh và Save" : "Lưu thay đổi Draft trước khi Arm"} className="flex items-center justify-center gap-1 rounded bg-emerald-700/80 p-2 text-xs disabled:opacity-40" onClick={() => void act(() => armLineReaction(selected.id))}><ShieldCheck size={14} /> {selected.status === "armed" ? "Armed" : "Arm"}</button>
          <button type="button" disabled={busy} className="flex items-center justify-center gap-1 rounded bg-rose-500/10 p-2 text-xs text-rose-300 disabled:opacity-40" onClick={() => {
            if (window.confirm(`Xóa Line ${selected.price.toFixed(2)} ${selected.direction.toUpperCase()}? Setup chưa khớp lệnh sẽ bị hủy trên các account đã chọn.`)) void act(() => cancelLineReaction(selected.id), true);
          }}><Trash2 size={14} /> Delete</button>
        </div>
      </form> : <div className="grid gap-2 text-xs text-slate-300">
        <div className="grid grid-cols-2 gap-2"><span>Accounts <strong>{planAccounts(selected).length}</strong></span><span>Trạng thái <strong>{selected.status}</strong></span></div>
        <div className="grid gap-1 rounded-md border border-ink-700 bg-ink-950/60 p-2">
          {planAccounts(selected).map(label => <div key={label} className="flex items-center justify-between gap-2"><span className="min-w-0 truncate text-slate-400">{label}</span><strong className="uppercase text-[10px]">{selected.account_statuses?.[label] ?? selected.status}</strong></div>)}
        </div>
        <div className="text-slate-500">{selected.config.target_mode} · {selected.config.risk_reward}R · trả {selected.config.limit_offset} · còn {hoursLabel(selected.expires_at)}</div>
        {selected.last_error && <p className="text-amber-300">{selected.last_error}</p>}
        {canCancelSelected ? <button type="button" disabled={busy} className="justify-self-start text-rose-300 disabled:opacity-40" onClick={() => void act(() => cancelLineReaction(selected.id), true)}>Hủy setup/pending còn lại</button> : null}
      </div>}
    </div> : null}
  </section>;
}
