import { useQueryClient } from "@tanstack/react-query";
import { Keyboard, X } from "lucide-react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { isEditableHotkeyTarget, resolveAppHotkey } from "../lib/appHotkeys";
import { enabledPlaybookKeys, useChartStore } from "../store/chartStore";
import type { PlaybookKey } from "../types";
import { type AppPage, useNavigationStore } from "../store/navigationStore";

type AppHotkeysProps = {
  activePage: AppPage;
  reviewLocked: boolean;
};

const SHORTCUT_GROUPS = [
  {
    title: "Điều hướng",
    shortcuts: [
      ["1", "Chart"],
      ["2", "Dashboard"],
      ["3", "Journal"],
      ["4", "Weekly Journal"],
      ["5", "Calm"],
    ],
  },
  {
    title: "Chart",
    shortcuts: [
      ["T", "Chuyển H1 ↔ M15"],
      ["V", "Bật/tắt trade overlays"],
      ["P / Shift+P", "Playbook kế tiếp / trước"],
      ["R", "Reload dữ liệu chart"],
      ["M / N / H", "Thước đo / Note / Đường giá"],
      ["F / Shift+F", "Fibonacci / OTE"],
      ["Shift+V", "Fixed Range Volume Profile"],
      ["Alt+C", "Copy giá từ chart"],
    ],
  },
  {
    title: "Theo ngữ cảnh",
    shortcuts: [
      ["S", "Lưu Zone hoặc Trade Review"],
      ["Delete / Backspace", "Xóa Zone, Drawing hoặc Line đang chọn"],
      ["Esc", "Đóng hoặc bỏ chọn"],
      ["↑ ↓ ← →", "Di chuyển trong Mindful Maze"],
    ],
  },
] as const;

export function AppHotkeys({ activePage, reviewLocked }: AppHotkeysProps) {
  const queryClient = useQueryClient();
  const setPage = useNavigationStore((state) => state.setPage);
  const timeframe = useChartStore((state) => state.timeframe);
  const tradeVisibilityMode = useChartStore((state) => state.tradeVisibilityMode);
  const setTimeframe = useChartStore((state) => state.setTimeframe);
  const setTradeVisibilityMode = useChartStore((state) => state.setTradeVisibilityMode);
  const selectedPlaybooks = useChartStore((state) => state.selectedPlaybooks);
  const setSelectedPlaybooks = useChartStore((state) => state.setSelectedPlaybooks);
  const [helpOpen, setHelpOpen] = useState(false);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (helpOpen && event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        setHelpOpen(false);
        return;
      }
      if (isEditableHotkeyTarget(event.target) || event.repeat) return;

      const action = resolveAppHotkey(event);
      if (!action) return;

      if (action.kind === "navigate") {
        if (reviewLocked && (action.page === "chart" || action.page === "dashboard")) return;
        event.preventDefault();
        setPage(action.page);
        return;
      }

      if (action.kind === "show-help") {
        event.preventDefault();
        setHelpOpen(true);
        return;
      }

      if (activePage !== "chart") return;
      event.preventDefault();
      if (action.kind === "toggle-timeframe") {
        setTimeframe(timeframe === "H1" ? "M15" : "H1");
      } else if (action.kind === "toggle-trades") {
        setTradeVisibilityMode(tradeVisibilityMode === "off" ? "visible" : "off");
      } else if (action.kind === "cycle-playbook") {
        const order: PlaybookKey[] = Array.from(enabledPlaybookKeys);
        const currentIndex = selectedPlaybooks.length === 1 ? order.indexOf(selectedPlaybooks[0]) : -1;
        const nextIndex = action.direction === 1
          ? (currentIndex + 1 + order.length) % order.length
          : (currentIndex < 0 ? order.length - 1 : currentIndex - 1 + order.length) % order.length;
        setSelectedPlaybooks([order[nextIndex]]);
      } else if (action.kind === "reload-chart") {
        void queryClient.refetchQueries({ queryKey: ["chart"], type: "active" });
      }
    };

    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [activePage, helpOpen, queryClient, reviewLocked, selectedPlaybooks, setPage, setSelectedPlaybooks, setTimeframe, setTradeVisibilityMode, timeframe, tradeVisibilityMode]);

  if (!helpOpen) return null;

  return createPortal(
    <div className="fixed inset-0 z-[120] grid place-items-center bg-black/70 p-4 backdrop-blur-sm" role="presentation" onMouseDown={() => setHelpOpen(false)}>
      <section
        aria-label="Hướng dẫn phím tắt"
        aria-modal="true"
        className="w-full max-w-xl overflow-hidden rounded-2xl border border-cyan-400/25 bg-ink-900 shadow-[0_24px_90px_rgba(0,0,0,0.65)]"
        role="dialog"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-ink-700 px-5 py-4">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl border border-cyan-400/30 bg-cyan-400/10 text-cyan-300">
              <Keyboard size={20} />
            </span>
            <div>
              <h2 className="font-semibold text-slate-100">Hotkeys</h2>
              <p className="mt-0.5 text-xs text-slate-500">Thao tác nhanh mà không rời khỏi chart.</p>
            </div>
          </div>
          <button aria-label="Đóng hướng dẫn hotkey" className="grid h-9 w-9 place-items-center rounded-lg text-slate-400 hover:bg-ink-700 hover:text-slate-100" type="button" onClick={() => setHelpOpen(false)}>
            <X size={19} />
          </button>
        </header>

        <div className="grid gap-5 p-5 sm:grid-cols-2">
          {SHORTCUT_GROUPS.map((group) => (
            <div className={group.title === "Theo ngữ cảnh" ? "sm:col-span-2" : ""} key={group.title}>
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">{group.title}</h3>
              <div className={group.title === "Theo ngữ cảnh" ? "grid gap-2 sm:grid-cols-2" : "grid gap-2"}>
                {group.shortcuts.map(([keys, label]) => (
                  <div className="flex min-h-9 items-center justify-between gap-3 rounded-lg border border-ink-700 bg-ink-950/60 px-3 py-2" key={keys}>
                    <span className="text-sm text-slate-300">{label}</span>
                    <kbd className="shrink-0 rounded-md border border-slate-600 bg-ink-800 px-2 py-1 font-mono text-xs font-semibold text-cyan-200 shadow-[inset_0_-1px_0_rgba(255,255,255,0.08)]">{keys}</kbd>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        <footer className="border-t border-ink-700 px-5 py-3 text-xs text-slate-500">
          Hotkey tạm dừng khi con trỏ đang ở ô nhập liệu. Nhấn <kbd className="rounded border border-ink-600 px-1.5 py-0.5 text-slate-300">Esc</kbd> để đóng.
        </footer>
      </section>
    </div>,
    document.body,
  );
}
