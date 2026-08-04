# Zone Reaction Strategy V2

Zone Reaction V2 la playbook research-first tap trung vao phan ung M15 tai tung zone rieng le. Playbook nay khong yeu cau confluence nhieu zone de tranh lam dataset qua mong.

## Runtime Scope

`zone_reaction_v2` la playbook runtime/research/backtest chinh cho reject/internal reject. Playbook breakout SR duoc tach rieng thanh `sr_breakout_v1` de tranh tron logic reject va breakout trong cung mot state machine.

Live worker chi dung H1 price zones lam primary trade zones; M15 van la timeframe reaction/trigger/entry. Rule nay giu cho lenh live khop voi zone dang hien thi tren dashboard H1 va tranh trade theo M15 zone ma human khong thay tren chart H1.

Legacy playbooks nhu `trend_pullback`, `ob_mitigation_continuation`, `fvg_fill_go`, `breakout_retest`, `momentum_expansion_continuation`, `range_boundary_reversal`, `liquidity_sweep_reversal`, va `failed_breakout_trap` da duoc ngung khoi strategy runtime. Trade cu trong database van co the hien thi playbook string cu de review lich su, nhung backend/UI/CLI khong con cho chay them cac playbook do.

Playbook runtime hien tai:

- `zone_reaction_v2`: reject/internal reject tai `support`, `resistance`, `fvg`.
- `sr_breakout_v1`: breakout/retest qua `support`, `resistance`. Xem `docs/21-sr-breakout-v1.md`.
- `liquidity_sweep_reclaim_v1`: quote-driven reclaim cua Zone Buy liquidity. Xem `docs/22-liquidity-sweep-reclaim-v1.md`.

## Entity Scope

Primary zone hop le:

- `support`
- `resistance`
- `fvg`

`consolidation` tam thoi bi loai khoi `zone_reaction_v2` vi report dau tien cho thay no tao hon 80% tong trade va lam loang ket qua. `order_block` cung khong duoc dung trong `zone_reaction_v2`. OB va consolidation van co the duoc detect/ve tren chart de human tham khao hoac dung cho playbook khac.

## Reaction V2 States

- `reject`: gia cham zone va dong nen bat nguoc manh.
- `internal_reject`: gia da vao trong zone, sau do co BOS/CHOCH + price action M15 cung huong entry. State nay xu ly FVG/SR rong, khi gia fill sau trong zone nhung chua dong cua ra khoi toan bo zone.
- `fakeout`: gia pha nhe qua zone duoi nguong ATR roi dong quay lai.
- `slow_reaction`: gia nam trong/cham zone nhieu nen M15 than nho, chua co huong ro.
- `waiting_bos`: gia cham zone nhung chua co trigger ro.
- `invalid`: setup khong hop le.
- `far`: gia con xa zone.

Zone Reaction V2 khong detect breakout va khong tao state breakout/retest. Toan bo breakout/retest cua Support/Resistance thuoc `sr_breakout_v1`.

## Defaults

```toml
[strategy.playbooks.zone_reaction_v2]
enabled = true
allowed_reactions = ["reject", "internal_reject"]
fakeout_max_atr = 0.5
reject_body_min_ratio = 1.5
reject_avg_body_period = 20
slow_min_bars = 3
slow_max_bars = 8
slow_body_max_ratio = 0.8
rr_minimum = 2.5
stop_buffer_atr = 0.2
min_stop_price = 4.0
min_stop_atr = 1.5
max_stop_distance = 25.0
reject_wide_stop_fallback = "atr"
reject_atr_stop = 1.2
impulse_limit_range_atr = 4.0
impulse_limit_extension_atr = 1.0
impulse_limit_expiry_bars = 8
require_trigger_for_fakeout = true
fakeout_max_reaction_depth_atr = 1.5
internal_reject_enabled = true
internal_reject_requires_structure = false
internal_reject_sr_requires_structure = false
internal_reject_requires_price_action = true
internal_reject_watch_after_fvg_fill_bars = 8
internal_reject_body_min_ratio = 1.5
internal_reject_min_fill_ratio = 0.4
internal_reject_deep_fvg_fill_ratio = 0.8
internal_reject_stop_buffer_atr = 0.4
allow_neutral_range_trade = true
block_news_or_risk_off = true
fvg_max_trades_per_zone = 2
confluence_score_bonus = 0.08

[backtest]
zone_loss_cooldown_candles = 12
```

`slow_max_bars = 8` nghia la slow reaction chi cho BOS/CHOCH toi da 8 nen M15.

