import type { SetupCandidate } from "../../types";

export function h1SetupExpiryDuration(candidate: SetupCandidate): string | null {
  if (candidate.playbook !== "h1_impulse_retest_v1") return null;
  const explicitHours = candidate.metadata.expiry_hours;
  if (typeof explicitHours === "number" && Number.isFinite(explicitHours) && explicitHours > 0) {
    return formatHours(explicitHours);
  }
  if (!candidate.expires_at) return null;
  const rawStart = candidate.metadata.as_of ?? candidate.metadata.created_at;
  if (typeof rawStart !== "string") return null;
  const start = Date.parse(rawStart);
  const end = Date.parse(candidate.expires_at);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return null;
  return formatHours((end - start) / 3_600_000);
}

function formatHours(hours: number): string {
  const rounded = Math.round(hours * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)}h`;
}
