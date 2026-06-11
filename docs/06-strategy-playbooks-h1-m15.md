# 06 - Strategy Playbooks H1 + M15

> Legacy note: file nay la tai lieu lich su ve bo multi-playbook ban dau.
> Runtime hien tai chi chay `zone_reaction_v2`; xem `docs/19-zone-reaction-v2.md`
> de doc strategy source of truth trong phase hien tai.

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
- Displacement candle.
- SL/invalid level gần hơn.

Price action confirmation hiện được detect bằng `price_action_v1` trên M15 và lưu trong `structure_points`.
Chi tiết công thức nằm ở `docs/13-price-action-detectors-formula.md`.

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

## Zone Reaction State On M15

Strategy Engine không vào setup chỉ vì giá chạm zone. Mỗi zone quan trọng được tracking phản ứng trên M15:

- `approaching`: giá cách zone trong khoảng gần theo ATR.
- `touched`: wick/body đã chạm zone.
- `inside_wait`: giá chạm/phá zone nhưng close vẫn nằm trong zone, cần chờ tiếp.
- `rejected`: giá chạm/phá nhẹ rồi close ngược khỏi zone theo hướng kỳ vọng.
- `breakout_confirmed`: close rõ ngoài zone với buffer ATR.
- `retest_waiting`: consolidation/range breakout đã xác nhận, chờ retest.
- `invalid_for_setup`: vùng không còn dùng được cho playbook đang xét.

Dashboard hiển thị setup theo status:

- `watching`: gần đủ điều kiện, đang đợi giá/trigger.
- `waiting_confirmation`: đã có tương tác với zone nhưng thiếu confirmation.
- `eligible`: đủ điều kiện để human review.
- `blocked`: có ý tưởng nhưng bị rule chặn.
- `expired`: hết hiệu lực.

## Playbook priority

1. Trend Pullback.
2. OB Mitigation Continuation.
3. FVG Fill And Go.
4. Breakout Retest.
5. Momentum Expansion Continuation.
6. Range Boundary Reversal.
7. Liquidity Sweep Reversal.
8. Failed Breakout Trap.

Trend Pullback vẫn là playbook ưu tiên đầu tiên vì bền vững hơn cho retail trader. Các playbook countertrend chỉ được dùng tự động trong neutral/ranging hoặc khi human set secondary bias phù hợp.

## Playbook 1: Trend Following Pullback

Điều kiện:

- H1 bias cùng hướng rõ.
- H1 regime trending.
- Giá chạm support/resistance hoặc FVG theo hướng H1 bias.
- Order Block chỉ dùng làm confluence phụ trong Trend Pullback, không dùng làm primary entry zone ở phiên bản hiện tại.
- Entry cần tối thiểu 3 confluence:
  - H1 bias đúng hướng.
  - Giá chạm vùng pullback hợp lệ.
  - M15 confirmation: displacement mạnh + price action candle như engulfing/pinbar/marubozu hoặc BOS.
- Không guess entry khi chưa có trigger rõ ràng.

Long example:

```yaml
required_context:
  h1_bias: bullish
  h1_regime: trending
  zone:
    type_any: [support, fvg]
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

## Additional Playbooks V1

### OB Mitigation Continuation

- Dùng OB cùng hướng H1 bias.
- Ưu tiên OB chưa mitigated hoặc mitigated nhẹ.
- M15 phải reject khỏi OB hoặc có displacement cùng hướng.

### FVG Fill And Go

- Dùng FVG cùng hướng H1 bias.
- Nếu giá close trong FVG thì setup ở `waiting_confirmation`.
- Eligible khi có M15 rejection/PA cùng hướng sau fill.

### Momentum Expansion Continuation

- Dùng khi H1 có expansion overlay và bias rõ.
- Chỉ chấp nhận pullback nông vào SR/OB/FVG.
- Cần M15 displacement cùng hướng.

### Failed Breakout Trap

- Dùng khi breakout khỏi consolidation/range thất bại và close quay lại bên trong.
- Entry theo hướng ngược breakout sau M15 confirmation.
- Target range mid hoặc biên còn lại.

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

## Setup Candidate Object

Chart payload có thêm `layers.setup_candidates` để UI hiển thị các setup đang được Strategy Engine theo dõi:

```yaml
setup_candidate:
  id: string
  symbol: string
  timeframe: M15
  playbook: string
  direction: long | short
  status: watching | waiting_confirmation | eligible | blocked | expired
  zone_reaction_state: string
  score: float
  entry: decimal | null
  stop_loss: decimal | null
  take_profit: decimal[]
  risk_reward: float | null
  primary_zone_id: string | null
  related_zone_ids: string[]
  trigger_point_ids: string[]
  reason: string[]
  blocked_reason: string[]
  expires_at: datetime | null
  metadata: json
