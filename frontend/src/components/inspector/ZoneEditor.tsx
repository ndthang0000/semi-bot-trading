import { Check, Copy, RotateCcw, Save, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { confirmDraftZone, deleteManualZone, updateZoneOverride } from "../../api/chart";
import { copyTextToClipboard } from "../../lib/clipboard";
import { compactTime, price } from "../../lib/time";
import { useChartStore } from "../../store/chartStore";
import type { PriceZone, ZoneEmotionState, ZoneThesisReason, ZoneTradeMode } from "../../types";

type ToastKind = "success" | "error";
type TrendAnswer = "" | "bullish" | "bearish" | "neutral";
type SwingLocation = "" | "inside_zone" | "near_zone" | "none";

export function ZoneEditor({
  zone,
  onZoneUpdated,
  showToast,
}: {
  zone: PriceZone;
  onZoneUpdated: () => void;
  showToast: (kind: ToastKind, text: string) => void;
}) {
  const setSelected = useChartStore((state) => state.setSelected);
  const [priceLow, setPriceLow] = useState(String(zone.price_low));
  const [priceHigh, setPriceHigh] = useState(String(zone.price_high));
  const [weight, setWeight] = useState(String(zone.weight));
  const [confidence, setConfidence] = useState(String(zone.confidence));
  const [status, setStatus] = useState<"active" | "draft" | "disabled">(editableZoneStatus(zone));
  const [tradeModes, setTradeModes] = useState<ZoneTradeMode[]>(defaultTradeModes(zone));
  const [reason, setReason] = useState("");
  const [shortTermTrend, setShortTermTrend] = useState<TrendAnswer>("");
  const [mediumTermTrend, setMediumTermTrend] = useState<TrendAnswer>("");
  const [swingLocation, setSwingLocation] = useState<SwingLocation>("");
  const [thesisReasons, setThesisReasons] = useState<ZoneThesisReason[]>([]);
  const [emotionState, setEmotionState] = useState<"" | ZoneEmotionState>("");
  const [activationComment, setActivationComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [copiedZoneId, setCopiedZoneId] = useState<string | null>(null);
  const isDraftSr = status === "draft" && (zone.type === "support" || zone.type === "resistance");
  const draftEndReady = useMemo(() => {
    if (!zone.visual_end) return false;
    const endTime = Date.parse(zone.visual_end);
    return Number.isFinite(endTime) && endTime > Date.now();
  }, [zone.visual_end]);
  const zoneSize = useMemo(() => {
    const low = Number(priceLow);
    const high = Number(priceHigh);
    return Number.isFinite(low) && Number.isFinite(high) && high >= low ? high - low : null;
  }, [priceHigh, priceLow]);
  const isDirty = useMemo(() => {
    const low = Number(priceLow);
    const high = Number(priceHigh);
    const parsedWeight = Number(weight);
    const parsedConfidence = Number(confidence);
    return (
      low !== zone.price_low ||
      high !== zone.price_high ||
      parsedWeight !== zone.weight ||
      parsedConfidence !== zone.confidence ||
      status !== editableZoneStatus(zone) ||
      !sameTradeModes(tradeModes, defaultTradeModes(zone)) ||
      reason.trim().length > 0
    );
  }, [confidence, priceHigh, priceLow, reason, status, tradeModes, weight, zone]);

  useEffect(() => {
    reset();
  }, [zone]);

  const reset = () => {
    setPriceLow(String(zone.price_low));
    setPriceHigh(String(zone.price_high));
    setWeight(String(zone.weight));
    setConfidence(String(zone.confidence));
    setStatus(editableZoneStatus(zone));
    setTradeModes(defaultTradeModes(zone));
    setReason("");
    setShortTermTrend("");
    setMediumTermTrend("");
    setSwingLocation("");
    setThesisReasons([]);
    setEmotionState("");
    setActivationComment("");
    setError(null);
  };

  const activationProgress = useMemo(() => {
    return [
      shortTermTrend !== "",
      mediumTermTrend !== "",
      swingLocation !== "",
      thesisReasons.length >= 1 && thesisReasons.length <= 3,
      emotionState !== "",
    ].filter(Boolean).length;
  }, [emotionState, mediumTermTrend, shortTermTrend, swingLocation, thesisReasons]);

  const confirmZone = useCallback(async () => {
    if (!isDraftSr || !draftEndReady || activationProgress !== 5 || isDirty) return;
    setIsSaving(true);
    setError(null);
    try {
      const updated = await confirmDraftZone(zone.id, {
        short_term_trend: shortTermTrend as Exclude<TrendAnswer, "">,
        medium_term_trend: mediumTermTrend as Exclude<TrendAnswer, "">,
        swing_location: swingLocation as Exclude<SwingLocation, "">,
        thesis_reasons: thesisReasons,
        emotion_state: emotionState as ZoneEmotionState,
        comment: activationComment.trim(),
      });
      setSelected({ kind: "zone", entity: updated });
      onZoneUpdated();
      showToast("success", "Zone is active. The bot may now evaluate it.");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not activate draft zone.";
      setError(message);
      showToast("error", message);
    } finally {
      setIsSaving(false);
    }
  }, [
    activationComment,
    activationProgress,
    emotionState,
    draftEndReady,
    isDirty,
    isDraftSr,
    mediumTermTrend,
    onZoneUpdated,
    setSelected,
    shortTermTrend,
    showToast,
    swingLocation,
    thesisReasons,
    zone.id,
  ]);

  const save = useCallback(async () => {
    const low = Number(priceLow);
    const high = Number(priceHigh);
    const parsedWeight = Number(weight);
    const parsedConfidence = Number(confidence);
    if (!Number.isFinite(low) || !Number.isFinite(high) || low >= high) {
      setError("Price low must be lower than price high.");
      return;
    }
    if (!Number.isFinite(parsedWeight) || parsedWeight < 0 || parsedWeight > 1) {
      setError("Weight must be between 0 and 1.");
      return;
    }
    if (!Number.isFinite(parsedConfidence) || parsedConfidence < 0 || parsedConfidence > 1) {
      setError("Confidence must be between 0 and 1.");
      return;
    }
    if (!isDirty) {
      showToast("success", "Zone is already up to date.");
      return;
    }

    setIsSaving(true);
    setError(null);
    try {
      const updated = await updateZoneOverride(zone.id, {
        price_low: low,
        price_high: high,
        visual_start: zone.visual_start,
        visual_end: zone.visual_end,
        expires_at: zone.visual_end,
        weight: parsedWeight,
        confidence: parsedConfidence,
        status,
        reason: reason.trim() || undefined,
        trade_modes: tradeModes,
      });
      setSelected({ kind: "zone", entity: updated });
      onZoneUpdated();
      showToast("success", "Zone override saved.");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not save zone override.";
      setError(message);
      showToast("error", message);
    } finally {
      setIsSaving(false);
    }
  }, [confidence, isDirty, onZoneUpdated, priceHigh, priceLow, reason, setSelected, showToast, status, tradeModes, weight, zone]);

  const deleteZone = useCallback(async () => {
    if (isSaving) return;
    const confirmed = window.confirm(`Delete ${zoneDisplayName(zone)} zone from chart? This will hide it from chart payload.`);
    if (!confirmed) return;
    setIsSaving(true);
    setError(null);
    try {
      await deleteManualZone(zone.id, reason.trim() || "hotkey/manual delete");
      setSelected(null);
      onZoneUpdated();
      showToast("success", "Zone deleted from chart.");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not delete zone.";
      setError(message);
      showToast("error", message);
    } finally {
      setIsSaving(false);
    }
  }, [isSaving, onZoneUpdated, reason, setSelected, showToast, zone]);

  const copyZoneId = useCallback(async () => {
    try {
      await copyTextToClipboard(zone.id);
      setCopiedZoneId(zone.id);
      showToast("success", "Zone ID copied.");
      window.setTimeout(() => {
        setCopiedZoneId((current) => (current === zone.id ? null : current));
      }, 1500);
    } catch {
      showToast("error", "Could not copy zone ID.");
    }
  }, [showToast, zone.id]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (isEditableTarget(event.target)) return;
      const key = event.key.toLowerCase();
      if (key === "s") {
        event.preventDefault();
        void save();
      } else if (key === "d" || key === "delete" || key === "backspace") {
        event.preventDefault();
        void deleteZone();
      } else if (key === "escape") {
        event.preventDefault();
        setSelected(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [deleteZone, save, setSelected]);

  return (
    <div className="grid gap-3 text-sm">
      <div className="grid gap-2">
        <ZoneIdDetail copied={copiedZoneId === zone.id} zoneId={zone.id} onCopy={copyZoneId} />
        <Detail label="Type" value={`${zone.timeframe} ${zoneDisplayName(zone)}`} />
        <Detail label="Source" value={zone.source} />
        <Detail label="Start" value={compactTime(zone.visual_start)} />
        <Detail label="End" value={compactTime(zone.visual_end)} />
        <Detail label="Expires" value={compactTime(zone.valid_until)} />
        <Detail label="Touches" value={String(zone.metadata.touch_count_total ?? zone.metadata.touch_count ?? "--")} />
        <Detail label="Size" value={zoneSize === null ? "--" : price(zoneSize)} />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <NumberField label="Low" value={priceLow} onChange={setPriceLow} step="0.01" />
        <NumberField label="High" value={priceHigh} onChange={setPriceHigh} step="0.01" />
        <NumberField label="Weight" value={weight} onChange={setWeight} step="0.01" min="0" max="1" />
        <NumberField label="Confidence" value={confidence} onChange={setConfidence} step="0.01" min="0" max="1" />
      </div>

      {isDraftSr ? (
        <div className="flex items-center justify-between rounded-md border border-amber-400/40 bg-amber-400/10 px-3 py-2">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.16em] text-amber-200">Draft zone</div>
            <div className="mt-1 text-xs text-amber-100/70">Bot trading is locked until confirmation.</div>
          </div>
          <span className="rounded border border-amber-300/40 px-2 py-1 text-xs font-semibold text-amber-100">DRAFT</span>
        </div>
      ) : (
        <label className="grid gap-1 text-xs text-slate-500">
          Status
          <select
            className="h-9 rounded-md border border-ink-700 bg-ink-850 px-2 text-sm text-slate-100 outline-none"
            value={status}
            onChange={(event) => setStatus(event.target.value === "disabled" ? "disabled" : "active")}
          >
            <option value="active">active</option>
            <option value="disabled">disabled</option>
          </select>
        </label>
      )}

      <div className="grid gap-2 rounded-md border border-ink-700 bg-ink-950/50 p-3">
        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Trade modes</div>
        <div className="grid grid-cols-3 gap-2">
          {TRADE_MODE_OPTIONS.map((option) => (
            <label key={option.value} className="inline-flex items-center gap-2 rounded border border-ink-700 bg-ink-850 px-2 py-1.5 text-xs text-slate-200">
              <input
                checked={tradeModes.includes(option.value)}
                className="accent-cyan-400"
                type="checkbox"
                onChange={(event) => {
                  setTradeModes((current) =>
                    event.target.checked ? Array.from(new Set([...current, option.value])) : current.filter((mode) => mode !== option.value),
                  );
                }}
              />
              {option.label}
            </label>
          ))}
        </div>
      </div>

      {isDraftSr ? (
        <div className="grid gap-4 rounded-lg border border-amber-400/30 bg-ink-950/70 p-3">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.16em] text-amber-200">Activation review</div>
              <div className="mt-1 text-xs text-slate-500">Answer every section before this SR zone can trade.</div>
            </div>
            <span className="shrink-0 text-xs font-semibold text-amber-100">{activationProgress}/5</span>
          </div>

          <ReviewSelect
            label="Trend ngắn hạn (48h)"
            value={shortTermTrend}
            options={TREND_OPTIONS}
            onChange={(value) => setShortTermTrend(value as TrendAnswer)}
          />
          <ReviewSelect
            label="Trend trung hạn (1–2 tuần)"
            value={mediumTermTrend}
            options={TREND_OPTIONS}
            onChange={(value) => setMediumTermTrend(value as TrendAnswer)}
          />
          <ReviewSelect
            label={zone.type === "support" ? "Swing Low tại vùng Support" : "Swing High tại vùng Resistance"}
            value={swingLocation}
            options={SWING_OPTIONS}
            onChange={(value) => setSwingLocation(value as SwingLocation)}
          />

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-slate-400">Thesis — chọn 1 đến 3 lý do</span>
              <span className="text-xs text-slate-500">{thesisReasons.length}/3</span>
            </div>
            {thesisGroups(zone).map((group) => (
              <div key={group.label} className="grid gap-1.5">
                <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-600">{group.label}</div>
                {group.options.map((option) => {
                  const checked = thesisReasons.includes(option.value);
                  const disabled = !checked && thesisReasons.length >= 3;
                  return (
                    <label
                      key={option.value}
                      className={`flex items-start gap-2 rounded border px-2.5 py-2 text-xs ${
                        checked
                          ? "border-cyan-400/50 bg-cyan-400/10 text-cyan-100"
                          : "border-ink-700 bg-ink-850 text-slate-300"
                      } ${disabled ? "cursor-not-allowed opacity-45" : "cursor-pointer"}`}
                    >
                      <input
                        checked={checked}
                        className="mt-0.5 accent-cyan-400"
                        disabled={disabled}
                        type="checkbox"
                        onChange={(event) => {
                          setThesisReasons((current) =>
                            event.target.checked
                              ? [...current, option.value].slice(0, 3)
                              : current.filter((reasonValue) => reasonValue !== option.value),
                          );
                        }}
                      />
                      <span>{option.label}</span>
                    </label>
                  );
                })}
              </div>
            ))}
          </div>

          <ReviewSelect
            label="Trạng thái cảm xúc hiện tại"
            value={emotionState}
            options={EMOTION_OPTIONS}
            onChange={(value) => setEmotionState(value as "" | ZoneEmotionState)}
          />
          <label className="grid gap-1 text-xs text-slate-500">
            Comment (optional)
            <textarea
              className="min-h-20 resize-y rounded-md border border-ink-700 bg-ink-850 px-2 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400/60"
              maxLength={2000}
              value={activationComment}
              onChange={(event) => setActivationComment(event.target.value)}
            />
          </label>

          {isDirty ? (
            <div className="rounded border border-amber-400/30 bg-amber-400/10 px-2.5 py-2 text-xs text-amber-100">
              Save geometry, trade modes, or other edits before confirming this zone.
            </div>
          ) : null}
          {!draftEndReady ? (
            <div className="rounded border border-rose-400/30 bg-rose-400/10 px-2.5 py-2 text-xs text-rose-100">
              Extend the zone right edge into the future before confirming.
            </div>
          ) : null}
          <button
            className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-emerald-400/60 bg-emerald-400/15 text-sm font-semibold text-emerald-100 hover:bg-emerald-400/25 disabled:cursor-not-allowed disabled:opacity-40"
            type="button"
            disabled={isSaving || isDirty || !draftEndReady || activationProgress !== 5}
            onClick={confirmZone}
          >
            <Check size={15} />
            {isSaving ? "Confirming" : "Confirm Active"}
          </button>
        </div>
      ) : null}

      <label className="grid gap-1 text-xs text-slate-500">
        Reason
        <textarea
          className="min-h-16 resize-none rounded-md border border-ink-700 bg-ink-850 px-2 py-2 text-sm text-slate-100 outline-none"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>

      {error ? <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-2 text-xs text-rose-100">{error}</div> : null}

      <div className="grid grid-cols-3 gap-2">
        <button
          className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-ink-700 bg-ink-800 text-sm text-slate-100 hover:border-slate-500"
          type="button"
          onClick={reset}
        >
          <RotateCcw size={14} />
          Reset
        </button>
        <button
          className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-cyan-400/60 bg-cyan-400/15 text-sm font-semibold text-cyan-100 hover:bg-cyan-400/25 disabled:cursor-not-allowed disabled:opacity-50"
          type="button"
          disabled={isSaving || !isDirty}
          onClick={save}
        >
          <Save size={14} />
          {isSaving ? "Saving" : "Save"}
        </button>
        <button
          className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-rose-400/50 bg-rose-500/10 text-sm font-semibold text-rose-100 hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50"
          type="button"
          disabled={isSaving}
          title="Delete zone (D)"
          onClick={deleteZone}
        >
          <Trash2 size={14} />
          Delete
        </button>
      </div>
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
  step,
  min,
  max,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  step: string;
  min?: string;
  max?: string;
}) {
  return (
    <label className="grid gap-1 text-xs text-slate-500">
      {label}
      <input
        className="h-9 min-w-0 rounded-md border border-ink-700 bg-ink-850 px-2 text-sm text-slate-100 outline-none"
        max={max}
        min={min}
        step={step}
        type="number"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function ReviewSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid gap-1 text-xs text-slate-500">
      {label}
      <select
        className="h-9 rounded-md border border-ink-700 bg-ink-850 px-2 text-sm text-slate-100 outline-none focus:border-cyan-400/60"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">-- Chọn --</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </label>
  );
}

const TREND_OPTIONS = [
  { value: "bullish", label: "Bullish" },
  { value: "bearish", label: "Bearish" },
  { value: "neutral", label: "Neutral" },
];

const SWING_OPTIONS = [
  { value: "inside_zone", label: "Swing nằm trong zone" },
  { value: "near_zone", label: "Swing nằm gần zone" },
  { value: "none", label: "Không có Swing phù hợp" },
];

const EMOTION_OPTIONS = [
  { value: "calm", label: "Bình tĩnh" },
  { value: "fomo", label: "FOMO" },
  { value: "revenge", label: "Revenge" },
  { value: "proving_right", label: "Muốn chứng minh mình đúng" },
  { value: "fear_missing_price", label: "Sợ bỏ lỡ mức giá đẹp" },
  { value: "uncertain", label: "Không chắc chắn" },
];

function thesisGroups(zone: PriceZone): Array<{ label: string; options: Array<{ value: ZoneThesisReason; label: string }> }> {
  const isSupport = zone.type === "support";
  return [
    {
      label: "Value entry ngoài swing",
      options: [
        {
          value: "value_entry_outside_swing",
          label: isSupport
            ? "Dưới Swing Low để chờ mua ở mức giá tốt hơn."
            : "Trên Swing High để chờ bán ở mức giá tốt hơn.",
        },
      ],
    },
    {
      label: "Follow trend",
      options: [
        { value: "follow_short_term_trend", label: "Pullback về Swing để follow trend ngắn hạn." },
        { value: "follow_medium_term_trend", label: "Pullback về Swing để follow trend trung hạn." },
        { value: "breakout_retest", label: "Retest cấu trúc vừa breakout để follow trend." },
        {
          value: "structure_flip",
          label: isSupport
            ? "Structure flip: resistance cũ trở thành support."
            : "Structure flip: support cũ trở thành resistance.",
        },
      ],
    },
    {
      label: "Range",
      options: [
        {
          value: "range_boundary",
          label: isSupport ? "Biên dưới của vùng sideway/range." : "Biên trên của vùng sideway/range.",
        },
        { value: "repeated_reactions", label: "Giá đã nhiều lần phản ứng tại vùng này." },
        { value: "long_accumulation", label: "Vùng tích lũy lâu trước một chuyển động mạnh." },
      ],
    },
  ];
}

const TRADE_MODE_OPTIONS: Array<{ value: ZoneTradeMode; label: string }> = [
  { value: "reject", label: "Reject" },
  { value: "internal_reject", label: "Internal" },
  { value: "breakout", label: "Breakout" },
];

function defaultTradeModes(zone: PriceZone): ZoneTradeMode[] {
  const raw = zone.metadata.trade_modes;
  if (Array.isArray(raw)) {
    return raw.filter((mode): mode is ZoneTradeMode => mode === "reject" || mode === "internal_reject" || mode === "breakout");
  }
  if (zone.type === "fvg") return ["reject", "internal_reject"];
  if (zone.type === "consolidation") return ["breakout"];
  if (zone.type === "support" || zone.type === "resistance") return ["reject"];
  return [];
}

function sameTradeModes(first: ZoneTradeMode[], second: ZoneTradeMode[]): boolean {
  if (first.length !== second.length) return false;
  const normalized = new Set(first);
  return second.every((mode) => normalized.has(mode));
}

function editableZoneStatus(zone: PriceZone): "active" | "draft" | "disabled" {
  if (zone.status === "draft") return "draft";
  return zone.status === "disabled" ? "disabled" : "active";
}

function zoneDisplayName(zone: PriceZone): string {
  const kind = zone.metadata.add_entity_kind;
  if (kind === "demand_order_block") return "Demand OB";
  if (kind === "supply_order_block") return "Supply OB";
  if (kind === "bullish_fvg") return "Bullish FVG";
  if (kind === "bearish_fvg") return "Bearish FVG";
  if (kind === "buy_side_liquidity") return "Buy-side Liquidity";
  if (kind === "sell_side_liquidity") return "Sell-side Liquidity";
  if (zone.type === "order_block") return zone.direction === "bullish" ? "Demand OB" : "Supply OB";
  if (zone.type === "fvg") return zone.direction === "bullish" ? "Bullish FVG" : "Bearish FVG";
  if (zone.type === "liquidity_pool") return "Liquidity Pool";
  return zone.type;
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] gap-3">
      <span className="text-slate-500">{label}</span>
      <strong className="min-w-0 break-words text-slate-100">{value}</strong>
    </div>
  );
}

function ZoneIdDetail({
  zoneId,
  copied,
  onCopy,
}: {
  zoneId: string;
  copied: boolean;
  onCopy: () => void;
}) {
  return (
    <div className="grid grid-cols-[96px_minmax(0,1fr)] items-center gap-3">
      <span className="text-slate-500">ID</span>
      <div className="flex min-w-0 items-center gap-1.5">
        <strong className="min-w-0 flex-1 truncate text-slate-100" title={zoneId}>{zoneId}</strong>
        <button
          aria-label="Copy zone ID"
          className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded border transition ${
            copied
              ? "border-emerald-400/50 bg-emerald-400/10 text-emerald-300"
              : "border-ink-700 bg-ink-850 text-slate-400 hover:border-cyan-400/60 hover:text-cyan-200"
          }`}
          title={copied ? "Copied" : "Copy zone ID"}
          type="button"
          onClick={onCopy}
        >
          {copied ? <Check size={13} /> : <Copy size={13} />}
        </button>
      </div>
    </div>
  );
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tagName = target.tagName.toLowerCase();
  return tagName === "input" || tagName === "textarea" || tagName === "select" || target.isContentEditable;
}
