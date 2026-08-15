import type {
  ChartPayload,
  MarketContext,
  PlaybookKey,
  PriceZone,
  ReplayTimeline,
  SpreadSummary,
  Timeframe,
  TradeHistoryResponse,
  TradeReview,
  TradeReviewAttachment,
  JournalPatternsResponse,
  StrategyReview,
  OperatorReview,
  ZoneTradeMode,
  ZoneActivationReview,
  WeeklyJournal,
  WeeklyJournalsResponse,
} from "../types";
import { authFetch } from "./auth";

type ChartQuery = {
  symbol: string;
  timeframe: Timeframe;
  limit: number;
  startIndex: number | null;
  activeZonesOnly: boolean;
  selectedPlaybooks: PlaybookKey[];
  replayAt?: string | null;
  replayStart?: string | null;
};

export async function fetchChartPayload(query: ChartQuery): Promise<ChartPayload> {
  const params = new URLSearchParams({
    symbol: query.symbol,
    timeframe: query.timeframe,
    limit: String(query.limit),
  });
  if (query.startIndex !== null) {
    params.set("start_index", String(query.startIndex));
  }
  if (query.activeZonesOnly) {
    params.set("active_zones_only", "true");
  }
  params.set("playbooks", query.selectedPlaybooks.length > 0 ? query.selectedPlaybooks.join(",") : "__none__");
  if (query.replayAt) {
    params.set("replay_at", query.replayAt);
  }
  if (query.replayStart) {
    params.set("replay_start", query.replayStart);
  }

  const response = await authFetch(`/api/chart?${params.toString()}`);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Chart API failed with ${response.status}`);
  }
  return response.json();
}

export async function fetchReplayTimeline(query: Omit<ChartQuery, "activeZonesOnly" | "selectedPlaybooks" | "replayAt" | "replayStart">): Promise<ReplayTimeline> {
  const params = new URLSearchParams({
    symbol: query.symbol,
    timeframe: query.timeframe,
    limit: String(query.limit),
  });
  if (query.startIndex !== null) {
    params.set("start_index", String(query.startIndex));
  }
  const response = await authFetch(`/api/replay/timeline?${params.toString()}`);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Replay timeline failed with ${response.status}`);
  }
  return response.json();
}

export type TradeHistoryQuery = {
  symbol: string;
  timeframe: Timeframe;
  limit: number;
  offset: number;
  selectedPlaybooks: PlaybookKey[];
  status?: string;
  side?: string;
  outcome?: string;
  zoneType?: string;
  reaction?: string;
  tradeId?: string;
  backtest?: boolean | null;
  sort: string;
};

export async function fetchTradeHistory(query: TradeHistoryQuery): Promise<TradeHistoryResponse> {
  const params = new URLSearchParams({
    symbol: query.symbol,
    timeframe: query.timeframe,
    limit: String(query.limit),
    offset: String(query.offset),
    sort: query.sort,
  });
  params.set("playbooks", query.selectedPlaybooks.length > 0 ? query.selectedPlaybooks.join(",") : "__none__");
  if (query.status) params.set("status", query.status);
  if (query.side) params.set("side", query.side);
  if (query.outcome && query.outcome !== "all") params.set("outcome", query.outcome);
  if (query.zoneType) params.set("zone_type", query.zoneType);
  if (query.reaction) params.set("reaction", query.reaction);
  if (query.tradeId) params.set("trade_id", query.tradeId);
  if (query.backtest !== null && query.backtest !== undefined) params.set("backtest", String(query.backtest));

  const response = await authFetch(`/api/trades?${params.toString()}`);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Trade history failed with ${response.status}`);
  }
  return response.json();
}

export async function updateTradeVisibility(
  tradeOrderId: string,
  hiddenOnChart: boolean,
): Promise<{ id: string; hidden_on_chart: boolean }> {
  const response = await authFetch(`/api/trades/${encodeURIComponent(tradeOrderId)}/visibility`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ hidden_on_chart: hiddenOnChart }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Trade visibility update failed with ${response.status}`);
  }
  return response.json();
}

export type TradeReviewInput = {
  grade?: string | null;
  verdict: string;
  mistake_tags: string[];
  should_trade_again: string;
  comment: string;
  reviewer?: string;
  strategy_review?: StrategyReview;
  operator_review?: OperatorReview;
};

export async function updateTradeReview(tradeOrderId: string, input: TradeReviewInput): Promise<TradeReview> {
  const response = await authFetch(`/api/trades/${encodeURIComponent(tradeOrderId)}/review`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Trade review failed with ${response.status}`);
  }
  return response.json();
}

export type TradeReviewAttachmentInput = {
  kind: "entry" | "exit" | "review" | "manual";
  image_data: string;
  caption?: string;
  chart_symbol?: string | null;
  chart_timeframe?: string | null;
  chart_start?: string | null;
  chart_end?: string | null;
};

export async function fetchTradeReviewAttachments(tradeOrderId: string): Promise<TradeReviewAttachment[]> {
  const response = await authFetch(`/api/trades/${encodeURIComponent(tradeOrderId)}/attachments`);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Trade attachments failed with ${response.status}`);
  }
  return response.json();
}

export async function createTradeReviewAttachment(
  tradeOrderId: string,
  input: TradeReviewAttachmentInput,
): Promise<TradeReviewAttachment> {
  const response = await authFetch(`/api/trades/${encodeURIComponent(tradeOrderId)}/attachments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Create attachment failed with ${response.status}`);
  }
  return response.json();
}

