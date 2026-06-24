/**
 * NewsWidget — surfaces economic news events in two ways:
 *
 * 1. A compact pill in the TopBar that appears when a tier-1/2 event is
 *    within 2 hours. Clicking it opens a dropdown with the week's schedule.
 *
 * 2. A full-width banner (rendered above the main content in App.tsx) that
 *    appears only during an active blackout window.
 *
 * Both are invisible when no relevant news is imminent — no clutter.
 */

import { useEffect, useRef, useState } from "react";
import type { NewsEvent, NewsResponse } from "../api/chart";
import { fetchNews } from "../api/chart";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatMinutes(minutes: number): string {
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function formatTime(isoString: string): string {
  const d = new Date(isoString);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

function formatDate(isoString: string): string {
  const d = new Date(isoString);
  const today = new Date();
  const tomorrow = new Date(today);
  tomorrow.setDate(tomorrow.getDate() + 1);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === tomorrow.toDateString()) return "Tomorrow";
  return d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

type TierStyle = { dot: string; badge: string; text: string };
const TIER_STYLE: Record<number, TierStyle> = {
  1: { dot: "bg-red-500", badge: "bg-red-500/15 text-red-300 border-red-500/40", text: "text-red-300" },
  2: { dot: "bg-red-400", badge: "bg-red-400/10 text-red-300/80 border-red-400/30", text: "text-red-300/80" },
};

// ---------------------------------------------------------------------------
// Blackout Banner — full-width strip shown during active blackout
// ---------------------------------------------------------------------------

type BlackoutBannerProps = { event: NewsEvent };

export function BlackoutBanner({ event }: BlackoutBannerProps) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 10_000);
    return () => clearInterval(id);
  }, []);

  const resumes = new Date(event.blackout_until);
  const minsLeft = Math.max(0, Math.round((resumes.getTime() - now) / 60_000));
  const resumeStr = minsLeft <= 0 ? "shortly" : `in ${formatMinutes(minsLeft)}`;
  const tier = event.tier as 1 | 2;
  const label = tier === 1 ? "🔴🔴" : "🔴";

  return (
    <div className="flex h-8 shrink-0 items-center justify-center gap-3 bg-red-950/70 px-4 text-xs text-red-200 border-b border-red-800/50">
      <span className="font-semibold tracking-wide uppercase">⛔ Trading paused</span>
      <span className="text-red-400">·</span>
      <span>{label} {event.title}</span>
      <span className="text-red-400">·</span>
      <span className="text-red-300/70">Resumes {resumeStr}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// News Pill — compact button in the TopBar
// ---------------------------------------------------------------------------

type NewsPillProps = { data: NewsResponse };

export function NewsPill({ data }: NewsPillProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", handler);
    return () => window.removeEventListener("pointerdown", handler);
  }, [open]);

  // Find the next upcoming event (soonest, not yet blackout-expired)
  const next = data.events[0] ?? null;
  if (!next) return null;

  // Only show pill when event is within 2 hours
  if (next.minutes_until > 120) return null;

  const tier = next.tier as 1 | 2;
  const style = TIER_STYLE[tier];

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        className={`inline-flex h-9 items-center gap-1.5 rounded-md border px-3 text-xs font-medium transition ${
          open
            ? "border-red-500/60 bg-red-500/10 text-red-200"
            : "border-red-800/60 bg-red-950/40 text-red-300 hover:border-red-600/60"
        }`}
        title="Upcoming high-impact news"
        onClick={() => setOpen((v) => !v)}
      >
        <span className={`h-1.5 w-1.5 rounded-full ${style.dot} ${next.is_active_blackout ? "animate-pulse" : ""}`} />
        <span className="max-w-[120px] truncate">{next.title}</span>
        <span className="tabular-nums text-red-400/80">
          {next.is_active_blackout ? "LIVE" : formatMinutes(next.minutes_until)}
        </span>
      </button>

      {open && (
        <div className="absolute right-0 top-11 z-50 w-80 rounded-md border border-ink-700 bg-ink-900 shadow-2xl shadow-black/50">
          <NewsDropdown events={data.events} onClose={() => setOpen(false)} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dropdown schedule
// ---------------------------------------------------------------------------

type NewsDropdownProps = { events: NewsEvent[]; onClose: () => void };

function NewsDropdown({ events }: NewsDropdownProps) {
  // Group by calendar day
  const grouped = new Map<string, NewsEvent[]>();
  for (const ev of events) {
    const day = formatDate(ev.scheduled_at);
    if (!grouped.has(day)) grouped.set(day, []);
    grouped.get(day)!.push(ev);
  }

  if (events.length === 0) {
    return (
      <div className="px-4 py-5 text-center text-xs text-slate-500">
        No high-impact events in the next 48 hours
      </div>
    );
  }

  return (
    <div className="max-h-80 overflow-y-auto py-2">
      <div className="px-3 pb-1.5 pt-1 text-[10px] font-semibold uppercase tracking-widest text-slate-500">
        Upcoming News · XAUUSD
      </div>
      {Array.from(grouped.entries()).map(([day, dayEvents]) => (
        <div key={day}>
          <div className="px-3 py-1 text-[10px] font-medium uppercase tracking-wider text-slate-600">
            {day}
          </div>
          {dayEvents.map((ev) => {
            const tier = ev.tier as 1 | 2;
            const style = TIER_STYLE[tier];
            return (
              <div
                key={ev.id}
                className={`mx-2 mb-0.5 flex items-center gap-2.5 rounded px-2 py-1.5 ${
                  ev.is_active_blackout ? "bg-red-950/50" : "hover:bg-ink-800/60"
                }`}
              >
                <span className={`mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full ${style.dot} ${ev.is_active_blackout ? "animate-pulse" : ""}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className={`truncate text-xs font-medium ${style.text}`}>{ev.title}</span>
                    {ev.is_active_blackout && (
                      <span className="shrink-0 rounded bg-red-500/20 px-1 py-0.5 text-[9px] font-semibold uppercase text-red-300">
                        Active
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-[10px] text-slate-500">
                    <span>{formatTime(ev.scheduled_at)}</span>
                    <span>·</span>
                    <span>±{ev.blackout_before_min}/{ev.blackout_after_min}m blackout</span>
                    {ev.forecast && (
                      <>
                        <span>·</span>
                        <span>F: {ev.forecast}</span>
                      </>
                    )}
                  </div>
                </div>
                <span className={`shrink-0 tabular-nums text-[10px] font-medium ${style.text}`}>
                  {ev.is_active_blackout ? "NOW" : formatMinutes(ev.minutes_until)}
                </span>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Hook — polls /api/news every 60 s; returns null until first load
// ---------------------------------------------------------------------------

export function useNewsData(): NewsResponse | null {
  const [data, setData] = useState<NewsResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const result = await fetchNews(48);
        if (!cancelled) setData(result);
      } catch {
        // silently ignore — news widget is non-critical
      }
    };
    load();
    const id = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return data;
}
