const DAY_MS = 86_400_000;
const VIETNAM_DATE_FORMATTER = new Intl.DateTimeFormat("en", {
  timeZone: "Asia/Ho_Chi_Minh",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

export function parseDateKey(dateKey: string): Date {
  const [year, month, day] = dateKey.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

export function dateKey(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function addDaysToDateKey(value: string, days: number): string {
  return dateKey(new Date(parseDateKey(value).getTime() + days * DAY_MS));
}

export function weekStartForDateKey(value: string): string {
  const date = parseDateKey(value);
  const mondayOffset = (date.getUTCDay() + 6) % 7;
  return addDaysToDateKey(value, -mondayOffset);
}

export function currentVietnamDateKey(now = new Date()): string {
  const parts = VIETNAM_DATE_FORMATTER.formatToParts(now).reduce(
    (result, part) => {
      if (part.type === "year" || part.type === "month" || part.type === "day") {
        result[part.type] = part.value;
      }
      return result;
    },
    {} as Record<string, string>,
  );
  return `${parts.year}-${parts.month}-${parts.day}`;
}

export function currentVietnamWeekStart(now = new Date()): string {
  return weekStartForDateKey(currentVietnamDateKey(now));
}

export function formatWeekRange(weekStart: string): string {
  const formatter = new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "UTC",
  });
  return `${formatter.format(parseDateKey(weekStart))} – ${formatter.format(parseDateKey(addDaysToDateKey(weekStart, 6)))}`;
}

export function plainTextToRichText(value: string): string {
  if (!value) return "<p></p>";
  return value
    .split(/\n{2,}/)
    .map((paragraph) => `<p>${escapeHtml(paragraph).replace(/\n/g, "<br>")}</p>`)
    .join("");
}

export function richTextToPlainText(value: string): string {
  const withBreaks = value
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|h[1-6]|li|blockquote|pre)>/gi, "\n")
    .replace(/<li[^>]*>/gi, "• ")
    .replace(/<[^>]+>/g, "");
  return decodeBasicEntities(withBreaks)
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function decodeBasicEntities(value: string): string {
  return value
    .replace(/&nbsp;/g, " ")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&");
}
