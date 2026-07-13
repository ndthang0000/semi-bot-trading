export const TRADE_REACTION_FILTERS = ["reject", "fakeout", "waiting_bos", "slow_reaction"] as const;

const TRADE_REACTION_FILTER_SET = new Set<string>(TRADE_REACTION_FILTERS);

export function normalizeTradeReactionFilter(value: unknown): string {
  return typeof value === "string" && TRADE_REACTION_FILTER_SET.has(value) ? value : "";
}
