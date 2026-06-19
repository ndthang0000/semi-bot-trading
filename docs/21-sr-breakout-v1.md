# SR Breakout V1

`sr_breakout_v1` la playbook rieng cho trade breakout qua vung Support/Resistance tren H1. Playbook nay tach khoi `zone_reaction_v2` de khong tron reject/internal reject voi breakout.

## Entity Scope

Chi dung:

- `support`
- `resistance`

Zone co the do bot detect hoac human tao/chinh. Default trade mode cua support/resistance la `["reject"]`, nen `sr_breakout_v1` chi dung zone khi:

- Human bat `trade_modes` co `breakout`, hoac
- Config research bat `allow_bot_sr_breakout = true`.

Metadata luu tren `price_zones.metadata_json.trade_modes`, vi vay khong can migration DB.

## Macro Gate

Macro trend la gate chinh:

- `macro_trend = up`: chi long khi H1 breakout len tren resistance.
- `macro_trend = down`: chi short khi H1 breakout xuong duoi support.
- `macro_trend = flat/unknown`: khong trade bot zone. Neu human bat `breakout`, zone van duoc phep tao setup theo loai zone:
  - resistance -> long
  - support -> short

Human `breakout` mode bypass bias/regime gate, nhung khong bypass macro trend nguoc huong. Vi du macro `down` thi resistance breakout long van bi bo qua.

## Breakout Rules

Tin hieu xac nhan la nen H1 da dong:

- Long breakout resistance: `close > zone_high + 0.15 ATR_H1`.
- Short breakout support: `close < zone_low - 0.15 ATR_H1`.

Khoang cach close so voi zone quyet dinh entry model:

- Neu distance <= `0.5 ATR_H1`: setup `eligible`, entry theo next open/backtest fill.
- Neu distance > `0.5 ATR_H1`: setup `waiting_retest`, khong chase breakout candle.
- Retest het han sau `8` nen H1.

Retest:

- Long: sau breakout xa len tren resistance, gia quay lai cham vung bi pha va dong lai tren zone.
- Short: sau breakout xa xuong duoi support, gia quay lai cham vung bi pha va dong lai duoi zone.

## Entry, SL, TP

Entry:

- Setup dung close cua nen signal lam planned entry trong candidate.
- Backtest engine hien tai fill lenh o next candle open theo co che chung.

Stop loss:

- Long: `entry - 1.5 * ATR_M15`
- Short: `entry + 1.5 * ATR_M15`

ATR_H1 van duoc dung cho dieu kien breakout/retest, nhung rieng SL dung ATR_M15 entry-timeframe de khong bi keo qua rong.

Take profit:

- TP = `2R`

Risk filters:

- Khong dung min stop `4.0` cua `zone_reaction_v2`.
- Block setup neu stop distance > `max_stop_distance`, default `40` gia.

## Config

```toml
[strategy.playbooks.sr_breakout_v1]
enabled = true
allow_bot_sr_breakout = false
breakout_buffer_atr = 0.15
market_entry_max_distance_atr = 0.5
retest_max_bars = 8
sl_atr = 1.5
rr = 2.5
max_stop_distance = 60.0
```

## State Machine

```text
IDLE
  -> BREAKOUT_CONFIRMED
  -> WAITING_RETEST
  -> RETEST_CONFIRMED
  -> PREPARE_ENTRY
```

Gan breakout:

```text
IDLE -> BREAKOUT_CONFIRMED -> PREPARE_ENTRY
```

Breakout xa:

```text
IDLE -> BREAKOUT_CONFIRMED -> WAITING_RETEST
```

Retest hop le:

```text
WAITING_RETEST -> RETEST_CONFIRMED -> PREPARE_ENTRY
```

## Backtest

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 60000 \
  --engine incremental \
  --playbook sr_breakout_v1 \
  --persist \
  --clear-backtest-trades \
  --html-output var/reports/sr_breakout_v1.html
```

Neu muon research bot SR tu dong breakout, bat trong `config/trading.toml`:

```toml
[strategy.playbooks.sr_breakout_v1]
allow_bot_sr_breakout = true
```

Sau khi test xong nen tat lai neu chi muon human opt-in zone breakout.
