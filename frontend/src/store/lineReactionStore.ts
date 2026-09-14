import { create } from "zustand";
export type LineConfig = {
  recovery_mode?: "average_body" | "price" | "session_price"; recovery_price?: number;
  recovery_price_by_session?: Record<string, number>;
  recovery_ratio: number; body_period: number; stop_buffer_atr: number; max_stop_h1_atr: number;
  min_stop_price?: number;
  limit_offset: number; limit_ttl_minutes: number; risk_reward: number; target_mode: string;
  partial_enabled: boolean; partial_trigger_r: number; partial_fraction: number;
  trade_sessions: string[];
};
export type LinePlan = { id: string; symbol?: string; price: number; direction: string; status: string; account_label: string;
  account_labels?: string[]; member_ids?: string[]; account_statuses?: Record<string, string>;
  created_at: string; updated_at?: string; armed_at: string | null; expires_at: string; last_error: string | null;
  config: LineConfig; signal: unknown; visual_start: string | null; visual_end: string | null };
export type LineDraft = { price: number; direction: "long" | "short"; visual_start: string; visual_end: string; client_request_id: string };
export const useLineReactionStore = create<{
  plans: LinePlan[]; draft: LineDraft | null; selectedId: string | null;
  setPlans: (plans: LinePlan[]) => void; setDraft: (draft: LineDraft | null) => void;
  upsertPlan: (plan: LinePlan) => void;
  select: (id: string | null) => void;
}>(set => ({ plans: [], draft: null, selectedId: null,
  setPlans: plans => set({plans}), setDraft: draft => set({draft}),
  upsertPlan: plan => set(state => ({ plans: [...state.plans.filter(item => item.id !== plan.id), plan] })),
  select: selectedId => set({selectedId}) }));
