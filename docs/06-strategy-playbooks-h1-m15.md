# 06 - Strategy Playbooks H1 + M15

## Mục tiêu

File này mô tả khung chiến lược, chưa phải rule vào lệnh cuối cùng. Strategy Engine phải đọc effective context đã qua human override, không đọc bot raw context.

MVP tập trung XAUUSD H1 + M15, replay/backtest trước live execution. H1 là bias chính; không dùng H4 trong MVP.

## Multi-timeframe model

H1 dùng để xác định:

- Bias chính.
- Regime.
- Vùng supply/demand, support/resistance, OB, FVG quan trọng.
- Liquidity pool lớn.
- Điều kiện nên trade thuận trend hay range.

M15 dùng để xác định:

- Pullback/entry zone.
- Trigger ngắn hạn.
- Liquidity sweep nhỏ.
- Confirmation candle.
- Price action reversal candle: engulfing, pinbar, morning star, marubozu.
- SL/invalid level gần hơn.

## Context matrix

| H1 Bias | H1 Regime | M15 State | Ưu tiên |
|---|---|---|---|
| Bullish | Trending | Pullback vào demand/OB/FVG | Long continuation, ưu tiên cao nhất |
| Bearish | Trending | Pullback vào supply/OB/FVG | Short continuation, ưu tiên cao nhất |
| Neutral | Ranging | Chạm range high/low | Mean reversion |
| Bullish/Bearish | Expansion | Breakout + retest | Momentum, size giảm |
| Any | High Volatility | Sweep/fakeout nhiều | Thận trọng hoặc đứng ngoài |
| Any | Low Volatility/Contraction | Compression | Chờ breakout |
| Human secondary bias | Ranging/Resistance/Support | Sweep/reclaim rõ | Mean reversion hoặc sweep reversal nếu được human cho phép |

## Playbook priority

1. Trend Pullback.
2. Sweep Reversal.
3. Breakout Retest.
4. Range Reversal.

Trend Pullback là playbook ưu tiên đầu tiên vì bền vững hơn cho retail trader. Range Reversal để sau vì khó và dễ nhiễu.

## Playbook 1: Trend Following Pullback

Điều kiện:

- H1 bias cùng hướng rõ.
- H1 regime trending.
- Giá chạm Order Block + FVG hoặc zone confluence theo hướng H1 bias.
- Entry cần tối thiểu 3 confluence:
  - H1 bias đúng hướng.
  - Giá chạm OB + FVG.
  - M15 confirmation: displacement mạnh + price action candle như engulfing/pinbar/marubozu hoặc BOS.
- Không guess entry khi chưa có trigger rõ ràng.

Long example:

```yaml
required_context:
  h1_bias: bullish
  h1_regime: trending
  zone:
    type_any: [support, order_block, fvg, demand]
    direction: bullish
    weight_min: 0.6
entry_trigger:
  - price_touches_bullish_ob_and_fvg
  - m15_displacement_up
  - m15_engulfing_or_pinbar_or_bos_up
invalidation:
  - below_selected_ob_or_fvg
  - below_nearest_m15_swing_low
stop_loss:
  - zone_plus_swing_buffer_5_to_10_pips_or_atr
take_profit:
  - tp1_min_rr_1_to_2_close_50_percent
  - tp2_next_liquidity_pool_or_strong_sr
```

Alert:

- Khi giá approaching zone.
- Khi giá touched zone.
- Khi M15 trigger xuất hiện.

## Playbook 2: Range Mean Reversion

Điều kiện:

- H1 hoặc M15 regime ranging/consolidation.
- Bias neutral hoặc yếu.
- Hoặc human set secondary bias cho mean reversion.
- Range high/low rõ, có nhiều touch.
- Giá sweep range boundary rồi reclaim.
- Không trade giữa range.

Long tại range low:

```yaml
required_context:
  regime: ranging
  location: range_low
entry_trigger:
  - sweep_below_range_low
  - close_back_inside_range
  - rejection_candle_or_m15_choch_up
invalidation:
  - close_below_sweep_low
targets:
  - range_mid
  - range_high
```

## Playbook 3: Breakout + Retest

Điều kiện:

