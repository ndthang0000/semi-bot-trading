# Zone Reaction Strategy V2

Zone Reaction V2 la playbook research-first tap trung vao phan ung M15 tai tung zone rieng le. Playbook nay khong yeu cau confluence nhieu zone de tranh lam dataset qua mong.

## Runtime Scope

`zone_reaction_v2` la playbook runtime/research/backtest duy nhat trong phase hien tai.

Legacy playbooks nhu `trend_pullback`, `ob_mitigation_continuation`, `fvg_fill_go`, `breakout_retest`, `momentum_expansion_continuation`, `range_boundary_reversal`, `liquidity_sweep_reversal`, va `failed_breakout_trap` da duoc ngung khoi strategy runtime. Trade cu trong database van co the hien thi playbook string cu de review lich su, nhung backend/UI/CLI khong con cho chay them cac playbook do.

## Entity Scope

Primary zone hop le:

- `support`
- `resistance`
- `fvg`

`consolidation` tam thoi bi loai khoi `zone_reaction_v2` vi report dau tien cho thay no tao hon 80% tong trade va lam loang ket qua. `order_block` cung khong duoc dung trong `zone_reaction_v2`. OB va consolidation van co the duoc detect/ve tren chart de human tham khao hoac dung cho playbook khac.

## Reaction V2 States

- `reject`: gia cham zone va dong nen bat nguoc manh.
- `fakeout`: gia pha nhe qua zone duoi nguong ATR roi dong quay lai.
- `slow_reaction`: gia nam trong/cham zone nhieu nen M15 than nho, chua co huong ro.
- `clean_breakout`: gia dong cua vuot zone voi body du lon.
- `waiting_bos`: gia cham zone nhung chua co trigger ro.
- `waiting_retest`: da co clean breakout cung bias, dang cho gia retest lai zone.
- `retest_reject`: gia retest lai zone sau clean breakout va bi reject theo huong breakout; co the tao entry.
- `invalid`: setup khong hop le.
- `far`: gia con xa zone.

## Defaults

```toml
[strategy.playbooks.zone_reaction_v2]
enabled = true
allowed_reactions = ["reject"]
fakeout_max_atr = 0.5
reject_body_min_ratio = 1.5
reject_avg_body_period = 20
slow_min_bars = 3
slow_max_bars = 8
slow_body_max_ratio = 0.8
breakout_min_body_atr = 0.8
breakout_min_close_outside_atr = 0.5
consolidation_breakout_body_atr = 1.2
retest_max_bars = 8
rr_minimum = 2.0
stop_buffer_atr = 0.2
min_stop_price = 4.0
min_stop_atr = 1.2
max_stop_distance = 30.0
require_trigger_for_fakeout = true
fakeout_max_reaction_depth_atr = 1.5
allow_neutral_range_trade = true
block_news_or_risk_off = true
confluence_score_bonus = 0.08

[backtest]
zone_loss_cooldown_candles = 12
```

`slow_max_bars = 8` nghia la slow reaction chi cho BOS/CHOCH toi da 8 nen M15.

## Context Rules

- `bullish`: chi long.
- `bearish`: chi short.
- `neutral + ranging`: cho phep trade hai chieu theo phan ung zone.
- `news` hoac `risk_off`: block setup neu `block_news_or_risk_off = true`.

Clean breakout nguoc bias khong vao lenh. Setup se bi block va metadata se co:

- `bias_phase = transition_bullish`
- `bias_phase = transition_bearish`

Clean breakout cung bias khong vao ngay. Bot chuyen sang `waiting_retest`. Khi gia retest lai zone va dong cua reject theo huong breakout, state chuyen thanh `retest_reject` va setup co the thanh `eligible`.

Dieu kien clean breakout V2:

- Body nen breakout >= `breakout_min_body_atr`.
- Close phai nam ngoai zone toi thieu `breakout_min_close_outside_atr`.
- Mac dinh `breakout_min_close_outside_atr = 0.5`, nghia la gia dong cua phai cach bien zone it nhat `0.5 ATR`.
- Rule nay ap dung ca khi detect clean breakout truc tiep va khi tim breakout truoc do de cho phep trade retest.

