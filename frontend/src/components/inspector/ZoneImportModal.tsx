import { X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { importZones, type ZoneImportResult } from "../../api/chart";
import { normalizeZoneImportEnvelope } from "../../lib/zoneImport";
import { MysticImportIcon } from "./MysticImportIcon";

export function ZoneImportModal({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: (result: ZoneImportResult) => void;
}) {
  const [jsonText, setJsonText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const parsedCount = useMemo(() => payloadCount(jsonText), [jsonText]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || isImporting) return;
      event.preventDefault();
      onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isImporting, onClose]);

  const submit = async () => {
    setError(null);
    let input: unknown;
    try {
      input = JSON.parse(jsonText);
    } catch (parseError) {
      setError(parseError instanceof Error ? `JSON không hợp lệ: ${parseError.message}` : "JSON không hợp lệ.");
      return;
    }
    const normalizedInput = normalizeZoneImportEnvelope(input);
    if (!normalizedInput) {
      setError("JSON phải là output API-ready của plan-xauusd-weekly và chứa api_payloads không rỗng.");
      return;
    }

    setIsImporting(true);
    try {
      const result = await importZones(normalizedInput);
      onImported(result);
    } catch (importError) {
      setError(importError instanceof Error ? importError.message : "Không thể import zone.");
    } finally {
      setIsImporting(false);
    }
  };

  return createPortal(
    <div
      className="fixed inset-0 z-[110] grid place-items-center bg-black/65 p-4 backdrop-blur-sm"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !isImporting) onClose();
      }}
    >
      <section
        aria-labelledby="zone-import-title"
        aria-modal="true"
        className="flex max-h-[86vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-ink-700 bg-ink-900 shadow-2xl shadow-black/50"
        role="dialog"
      >
        <header className="flex items-start justify-between gap-4 border-b border-ink-700 bg-ink-950 px-5 py-4">
          <div className="flex min-w-0 items-start gap-3">
            <div className="rounded-xl border border-sky-300/35 bg-gradient-to-br from-blue-500/25 via-sky-400/15 to-cyan-300/10 p-2.5 text-sky-200 shadow-[0_0_24px_rgba(37,99,235,0.2),inset_0_0_18px_rgba(56,189,248,0.08)]">
              <MysticImportIcon size={21} />
            </div>
            <div>
              <h2 id="zone-import-title" className="text-sm font-semibold text-slate-100">Import zones từ JSON</h2>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">
                Paste nguyên khối API-ready JSON do skill plan-xauusd-weekly tạo ra.
              </p>
            </div>
          </div>
          <button
            aria-label="Đóng modal import"
            className="rounded-md p-1.5 text-slate-500 transition hover:bg-ink-800 hover:text-slate-100 disabled:opacity-40"
            disabled={isImporting}
            type="button"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col gap-3 p-5">
          <label className="flex min-h-0 flex-1 flex-col gap-2">
            <span className="flex items-center justify-between text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
              JSON payload
              {parsedCount !== null ? <span className="normal-case tracking-normal text-cyan-300">{parsedCount} zone</span> : null}
            </span>
            <textarea
              autoFocus
              className="min-h-[320px] w-full flex-1 resize-y rounded-lg border border-ink-700 bg-ink-950 p-3 font-mono text-xs leading-relaxed text-slate-200 outline-none placeholder:text-slate-700 focus:border-cyan-400"
              placeholder={'{\n  "as_of": "...",\n  "duplicate_audit": { "safe_to_import": true, "skipped": [] },\n  "api_endpoint": "POST /api/zones/import",\n  "api_payloads": [ ... ]\n}'}
              spellCheck={false}
              value={jsonText}
              onChange={(event) => {
                setJsonText(event.target.value);
                setError(null);
              }}
            />
          </label>

          {error ? (
            <div className="rounded-md border border-rose-400/40 bg-rose-400/10 px-3 py-2 text-xs leading-relaxed text-rose-100">
              {error}
            </div>
          ) : (
            <div className="text-xs leading-relaxed text-slate-500">
              Import là atomic: nếu một zone sai hoặc trùng DB thì toàn bộ request sẽ bị từ chối. Support/resistance được tạo ở trạng thái draft.
            </div>
          )}
        </div>

        <footer className="flex items-center justify-end gap-2 border-t border-ink-700 bg-ink-950 px-5 py-4">
          <button
            className="rounded-md border border-ink-700 px-4 py-2 text-xs font-semibold text-slate-300 transition hover:border-slate-600 hover:text-white disabled:opacity-40"
            disabled={isImporting}
            type="button"
            onClick={onClose}
          >
            Hủy
          </button>
          <button
            className="inline-flex items-center gap-2 rounded-md border border-sky-300/45 bg-gradient-to-r from-blue-600/35 via-sky-500/25 to-cyan-400/20 px-4 py-2 text-xs font-semibold text-sky-100 shadow-[0_0_20px_rgba(37,99,235,0.16)] transition hover:border-cyan-200/60 hover:shadow-[0_0_24px_rgba(56,189,248,0.24)] disabled:cursor-not-allowed disabled:opacity-40"
            disabled={isImporting || jsonText.trim().length === 0}
            type="button"
            onClick={() => void submit()}
          >
            <MysticImportIcon size={15} />
            {isImporting ? "Đang import…" : "Import zones"}
          </button>
        </footer>
      </section>
    </div>,
    document.body,
  );
}

function payloadCount(text: string): number | null {
  if (!text.trim()) return null;
  try {
    const value: unknown = JSON.parse(text);
    if (!value || typeof value !== "object" || !("api_payloads" in value)) return null;
    const payloads = (value as { api_payloads?: unknown }).api_payloads;
    return Array.isArray(payloads) ? payloads.length : null;
  } catch {
    return null;
  }
}
