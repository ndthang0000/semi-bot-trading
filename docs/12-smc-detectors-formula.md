# 12 - SMC Detectors Formula

File này mô tả cách bot hiện tại tính các detector SMC mới trong code:

- Fair Value Gap: `fvg_v1`
- Order Block: `order_block_v1`
- Liquidity Sweep: `liquidity_v1`
- Consolidation / Range: `consolidation_v1`

Mục tiêu của file này là ghi lại công thức thực tế đang được implement, để sau này có thể review, tinh chỉnh threshold, hoặc thay thế bằng version mới.

Source code chính: `semi_bot_trading/smc_zones.py`.

## 1. Nguyên tắc chung

Các detector này tạo entity dạng `PriceZone` và lưu vào bảng `price_zones`.

Các field quan trọng:

- `detector`: version detector, ví dụ `fvg_v1`.
- `zone_type`: loại vùng UI sẽ vẽ, ví dụ `fvg`, `order_block`, `liquidity_pool`, `consolidation`.
- `direction`: `bullish`, `bearish`, hoặc `neutral`.
- `price_low`, `price_high`: biên giá của vùng.
- `start_time`: thời điểm vùng bắt đầu hình thành trên chart.
- `detected_at`: thời điểm bot xác nhận vùng.
- `end_time`: thời điểm vùng hết hiệu lực hoặc bị consume/break.
- `status`: trạng thái vùng.
- `bot_confidence`: độ tự tin của bot.
- `bot_weight`: trọng số ban đầu của bot.
- `effective_confidence`, `effective_weight`: trọng số cuối cùng sau lifecycle, mitigation, invalidation.
- `metadata`: debug data chi tiết.

Trong replay mode, các detector này được tính lại bằng candles từ `replay_start` đến `replay_at`. Không dùng zone đã precompute trong database, để giảm look-ahead bias.

## 2. Fair Value Gap

Detector id: `fvg_v1`

Zone type: `fvg`

### 2.1. Input

Dùng chuỗi candle theo timeframe đang xem, hiện chủ yếu là `H1` hoặc `M15`.

Detector chạy theo cụm 3 nến:

```text
candle 1 = candles[i - 2]
candle 2 = candles[i - 1]
candle 3 = candles[i]
```

Candle 2 phải là impulse candle tương đối mạnh theo ATR, và gap value cũng phải đủ lớn so với ATR.

### 2.2. Điều kiện impulse candle

ATR baseline được tính bằng các candle trước cây middle:

```text
atr_value = ATR(candles trước candle2, period = 14)
```

Lý do: nếu lấy ATR bao gồm chính cây middle, cây displacement lớn sẽ tự làm ATR phình lên và làm rule kém nhạy.

```text
middle_body_ratio = abs(candle2.close - candle2.open) / (candle2.high - candle2.low)
middle_range_atr = (candle2.high - candle2.low) / atr_value
```

Điều kiện hiện tại:

```text
middle_body_ratio >= 0.50
middle_range_atr >= fvg_middle_candle_atr_multiplier
```

Default:

```text
fvg_middle_candle_atr_multiplier = 2.0
```

Nếu `candle2.high == candle2.low`, hoặc không có đủ ATR baseline, bỏ qua cụm này.

### 2.3. Điều kiện follow-through của candle 3

Sau khi candle 2 tạo displacement, candle 3 phải xác nhận rằng imbalance vẫn đi theo hướng đó, thay vì hồi ngược ngay lập tức.

```text
third_body_ratio = abs(candle3.close - candle3.open) / (candle3.high - candle3.low)
```

Default:

```text
fvg_third_candle_follow_through_required = true
fvg_third_candle_min_body_ratio = 0.20
```

Rule:

```text
Bullish FVG:
    candle3.close > candle3.open
    third_body_ratio >= fvg_third_candle_min_body_ratio

Bearish FVG:
    candle3.close < candle3.open
    third_body_ratio >= fvg_third_candle_min_body_ratio
```

Lý do: nếu candle 3 tạo gap nhưng đóng ngược hướng ngay, đó thường là imbalance chất lượng thấp hoặc bị fill quá nhanh. Rule này không dùng dữ liệu tương lai sau candle 3, nên replay/backtest vẫn không bị look-ahead.

