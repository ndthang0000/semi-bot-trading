import { describe, expect, it } from "vitest";
import { formatUtcClock, tradingSessionAt } from "./tradingSession";

describe("tradingSessionAt", () => {
  it.each([
    ["2026-09-12T00:00:00Z", "asian"],
    ["2026-09-12T06:59:00Z", "asian"],
    ["2026-09-12T07:00:00Z", "london"],
    ["2026-09-12T12:00:00Z", "london_ny"],
    ["2026-09-12T17:00:00Z", "new_york"],
    ["2026-09-12T21:00:00Z", "off_hours"],
    ["2026-09-12T23:59:00Z", "off_hours"],
  ])("maps %s to %s", (iso, expected) => {
    expect(tradingSessionAt(new Date(iso)).key).toBe(expected);
  });

  it("formats the UTC clock without using the browser timezone", () => {
    expect(formatUtcClock(new Date("2026-09-12T07:05:00+00:00"))).toBe("07:05");
  });
});
