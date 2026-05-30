import { Layers, MousePointer2, RotateCcw, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { updateZoneOverride } from "../api/chart";
import { compactTime, price } from "../lib/time";
import { useChartStore } from "../store/chartStore";
import type { ChartPayload, PriceZone } from "../types";

type InspectorProps = {
  payload: ChartPayload | undefined;
  onZoneUpdated: () => void;
};

export function Inspector({ payload, onZoneUpdated }: InspectorProps) {
  const selected = useChartStore((state) => state.selected);
  const setSelected = useChartStore((state) => state.setSelected);
  const zones = payload?.layers.zones ?? [];

  return (
    <aside className="min-h-0 overflow-y-auto border-l border-ink-700 bg-ink-900">
      <section className="border-b border-ink-700 p-4">
        <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
          <MousePointer2 size={14} />
          Selected
        </div>
        {!selected ? (
          <div className="rounded-md border border-dashed border-ink-700 p-4 text-sm text-slate-500">Click a zone or marker</div>
        ) : selected.kind === "zone" ? (
          <ZoneEditor zone={selected.entity} onZoneUpdated={onZoneUpdated} />
        ) : selected.kind === "structure" ? (
          <div className="grid gap-2 text-sm">
            <Detail label="Type" value={selected.entity.type} />
            <Detail label="Price" value={price(selected.entity.price)} />
            <Detail label="Time" value={compactTime(selected.entity.time)} />
            <Detail label="Detector" value={selected.entity.detector} />
            <Detail label="Direction" value={selected.entity.direction ?? "--"} />
          </div>
        ) : (
          <div className="grid gap-2 text-sm">
            <Detail label="Side" value={selected.entity.side} />
            <Detail label="Status" value={selected.entity.status} />
            <Detail label="Entry" value={price(selected.entity.entry_price)} />
            <Detail label="SL" value={price(selected.entity.stop_loss)} />
            <Detail label="Opened" value={compactTime(selected.entity.opened_at)} />
          </div>
        )}
      </section>

      <section className="p-4">
        <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
          <Layers size={14} />
          Zones
        </div>
        <div className="grid gap-2">
          {zones
            .slice()
            .sort((a, b) => b.weight - a.weight)
            .map((zone) => (
              <button
                key={zone.id}
                className={`rounded-md border p-3 text-left transition ${
                  selected?.kind === "zone" && selected.entity.id === zone.id
                    ? "border-cyan-400 bg-cyan-400/10"
                    : "border-ink-700 bg-ink-850 hover:border-slate-600"
                }`}
                type="button"
                onClick={() => setSelected({ kind: "zone", entity: zone })}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className={zone.direction === "bullish" ? "font-semibold text-emerald-300" : "font-semibold text-rose-300"}>
                    {zone.type}
                  </span>
                  <span className="text-xs text-slate-400">{zone.status}</span>
                </div>
                <div className="mt-1 text-xs text-slate-400">
                  {price(zone.price_low)} - {price(zone.price_high)} · w {zone.weight.toFixed(2)} · {formatZoneDate(zone.visual_start)}
                </div>
              </button>
            ))}
        </div>
      </section>
    </aside>
  );
}

function ZoneEditor({ zone, onZoneUpdated }: { zone: PriceZone; onZoneUpdated: () => void }) {
  const setSelected = useChartStore((state) => state.setSelected);
  const [priceLow, setPriceLow] = useState(String(zone.price_low));
  const [priceHigh, setPriceHigh] = useState(String(zone.price_high));
  const [weight, setWeight] = useState(String(zone.weight));
  const [confidence, setConfidence] = useState(String(zone.confidence));
  const [status, setStatus] = useState<"active" | "disabled">(zone.status === "disabled" ? "disabled" : "active");
  const [noExpiry, setNoExpiry] = useState(defaultNoExpiry(zone));
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    setPriceLow(String(zone.price_low));
    setPriceHigh(String(zone.price_high));
    setWeight(String(zone.weight));
    setConfidence(String(zone.confidence));
    setStatus(zone.status === "disabled" ? "disabled" : "active");
    setNoExpiry(defaultNoExpiry(zone));
    setReason("");
    setError(null);
  }, [zone]);

  const reset = () => {
    setPriceLow(String(zone.price_low));
    setPriceHigh(String(zone.price_high));
    setWeight(String(zone.weight));
    setConfidence(String(zone.confidence));
    setStatus(zone.status === "disabled" ? "disabled" : "active");
    setNoExpiry(defaultNoExpiry(zone));
    setReason("");
    setError(null);
  };

  const save = async () => {
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

    setIsSaving(true);
    setError(null);
    try {
      const updated = await updateZoneOverride(zone.id, {
        price_low: low,
        price_high: high,
        visual_start: zone.visual_start,
        visual_end: zone.visual_end,
        weight: parsedWeight,
        confidence: parsedConfidence,
        status,
        no_expiry: noExpiry,
        reason: reason.trim() || undefined,
      });
      setSelected({ kind: "zone", entity: updated });
      onZoneUpdated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save zone override.");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="grid gap-3 text-sm">
      <div className="grid gap-2">
        <Detail label="Type" value={zone.type} />
        <Detail label="Source" value={zone.source} />
        <Detail label="Start" value={compactTime(zone.visual_start)} />
        <Detail label="End" value={compactTime(zone.visual_end)} />
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

      <label className="flex items-center gap-2 text-xs text-slate-400">
        <input
          checked={noExpiry}
          className="accent-cyan-400"
          type="checkbox"
          onChange={(event) => setNoExpiry(event.target.checked)}
        />
        No expiry
      </label>

      <label className="grid gap-1 text-xs text-slate-500">
        Reason
        <textarea
          className="min-h-16 resize-none rounded-md border border-ink-700 bg-ink-850 px-2 py-2 text-sm text-slate-100 outline-none"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>

      {error ? <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-2 text-xs text-rose-100">{error}</div> : null}

      <div className="grid grid-cols-2 gap-2">
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
          disabled={isSaving}
          onClick={save}
        >
          <Save size={14} />
          {isSaving ? "Saving" : "Save"}
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

function defaultNoExpiry(zone: PriceZone): boolean {
  return zone.valid_until === null && zone.metadata.human_adjusted === true;
}

function formatZoneDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return `${String(date.getDate()).padStart(2, "0")}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] gap-3">
      <span className="text-slate-500">{label}</span>
      <strong className="min-w-0 break-words text-slate-100">{value}</strong>
    </div>
  );
}
