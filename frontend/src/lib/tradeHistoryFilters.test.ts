import { describe, expect, it } from "vitest";
import { normalizeTradeReactionFilter } from "./tradeHistoryFilters";

describe("normalizeTradeReactionFilter", () => {
  it("keeps supported reaction filters", () => {
    expect(normalizeTradeReactionFilter("reject")).toBe("reject");
    expect(normalizeTradeReactionFilter("slow_reaction")).toBe("slow_reaction");
  });

  it("clears removed or malformed persisted filters", () => {
    expect(normalizeTradeReactionFilter("removed_reaction")).toBe("");
    expect(normalizeTradeReactionFilter(null)).toBe("");
  });
});
