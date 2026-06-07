# Zone Reaction Strategy V2

Zone Reaction V2 la playbook research-first tap trung vao phan ung M15 tai tung zone rieng le. Playbook nay khong yeu cau confluence nhieu zone de tranh lam dataset qua mong.

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
fakeout_max_atr = 0.5
reject_body_min_ratio = 1.5
reject_avg_body_period = 20
slow_min_bars = 3
slow_max_bars = 5
slow_body_max_ratio = 0.8
breakout_min_body_atr = 0.8
consolidation_breakout_body_atr = 1.2
retest_max_bars = 8
rr_minimum = 2.0
allow_neutral_range_trade = true
block_news_or_risk_off = true
confluence_score_bonus = 0.08
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

## Confluence

Confluence khong bat buoc. Neu zone dang xet overlap/gan voi zone hop le khac trong `0.25 ATR`, metadata se ghi:

- `confluence_count`
- `confluence_types`
- `confluence_score_bonus`

## Commands

Backtest rieng Zone Reaction V2:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 30000 \
  --engine incremental \
  --playbook zone_reaction_v2 \
  --html-output var/reports/zone_reaction_v2.html
```

Research events rieng Zone Reaction V2:

```bash
python -m semi_bot_trading.cli research-events \
  --limit 30000 \
  --playbook zone_reaction_v2 \
  --output var/research_zone_reaction_v2.csv

python -m semi_bot_trading.cli research-report \
  --input var/research_zone_reaction_v2.csv \
  --html-output var/reports/research_zone_reaction_v2.html
```
