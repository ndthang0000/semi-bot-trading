import { describe, expect, it } from "vitest";
import type { TradeOrder } from "../../types";
import { filterTradesByAccount, groupTradeBoxesByCandidate, tradeAccountCount, type TradeBox } from "./tradeOverlay";

function trade(id: string, accountLabel: string, candidateId: string): TradeOrder {
  return {
    id,
    trade_idea_id: `idea-${id}`,
    account_label: accountLabel,
    playbook: "h1_impulse_retest_v1",
    direction: "short",
    side: "sell",
    order_type: "limit",
    status: "filled",
    entry_price: 4650,
    stop_loss: 4664,
    take_profit: [4597],
    quantity: 0.1,
    opened_at: "2026-08-25T05:21:31Z",
    closed_at: null,
    close_price: null,
    pnl: null,
    pnl_r: null,
    hidden_on_chart: false,
    source: "live",
    metadata: {
      candidate_id: candidateId,
      execution_group_id: "h1-shared-client",
    },
  };
}

function box(item: TradeOrder, x: number): TradeBox {
  return {
    trade: item,
    trades: [item],
    x,
    y: 10,
    width: 20,
    height: 40,
    profit: { x, y: 30, width: 20, height: 20 },
    loss: { x, y: 10, width: 20, height: 20 },
  };
}

describe("H1 multi-account trade grouping", () => {
  it("keeps only trades belonging to the selected account", () => {
    const exness = trade("exness-order", "Exness Personal", "exness-plan-id");
    const ftmo = trade("ftmo-order", "FTMO 100K 2-Step", "ftmo-plan-id");

    expect(filterTradesByAccount([exness, ftmo], "Exness Personal")).toEqual([exness]);
    expect(filterTradesByAccount([exness, ftmo], null)).toEqual([exness, ftmo]);
  });

  it("groups account-specific plan ids by their shared execution client id", () => {
    const exness = trade("exness-order", "Exness Personal", "exness-plan-id");
    const ftmo = trade("ftmo-order", "FTMO 100K 2-Step", "ftmo-plan-id");

    const grouped = groupTradeBoxesByCandidate([box(exness, 10), box(ftmo, 12)]);

    expect(grouped).toHaveLength(1);
    expect(grouped[0].trades).toHaveLength(2);
    expect(tradeAccountCount(grouped[0].trades)).toBe(2);
  });

  it("counts distinct accounts instead of lifecycle rows", () => {
    const first = trade("first", "Exness Personal", "plan-id");
    const duplicate = trade("second", "Exness Personal", "plan-id");

    expect(tradeAccountCount([first, duplicate])).toBe(1);
  });
});
