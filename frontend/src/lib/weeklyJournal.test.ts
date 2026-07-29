import { describe, expect, it } from "vitest";
import {
  addDaysToDateKey,
  currentVietnamWeekStart,
  plainTextToRichText,
  richTextToPlainText,
  weekStartForDateKey,
} from "./weeklyJournal";

describe("weekly journal date helpers", () => {
  it("maps any day in a historical week to Monday", () => {
    expect(weekStartForDateKey("2026-07-27")).toBe("2026-07-27");
    expect(weekStartForDateKey("2026-07-29")).toBe("2026-07-27");
    expect(weekStartForDateKey("2026-08-02")).toBe("2026-07-27");
  });

  it("moves cleanly between weeks and across months", () => {
    expect(addDaysToDateKey("2026-07-27", -7)).toBe("2026-07-20");
    expect(addDaysToDateKey("2026-07-27", 7)).toBe("2026-08-03");
  });

  it("uses the Vietnam calendar day when finding the current week", () => {
    expect(currentVietnamWeekStart(new Date("2026-07-26T18:30:00Z"))).toBe("2026-07-27");
  });

  it("upgrades legacy plain text without interpreting it as HTML", () => {
    const html = plainTextToRichText("Kỷ luật < cảm xúc\nKhông FOMO");
    expect(html).toBe("<p>Kỷ luật &lt; cảm xúc<br>Không FOMO</p>");
    expect(richTextToPlainText(html)).toBe("Kỷ luật < cảm xúc\nKhông FOMO");
  });
});
