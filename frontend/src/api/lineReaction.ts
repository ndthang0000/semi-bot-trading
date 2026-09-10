import { authFetch } from "./auth";
import type { LinePlan } from "../store/lineReactionStore";

export type LineSession = { value: string; label: string; start_utc: string; end_utc: string };
export type LineReactionResponse = { plans: LinePlan[]; sessions: LineSession[] };
export type LineAccount = {
  label: string;
  execution?: { worker_status?: string; heartbeat_at?: string | null };
};

async function lineRequest<T>(path: string, body?: unknown, method = "GET"): Promise<T> {
  const response = await authFetch(path, {
    method,
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  const data = await response.json().catch(() => {
    throw new Error("API Line Reaction trả về dữ liệu không hợp lệ. Kiểm tra phiên bản backend và tải lại trang.");
  });
  if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail : JSON.stringify(data?.detail));
  return data as T;
}

export const fetchLineReactions = () => lineRequest<LineReactionResponse>("/api/line-reactions");
export const createLineReaction = (body: unknown) => lineRequest<LinePlan>("/api/line-reactions", body, "POST");
export const updateLineReaction = (id: string, body: unknown) =>
  lineRequest<LinePlan>(`/api/line-reactions/${encodeURIComponent(id)}`, body, "PATCH");
export const updateLinePrice = (plan: LinePlan, price: number) => updateLineReaction(plan.id, {
  symbol: plan.symbol ?? "XAUUSD", account_labels: plan.account_labels ?? [plan.account_label],
  direction: plan.direction, price, config: plan.config,
  visual_start: plan.visual_start ?? plan.armed_at ?? plan.created_at,
  visual_end: plan.visual_end ?? plan.expires_at,
});
export const armLineReaction = (id: string) =>
  lineRequest<LinePlan>(`/api/line-reactions/${encodeURIComponent(id)}/arm`, {}, "POST");
export const cancelLineReaction = (id: string) =>
  lineRequest<LinePlan>(`/api/line-reactions/${encodeURIComponent(id)}/cancel`, {}, "POST");

export async function fetchLineAccounts(): Promise<LineAccount[]> {
  const response = await authFetch("/api/accounts");
  const data = await response.json().catch(() => null);
  if (!response.ok || !Array.isArray(data?.accounts)) throw new Error(`Không thể tải danh sách account (${response.status})`);
  return data.accounts
    .map((account: LineAccount & { account_label?: string }) => ({ ...account, label: account.label ?? account.account_label ?? "" }))
    .filter((account: LineAccount) => Boolean(account.label));
}
