# Line Reaction V1

Human-authored horizontal price segment, account scoped, independent of price zones.
Use Add Entity -> Add line buy / Add line sell. Click the first point, move
horizontally left (temporary dashed segment), then click the endpoint to save Draft.
The first point fixes price; endpoint time order is normalized. Esc cancels drawing.
The Zones tab in the right inspector opens automatically and groups these entries
under Reaction Lines, separately from Price Areas. Edit Draft config/accounts,
save, then Arm explicitly. Execution starts at server arm time, never at a drawn
past time. The future right endpoint (`visual_end`) is the execution expiry.
Line Prices stay compact until selected; configuration and lifecycle actions are
shown only in the selected line detail.
Draft lines use a dashed stroke; Armed and later lifecycle states use a solid
stroke. Selecting a Draft or Armed line on the chart reveals left/right handles.
Dragging either handle changes the visible duration and refreshes execution expiry.
Line Detail shows the remaining duration and absolute expiry read-only. Traders
change expiry by dragging the right endpoint on the chart.
Escape clears the selected line and closes Line Detail. Clicking elsewhere in the
chart also clears it. Delete/Backspace asks for confirmation before cancelling the
selected line group. Draft uses a thinner dashed stroke than Armed.
One visible line is one logical setup shared by its selected accounts. New Drafts
select every online worker account by default; offline accounts remain visible and
can be selected explicitly. The database keeps one execution row
per account under a shared `client_group_id`, preserving independent worker state
and the one-concurrent-trade-per-account guard. Direction is fixed by Add line
buy/sell and cannot be changed in Line Detail. Remaining expiry is shown in hours
for H1 planning. Dragging the future `visual_end` changes expiry while preserving
the beginning of the line.
Line Prices, line overlays, Add line buy/sell and the required Structure + ZigZag
layer are scoped to the Line Reaction V1 playbook selection.
Legacy lines without visual endpoints retain the original arm/expiry span. Draft is inert. No backdating,
zone/bias/macro/structure entry filters or London-NY restriction.
Global switch: [strategy.playbooks.line_reaction_v1] enabled = true.

## Trigger

M15 closed candles only. Candle open >= armed_at; close must be available now,
trigger younger than 15 minutes, line unexpired. Require low <= line <= high,
correct body direction and close strictly on the reclaim side.
Shared close_extreme_recovery_metrics compares close-low (long) or high-close
(short) to the exact preceding 20 candle bodies. Default/minimum ratio 2.0;
configurable period. If BOTH directions pass the threshold, reject the candle,
including equality. Missing/zero baseline, missing ATR, doji and stale signals fail closed.

Each Line stores its own multi-select `trade_sessions`. The default selects all
five fixed UTC windows: Asian 00:00–07:00, London 07:00–12:00, London–NY
12:00–17:00, New York 17:00–21:00 and Off-hours 21:00–24:00. The worker only
accepts a recovery and sends a new order inside a selected session. An unsubmitted
signal is cleared when its session ends; a confirmed pending limit is cancelled so
it cannot fill in an unselected session. Filled positions keep normal management.
Adjacent selected windows are merged, including Off-hours into the following Asian
session. Selecting all sessions therefore provides continuous coverage without
shortening limit TTL at the individual session boundaries. The API session catalog
is the source used by the Line Detail UI for names and UTC times.

## Entry, SL and expiry

ATR period 14, M15/H1 closed data snapshotted at trigger.
Structural SL = low - 0.1 ATR M15 (long), high + 0.1 ATR M15 (short).
If broker entry distance to structural SL <= 1.2 ATR H1, market with wick SL.
Otherwise limit = trigger close - 5 (long), trigger close + 5 (short).
Offset is price units, not points/pips, and does not follow the quote.
Final distance = min(distance from limit to wick SL, 1.2 ATR H1).
SL can therefore lie inside the trigger wick, recorded as atr_cap metadata.
Invalid-side limit, crossed structural stop or nonpositive risk: no order.
Reprice before sizing with this formula; don't use generic adverse-drift SL shifts.
Recheck the selected session, spread and market SL cap immediately before sending.
Actual fills can still slip.

