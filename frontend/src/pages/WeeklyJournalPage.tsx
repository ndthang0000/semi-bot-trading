import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, ChevronLeft, ChevronRight, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { fetchWeeklyJournals, updateWeeklyJournal } from "../api/chart";
import { RichTextEditor } from "../components/weeklyJournal/RichTextEditor";
import {
  addDaysToDateKey,
  currentVietnamDateKey,
  currentVietnamWeekStart,
  formatWeekRange,
  plainTextToRichText,
  richTextToPlainText,
  weekStartForDateKey,
} from "../lib/weeklyJournal";
import type { WeeklyJournal } from "../types";

const SCORE_SERIES = [
  { key: "discipline_score", label: "Kỷ luật", color: "#4ade80" },
  { key: "fomo_score", label: "FOMO", color: "#facc15" },
  { key: "revenge_score", label: "Revenge", color: "#f87171" },
] as const;

export function WeeklyJournalPage() {
  const queryClient = useQueryClient();
  const currentWeek = currentVietnamWeekStart();
  const [selectedWeek, setSelectedWeek] = useState(currentWeek);
  const [content, setContent] = useState("");
  const [discipline, setDiscipline] = useState(5);
  const [fomo, setFomo] = useState(5);
  const [revenge, setRevenge] = useState(5);
  const [achievedR, setAchievedR] = useState("0");
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const journalsQuery = useQuery({
    queryKey: ["weekly-journals"],
    queryFn: () => fetchWeeklyJournals(104),
    staleTime: 30_000,
  });
  const journals = journalsQuery.data?.journals ?? [];
  const selectedJournal = journals.find((journal) => journal.week_start === selectedWeek);
  const selectedContent = selectedJournal
    ? selectedJournal.content_format === "rich_text"
      ? selectedJournal.content
      : plainTextToRichText(selectedJournal.content)
    : "<p></p>";

  useEffect(() => {
    setContent(selectedContent);
    setDiscipline(selectedJournal?.discipline_score ?? 5);
    setFomo(selectedJournal?.fomo_score ?? 5);
    setRevenge(selectedJournal?.revenge_score ?? 5);
    setAchievedR(String(selectedJournal?.achieved_r ?? 0));
    setSavedAt(selectedJournal?.updated_at ?? null);
  }, [selectedJournal?.updated_at, selectedWeek]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = content !== selectedContent
    || discipline !== (selectedJournal?.discipline_score ?? 5)
    || fomo !== (selectedJournal?.fomo_score ?? 5)
    || revenge !== (selectedJournal?.revenge_score ?? 5)
    || Number(achievedR) !== (selectedJournal?.achieved_r ?? 0);
  const achievedRValue = Number(achievedR);
  const achievedRValid = achievedR.trim() !== "" && Number.isFinite(achievedRValue)
    && achievedRValue >= -1_000 && achievedRValue <= 1_000;
  const visibleContentLength = richTextToPlainText(content).length;
  const contentWithinLimit = content.length <= 50_000;

  const saveMutation = useMutation({
    mutationFn: () => updateWeeklyJournal(selectedWeek, {
      content,
      content_format: "rich_text",
      discipline_score: discipline,
      fomo_score: fomo,
      revenge_score: revenge,
      achieved_r: achievedRValue,
    }),
    onSuccess: (saved) => {
      queryClient.setQueryData(["weekly-journals"], (current: typeof journalsQuery.data) => {
        const currentJournals = current?.journals ?? [];
        const next = [saved, ...currentJournals.filter((journal) => journal.week_start !== saved.week_start)]
          .sort((a, b) => b.week_start.localeCompare(a.week_start));
        const existed = currentJournals.some((journal) => journal.week_start === saved.week_start);
        return { journals: next, total: (current?.total ?? 0) + (existed ? 0 : 1) };
      });
      setSavedAt(saved.updated_at);
    },
  });

  function selectWeek(nextWeek: string) {
    if (nextWeek === selectedWeek) return;
    if (dirty && !window.confirm("Bạn có thay đổi chưa lưu. Chuyển tuần và bỏ các thay đổi này?")) return;
    setSelectedWeek(nextWeek);
  }

  const saveError = saveMutation.error instanceof Error ? saveMutation.error.message : null;

  return (
    <div className="h-full overflow-y-auto bg-ink-950 text-slate-100">
      <header className="sticky top-0 z-10 border-b border-ink-700 bg-ink-900/95 px-6 py-4 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold">Nhật ký tuần</h1>
            <p className="mt-0.5 text-xs text-slate-500">Theo dõi kỷ luật và cảm xúc, tách biệt khỏi kết quả lời/lỗ.</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => selectWeek(addDaysToDateKey(selectedWeek, -7))}
              className="rounded-lg border border-ink-700 p-2 text-slate-400 hover:border-slate-500 hover:text-slate-200"
              aria-label="Tuần trước"
            >
              <ChevronLeft size={16} />
            </button>
            <label className="flex items-center gap-2 rounded-lg border border-ink-700 bg-ink-950 px-3 py-2 text-xs text-slate-400">
              <CalendarDays size={15} />
              <span className="hidden sm:inline">Chọn ngày</span>
              <input
                type="date"
                value={selectedWeek}
                max={currentVietnamDateKey()}
                onChange={(event) => {
                  if (event.target.value) selectWeek(weekStartForDateKey(event.target.value));
                }}
                className="bg-transparent text-slate-200 outline-none"
              />
            </label>
            <button
              type="button"
              onClick={() => selectWeek(addDaysToDateKey(selectedWeek, 7))}
              disabled={selectedWeek >= currentWeek}
              className="rounded-lg border border-ink-700 p-2 text-slate-400 hover:border-slate-500 hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-30"
              aria-label="Tuần sau"
            >
              <ChevronRight size={16} />
            </button>
            {selectedWeek !== currentWeek && (
              <button
                type="button"
                onClick={() => selectWeek(currentWeek)}
                className="rounded-lg border border-cyan-500/40 px-3 py-2 text-xs text-cyan-200 hover:bg-cyan-500/10"
              >
                Tuần này
              </button>
            )}
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-7xl gap-5 px-6 py-6 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-5">
          <section className="rounded-xl border border-ink-700 bg-ink-900 p-5">
            <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Tiến trình cảm xúc</div>
                <div className="mt-1 text-sm text-slate-300">Kỷ luật nên tăng; FOMO và Revenge nên giảm.</div>
              </div>
              <div className="flex flex-wrap gap-3 text-xs">
                {SCORE_SERIES.map((series) => (
                  <span key={series.key} className="flex items-center gap-1.5 text-slate-400">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: series.color }} />
                    {series.label}
                  </span>
                ))}
              </div>
            </div>
            <EmotionGraph journals={journals} />
            <div className="mt-6 border-t border-ink-700 pt-5">
              <div className="mb-2 flex items-center justify-between gap-3">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">R đạt được</div>
                  <div className="mt-0.5 text-xs text-slate-600">Tổng kết quả R bạn ghi nhận cho từng tuần.</div>
                </div>
                <span className="text-xs text-slate-600">Dương / âm quanh mốc 0R</span>
              </div>
              <WeeklyRGraph journals={journals} />
            </div>
          </section>

          <section className="rounded-xl border border-ink-700 bg-ink-900 p-5">
            <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.16em] text-cyan-300">
                  {selectedJournal ? "Chỉnh sửa nhật ký" : "Tạo nhật ký"}
                </div>
                <h2 className="mt-1 text-xl font-semibold">{formatWeekRange(selectedWeek)}</h2>
                <div className="mt-1 text-xs text-slate-500">
                  {selectedWeek === currentWeek ? "Tuần hiện tại" : "Tuần trong quá khứ"} · Asia/Ho_Chi_Minh
                </div>
              </div>
              <div className="text-right text-xs text-slate-500">
                {dirty ? <span className="text-amber-300">Có thay đổi chưa lưu</span> : savedAt ? `Đã lưu ${formatSavedTime(savedAt)}` : "Chưa có nhật ký"}
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <ScoreField
                label="Kỷ luật"
                hint="Càng cao càng tốt"
                value={discipline}
                color="green"
                onChange={setDiscipline}
              />
              <ScoreField
                label="FOMO"
                hint="Càng thấp càng tốt"
                value={fomo}
                color="amber"
                onChange={setFomo}
              />
              <ScoreField
                label="Revenge"
                hint="Càng thấp càng tốt"
                value={revenge}
                color="red"
                onChange={setRevenge}
              />
              <RField value={achievedR} valid={achievedRValid} onChange={setAchievedR} />
            </div>

            <div className="mt-5">
              <div className="mb-2 text-sm font-medium text-slate-300">Điều gì đã xảy ra trong tuần này?</div>
              <RichTextEditor value={content} onChange={setContent} />
            </div>

            <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
              <div className={`text-xs ${contentWithinLimit ? "text-slate-600" : "text-red-400"}`}>
                {visibleContentLength.toLocaleString()} ký tự nội dung
                {!contentWithinLimit ? " · Nội dung định dạng vượt giới hạn lưu 50.000 ký tự" : ""}
              </div>
              <div className="flex items-center gap-3">
                {saveError && <span className="max-w-sm text-xs text-red-400">{saveError}</span>}
                <button
                  type="button"
                  disabled={saveMutation.isPending || !dirty || !achievedRValid || !contentWithinLimit}
                  onClick={() => saveMutation.mutate()}
                  className="flex items-center gap-2 rounded-lg border border-cyan-400/50 bg-cyan-500/10 px-4 py-2.5 text-sm font-semibold text-cyan-100 transition-colors hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <Save size={16} />
                  {saveMutation.isPending ? "Đang lưu..." : "Lưu nhật ký"}
                </button>
              </div>
            </div>
          </section>
        </div>

        <aside className="min-w-0 rounded-xl border border-ink-700 bg-ink-900 p-4 xl:sticky xl:top-24 xl:max-h-[calc(100dvh-8rem)]">
          <div className="mb-3">
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Các tuần đã viết</div>
            <div className="mt-1 text-xs text-slate-600">{journalsQuery.data?.total ?? 0} tuần</div>
          </div>
          <div className="space-y-2 overflow-y-auto xl:max-h-[calc(100dvh-12rem)]">
            {journalsQuery.isLoading ? (
              <div className="py-8 text-center text-sm text-slate-600">Đang tải...</div>
            ) : journalsQuery.isError ? (
              <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-3 text-xs text-red-300">Không thể tải nhật ký.</div>
            ) : journals.length === 0 ? (
              <div className="py-8 text-center text-sm leading-6 text-slate-600">Chưa có tuần nào.<br />Hãy bắt đầu với tuần hiện tại hoặc chọn tuần cũ.</div>
            ) : (
              journals.map((journal) => (
                <JournalHistoryCard
                  key={journal.id}
                  journal={journal}
                  selected={journal.week_start === selectedWeek}
                  onSelect={() => selectWeek(journal.week_start)}
                />
              ))
            )}
          </div>
        </aside>
      </main>
    </div>
  );
}

