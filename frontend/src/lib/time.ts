import type { UTCTimestamp } from "lightweight-charts";

export function toUnixTime(value: string): UTCTimestamp {
  return Math.floor(new Date(value).getTime() / 1000) as UTCTimestamp;
}

export function compactTime(value: string | null | undefined): string {
  if (!value) return "--";
  return value.replace("T", " ").replace("+00:00", "");
}

export function price(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "--";
  return value.toFixed(2);
}
