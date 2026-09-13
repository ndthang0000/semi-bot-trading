// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { LineReactionPanel } from "./LineReactionPanel";
import { useLineReactionStore } from "../../store/lineReactionStore";
import { authFetch } from "../../api/auth";
vi.mock("../../api/auth", () => ({ authFetch: vi.fn() }));
(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: ReturnType<typeof createRoot> | undefined;
let container: HTMLDivElement;
const showToast = vi.fn();
const sessions = [
  ["asian", "Asian", "00:00", "07:00"], ["london", "London", "07:00", "12:00"],
  ["london_ny", "London–NY", "12:00", "17:00"], ["new_york", "New York", "17:00", "21:00"],
  ["off_hours", "Off-hours", "21:00", "24:00"],
].map(([value, label, start_utc, end_utc]) => ({ value, label, start_utc, end_utc }));
afterEach(async () => { await act(async () => root?.unmount()); container?.remove(); vi.clearAllMocks(); useLineReactionStore.setState({ plans: [], draft:null, selectedId:null }); });

it("saving a drawn line creates an inert draft and requires a separate arm action", async () => {
  let plans: object[] = [];
  vi.mocked(authFetch).mockImplementation(async (path, init) => {
    if (String(path) === "/api/accounts") return new Response(JSON.stringify({ accounts: [
      { account_label: "Fund", execution: { worker_status: "online" } },
      { account_label: "Personal", execution: { worker_status: "online" } },
      { account_label: "Paused", execution: { worker_status: "offline" } },
    ] }));
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      plans = [{ ...body, id: "line-1", status: "draft", created_at: new Date().toISOString(),
        expires_at: new Date(Date.now()+3600000).toISOString(), armed_at: null, signal: null }];
      return new Response(JSON.stringify(plans[0]));
    }
    return new Response(JSON.stringify({ plans, sessions }));
  });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  useLineReactionStore.getState().setDraft({ price:3000, direction:"long", visual_start:"2026-09-06T10:00:00Z",visual_end:"2026-09-06T12:00:00Z",client_request_id:"request-1234" });
  await act(async () => root?.render(<LineReactionPanel symbol="XAUUSD" showToast={showToast} />));
  const posts = vi.mocked(authFetch).mock.calls.filter(([, options]) => options?.method === "POST");
  expect(posts).toHaveLength(1);
  expect(posts[0][0]).toBe("/api/line-reactions");
  expect(JSON.parse(String(posts[0][1]?.body))).toMatchObject({
    account_labels:["Fund", "Personal"], price:3000, visual_end:"2026-09-06T12:00:00Z",
    client_request_id:"request-1234",
    config:{recovery_mode:"session_price", recovery_price:8, recovery_ratio:2, max_stop_h1_atr:1,
      recovery_price_by_session:{asian:8, london:7, london_ny:12, new_york:10},
      partial_enabled:false, limit_offset:0, limit_ttl_minutes:30,
      trade_sessions:["asian", "london", "london_ny", "new_york"]},
  });
  expect(JSON.parse(String(posts[0][1]?.body)).account_labels).not.toContain("Paused");
  expect(container.textContent).toContain("Pausedoffline");
  expect(container.textContent).toContain("Save Arm Delete");
  expect(useLineReactionStore.getState().draft).toBeNull();
});

it("sorts line cards from highest to lowest price and distinguishes Draft from Armed", async () => {
  const config = { recovery_ratio:2, body_period:20, stop_buffer_atr:0.1, max_stop_h1_atr:1.2,
    limit_offset:5, limit_ttl_minutes:120, risk_reward:2, target_mode:"fixed_rr",
    partial_enabled:false, partial_trigger_r:1, partial_fraction:0.4 };
  const base = { account_label:"Fund", account_labels:["Fund"], created_at:new Date().toISOString(),
    expires_at:new Date(Date.now()+3600000).toISOString(), armed_at:null, signal:null,
    visual_start:null, visual_end:null, last_error:null, config };
  vi.mocked(authFetch).mockImplementation(async path => {
    if (String(path) === "/api/accounts") return new Response(JSON.stringify({ accounts: [{ account_label:"Fund", execution:{worker_status:"online"} }] }));
    return new Response(JSON.stringify({ sessions, plans: [
      { ...base, id:"low", price:4325.01, direction:"long", status:"armed" },
      { ...base, id:"high", price:4390.20, direction:"short", status:"draft" },
      { ...base, id:"middle", price:4364.09, direction:"short", status:"draft" },
    ] }));
  });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  await act(async () => root?.render(<LineReactionPanel symbol="XAUUSD" showToast={showToast} />));
  const prices = Array.from(container.querySelectorAll("button strong.font-mono"), node => node.textContent);
  expect(prices).toEqual(["4390.20", "4364.09", "4325.01"]);
  const badges = Array.from(container.querySelectorAll("button span.uppercase"));
  expect(badges.find(node => node.textContent === "draft")?.className).toContain("amber");
  expect(badges.find(node => node.textContent === "armed")?.className).toContain("emerald");
});

