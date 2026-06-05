import { Layers, MousePointer2, RotateCcw, Save, Target, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { deleteManualZone, updateZoneOverride } from "../api/chart";
import { compactTime, price } from "../lib/time";
import { useChartStore } from "../store/chartStore";
import type { ChartPayload, PriceZone, SetupCandidate, TradeOrder, ZoneTypeVisibility } from "../types";

type InspectorProps = {
  payload: ChartPayload | undefined;
  onZoneUpdated: () => void;
};

type InspectorTab = "zones" | "setups";

export function Inspector({ payload, onZoneUpdated }: InspectorProps) {
  const selected = useChartStore((state) => state.selected);
  const setSelected = useChartStore((state) => state.setSelected);
  const focusZone = useChartStore((state) => state.focusZone);
  const importantZonesOnly = useChartStore((state) => state.importantZonesOnly);
  const maxVisibleZones = useChartStore((state) => state.maxVisibleZones);
  const showZones = useChartStore((state) => state.showZones);
  const zoneTypeVisibility = useChartStore((state) => state.zoneTypeVisibility);
  const zones = payload?.layers.zones ?? [];
  const setupCandidates = payload?.layers.setup_candidates ?? [];
  const layerFilteredZones = showZones ? zones.filter((zone) => isZoneTypeVisible(zone, zoneTypeVisibility)) : [];
  const lastCandle = payload?.layers.candles.at(-1);
  const selectedZoneId = selected?.kind === "zone" ? selected.entity.id : null;
  const visibleZones =
    importantZonesOnly && lastCandle
      ? filterImportantZoneList(layerFilteredZones, lastCandle.close, lastCandle.time, maxVisibleZones, selectedZoneId)
      : layerFilteredZones.slice().sort((a, b) => b.weight - a.weight);
  const [activeTab, setActiveTab] = useState<InspectorTab>("zones");

  return (
    <aside className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden border-l border-ink-700 bg-ink-900">
      <div className="border-b border-ink-700 p-3">
        <div className="grid grid-cols-2 gap-2 rounded-lg border border-ink-700 bg-ink-950 p-1">
          <button
            className={`inline-flex h-9 items-center justify-center gap-2 rounded-md text-sm font-semibold transition ${
              activeTab === "zones" ? "bg-cyan-400/15 text-cyan-100" : "text-slate-400 hover:bg-ink-800 hover:text-slate-100"
            }`}
            type="button"
            onClick={() => setActiveTab("zones")}
          >
            <Layers size={16} />
            Zones
            <span className="rounded bg-ink-900 px-1.5 py-0.5 text-[10px] text-slate-400">{visibleZones.length}</span>
          </button>
          <button
            className={`inline-flex h-9 items-center justify-center gap-2 rounded-md text-sm font-semibold transition ${
              activeTab === "setups" ? "bg-cyan-400/15 text-cyan-100" : "text-slate-400 hover:bg-ink-800 hover:text-slate-100"
            }`}
            type="button"
            onClick={() => setActiveTab("setups")}
          >
            <Target size={16} />
            Setups
            <span className="rounded bg-ink-900 px-1.5 py-0.5 text-[10px] text-slate-400">{setupCandidates.length}</span>
          </button>
        </div>
      </div>

      {activeTab === "zones" ? (
        <ZonesTab
          importantZonesOnly={importantZonesOnly}
          onZoneUpdated={onZoneUpdated}
          selected={selected}
          setSelected={setSelected}
          focusZone={focusZone}
          visibleZones={visibleZones}
          totalZones={zones.length}
        />
      ) : (
        <SetupsPanel candidates={setupCandidates} zones={zones} />
      )}
    </aside>
  );
}

function ZonesTab({
  selected,
  visibleZones,
  totalZones,
  importantZonesOnly,
  onZoneUpdated,
  setSelected,
  focusZone,
}: {
  selected: ReturnType<typeof useChartStore.getState>["selected"];
  visibleZones: PriceZone[];
  totalZones: number;
  importantZonesOnly: boolean;
  onZoneUpdated: () => void;
  setSelected: (selected: ReturnType<typeof useChartStore.getState>["selected"]) => void;
  focusZone: (zone: PriceZone) => void;
}) {
  return (
    <div className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden">
      <section className="min-h-0 border-b border-ink-700 p-4">
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
          <TradeDetails trade={selected.entity} />
        )}
      </section>

      <section className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden p-4">
        <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
          <Layers size={14} />
          Zones
          {importantZonesOnly ? (
            <span className="ml-auto normal-case tracking-normal text-slate-600">
              {visibleZones.length}/{totalZones}
            </span>
          ) : null}
        </div>
        <div className="min-h-0 overflow-y-auto overscroll-contain pr-1">
          <div className="grid gap-2">
            {visibleZones.map((zone) => (
              <button
                key={zone.id}
                className={`rounded-md border p-3 text-left transition ${
                  selected?.kind === "zone" && selected.entity.id === zone.id
                    ? "border-cyan-400 bg-cyan-400/10"
                    : "border-ink-700 bg-ink-850 hover:border-slate-600"
                }`}
                type="button"
                onClick={() => {
                  setSelected({ kind: "zone", entity: zone });
                  focusZone(zone);
                }}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className={zoneTitleClass(zone)}>{zoneDisplayName(zone)}</span>
                  <span className="text-xs text-slate-400">{zone.status}</span>
                </div>
                <div className="mt-1 text-xs text-slate-400">
                  {price(zone.price_low)} - {price(zone.price_high)} · w {zone.weight.toFixed(2)} · {formatZoneDate(zone.visual_start)}
                </div>
              </button>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

function SetupsPanel({ candidates, zones }: { candidates: SetupCandidate[]; zones: PriceZone[] }) {
  const focusZone = useChartStore((state) => state.focusZone);
  const [focusedCandidateId, setFocusedCandidateId] = useState<string | null>(null);
  const [watchedIds, setWatchedIds] = useState<Set<string>>(new Set());
  const [rejectedIds, setRejectedIds] = useState<Set<string>>(new Set());
  const [disabledPlaybooks, setDisabledPlaybooks] = useState<Set<string>>(new Set());
  const visibleCandidates = candidates.filter(
    (candidate) => !rejectedIds.has(candidate.id) && !disabledPlaybooks.has(candidate.playbook),
  );
  const grouped = {
    eligible: visibleCandidates.filter((candidate) => candidate.status === "eligible"),
    waiting: visibleCandidates.filter((candidate) => candidate.status === "waiting_confirmation"),
    watching: visibleCandidates.filter((candidate) => candidate.status === "watching" || watchedIds.has(candidate.id)),
    blocked: visibleCandidates.filter((candidate) => candidate.status === "blocked" && !watchedIds.has(candidate.id)),
  };

  const focusCandidate = (candidate: SetupCandidate) => {
    setFocusedCandidateId(candidate.id);
    const zone = zones.find((item) => item.id === candidate.primary_zone_id);
    if (!zone) return;
    focusZone(zone);
  };

  return (
    <section className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden p-4">
      <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
        <Target size={14} />
        Setups
        <span className="ml-auto normal-case tracking-normal text-slate-600">{visibleCandidates.length}/{candidates.length}</span>
      </div>
      {visibleCandidates.length === 0 ? (
        <div className="rounded-md border border-dashed border-ink-700 p-3 text-xs text-slate-500">No active setup candidates</div>
      ) : (
        <div className="min-h-0 overflow-y-auto overscroll-contain pr-1">
          <div className="grid gap-3">
            {Object.entries(grouped).map(([status, items]) =>
              items.length > 0 ? (
                <div key={status} className="grid gap-1.5">
                  <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-600">{statusLabel(status)}</div>
                  {items.map((candidate) => (
                    <div
                      key={candidate.id}
                      className={`rounded-md border p-3 text-left transition ${
                        focusedCandidateId === candidate.id
                          ? "ring-1 ring-cyan-300"
                          : ""
                      } ${setupCardClass(candidate.status)}`}
                      role="button"
                      tabIndex={0}
                      onClick={() => focusCandidate(candidate)}
                      onKeyDown={(event) => {
                        if (event.key !== "Enter" && event.key !== " ") return;
                        event.preventDefault();
                        focusCandidate(candidate);
                      }}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-semibold text-slate-100">{playbookLabel(candidate.playbook)}</span>
                        <span className={candidate.direction === "long" ? "text-xs text-emerald-300" : "text-xs text-rose-300"}>
                          {candidate.direction}
                        </span>
                      </div>
                      <div className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-[11px] text-slate-400">
                        <span>score {candidate.score.toFixed(2)}</span>
                        <span>{candidate.zone_reaction_state}</span>
                        {candidate.risk_reward ? <span>RR {candidate.risk_reward.toFixed(2)}</span> : null}
                      </div>
                      {candidate.entry && candidate.stop_loss ? (
                        <div className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-[11px] text-slate-500">
                          <span>Entry {price(candidate.entry)}</span>
                          <span>SL {price(candidate.stop_loss)}</span>
                          {candidate.take_profit[0] ? <span>TP {price(candidate.take_profit[0])}</span> : null}
                        </div>
                      ) : null}
                      <div className="mt-1 truncate text-[11px] text-slate-500">
                        {(candidate.blocked_reason[0] ?? candidate.reason[0] ?? "--")}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1">
                        <SetupAction
                          label={watchedIds.has(candidate.id) ? "Watching" : "Watch"}
                          onClick={() =>
                            setWatchedIds((current) => toggleSetValue(current, candidate.id))
                          }
                        />
                        <SetupAction
                          label="Reject"
                          onClick={() =>
                            setRejectedIds((current) => addSetValue(current, candidate.id))
                          }
                        />
                        <SetupAction
                          label="Disable PB"
                          onClick={() =>
                            setDisabledPlaybooks((current) => addSetValue(current, candidate.playbook))
                          }
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : null,
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function SetupAction({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <span
      className="rounded border border-ink-700 bg-ink-950 px-1.5 py-0.5 text-[10px] text-slate-300 hover:border-cyan-500 hover:text-cyan-100"
      role="button"
      tabIndex={0}
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        event.stopPropagation();
        onClick();
      }}
    >
      {label}
    </span>
  );
}

function TradeMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-xs text-slate-500">{label}</span>
      <strong className="shrink-0 whitespace-nowrap text-right text-sm text-slate-100">{value}</strong>
    </div>
  );
}

function TradeDetails({ trade }: { trade: TradeOrder }) {
  const metadata = trade.metadata ?? {};
  const candidateMetadata = readObject(metadata.candidate_metadata);
  const reasons = readStringList(metadata.reason);
  const blockedReasons = readStringList(metadata.blocked_reason);
  const triggerTypes = readStringList(candidateMetadata.trigger_types);
  const takeProfit = firstTakeProfitPrice(trade.take_profit);
  const statusNote = tradeStatusNote(trade.status);
  return (
    <div className="grid gap-3 text-sm">
      <div className="grid gap-2">
        <Detail label="Playbook" value={playbookLabel(trade.playbook)} />
        <Detail label="Side" value={trade.side} />
        <Detail label="Status" value={trade.status} />
        <Detail label="Backtest" value={metadata.backtest === true ? "true" : "--"} />
      </div>

      {statusNote ? (
        <div className="rounded-md border border-yellow-300/25 bg-yellow-300/[0.06] p-2 text-xs leading-relaxed text-yellow-50">
          {statusNote}
        </div>
      ) : null}

      <div className="grid gap-2 rounded-md border border-ink-700 bg-ink-950/60 p-3">
        <TradeMetric label="Entry" value={price(trade.entry_price)} />
        <TradeMetric label="SL" value={price(trade.stop_loss)} />
        <TradeMetric label="TP" value={price(takeProfit)} />
        <TradeMetric label="Exit" value={price(trade.close_price)} />
        <TradeMetric label="PnL R" value={trade.pnl_r === null ? "--" : `${trade.pnl_r.toFixed(2)}R`} />
        <TradeMetric label="Score" value={formatUnknownNumber(metadata.score)} />
      </div>

      <div className="grid gap-2">
        <Detail label="Opened" value={compactTime(trade.opened_at)} />
        <Detail label="Closed" value={compactTime(trade.closed_at)} />
        <Detail label="Reaction" value={String(metadata.zone_reaction_state ?? "--")} />
        <Detail label="Zone" value={String(candidateMetadata.zone_type ?? "--")} />
        <Detail label="Trigger" value={triggerTypes.length > 0 ? triggerTypes.join(" + ") : "--"} />
      </div>

      <div className="grid gap-1">
        <div className="text-xs text-slate-500">Reason</div>
        <div className="rounded-md border border-cyan-400/25 bg-cyan-400/[0.06] p-2 text-xs leading-relaxed text-cyan-50">
          {reasons.length > 0 ? (
            <ul className="grid gap-1">
              {reasons.map((reason, index) => (
                <li key={`${reason}-${index}`}>• {reason}</li>
              ))}
            </ul>
          ) : (
            "--"
          )}
        </div>
      </div>

      {blockedReasons.length > 0 ? (
        <div className="grid gap-1">
          <div className="text-xs text-slate-500">Blocked reason at signal</div>
          <div className="rounded-md border border-rose-400/25 bg-rose-500/[0.06] p-2 text-xs leading-relaxed text-rose-50">
            <ul className="grid gap-1">
              {blockedReasons.map((reason, index) => (
                <li key={`${reason}-${index}`}>• {reason}</li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}
    </div>
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
  }, [confidence, noExpiry, onZoneUpdated, priceHigh, priceLow, reason, setSelected, status, weight, zone]);

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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete zone.");
    } finally {
      setIsSaving(false);
    }
  }, [isSaving, onZoneUpdated, reason, setSelected, zone.id]);

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
        <Detail label="Type" value={zoneDisplayName(zone)} />
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
          disabled={isSaving}
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

function defaultNoExpiry(zone: PriceZone): boolean {
  return zone.valid_until === null && zone.metadata.human_adjusted === true;
}

function filterImportantZoneList(
  zones: PriceZone[],
  currentPrice: number,
  lastCandleTime: string,
  maxZones: number,
  selectedZoneId: string | null,
): PriceZone[] {
  const pinned = zones.filter((zone) => zone.id === selectedZoneId);
  const pinnedIds = new Set(pinned.map((zone) => zone.id));
  const ranked = zones
    .filter((zone) => !pinnedIds.has(zone.id))
    .map((zone) => ({ zone, score: zoneImportanceScore(zone, currentPrice, lastCandleTime) }))
    .sort((a, b) => b.score - a.score);

  const selectedZones: PriceZone[] = [...pinned];
  const targetCount = Math.max(maxZones, pinned.length);
  for (const candidate of ranked) {
    if (selectedZones.length >= targetCount) break;
    selectedZones.push(candidate.zone);
  }
  return selectedZones;
}

function isZoneTypeVisible(zone: PriceZone, visibility: ZoneTypeVisibility): boolean {
  if (zone.type === "support") return visibility.support;
  if (zone.type === "resistance") return visibility.resistance;
  if (zone.type === "order_block") return visibility.order_block;
  if (zone.type === "fvg") return visibility.fvg;
  if (zone.type === "liquidity_pool") return visibility.liquidity_pool;
  if (zone.type === "consolidation") return visibility.consolidation;
  return true;
}

function zoneImportanceScore(zone: PriceZone, currentPrice: number, lastCandleTime: string): number {
  const center = (zone.price_low + zone.price_high) / 2;
  const zoneWidth = Math.max(zone.price_high - zone.price_low, 1);
  const distance = Math.abs(center - currentPrice);
  const proximity = 1 / (1 + distance / Math.max(currentPrice * 0.008, zoneWidth * 3, 1));
  const anchorTime = Date.parse(zone.detected_at || zone.visual_start);
  const lastTime = Date.parse(lastCandleTime);
  const ageDays = Number.isFinite(anchorTime) && Number.isFinite(lastTime) ? Math.max((lastTime - anchorTime) / 86_400_000, 0) : 0;
  const recency = 1 / (1 + ageDays / 21);
  const activeBoost = zone.status === "active" ? 0.12 : 0;
  const humanBoost = isHumanZone(zone) ? 0.18 : 0;

  return zone.weight * 0.48 + proximity * 0.24 + recency * 0.16 + activeBoost + humanBoost;
}

function isHumanZone(zone: PriceZone): boolean {
  return zone.source === "human" || zone.metadata.human_created === true;
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

function zoneTitleClass(zone: PriceZone): string {
  if (zone.type === "order_block") {
    return zone.direction === "bullish" ? "font-semibold text-cyan-300" : "font-semibold text-fuchsia-300";
  }
  if (zone.type === "fvg") {
    return zone.direction === "bullish" ? "font-semibold text-lime-300" : "font-semibold text-orange-300";
  }
  if (zone.type === "consolidation") return "font-semibold text-sky-300";
  if (zone.type === "liquidity_pool") return "font-semibold text-yellow-300";
  return zone.direction === "bullish" ? "font-semibold text-emerald-300" : "font-semibold text-rose-300";
}

function statusLabel(status: string): string {
  if (status === "waiting") return "Waiting";
  if (status === "watching") return "Watching";
  if (status === "eligible") return "Eligible";
  if (status === "blocked") return "Blocked";
  return status;
}

function setupCardClass(status: SetupCandidate["status"]): string {
  if (status === "eligible") return "border-cyan-400/70 bg-cyan-400/10 hover:bg-cyan-400/15";
  if (status === "waiting_confirmation") return "border-yellow-300/50 bg-yellow-300/[0.07] hover:bg-yellow-300/[0.12]";
  if (status === "watching") return "border-slate-600 bg-ink-850 hover:border-slate-500";
  if (status === "blocked") return "border-rose-500/30 bg-rose-500/[0.05] opacity-80 hover:opacity-100";
  return "border-ink-700 bg-ink-850";
}

function playbookLabel(value: string): string {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function toggleSetValue(current: Set<string>, value: string): Set<string> {
  const next = new Set(current);
  if (next.has(value)) {
    next.delete(value);
  } else {
    next.add(value);
  }
  return next;
}

function addSetValue(current: Set<string>, value: string): Set<string> {
  const next = new Set(current);
  next.add(value);
  return next;
}

function readObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function readStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.length > 0);
}

function firstTakeProfitPrice(values: TradeOrder["take_profit"]): number | null {
  const first = values.at(0);
  if (typeof first === "number") return first;
  if (first && typeof first.price === "number") return first.price;
  return null;
}

function formatUnknownNumber(value: unknown): string {
  return typeof value === "number" ? value.toFixed(2) : "--";
}

function tradeStatusNote(status: string): string | null {
  if (status === "time_exit") {
    return "Time exit: lệnh chưa chạm SL/TP trong thời gian giữ tối đa của backtest, nên bị đóng ở close của nến hết hạn. Nếu giá chạm TP sau thời điểm Closed thì backtest không tính TP đó.";
  }
  if (status === "target_hit") return "Target hit: giá đã chạm TP trong thời gian giữ lệnh.";
  if (status === "stopped") return "Stopped: giá đã chạm SL trong thời gian giữ lệnh.";
  return null;
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName.toLowerCase();
  return tagName === "input" || tagName === "textarea" || tagName === "select" || target.isContentEditable;
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