## Trade Modes

Moi zone co `metadata.trade_modes` quyet dinh reaction family nao duoc trade:

- Default theo zone type: `support`/`resistance` = `["reject"]`, `fvg` = `["reject", "internal_reject"]`.
- Support/Resistance do human tao bat dau voi `status=draft`. Trade modes van
  duoc luu/chinh trong Draft nhung inert; Zone Reaction V2 va SR Breakout V1 chi
  duoc evaluate sau khi questionnaire confirm doi zone thanh `active`.
- `visual_end` chi la chart projection cua `price_zones.end_time`; playbook
  khong duoc dung field presentation nay de quyet dinh eligibility. Runtime dung
  `status`, `valid_until` va `invalidated_at`. FVG mitigated watch window cung
  lay fill/lifecycle time tu `invalidated_at` hoac `valid_until`.
- Khi tao manual zone, frontend gui default nay va backend validate/lưu explicit vao `metadata.trade_modes`; backend cung dung cung default cho zone cu chua co field de UI va strategy khong lech nhau.
- Zone do human ve/chinh sua duoc xem la human thesis va **bypass toan bo context gate** (bias/regime/news/macro trend) cho family duoc trade. Human van co the set explicit `trade_modes` tren UI de gioi han family; cac dieu kien chat luong tin hieu (reject body, internal reject trigger, RR) van ap dung.
- Trong live mode, human manual zone chi duoc generate setup tu candle co open time bang hoac sau thoi diem zone duoc tao (`created_at`). Cac lan human keo/chinh zone sau do (`last_human_override_at`) khong reset activation, vi trader co the tinh chinh zone cho phu hop thi truong khi gia dang chay. `visual_start` chi de ve chart, khong duoc dung de backdate setup tren candle da mo truoc khi human ve zone.
- He qua: bot SR zone khong con trade `internal_reject` theo default; muon internal reject tren SR zone cu the thi human set `trade_modes = ["reject", "internal_reject"]`.
- Neu human set SR zone chi `trade_modes = ["internal_reject"]`, cac state tien-xac-nhan nhu `slow_reaction`/`waiting_bos` van duoc emit len UI de debug va cho BOS/CHOCH + price action; chung chi thanh `eligible` khi promote duoc thanh `internal_reject`.
- Metadata candidate ghi `context_bypass` va `trade_modes` de debug.

## Context Rules

- `bullish`: chi long.
- `bearish`: chi short.
- `neutral + ranging`: cho phep trade hai chieu theo phan ung zone.
- `news` hoac `risk_off`: block setup neu `block_news_or_risk_off = true`.

Neu gia dong cua xuyen qua phia invalid cua zone, Zone Reaction V2 dung theo doi reaction do, khong emit candidate breakout va khong carry-forward reject cu. Neu zone cho phep `trade_modes = ["breakout"]`, `sr_breakout_v1` se xu ly breakout/retest doc lap theo `docs/21-sr-breakout-v1.md`.

Slow reaction khong vao ngay. Bot chuyen sang `waiting_bos`; neu BOS/CHOCH M15 xuat hien cung huong trong window cho phep thi setup moi thanh `eligible`.

## Entry And Stop Rules

Phase hien tai la reject-family. Chi `reject` va `internal_reject` duoc phep tao trade setup `eligible`.

`fakeout`, `waiting_bos` va cac reaction reject-family khac van co the duoc detect/ghi metadata de debug hoac research, nhung khong duoc tao trade trong `zone_reaction_v2` khi chung khong nam trong `allowed_reactions`.

Strong body reject phai dung mau nen theo huong entry: long reject can bullish candle (`close > open`), short reject can bearish candle (`close < open`). Neu candle cham resistance/support co wick reject nhung dong nguoc mau, setup khong duoc promote thanh strong reject; no chuyen sang `waiting_bos` voi metadata `wick_reject=true`. Candle ke tiep moi duoc promote thanh `reject` khi xac nhan cung huong: short can bearish candle pha low cua wick candle, long can bullish candle pha high cua wick candle.

Moi trade `reject` va `internal_reject` luu snapshot body-strength trong candidate/order metadata:

- `reaction_avg_body`: average body M15 dung tai thoi diem runtime.
- `reaction_body_avg_ratio`: `reaction_body / reaction_avg_body`.
- `reaction_body` luon la than nen that `abs(close - open)`, ke ca voi pinbar.
- Pinbar luu them `reaction_trigger_method = pinbar`,
  `reaction_rejection_size` (khoang cach tu wick extreme ve close), va
  `reaction_rejection_avg_ratio = reaction_rejection_size / reaction_avg_body`.
  Khong ghi de rejection size vao `reaction_body`, de giu cung mot semantics
  cho report va thong ke giua strong-body reject, pinbar va internal reject.

