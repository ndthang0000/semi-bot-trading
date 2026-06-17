# H1 Swing Point Deep Research — XAUUSD

**Generated:** 2026-06-16  
**Data source:** `var/trading.sqlite3` — `structure_points` table, swing_v1 detector, timeframe H1  
**Lookahead bias:** Intentionally allowed (retrospective analysis)

---

## 1. Dataset Overview

Swing types: **HH** (Higher High), **HL** (Higher Low), **LH** (Lower High), **LL** (Lower Low)

| Year | HH | HL | LH | LL | Total | Price range |
|------|----|----|----|----|-------|-------------|
| 2023 | 66 | 76 | 76 | 69 | 287 | 1810 – 2144 (+334 pts) |
| 2024 | 221 | 262 | 217 | 185 | 885 | 1984 – 2790 (+806 pts) |
| 2025 | 246 | 251 | 201 | 191 | 889 | 2614 – 4550 (+1936 pts) |
| 2026 | 52 | 59 | 47 | 37 | 195 | 4310 – 5595 (+1286 pts, partial to ~Mar) |

2025–2026 có số swing gần bằng nhau nhưng biên độ giá gấp 5–6× → mỗi con sóng lớn hơn rất nhiều.

---

## 2. Wave Size (Biên Độ Mỗi Con Sóng)

Đo khoảng cách giá giữa hai swing liên tiếp (không tính thời gian, chỉ tính price distance).

### Bullish wave: HL → HH (đáy cục bộ lên đỉnh cục bộ)

| Year | Median | P75 | P90 | Max |
|------|--------|-----|-----|-----|
| 2023 | 13.3 | 19.4 | 26.2 | 110.6 |
| 2024 | 18.4 | 27.5 | 38.2 | 76.1 |
| 2025 | 33.9 | 49.9 | 79.0 | 176.6 |
| 2026 | **73.6** | **119.6** | **211.6** | **410.5** |

### Bearish wave: LH → LL (đỉnh cục bộ xuống đáy cục bộ)

| Year | Median | P75 | P90 | Max |
|------|--------|-----|-----|-----|
| 2023 | 11.4 | 18.0 | 24.6 | 86.8 |
| 2024 | 17.2 | 25.8 | 39.5 | 101.0 |
| 2025 | 29.4 | 46.7 | 74.9 | 300.8 |
| 2026 | **68.0** | **104.7** | **205.4** | **454.5** |

**Nhận xét:**
- Median wave size tăng gần **6×** từ 2023 → 2026.
- Trong năm 2026, **50% các sóng dài hơn 70 pts**; 10% trên đỉnh dài hơn 200 pts.
- Bearish wave luôn nhỏ hơn bullish wave ~10–15% → xu hướng tăng dài hạn của gold khiến correction ngắn hơn impulse.
- Trong năm 2023: wave median ~12–13 pts → SL/TP cần calibrate ở mức 8–20 pts.  
  Trong năm 2026: wave median ~68–74 pts → SL/TP cần calibrate ở mức 50–150 pts.

---

## 3. H1 Candle Range Tại Swing Point

H1 range (high − low) của chính cây nến tạo swing:

| Year | Swing High — Median | p90 | Swing Low — Median | p90 |
|------|---------------------|-----|--------------------|-----|
| 2023 | 4.5 pts | 10.1 | 4.7 pts | 11.2 |
| 2024 | 6.9 pts | 15.7 | 7.6 pts | 16.9 |
| 2025 | 11.9 pts | 27.2 | 13.3 pts | 32.9 |
| 2026 | **26.2 pts** | **69.3** | **33.9 pts** | **99.7** |

**Nhận xét:**
- H1 range tại swing tăng ~5.8× từ 2023 → 2026.  
- Swing low thường có H1 range lớn hơn swing high một chút → nến đáy có wick lớn hơn.
- Trong năm 2026, **10% swing lows có H1 range > 100 pts** → đây là các spike mạnh (wick khổng lồ).
- Cần dùng giá trị **tuyệt đối** khi đặt SL, không nên dùng tỷ lệ cố định theo pips.