### 2.4. Bullish FVG

```text
candle3.low > candle1.high
gap_size = candle3.low - candle1.high
gap_atr_ratio = gap_size / atr_value
gap_atr_ratio >= fvg_gap_atr_ratio
gap_atr_ratio >= fvg_min_width_atr_ratio
```

Default:

```text
fvg_gap_atr_ratio = 0.25
fvg_min_width_atr_ratio = 1.0
fvg_max_width_atr_ratio = 2.0
```

Vùng được tạo:

```text
direction = bullish
price_low = candle1.high
price_high = candle3.low
start_time = candle3.open_time
detected_at = candle3.open_time
```

Nếu FVG quá rộng so với ATR, detector sẽ thu nhỏ vùng theo phía có lợi cho entry:

```text
max_width = fvg_max_width_atr_ratio * atr_value

Bullish FVG quá rộng:
    price_high = price_low + max_width

Bearish FVG quá rộng:
    price_low = price_high - max_width
```

Lý do: full H1 FVG đôi khi quá lớn, làm stop loss và target 2R bị kéo rất xa so với nhịp M15. Metadata vẫn lưu `original_gap_low`, `original_gap_high`, `original_gap_size`, `max_width_atr_ratio`, và `shrunk_for_entry` để debug hoặc revert về full-width sau này.

### 2.5. Bearish FVG

```text
candle3.high < candle1.low
gap_size = candle1.low - candle3.high
gap_atr_ratio = gap_size / atr_value
gap_atr_ratio >= fvg_gap_atr_ratio
gap_atr_ratio >= fvg_min_width_atr_ratio
```

Vùng được tạo:

```text
direction = bearish
price_low = candle3.high
price_high = candle1.low
start_time = candle3.open_time
detected_at = candle3.open_time
```

### 2.6. Consequent Encroachment

CE 50% được lưu trong metadata:

```text
consequent_encroachment = (price_low + price_high) / 2
```

Hiện CE chỉ là metadata để debug/confluence sau này, chưa dùng để tự invalid zone.

### 2.7. Fill ratio

FVG bullish:

```text
width = price_high - price_low
fill_ratio = (price_high - max(candle.low, price_low)) / width
```

Chỉ tính khi candle sau đó có `candle.low < price_high`.

FVG bearish:

```text
width = price_high - price_low
fill_ratio = (min(candle.high, price_high) - price_low) / width
```

Chỉ tính khi candle sau đó có `candle.high > price_low`.

Bot lấy fill ratio lớn nhất kể từ sau khi FVG được tạo.

### 2.8. Lifecycle

Default:

```text
partial_fill_threshold = 0.50
fill_threshold = 0.95
H1 max_active_days = 2
H1 decay_start_days = 0.75
M15 max_active_days = 1
M15 decay_start_days = 0.5
```

Nếu:

```text
fill_ratio >= 0.80
```

Thì:

```text
status = mitigated
end_time = fill_time
invalidated_at = fill_time
effective_weight = bot_weight * 0.25
effective_confidence = bot_confidence * 0.70
metadata.fill_state = filled
```

Nếu:

```text
0.50 <= fill_ratio < 0.80
```

Thì:

```text
status = active
effective_weight = bot_weight * 0.60
effective_confidence = bot_confidence * 0.85
metadata.fill_state = partial
```

Nếu:

```text
fill_ratio < 0.50
```

Thì:

```text
status = active
metadata.fill_state = open
```

Nếu FVG chưa filled nhưng tuổi vùng vượt `max_active_days`:

```text
status = expired
end_time = detected_at + max_active_days
valid_until = end_time
effective_weight = effective_weight * 0.20
effective_confidence = effective_confidence * 0.80
metadata.expired_rule = smc_zone_max_active_days
```

Nếu FVG chưa expired nhưng đã qua `decay_start_days`, weight giảm tuyến tính tới còn tối thiểu 50% trước lúc expired:

```text
decay_progress = (age_days - decay_start_days) / (max_active_days - decay_start_days)
age_decay_multiplier = 1 - min(decay_progress, 1) * 0.50
effective_weight = effective_weight * age_decay_multiplier
effective_confidence = effective_confidence * max(age_decay_multiplier, 0.80)
```

