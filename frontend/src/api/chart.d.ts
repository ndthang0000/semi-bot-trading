import type { ChartPayload, MarketContext, PriceZone, ReplayTimeline, Timeframe } from "../types";
type ChartQuery = {
    symbol: string;
    timeframe: Timeframe;
    limit: number;
    activeZonesOnly: boolean;
    replayAt?: string | null;
    replayStart?: string | null;
};
export declare function fetchChartPayload(query: ChartQuery): Promise<ChartPayload>;
export declare function fetchReplayTimeline(query: Omit<ChartQuery, "activeZonesOnly" | "replayAt" | "replayStart">): Promise<ReplayTimeline>;
export type ZoneOverrideInput = {
    price_low: number;
    price_high: number;
    visual_start?: string;
    visual_end?: string | null;
    weight: number;
    confidence?: number;
    status: "active" | "disabled";
    no_expiry: boolean;
    reason?: string;
};
export declare function updateZoneOverride(zoneId: string, input: ZoneOverrideInput): Promise<PriceZone>;
export type ContextOverrideInput = {
    value?: string;
    secondary_value?: string | null;
    overlays?: string[];
    confidence?: number;
    no_expiry?: boolean;
    expires_at?: string | null;
    reason?: string;
    use_bot?: boolean;
};
export declare function updateMarketContextOverride(timeframe: string, contextType: "bias" | "regime", input: ContextOverrideInput): Promise<MarketContext>;
export {};
