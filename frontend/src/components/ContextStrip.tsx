import { Pencil, RotateCcw, Save, X } from "lucide-react";
import { useEffect, useState } from "react";
import { updateMarketContextOverride } from "../api/chart";
import { compactTime } from "../lib/time";
import type { ChartPayload, MarketContext } from "../types";

type ContextType = "bias" | "regime";

type ContextStripProps = {
  payload: ChartPayload | undefined;
  onContextUpdated: () => void;
};

const BIAS_VALUES = ["bullish", "bearish", "neutral"];
const REGIME_VALUES = ["trending", "ranging", "news", "risk_off"];
const REGIME_OVERLAYS = ["expansion", "contraction", "high_volatility", "low_volatility"];
const EXPIRY_PRESETS = [
  { label: "1h", hours: 1 },
  { label: "2h", hours: 2 },
  { label: "3h", hours: 3 },
  { label: "4h", hours: 4 },
  { label: "6h", hours: 6 },
  { label: "10h", hours: 10 },
  { label: "15h", hours: 15 },
  { label: "20h", hours: 20 },
  { label: "1day", hours: 24 },
  { label: "2day", hours: 48 },
  { label: "3day", hours: 72 },
  { label: "4day", hours: 96 },
  { label: "5day", hours: 120 },
  { label: "6day", hours: 144 },
  { label: "1week", hours: 168 },
];

export function ContextStrip({ payload, onContextUpdated }: ContextStripProps) {
  const [editing, setEditing] = useState<ContextType | null>(null);
  const h1 = payload?.layers.contexts.H1;
  const biasContext = h1?.bias;
  const regimeContext = h1?.regime;
  const macroContext = h1?.macro_trend;
  const bias = biasContext?.effective_value ?? "--";
  const regime = regimeContext?.effective_value ?? "--";
  const overlays = readOverlays(regimeContext?.metadata.overlays);
  const priceChange = readCurrentPriceChange(payload);

  return (
    <section className="grid grid-cols-[210px_220px_170px_150px_150px_minmax(0,1fr)] gap-3 border-b border-ink-700 bg-ink-950 px-4 py-3">
      <BiasCard bias={bias} context={biasContext} priceChange={priceChange} onEdit={() => setEditing("bias")} />
      <ContextCard
        label="H1 Regime"
        value={overlays.length ? `${regime} + ${overlays.join(" + ")}` : regime}
        context={regimeContext}
        onEdit={() => setEditing("regime")}
      />
      <MacroTrendCard context={macroContext} />
      <AtrCard atr={payload?.layers.atr} />
      <RsiCard rsi={payload?.layers.rsi} />
      <ContextCard label="Range" value={payload ? `${compactTime(payload.range.start)} -> ${compactTime(payload.range.end)}` : "--"} />

      {editing && h1?.[editing] ? (
        <ContextOverrideEditor
          context={h1[editing]}
          contextType={editing}
          onCancel={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            onContextUpdated();
          }}
        />
      ) : null}
    </section>
  );
}

function AtrCard({ atr }: { atr: ChartPayload["layers"]["atr"] | undefined }) {
  const h1 = atr?.H1;
  const m15 = atr?.M15;
  const period = h1?.period ?? m15?.period ?? 14;

  return (
    <div className="min-h-14 rounded-md border border-ink-700 bg-ink-900 px-3 py-2" title={`Average True Range (${period})`}>
      <div className="text-xs text-slate-500">ATR({period})</div>
      <div className="mt-1 grid grid-cols-2 gap-2 text-[11px] leading-tight">
        <div>
          <div className="text-slate-500">H1</div>
          <div className="font-semibold text-slate-100">{formatAtrValue(h1?.value)}</div>
        </div>
        <div>
          <div className="text-slate-500">M15</div>
          <div className="font-semibold text-slate-100">{formatAtrValue(m15?.value)}</div>
        </div>
      </div>
    </div>
  );
}