Snapshot nay giu report va research dung voi quyet dinh runtime ngay ca khi bang candle sau nay duoc import lai. Trade cu khong co hai field van duoc report reconstruct tu historical M15 candles.

Impulse reject khong duoc chase market neu gia da dong cua qua xa zone. Voi `reject`:

- Neu range cua nen reaction `> impulse_limit_range_atr * ATR_M15`.
- Va close extension khoi zone edge `> impulse_limit_extension_atr * ATR_M15`.
- Long support/bullish FVG dat `limit` tai `zone_high`; short resistance/bearish FVG dat `limit` tai `zone_low`.
- TP duoc tinh lai tu limit entry theo `rr_minimum`; SL giu theo stop logic hien tai.
- Limit expire sau `impulse_limit_expiry_bars` nen M15 tinh tu khi setup xuat hien sau close cua nen signal.

Candidate co `metadata.carried_forward = true` chi giu mot setup vua xuat hien
tren UI/live polling sau khi gia roi zone. No khong phai signal execution moi:
backtest va research phai loai candidate nay, thay vi fill tai open cua nen hien
tai ke tiep. Signal goc da duoc backtest tai chinh candle `metadata.as_of`.

### Macro Trend Gate

Backtest 2023-2026 cho thay counter-macro trade co edge am ro rang: short tai resistance trong gold uptrend thua `-22.7R` tren 83 trades, trong khi long tai support thang `+20.8R`. MA200 H1 khong tach duoc edge, nhung momentum ~30 ngay thi co.

Detector `macro_trend_v1` (`semi_bot_trading/context.py`) tinh:

```text
momentum = close_now - close_{lookback_candles truoc}
momentum_atr = momentum / ATR_H1
```

Classification:

```text
momentum_atr >  flat_threshold_atr  => up
momentum_atr < -flat_threshold_atr  => down
con lai                             => flat
khong du lich su (< lookback)       => unknown
```

Config:

```toml
[context.macro_trend]
detector = "macro_trend_v1"
timeframe = "H1"
lookback_candles = 720
flat_threshold_atr = 0.0
atr_period = 14

[strategy.playbooks.zone_reaction_v2]
macro_gate_enabled = true
fvg_macro_gate_enabled = true
```

Gate rule cho SR khi `macro_gate_enabled = true`:

- `macro_trend = up`: block moi short setup (`Macro trend up blocks Zone Reaction V2 short.`).
- `macro_trend = down`: block moi long setup.
- `flat` hoac `unknown`: cho phep hai chieu (gate degrade gracefully khi thieu lich su).

Bot-detected FVG dung combined gate rieng khi `fvg_macro_gate_enabled = true`:

- Bullish FVG/LONG duoc phep neu `H1 bias = bullish` **hoac** `macro_trend = up`.
- Bearish FVG/SHORT duoc phep neu `H1 bias = bearish` **hoac** `macro_trend = down`.
- Chi block khi ca hai context deu khong support direction. Vi du bullish FVG voi `bias = bearish` va `macro = down` se bi block; `bias = bullish, macro = down` van duoc phep.
- Human FVG van bypass context gate nhu cac human zone khac.

Macro trend la context type `macro_trend` trong `market_contexts`, nen human co the override `effective_value` nhu bias/regime. Backtest incremental tinh point-in-time tu H1 candles co san tai signal candle, khong dung gia tri persisted de tranh look-ahead.

CLI cho runtime/dashboard:

```bash
python -m semi_bot_trading.cli detect-macro-trend
```

Metadata trade ghi them `macro_trend` de research/debug.

Luu y: data 2023-2026 toan bull market. Gate nay chua duoc kiem chung trong bear/sideway market dai han; khi co data bear, can re-validate truoc khi tin short side.

### Internal Reject For Wide/Deep Zones

Classic `reject` yeu cau gia dong cua ra khoi toan bo zone:

- Long tai support/bullish FVG: close tren `zone_high`.
- Short tai resistance/bearish FVG: close duoi `zone_low`.

Rule nay tot voi zone hep, nhung co the bo lo FVG/SR rong. Voi zone rong, gia co the fill sau vao trong zone, tao BOS/CHOCH + price action dao chieu ngay ben trong zone, roi moi bat di. Cho nen `internal_reject` cho phep vao lenh khi close van nam trong zone.

