import { authFetch } from "./auth";

export type QuickOrderSide = "buy" | "sell";
export type QuickOrderType = "market" | "limit";

export type QuickOrderInput = {
  symbol: string;
  account_labels: string[];
  side: QuickOrderSide;
  order_type: QuickOrderType;
  entry_price: number | null;
  stop_loss: number | null;
  risk_reward: number;
};

export type QuickOrderPreview = {
  symbol: string;
  atr_h1: number;
  atr_candle_time: string;
  accounts: Array<{
    account_label: string;
    execution_ready: boolean;
    worker_status: string;
    quote_fresh: boolean;
    quote: { bid: number; ask: number; spread: number; snapshot_at: string };
    entry: number;
    stop_loss: number;
    take_profit: number;
    stop_distance: number;
    stop_atr: number;
    risk_reward: number;
    stop_was_adjusted: boolean;
  }>;
};

async function request<T>(path: string, body: unknown, method = "POST"): Promise<T> {
  const response = await authFetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : `Quick Order failed (${response.status})`);
  return data as T;
}

export const previewQuickOrder = (body: QuickOrderInput) =>
  request<QuickOrderPreview>("/api/quick-orders/preview", body);

export const createQuickOrder = (body: QuickOrderInput & { client_request_id: string; expires_in_minutes: number }) =>
  request<{ id: string; account_statuses: Record<string, string> }>("/api/quick-orders", body);

export const cancelQuickOrder = (groupId: string) =>
  request<{ id: string; account_statuses: Record<string, string> }>(
    `/api/quick-orders/${encodeURIComponent(groupId)}/cancel`,
    undefined,
  );

export const updateQuickOrderLevels = (
  groupId: string,
  body: { entry_price: number; stop_loss: number; take_profit: number },
) => request<{ id: string; account_statuses: Record<string, string>; requires_broker_replace: boolean }>(
  `/api/quick-orders/${encodeURIComponent(groupId)}/levels`,
  body,
  "PATCH",
);
