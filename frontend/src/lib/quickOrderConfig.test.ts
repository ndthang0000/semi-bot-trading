import { describe, expect, it } from "vitest";
import { DEFAULT_LIMIT_EXPIRY_MINUTES, quickOrderAccountLabels } from "./quickOrderConfig";

describe("Quick Order configuration", () => {
  it("defaults Limit orders to eight hours", () => {
    expect(DEFAULT_LIMIT_EXPIRY_MINUTES).toBe(480);
  });

  it("excludes FTMO accounts without hiding other workers", () => {
    expect(quickOrderAccountLabels([
      "Exness Personal",
      "FTMO 100K 2-Step",
      "Backup FTMO Challenge",
    ])).toEqual(["Exness Personal"]);
  });
});
