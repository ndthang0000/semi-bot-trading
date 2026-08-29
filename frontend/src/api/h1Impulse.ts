import { authFetch } from "./auth";
import type { SetupCandidate } from "../types";

export type H1ImpulseEntrySource =
  | "previous_h1_high"
  | "previous_h1_low"
  | "fib_0.5_min_stop_fallback"
  | "fib_0.5_then_atr_1.2_cap"
  | "atr_1.2_max_stop_cap"
  | "unavailable";

export type H1ImpulseTargetMode = "fixed_rr" | "wave_safe" | "wave_base";

export type H1ImpulseTargetOption = {
  mode: H1ImpulseTargetMode;
  label: string;
  available: boolean;
  price: number | null;
  risk_reward: number | null;
  reward_distance: number | null;
  baseline_move: number | null;
  multiplier: number | null;
  sample_count: number | null;
  reason: string;
};

export type H1ImpulsePreview = {
  schema_version: 1;
  playbook: "h1_impulse_retest_v1";
  preview_only: true;
  symbol: string;
  as_of: string;
  status: "eligible" | "blocked";
  direction: "long" | "short" | "neutral";
  signal_candle_time: string;
  signal_candle_close_time: string;
  expires_at: string;
  expiry_hours: number;
  previous_candle_time: string;
  atr: number;
  atr_period: number;
  atr_as_of: string | null;
  reference_price: number | null;
  risk_reward: number;
  target_mode: H1ImpulseTargetMode;
  target_plan: {
    requested_mode: H1ImpulseTargetMode;
    applied_mode: H1ImpulseTargetMode;
    fallback_reason: string | null;
    options: H1ImpulseTargetOption[];
    wave_snapshot: {
      as_of: string;
      baseline_direction: "up" | "down";
      baseline_move: number | null;
      sample_count: number;
      market_state: string;
      control: string;
      latest: Record<string, unknown> | null;
    };
  };
  entry: number;
  entry_source: H1ImpulseEntrySource;
  entry_options: Array<{ source: string; label: string; price: number }>;
  previous_edge_entry: number;
  fib_0_5_entry: number;
  stop_loss: number;
  stop_buffer: number;
  stop_distance: number;
  stop_distance_atr: number;
  min_stop_distance: number;
  max_stop_distance: number;
  take_profit: number;
  limit_placement_valid: boolean;
  broke_previous_edge: boolean;
  blocked_reason: string[];
  soft_blocked_reason: string[];
  hard_blocked_reason: string[];
  outcome: {
    status: "blocked" | "unfilled" | "expired_unfilled" | "open" | "win" | "loss" | "ambiguous";
    filled_at: string | null;
    exited_at: string | null;
    bars_to_fill: number | null;
    bars_held: number | null;
    result_r: number | null;
  };
  signal: {
    open: number;
    high: number;
    low: number;
    close: number;
    range: number;
    body: number;
    upper_wick: number;
    lower_wick: number;
    body_atr_ratio: number;
    range_atr_ratio: number;
    body_range_ratio: number;
    close_location: number;
    close_side_wick_ratio: number;
    opposite_wick_ratio: number;
  };
  previous: {
    open: number;
    high: number;
    low: number;
    close: number;
    entry_stop_distance: number;
    entry_stop_distance_atr: number;
  };
  parameters: {
    atr_period: number;
    stop_buffer_atr: number;
    min_stop_atr: number;
    max_stop_atr: number;
    min_body_atr: number;
    min_range_atr: number;
    max_range_atr: number;
    min_body_range_ratio: number;
    min_close_location: number;
    max_close_side_wick_ratio: number;
    wave_safe_fraction: number;
    min_wave_samples: number;
    expiry_medium_body_atr: number;
    expiry_large_body_atr: number;
    expiry_hours_small: number;
    expiry_hours_medium: number;
    expiry_hours_large: number;
    min_order_ttl_hours: number;
    max_order_ttl_hours: number;
    max_signal_age_hours: number;
  };
};

