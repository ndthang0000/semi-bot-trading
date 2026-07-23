import { describe, expect, it } from "vitest";
import type { TradeOrder } from "../types";
import { buildWeeklyReviewGate } from "./weeklyReview";

function trade(id: string, closedAt: string, reviewed = false): TradeOrder {
  return {
    id,
    trade_idea_id: `idea-${id}`,
    account_label: "Default",
    side: "buy",
    order_type: "market",
    status: "closed",
    playbook: "zone_reaction_v2",
    direction: "long",
    entry_price: 4100,
    stop_loss: 4090,
    take_profit: [4125],
    quantity: 1,
    opened_at: closedAt,
    closed_at: closedAt,
    close_price: 4110,
    pnl: 100,
    pnl_r: 1,
    hidden_on_chart: false,
    source: "live",
    metadata: {},
    review: reviewed
      ? {
          id: `review-${id}`,
          trade_order_id: id,
          grade: "B",
          verdict: "good_trade",
          mistake_tags: [],
          should_trade_again: "yes",
          comment: "",
          reviewer: "human",
          created_at: closedAt,
          updated_at: closedAt,
          metadata: { strategy_review: {}, operator_review: {} },
          strategy_review: {},
          operator_review: {},
        }
      : null,
  };
}

describe("buildWeeklyReviewGate", () => {
  it("does not require current-week reviews before Saturday in Vietnam time", () => {
    const result = buildWeeklyReviewGate(
      [trade("t1", "2026-07-10T10:00:00+00:00")],
      new Date("2026-07-10T12:00:00+00:00"),
    );

    expect(result.active).toBe(false);
  });

  it("requires current-week closed trades from Saturday onward", () => {
    const result = buildWeeklyReviewGate(
      [trade("t1", "2026-07-10T10:00:00+00:00")],
      new Date("2026-07-11T01:00:00+00:00"),
    );

    expect(result.active).toBe(true);
    expect(result.dueTradeIds.has("t1")).toBe(true);
  });

  it("keeps previous-week unreviewed trades due after the weekend", () => {
    const result = buildWeeklyReviewGate(
      [trade("t1", "2026-07-10T10:00:00+00:00")],
      new Date("2026-07-13T02:00:00+00:00"),
    );

    expect(result.active).toBe(true);
    expect(result.dueCount).toBe(1);
  });

  it("ignores reviewed trades", () => {
    const result = buildWeeklyReviewGate(
      [trade("t1", "2026-07-10T10:00:00+00:00", true)],
      new Date("2026-07-11T01:00:00+00:00"),
    );

    expect(result.active).toBe(false);
  });

  it("accepts structured review fields as completed review", () => {
    const reviewedTrade = trade("t1", "2026-07-10T10:00:00+00:00");
    reviewedTrade.review = {
      id: "review-t1",
      trade_order_id: "t1",
      grade: null,
      verdict: "unreviewed",
      mistake_tags: [],
      should_trade_again: "unknown",
      comment: "",
      reviewer: "human",
      created_at: "2026-07-10T10:00:00+00:00",
      updated_at: "2026-07-10T10:00:00+00:00",
      metadata: { strategy_review: { setup_validity: "valid" }, operator_review: {} },
      strategy_review: { setup_validity: "valid" },
      operator_review: {},
    };

    const result = buildWeeklyReviewGate([reviewedTrade], new Date("2026-07-11T01:00:00+00:00"));

    expect(result.active).toBe(false);
  });
});
