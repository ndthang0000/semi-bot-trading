import { describe, expect, it } from "vitest";
import { playbookControlledLayers } from "./chartStore";
import { isZoneVisibleForPlaybooks, zoneDisplayName } from "../components/chart/chartCore";
import type { PriceZone } from "../types";

describe("playbook-controlled chart layers", () => {
  it("selects only Liquidity Pools and Structure for Liquidity Sweep V1", () => {
    const layers = playbookControlledLayers(["liquidity_sweep_reclaim_v1"]);

    expect(layers.showZones).toBe(true);
    expect(layers.showStructure).toBe(true);
    expect(layers.tradeVisibilityMode).toBe("off");
    expect(layers.zoneTypeVisibility).toEqual({
      support: false,
      resistance: false,
      order_block: false,
      fvg: false,
      liquidity_pool: true,
      consolidation: false,
    });
  });

  it("uses the union of requirements when several playbooks are selected", () => {
    const layers = playbookControlledLayers(["zone_reaction_v2", "liquidity_sweep_reclaim_v1"], "all");

    expect(layers.showStructure).toBe(true);
    expect(layers.tradeVisibilityMode).toBe("all");
    expect(layers.zoneTypeVisibility.support).toBe(true);
    expect(layers.zoneTypeVisibility.resistance).toBe(true);
    expect(layers.zoneTypeVisibility.fvg).toBe(true);
    expect(layers.zoneTypeVisibility.liquidity_pool).toBe(true);
    expect(layers.zoneTypeVisibility.order_block).toBe(false);
    expect(layers.zoneTypeVisibility.consolidation).toBe(false);
  });

  it("keeps Manual AI focused on Structure and ZigZag only", () => {
    const layers = playbookControlledLayers(["manual_ai_v1"]);

    expect(layers.showZones).toBe(false);
    expect(layers.showStructure).toBe(true);
    expect(layers.tradeVisibilityMode).toBe("off");
  });
});

describe("Liquidity Sweep V1 zone presentation", () => {
  it("hides historical swept events but keeps actionable liquidity zones", () => {
    const historical = liquidityZone("swept");
    const actionable = liquidityZone("active");

    expect(isZoneVisibleForPlaybooks(historical, ["liquidity_sweep_reclaim_v1"])).toBe(false);
    expect(isZoneVisibleForPlaybooks(historical, ["liquidity_sweep_reclaim_v1"], true)).toBe(true);
    expect(isZoneVisibleForPlaybooks(actionable, ["liquidity_sweep_reclaim_v1"])).toBe(true);
    expect(zoneDisplayName(historical)).toBe("Historical Liquidity Sweep");
    expect(zoneDisplayName(actionable)).toBe("Buy Liquidity Zone");
  });

  it("keeps historical events available outside the liquidity playbook view", () => {
    expect(isZoneVisibleForPlaybooks(liquidityZone("swept"), ["zone_reaction_v2"])).toBe(true);
  });
});

function liquidityZone(status: string): PriceZone {
  return {
    id: `liq-${status}`,
    type: "liquidity_pool",
    timeframe: "H1",
    direction: "bullish",
    detector: "liquidity_v1",
    status,
    source: "bot",
    price_low: 4000,
    price_high: 4010,
    visual_start: "2026-08-01T00:00:00+00:00",
    visual_end: null,
    valid_from: "2026-08-01T00:00:00+00:00",
    valid_until: null,
    invalidated_at: null,
    invalidated_by_structure_point_id: null,
    detected_at: "2026-08-01T00:00:00+00:00",
    weight: 0.7,
    confidence: 0.7,
    metadata: {},
  };
}
