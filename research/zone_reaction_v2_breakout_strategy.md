# Zone Reaction V2 — Chiến Lược Breakout (Retest-Reject)

**Playbook:** `zone_reaction_v2`  
**File nguồn:** `semi_bot_trading/strategy/zone_reaction_v2.py`  
**Cập nhật:** 2026-06-17

---

## Tổng quan

Zone Reaction V2 về bản chất là **reject playbook** (trade khi price từ chối zone). Tuy nhiên, nó có một nhánh breakout riêng xử lý trường hợp price **phá vỡ zone** thay vì bật lại. Nhánh này có 3 giai đoạn: **Clean Breakout → Waiting Retest → Retest Reject (Entry)**.

> **Lưu ý quan trọng:** Zone Reaction V2 không có entry ngay tại thời điểm breakout — nó **chờ retest** rồi mới vào lệnh. Đây là sự khác biệt cốt lõi so với `sr_breakout_v1` (playbook breakout thuần túy).

---

## Timeframe

| Mục đích | Timeframe |
|----------|-----------|
| Phát hiện zone (support/resistance/FVG) | H1 |
| Phát hiện swing structure (HH/HL/LH/LL) | H1 |
| Phân loại reaction (classify) | H1 — cây nến H1 hiện tại |
| Trigger xác nhận (BOS/CHOCH, price action) | **M15** |
| Entry / SL / TP | Dựa trên close H1 hiện tại |
| Lookback tìm breakout candle | 8 cây H1 gần nhất |
| Macro trend lookback | 720 cây H1 (~30 ngày) |

---

## Điều kiện Zone Hợp Lệ

Breakout chỉ xảy ra trên các zone thuộc `zone_reaction_v2`:

| Zone type | Hướng kỳ vọng | Breakout direction |
|-----------|--------------|-------------------|
| support | long | short (giá phá xuống) |
| resistance | short | long (giá phá lên) |
| fvg (bullish) | long | short (giá lấp đầy và phá xuống) |
| fvg (bearish) | short | long (giá lấp đầy và phá lên) |

---

## Giai đoạn 1 — Clean Breakout (H1)

### Điều kiện kích hoạt

Được kiểm tra trong `classify_zone_reaction_v2()` sau khi đã loại trừ fakeout.

**Phá xuống support/fvg bullish (→ short setup):**
```
close_H1 < zone_low − (0.5 × ATR_H1)    [đóng đủ xa bên dưới]
AND
|close_H1 − open_H1| ≥ 0.8 × ATR_H1    [body nến đủ lớn, không phải wick]
```

**Phá lên resistance/fvg bearish (→ long setup):**
```
close_H1 > zone_high + (0.5 × ATR_H1)   [đóng đủ xa bên trên]
AND
|close_H1 − open_H1| ≥ 0.8 × ATR_H1    [body nến đủ lớn]
```

### Fakeout bị loại trước

Trước khi check breakout, hệ thống check fakeout:
```
Penetration ≤ 0.5 × ATR  AND  close quay lại trong zone  →  fakeout (không phải breakout)
```

### Kết quả

- State: `clean_breakout`
- Status: `waiting_confirmation` — **chưa vào lệnh**, chờ retest
- Metadata ghi thêm: `bias_phase = "transition_bearish"` hoặc `"transition_bullish"`

---

## Giai đoạn 2 — Waiting Retest (H1)

### Cơ chế tìm breakout candle

Hàm `breakout_retest_reaction()` được gọi **ưu tiên đầu tiên** trước tất cả các check khác. Nó nhìn lại **8 cây H1 gần nhất** (không tính cây hiện tại) để tìm breakout candle:

```
Với mỗi candle trong 8 cây lookback (theo thứ tự mới nhất):
  Nếu là bearish breakout (short):
    zone_low − close ≥ 0.5 × ATR  AND  body ≥ 0.8 × ATR  →  breakout_candle tìm thấy

  Nếu là bullish breakout (long):
    close − zone_high ≥ 0.5 × ATR  AND  body ≥ 0.8 × ATR  →  breakout_candle tìm thấy
```

### Kiểm tra retest

Sau khi tìm được `breakout_candle`, kiểm tra cây H1 hiện tại có chạm lại zone không:

**Bearish breakout (short):**
```
low_H1 ≤ zone_high  AND  high_H1 ≥ zone_low   →  đang retest
```

**Bullish breakout (long):**
```
high_H1 ≥ zone_low  AND  low_H1 ≤ zone_high   →  đang retest
```

### Kết quả

- State: `waiting_retest`
- Status: `waiting_confirmation` — **vẫn chưa vào lệnh**
- Metadata ghi: `breakout_candle_time`, `breakout_direction`

---

## Giai đoạn 3 — Retest Reject — ENTRY (H1 + M15)

### Điều kiện vào lệnh (H1)

Tiếp nối từ giai đoạn 2, cây H1 hiện tại phải:

**Bearish (short entry):**
```
Retest đã xảy ra (high chạm zone)
AND  close_H1 < zone_low               [đóng cửa trở lại bên dưới zone]
AND  body_H1 ≥ avg_body_H1(20 cây)    [body đủ mạnh, không phải wick nhỏ]
→  retest_reject, direction = "short"
```

**Bullish (long entry):**
```
Retest đã xảy ra (low chạm zone)
AND  close_H1 > zone_high              [đóng cửa trở lại bên trên zone]
AND  body_H1 ≥ avg_body_H1(20 cây)    [body đủ mạnh]
→  retest_reject, direction = "long"
```

### State machine path

