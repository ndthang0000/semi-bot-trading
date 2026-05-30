# Support / Resistance Formula

Tài liệu này ghi lại công thức SR hiện tại của MVP. Mục tiêu là có một nguồn tham chiếu rõ ràng để sau này điều chỉnh detector, touch, weight và invalidation mà không phải đọc lại toàn bộ code.

Code chính: `semi_bot_trading/zones.py`

Config chính: `config/trading.toml`

## 1. Input

SR detector không đọc trực tiếp từ tất cả candle. Nó lấy input từ các swing đã được market structure detector xác nhận.

- `Swing High` dùng để tạo `resistance`.
- `Swing Low` dùng để tạo `support`.
- Swing hiện tại được lấy từ detector `swing_v1`.
- Timeframe hiện tại dùng theo chart/replay, MVP chủ yếu là `H1`.

Config hiện tại:

```toml
[zones.support_resistance]
detector = "sr_v1"
tolerance_pct = 0.0015
min_zone_width = 1.0
min_touches = 2
lookback_swings = 300
max_zones = 40
```

Ý nghĩa:

- `tolerance_pct`: khoảng sai số theo phần trăm giá để gom các swing gần nhau.
- `min_zone_width`: độ rộng tối thiểu của vùng giá.
- `min_touches`: số swing tối thiểu trong một cụm để tạo thành SR zone.
- `lookback_swings`: số swing gần nhất được đưa vào detector.
- `max_zones`: số vùng tối đa trả về.

## 2. Gom Swing Thành Cụm

Detector tách riêng swing high và swing low:

```text
resistance_candidates = all swings where swing_type == "high"
support_candidates    = all swings where swing_type == "low"
```

Các swing được sort theo giá tăng dần. Mỗi swing sẽ được so với center của từng cluster hiện có.

Công thức tolerance:

```text
tolerance = max(cluster_center * tolerance_pct, min_zone_width)
```

Nếu:

```text
abs(swing_price - cluster_center) <= tolerance
```

thì swing đó được thêm vào cluster hiện tại.

Nếu không match cluster nào, bot tạo cluster mới.

Ví dụ với XAUUSD quanh giá `5000`:

```text
tolerance = max(5000 * 0.0015, 1.0)
          = max(7.5, 1.0)
          = 7.5
```

Nghĩa là các Swing High gần nhau trong khoảng khoảng `7.5 giá` quanh cluster center có thể được gom vào cùng một resistance.

## 3. Điều Kiện Tạo Zone

Một cluster chỉ trở thành zone khi:

```text
len(cluster.points) >= min_touches
```

Config hiện tại:

```text
min_touches = 2
```

Tức là ít nhất 2 swing high gần nhau mới tạo resistance, hoặc ít nhất 2 swing low gần nhau mới tạo support.

## 4. Công Thức Biên Zone

Với mỗi cluster hợp lệ:

```text
prices = all swing prices in cluster
center = average(prices)
half_width = max(center * tolerance_pct, min_zone_width)

price_low  = min(prices) - half_width
price_high = max(prices) + half_width
```

Zone metadata lưu thêm:

```text
center
tolerance_pct
min_zone_width
swing_point_ids
swing_point_times
swing_point_prices
```

Zone time:

```text
start_time  = first swing time in cluster
valid_from  = first swing time in cluster
detected_at = last swing time in cluster
end_time    = null until invalidated
```

Zone type:

```text
if cluster.swing_type == "high":
    zone_type = "resistance"
    direction = "bearish"

if cluster.swing_type == "low":
    zone_type = "support"
    direction = "bullish"
```

## 5. Touch Count

Hiện tại có 2 loại touch.

### 5.1. Base Touch

Base touch là số swing tạo nên zone:

```text
touch_count_base = len(cluster.points)
```

Khi zone mới được tạo:

```text
metadata.touch_count = touch_count_base
```

Ví dụ 3 Swing High gần nhau tạo resistance:

```text
touch_count_base = 3
```

### 5.2. Touch Sau Khi Zone Được Detect

Sau khi zone được tạo, lifecycle sẽ quét các candle từ `zone.detected_at` trở đi.

Candle được xem là chạm zone nếu:

```text
candle.high >= zone.price_low
and
candle.low <= zone.price_high
```

Tức là chỉ cần range của candle overlap vùng giá là tính touch.

Để tránh đếm spam, nếu nhiều candle liên tiếp nằm trong zone thì chỉ tính là 1 touch. Logic này dùng biến `in_touch`:

