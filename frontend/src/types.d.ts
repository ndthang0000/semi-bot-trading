export type Timeframe = "M15" | "H1";
export type ZoneVisibilityKey = "support" | "resistance" | "order_block" | "fvg" | "liquidity_pool" | "consolidation";
export type ZoneTypeVisibility = Record<ZoneVisibilityKey, boolean>;
export type PlaybookKey = "trend_pullback" | "zone_reaction_v2" | "ob_mitigation_continuation" | "fvg_fill_go" | "breakout_retest" | "momentum_expansion_continuation" | "range_boundary_reversal" | "liquidity_sweep_reversal" | "failed_breakout_trap";
export type AddEntityKind = "support" | "resistance" | "demand_order_block" | "supply_order_block" | "bullish_fvg" | "bearish_fvg" | "consolidation" | "buy_side_liquidity" | "sell_side_liquidity";
export type ChartCandle = {
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number | null;
};
export type StructurePoint = {
    id: string;
    time: string;
    type: string;
    price: number;
    detector: string;
    status: string;
    confidence: number;
    direction: string | null;
    related_zone_ids: string[];
    metadata: Record<string, unknown>;
};
export type PriceZone = {
    id: string;
    type: string;
    direction: "bullish" | "bearish" | string;
    detector: string;
    status: string;
    source: string;
    price_low: number;
    price_high: number;
    visual_start: string;
    visual_end: string | null;
    valid_from: string;
    valid_until: string | null;
    invalidated_at: string | null;
    invalidated_by_structure_point_id: string | null;
    detected_at: string;
    weight: number;
    confidence: number;
    metadata: Record<string, unknown>;
};
export type MarketContext = {
    bot_value: string;
    primary_value: string;
    secondary_value: string | null;
    bot_confidence: number;
    effective_value: string;
    effective_confidence: number;
    source: string;
    valid_from: string;
    valid_until: string | null;
    status: string;
    metadata: Record<string, unknown>;
};
export type TradeOrder = {
    id: string;
    trade_idea_id: string;
    playbook: string;
    direction: string;
    side: string;
    order_type: string;
    status: string;
    entry_price: number | null;
    stop_loss: number | null;
    take_profit: Array<number | {
        price?: number;
    }>;
    quantity: number;
    opened_at: string | null;
    closed_at: string | null;
    close_price: number | null;
    pnl: number | null;
    pnl_r: number | null;
    source: string;
    metadata: Record<string, unknown>;
    chart_index?: number | null;
    review?: TradeReview | null;
};
export type TradeReview = {
    id: string | null;
    trade_order_id: string;
    grade: "A" | "B" | "C" | "D" | null;
    verdict: string;
    mistake_tags: string[];
    should_trade_again: string;
    comment: string;
    reviewer: string;
    created_at: string | null;
    updated_at: string | null;
};
export type TradeHistoryResponse = {
    symbol: string;
    timeframe: Timeframe;
    limit: number;
    offset: number;
    total: number;
    trades: TradeOrder[];
};
export type SetupCandidate = {
    id: string;
    symbol: string;
    timeframe: "M15";
    playbook: string;
    direction: "long" | "short";
    status: "watching" | "waiting_confirmation" | "eligible" | "blocked" | "expired";
    zone_reaction_state: string;
    score: number;
    entry: number | null;
    stop_loss: number | null;
    take_profit: number[];
    risk_reward: number | null;
    primary_zone_id: string | null;
    related_zone_ids: string[];
    trigger_point_ids: string[];
    reason: string[];
    blocked_reason: string[];
    expires_at: string | null;
    metadata: Record<string, unknown>;
};
export type ChartPayload = {
    version: number;
    symbol: string;
    timeframe: Timeframe;
    range: {
        start: string;
        end: string;
        limit: number;
        start_index: number | null;
        requested_start: string | null;
        requested_end: string | null;
    };
    layers: {
        candles: ChartCandle[];
        structure: StructurePoint[];
        structure_timeframe: string;
        zones: PriceZone[];
        contexts: Record<string, Record<string, MarketContext>>;
        trades: TradeOrder[];
        setup_candidates: SetupCandidate[];
    };
    replay?: {
        enabled: boolean;
        as_of: string;
        start?: string;
        lookahead_guard: string;
    };
};
export type ReplayTimeline = {
    symbol: string;
    timeframe: Timeframe;
    limit: number;
    start_index: number | null;
    total_count: number;
    times: string[];
    start: string | null;
    end: string | null;
    count: number;
};
export type SelectedEntity = {
    kind: "zone";
    entity: PriceZone;
} | {
    kind: "structure";
    entity: StructurePoint;
} | {
    kind: "trade";
    entity: TradeOrder;
};
export type ZoneFocusRequest = {
    id: number;
    zone: PriceZone;
};
export type TradeFocusRequest = {
    id: number;
    trade: TradeOrder;
};
