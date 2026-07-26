import type { TradeOrder } from "../types";

export type CalmOutcome = "win" | "loss";

export type CalmTradeEvent = {
  id: string;
  groupKey: string;
  outcome: CalmOutcome;
  pnlR: number;
  closedAt: string;
  tradeIds: string[];
  accountLabels: string[];
};

export type CalmMessageDeckState = {
  remaining: number[];
  lastIndex: number | null;
};

export const WIN_MESSAGES = [
  "Một lệnh thắng không làm xác suất của setup tiếp theo cao hơn.",
  "Thị trường không biết bạn vừa thắng.",
  "Profit là kết quả; tuân thủ quy trình mới là kỹ năng.",
  "Bạn không cần trả lại thị trường số tiền vừa kiếm được.",
  "Đừng tăng risk chỉ vì quyết định vừa rồi đúng.",
  "Một kết quả tốt không biến một setup kém thành setup tốt.",
  "Trade tốt nhất tiếp theo có thể là không làm gì.",
  "Giữ được lợi nhuận cũng là một phần của chiến thắng.",
  "Hãy đánh giá setup tiếp theo từ đầu, không dựa trên cảm giác đang thắng.",
  "Bạn đã hoàn thành trade này. Không cần chứng minh thêm điều gì với thị trường.",
] as const;

export const LOSS_MESSAGES = [
  "Trade tiếp theo không có trách nhiệm bù lại trade vừa rồi.",
  "Một lệnh thua đúng quy trình chỉ là chi phí của hệ thống.",
  "Bạn không cần lấy lại khoản lỗ ngay từ chính thị trường này.",
  "SL đã hoàn thành nhiệm vụ bảo vệ tài khoản.",
  "Một sample không đủ để kết luận strategy đã sai.",
  "Không vào lệnh cũng là một quyết định hợp lệ.",
  "Cảm giác muốn gỡ không phải là tín hiệu giao dịch.",
  "Một setup đúng quy trình vẫn có quyền thua.",
  "Khoản lỗ đã kết thúc; đừng để nó quyết định trade tiếp theo.",
  "Mục tiêu hiện tại không phải kiếm lại tiền, mà là lấy lại trạng thái bình tĩnh.",
] as const;

const MESSAGE_DECK_STORAGE_KEY = "calm-reset-message-decks-v1";
const SEEN_TRADES_STORAGE_KEY = "calm-reset-seen-trades-v1";
const HANDLED_GROUPS_STORAGE_KEY = "calm-reset-handled-groups-v1";
const MAX_STORED_IDS = 1_000;

export function messagesForOutcome(outcome: CalmOutcome): readonly string[] {
  return outcome === "win" ? WIN_MESSAGES : LOSS_MESSAGES;
}

export function drawCalmMessage(outcome: CalmOutcome): string {
  const messages = messagesForOutcome(outcome);
  const storedDecks = readJson<Partial<Record<CalmOutcome, CalmMessageDeckState>>>(MESSAGE_DECK_STORAGE_KEY, {
    win: { remaining: [], lastIndex: null },
    loss: { remaining: [], lastIndex: null },
  });
  const decks: Record<CalmOutcome, CalmMessageDeckState> = {
    win: normalizeDeckState(storedDecks?.win),
    loss: normalizeDeckState(storedDecks?.loss),
  };
  const draw = drawMessageIndex(messages.length, decks[outcome]);
  decks[outcome] = draw.state;
  writeJson(MESSAGE_DECK_STORAGE_KEY, decks);
  return messages[draw.index];
}

export function drawMessageIndex(
  messageCount: number,
  state: CalmMessageDeckState,
  random: () => number = Math.random,
): { index: number; state: CalmMessageDeckState } {
  if (messageCount <= 0) {
    throw new Error("Calm Reset needs at least one message.");
  }
  let remaining = state.remaining.filter(
    (index, position, values) => index >= 0 && index < messageCount && values.indexOf(index) === position,
  );
  if (remaining.length === 0) {
    remaining = shuffledIndexes(messageCount, random);
    if (messageCount > 1 && remaining[0] === state.lastIndex) {
      [remaining[0], remaining[1]] = [remaining[1], remaining[0]];
    }
  }
  const index = remaining.shift()!;
  return {
    index,
    state: {
      remaining,
      lastIndex: index,
    },
  };
}

