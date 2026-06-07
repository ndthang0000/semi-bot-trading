import { create } from "zustand";
import { persist } from "zustand/middleware";
export const defaultZoneTypeVisibility = {
    support: true,
    resistance: true,
    order_block: true,
    fvg: true,
    liquidity_pool: true,
    consolidation: true,
};
export const defaultSelectedPlaybooks = ["trend_pullback"];
export const playbookLayerRequirements = {
    trend_pullback: { zones: ["support", "resistance", "order_block", "fvg"], structure: true },
    zone_reaction_v2: { zones: ["support", "resistance", "fvg"], structure: true },
    ob_mitigation_continuation: { zones: ["order_block"], structure: true },
    fvg_fill_go: { zones: ["fvg"], structure: true },
    breakout_retest: { zones: ["consolidation"], structure: true },
    momentum_expansion_continuation: { zones: ["support", "resistance", "order_block", "fvg"], structure: true },
    range_boundary_reversal: { zones: ["consolidation", "support", "resistance"], structure: true },
    liquidity_sweep_reversal: { zones: ["liquidity_pool", "support", "resistance"], structure: true },
    failed_breakout_trap: { zones: ["consolidation"], structure: true },
};
export const useChartStore = create()(persist((set) => ({
    symbol: "XAUUSD",
    timeframe: "H1",
    limit: 300,
    startIndex: null,
    activeZonesOnly: false,
    showZones: true,
    zoneTypeVisibility: defaultZoneTypeVisibility,
    showStructure: true,
    importantZonesOnly: true,
    maxVisibleZones: 8,
    selectedPlaybooks: defaultSelectedPlaybooks,
    addEntityKind: null,
    selected: null,
    zoneFocusRequest: null,
    tradeFocusRequest: null,
    setTimeframe: (timeframe) => set({ timeframe, selected: null }),
    setLimit: (limit) => set({ limit: Math.min(Math.max(limit, 1), 15000) }),
    setStartIndex: (startIndex) => set({ startIndex: startIndex === null ? null : Math.max(0, Math.floor(startIndex)), selected: null }),
    shiftStartIndex: (delta) => set((state) => ({
        startIndex: Math.max(0, (state.startIndex ?? 0) + delta),
        selected: null,
    })),
    setActiveZonesOnly: (activeZonesOnly) => set({ activeZonesOnly }),
    setShowZones: (showZones) => set((state) => ({
        showZones: requiredZoneTypesForPlaybooks(state.selectedPlaybooks).size > 0 ? true : showZones,
    })),
    setZoneTypeVisible: (zoneType, visible) => set((state) => ({
        zoneTypeVisibility: {
            ...state.zoneTypeVisibility,
            [zoneType]: requiredZoneTypesForPlaybooks(state.selectedPlaybooks).has(zoneType) ? true : visible,
        },
        showZones: visible ? true : state.showZones,
    })),
    setAllZoneTypesVisible: (visible) => set((state) => {
        const requiredZoneTypes = requiredZoneTypesForPlaybooks(state.selectedPlaybooks);
        return {
            zoneTypeVisibility: {
                support: visible,
                resistance: visible,
                order_block: visible,
                fvg: visible,
                liquidity_pool: visible,
                consolidation: visible,
                ...Object.fromEntries(Array.from(requiredZoneTypes).map((zoneType) => [zoneType, true])),
            },
            showZones: visible || requiredZoneTypes.size > 0,
        };
    }),
    setShowStructure: (showStructure) => set((state) => ({
        showStructure: requiresStructureForPlaybooks(state.selectedPlaybooks) ? true : showStructure,
    })),
    setImportantZonesOnly: (importantZonesOnly) => set({ importantZonesOnly }),
    setMaxVisibleZones: (maxVisibleZones) => set({ maxVisibleZones: Math.min(Math.max(maxVisibleZones, 1), 40) }),
    setSelectedPlaybooks: (selectedPlaybooks) => set((state) => applyPlaybookLayerRequirements({ ...state, selectedPlaybooks: uniquePlaybooks(selectedPlaybooks) })),
    toggleSelectedPlaybook: (playbook, enabled) => set((state) => {
        const selectedPlaybooks = enabled
            ? uniquePlaybooks([...state.selectedPlaybooks, playbook])
            : state.selectedPlaybooks.filter((item) => item !== playbook);
        return applyPlaybookLayerRequirements({ ...state, selectedPlaybooks });
    }),
    setAddEntityKind: (addEntityKind) => set({ addEntityKind, selected: null }),
    setSelected: (selected) => set({ selected }),
    focusZone: (zone) => set((state) => ({
        zoneFocusRequest: {
            id: (state.zoneFocusRequest?.id ?? 0) + 1,
            zone,
        },
    })),
    focusTrade: (trade) => set((state) => ({
        tradeFocusRequest: {
            id: (state.tradeFocusRequest?.id ?? 0) + 1,
            trade,
        },
    })),
}), {
    name: "semi-bot-chart-layer-settings",
    partialize: (state) => ({
        activeZonesOnly: state.activeZonesOnly,
        showZones: state.showZones,
        zoneTypeVisibility: state.zoneTypeVisibility,
        showStructure: state.showStructure,
        importantZonesOnly: state.importantZonesOnly,
        maxVisibleZones: state.maxVisibleZones,
        selectedPlaybooks: state.selectedPlaybooks,
        startIndex: state.startIndex,
    }),
    merge: (persisted, current) => {
        const layerSettings = persisted;
        const selectedPlaybooks = uniquePlaybooks(layerSettings?.selectedPlaybooks ?? current.selectedPlaybooks);
        const merged = {
            ...current,
            ...layerSettings,
            selectedPlaybooks,
            zoneTypeVisibility: {
                ...defaultZoneTypeVisibility,
                ...(layerSettings?.zoneTypeVisibility ?? {}),
            },
            maxVisibleZones: Math.min(Math.max(Number(layerSettings?.maxVisibleZones ?? current.maxVisibleZones), 1), 40),
            startIndex: layerSettings?.startIndex === null || layerSettings?.startIndex === undefined
                ? null
                : Math.max(0, Math.floor(Number(layerSettings.startIndex) || 0)),
            selected: null,
            addEntityKind: null,
            zoneFocusRequest: null,
            tradeFocusRequest: null,
        };
        return {
            ...merged,
            ...applyPlaybookLayerRequirements(merged),
        };
    },
}));
function applyPlaybookLayerRequirements(state) {
    const requiredZoneTypes = requiredZoneTypesForPlaybooks(state.selectedPlaybooks);
    const requiresStructure = requiresStructureForPlaybooks(state.selectedPlaybooks);
    if (requiredZoneTypes.size === 0 && !requiresStructure) {
        return {
            selectedPlaybooks: state.selectedPlaybooks,
        };
    }
    const zoneTypeVisibility = { ...state.zoneTypeVisibility };
    requiredZoneTypes.forEach((zoneType) => {
        zoneTypeVisibility[zoneType] = true;
    });
    return {
        selectedPlaybooks: state.selectedPlaybooks,
        showZones: requiredZoneTypes.size > 0 ? true : state.showZones,
        zoneTypeVisibility,
        showStructure: requiresStructure ? true : state.showStructure,
    };
}
function uniquePlaybooks(playbooks) {
    return Array.from(new Set(playbooks)).filter((playbook) => playbook in playbookLayerRequirements);
}
function requiredZoneTypesForPlaybooks(playbooks) {
    const requiredZoneTypes = new Set();
    for (const playbook of playbooks) {
        playbookLayerRequirements[playbook].zones.forEach((zoneType) => requiredZoneTypes.add(zoneType));
    }
    return requiredZoneTypes;
}
function requiresStructureForPlaybooks(playbooks) {
    return playbooks.some((playbook) => playbookLayerRequirements[playbook].structure);
}
