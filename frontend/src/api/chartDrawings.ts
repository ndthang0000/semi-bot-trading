import type { ChartDrawing, ChartDrawingAnchor, ChartDrawingType, Timeframe } from "../types";
import { authFetch } from "./auth";

export type ChartDrawingCreateInput = {
  symbol: string;
  drawing_type: ChartDrawingType;
  origin_timeframe: Timeframe;
  visible_timeframes: Timeframe[];
  anchors: ChartDrawingAnchor[];
  properties?: Record<string, unknown>;
  content?: string | null;
};

async function apiError(response: Response, fallback: string): Promise<Error> {
  const body = await response.json().catch(() => null);
  return new Error(typeof body?.detail === "string" ? body.detail : fallback);
}

export async function fetchChartDrawings(symbol: string, timeframe: Timeframe): Promise<ChartDrawing[]> {
  const params = new URLSearchParams({ symbol, timeframe });
  const response = await authFetch(`/api/chart-drawings?${params.toString()}`);
  if (!response.ok) throw await apiError(response, `Chart drawings failed with ${response.status}`);
  const body = await response.json();
  return body.drawings;
}

export async function createChartDrawing(input: ChartDrawingCreateInput): Promise<ChartDrawing> {
  const response = await authFetch("/api/chart-drawings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) throw await apiError(response, `Create drawing failed with ${response.status}`);
  return response.json();
}

export async function updateChartDrawing(
  drawing: ChartDrawing,
  input: { anchors?: ChartDrawingAnchor[]; properties?: Record<string, unknown>; content?: string | null; locked?: boolean; hidden?: boolean },
): Promise<ChartDrawing> {
  const response = await authFetch(`/api/chart-drawings/${encodeURIComponent(drawing.id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ revision: drawing.revision, ...input }),
  });
  if (!response.ok) throw await apiError(response, `Update drawing failed with ${response.status}`);
  return response.json();
}

export async function fetchPreviousBrokerDayVolumeProfilePreset(symbol: string): Promise<{
  symbol: string;
  preset: "previous_broker_day";
  range_start: string;
  range_end: string;
  source_timeframe: "D1";
}> {
  const params = new URLSearchParams({ symbol });
  const response = await authFetch(`/api/volume-profile/presets/previous-broker-day?${params.toString()}`);
  if (!response.ok) throw await apiError(response, `Previous broker day failed with ${response.status}`);
  return response.json();
}

export async function deleteChartDrawing(drawing: ChartDrawing): Promise<void> {
  const response = await authFetch(`/api/chart-drawings/${encodeURIComponent(drawing.id)}?revision=${drawing.revision}`, {
    method: "DELETE",
  });
  if (!response.ok) throw await apiError(response, `Delete drawing failed with ${response.status}`);
}
