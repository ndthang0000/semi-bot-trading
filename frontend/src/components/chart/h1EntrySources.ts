export type H1EntrySourceKind = "previous" | "fibonacci" | "minimum" | "maximum" | "custom";

export function canonicalH1EntrySource(source: string): string {
  if (source === "fib_0.5_min_stop_fallback") return "fib_0.5";
  if (["fib_0.5_then_atr_1.2_cap", "atr_1.2_max_stop_cap", "max_risk_cap"].includes(source)) {
    return "max_stop_atr";
  }
  return source;
}

export function h1EntrySourceKind(source: string): H1EntrySourceKind {
  const canonicalSource = canonicalH1EntrySource(source);
  if (canonicalSource.startsWith("previous_h1_")) return "previous";
  if (canonicalSource.startsWith("fib_")) return "fibonacci";
  if (canonicalSource === "min_stop_atr") return "minimum";
  if (canonicalSource === "max_stop_atr") return "maximum";
  return "custom";
}
