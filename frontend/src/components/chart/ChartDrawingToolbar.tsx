import { Copy, GripVertical, Minus, MousePointer2, Ruler, Type } from "lucide-react";
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { ChartDrawingTool } from "../../types";

type Props = {
  activeTool: ChartDrawingTool;
  onToolChange: (tool: ChartDrawingTool) => void;
};

const STORAGE_KEY = "semi-bot-chart-drawing-toolbar-position-v1";

const tools: Array<{ key: ChartDrawingTool; label: string; hotkey: string; icon: typeof Ruler | null }> = [
  { key: "cursor", label: "Con trỏ", hotkey: "Esc", icon: MousePointer2 },
  { key: "measure", label: "Thước đo", hotkey: "M", icon: Ruler },
  { key: "horizontal_line", label: "Đường giá ngang", hotkey: "H", icon: Minus },
  { key: "fib_standard", label: "Fibonacci Retracement", hotkey: "F", icon: null },
  { key: "fib_ote", label: "Fibonacci OTE", hotkey: "Shift+F", icon: null },
  { key: "note", label: "Ghi chú", hotkey: "N", icon: Type },
  { key: "copy_price", label: "Copy giá tại điểm click", hotkey: "Alt+C", icon: Copy },
];

export function ChartDrawingToolbar({ activeTool, onToolChange }: Props) {
  const toolbarRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ pointerX: number; pointerY: number; x: number; y: number } | null>(null);
  const [position, setPosition] = useState(() => readPosition());

  const clampPosition = (x: number, y: number) => {
    const toolbar = toolbarRef.current;
    const parent = toolbar?.parentElement;
    if (!toolbar || !parent) return { x, y };
    return {
      x: Math.min(Math.max(8, x), Math.max(8, parent.clientWidth - toolbar.offsetWidth - 8)),
      y: Math.min(Math.max(8, y), Math.max(8, parent.clientHeight - toolbar.offsetHeight - 8)),
    };
  };

  useEffect(() => {
    const keepInsideChart = () => setPosition((current) => clampPosition(current.x, current.y));
    keepInsideChart();
    window.addEventListener("resize", keepInsideChart);
    return () => window.removeEventListener("resize", keepInsideChart);
  }, []);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(position));
  }, [position]);

  const startDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    dragRef.current = { pointerX: event.clientX, pointerY: event.clientY, ...position };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const drag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    if (!dragRef.current) return;
    event.preventDefault();
    const next = clampPosition(
      dragRef.current.x + event.clientX - dragRef.current.pointerX,
      dragRef.current.y + event.clientY - dragRef.current.pointerY,
    );
    setPosition(next);
  };

  const stopDrag = (event: ReactPointerEvent<HTMLButtonElement>) => {
    dragRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };

  return (
    <div
      ref={toolbarRef}
      aria-label="Công cụ vẽ chart"
      className="absolute z-[70] hidden max-w-[calc(100%-16px)] items-center overflow-x-auto rounded-xl border border-white/10 bg-[#202124]/95 p-1.5 text-slate-200 shadow-[0_10px_28px_rgba(0,0,0,0.48)] backdrop-blur-md lg:flex"
      style={{ left: position.x, top: position.y }}
      onClick={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
      role="toolbar"
    >
      <button
        aria-label="Kéo để di chuyển thanh công cụ"
        className="mr-1 grid h-9 w-7 shrink-0 cursor-grab touch-none place-items-center rounded-lg text-slate-500 hover:bg-white/5 hover:text-slate-300 active:cursor-grabbing"
        title="Kéo để di chuyển"
        type="button"
        onPointerDown={startDrag}
        onPointerMove={drag}
        onPointerUp={stopDrag}
        onPointerCancel={stopDrag}
      >
        <GripVertical size={18} />
      </button>
      <span className="mr-1 h-7 w-px shrink-0 bg-white/10" />
      {tools.map((tool) => {
        const Icon = tool.icon;
        const active = activeTool === tool.key;
        return (
          <button
            key={tool.key}
            aria-pressed={active}
            className={`grid h-9 min-w-9 shrink-0 place-items-center rounded-lg px-2 transition ${
              active ? "bg-cyan-400/18 text-cyan-200 ring-1 ring-cyan-300/50" : "text-slate-300 hover:bg-white/8 hover:text-white"
            }`}
            title={`${tool.label} (${tool.hotkey})`}
            type="button"
            onClick={() => onToolChange(active && tool.key !== "cursor" ? "cursor" : tool.key)}
          >
            {Icon ? <Icon size={19} strokeWidth={1.8} /> : <FibonacciIcon variant={tool.key === "fib_ote" ? "ote" : "standard"} />}
            <span className="sr-only">{tool.label}</span>
          </button>
        );
      })}
    </div>
  );
}

function FibonacciIcon({ variant }: { variant: "standard" | "ote" }) {
  return (
    <svg aria-hidden="true" className={variant === "ote" ? "text-amber-300" : "text-violet-200"} height="22" viewBox="0 0 24 24" width="22">
      {variant === "ote" ? <rect fill="currentColor" opacity="0.22" x="3" y="9" width="18" height="6" rx="1" /> : null}
      <path d="M3 5.5h18M3 9.5h18M3 14.5h18M3 18.5h18" fill="none" stroke="currentColor" strokeWidth="1.25" />
      {variant === "standard" ? (
        <path d="M4 19 20 5" fill="none" stroke="currentColor" strokeDasharray="2 2" strokeWidth="1.2" />
      ) : (
        <path d="M5 7v10M19 7v10" fill="none" stroke="currentColor" strokeWidth="1.4" />
      )}
      <circle cx={variant === "standard" ? 4 : 5} cy={variant === "standard" ? 19 : 12} fill="#202124" r="1.8" stroke="currentColor" strokeWidth="1.2" />
      <circle cx={variant === "standard" ? 20 : 19} cy={variant === "standard" ? 5 : 12} fill="#202124" r="1.8" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

function readPosition(): { x: number; y: number } {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
    if (Number.isFinite(value?.x) && Number.isFinite(value?.y)) return value;
  } catch {
    // Ignore invalid local storage written by an older UI.
  }
  return { x: 28, y: 360 };
}
