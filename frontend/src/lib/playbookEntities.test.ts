import { describe, expect, it } from "vitest";
import { allowedAddEntityKinds } from "./playbookEntities";

describe("playbook Add entity routing", () => {
  it("exposes only Manual AI trade for Manual AI", () => {
    expect([...allowedAddEntityKinds(["manual_ai_v1"])]).toEqual(["manual_ai"]);
  });

  it("exposes only Buy/Sell liquidity zones for Liquidity Sweep", () => {
    expect([...allowedAddEntityKinds(["liquidity_sweep_reclaim_v1"])]).toEqual([
      "buy_side_liquidity",
      "sell_side_liquidity",
    ]);
  });

  it("keeps the remaining manual zone entities under Zone Reaction V2", () => {
    const kinds = allowedAddEntityKinds(["zone_reaction_v2"]);
    expect(kinds.has("manual_ai")).toBe(false);
    expect(kinds.has("buy_side_liquidity")).toBe(false);
    expect(kinds.has("sell_side_liquidity")).toBe(false);
    expect(kinds).toEqual(new Set([
      "support",
      "resistance",
      "demand_order_block",
      "supply_order_block",
      "bullish_fvg",
      "bearish_fvg",
      "consolidation",
    ]));
  });

  it("uses the union when several playbooks are selected", () => {
    const kinds = allowedAddEntityKinds(["manual_ai_v1", "liquidity_sweep_reclaim_v1"]);
    expect(kinds).toEqual(new Set(["manual_ai", "buy_side_liquidity", "sell_side_liquidity"]));
  });

  it("exposes line drawing only for Line Reaction V1", () => {
    expect(allowedAddEntityKinds(["line_reaction_v1"])).toEqual(new Set(["line_buy", "line_sell"]));
    expect(allowedAddEntityKinds(["zone_reaction_v2"]).has("line_buy")).toBe(false);
  });
});
