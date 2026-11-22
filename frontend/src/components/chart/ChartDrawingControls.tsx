import { useEffect, useState, type PointerEventHandler } from "react";
import type { ChartDrawing, ChartDrawingAnchor, ChartDrawingTool, VolumeProfileSettings } from "../../types";
import { ChartDrawingLayer, type FibExtensionPreview, type MeasurePreview, type PriceGuide, type RenderedChartDrawing } from "./ChartDrawingLayer";
import { ChartDrawingToolbar } from "./ChartDrawingToolbar";

export type PendingChartNote = {
  anchor: ChartDrawingAnchor;
  x: number;
  y: number;
};

type Props = {
  drawings: RenderedChartDrawing[];
  measure: MeasurePreview | null;
  fibExtensionPreview: FibExtensionPreview | null;
  priceGuide: PriceGuide | null;
  plotWidth: number;
  selectedId: string | null;
  activeTool: ChartDrawingTool;
  measureHasStart: boolean;
  fibExtensionAnchorCount: number;
  pendingNote: PendingChartNote | null;
  noteContent: string;
  chartWidth: number;
  message: string | null;
  onDelete: (drawing: ChartDrawing) => void;
  onMoveStart: (event: React.PointerEvent<HTMLButtonElement>, drawing: ChartDrawing) => void;
  onRangeMoveStart: (event: React.PointerEvent<HTMLButtonElement>, drawing: ChartDrawing, anchorIndex: number) => void;
  onVolumeProfileSettingsSave: (drawing: ChartDrawing, settings: VolumeProfileSettings) => void;
  onDrawingDeselect: () => void;
  onPreviousDayVolumeProfile: () => void;
  onSelect: (drawing: ChartDrawing) => void;
  onToolChange: (tool: ChartDrawingTool) => void;
  onPointerDown: PointerEventHandler<HTMLDivElement>;
  onPointerMove: PointerEventHandler<HTMLDivElement>;
  onPointerLeave: () => void;
  onNoteContentChange: (content: string) => void;
  onSaveNote: () => void;
  onCancelNote: () => void;
};

export function ChartDrawingControls(props: Props) {
  return (
    <>
      <ChartDrawingLayer
        drawings={props.drawings}
        measure={props.measure}
        fibExtensionPreview={props.fibExtensionPreview}
        priceGuide={props.priceGuide}
        plotWidth={props.plotWidth}
        selectedId={props.selectedId}
        onDelete={props.onDelete}
        onMoveStart={props.onMoveStart}
        onRangeMoveStart={props.onRangeMoveStart}
        onSelect={props.onSelect}
      />
      {props.activeTool !== "cursor" && !props.pendingNote ? (
        <div
          className="absolute inset-0 z-[60] cursor-crosshair"
          onClick={(event) => event.stopPropagation()}
          onPointerDown={props.onPointerDown}
          onPointerMove={props.onPointerMove}
          onPointerLeave={props.onPointerLeave}
        />
      ) : null}
      <ChartDrawingToolbar activeTool={props.activeTool} onToolChange={props.onToolChange} onPreviousDayVolumeProfile={props.onPreviousDayVolumeProfile} />
      <VolumeProfileSettingsEditor
        drawing={props.drawings.find((item) => item.drawing.id === props.selectedId)?.drawing ?? null}
        onClose={props.onDrawingDeselect}
        onSave={props.onVolumeProfileSettingsSave}
      />
      {props.activeTool !== "cursor" && !props.pendingNote ? (
        <div className="pointer-events-none absolute left-4 top-4 z-[65] hidden rounded-lg border border-cyan-400/35 bg-ink-900/92 px-3 py-2 text-xs text-cyan-100 shadow-lg lg:block">
          {drawingHint(props.activeTool, props.measureHasStart, props.fibExtensionAnchorCount)}
          <span className="ml-2 text-slate-500">Esc để hủy</span>
        </div>
      ) : null}
      {props.pendingNote ? (
        <form
          className="absolute z-[80] w-72 rounded-xl border border-amber-300/35 bg-[#17150e]/98 p-3 shadow-2xl"
          style={{
            left: Math.min(props.pendingNote.x + 8, Math.max(8, props.chartWidth - 296)),
            top: Math.max(8, props.pendingNote.y - 12),
          }}
          onSubmit={(event) => {
            event.preventDefault();
            props.onSaveNote();
          }}
        >
          <label className="mb-2 block text-xs font-semibold uppercase tracking-wider text-amber-200">
            Ghi chú tại {props.pendingNote.anchor.price.toFixed(2)}
          </label>
          <textarea
            autoFocus
            className="min-h-24 w-full resize-y rounded-lg border border-white/10 bg-black/35 px-3 py-2 text-sm text-slate-100 outline-none focus:border-amber-300/60"
            maxLength={2000}
            placeholder="Nhập nhận định, điều kiện hoặc lưu ý..."
            value={props.noteContent}
            onChange={(event) => props.onNoteContentChange(event.target.value)}
          />
          <div className="mt-2 flex justify-end gap-2">
            <button className="rounded-lg px-3 py-1.5 text-xs text-slate-400 hover:bg-white/5" type="button" onClick={props.onCancelNote}>Hủy</button>
            <button className="rounded-lg bg-amber-300 px-3 py-1.5 text-xs font-bold text-amber-950 disabled:opacity-40" disabled={!props.noteContent.trim()} type="submit">Lưu note</button>
          </div>
        </form>
      ) : null}
      {props.message ? (
        <div className="pointer-events-none absolute bottom-16 left-1/2 z-[75] -translate-x-1/2 rounded-lg border border-emerald-400/35 bg-emerald-950/95 px-3 py-2 text-xs text-emerald-100 shadow-lg">
          {props.message}
        </div>
      ) : null}
    </>
  );
}

