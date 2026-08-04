import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, Trash2, Upload, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toPng } from "html-to-image";
import {
  createTradeReviewAttachment,
  deleteTradeReviewAttachment,
  fetchJournalPatterns,
  fetchTradeReviewAttachments,
  updateTradeReview,
} from "../api/chart";
import { authFetch } from "../api/auth";
import { isTradeReviewComplete, type WeeklyReviewGateState } from "../lib/weeklyReview";
import type {
  JournalPatternRow,
  OperatorReview,
  StrategyReview,
  TradeHistoryResponse,
  TradeOrder,
  TradeReview,
  TradeReviewAttachment,
} from "../types";

type JournalTab = "trades" | "queue" | "patterns";

type Filters = {
  outcome: string;
  direction: string;
  reviewed: string;
};

const GRADES = ["A", "B", "C", "D"];
const VERDICTS = ["unreviewed", "good_trade", "bad_trade", "should_skip", "missed_context"];
const SHOULD_TRADE_AGAIN = ["unknown", "yes", "no", "conditional"];

const STRATEGY_SELECTS: Array<[keyof StrategyReview, string, string[]]> = [
  ["setup_grade", "Setup grade", ["a", "b", "c", "d"]],
  ["setup_validity", "Setup validity", ["valid", "weak", "invalid", "unclear"]],
  ["zone_quality", "Zone quality", ["strong", "normal", "weak"]],
  ["entry_quality", "Entry quality", ["good", "late", "early", "chase", "bad_price"]],
  ["sl_quality", "SL quality", ["good", "too_tight", "too_wide", "bad_structure"]],
  ["tp_quality", "TP quality", ["realistic", "too_far", "too_close"]],
  ["market_context", "Market context", ["aligned", "counter", "unclear"]],
  ["should_bot_trade_again", "Bot trade again", ["yes", "no", "conditional"]],
];

const OPERATOR_SELECTS: Array<[keyof OperatorReview, string, string[]]> = [
  ["operator_state", "State", ["calm", "anxious", "fomo", "doubt", "revenge", "tired"]],
  ["operator_action", "Action", ["no_intervention", "moved_sl", "closed_early", "cancelled_order", "reduced_risk", "increased_risk"]],
  ["intervention_result", "Intervention result", ["helped", "hurt", "neutral", "unknown"]],
  ["followed_plan", "Followed plan", ["yes", "no", "partial"]],
];

const STRATEGY_TAGS = [
  "good_zone", "weak_zone", "late_entry", "early_entry", "wide_sl", "atr_fallback",
  "internal_reject", "clean_reject", "slow_reaction", "counter_macro", "ranging_market",
  "low_volatility", "news_nearby", "friday_trade", "limit_order_good", "limit_order_missed",
];

const OPERATOR_TAGS = [
  "fear_moved_sl", "closed_too_early", "watched_chart_too_much", "trusted_bot",
  "ignored_plan", "panic_exit", "good_patience", "manual_override_helped", "manual_override_hurt",
];

const MISTAKE_OPTIONS = [
  "early_entry", "late_entry", "wrong_direction", "ignored_bias",
  "ignored_regime", "overtraded", "moved_sl", "sized_wrong", "fomo",
];

async function fetchTrades(params: URLSearchParams): Promise<TradeHistoryResponse> {
  const res = await authFetch(`/api/trades?${params}`);
  if (!res.ok) throw new Error("Failed to fetch trades");
  return res.json();
}

function fmt(iso: string | null): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    hour12: false,
  });
}

function metaVal(m: Record<string, unknown>, key: string): string {
  const top = m?.[key];
  if (top !== undefined && top !== null) return String(top);
  const nested = (m?.candidate_metadata as Record<string, unknown> | undefined)?.[key];
  if (nested !== undefined && nested !== null) return String(nested);
  return "-";
}

function reviewOrEmpty(review: TradeReview | null | undefined) {
  return {
    strategy: review?.strategy_review ?? {},
    operator: review?.operator_review ?? {},
  };
}

