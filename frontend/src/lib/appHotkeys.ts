import type { AppPage } from "../store/navigationStore";

export type AppHotkeyAction =
  | { kind: "navigate"; page: AppPage }
  | { kind: "toggle-timeframe" }
  | { kind: "toggle-trades" }
  | { kind: "cycle-playbook"; direction: 1 | -1 }
  | { kind: "reload-chart" }
  | { kind: "show-help" };

const PAGE_HOTKEYS: Record<string, AppPage> = {
  "1": "chart",
  "2": "dashboard",
  "3": "journal",
  "4": "weekly-journal",
  "5": "calm",
};

export function resolveAppHotkey(event: Pick<KeyboardEvent, "altKey" | "code" | "ctrlKey" | "key" | "metaKey" | "shiftKey">): AppHotkeyAction | null {
  if (event.ctrlKey || event.metaKey || event.altKey) return null;

  const page = PAGE_HOTKEYS[event.key];
  if (page) return { kind: "navigate", page };

  const key = event.key.toLowerCase();
  if (key === "t") return { kind: "toggle-timeframe" };
  if (key === "v") return { kind: "toggle-trades" };
  if (key === "p") return { kind: "cycle-playbook", direction: event.shiftKey ? -1 : 1 };
  if (key === "r") return { kind: "reload-chart" };
  if (event.key === "?" || (event.code === "Slash" && event.shiftKey)) return { kind: "show-help" };
  return null;
}

export function isEditableHotkeyTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName.toLowerCase();
  return tagName === "input" || tagName === "textarea" || tagName === "select" || target.isContentEditable;
}