function drawingHint(tool: ChartDrawingTool, measureHasStart: boolean, fibExtensionAnchorCount: number): string {
  if (tool === "measure") return measureHasStart ? "Click điểm kết thúc để hoàn thành phép đo" : "Click điểm bắt đầu phép đo";
  if (tool === "fib_standard") return "Kéo từ swing bắt đầu đến swing kết thúc để vẽ Fibonacci";
  if (tool === "fib_ote") return "Kéo theo nhịp impulse; vùng vàng 0.62–0.79 là OTE";
  if (tool === "fib_extension") {
    if (fibExtensionAnchorCount === 1) return "Click B tại cuối nhịp impulse";
    if (fibExtensionAnchorCount === 2) return "Click C tại cuối nhịp hồi để tạo extension";
    return "Click A tại đầu nhịp impulse";
  }
  if (tool === "volume_profile") return "Kéo qua khoảng thời gian cần tính Fixed Range Volume Profile";
  return "Click một mức giá trên chart";
}

function VolumeProfileSettingsEditor({ drawing, onClose, onSave }: { drawing: ChartDrawing | null; onClose: () => void; onSave: (drawing: ChartDrawing, settings: VolumeProfileSettings) => void }) {
  const profile = drawing?.drawing_type === "volume_profile_fixed_range" ? drawing.volume_profile : undefined;
  const [settings, setSettings] = useState<VolumeProfileSettings | null>(profile?.settings ?? null);
  useEffect(() => setSettings(profile?.settings ?? null), [drawing?.id, drawing?.revision, profile?.settings]);
  if (!drawing || !profile || !settings) return null;
  return (
    <form
      className="absolute right-4 top-4 z-[80] hidden w-72 gap-2 rounded-xl border border-teal-300/30 bg-ink-950/95 p-3 text-xs text-slate-200 shadow-2xl backdrop-blur lg:grid"
      onSubmit={(event) => { event.preventDefault(); onSave(drawing, settings); }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="grid min-w-0 gap-0.5">
          <strong className="text-teal-200">Fixed Range Volume Profile</strong>
          <span className="text-[10px] text-slate-500">M1 tick volume · {profile.source_bar_count} bars</span>
        </div>
        <button
          aria-label="Close Volume Profile settings"
          className="shrink-0 rounded border border-slate-600 px-2 py-1 text-[10px] font-semibold text-slate-300 hover:border-cyan-300/50 hover:text-cyan-100"
          type="button"
          onClick={onClose}
        >
          ESC
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <SettingNumber label="Rows" min={10} max={200} value={settings.rows} onChange={(rows) => setSettings({ ...settings, rows })} />
        <SettingNumber label="Value area %" min={1} max={100} value={settings.value_area_pct} onChange={(value_area_pct) => setSettings({ ...settings, value_area_pct })} />
        <SettingNumber label="Width %" min={10} max={100} value={settings.width_pct} onChange={(width_pct) => setSettings({ ...settings, width_pct })} />
        <label className="grid gap-1"><span className="text-slate-400">Mode</span><select className="rounded border border-ink-600 bg-ink-900 px-2 py-1.5" value={settings.mode} onChange={(event) => setSettings({ ...settings, mode: event.target.value as VolumeProfileSettings["mode"] })}><option value="up_down">Up / Down</option><option value="total">Total</option><option value="delta">Delta</option></select></label>
        <label className="grid gap-1"><span className="text-slate-400">Placement</span><select className="rounded border border-ink-600 bg-ink-900 px-2 py-1.5" value={settings.placement} onChange={(event) => setSettings({ ...settings, placement: event.target.value as VolumeProfileSettings["placement"] })}><option value="right">Right</option><option value="left">Left</option></select></label>
      </div>
      <div className="flex gap-3">
        {(["show_poc", "show_vah", "show_val"] as const).map((key) => <label key={key} className="flex items-center gap-1"><input checked={settings[key]} type="checkbox" onChange={(event) => setSettings({ ...settings, [key]: event.target.checked })} />{key.replace("show_", "").toUpperCase()}</label>)}
      </div>
      <button className="rounded-lg bg-teal-300 px-3 py-2 font-bold text-teal-950" type="submit">Save profile settings</button>
    </form>
  );
}

function SettingNumber({ label, min, max, value, onChange }: { label: string; min: number; max: number; value: number; onChange: (value: number) => void }) {
  return <label className="grid gap-1"><span className="text-slate-400">{label}</span><input className="rounded border border-ink-600 bg-ink-900 px-2 py-1.5" min={min} max={max} type="number" value={value} onChange={(event) => onChange(Number(event.target.value))} /></label>;
}
