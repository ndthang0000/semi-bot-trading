// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { LineReactionLayer } from "./LineReactionLayer";
import { useLineReactionStore, type LinePlan } from "../../store/lineReactionStore";
import { updateLineReaction, updateLinePrice } from "../../api/lineReaction";

vi.mock("../../api/lineReaction", () => ({ updateLineReaction: vi.fn(), updateLinePrice: vi.fn() }));
vi.mock("../../store/chartStore", () => ({
  useChartStore: { getState: () => ({ setSelected: vi.fn(), setInspectorTab: vi.fn() }) },
}));
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const start = "2026-09-06T10:00:00.000Z";
const end = "2026-09-06T11:00:00.000Z";
const config = {
  recovery_ratio: 2, body_period: 20, stop_buffer_atr: 0.1, max_stop_h1_atr: 1.2,
  limit_offset: 5, limit_ttl_minutes: 120, risk_reward: 2, target_mode: "fixed_rr",
  partial_enabled: false, partial_trigger_r: 1, partial_fraction: 0.4, trade_sessions: ["london"],
};
const plan: LinePlan = {
  id: "line-1", symbol: "XAUUSD", account_label: "Fund", account_labels: ["Fund"], price: 3000,
  direction: "long", status: "draft", created_at: start, armed_at: null, expires_at: end,
  last_error: null, config, signal: null, visual_start: start, visual_end: end,
};
const base = Date.parse(start) / 1000;
const timeScale = {
  timeToCoordinate: vi.fn((time: number) => (Number(time) - base) / 36),
  coordinateToTime: vi.fn((x: number) => (base + x * 36)),
  width: vi.fn(() => 500),
};
const chart = { timeScale: () => timeScale, chartElement: () => ({ getBoundingClientRect: () => ({ left: 0, top: 0 }) }) };
const series = { priceToCoordinate: () => 50, coordinateToPrice: (y: number) => 3050 - y };
const candles = [
  { time: start, open: 3000, high: 3001, low: 2999, close: 3000 },
  { time: end, open: 3000, high: 3001, low: 2999, close: 3000 },
];

let root: ReturnType<typeof createRoot> | undefined;
let container: HTMLDivElement;
afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  useLineReactionStore.setState({ plans: [], draft: null, selectedId: null });
});

function renderLayer() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  useLineReactionStore.setState({ plans: [plan], draft: null, selectedId: null });
  return act(async () => root?.render(<LineReactionLayer
    chartRef={{ current: chart } as never}
    seriesRef={{ current: series } as never}
    candles={candles as never}
  />));
}

it("renders Draft dashed and selects the line from the chart", async () => {
  const interval = vi.spyOn(window, "setInterval");
  await renderLayer();
  expect(interval).not.toHaveBeenCalled();
  const line = container.querySelector<HTMLElement>("[data-line-reaction='true']");
  expect(line?.className).toContain("border-dashed");
  expect(line?.className).toContain("text-[9px]");
  expect(line?.className).toContain("leading-[11px]");
  await act(async () => line?.click());
  expect(useLineReactionStore.getState().selectedId).toBe("line-1");
  expect(container.querySelectorAll("button")).toHaveLength(2);
  await act(async () => useLineReactionStore.getState().setPlans([{ ...plan, status: "armed" }]));
  const armedLine = container.querySelector<HTMLElement>("[data-line-reaction='true']");
  expect(armedLine?.className).toContain("border-solid");
  expect(armedLine?.className).toContain("border-t");
  expect(armedLine?.className).not.toContain("border-t-2");
});

it("resizes the right endpoint without moving the start", async () => {
  await renderLayer();
  await act(async () => useLineReactionStore.getState().select("line-1"));
  const updated = { ...plan, visual_end: "2026-09-06T12:00:00.000Z", expires_at: "2026-09-06T12:00:00.000Z" };
  vi.mocked(updateLineReaction).mockResolvedValue(updated);
  const handle = container.querySelector<HTMLButtonElement>("button[aria-label='Kéo đầu phải Line']");
  await act(async () => {
    handle?.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, clientX: 100 }));
    window.dispatchEvent(new MouseEvent("pointermove", { bubbles: true, clientX: 200 }));
    window.dispatchEvent(new MouseEvent("pointerup", { bubbles: true, clientX: 200 }));
    await Promise.resolve();
  });
  expect(updateLineReaction).toHaveBeenCalledOnce();
  expect(vi.mocked(updateLineReaction).mock.calls[0][1]).toMatchObject({
    visual_start: start,
    visual_end: "2026-09-06T12:00:00+00:00",
  });
  expect(useLineReactionStore.getState().plans[0].visual_end).toBe("2026-09-06T12:00:00.000Z");
});

it("moves selected price by 0.5 with arrows and ignores inputs and locked lines", async () => {
  await renderLayer();
  await act(async () => useLineReactionStore.getState().select(plan.id));
  vi.mocked(updateLinePrice).mockImplementation(async (item, price) => ({ ...item, price }));
  await act(async () => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true })); });
  expect(updateLinePrice).toHaveBeenLastCalledWith(plan, 3000.5);
  await act(async () => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })); });
  expect(useLineReactionStore.getState().plans[0].price).toBe(3000);
  const input = document.createElement("input"); container.appendChild(input);
  await act(async () => { input.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true })); });
  await act(async () => useLineReactionStore.getState().setPlans([{ ...plan, status: "open" }]));
  await act(async () => { window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true })); });
  expect(updateLinePrice).toHaveBeenCalledTimes(2);
});

it("drags price vertically without changing time endpoints", async () => {
  await renderLayer();
  await act(async () => useLineReactionStore.getState().select(plan.id));
  vi.mocked(updateLinePrice).mockImplementation(async (item, price) => ({ ...item, price }));
  const line = container.querySelector<HTMLElement>("[data-line-reaction='true']")!;
  await act(async () => {
    line.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, clientX: 20, clientY: 50 }));
    window.dispatchEvent(new MouseEvent("pointermove", { clientX: 80, clientY: 40 }));
    window.dispatchEvent(new MouseEvent("pointerup"));
  });
  expect(updateLinePrice).toHaveBeenCalledWith(plan, 3010);
  expect(useLineReactionStore.getState().plans[0].visual_start).toBe(start);
  expect(useLineReactionStore.getState().plans[0].visual_end).toBe(end);
});
