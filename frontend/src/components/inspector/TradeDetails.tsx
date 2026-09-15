import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, Check, Copy, Eye, EyeOff, Percent, Save, ShieldCheck, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toPng } from "html-to-image";
import { createTradeReviewAttachment, executeTradeManagementAction, fetchTradeReviewAttachments, updateTradeReview, updateTradeVisibility, type TradeManagementAction, type TradeManagementCommand } from "../../api/chart";
import { authFetch } from "../../api/auth";
import { copyTextToClipboard } from "../../lib/clipboard";
import { compactTime, price } from "../../lib/time";
import { useChartStore } from "../../store/chartStore";
import type { ChartPayload, TradeHistoryResponse, TradeOrder, TradeReview, TradeReviewAttachment } from "../../types";

type ToastKind = "success" | "error";

const MANUAL_TRADE_MANAGEMENT_ENABLED = true;

type StateMachineStep = {
  key: string;
  label: string;
  status: string;
};

type AccountPartialTakeProfitSettings = {
  enabled: boolean;
  trigger_r: number;
  fraction: number;
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
  const [copiedTradeId, setCopiedTradeId] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<TradeManagementAction | null>(null);
  const metadata = trade.metadata ?? {};
  const candidateMetadata = readObject(metadata.candidate_metadata);
  const stateMachine = readStateMachine(candidateMetadata.state_machine);
  const reasons = readStringList(metadata.reason);
  const blockedReasons = readStringList(metadata.blocked_reason);
  const triggerTypes = readStringList(candidateMetadata.trigger_types);
  const stopLossMode = readString(candidateMetadata.stop_source) ?? readString(metadata.stop_source);
  const takeProfit = firstTakeProfitPrice(trade.take_profit);
  const partialPlan = readObject(metadata.partial_take_profit);
  const entryDiscount = readObject(candidateMetadata.entry_discount);
  const tradeManagement = readObject(metadata.trade_management);
  const partialDone = partialPlan.done === true;
  const breakevenOnly = readNumber(partialPlan.fraction) === 0;
  const breakevenApplied = partialPlan.breakeven_applied === true;
  const initialStopLoss = readNumber(metadata.initial_stop_loss);
  const brokerEntryPrice = readNumber(metadata.broker_position_entry_price) ?? trade.entry_price;
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
  const stopAtBreakEven = isStopAtBreakEven(trade.side, trade.stop_loss, brokerEntryPrice);
  const closeExecuted = tradeManagement.last_action === "close_now";
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
  const managementMutation = useMutation({
    mutationFn: (action: TradeManagementAction) => executeTradeManagementAction(trade.id, action),
    onSuccess: (command, action) => {
      setConfirmAction(null);
      if (command.status !== "succeeded") {
        showToast("success", "Action queued. The account worker is still processing it.");
        return;
      }
      const updatedTrade = applyTradeManagementPatch(trade, command);
      const updateTrade = (item: TradeOrder): TradeOrder => item.id === trade.id ? updatedTrade : item;
      queryClient.setQueriesData<ChartPayload>({ queryKey: ["chart"] }, (current) =>
        current ? { ...current, layers: { ...current.layers, trades: current.layers.trades.map(updateTrade) } } : current,
      );
      queryClient.setQueriesData<TradeHistoryResponse>({ queryKey: ["trade-history"] }, (current) =>
        current ? { ...current, trades: current.trades.map(updateTrade) } : current,
      );
      setSelected({ kind: "trade", entity: updatedTrade });
      void queryClient.invalidateQueries({ queryKey: ["chart"] });
      void queryClient.invalidateQueries({ queryKey: ["trade-history"] });
      const breakEvenError = readString(readObject(command.result).break_even_error);
      if (breakEvenError) {
        showToast("error", `Partial close completed, but break-even failed: ${breakEvenError}`);
      } else {
        showToast("success", tradeActionSuccessMessage(action));
      }
    },
    onError: (error) => {
      showToast("error", error instanceof Error ? error.message : "Trade action failed.");
    },
  });

  const copyTradeId = useCallback(async () => {
    try {
      await copyTextToClipboard(trade.id);
      setCopiedTradeId(trade.id);
      showToast("success", "Trade ID copied.");
      window.setTimeout(() => {
        setCopiedTradeId((current) => (current === trade.id ? null : current));
      }, 1500);
    } catch {
      showToast("error", "Could not copy trade ID.");
    }
  }, [showToast, trade.id]);

  return (
    <div className="grid gap-3 text-sm">
      <div className="grid gap-2">
        <TradeIdDetail copied={copiedTradeId === trade.id} tradeId={trade.id} onCopy={copyTradeId} />
        <Detail label="Account" value={trade.account_label ?? "--"} />
        <Detail label="Playbook" value={playbookLabel(trade.playbook)} />
        <Detail label="Side" value={trade.side} />
        <Detail label="Status" value={trade.status} />
        <Detail label="Backtest" value={metadata.backtest === true ? "true" : "--"} />
      </div>

      {trade.source === "live" && trade.status === "filled" && !closeExecuted ? (
        <div className="grid gap-2 rounded-lg border border-cyan-300/25 bg-cyan-300/[0.05] p-3">
          <div className="text-xs font-semibold text-cyan-100">Vé đã mua · Giữ đúng kế hoạch</div>
          {trade.stop_loss !== null && Number.isFinite(trade.stop_loss) && trade.stop_loss > 0 ? (
            <>
              <p className="text-xs leading-relaxed text-slate-300">
                Risk đã định trước là chi phí của tấm vé. Một cảnh kịch tính chưa phải lý do
                rời rạp: hãy để lệnh đi theo SL, TP và quy tắc quản lý đã chọn.
              </p>
              <div className="grid grid-cols-2 gap-2">
                <TradeMetric label="SL đang lưu" value={price(trade.stop_loss)} />
                <TradeMetric label="TP kế hoạch" value={price(takeProfit)} />
              </div>
              <p className="text-[11px] leading-relaxed text-slate-400">
                Muốn can thiệp? Rời tay khỏi chuột, thở chậm và đọc lại điều kiện thoát.
                Chỉ thay đổi khi điều kiện đã định trước xảy ra hoặc có lỗi thực thi.
                Không nới SL hay đổi partial TP chỉ để bớt lo.
              </p>
              <p className="text-[10px] leading-relaxed text-slate-500">
                SL trên dashboard là dữ liệu đã lưu, không xác nhận bảo vệ hiện tại tại broker.
                Tấm vé không đảm bảo thắng hay giới hạn tuyệt đối khoản lỗ khi có trượt giá.
              </p>
            </>
          ) : (
            <p className="text-xs leading-relaxed text-amber-200">
              Chưa có SL hợp lệ trong dữ liệu lệnh. Kiểm tra và xử lý bảo vệ tại broker;
              lời nhắc “ngồi yên xem kịch” không áp dụng khi thiếu SL.
            </p>
          )}
        </div>
      ) : null}

      {statusNote ? (
        <div className="rounded-md border border-yellow-300/25 bg-yellow-300/[0.06] p-2 text-xs leading-relaxed text-yellow-50">
          {statusNote}
        </div>
      ) : null}

      {trade.source === "live" && trade.account_label && trade.status === "filled" && closeExecuted ? (
        <div className="rounded-md border border-rose-400/30 bg-rose-500/[0.06] p-3 text-xs text-rose-100">
          Close executed by the account worker; waiting for the broker close deal to sync.
        </div>
      ) : null}

      {trade.source === "live" && trade.account_label && trade.status === "filled" && !closeExecuted ? (
        <TradeManagementActions
          action={confirmAction}
          breakevenDone={breakevenApplied || stopAtBreakEven}
          busy={managementMutation.isPending}
          disabled={!MANUAL_TRADE_MANAGEMENT_ENABLED}
          partialDone={partialDone}
          onCancel={() => setConfirmAction(null)}
          onConfirm={() => {
            if (confirmAction) managementMutation.mutate(confirmAction);
          }}
          onSelect={setConfirmAction}
        />
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

      {trade.playbook === "line_reaction_v1" && Object.keys(entryDiscount).length > 0 ? (
        <div className="grid gap-2 rounded-md border border-cyan-400/25 bg-cyan-400/[0.06] p-3">
          <TradeMetric label="Entry mode" value={String(entryDiscount.source ?? "--")} />
          <TradeMetric label="Recovery" value={`${formatUnknownNumber(entryDiscount.recovery_ratio)}x`} />
          <TradeMetric label="Manual offset" value={price(readNumber(entryDiscount.manual_offset))} />
          <TradeMetric label="Auto offset" value={price(readNumber(entryDiscount.auto_offset))} />
          <TradeMetric label="Final offset" value={price(readNumber(entryDiscount.effective_offset))} />
        </div>
      ) : null}

      {Object.keys(partialPlan).length > 0 ? (
        <div className="grid gap-2 rounded-md border border-emerald-400/25 bg-emerald-400/[0.06] p-3">
          <TradeMetric label={breakevenOnly ? "Break even" : "Partial"} value={partialDone ? "done" : "armed"} />
          <TradeMetric label="Trigger" value={`${formatUnknownNumber(partialPlan.trigger_r)}R @ ${price(readNumber(partialPlan.trigger_price))}`} />
          {!breakevenOnly ? <TradeMetric label="Partial close" value={partialDone ? `${formatUnknownNumber(partialPlan.closed_volume)} lot` : "--"} /> : null}
          <TradeMetric
            label="BE SL"
            value={breakevenApplied ? price(readNumber(partialPlan.breakeven_stop)) : partialDone ? "pending" : price(readNumber(partialPlan.breakeven_stop))}
          />
        </div>
      ) : null}

      {trade.playbook === "zone_reaction_v2" && trade.source === "live" && trade.account_label && ["filled", "pending_fill"].includes(trade.status) ? (
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

function TradeManagementActions({
  action,
  breakevenDone,
  busy,
  disabled,
  partialDone,
  onCancel,
  onConfirm,
  onSelect,
}: {
  action: TradeManagementAction | null;
  breakevenDone: boolean;
  busy: boolean;
  disabled: boolean;
  partialDone: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  onSelect: (action: TradeManagementAction) => void;
}) {
  const confirmation = action ? tradeActionConfirmation(action) : null;
  return (
    <div className="grid gap-2 rounded-md border border-amber-300/25 bg-amber-300/[0.04] p-3">
      <div>
        <div className="text-xs font-semibold text-amber-100">Manage live position</div>
        <div className="mt-0.5 text-[10px] text-slate-500">
          {disabled
            ? "Discipline lock is active. The position will follow its planned SL/TP and automated management."
            : "Actions are sent to the worker for this trade only."}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <button
          className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border border-amber-300/35 bg-amber-300/[0.08] px-2 text-xs font-semibold text-amber-100 hover:bg-amber-300/15 disabled:cursor-not-allowed disabled:opacity-35"
          disabled={disabled || busy || partialDone}
          title={disabled ? "Disabled by discipline lock" : partialDone ? "Partial profit has already been taken" : "Close 50% and move the remaining stop to entry"}
          type="button"
          onClick={() => onSelect("partial_50_be")}
        >
          <Percent size={14} /> Partial 50% + BE
        </button>
        <button
          className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border border-cyan-300/35 bg-cyan-300/[0.08] px-2 text-xs font-semibold text-cyan-100 hover:bg-cyan-300/15 disabled:cursor-not-allowed disabled:opacity-35"
          disabled={disabled || busy || breakevenDone}
          title={disabled ? "Disabled by discipline lock" : breakevenDone ? "Stop loss is already at entry or better" : "Move stop loss to the broker entry price"}
          type="button"
          onClick={() => onSelect("break_even")}
        >
          <ShieldCheck size={14} /> Break even
        </button>
        <button
          className="col-span-2 inline-flex h-9 items-center justify-center gap-1.5 rounded-md border border-rose-400/45 bg-rose-500/[0.08] px-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/15 disabled:cursor-not-allowed disabled:opacity-35"
          disabled={disabled || busy}
          title={disabled ? "Disabled by discipline lock" : "Close the remaining broker position at market"}
          type="button"
          onClick={() => onSelect("close_now")}
        >
          <XCircle size={14} /> Close now
        </button>
      </div>
      {!disabled && confirmation ? (
        <div className={`grid gap-2 rounded-md border p-2.5 text-xs ${action === "close_now" ? "border-rose-400/35 bg-rose-500/[0.08]" : "border-amber-300/30 bg-ink-950/70"}`}>
          <div className="font-semibold text-slate-100">{confirmation.title}</div>
          <p className="leading-relaxed text-slate-400">{confirmation.description}</p>
          <div className="grid grid-cols-2 gap-2">
            <button className="h-8 rounded-md border border-ink-600 text-slate-300 hover:border-slate-500" disabled={busy} type="button" onClick={onCancel}>Cancel</button>
            <button className={`h-8 rounded-md border font-semibold ${action === "close_now" ? "border-rose-400/50 bg-rose-500/15 text-rose-100" : "border-cyan-400/45 bg-cyan-400/10 text-cyan-100"}`} disabled={busy} type="button" onClick={onConfirm}>
              {busy ? "Processing…" : "Confirm action"}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function tradeActionConfirmation(action: TradeManagementAction): { title: string; description: string } {
  if (action === "close_now") {
    return { title: "Close this position now?", description: "The worker will close the full remaining broker position at market. Slippage may occur." };
  }
  if (action === "partial_50_be") {
    return { title: "Take partial profit now?", description: "The worker will close 50% of the current position volume, then move the remaining stop loss to the broker entry price." };
  }
  return { title: "Move stop loss to break even?", description: "The worker will preserve the current take profit and move the stop loss to the broker entry price. A better existing stop will not be degraded." };
}

function tradeActionSuccessMessage(action: TradeManagementAction): string {
  if (action === "close_now") return "Position close executed by the account worker.";
  if (action === "partial_50_be") return "Closed 50% and moved the remaining position to break even.";
  return "Stop loss moved to break even.";
}

function isStopAtBreakEven(side: string, stopLoss: number | null, entry: number | null): boolean {
  if (stopLoss === null || entry === null || stopLoss <= 0) return false;
  return side === "buy" ? stopLoss >= entry - 1e-9 : stopLoss <= entry + 1e-9;
}

function applyTradeManagementPatch(trade: TradeOrder, command: TradeManagementCommand): TradeOrder {
  const patch = readObject(readObject(command.result).trade_patch);
  const patchedMetadata = readObject(patch.metadata);
  return {
    ...trade,
    status: readString(patch.status) ?? trade.status,
    stop_loss: "stop_loss" in patch ? readNumber(patch.stop_loss) : trade.stop_loss,
    closed_at: "closed_at" in patch ? readNullableString(patch.closed_at) : trade.closed_at,
    close_price: "close_price" in patch ? readNumber(patch.close_price) : trade.close_price,
    pnl: "pnl" in patch ? readNumber(patch.pnl) : trade.pnl,
    pnl_r: "pnl_r" in patch ? readNumber(patch.pnl_r) : trade.pnl_r,
    metadata: Object.keys(patchedMetadata).length > 0 ? patchedMetadata : trade.metadata,
  };
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
  const [triggerDraft, setTriggerDraft] = useState("1");
  const [fractionDraft, setFractionDraft] = useState("0.4");
  const settings = settingsQuery.data;

  useEffect(() => {
    if (settings) {
      setTriggerDraft(settings.trigger_r.toString());
      setFractionDraft(settings.fraction.toString());
    }
  }, [settings]);

  const mutation = useMutation({
    mutationFn: (next: AccountPartialTakeProfitSettings) => updateAccountPartialTakeProfit(accountLabel, next),
    onSuccess: (saved) => {
      queryClient.setQueryData(["account-partial-take-profit", accountLabel], saved);
      void queryClient.invalidateQueries({ queryKey: ["accounts"] });
      showToast("success", `Partial TP ${saved.enabled ? `ON: ${Math.round(saved.fraction * 100)}% at ${saved.trigger_r}R + BE` : "OFF"} for ${accountLabel}.`);
    },
    onError: (error) => {
      showToast("error", error instanceof Error ? error.message : "Could not update Partial TP settings.");
    },
  });

  const parsedTrigger = Number(triggerDraft);
  const parsedFraction = Number(fractionDraft);
  const validTrigger = Number.isFinite(parsedTrigger) && parsedTrigger >= 0.5 && parsedTrigger <= 2;
  const validFraction = Number.isFinite(parsedFraction) && parsedFraction >= 0.25 && parsedFraction <= 0.5;
  const save = (enabled: boolean) => {
    if (!validTrigger) {
      showToast("error", "Partial TP trigger must be between 0.5R and 2.0R.");
      return;
    }
    if (!validFraction) {
      showToast("error", "Partial TP fraction must be between 25% and 50%.");
      return;
    }
    mutation.mutate({ enabled, trigger_r: parsedTrigger, fraction: parsedFraction });
  };

  return (
    <div className="grid gap-3 rounded-md border border-cyan-400/25 bg-cyan-400/[0.05] p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-xs font-semibold text-cyan-100">Zone Reaction V2 · Partial TP</div>
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

      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] gap-2">
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
        <label className="grid gap-1 text-[11px] text-slate-500">
          Close fraction
          <select
            value={fractionDraft}
            onChange={(event) => setFractionDraft(event.target.value)}
            className="h-9 min-w-0 rounded-md border border-ink-700 bg-ink-950 px-2 text-sm font-semibold text-slate-100 outline-none focus:border-cyan-400"
          >
            {[0.25, 0.33, 0.4, 0.5].map((value) => (
              <option key={value} value={value}>{Math.round(value * 100)}%</option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={!settings || !validTrigger || !validFraction || mutation.isPending}
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

function TradeIdDetail({
  tradeId,
  copied,
  onCopy,
}: {
  tradeId: string;
  copied: boolean;
  onCopy: () => void;
}) {
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] items-center gap-3">
      <span className="text-slate-500">Trade ID</span>
      <div className="flex min-w-0 items-center gap-1.5">
        <strong className="min-w-0 flex-1 truncate font-mono text-xs text-slate-100" title={tradeId}>
          {tradeId}
        </strong>
        <button
          aria-label="Copy trade ID"
          className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded border transition ${
            copied
              ? "border-emerald-400/50 bg-emerald-400/10 text-emerald-300"
              : "border-ink-700 bg-ink-850 text-slate-400 hover:border-cyan-400/60 hover:text-cyan-200"
          }`}
          title={copied ? "Copied" : "Copy trade ID"}
          type="button"
          onClick={onCopy}
        >
          {copied ? <Check size={13} /> : <Copy size={13} />}
        </button>
      </div>
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

function readNullableString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
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