---

## 4. H1 Candle Pattern Tại Swing Points

### 4.1 Tại Swing Highs (HH + LH)

| Pattern | 2023 | 2024 | 2025 | 2026 |
|---------|------|------|------|------|
| bear_shooting_star | **21%** | **19%** | **22%** | **16%** |
| bull_hammer | 17% | 17% | 15% | 12% |
| bull_normal | 15% | 13% | 8% | 14% |
| bull_upper_wick | 12% | 12% | 11% | 13% |
| pinbar_bear | 9% | 10% | 9% | 10% |
| marubozu_bull | 7% | 8% | 10% | 10% |
| bear_normal | 8% | 6% | 7% | 12% |
| doji | 6% | 6% | 8% | 5% |
| marubozu_bear | 4% | 6% | 6% | 4% |

**Diễn giải:**
- **~30% swing high có tín hiệu bearish rõ ràng** (bear_shooting_star + pinbar_bear): nến có upper wick dài, từ chối vùng cao.
- **~40–45% swing high là nến bullish** (bull_hammer, bull_normal, bull_upper_wick, marubozu_bull): điều này bình thường vì swing detector nhìn vào cấu trúc giá xung quanh, không phải pattern của chính cây nến đó. HH/LH được xác nhận AFTER THE FACT khi giá quay xuống.
- Doji ~6–8% → không phổ biến, xảy ra khi swing hình thành ở vùng consolidation.
- Pattern **bear_shooting_star nhất quán là top 1** qua tất cả các năm → khi thấy shooting star trên H1, cần cẩn thận reversal.

### 4.2 Tại Swing Lows (HL + LL)

| Pattern | 2023 | 2024 | 2025 | 2026 |
|---------|------|------|------|------|
| bull_hammer | 14% | **20%** | **19%** | **20%** |
| bear_shooting_star | 17% | 15% | 16% | 16% |
| bear_lower_wick | 11% | 17% | 16% | 17% |
| pinbar_bull | 12% | 13% | 12% | 18% |
| bear_normal | 18% | 11% | 12% | 10% |
| marubozu_bear | 7% | 8% | 6% | 5% |
| doji | 8% | 7% | 7% | 3% |
| marubozu_bull | 6% | 5% | 6% | 3% |

**Diễn giải:**
- **~30–35% swing low có tín hiệu bullish rõ ràng** (bull_hammer + pinbar_bull): nến có lower wick dài, từ chối vùng thấp. Năm 2026 tăng lên ~38% (bull_hammer 20% + pinbar_bull 18%).
- **~35–40% swing low là nến bearish** — tương tự swing high, nhiều đáy được confirm AFTER THE FACT.
- Xu hướng 2026: pinbar_bull tăng lên 18% → các đáy trong môi trường biến động cao hơn thường để lại wick đuôi dài rõ ràng hơn.

### 4.3 Asymmetry: Wick Direction Confirms Structure

Điều quan trọng nhất trong body/wick analysis:

| Swing type | Upper wick ratio (median) | Lower wick ratio (median) | Body ratio (median) |
|------------|--------------------------|--------------------------|---------------------|
| Swing HIGH | **0.36–0.39** | 0.16–0.17 | 0.40–0.47 |
| Swing LOW | 0.12–0.14 | **0.41–0.47** | 0.38–0.40 |

- **Swing high → upper wick lớn gấp 2–3× lower wick**: giá từ chối vùng cao, cây nến H1 để lại wick trên.
- **Swing low → lower wick lớn gấp 3–4× upper wick**: giá từ chối vùng thấp, cây nến H1 để lại wick dưới.
- Asymmetry này **nhất quán qua tất cả 4 năm** — đây là tín hiệu cấu trúc rất đáng tin cậy.
- Body ratio ~0.40 ở cả hai → thân nến trung bình (không phải doji, không phải marubozu).