Metadata lifecycle:

```text
max_active_days
decay_start_days
expires_at
age_days_at_evaluation
age_decay_multiplier
```

### 2.8. Confidence và weight

```text
width = price_high - price_low

confidence = min(
  0.40
  + middle_body_ratio * 0.25
  + min(middle_range_atr, 3.0) * 0.08,
  0.92
)

weight = min(
  0.35
  + min(gap_atr_ratio, 1.0) * 0.20
  + min(middle_range_atr, 3.0) * 0.08,
  0.90
)
```

Ý nghĩa:

- Nến giữa càng lớn so với ATR thì confidence/weight càng cao.
- Gap càng lớn so với ATR thì weight càng cao.
- Bonus `middle_range_atr` được cap tại `3 ATR`.
- Bonus `gap_atr_ratio` được cap tại `1 ATR`.

### 2.9. Metadata

```yaml
detector: fvg_v1
middle_candle_time: ...
middle_body_ratio: ...
middle_range_atr: ...
gap_size: ...
gap_atr_ratio: ...
atr_at_detection: ...
consequent_encroachment: ...
fill_ratio: ...
fill_state: open | partial | filled
```

### 2.10. Hạn chế hiện tại

- Chưa lọc FVG theo H1 bias.
- Chưa yêu cầu FVG phải xuất hiện sau BOS/CHOCH.
- Chưa có confluence score với SR/OB/liquidity.
- `min_middle_body_ratio = 0.50` vẫn hardcode trong code, nếu cần tuning thêm thì nên đưa ra config.

## 3. Order Block

Detector id: `order_block_v1`

Zone type: `order_block`

### 3.1. Input

Dùng candle theo timeframe đang xem.

Ý tưởng hiện tại:

- Tìm displacement candle.
- Displacement candle phải phá swing structure gần nhất theo đúng hướng.
- Tìm last opposite candle trước displacement.
- Lấy body của last opposite candle làm OB chính.
- Lọc OB quá mỏng/quá rộng theo ATR.
- Merge bớt các OB cùng hướng bị overlap mạnh.

### 3.2. Displacement candle

Với candle tại index `i`:

```text
candle_range = candle.high - candle.low
body_ratio = abs(candle.close - candle.open) / candle_range
atr_value = ATR(candles trước candle i, period = 14)
```

Điều kiện:

```text
candle_range >= atr_value * ob_displacement_atr_multiplier
body_ratio >= ob_min_body_ratio
```

Default:

```text
atr_period = 14
ob_displacement_atr_multiplier = 1.5
ob_min_body_ratio = 0.60
lookback_candles = 3
```

Nếu ATR chưa đủ dữ liệu hoặc candle range bằng 0, bỏ qua. ATR không bao gồm chính displacement candle để tránh candle lớn tự làm ATR phình lên.

### 3.3. Direction

```text
if candle.close > candle.open:
  direction = bullish
else:
  direction = bearish
```

### 3.4. Structure break bắt buộc

Default:

```text
ob_require_structure_break = true
```

Bullish OB chỉ hợp lệ nếu displacement close phá swing high gần nhất:

```text
candle.close > recent_swing_high.price
```

Bearish OB chỉ hợp lệ nếu displacement close phá swing low gần nhất:

```text
candle.close < recent_swing_low.price
```

Bot hiện kiểm tra tối đa 5 swing gần nhất đúng loại trước thời điểm displacement. Swing bị phá được lưu vào metadata.

### 3.5. Last opposite candle

Bot nhìn ngược tối đa 3 candle trước displacement:

```text
candidates = candles[i - lookback_candles : i]
```

Bullish OB:

```text
direction = bullish
candidate candle phải là nến giảm: close < open
```

Bearish OB:

```text
direction = bearish
candidate candle phải là nến tăng: close > open
```

Bot chọn candle opposite gần displacement nhất.

Nếu không tìm được opposite candle, bot bỏ qua. Không còn fallback dùng candle ngay trước displacement.

Để tránh spam trùng vùng:

```text
dedupe key = (candidate.open_time, direction)
```

### 3.6. Vùng giá OB

Vùng chính lấy theo body:

```text
body_low = min(candidate.open, candidate.close)
body_high = max(candidate.open, candidate.close)
```

Vùng được tạo:

```text
price_low = body_low
price_high = body_high
start_time = candidate.open_time
valid_from = displacement.open_time
detected_at = displacement.open_time
```

Wick chỉ lưu metadata:

```text
wick_extension_low = candidate.low
wick_extension_high = candidate.high
```

### 3.7. Width filter theo ATR

```text
body_width = body_high - body_low
body_width_atr = body_width / atr_value
```

Default:

```text
ob_min_width_atr_ratio = 0.05
ob_max_width_atr_ratio = 1.0
```

Điều kiện:

```text
0.05 <= body_width_atr <= 1.0
```

Ý nghĩa:

- OB quá mỏng bị bỏ qua vì dễ chỉ là noise/line.
- OB quá rộng bị bỏ qua vì khó trade với RR tốt.

### 3.8. Mitigation ratio

Bullish OB:

```text
if future_candle.low <= price_high and future_candle.high >= price_low:
  mitigation_ratio = (price_high - max(future_candle.low, price_low)) / width
```

Bearish OB:

```text
if future_candle.high >= price_low and future_candle.low <= price_high:
  mitigation_ratio = (min(future_candle.high, price_high) - price_low) / width
```

Bot lấy mitigation ratio lớn nhất sau khi OB được tạo.

### 3.9. Invalidation

Bullish OB bị invalidated khi:

```text
future_candle.close < price_low
```

Bearish OB bị invalidated khi:

```text
future_candle.close > price_high
```

Khi invalidated:

```text
status = invalidated
end_time = invalidated_at
effective_weight = bot_weight * 0.15
effective_confidence = bot_confidence * 0.65
metadata.invalidated_rule = close beyond order block body
```

### 3.10. Lifecycle theo mitigation

Default:

```text
H1 max_active_days = 3
H1 decay_start_days = 1
M15 max_active_days = 2
M15 decay_start_days = 1
```

Nếu không invalidated và:

```text
mitigation_ratio >= 0.80
```

Thì:

```text
status = mitigated
end_time = mitigation_time
invalidated_at = mitigation_time
effective_weight = bot_weight * 0.30
effective_confidence = bot_confidence * 0.75
metadata.mitigation_state = full
```

Nếu:

```text
0.50 <= mitigation_ratio < 0.80
```

Thì:

```text
status = active
effective_weight = bot_weight * 0.65
effective_confidence = bot_confidence * 0.88
metadata.mitigation_state = partial
```

Nếu:

```text
mitigation_ratio < 0.50
```

Thì:

```text
status = active
metadata.mitigation_state = fresh
```

Nếu OB chưa mitigated/invalidated nhưng tuổi vùng vượt `max_active_days`:

```text
status = expired
end_time = detected_at + max_active_days
valid_until = end_time
effective_weight = effective_weight * 0.20
effective_confidence = effective_confidence * 0.80
metadata.expired_rule = smc_zone_max_active_days
```

Nếu OB chưa expired nhưng đã qua `decay_start_days`, weight giảm tuyến tính tới còn tối thiểu 50% trước lúc expired. Công thức giống FVG.

### 3.11. Merge overlapping OB

Default:

```text
ob_merge_overlap_ratio = 0.60
```

Hai OB cùng direction được xem là trùng/chồng nếu:

```text
overlap / smaller_width >= 0.60
```

Khi overlap, bot giữ vùng có rank tốt hơn:

```text
rank = (status_rank, effective_weight, detected_at)
```

Trong đó:

```text
active > mitigated > invalidated
```

### 3.12. Confidence và weight

```text
displacement_range_atr = displacement_range / atr_value
structure_break_bonus = 0.12 nếu có broken_swing

confidence = min(
  0.42
  + body_ratio * 0.24
  + min(displacement_range_atr, 2.5) * 0.08
  + structure_break_bonus,
  0.94
)

weight = min(
  0.36
  + body_ratio * 0.18
  + min(displacement_range_atr, 2.5) * 0.10
  + structure_break_bonus,
  0.94
)
```

