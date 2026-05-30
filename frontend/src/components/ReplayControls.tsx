import { ChevronLeft, ChevronRight, Pause, Play } from "lucide-react";
import type { ReplayTimeline } from "../types";

type ReplayControlsProps = {
  isPlaying: boolean;
  speedSeconds: number;
  timeline: ReplayTimeline | undefined;
  currentIndex: number;
  onPlayingChange: (playing: boolean) => void;
  onSpeedChange: (seconds: number) => void;
  onStep: (delta: number) => void;
};

export function ReplayControls({
  isPlaying,
  speedSeconds,
  timeline,
  currentIndex,
  onPlayingChange,
  onSpeedChange,
  onStep,
}: ReplayControlsProps) {
  const count = timeline?.count ?? 0;
  const currentTime = timeline?.times[currentIndex] ?? null;
  const canStepBack = currentIndex > 0;
  const canStepForward = count > 0 && currentIndex < count - 1;

  return (
    <section className="flex h-12 items-center justify-between border-b border-ink-700 bg-ink-900 px-4">
      <div className="flex items-center gap-3">
        <div className="text-sm font-semibold text-cyan-200">Replay Chart</div>
        <button
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-ink-700 bg-ink-850 text-slate-200 hover:border-cyan-500 disabled:cursor-not-allowed disabled:opacity-40"
          disabled={!canStepBack}
          title="Previous candle"
          type="button"
          onClick={() => onStep(-1)}
        >
          <ChevronLeft size={16} />
        </button>
        <button
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-cyan-400/60 bg-cyan-400/15 text-cyan-100 hover:bg-cyan-400/25 disabled:cursor-not-allowed disabled:opacity-40"
          disabled={count === 0}
          title={isPlaying ? "Pause replay" : "Play replay"}
          type="button"
          onClick={() => onPlayingChange(!isPlaying)}
        >
          {isPlaying ? <Pause size={15} /> : <Play size={15} />}
        </button>
        <button
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-ink-700 bg-ink-850 text-slate-200 hover:border-cyan-500 disabled:cursor-not-allowed disabled:opacity-40"
          disabled={!canStepForward}
          title="Next candle"
          type="button"
          onClick={() => onStep(1)}
        >
          <ChevronRight size={16} />
        </button>
        <label className="flex items-center gap-2 text-xs text-slate-400">
          sec/candle
          <input
            className="h-8 w-20 rounded-md border border-ink-700 bg-ink-850 px-2 text-sm text-slate-100 outline-none disabled:cursor-not-allowed disabled:opacity-50"
            min={0.1}
            step={0.1}
            type="number"
            value={speedSeconds}
            onChange={(event) => onSpeedChange(Math.max(0.1, Number(event.target.value) || 1))}
          />
        </label>
      </div>
      <div className="text-xs text-slate-400">
        {currentTime ? (
          <>
            <span className="font-semibold text-slate-200">{currentIndex + 1}</span> / {count} · {formatReplayTime(currentTime)}
          </>
        ) : (
          "Loading replay timeline"
        )}
      </div>
    </section>
  );
}

function formatReplayTime(value: string): string {
  return value.replace("T", " ").replace("+00:00", "");
}
