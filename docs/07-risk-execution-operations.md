# 07 - Risk, Execution và Operations

## Nguyên tắc an toàn

Executor là phần nguy hiểm nhất của hệ thống. Nó phải bị giới hạn bởi Risk Engine, audit log và mode xác nhận.

Mặc định ban đầu:

- Không full auto.
- MVP trên Macbook chỉ replay/backtest, không connect account thật.
- Live phase sau này dùng Exness/MT5 qua Python `MetaTrader5`.
- Mọi execution request phải có context snapshot.
- Mọi order phải có stop loss hoặc invalidation rõ ràng.
- Có kill switch.

## Risk Engine

Risk Engine kiểm tra trước khi executor nhận request.

Rule MVP:

- Risk mặc định theo account profile: tài khoản quỹ 1%, tài khoản thường 2%.
- Manual AI, H1 Impulse và Zone Reaction V2 dùng mức thấp hơn: tài khoản quỹ
  0.75%, tài khoản thường 1.5%.
- Max total open risk.
- Max daily loss: 5%.
- Max trades per day: 10.
- Max concurrent positions per symbol.
- Minimum RR: 1:2.
- Spread/slippage threshold.
- Data freshness.
- Human confirmation required.
- No-trade override active.
- Không cần dừng trade sau chuỗi thua trong decision hiện tại.
- Không tự giảm lot size khi high volatility trong decision hiện tại, nhưng high/news regime vẫn có thể block setup nếu rule yêu cầu.

Ví dụ:

```yaml
risk_policy:
  prop_firm_risk_per_trade_pct: 1.0
  personal_risk_per_trade_pct: 2.0
  reduced_playbook_prop_firm_risk_per_trade_pct: 0.75
  reduced_playbook_personal_risk_per_trade_pct: 1.5
  max_daily_loss_pct: 5.0
  max_trades_per_day: 10
  max_open_positions_per_symbol: 1
  min_rr: 2.0
  require_stop_loss: true
  require_human_confirmation: true
```

## Execution Request

```yaml
execution_request:
  id: string
  trade_idea_id: string
  symbol: string
  side: buy | sell
  order_type: market | limit
  quantity: decimal
  entry_price: decimal | null
  stop_loss: decimal
  take_profit: decimal[]
  risk_snapshot: json
  context_snapshot: json
  requested_by: strategy | human
  status: pending_risk | rejected_by_risk | pending_human | approved | sent | filled | cancelled | failed
  created_at: datetime
  human_confirmation_expires_at: datetime | null
```

## Executor responsibilities

Executor chỉ làm:

- Nhận approved execution request.
- Map symbol/order format theo MT5/Exness.
- Gửi order.
- Theo dõi order state.
- Modify/cancel khi có request hợp lệ.
- Đồng bộ position.
- Ghi log.

Executor không làm:

- Tự phân tích market.
- Tự tăng size vì confidence cao.
- Tự bỏ qua stop loss.
- Tự retry đặt lệnh thị trường nhiều lần khi network lỗi.

## Broker abstraction

Broker đã chốt cho live phase là Exness qua MT5, nhưng vẫn nên giữ abstraction để test/backtest và tránh khóa logic strategy vào một thư viện.

```python
class BrokerClient:
    def place_order(self, request): ...
    def cancel_order(self, order_id): ...
    def modify_order(self, order_id, patch): ...
    def get_positions(self): ...
    def get_orders(self): ...
```

Adapter:

- `MockBrokerClient` cho replay/backtest.
- `MT5BrokerClient` dùng Python `MetaTrader5` cho Exness ở live phase.

## Replay / Backtest trading

Replay/backtest cần làm trước live execution.

Tính năng:

- Simulate fill.
- Simulate slippage/spread.
- Track PnL.
- Track trade lifecycle.
- Export report.

Replay/backtest engine giúp test:

- Strategy logic.
- Alert quality.
- Human override impact.
- Risk rules.

## Live confirmation rule sau MVP

Khi chuyển sang live:

- Human confirm trên UI, không confirm qua Telegram.
- Nếu sau 5 phút chưa confirm:
  - Nếu giá đã tệ hơn entry mong muốn, tạo limit order tại entry mong muốn.
  - Nếu giá tốt hơn entry mong muốn, có thể vào market.