Ý nghĩa:

- Displacement càng lớn so với ATR thì OB càng đáng chú ý.
- Body displacement càng rõ thì confidence càng cao.
- OB phá structure được cộng bonus.
- Bonus displacement được cap tại `2.5 ATR`.

### 3.13. Metadata

```yaml
detector: order_block_v1
definition: last opposite candle body before displacement that breaks structure
candidate_time: ...
displacement_time: ...
displacement_range_atr: ...
displacement_body_ratio: ...
body_zone_low: ...
body_zone_high: ...
body_width_atr: ...
wick_extension_low: ...
wick_extension_high: ...
broken_swing_id: ...
broken_swing_type: high | low
broken_swing_price: ...
broken_swing_time: ...
mitigation_ratio: ...
mitigation_state: fresh | partial | full
invalidated_rule: close beyond order block body
```

### 3.14. Hạn chế hiện tại

- Chưa lọc OB theo HTF bias.
- Chưa kiểm tra OB nằm trong premium/discount.
- Structure break hiện dùng swing high/low gần nhất, chưa map trực tiếp tới stored BOS/CHOCH event.
- Chưa có confluence score với FVG/SR/liquidity.

## 4. Liquidity Sweep

Detector id: `liquidity_v1`

Zone type: `liquidity_pool`

### 4.1. Input

Dùng:

- Candles theo timeframe đang xem.
- Swing points đã detect từ market structure.

### 4.2. Buy-side sweep

Với swing high:

```text
future_candle.high > swing.price
future_candle.close < swing.price
```

Khi xảy ra:

```text
direction = bearish
sweep_type = buy_side_sweep
```

Ý nghĩa: giá quét liquidity phía trên swing high rồi đóng lại dưới level.

### 4.3. Sell-side sweep

Với swing low:

```text
future_candle.low < swing.price
future_candle.close > swing.price
```

Khi xảy ra:

```text
direction = bullish
sweep_type = sell_side_sweep
```

Ý nghĩa: giá quét liquidity phía dưới swing low rồi đóng lại trên level.

### 4.4. Vùng giá liquidity pool

Bot vẽ một vùng mỏng quanh swing price:

```text
atr_value = ATR(candles_to_sweep, 14)
fallback_atr = max(swing.price * 0.0005, 1.0)
half_width = max(atr_value * 0.12, swing.price * 0.0002, 0.5)
```

Vùng được tạo:

```text
price_low = swing.price - half_width
price_high = swing.price + half_width
start_time = swing.event_time
end_time = sweep_candle.open_time
valid_from = swing.event_time
valid_until = sweep_candle.open_time
detected_at = sweep_candle.open_time
status = swept
```

### 4.5. Confidence và weight

```text
confidence = 0.72 nếu sweep candle có body
confidence = 0.64 nếu sweep candle gần như không có body
bot_weight = 0.70
effective_weight = bot_weight * 0.55
```

Lý do effective weight thấp hơn bot weight: liquidity đã bị sweep/consume, nên dùng như context sau khi xảy ra, không phải active zone để chờ giá quay lại.

### 4.6. Metadata

```yaml
detector: liquidity_v1
swing_point_id: ...
swing_type: high | low
sweep_type: buy_side_sweep | sell_side_sweep
sweep_time: ...
swept_level: ...
sweep_close_reclaim: ...
atr_at_sweep: ...
```

### 4.7. Hạn chế hiện tại

- Chưa group equal highs/equal lows thành liquidity pool trước khi sweep.
- Chưa yêu cầu sweep xảy ra tại vùng H1 quan trọng.
- Chưa chấm điểm theo số lần touch liquidity level.
- Chưa kết hợp confirmation M15 như engulfing/pinbar/BOS sau sweep.

## 5. Consolidation / Range

Detector id: `consolidation_v1`

Zone type: `consolidation`

### 5.1. Input

Dùng candles theo timeframe đang xem.

Detector chạy sliding window.

Default:

```text
min_candles = 12
max_candles = 36
max_width_atr = 4.0
max_efficiency = 0.35
min_touches = 4
max_zones = 30
```