---

## 5. M15 Candle Patterns Inside Swing H1 Candle

Phân tích các cây nến M15 nằm trong giờ H1 tạo swing (tức là 4 cây M15 cấu thành H1 swing candle). Lưu ý: sample size nhỏ hơn vì một số giờ thiếu M15 data.

### Tại Swing Highs (M15 patterns)

| Pattern | 2023 | 2024 | 2025 | 2026 |
|---------|------|------|------|------|
| bull_hammer (M15) | 7% | 4% | **21%** | **18%** |
| bear_shooting_star | 18% | 4% | 15% | 13% |
| marubozu_bull | **21%** | 13% | 7% | 10% |
| marubozu_bear | 7% | **29%** | 7% | 8% |
| bull_upper_wick | 18% | 17% | 7% | 8% |
| doji | 7% | 8% | 4% | 10% |

**Nhận xét M15 tại swing high:**
- 2024: `marubozu_bear` chiếm 29% → nhiều nến M15 trong giờ đó thuần bearish, phù hợp rejection mạnh.
- 2025–2026: `bull_hammer` M15 nổi lên 18–21% trong giờ swing high → price lên cao, wick xuống rồi recover trên M15, nhưng H1 tổng thể vẫn tạo swing high.
- `bear_shooting_star` + `marubozu_bear` cộng lại 20–35% → các nến M15 bearish tập trung vào giữa/cuối giờ swing high.

### Tại Swing Lows (M15 patterns)

| Pattern | 2023 | 2024 | 2025 | 2026 |
|---------|------|------|------|------|
| bull_hammer (M15) | 6% | 18% | **32%** | **20%** |
| bear_shooting_star | **25%** | 21% | 11% | 10% |
| marubozu_bull | 13% | 21% | 6% | 15% |
| marubozu_bear | 6% | 11% | 13% | 10% |
| doji | 13% | 7% | 4% | 10% |
| pinbar_bull | 13% | 4% | 6% | — |

**Nhận xét M15 tại swing low:**
- 2025: `bull_hammer` M15 chiếm **32%** — đây là tín hiệu mạnh nhất: trong giờ tạo đáy, các nến M15 thường là hammer (wicks xuống, đóng cửa cao hơn) → price thăm dò vùng thấp rồi bị từ chối ngay trên M15.
- 2023: `bear_shooting_star` M15 chiếm 25% tại swing low → confusing pattern, nhưng phù hợp với môi trường 2023 ít biến động hơn, swing được confirm muộn hơn.
- Trend rõ ràng 2024→2026: `bull_hammer` M15 tăng dần tại swing lows → tín hiệu reversal trên M15 trở nên rõ hơn khi market biến động tăng.

---

## 6. Session Distribution (UTC Hours)

Phân bố swing theo phiên giao dịch (UTC):

| Session | Swing High | Swing Low |
|---------|-----------|-----------|
| Asia (0–7h) | **39%** | **37%** |
| London (8–12h) | 17% | 18% |
| NY (13–17h) | 30% | 30% |
| Late/Close (18–23h) | 14% | 15% |

**Nhận xét:**
- **Phiên Á chiếm ~38–40% tổng số swing points** — nhiều nhất, nhất quán qua mọi năm.
- Lý do: phiên Á có liquidity thấp hơn → price sweep các mức cao/thấp dễ tạo cấu trúc hơn. Gold thường tạo fake-out hoặc accumulation trong phiên Á.
- Phiên Mỹ (NY) chiếm ~30% — số swing đáng kể, thường là real breakout hoặc major reversal khi có news.
- Phiên London ~17–18% — ít hơn nhưng quality cao hơn (opening của EU, thường là trend-setting move).
- Distribution **gần như không đổi từ 2023–2026** → đây là tính chất cấu trúc của gold, không phụ thuộc price level.

---

## 7. Tổng Hợp & Ứng Dụng Thực Tế

