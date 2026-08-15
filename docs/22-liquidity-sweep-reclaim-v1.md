# Liquidity Sweep Reclaim V1

`liquidity_sweep_reclaim_v1` is a LIVE quote-driven playbook. Version 1 trades
only **Zone Buy liquidity**: an H1 `liquidity_pool` with `direction=bullish` and
an explicit `metadata.trade_modes` entry of `liquidity_sweep`.

Existing liquidity zones are inert unless a human explicitly enables this mode.
The playbook does not participate in M15 backtest because M15 OHLC cannot prove
the intrabar order of sweep, breakout, and reclaim events.

## MVP zone source

V1 deliberately has no automatic pre-sweep candidate detector. Actionable zones
come from the weekly AI plan, are reviewed by a human, then imported as active
zones. The planner proposes at most three unswept H1 candidates built from at
least two nearby confirmed lows and emits this exact routing contract:

```text
type = liquidity_pool
direction = bullish
status = active
metadata.add_entity_kind = buy_side_liquidity
metadata.trade_modes = ["liquidity_sweep"]
```

Rows produced by detector `liquidity_v1` are different: they are retrospective
`status=swept` evidence named **Historical Liquidity Sweep**. They remain in the
database for research/replay and are hidden from the chart/list while Liquidity
Sweep V1 is selected. They are never armed by the LIVE playbook.

## State and price rules

- Bid touching `price_low` snapshots ATR(14) M15 and starts a 15-minute timer.
- `invalidation_price = price_low - 2 * ATR_M15_at_touch`.
- Bid exactly at the invalidation price is allowed; strictly below it is a true
  breakout and permanently invalidates this zone event for that account.
- Ask must reach `price_high` before the deadline to create a market Buy.
- While Ask remains/re-enters above `price_high`, the same stable candidate is
  re-emitted until the deadline. This lets temporary news/spread/risk guards
  retry safely; an accepted execution request still deduplicates the order.
- The deadline is exclusive: reclaim exactly 15 minutes after touch is timed out.
- Invalidated, timed-out, and consumed states do not rearm. A reclaimed state
  may re-emit its stable candidate only before the original deadline. Editing
  the zone creates a new geometry version and therefore starts a fresh event.

Stop and target:

```text
SL = deepest observed Bid - max(current spread, 0.2 * ATR snapshot)
TP = entry + 2.5 * (entry - SL)
```

State is stored per `(zone_id, account_label)` because broker quotes differ;
the Zone inspector exposes every account state instead of only the latest worker.
The existing news, spread, weekend, risk sizing, daily loss, max-position and
partial-TP execution guards remain in force.

## Config

```toml
[strategy.playbooks.liquidity_sweep_reclaim_v1]
enabled = true
timeout_minutes = 15
max_sweep_atr = 2.0
sl_buffer_atr = 0.2
rr = 2.5
```