### 5.2. Sliding window

Bot duyệt từng đoạn candle:

```text
window_size từ 12 đến 36 candles
candidate = candles[start:index]
```

Trong mỗi vị trí, nếu nhiều window hợp lệ, bot giữ `best_zone` cuối cùng tìm được trong vòng lặp window.

Sau khi tìm được một consolidation zone, bot nhảy index:

```text
index = best_end + max(3, min_candles / 3)
```

Mục tiêu: giảm spam quá nhiều vùng gần nhau.

### 5.3. Range high/low

```text
range_high = max(candle.high for candle in window)
range_low = min(candle.low for candle in window)
width = range_high - range_low
```

### 5.4. ATR trung bình trong window

```text
atr_value = average(true_range(candle_i, previous_close))
```

Nếu `atr_value <= 0`, bỏ qua.

### 5.5. Width filter

Điều kiện range không được quá rộng so với ATR:

```text
width <= atr_value * max_width_atr
```

Default:

```text
max_width_atr = 4.0
```

### 5.6. Range efficiency

```text
travel = sum(true_range của từng candle trong window)
range_efficiency = abs(last_close - first_close) / travel
```

Điều kiện:

```text
range_efficiency <= 0.35
```

Ý nghĩa:

- Nếu giá đi rất nhiều nhưng cuối cùng không tiến xa, thị trường đang xoay trong range.
- Nếu efficiency cao, đó giống trend hơn là consolidation.

### 5.7. Touch count

Touch range high:

```text
range_high - candle.high <= width * 0.18
```

Touch range low:

```text
candle.low - range_low <= width * 0.18
```

Điều kiện:

```text
touch_count = high_touches + low_touches
touch_count >= 4
high_touches > 0
low_touches > 0
```

Nghĩa là range phải có phản ứng ở cả hai biên, không chỉ một phía.

### 5.8. Zone được tạo

```text
direction = neutral
price_low = range_low
price_high = range_high
start_time = window[0].open_time
valid_from = window[-1].open_time
detected_at = window[-1].open_time
status = active
```

### 5.9. Breakout

Sau khi zone được tạo, bot nhìn các future candles.

```text
breakout_buffer = width * 0.08
```

Bullish breakout:

```text
future_candle.close > price_high + breakout_buffer
```

Khi đó:

```text
status = broken
direction = bullish
end_time = future_candle.open_time
invalidated_at = future_candle.open_time
effective_weight = bot_weight * 0.45
effective_confidence = bot_confidence * 0.80
metadata.breakout_direction = bullish
metadata.breakout_time = future_candle.open_time
```

Bearish breakout:

```text
future_candle.close < price_low - breakout_buffer
```

Khi đó:

```text
status = broken
direction = bearish
end_time = future_candle.open_time
invalidated_at = future_candle.open_time
effective_weight = bot_weight * 0.45
effective_confidence = bot_confidence * 0.80
metadata.breakout_direction = bearish
metadata.breakout_time = future_candle.open_time
```

### 5.10. Merge vùng gần giống nhau

Sau khi detect xong, bot merge bớt consolidation zones bị overlap mạnh.

Với hai vùng gần nhau:

```text
overlap = min(a.price_high, b.price_high) - max(a.price_low, b.price_low)
smaller_width = min(width_a, width_b)
```

Nếu:

```text
overlap / smaller_width >= 0.60
```

và time overlap hợp lệ, bot giữ vùng có `effective_weight` cao hơn.

### 5.11. Confidence và weight

```text
confidence = min(
  0.40
  + touch_count * 0.04
  + (max_efficiency - range_efficiency) * 0.50,
  0.88
)

weight = min(
  0.35
  + touch_count * 0.035
  + max(0.0, max_width_atr - width / atr_value) * 0.05,
  0.86
)
```

Ý nghĩa:

- Nhiều touch hơn thì confidence/weight tăng.
- Range càng kém hiệu quả theo hướng trend thì confidence tăng.
- Range càng gọn so với ATR threshold thì weight tăng.

### 5.12. Metadata