function toggleListValue(values: string[] | undefined, value: string): string[] {
  const current = values ?? [];
  return current.includes(value) ? current.filter((item) => item !== value) : [...current, value];
}

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error("Could not read file"));
    reader.readAsDataURL(file);
  });
}

function DetailPanel({ trade, onClose, onSaved }: {
  trade: TradeOrder;
  onClose: () => void;
  onSaved: () => void;
}) {
  const qc = useQueryClient();
  const existing = trade.review;
  const emptyReview = reviewOrEmpty(existing);
  const [grade, setGrade] = useState<string>(existing?.grade ?? "");
  const [verdict, setVerdict] = useState(existing?.verdict ?? "unreviewed");
  const [tags, setTags] = useState<string[]>(existing?.mistake_tags ?? []);
  const [shouldTrade, setShouldTrade] = useState(existing?.should_trade_again ?? "unknown");
  const [comment, setComment] = useState(existing?.comment ?? "");
  const [strategyReview, setStrategyReview] = useState<StrategyReview>(emptyReview.strategy);
  const [operatorReview, setOperatorReview] = useState<OperatorReview>(emptyReview.operator);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    const nextReview = reviewOrEmpty(trade.review);
    setGrade(trade.review?.grade ?? "");
    setVerdict(trade.review?.verdict ?? "unreviewed");
    setTags(trade.review?.mistake_tags ?? []);
    setShouldTrade(trade.review?.should_trade_again ?? "unknown");
    setComment(trade.review?.comment ?? "");
    setStrategyReview(nextReview.strategy);
    setOperatorReview(nextReview.operator);
    setDirty(false);
  }, [trade.id, trade.review]);

  const attachmentsQuery = useQuery({
    queryKey: ["trade-attachments", trade.id],
    queryFn: () => fetchTradeReviewAttachments(trade.id),
    staleTime: 15_000,
  });

  const saveMutation = useMutation({
    mutationFn: () => updateTradeReview(trade.id, {
      grade: grade || null,
      verdict,
      mistake_tags: tags,
      should_trade_again: shouldTrade,
      comment,
      reviewer: "human",
      strategy_review: strategyReview,
      operator_review: operatorReview,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["journal-trades"] });
      qc.invalidateQueries({ queryKey: ["weekly-review-gate"] });
      qc.invalidateQueries({ queryKey: ["journal-patterns"] });
      setDirty(false);
      onSaved();
    },
  });

  const uploadMutation = useMutation({
    mutationFn: (input: { imageData: string; caption: string }) => createTradeReviewAttachment(trade.id, {
      kind: "review",
      image_data: input.imageData,
      caption: input.caption,
      chart_symbol: "XAUUSD",
      chart_timeframe: "H1",
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["trade-attachments", trade.id] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (attachmentId: string) => deleteTradeReviewAttachment(trade.id, attachmentId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["trade-attachments", trade.id] }),
  });

  const rr = trade.take_profit[0] && trade.entry_price && trade.stop_loss
    ? Math.abs((Number(trade.take_profit[0]) - trade.entry_price) / (trade.entry_price - trade.stop_loss))
    : null;

  const updateStrategy = (key: keyof StrategyReview, value: string | string[]) => {
    setStrategyReview((current) => ({ ...current, [key]: value }));
    setDirty(true);
  };
  const updateOperator = (key: keyof OperatorReview, value: string | string[] | number | undefined) => {
    setOperatorReview((current) => ({ ...current, [key]: value }));
    setDirty(true);
  };

  const captureChart = async () => {
    const node = document.querySelector("[data-chart-capture-root='true']");
    if (!(node instanceof HTMLElement)) {
      return;
    }
    const imageData = await toPng(node, { cacheBust: true, pixelRatio: 1, backgroundColor: "#080b10" });
    await uploadMutation.mutateAsync({ imageData, caption: "Chart review snapshot" });
  };

  const uploadFile = async (file: File | null) => {
    if (!file) return;
    const imageData = await fileToDataUrl(file);
    await uploadMutation.mutateAsync({ imageData, caption: file.name });
  };

  return (
    <div className="flex h-full flex-col border-l border-ink-700 bg-ink-900 text-slate-100">
      <div className="flex items-center justify-between border-b border-ink-700 px-4 py-3">
        <div>
          <div className="text-sm font-semibold">{trade.playbook}</div>
          <div className="text-xs text-slate-500">{trade.id.slice(0, 24)}...</div>
        </div>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-300" type="button">
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 space-y-5 overflow-y-auto p-4">
        <InfoSection title="Bot Decision" rows={[
          ["Account", trade.account_label || "Default"],
          ["Direction", trade.direction ?? trade.side],
          ["Entry", trade.entry_price?.toFixed(2) ?? "-"],
          ["Volume", `${trade.quantity.toLocaleString("en", { maximumFractionDigits: 4 })} lot`],
          ["Stop Loss", trade.stop_loss?.toFixed(2) ?? "-"],
          ["Take Profit", typeof trade.take_profit[0] === "number" ? trade.take_profit[0].toFixed(2) : "-"],
          ["R:R", rr ? `1:${rr.toFixed(2)}` : "-"],
          ["PnL (R)", trade.pnl_r !== null ? `${trade.pnl_r >= 0 ? "+" : ""}${trade.pnl_r.toFixed(2)}R` : "-"],
          ["Opened", fmt(trade.opened_at)],
          ["Closed", fmt(trade.closed_at)],
          ["Zone Type", metaVal(trade.metadata, "zone_type")],
          ["Reaction", metaVal(trade.metadata, "zone_reaction_state")],
          ["Stop Source", metaVal(trade.metadata, "stop_source")],
          ["Session", metaVal(trade.metadata, "session")],
        ]} pnlR={trade.pnl_r} />

        <ReviewBasics
          grade={grade}
          verdict={verdict}
          mistakeTags={tags}
          shouldTrade={shouldTrade}
          onGrade={(value) => { setGrade(value); setDirty(true); }}
          onVerdict={(value) => { setVerdict(value); setDirty(true); }}
          onMistakeTag={(value) => { setTags((current) => toggleListValue(current, value)); setDirty(true); }}
          onShouldTrade={(value) => { setShouldTrade(value); setDirty(true); }}
        />

        <StructuredReviewSection
          title="Strategy Review"
          selects={STRATEGY_SELECTS}
          values={strategyReview}
          onChange={(key, value) => updateStrategy(key as keyof StrategyReview, value)}
          tags={STRATEGY_TAGS}
          selectedTags={strategyReview.strategy_tags ?? []}
          onToggleTag={(tag) => updateStrategy("strategy_tags", toggleListValue(strategyReview.strategy_tags, tag))}
        />

        <OperatorReviewSection
          values={operatorReview}
          onChange={updateOperator}
          selectedTags={operatorReview.operator_tags ?? []}
          onToggleTag={(tag) => updateOperator("operator_tags", toggleListValue(operatorReview.operator_tags, tag))}
        />

        <ScreenshotsSection
          attachments={attachmentsQuery.data ?? []}
          canCapture={document.querySelector("[data-chart-capture-root='true']") instanceof HTMLElement}
          loading={attachmentsQuery.isLoading}
          uploading={uploadMutation.isPending}
          deletingId={deleteMutation.variables ?? null}
          onCapture={() => captureChart().catch(() => undefined)}
          onUpload={uploadFile}
          onDelete={(attachment) => deleteMutation.mutate(attachment.id)}
        />

        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Post Trade Notes</div>
          <textarea
            rows={4}
            value={comment}
            onChange={(event) => { setComment(event.target.value); setDirty(true); }}
            placeholder="Notes about this trade..."
            className="w-full resize-none rounded border border-ink-700 bg-ink-950 px-3 py-2 text-xs text-slate-200 placeholder-slate-600 focus:border-blue-500 focus:outline-none"
          />
        </div>

        <button
          onClick={() => saveMutation.mutate()}
          disabled={!dirty || saveMutation.isPending}
          className="w-full rounded bg-blue-600 px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-blue-500 disabled:opacity-40"
          type="button"
        >
          {saveMutation.isPending ? "Saving..." : "Save Review"}
        </button>
        {saveMutation.isError ? <div className="text-xs text-red-400">Failed to save review.</div> : null}
      </div>
    </div>
  );
}

