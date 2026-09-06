import type { LineDraft } from "../../store/lineReactionStore";
import { createRandomUuid } from "../../lib/randomUuid";
export function lineDraftFromPoints(
  start: { x: number; time: string; price: number },
  end: { x: number; time: string },
  direction: "long" | "short",
): LineDraft | null {
  if (Math.abs(end.x-start.x) < 3 || end.time === start.time) return null;
  const times = [start.time, end.time].sort((a,b) => Date.parse(a)-Date.parse(b));
  return { price:start.price, direction, visual_start:times[0], visual_end:times[1], client_request_id: createRandomUuid() };
}