- Chỉ hỗ trợ market và limit order ở phase đầu.
- Tạm thời không làm partial take profit, trailing stop, breakeven automation trong executor.

## Kill switch

Cần có kill switch ở nhiều lớp:

- UI button: disable execution.
- Config/env: `EXECUTION_ENABLED=false`.
- Risk engine: reject all new requests.
- Executor: cancel pending orders nếu user chọn.

Kill switch state phải được hiển thị rõ trong UI và alert Telegram.

## Secrets

Không commit secrets.

Cần quản lý:

- Telegram bot token.
- MT5 account/server/password hoặc phương thức login phù hợp.
- Không cần data provider API key trong MVP mock data.

Gợi ý:

- `.env` local.
- Secret manager sau này.
- Trading key chỉ dùng cho executor service.

On VPS, prefer split env files:

- `.env.api`: backend/API auth and CORS only. Do not store MT5 passwords here.
- `.env.exness`: Exness live worker credentials and account risk settings.
- `.env.ftmo`: FTMO live worker credentials and account risk settings.

Start commands should pass the env explicitly, for example
`serve-api --env .env.api`, `live-worker --env .env.exness`, and
`live-worker --env .env.ftmo`.

## Observability

Log cần có:

- Data ingestion status.
- Analyzer runtime/errors.
- Entity emitted.
- Override created/expired/revoked.
- Alert sent/suppressed.
- Trade idea created.
- Risk rejection reason.
- Execution request lifecycle.
- MT5 broker response.
- Backtest/replay trade result.

Metrics:

- Candle latency.
- Analyzer latency per symbol/timeframe.
- Spread latest/average/percentiles theo broker symbol để phát hiện khung giờ spread ăn mòn lợi nhuận.
- WebSocket connected clients.
- Alert count by severity.
- Risk rejection count.
- Executor errors.

## Weekend Flatten

Voi style XAUUSD H1/M15 zone reaction, live worker khong giu lenh qua weekend. Mac dinh:

- Ngung mo lenh moi sau `Friday 12:00 America/New_York`.
- Tu dong cancel **tat ca** pending orders va close **tat ca** open positions cua
  symbol tren account worker sau `Friday 15:30 America/New_York`, bao gom bot,
  manual (`magic=0`) va order cua EA khac.
- `Friday 15:30 America/New_York` thuong la `Saturday 02:30 Asia/Ho_Chi_Minh` khi New York dang DST.
- Weekend window ket thuc luc `Sunday 17:00 America/New_York`, gan voi luc thi truong mo lai tuan moi.

Config `.env`:

```text
WEEKEND_FLATTEN_ENABLED=true
WEEKEND_FLATTEN_TIMEZONE=America/New_York
WEEKEND_NO_NEW_TRADES_TIME=12:00
WEEKEND_FLATTEN_TIME=15:30
```

Dung timezone New York de tu dong dung khi DST doi gio; tranh hard-code gio Viet Nam.

## News Time Normalization

Feed XML `nfs.faireconomy.media` cung cap clock time theo UTC. Parser luu truc
tiep UTC; khong cong them offset Eastern. Vi du BEA 08:30 EDT duoc feed bieu
dien la `12:30pm` va database phai luu `12:30 UTC`.

Khong co post-news cooldown rieng. Live execution chi dung blackout co ban theo
tier: Tier 1 truoc/sau 30 phut va Tier 2 truoc/sau 15 phut.

### FTMO news compliance

FTMO compliance duoc tach khoi market-risk tier. No chi active khi worker co:

```text
ACCOUNT_PROFILE=ftmo_challenge
FTMO_PHASE=funded
FTMO_ACCOUNT_TYPE=standard
FTMO_NEWS_BUFFER_MINUTES=5
FTMO_NEWS_CALENDAR_MAX_AGE_HOURS=36
FTMO_NEWS_FLATTEN_ENABLED=true
```

`FTMO_PHASE=evaluation` bao gom Challenge/Verification; `FTMO_ACCOUNT_TYPE=swing`
khong ap dung news restriction. Voi funded Standard, worker dung state machine:

- T-5 den truoc T-3: huy pending order cua bot va dong position cua bot theo
  `MT5_MAGIC`. Lenh manual khong bi cham toi.
- T-3 den T+2: hard freeze noi bo, khong gui bat ky MT5 order action nao. Mot
  phut safety margin T-3 den T-2 bao ve khoi request cham; FTMO hard window chinh
  thuc van la T-2 den T+2. Dashboard
  close command, partial TP, break-even, weekend flatten va entry moi deu pause.