function ScoreField({
  label,
  hint,
  value,
  color,
  onChange,
}: {
  label: string;
  hint: string;
  value: number;
  color: "green" | "amber" | "red";
  onChange: (value: number) => void;
}) {
  const tones = {
    green: "text-green-300 accent-green-400",
    amber: "text-amber-300 accent-amber-400",
    red: "text-red-300 accent-red-400",
  };
  return (
    <label className="rounded-xl border border-ink-700 bg-ink-950 p-4">
      <span className="flex items-start justify-between gap-2">
        <span>
          <span className="block text-sm font-semibold text-slate-200">{label}</span>
          <span className="mt-0.5 block text-[11px] text-slate-600">{hint}</span>
        </span>
        <span className={`text-2xl font-bold ${tones[color]}`}>{value}</span>
      </span>
      <input
        type="range"
        min={1}
        max={10}
        step={1}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        className={`mt-4 w-full ${tones[color]}`}
        aria-label={`${label}: ${value}/10`}
      />
      <span className="mt-1 flex justify-between text-[10px] text-slate-700"><span>1</span><span>10</span></span>
    </label>
  );
}

function RField({
  value,
  valid,
  onChange,
}: {
  value: string;
  valid: boolean;
  onChange: (value: string) => void;
}) {
  const numericValue = Number(value);
  return (
    <label className="rounded-xl border border-ink-700 bg-ink-950 p-4">
      <span className="flex items-start justify-between gap-2">
        <span>
          <span className="block text-sm font-semibold text-slate-200">R đạt được</span>
          <span className="mt-0.5 block text-[11px] text-slate-600">Tổng R thực tế của tuần</span>
        </span>
        <span className={`text-2xl font-bold ${!valid ? "text-red-300" : numericValue >= 0 ? "text-cyan-300" : "text-red-300"}`}>
          {valid ? formatR(numericValue) : "--"}
        </span>
      </span>
      <div className="mt-4 flex items-center rounded-lg border border-ink-700 bg-ink-900 px-3 focus-within:border-cyan-500/60">
        <input
          type="number"
          min={-1_000}
          max={1_000}
          step="0.01"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="min-w-0 flex-1 bg-transparent py-2 text-sm text-slate-100 outline-none"
          aria-label="R đạt được trong tuần"
        />
        <span className="text-xs font-semibold text-slate-500">R</span>
      </div>
      <div className={`mt-2 text-[10px] ${valid ? "text-slate-700" : "text-red-400"}`}>
        {valid ? "Có thể nhập số âm, dương hoặc 0." : "Nhập một số từ -1000 đến 1000."}
      </div>
    </label>
  );
}

