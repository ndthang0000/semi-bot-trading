import type { AddEntityKind, PlaybookKey } from "../types";

export type AddEntityMenuKind = AddEntityKind | "manual_ai";

const ZONE_REACTION_ENTITIES: AddEntityMenuKind[] = [
  "support",
  "resistance",
  "demand_order_block",
  "supply_order_block",
  "bullish_fvg",
  "bearish_fvg",
  "consolidation",
];

export const playbookAddEntityKinds: Record<PlaybookKey, AddEntityMenuKind[]> = {
  zone_reaction_v2: ZONE_REACTION_ENTITIES,
  sr_breakout_v1: ["support", "resistance"],
  manual_ai_v1: ["manual_ai"],
  liquidity_sweep_reclaim_v1: ["buy_side_liquidity", "sell_side_liquidity"],
};

/** Multiple selected playbooks expose the union of their valid entity types. */
export function allowedAddEntityKinds(playbooks: PlaybookKey[]): Set<AddEntityMenuKind> {
  return new Set(playbooks.flatMap((playbook) => playbookAddEntityKinds[playbook]));
}
