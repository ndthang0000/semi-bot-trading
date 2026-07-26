import { Check } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { CalmGameProps } from "./gameTypes";

const PALETTE = [
  { id: 1, color: "#67e8f9", label: "Cyan" },
  { id: 2, color: "#a78bfa", label: "Violet" },
  { id: 3, color: "#f9a8d4", label: "Rose" },
  { id: 4, color: "#6ee7b7", label: "Mint" },
] as const;

const PATTERNS = [
  [
    2, 2, 1, 1, 2, 2,
    2, 1, 1, 1, 1, 2,
    1, 1, 4, 4, 1, 1,
    1, 4, 4, 4, 4, 1,
    3, 3, 4, 4, 3, 3,
    3, 3, 3, 3, 3, 3,
  ],
  [
    1, 1, 2, 2, 1, 1,
    1, 2, 2, 2, 2, 1,
    2, 2, 3, 3, 2, 2,
    2, 3, 3, 3, 3, 2,
    4, 4, 3, 3, 4, 4,
    4, 4, 4, 4, 4, 4,
  ],
  [
    4, 4, 1, 1, 4, 4,
    4, 1, 1, 1, 1, 4,
    1, 1, 2, 2, 1, 1,
    1, 2, 2, 2, 2, 1,
    3, 3, 2, 2, 3, 3,
    3, 3, 3, 3, 3, 3,
  ],
] as const;

export function PixelCalmGame({ onComplete }: CalmGameProps) {
  const pattern = useMemo(() => PATTERNS[Math.floor(Math.random() * PATTERNS.length)], []);
  const [selectedColor, setSelectedColor] = useState(1);
  const [filled, setFilled] = useState<Set<number>>(new Set());
  const completedRef = useRef(false);

  useEffect(() => {
    if (completedRef.current || filled.size !== pattern.length) return;
    completedRef.current = true;
    const timer = window.setTimeout(onComplete, 450);
    return () => window.clearTimeout(timer);
  }, [filled.size, onComplete, pattern.length]);

  const fill = (index: number) => {
    if (filled.has(index) || pattern[index] !== selectedColor) return;
    setFilled((current) => new Set([...current, index]));
  };

  return (
    <div className="flex h-full min-h-[500px] flex-col items-center justify-center">
      <div className="mb-5 text-center">
        <div className="text-xs font-bold uppercase tracking-[0.22em] text-pink-300">Tô từng ô một</div>
        <div className="mt-1 text-xs text-slate-600">Chọn màu rồi tìm đúng số · chọn sai không bị phạt</div>
      </div>

      <div className="grid grid-cols-6 gap-1.5 rounded-2xl border border-ink-700 bg-ink-950 p-3 shadow-[0_0_60px_rgba(249,168,212,0.08)]">
        {pattern.map((colorId, index) => {
          const palette = PALETTE[colorId - 1];
          const isFilled = filled.has(index);
          return (
            <button
              key={index}
              type="button"
              aria-label={`Ô số ${colorId}`}
              onClick={() => fill(index)}
              className="grid h-12 w-12 place-items-center rounded-lg border text-xs font-bold transition-transform hover:scale-[1.03]"
              style={{
                borderColor: isFilled ? palette.color : "rgba(51,65,85,0.65)",
                backgroundColor: isFilled ? `${palette.color}CC` : "rgba(15,23,42,0.72)",
                color: isFilled ? "#081018" : "rgb(100,116,139)",
              }}
            >
              {isFilled ? <Check size={15} /> : colorId}
            </button>
          );
        })}
      </div>

      <div className="mt-5 flex gap-2">
        {PALETTE.map((item) => (
          <button
            key={item.id}
            type="button"
            aria-label={`Chọn màu ${item.label}`}
            onClick={() => setSelectedColor(item.id)}
            className={`grid h-11 w-11 place-items-center rounded-full border-2 transition-transform hover:scale-105 ${
              selectedColor === item.id ? "scale-110 border-white" : "border-transparent"
            }`}
            style={{ backgroundColor: item.color }}
          >
            <span className="text-xs font-black text-ink-950">{item.id}</span>
          </button>
        ))}
      </div>
      <div className="mt-4 text-[10px] uppercase tracking-[0.16em] text-slate-600">
        Đã tô {filled.size}/{pattern.length} ô
      </div>
    </div>
  );
}
