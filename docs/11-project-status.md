# Project Status

Last updated: 2026-06-01

File này ghi lại trạng thái thực tế của project sau các vòng implement gần nhất. Roadmap chi tiết vẫn nằm ở `docs/08-development-phases.md`; file này dùng để nhìn nhanh: đã xong gì, còn thiếu gì, và bước tiếp theo nên làm gì.

## 1. Overall Status

MVP hiện tại đã có nền tảng chạy được cho:

- Load historical XAUUSD.
- Lưu candle vào SQLite.
- API chart payload.
- Web chart dark mode.
- Realtime dashboard route `/`.
- Replay route `/replay-chart`.
- Swing, zigzag, SR, bias, regime cơ bản.
- FVG, Order Block, Liquidity Sweep, Consolidation detectors MVP.
- M15 Price Action Detector MVP.
- Human chỉnh zone và override bias/regime.
- Replay recompute detector theo từng candle để tránh look-ahead bias.

Các phần chưa làm lớn nhất:

- Telegram alert.
- Strategy engine/playbook/backtest trade.
- Risk engine và execution guardrails.
- MT5/Exness live adapter.

## 2. Done

### 2.1. Foundation

Done:

- Python package `semi_bot_trading`.
- FastAPI backend.
- SQLite database.
- CLI commands.
- Config centralization trong `config/trading.toml`.
- Test suite bằng `unittest`.
- Frontend React + TypeScript + Vite.
- Dark mode chart UI.

Notes:

- Project hiện chạy local trên Macbook.
- Data source hiện là historical/mock data trong database.
- Live MT5 chưa làm.

### 2.2. Market Data

Done:

- Import/store candles.
- Hỗ trợ XAUUSD.
- Hỗ trợ H1 và M15.
- API trả candles theo symbol/timeframe/limit.
- Replay timeline endpoint.

Partial:

- Chưa có data freshness monitor.
- Chưa có MT5 adapter.
- Chưa có realtime stream thật.

### 2.3. Market Structure

Done:

- Swing detector.
- Swing lookback/window config.
- HH/HL/LH/LL classification.
- BOS/CHOCH detector.
- Market structure dùng H1 cho bias/context.
- UI vẽ Swing High/Swing Low bằng mũi tên.
- UI vẽ ZigZag nối các swing.

Current config:

```toml
[structure.swing.timeframes]
H1 = { window = 4 }
M15 = { window = 4 }
```

### 2.4. Bias

Done:

- Bot detect H1 bias.
- H1 là timeframe chính cho bias trong MVP.
- H1 bullish/bearish/neutral dựa trên market structure.
- BOS/CHOCH dùng để củng cố/cảnh báo.
- UI hiển thị bias.
- Human override bias.
- Expiry selector cho override bias.

Partial:

- Expiry alert trước khi hết hạn chưa làm.
- Recompute/return-to-bot flow sau expiry mới ở mức backend logic cơ bản, chưa có UX/alert đầy đủ.
- Secondary bias do human set đã có mô hình `secondary_value`, nhưng strategy chưa dùng vì strategy engine chưa làm.

### 2.5. Regime

Done:

- Bot detect regime H1.
- Primary regime: `trending` / `ranging`.
- Overlay: `expansion`, `contraction`, `high_volatility`, `low_volatility`.
- Human override regime.
- Expiry selector cho regime override.

Partial:

- `news` và `risk_off` chủ yếu để human set; chưa có calendar/news integration.
- Regime chưa được dùng trong strategy engine vì strategy engine chưa làm.

### 2.6. Support / Resistance

Done:

- SR detector V2.
- Gom Swing High thành resistance.
- Gom Swing Low thành support.
- ATR-based zone width.
- Width được chốt theo ATR tại thời điểm zone detect, không dùng ATR tương lai.
- Touch classification:
  - `wick_touch`
  - `body_touch`
  - `close_inside`
  - `mixed_touch`
- Reaction scoring:
  - bounce theo ATR
  - displacement after touch
  - momentum follow-through
  - wick absorption
  - clean rejection
- Weight components:
  - base score
  - touch score
  - recency score
  - reaction score
  - age penalty
  - overtest penalty
  - mitigation penalty
  - invalidation penalty
- Debug metadata lưu trong zone.
- Regression test đảm bảo zone không tự giãn khi ATR tương lai tăng.
- Tài liệu công thức: `docs/10-support-resistance-formula.md`.

Partial:

- Confluence score chưa làm.
- Flip zone logic chưa làm.
- UI chưa hiển thị breakdown weight components, mới lưu metadata.

### 2.6.1. SMC Zone Detectors

Done:

- FVG detector `fvg_v1`:
  - 3-candle classic.
  - Nến giữa phải là impulse body tương đối mạnh.
  - Lưu fill ratio, consequent encroachment, trạng thái open/partial/filled.