it("saves a 1.25R break-even configuration on an armed line", async () => {
  const config = { recovery_ratio:2, body_period:20, stop_buffer_atr:0.1, max_stop_h1_atr:1.2,
    limit_offset:5, limit_ttl_minutes:120, risk_reward:2, target_mode:"fixed_rr",
    partial_enabled:true, partial_trigger_r:1, partial_fraction:0, trade_sessions:["london"] };
  const plan = { id:"armed-line", account_label:"Fund", account_labels:["Fund"],
    price:4330, direction:"long", status:"armed", created_at:new Date().toISOString(),
    updated_at:new Date().toISOString(), armed_at:new Date().toISOString(), signal:null,
    expires_at:new Date(Date.now()+3600000).toISOString(), visual_start:null, visual_end:null,
    last_error:null, config };
  vi.mocked(authFetch).mockImplementation(async (path, init) => {
    if (String(path) === "/api/accounts") return new Response(JSON.stringify({ accounts: [
      { account_label:"Fund", execution:{worker_status:"online"} },
    ] }));
    if (init?.method === "PATCH") {
      const body = JSON.parse(String(init.body));
      return new Response(JSON.stringify({ ...plan, config:body.config, updated_at:new Date().toISOString() }));
    }
    return new Response(JSON.stringify({ sessions, plans:[plan] }));
  });
  useLineReactionStore.setState({ plans:[plan], draft:null, selectedId:plan.id });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  await act(async () => root?.render(<LineReactionPanel symbol="XAUUSD" showToast={showToast} />));

  const triggerInput = Array.from(container.querySelectorAll("label"))
    .find(label => label.textContent?.startsWith("Trigger R"))?.querySelector("input");
  const recoveryInput = Array.from(container.querySelectorAll("label"))
    .find(label => label.textContent?.startsWith("Recovery / body"))?.querySelector("input");
  const limitOffsetInput = Array.from(container.querySelectorAll("label"))
    .find(label => label.textContent?.startsWith("Trả giá từ close"))?.querySelector("input");
  expect(triggerInput?.step).toBe("0.05");
  expect(recoveryInput).toMatchObject({ min:"1", max:"10", step:"0.1" });
  expect(limitOffsetInput?.step).toBe("0.5");
  await act(async () => {
    if (!triggerInput || !recoveryInput) throw new Error("Line config input not found");
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(triggerInput, "1.25");
    triggerInput.dispatchEvent(new Event("input", { bubbles:true }));
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(recoveryInput, "1.2");
    recoveryInput.dispatchEvent(new Event("input", { bubbles:true }));
  });
  const save = Array.from(container.querySelectorAll("button")).find(button => button.textContent?.trim() === "Save");
  await act(async () => save?.click());

  const patchCall = vi.mocked(authFetch).mock.calls.find(([, options]) => options?.method === "PATCH");
  expect(patchCall?.[0]).toBe("/api/line-reactions/armed-line");
  expect(JSON.parse(String(patchCall?.[1]?.body)).config.partial_trigger_r).toBe(1.25);
  expect(JSON.parse(String(patchCall?.[1]?.body)).config.recovery_ratio).toBe(1.2);
  expect(showToast).toHaveBeenCalledWith("success", "Đã lưu cấu hình Line Reaction.");
  expect(container.querySelector('input[aria-label="Giá Line"]')).toBeNull();
  await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="Sửa giá Line"]')?.click());
  const priceInput = container.querySelector<HTMLInputElement>('input[aria-label="Giá Line"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(priceInput, "4330.5");
    priceInput.dispatchEvent(new Event("input", { bubbles:true }));
  });
  await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="Lưu giá Line"]')?.click());
  const priceCall = vi.mocked(authFetch).mock.calls.filter(([, options]) => options?.method === "PATCH").at(-1);
  expect(JSON.parse(String(priceCall?.[1]?.body)).price).toBe(4330.5);
});

it("shows the API error in a toast when saving fails", async () => {
  const config = { recovery_ratio:2, body_period:20, stop_buffer_atr:0.1, max_stop_h1_atr:1.2,
    limit_offset:5, limit_ttl_minutes:120, risk_reward:2, target_mode:"fixed_rr",
    partial_enabled:false, partial_trigger_r:1, partial_fraction:0.4, trade_sessions:["london"] };
  const plan = { id:"failed-save", account_label:"Fund", account_labels:["Fund"],
    price:4330, direction:"long", status:"armed", created_at:new Date().toISOString(),
    updated_at:new Date().toISOString(), armed_at:new Date().toISOString(), signal:null,
    expires_at:new Date(Date.now()+3600000).toISOString(), visual_start:null, visual_end:null,
    last_error:null, config };
  vi.mocked(authFetch).mockImplementation(async (path, init) => {
    if (String(path) === "/api/accounts") return new Response(JSON.stringify({ accounts: [
      { account_label:"Fund", execution:{worker_status:"online"} },
    ] }));
    if (init?.method === "PATCH") return new Response(
      JSON.stringify({ detail:"Only Draft or Armed lines can be edited" }),
      { status:409 },
    );
    return new Response(JSON.stringify({ sessions, plans:[plan] }));
  });
  useLineReactionStore.setState({ plans:[plan], draft:null, selectedId:plan.id });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  await act(async () => root?.render(<LineReactionPanel symbol="XAUUSD" showToast={showToast} />));
  const save = Array.from(container.querySelectorAll("button")).find(button => button.textContent?.trim() === "Save");
  await act(async () => save?.click());

  expect(showToast).toHaveBeenCalledWith(
    "error",
    "Không thể lưu Line: Only Draft or Armed lines can be edited",
  );
  expect(container.textContent).toContain("Only Draft or Armed lines can be edited");
});