### 7.1 Calibration SL/TP theo năm

| Năm | Min SL khuyến nghị | Typical wave | Max swing range H1 (p90) |
|-----|-------------------|--------------|--------------------------|
| 2023 | 8–12 pts | 12–20 pts | 10–11 pts |
| 2024 | 12–18 pts | 17–28 pts | 16–17 pts |
| 2025 | 20–35 pts | 30–50 pts | 27–33 pts |
| 2026 | **50–80 pts** | **68–120 pts** | **69–100 pts** |

→ Trong 2026, SL dưới 30 pts sẽ bị swept thường xuyên. Minimum viable SL ~50 pts.

### 7.2 Tín Hiệu Nến Đáng Tin Cậy Nhất Tại Swing

**Tại SWING HIGH (tìm short setup):**
1. H1 `bear_shooting_star` hoặc `pinbar_bear` (cộng lại ~30%) — high confidence
2. H1 upper wick ratio > 0.35 (median tại swing high là 0.36–0.39)
3. Confirm bằng M15: tìm `marubozu_bear` hoặc `bear_shooting_star` trong 2–3 cây M15 cuối

**Tại SWING LOW (tìm long setup):**
1. H1 `bull_hammer` hoặc `pinbar_bull` (cộng lại ~30–38%) — high confidence
2. H1 lower wick ratio > 0.40 (median tại swing low là 0.41–0.47)
3. Confirm bằng M15: tìm `bull_hammer` M15 (signal mạnh nhất, 20–32% tại đáy từ 2024–2026)

### 7.3 Những Gì Không Dự Đoán Được Từ Pattern

- **~40–45% swing highs** là nến bullish-looking (bull_hammer, marubozu_bull, bull_normal) → không thể dùng nến đơn lẻ để confirm swing high.
- **~35–40% swing lows** là nến bearish-looking → tương tự.
- Kết luận: **cấu trúc swing (sequence of HH/HL/LH/LL) quan trọng hơn pattern của cây nến tạo swing**. Pattern chỉ là confirmation, không phải primary signal.

### 7.4 Implication Cho Strategy

1. **Zone reaction entries**: Khi price vào vùng support/resistance và để lại wick rõ (lower_wick > 40% range tại support, upper_wick > 35% range tại resistance) → xác suất đây là swing point cao hơn.

2. **ATR-based stops trong 2026**: ATR H1 trung bình tại swing ~26–34 pts. SL cần ít nhất 1.5–2× ATR tại swing = **40–70 pts minimum** cho 2026.

3. **Session timing**: Tránh chase breakout trong phiên Á (39% là swing/fakeout). London open và NY open là nơi swing thường được confirm hoặc fail definitively.

4. **Wave length targeting**: Dùng median wave size làm TP1:
   - 2026: median bullish wave = 73.6 pts → TP1 có thể đặt 50–70 pts sau entry
   - 2026: p75 = 119.6 pts → TP2 ở 100–120 pts nếu momentum tốt

---

## 8. Raw Numbers Reference

### Wave size percentiles (price points, both directions combined)

| Year | P25 | Median | P75 | P90 | Max |
|------|-----|--------|-----|-----|-----|
| 2023 | 7–8 | 12–13 | 18–19 | 25–26 | 87–111 |
| 2024 | 10–11 | 17–18 | 26–28 | 38–40 | 76–101 |
| 2025 | 18–20 | 29–34 | 47–50 | 74–79 | 177–301 |
| 2026 | 38–42 | 68–74 | 105–120 | 205–212 | 411–455 |

### H1 body/wick summary (all years)

```
Swing HIGH: upper_wick_ratio median = 0.37  |  lower_wick_ratio median = 0.17
Swing LOW:  upper_wick_ratio median = 0.13  |  lower_wick_ratio median = 0.43
Body ratio: ~0.40 at both (consistent)
```

---

*End of report. Data covers XAUUSD H1 swing_v1 detector, 2023-01-01 to 2026-03-xx.*
