import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, Eye, EyeOff, Save } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toPng } from "html-to-image";
import { createTradeReviewAttachment, fetchTradeReviewAttachments, updateTradeReview, updateTradeVisibility } from "../../api/chart";
import { authFetch } from "../../api/auth";
import { compactTime, price } from "../../lib/time";
import { useChartStore } from "../../store/chartStore";
import type { ChartPayload, TradeHistoryResponse, TradeOrder, TradeReview, TradeReviewAttachment } from "../../types";

type ToastKind = "success" | "error";

type StateMachineStep = {
  key: string;
  label: string;
  status: string;
};

type AccountPartialTakeProfitSettings = {
  enabled: boolean;
  trigger_r: number;
};

async function fetchAccountPartialTakeProfit(accountLabel: string): Promise<AccountPartialTakeProfitSettings> {
  const response = await authFetch("/api/accounts");
  if (!response.ok) throw new Error("Could not load Partial TP settings.");
  const body = (await response.json()) as {
    accounts?: Array<{ label: string; partial_take_profit?: AccountPartialTakeProfitSettings }>;
  };
  const account = body.accounts?.find((item) => item.label === accountLabel);
  if (!account?.partial_take_profit) throw new Error("Account worker has not registered Partial TP settings yet.");
  return account.partial_take_profit;
}

async function updateAccountPartialTakeProfit(
  accountLabel: string,
  settings: AccountPartialTakeProfitSettings,
): Promise<AccountPartialTakeProfitSettings> {
  const response = await authFetch(`/api/accounts/${encodeURIComponent(accountLabel)}/partial-take-profit`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail ?? "Could not update Partial TP settings.");
  return body.partial_take_profit as AccountPartialTakeProfitSettings;
}

