import { describe, expect, it } from "vitest";
import { accountBadgeClass } from "./accountPresentation";

describe("account presentation", () => {
  it("keeps the Journal colors for Exness and FTMO accounts", () => {
    expect(accountBadgeClass("Exness Personal")).toContain("amber");
    expect(accountBadgeClass("FTMO 100K 2-Step")).toContain("indigo");
  });

  it("uses a neutral style for unknown accounts", () => {
    expect(accountBadgeClass("Default")).toContain("slate");
  });
});
