import { ArrowLeft, Check, Play, RefreshCw, Shuffle, Wind } from "lucide-react";
import { useEffect, useState } from "react";
import { MindfulMazeGame } from "../components/calm/MindfulMazeGame";
import { PixelCalmGame } from "../components/calm/PixelCalmGame";
import { RhythmResetGame } from "../components/calm/RhythmResetGame";
import {
  CALM_GAMES,
  randomCalmGame,
  type CalmGameId,
} from "../components/calm/gameTypes";
import { drawCalmMessage } from "../lib/calmReset";
import { useCalmResetStore } from "../store/calmResetStore";
import { useNavigationStore } from "../store/navigationStore";

export function CalmPage() {
  const event = useCalmResetStore((state) => state.event);
  const storedMessage = useCalmResetStore((state) => state.message);
  const returnPage = useCalmResetStore((state) => state.returnPage);
  const setStoredMessage = useCalmResetStore((state) => state.setMessage);
  const requestPreview = useCalmResetStore((state) => state.requestPreview);
  const completeReset = useCalmResetStore((state) => state.complete);
  const setPage = useNavigationStore((state) => state.setPage);
  const [gameId, setGameId] = useState<CalmGameId>(() => randomCalmGame());
  const [gameStarted, setGameStarted] = useState(Boolean(event));
  const [gameCompleted, setGameCompleted] = useState(false);
  const [gameChangeUsed, setGameChangeUsed] = useState(false);
  const [gameRun, setGameRun] = useState(0);

  useEffect(() => {
    if (!event) return;
    setGameId(randomCalmGame());
    setGameStarted(true);
    setGameCompleted(false);
    setGameChangeUsed(false);
    setGameRun((run) => run + 1);
  }, [event?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const message = storedMessage
    ?? "Tạm rời khỏi biểu đồ. Hít thở chậm trước khi quyết định điều gì tiếp theo.";
  const resultTone = event?.outcome === "win"
    ? "text-emerald-300"
    : event?.outcome === "loss"
      ? "text-rose-300"
      : "text-cyan-200";
  const game = CALM_GAMES.find((item) => item.id === gameId) ?? CALM_GAMES[0];

  const start = () => {
    setGameStarted(true);
    setGameCompleted(false);
    setGameRun((run) => run + 1);
  };

  const changeGame = () => {
    if (gameChangeUsed || gameCompleted) return;
    setGameId((current) => randomCalmGame(current));
    setGameChangeUsed(true);
    setGameStarted(true);
    setGameRun((run) => run + 1);
  };

  const finish = () => {
    completeReset();
    setPage(returnPage === "calm" ? "chart" : returnPage);
  };

  return (
    <div className="h-full overflow-y-auto bg-[radial-gradient(circle_at_50%_25%,rgba(8,145,178,0.13),transparent_42%),#080b10] text-slate-100">
      <div className="mx-auto flex min-h-full max-w-6xl flex-col px-8 py-8">
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
          {!gameStarted ? (
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

        <div className="mt-8 grid flex-1 grid-cols-1 gap-6 lg:grid-cols-[0.82fr_1.18fr]">
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
              Không dự đoán giá trong lúc này. Không có điểm số, game over hoặc hình phạt khi thao tác sai.
            </div>
          </section>

          <section className="relative flex min-h-[570px] flex-col overflow-hidden rounded-2xl border border-cyan-400/20 bg-ink-900/65 p-6 shadow-[0_20px_80px_rgba(8,145,178,0.12)]">
            <div className="flex items-center justify-between border-b border-ink-700/80 pb-4 text-[10px] uppercase tracking-[0.18em] text-slate-600">
              <div>
                <span className="text-slate-400">{game.label}</span>
                <span className="ml-2">· {game.duration}</span>
              </div>
              {gameStarted && !gameCompleted ? (
                <button
                  type="button"
                  disabled={gameChangeUsed}
                  onClick={changeGame}
                  className="flex items-center gap-1.5 rounded-md border border-ink-700 bg-ink-950 px-2.5 py-1.5 text-[10px] font-semibold normal-case tracking-normal text-slate-400 hover:text-white disabled:cursor-not-allowed disabled:opacity-35"
                >
                  <Shuffle size={12} />
                  {gameChangeUsed ? "Đã đổi game" : "Đổi game · 1 lần"}
                </button>
              ) : null}
            </div>

            <div className="flex flex-1 items-center justify-center">
              {!gameStarted ? (
                <GameStart gameId={gameId} onStart={start} />
              ) : gameCompleted ? (
                <GameComplete onFinish={finish} returnPage={returnPage} />
              ) : (
                <CalmGame
                  key={`${gameId}-${gameRun}`}
                  gameId={gameId}
                  onComplete={() => setGameCompleted(true)}
                />
              )}
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function CalmGame({ gameId, onComplete }: {
  gameId: CalmGameId;
  onComplete: () => void;
}) {
  if (gameId === "maze") return <MindfulMazeGame onComplete={onComplete} />;
  if (gameId === "pixel") return <PixelCalmGame onComplete={onComplete} />;
  return <RhythmResetGame onComplete={onComplete} />;
}

function GameStart({ gameId, onStart }: {
  gameId: CalmGameId;
  onStart: () => void;
}) {
  const descriptions: Record<CalmGameId, string> = {
    rhythm: "Theo nhịp hít 4 giây, giữ 2 giây, thở 6 giây và tap trong pha thở ra.",
    maze: "Tìm đường từ góc trên trái đến điểm sáng ở góc dưới phải, từng bước một.",
    pixel: "Chọn màu và tô đúng các ô số để hoàn thành bức tranh pixel nhỏ.",
  };
  return (
    <div className="text-center">
      <div className="mx-auto grid h-24 w-24 place-items-center rounded-full border border-cyan-300/30 bg-cyan-300/10 text-cyan-200">
        <Wind size={34} />
      </div>
      <h2 className="mt-6 text-xl font-semibold">Game được chọn ngẫu nhiên</h2>
      <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-slate-500">
        {descriptions[gameId]}
      </p>
      <button
        type="button"
        onClick={onStart}
        className="mt-6 inline-flex items-center gap-2 rounded-xl border border-cyan-400/40 bg-cyan-400/15 px-5 py-3 text-sm font-semibold text-cyan-100 hover:bg-cyan-400/25"
      >
        <Play size={16} />
        Bắt đầu
      </button>
    </div>
  );
}

function GameComplete({ onFinish, returnPage }: {
  onFinish: () => void;
  returnPage: string;
}) {
  return (
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
        onClick={onFinish}
        className="mt-7 inline-flex items-center gap-2 rounded-xl border border-emerald-400/40 bg-emerald-400/15 px-5 py-3 text-sm font-semibold text-emerald-100 hover:bg-emerald-400/25"
      >
        <ArrowLeft size={16} />
        Quay lại {returnPage === "calm" ? "Chart" : pageLabel(returnPage)}
      </button>
    </div>
  );
}

function formatR(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}R`;
}

function pageLabel(page: string): string {
  return page.charAt(0).toUpperCase() + page.slice(1);
}
