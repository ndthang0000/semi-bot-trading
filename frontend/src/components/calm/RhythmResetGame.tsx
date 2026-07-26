import { useEffect, useRef, useState } from "react";
import type { CalmGameProps } from "./gameTypes";

const CYCLE_SECONDS = 12;
const MIN_GAME_SECONDS = 48;
const REQUIRED_TAPS = 3;

export function RhythmResetGame({ onComplete }: CalmGameProps) {
  const [startedAt] = useState(() => Date.now());
  const [elapsed, setElapsed] = useState(0);
  const [tappedCycles, setTappedCycles] = useState<Set<number>>(new Set());
  const completedRef = useRef(false);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setElapsed((Date.now() - startedAt) / 1_000);
    }, 100);
    return () => window.clearInterval(timer);
  }, [startedAt]);

  const cycle = Math.floor(elapsed / CYCLE_SECONDS);
  const withinCycle = elapsed % CYCLE_SECONDS;
  const phase = breathingPhase(withinCycle);
  const circleSize = breathingCircleSize(withinCycle);
  const canTap = phase.key === "exhale" && !tappedCycles.has(cycle);
  const secondsRemaining = Math.max(0, Math.ceil(MIN_GAME_SECONDS - elapsed));
  const progressDots = Array.from(
    { length: 4 },
    (_, index) => elapsed >= (index + 1) * CYCLE_SECONDS,
  );

  useEffect(() => {
    if (
      !completedRef.current
      && elapsed >= MIN_GAME_SECONDS
      && tappedCycles.size >= REQUIRED_TAPS
    ) {
      completedRef.current = true;
      onComplete();
    }
  }, [elapsed, onComplete, tappedCycles.size]);

  const tap = () => {
    if (!canTap) return;
    setTappedCycles((current) => new Set([...current, cycle]));
  };

  return (
    <div className="flex h-full min-h-[500px] flex-col items-center justify-center">
      <div className="mb-6 text-center">
        <div className="text-xs font-bold uppercase tracking-[0.24em] text-cyan-300">{phase.label}</div>
        <div className="mt-1 text-xs text-slate-600">{phase.hint}</div>
      </div>

      <div className="relative grid h-[240px] w-[240px] place-items-center">
        <div className="absolute h-[230px] w-[230px] rounded-full border border-cyan-400/10" />
        <div
          className="grid place-items-center rounded-full border border-cyan-300/40 bg-cyan-300/10 shadow-[0_0_70px_rgba(34,211,238,0.18)]"
          style={{
            width: `${circleSize}px`,
            height: `${circleSize}px`,
            transition: "width 100ms linear, height 100ms linear",
          }}
        >
          <span className="text-2xl font-light tabular-nums text-cyan-100">
            {phaseSecondsRemaining(withinCycle)}
          </span>
        </div>
      </div>

      <button
        type="button"
        disabled={!canTap}
        onClick={tap}
        className="mt-7 min-w-52 rounded-xl border border-cyan-400/30 bg-cyan-400/10 px-6 py-3 text-sm font-semibold text-cyan-100 transition enabled:hover:bg-cyan-400/25 disabled:border-ink-700 disabled:bg-ink-950 disabled:text-slate-700"
      >
        {tappedCycles.has(cycle) ? "Đã bắt nhịp" : canTap ? "Tap · thở ra" : "Chờ nhịp thở ra"}
      </button>

      <div className="mt-7 flex items-center gap-3">
        {progressDots.map((done, index) => (
          <div
            key={index}
            className={`h-1.5 w-10 rounded-full ${done ? "bg-cyan-300" : "bg-ink-700"}`}
          />
        ))}
      </div>
      <div className="mt-3 text-[10px] uppercase tracking-[0.16em] text-slate-600">
        {secondsRemaining > 0 ? `Còn tối thiểu ${secondsRemaining}s · ` : ""}
        Tap thành công {tappedCycles.size}/{REQUIRED_TAPS}
      </div>
    </div>
  );
}

function breathingPhase(second: number): { key: "inhale" | "hold" | "exhale"; label: string; hint: string } {
  if (second < 4) return { key: "inhale", label: "Hít vào", hint: "Chậm và đều" };
  if (second < 6) return { key: "hold", label: "Giữ", hint: "Không gồng người" };
  return { key: "exhale", label: "Thở ra", hint: "Tap khi bạn cảm thấy nhịp đã chậm lại" };
}

function breathingCircleSize(second: number): number {
  if (second < 4) return 130 + (second / 4) * 90;
  if (second < 6) return 220;
  return 220 - ((second - 6) / 6) * 90;
}

function phaseSecondsRemaining(second: number): number {
  if (second < 4) return Math.max(1, Math.ceil(4 - second));
  if (second < 6) return Math.max(1, Math.ceil(6 - second));
  return Math.max(1, Math.ceil(12 - second));
}
