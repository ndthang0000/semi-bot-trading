import { describe, expect, it } from "vitest";
import { resolveAppHotkey } from "./appHotkeys";

function keyEvent(key: string, overrides: Partial<Pick<KeyboardEvent, "altKey" | "code" | "ctrlKey" | "metaKey" | "shiftKey">> = {}) {
  return {
    altKey: false,
    code: key === "?" ? "Slash" : `Key${key.toUpperCase()}`,
    ctrlKey: false,
    key,
    metaKey: false,
    shiftKey: key === "?",
    ...overrides,
  };
}

describe("resolveAppHotkey", () => {
  it.each([
    ["1", "chart"],
    ["2", "dashboard"],
    ["3", "journal"],
    ["4", "weekly-journal"],
    ["5", "calm"],
  ])("maps %s to the %s page", (key, page) => {
    expect(resolveAppHotkey(keyEvent(key))).toEqual({ kind: "navigate", page });
  });

  it("maps chart and help actions case-insensitively", () => {
    expect(resolveAppHotkey(keyEvent("T"))).toEqual({ kind: "toggle-timeframe" });
    expect(resolveAppHotkey(keyEvent("v"))).toEqual({ kind: "toggle-trades" });
    expect(resolveAppHotkey(keyEvent("r"))).toEqual({ kind: "reload-chart" });
    expect(resolveAppHotkey(keyEvent("?"))).toEqual({ kind: "show-help" });
  });

  it("does not treat a plain slash as the help shortcut", () => {
    expect(resolveAppHotkey(keyEvent("/", { code: "Slash", shiftKey: false }))).toBeNull();
  });

  it("ignores browser and operating-system modifier shortcuts", () => {
    expect(resolveAppHotkey(keyEvent("r", { ctrlKey: true }))).toBeNull();
    expect(resolveAppHotkey(keyEvent("1", { metaKey: true }))).toBeNull();
    expect(resolveAppHotkey(keyEvent("t", { altKey: true }))).toBeNull();
  });
});
