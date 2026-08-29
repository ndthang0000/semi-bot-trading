export function accountBadgeClass(accountLabel: string): string {
  const normalized = accountLabel.toLowerCase();
  if (normalized.includes("exness")) {
    return "border-amber-300/35 bg-amber-400/15 text-amber-200 shadow-[0_0_10px_rgba(251,191,36,0.10)]";
  }
  if (normalized.includes("ftmo")) {
    return "border-indigo-400/30 bg-gradient-to-r from-slate-950 via-blue-950 to-indigo-950 text-cyan-200 shadow-[0_0_12px_rgba(56,189,248,0.14)]";
  }
  return "border-slate-600/40 bg-slate-700/45 text-slate-300";
}