function EmotionGraph({ journals }: { journals: WeeklyJournal[] }) {
  const ordered = useMemo(
    () => [...journals].sort((a, b) => a.week_start.localeCompare(b.week_start)).slice(-16),
    [journals],
  );
  if (ordered.length === 0) {
    return <div className="grid h-52 place-items-center rounded-lg border border-dashed border-ink-700 text-sm text-slate-600">Graph sẽ xuất hiện sau khi bạn lưu tuần đầu tiên.</div>;
  }

  const width = 800;
  const height = 230;
  const padding = { top: 15, right: 18, bottom: 42, left: 35 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const x = (index: number) => padding.left + (ordered.length === 1 ? chartWidth / 2 : (index / (ordered.length - 1)) * chartWidth);
  const y = (score: number) => padding.top + ((10 - score) / 9) * chartHeight;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-56 w-full" role="img" aria-label="Biểu đồ điểm kỷ luật, FOMO và revenge theo tuần">
      {[1, 4, 7, 10].map((score) => (
        <g key={score}>
          <line x1={padding.left} x2={width - padding.right} y1={y(score)} y2={y(score)} stroke="#263244" strokeWidth="1" strokeDasharray="3 5" />
          <text x={padding.left - 10} y={y(score) + 3} textAnchor="end" fontSize="10" fill="#64748b">{score}</text>
        </g>
      ))}

      {SCORE_SERIES.map((series) => {
        const points = ordered.map((journal, index) => `${x(index)},${y(journal[series.key])}`).join(" ");
        return (
          <g key={series.key}>
            {ordered.length > 1 && <polyline points={points} fill="none" stroke={series.color} strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />}
            {ordered.map((journal, index) => (
              <circle key={journal.id} cx={x(index)} cy={y(journal[series.key])} r="4" fill="#101722" stroke={series.color} strokeWidth="2">
                <title>{`${series.label} · ${formatWeekRange(journal.week_start)}: ${journal[series.key]}/10`}</title>
              </circle>
            ))}
          </g>
        );
      })}

      {ordered.map((journal, index) => {
        const showLabel = ordered.length <= 8 || index % 2 === 0 || index === ordered.length - 1;
        return showLabel ? (
          <text key={journal.id} x={x(index)} y={height - 12} textAnchor="middle" fontSize="9" fill="#64748b">
            {journal.week_start.slice(5).replace("-", "/")}
          </text>
        ) : null;
      })}
    </svg>
  );
}