- Sau T+2 den T+5: cooldown; entry moi va order management van pause.
- Calendar qua `FTMO_NEWS_CALENDAR_MAX_AGE_HOURS` se fail closed: khong entry,
  dashboard close, partial TP hay break-even, va gui critical alert.

FTMO restricted list duoc classify rieng, khong dua vao nhan High/Medium cua
ForexFactory. Hien tai gom Federal Funds Rate/Statement, NFP, Unemployment/Wages,
Advance GDP q/q, FOMC Meeting Minutes va CPI y/y. General market-risk blackout
Tier 1/2 van hoat dong doc lap va co the rong hon danh sach FTMO.

## Partial TP / Break-even

Live worker quan ly lenh dang mo bang rule mac dinh:

- Khi trade dat `+1.0R`, dong `40%` volume.
- Sau khi partial close thanh cong, doi SL cua position con lai ve entry, cong/tru buffer neu co.
- Phan con lai giu TP cuoi cua setup; `zone_reaction_v2` hien tai dung `2.0R`.
- Metadata `trade_orders.metadata_json.partial_take_profit` ghi `armed/done`, trigger price, closed volume va BE SL de UI/debug.

Config `.env`:

```text
PARTIAL_TAKE_PROFIT_ENABLED=true
PARTIAL_TAKE_PROFIT_R=1.0
PARTIAL_TAKE_PROFIT_FRACTION=0.4
PARTIAL_TAKE_PROFIT_BE_BUFFER=0.0
```

Rule nay chi ap dung cho `trade_orders.source = live` dang `filled`; pending limit order phai filled thanh position truoc khi duoc quan ly.

### Dashboard trade management

Trade Inspector có thể queue ba command giảm exposure cho một trade `live`
đang `filled`:

- `close_trade_position`: đóng toàn bộ volume còn lại tại market.
- `partial_trade_position`: đóng 50% volume hiện tại rồi dời SL phần còn lại về
  broker entry; nếu bước BE lỗi, partial vẫn được ghi `done` và worker chỉ retry
  BE, không partial lần hai. Nếu SL đã tốt hơn entry thì giữ nguyên SL đó.
- `break_even_trade_position`: giữ nguyên TP và dời SL về broker entry; nếu SL
  hiện tại đã hòa vốn hoặc tốt hơn thì command thành công mà không gửi modify.

API chỉ ghi `account_execution_commands`; worker đúng `account_label` mới được
gọi MT5. Trước mọi action, worker bắt buộc khớp broker position ticket từ trade
metadata, side và `MT5_MAGIC`. Mismatch fail closed. Các command vẫn tuân theo
FTMO hard-news freeze/stale-calendar guard giống close-all và automation quản lý
lệnh. UI dùng idempotency key và poll `/api/account-commands/{command_id}` để
hiển thị kết quả thực thi thay vì coi HTTP `202` là broker đã hoàn tất.

Moi pending limit duoc broker xac nhan fill deu di qua mot transition chung,
khong phu thuoc playbook. Transition nay dong bo `trade_orders`,
`execution_requests` va plan lien ket sang `filled`, ghi actual fill/open time tu
MT5 neu co, sau do queue mot `execution_event` Telegram. Dedupe key dung
`account_label + trade_order_id + filled`, nen poll lai hoac hai detector cung
nhin thay fill cung khong gui trung message. Worker kiem tra ca position dang mo
va order history de khong mat event neu lenh fill roi dong giua hai lan poll.

Candidate live duoc dedupe theo `candidate_id + account_label`. Mot execution
request da `filled` hoac `closed` tieu thu vinh vien candidate do, ke ca sau khi
position duoc human dong va candidate detector van con tra ve `eligible`.
`pending`/`sent` chan request trung trong luc order dang xu ly; chi request
`failed` hoac `cancelled` truoc khi co execution thanh cong moi duoc retry.

Chart inspector cho phep doi Partial TP theo tung account: bat/tat, chon moc
tu `0.5R` den `2.0R` va ty le dong tu `25%` den `50%`. Thay doi duoc worker ap dung chi cho lenh live Zone Reaction V2 dang
`armed` (chua partial) va cac lenh tao sau do; lich su lenh da partial/da dong
khong bi viet lai. `.env` la gia tri khoi tao khi account chua co UI override.

