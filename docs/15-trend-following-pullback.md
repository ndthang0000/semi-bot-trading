# Trend Following Pullback Playbook

## Mục tiêu

Trend Following Pullback là chiến lược ưu tiên trade thuận xu hướng H1. H1 dùng để xác định bias, regime và vùng giá quan trọng. M15 dùng để quan sát phản ứng giá tại vùng và tìm trigger vào lệnh.

Playbook này không cố bắt đỉnh đáy và không chase breakout. Ý tưởng chính là chờ giá pullback về vùng có giá trị, sau đó chỉ vào lệnh khi M15 cho thấy vùng đó được bảo vệ.

## Context bắt buộc

- Timeframe context: H1.
- Timeframe trigger: M15.
- H1 regime ưu tiên: `trending`.
- H1 bias phải rõ:
  - `bullish`: chỉ ưu tiên long.
  - `bearish`: chỉ ưu tiên short.
- Nếu H1 neutral, setup thường bị block hoặc điểm thấp vì không đúng bản chất trend following.

## Entity được sử dụng

Playbook này chỉ cần các entity sau:

- `support`: vùng mua tiềm năng khi H1 bullish.
- `resistance`: vùng bán tiềm năng khi H1 bearish.
- `order_block`: Demand OB cho long, Supply OB cho short.
- `fvg`: Bullish FVG cho long, Bearish FVG cho short.

Riêng FVG trong Trend Pullback có filter chất lượng riêng:

```toml
[strategy.playbooks.trend_pullback]
fvg_min_width_atr = 1.5
fvg_max_width_atr = 4.0
```

Ý nghĩa:

- FVG nhỏ hơn `1.5 ATR` không được dùng làm primary zone cho Trend Pullback vì vùng quá mỏng, dễ bị sweep và tạo SL quá sát.
- FVG lớn hơn `4 ATR` cũng bị block vì vùng quá rộng, entry/SL kém chính xác và RR dễ bị méo.
- FVG detector chung vẫn có ngưỡng tạo zone riêng `fvg_min_width_atr_ratio = 1.0`; tức dưới `1 ATR` thì không tạo FVG zone trong DB/chart.

Các entity không dùng trong backtest tối ưu riêng cho pullback:

- `consolidation`
- `liquidity_pool`
- range breakout/trap-specific zones

Khi chạy CLI với `--playbook trend_pullback`, backtest incremental sẽ chỉ sinh candidate cho playbook này và bỏ detector không liên quan để chạy nhanh hơn.

## Điều kiện Long

1. H1 bias là `bullish`.
2. H1 regime là `trending`.
3. Giá M15 pullback về một trong các vùng:
   - support
   - Demand OB
   - Bullish FVG
4. M15 có reaction state phù hợp:
   - `rejected`: tốt nhất.
   - `inside_wait`: chỉ tiếp tục theo dõi, chưa vào.
   - `breakout_confirmed` ngược hướng: block.
5. Có trigger M15 cùng hướng:
   - bullish displacement
   - bullish engulfing
   - bullish pinbar
   - bullish marubozu
   - morning star
   - BOS/CHOCH bullish sau phản ứng tại vùng

## Điều kiện Short

1. H1 bias là `bearish`.
2. H1 regime là `trending`.
3. Giá M15 pullback về một trong các vùng:
   - resistance
   - Supply OB
   - Bearish FVG
4. M15 có reaction state phù hợp:
   - `rejected`: tốt nhất.
   - `inside_wait`: chỉ tiếp tục theo dõi, chưa vào.
   - `breakout_confirmed` ngược hướng: block.
5. Có trigger M15 cùng hướng:
   - bearish displacement
   - bearish engulfing
   - bearish pinbar
   - bearish marubozu
   - evening star
   - BOS/CHOCH bearish sau phản ứng tại vùng

## Entry, SL, TP trong backtest