Dieu kien `internal_reject`:

- Zone type: `support`, `resistance`, hoac `fvg`.
- Candle M15 da touch/di vao zone va close van nam trong zone.
- Structure trigger (`BOS`/`CHOCH` cung huong entry) khong bat buoc cho SR zone khi `internal_reject_sr_requires_structure = false`; SR internal reject co the vao bang price action manh trong zone. FVG cung khong bat buoc structure theo `internal_reject_requires_structure = false`.
- Co price action trigger cung huong entry: `engulfing`, `pinbar`, `marubozu`, `morning/evening star`, hoac `displacement`.
- Structure trigger va price action duoc phep nam trong cung reaction window `internal_reject_watch_after_fvg_fill_bars`, khong bat buoc cung mot nen M15. Tuy nhien it nhat mot trigger phai xuat hien o nen signal hien tai de tranh reuse tin hieu cu.
- Nen reaction phai co than cung huong entry va dat `internal_reject_body_min_ratio = 1.5` lan average body 20 nen M15, cung baseline voi classic reject. Pinbar than nho van duoc detect lam PA nhung khong duoc promote thanh internal reject neu body gate khong dat.
- SR va FVG deu phai fill it nhat `internal_reject_min_fill_ratio = 0.4` theo chieu rong zone. Support/bullish FVG do tu canh tren xuong reaction low; resistance/bearish FVG do tu canh duoi len reaction high. SR khong con dung penetration/ATR, tranh cung mot nguong ATR mang y nghia khac nhau tren zone hep va zone rong.
- FVG da `mitigated` van duoc quan sat them `internal_reject_watch_after_fvg_fill_bars = 8` nen M15 sau fill neu chua expired.

Direction:

- `support` hoac bullish `fvg`: chi long.
- `resistance` hoac bearish `fvg`: chi short.
- Context van ap dung nhu cu: bullish chi long, bearish chi short, neutral+ranging cho phep hai chieu, news/risk_off bi block.

Metadata trade ghi them:

- `reaction_v2 = internal_reject`
- `internal_reject_reason`
- `fill_ratio`
- `zone_width_atr`
- `inside_zone_close_position`
- `structure_trigger_types`
- `price_action_trigger_types`

Khac voi `fakeout`: `internal_reject` khong yeu cau gia phai wick xuyen qua bien zone roi close reclaim. No chi can phan ung dao chieu co BOS/CHOCH + PA ben trong zone.

Fakeout co penetration nho qua zone nhung ca cay nen quet qua sau cung khong vao ngay. Bot do:

```text
fakeout_reaction_depth_atr = abs(close - wick_extreme) / ATR_M15
```

Neu `fakeout_reaction_depth_atr > 1.5`, setup giu trang thai `waiting_confirmation`. Ly do: nhom fakeout co wick qua sau thuong tao SL lon va de bi nhieu.

Classic reject dat stop ngoai zone/reaction wick voi buffer:

```text
buffer = max(0.2 * ATR_M15, 0.01)
```

Sau do stop duoc noi rong neu risk qua nho:

```text
min_stop_distance = max(min_stop_price, min_stop_atr * ATR_M15)
default = max(4.0 gia, 1.6 * ATR_M15)
```

Voi XAUUSD H1/M15, rule nay tranh cac lenh co SL qua chat nhu 0.6-3 gia, la nhom trade backtest dang co ket qua rat kem.

Sau khi tinh stop, neu stop distance qua lon, bot khong block setup. `max_stop_distance` chi la nguong kich hoat fallback sang SL theo ATR:

```text
max_stop_distance = 25.0 gia
```

Voi classic `reject`, bot mac dinh uu tien stop ngoai toan bo zone. Neu stop theo zone qua rong, bot fallback sang wick cua nen phan ung. Wick fallback chi hop le khi SL nam ngoai H1 zone; neu wick SL van nam trong zone, bot bo qua wick va fallback tiep sang ATR H1. Neu bat ky stop theo zone/wick cua `reject`, `internal_reject`, `slow_reaction`, `waiting_bos`, hoac `fakeout` van qua rong va:

```toml
reject_wide_stop_fallback = "atr"
```

bot dung ATR stop theo H1 context:

```text
long:  stop = entry - max(min_stop_distance, reject_atr_stop * ATR_H1)
short: stop = entry + max(min_stop_distance, reject_atr_stop * ATR_H1)
```