function RsiCard({ rsi }: { rsi: ChartPayload["layers"]["rsi"] | undefined }) {
  const h1 = rsi?.H1;
  const period = h1?.period ?? 14;

  return (
    <div className="min-h-14 rounded-md border border-ink-700 bg-ink-900 px-3 py-2" title={`Relative Strength Index (${period}) and H1 RSI slope`}>
      <div className="text-xs text-slate-500">RSI({period})</div>
      <div className="mt-1 grid grid-cols-3 gap-2 text-[11px] leading-tight">
        <div>
          <div className="text-slate-500">H1</div>
          <div className="font-semibold text-slate-100">{formatRsiValue(h1?.value)}</div>
        </div>
        <div>
          <div className="text-slate-500">S3</div>
          <div className={`font-semibold ${slopeToneClass(h1?.slope_3)}`}>{formatRsiSlope(h1?.slope_3)}</div>
        </div>
        <div>
          <div className="text-slate-500">S5</div>
          <div className={`font-semibold ${slopeToneClass(h1?.slope_5)}`}>{formatRsiSlope(h1?.slope_5)}</div>
        </div>
      </div>
    </div>
  );
}

function BiasCard({
  bias,
  context,
  priceChange,
  onEdit,
}: {
  bias: string;
  context: MarketContext | undefined;
  priceChange: { currentPrice: number; changePercent: number } | null;
  onEdit: () => void;
}) {
  const tone = bias === "bearish" ? "bearish" : bias === "bullish" ? "bullish" : "neutral";
  const toneClass = tone === "bullish" ? "text-emerald-300" : tone === "bearish" ? "text-rose-300" : "text-slate-100";
  const changeToneClass =
    priceChange && priceChange.changePercent >= 0 ? "text-emerald-300" : priceChange ? "text-rose-300" : "text-slate-500";
  const changePrefix = priceChange && priceChange.changePercent > 0 ? "+" : "";

  return (
    <div className="min-h-14 rounded-md border border-ink-700 bg-ink-900 px-3 py-2">
      <div className="flex items-center justify-between gap-2 text-xs text-slate-500">
        <span>H1 Bias</span>
        <ContextSourceBadge context={context} />
      </div>
      <div className="mt-1 flex items-end justify-between gap-3">
        <div className={`text-sm font-semibold leading-tight ${toneClass}`}>{bias}</div>
        <div className="flex items-end gap-2">
          <div className="text-right">
            <div className="text-sm font-semibold leading-tight text-slate-100">
              {priceChange ? priceChange.currentPrice.toFixed(2) : "--"}
            </div>
            <div className={`text-[11px] font-semibold leading-tight ${changeToneClass}`}>
              {priceChange ? `${changePrefix}${priceChange.changePercent.toFixed(2)}%` : "--"}
            </div>
          </div>
          <IconButton title="Edit H1 Bias" onClick={onEdit}>
            <Pencil size={13} />
          </IconButton>
        </div>
      </div>
    </div>
  );
}

function MacroTrendCard({ context }: { context: MarketContext | undefined }) {
  const value = context?.effective_value ?? "--";
  const toneClass =
    value === "up" ? "text-emerald-300" : value === "down" ? "text-rose-300" : "text-slate-100";
  const momentumAtr = typeof context?.metadata.momentum_atr === "number" ? (context.metadata.momentum_atr as number) : null;
  const lookback = typeof context?.metadata.lookback_candles === "number" ? (context.metadata.lookback_candles as number) : null;
  const lookbackDays = lookback ? Math.round(lookback / 24) : null;
  const momentumLabel =
    momentumAtr !== null ? `${momentumAtr > 0 ? "+" : ""}${momentumAtr.toFixed(1)} ATR${lookbackDays ? ` / ${lookbackDays}d` : ""}` : null;

  return (
    <div className="min-h-14 rounded-md border border-ink-700 bg-ink-900 px-3 py-2" title="Slow H1 momentum gate: up blocks shorts, down blocks longs">
      <div className="flex items-center justify-between gap-2 text-xs text-slate-500">
        <span>Macro Trend{lookbackDays ? ` (${lookbackDays}d)` : ""}</span>
        <ContextSourceBadge context={context} />
      </div>
      <div className="mt-1 flex items-end justify-between gap-2">
        <div className={`text-sm font-semibold leading-tight ${toneClass}`}>{value}</div>
        {momentumLabel ? <div className="text-[11px] font-semibold leading-tight text-slate-400">{momentumLabel}</div> : null}
      </div>
    </div>
  );
}