- Order Block detector `order_block_v1`:
  - Lấy last opposite candle body trước displacement.
  - Lưu wick extension để tham khảo.
  - Giảm weight khi mitigated, invalidated khi close xuyên body zone.
- Liquidity Sweep detector `liquidity_v1`:
  - Sweep swing high: high phá level nhưng close reclaim xuống dưới.
  - Sweep swing low: low phá level nhưng close reclaim lên trên.
  - Lưu swept level, sweep type, sweep time.
- Consolidation detector `consolidation_v1`:
  - Sliding window theo range width/ATR.
  - Yêu cầu range efficiency thấp và có touch ở cả high/low.
  - Breakout khỏi range sẽ kết thúc zone.
- CLI mới: `detect-smc-zones`.
- Realtime dashboard đọc các zone này từ database.
- Replay chart recompute các detector này từ candles đã xuất hiện tới `replay_at`, không dùng DB precomputed zones.

Partial:

- OB dùng displacement phá swing structure gần nhất, nhưng chưa map trực tiếp tới stored BOS/CHOCH event.
- Liquidity sweep chưa group equal highs/equal lows thành pool riêng trước khi sweep.
- Consolidation chưa có UI riêng để đánh dấu range high/range low/touch count.
- Chưa có confluence score chung giữa SR + OB + FVG + liquidity.

### 2.6.2. M15 Price Action Detector

Done:

- Detector mới `price_action_v1`.
- Timeframe mặc định M15.
- Lưu event vào `structure_points`.
- Pinbar bullish/bearish.
- Engulfing bullish/bearish.
- Marubozu bullish/bearish.
- Morning star / evening star.
- Displacement candle bullish/bearish.
- Displacement dùng ATR trước nến hiện tại để tránh look-ahead bias.
- Config trong `config/trading.toml`.
- CLI mới: `detect-price-action`.
- Unit tests cho từng nhóm pattern.
- Tài liệu công thức: `docs/13-price-action-detectors-formula.md`.

Partial:

- Chưa vẽ marker riêng cho price action trên UI để tránh chart quá rối.
- Chưa filter theo H1 bias/zone location trong detector; phần này thuộc Strategy Engine.
- Chưa dùng price action event để tạo trade idea vì Strategy Engine chưa làm.

### 2.7. Chart UI

Done:

- Web app local dark mode.
- Default timeframe H1.
- Dashboard route `/`.
- Replay route `/replay-chart`.
- Candle chart.
- Zones overlay.
- Structure overlay.
- Swing arrows.
- ZigZag line.
- Selected inspector.
- Click vùng rỗng để unselect.
- Drag/resize zone trực tiếp trên chart.
- Save zone override.
- Chart không bị flicker mạnh khi replay fetch candle mới.
- Replay viewport không auto zoom ngang/dọc khó chịu.
- Giữ manual vertical scale khi candle mới xuất hiện.
- Giá hiện tại và daily percent hiển thị ở bias card.

Partial:

- UI còn cần polish thêm nếu muốn giống TradingView hơn.
- Inspector chưa hiển thị đầy đủ debug metadata như reaction score breakdown.
- Chưa có panel filter/hide theo detector/entity type nâng cao.

### 2.8. Human Override

Done:

- Human chỉnh SR zone geometry:
  - price low/high
  - visual start/end
  - weight
  - confidence
  - status active/disabled
  - no expiry
  - reason
- Human override bias.
- Human override regime.
- Expiry options:
  - 1h, 2h, 3h, 4h, 6h, 10h, 15h, 20h
  - 1day đến 6day
  - 1week
  - no expiry
- Override audit được lưu vào database.

Partial:

- Chưa có audit history UI riêng.
- Chưa có expiring-soon alert.
- Chưa có conflict UI khi bot invalidates một vùng human đang override.

### 2.9. Replay Chart

Done:

- Route riêng `/replay-chart`.
- Replay controls:
  - play/pause
  - next
  - previous
  - seconds per candle
  - current index/time
- Replay API dùng `replay_start` + `replay_at`.
- Replay recompute detectors từ candles đã xuất hiện tới thời điểm replay.
- Không dùng DB precomputed zones/structure trong replay payload.
- Giảm look-ahead bias cho Swing/SR/FVG/OB/Liquidity/Consolidation/Bias/Regime.
- Replay dùng H1/M15 theo selected timeframe.

Partial:

- Chưa có replay session persistence.
- Chưa có jump-to-date.
- Chưa có speed presets.
- Chưa có backtest trade lifecycle trong replay.

## 3. Not Started / Missing

### 3.1. Detector Refinement

Missing:

- Confluence score chung giữa SR, OB, FVG, liquidity, consolidation và price action.
- Equal highs/lows liquidity pool trước khi sweep.
- UI debug metadata đầy đủ cho từng detector.
- Price action marker/layer riêng nếu cần debug entry trigger trực quan.

### 3.2. Alerts

Not started:

- Telegram private bot.
- Alert event table/queue.
- Alert dedupe.
- Alert templates.
- Chart snapshot.

### 3.3. Strategy Engine / Backtest Trades

Not started:

- Trade idea creation.
- Trend Pullback playbook.
- Sweep Reversal playbook.
- Breakout Retest playbook.
- Range Reversal playbook.
- Entry/SL/TP rules.
- RR check.
- Risk checks.
- PnL report.
- Trade drawing from generated backtest trades.

### 3.4. Execution

Not started:

- MT5/Exness adapter.
- Risk engine.
- Human confirm before live order.
- Market/limit order execution.
- 5-minute timeout rule.
- Kill switch.
- Position/order sync.

## 4. Current Milestone View

Milestone A: "Nhìn được chart có bot annotation"

Status: mostly done.

Done:

- Chart.
- Candles.
- Swing/ZigZag.
- SR zones.
- Bias/regime cards.
- Replay detector visualization.

Still missing:

- Price action marker/layer riêng nếu cần debug entry trigger trực quan.

Milestone B: "Human sửa được bot"

Status: largely done for SR/Bias/Regime.

Done:

- Edit zone directly on chart.
- Override bias/regime.
- Expiry/no-expiry.
- Save to DB.

Still missing:

- Audit history UI.
- Expiry alert.
- Conflict handling UI.

Milestone C: "Không cần nhìn chart liên tục"

Status: not started.

Missing:

- Telegram alerts.
- Alert queue/dedupe.
- Entity/state change notifications.

Milestone D: "Biết setup nào đáng trade"

Status: not started.

Missing:

- Strategy engine.
- Backtest trade generation.
- Reports.

Milestone E: "Execution có kiểm soát"

Status: not started.

Missing:

- MT5 adapter.
- Risk engine.
- UI confirmation.
- Live order flow.

## 5. Recommended Next Plan

### Next Step 1: Finish Detector Set Before Strategy

Status:

- Detector set MVP đã đủ để bắt đầu Strategy Observe Mode.
- Các detector vẫn cần refine, nhưng không nên chờ perfect mới viết strategy.

Reason:

- Strategy Trend Pullback cần ít nhất OB/FVG/SR + H1 Bias/Regime.
- Sweep Reversal cần Liquidity Sweep.
- Range Reversal cần Consolidation/Range.
- Entry confirmation cần M15 price action.

### Next Step 2: Add Detector Debug UI

Sau khi có thêm detectors, cần UI debug:

- Toggle từng detector.
- Inspector hiển thị metadata quan trọng.
- Weight component breakdown.
- Reason text: vì sao vùng này mạnh/yếu.

### Next Step 3: Strategy Engine Observe Mode

Sau khi detector đủ:

- Implement Trend Pullback đầu tiên.
- Chỉ tạo `trade_idea`, chưa vào lệnh.
- Hiển thị setup candidate trên chart.
- Lưu context snapshot.

### Next Step 4: Replay/Backtest Trade Mode

Sau observe mode:

- Replay tạo trade theo rule.
- Simulate entry/SL/TP.
- Draw trade history trên chart.
- Report winrate/RR/PnL theo playbook.

### Next Step 5: Telegram Alerts

Có thể làm song song sau khi Strategy Observe Mode có event rõ:

- New SR/OB/FVG high weight.
- Bias/regime changed.
- Setup candidate.
- Price touched important zone.

## 6. Recommendation For Immediate Next Coding Task

Nên làm tiếp:

```text
Strategy Engine Observe Mode cho Trend Pullback
```

Lý do:

- Detector nền đã đủ cho playbook đầu tiên.
- Trend Pullback là ưu tiên cao nhất trong strategy plan.
- Price action M15 vừa được thêm nên có thể dùng làm entry trigger.
- Observe Mode chỉ tạo `trade_idea`, chưa vào lệnh, nên phù hợp để debug bằng replay.

Scope đề xuất cho task tiếp theo:

- Tạo bảng/model `trade_ideas` nếu schema hiện tại chưa đủ field cần dùng.
- Implement playbook `trend_pullback`.
- Input:
  - H1 effective bias/regime.
  - H1 zones SR/OB/FVG còn active.
  - M15 price action event cùng hướng.
  - RR tối thiểu 1:2.
- Output:
  - candidate trade idea.
  - suggested entry, SL, TP.
  - confluence snapshot.
  - reason/debug metadata.
- Unit tests.
