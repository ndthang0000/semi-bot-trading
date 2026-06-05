import type { ChartPayload, MarketContext, PlaybookKey, PriceZone, ReplayTimeline, Timeframe } from "../types";

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

  const response = await fetch(`/api/chart?${params.toString()}`);
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
  const response = await fetch(`/api/replay/timeline?${params.toString()}`);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Replay timeline failed with ${response.status}`);
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
  status: "active" | "disabled";
  no_expiry: boolean;
  reason?: string;
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
  status: "active" | "disabled";
  client_kind?: string;
  no_expiry: boolean;
  reason?: string;
};

export async function createManualZone(input: ZoneCreateInput): Promise<PriceZone> {
  const response = await fetch("/api/zones", {
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

export async function updateZoneOverride(zoneId: string, input: ZoneOverrideInput): Promise<PriceZone> {
  const response = await fetch(`/api/zones/${encodeURIComponent(zoneId)}`, {
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

export async function deleteManualZone(zoneId: string, reason?: string): Promise<PriceZone> {
  const params = new URLSearchParams();
  if (reason) {
    params.set("reason", reason);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const response = await fetch(`/api/zones/${encodeURIComponent(zoneId)}${suffix}`, {
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

export async function updateMarketContextOverride(
  timeframe: string,
  contextType: "bias" | "regime",
  input: ContextOverrideInput,
): Promise<MarketContext> {
  const response = await fetch(`/api/contexts/${encodeURIComponent(timeframe)}/${encodeURIComponent(contextType)}`, {
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