export type H1ImpulseRevalidation = {
  can_reorder: boolean;
  evaluated_at: string;
  signal_candle_time: string;
  signal_close_time: string;
  signal_age_hours: number;
  max_signal_age_hours: number;
  entry_touched: boolean;
  invalidation_touched: boolean;
  target_reached_without_fill: boolean;
  first_entry_touch_at: string | null;
  first_invalidation_touch_at: string | null;
  first_target_touch_at: string | null;
  hard_blocked_reasons: string[];
  timeframe_used: "M5" | "H1";
  min_order_ttl_hours: number;
  max_order_ttl_hours: number;
};

export async function previewH1Impulse(payload: {
  symbol: string;
  signalCandleTime: string;
  riskReward: number;
  targetMode?: H1ImpulseTargetMode;
  asOf?: string;
}): Promise<H1ImpulsePreview> {
  const response = await authFetch("/api/playbooks/h1-impulse-retest/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      symbol: payload.symbol,
      signal_candle_time: payload.signalCandleTime,
      risk_reward: payload.riskReward,
      target_mode: payload.targetMode ?? "fixed_rr",
      ...(payload.asOf ? { as_of: payload.asOf } : {}),
    }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `H1 impulse preview failed with ${response.status}`);
  }
  return response.json();
}

export async function revalidateH1Impulse(payload: {
  symbol: string;
  signalCandleTime: string;
  direction: "long" | "short";
  entry: number;
  stopLoss: number;
  takeProfit: number;
}): Promise<H1ImpulseRevalidation> {
  const response = await authFetch("/api/playbooks/h1-impulse-retest/revalidate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      symbol: payload.symbol,
      signal_candle_time: payload.signalCandleTime,
      direction: payload.direction,
      entry: payload.entry,
      stop_loss: payload.stopLoss,
      take_profit: payload.takeProfit,
    }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : JSON.stringify(body?.detail ?? `H1 revalidation failed (${response.status})`));
  }
  return response.json();
}

export function h1ImpulsePreviewToSetupCandidate(preview: H1ImpulsePreview): SetupCandidate {
  const outcomeLabel = preview.outcome.status.toUpperCase();
  return {
    id: `h1-impulse:${preview.symbol}:${preview.signal_candle_time}:${preview.target_mode}:${preview.risk_reward}`,
    symbol: preview.symbol,
    timeframe: "H1",
    playbook: "h1_impulse_retest_v1",
    direction: preview.direction === "short" ? "short" : "long",
    status: preview.status,
    zone_reaction_state: outcomeLabel,
    score: preview.status === "eligible" ? 1 : 0,
    entry: preview.entry,
    stop_loss: preview.stop_loss,
    take_profit: [preview.take_profit],
    risk_reward: preview.risk_reward,
    primary_zone_id: null,
    related_zone_ids: [],
    trigger_point_ids: [],
    reason: [
      `Entry source: ${preview.entry_source}`,
      `Historical outcome: ${outcomeLabel}`,
    ],
    blocked_reason: preview.blocked_reason,
    expires_at: preview.expires_at,
    metadata: {
      h1_impulse_preview: true,
      created_at: preview.signal_candle_close_time,
      as_of: preview.as_of,
      signal_candle_time: preview.signal_candle_time,
      previous_candle_time: preview.previous_candle_time,
      entry_source: preview.entry_source,
      target_mode: preview.target_mode,
      target_plan: preview.target_plan,
      target_reward_distance: preview.target_plan.options.find((option) => option.mode === preview.target_mode)?.reward_distance ?? null,
      target_warning: preview.target_plan.fallback_reason,
      entry_options: preview.entry_options,
      limit_expires_at: preview.expires_at,
      expiry_hours: preview.expiry_hours,
      outcome: preview.outcome,
      atr: preview.atr,
      atr_period: preview.atr_period,
      stop_distance_atr: preview.stop_distance_atr,
      reference_price: preview.reference_price,
      original_status: preview.status,
      original_blocked_reasons: preview.blocked_reason,
      soft_blocked_reasons: preview.soft_blocked_reason,
      hard_blocked_reasons: preview.hard_blocked_reason,
      parameters: preview.parameters,
      preview_only: true,
    },
  };
}
