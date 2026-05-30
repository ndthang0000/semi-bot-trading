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
export declare const useChartStore: import("zustand").UseBoundStore<import("zustand").StoreApi<ChartState>>;
export {};