export function TradeDetails({ trade, showToast }: { trade: TradeOrder; showToast: (kind: ToastKind, text: string) => void }) {
  const queryClient = useQueryClient();
  const setSelected = useChartStore((state) => state.setSelected);
  const metadata = trade.metadata ?? {};
  const candidateMetadata = readObject(metadata.candidate_metadata);
  const stateMachine = readStateMachine(candidateMetadata.state_machine);
  const reasons = readStringList(metadata.reason);
  const blockedReasons = readStringList(metadata.blocked_reason);
  const triggerTypes = readStringList(candidateMetadata.trigger_types);
  const stopLossMode = readString(candidateMetadata.stop_source) ?? readString(metadata.stop_source);
  const takeProfit = firstTakeProfitPrice(trade.take_profit);
  const partialPlan = readObject(metadata.partial_take_profit);
  const partialDone = partialPlan.done === true;
  const breakevenApplied = partialPlan.breakeven_applied === true;
  const initialStopLoss = readNumber(metadata.initial_stop_loss);
  const displayedStopLoss = initialStopLoss ?? trade.stop_loss;
  const stopLossSize =
    trade.entry_price !== null && displayedStopLoss !== null
      ? Math.abs(trade.entry_price - displayedStopLoss)
      : null;
  const reactionBody = readNumber(candidateMetadata.reaction_body) ?? readNumber(metadata.reaction_body);
  const reactionAverageBody =
    readNumber(candidateMetadata.reaction_avg_body) ?? readNumber(metadata.reaction_avg_body);
  const reactionTriggerMethod =
    readString(candidateMetadata.reaction_trigger_method) ?? readString(metadata.reaction_trigger_method);
  const reactionRejectionSize =
    readNumber(candidateMetadata.reaction_rejection_size) ?? readNumber(metadata.reaction_rejection_size);
  const reactionRejectionRatio =
    readNumber(candidateMetadata.reaction_rejection_avg_ratio) ??
    readNumber(metadata.reaction_rejection_avg_ratio);
  const storedReactionBodyRatio =
    readNumber(candidateMetadata.reaction_body_avg_ratio) ?? readNumber(metadata.reaction_body_avg_ratio);
  const reactionBodyRatio =
    storedReactionBodyRatio ??
    (reactionBody !== null && reactionAverageBody !== null && reactionAverageBody > 0
      ? reactionBody / reactionAverageBody
      : null);
  const showCurrentStopLoss =
    initialStopLoss !== null && trade.stop_loss !== null && Math.abs(initialStopLoss - trade.stop_loss) > 1e-9;
  const statusNote = tradeStatusNote(trade.status);
  const visibilityMutation = useMutation({
    mutationFn: () => updateTradeVisibility(trade.id, !trade.hidden_on_chart),
    onSuccess: (saved) => {
      const updateTrade = (item: TradeOrder): TradeOrder =>
        item.id === saved.id ? { ...item, hidden_on_chart: saved.hidden_on_chart } : item;
      queryClient.setQueriesData<ChartPayload>({ queryKey: ["chart"] }, (current) =>
        current
          ? { ...current, layers: { ...current.layers, trades: current.layers.trades.map(updateTrade) } }
          : current,
      );
      queryClient.setQueriesData<TradeHistoryResponse>({ queryKey: ["trade-history"] }, (current) =>
        current ? { ...current, trades: current.trades.map(updateTrade) } : current,
      );
      setSelected({ kind: "trade", entity: updateTrade(trade) });
      showToast("success", saved.hidden_on_chart ? "Trade hidden from chart." : "Trade restored on chart.");
    },
    onError: (error) => {
      showToast("error", error instanceof Error ? error.message : "Could not update trade visibility.");
    },
  });

  return (
    <div className="grid gap-3 text-sm">
      <div className="grid gap-2">
        <Detail label="Account" value={trade.account_label ?? "--"} />
        <Detail label="Playbook" value={playbookLabel(trade.playbook)} />
        <Detail label="Side" value={trade.side} />
        <Detail label="Status" value={trade.status} />
        <Detail label="Backtest" value={metadata.backtest === true ? "true" : "--"} />
      </div>

      {statusNote ? (
        <div className="rounded-md border border-yellow-300/25 bg-yellow-300/[0.06] p-2 text-xs leading-relaxed text-yellow-50">
          {statusNote}
        </div>
      ) : null}

      <button
        className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-ink-700 bg-ink-850 px-3 text-sm text-slate-200 hover:border-cyan-500 disabled:opacity-50"
        disabled={visibilityMutation.isPending}
        type="button"
        onClick={() => visibilityMutation.mutate()}
      >
        {trade.hidden_on_chart ? <Eye size={15} /> : <EyeOff size={15} />}
        {visibilityMutation.isPending
          ? "Saving..."
          : trade.hidden_on_chart
            ? "Show on chart"
            : "Hide from chart"}
      </button>

      <div className="grid gap-2 rounded-md border border-ink-700 bg-ink-950/60 p-3">
        <TradeMetric label="Entry" value={price(trade.entry_price)} />
        <TradeMetric label={showCurrentStopLoss ? "Initial SL" : "SL"} value={price(displayedStopLoss)} />
        {showCurrentStopLoss ? <TradeMetric label="Current SL" value={price(trade.stop_loss)} /> : null}
        <TradeMetric label="TP" value={price(takeProfit)} />
        <TradeMetric label="Exit" value={price(trade.close_price)} />
        <TradeMetric label="SL size" value={price(stopLossSize)} />
        <TradeMetric
          label="BT/R"
          value={formatBodyTriggerMetric(reactionBody, reactionBodyRatio, reactionAverageBody)}
        />
        {reactionTriggerMethod === "pinbar" ? (
          <TradeMetric
            label="Pinbar/R"
            value={formatReactionStrengthMetric(reactionRejectionSize, reactionRejectionRatio)}
          />
        ) : null}
        <TradeMetric label="PnL R" value={trade.pnl_r === null ? "--" : `${trade.pnl_r.toFixed(2)}R`} />
        <TradeMetric label="Score" value={formatUnknownNumber(metadata.score)} />
      </div>

      {Object.keys(partialPlan).length > 0 ? (
        <div className="grid gap-2 rounded-md border border-emerald-400/25 bg-emerald-400/[0.06] p-3">
          <TradeMetric label="Partial" value={partialDone ? "done" : "armed"} />
          <TradeMetric label="Trigger" value={`${formatUnknownNumber(partialPlan.trigger_r)}R @ ${price(readNumber(partialPlan.trigger_price))}`} />
          <TradeMetric label="Partial close" value={partialDone ? `${formatUnknownNumber(partialPlan.closed_volume)} lot` : "--"} />
          <TradeMetric
            label="BE SL"
            value={breakevenApplied ? price(readNumber(partialPlan.breakeven_stop)) : partialDone ? "pending" : price(readNumber(partialPlan.breakeven_stop))}
          />
        </div>
      ) : null}

      {trade.source === "live" && trade.account_label && ["filled", "pending_fill"].includes(trade.status) ? (
        <PartialTakeProfitControls accountLabel={trade.account_label} showToast={showToast} />
      ) : null}

      <div className="grid gap-2">
        <Detail label="Opened" value={compactTime(trade.opened_at)} />
        <Detail label="Closed" value={compactTime(trade.closed_at)} />
        <Detail label="Reaction" value={String(metadata.zone_reaction_state ?? "--")} />
        <Detail label="Zone" value={String(candidateMetadata.zone_type ?? "--")} />
        <Detail label="SL mode" value={stopLossMode ?? "--"} />
        <Detail label="Trigger" value={triggerTypes.length > 0 ? triggerTypes.join(" + ") : "--"} />
      </div>

      <StateMachine steps={stateMachine} />

      <div className="grid gap-1">
        <div className="text-xs text-slate-500">Reason</div>
        <div className="rounded-md border border-cyan-400/25 bg-cyan-400/[0.06] p-2 text-xs leading-relaxed text-cyan-50">
          {reasons.length > 0 ? (
            <ul className="grid gap-1">
              {reasons.map((reason, index) => (
                <li key={`${reason}-${index}`}>- {reason}</li>
              ))}
            </ul>
          ) : (
            "--"
          )}
        </div>
      </div>

      {blockedReasons.length > 0 ? (
        <div className="grid gap-1">
          <div className="text-xs text-slate-500">Blocked reason at signal</div>
          <div className="rounded-md border border-rose-400/25 bg-rose-500/[0.06] p-2 text-xs leading-relaxed text-rose-50">
            <ul className="grid gap-1">
              {blockedReasons.map((reason, index) => (
                <li key={`${reason}-${index}`}>- {reason}</li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}

      <TradeReviewEditor
        trade={trade}
        showToast={showToast}
        onSaved={(review) => {
          setSelected({ kind: "trade", entity: { ...trade, review } });
        }}
      />
    </div>
  );
}

function PartialTakeProfitControls({
  accountLabel,
  showToast,
}: {
  accountLabel: string;
  showToast: (kind: ToastKind, text: string) => void;
}) {
  const queryClient = useQueryClient();
  const settingsQuery = useQuery({
    queryKey: ["account-partial-take-profit", accountLabel],
    queryFn: () => fetchAccountPartialTakeProfit(accountLabel),
    staleTime: 15_000,
  });
  const [triggerDraft, setTriggerDraft] = useState("1.25");
  const settings = settingsQuery.data;

  useEffect(() => {
    if (settings) setTriggerDraft(settings.trigger_r.toString());
  }, [settings]);

  const mutation = useMutation({
    mutationFn: (next: AccountPartialTakeProfitSettings) => updateAccountPartialTakeProfit(accountLabel, next),
    onSuccess: (saved) => {
      queryClient.setQueryData(["account-partial-take-profit", accountLabel], saved);
      void queryClient.invalidateQueries({ queryKey: ["accounts"] });
      showToast("success", `Partial TP ${saved.enabled ? `ON at ${saved.trigger_r}R` : "OFF"} for ${accountLabel}.`);
    },
    onError: (error) => {
      showToast("error", error instanceof Error ? error.message : "Could not update Partial TP settings.");
    },
  });

  const parsedTrigger = Number(triggerDraft);
  const validTrigger = Number.isFinite(parsedTrigger) && parsedTrigger >= 0.5 && parsedTrigger <= 2;
  const save = (enabled: boolean) => {
    if (!validTrigger) {
      showToast("error", "Partial TP trigger must be between 0.5R and 2.0R.");
      return;
    }
    mutation.mutate({ enabled, trigger_r: parsedTrigger });
  };

  return (
    <div className="grid gap-3 rounded-md border border-cyan-400/25 bg-cyan-400/[0.05] p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold text-cyan-100">Partial TP automation</div>
          <div className="mt-0.5 text-[10px] text-slate-500">{accountLabel}</div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={settings?.enabled ?? false}
          disabled={!settings || mutation.isPending}
          onClick={() => save(!settings?.enabled)}
          className={`flex items-center gap-2 rounded-full border px-2.5 py-1 text-[11px] font-semibold transition ${
            settings?.enabled
              ? "border-cyan-400/50 bg-cyan-400/10 text-cyan-200"
              : "border-ink-600 bg-ink-950 text-slate-500"
          } disabled:cursor-not-allowed disabled:opacity-50`}
        >
          <span className={`relative h-4 w-7 rounded-full ${settings?.enabled ? "bg-cyan-500" : "bg-ink-600"}`}>
            <span className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all ${settings?.enabled ? "left-3.5" : "left-0.5"}`} />
          </span>
          {settings?.enabled ? "ON" : "OFF"}
        </button>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2">
        <label className="grid gap-1 text-[11px] text-slate-500">
          Trigger R
          <input
            type="number"
            min="0.5"
            max="2"
            step="0.25"
            value={triggerDraft}
            onChange={(event) => setTriggerDraft(event.target.value)}
            className="h-9 min-w-0 rounded-md border border-ink-700 bg-ink-950 px-2 text-sm font-semibold text-slate-100 outline-none focus:border-cyan-400"
          />
        </label>
        <button
          type="button"
          disabled={!settings || !validTrigger || mutation.isPending}
          onClick={() => save(settings?.enabled ?? true)}
          className="mt-[19px] h-9 rounded-md border border-cyan-400/50 bg-cyan-400/10 px-3 text-xs font-semibold text-cyan-100 hover:bg-cyan-400/20 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {mutation.isPending ? "Saving" : "Apply"}
        </button>
      </div>

      <div className="flex gap-2">
        {[1, 1.25].map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setTriggerDraft(value.toString())}
            className="rounded border border-ink-700 bg-ink-950 px-2 py-1 text-[11px] text-slate-300 hover:border-cyan-400/50 hover:text-cyan-100"
          >
            {value.toFixed(2)}R
          </button>
        ))}
      </div>

      <p className="text-[10px] leading-relaxed text-slate-500">
        Applies to every armed live trade and future trade on this account. Lowering the trigger below current profit can execute on the next worker cycle; closed history is unchanged.
      </p>
      {settingsQuery.isError ? <div className="text-xs text-rose-300">{settingsQuery.error.message}</div> : null}
    </div>
  );
}

function TradeMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-xs text-slate-500">{label}</span>
      <strong className="shrink-0 whitespace-nowrap text-right text-sm text-slate-100">{value}</strong>
    </div>
  );
}

const REVIEW_TAGS = [
  ["wrong_bias", "Wrong bias"],
  ["wrong_regime", "Wrong regime"],
  ["weak_zone", "Weak zone"],
  ["zone_already_broken", "Zone broken"],
  ["weak_reaction", "Weak reaction"],
  ["weak_breakout", "Weak breakout"],
  ["bad_entry", "Bad entry"],
  ["sl_too_tight", "SL too tight"],
  ["tp_unrealistic", "TP unrealistic"],
  ["against_momentum", "Against momentum"],
  ["news_risk", "News risk"],
  ["good_context", "Good context"],
] as const;

function TradeReviewEditor({
  trade,
  onSaved,
  showToast,
}: {
  trade: TradeOrder;
  onSaved: (review: TradeReview) => void;
  showToast: (kind: ToastKind, text: string) => void;
}) {
  const qc = useQueryClient();
  const review = trade.review;
  const [grade, setGrade] = useState(review?.grade ?? "");
  const [verdict, setVerdict] = useState(review?.verdict ?? "unreviewed");
  const [shouldTradeAgain, setShouldTradeAgain] = useState(review?.should_trade_again ?? "unknown");
  const [mistakeTags, setMistakeTags] = useState<Set<string>>(new Set(review?.mistake_tags ?? []));
  const [comment, setComment] = useState(review?.comment ?? "");
  const [error, setError] = useState<string | null>(null);
  const attachmentsQuery = useQuery({
    queryKey: ["trade-attachments", trade.id],
    queryFn: () => fetchTradeReviewAttachments(trade.id),
    staleTime: 15_000,
  });
  const mutation = useMutation({
    mutationFn: () =>
      updateTradeReview(trade.id, {
        grade: grade || null,
        verdict,
        mistake_tags: Array.from(mistakeTags),
        should_trade_again: shouldTradeAgain,
        comment,
        reviewer: "human",
        strategy_review: review?.strategy_review ?? {},
        operator_review: review?.operator_review ?? {},
      }),
    onSuccess: (savedReview) => {
      setError(null);
      onSaved(savedReview);
      showToast("success", "Trade review saved.");
    },
    onError: (err) => {
      const message = err instanceof Error ? err.message : "Could not save trade review.";
      setError(message);
      showToast("error", message);
    },
  });
  const captureMutation = useMutation({
    mutationFn: async () => {
      const node = document.querySelector("[data-chart-capture-root='true']");
      if (!(node instanceof HTMLElement)) {
        throw new Error("Chart viewport is not available.");
      }
      const imageData = await toPng(node, { cacheBust: true, pixelRatio: 1, backgroundColor: "#080b10" });
      return createTradeReviewAttachment(trade.id, {
        kind: "review",
        image_data: imageData,
        caption: "Chart review snapshot",
        chart_symbol: "XAUUSD",
        chart_timeframe: "H1",
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["trade-attachments", trade.id] });
      showToast("success", "Chart screenshot captured.");
    },
    onError: (err) => {
      const message = err instanceof Error ? err.message : "Could not capture chart.";
      showToast("error", message);
    },
  });
  const saveReview = useCallback(() => {
    mutation.mutate();
  }, [mutation]);

  useEffect(() => {
    setGrade(review?.grade ?? "");
    setVerdict(review?.verdict ?? "unreviewed");
    setShouldTradeAgain(review?.should_trade_again ?? "unknown");
    setMistakeTags(new Set(review?.mistake_tags ?? []));
    setComment(review?.comment ?? "");
    setError(null);
  }, [review, trade.id]);

  const toggleTag = (tag: string) => {
    setMistakeTags((current) => toggleSetValue(current, tag));
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return;
      if (event.key.toLowerCase() !== "s") return;
      event.preventDefault();
      saveReview();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [saveReview]);

  return (
    <div className="grid gap-3 rounded-md border border-ink-700 bg-ink-950/60 p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Human Review</div>
        <div className="flex items-center gap-2">
          {review?.updated_at ? <span className="hidden text-[10px] text-slate-600 sm:inline">{compactTime(review.updated_at)}</span> : null}
          <button
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-cyan-400/60 bg-cyan-400/15 px-2 text-xs font-semibold text-cyan-100 hover:bg-cyan-400/25 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={mutation.isPending}
            title="Save review (S)"
            type="button"
            onClick={saveReview}
          >
            <Save size={13} />
            {mutation.isPending ? "Saving" : "Save"}
          </button>
        </div>
      </div>

      <div className="grid gap-2 rounded-md border border-ink-700 bg-ink-850/50 p-2">
        <div className="flex items-center justify-between gap-2">
          <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Screenshots</div>
          <button
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-cyan-400/60 bg-cyan-400/15 px-2 text-xs font-semibold text-cyan-100 hover:bg-cyan-400/25 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={captureMutation.isPending}
            type="button"
            onClick={() => captureMutation.mutate()}
          >
            <Camera size={13} />
            {captureMutation.isPending ? "Capturing" : "Capture Chart"}
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {(attachmentsQuery.data ?? []).slice(0, 4).map((attachment) => (
            <AttachmentThumb key={attachment.id} attachment={attachment} />
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <ReviewSelect value={grade} onChange={setGrade} options={[["", "No grade"], ["A", "A"], ["B", "B"], ["C", "C"], ["D", "D"]]} />
        <ReviewSelect
          value={verdict}
          onChange={setVerdict}
          options={[
            ["unreviewed", "Unreviewed"],
            ["good_trade", "Good trade"],
            ["bad_trade", "Bad trade"],
            ["should_skip", "Should skip"],
            ["missed_context", "Missed context"],
          ]}
        />
      </div>

      <ReviewSelect
        value={shouldTradeAgain}
        onChange={setShouldTradeAgain}
        options={[
          ["unknown", "Trade again?"],
          ["yes", "Yes"],
          ["no", "No"],
          ["conditional", "Conditional"],
        ]}
      />

      <div className="flex flex-wrap gap-1.5">
        {REVIEW_TAGS.map(([tag, label]) => (
          <button
            key={tag}
            className={`rounded border px-2 py-1 text-[11px] transition ${
              mistakeTags.has(tag)
                ? "border-cyan-300/70 bg-cyan-300/15 text-cyan-100"
                : "border-ink-700 bg-ink-850 text-slate-400 hover:border-slate-500 hover:text-slate-200"
            }`}
            type="button"
            onClick={() => toggleTag(tag)}
          >
            {label}
          </button>
        ))}
      </div>

      <label className="grid gap-1 text-xs text-slate-500">
        Comment
        <textarea
          className="min-h-24 resize-y rounded-md border border-ink-700 bg-ink-850 px-2 py-2 text-sm leading-relaxed text-slate-100 outline-none focus:border-cyan-400"
          placeholder="Trade notes..."
          value={comment}
          onChange={(event) => setComment(event.target.value)}
        />
      </label>

      {error ? <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-2 text-xs text-rose-100">{error}</div> : null}

      <button
        className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-cyan-400/60 bg-cyan-400/15 text-sm font-semibold text-cyan-100 hover:bg-cyan-400/25 disabled:cursor-not-allowed disabled:opacity-50"
        disabled={mutation.isPending}
        title="Save review (S)"
        type="button"
        onClick={saveReview}
      >
        <Save size={14} />
        {mutation.isPending ? "Saving review" : "Save review (S)"}
      </button>
    </div>
  );
}

function AttachmentThumb({ attachment }: { attachment: TradeReviewAttachment }) {
  const imageQuery = useQuery({
    queryKey: ["trade-attachment-image", attachment.id],
    queryFn: async () => {
      const response = await authFetch(attachment.file_url);
      if (!response.ok) throw new Error("Image failed");
      return URL.createObjectURL(await response.blob());
    },
    staleTime: 60_000,
  });
  if (!imageQuery.data) return <div className="h-20 rounded bg-ink-800" />;
  return <img src={imageQuery.data} alt={attachment.caption || "Trade screenshot"} className="h-20 w-full rounded object-cover" />;
}

function ReviewSelect({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  options: Array<[string, string]>;
}) {
  return (
    <select
      className="h-9 min-w-0 rounded-md border border-ink-700 bg-ink-850 px-2 text-xs text-slate-200 outline-none focus:border-cyan-400"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    >
      {options.map(([optionValue, label]) => (
        <option key={optionValue} value={optionValue}>
          {label}
        </option>
      ))}
    </select>
  );
}

function StateMachine({ steps, compact = false }: { steps: StateMachineStep[]; compact?: boolean }) {
  if (steps.length === 0) return null;
  return (
    <div className={compact ? "mt-2 flex min-w-0 flex-wrap gap-1" : "grid min-w-0 gap-1"}>
      {!compact ? <div className="text-xs text-slate-500">State machine</div> : null}
      <div className="flex min-w-0 flex-wrap gap-1 overflow-hidden">
        {steps.map((step) => (
          <span
            key={step.key}
            className={`rounded border px-1.5 py-0.5 text-[10px] ${
              step.status === "active"
                ? "border-cyan-300/70 bg-cyan-300/15 text-cyan-100"
                : step.status === "done"
                  ? "border-emerald-300/30 bg-emerald-300/[0.06] text-emerald-200"
                  : "border-ink-700 bg-ink-950 text-slate-500"
            }`}
            title={step.label}
          >
            {compact ? shortStateLabel(step.key) : step.key}
          </span>
        ))}
      </div>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] gap-3">
      <span className="text-slate-500">{label}</span>
      <strong className="min-w-0 break-words text-slate-100">{value}</strong>
    </div>
  );
}

function playbookLabel(value: string): string {
  if (value === "sr_breakout_v1") return "SR Breakout V1";
  if (value === "zone_reaction_v2") return "Zone Reaction V2";
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function shortStateLabel(value: string): string {
  const labels: Record<string, string> = {
    IDLE: "IDLE",
    ZONE_TOUCHED: "TOUCH",
    REACTING_IN_ZONE: "REACT",
    WAIT_FOR_BOS: "BOS",
    WAITING_RETEST: "RETEST",
    BIAS_WARNING: "WARN",
    PREPARE_ENTRY: "ENTRY",
  };
  return labels[value] ?? value;
}

function readStateMachine(value: unknown): StateMachineStep[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => (item && typeof item === "object" && !Array.isArray(item) ? (item as Record<string, unknown>) : null))
    .filter((item): item is Record<string, unknown> => item !== null)
    .map((item) => ({
      key: typeof item.key === "string" ? item.key : "--",
      label: typeof item.label === "string" ? item.label : "--",
      status: typeof item.status === "string" ? item.status : "pending",
    }));
}

function readObject(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function readStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.length > 0);
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function firstTakeProfitPrice(values: TradeOrder["take_profit"]): number | null {
  const first = values.at(0);
  if (typeof first === "number") return first;
  if (first && typeof first.price === "number") return first.price;
  return null;
}

function formatUnknownNumber(value: unknown): string {
  return typeof value === "number" ? value.toFixed(2) : "--";
}

function formatBodyTriggerMetric(body: number | null, ratio: number | null, averageBody: number | null): string {
  if (body === null || ratio === null || averageBody === null) return "--";
  return `${body.toFixed(2)} / ${ratio.toFixed(2)}x · avg20 ${averageBody.toFixed(2)}`;
}

function formatReactionStrengthMetric(size: number | null, ratio: number | null): string {
  if (size === null || ratio === null) return "--";
  return `${size.toFixed(2)} / ${ratio.toFixed(2)}x`;
}

function tradeStatusNote(status: string): string | null {
  if (status === "time_exit") {
    return "Time exit: trade did not hit SL/TP within max hold time, so it closed at the expiry candle close.";
  }
  if (status === "target_hit") return "Target hit: price reached TP during the trade hold window.";
  if (status === "stopped") return "Stopped: price reached SL during the trade hold window.";
  return null;
}

function toggleSetValue(current: Set<string>, value: string): Set<string> {
  const next = new Set(current);
  if (next.has(value)) {
    next.delete(value);
  } else {
    next.add(value);
  }
  return next;
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName.toLowerCase();
  return tagName === "input" || tagName === "textarea" || tagName === "select" || target.isContentEditable;
}