Khi MT5 position dong, worker tinh net P&L tu gross exit profit cong voi
commission, swap va fee cua **toan bo deals** thuoc position. Commission co the
bi charge rieng o deal mo (`DEAL_ENTRY_IN`) va deal dong (`DEAL_ENTRY_OUT`), nen
chi doc closing deal se lam P&L cao hon broker balance. Breakdown duoc snapshot
vao `trade_orders.metadata_json.broker_close_costs` gom `gross_profit`,
`commission`, `swap`, `fee` va `net_profit`.
Live trade cu da `closed` nhung chua co snapshot nay duoc worker resync mot lan
tu MT5 history; backfill khong tao lai Telegram close alert.

## Spread Monitoring

Live worker lưu bid/ask/spread của XAUUSD mỗi vòng poll vào `spread_snapshots`. Spread được lưu theo price unit giống `MAX_SPREAD_PRICE`, ví dụ XAUUSD spread `1.20` nghĩa là ask-bid lệch 1.20 USD.

Xem nhanh thống kê:

```bash
python -m semi_bot_trading.cli spread-summary --hours 24
python -m semi_bot_trading.cli spread-summary --hours 168
```

UI realtime đọc `/api/spread` bằng polling ngắn. Chưa cần Socket.IO cho spread vì chỉ cần current status và summary vài giây/lần; WebSocket/Socket.IO chỉ nên thêm khi cần stream tick-by-tick, multi-symbol, hoặc event push có độ trễ thấp.

## Incident cases

### Data stale

Nếu candle không cập nhật:

- Mark data feed stale.
- Stop creating trade ideas.
- Send critical system alert.
- UI warning.

### Analyzer crash

- Restart worker.
- UI shows degraded state.
- Executor unaffected.
- No new trade ideas.

### Telegram down

- Store alert failed.
- Retry.
- Do not block trading state.

### MT5 / Broker API down

- Stop new execution.
- Try to sync existing positions.
- Alert critical.

## Compliance cá nhân

Tài liệu này không phải lời khuyên tài chính. Hệ thống cần được dùng với replay/backtest và kiểm thử trước khi có lệnh thật.

## Implementation Notes

Live MT5 support is implemented as a separate worker:

```powershell
python -m semi_bot_trading.cli live-worker
```

One-shot smoke run:

```powershell
python -m semi_bot_trading.cli live-worker --once
```

Required runtime variables:

```text
MT5_LOGIN
MT5_PASSWORD
MT5_SERVER
MT5_PATH
MT5_SYMBOL
MT5_SERVER_UTC_OFFSET_HOURS
EXECUTION_ENABLED
LIVE_ORDER_VOLUME
MAX_OPEN_POSITIONS_PER_SYMBOL
MAX_TRADES_PER_DAY
```

Multi-account live operation uses one worker process per MT5 account. Each
worker must have a unique `ACCOUNT_LABEL` and `MT5_MAGIC`; live execution,
trade counts, daily loss, FVG-per-zone limits, spread snapshots, and order sync
are scoped by `ACCOUNT_LABEL` so Exness and FTMO cannot contaminate each
other's limits.

Only one worker should normally own shared market data and detectors:
`LIVE_SYNC_CANDLES=true` and `LIVE_RUN_DETECTORS=true`. Secondary account
workers can set both flags to `false`; they still snapshot their account/spread,
sync closed positions, manage partial TP/BE, apply weekend flatten, read setup
candidates from the DB, run account-specific risk checks, and execute only for
their own `ACCOUNT_LABEL`.

FTMO accounts must use `ACCOUNT_PROFILE=ftmo_challenge` and should start with
`EXECUTION_ENABLED=false`. FTMO startup validation fails closed if symbol
metadata is missing or `trade_contract_size` is suspicious. Do not use cent
balance scaling for FTMO; leave `ACCOUNT_BALANCE_SCALE` unset or set it to
`1.0`.

Keep `FTMO_PHASE=evaluation` through Challenge and Verification. Change it to
`funded` only after receiving a funded Standard FTMO Account. Confirm
`FTMO_ACCOUNT_TYPE=standard` versus `swing`; a wrong value can either flatten
unnecessarily or leave a Standard account without contractual protection.

