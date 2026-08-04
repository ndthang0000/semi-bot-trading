import { ChevronDown, ChevronUp, X } from "lucide-react";
import { useEffect } from "react";

type MobileBottomSheetProps = {
  children: React.ReactNode;
  expanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
  onClose: () => void;
  open: boolean;
  title: string;
};

export function MobileBottomSheet({
  children,
  expanded = false,
  onExpandedChange,
  onClose,
  open,
  title,
}: MobileBottomSheetProps) {
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[90] lg:hidden" role="dialog" aria-modal="true" aria-label={title}>
      <button
        aria-label="Dismiss panel"
        className="absolute inset-0 bg-black/55 backdrop-blur-[1px]"
        type="button"
        onClick={onClose}
      />
      <section
        className={`absolute inset-x-0 bottom-0 flex flex-col overflow-hidden rounded-t-2xl border-t border-ink-600 bg-ink-900 shadow-[0_-18px_50px_rgba(0,0,0,0.48)] transition-[height] duration-200 ${
          expanded ? "h-[calc(100dvh-2.5rem)]" : "h-[min(64dvh,36rem)]"
        }`}
      >
        <div className="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-slate-600" />
        <div className="flex h-12 shrink-0 items-center justify-between border-b border-ink-700 px-4">
          <h2 className="truncate text-sm font-semibold text-slate-100">{title}</h2>
          <div className="flex items-center gap-1">
            {onExpandedChange ? (
              <button
                aria-label={expanded ? "Collapse panel" : "Expand panel"}
                className="grid h-10 w-10 place-items-center rounded-lg text-slate-400 active:bg-ink-700"
                type="button"
                onClick={() => onExpandedChange(!expanded)}
              >
                {expanded ? <ChevronDown size={20} /> : <ChevronUp size={20} />}
              </button>
            ) : null}
            <button
              aria-label="Close panel"
              className="grid h-10 w-10 place-items-center rounded-lg text-slate-400 active:bg-ink-700"
              type="button"
              onClick={onClose}
            >
              <X size={20} />
            </button>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain pb-[max(1rem,env(safe-area-inset-bottom))]">
          {children}
        </div>
      </section>
    </div>
  );
}
