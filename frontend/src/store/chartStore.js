import { create } from "zustand";
export const useChartStore = create((set) => ({
    symbol: "XAUUSD",
    timeframe: "H1",
    limit: 300,
    activeZonesOnly: false,
    showZones: true,
    showStructure: true,
    selected: null,
    setTimeframe: (timeframe) => set({ timeframe, selected: null }),
    setLimit: (limit) => set({ limit }),
    setActiveZonesOnly: (activeZonesOnly) => set({ activeZonesOnly }),
    setShowZones: (showZones) => set({ showZones }),
    setShowStructure: (showStructure) => set({ showStructure }),
    setSelected: (selected) => set({ selected }),
}));
