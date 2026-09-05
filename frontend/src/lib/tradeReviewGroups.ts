import type { TradeOrder, TradeReview, TradeReviewGroup } from "../types";

export function tradeReviewGroupId(trade: TradeOrder): string {
  const executionGroupId = trade.metadata?.execution_group_id;
  if (typeof executionGroupId === "string" && executionGroupId.trim()) {
    return `${trade.source}:${trade.playbook}:${executionGroupId}`;
  }
  return `order:${trade.id}`;
}

export function groupTradesForReview(trades: TradeOrder[]): TradeReviewGroup[] {
  const grouped = new Map<string, TradeOrder[]>();
  for (const trade of trades) {
    const id = tradeReviewGroupId(trade);
    grouped.set(id, [...(grouped.get(id) ?? []), trade]);
  }

  return Array.from(grouped, ([id, groupTrades]) => {
    const ordered = [...groupTrades].sort(compareRepresentativePriority);
    const review = preferredReview(ordered);
    return {
      id,
      trades: ordered,
      review,
      representative: { ...ordered[0], review },
    };
  }).sort((a, b) => tradeTime(b.representative).localeCompare(tradeTime(a.representative)));
}

export function groupAccountExecutions(group: TradeReviewGroup): TradeOrder[] {
  const byAccount = new Map<string, TradeOrder[]>();
  for (const trade of group.trades) {
    const account = trade.account_label || "Default";
    byAccount.set(account, [...(byAccount.get(account) ?? []), trade]);
  }
  return Array.from(byAccount.values(), (accountTrades) => [...accountTrades].sort(compareExecutionPriority)[0])
    .sort(compareRepresentativePriority);
}

function preferredReview(trades: TradeOrder[]): TradeReview | null {
  return trades.find((trade) => isFtmo(trade) && trade.review)?.review
    ?? trades.find((trade) => trade.review)?.review
    ?? null;
}

function compareRepresentativePriority(a: TradeOrder, b: TradeOrder): number {
  const priority = (trade: TradeOrder) =>
    (isFtmo(trade) ? 100 : 0)
    + (trade.pnl_r !== null ? 40 : 0)
    + (trade.opened_at ? 20 : 0)
    + (trade.review ? 10 : 0);
  return priority(b) - priority(a) || tradeTime(b).localeCompare(tradeTime(a));
}

function compareExecutionPriority(a: TradeOrder, b: TradeOrder): number {
  const priority = (trade: TradeOrder) =>
    (trade.pnl_r !== null ? 40 : 0) + (trade.opened_at ? 20 : 0) + (trade.review ? 10 : 0);
  return priority(b) - priority(a) || tradeTime(b).localeCompare(tradeTime(a));
}

function isFtmo(trade: TradeOrder): boolean {
  return (trade.account_label || "").toLowerCase().includes("ftmo");
}

function tradeTime(trade: TradeOrder): string {
  return trade.opened_at ?? trade.closed_at ?? "";
}
