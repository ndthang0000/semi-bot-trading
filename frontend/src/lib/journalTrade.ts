import type { TradeOrder } from "../types";

export type TradeLifecycleStatus = "pending" | "open" | "closed" | "expired" | "cancelled" | "failed";

type LifecycleTrade = Pick<
  TradeOrder,
  "status" | "closed_at" | "pnl_r" | "manual_ai_plan_status" | "manual_ai_expires_at"
>;

const BROKER_EXPIRY_TOLERANCE_MS = 90_000;

function cancelledAtBrokerExpiry(trade: LifecycleTrade): boolean {
  if (!trade.closed_at || !trade.manual_ai_expires_at) return false;
  const closedAt = Date.parse(trade.closed_at);
  const expiresAt = Date.parse(trade.manual_ai_expires_at);
  if (!Number.isFinite(closedAt) || !Number.isFinite(expiresAt)) return false;
  return Math.abs(closedAt - expiresAt) <= BROKER_EXPIRY_TOLERANCE_MS;
}

export function tradeLifecycleStatus(trade: LifecycleTrade): TradeLifecycleStatus {
  const orderStatus = trade.status.toLowerCase();
  const planStatus = trade.manual_ai_plan_status?.toLowerCase() ?? "";

  if (["closed", "stopped", "target_hit", "time_exit"].includes(orderStatus)) return "closed";
  if (orderStatus === "filled") return trade.closed_at ? "closed" : "open";
  if (orderStatus === "cancelled") {
    return planStatus === "expired" || cancelledAtBrokerExpiry(trade) ? "expired" : "cancelled";
  }
  if (planStatus === "expired") return "expired";
  if (["failed", "rejected"].includes(orderStatus) || planStatus === "rejected") return "failed";
  if (["pending_fill", "pending", "sent", "approved", "arming", "armed"].includes(orderStatus)) return "pending";
  if (trade.closed_at || trade.pnl_r !== null) return "closed";
  return "pending";
}

export function tradeLifecycleLabel(status: TradeLifecycleStatus): string {
  return {
    pending: "Pending limit",
    open: "Open position",
    closed: "Closed",
    expired: "Expired",
    cancelled: "Cancelled",
    failed: "Failed",
  }[status];
}

export function tradeLifecycleBadgeClass(status: TradeLifecycleStatus): string {
  return {
    pending: "border-amber-300/35 bg-amber-400/10 text-amber-200",
    open: "border-cyan-300/35 bg-cyan-400/10 text-cyan-200",
    closed: "border-emerald-300/25 bg-emerald-400/10 text-emerald-200",
    expired: "border-slate-500/40 bg-slate-700/35 text-slate-400",
    cancelled: "border-orange-300/25 bg-orange-400/10 text-orange-200",
    failed: "border-rose-300/35 bg-rose-400/10 text-rose-200",
  }[status];
}
