# Support / Resistance Formula V2

Tài liệu này mô tả cách detector xác định, chấm điểm, cập nhật và invalidate các vùng Support / Resistance theo hướng **zone-based + reaction-quality-based**.

Mục tiêu của V2:

- Không chỉ đếm số lần giá chạm zone.
- Phân biệt touch tốt và touch yếu.
- Tăng weight cho vùng có phản ứng thật sự mạnh.
- Giảm weight cho vùng bị test quá nhiều nhưng không còn phản ứng.
- Dùng ATR để scale zone width theo volatility.
- Tách score thành các thành phần rõ ràng, dễ debug và optimize.

Code chính:

```text
semi_bot_trading/zones.py
```

Config chính:

```text
config/trading.toml
```

---

## 1. Input

SR detector không đọc trực tiếp từ toàn bộ candle để tạo zone ban đầu. Nó lấy input chính từ các swing đã được market structure detector xác nhận.

- `Swing High` dùng để tạo `resistance`.
- `Swing Low` dùng để tạo `support`.
- Swing hiện tại được lấy từ detector `swing_v1`.
- Timeframe MVP chủ yếu là `H1`.

Config đề xuất:

```toml
[zones.support_resistance]
detector = "sr_v2"
tolerance_pct = 0.0005
min_zone_width = 1.0
atr_width_multiplier = 0.25
min_touches = 2
lookback_swings = 300
max_zones = 40
```

Ý nghĩa:

- `tolerance_pct`: khoảng sai số theo phần trăm giá để gom swing gần nhau.
- `min_zone_width`: độ rộng tối thiểu của vùng.
- `atr_width_multiplier`: dùng ATR để tránh zone quá hẹp hoặc quá rộng.
- `min_touches`: số swing tối thiểu trong một cụm để tạo zone.
- `lookback_swings`: số swing gần nhất được đưa vào detector.
- `max_zones`: số vùng tối đa trả về.

---

## 2. Gom Swing Thành Cụm

Detector tách riêng swing high và swing low:

```text
resistance_candidates = all swings where swing_type == "high"
support_candidates    = all swings where swing_type == "low"
```

Các swing được sort theo giá tăng dần. Mỗi swing được so với center của từng cluster hiện có.

Công thức tolerance V2:

```text
raw_pct_width = cluster_center * tolerance_pct
atr_width     = ATR(14) * atr_width_multiplier

tolerance = max(raw_pct_width, atr_width, min_zone_width)
```

Nếu:

```text
abs(swing_price - cluster_center) <= tolerance
```

thì swing đó được thêm vào cluster hiện tại.

Nếu không match cluster nào, bot tạo cluster mới.

Lý do dùng ATR:

- XAUUSD có volatility thay đổi rất mạnh theo từng giai đoạn.
- Fixed percentage có thể tạo zone quá rộng khi giá cao.
- ATR giúp zone phản ánh volatility hiện tại tốt hơn.

---

## 3. Điều Kiện Tạo Zone

Một cluster chỉ trở thành zone khi:

```text
len(cluster.points) >= min_touches
```

Config mặc định:

```text
min_touches = 2
```

Tức là ít nhất 2 swing high gần nhau mới tạo resistance, hoặc ít nhất 2 swing low gần nhau mới tạo support.

---

## 4. Công Thức Biên Zone

Với mỗi cluster hợp lệ:

```text
prices = all swing prices in cluster
center = average(prices)

raw_pct_width = center * tolerance_pct
atr_width     = ATR(14) * atr_width_multiplier
half_width    = max(raw_pct_width, atr_width, min_zone_width)

price_low  = min(prices) - half_width
price_high = max(prices) + half_width
```

Zone metadata nên lưu:

```text
center
half_width
atr_at_detection
tolerance_pct
atr_width_multiplier
min_zone_width
swing_point_ids
swing_point_times
swing_point_prices
```

Zone time:

```text
start_time  = first swing time in cluster
valid_from  = last swing time in cluster, after min_touches is satisfied
detected_at = last swing time in cluster
end_time    = null until invalidated
```

`start_time` chỉ là mốc trực quan để nhìn zone bắt nguồn từ đâu. Bot không được dùng zone để tạo setup trước `detected_at`.

Zone type:

```text
if cluster.swing_type == "high":
    zone_type = "resistance"
    direction = "bearish"

if cluster.swing_type == "low":
    zone_type = "support"
    direction = "bullish"
```

### 4.1. Dedupe Khi Materialize Realtime