```

## Human confirmation modes

Mode đề xuất:

- `observe_only`: chỉ chart + alert.
- `backtest_replay`: replay historical XAUUSD và tạo trade/backtest result.
- `semi_auto_confirm`: bot đề xuất, human confirm, executor đặt lệnh.
- `semi_auto_confirm_timeout`: live phase sau này, human confirm trên UI; sau 5 phút chưa confirm thì vào limit nếu giá đã tệ hơn entry mong muốn, hoặc market nếu giá tốt hơn.
- `full_auto`: chưa nên triển khai trước khi có đủ log/backtest.

MVP bắt đầu với `observe_only` và `backtest_replay`.

Realtime dashboard không auto accept setup. Human vẫn phải review/approve trước khi có live execution.

Backtest thì auto accept các setup `eligible` theo rule của Strategy Engine để đo kết quả playbook. Engine mặc định là `incremental`.

Backtest guard:

- Signal chỉ được tạo từ dữ liệu có `time <= signal_time`.
- Swing chỉ được dùng sau `confirmed_at`, không dùng pivot chưa confirm.
- Incremental engine precompute detector theo chunk lịch sử, nhưng mỗi candle chỉ expose zone/structure/context đã xuất hiện tại thời điểm đó.
- Entry fill ở nến M15 kế tiếp, không dùng giá của candle signal để vào lệnh.
- Entry fill ở nến M15 kế tiếp theo bid/ask side và adverse slippage.
- Sau khi có entry fill, TP được tính lại theo risk thực tế để giữ target RR của setup.
- Exit SL/TP dùng bid/ask side theo hướng đóng vị thế; không cộng thêm slippage ở exit trong model mặc định.
- Nếu cùng một candle chạm cả SL và TP, simulator giả định SL hit trước để conservative.

Config:

```toml
[backtest]
auto_accept = true
spread = 0.30
slippage = 0.10
max_hold_candles = 96
warmup_candles = 80
```

CLI:

```bash
python -m semi_bot_trading.cli backtest-strategies --limit 500
```

Full local dataset:

```bash
python -m semi_bot_trading.cli backtest-strategies --limit 60000 --engine incremental --persist --clear-backtest-trades
```

Persist run/trades so chart payload can draw historical entry/exit:

```bash
python -m semi_bot_trading.cli backtest-strategies --limit 500 --persist --clear-backtest-trades
```

Reference replay-safe mode, slower but useful for comparison:

```bash
python -m semi_bot_trading.cli backtest-strategies --limit 500 --engine replay
```

Debug observe-only mode:

```bash
python -m semi_bot_trading.cli backtest-strategies --limit 500 --no-auto-accept
```

Persistence:

- `backtest_runs`: one row per run with config/costs/lookahead guard/summary.
- `trade_ideas`: one executed idea per auto-accepted setup.
- `trade_orders`: filled backtest order with entry, SL, TP, close price, `pnl_r`, source=`backtest`.
- `trade_fills`: synthetic entry and exit fills for audit.

Current benchmark on local XAUUSD dataset:

- `500` M15 candles: incremental ~0.36s vs replay ~4.97s.
- `60000` M15 candles: chunked incremental ~52s, 2191 trades persisted.

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