- Contraction chuyển sang expansion.
- Breakout khỏi consolidation với displacement.
- Retest vùng breakout hoặc FVG/OB tạo bởi breakout.
- ATR xác nhận nếu có; volume là optional vì Exness/MT5 có thể chỉ có tick volume.

Rule:

- Không chase candle breakout đầu tiên nếu range quá lâu hoặc volatility quá cao.
- Ưu tiên retest có risk rõ.
- Alert khi breakout xảy ra, nhưng setup chỉ active sau retest.

## Playbook 4: Liquidity Sweep Reversal

Điều kiện:

- Giá sweep liquidity trên/bên dưới vùng HTF quan trọng.
- Close reclaim lại vùng.
- M15 CHOCH/BOS hoặc displacement ngược hướng sweep.
- Có price action confirmation như engulfing hoặc pinbar.
- H1 regime không phải trending quá mạnh theo hướng sweep.

Use case:

- Sweep high ở resistance H1 trong ranging/high volatility.
- Sweep low ở support H1 trong ranging hoặc bullish pullback.
- Secondary bias do human set có thể cho phép sweep reversal ngược primary bias.

## Playbook 5: No Trade / Stand Aside

Bot phải biết khi nào không nên đề xuất setup.

No-trade conditions:

- H1 bias và M15 bias mâu thuẫn nhưng không có pullback playbook rõ.
- High volatility + wick noise cao.
- Data stale hoặc missing candles.
- Spread/slippage vượt threshold.
- Vùng quan trọng quá gần nhau, RR không đủ.
- Human set regime/bias override thành no-trade hoặc risk-off.
- News/risk-off overlay active.
- Trước/sau tin tức lớn nếu có news filter hoặc human set `news`.
- RR dưới 1:2.

## Trade idea object

```yaml
trade_idea:
  id: string
  symbol: string
  direction: long | short
  playbook: trend_pullback | range_reversion | breakout_retest | liquidity_sweep_reversal
  status: candidate | waiting_confirmation | ready_for_review | approved | rejected | expired
  htf_context_snapshot: json
  mtf_context_snapshot: json
  entry_zone_id: string
  entry_trigger: string
  suggested_entry: decimal | null
  suggested_stop_loss: decimal
  suggested_take_profit: decimal[]
  risk_reward: float
  min_risk_reward: 2.0
  scale_out_plan: json
  confidence: float
  requires_human_confirmation: boolean
  created_at: datetime
  expires_at: datetime
```

## Human confirmation modes

Mode đề xuất:

- `observe_only`: chỉ chart + alert.
- `backtest_replay`: replay historical XAUUSD và tạo trade/backtest result.
- `semi_auto_confirm`: bot đề xuất, human confirm, executor đặt lệnh.
- `semi_auto_confirm_timeout`: live phase sau này, human confirm trên UI; sau 5 phút chưa confirm thì vào limit nếu giá đã tệ hơn entry mong muốn, hoặc market nếu giá tốt hơn.
- `full_auto`: chưa nên triển khai trước khi có đủ log/backtest.

MVP bắt đầu với `observe_only` và `backtest_replay`.

## Risk and trade management defaults

- Risk per trade: 1%.
- Max daily loss: 5%.
- Max trades per day: 10.
- RR tối thiểu: 1:2.
- RR lý tưởng: 1:2.5 đến 1:3.
- Stop loss: kết hợp zone + swing, thêm buffer 5-10 pips hoặc theo ATR.
- TP1: ít nhất 1:2, chốt 50%.
- TP2: liquidity pool hoặc strong S/R tiếp theo.
- MVP chưa làm partial take profit/trailing stop/breakeven automation trong execution; trong backtest có thể mô phỏng TP1/TP2 để đánh giá.

## Metrics cần theo dõi

- Win rate theo playbook.
- Expectancy theo playbook.
- Average R.
- Max adverse excursion.
- Alert-to-trade conversion.
- Human override impact:
  - trade có human override vs không.
  - vùng human chỉnh có phản ứng tốt hơn bot raw không.
- False positive alert rate.

## Decisions hiện tại

- Market: Forex, symbol đầu tiên XAUUSD.
- Timeframe: H1 + M15.
- MVP không dùng M5.
- Volume optional.
- Indicator phụ nên bắt đầu với ATR cho buffer/volatility; EMA/VWAP/ADX để sau nếu cần.
- Session ưu tiên chưa chốt.
