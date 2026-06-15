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

- Max risk per trade: 1%.
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
  max_risk_per_trade_pct: 1.0
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
- WebSocket connected clients.
- Alert count by severity.
- Risk rejection count.
- Executor errors.

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
EXECUTION_ENABLED
LIVE_ORDER_VOLUME
MAX_OPEN_POSITIONS_PER_SYMBOL
MAX_TRADES_PER_DAY
```

`MT5_SYMBOL` is the broker symbol, for example `XAUUSDm` on an Exness cent
account. The local project symbol remains `XAUUSD`.

`MT5_PATH` is optional for manual runs, but strongly recommended for Windows
services on VPS because MetaTrader5 auto-discovery can fail in Session 0. Point
it to `terminal64.exe`, not just the install folder, for example:

```text
MT5_PATH=C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe
```

The worker syncs only closed candles before running detectors and strategy.
When `EXECUTION_ENABLED=false`, it still updates data and sends Telegram alerts,
but it does not place orders. When `EXECUTION_ENABLED=true`, the worker may send
real market orders for eligible setup candidates through MT5.