function WeeklyRGraph({ journals }: { journals: WeeklyJournal[] }) {
  const ordered = useMemo(
    () => [...journals].sort((a, b) => a.week_start.localeCompare(b.week_start)).slice(-16),
    [journals],
  );
  if (ordered.length === 0) {
    return <div className="grid h-36 place-items-center rounded-lg border border-dashed border-ink-700 text-sm text-slate-600">Chưa có dữ liệu R.</div>;
  }

  const width = 800;
  const height = 170;
  const padding = { top: 15, right: 18, bottom: 38, left: 42 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;
  const zeroY = padding.top + chartHeight / 2;
  const maxAbs = Math.max(1, ...ordered.map((journal) => Math.abs(journal.achieved_r)));
  const slotWidth = chartWidth / ordered.length;
  const barWidth = Math.min(34, Math.max(8, slotWidth * 0.52));

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-40 w-full" role="img" aria-label="Biểu đồ R đạt được theo tuần">
      <line x1={padding.left} x2={width - padding.right} y1={zeroY} y2={zeroY} stroke="#64748b" strokeWidth="1" />
      <text x={padding.left - 8} y={zeroY + 3} textAnchor="end" fontSize="10" fill="#64748b">0R</text>
      <text x={padding.left - 8} y={padding.top + 4} textAnchor="end" fontSize="9" fill="#475569">+{maxAbs.toFixed(1)}</text>
      <text x={padding.left - 8} y={padding.top + chartHeight + 3} textAnchor="end" fontSize="9" fill="#475569">-{maxAbs.toFixed(1)}</text>

      {ordered.map((journal, index) => {
        const centerX = padding.left + slotWidth * index + slotWidth / 2;
        const magnitude = (Math.abs(journal.achieved_r) / maxAbs) * (chartHeight / 2);
        const positive = journal.achieved_r >= 0;
        const barY = positive ? zeroY - magnitude : zeroY;
        const color = positive ? "#22d3ee" : "#f87171";
        const showLabel = ordered.length <= 8 || index % 2 === 0 || index === ordered.length - 1;
        return (
          <g key={journal.id}>
            {journal.achieved_r === 0 ? (
              <circle cx={centerX} cy={zeroY} r="3" fill="#64748b">
                <title>{`${formatWeekRange(journal.week_start)}: 0R`}</title>
              </circle>
            ) : (
              <rect x={centerX - barWidth / 2} y={barY} width={barWidth} height={magnitude} rx="2" fill={color} fillOpacity="0.85">
                <title>{`${formatWeekRange(journal.week_start)}: ${formatR(journal.achieved_r)}`}</title>
              </rect>
            )}
            {showLabel && (
              <text x={centerX} y={height - 10} textAnchor="middle" fontSize="9" fill="#64748b">
                {journal.week_start.slice(5).replace("-", "/")}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

function JournalHistoryCard({
  journal,
  selected,
  onSelect,
}: {
  journal: WeeklyJournal;
  selected: boolean;
  onSelect: () => void;
}) {
  const previewSource = journal.content_format === "rich_text"
    ? richTextToPlainText(journal.content)
    : journal.content;
  const preview = previewSource.trim().replace(/\s+/g, " ");
  return (
    <button
      type="button"
      onClick={onSelect}
      className={[
        "w-full rounded-lg border p-3 text-left transition-colors",
        selected
          ? "border-cyan-400/60 bg-cyan-500/10"
          : "border-ink-700 bg-ink-950 hover:border-slate-600",
      ].join(" ")}
    >
      <div className="text-xs font-semibold text-slate-200">{formatWeekRange(journal.week_start)}</div>
      <div className="mt-2 flex gap-2 text-[11px]">
        <span className="text-green-300">K {journal.discipline_score}</span>
        <span className="text-amber-300">F {journal.fomo_score}</span>
        <span className="text-red-300">Rev {journal.revenge_score}</span>
        <span className={journal.achieved_r >= 0 ? "text-cyan-300" : "text-red-300"}>R {formatR(journal.achieved_r)}</span>
      </div>
      <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500">{preview || "Chưa có nội dung text."}</p>
    </button>
  );
}

function formatSavedTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("vi-VN", {
    timeZone: "Asia/Ho_Chi_Minh",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function formatR(value: number): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}R`;
}
