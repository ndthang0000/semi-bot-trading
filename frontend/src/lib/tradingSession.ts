export type TradingSession = {
  key: "asian" | "london" | "london_ny" | "new_york" | "off_hours";
  label: string;
  startUtc: string;
  endUtc: string;
  badgeClass: string;
  textClass: string;
  dotClass: string;
};

const SESSIONS: Array<TradingSession & { startMinute: number; endMinute: number }> = [
  { key: "asian", label: "Asian", startUtc: "00:00", endUtc: "07:00", startMinute: 0, endMinute: 420,
    badgeClass: "border-indigo-400/30 bg-indigo-400/10 text-indigo-200", textClass: "text-indigo-300", dotClass: "bg-indigo-300" },
  { key: "london", label: "London", startUtc: "07:00", endUtc: "12:00", startMinute: 420, endMinute: 720,
    badgeClass: "border-cyan-400/30 bg-cyan-400/10 text-cyan-200", textClass: "text-cyan-300", dotClass: "bg-cyan-300" },
  { key: "london_ny", label: "London–NY", startUtc: "12:00", endUtc: "17:00", startMinute: 720, endMinute: 1020,
    badgeClass: "border-amber-400/30 bg-amber-400/10 text-amber-200", textClass: "text-amber-300", dotClass: "bg-amber-300" },
  { key: "new_york", label: "New York", startUtc: "17:00", endUtc: "21:00", startMinute: 1020, endMinute: 1260,
    badgeClass: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200", textClass: "text-emerald-300", dotClass: "bg-emerald-300" },
  { key: "off_hours", label: "Off-hours", startUtc: "21:00", endUtc: "24:00", startMinute: 1260, endMinute: 1440,
    badgeClass: "border-slate-500/30 bg-slate-500/10 text-slate-300", textClass: "text-slate-400", dotClass: "bg-slate-400" },
];

export function tradingSessionAt(now: Date): TradingSession {
  const minute = now.getUTCHours() * 60 + now.getUTCMinutes();
  const session = SESSIONS.find(item => minute >= item.startMinute && minute < item.endMinute) ?? SESSIONS[4];
  const { startMinute: _startMinute, endMinute: _endMinute, ...result } = session;
  return result;
}

export function formatUtcClock(now: Date): string {
  return `${String(now.getUTCHours()).padStart(2, "0")}:${String(now.getUTCMinutes()).padStart(2, "0")}`;
}
