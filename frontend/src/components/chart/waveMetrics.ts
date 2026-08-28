import type { WaveLeg } from "../../types";

export function formatWaveDuration(leg: WaveLeg): string {
  if (leg.bars !== null) return leg.bars.toFixed(0);
  return Number.isInteger(leg.duration_hours) ? leg.duration_hours.toFixed(0) : leg.duration_hours.toFixed(1);
}

export function formatWaveLegLabel(leg: WaveLeg): string {
  const sign = leg.direction === "up" ? "+" : "−";
  return `${sign}${leg.price_move.toFixed(1)} · ${formatWaveDuration(leg)}H`;
}
