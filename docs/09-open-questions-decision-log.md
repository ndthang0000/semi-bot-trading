# 09 - Open Questions và Decision Log

## Cách dùng file này

File này là nơi gom câu trả lời, quyết định và các điểm còn mở. Khi bạn đổi rule hoặc bổ sung data/broker detail, cập nhật file này trước rồi sync sang các docs liên quan.

## Decision Log

| Date | Topic | Decision | Notes |
|---|---|---|---|
| 2026-05-30 | Product direction | Human-in-the-loop semi-auto trading system | Bot detects, human can override, executor guarded |
| 2026-05-30 | Market | Forex | Trade qua Exness sau MVP |
| 2026-05-30 | First symbol | XAUUSD | MVP chỉ tập trung một symbol |
| 2026-05-30 | Data source MVP | Mock/historical file data | User sẽ bổ sung XAUUSD H1 và M15 vào repo |
| 2026-05-30 | Live data/execution | MT5 via Python `MetaTrader5` | Kết nối Exness/MT5 sau MVP |
| 2026-05-30 | Primary timeframe | H1 + M15 | H1 context/bias, M15 setup/confirmation |
| 2026-05-30 | H4 filter | Not used in MVP | Dùng thẳng H1 bias trước |
| 2026-05-30 | M5 entry | Not used in MVP | Có thể thêm nếu M15 chưa hiệu quả |
| 2026-05-30 | UI | Local web app, dark mode | Một chart XAUUSD trước |
| 2026-05-30 | Replay mode | Required | Backtest trước live |
| 2026-05-30 | Execution MVP | Backtest/replay only | Không connect account thật trên Macbook MVP |
| 2026-05-30 | Telegram | Private message | Không dùng group, không cần inline buttons |
| 2026-05-30 | Risk | 1% per trade, 5% daily loss, max 10 trades/day | Min RR 1:2 |
| 2026-05-30 | Live confirmation | Confirm on UI | Sau 5 phút chưa confirm: limit nếu giá tệ hơn, market nếu giá tốt hơn |
| 2026-05-30 | Candle persistence | Store candles in database | Imported file is source, database is working store |
| 2026-05-30 | Zone persistence | Store all zones in database | Keep active and historical zones with lifecycle/status |
| 2026-05-30 | Trade persistence | Store all trade ideas/orders/fills | Chart UI must draw old trades |
| 2026-05-30 | Zone visual validity | Zone length runs from creation to invalidation/end | Active zones extend to current candle; invalidated zones stop at `end_time` |

## Answered Questions

### 1. Market và instrument

- Market: Forex.
- Broker/sàn: Exness.
- Symbol đầu tiên: XAUUSD.
- Có thể thiết kế mở rộng nhiều symbol, nhưng MVP chỉ bật XAUUSD.

### 2. Data provider

- MVP trên Macbook dùng mock/historical data.
- User sẽ bổ sung file XAUUSD H1 và M15 vào repo.
- Sau MVP, Python bot dùng thư viện `MetaTrader5` connect MT5 để lấy data từ Exness.
- Timeframe thấp nhất MVP: M15.
- Volume: optional, vì Exness/MT5 có thể chỉ có tick volume.
- Không cần order book, liquidation, funding.

### 3. Broker / exchange

- Live phase dùng Exness trên MT5.
- Python executor dùng thư viện `MetaTrader5`.
- MVP chưa connect account thật.

### 4. Timeframe

- H1 + M15 là timeframe MVP.
- H1 là HTF chính trong MVP, chưa dùng H4 filter.
- Không cần M5 trong MVP.
- Nếu backtest cho thấy M15 entry quá muộn, có thể thêm M5 sau.

### 5. Bias

Bias là hướng thiên vị hoặc kỳ vọng chính về hướng giá trong một khoảng thời gian, quyết định ưu tiên tìm lệnh Long hay Short.

Rule:

- Ưu tiên chính: HH/HL/LH/LL theo Market Structure.
- BOS dùng để xác nhận và củng cố bias.
- CHOCH dùng để cảnh báo/đổi bias khi H1 có CHOCH rõ ràng.
- Thứ tự: HH/HL hoặc LH/LL -> BOS -> CHOCH.
- Khi H1 bullish nhưng M15 bearish pullback, vẫn giữ Bullish Bias.
- Khi H1 bearish nhưng M15 bullish pullback, vẫn giữ Bearish Bias.
- Neutral Bias khi H1 sideway/range rõ, không tạo HH/HL hoặc LH/LL mới, có Equal Highs/Equal Lows liên tục và không có BOS mạnh.
- Override bias hết hạn phải alert và recompute H1 Market Structure/Bias trước khi trả bot quyền kiểm soát.
- Hệ thống hỗ trợ 2 bias cùng lúc: primary bias do bot/human effective context, secondary bias chỉ do human set để cho phép breakout hoặc mean reversion.

### 6. Regime

Regime là trạng thái vận động hiện tại của thị trường, mô tả cách giá đang di chuyển về độ mạnh, tốc độ và tính chất.

Taxonomy:

- Primary regime: Trending hoặc Ranging.
- Momentum overlay: Expansion hoặc Contraction.
- Volatility overlay: High Volatility hoặc Low Volatility.
- Special overlay: News hoặc Risk-off.

Rule:

- Trending và Expansion có thể đồng thời.
- Mỗi thời điểm chỉ có một primary regime, nhưng có thể có overlay conditions.
- High/Low Volatility là overlay condition.
- News/Risk-off là trạng thái đặc biệt, MVP có thể set thủ công bởi human trước khi có calendar/macro engine.

### 7. Order Block

Order Block là vùng giá quan trọng nơi Smart Money/Institutional có thể đã đặt lệnh lớn, thường là vùng cuối cùng trước Displacement mạnh.

Rule:

- Ưu tiên candle cuối cùng trước displacement theo ICT.
- Bullish OB: nến giảm cuối trước displacement tăng phá structure.
- Bearish OB: nến tăng cuối trước displacement giảm phá structure.
- Ưu tiên lấy body làm vùng chính.
- Wick chỉ dùng làm vùng mở rộng/tham khảo.
- Invalidated khi có nến close mạnh xuyên qua vùng OB kèm displacement ngược chiều.
- Wick chạm hoặc xuyên nhẹ không invalidate.
- Mitigated dưới 30-40%: giữ giá trị cao.
- Mitigated từ 50% trở lên: giảm weight rõ.
- Mitigated gần 100%: giảm mạnh, coi như yếu hoặc mất hiệu lực.

### 8. FVG

Fair Value Gap là vùng imbalance khi giá di chuyển mạnh, bỏ qua một vùng giá mà không giao dịch đầy đủ.

Rule:

- Dùng 3-candle classic.
- Nến 1 và nến 3 không overlap, tạo gap giữa high/low tương ứng.
- Nến giữa là impulse/displacement candle mạnh.
- Filled 80-100%: xem là filled/mitigated hoàn toàn.
- Filled 50-79%: partial fill, weight giảm rõ.
- Filled dưới 50%: vẫn giữ giá trị cao.
- Consequent Encroachment 50% dùng như confluence phụ/cảnh báo FVG yếu dần.
- FVG ngược HTF bias không alert ưu tiên, trừ khi có confluence cực mạnh như Liquidity Sweep + CHOCH.

### 9. Support / Resistance

- Support/Resistance xác định theo Swing High/Swing Low hoặc ZigZag.
- Không dùng câu hỏi SR để thay thế logic sideway.
- Consolidation/sideway là detector riêng dựa trên range high/low, số lần touch, volatility thấp/thu hẹp và thiếu BOS mạnh.

### 10. Liquidity Sweep

- Dùng logic truyền thống: sweep swing high/low hoặc range high/low, có wick phá vùng và ưu tiên close reclaim.
- Sweep M15 tại vùng H1 có weight cao hơn.
- Sweep là context/trigger candidate; entry vẫn cần confirmation M15 như displacement, engulfing, pinbar hoặc BOS/CHOCH.

### 11. Human override

- Default expiry: 4H.
- Human có thể set no-expiry.
- Hệ thống chỉ một user, không cần multi-profile/user permission trong MVP.
- Nếu bot invalidate vùng human chỉnh, bot chỉ tắt effective zone sau khi human override hết hạn hoặc human revoke.
- Không cần human lock zone.

### 12. Telegram

