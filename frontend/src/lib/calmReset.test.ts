import { describe, expect, it } from "vitest";
import { drawMessageIndex, groupClosedTrades, LOSS_MESSAGES, WIN_MESSAGES } from "./calmReset";
import type { TradeOrder } from "../types";

describe("Calm Reset messages", () => {
  it("keeps ten messages for each trade outcome", () => {
    expect(WIN_MESSAGES).toHaveLength(10);
    expect(LOSS_MESSAGES).toHaveLength(10);
  });

  it("uses every message before starting a new shuffled deck", () => {
    let state = { remaining: [] as number[], lastIndex: null as number | null };
    const firstDeck: number[] = [];
    for (let index = 0; index < 10; index += 1) {
      const draw = drawMessageIndex(10, state, () => 0.25);
      firstDeck.push(draw.index);
      state = draw.state;
    }
    expect(new Set(firstDeck).size).toBe(10);

    const next = drawMessageIndex(10, state, () => 0.25);
    expect(next.index).not.toBe(firstDeck.at(-1));
  });
});

describe("Calm Reset trade grouping", () => {
  it("groups account executions for the same candidate into one event", () => {
    const trades = [
      trade("ftmo", "FTMO 100K", 0.82),
      trade("exness", "Exness Personal", 0.81),
    ];

    const events = groupClosedTrades(trades);

    expect(events).toHaveLength(1);
    expect(events[0].outcome).toBe("win");
    expect(events[0].pnlR).toBeCloseTo(0.815);
    expect(events[0].accountLabels).toEqual(["FTMO 100K", "Exness Personal"]);
  });

  it("does not react to a partial take profit while the trade remains open", () => {
    const partial = trade("partial", "Exness Personal", 0.6);
    partial.status = "filled";
    partial.closed_at = null;

    expect(groupClosedTrades([partial])).toEqual([]);
  });
});

function trade(id: string, accountLabel: string, pnlR: number): TradeOrder {
  return {
    id,
    trade_idea_id: `idea-${id}`,
    account_label: accountLabel,
    playbook: "zone_reaction_v2",
    direction: "long",
    side: "buy",
    order_type: "market",
    status: "closed",
    entry_price: 4_000,
    stop_loss: 3_980,
    take_profit: [4_050],
    quantity: 0.5,
    opened_at: "2026-07-26T00:00:00+00:00",
    closed_at: "2026-07-26T01:00:00+00:00",
    close_price: 4_020,
    pnl: 800,
    pnl_r: pnlR,
    hidden_on_chart: false,
    source: "live",
    metadata: { candidate_id: "candidate-shared" },
  };
}