ATR_H1 o day la ATR cua timeframe context/zone, giup fallback SL ton trong bien do H1 thay vi bi keo qua sat theo M15 trigger. Neu caller khong truyen H1 candles thi bot fallback ve ATR cua strategy timeframe, nhung runtime/backtest/dashboard chinh deu truyen H1 context candles. Khoang stop fallback nay la lop cuoi cung nen **khong bi cap boi `max_stop_distance`**; `max_stop_distance` chi la nguong kich hoat fallback tu zone/reaction-wick sang ATR stop, khong con la hard block. Cac state cho xac nhan nhu `slow_reaction`/`waiting_bos` van giu `waiting_confirmation`, khong chuyen sang `blocked` chi vi SL placeholder qua xa.

Voi FVG, neu stop theo full zone/reaction wick vuot `max_stop_distance` va `reject_wide_stop_fallback = "atr"`, bot fallback truc tiep ve ATR cua H1 context:

```text
long FVG:  stop = entry - max(min_stop_distance, reject_atr_stop * ATR_H1)
short FVG: stop = entry + max(min_stop_distance, reject_atr_stop * ATR_H1)
```

Mac dinh `reject_atr_stop = 1.2`, nen FVG rong khong bi bo lo chi vi SL bi neo vao dau kia cua zone, nhung SL van rong theo bien do H1.

### FVG Trade Count Cap

Mot FVG co the cho phan ung tot lan dau, nhung cac lan fill/retest sau thuong nhieu nhieu hon. De tranh bot lap lai qua nhieu lenh tren cung mot FVG, backtest/live executor gioi han:

```toml
fvg_max_trades_per_zone = 2
```

Nghia la moi `primary_zone_id` co `zone_type = fvg` chi duoc accept toi da 2 trade. Candidate thu 3 tro di bi bo qua truoc khi chon best setup. Backtest dem in-memory trong tung run; live worker dem cac `trade_orders.source = live` da luu trong DB. Set `0` de tat gioi han nay khi can research full sample.

Rieng `internal_reject`, stop khong dat qua toan bo zone nua. Bot dat stop theo wick cua nen phan ung:

```text
internal_buffer = max(internal_reject_stop_buffer_atr * ATR_M15, 0.01)
long internal_reject:  stop = reaction_low - internal_buffer
short internal_reject: stop = reaction_high + internal_buffer
```

Mac dinh `internal_reject_stop_buffer_atr = 0.4`. Wick SL cua internal reject
duoc phep nam trong parent zone, vi diem invalidation la reaction wick thay vi
bien ngoai cua toan bo zone. Sau do bot van ap dung `min_stop_distance`; neu
khoang SL vuot `max_stop_distance`, bot moi fallback sang ATR H1. Cach nay tranh
truong hop zone SR/FVG rat rong lam SL bi day ve dau kia cua zone.

## Live Intrabar Evaluation

Live worker luu nen MT5 cuoi cung vao bang `live_candles` thay vi ghi vao bang nen da dong. Detector SR/FVG/structure van chi cap nhat khi co M15 dong nen moi. Neu muon bot nhin thay wick touch/reject trong nen dang chay, bat:

```text
LIVE_EVALUATE_INTRABAR=true
```

Khi bat, worker se build setup candidates moi poll bang live candle moi nhat. Dieu nay giup ghi nhan touch som hon, nhung cung co nghia live execution co the vao lenh truoc khi nen M15 dong. Khi de `false`, bot chi evaluate setup khi co M15 dong nen moi.

Luu y: intrabar candle chi them OHLC dang chay vao strategy evaluation. Structure/price-action detectors van chi cap nhat tren nen M15 da dong, nen cac setup can BOS/CHOCH + PA (nhu `internal_reject` tren SR zone) van phai doi trigger confirmed tru khi trigger do da co san trong reaction window.

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

## Research Telemetry

Strategy hien dang luu them RSI H1 vao metadata de phuc vu thong ke sau nay, chua dung RSI de filter entry:

- `rsi_h1`: RSI Wilder period 14 tren H1 closed candles tai thoi diem signal.
- `rsi_h1_slope_3`: `rsi_h1` hien tai tru RSI H1 cua 3 nen H1 truoc.
- `rsi_h1_slope_5`: `rsi_h1` hien tai tru RSI H1 cua 5 nen H1 truoc.
- `rsi_h1_as_of`: H1 candle time duoc dung de tinh RSI.

Replay/backtest truyen point-in-time H1 candles vao strategy engine, nen cac field nay khong duoc tinh bang candle tuong lai. UI cung hien thi box `RSI(14)` tren context strip de human doc nhanh RSI H1 va slope 3/5.

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
