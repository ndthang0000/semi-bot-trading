import { Lock, Trash2 } from "lucide-react";
import type { PointerEvent as ReactPointerEvent } from "react";
import type { ChartDrawing } from "../../types";

export type DrawingPoint = { x: number; y: number; price: number; time: string };
export type RenderedChartDrawing = { drawing: ChartDrawing; points: DrawingPoint[] };
export type MeasurePreview = { start: DrawingPoint; end: DrawingPoint };
export type FibExtensionPreview = { anchors: DrawingPoint[]; cursor: DrawingPoint };
export type PriceGuide = { y: number; price: number };

type Props = {
  drawings: RenderedChartDrawing[];
  measure: MeasurePreview | null;
  fibExtensionPreview: FibExtensionPreview | null;
  priceGuide: PriceGuide | null;
  plotWidth: number;
  selectedId: string | null;
  onSelect: (drawing: ChartDrawing) => void;
  onDelete: (drawing: ChartDrawing) => void;
  onMoveStart: (event: ReactPointerEvent<HTMLButtonElement>, drawing: ChartDrawing) => void;
};

const STANDARD_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
const OTE_LEVELS = [0, 0.5, 0.62, 0.705, 0.79, 1];
const EXTENSION_LEVELS = [0, 0.618, 1, 1.272, 1.618, 2, 2.618];

export function fibRetracementValue(origin: number, end: number, level: number): number {
  return end + (origin - end) * level;
}

export function fibExtensionValue(origin: number, end: number, retracementEnd: number, level: number): number {
  return retracementEnd + (end - origin) * level;
}

export function fibExtensionLineRange(impulseEndX: number, retracementEndX: number): { left: number; right: number } {
  return {
    left: Math.min(impulseEndX, retracementEndX),
    right: Math.max(impulseEndX, retracementEndX),
  };
}

export function ChartDrawingLayer({ drawings, measure, fibExtensionPreview, priceGuide, plotWidth, selectedId, onSelect, onDelete, onMoveStart }: Props) {
  return (
    <div className="pointer-events-none absolute inset-0 z-[42]">
      <svg className="absolute inset-0 h-full w-full overflow-visible" aria-hidden="true">
        {drawings.map(({ drawing, points }) => {
          const selected = drawing.id === selectedId;
          if (drawing.drawing_type === "horizontal_line" && points[0]) {
            return (
              <g key={drawing.id} className="pointer-events-auto cursor-pointer" onClick={() => onSelect(drawing)}>
                <line x1={0} x2={plotWidth} y1={points[0].y} y2={points[0].y} stroke={selected ? "#67e8f9" : "#94a3b8"} strokeWidth={selected ? 2 : 1} strokeDasharray="5 4" />
                <rect x={Math.max(4, plotWidth - 72)} y={points[0].y - 10} width={68} height={19} rx={4} fill="#111827" stroke={selected ? "#67e8f9" : "#475569"} />
                <text x={Math.max(8, plotWidth - 68)} y={points[0].y + 4} fill="#dbeafe" fontSize="11">{points[0].price.toFixed(2)}</text>
              </g>
            );
          }
          if (drawing.drawing_type === "fib_retracement" && points.length === 2) {
            const levels = drawing.properties.variant === "ote" ? OTE_LEVELS : STANDARD_LEVELS;
            const left = Math.min(points[0].x, points[1].x);
            const right = Math.max(points[0].x, points[1].x);
            return (
              <g key={drawing.id} className="pointer-events-auto cursor-pointer" onClick={() => onSelect(drawing)}>
                <line x1={points[0].x} x2={points[1].x} y1={points[0].y} y2={points[1].y} stroke="#64748b" strokeWidth="1" strokeDasharray="3 3" />
                {levels.map((level) => {
                  // Anchor 0 is the impulse origin and anchor 1 is its end.
                  // Retracement 0 therefore starts at the impulse end, while
                  // level 1 returns to the origin (TradingView convention).
                  const y = fibRetracementValue(points[0].y, points[1].y, level);
                  const price = fibRetracementValue(points[0].price, points[1].price, level);
                  const ote = drawing.properties.variant === "ote" && level >= 0.62 && level <= 0.79;
                  return (
                    <g key={level}>
                      <line x1={left} x2={right} y1={y} y2={y} stroke={ote ? "#fbbf24" : selected ? "#67e8f9" : "#a78bfa"} strokeWidth={ote || selected ? 1.5 : 1} opacity={0.9} />
                      <text x={right + 5} y={y + 4} fill={ote ? "#fde68a" : "#c4b5fd"} fontSize="10">{level.toFixed(3).replace(/0+$/, "").replace(/\.$/, "")} · {price.toFixed(2)}</text>
                    </g>
                  );
                })}
              </g>
            );
          }
          if (drawing.drawing_type === "fib_extension" && points.length === 3) {
            return <FibExtensionSvg key={drawing.id} points={points} plotWidth={plotWidth} selected={selected} onClick={() => onSelect(drawing)} />;
          }
          return null;
        })}
        {measure ? <MeasureSvg measure={measure} /> : null}
        {fibExtensionPreview ? <FibExtensionPreviewSvg preview={fibExtensionPreview} plotWidth={plotWidth} /> : null}
        {priceGuide ? (
          <g>
            <line x1={0} x2={plotWidth} y1={priceGuide.y} y2={priceGuide.y} stroke="#67e8f9" strokeDasharray="4 4" strokeWidth="1" opacity="0.9" />
            <rect x={Math.max(4, plotWidth - 72)} y={priceGuide.y - 10} width={68} height={19} rx={4} fill="#083344" stroke="#22d3ee" />
            <text x={Math.max(8, plotWidth - 68)} y={priceGuide.y + 4} fill="#cffafe" fontSize="11">{priceGuide.price.toFixed(2)}</text>
          </g>
        ) : null}
      </svg>

      {drawings.map(({ drawing, points }) => drawing.drawing_type === "note" && points[0] ? (
        <button
          key={drawing.id}
          className={`pointer-events-auto absolute max-w-64 -translate-y-full rounded-lg border px-3 py-2 text-left text-xs shadow-xl backdrop-blur ${
            drawing.id === selectedId ? "border-cyan-300 bg-cyan-950/95 text-cyan-50" : "border-amber-300/45 bg-[#19170f]/94 text-amber-50"
          }`}
          style={{ left: points[0].x + 7, top: points[0].y - 6 }}
          title="Click để chọn ghi chú"
          type="button"
          onClick={() => onSelect(drawing)}
          onPointerDown={(event) => onMoveStart(event, drawing)}
        >
          {drawing.locked ? <Lock className="mb-1 inline text-amber-300" size={11} /> : null}
          <span className="block whitespace-pre-wrap break-words">{drawing.content}</span>
        </button>
      ) : null)}

      {selectedId ? (
        <button
          className="pointer-events-auto absolute bottom-16 right-4 flex items-center gap-2 rounded-lg border border-rose-400/40 bg-rose-950/90 px-3 py-2 text-xs font-semibold text-rose-100 shadow-lg hover:bg-rose-900"
          type="button"
          onClick={() => {
            const selected = drawings.find((item) => item.drawing.id === selectedId)?.drawing;
            if (selected) onDelete(selected);
          }}
        >
          <Trash2 size={14} /> Xóa drawing
        </button>
      ) : null}
    </div>
  );
}

