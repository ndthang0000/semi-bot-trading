import { describe, expect, it } from "vitest";
import { normalizeZoneImportEnvelope } from "./zoneImport";

const baseEnvelope = {
  as_of: "2026-07-31T20:45:00+00:00",
  duplicate_audit: { safe_to_import: true, skipped: [] },
  api_payloads: [{ zone_type: "support" }],
};

describe("normalizeZoneImportEnvelope", () => {
  it("accepts the current bulk import endpoint", () => {
    const result = normalizeZoneImportEnvelope({
      ...baseEnvelope,
      api_endpoint: "POST /api/zones/import",
    });

    expect(result?.api_endpoint).toBe("POST /api/zones/import");
  });

  it("upgrades the legacy weekly-plan endpoint", () => {
    const result = normalizeZoneImportEnvelope({
      ...baseEnvelope,
      api_endpoint: "POST /api/zones",
    });

    expect(result?.api_endpoint).toBe("POST /api/zones/import");
  });

  it("rejects unsafe or empty plans", () => {
    expect(normalizeZoneImportEnvelope({
      ...baseEnvelope,
      duplicate_audit: { safe_to_import: false, skipped: [] },
      api_endpoint: "POST /api/zones/import",
    })).toBeNull();
    expect(normalizeZoneImportEnvelope({
      ...baseEnvelope,
      api_endpoint: "POST /api/zones/import",
      api_payloads: [],
    })).toBeNull();
  });
});
