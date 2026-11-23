// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChartDrawing } from "../../types";
import { ChartDrawingLayer, type RenderedChartDrawing } from "./ChartDrawingLayer";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const drawing: ChartDrawing = {
  id: "volume-profile-1",
  symbol: "XAUUSD",
  drawing_type: "volume_profile_fixed_range",
  origin_timeframe: "H1",
  visible_timeframes: ["H1", "M15", "M5"],
  anchors: [
    { time: "2026-11-20T00:00:00+00:00", price: 3500 },
    { time: "2026-11-21T00:00:00+00:00", price: 3600 },
  ],
  properties: {},
  content: null,
  locked: false,
  hidden: false,
  revision: 1,
  created_by: "human",
  created_at: "2026-11-21T00:00:00+00:00",
  updated_at: "2026-11-21T00:00:00+00:00",
  volume_profile: {
    source_timeframe: "M1",
    volume_kind: "tick_volume",
    tick_size: 0.01,
    tick_size_source: "symbol_info",
    range_start: "2026-11-20T00:00:00+00:00",
    range_end: "2026-11-21T00:00:00+00:00",
    source_bar_count: 1000,
    total_volume: 100,
    profile_low: 3500,
    profile_high: 3600,
    row_size: 100,
    poc: 3550,
    vah: 3580,
    val: 3520,
    settings: {
      rows: 24,
      value_area_pct: 70,
      mode: "up_down",
      width_pct: 30,
      placement: "left",
      show_poc: true,
      show_vah: true,
      show_val: true,
    },
    rows: [],
  },
};

const renderedDrawing: RenderedChartDrawing = {
  drawing,
  points: [
    { x: 100, y: 180, price: 3500, time: drawing.anchors[0].time },
    { x: 400, y: 80, price: 3600, time: drawing.anchors[1].time },
  ],
  volumeProfile: {
    rows: [{
      index: 0,
      price_low: 3500,
      price_high: 3600,
      price_mid: 3550,
      up_volume: 60,
      down_volume: 40,
      total_volume: 100,
      delta: 20,
      in_value_area: true,
      y: 80,
      height: 100,
    }],
    pocY: 130,
    vahY: 100,
    valY: 160,
  },
};

let root: Root | null = null;
let container: HTMLDivElement | null = null;

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = null;
  container = null;
});

describe("ChartDrawingLayer Volume Profile selection", () => {
  it("renders a compact VP tag that selects the profile", async () => {
    const onSelect = vi.fn();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    await act(async () => root?.render(
      <ChartDrawingLayer
        drawings={[renderedDrawing]}
        measure={null}
        fibExtensionPreview={null}
        priceGuide={null}
        plotWidth={800}
        selectedId={null}
        onSelect={onSelect}
        onDelete={vi.fn()}
        onMoveStart={vi.fn()}
        onRangeMoveStart={vi.fn()}
      />,
    ));

    const tag = container.querySelector<HTMLButtonElement>('button[aria-label="Select Volume Profile"]');
    expect(tag?.textContent).toBe("VP");
    await act(async () => tag?.click());
    expect(onSelect).toHaveBeenCalledWith(drawing);
  });
});
