export type Timeframe = "M5" | "M15" | "H1";

export type ChartDrawingType = "note" | "fib_retracement" | "horizontal_line";
export type ChartDrawingTool = "cursor" | "measure" | "note" | "fib_standard" | "fib_ote" | "horizontal_line" | "copy_price";

export type ChartDrawingAnchor = {
  time: string;
  price: number;
};

export type ChartDrawing = {
  id: string;
  symbol: string;
  drawing_type: ChartDrawingType;
  origin_timeframe: Timeframe;
  visible_timeframes: Timeframe[];
  anchors: ChartDrawingAnchor[];
  properties: Record<string, unknown>;
  content: string | null;
  locked: boolean;
  hidden: boolean;
  revision: number;
  created_by: string;
  created_at: string;
  updated_at: string;
};

export type ZoneVisibilityKey =
  | "support"
  | "resistance"
  | "order_block"
  | "fvg"
  | "liquidity_pool"
  | "consolidation";

export type ZoneTypeVisibility = Record<ZoneVisibilityKey, boolean>;

export type TradeVisibilityMode = "visible" | "hidden" | "all" | "off";

export type PlaybookKey =
  | "quick_order_v1"
  | "line_reaction_v1"
  | "zone_reaction_v2"
  | "sr_breakout_v1"
  | "manual_ai_v1"
  | "liquidity_sweep_reclaim_v1"
  | "h1_impulse_retest_v1";

export type AddEntityKind =
  | "line_buy"
  | "line_sell"
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

export type ZoneTradeMode = "reject" | "internal_reject" | "breakout" | "liquidity_sweep";

export type ZoneActivationReview = {
  version?: number;
  short_term_trend: "bullish" | "bearish" | "neutral";
  medium_term_trend: "bullish" | "bearish" | "neutral";
  swing_location: "inside_zone" | "near_zone" | "none";
  swing_type?: "swing_low" | "swing_high";
  thesis_reasons: ZoneThesisReason[];
  emotion_state: ZoneEmotionState;
  comment: string;
  confirmed_at?: string;
  confirmed_by?: string;
};

export type ZoneThesisReason =
  | "value_entry_outside_swing"
  | "follow_short_term_trend"
  | "follow_medium_term_trend"
  | "breakout_retest"
  | "structure_flip"
  | "range_boundary"
  | "repeated_reactions"
  | "long_accumulation";

export type ZoneEmotionState =
  | "calm"
  | "fomo"
  | "revenge"
  | "proving_right"
  | "fear_missing_price"
  | "uncertain";

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
  manual_ai_plan_status?: string | null;
  manual_ai_expires_at?: string | null;
  chart_index?: number | null;
  review?: TradeReview | null;
};

export type TradeReviewGroup = {
  id: string;
  representative: TradeOrder;
  trades: TradeOrder[];
  review: TradeReview | null;
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

export type WeeklyJournal = {
  id: string;
  week_start: string;
  week_end: string;
  content: string;
  content_format: "plain_text" | "rich_text";
  icon: string;
  discipline_score: number;
  fomo_score: number;
  revenge_score: number;
  achieved_r: number;
  created_at: string;
  updated_at: string;
};

export type WeeklyJournalsResponse = {
  journals: WeeklyJournal[];
  total: number;
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

export type M15SignalSnapshot = {
  candle_time: string;
  candle_close_time: string | null;
  candle_closed: boolean;
  open: number;
  high: number;
  low: number;
  close: number;
  candle_direction: "bullish" | "bearish" | "doji";
  avg_body_period: number;
  avg_body: number;
  body: number;
  body_avg_ratio: number | null;
  candidate_count: number;
  candidate_id: string | null;
  status: string;
  reaction_state: string | null;
  trigger_method: string | null;
  trigger_candle_time: string | null;
  trigger_is_latest_closed_candle: boolean;
  trigger_avg_body: number | null;
  trigger_body: number | null;
  trigger_body_avg_ratio: number | null;
  strength_size: number | null;
  strength_avg_ratio: number | null;
  zone_id: string | null;
  zone_type: string | null;
  reason: string | null;
};

export type IntradayLevelStatus = "live" | "unswept" | "testing" | "swept" | "reclaimed" | "broken" | "testing_flip" | "stale";

export type IntradayLevel = {
  id: string;
  kind: "previous_day" | "current_day" | "asia" | "london" | "new_york" | "m15_swing" | string;
  label: string;
  side: "high" | "low";
  price: number;
  period_start: string;
  period_end: string;
  status: IntradayLevelStatus;
  priority: number;
  live: boolean;
  distance: number;
  distance_atr: number | null;
  approach_low: number;
  approach_high: number;
};

export type IntradayMap = {
  as_of: string;
  timezone: "UTC" | string;
  current_price: number | null;
  current_session: string;
  atr_m15: number | null;
  approach_allowance: number | null;
  nearest_above_id: string | null;
  nearest_below_id: string | null;
  levels: IntradayLevel[];
};

export type H1ImpulseMarker = {
  time: string;
  close_time: string;
  direction: "long" | "short";
  status: "candidate" | "eligible";
  body_atr_ratio: number;
  range_atr_ratio: number;
  body_range_ratio: number;
  entry_source: string;
  blocked_reason: string[];
};

export type WaveLeg = {
  id: string;
  direction: "up" | "down";
  start_time: string;
  end_time: string;
  start_price: number;
  end_price: number;
  mid_time: string;
  mid_price: number;
  price_move: number;
  bars: number | null;
  duration_hours: number;
  confirmed: boolean;
};

export type WaveMetrics = {
  legs: WaveLeg[];
  strength: {
    up_median_price: number | null;
    down_median_price: number | null;
    up_median_bars: number | null;
    down_median_bars: number | null;
    up_median_speed: number | null;
    down_median_speed: number | null;
    ratio: number | null;
    control: "buy" | "sell" | "balanced" | "unknown";
    up_samples: number;
    down_samples: number;
    latest: {
      direction: "up" | "down";
      price_move: number;
      bars: number | null;
      speed: number | null;
    } | null;
    latest_to_previous_ratio: number | null;
    up_change_pct: number | null;
    down_change_pct: number | null;
    efficiency: number | null;
    efficiency_direction: "up" | "down" | "flat";
    market_state: "trending_up" | "trending_down" | "rotational" | "choppy" | "unknown";
    efficiency_samples: number;
  };
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
    wave_metrics: WaveMetrics;
    zones: PriceZone[];
    contexts: Record<string, Record<string, MarketContext>>;
    atr: Record<string, AtrSnapshot>;
    rsi: Record<string, RsiSnapshot>;
    trades: TradeOrder[];
    setup_candidates: SetupCandidate[];
    h1_impulse_markers: H1ImpulseMarker[];
    m15_triggers: M15TriggerOverlay[];
    m15_signal: M15SignalSnapshot | null;
    intraday_map: IntradayMap;
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
