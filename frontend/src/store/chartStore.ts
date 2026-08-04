import { create } from "zustand";
import { persist } from "zustand/middleware";
import type {
  AddEntityKind,
  PlaybookKey,
  PriceZone,
  SelectedEntity,
  TradeOrder,
  TradeFocusRequest,
  TradeVisibilityMode,
  Timeframe,
  ZoneFocusRequest,
  ZoneTypeVisibility,
  ZoneVisibilityKey,
} from "../types";

export const defaultZoneTypeVisibility: ZoneTypeVisibility = {
  support: true,
  resistance: true,
  order_block: true,
  fvg: true,
  liquidity_pool: true,
  consolidation: true,
};

export const defaultSelectedPlaybooks: PlaybookKey[] = ["zone_reaction_v2"];

export const playbookLayerRequirements: Record<PlaybookKey, { zones: ZoneVisibilityKey[]; structure: boolean }> = {
  zone_reaction_v2: { zones: ["support", "resistance", "fvg"], structure: true },
  sr_breakout_v1: { zones: ["support", "resistance"], structure: true },
  liquidity_sweep_reclaim_v1: { zones: ["liquidity_pool"], structure: true },
};

type ChartState = {
  symbol: string;
  timeframe: Timeframe;
  limit: number;
  startIndex: number | null;
  activeZonesOnly: boolean;
  showZones: boolean;
  zoneTypeVisibility: ZoneTypeVisibility;
  showStructure: boolean;
  tradeVisibilityMode: TradeVisibilityMode;
  importantZonesOnly: boolean;
  maxVisibleZones: number;
  autoRefreshEnabled: boolean;
  selectedPlaybooks: PlaybookKey[];
  addEntityKind: AddEntityKind | null;
  selected: SelectedEntity | null;
  zoneFocusRequest: ZoneFocusRequest | null;
  tradeFocusRequest: TradeFocusRequest | null;
  setTimeframe: (timeframe: Timeframe) => void;
  setLimit: (limit: number) => void;
  setStartIndex: (startIndex: number | null) => void;
  shiftStartIndex: (delta: number) => void;
  setActiveZonesOnly: (activeZonesOnly: boolean) => void;
  setShowZones: (showZones: boolean) => void;
  setZoneTypeVisible: (zoneType: ZoneVisibilityKey, visible: boolean) => void;
  setAllZoneTypesVisible: (visible: boolean) => void;
  setShowStructure: (showStructure: boolean) => void;
  setTradeVisibilityMode: (mode: TradeVisibilityMode) => void;
  setImportantZonesOnly: (importantZonesOnly: boolean) => void;
  setMaxVisibleZones: (maxVisibleZones: number) => void;
  setAutoRefreshEnabled: (autoRefreshEnabled: boolean) => void;
  setSelectedPlaybooks: (playbooks: PlaybookKey[]) => void;
  toggleSelectedPlaybook: (playbook: PlaybookKey, enabled: boolean) => void;
  setAddEntityKind: (kind: AddEntityKind | null) => void;
  setSelected: (selected: SelectedEntity | null) => void;
  focusZone: (zone: PriceZone) => void;
  focusTrade: (trade: TradeOrder) => void;
};

