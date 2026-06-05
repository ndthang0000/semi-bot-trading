# 13 - M15 Price Action Detector Formula

## Mục tiêu

Price Action Detector dùng M15 để tạo confirmation cho entry, còn H1 vẫn là context chính cho bias, regime và vùng giá lớn.

Detector hiện tại lưu kết quả vào bảng `structure_points` với:

- `detector = price_action_v1`
- `timeframe = M15`
- `status = confirmed`
- `metadata.confirmation_role = entry_trigger`

Các event này chưa phải lệnh trade. Strategy Engine sẽ dùng chúng như trigger/confluence sau khi giá chạm H1 zone.

## Config

Các tham số nằm trong `config/trading.toml`:

```toml
[price_action]
detector = "price_action_v1"
timeframe = "M15"
atr_period = 14
displacement_atr_multiplier = 1.5
displacement_body_ratio = 0.60
pinbar_wick_body_ratio = 2.0
pinbar_min_wick_ratio = 0.55
engulfing_min_body_ratio = 0.45
marubozu_min_body_ratio = 0.75
star_large_body_ratio = 0.45
star_small_body_ratio = 0.35
```

## Candle Metrics

Với mỗi nến:

```text
range = high - low
body = abs(close - open)
upper_wick = high - max(open, close)
lower_wick = min(open, close) - low
body_ratio = body / range
upper_wick_ratio = upper_wick / range
lower_wick_ratio = lower_wick / range
close_position = (close - low) / range
```

Nếu `range <= 0` hoặc thiếu `open`, detector bỏ qua nến đó.

## Pinbar

### Bullish Pinbar

Điều kiện:

- `lower_wick >= body * pinbar_wick_body_ratio`
- `lower_wick_ratio >= pinbar_min_wick_ratio`
- `close_position >= 0.55`

Ý nghĩa:

- Giá bị đạp xuống dưới nhưng bị mua lên lại.
- Dùng tốt hơn khi xuất hiện tại support, demand OB, bullish FVG hoặc sau liquidity sweep low.

Output:

```text
point_type = pinbar_bullish
direction = up
price = close
```

### Bearish Pinbar

Điều kiện:

- `upper_wick >= body * pinbar_wick_body_ratio`
- `upper_wick_ratio >= pinbar_min_wick_ratio`
- `close_position <= 0.45`

Ý nghĩa:

- Giá bị đẩy lên trên nhưng bị bán xuống lại.
- Dùng tốt hơn khi xuất hiện tại resistance, supply OB, bearish FVG hoặc sau liquidity sweep high.

Output:

```text
point_type = pinbar_bearish
direction = down
price = close
```

## Engulfing

Detector dùng body engulfing, không yêu cầu wick engulfing.

Body bounds:

```text
body_low = min(open, close)
body_high = max(open, close)
```

Điều kiện chung:

- Body của nến hiện tại bao trùm body của nến trước:

```text
current_body_low <= previous_body_low
current_body_high >= previous_body_high
```

- `current_body_ratio >= engulfing_min_body_ratio`

### Bullish Engulfing

Điều kiện:

- Nến trước bearish.
- Nến hiện tại bullish.
- Thỏa điều kiện body engulfing.

Output:

```text
point_type = engulfing_bullish
direction = up
price = current.close
```

### Bearish Engulfing

Điều kiện:

- Nến trước bullish.
- Nến hiện tại bearish.
- Thỏa điều kiện body engulfing.

Output:

```text
point_type = engulfing_bearish
direction = down
price = current.close
```

## Marubozu

Marubozu là nến thân rất lớn, wick nhỏ, thể hiện momentum rõ.

Điều kiện:

- `body_ratio >= marubozu_min_body_ratio`
- `upper_wick_ratio <= 0.15`
- `lower_wick_ratio <= 0.15`

Output:

```text
point_type = marubozu_bullish nếu close > open
point_type = marubozu_bearish nếu close < open
direction = up/down theo màu nến
price = close
```

Ghi chú:

- Marubozu cùng hướng H1 bias có thể dùng như confirmation continuation.
- Marubozu ngược hướng tại vùng mạnh có thể là tín hiệu displacement/CHOCH sớm, nhưng strategy cần thêm filter.

## Morning Star / Evening Star

Detector dùng pattern 3 nến.

### Morning Star

Điều kiện:

- Nến 1 bearish.
- `nến 1 body_ratio >= star_large_body_ratio`
- `nến 2 body_ratio <= star_small_body_ratio`
- Nến 3 bullish.
- `nến 3 body_ratio >= star_large_body_ratio`
- Nến 3 đóng trên midpoint body của nến 1:

```text
third.close >= (first.open + first.close) / 2
```

Output:

```text
point_type = morning_star
direction = up
price = third.close
```

### Evening Star

Điều kiện:

- Nến 1 bullish.
- `nến 1 body_ratio >= star_large_body_ratio`
- `nến 2 body_ratio <= star_small_body_ratio`
- Nến 3 bearish.
- `nến 3 body_ratio >= star_large_body_ratio`
- Nến 3 đóng dưới midpoint body của nến 1:

```text
third.close <= (first.open + first.close) / 2
```

Output:

```text
point_type = evening_star
direction = down
price = third.close
```

## Displacement Candle

Displacement candle là nến range lớn so với ATR trước đó, thân nến đủ lớn để tránh nhận nhầm wick noise.

ATR dùng candles trước nến hiện tại, không dùng chính nến đang detect để tránh look-ahead bias.

Điều kiện:

```text
atr = ATR(candles_before_current, atr_period)
range_atr = current_range / atr

range_atr >= displacement_atr_multiplier
body_ratio >= displacement_body_ratio
```

Output:

```text
point_type = displacement_bullish nếu close > open
point_type = displacement_bearish nếu close < open
direction = up/down theo màu nến
price = close
metadata.range_atr = range_atr
metadata.atr_at_detection = atr
```

## Confidence

Confidence hiện là heuristic nhẹ để ranking/debug, chưa phải xác suất thắng.

Tư duy chung:

- Pinbar tăng confidence theo wick ratio.
- Engulfing tăng confidence theo body ratio và tỷ lệ body hiện tại so với body trước.
- Marubozu tăng confidence theo body ratio.
- Star tăng confidence khi nến 3 mạnh và nến giữa nhỏ.
- Displacement tăng confidence theo `range_atr` và `body_ratio`.

Strategy Engine sau này không nên dùng confidence đơn lẻ để vào lệnh. Nó phải kết hợp:

- H1 bias.
- H1 regime.
- Zone confluence.
- M15 price action direction.
- RR tối thiểu.
- Risk guardrails.

## CLI

Detect và lưu event M15:

```bash
python -m semi_bot_trading.cli detect-price-action --timeframe M15
```

Override tham số khi test:

```bash
python -m semi_bot_trading.cli detect-price-action \
  --timeframe M15 \
  --displacement-atr-multiplier 1.8 \
  --pinbar-wick-body-ratio 2.5
```

## Giới Hạn Hiện Tại

- Chưa filter theo H1 bias trực tiếp trong detector. Filter này thuộc Strategy Engine.
- Chưa yêu cầu pattern nằm trong/ở gần H1 zone. Điều kiện location cũng thuộc Strategy Engine.
- Morning/evening star chưa yêu cầu gap thật vì forex/gold thường ít gap liên tục như stock.
- Chưa vẽ riêng marker price action trên chart để tránh UI rối; dữ liệu đã được lưu để Strategy Engine dùng.
