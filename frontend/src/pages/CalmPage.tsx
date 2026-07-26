import { ArrowLeft, Check, Play, RefreshCw, Wind } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { drawCalmMessage } from "../lib/calmReset";
import { useCalmResetStore } from "../store/calmResetStore";
import { useNavigationStore } from "../store/navigationStore";

const CYCLE_SECONDS = 12;
const MIN_GAME_SECONDS = 48;
const REQUIRED_TAPS = 3;

export function CalmPage() {
  const event = useCalmResetStore((state) => state.event);
  const storedMessage = useCalmResetStore((state) => state.message);
  const returnPage = useCalmResetStore((state) => state.returnPage);
  const setStoredMessage = useCalmResetStore((state) => state.setMessage);
  const requestPreview = useCalmResetStore((state) => state.requestPreview);
  const completeReset = useCalmResetStore((state) => state.complete);
  const setPage = useNavigationStore((state) => state.setPage);
  const [running, setRunning] = useState(Boolean(event));
  const [startedAt, setStartedAt] = useState(() => Date.now());
  const [elapsed, setElapsed] = useState(0);
  const [tappedCycles, setTappedCycles] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (!event) return;
    setRunning(true);
    setStartedAt(Date.now());
    setElapsed(0);
    setTappedCycles(new Set());
  }, [event?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      setElapsed((Date.now() - startedAt) / 1_000);
    }, 100);
    return () => window.clearInterval(timer);
  }, [running, startedAt]);

  const cycle = Math.floor(elapsed / CYCLE_SECONDS);
  const withinCycle = elapsed % CYCLE_SECONDS;
  const phase = breathingPhase(withinCycle);
  const circleSize = breathingCircleSize(withinCycle);
  const canTap = running && phase.key === "exhale" && !tappedCycles.has(cycle);
  const completed = elapsed >= MIN_GAME_SECONDS && tappedCycles.size >= REQUIRED_TAPS;
  const secondsRemaining = Math.max(0, Math.ceil(MIN_GAME_SECONDS - elapsed));
  const message = storedMessage ?? "Tạm rời khỏi biểu đồ. Hít thở chậm trước khi quyết định điều gì tiếp theo.";
  const resultTone = event?.outcome === "win"
    ? "text-emerald-300"
    : event?.outcome === "loss"
      ? "text-rose-300"
      : "text-cyan-200";
  const progressDots = useMemo(
    () => Array.from({ length: 4 }, (_, index) => elapsed >= (index + 1) * CYCLE_SECONDS),
    [elapsed],
  );

  const start = () => {
    setStartedAt(Date.now());
    setElapsed(0);
    setTappedCycles(new Set());
    setRunning(true);
  };

  const tap = () => {
    if (!canTap) return;
    setTappedCycles((current) => new Set([...current, cycle]));
  };

  const finish = () => {
    completeReset();
    setPage(returnPage === "calm" ? "chart" : returnPage);
  };

  return (
    <div className="h-full overflow-y-auto bg-[radial-gradient(circle_at_50%_25%,rgba(8,145,178,0.13),transparent_42%),#080b10] text-slate-100">
      <div className="mx-auto flex min-h-full max-w-5xl flex-col px-8 py-8">
        <header className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2 text-xs font-bold tracking-[0.22em] text-cyan-300">
              <Wind size={17} />
              CALM RESET
            </div>
            <h1 className="mt-2 text-2xl font-semibold">
              {event ? "Đưa tâm trí về trạng thái trung lập" : "Một phút rời khỏi thị trường"}
            </h1>
          </div>
          {!running ? (
            <button
              type="button"
              onClick={() => setPage("chart")}
              className="flex items-center gap-2 rounded-lg border border-ink-700 bg-ink-900 px-3 py-2 text-xs text-slate-400 hover:text-white"
            >
              <ArrowLeft size={14} />
              Quay lại Chart
            </button>
          ) : null}
        </header>

        <div className="mt-8 grid flex-1 grid-cols-1 gap-6 lg:grid-cols-[0.9fr_1.1fr]">
          <section className="flex flex-col rounded-2xl border border-ink-700 bg-ink-900/80 p-6 shadow-2xl backdrop-blur">
            <div className="flex items-center justify-between text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
              <span>{event ? `Trade ${event.outcome}` : "Voluntary reset"}</span>
              {event ? <span className={resultTone}>{formatR(event.pnlR)}</span> : null}
            </div>
            <blockquote className="mt-6 flex-1 border-l-2 border-cyan-400/40 pl-5 text-xl font-medium leading-relaxed text-slate-100">
              “{message}”
            </blockquote>
            {event ? (
              <button
                type="button"
                onClick={() => setStoredMessage(drawCalmMessage(event.outcome))}
                className="mt-6 flex w-fit items-center gap-2 rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 text-xs text-slate-400 transition hover:border-slate-600 hover:text-white"
              >
                <RefreshCw size={14} />
                Đọc câu khác
              </button>
            ) : (
              <div className="mt-6 rounded-xl border border-dashed border-ink-700 bg-ink-950/70 p-4">
                <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">UI Preview</div>
                <p className="mt-1 text-xs leading-relaxed text-slate-600">
                  Event giả chỉ chạy trong frontend, không ghi database hay thay đổi thống kê.
                </p>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => requestPreview("win")}
                    className="rounded-lg border border-emerald-400/30 bg-emerald-400/10 px-3 py-2 text-xs font-semibold text-emerald-200 hover:bg-emerald-400/20"
                  >
                    Preview Win
                  </button>
                  <button
                    type="button"
                    onClick={() => requestPreview("loss")}
                    className="rounded-lg border border-rose-400/30 bg-rose-400/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-400/20"
                  >
                    Preview Loss
                  </button>
                </div>
              </div>
            )}
            <div className="mt-5 border-t border-ink-700 pt-4 text-xs leading-relaxed text-slate-500">
              Không dự đoán giá trong lúc này. Chỉ theo nhịp vòng tròn và tap khi vòng tròn đang thu nhỏ.
            </div>
          </section>

          <section className="relative flex min-h-[520px] flex-col items-center justify-center overflow-hidden rounded-2xl border border-cyan-400/20 bg-ink-900/65 p-8 shadow-[0_20px_80px_rgba(8,145,178,0.12)]">
            <div className="absolute inset-x-0 top-0 flex items-center justify-between border-b border-ink-700/80 px-5 py-3 text-[10px] uppercase tracking-[0.18em] text-slate-600">
              <span>Rhythm Reset</span>
              <span>{running ? `${secondsRemaining}s minimum` : "48 seconds"}</span>
            </div>

            {!running ? (
              <div className="text-center">
                <div className="mx-auto grid h-24 w-24 place-items-center rounded-full border border-cyan-300/30 bg-cyan-300/10 text-cyan-200">
                  <Wind size={34} />
                </div>
                <h2 className="mt-6 text-xl font-semibold">4 nhịp thở chậm</h2>
                <p className="mt-2 max-w-sm text-sm leading-relaxed text-slate-500">
                  Hít vào 4 giây, giữ 2 giây, thở ra 6 giây. Tap ít nhất 3 lần trong giai đoạn thở ra.
                </p>
                <button
                  type="button"
                  onClick={start}
                  className="mt-6 inline-flex items-center gap-2 rounded-xl border border-cyan-400/40 bg-cyan-400/15 px-5 py-3 text-sm font-semibold text-cyan-100 hover:bg-cyan-400/25"
                >
                  <Play size={16} />
                  Bắt đầu
                </button>
              </div>
            ) : completed ? (
              <div className="text-center">
                <div className="mx-auto grid h-28 w-28 place-items-center rounded-full border border-emerald-300/35 bg-emerald-300/10 text-emerald-300 shadow-[0_0_50px_rgba(52,211,153,0.15)]">
                  <Check size={42} />
                </div>
                <h2 className="mt-6 text-2xl font-semibold">Reset hoàn thành</h2>
                <p className="mt-2 text-sm text-slate-500">
                  Trade trước đã kết thúc. Quyết định tiếp theo bắt đầu từ trạng thái mới.
                </p>
                <button
                  type="button"
                  onClick={finish}
                  className="mt-7 inline-flex items-center gap-2 rounded-xl border border-emerald-400/40 bg-emerald-400/15 px-5 py-3 text-sm font-semibold text-emerald-100 hover:bg-emerald-400/25"
                >
                  <ArrowLeft size={16} />
                  Quay lại {returnPage === "calm" ? "Chart" : pageLabel(returnPage)}
                </button>
              </div>
            ) : (
              <>
                <div className="mb-8 text-center">
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
                  className="mt-8 min-w-52 rounded-xl border border-cyan-400/30 bg-cyan-400/10 px-6 py-3 text-sm font-semibold text-cyan-100 transition enabled:hover:bg-cyan-400/25 disabled:border-ink-700 disabled:bg-ink-950 disabled:text-slate-700"
                >
                  {tappedCycles.has(cycle) ? "Đã bắt nhịp" : canTap ? "Tap · thở ra" : "Chờ nhịp thở ra"}
                </button>

                <div className="mt-8 flex items-center gap-3">
                  {progressDots.map((done, index) => (
                    <div
                      key={index}
                      className={`h-1.5 w-10 rounded-full ${done ? "bg-cyan-300" : "bg-ink-700"}`}
                    />
                  ))}
                </div>
                <div className="mt-3 text-[10px] uppercase tracking-[0.16em] text-slate-600">
                  Tap thành công {tappedCycles.size}/{REQUIRED_TAPS}
                </div>
              </>
            )}
          </section>
        </div>
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

function formatR(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}R`;
}

function pageLabel(page: string): string {
  return page.charAt(0).toUpperCase() + page.slice(1);
}