- Signal chỉ được tạo sau khi nến M15 xác nhận đã đóng.
- Entry backtest fill ở open của nến M15 tiếp theo.
- Spread và slippage được cộng vào entry/exit để giảm look-ahead và giảm ảo tưởng edge.
- Stop loss đặt theo vùng:
  - Long: dưới zone low.
  - Short: trên zone high.
- Take profit mặc định theo RR tối thiểu của strategy config, hiện đang ưu tiên khoảng `1:2`.
- Nếu cùng một nến chạm cả SL và TP, backtest xử lý bảo thủ: tính SL trước.

## Look-Ahead Guard

Khi chạy incremental backtest:

- Zone snapshot chỉ dùng nến H1 đã đóng tới thời điểm signal.
- H1 structure/context chỉ expose điểm có `confirmed_at <= signal candle close`.
- M15 trigger chỉ dùng nến đã đóng.
- Entry luôn ở nến M15 tiếp theo, không entry trong cùng nến signal.

Đây là phiên bản gần với realtime hơn so với việc lấy toàn bộ zone đã lưu sẵn trong database.

## Command tối ưu riêng cho Pullback

Smoke test nhanh:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 3000 \
  --engine incremental \
  --playbook trend_pullback \
  --max-rows 10
```

Hoặc dùng script có sẵn:

```bash
LIMIT=3000 MAX_ROWS=10 ./scripts/backtest_trend_pullback.sh
```

Backtest 30k nến:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 30000 \
  --engine incremental \
  --playbook trend_pullback
```

Chạy 30k nến bằng script:

```bash
./scripts/backtest_trend_pullback.sh
```

Xuất HTML report:

```bash
HTML_OUTPUT=var/reports/trend_pullback.html ./scripts/backtest_trend_pullback.sh
```

Backtest với spread/slippage custom:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 30000 \
  --engine incremental \
  --playbook trend_pullback \
  --spread 0.30 \
  --slippage 0.10
```

Xuất HTML bằng CLI trực tiếp:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 30000 \
  --engine incremental \
  --playbook trend_pullback \
  --html-output var/reports/trend_pullback.html
```

Persist trade để vẽ lên chart UI:

```bash
python -m semi_bot_trading.cli backtest-strategies \
  --limit 30000 \
  --engine incremental \
  --playbook trend_pullback \
  --persist \
  --clear-backtest-trades
```

Hoặc dùng script:

```bash
PERSIST=1 ./scripts/backtest_trend_pullback.sh
```

Trade được lưu vào `trade_ideas`, `trade_orders`, `trade_fills` với:

- `trade_orders.source = backtest`
- `metadata_json.backtest = true`
- `context_snapshot_json.backtest = true`

Chart UI chỉ hiển thị trade thuộc playbook đang được chọn trong menu `Playbooks`. Nếu chỉ chọn `trend_pullback`, chart chỉ vẽ các lệnh pullback.

## Cách đọc report để tối ưu

Ưu tiên xem các nhóm sau:

- `By zone type`: support/resistance/OB/FVG, loại nào đang có edge.
- `By trigger type`: trigger PA nào thật sự hiệu quả.
- `By H1 bias`: bullish/bearish/neutral có bị lệch chất lượng không.
- `By H1 regime`: nếu trending vẫn lỗ nặng thì rule regime hoặc zone đang quá noise.
- `By zone width/ATR bucket`: vùng quá hẹp hoặc quá rộng có thể cần filter.
- `By zone touch count`: nhiều touch quá có thể vùng đã yếu.

Các hướng tối ưu tiếp theo:

- Chỉ cho phép pullback theo OB/FVG hoặc chỉ SR để so sánh.
- Tăng yêu cầu reaction từ `inside_wait` lên `rejected`.
- Tăng yêu cầu trigger: cần displacement + PA, không chỉ một pattern đơn.
- Filter vùng quá xa/gần current price theo ATR.
- Tách long/short để xem XAUUSD có lệch edge theo chiều nào.