function FibExtensionSvg({ points, plotWidth, selected, onClick }: { points: DrawingPoint[]; plotWidth: number; selected: boolean; onClick: () => void }) {
  const [origin, end, retracementEnd] = points;
  const { left, right } = fibExtensionLineRange(end.x, retracementEnd.x);
  const labelX = Math.min(right + 5, Math.max(5, plotWidth - 118));
  return (
    <g className="pointer-events-auto cursor-pointer" onClick={onClick}>
      <polyline points={`${origin.x},${origin.y} ${end.x},${end.y} ${retracementEnd.x},${retracementEnd.y}`} fill="none" stroke={selected ? "#67e8f9" : "#64748b"} strokeWidth={selected ? 1.5 : 1} strokeDasharray="3 3" />
      {EXTENSION_LEVELS.map((level) => {
        const y = fibExtensionValue(origin.y, end.y, retracementEnd.y, level);
        const price = fibExtensionValue(origin.price, end.price, retracementEnd.price, level);
        const major = level === 1 || level === 1.618;
        return (
          <g key={level}>
            <line x1={left} x2={right} y1={y} y2={y} stroke={selected ? "#67e8f9" : major ? "#34d399" : "#6ee7b7"} strokeWidth={major || selected ? 1.5 : 1} opacity={major ? 0.95 : 0.76} />
            <text x={labelX} y={y - 4} fill={major ? "#a7f3d0" : "#6ee7b7"} fontSize="10">{formatFibLevel(level)} · {price.toFixed(2)}</text>
          </g>
        );
      })}
    </g>
  );
}

function FibExtensionPreviewSvg({ preview, plotWidth }: { preview: FibExtensionPreview; plotWidth: number }) {
  const points = [...preview.anchors, preview.cursor];
  if (preview.anchors.length === 1) {
    return <line x1={points[0].x} y1={points[0].y} x2={points[1].x} y2={points[1].y} stroke="#6ee7b7" strokeWidth="1.5" strokeDasharray="4 3" />;
  }
  return <FibExtensionSvg points={points} plotWidth={plotWidth} selected={false} onClick={() => undefined} />;
}

function formatFibLevel(level: number): string {
  return level.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

function MeasureSvg({ measure }: { measure: MeasurePreview }) {
  const delta = measure.end.price - measure.start.price;
  const percent = measure.start.price === 0 ? 0 : (delta / measure.start.price) * 100;
  const minutes = Math.round(Math.abs(Date.parse(measure.end.time) - Date.parse(measure.start.time)) / 60_000);
  const duration = minutes >= 1_440 ? `${(minutes / 1_440).toFixed(1)}d` : minutes >= 60 ? `${(minutes / 60).toFixed(1)}h` : `${minutes}m`;
  const x = Math.min(measure.start.x, measure.end.x);
  const y = Math.min(measure.start.y, measure.end.y);
  const width = Math.max(1, Math.abs(measure.end.x - measure.start.x));
  const height = Math.max(1, Math.abs(measure.end.y - measure.start.y));
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={delta >= 0 ? "rgba(16,185,129,.13)" : "rgba(244,63,94,.13)"} stroke={delta >= 0 ? "#34d399" : "#fb7185"} strokeWidth="1" strokeDasharray="4 3" />
      <line x1={measure.start.x} y1={measure.start.y} x2={measure.end.x} y2={measure.end.y} stroke={delta >= 0 ? "#34d399" : "#fb7185"} strokeWidth="1.5" />
      <rect x={x + 5} y={y + 5} width={132} height={48} rx={5} fill="#0f172a" stroke="#475569" />
      <text x={x + 12} y={y + 19} fill="#e2e8f0" fontSize="11">Δ {delta >= 0 ? "+" : ""}{delta.toFixed(2)}</text>
      <text x={x + 12} y={y + 33} fill={delta >= 0 ? "#6ee7b7" : "#fda4af"} fontSize="11">{percent >= 0 ? "+" : ""}{percent.toFixed(2)}%</text>
      <text x={x + 12} y={y + 47} fill="#94a3b8" fontSize="10">Khoảng thời gian {duration}</text>
    </g>
  );
}