- Gửi private message.
- Không cần nhiều mức alert cho user.
- Alert bắt buộc khi bot detect entity mới hoặc bot/human/state thay đổi.
- Không cần inline buttons như Open Chart, Mute, Acknowledge.
- Chart snapshot có entry/SL/TP là nice-to-have.

### 13. Strategy

Priority:

1. Trend Pullback.
2. Sweep Reversal.
3. Breakout Retest.
4. Range Reversal.

Entry cần tối thiểu 3 confluence:

- H1 Bias đúng hướng.
- Giá chạm Order Block + FVG.
- Confirmation trên M15: displacement mạnh + price action candle như engulfing, pinbar, morning star, marubozu hoặc BOS.

Stop loss:

- Kết hợp zone + swing.
- Đặt dưới/trên OB hoặc Swing Low/High gần nhất.
- Thêm buffer 5-10 pips hoặc theo ATR.

Take profit:

- TP1: RR tối thiểu 1:2, chốt 50%.
- TP2: Liquidity Pool hoặc Strong S/R tiếp theo.
- Có thể scale-out trong logic/backtest, nhưng executor MVP chưa làm partial/trailing/breakeven automation.

RR:

- Tối thiểu 1:2.
- Lý tưởng 1:2.5 đến 1:3.

### 14. Risk

- Risk per trade: 1%.
- Max daily loss: 5%.
- Max trades/day: 10.
- Không cần dừng trade sau chuỗi thua trong decision hiện tại.
- Không cần tự giảm lot khi high volatility trong decision hiện tại.

### 15. Execution mode

- MVP: backtest/replay only.
- Live phase: human confirm trên UI.
- Nếu sau 5 phút chưa confirm:
  - Giá tệ hơn entry mong muốn: đặt limit.
  - Giá tốt hơn entry mong muốn: vào market.
- Order type cần hỗ trợ: market và limit.
- Chưa cần partial take profit, trailing stop, breakeven automation.

### 16. UI preference

- Web app local.
- MVP một chart XAUUSD.
- Replay mode bắt buộc.
- Dark mode mặc định.

### 17. Persistence và chart history

- Dữ liệu nến phải lưu vào database sau khi import từ file.
- Dữ liệu vùng giá phải lưu vào database, gồm cả vùng active và vùng cũ.
- Không xóa vùng cũ; dùng `status`, `start_time`, `end_time`, `valid_from`, `valid_until` để quản lý vòng đời.
- Dữ liệu trade phải lưu vào database, gồm trade idea, order, fill, close, PnL và context snapshot.
- UI phải vẽ được tất cả lệnh cũ trên chart.
- Chiều dài ngang của zone thể hiện hiệu lực visual: bắt đầu khi zone hình thành, kết thúc khi structure/invalidation xảy ra hoặc zone bị disable/expired.
- Vùng gần nhất được cộng freshness score, nhưng HTF zone cũ vẫn có thể quan trọng nếu có confluence/phản ứng giá.

## Remaining Open Questions

- File data XAUUSD H1/M15 sẽ ở định dạng nào: CSV, JSON, Parquet, hoặc export MT5?
- Timezone của file candle là gì: broker server time, UTC, hay Asia/Ho_Chi_Minh?
- XAUUSD pip/point convention muốn dùng trong UI/risk là gì?
- Session ưu tiên cho XAUUSD: London, New York, overlap hay tất cả?
- Có cần news calendar thủ công trong MVP không, hay chỉ human set `news` overlay?
- Cách tính lot size cho Exness MT5 cần theo contract spec cụ thể nào?
- Database MVP nên dùng SQLite hay DuckDB trước khi lên Postgres/TimescaleDB?

## Assumption Register

| Assumption | Risk if wrong | How to validate |
|---|---|---|
| Candle OHLCV H1/M15 đủ cho MVP | Entry có thể trễ nếu cần M5 | Replay/backtest và review chart |
| Tick volume optional | Một số confirmation thiếu lực volume | So sánh detector có/không tick volume |
| H1 bias không cần H4 filter | Có thể trade ngược macro/HTF | Review backtest và thêm H4 nếu cần |
| Dark web app + TradingView Lightweight Charts đủ | Advanced drawing/drag có thể bị giới hạn | Prototype drag/resize zone sớm |
| Telegram private message đủ | Có thể cần mobile action/ack sau | Test alert workflow thực tế |
