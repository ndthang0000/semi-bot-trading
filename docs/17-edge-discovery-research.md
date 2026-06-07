# Edge Discovery Research Workflow

Muc tieu cua workflow nay la tam dung viec viet strategy theo cam tinh, chuyen sang thong ke event-level de tim edge truoc.

## 1. Tu duy chinh

Backtest trade chi tra loi:

```text
Strategy hien tai co loi khong?
```

Research event tra loi:

```text
Dieu kien nao tren chart co xac suat/expectancy tot?
```

Vi vay research dataset khong chi gom trade da vao lenh. No gom cac setup candidate ma bot thay duoc tai thoi diem candle da dong:

- `eligible`
- `waiting_confirmation`
- tuy chon them `watching`
- tuy chon them `blocked`

Moi sample se duoc do outcome tu candle M15 tiep theo, co tinh spread/slippage va max hold.

## 2. Chia data

Mac dinh:

```text
train      <= 2024
validation = 2025
test       >= 2026
```

Cach dung:

- Tim y tuong/filter tren `train`.
- Kiem tra lai tren `validation`.
- Chi dung `test` de xac nhan cuoi, khong toi uu truc tiep tren test.

## 3. Generate research CSV

Tat ca playbook:

```bash
python -m semi_bot_trading.cli research-events \
  --limit 30000 \
  --output var/research_events.csv
```

Rieng Trend Pullback:

```bash
python -m semi_bot_trading.cli research-events \
  --limit 30000 \
  --playbook trend_pullback \
  --output var/research_trend_pullback.csv
```

Mac dinh chi sample:

```text
eligible,waiting_confirmation
```

Neu muon xem ca setup bi block:

```bash
python -m semi_bot_trading.cli research-events \
  --limit 30000 \
  --statuses eligible,waiting_confirmation,blocked \
  --output var/research_with_blocked.csv
```

## 4. Generate report

Text + HTML:

```bash
python -m semi_bot_trading.cli research-report \
  --input var/research_events.csv \
  --html-output var/reports/research_events.html
```

Rieng Trend Pullback:

```bash
python -m semi_bot_trading.cli research-report \
  --input var/research_trend_pullback.csv \
  --html-output var/reports/research_trend_pullback.html
```

## 5. CSV Columns

Core fields:

```text
event_id
split
signal_year
signal_time
entry_time
exit_time
playbook
direction
candidate_status
exit_status
pnl_r
mfe_r
mae_r
risk_reward
score
```

Market context:

```text
h1_bias
h1_regime
overlays
```

Zone/context:

```text
zone_type
zone_direction
zone_detector
zone_source
zone_weight
zone_confidence
zone_width_atr
zone_touch_count
zone_fill_ratio
zone_mitigation_ratio
zone_reaction_state
```

Trigger/reason:

```text
trigger_types
primary_zone_id
blocked_reason
reason
```

## 6. Metrics

Report gom:

- Samples
- Wins/losses
- Win rate
- Total R
- Avg R
- Profit factor
- Avg MFE R
- Avg MAE R

`MFE` va `MAE` dung de xem setup co di dung huong truoc khi fail hay khong:

```text
MFE cao + pnl am: co the entry/SL/TP dang sai.
MAE lon: setup bi vao qua som hoac zone/reaction yeu.
```

## 7. Cach doc edge

Mot condition set chi dang quan tam khi:

```text
samples du lon
avg_R > 0
profit_factor > 1.2
ket qua train va validation cung huong
khong chi tot trong 1 nam duy nhat
MFE/MAE hop ly
```

Neu mot edge chi tot o train nhung te o validation/test, coi nhu overfit.

## 8. Lookahead Guard

Research event dung incremental closed-candle snapshots:

```text
Candidate context, zones, structure, and triggers are only exposed up to signal candle close.
Outcome is measured from next M15 candle open.
```

Replay/backtest/research deu dung nguyen tac nay de tranh look-ahead bias.

## 9. Next Analysis Path

Thu tu nen lam:

1. Chay research tat ca playbook.
2. Xem `By split` de biet edge co ton tai across years khong.
3. Xem `Potential condition sets`.
4. Loc theo playbook co trien vong nhat.
5. Chay research rieng playbook do.
6. Tim filter ung vien.
7. Chi sau do moi sua Strategy Engine.
