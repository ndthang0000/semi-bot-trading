# Liquidity Sweep Reclaim V1

`liquidity_sweep_reclaim_v1` is a LIVE quote-driven, two-sided playbook:

- **Zone Buy liquidity**: H1 `liquidity_pool`, `direction=bullish`.
- **Zone Sell liquidity**: H1 `liquidity_pool`, `direction=bearish`.

Both require an explicit `metadata.trade_modes` entry of `liquidity_sweep`.
Existing liquidity zones remain inert until a human enables this mode. The
playbook does not participate in M15 backtest because M15 OHLC cannot prove the
intrabar order of sweep, breakout, and reclaim events.

## MVP zone source

V1 deliberately has no automatic pre-sweep candidate detector. Actionable zones
come from the weekly AI plan, are reviewed by a human, then imported as active
zones. The routing contract is:

```text
type = liquidity_pool
direction = bullish | bearish
status = active
metadata.add_entity_kind = buy_side_liquidity | sell_side_liquidity
metadata.trade_modes = ["liquidity_sweep"]
```

Rows produced by detector `liquidity_v1` are retrospective `status=swept`
evidence named **Historical Liquidity Sweep**. They remain in the database for
research/replay and are hidden from the chart/list while Liquidity Sweep V1 is
selected by default. The playbook menu exposes a research-only **Show historical
sweeps** toggle; enabling it also disables `Active zones only` so swept rows are
available to the chart. Historical rows are never armed by the LIVE playbook.

## Symmetric state machine

The same state machine handles both directions. Touch and reclaim must occur on
separate quote observations. The ATR snapshot and deadline never move after the
initial touch.

| Rule | Zone Buy liquidity / Long | Zone Sell liquidity / Short |
| --- | --- | --- |
| Start | Bid touches `price_low` | Ask touches `price_high` |
| Invalidation | Bid `< price_low - 1 × ATR` | Ask `> price_high + 1 × ATR` |
| Reclaim | Ask reaches `price_high` | Bid reaches `price_low` |
| Entry | Market Buy at current Ask | Market Sell at current Bid |
| Sweep extreme | Lowest observed Bid | Highest observed Ask |

An exact 1-ATR sweep is allowed; only a strict move beyond it is invalidated.
Reclaim must happen strictly before the 15-minute deadline. A reclaimed event
re-emits the same stable candidate until that deadline so a temporary execution
guard can retry without creating duplicate orders. Invalidated, timed-out, and
consumed states do not rearm. Editing the zone changes its geometry version and
starts a fresh event.

Stop and target are mirrored:

```text
Long SL  = lowest Bid  - max(current spread, 0.2 × ATR snapshot)
Short SL = highest Ask + max(current spread, 0.2 × ATR snapshot)
```

The final target is selected from the completed structural stop width relative
to the M15 ATR snapshot taken at the first touch:

| `abs(entry - SL) / ATR M15` | Final target |
| --- | --- |
| `<= 1.5` | `4R` |
| `> 1.5` and `<= 2.25` | `3R` |
| `> 2.25` and `<= 3.0` | `2R` |
| `> 3.0` | no trade; state becomes `invalidated_risk` |

Every Liquidity Sweep setup locks partial management on: the account's current
partial trigger milestone is used, 50% of the position is closed there, and the
remaining stop is moved to the exact entry price. Other playbooks keep their own
partial settings.

State is stored per `(zone_id, account_label)` because broker quotes differ.
Legacy Buy-only state columns are migrated into the generic `touched_edge_at`
and `extreme_price` fields at startup. The Zone inspector exposes every account
state. Existing news, spread, weekend, risk sizing, daily-loss, max-position and
partial-TP execution guards remain in force.

## Config

```toml
[strategy.playbooks.liquidity_sweep_reclaim_v1]
enabled = true
timeout_minutes = 15
max_sweep_atr = 1.0
sl_buffer_atr = 0.2
```
