import { authFetch } from "./auth";

export type ManualAiPlan = {
  id: string;
  client_id: string;
  account_label: string | null;
  symbol: string;
  side: "buy" | "sell";
  status: string;
  execution_state: "primary" | "watch_only";
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  risk_pct: number;
  risk_reward: number;
  playbook: "manual_ai_v1" | "h1_impulse_retest_v1";
  entry_source: string;
  expires_at: string;
  expires_in_minutes: number;
  partial_take_profit: {
    enabled: boolean;
    trigger_r: number;
    close_fraction: number;
    move_stop_to: "breakeven" | "unchanged";
    breakeven_buffer: number;
  };
};

export type ManualAiWorker = {
  label: string;
  execution: {
    worker_status: string;
    heartbeat_at: string | null;
  };
};

export async function importManualAiPlans(payload: unknown, source: "import" | "manual"): Promise<{ plans: ManualAiPlan[] }> {
  const response = await authFetch(`/api/manual-ai/plans${source === "import" ? "/import" : ""}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail ?? `Import failed (${response.status})`));
  }
  return response.json();
}

export async function approveManualAiPlan(planId: string, payload: unknown): Promise<{ plans: ManualAiPlan[] }> {
  const response = await authFetch(`/api/manual-ai/plans/${encodeURIComponent(planId)}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail ?? `Approval failed (${response.status})`));
  }
  const body = await response.json();
  return Array.isArray(body?.plans) ? body : { plans: [body] };
}

export async function fetchManualAiWorkers(): Promise<ManualAiWorker[]> {
  const response = await authFetch("/api/accounts");
  if (!response.ok) throw new Error(`Không thể tải danh sách worker (${response.status})`);
  const body = await response.json();
  return Array.isArray(body?.accounts) ? body.accounts : [];
}

export async function cancelManualAiPlan(planId: string): Promise<ManualAiPlan> {
  const response = await authFetch(`/api/manual-ai/plans/${encodeURIComponent(planId)}/cancel`, {
    method: "POST",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `Cancel failed (${response.status})`);
  }
  return response.json();
}

export async function rejectManualAiPlan(planId: string): Promise<ManualAiPlan> {
  const response = await authFetch(`/api/manual-ai/plans/${encodeURIComponent(planId)}/reject`, {
    method: "POST",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `Reject failed (${response.status})`);
  }
  return response.json();
}

export type ManualAiLevelsUpdate = {
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  entry_source: string;
};

export async function updateManualAiPlanLevels(
  planId: string,
  levels: ManualAiLevelsUpdate,
): Promise<{ plans: ManualAiPlan[]; requires_broker_replace: boolean }> {
  const response = await authFetch(`/api/manual-ai/plans/${encodeURIComponent(planId)}/levels`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(levels),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `Update levels failed (${response.status})`);
  }
  return response.json();
}
