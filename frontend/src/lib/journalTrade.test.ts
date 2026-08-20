import { describe, expect, it } from "vitest";
import { firstTakeProfitPrice, takeProfitPrices, tradeLifecycleStatus } from "./journalTrade";

describe("takeProfitPrices", () => {
  it("normalizes numeric and object-shaped targets", () => {
    const trade = { take_profit: [3040, { price: 3060 }, {}] };
    expect(takeProfitPrices(trade)).toEqual([3040, 3060]);
    expect(firstTakeProfitPrice(trade)).toBe(3040);
  });

  it("returns null when a trade has no usable target", () => {
    expect(firstTakeProfitPrice({ take_profit: [] })).toBeNull();
  });
});

describe("tradeLifecycleStatus", () => {
  it("does not call an expired Manual AI limit open", () => {
    expect(tradeLifecycleStatus({
      status: "cancelled",
      closed_at: "2026-08-14T05:02:31+00:00",
      pnl_r: null,
      manual_ai_plan_status: "expired",
      manual_ai_expires_at: "2026-08-14T05:02:29+00:00",
    })).toBe("expired");
  });

  it("treats broker-side cancellation near the configured expiry as expired", () => {
    expect(tradeLifecycleStatus({
      status: "cancelled",
      closed_at: "2026-08-14T05:02:01+00:00",
      pnl_r: null,
      manual_ai_plan_status: "cancelled",
      manual_ai_expires_at: "2026-08-14T05:02:29+00:00",
    })).toBe("expired");
  });

  it("distinguishes pending limits from filled positions", () => {
    expect(tradeLifecycleStatus({ status: "pending_fill", closed_at: null, pnl_r: null, manual_ai_plan_status: "armed", manual_ai_expires_at: null })).toBe("pending");
    expect(tradeLifecycleStatus({ status: "filled", closed_at: null, pnl_r: null, manual_ai_plan_status: "filled", manual_ai_expires_at: null })).toBe("open");
  });

  it("keeps cancelled and closed executions separate", () => {
    expect(tradeLifecycleStatus({ status: "cancelled", closed_at: "2026-08-14T05:02:31+00:00", pnl_r: null, manual_ai_plan_status: "cancelled", manual_ai_expires_at: "2026-08-14T09:02:31+00:00" })).toBe("cancelled");
    expect(tradeLifecycleStatus({ status: "closed", closed_at: "2026-08-14T12:00:14+00:00", pnl_r: -1, manual_ai_plan_status: "filled", manual_ai_expires_at: null })).toBe("closed");
  });
});