```
IDLE → APPROACHING → ZONE_TOUCHED → REACTING_IN_ZONE → WAITING_RETEST → PREPARE_ENTRY
```

### Status: `eligible` → Vào lệnh

---

## Tính toán Entry / SL / TP

`retest_reject` dùng **wick-based stop** (không dùng zone stop như `reject` thông thường):

### Long entry (breakout lên resistance)

```
Entry  = close_H1 hiện tại (market order)
SL     = reaction_low_của_cây_retest − (0.2 × ATR_H1)
TP     = Entry + (Entry − SL) × 2.5
```

### Short entry (breakout xuống support)

```
Entry  = close_H1 hiện tại (market order)
SL     = reaction_high_của_cây_retest + (0.2 × ATR_H1)
TP     = Entry − (Entry − SL) × 2.5   [Entry + SL thực ra Entry − risk × 2.5]
```

### Giới hạn SL

```
SL tối thiểu = max(4.0 pts, 1.2 × ATR_H1)
SL tối đa   = 30.0 pts   ← CẦN REVIEW cho 2026 (ATR H1 ~25–35 pts)
RR tối thiểu = 2.5
```

> ⚠️ **Vấn đề 2026:** `max_stop_distance = 30.0` nhưng ATR H1 trong 2026 median ~26–34 pts. SL tự nhiên từ wick retest rất dễ vượt 30 pts → setup bị `blocked`. Cần nâng lên 60–80 pts.

---

## Context Gates (Bộ lọc)

Các điều kiện này vẫn áp dụng cho breakout, trừ khi human đặt `trade_mode` tường minh:

| Gate | Điều kiện block |
|------|----------------|
| Macro trend (H1, 720 nến) | `up` blocks short; `down` blocks long |
| Regime | `news` hoặc `risk_off` blocks tất cả |
| FVG macro gate riêng | Có thể tắt riêng qua `fvg_macro_gate_enabled` |
| Trade mode | Zone phải có `reject` trong trade_modes |
| Bias gate | Tạm thời **tắt** (đang research) |

---

## Scoring

| Thành phần | Điểm |
|-----------|------|
| Zone weight × 0.24 | 0–0.24 |
| Reaction state (retest_reject) | **0.0** ← không có trong dict |
| Bias aligned | +0.18 |
| Has M15 trigger | +0.10 |
| RR bonus | +0–0.10 (tỷ lệ RR/8) |
| Confluence zones | +0.08 |
| Status = blocked | × 0.5 |

> ⚠️ **Bug/thiếu sót:** `retest_reject` không có entry trong scoring dict (chỉ có `clean_breakout = 0.10`, `waiting_retest = 0.10`). Score tối đa của retest_reject thấp hơn `reject` và `fakeout` đáng kể. Cần thêm `"retest_reject": 0.28` vào dict nếu muốn setup này được ưu tiên đúng mức.

---

## Sơ đồ Luồng Tổng Thể

```
[H1] Price tiếp cận zone
        ↓
[H1] Price chạm zone → "approaching" (watching)
        ↓
[H1] Price xuyên qua zone
  body ≥ 0.8 ATR  AND  close ≥ 0.5 ATR ngoài zone
        ↓
  [H1] clean_breakout  →  waiting_confirmation
        ↓
[H1, 1–8 nến tiếp theo] Price quay lại chạm zone
        ↓
  [H1] waiting_retest  →  waiting_confirmation
        ↓
[H1] Cây nến retest đóng cửa:
  - Trở lại đúng hướng breakout
  - body ≥ avg_body(20)
        ↓
  [H1] retest_reject  →  ELIGIBLE
        ↓
[M15] Tùy chọn: tìm BOS/CHOCH/PA confirm để tăng confidence
        ↓
  Entry = close H1
  SL    = wick cây retest ± 0.2 ATR
  TP    = Entry ± risk × 2.5
```

---

## Khác biệt với sr_breakout_v1

| | zone_reaction_v2 (breakout) | sr_breakout_v1 |
|--|---------------------------|----------------|
| Zone types | support, resistance, fvg | support, resistance |
| Entry lúc breakout | ❌ Không | ✅ `breakout_close` (market) |
| Entry lúc retest | ✅ `retest_reject` | ✅ `retest_breakout` |
| Stop mode | Wick-based | Zone edge hoặc ATR |
| Macro gate | Có (riêng cho FVG) | Có |
| Context bypass | Qua trade_mode `reject` | Qua trade_mode `breakout` |
| Score breakout state | 0.0 (thiếu entry dict) | 0.32–0.36 |

---

## Config liên quan (`config/trading.toml`)

```toml
[strategy.playbooks.zone_reaction_v2]
breakout_min_body_atr = 0.8           # body tối thiểu để là breakout
breakout_min_close_outside_atr = 0.5  # close tối thiểu ngoài zone
retest_max_bars = 8                   # nhìn lại tối đa 8 cây H1
fakeout_max_atr = 0.5                 # xuyên ≤ 0.5 ATR = fakeout
stop_buffer_atr = 0.2                 # buffer thêm vào wick SL
min_stop_price = 4.0                  # SL tối thiểu tuyệt đối
min_stop_atr = 1.2                    # SL tối thiểu theo ATR
max_stop_distance = 30.0              # ⚠️ quá thấp cho 2026
rr_minimum = 2.5                      # RR tối thiểu
macro_gate_enabled = true
fvg_macro_gate_enabled = true
```

---

*Nguồn: `semi_bot_trading/strategy/zone_reaction_v2.py` — hàm `classify_zone_reaction_v2`, `breakout_retest_reaction`, `evaluate_zone_reaction_v2`, `compute_zone_reaction_v2_levels`*