export function groupClosedTrades(trades: TradeOrder[]): CalmTradeEvent[] {
  const groups = new Map<string, TradeOrder[]>();
  for (const trade of trades) {
    if (trade.status !== "closed" || !trade.closed_at || !Number.isFinite(trade.pnl_r)) continue;
    const key = calmTradeGroupKey(trade);
    groups.set(key, [...(groups.get(key) ?? []), trade]);
  }
  return [...groups.entries()]
    .map(([groupKey, rows]) => {
      const pnlValues = rows.map((trade) => Number(trade.pnl_r));
      const pnlR = pnlValues.reduce((total, value) => total + value, 0) / pnlValues.length;
      const closedAt = rows
        .map((trade) => trade.closed_at!)
        .sort((left, right) => right.localeCompare(left))[0];
      return {
        id: `${groupKey}:${closedAt}`,
        groupKey,
        outcome: pnlR > 0 ? "win" as const : "loss" as const,
        pnlR,
        closedAt,
        tradeIds: rows.map((trade) => trade.id),
        accountLabels: [...new Set(rows.map((trade) => trade.account_label || "Default"))],
      };
    })
    .sort((left, right) => left.closedAt.localeCompare(right.closedAt));
}

export function calmTradeGroupKey(trade: TradeOrder): string {
  const candidateId = readMetadataString(trade.metadata, "candidate_id");
  if (candidateId) return `candidate:${candidateId}`;
  const nestedCandidateId = readMetadataString(trade.metadata, "id", "candidate_snapshot");
  if (nestedCandidateId) return `candidate:${nestedCandidateId}`;
  return `trade:${trade.id}`;
}

export function readSeenTradeIds(): Set<string> {
  return readStringSet(SEEN_TRADES_STORAGE_KEY);
}

export function storeSeenTradeIds(ids: Iterable<string>): void {
  writeJson(SEEN_TRADES_STORAGE_KEY, [...new Set(ids)].slice(-MAX_STORED_IDS));
}

export function readHandledGroupKeys(): Set<string> {
  return readStringSet(HANDLED_GROUPS_STORAGE_KEY);
}

export function storeHandledGroupKeys(keys: Iterable<string>): void {
  writeJson(HANDLED_GROUPS_STORAGE_KEY, [...new Set(keys)].slice(-MAX_STORED_IDS));
}

function shuffledIndexes(count: number, random: () => number): number[] {
  const values = Array.from({ length: count }, (_, index) => index);
  for (let index = values.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(random() * (index + 1));
    [values[index], values[swapIndex]] = [values[swapIndex], values[index]];
  }
  return values;
}

function normalizeDeckState(value: CalmMessageDeckState | undefined): CalmMessageDeckState {
  return {
    remaining: Array.isArray(value?.remaining)
      ? value.remaining.filter((index): index is number => typeof index === "number" && Number.isInteger(index))
      : [],
    lastIndex: typeof value?.lastIndex === "number" && Number.isInteger(value.lastIndex)
      ? value.lastIndex
      : null,
  };
}

function readStringSet(key: string): Set<string> {
  const values = readJson<unknown>(key, []);
  return new Set(
    Array.isArray(values)
      ? values.filter((value): value is string => typeof value === "string")
      : [],
  );
}

function readMetadataString(
  metadata: Record<string, unknown>,
  key: string,
  nestedKey?: string,
): string | null {
  const source = nestedKey && typeof metadata[nestedKey] === "object" && metadata[nestedKey] !== null
    ? metadata[nestedKey] as Record<string, unknown>
    : metadata;
  const value = source[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) as T : fallback;
  } catch {
    return fallback;
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Calm Reset is deliberately optional; unavailable storage must not affect trading UI.
  }
}
