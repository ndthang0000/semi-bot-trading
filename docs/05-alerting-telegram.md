# 05 - Telegram Alerting

## Mục tiêu

Telegram alert giúp human không phải nhìn chart liên tục. MVP gửi private message cho một user, không dùng group và không cần nhiều mức alert hiển thị cho user.

## Loại alert MVP

### 1. New Entity Detected

Khi bot detect bất kỳ entity mới có ý nghĩa:

- H1 support/resistance weight cao.
- OB có displacement + BOS.
- FVG mới cùng HTF bias.
- Consolidation range đủ rõ.
- Liquidity sweep.
- HH/HL/LH/LL, BOS/CHOCH quan trọng.

### 2. Price Approaching Zone

Khi giá cách vùng quan trọng một khoảng nhỏ:

- Theo ATR.
- Theo % giá.
- Theo số pip/tick tùy market.

### 3. Zone Touched

Khi giá chạm zone:

- Chạm lần đầu.
- Chạm lại sau mitigation.
- Chạm vùng human-adjusted.

### 4. Liquidity Sweep

Khi có sweep:

- Sweep range high/low.
- Sweep swing high/low.
- Sweep rồi reclaim.

### 5. Bias / Regime / State Changed

Khi bot đổi bias/regime hoặc bất kỳ state quan trọng nào:

- Bias changed.
- Regime changed.
- Overlay changed: expansion/contraction/high volatility/low volatility/news/risk-off.
- Human override created/updated/revoked.
- Human override expiring soon/expired.
- Entity mitigated/filled/invalidated/disabled.

### 6. Setup Candidate

Khi đủ điều kiện playbook:

- HTF bias/regime phù hợp.
- Giá ở vùng quan trọng.
- M15 có trigger.
- Risk rule sơ bộ đạt.

### 7. Trade / Backtest / Execution Event

- Backtest trade idea created.
- Backtest entry triggered.
- Backtest trade closed.
- Sau live phase: order pending/filled/cancelled/failed.

## Format message gợi ý

```text
[XAUUSD][M15] Price touched Bullish OB

Price: 2342.50
Zone: 2338.20 - 2344.10
HTF Bias: Bullish (Human, expires in 2h)
Regime: Trending + Expansion
Weight: 0.82
Confidence: 0.74

Reason:
- H1 bullish structure
- M15 pullback into OB
- FVG overlap 42%

Action:
Watch for M15 confirmation. No auto execution.

Open chart: <link>
```

Nếu là setup/backtest trade, nên gửi thêm ảnh chart snapshot có entry, SL, TP nếu backend/UI render được ảnh ổn định.

## Alert suppression

Chống spam là yêu cầu bắt buộc.

Rule gợi ý:

- Không gửi lại cùng event/entity trong N phút.
- Nếu giá vẫn nằm trong zone, không gửi mỗi tick.
- Chỉ gửi lại khi có state change: approach -> touched -> rejected -> invalidated.
- Alert weight thấp vẫn có thể gửi nếu là entity mới hoặc state change bắt buộc, nhưng message phải ghi rõ weight thấp.
- Human-adjusted zone có thể được ưu tiên gửi.

## Alert routing

- Gửi private chat.
- Không cần group.
- Không cần nhiều channel theo severity.
- Nội bộ vẫn có thể lưu `severity` để debug/filter sau này, nhưng Telegram MVP không cần user chọn severity.
- Không cần inline buttons như Open Chart, Mute, Acknowledge trong MVP.

## Telegram commands sau MVP

Có thể thêm command:

- `/status XAUUSD`
- `/bias XAUUSD`
- `/zones XAUUSD H1`
- `/mute XAUUSD 1h`
- `/unmute XAUUSD`

Không confirm trade qua Telegram. Live phase confirm trên UI.

## Data model

```yaml
alert_event:
  id: string
  symbol: string
  timeframe: string
  event_type: new_zone | approaching_zone | zone_touched | liquidity_sweep | bias_changed | regime_changed | setup_candidate | system
  severity: info | watch | important | critical
  entity_ids: string[]
  message_payload: json
  dedupe_key: string
  created_at: datetime
  sent_at: datetime | null
  status: pending | sent | suppressed | failed
  chart_snapshot_path: string | null
```

## Failure handling

- Telegram API lỗi: retry exponential backoff.
- Sau retry thất bại: lưu failed, hiển thị trong UI.
- Bot token không hợp lệ: system alert local/log.
- Không block analyzer vì Telegram lỗi.

## Decisions hiện tại

- Telegram gửi private message.
- Không cần nhiều mức alert cho user trong MVP.
- Alert bắt buộc khi bot detect entity mới hoặc bot/human/state thay đổi.
- Không cần inline buttons trong MVP.
- Không cần override/mute từ Telegram trong MVP.
- Chart snapshot là nice-to-have, ưu tiên cho setup có entry/SL/TP.

## Implementation Notes

Runtime Telegram support is implemented through:

- `alert_events` SQLite table.
- `semi_bot_trading.alerts` queue/sender helpers.
- CLI smoke test:

```powershell
python -m semi_bot_trading.cli telegram-test --message-key smoke-1
```

Credentials are read from `.env` or environment variables:

```text
TELEGRAM_TOKEN
TELEGRAM_CHAT_ID
CHART_URL_BASE
```

The live worker queues Telegram alerts for new important zones, setup candidates
(`eligible`, `waiting_confirmation`, and `blocked` with block reasons), and
execution events, then sends pending alerts without blocking detector logic.