TTL = min(line expiry, signal close + pending TTL, default 120 minutes).
Unsent signals waiting for spread/news/risk gates expire after 15 minutes.
Pending orders already sent retain their TTL.
MAX_SPREAD_PRICE is checked by the executor and again immediately before market send.
All account, weekend, mandatory news, position and daily-risk gates remain.

## TP, partial and risk

Fixed RR: 1.5, 2, 2.5 or 3. Wave Safe/Base reuse H1 Impulse calculations on confirmed H1
structure available at signal close. Require >=3 same-direction completed legs.
Explicit wave mode with missing evidence or target below 2R blocks entry.
Wave reward is capped at the selected 1.5/2/2.5/3R. Wave evidence is frozen at trigger.
Risk: approved-plan policy, 0.75% fund / 1.5% personal, sized from final geometry.
Partial defaults OFF; optional partial/BE is locked per-line metadata. A selected
fraction of zero is the break-even-only mode: at the configured R trigger the
worker preserves the full position and moves its SL to entry. Zone Reaction
account partial settings never overwrite it.

## Lifecycle and concurrency

Draft -> Armed -> Executing (reserved) -> Pending/Open -> Closed.
Cancelled/Expired/Failed are terminal. One execution attempt per line.
After `pending_intent_grace_minutes` (default five), an interrupted `pending`
intent is checked against active MT5
bot exposure for the symbol. If MT5 confirms there is no bot position or pending
order, the attempt becomes Failed and releases the account slot without retrying.
If exposure exists or MT5 cannot confirm state, it becomes
`reconciliation_required`, retains the reservation, and shows an explicit error.
The worker keeps checking and releases the slot only after active bot exposure is
gone. Unknown broker intents are never blindly retried.
SQLite unique partial index on account_label for executing/pending/open/cancel_requested/
reconciliation_required serializes Line Reaction exposure per account across
symbols/worker processes.
Intent existence is rechecked inside BEGIN IMMEDIATE before persistence.
Multiple armed lines may wait. A trigger reserves every available member of the
same logical Line group in one transaction, so selected accounts execute the same
frozen signal and Line config. If any selected account is already reserved by an
executing, pending, open, cancel-requested or reconciliation-required Line, the
whole new group keeps waiting. This prevents workers from choosing different
overlapping Lines with different TP/partial settings on the same recovery candle.

Expiry/cancel removes confirmed pending orders only, never filled/unknown positions.
GTC fallback needs worker polling; cancellation is delayed/offline when worker is off.
Fund news hard guards take priority. Filled trades retain normal SL/TP/partial handling.

## Storage/API and scope

line_reaction_plans stores account/direction/price/config, shared client_group_id, lifecycle, timestamps,
signal/ATR/wave snapshot and last_error. Additive migration runs at startup.
Create requests carry a client-generated idempotency key so a successful POST is
not duplicated when the following refresh fails. Removing an account from a Draft
or Armed group marks its member row cancelled and removed while retaining the row
for audit.
GET /api/line-reactions returns at most 20 logical Line groups with all account
members for each group, prioritizing non-terminal Lines before recent history. POST
/api/line-reactions; POST
/api/line-reactions/{id}/arm or /cancel.
PATCH /api/line-reactions/{id} updates Draft or Armed groups. Once any member is
Executing/Pending/Open, geometry and config are locked to avoid changing a plan
during broker submission.
Authenticated API, registered accounts and configured symbol only.
Trades carry playbook line_reaction_v1 and appear in trade filters/inspector.
This version supports live execution and pure evaluator tests. Historical backtest
engine does not simulate human-created line histories. Replay hides live creation.
