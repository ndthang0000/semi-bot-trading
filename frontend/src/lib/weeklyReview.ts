import type { TradeOrder, TradeReview } from "../types";

const HCM_OFFSET_MS = 7 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;
const SATURDAY_REVIEW_START_MS = 12 * 60 * 60 * 1000;

export type WeeklyReviewGateState = {
  active: boolean;
  dueTrades: TradeOrder[];
  dueTradeIds: Set<string>;
  dueCount: number;
  oldestClosedAt: string | null;
  currentWeekDue: boolean;
};

export function buildWeeklyReviewGate(trades: TradeOrder[], now: Date = new Date()): WeeklyReviewGateState {
  const nowDay = hcmDayNumber(now);
  const nowWeekStart = hcmWeekStartDay(nowDay);
  const nowWeekday = hcmWeekday(nowDay);
  const currentWeekDue = nowWeekday > 5
    || (nowWeekday === 5 && hcmTimeOfDayMs(now) >= SATURDAY_REVIEW_START_MS);

  const dueTrades = trades
    .filter((trade) => trade.closed_at && trade.pnl_r !== null && !isTradeReviewComplete(trade.review ?? null))
    .filter((trade) => {
      const closedDay = hcmDayNumber(new Date(trade.closed_at!));
      if (closedDay < nowWeekStart) return true;
      return currentWeekDue && closedDay >= nowWeekStart && closedDay <= nowDay;
    })
    .sort((a, b) => String(a.closed_at).localeCompare(String(b.closed_at)));

  return {
    active: dueTrades.length > 0,
    dueTrades,
    dueTradeIds: new Set(dueTrades.map((trade) => trade.id)),
    dueCount: dueTrades.length,
    oldestClosedAt: dueTrades[0]?.closed_at ?? null,
    currentWeekDue,
  };
}

export function isTradeReviewComplete(review: TradeReview | null | undefined): boolean {
  if (!review) return false;
  if (review.grade) return true;
  if (review.strategy_review?.setup_validity) return true;
  if (review.operator_review?.followed_plan) return true;
  const verdictCompletes = ["good_trade", "bad_trade", "should_skip"].includes(review.verdict);
  return verdictCompletes && review.comment.trim().length > 0;
}

function hcmDayNumber(date: Date): number {
  return Math.floor((date.getTime() + HCM_OFFSET_MS) / DAY_MS);
}

function hcmTimeOfDayMs(date: Date): number {
  return (date.getTime() + HCM_OFFSET_MS) % DAY_MS;
}

function hcmWeekStartDay(dayNumber: number): number {
  return dayNumber - hcmWeekday(dayNumber);
}

function hcmWeekday(dayNumber: number): number {
  return (dayNumber + 3) % 7; // 1970-01-01 was Thursday, so Mon=0.
}
