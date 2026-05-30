# 00 - Tổng quan sản phẩm

## Tầm nhìn

Đây là một hệ thống trading bán tự động, nơi bot làm phần quan sát, chuẩn hóa dữ liệu, phát hiện cấu trúc thị trường và cảnh báo; còn human giữ vai trò đánh giá context, chỉnh sửa nhận định quan trọng và phê duyệt hành động rủi ro cao.

Bot không được xem là nguồn sự thật tuyệt đối. Mọi nhận định của bot phải có trạng thái, confidence, nguồn gốc và có thể bị human overwrite trong một thời gian cụ thể.

## Vấn đề cần giải quyết

Trading theo price action và SMC/ICT-style context có nhiều phần khó tự động hóa hoàn toàn:

- Bot có thể phát hiện pattern, nhưng dễ hiểu sai context market.
- Một vùng support/resistance hoặc order block có thể đúng về kỹ thuật nhưng quá rộng, quá cũ hoặc ít giá trị ở thời điểm hiện tại.
- Bias và regime có thể thay đổi nhanh, hoặc human có góc nhìn tốt hơn do tin tức, session, liquidity, correlation.
- Hệ thống cần lưu lại mọi quyết định để rút kinh nghiệm, backtest và cải thiện detector.

## Nguyên tắc sản phẩm

- Human-in-the-loop là mặc định, không phải tính năng phụ.
- Bot tạo hypothesis, human có quyền xác nhận, chỉnh sửa hoặc bác bỏ.
- Mọi entity phân tích đều có `source`, `confidence`, `weight`, `status`, `timeframe`, `valid_until`.
- Human override có expiry rõ ràng; hết hạn thì hệ thống quay về bot value hoặc value mới nhất theo rule.
- Executor phải tách biệt với analyzer để tránh lỗi phân tích dẫn tới đặt lệnh ngoài ý muốn.
- Alert phải actionable: nói rõ vì sao cảnh báo xuất hiện, timeframe nào, vùng nào, confidence bao nhiêu, human có override hay không.

## Persona người dùng

Primary user là trader discretionary có hiểu biết về market structure, SMC/ICT concepts và muốn bot hỗ trợ quan sát realtime.

Nhu cầu chính:

- Nhìn chart realtime có annotation đáng tin cậy.
- Chỉnh được vùng giá trực tiếp trên chart.
- Override được bias/regime có expiry.
- Nhận cảnh báo Telegram khi giá tiếp cận vùng quan trọng hoặc setup hình thành.
- Theo dõi performance của từng loại setup để cải thiện chiến lược.

## Quyết định MVP hiện tại

- Market: Forex.
- Broker/execution target sau MVP: Exness qua MT5.
- Symbol đầu tiên: XAUUSD.
- Multi-symbol được thiết kế mở rộng, nhưng MVP chỉ tập trung XAUUSD.
- Development machine: Macbook, nên MVP dùng mock/historical candle data thay vì connect MT5 thật.
- Data ban đầu: file historical XAUUSD H1 và M15 do user bổ sung vào repo.
- Timeframe chính: H1 xác định bias/regime/context, M15 tìm setup/confirmation.
- UI: web app local, dark mode mặc định, một chart XAUUSD trước.
- Execution MVP: backtest/replay, chưa connect account thật.
- Notification: Telegram private message.

## Scope ban đầu

MVP nên tập trung vào signal + chart + override + replay/backtest, chưa ưu tiên full auto execution.

Trong scope:

- Historical/mock candles từ file XAUUSD H1/M15, sau đó mới nối realtime MT5.
- Multi-timeframe H1 + M15.
- Detector cho swing structure, support/resistance, FVG, OB, liquidity sweep, consolidation, regime, bias.
- Chart UI có annotation realtime.
- Human chỉnh vùng và overwrite bias/regime/zone weight.
- Telegram alert.
- Replay/backtest để kiểm tra detector và strategy.

Ngoài scope MVP:

- Full auto trading không cần confirm.
- Portfolio đa tài sản phức tạp.
- Machine learning optimization.
- News NLP và macro event engine chuyên sâu; MVP chỉ có `news/risk-off` như trạng thái human/system có thể set.
- Copy trading hoặc social trading.
- Live execution qua MT5.
- Partial take profit, trailing stop, breakeven automation.

## Thành công được đo bằng gì

- Bot vẽ vùng và structure đủ nhanh để dùng realtime.
- Human có thể chỉnh một vùng trên chart trong dưới 5 giây.
- Alert Telegram giảm nhiễu, không spam cùng một vùng liên tục.
- Mọi override có audit trail rõ ràng.
- Strategy playbook có thể được replay/backtest bằng dữ liệu lịch sử XAUUSD.
- Hệ thống có safe mode: lỗi analyzer hoặc UI không được tự đặt lệnh.

## Decisions hiện tại

- Timeframe chính: H1 để xác định bias/regime/context, M15 để tìm setup/entry trigger.
- Bot ban đầu chạy bằng Python.
- UI là web app local dark mode.
- Telegram là kênh alert đầu tiên, gửi private message.
- Execution ban đầu là replay/backtest; live phase sau mới dùng Exness/MT5.
- Bias chính follow H1, không dùng H4 trong MVP.
- M15 bearish trong H1 bullish chỉ là pullback, chưa đổi bias nếu H1 chưa CHOCH rõ.
- Human có thể set thêm bias thứ hai để cho phép bot xét cả breakout hoặc mean reversion trong context đặc biệt.
