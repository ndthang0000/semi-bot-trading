import { RotateCcw, Save, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { deleteManualZone, updateZoneOverride } from "../../api/chart";
import { compactTime } from "../../lib/time";
import { useChartStore } from "../../store/chartStore";
import type { PriceZone, ZoneTradeMode } from "../../types";

type ToastKind = "success" | "error";

export function ZoneEditor({
  zone,
  onZoneUpdated,
  showToast,
}: {
  zone: PriceZone;
  onZoneUpdated: () => void;
  showToast: (kind: ToastKind, text: string) => void;
}) {
  const setSelected = useChartStore((state) => state.setSelected);
  const [priceLow, setPriceLow] = useState(String(zone.price_low));
  const [priceHigh, setPriceHigh] = useState(String(zone.price_high));
  const [weight, setWeight] = useState(String(zone.weight));
  const [confidence, setConfidence] = useState(String(zone.confidence));
  const [status, setStatus] = useState<"active" | "disabled">(zone.status === "disabled" ? "disabled" : "active");
  const [tradeModes, setTradeModes] = useState<ZoneTradeMode[]>(defaultTradeModes(zone));
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const isDirty = useMemo(() => {
    const low = Number(priceLow);
    const high = Number(priceHigh);
    const parsedWeight = Number(weight);
    const parsedConfidence = Number(confidence);
    return (
      low !== zone.price_low ||
      high !== zone.price_high ||
      parsedWeight !== zone.weight ||
      parsedConfidence !== zone.confidence ||
      status !== (zone.status === "disabled" ? "disabled" : "active") ||
      !sameTradeModes(tradeModes, defaultTradeModes(zone)) ||
      reason.trim().length > 0
    );
  }, [confidence, priceHigh, priceLow, reason, status, tradeModes, weight, zone]);

  useEffect(() => {
    reset();
  }, [zone]);

  const reset = () => {
    setPriceLow(String(zone.price_low));
    setPriceHigh(String(zone.price_high));
    setWeight(String(zone.weight));
    setConfidence(String(zone.confidence));
    setStatus(zone.status === "disabled" ? "disabled" : "active");
    setTradeModes(defaultTradeModes(zone));
    setReason("");
    setError(null);
  };

  const save = useCallback(async () => {
    const low = Number(priceLow);
    const high = Number(priceHigh);
    const parsedWeight = Number(weight);
    const parsedConfidence = Number(confidence);
    if (!Number.isFinite(low) || !Number.isFinite(high) || low >= high) {
      setError("Price low must be lower than price high.");
      return;
    }
    if (!Number.isFinite(parsedWeight) || parsedWeight < 0 || parsedWeight > 1) {
      setError("Weight must be between 0 and 1.");
      return;
    }
    if (!Number.isFinite(parsedConfidence) || parsedConfidence < 0 || parsedConfidence > 1) {
      setError("Confidence must be between 0 and 1.");
      return;
    }
    if (!isDirty) {
      showToast("success", "Zone is already up to date.");
      return;
    }

    setIsSaving(true);
    setError(null);
    try {
      const updated = await updateZoneOverride(zone.id, {
        price_low: low,
        price_high: high,
        visual_start: zone.visual_start,
        visual_end: zone.visual_end,
        expires_at: zone.visual_end,
        weight: parsedWeight,
        confidence: parsedConfidence,
        status,
        reason: reason.trim() || undefined,
        trade_modes: tradeModes,
      });
      setSelected({ kind: "zone", entity: updated });
      onZoneUpdated();
      showToast("success", "Zone override saved.");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not save zone override.";
      setError(message);
      showToast("error", message);
    } finally {
      setIsSaving(false);
    }
  }, [confidence, isDirty, onZoneUpdated, priceHigh, priceLow, reason, setSelected, showToast, status, tradeModes, weight, zone]);

  const deleteZone = useCallback(async () => {
    if (isSaving) return;
    const confirmed = window.confirm(`Delete ${zoneDisplayName(zone)} zone from chart? This will hide it from chart payload.`);
    if (!confirmed) return;
    setIsSaving(true);
    setError(null);
    try {
      await deleteManualZone(zone.id, reason.trim() || "hotkey/manual delete");
      setSelected(null);
      onZoneUpdated();
      showToast("success", "Zone deleted from chart.");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not delete zone.";
      setError(message);
      showToast("error", message);
    } finally {
      setIsSaving(false);
    }
  }, [isSaving, onZoneUpdated, reason, setSelected, showToast, zone]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return;
      const key = event.key.toLowerCase();
      if (key === "s") {
        event.preventDefault();
        void save();
      } else if (key === "d" || key === "delete" || key === "backspace") {
        event.preventDefault();
        void deleteZone();
      } else if (key === "escape") {
        event.preventDefault();
        setSelected(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [deleteZone, save, setSelected]);

  return (
    <div className="grid gap-3 text-sm">
      <div className="grid gap-2">
        <Detail label="Type" value={`${zone.timeframe} ${zoneDisplayName(zone)}`} />
        <Detail label="Source" value={zone.source} />
        <Detail label="Start" value={compactTime(zone.visual_start)} />
        <Detail label="End" value={compactTime(zone.visual_end)} />
        <Detail label="Expires" value={compactTime(zone.valid_until)} />
        <Detail label="Touches" value={String(zone.metadata.touch_count_total ?? zone.metadata.touch_count ?? "--")} />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <NumberField label="Low" value={priceLow} onChange={setPriceLow} step="0.01" />
        <NumberField label="High" value={priceHigh} onChange={setPriceHigh} step="0.01" />
        <NumberField label="Weight" value={weight} onChange={setWeight} step="0.01" min="0" max="1" />
        <NumberField label="Confidence" value={confidence} onChange={setConfidence} step="0.01" min="0" max="1" />
      </div>

      <label className="grid gap-1 text-xs text-slate-500">
        Status
        <select
          className="h-9 rounded-md border border-ink-700 bg-ink-850 px-2 text-sm text-slate-100 outline-none"
          value={status}
          onChange={(event) => setStatus(event.target.value === "disabled" ? "disabled" : "active")}
        >
          <option value="active">active</option>
          <option value="disabled">disabled</option>
        </select>
      </label>

      <div className="grid gap-2 rounded-md border border-ink-700 bg-ink-950/50 p-3">
        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Trade modes</div>
        <div className="grid grid-cols-3 gap-2">
          {TRADE_MODE_OPTIONS.map((option) => (
            <label key={option.value} className="inline-flex items-center gap-2 rounded border border-ink-700 bg-ink-850 px-2 py-1.5 text-xs text-slate-200">
              <input
                checked={tradeModes.includes(option.value)}
                className="accent-cyan-400"
                type="checkbox"
                onChange={(event) => {
                  setTradeModes((current) =>
                    event.target.checked ? Array.from(new Set([...current, option.value])) : current.filter((mode) => mode !== option.value),
                  );
                }}
              />
              {option.label}
            </label>
          ))}
        </div>
      </div>

      <label className="grid gap-1 text-xs text-slate-500">
        Reason
        <textarea
          className="min-h-16 resize-none rounded-md border border-ink-700 bg-ink-850 px-2 py-2 text-sm text-slate-100 outline-none"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>

      {error ? <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-2 text-xs text-rose-100">{error}</div> : null}

      <div className="grid grid-cols-3 gap-2">
        <button
          className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-ink-700 bg-ink-800 text-sm text-slate-100 hover:border-slate-500"
          type="button"
          onClick={reset}
        >
          <RotateCcw size={14} />
          Reset
        </button>
        <button
          className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-cyan-400/60 bg-cyan-400/15 text-sm font-semibold text-cyan-100 hover:bg-cyan-400/25 disabled:cursor-not-allowed disabled:opacity-50"
          type="button"
          disabled={isSaving || !isDirty}
          onClick={save}
        >
          <Save size={14} />
          {isSaving ? "Saving" : "Save"}
        </button>
        <button
          className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-rose-400/50 bg-rose-500/10 text-sm font-semibold text-rose-100 hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          type="button"
          disabled={isSaving}
          title="Delete zone (D)"
          onClick={deleteZone}
        >
          <Trash2 size={14} />
          Delete
        </button>
      </div>
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
  step,
  min,
  max,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  step: string;
  min?: string;
  max?: string;
}) {
  return (
    <label className="grid gap-1 text-xs text-slate-500">
      {label}
      <input
        className="h-9 min-w-0 rounded-md border border-ink-700 bg-ink-850 px-2 text-sm text-slate-100 outline-none"
        max={max}
        min={min}
        step={step}
        type="number"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

const TRADE_MODE_OPTIONS: Array<{ value: ZoneTradeMode; label: string }> = [
  { value: "reject", label: "Reject" },
  { value: "internal_reject", label: "Internal" },
  { value: "breakout", label: "Breakout" },
];

function defaultTradeModes(zone: PriceZone): ZoneTradeMode[] {
  const raw = zone.metadata.trade_modes;
  if (Array.isArray(raw)) {
    return raw.filter((mode): mode is ZoneTradeMode => mode === "reject" || mode === "internal_reject" || mode === "breakout");
  }
  if (zone.type === "fvg") return ["reject", "internal_reject"];
  if (zone.type === "consolidation") return ["breakout"];
  if (zone.type === "support" || zone.type === "resistance") return ["reject"];
  return [];
}

function sameTradeModes(first: ZoneTradeMode[], second: ZoneTradeMode[]): boolean {
  if (first.length !== second.length) return false;
  const normalized = new Set(first);
  return second.every((mode) => normalized.has(mode));
}

function zoneDisplayName(zone: PriceZone): string {
  const kind = zone.metadata.add_entity_kind;
  if (kind === "demand_order_block") return "Demand OB";
  if (kind === "supply_order_block") return "Supply OB";
  if (kind === "bullish_fvg") return "Bullish FVG";
  if (kind === "bearish_fvg") return "Bearish FVG";
  if (kind === "buy_side_liquidity") return "Buy-side Liquidity";
  if (kind === "sell_side_liquidity") return "Sell-side Liquidity";
  if (zone.type === "order_block") return zone.direction === "bullish" ? "Demand OB" : "Supply OB";
  if (zone.type === "fvg") return zone.direction === "bullish" ? "Bullish FVG" : "Bearish FVG";
  if (zone.type === "liquidity_pool") return "Liquidity Pool";
  return zone.type;
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] gap-3">
      <span className="text-slate-500">{label}</span>
      <strong className="min-w-0 break-words text-slate-100">{value}</strong>
    </div>
  );
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName.toLowerCase();
  return tagName === "input" || tagName === "textarea" || tagName === "select" || target.isContentEditable;
}