function ContextCard({
  label,
  value,
  context,
  onEdit,
  tone = "neutral",
}: {
  label: string;
  value: string;
  context?: MarketContext;
  onEdit?: () => void;
  tone?: "bullish" | "bearish" | "neutral";
}) {
  const toneClass = tone === "bullish" ? "text-emerald-300" : tone === "bearish" ? "text-rose-300" : "text-slate-100";
  return (
    <div className="min-h-14 rounded-md border border-ink-700 bg-ink-900 px-3 py-2">
      <div className="flex items-center justify-between gap-2 text-xs text-slate-500">
        <span>{label}</span>
        <ContextSourceBadge context={context} />
      </div>
      <div className="mt-1 flex items-end justify-between gap-3">
        <div className={`text-sm font-semibold leading-tight ${toneClass}`}>{value}</div>
        {onEdit ? (
          <IconButton title={`Edit ${label}`} onClick={onEdit}>
            <Pencil size={13} />
          </IconButton>
        ) : null}
      </div>
    </div>
  );
}

function ContextOverrideEditor({
  context,
  contextType,
  onCancel,
  onSaved,
}: {
  context: MarketContext;
  contextType: ContextType;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [value, setValue] = useState(context.effective_value);
  const [confidence, setConfidence] = useState(String(context.effective_confidence));
  const [noExpiry, setNoExpiry] = useState(defaultNoExpiry(context));
  const [expiryHours, setExpiryHours] = useState(4);
  const [reason, setReason] = useState("");
  const [overlays, setOverlays] = useState(readOverlays(context.metadata.overlays));
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setValue(context.effective_value);
    setConfidence(String(context.effective_confidence));
    setNoExpiry(defaultNoExpiry(context));
    setExpiryHours(readExpiryHours(context) ?? 4);
    setReason("");
    setOverlays(readOverlays(context.metadata.overlays));
    setError(null);
  }, [context, contextType]);

  const save = async () => {
    const parsedConfidence = Number(confidence);
    if (!Number.isFinite(parsedConfidence) || parsedConfidence < 0 || parsedConfidence > 1) {
      setError("Confidence must be between 0 and 1.");
      return;
    }

    setIsSaving(true);
    setError(null);
    try {
      await updateMarketContextOverride("H1", contextType, {
        value,
        confidence: parsedConfidence,
        no_expiry: noExpiry,
        expires_at: noExpiry ? null : expiryIso(expiryHours),
        overlays: contextType === "regime" ? overlays : undefined,
        reason: reason.trim() || undefined,
      });
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save context override.");
    } finally {
      setIsSaving(false);
    }
  };

  const resetToBot = async () => {
    setIsSaving(true);
    setError(null);
    try {
      await updateMarketContextOverride("H1", contextType, {
        use_bot: true,
        reason: reason.trim() || undefined,
      });
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reset context.");
    } finally {
      setIsSaving(false);
    }
  };

  const values = contextType === "bias" ? BIAS_VALUES : REGIME_VALUES;
  return (
    <div className="col-span-4 grid gap-3 rounded-md border border-ink-700 bg-ink-900 p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-xs text-slate-500">H1 {contextType === "bias" ? "Bias" : "Regime"} Override</div>
          <div className="mt-0.5 text-xs text-slate-400">
            Bot: {context.bot_value} · effective: {context.effective_value}
          </div>
        </div>
        <IconButton title="Close editor" onClick={onCancel}>
          <X size={14} />
        </IconButton>
      </div>

      <div className="grid grid-cols-[160px_120px_140px_120px_minmax(0,1fr)] gap-2">
        <label className="grid gap-1 text-xs text-slate-500">
          Value
          <select
            className="h-9 rounded-md border border-ink-700 bg-ink-850 px-2 text-sm text-slate-100 outline-none"
            value={value}
            onChange={(event) => setValue(event.target.value)}
          >
            {values.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs text-slate-500">
          Confidence
          <input
            className="h-9 rounded-md border border-ink-700 bg-ink-850 px-2 text-sm text-slate-100 outline-none"
            max={1}
            min={0}
            step={0.01}
            type="number"
            value={confidence}
            onChange={(event) => setConfidence(event.target.value)}
          />
        </label>
        <label className="grid gap-1 text-xs text-slate-500">
          Expiry
          <select
            className="h-9 rounded-md border border-ink-700 bg-ink-850 px-2 text-sm text-slate-100 outline-none disabled:cursor-not-allowed disabled:opacity-50"
            disabled={noExpiry}
            value={expiryHours}
            onChange={(event) => setExpiryHours(Number(event.target.value))}
          >
            {EXPIRY_PRESETS.map((preset) => (
              <option key={preset.label} value={preset.hours}>
                {preset.label}
              </option>
            ))}
          </select>
        </label>
        <label className="mt-6 flex items-center gap-2 text-xs text-slate-400">
          <input
            checked={noExpiry}
            className="accent-cyan-400"
            type="checkbox"
            onChange={(event) => setNoExpiry(event.target.checked)}
          />
          No expiry
        </label>
        <label className="grid gap-1 text-xs text-slate-500">
          Reason
          <input
            className="h-9 rounded-md border border-ink-700 bg-ink-850 px-2 text-sm text-slate-100 outline-none"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
      </div>

      {contextType === "regime" ? (
        <div className="flex flex-wrap gap-3 text-xs text-slate-400">
          {REGIME_OVERLAYS.map((overlay) => (
            <label key={overlay} className="flex items-center gap-2">
              <input
                checked={overlays.includes(overlay)}
                className="accent-cyan-400"
                type="checkbox"
                onChange={(event) => {
                  setOverlays((current) =>
                    event.target.checked ? [...current, overlay] : current.filter((item) => item !== overlay),
                  );
                }}
              />
              {overlay}
            </label>
          ))}
        </div>
      ) : null}

      {error ? <div className="rounded-md border border-rose-500/40 bg-rose-500/10 p-2 text-xs text-rose-100">{error}</div> : null}

      <div className="flex justify-end gap-2">
        <button
          className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-ink-700 bg-ink-800 px-3 text-sm text-slate-100 hover:border-slate-500 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={isSaving}
          type="button"
          onClick={resetToBot}
        >
          <RotateCcw size={14} />
          Bot
        </button>
        <button
          className="inline-flex h-9 items-center justify-center gap-2 rounded-md border border-cyan-400/60 bg-cyan-400/15 px-3 text-sm font-semibold text-cyan-100 hover:bg-cyan-400/25 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={isSaving}
          type="button"
          onClick={save}
        >
          <Save size={14} />
          {isSaving ? "Saving" : "Save"}
        </button>
      </div>
    </div>
  );
}

