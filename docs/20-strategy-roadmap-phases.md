# Strategy Roadmap Phases

File nay chia roadmap strategy thanh cac phase nho de trien khai lan luot. Muc tieu la tranh gom qua nhieu y tuong vao mot lan code, giu moi phase co output ro rang, co report/backtest rieng, va co diem dung de review truoc khi sang phase tiep theo.

## Nguyen tac chung

- Khong toi uu strategy bang cam giac; moi thay doi can co backtest hoac research report rieng.
- Tach bach `research` va `production strategy`.
- Khong xoa strategy cu ngay lap tuc; chi disable hoac tach playbook moi de so sanh.
- Replay/backtest phai chong look-ahead: chi dung candle, zone, context va structure da confirmed tai thoi diem signal candle close.
- Moi phase phai co `Done criteria` truoc khi chuyen phase tiep theo.

## Phase 1: Freeze Zone Reaction V2 Thanh Reject-Only

### Muc tieu

Lam cho `zone_reaction_v2` bot nhieu hon bang cach chi giu reaction co dau hieu kha quan nhat hien tai: `reject`.

### Pham vi

- `zone_reaction_v2` chi duoc tao trade tu `reject`.
- Tat trade tu cac reaction:
  - `fakeout`
  - `waiting_bos`
  - `retest_reject`
  - `clean_breakout`
- Cac reaction bi tat van co the duoc detect/ghi metadata de debug hoac research, nhung khong duoc tao trade trong backtest/realtime.
- Khong them rule toi uu moi trong phase nay.

### Verify

Chay backtest rieng cho `zone_reaction_v2`:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 60000 \
  --engine incremental \
  --playbook zone_reaction_v2 \
  --persist \
  --clear-backtest-trades \
  --html-output var/reports/zone_reaction_v2_reject_only.html
```

Can so sanh:

- So trade truoc/sau.
- Win rate.
- Total R.
- Profit factor.
- Ket qua theo `support`, `resistance`, `fvg`.
- Bang `By reaction state` phai chi con trade tu `reject`.

### Done criteria

- Backtest moi khong con trade tu `fakeout`, `waiting_bos`, `retest_reject`, `clean_breakout`.
- UI van doc va ve trade history dung.
- Co report HTML cho ban reject-only.

## Phase 2: Optimize Reject Reaction

### Muc tieu

Tim xem reject reaction nao that su co edge, thay vi ap rule reject qua rong.

### Research dimensions

Thong ke reject theo zone type:

- `support`
- `resistance`
- `fvg`

Thong ke reject theo market context:

- `ranging`
- `trending`
- `neutral`
- `bullish`
- `bearish`
- overlay: `contraction`, `expansion`, `high_volatility`, `low_volatility`

Thong ke reject theo dac diem zone:

- `zone_width_atr`
- `touch_count`
- `weight`
- `confidence`
- age cua zone

Thong ke reject theo trigger:

- no trigger
- engulfing
- marubozu
- displacement
- pinbar

### Huong toi uu du kien

Sau khi co report, moi quyet dinh:

- Chi giu mot so zone type neu zone type khac qua yeu.
- Tang/giam nguong reject body.
- Loc pinbar neu pinbar tao nhieu trade thua.
- Loc zone qua hep/qua rong.
- Loc zone co touch count khong phu hop.

Khong hardcode rule moi truoc khi co report.

### Verify

Chay research/report cho reject-only:

```bash
python -m semi_bot_trading.cli research-report \
  --playbook zone_reaction_v2 \
  --html-output var/reports/reject_research.html
```

Neu can backtest lai sau khi thay doi config/rule:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 60000 \
  --engine incremental \
  --playbook zone_reaction_v2 \
  --html-output var/reports/zone_reaction_v2_reject_optimized.html
```

### Done criteria

- Co report chi ra nhom reject nao tot/xau.
- Co shortlist rule dang thu.
- Co quyet dinh nen giu `support`, `resistance`, `fvg` hay chi giu mot vai loai.

## Phase 3: Human Trade Mode Cho Zone

### Muc tieu

Cho Human quyet dinh moi zone duoc phep dung cho kieu trade nao.

### Data model

Them vao `metadata_json` cua zone:

```ts
trade_modes: ["limit", "reject", "breakout"]
```

Default theo zone type:

- `support`: `["reject"]`
- `resistance`: `["reject"]`
- `fvg`: `["limit", "reject"]`
- `consolidation`: `["breakout"]`
- `order_block`: `[]`

### UI

Trong selected zone panel, them control chon:

- Limit
- Reject
- Breakout