Khi chạy `materialize-zones`, hệ thống đi từng snapshot nến đã đóng để lưu zone lịch sử vào DB cho realtime dashboard. Cùng một cụm swing có thể sinh ra biên zone lệch nhẹ giữa các snapshot do ATR/window/lifecycle thay đổi. Vì `PriceZone.id` có chứa `price_low` và `price_high`, các biến thể gần giống nhau này có thể trở thành nhiều row khác nhau trong DB.

Để tránh chart vẽ chồng nhiều vùng SR gần như cùng một level, materializer có bước dedupe riêng cho `sr_v2` trước khi ghi DB:

```text
same symbol + timeframe + detector + zone_type + direction
AND (
  swing cluster giống nhau
  OR overlap_ratio >= 0.70
  OR center_distance <= max(zone_width) * 0.65
)
```

Khi merge, bot giữ zone có rank tốt nhất:

```text
active trước invalidated
effective_weight cao hơn
materialized_seen_count cao hơn
zone width hẹp hơn
```

Bot không mở rộng biên zone khi merge để tránh làm SR rộng thêm. Metadata của zone giữ lại sẽ có:

```text
deduped_materialized_zone_count
deduped_materialized_zone_ids
materialized_seen_count
```

---

## 5. Touch Detection

V1 chỉ tính touch khi candle overlap zone:

```text
candle.high >= zone.price_low
and
candle.low <= zone.price_high
```

V2 vẫn dùng overlap để detect touch ban đầu, nhưng phải phân loại touch.

---

## 6. Touch Classification

Mỗi lần candle chạm zone, phân loại thành các nhóm sau.

### 6.1. Wick Touch

Giá chỉ râu nến chạm zone, body đóng ngoài zone.

Support wick touch:

```text
candle.low <= zone.price_high
AND candle.close > zone.price_high
```

Resistance wick touch:

```text
candle.high >= zone.price_low
AND candle.close < zone.price_low
```

Ý nghĩa:

- Có rejection.
- Nếu follow-through tốt thì đây là touch chất lượng.

---

### 6.2. Body Touch

Body candle đi vào zone.

```text
body_low  = min(candle.open, candle.close)
body_high = max(candle.open, candle.close)

body_high >= zone.price_low
AND body_low <= zone.price_high
```

Ý nghĩa:

- Giá đã accept một phần trong zone.
- Không xấu tuyệt đối, nhưng kém hơn wick rejection.

---

### 6.3. Close Inside Zone

Candle đóng cửa bên trong zone.

```text
zone.price_low <= candle.close <= zone.price_high
```

Ý nghĩa:

- Market đang cân bằng tại zone.
- Nếu linger lâu, zone yếu dần.

---

### 6.4. Clean Rejection Touch

Touch được xem là clean rejection nếu:

Support:

```text
candle.low <= zone.price_high
AND candle.close > zone.price_high
AND lower_wick >= body * 1.5
AND close_position >= 0.60
```

Resistance:

```text
candle.high >= zone.price_low
AND candle.close < zone.price_low
AND upper_wick >= body * 1.5
AND close_position <= 0.40
```

Trong đó:

```text
range = candle.high - candle.low
body  = abs(candle.close - candle.open)

close_position = (candle.close - candle.low) / range
```

---

## 7. Reaction Quality After Touch

Đây là phần quan trọng nhất của V2.

Một zone không mạnh chỉ vì được chạm nhiều lần. Zone mạnh khi sau touch có phản ứng tốt.

Reaction được đo trong `reaction_window_candles`.

Config đề xuất:

```toml
[zones.reaction]
reaction_window_candles = 5
min_reaction_atr = 0.8
strong_reaction_atr = 1.5
follow_through_close_required = true
```

---

## 8. Reaction Metrics

### 8.1. Bounce Distance

Support:

```text
bounce_distance = max(high of next N candles) - touch_low
```

Resistance:

```text
bounce_distance = touch_high - min(low of next N candles)
```

Chuẩn hóa theo ATR:

```text
bounce_atr = bounce_distance / ATR(14)
```

Score:

```text
if bounce_atr >= strong_reaction_atr:
    reaction_score += 0.20
elif bounce_atr >= min_reaction_atr:
    reaction_score += 0.10
else:
    reaction_score -= 0.08
```

---

### 8.2. Displacement After Touch

Displacement là phản ứng mạnh sau khi chạm zone.

Support bullish displacement:

```text
next_candle.close > next_candle.open
AND body_size >= avg_body_20 * 1.3
AND close_position >= 0.70
```

Resistance bearish displacement:

```text
next_candle.close < next_candle.open
AND body_size >= avg_body_20 * 1.3
AND close_position <= 0.30
```

Score:

```text
if displacement_after_touch:
    reaction_score += 0.20
```

---

### 8.3. Momentum Follow-Through

Sau touch, giá phải tiếp tục đi đúng hướng ít nhất vài candle.

Support:

```text
close_after_N > touch_candle.close
```

Resistance:

```text
close_after_N < touch_candle.close
```

Score:

```text
if momentum_follow_through:
    reaction_score += 0.15
else:
    reaction_score -= 0.05
```

---

### 8.4. Wick Absorption

Wick absorption thể hiện giá quét vào zone nhưng bị đẩy ngược ra.

Support:

```text
lower_wick / range >= 0.45
AND close_position >= 0.60
```

Resistance:

```text
upper_wick / range >= 0.45
AND close_position <= 0.40
```

Score:

```text
if wick_absorption:
    reaction_score += 0.12
```

---

### 8.5. Clean Rejection

Clean rejection là touch nhanh, reject rõ, không linger.

Điều kiện:

```text
touch_duration_candles <= 2
AND clean_rejection_touch == true
```

Score:

```text
if clean_rejection:
    reaction_score += 0.12
```

Nếu giá nằm trong zone quá lâu:

```text
if touch_duration_candles >= 4:
    reaction_score -= 0.10
```

---

## 9. Level Decay

Một zone không phải càng nhiều touch càng mạnh mãi mãi.

V2 dùng logic:

- Touch đầu tiên và thứ hai thường có giá trị cao.
- Từ touch thứ ba trở đi, nếu phản ứng yếu thì zone bắt đầu bị consume.
- Nếu giá linger lâu trong zone, zone yếu.
- Nếu breakout mạnh khỏi zone, zone bị invalidated hoặc chuyển trạng thái.

Config đề xuất:

```toml
[zones.decay]
max_healthy_touches = 3
weak_touch_penalty = 0.08
too_many_touches_penalty = 0.06
linger_penalty = 0.10
```

Công thức:

```text
if touch_count_total > max_healthy_touches:
    weight -= (touch_count_total - max_healthy_touches) * too_many_touches_penalty
```

Nếu touch gần nhất có reaction yếu:

```text
if latest_reaction_score < 0:
    weight -= weak_touch_penalty
```

---

## 10. Zone Weight V2

Không dùng một công thức weight đơn giản dựa chủ yếu vào touch count nữa.

Công thức đề xuất:

```text
weight =
    base_score
  + touch_score
  + recency_score
  + reaction_score
  + confluence_score
  - age_penalty
  - mitigation_penalty
  - overtest_penalty
  - invalidation_penalty
```

Sau đó clamp:

```text
weight = min(max(weight, 0.05), 1.0)
```

---

## 11. Weight Components

### 11.1. Base Score

```text
base_score = 0.25
```

---

### 11.2. Touch Score

Touch score không nên tăng vô hạn.

```text
touch_score = min(touch_count_total * 0.06, 0.24)
```

---

### 11.3. Recency Score

Nếu zone có touch gần đây:

```text
if latest_index - last_touch_index <= recent_touch_lookback_candles:
    recency_score = 0.12
else:
    recency_score = 0.00
```

---

### 11.4. Reaction Score

Reaction score là tổng các reaction quality gần đây, nhưng nên giới hạn.

```text
reaction_score = clamp(avg_recent_reaction_score, -0.20, 0.35)
```

Chỉ lấy các touch gần đây nhất, ví dụ:

```text
recent_reaction_count = 3
```

---

### 11.5. Confluence Score

Confluence có thể thêm sau.

Ví dụ:

```text
if zone aligns with HTF bias:
    confluence_score += 0.08

if zone near EMA50 or EMA200:
    confluence_score += 0.04

if zone aligns with Fibonacci pullback:
    confluence_score += 0.05

if zone near session high/low:
    confluence_score += 0.05
```

Clamp:

```text
confluence_score = min(confluence_score, 0.15)
```

---

### 11.6. Age Penalty

```text
age_candles = number of candles from zone.detected_at to latest_time
age_penalty = (age_candles / 100.0) * age_decay_per_100_candles
```

Config:

```toml
[zones.lifecycle]
age_decay_per_100_candles = 0.06
```

---

### 11.7. Overtest Penalty

```text
if touch_count_total > max_healthy_touches:
    overtest_penalty = (touch_count_total - max_healthy_touches) * 0.06
else:
    overtest_penalty = 0
```

---

### 11.8. Mitigation Penalty

Nếu giá đã đi xuyên sâu vào zone nhiều lần nhưng chưa invalidate:

```text
penetration_ratio = max_penetration_depth / zone_width
```

```text
if penetration_ratio > 0.70:
    mitigation_penalty += 0.12
elif penetration_ratio > 0.50:
    mitigation_penalty += 0.06
```

Ý nghĩa:

- Zone đã bị consume một phần.
- Không nên giữ weight cao như zone fresh.

---

### 11.9. Invalidation Penalty

Nếu zone bị invalidated:

```text
invalidation_penalty = 0.70
```

Hoặc đơn giản:

```text
weight *= invalidation_weight_multiplier
```

Config:

```toml
[zones.lifecycle]
invalidation_weight_multiplier = 0.15
```

---

## 12. Confidence V2

Confidence không nên giống weight.

- `weight`: zone có đáng ưu tiên không.
- `confidence`: detector có chắc đây là zone thật không.

Công thức đề xuất:

```text
confidence =
    0.30
  + min(touch_count_total * 0.08, 0.25)
  + min(abs(avg_reaction_score), 0.20)
  - invalidation_penalty
```

Clamp:

```text
confidence = min(max(confidence, 0.05), 1.0)
```

Nếu zone bị invalidated:

```text
confidence = min(confidence, 0.25)
```

---

## 13. Invalidation V2

Resistance bị invalidated khi candle close vượt lên trên zone với buffer:

```text
candle.close > zone.price_high + close_break_buffer
```

Support bị invalidated khi candle close thủng xuống dưới zone với buffer:

```text
candle.close < zone.price_low - close_break_buffer
```

Config đề xuất:

```toml
[zones.lifecycle]
close_break_buffer_atr_multiplier = 0.15
```

Công thức:

```text
close_break_buffer = ATR(14) * close_break_buffer_atr_multiplier
```

Nếu invalidated:

```text
status = "invalidated"
end_time = invalidated_at
valid_until = invalidated_at
metadata.invalidation_reason = "close_beyond_zone"
```

### 13.1. False Break Refinement

False break không invalidate zone nếu nến chỉ wick xuyên vùng rồi đóng ngược lại ngoài zone.

Support false break:

```text
candle.low < zone.price_low
AND candle.close > zone.price_high
```

Resistance false break:

```text
candle.high > zone.price_high
AND candle.close < zone.price_low
```

Quy tắc xử lý:

- Không dịch chuyển parent zone.
- Parent zone được giữ để audit/debug nhưng bị gắn `metadata.trade_disabled_after_sweep = true`.
- Parent zone bị giảm weight/confidence bằng `false_break_parent_weight_multiplier`.
- Bot tạo một refined zone mới quanh sweep low/high.
- Strategy không được dùng parent zone đã bị sweep để vào lệnh mới.

Refined support:

```text
price_low  = false_break_candle.low
price_high = min(parent.price_low, price_low + ATR * false_break_refine_max_width_atr_multiplier)
```

Refined resistance:

```text
price_high = false_break_candle.high
price_low  = max(parent.price_high, price_high - ATR * false_break_refine_max_width_atr_multiplier)
```

Metadata refined zone:

```text
refined_from_false_break = true
parent_zone_id
false_break_time
false_break_price
false_break_atr
refined_width_atr
```

Lý do: sau một false break, thị trường đã tạo swing/sweep high-low mới. Nếu bot tiếp tục trade parent zone cũ thì dễ vào lệnh ở vị trí stale; refined zone giúp bot ưu tiên vùng phản ứng mới hơn.

### 13.2. Pre-Detection Integrity Check

Trước khi chấp nhận một SR cluster, bot phải kiểm tra đoạn từ swing đầu tiên đến lúc zone đủ `min_touches`.

Nếu trong đoạn `start_time < candle.open_time < detected_at` đã có candle close phá vùng theo rule invalidation, cluster đó không được tạo thành zone.

Support candidate bị loại nếu:

```text
candle.close < zone.price_low - close_break_buffer
```

Resistance candidate bị loại nếu:

```text
candle.close > zone.price_high + close_break_buffer
```

Lý do: một vùng support được tạo từ các swing low cũ nhưng đã từng bị close xuyên thủng trước khi đủ touches thì không còn là support nguyên vẹn. Nếu giá quay lại vùng đó, nó nên được xem là context khác, ví dụ retest/flip/resistance, không phải support còn sống.

---

## 14. Flip Zone Logic Optional

Khi resistance bị break mạnh, nó có thể trở thành support.

Khi support bị break mạnh, nó có thể trở thành resistance.

Chỉ flip nếu breakout có chất lượng.

Resistance -> Support:

```text
close > zone.price_high + buffer
AND breakout_body >= avg_body_20 * 1.3
AND close_position >= 0.70
```

Support -> Resistance:

```text
close < zone.price_low - buffer
AND breakout_body >= avg_body_20 * 1.3
AND close_position <= 0.30
```

Khi flip:

```text
old_zone.status = "flipped"
new_zone.zone_type = opposite_type
new_zone.source_zone_id = old_zone.id
new_zone.weight = old_zone.weight * 0.70
```

Lưu ý:

- Không nên bật flip zone ngay nếu MVP chưa ổn.
- Nên log và debug trước.

---

## 15. Sorting

Zones được sort theo:

```text
ORDER BY effective_weight DESC, detected_at DESC
```

Nhưng khi dùng để trade, nên filter thêm theo khoảng cách tới giá hiện tại:

```text
distance_to_price = abs(current_price - zone.center)
```

Có thể ưu tiên zone gần giá hiện tại:

```text
tradable_zones = zones where distance_to_price <= ATR(14) * 3
```

---

## 16. Debug Metadata Nên Lưu

Mỗi zone nên lưu thêm metadata để debug:

```text
touch_count_base
touch_count_after_detection
touch_count_total

last_touch_time
last_touch_type
last_reaction_score

avg_reaction_score
max_reaction_score
weak_touch_count
clean_rejection_count
displacement_reaction_count
momentum_follow_through_count

age_candles
overtest_penalty
mitigation_penalty
age_penalty
confluence_score

weight_components
```

`weight_components` nên lưu dạng dictionary:

```json
{
  "base_score": 0.25,
  "touch_score": 0.18,
  "recency_score": 0.12,
  "reaction_score": 0.22,
  "confluence_score": 0.05,
  "age_penalty": 0.04,
  "overtest_penalty": 0.06,
  "mitigation_penalty": 0.00,
  "invalidation_penalty": 0.00
}
```

---

## 17. Pseudocode

```text
for each zone:
    if zone was invalidated between first swing and detected_at:
        discard zone

    reset lifecycle metrics

    for each candle after zone.detected_at:
        if candle overlaps zone:
            if not currently_in_touch:
                start new touch event

            update touch event duration
            classify touch type
            calculate penetration depth

        else:
            if currently_in_touch:
                finalize touch event

                reaction = measure_reaction_after_touch(
                    zone,
                    touch_event,
                    next_N_candles
                )

                update reaction metrics
                update touch_count

            currently_in_touch = false

    calculate age_penalty
    calculate touch_score
    calculate recency_score
    calculate reaction_score
    calculate overtest_penalty
    calculate mitigation_penalty
    calculate confluence_score

    weight = combine components
    confidence = calculate confidence

    check invalidation
    optionally check flip zone
```

---

## 18. Config Đề Xuất Tổng Hợp

```toml
[zones.support_resistance]
detector = "sr_v2"
tolerance_pct = 0.0005
min_zone_width = 1.0
atr_width_multiplier = 0.25
min_touches = 2
lookback_swings = 300
max_zones = 40

[zones.lifecycle]
recent_touch_lookback_candles = 80
age_decay_per_100_candles = 0.06
freshness_bonus = 0.12
invalidation_weight_multiplier = 0.15
close_break_buffer_atr_multiplier = 0.15

[zones.reaction]
reaction_window_candles = 5
min_reaction_atr = 0.8
strong_reaction_atr = 1.5
recent_reaction_count = 3
follow_through_close_required = true

[zones.decay]
max_healthy_touches = 3
weak_touch_penalty = 0.08
too_many_touches_penalty = 0.06
linger_penalty = 0.10
```

---

## 19. Ưu Tiên Implement

Không nên implement tất cả một lúc.

Thứ tự nên làm:

1. ATR-based zone width.
2. Touch classification: wick touch, body touch, close inside zone.
3. Reaction score sau touch.
4. Weight components rõ ràng.
5. Overtest penalty.
6. Invalidation buffer bằng ATR.
7. Debug metadata.
8. Flip zone logic.

---

## 20. Triết Lý V2

SR zone không mạnh vì nó được vẽ ra.

SR zone mạnh khi:

- Giá chạm zone rồi bị reject rõ.
- Sau touch có displacement.
- Có momentum follow-through.
- Giá không linger quá lâu trong zone.
- Zone chưa bị test quá nhiều lần.
- Zone còn fresh và gần context hiện tại.

Bot không nên hỏi:

```text
"Zone này có bao nhiêu touch?"
```

Bot nên hỏi:

```text
"Mỗi lần chạm zone này, market phản ứng chất lượng như thế nào?"
```
