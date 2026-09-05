import { describe, expect, it } from "vitest";
import type { TradeOrder, TradeReview } from "../types";
import { groupAccountExecutions, groupTradesForReview, tradeReviewGroupId } from "./tradeReviewGroups";

function trade(id: string, account: string, groupId?: string, pnlR: number | null = 1): TradeOrder {
  return {
    id,
    trade_idea_id: `idea-${id}`,
    account_label: account,
    playbook: "manual_ai_v1",
    direction: "long",
    side: "buy",
    order_type: "limit",
    status: pnlR === null ? "cancelled" : "closed",
    entry_price: 4400,
    stop_loss: 4390,
    take_profit: [4420],
    quantity: 1,
    opened_at: pnlR === null ? null : "2026-09-04T10:00:00+00:00",
    closed_at: "2026-09-04T11:00:00+00:00",
    close_price: pnlR === null ? null : 4420,
    pnl: pnlR === null ? null : 100,
    pnl_r: pnlR,
    hidden_on_chart: false,
    source: "live",
    metadata: groupId ? { execution_group_id: groupId } : {},
    review: null,
  };
}

function review(orderId: string): TradeReview {
  return {
    id: `review-${orderId}`,
    trade_order_id: orderId,
    grade: "A",
    verdict: "good_trade",
    mistake_tags: [],
    should_trade_again: "yes",
    comment: "",
    reviewer: "human",
    created_at: "2026-09-04T12:00:00+00:00",
    updated_at: "2026-09-04T12:00:00+00:00",
    metadata: {},
    strategy_review: {},
    operator_review: {},
  };
}

describe("trade review groups", () => {
  it("groups account executions by the shared execution id and prefers FTMO", () => {
    const exness = trade("exness", "Exness Personal", "setup-1", 0.33);
    const ftmo = trade("ftmo", "FTMO 100K 2-Step", "setup-1", -0.11);
    const groups = groupTradesForReview([exness, ftmo]);

    expect(groups).toHaveLength(1);
    expect(groups[0].representative.id).toBe("ftmo");
    expect(groupAccountExecutions(groups[0])).toHaveLength(2);
  });

  it("keeps orders without a verified group identity separate", () => {
    const first = trade("one", "FTMO 100K 2-Step");
    const second = trade("two", "Exness Personal");

    expect(tradeReviewGroupId(first)).not.toBe(tradeReviewGroupId(second));
    expect(groupTradesForReview([first, second])).toHaveLength(2);
  });

  it("shares an existing sibling review with the representative", () => {
    const exness = trade("exness", "Exness Personal", "setup-1");
    exness.review = review(exness.id);
    const ftmo = trade("ftmo", "FTMO 100K 2-Step", "setup-1");
    const [group] = groupTradesForReview([exness, ftmo]);

    expect(group.review?.grade).toBe("A");
    expect(group.representative.review?.trade_order_id).toBe("exness");
  });

  it("uses the filled execution instead of cancelled replacement tickets", () => {
    const cancelled = trade("cancelled", "FTMO 100K 2-Step", "setup-1", null);
    const filled = trade("filled", "FTMO 100K 2-Step", "setup-1", 1.2);
    const [group] = groupTradesForReview([cancelled, filled]);

    expect(group.representative.id).toBe("filled");
    expect(groupAccountExecutions(group)[0].id).toBe("filled");
  });
});