export const useChartStore = create<ChartState>()(
  persist(
    (set) => ({
      symbol: "XAUUSD",
      timeframe: "H1",
      limit: 300,
      startIndex: null,
      activeZonesOnly: false,
      showZones: true,
      zoneTypeVisibility: defaultZoneTypeVisibility,
      showStructure: true,
      tradeVisibilityMode: "visible",
      importantZonesOnly: true,
      maxVisibleZones: 8,
      autoRefreshEnabled: true,
      selectedPlaybooks: defaultSelectedPlaybooks,
      addEntityKind: null,
      selected: null,
      zoneFocusRequest: null,
      tradeFocusRequest: null,
      // Manual zone drawing is H1-only (the API rejects M15 zone creation), so
      // leaving H1 must cancel any in-progress "add entity" draw mode.
      setTimeframe: (timeframe) =>
        set((state) => ({ timeframe, selected: null, addEntityKind: timeframe === "H1" ? state.addEntityKind : null })),
      setLimit: (limit) => set({ limit: Math.min(Math.max(limit, 1), 15000) }),
      setStartIndex: (startIndex) => set({ startIndex: startIndex === null ? null : Math.max(0, Math.floor(startIndex)), selected: null }),
      shiftStartIndex: (delta) =>
        set((state) => ({
          startIndex: Math.max(0, (state.startIndex ?? 0) + delta),
          selected: null,
        })),
      setActiveZonesOnly: (activeZonesOnly) => set({ activeZonesOnly }),
      setShowZones: (showZones) =>
        set((state) => ({
          showZones: requiredZoneTypesForPlaybooks(state.selectedPlaybooks).size > 0 ? true : showZones,
        })),
      setZoneTypeVisible: (zoneType, visible) =>
        set((state) => ({
          zoneTypeVisibility: {
            ...state.zoneTypeVisibility,
            [zoneType]: requiredZoneTypesForPlaybooks(state.selectedPlaybooks).has(zoneType) ? true : visible,
          },
          showZones: visible ? true : state.showZones,
        })),
      setAllZoneTypesVisible: (visible) =>
        set((state) => {
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
      setShowStructure: (showStructure) =>
        set((state) => ({
          showStructure: requiresStructureForPlaybooks(state.selectedPlaybooks) ? true : showStructure,
        })),
      setTradeVisibilityMode: (tradeVisibilityMode) => set({ tradeVisibilityMode }),
      setImportantZonesOnly: (importantZonesOnly) => set({ importantZonesOnly }),
      setMaxVisibleZones: (maxVisibleZones) => set({ maxVisibleZones: Math.min(Math.max(maxVisibleZones, 1), 40) }),
      setAutoRefreshEnabled: (autoRefreshEnabled) => set({ autoRefreshEnabled }),
      setSelectedPlaybooks: (selectedPlaybooks) =>
        set((state) => applyPlaybookLayerRequirements({ ...state, selectedPlaybooks: uniquePlaybooks(selectedPlaybooks) })),
      toggleSelectedPlaybook: (playbook, enabled) =>
        set((state) => {
          const selectedPlaybooks = enabled
            ? uniquePlaybooks([...state.selectedPlaybooks, playbook])
            : state.selectedPlaybooks.filter((item) => item !== playbook);
          return applyPlaybookLayerRequirements({ ...state, selectedPlaybooks });
        }),
      setAddEntityKind: (addEntityKind) => set({ addEntityKind, selected: null }),
      setSelected: (selected) => set({ selected }),
      focusZone: (zone) =>
        set((state) => ({
          zoneFocusRequest: {
            id: (state.zoneFocusRequest?.id ?? 0) + 1,
            zone,
          },
        })),
      focusTrade: (trade) =>
        set((state) => ({
          tradeFocusRequest: {
            id: (state.tradeFocusRequest?.id ?? 0) + 1,
            trade,
          },
        })),
    }),
    {
      name: "semi-bot-chart-layer-settings",
      partialize: (state) => ({
        activeZonesOnly: state.activeZonesOnly,
        showZones: state.showZones,
        zoneTypeVisibility: state.zoneTypeVisibility,
        showStructure: state.showStructure,
        tradeVisibilityMode: state.tradeVisibilityMode,
        importantZonesOnly: state.importantZonesOnly,
        maxVisibleZones: state.maxVisibleZones,
        autoRefreshEnabled: state.autoRefreshEnabled,
        selectedPlaybooks: state.selectedPlaybooks,
        startIndex: state.startIndex,
      }),
      merge: (persisted, current) => {
        const layerSettings = persisted as Partial<ChartState> | undefined;
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
          tradeVisibilityMode: normalizeTradeVisibilityMode(layerSettings?.tradeVisibilityMode),
          startIndex:
            layerSettings?.startIndex === null || layerSettings?.startIndex === undefined
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
    },
  ),
);

function applyPlaybookLayerRequirements(state: ChartState): Partial<ChartState> {
  const layers = playbookControlledLayers(state.selectedPlaybooks, state.tradeVisibilityMode);
  return {
    selectedPlaybooks: state.selectedPlaybooks,
    ...layers,
  };
}

export function playbookControlledLayers(
  playbooks: PlaybookKey[],
  currentTradeVisibility: TradeVisibilityMode = "visible",
): Pick<ChartState, "showZones" | "zoneTypeVisibility" | "showStructure" | "tradeVisibilityMode"> {
  const requiredZoneTypes = requiredZoneTypesForPlaybooks(playbooks);
  const liquidityOnly = playbooks.length === 1 && playbooks[0] === "liquidity_sweep_reclaim_v1";
  return {
    showZones: requiredZoneTypes.size > 0,
    zoneTypeVisibility: {
      support: requiredZoneTypes.has("support"),
      resistance: requiredZoneTypes.has("resistance"),
      order_block: requiredZoneTypes.has("order_block"),
      fvg: requiredZoneTypes.has("fvg"),
      liquidity_pool: requiredZoneTypes.has("liquidity_pool"),
      consolidation: requiredZoneTypes.has("consolidation"),
    },
    showStructure: requiresStructureForPlaybooks(playbooks),
    tradeVisibilityMode: liquidityOnly ? "off" : currentTradeVisibility,
  };
}

function uniquePlaybooks(playbooks: PlaybookKey[]): PlaybookKey[] {
  const filtered = Array.from(new Set(playbooks)).filter((playbook): playbook is PlaybookKey => playbook in playbookLayerRequirements);
  return filtered.length > 0 ? filtered : defaultSelectedPlaybooks;
}

function requiredZoneTypesForPlaybooks(playbooks: PlaybookKey[]): Set<ZoneVisibilityKey> {
  const requiredZoneTypes = new Set<ZoneVisibilityKey>();
  for (const playbook of playbooks) {
    playbookLayerRequirements[playbook].zones.forEach((zoneType) => requiredZoneTypes.add(zoneType));
  }
  return requiredZoneTypes;
}

function requiresStructureForPlaybooks(playbooks: PlaybookKey[]): boolean {
  return playbooks.some((playbook) => playbookLayerRequirements[playbook].structure);
}

function normalizeTradeVisibilityMode(value: unknown): TradeVisibilityMode {
  return value === "hidden" || value === "all" || value === "off" ? value : "visible";
}
