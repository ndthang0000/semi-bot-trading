import type { SetupCandidate } from "../../types";

export type H1ExecutionReview = {
  originalBlocked: boolean;
  softBlockedReasons: string[];
  hardBlockedReasons: string[];
};

export function reviewH1Execution(candidate: SetupCandidate, nowMs = Date.now()): H1ExecutionReview {
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
    if (rr < 1.5 || rr > 4) hardBlockedReasons.push(`Risk:reward ${rr.toFixed(2)} must be between 1.50 and 4.00.`);

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

    const referencePrice = Number(metadata.reference_price ?? 0);
    if (referencePrice > 0) {
      const validLimit = candidate.direction === "long" ? entry < referencePrice : entry > referencePrice;
      if (!validLimit) {
        hardBlockedReasons.push(
          candidate.direction === "long"
            ? "BUY LIMIT entry must be below the signal reference price."
            : "SELL LIMIT entry must be above the signal reference price.",
        );
      }
    }
  }

  const expiresAt = typeof metadata.limit_expires_at === "string" ? Date.parse(metadata.limit_expires_at) : NaN;
  if (Number.isFinite(expiresAt) && expiresAt <= nowMs) hardBlockedReasons.push("Signal has expired.");

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
