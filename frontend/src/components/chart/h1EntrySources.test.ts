import { describe, expect, it } from "vitest";
import { canonicalH1EntrySource, h1EntrySourceKind } from "./h1EntrySources";

describe("H1 impulse entry sources", () => {
  it.each([
    ["previous_h1_low", "previous_h1_low"],
    ["fib_0.5_min_stop_fallback", "fib_0.5"],
    ["fib_0.5_then_atr_1.2_cap", "max_stop_atr"],
    ["atr_1.2_max_stop_cap", "max_stop_atr"],
  ])("maps strategy source %s to quick source %s", (source, expected) => {
    expect(canonicalH1EntrySource(source)).toBe(expected);
  });

  it.each([
    ["previous_h1_high", "previous"],
    ["fib_0.618", "fibonacci"],
    ["min_stop_atr", "minimum"],
    ["atr_1.2_max_stop_cap", "maximum"],
    ["human_custom", "custom"],
  ])("classifies %s as %s", (source, expected) => {
    expect(h1EntrySourceKind(source)).toBe(expected);
  });
});
