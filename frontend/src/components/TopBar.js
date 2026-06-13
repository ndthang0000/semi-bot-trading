import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Activity, ChevronDown, ChevronLeft, ChevronRight, Eye, Layers, Pause, Play, Plus, RefreshCw, Rows3, Target, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { playbookLayerRequirements, useChartStore } from "../store/chartStore";
export function TopBar({ isFetching, mode, onRefresh }) {
    const timeframe = useChartStore((state) => state.timeframe);
    const limit = useChartStore((state) => state.limit);
    const startIndex = useChartStore((state) => state.startIndex);
    const autoRefreshEnabled = useChartStore((state) => state.autoRefreshEnabled);
    const addEntityKind = useChartStore((state) => state.addEntityKind);
    const setTimeframe = useChartStore((state) => state.setTimeframe);
    const setLimit = useChartStore((state) => state.setLimit);
    const setStartIndex = useChartStore((state) => state.setStartIndex);
    const shiftStartIndex = useChartStore((state) => state.shiftStartIndex);
    const setAutoRefreshEnabled = useChartStore((state) => state.setAutoRefreshEnabled);
    const setAddEntityKind = useChartStore((state) => state.setAddEntityKind);
    const autoRefreshActive = mode === "dashboard" && autoRefreshEnabled && startIndex === null;
    return (_jsxs("header", { className: "flex h-14 items-center justify-between gap-4 border-b border-ink-700 bg-ink-900 px-4", children: [_jsxs("div", { className: "flex items-center gap-3 font-semibold text-slate-100", children: [_jsx("span", { className: "flex h-8 w-8 items-center justify-center rounded-md border border-slate-700 bg-ink-800 text-cyan-300", children: _jsx(Activity, { size: 18 }) }), _jsx("span", { className: "whitespace-nowrap", children: "XAUUSD Control" })] }), _jsxs("div", { className: "flex min-w-0 items-center gap-2", children: [_jsxs("div", { className: "flex h-9 items-center overflow-hidden rounded-md border border-ink-700 bg-ink-850", children: [_jsx("span", { className: "flex h-full items-center px-2 text-cyan-300", children: _jsx(Plus, { size: 15 }) }), _jsxs("select", { className: "h-full min-w-[150px] bg-transparent pr-2 text-sm text-slate-100 outline-none", title: "Add entity: select a type, then drag a box on the chart", value: addEntityKind ?? "", onChange: (event) => setAddEntityKind((event.target.value || null)), children: [_jsx("option", { value: "", children: "Add entity" }), _jsx("option", { value: "support", children: "Support" }), _jsx("option", { value: "resistance", children: "Resistance" }), _jsx("option", { value: "demand_order_block", children: "Demand OB" }), _jsx("option", { value: "supply_order_block", children: "Supply OB" }), _jsx("option", { value: "bullish_fvg", children: "Bullish FVG" }), _jsx("option", { value: "bearish_fvg", children: "Bearish FVG" }), _jsx("option", { value: "consolidation", children: "Consolidation" }), _jsx("option", { value: "buy_side_liquidity", children: "Buy-side Liq" }), _jsx("option", { value: "sell_side_liquidity", children: "Sell-side Liq" })] }), addEntityKind ? (_jsx("button", { className: "flex h-full w-8 items-center justify-center border-l border-ink-700 text-slate-400 hover:text-slate-100", title: "Cancel add mode", type: "button", onClick: () => setAddEntityKind(null), children: _jsx(X, { size: 14 }) })) : null] }), _jsxs("nav", { className: "flex items-center rounded-md border border-ink-700 bg-ink-850 p-0.5 text-sm", children: [_jsx("a", { className: `rounded px-3 py-1.5 transition ${mode === "dashboard" ? "bg-cyan-400/15 font-semibold text-cyan-100" : "text-slate-400 hover:text-slate-100"}`, href: "/", children: "Realtime" }), _jsx("a", { className: `rounded px-3 py-1.5 transition ${mode === "replay" ? "bg-cyan-400/15 font-semibold text-cyan-100" : "text-slate-400 hover:text-slate-100"}`, href: "/replay-chart", children: "Replay" })] }), _jsxs("select", { className: "h-9 rounded-md border border-ink-700 bg-ink-850 px-3 text-sm text-slate-100 outline-none", value: timeframe, onChange: (event) => setTimeframe(event.target.value), children: [_jsx("option", { value: "M15", children: "M15" }), _jsx("option", { value: "H1", children: "H1" })] }), _jsx("input", { className: "h-9 w-24 rounded-md border border-ink-700 bg-ink-850 px-3 text-sm text-slate-100 outline-none", min: 50, max: 15000, step: 50, type: "number", value: limit, onChange: (event) => setLimit(Number(event.target.value)) }), _jsx(WindowMenu, { limit: limit, startIndex: startIndex, onLatest: () => setStartIndex(null), onFirst: () => setStartIndex(0), onShift: shiftStartIndex, onStartIndexChange: setStartIndex }), _jsx(PlaybookMenu, {}), _jsx(LayerMenu, {}), _jsxs("button", { className: `inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm transition ${autoRefreshActive
                            ? "border-cyan-500/60 bg-cyan-400/10 text-cyan-100"
                            : "border-ink-700 bg-ink-800 text-slate-300 hover:border-cyan-500"}`, title: startIndex === null ? "Toggle auto refresh every 60 seconds" : "Auto refresh is paused while viewing historical windows", type: "button", onClick: () => setAutoRefreshEnabled(!autoRefreshEnabled), children: [autoRefreshEnabled ? _jsx(Pause, { size: 15 }) : _jsx(Play, { size: 15 }), _jsx("span", { children: autoRefreshEnabled ? "Auto 60s" : "Manual" }), autoRefreshEnabled && startIndex !== null ? _jsx("span", { className: "text-[11px] text-slate-500", children: "paused" }) : null] }), _jsxs("button", { className: "inline-flex h-9 items-center gap-2 rounded-md border border-ink-700 bg-ink-800 px-3 text-sm text-slate-100 hover:border-cyan-500", type: "button", onClick: onRefresh, children: [_jsx(RefreshCw, { className: isFetching ? "animate-spin" : "", size: 15 }), "Reload"] })] })] }));
}
function WindowMenu({ limit, startIndex, onLatest, onFirst, onShift, onStartIndexChange }) {
    const [open, setOpen] = useState(false);
    const menuRef = useRef(null);
    useEffect(() => {
        if (!open)
            return;
        const onPointerDown = (event) => {
            if (!menuRef.current?.contains(event.target)) {
                setOpen(false);
            }
        };
        window.addEventListener("pointerdown", onPointerDown);
        return () => window.removeEventListener("pointerdown", onPointerDown);
    }, [open]);
    return (_jsxs("div", { ref: menuRef, className: "relative", children: [_jsxs("button", { className: `inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm transition ${open ? "border-cyan-400/70 bg-cyan-400/10 text-cyan-100" : "border-ink-700 bg-ink-800 text-slate-100 hover:border-cyan-500"}`, title: "Candle window", type: "button", onClick: () => setOpen((value) => !value), children: [_jsx(Rows3, { size: 15 }), _jsx("span", { children: startIndex === null ? "Latest" : `Start ${startIndex}` }), _jsx(ChevronDown, { className: open ? "rotate-180 transition" : "transition", size: 14 })] }), open ? (_jsxs("div", { className: "absolute right-0 top-11 z-50 w-72 rounded-md border border-ink-700 bg-ink-900 p-3 text-sm text-slate-200 shadow-2xl shadow-black/40", children: [_jsxs("div", { className: "mb-3 flex items-center justify-between", children: [_jsxs("div", { className: "flex items-center gap-2 font-semibold text-slate-100", children: [_jsx(Rows3, { size: 15, className: "text-cyan-300" }), "Candle window"] }), _jsxs("span", { className: "text-xs text-slate-500", children: ["limit ", limit] })] }), _jsxs("label", { className: "grid gap-1 text-xs text-slate-500", children: ["Start index", _jsx("input", { className: "h-9 rounded-md border border-ink-700 bg-ink-850 px-3 text-sm text-slate-100 outline-none placeholder:text-slate-600", min: 0, placeholder: "latest", title: "Blank = latest candles, 0 = first candle window", type: "number", value: startIndex ?? "", onChange: (event) => {
                                    const value = event.target.value.trim();
                                    onStartIndexChange(value === "" ? null : Number(value));
                                } })] }), _jsxs("div", { className: "mt-3 grid grid-cols-2 gap-2", children: [_jsxs("button", { className: "inline-flex h-9 items-center justify-center gap-1 rounded-md border border-ink-700 bg-ink-850 text-slate-200 hover:border-cyan-500 disabled:cursor-not-allowed disabled:opacity-40", disabled: startIndex === null || startIndex <= 0, type: "button", onClick: () => onShift(-limit), children: [_jsx(ChevronLeft, { size: 15 }), "Prev"] }), _jsxs("button", { className: "inline-flex h-9 items-center justify-center gap-1 rounded-md border border-ink-700 bg-ink-850 text-slate-200 hover:border-cyan-500", type: "button", onClick: () => onShift(limit), children: ["Next", _jsx(ChevronRight, { size: 15 })] }), _jsx("button", { className: "h-9 rounded-md border border-ink-700 bg-ink-850 text-slate-200 hover:border-cyan-500", type: "button", onClick: onFirst, children: "First" }), _jsx("button", { className: "h-9 rounded-md border border-ink-700 bg-ink-850 text-slate-200 hover:border-cyan-500", type: "button", onClick: onLatest, children: "Latest" })] })] })) : null] }));
}
function PlaybookMenu() {
    const [open, setOpen] = useState(false);
    const menuRef = useRef(null);
    const selectedPlaybooks = useChartStore((state) => state.selectedPlaybooks);
    const toggleSelectedPlaybook = useChartStore((state) => state.toggleSelectedPlaybook);
    useEffect(() => {
        if (!open)
            return;
        const onPointerDown = (event) => {
            if (!menuRef.current?.contains(event.target)) {
                setOpen(false);
            }
        };
        window.addEventListener("pointerdown", onPointerDown);
        return () => window.removeEventListener("pointerdown", onPointerDown);
    }, [open]);
    return (_jsxs("div", { ref: menuRef, className: "relative", children: [_jsxs("button", { className: `inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm transition ${open ? "border-cyan-400/70 bg-cyan-400/10 text-cyan-100" : "border-ink-700 bg-ink-800 text-slate-100 hover:border-cyan-500"}`, type: "button", onClick: () => setOpen((value) => !value), children: [_jsx(Target, { size: 15 }), "Playbooks", _jsx("span", { className: "rounded bg-ink-950 px-1.5 py-0.5 text-[11px] text-slate-400", children: selectedPlaybooks.length }), _jsx(ChevronDown, { className: open ? "rotate-180 transition" : "transition", size: 14 })] }), open ? (_jsxs("div", { className: "absolute right-0 top-11 z-50 w-80 rounded-md border border-ink-700 bg-ink-900 p-3 text-sm text-slate-200 shadow-2xl shadow-black/40", children: [_jsxs("div", { className: "mb-2 flex items-center justify-between", children: [_jsxs("div", { className: "flex items-center gap-2 font-semibold text-slate-100", children: [_jsx(Target, { size: 15, className: "text-cyan-300" }), "Running playbooks"] }), _jsx("span", { className: "text-xs text-cyan-200", children: "Auto layers" })] }), _jsx("div", { className: "grid gap-1", children: PLAYBOOK_ITEMS.map((item) => (_jsxs("label", { className: "grid cursor-pointer gap-0.5 rounded px-1.5 py-1.5 hover:bg-ink-800/70", children: [_jsxs("span", { className: "flex items-center gap-2", children: [_jsx("input", { checked: selectedPlaybooks.includes(item.key), className: "accent-cyan-400", onChange: (event) => toggleSelectedPlaybook(item.key, event.target.checked), type: "checkbox" }), _jsx("span", { className: "font-medium text-slate-100", children: item.label })] }), _jsx("span", { className: "pl-6 text-[11px] text-slate-500", children: playbookRequirementLabel(item.key) })] }, item.key))) })] })) : null] }));
}
function LayerMenu() {
    const [open, setOpen] = useState(false);
    const menuRef = useRef(null);
    const activeZonesOnly = useChartStore((state) => state.activeZonesOnly);
    const showZones = useChartStore((state) => state.showZones);
    const zoneTypeVisibility = useChartStore((state) => state.zoneTypeVisibility);
    const showStructure = useChartStore((state) => state.showStructure);
    const importantZonesOnly = useChartStore((state) => state.importantZonesOnly);
    const maxVisibleZones = useChartStore((state) => state.maxVisibleZones);
    const setActiveZonesOnly = useChartStore((state) => state.setActiveZonesOnly);
    const setShowZones = useChartStore((state) => state.setShowZones);
    const setZoneTypeVisible = useChartStore((state) => state.setZoneTypeVisible);
    const setAllZoneTypesVisible = useChartStore((state) => state.setAllZoneTypesVisible);
    const setShowStructure = useChartStore((state) => state.setShowStructure);
    const setImportantZonesOnly = useChartStore((state) => state.setImportantZonesOnly);
    const setMaxVisibleZones = useChartStore((state) => state.setMaxVisibleZones);
    useEffect(() => {
        if (!open)
            return;
        const onPointerDown = (event) => {
            if (!menuRef.current?.contains(event.target)) {
                setOpen(false);
            }
        };
        window.addEventListener("pointerdown", onPointerDown);
        return () => window.removeEventListener("pointerdown", onPointerDown);
    }, [open]);
    const visibleZoneCount = Object.values(zoneTypeVisibility).filter(Boolean).length;
    const totalVisibleCount = visibleZoneCount + (showStructure ? 1 : 0);
    const allZonesVisible = visibleZoneCount === LAYER_ITEMS.length;
    return (_jsxs("div", { ref: menuRef, className: "relative", children: [_jsxs("button", { className: `inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm transition ${open ? "border-cyan-400/70 bg-cyan-400/10 text-cyan-100" : "border-ink-700 bg-ink-800 text-slate-100 hover:border-cyan-500"}`, type: "button", onClick: () => setOpen((value) => !value), children: [_jsx(Layers, { size: 15 }), "Layers", _jsx("span", { className: "rounded bg-ink-950 px-1.5 py-0.5 text-[11px] text-slate-400", children: totalVisibleCount }), _jsx(ChevronDown, { className: open ? "rotate-180 transition" : "transition", size: 14 })] }), open ? (_jsxs("div", { className: "absolute right-0 top-11 z-50 w-72 rounded-md border border-ink-700 bg-ink-900 p-3 text-sm text-slate-200 shadow-2xl shadow-black/40", children: [_jsxs("div", { className: "mb-2 flex items-center justify-between", children: [_jsxs("div", { className: "flex items-center gap-2 font-semibold text-slate-100", children: [_jsx(Eye, { size: 15, className: "text-cyan-300" }), "Visible layers"] }), _jsx("button", { className: "text-xs text-cyan-200 hover:text-cyan-100", type: "button", onClick: () => setAllZoneTypesVisible(!allZonesVisible), children: allZonesVisible ? "Hide zones" : "Show zones" })] }), _jsxs("div", { className: "grid gap-1", children: [_jsx(MenuCheck, { checked: activeZonesOnly, label: "Active zones only", onChange: setActiveZonesOnly }), _jsxs("div", { className: "flex items-center gap-2 rounded px-1.5 py-1 text-slate-300", children: [_jsx("input", { checked: importantZonesOnly, className: "accent-cyan-400", type: "checkbox", onChange: (event) => setImportantZonesOnly(event.target.checked) }), _jsx("span", { className: "flex-1", children: "Important zones" }), _jsx("input", { className: "h-7 w-14 rounded border border-ink-700 bg-ink-850 px-2 text-xs text-slate-100 outline-none", max: 40, min: 1, title: "Max visible zones when Important is enabled", type: "number", value: maxVisibleZones, onChange: (event) => setMaxVisibleZones(Number(event.target.value)) })] })] }), _jsx("div", { className: "my-2 h-px bg-ink-700" }), _jsxs("div", { className: "grid gap-1", children: [_jsx(MenuCheck, { checked: showZones, label: "All price zones", onChange: setShowZones }), LAYER_ITEMS.map((item) => (_jsx(MenuCheck, { checked: zoneTypeVisibility[item.key], colorClass: item.colorClass, disabled: !showZones, label: item.label, onChange: (checked) => setZoneTypeVisible(item.key, checked) }, item.key))), _jsx(MenuCheck, { checked: showStructure, colorClass: "bg-blue-400", label: "Structure + ZigZag", onChange: setShowStructure })] })] })) : null] }));
}
function MenuCheck({ checked, colorClass, disabled = false, label, onChange, }) {
    return (_jsxs("label", { className: `flex items-center gap-2 rounded px-1.5 py-1 ${disabled ? "opacity-40" : "hover:bg-ink-800"}`, children: [_jsx("input", { checked: checked, className: "accent-cyan-400", disabled: disabled, type: "checkbox", onChange: (event) => onChange(event.target.checked) }), colorClass ? _jsx("span", { className: `h-2.5 w-2.5 rounded-full ${colorClass}` }) : null, _jsx("span", { children: label })] }));
}
const LAYER_ITEMS = [
    { key: "support", label: "Support", colorClass: "bg-emerald-400" },
    { key: "resistance", label: "Resistance", colorClass: "bg-rose-400" },
    { key: "order_block", label: "Order Blocks", colorClass: "bg-cyan-300" },
    { key: "fvg", label: "Fair Value Gaps", colorClass: "bg-lime-300" },
    { key: "liquidity_pool", label: "Liquidity Pools", colorClass: "bg-yellow-300" },
    { key: "consolidation", label: "Consolidation", colorClass: "bg-sky-300" },
];
const PLAYBOOK_ITEMS = [
    { key: "zone_reaction_v2", label: "Zone Reaction V2" },
    { key: "sr_breakout_v1", label: "SR Breakout V1" },
];
function playbookRequirementLabel(playbook) {
    const labels = {
        support: "Support",
        resistance: "Resistance",
        order_block: "OB",
        fvg: "FVG",
        liquidity_pool: "Liquidity",
        consolidation: "Consolidation",
    };
    const requirements = playbookLayerRequirements[playbook];
    const zoneLabels = requirements.zones.map((zoneType) => labels[zoneType]).join(", ");
    return `Layers: ${zoneLabels}${requirements.structure ? " + Structure" : ""}`;
}