function IconButton({ title, children, onClick }: { title: string; children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-ink-700 bg-ink-850 text-slate-300 hover:border-cyan-500 hover:text-cyan-200"
      title={title}
      type="button"
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function ContextSourceBadge({ context }: { context: MarketContext | undefined }) {
  if (!context || context.source === "bot") return null;
  return (
    <span className="rounded border border-cyan-400/40 bg-cyan-400/10 px-1.5 py-0.5 text-[10px] font-semibold text-cyan-200">
      {context.source}
    </span>
  );
}

function defaultNoExpiry(context: MarketContext): boolean {
  return context.valid_until === null && context.source === "human";
}

function readExpiryHours(context: MarketContext): number | null {
  if (!context.valid_until || context.source !== "human") return null;
  const validUntil = new Date(context.valid_until).getTime();
  const lastOverrideAt = context.metadata.last_human_override_at;
  const createdAt = typeof lastOverrideAt === "string" ? new Date(lastOverrideAt).getTime() : Date.now();
  if (Number.isNaN(validUntil) || Number.isNaN(createdAt)) return null;
  const hours = Math.round((validUntil - createdAt) / (60 * 60 * 1000));
  const preset = EXPIRY_PRESETS.find((item) => item.hours === hours);
  return preset?.hours ?? null;
}

function expiryIso(hours: number): string {
  return new Date(Date.now() + hours * 60 * 60 * 1000).toISOString().replace(".000Z", "+00:00");
}

function readOverlays(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function readCurrentPriceChange(payload: ChartPayload | undefined): { currentPrice: number; changePercent: number } | null {
  const candles = payload?.layers.candles;
  const last = candles?.at(-1);
  if (!candles || !last) return null;

  const lastDate = last.time.slice(0, 10);
  const firstCandleOfDay = candles.find((candle) => candle.time.startsWith(lastDate));
  const dayOpen = firstCandleOfDay?.open;
  if (!dayOpen) return { currentPrice: last.close, changePercent: 0 };

  return {
    currentPrice: last.close,
    changePercent: ((last.close - dayOpen) / dayOpen) * 100,
  };
}

function formatAtrValue(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "--";
}

function formatRsiValue(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(1) : "--";
}

function formatRsiSlope(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "--";
  }
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}`;
}

function slopeToneClass(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value) || Math.abs(value) < 0.05) {
    return "text-slate-100";
  }
  return value > 0 ? "text-emerald-300" : "text-rose-300";
}