function InfoSection({ title, rows, pnlR }: { title: string; rows: Array<[string, string]>; pnlR?: number | null }) {
  return (
    <div>
      <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">{title}</div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        {rows.map(([key, value]) => (
          <div key={key} className="flex justify-between py-0.5">
            <span className="text-slate-500">{key}</span>
            <span className={`font-medium ${key === "PnL (R)" ? (pnlR ?? 0) >= 0 ? "text-green-400" : "text-red-400" : "text-slate-300"}`}>
              {value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ReviewBasics(props: {
  grade: string;
  verdict: string;
  mistakeTags: string[];
  shouldTrade: string;
  onGrade: (value: string) => void;
  onVerdict: (value: string) => void;
  onMistakeTag: (value: string) => void;
  onShouldTrade: (value: string) => void;
}) {
  return (
    <div>
      <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">Review Basics</div>
      <div className="mb-3">
        <div className="mb-1 text-xs text-slate-500">Grade</div>
        <div className="flex gap-1">
          {GRADES.map((grade) => (
            <button
              key={grade}
              onClick={() => props.onGrade(props.grade === grade ? "" : grade)}
              className={`h-8 w-8 rounded text-xs font-bold transition-colors ${props.grade === grade ? "bg-blue-600 text-white" : "border border-ink-700 text-slate-500 hover:border-slate-500"}`}
              type="button"
            >
              {grade}
            </button>
          ))}
        </div>
      </div>
      <ButtonGroup label="Verdict" values={VERDICTS} selected={props.verdict} onSelect={props.onVerdict} />
      <TagGroup label="Mistake Tags" tags={MISTAKE_OPTIONS} selected={props.mistakeTags} onToggle={props.onMistakeTag} danger />
      <ButtonGroup label="Trade again?" values={SHOULD_TRADE_AGAIN} selected={props.shouldTrade} onSelect={props.onShouldTrade} />
    </div>
  );
}

function StructuredReviewSection(props: {
  title: string;
  selects: Array<[string, string, string[]]>;
  values: Record<string, unknown>;
  onChange: (key: string, value: string) => void;
  tags: string[];
  selectedTags: string[];
  onToggleTag: (tag: string) => void;
}) {
  return (
    <div>
      <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">{props.title}</div>
      <div className="grid grid-cols-2 gap-2">
        {props.selects.map(([key, label, options]) => (
          <label key={key} className="block">
            <span className="mb-1 block text-xs text-slate-500">{label}</span>
            <select
              value={String(props.values[key] ?? "")}
              onChange={(event) => props.onChange(key, event.target.value)}
              className="w-full rounded border border-ink-700 bg-ink-950 px-2 py-1.5 text-xs text-slate-200"
            >
              <option value="">-</option>
              {options.map((option) => <option key={option} value={option}>{option.replace(/_/g, " ")}</option>)}
            </select>
          </label>
        ))}
      </div>
      <TagGroup label="Strategy Tags" tags={props.tags} selected={props.selectedTags} onToggle={props.onToggleTag} />
    </div>
  );
}

function OperatorReviewSection(props: {
  values: OperatorReview;
  onChange: (key: keyof OperatorReview, value: string | string[] | number | undefined) => void;
  selectedTags: string[];
  onToggleTag: (tag: string) => void;
}) {
  return (
    <div>
      <StructuredReviewSection
        title="Operator Review"
        selects={OPERATOR_SELECTS}
        values={props.values as Record<string, unknown>}
        onChange={(key, value) => props.onChange(key as keyof OperatorReview, value)}
        tags={OPERATOR_TAGS}
        selectedTags={props.selectedTags}
        onToggleTag={props.onToggleTag}
      />
      <div className="mt-2 grid grid-cols-3 gap-2">
        {[
          ["emotion_score", "Emotion"],
          ["confidence_before", "Conf before"],
          ["confidence_after", "Conf after"],
        ].map(([key, label]) => (
          <label key={key} className="block">
            <span className="mb-1 block text-xs text-slate-500">{label}</span>
            <input
              type="number"
              min={1}
              max={5}
              value={Number(props.values[key as keyof OperatorReview] ?? "") || ""}
              onChange={(event) => props.onChange(key as keyof OperatorReview, event.target.value ? Number(event.target.value) : undefined)}
              className="w-full rounded border border-ink-700 bg-ink-950 px-2 py-1.5 text-xs text-slate-200"
            />
          </label>
        ))}
      </div>
    </div>
  );
}

function ButtonGroup({ label, values, selected, onSelect }: { label: string; values: string[]; selected: string; onSelect: (value: string) => void }) {
  return (
    <div className="mb-3">
      <div className="mb-1 text-xs text-slate-500">{label}</div>
      <div className="flex flex-wrap gap-1">
        {values.map((value) => (
          <button
            key={value}
            onClick={() => onSelect(value)}
            className={`rounded px-2 py-1 text-xs transition-colors ${selected === value ? "bg-blue-600/30 text-blue-300 ring-1 ring-blue-500" : "border border-ink-700 text-slate-500 hover:border-slate-500"}`}
            type="button"
          >
            {value.replace(/_/g, " ")}
          </button>
        ))}
      </div>
    </div>
  );
}

function TagGroup(props: { label: string; tags: string[]; selected: string[]; onToggle: (tag: string) => void; danger?: boolean }) {
  return (
    <div className="mt-3">
      <div className="mb-1 text-xs text-slate-500">{props.label}</div>
      <div className="flex flex-wrap gap-1">
        {props.tags.map((tag) => {
          const active = props.selected.includes(tag);
          return (
            <button
              key={tag}
              onClick={() => props.onToggle(tag)}
              className={`rounded px-2 py-0.5 text-xs transition-colors ${active ? props.danger ? "bg-red-600/30 text-red-300 ring-1 ring-red-500" : "bg-cyan-600/25 text-cyan-200 ring-1 ring-cyan-500" : "border border-ink-700 text-slate-500 hover:border-slate-500"}`}
              type="button"
            >
              {tag.replace(/_/g, " ")}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ScreenshotsSection(props: {
  attachments: TradeReviewAttachment[];
  canCapture: boolean;
  loading: boolean;
  uploading: boolean;
  deletingId: string | null;
  onCapture: () => void;
  onUpload: (file: File | null) => void;
  onDelete: (attachment: TradeReviewAttachment) => void;
}) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">Screenshots</div>
        <div className="flex gap-1">
          <button
            onClick={props.onCapture}
            disabled={props.uploading || !props.canCapture}
            className="inline-flex items-center gap-1 rounded border border-ink-700 px-2 py-1 text-xs text-slate-300 hover:border-cyan-500 disabled:opacity-40"
            title={props.canCapture ? "Capture current chart viewport" : "Open the trade from Chart to capture the chart viewport"}
            type="button"
          >
            <Camera size={13} /> Capture Chart
          </button>
          <label className="inline-flex cursor-pointer items-center gap-1 rounded border border-ink-700 px-2 py-1 text-xs text-slate-300 hover:border-cyan-500">
            <Upload size={13} /> Upload
            <input
              type="file"
              accept="image/png"
              className="hidden"
              onChange={(event) => props.onUpload(event.target.files?.[0] ?? null)}
            />
          </label>
        </div>
      </div>
      {props.loading ? <div className="text-xs text-slate-600">Loading screenshots...</div> : null}
      <div className="grid grid-cols-2 gap-2">
        {props.attachments.map((attachment) => (
          <div key={attachment.id} className="overflow-hidden rounded border border-ink-700 bg-ink-950">
            <AuthenticatedImage attachment={attachment} />
            <div className="flex items-center justify-between px-2 py-1">
              <div className="truncate text-[11px] text-slate-500">{attachment.caption || attachment.kind}</div>
              <button
                onClick={() => props.onDelete(attachment)}
                disabled={props.deletingId === attachment.id}
                className="text-slate-600 hover:text-red-300"
                type="button"
              >
                <Trash2 size={13} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AuthenticatedImage({ attachment }: { attachment: TradeReviewAttachment }) {
  const imageQuery = useQuery({
    queryKey: ["trade-attachment-image", attachment.id],
    queryFn: async () => {
      const response = await authFetch(attachment.file_url);
      if (!response.ok) throw new Error("Image failed");
      return URL.createObjectURL(await response.blob());
    },
    staleTime: 60_000,
  });
  if (!imageQuery.data) return <div className="h-28 bg-ink-800" />;
  return <img src={imageQuery.data} alt={attachment.caption || "Trade screenshot"} className="h-28 w-full object-cover" />;
}

function FilterBar({ filters, onChange }: { filters: Filters; onChange: (f: Filters) => void }) {
  const set = (key: keyof Filters, val: string) => onChange({ ...filters, [key]: val });
  const btnCls = (active: boolean) =>
    `rounded px-2 py-1 text-xs transition-colors ${active ? "bg-blue-600/30 text-blue-300 ring-1 ring-blue-500" : "text-slate-500 hover:text-slate-300"}`;

  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-ink-700 bg-ink-900 px-4 py-2">
      <div className="flex items-center gap-1">
        <span className="text-xs text-slate-600">Outcome</span>
        {[["all", "All"], ["win", "Win"], ["loss", "Loss"]].map(([v, l]) => (
          <button key={v} className={btnCls(filters.outcome === v)} onClick={() => set("outcome", v)} type="button">{l}</button>
        ))}
      </div>
      <div className="flex items-center gap-1">
        <span className="text-xs text-slate-600">Direction</span>
        {[["all", "All"], ["long", "Long"], ["short", "Short"]].map(([v, l]) => (
          <button key={v} className={btnCls(filters.direction === v)} onClick={() => set("direction", v)} type="button">{l}</button>
        ))}
      </div>
      <div className="flex items-center gap-1">
        <span className="text-xs text-slate-600">Reviewed</span>
        {[["all", "All"], ["yes", "Yes"], ["no", "No"]].map(([v, l]) => (
          <button key={v} className={btnCls(filters.reviewed === v)} onClick={() => set("reviewed", v)} type="button">{l}</button>
        ))}
      </div>
    </div>
  );
}

function TradeRow({ trade, selected, onClick }: { trade: TradeOrder; selected: boolean; onClick: () => void }) {
  const r = trade.pnl_r;
  const reviewed = isTradeReviewComplete(trade.review);
  const accountLabel = trade.account_label || "Default";
  return (
    <tr
      onClick={onClick}
      className={`cursor-pointer border-b border-ink-700/50 text-xs transition-colors ${selected ? "bg-blue-600/10" : "hover:bg-ink-800"}`}
    >
      <td className="whitespace-nowrap px-3 py-2 text-slate-400">{fmt(trade.opened_at)}</td>
      <td className="whitespace-nowrap px-3 py-2">
        <span
          className={`inline-block max-w-40 truncate rounded border px-1.5 py-0.5 align-middle text-[11px] font-semibold ${accountBadgeClass(accountLabel)}`}
          title={accountLabel}
        >
          {accountLabel}
        </span>
      </td>
      <td className="px-3 py-2 text-slate-300">{trade.playbook}</td>
      <td className={`px-3 py-2 font-medium ${trade.direction === "long" || trade.side === "buy" ? "text-green-400" : "text-red-400"}`}>
        {trade.direction ?? trade.side}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-right tabular-nums text-slate-400">
        {trade.quantity.toLocaleString("en", { maximumFractionDigits: 4 })}
      </td>
      <td className="px-3 py-2 text-slate-400">{trade.entry_price?.toFixed(2) ?? "-"}</td>
      <td className="px-3 py-2 text-slate-400">{trade.stop_loss?.toFixed(2) ?? "-"}</td>
      <td className={`px-3 py-2 text-right font-semibold ${r !== null ? r >= 0 ? "text-green-400" : "text-red-400" : "text-slate-500"}`}>
        {r !== null ? `${r >= 0 ? "+" : ""}${r.toFixed(2)}R` : "open"}
      </td>
      <td className="px-3 py-2 text-center">
        {reviewed ? (
          <span className="rounded bg-cyan-600/25 px-1.5 py-0.5 text-xs font-bold text-cyan-200">done</span>
        ) : (
          <span className="text-slate-700">-</span>
        )}
      </td>
    </tr>
  );
}

function accountBadgeClass(accountLabel: string): string {
  const normalized = accountLabel.toLowerCase();
  if (normalized.includes("exness")) {
    return "border-amber-300/35 bg-amber-400/15 text-amber-200 shadow-[0_0_10px_rgba(251,191,36,0.10)]";
  }
  if (normalized.includes("ftmo")) {
    return "border-indigo-400/30 bg-gradient-to-r from-slate-950 via-blue-950 to-indigo-950 text-cyan-200 shadow-[0_0_12px_rgba(56,189,248,0.14)]";
  }
  return "border-slate-600/40 bg-slate-700/45 text-slate-300";
}

function PatternsTab() {
  const { data, isLoading } = useQuery({
    queryKey: ["journal-patterns", false],
    queryFn: () => fetchJournalPatterns(false),
    staleTime: 30_000,
  });
  const groups = data?.groups ?? {};
  const tables: Array<[string, JournalPatternRow[]]> = [
    ["Strategy Tags", groups.strategy_tags ?? []],
    ["Operator Action", groups.operator_action ?? []],
    ["Operator State", groups.operator_state ?? []],
    ["Followed Plan", groups.followed_plan ?? []],
    ["Zone Type", groups.zone_type ?? []],
    ["Reaction V2", groups.reaction_v2 ?? []],
    ["Stop Source", groups.stop_source ?? []],
  ];
  if (isLoading) return <div className="p-4 text-sm text-slate-500">Loading patterns...</div>;
  return (
    <div className="grid grid-cols-1 gap-4 p-4 xl:grid-cols-2">
      {tables.map(([title, rows]) => (
        <div key={title}>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500">{title}</div>
          <table className="w-full overflow-hidden rounded border border-ink-700 text-xs">
            <thead className="bg-ink-900 text-slate-500">
              <tr>
                <th className="px-3 py-2 text-left font-normal">Group</th>
                <th className="px-3 py-2 text-right font-normal">Trades</th>
                <th className="px-3 py-2 text-right font-normal">Win%</th>
                <th className="px-3 py-2 text-right font-normal">Total R</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.key} className="border-t border-ink-700/70">
                  <td className="px-3 py-2 text-slate-300">{row.key.replace(/_/g, " ")}</td>
                  <td className="px-3 py-2 text-right text-slate-400">{row.trades}</td>
                  <td className="px-3 py-2 text-right text-slate-400">{Math.round(row.win_rate * 100)}%</td>
                  <td className={`px-3 py-2 text-right font-semibold ${row.total_r >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {row.total_r >= 0 ? "+" : ""}{row.total_r.toFixed(2)}R
                  </td>
                </tr>
              ))}
              {rows.length === 0 ? (
                <tr><td colSpan={4} className="px-3 py-6 text-center text-slate-600">No data</td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

export function JournalPage({ weeklyReviewGate }: { weeklyReviewGate?: WeeklyReviewGateState }) {
  const [tab, setTab] = useState<JournalTab>(weeklyReviewGate?.active ? "queue" : "trades");
  const [filters, setFilters] = useState<Filters>({ outcome: "all", direction: "all", reviewed: "all" });
  const [selected, setSelected] = useState<TradeOrder | null>(null);
  const qc = useQueryClient();
  const reviewGateActive = weeklyReviewGate?.active === true;

  const params = new URLSearchParams({ limit: "500", backtest: "false" });
  if (filters.outcome !== "all") params.set("outcome", filters.outcome);
  if (filters.direction !== "all") params.set("side", filters.direction);

  const { data, isLoading } = useQuery({
    queryKey: ["journal-trades", params.toString()],
    queryFn: () => fetchTrades(params),
    staleTime: 15_000,
  });

  const reviewGateIds = weeklyReviewGate?.dueTradeIds ?? null;
  const trades = useMemo(() => {
    return (data?.trades ?? []).filter((trade) => {
      const reviewed = isTradeReviewComplete(trade.review);
      if ((reviewGateActive || tab === "queue") && reviewGateIds && !reviewGateIds.has(trade.id)) return false;
      if (tab === "queue" && (!trade.closed_at || trade.pnl_r === null)) return false;
      if (tab === "queue" && reviewed) return false;
      if (filters.reviewed === "yes" && !reviewed) return false;
      if (filters.reviewed === "no" && reviewed) return false;
      return true;
    });
  }, [data?.trades, filters.reviewed, reviewGateActive, reviewGateIds, tab]);

  const selectedFresh = selected ? (trades.find((trade) => trade.id === selected.id) ?? selected) : null;
  const title = reviewGateActive ? "Weekly Review Required" : "Trade Journal";

  return (
    <div className="flex h-full overflow-hidden bg-ink-950 text-slate-100">
      <div className={`flex min-w-0 flex-col ${selectedFresh ? "w-[60%]" : "w-full"} transition-all`}>
        <div className="border-b border-ink-700 bg-ink-900 px-4 py-3">
          <h1 className="text-sm font-semibold">{title}</h1>
          <div className="text-xs text-slate-500">{reviewGateActive ? `${weeklyReviewGate?.dueCount ?? trades.length} closed trades need human review` : `${trades.length} trades`}</div>
        </div>
        {reviewGateActive ? (
          <div className="border-b border-cyan-400/25 bg-cyan-400/[0.08] px-4 py-3 text-xs leading-relaxed text-cyan-50">
            Review due trades before returning to Chart or Dashboard. A grade, structured review field, or clear verdict with comment completes the gate.
          </div>
        ) : null}
        <div className="flex gap-1 border-b border-ink-700 bg-ink-900 px-4 py-2">
          {[
            ["trades", "Trades"],
            ["queue", "Review Queue"],
            ["patterns", "Patterns"],
          ].map(([value, label]) => (
            <button
              key={value}
              onClick={() => setTab(value as JournalTab)}
              className={`rounded px-3 py-1.5 text-xs font-medium ${tab === value ? "bg-cyan-500/15 text-cyan-200 ring-1 ring-cyan-500/50" : "text-slate-500 hover:text-slate-300"}`}
              type="button"
            >
              {label}
            </button>
          ))}
        </div>
        {tab === "patterns" ? (
          <PatternsTab />
        ) : (
          <>
            <FilterBar filters={filters} onChange={setFilters} />
            <div className="flex-1 overflow-auto">
              {isLoading ? (
                <div className="flex h-32 items-center justify-center text-sm text-slate-500">Loading...</div>
              ) : trades.length === 0 ? (
                <div className="flex h-32 items-center justify-center text-sm text-slate-600">No trades found</div>
              ) : (
                <table className="w-full min-w-[980px]">
                  <thead>
                    <tr className="border-b border-ink-700 bg-ink-900 text-xs text-slate-500">
                      <th className="px-3 py-2 text-left font-normal">Date (UTC)</th>
                      <th className="px-3 py-2 text-left font-normal">Account</th>
                      <th className="px-3 py-2 text-left font-normal">Playbook</th>
                      <th className="px-3 py-2 text-left font-normal">Dir</th>
                      <th className="px-3 py-2 text-right font-normal">Volume (lot)</th>
                      <th className="px-3 py-2 text-left font-normal">Entry</th>
                      <th className="px-3 py-2 text-left font-normal">SL</th>
                      <th className="px-3 py-2 text-right font-normal">PnL</th>
                      <th className="px-3 py-2 text-center font-normal">Review</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((trade) => (
                      <TradeRow
                        key={trade.id}
                        trade={trade}
                        selected={selectedFresh?.id === trade.id}
                        onClick={() => setSelected(selectedFresh?.id === trade.id ? null : trade)}
                      />
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
      </div>

      {selectedFresh ? (
        <div className="w-[40%] min-w-[360px] flex-shrink-0">
          <DetailPanel
            trade={selectedFresh}
            onClose={() => setSelected(null)}
            onSaved={() => qc.invalidateQueries({ queryKey: ["journal-trades"] })}
          />
        </div>
      ) : null}
    </div>
  );
}