Yeu cau UI:

- Save vao DB qua existing zone update/override flow.
- Refresh page khong mat setting.
- Zone nao khong co metadata thi dung default theo type.

### Strategy engine

- Strategy chi duoc dung zone neu zone co trade mode phu hop.
- `zone_reaction_v2` chi doc zone co `reject`.
- FVG limit research chi doc zone co `limit`.
- Breakout strategy chi doc zone co `breakout`.

### Done criteria

- Human chinh duoc trade mode cua zone.
- Metadata duoc luu trong DB.
- Backtest/realtime doc dung mode.
- UI khong lam chart autoscale/jump khi save.

## Phase 4: FVG Limit Order Research

### Muc tieu

Kiem tra y tuong gia phan ung tot tai FVG bang thong ke rieng. Phase nay la research, chua bat production strategy.

### Entry models

Research 3 kieu limit entry:

- `fvg_ce_50`: limit tai Consequent Encroachment 50%.
- `fvg_proximal`: limit tai mep gan nhat cua FVG.
- `fvg_deep_fill`: limit khi gia fill sau 80%.

### Look-ahead guard

- FVG chi active sau khi nen thu 3 dong.
- Limit order chi duoc fill tu nen tiep theo.
- Khong dung ket qua tuong lai de chon FVG.

### Risk default

- SL ngoai FVG + `0.2 ATR`.
- `min_stop_distance = max(4.0, 1.2 * ATR_M15)`.
- `max_stop_distance = 35`.
- TP mac dinh `2R`.

### Verify

```bash
python -m semi_bot_trading.cli research-report \
  --playbook fvg_limit_order \
  --html-output var/reports/fvg_limit_order.html
```

### Done criteria

- Co report rieng cho FVG limit.
- Co thong ke theo 3 entry model.
- Co ket luan FVG limit co dang bien thanh strategy that hay khong.

## Phase 5: Breakout Strategy Cho Trending Market

### Muc tieu

Xu ly thi truong trending/expansion, noi reject-zone thuong kem hieu qua vi gia di chuyen nhanh va khong quay lai react dep.

### Playbook moi

`breakout_retest_v2`

Playbook nay khong nam trong `zone_reaction_v2`.

### State machine

```text
IDLE
  -> RANGE_DETECTED
  -> BREAKOUT_CONFIRMED
  -> WAITING_RETEST
  -> RETEST_CONFIRMED
  -> PREPARE_ENTRY
```

### Rule ban dau

- Khong chase breakout candle.
- Chi trade sau retest.
- Uu tien long truoc neu research cu van cho thay long tot hon short.
- Dung consolidation/range zone lam vung breakout.
- Short chi bat sau khi co research rieng chung minh co edge.

### Verify

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 60000 \
  --engine incremental \
  --playbook breakout_retest_v2 \
  --html-output var/reports/breakout_retest_v2.html
```

### Done criteria

- Co backtest rieng cho `breakout_retest_v2`.
- Co report theo long/short.
- Co the bat/tat playbook tren UI.
- Khong anh huong `zone_reaction_v2`.

## Phase 6: Swing Special High-Risk Limit Research

### Muc tieu

Kiem tra y tuong limit order high-risk quanh swing dac biet. Phase nay chi la research.

### Dinh nghia ban dau

Mot setup `swing_special` can co:

- Swing high/low ro rang.
- Sau swing co displacement manh.
- Co FVG hoac imbalance gan swing origin.
- Gia quay lai vung nay lan dau.
- Entry limit tai FVG CE hoac swing-origin zone.

### Metadata

```ts
high_risk = true
research_only = true
```

### Done criteria

- Co report rieng.
- Khong anh huong production strategy.
- Co ket luan nhom nay co dang phat trien tiep hay khong.

## Implementation Order

Lam theo thu tu:

1. Tao roadmap phase doc nay.
2. Phase 1: reject-only.
3. Phase 2: reject research report.
4. Phase 3: human trade mode.
5. Phase 4: FVG limit research.
6. Phase 5: breakout strategy.
7. Phase 6: swing special research.

Khong lam Phase 4-6 truoc khi Phase 1-2 ro rang, vi strategy base hien tai van con nhieu noise.

## Assumptions

- File nay chi la roadmap, khong doi behavior cua he thong.
- Strategy cu chua xoa, chi tach va disable dan theo tung phase.
- OB tam thoi khong dung trong strategy moi.
- Consolidation chi quay lai trong breakout strategy, khong dung trong zone reaction.
- Moi phase can co report/backtest rieng truoc khi qua phase tiep theo.
