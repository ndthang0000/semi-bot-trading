# Bias Formula

Bias la huong uu tien chinh cua H1 context. Strategy dung bias de quyet dinh uu tien long, short, hay giam tin hieu khi market khong co huong ro.

## Scope

Config hien tai:

```toml
[context.bias]
detector = "bias_v2"
timeframe = "H1"
recent_swings = 6
recent_breaks = 3
```

Bot dung:

- H1 structure la context chinh.
- M15 khong duoc dung de doi H1 bias. M15 chi dung cho reaction/trigger.
- Swing points: `HH`, `HL`, `LH`, `LL`.
- Break points: `BOS`, `CHOCH`.
- Candles H1 gan nhat de tinh ATR va range efficiency.

## Bias V2 Summary

Bias V2 khong con dem phieu bang nhau nhu V1. Moi structure point co weight theo recency, break structure co weight rieng, CHOCH manh hon BOS, va break co close vuot level cang ro thi weight cang cao.

Pipeline:

```text
weighted_swing_score
+ weighted_break_score
= raw_score

normalized_score = raw_score / total_weight
```

Classification:

```text
if normalized_score >= 0.25:
    bias = bullish

elif normalized_score <= -0.25:
    bias = bearish

else:
    bias = neutral
```

## Swing Score

Swing direction:

```text
HH or HL => +1
LH or LL => -1
```

Recency weight:

```text
oldest recent swing = 0.55
newest recent swing = 1.00
```

Formula:

```text
swing_contribution = direction_score * recency_weight
swing_score = sum(swing_contribution)
```

Y nghia:

- Swing moi co tac dong lon hon swing cu.
- Chuoi `HH/HL` nghieng bullish.
- Chuoi `LH/LL` nghieng bearish.
- Structure lan xon se lam score ve gan 0.

## Break Score

Break direction lay tu `metadata.direction`:

```text
direction = up   => +1
direction = down => -1
```

Base type weight:

```text
BOS   = 1.20
CHOCH = 1.60
```

Recency weight:

```text
oldest recent break = 0.75
newest recent break = 1.15
```

Break quality multiplier:

```text
break_atr = abs(close_price - broken_level) / ATR
quality_multiplier = 0.80 + min(break_atr, 1.50) * 0.20
clamped range: 0.80 -> 1.30
```

Formula:

```text
break_contribution =
    direction_score
    * recency_weight
    * type_weight
    * quality_multiplier
```

Y nghia:

- BOS xac nhan tiep dien structure.
- CHOCH la canh bao dao chieu nen duoc uu tien hon BOS.
- Break close vuot level cang ro, weight cang cao.
- Neu break metadata thieu `close_price` hoac `broken_level`, quality multiplier mac dinh la `1.0`.

## CHOCH Neutralization

Sau khi co bias tam thoi, bot kiem tra latest break.

Neu latest break la CHOCH nguoc voi bias tam thoi, bias bi ep ve neutral:

```text
latest CHOCH up   + bearish bias => neutral
latest CHOCH down + bullish bias => neutral
```

Ly do: CHOCH nguoc huong la dau hieu structure co the dang doi pha, bot khong nen giu bias cu qua tu tin.

Metadata:

```text
neutral_reason = "opposing_choch_up" | "opposing_choch_down"
choch_neutralized = true
```

## Range Neutralization

Bias V2 co them bo loc market dang di ngang.

Range efficiency:

```text
range_efficiency =
    abs(last_close - first_close) / sum(true_range)
```

Neu gia di nhieu nhung ket qua net movement thap, market co kha nang dang range.

Rule:

```text
if bias != neutral
and range_efficiency <= 0.25
and abs(normalized_score) < 0.45:
    bias = neutral
```

Metadata:

```text
neutral_reason = "ranging_structure_weak"
range_neutralized = true
```

Y nghia:

- Neu structure chi hoi nghieng bullish/bearish nhe nhung market ro rang sideways, bot se khong ep directional bias.
- Neu score directional rat manh (`abs(normalized_score) >= 0.45`), bias van co the duoc giu.

## Confidence

Directional confidence:

```text
confidence = clamp(abs(normalized_score), 0.35, 1.0)
```

Neutral confidence:

```text
confidence = max(0.35, min(1.0, 1.0 - abs(normalized_score)))
```

Neu neutral do CHOCH nguoc:

```text
confidence = max(confidence, 0.60)
```

Neu neutral do range weak:

```text
confidence = max(confidence, 0.65)
```

Y nghia:

- Directional bias can score ro rang de confidence cao.
- Neutral co confidence cao khi structure that su conflict/range.
- Neutral khong co nghia la market khong di chuyen; no chi co nghia bot khong co directional edge du ro.

## Effective Bias

Bot tao:

```text
bot_value = bias
primary_value = bias
effective_value = bias
secondary_value = null
source = bot
```

Human override co the thay doi:

- `effective_value`: bias chinh dang duoc strategy dung.
- `secondary_value`: bias phu do human set de cho phep mot so setup countertrend/mean reversion.
- Khi override het han, bot detect lai H1 structure theo Bias V2.

## Metadata Output

Bias context luu metadata chinh:

```text
detector = "bias_v2"
version = 2
swing_score
break_score
raw_score
normalized_score
total_weight
latest_break_type
latest_break_direction
latest_choch_direction
neutral_reason
choch_neutralized
range_neutralized
range_efficiency
atr
swing_points
break_points
```

Replay chart dung cung cong thuc voi detector:

```text
detector = "bias_v2_replay"
```

## Example

Input:

```text
recent swings:
HH, HL, HH, HL

recent breaks:
BOS up, CHOCH down
```

Neu weighted score truoc neutralization van bullish nhung latest break la `CHOCH down`:

```text
final bias = neutral
neutral_reason = opposing_choch_down
```

## Notes For Future Optimization

Nhung tham so co the toi uu sau:

```text
BIAS_DIRECTION_THRESHOLD = 0.25
BIAS_RANGE_EFFICIENCY_NEUTRAL_MAX = 0.25
BIAS_RANGE_SCORE_MAX = 0.45
BOS type weight = 1.20
CHOCH type weight = 1.60
```

Neu trend pullback qua it lenh, co the giam threshold. Neu bot vao nhieu lenh khi market chop, co the tang threshold hoac giam `BIAS_RANGE_SCORE_MAX`.
