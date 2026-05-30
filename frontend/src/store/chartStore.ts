import { create } from "zustand";
import type { SelectedEntity, Timeframe } from "../types";

type ChartState = {
  symbol: string;
  timeframe: Timeframe;
  limit: number;
  activeZonesOnly: boolean;
  showZones: boolean;
  showStructure: boolean;
  selected: SelectedEntity | null;
  setTimeframe: (timeframe: Timeframe) => void;
  setLimit: (limit: number) => void;
  setActiveZonesOnly: (activeZonesOnly: boolean) => void;
  setShowZones: (showZones: boolean) => void;
  setShowStructure: (showStructure: boolean) => void;
  setSelected: (selected: SelectedEntity | null) => void;
};

export const useChartStore = create<ChartState>((set) => ({
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
