import type { SetupCandidate } from "../../types";

export type H1ExecutionReview = {
  originalBlocked: boolean;
  softBlockedReasons: string[];
  hardBlockedReasons: string[];
};

export function reviewH1Execution(candidate: SetupCandidate): H1ExecutionReview {
  const metadata = candidate.metadata;
  const originalBlocked = metadata.original_status === "blocked" || candidate.status === "blocked";
  const softBlockedReasons = readStringList(metadata.soft_blocked_reasons);
  const originalHard = readStringList(metadata.hard_blocked_reasons);
  const hardBlockedReasons = originalHard.filter((reason) => reason.toLowerCase().includes("doji"));
  const entry = candidate.entry;
  const stopLoss = candidate.stop_loss;
  const takeProfit = candidate.take_profit[0];

  if (entry === null || stopLoss === null || typeof takeProfit !== "number") {
    hardBlockedReasons.push("Entry, SL and TP are required.");
  } else {
    const validGeometry = candidate.direction === "long"
      ? stopLoss < entry && entry < takeProfit
      : takeProfit < entry && entry < stopLoss;
    if (!validGeometry) hardBlockedReasons.push(`Invalid ${candidate.direction.toUpperCase()} Entry/SL/TP geometry.`);

    const risk = Math.abs(entry - stopLoss);
    const reward = Math.abs(takeProfit - entry);
    const rr = risk > 0 ? reward / risk : 0;
    const targetMode = typeof metadata.target_mode === "string" ? metadata.target_mode : "fixed_rr";
    const waveTarget = targetMode === "wave_safe" || targetMode === "wave_base";
    if (rr < 1 || (!waveTarget && rr > 4)) {
      hardBlockedReasons.push(
        waveTarget
          ? `Wave risk:reward ${rr.toFixed(2)} must be at least 1.00.`
          : `Risk:reward ${rr.toFixed(2)} must be between 1.00 and 4.00.`,
      );
    }

    const atr = Number(metadata.atr ?? 0);
    const parameters = isRecord(metadata.parameters) ? metadata.parameters : {};
    const minStopAtr = Number(parameters.min_stop_atr ?? 0.5);
    const maxStopAtr = Number(parameters.max_stop_atr ?? 1.2);
    if (!(atr > 0)) {
      hardBlockedReasons.push("H1 ATR snapshot is unavailable.");
    } else {
      const stopAtr = risk / atr;
      if (stopAtr < minStopAtr || stopAtr > maxStopAtr) {
        hardBlockedReasons.push(`SL size ${stopAtr.toFixed(2)} ATR must be between ${minStopAtr.toFixed(2)} and ${maxStopAtr.toFixed(2)} ATR.`);
      }
    }

  }

  return {
    originalBlocked,
    softBlockedReasons,
    hardBlockedReasons: [...new Set(hardBlockedReasons)],
  };
}

function readStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
