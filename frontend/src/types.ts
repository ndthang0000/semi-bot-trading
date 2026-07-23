export type Timeframe = "M15" | "H1";

export type ZoneVisibilityKey =
  | "support"
  | "resistance"
  | "order_block"
  | "fvg"
  | "liquidity_pool"
  | "consolidation";

export type ZoneTypeVisibility = Record<ZoneVisibilityKey, boolean>;

export type TradeVisibilityMode = "visible" | "hidden" | "all" | "off";

export type PlaybookKey = "zone_reaction_v2" | "sr_breakout_v1";

export type AddEntityKind =
  | "support"
  | "resistance"
  | "demand_order_block"
  | "supply_order_block"
  | "bullish_fvg"
  | "bearish_fvg"
  | "consolidation"
  | "buy_side_liquidity"
  | "sell_side_liquidity";

export type ChartCandle = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
};

export type M15TriggerOverlay = ChartCandle & {
  zone_id: string;
  zone_type: string;
  reaction_state: string;
  candidate_id: string | null;
  status: "touch" | SetupCandidate["status"] | string;
  direction: string | null;
  reason: string[];
  metadata: Record<string, unknown>;
};

export type AtrSnapshot = {
  period: number;
  value: number | null;
  as_of: string | null;
};

export type RsiSnapshot = {
  period: number;
  value: number | null;
  slope_3: number | null;
  slope_5: number | null;
  as_of: string | null;
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
  timeframe: Timeframe;
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

export type ZoneTradeMode = "reject" | "internal_reject" | "breakout";

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
  account_label: string;
  playbook: string;
  direction: string;
  side: string;
  order_type: string;
  status: string;
  entry_price: number | null;
  stop_loss: number | null;
  take_profit: Array<number | { price?: number }>;
  quantity: number;
  opened_at: string | null;
  closed_at: string | null;
  close_price: number | null;
  pnl: number | null;
  pnl_r: number | null;
  hidden_on_chart: boolean;
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
  metadata: Record<string, unknown>;
  strategy_review: StrategyReview;
  operator_review: OperatorReview;
};

export type StrategyReview = {
  setup_grade?: string;
  setup_validity?: string;
  zone_quality?: string;
  entry_quality?: string;
  sl_quality?: string;
  tp_quality?: string;
  market_context?: string;
  should_bot_trade_again?: string;
  strategy_tags?: string[];
};

export type OperatorReview = {
  operator_state?: string;
  operator_action?: string;
  intervention_result?: string;
  followed_plan?: string;
  emotion_score?: number;
  confidence_before?: number;
  confidence_after?: number;
  operator_tags?: string[];
};

export type TradeReviewAttachment = {
  id: string;
  trade_order_id: string;
  kind: "entry" | "exit" | "review" | "manual";
  caption: string;
  chart_symbol: string | null;
  chart_timeframe: string | null;
  chart_start: string | null;
  chart_end: string | null;
  created_at: string;
  file_url: string;
};

export type JournalPatternRow = {
  key: string;
  trades: number;
  wins: number;
  losses: number;
  total_r: number;
  avg_r: number;
  win_rate: number;
};

export type JournalPatternsResponse = {
  groups: Record<string, JournalPatternRow[]>;
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
  timeframe: Timeframe;
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
    atr: Record<string, AtrSnapshot>;
    rsi: Record<string, RsiSnapshot>;
    trades: TradeOrder[];
    setup_candidates: SetupCandidate[];
    m15_triggers: M15TriggerOverlay[];
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

export type SpreadSnapshot = {
  id: string;
  symbol: string;
  broker_symbol: string;
  bid: number;
  ask: number;
  spread: number;
  snapshot_at: string;
  source: string;
  metadata: Record<string, unknown>;
};

export type SpreadSummary = {
  symbol: string;
  hours: number;
  count: number;
  latest: SpreadSnapshot | null;
  min: number | null;
  avg: number | null;
  p50: number | null;
  p90: number | null;
  p95: number | null;
  p99: number | null;
  max: number | null;
};

export type SelectedEntity =
  | { kind: "zone"; entity: PriceZone }
  | { kind: "structure"; entity: StructurePoint }
  | { kind: "trade"; entity: TradeOrder };

export type ZoneFocusRequest = {
  id: number;
  zone: PriceZone;
};

export type TradeFocusRequest = {
  id: number;
  trade: TradeOrder;
};