```text
if candle overlaps zone and not in_touch:
    touch_count_after_detection += 1
    last_touch_time = candle.open_time

in_touch = candle overlaps zone
```

Tổng touch:

```text
touch_count_total = touch_count_base + touch_count_after_detection
```

## 6. Confidence

Khi zone mới được tạo từ cluster:

```text
confidence = min(0.35 + touch_count * 0.12, 1.0)
```

Sau lifecycle:

```text
confidence = min(0.35 + touch_count_total * 0.08, 1.0)
```

Nếu zone bị invalidated:

```text
confidence = min(confidence, 0.25)
```

## 7. Weight Ban Đầu

Khi zone mới được tạo từ cluster:

```text
touch_count = len(cluster.points)
recency_rank = count(points where point.event_time >= latest_swing_time)

weight = min(0.25 + touch_count * 0.10 + recency_rank * 0.10, 1.0)
```

Lưu ý: `recency_rank` hiện tại thường chỉ cộng điểm cho cluster có chứa swing mới nhất trong toàn bộ input swings.

## 8. Weight Sau Lifecycle

Sau khi lifecycle chạy, weight được tính lại theo công thức:

```text
age_candles = number of candles from zone.detected_at to latest_time
age_penalty = (age_candles / 100.0) * age_decay_per_100_candles
touch_score = min(touch_count_total * 0.08, 0.45)

weight = 0.30 + touch_score - age_penalty
```

Config hiện tại:

```toml
[zones.lifecycle]
recent_touch_lookback_candles = 80
age_decay_per_100_candles = 0.08
freshness_bonus = 0.15
invalidation_weight_multiplier = 0.15
```

Nếu zone có touch gần đây:

```text
latest_index - last_touch_index <= recent_touch_lookback_candles
```

thì:

```text
weight += freshness_bonus
```

Nếu zone bị invalidated:

```text
weight *= invalidation_weight_multiplier
```

Cuối cùng clamp:

```text
weight = min(max(weight, 0.05), 1.0)
```

## 9. Invalidation

Resistance bị invalidated khi candle close vượt lên trên zone:

```text
candle.close > zone.price_high + close_break_buffer
```

Support bị invalidated khi candle close thủng xuống dưới zone:

```text
candle.close < zone.price_low - close_break_buffer
```

Config hiện tại:

```text
close_break_buffer = 0.0
```

Khi invalidated:

```text
status = "invalidated"
end_time = invalidated_at
valid_until = invalidated_at
metadata.invalidation_reason = "close_beyond_zone"
```

## 10. Sorting

Sau khi detect xong, zones được sort:

```text
ORDER BY effective_weight DESC, detected_at DESC
```

Sau đó chỉ lấy:

```text
max_zones = 40
```

## 11. Hạn Chế Hiện Tại

Logic hiện tại đủ cho MVP và replay debug, nhưng còn đơn giản:

- Touch chỉ dựa vào candle overlap zone, chưa xét rejection thật sự.
- Chưa phân biệt wick touch, body touch, close inside zone.
- Chưa xét candle phản ứng sau touch.
- Chưa xét liquidity sweep quanh SR.
- Chưa xét BOS/CHOCH sau khi chạm vùng.
- Chưa xét volume/tick volume.
- `tolerance_pct = 0.0015` có thể làm vùng XAUUSD hơi rộng ở một số giai đoạn.
- Weight chưa xét khoảng cách từ giá hiện tại tới zone.
- Weight chưa xét confluence với OB/FVG/bias/regime.

## 12. Ý Tưởng Điều Chỉnh Sau

Các hướng nâng cấp nên cân nhắc:

- Tách `touch_strength` theo wick rejection, body rejection, close rejection.
- Giảm weight nếu zone bị test quá nhiều lần mà phản ứng yếu.
- Tăng weight nếu touch đi kèm liquidity sweep rồi reject.
- Tăng weight nếu zone cùng hướng với H1 bias hoặc playbook hiện tại.
- Dùng ATR-based width thay vì chỉ dùng phần trăm giá.
- Tính `freshness` theo thời gian thực thay vì số candle.
- Tách score thành nhiều thành phần rõ ràng:

```text
weight =
    base_score
  + touch_score
  + recency_score
  + reaction_score
  + confluence_score
  - age_penalty
  - mitigation_penalty
  - invalidation_penalty
```