export async function deleteTradeReviewAttachment(tradeOrderId: string, attachmentId: string): Promise<void> {
  const response = await authFetch(
    `/api/trades/${encodeURIComponent(tradeOrderId)}/attachments/${encodeURIComponent(attachmentId)}`,
    { method: "DELETE" },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Delete attachment failed with ${response.status}`);
  }
}

export async function fetchJournalPatterns(backtest = false): Promise<JournalPatternsResponse> {
  const response = await authFetch(`/api/journal/patterns?backtest=${String(backtest)}`);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Journal patterns failed with ${response.status}`);
  }
  return response.json();
}

export async function fetchWeeklyJournals(limit = 104): Promise<WeeklyJournalsResponse> {
  const response = await authFetch(`/api/weekly-journals?limit=${limit}`);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Weekly journals failed with ${response.status}`);
  }
  return response.json();
}

export type WeeklyJournalInput = {
  content: string;
  content_format: "plain_text" | "rich_text";
  icon: string;
  discipline_score: number;
  fomo_score: number;
  revenge_score: number;
  achieved_r: number;
};

export async function updateWeeklyJournal(
  weekStart: string,
  input: WeeklyJournalInput,
): Promise<WeeklyJournal> {
  const response = await authFetch(`/api/weekly-journals/${encodeURIComponent(weekStart)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Weekly journal save failed with ${response.status}`);
  }
  return response.json();
}

export type ZoneOverrideInput = {
  price_low: number;
  price_high: number;
  visual_start?: string;
  visual_end?: string | null;
  weight: number;
  confidence?: number;
  status: "active" | "draft" | "disabled";
  expires_at?: string | null;
  reason?: string;
  trade_modes?: ZoneTradeMode[];
  direction?: string;
};

export type ZoneCreateInput = {
  symbol: string;
  timeframe: Timeframe;
  zone_type: string;
  direction: string;
  price_low: number;
  price_high: number;
  visual_start: string;
  visual_end?: string | null;
  weight: number;
  confidence: number;
  status: "active" | "draft" | "disabled";
  client_kind?: string;
  expires_at?: string | null;
  reason?: string;
  trade_modes: ZoneTradeMode[];
};

export type ZoneImportEnvelope = {
  as_of: string;
  duplicate_audit: {
    safe_to_import: boolean;
    skipped: Array<Record<string, unknown>>;
  };
  api_endpoint: "POST /api/zones/import";
  api_payloads: ZoneCreateInput[];
};

export type ZoneImportResult = {
  created_count: number;
  draft_count: number;
  zones: PriceZone[];
};

export async function createManualZone(input: ZoneCreateInput): Promise<PriceZone> {
  const response = await authFetch("/api/zones", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Zone create failed with ${response.status}`);
  }
  return response.json();
}

export async function importZones(input: ZoneImportEnvelope): Promise<ZoneImportResult> {
  const response = await authFetch("/api/zones/import", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    if (typeof detail === "string") {
      throw new Error(detail);
    }
    if (detail && typeof detail.message === "string") {
      const count = Array.isArray(detail.conflicts) ? detail.conflicts.length : 0;
      throw new Error(count > 0 ? `${detail.message} (${count} conflict${count === 1 ? "" : "s"})` : detail.message);
    }
    throw new Error(`Zone import failed with ${response.status}`);
  }
  return response.json();
}

export async function updateZoneOverride(zoneId: string, input: ZoneOverrideInput): Promise<PriceZone> {
  const response = await authFetch(`/api/zones/${encodeURIComponent(zoneId)}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Zone update failed with ${response.status}`);
  }
  return response.json();
}

export async function confirmDraftZone(zoneId: string, input: Omit<ZoneActivationReview, "version" | "swing_type" | "confirmed_at" | "confirmed_by">): Promise<PriceZone> {
  const response = await authFetch(`/api/zones/${encodeURIComponent(zoneId)}/confirm`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Zone confirmation failed with ${response.status}`);
  }
  return response.json();
}

export async function deleteManualZone(zoneId: string, reason?: string): Promise<PriceZone> {
  const params = new URLSearchParams();
  if (reason) {
    params.set("reason", reason);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const response = await authFetch(`/api/zones/${encodeURIComponent(zoneId)}${suffix}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Zone delete failed with ${response.status}`);
  }
  return response.json();
}

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

export type NewsEvent = {
  id: string;
  title: string;
  country: string;
  impact: string;
  tier: 1 | 2;
  scheduled_at: string;
  blackout_from: string;
  blackout_until: string;
  blackout_before_min: number;
  blackout_after_min: number;
  minutes_until: number;
  is_active_blackout: boolean;
  forecast: string | null;
  previous: string | null;
  url: string | null;
};

export type NewsResponse = {
  events: NewsEvent[];
  active_blackout: NewsEvent | null;
};

export async function fetchNews(hoursAhead = 48): Promise<NewsResponse> {
  const response = await authFetch(`/api/news?hours_ahead=${hoursAhead}`);
  if (!response.ok) throw new Error(`News API failed with ${response.status}`);
  return response.json();
}

export async function fetchSpreadSummary(symbol: string, hours = 24): Promise<SpreadSummary> {
  const params = new URLSearchParams({ symbol, hours: String(hours) });
  const response = await authFetch(`/api/spread?${params.toString()}`);
  if (!response.ok) throw new Error(`Spread API failed with ${response.status}`);
  return response.json();
}

export async function updateMarketContextOverride(
  timeframe: string,
  contextType: "bias" | "regime",
  input: ContextOverrideInput,
): Promise<MarketContext> {
  const response = await authFetch(`/api/contexts/${encodeURIComponent(timeframe)}/${encodeURIComponent(contextType)}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Context update failed with ${response.status}`);
  }
  return response.json();
}