```yaml
detector: consolidation_v1
window_candles: ...
width_atr: ...
range_efficiency: ...
touch_count: ...
high_touches: ...
low_touches: ...
atr_at_detection: ...
breakout_direction: bullish | bearish
breakout_time: ...
```

### 5.13. Hạn chế hiện tại

- Chưa phân biệt range đẹp và chop/noise xấu.
- Chưa dùng volume hoặc session.
- Chưa dùng equal high/equal low clustering riêng.
- Chưa chuyển consolidation trực tiếp thành regime ranging, hiện regime detector vẫn tách riêng.
- Chưa vẽ touch markers tại high/low của range.

## 6. Config hiện tại

Các giới hạn số lượng detector nằm trong `config/trading.toml`:

```toml
[zones.smc]
max_candles = 5000
lookback_swings = 300
fvg_middle_candle_atr_multiplier = 2.0
fvg_gap_atr_ratio = 0.25
fvg_min_width_atr_ratio = 1.0
fvg_max_width_atr_ratio = 2.0
fvg_third_candle_follow_through_required = true
fvg_third_candle_min_body_ratio = 0.20
ob_displacement_atr_multiplier = 1.5
ob_min_body_ratio = 0.60
ob_min_width_atr_ratio = 0.05
ob_max_width_atr_ratio = 1.0
ob_require_structure_break = true
ob_merge_overlap_ratio = 0.60
max_fvg_zones = 80
max_order_block_zones = 60
max_liquidity_zones = 80
max_consolidation_zones = 30
```

Ý nghĩa:

- `max_candles`: số candle gần nhất dùng để chạy detector khi populate DB bằng CLI.
- `lookback_swings`: số swing gần nhất dùng cho liquidity sweep.
- `fvg_middle_candle_atr_multiplier`: cây middle candle của FVG phải có range lớn hơn ATR bao nhiêu lần.
- `fvg_gap_atr_ratio`: gap value của FVG phải lớn hơn ATR bao nhiêu lần.
- `fvg_min_width_atr_ratio`: FVG quá mỏng so với ATR sẽ không được tạo zone. Default `1.0`, nghĩa là gap phải rộng ít nhất 1 ATR.
- `fvg_max_width_atr_ratio`: FVG quá rộng sẽ được thu nhỏ về tối đa ngưỡng này theo phía có lợi cho entry. Default `1.5`. Set `0` để giữ full-width FVG.
- `fvg_third_candle_follow_through_required`: yêu cầu candle 3 đóng cùng hướng FVG để tránh gap hồi ngược ngay.
- `fvg_third_candle_min_body_ratio`: body tối thiểu của candle 3 khi follow-through được bật.
- `ob_displacement_atr_multiplier`: displacement candle của OB phải lớn hơn ATR bao nhiêu lần.
- `ob_min_body_ratio`: body/range tối thiểu của displacement candle.
- `ob_min_width_atr_ratio`: OB body zone quá mỏng so với ATR sẽ bị bỏ qua.
- `ob_max_width_atr_ratio`: OB body zone quá rộng so với ATR sẽ bị bỏ qua.
- `ob_require_structure_break`: yêu cầu displacement phải phá swing structure.
- `ob_merge_overlap_ratio`: overlap ratio để merge các OB cùng hướng.
- `max_*_zones`: số zone tối đa lưu cho từng detector.

Hiện các threshold nội bộ như `min_middle_body_ratio` của FVG và `max_width_atr` của consolidation vẫn hardcode trong `smc_zones.py`. Nếu sau này cần tuning thường xuyên, nên đưa chúng vào `config/trading.toml`.

## 7. Thứ tự ưu tiên cải tiến

Nên cải tiến theo thứ tự:

1. Đưa các threshold còn lại của FVG/Consolidation ra config.
2. Thêm HTF bias filter cho FVG và OB.
3. Map OB trực tiếp với stored BOS/CHOCH event thay vì chỉ kiểm tra swing break.
4. Group liquidity pool theo equal highs/equal lows trước khi detect sweep.
5. Thêm confluence score: SR + OB + FVG + Liquidity + Bias + Regime.
6. Hiển thị breakdown score trong UI inspector.
7. Thêm replay debug event log: zone nào được tạo ở candle nào, vì sao bị reject.
