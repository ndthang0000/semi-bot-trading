import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Layers, MousePointer2, RotateCcw, Save, Target, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { deleteManualZone, updateZoneOverride } from "../api/chart";
import { compactTime, price } from "../lib/time";
import { useChartStore } from "../store/chartStore";
export function Inspector({ payload, onZoneUpdated }) {
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
    const visibleZones = importantZonesOnly && lastCandle
        ? filterImportantZoneList(layerFilteredZones, lastCandle.close, lastCandle.time, maxVisibleZones, selectedZoneId)
        : layerFilteredZones.slice().sort((a, b) => b.weight - a.weight);
    const [activeTab, setActiveTab] = useState("zones");
    return (_jsxs("aside", { className: "grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden border-l border-ink-700 bg-ink-900", children: [_jsx("div", { className: "border-b border-ink-700 p-3", children: _jsxs("div", { className: "grid grid-cols-2 gap-2 rounded-lg border border-ink-700 bg-ink-950 p-1", children: [_jsxs("button", { className: `inline-flex h-9 items-center justify-center gap-2 rounded-md text-sm font-semibold transition ${activeTab === "zones" ? "bg-cyan-400/15 text-cyan-100" : "text-slate-400 hover:bg-ink-800 hover:text-slate-100"}`, type: "button", onClick: () => setActiveTab("zones"), children: [_jsx(Layers, { size: 16 }), "Zones", _jsx("span", { className: "rounded bg-ink-900 px-1.5 py-0.5 text-[10px] text-slate-400", children: visibleZones.length })] }), _jsxs("button", { className: `inline-flex h-9 items-center justify-center gap-2 rounded-md text-sm font-semibold transition ${activeTab === "setups" ? "bg-cyan-400/15 text-cyan-100" : "text-slate-400 hover:bg-ink-800 hover:text-slate-100"}`, type: "button", onClick: () => setActiveTab("setups"), children: [_jsx(Target, { size: 16 }), "Setups", _jsx("span", { className: "rounded bg-ink-900 px-1.5 py-0.5 text-[10px] text-slate-400", children: setupCandidates.length })] })] }) }), activeTab === "zones" ? (_jsx(ZonesTab, { importantZonesOnly: importantZonesOnly, onZoneUpdated: onZoneUpdated, selected: selected, setSelected: setSelected, focusZone: focusZone, visibleZones: visibleZones, totalZones: zones.length })) : (_jsx(SetupsPanel, { candidates: setupCandidates, zones: zones }))] }));
}
function ZonesTab({ selected, visibleZones, totalZones, importantZonesOnly, onZoneUpdated, setSelected, focusZone, }) {
    return (_jsxs("div", { className: "grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden", children: [_jsxs("section", { className: "min-h-0 border-b border-ink-700 p-4", children: [_jsxs("div", { className: "mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500", children: [_jsx(MousePointer2, { size: 14 }), "Selected"] }), !selected ? (_jsx("div", { className: "rounded-md border border-dashed border-ink-700 p-4 text-sm text-slate-500", children: "Click a zone or marker" })) : selected.kind === "zone" ? (_jsx(ZoneEditor, { zone: selected.entity, onZoneUpdated: onZoneUpdated })) : selected.kind === "structure" ? (_jsxs("div", { className: "grid gap-2 text-sm", children: [_jsx(Detail, { label: "Type", value: selected.entity.type }), _jsx(Detail, { label: "Price", value: price(selected.entity.price) }), _jsx(Detail, { label: "Time", value: compactTime(selected.entity.time) }), _jsx(Detail, { label: "Detector", value: selected.entity.detector }), _jsx(Detail, { label: "Direction", value: selected.entity.direction ?? "--" })] })) : (_jsx(TradeDetails, { trade: selected.entity }))] }), _jsxs("section", { className: "grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden p-4", children: [_jsxs("div", { className: "mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500", children: [_jsx(Layers, { size: 14 }), "Zones", importantZonesOnly ? (_jsxs("span", { className: "ml-auto normal-case tracking-normal text-slate-600", children: [visibleZones.length, "/", totalZones] })) : null] }), _jsx("div", { className: "min-h-0 overflow-y-auto overscroll-contain pr-1", children: _jsx("div", { className: "grid gap-2", children: visibleZones.map((zone) => (_jsxs("button", { className: `rounded-md border p-3 text-left transition ${selected?.kind === "zone" && selected.entity.id === zone.id
                                    ? "border-cyan-400 bg-cyan-400/10"
                                    : "border-ink-700 bg-ink-850 hover:border-slate-600"}`, type: "button", onClick: () => {
                                    setSelected({ kind: "zone", entity: zone });
                                    focusZone(zone);
                                }, children: [_jsxs("div", { className: "flex items-center justify-between gap-2", children: [_jsx("span", { className: zoneTitleClass(zone), children: zoneDisplayName(zone) }), _jsx("span", { className: "text-xs text-slate-400", children: zone.status })] }), _jsxs("div", { className: "mt-1 text-xs text-slate-400", children: [price(zone.price_low), " - ", price(zone.price_high), " \u00B7 w ", zone.weight.toFixed(2), " \u00B7 ", formatZoneDate(zone.visual_start)] })] }, zone.id))) }) })] })] }));
}
function SetupsPanel({ candidates, zones }) {
    const focusZone = useChartStore((state) => state.focusZone);
    const [focusedCandidateId, setFocusedCandidateId] = useState(null);
    const [watchedIds, setWatchedIds] = useState(new Set());
    const [rejectedIds, setRejectedIds] = useState(new Set());
    const [disabledPlaybooks, setDisabledPlaybooks] = useState(new Set());
    const visibleCandidates = candidates.filter((candidate) => !rejectedIds.has(candidate.id) && !disabledPlaybooks.has(candidate.playbook));
    const grouped = {
        eligible: visibleCandidates.filter((candidate) => candidate.status === "eligible"),
        waiting: visibleCandidates.filter((candidate) => candidate.status === "waiting_confirmation"),
        watching: visibleCandidates.filter((candidate) => candidate.status === "watching" || watchedIds.has(candidate.id)),
        blocked: visibleCandidates.filter((candidate) => candidate.status === "blocked" && !watchedIds.has(candidate.id)),
    };
    const focusCandidate = (candidate) => {
        setFocusedCandidateId(candidate.id);
        const zone = zones.find((item) => item.id === candidate.primary_zone_id);
        if (!zone)
            return;
        focusZone(zone);
    };
    return (_jsxs("section", { className: "grid min-h-0 grid-rows-[auto_minmax(0,1fr)] overflow-hidden p-4", children: [_jsxs("div", { className: "mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-500", children: [_jsx(Target, { size: 14 }), "Setups", _jsxs("span", { className: "ml-auto normal-case tracking-normal text-slate-600", children: [visibleCandidates.length, "/", candidates.length] })] }), visibleCandidates.length === 0 ? (_jsx("div", { className: "rounded-md border border-dashed border-ink-700 p-3 text-xs text-slate-500", children: "No active setup candidates" })) : (_jsx("div", { className: "min-h-0 overflow-y-auto overscroll-contain pr-1", children: _jsx("div", { className: "grid gap-3", children: Object.entries(grouped).map(([status, items]) => items.length > 0 ? (_jsxs("div", { className: "grid gap-1.5", children: [_jsx("div", { className: "text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-600", children: statusLabel(status) }), items.map((candidate) => (_jsxs("div", { className: `rounded-md border p-3 text-left transition ${focusedCandidateId === candidate.id
                                    ? "ring-1 ring-cyan-300"
                                    : ""} ${setupCardClass(candidate.status)}`, role: "button", tabIndex: 0, onClick: () => focusCandidate(candidate), onKeyDown: (event) => {
                                    if (event.key !== "Enter" && event.key !== " ")
                                        return;
                                    event.preventDefault();
                                    focusCandidate(candidate);
                                }, children: [_jsxs("div", { className: "flex items-center justify-between gap-2", children: [_jsx("span", { className: "truncate text-sm font-semibold text-slate-100", children: playbookLabel(candidate.playbook) }), _jsx("span", { className: candidate.direction === "long" ? "text-xs text-emerald-300" : "text-xs text-rose-300", children: candidate.direction })] }), _jsxs("div", { className: "mt-1 flex flex-wrap gap-x-2 gap-y-1 text-[11px] text-slate-400", children: [_jsxs("span", { children: ["score ", candidate.score.toFixed(2)] }), _jsx("span", { children: candidate.zone_reaction_state }), candidate.risk_reward ? _jsxs("span", { children: ["RR ", candidate.risk_reward.toFixed(2)] }) : null] }), candidate.entry && candidate.stop_loss ? (_jsxs("div", { className: "mt-1 flex flex-wrap gap-x-2 gap-y-1 text-[11px] text-slate-500", children: [_jsxs("span", { children: ["Entry ", price(candidate.entry)] }), _jsxs("span", { children: ["SL ", price(candidate.stop_loss)] }), candidate.take_profit[0] ? _jsxs("span", { children: ["TP ", price(candidate.take_profit[0])] }) : null] })) : null, _jsx("div", { className: "mt-1 truncate text-[11px] text-slate-500", children: (candidate.blocked_reason[0] ?? candidate.reason[0] ?? "--") }), _jsxs("div", { className: "mt-2 flex flex-wrap gap-1", children: [_jsx(SetupAction, { label: watchedIds.has(candidate.id) ? "Watching" : "Watch", onClick: () => setWatchedIds((current) => toggleSetValue(current, candidate.id)) }), _jsx(SetupAction, { label: "Reject", onClick: () => setRejectedIds((current) => addSetValue(current, candidate.id)) }), _jsx(SetupAction, { label: "Disable PB", onClick: () => setDisabledPlaybooks((current) => addSetValue(current, candidate.playbook)) })] })] }, candidate.id)))] }, status)) : null) }) }))] }));
}
function SetupAction({ label, onClick }) {
    return (_jsx("span", { className: "rounded border border-ink-700 bg-ink-950 px-1.5 py-0.5 text-[10px] text-slate-300 hover:border-cyan-500 hover:text-cyan-100", role: "button", tabIndex: 0, onClick: (event) => {
            event.stopPropagation();
            onClick();
        }, onKeyDown: (event) => {
            if (event.key !== "Enter" && event.key !== " ")
                return;
            event.preventDefault();
            event.stopPropagation();
            onClick();
        }, children: label }));
}
function TradeMetric({ label, value }) {
    return (_jsxs("div", { className: "flex items-center justify-between gap-3", children: [_jsx("span", { className: "text-xs text-slate-500", children: label }), _jsx("strong", { className: "shrink-0 whitespace-nowrap text-right text-sm text-slate-100", children: value })] }));
}
function TradeDetails({ trade }) {
    const metadata = trade.metadata ?? {};
    const candidateMetadata = readObject(metadata.candidate_metadata);
    const reasons = readStringList(metadata.reason);
    const blockedReasons = readStringList(metadata.blocked_reason);
    const triggerTypes = readStringList(candidateMetadata.trigger_types);
    const takeProfit = firstTakeProfitPrice(trade.take_profit);
    const statusNote = tradeStatusNote(trade.status);
    return (_jsxs("div", { className: "grid gap-3 text-sm", children: [_jsxs("div", { className: "grid gap-2", children: [_jsx(Detail, { label: "Playbook", value: playbookLabel(trade.playbook) }), _jsx(Detail, { label: "Side", value: trade.side }), _jsx(Detail, { label: "Status", value: trade.status }), _jsx(Detail, { label: "Backtest", value: metadata.backtest === true ? "true" : "--" })] }), statusNote ? (_jsx("div", { className: "rounded-md border border-yellow-300/25 bg-yellow-300/[0.06] p-2 text-xs leading-relaxed text-yellow-50", children: statusNote })) : null, _jsxs("div", { className: "grid gap-2 rounded-md border border-ink-700 bg-ink-950/60 p-3", children: [_jsx(TradeMetric, { label: "Entry", value: price(trade.entry_price) }), _jsx(TradeMetric, { label: "SL", value: price(trade.stop_loss) }), _jsx(TradeMetric, { label: "TP", value: price(takeProfit) }), _jsx(TradeMetric, { label: "Exit", value: price(trade.close_price) }), _jsx(TradeMetric, { label: "PnL R", value: trade.pnl_r === null ? "--" : `${trade.pnl_r.toFixed(2)}R` }), _jsx(TradeMetric, { label: "Score", value: formatUnknownNumber(metadata.score) })] }), _jsxs("div", { className: "grid gap-2", children: [_jsx(Detail, { label: "Opened", value: compactTime(trade.opened_at) }), _jsx(Detail, { label: "Closed", value: compactTime(trade.closed_at) }), _jsx(Detail, { label: "Reaction", value: String(metadata.zone_reaction_state ?? "--") }), _jsx(Detail, { label: "Zone", value: String(candidateMetadata.zone_type ?? "--") }), _jsx(Detail, { label: "Trigger", value: triggerTypes.length > 0 ? triggerTypes.join(" + ") : "--" })] }), _jsxs("div", { className: "grid gap-1", children: [_jsx("div", { className: "text-xs text-slate-500", children: "Reason" }), _jsx("div", { className: "rounded-md border border-cyan-400/25 bg-cyan-400/[0.06] p-2 text-xs leading-relaxed text-cyan-50", children: reasons.length > 0 ? (_jsx("ul", { className: "grid gap-1", children: reasons.map((reason, index) => (_jsxs("li", { children: ["\u2022 ", reason] }, `${reason}-${index}`))) })) : ("--") })] }), blockedReasons.length > 0 ? (_jsxs("div", { className: "grid gap-1", children: [_jsx("div", { className: "text-xs text-slate-500", children: "Blocked reason at signal" }), _jsx("div", { className: "rounded-md border border-rose-400/25 bg-rose-500/[0.06] p-2 text-xs leading-relaxed text-rose-50", children: _jsx("ul", { className: "grid gap-1", children: blockedReasons.map((reason, index) => (_jsxs("li", { children: ["\u2022 ", reason] }, `${reason}-${index}`))) }) })] })) : null] }));
}
function ZoneEditor({ zone, onZoneUpdated }) {
    const setSelected = useChartStore((state) => state.setSelected);
    const [priceLow, setPriceLow] = useState(String(zone.price_low));
    const [priceHigh, setPriceHigh] = useState(String(zone.price_high));
    const [weight, setWeight] = useState(String(zone.weight));
    const [confidence, setConfidence] = useState(String(zone.confidence));
    const [status, setStatus] = useState(zone.status === "disabled" ? "disabled" : "active");
    const [noExpiry, setNoExpiry] = useState(defaultNoExpiry(zone));
    const [reason, setReason] = useState("");
    const [error, setError] = useState(null);
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
        }
        catch (err) {
            setError(err instanceof Error ? err.message : "Could not save zone override.");
        }
        finally {
            setIsSaving(false);
        }
    }, [confidence, noExpiry, onZoneUpdated, priceHigh, priceLow, reason, setSelected, status, weight, zone]);
    const deleteZone = useCallback(async () => {
        if (isSaving)
            return;
        const confirmed = window.confirm(`Delete ${zoneDisplayName(zone)} zone from chart? This will hide it from chart payload.`);
        if (!confirmed)
            return;
        setIsSaving(true);
        setError(null);
        try {
            await deleteManualZone(zone.id, reason.trim() || "hotkey/manual delete");
            setSelected(null);
            onZoneUpdated();
        }
        catch (err) {
            setError(err instanceof Error ? err.message : "Could not delete zone.");
        }
        finally {
            setIsSaving(false);
        }
    }, [isSaving, onZoneUpdated, reason, setSelected, zone.id]);
    useEffect(() => {
        const onKeyDown = (event) => {
            if (isEditableTarget(event.target))
                return;
            const key = event.key.toLowerCase();
            if (key === "s") {
                event.preventDefault();
                void save();
            }
            else if (key === "d" || key === "delete" || key === "backspace") {
                event.preventDefault();
                void deleteZone();
            }
            else if (key === "escape") {
                event.preventDefault();
                setSelected(null);
            }
        };
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, [deleteZone, save, setSelected]);
    return (_jsxs("div", { className: "grid gap-3 text-sm", children: [_jsxs("div", { className: "grid gap-2", children: [_jsx(Detail, { label: "Type", value: zoneDisplayName(zone) }), _jsx(Detail, { label: "Source", value: zone.source }), _jsx(Detail, { label: "Start", value: compactTime(zone.visual_start) }), _jsx(Detail, { label: "End", value: compactTime(zone.visual_end) }), _jsx(Detail, { label: "Touches", value: String(zone.metadata.touch_count_total ?? zone.metadata.touch_count ?? "--") })] }), _jsxs("div", { className: "grid grid-cols-2 gap-2", children: [_jsx(NumberField, { label: "Low", value: priceLow, onChange: setPriceLow, step: "0.01" }), _jsx(NumberField, { label: "High", value: priceHigh, onChange: setPriceHigh, step: "0.01" }), _jsx(NumberField, { label: "Weight", value: weight, onChange: setWeight, step: "0.01", min: "0", max: "1" }), _jsx(NumberField, { label: "Confidence", value: confidence, onChange: setConfidence, step: "0.01", min: "0", max: "1" })] }), _jsxs("label", { className: "grid gap-1 text-xs text-slate-500", children: ["Status", _jsxs("select", { className: "h-9 rounded-md border border-ink-700 bg-ink-850 px-2 text-sm text-slate-100 outline-none", value: status, onChange: (event) => setStatus(event.target.value === "disabled" ? "disabled" : "active"), children: [_jsx("option", { value: "active", children: "active" }), _jsx("option", { value: "disabled", children: "disabled" })] })] }), _jsxs("label", { className: "flex items-center gap-2 text-xs text-slate-400", children: [_jsx("input", { checked: noExpiry, className: "accent-cyan-400", type: "checkbox", onChange: (event) => setNoExpiry(event.target.checked) }), "No expiry"] }), _jsxs("label", { className: "grid gap-1 text-xs text-slate-500", children: ["Reason", _jsx("textarea", { className: "min-h-16 resize-none rounded-md border border-ink-700 bg-ink-850 px-2 py-2 text-sm text-slate-100 outline-none", value: reason, onChange: (event) => setReason(event.target.value) })] }), error ? _jsx("div", { className: "rounded-md border border-rose-500/40 bg-rose-500/10 p-2 text-xs text-rose-100", children: error }) : null, _jsxs("div", { className: "grid grid-cols-3 gap-2", children: [_jsxs("button", { className: "inline-flex h-9 items-center justify-center gap-2 rounded-md border border-ink-700 bg-ink-800 text-sm text-slate-100 hover:border-slate-500", type: "button", onClick: reset, children: [_jsx(RotateCcw, { size: 14 }), "Reset"] }), _jsxs("button", { className: "inline-flex h-9 items-center justify-center gap-2 rounded-md border border-cyan-400/60 bg-cyan-400/15 text-sm font-semibold text-cyan-100 hover:bg-cyan-400/25 disabled:cursor-not-allowed disabled:opacity-50", type: "button", disabled: isSaving, onClick: save, children: [_jsx(Save, { size: 14 }), isSaving ? "Saving" : "Save"] }), _jsxs("button", { className: "inline-flex h-9 items-center justify-center gap-2 rounded-md border border-rose-400/50 bg-rose-500/10 text-sm font-semibold text-rose-100 hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50", type: "button", disabled: isSaving, title: "Delete zone (D)", onClick: deleteZone, children: [_jsx(Trash2, { size: 14 }), "Delete"] })] })] }));
}
function NumberField({ label, value, onChange, step, min, max, }) {
    return (_jsxs("label", { className: "grid gap-1 text-xs text-slate-500", children: [label, _jsx("input", { className: "h-9 min-w-0 rounded-md border border-ink-700 bg-ink-850 px-2 text-sm text-slate-100 outline-none", max: max, min: min, step: step, type: "number", value: value, onChange: (event) => onChange(event.target.value) })] }));
}
function defaultNoExpiry(zone) {
    return zone.valid_until === null && zone.metadata.human_adjusted === true;
}
function filterImportantZoneList(zones, currentPrice, lastCandleTime, maxZones, selectedZoneId) {
    const pinned = zones.filter((zone) => zone.id === selectedZoneId);
    const pinnedIds = new Set(pinned.map((zone) => zone.id));
    const ranked = zones
        .filter((zone) => !pinnedIds.has(zone.id))
        .map((zone) => ({ zone, score: zoneImportanceScore(zone, currentPrice, lastCandleTime) }))
        .sort((a, b) => b.score - a.score);
    const selectedZones = [...pinned];
    const targetCount = Math.max(maxZones, pinned.length);
    for (const candidate of ranked) {
        if (selectedZones.length >= targetCount)
            break;
        selectedZones.push(candidate.zone);
    }
    return selectedZones;
}
function isZoneTypeVisible(zone, visibility) {
    if (zone.type === "support")
        return visibility.support;
    if (zone.type === "resistance")
        return visibility.resistance;
    if (zone.type === "order_block")
        return visibility.order_block;
    if (zone.type === "fvg")
        return visibility.fvg;
    if (zone.type === "liquidity_pool")
        return visibility.liquidity_pool;
    if (zone.type === "consolidation")
        return visibility.consolidation;
    return true;
}
function zoneImportanceScore(zone, currentPrice, lastCandleTime) {
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
function isHumanZone(zone) {
    return zone.source === "human" || zone.metadata.human_created === true;
}
function zoneDisplayName(zone) {
    const kind = zone.metadata.add_entity_kind;
    if (kind === "demand_order_block")
        return "Demand OB";
    if (kind === "supply_order_block")
        return "Supply OB";
    if (kind === "bullish_fvg")
        return "Bullish FVG";
    if (kind === "bearish_fvg")
        return "Bearish FVG";
    if (kind === "buy_side_liquidity")
        return "Buy-side Liquidity";
    if (kind === "sell_side_liquidity")
        return "Sell-side Liquidity";
    if (zone.type === "order_block")
        return zone.direction === "bullish" ? "Demand OB" : "Supply OB";
    if (zone.type === "fvg")
        return zone.direction === "bullish" ? "Bullish FVG" : "Bearish FVG";
    if (zone.type === "liquidity_pool")
        return "Liquidity Pool";
    return zone.type;
}
function zoneTitleClass(zone) {
    if (zone.type === "order_block") {
        return zone.direction === "bullish" ? "font-semibold text-cyan-300" : "font-semibold text-fuchsia-300";
    }
    if (zone.type === "fvg") {
        return zone.direction === "bullish" ? "font-semibold text-lime-300" : "font-semibold text-orange-300";
    }
    if (zone.type === "consolidation")
        return "font-semibold text-sky-300";
    if (zone.type === "liquidity_pool")
        return "font-semibold text-yellow-300";
    return zone.direction === "bullish" ? "font-semibold text-emerald-300" : "font-semibold text-rose-300";
}
function statusLabel(status) {
    if (status === "waiting")
        return "Waiting";
    if (status === "watching")
        return "Watching";
    if (status === "eligible")
        return "Eligible";
    if (status === "blocked")
        return "Blocked";
    return status;
}
function setupCardClass(status) {
    if (status === "eligible")
        return "border-cyan-400/70 bg-cyan-400/10 hover:bg-cyan-400/15";
    if (status === "waiting_confirmation")
        return "border-yellow-300/50 bg-yellow-300/[0.07] hover:bg-yellow-300/[0.12]";
    if (status === "watching")
        return "border-slate-600 bg-ink-850 hover:border-slate-500";
    if (status === "blocked")
        return "border-rose-500/30 bg-rose-500/[0.05] opacity-80 hover:opacity-100";
    return "border-ink-700 bg-ink-850";
}
function playbookLabel(value) {
    return value
        .split("_")
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ");
}
function toggleSetValue(current, value) {
    const next = new Set(current);
    if (next.has(value)) {
        next.delete(value);
    }
    else {
        next.add(value);
    }
    return next;
}
function addSetValue(current, value) {
    const next = new Set(current);
    next.add(value);
    return next;
}
function readObject(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}
function readStringList(value) {
    if (!Array.isArray(value))
        return [];
    return value.filter((item) => typeof item === "string" && item.length > 0);
}
function firstTakeProfitPrice(values) {
    const first = values.at(0);
    if (typeof first === "number")
        return first;
    if (first && typeof first.price === "number")
        return first.price;
    return null;
}
function formatUnknownNumber(value) {
    return typeof value === "number" ? value.toFixed(2) : "--";
}
function tradeStatusNote(status) {
    if (status === "time_exit") {
        return "Time exit: lệnh chưa chạm SL/TP trong thời gian giữ tối đa của backtest, nên bị đóng ở close của nến hết hạn. Nếu giá chạm TP sau thời điểm Closed thì backtest không tính TP đó.";
    }
    if (status === "target_hit")
        return "Target hit: giá đã chạm TP trong thời gian giữ lệnh.";
    if (status === "stopped")
        return "Stopped: giá đã chạm SL trong thời gian giữ lệnh.";
    return null;
}
function isEditableTarget(target) {
    if (!(target instanceof HTMLElement))
        return false;
    const tagName = target.tagName.toLowerCase();
    return tagName === "input" || tagName === "textarea" || tagName === "select" || target.isContentEditable;
}
function formatZoneDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime()))
        return "--";
    return `${String(date.getDate()).padStart(2, "0")}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}
function Detail({ label, value }) {
    return (_jsxs("div", { className: "grid grid-cols-[96px_minmax(0,1fr)] gap-3", children: [_jsx("span", { className: "text-slate-500", children: label }), _jsx("strong", { className: "min-w-0 break-words text-slate-100", children: value })] }));
}
