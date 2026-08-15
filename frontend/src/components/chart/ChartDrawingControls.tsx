import type { PointerEventHandler } from "react";
import type { ChartDrawing, ChartDrawingAnchor, ChartDrawingTool } from "../../types";
import { ChartDrawingLayer, type MeasurePreview, type PriceGuide, type RenderedChartDrawing } from "./ChartDrawingLayer";
import { ChartDrawingToolbar } from "./ChartDrawingToolbar";

export type PendingChartNote = {
  anchor: ChartDrawingAnchor;
  x: number;
  y: number;
};

type Props = {
  drawings: RenderedChartDrawing[];
  measure: MeasurePreview | null;
  priceGuide: PriceGuide | null;
  plotWidth: number;
  selectedId: string | null;
  activeTool: ChartDrawingTool;
  measureHasStart: boolean;
  pendingNote: PendingChartNote | null;
  noteContent: string;
  chartWidth: number;
  message: string | null;
  onDelete: (drawing: ChartDrawing) => void;
  onMoveStart: (event: React.PointerEvent<HTMLButtonElement>, drawing: ChartDrawing) => void;
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
        priceGuide={props.priceGuide}
        plotWidth={props.plotWidth}
        selectedId={props.selectedId}
        onDelete={props.onDelete}
        onMoveStart={props.onMoveStart}
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
      <ChartDrawingToolbar activeTool={props.activeTool} onToolChange={props.onToolChange} />
      {props.activeTool !== "cursor" && !props.pendingNote ? (
        <div className="pointer-events-none absolute left-4 top-4 z-[65] hidden rounded-lg border border-cyan-400/35 bg-ink-900/92 px-3 py-2 text-xs text-cyan-100 shadow-lg lg:block">
          {drawingHint(props.activeTool, props.measureHasStart)}
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

function drawingHint(tool: ChartDrawingTool, measureHasStart: boolean): string {
  if (tool === "measure") return measureHasStart ? "Click điểm kết thúc để hoàn thành phép đo" : "Click điểm bắt đầu phép đo";
  if (tool === "fib_standard") return "Kéo từ swing bắt đầu đến swing kết thúc để vẽ Fibonacci";
  if (tool === "fib_ote") return "Kéo theo nhịp impulse; vùng vàng 0.62–0.79 là OTE";
  return "Click một mức giá trên chart";
}