Set `ACCOUNT_INITIAL_BALANCE` to the original FTMO account size (for example,
`100000`) so the Account Dashboard daily percentage uses the same denominator
as the FTMO Maximum Daily Loss objective. Daily profit is calculated as current
equity minus the balance reconstructed at `00:00 Europe/Prague`; this IANA zone
automatically follows CET/CEST daylight-saving changes. `DAILY_RESET_TIMEZONE`
defaults to `Europe/Prague`.
The pre-order Risk Engine uses that same equity-based snapshot, including open
P/L, and calculates the 5% limit from the original account balance. FTMO entry
fails closed if the daily metric is missing or older than two minutes; the live
worker refreshes it immediately before evaluating candidates.
For FTMO labels containing the account size (for example `FTMO 100K 2-Step`),
the worker can infer `100000`; the explicit env value still takes priority.

The Account Dashboard switch is a second, database-backed execution gate. The
worker environment `EXECUTION_ENABLED=true` remains the hard ceiling: the UI
can pause and resume a live-enabled worker but cannot override a disabled env.
“Close all position” first pauses execution, cancels pending bot orders, and
closes bot positions whose MT5 magic number matches that worker. Its confirmation
modal has an opt-in checkbox to include manual/human positions for the symbol;
that checkbox is off by default. Manual pending orders are always left untouched.

Account Dashboard also exposes a per-account `Manual Trading Lock`. This control
does not disable bot execution. When enabled, the worker snapshots existing
XAUUSD manual positions and pending orders (`magic=0`) as a grandfathered
baseline, then checks for new manual exposure every
`MANUAL_TRADE_GUARD_SECONDS` (default `1.0`). New manual pending orders are
cancelled and new manual positions are closed at market; bot magic and other
non-zero EA magic numbers are untouched. MT5 cannot intercept a human click
before broker acceptance, so a manual market position may incur spread/slippage
before the guard closes it. The fast guard and 15-second strategy cycle share
one MT5 client and run sequentially to avoid concurrent terminal calls.

Nếu MT5 terminal bị `Restart App` trong lúc worker đang chạy, lỗi mất session
hoặc broker symbol sẽ kích hoạt reconnect, resolve lại `MT5_SYMBOL` và validate
lại account trước khi guard tiếp tục. `manual_lock_last_error` chỉ giữ lỗi hiện
tại; lần kiểm tra guard thành công kế tiếp phải tự xóa cảnh báo cũ trên dashboard.

Account Dashboard chi hien trang thai `Manual LOCKED`/arming/inactive o dang
read-only; UI khong co toggle unlock de tranh human tat guard trong luc mat binh
tinh. Endpoint backend van duoc giu cho thao tac quan tri co chu dich.

Exness cent accounts should use `ACCOUNT_PROFILE=personal_cent` or explicitly
set `ACCOUNT_BALANCE_SCALE=0.01` when MT5 reports USD-equivalent balance in USC
units, for example 1000 USD displayed as 100000 USC.

`MT5_SYMBOL` is the broker symbol, for example `XAUUSDm` on an Exness cent
account. The local project symbol remains `XAUUSD`.

`MT5_SERVER_UTC_OFFSET_HOURS` defaults to `0`. Set it per worker when MT5
history timestamps use broker wall time instead of UTC; for example, use `3`
when the FTMO terminal is three hours ahead. The worker subtracts this offset
before storing candle and deal-close timestamps, and adds the same offset to
UTC history-query boundaries and `ORDER_TIME_SPECIFIED` pending-order
expirations. This keeps FTMO deal reconstruction and order expiry on the broker
clock while an Exness worker configured with `0` remains unchanged.
Recheck it when the broker's summer/winter server time changes.

`MT5_PATH` is optional for manual runs, but strongly recommended for Windows
services on VPS because MetaTrader5 auto-discovery can fail in Session 0. Point
it to `terminal64.exe`, not just the install folder, for example:

```text
MT5_PATH=C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe
```

The worker syncs only closed candles before running detectors. Heavy detectors
run when a new M15 candle has closed, while setup evaluation and execution
checks run every poll cycle so human zone edits or delayed DB syncs do not
require a worker restart. When `EXECUTION_ENABLED=false`, it still updates data
and sends Telegram alerts, but it does not place orders. When
`EXECUTION_ENABLED=true`, the worker may send real market orders for eligible
setup candidates through MT5.