Slow reaction khong vao ngay. Bot chuyen sang `waiting_bos`; neu BOS/CHOCH M15 xuat hien cung huong trong window cho phep thi setup moi thanh `eligible`.

## Entry And Stop Rules

Phase hien tai la reject-only. Chi `reject` duoc phep tao trade setup `eligible`.

`fakeout`, `waiting_bos`, `retest_reject`, `clean_breakout` va cac reaction khac van co the duoc detect/ghi metadata de debug hoac research, nhung khong duoc tao trade trong `zone_reaction_v2` khi `allowed_reactions = ["reject"]`.

Fakeout co penetration nho qua zone nhung ca cay nen quet qua sau cung khong vao ngay. Bot do:

```text
fakeout_reaction_depth_atr = abs(close - wick_extreme) / ATR_M15
```

Neu `fakeout_reaction_depth_atr > 1.5`, setup giu trang thai `waiting_confirmation`. Ly do: nhom fakeout co wick qua sau thuong tao SL lon va de bi nhieu.

Stop loss duoc dat ngoai zone/reaction wick voi buffer:

```text
buffer = max(0.2 * ATR_M15, 0.01)
```

Sau do stop duoc noi rong neu risk qua nho:

```text
min_stop_distance = max(min_stop_price, min_stop_atr * ATR_M15)
default = max(4.0 gia, 1.2 * ATR_M15)
```

Voi XAUUSD H1/M15, rule nay tranh cac lenh co SL qua chat nhu 0.6-3 gia, la nhom trade backtest dang co ket qua rat kem.

Sau khi tinh stop, bot chan setup neu stop distance qua lon:

```text
max_stop_distance = 30.0 gia
```

Neu `abs(entry - stop_loss) > 30.0`, setup bi `blocked` voi reason `Stop distance ... exceeds ... maximum`. Rule nay tranh cac lenh co SL qua rong lam target 2R qua xa va kho danh gia edge.

Rieng `retest_reject`, stop khong dat qua toan bo zone nua. Bot dat stop theo wick cua nen retest:

```text
long retest_reject:  stop = reaction_low - 0.2 ATR
short retest_reject: stop = reaction_high + 0.2 ATR
```

Sau do van ap dung `min_stop_distance`. Cach nay tranh truong hop zone SR/FVG rat rong lam SL bi day ve dau kia cua zone.

## Backtest Zone Loss Cooldown

Neu mot trade backtest tu `primary_zone_id` bi thua (`pnl_r < 0`), zone do bi khoa khong tao trade moi trong:

```text
zone_loss_cooldown_candles = 12 nen M15
```

Cooldown duoc tinh tu sau nen exit cua trade thua. Rule nay chi khoa dung zone do, khong khoa toan bo playbook va khong anh huong zone khac. Trade thang hoac hoa khong kich hoat cooldown.

Muc tieu: tranh bot vao lien tiep 2-3 lenh tren cung mot zone vua that bai, dac biet voi reject strategy khi gia dang linger quanh vung.

## Confluence

Confluence khong bat buoc. Neu zone dang xet overlap/gan voi zone hop le khac trong `0.25 ATR`, metadata se ghi:

- `confluence_count`
- `confluence_types`
- `confluence_score_bonus`

## Commands

Backtest rieng Zone Reaction V2:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 60000 \
  --engine incremental \
  --playbook zone_reaction_v2 \
  --html-output var/reports/zone_reaction_v2.html
```

Research events rieng Zone Reaction V2:

```bash
python -m semi_bot_trading.cli research-events \
  --limit 60000 \
  --playbook zone_reaction_v2 \
  --output var/research_zone_reaction_v2.csv

python -m semi_bot_trading.cli research-report \
  --input var/research_zone_reaction_v2.csv \
  --html-output var/reports/research_zone_reaction_v2.html
```
