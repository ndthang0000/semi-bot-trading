import type { ZoneImportEnvelope } from "../api/chart";

const CURRENT_IMPORT_ENDPOINT = "POST /api/zones/import";
const LEGACY_IMPORT_ENDPOINT = "POST /api/zones";

export function normalizeZoneImportEnvelope(value: unknown): ZoneImportEnvelope | null {
  if (!value || typeof value !== "object") return null;
  const envelope = value as Record<string, unknown>;
  const duplicateAudit = envelope.duplicate_audit;
  const payloads = envelope.api_payloads;
  const endpoint = envelope.api_endpoint;
  if (
    typeof envelope.as_of !== "string"
    || !duplicateAudit
    || typeof duplicateAudit !== "object"
    || (duplicateAudit as { safe_to_import?: unknown }).safe_to_import !== true
    || !Array.isArray(payloads)
    || payloads.length === 0
    || (endpoint !== CURRENT_IMPORT_ENDPOINT && endpoint !== LEGACY_IMPORT_ENDPOINT)
  ) {
    return null;
  }
  return {
    ...(envelope as unknown as ZoneImportEnvelope),
    api_endpoint: CURRENT_IMPORT_ENDPOINT,
  };
}
