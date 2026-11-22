import type { ChartDrawing } from "../../types";

function sameInstant(left: string, right: string): boolean {
  const leftTime = Date.parse(left);
  const rightTime = Date.parse(right);
  return Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime === rightTime;
}

export function findVolumeProfileForRange(
  drawings: ChartDrawing[],
  symbol: string,
  rangeStart: string,
  rangeEnd: string,
): ChartDrawing | null {
  return drawings.find((drawing) => {
    if (drawing.symbol !== symbol || drawing.drawing_type !== "volume_profile_fixed_range" || drawing.hidden) return false;
    const start = drawing.volume_profile?.range_start ?? drawing.anchors[0]?.time;
    const end = drawing.volume_profile?.range_end ?? drawing.anchors[1]?.time;
    return Boolean(start && end && sameInstant(start, rangeStart) && sameInstant(end, rangeEnd));
  }) ?? null;
}
