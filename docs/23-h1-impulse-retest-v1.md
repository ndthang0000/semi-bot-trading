# 23 - H1 Impulse Retest V1

## Phạm vi hiện tại

`h1_impulse_retest_v1` gồm calculator và UI preview cho một nến H1 đã đóng do
trader chọn trực tiếp trên chart. Preview đủ điều kiện có thể được trader chỉnh
Entry/SL/TP, duyệt và chuyển thành pending limit qua lifecycle an toàn đang dùng
cho Manual AI. Playbook chưa tự động tạo setup và chưa có backtest engine.

Mục tiêu của phase này là quan sát đầy đủ input, output và lý do bị chặn trước
khi chốt rule execution.

## H1 candidate markers

Chart payload đánh giá từng nến H1 đã đóng bằng rolling ATR tại chính thời điểm
nến đó, không dùng ATR hiện tại cho lịch sử. Nến có Body tối thiểu `0.8 ATR`
được đưa vào layer `h1_impulse_markers` theo hai cấp:

- `candidate`: Body đạt chuẩn nhưng còn ít nhất một điều kiện playbook bị chặn;
  UI dùng ngôi sao xám và tooltip liệt kê lý do.
- `eligible`: đạt toàn bộ điều kiện calculator; UI dùng ngôi sao vàng cho cả
  LONG và SHORT.

Layer chỉ hiển thị khi playbook `h1_impulse_retest_v1` đang được bật, mặc định
hiển thị cả hai cấp và có filter `Eligible signals only`. Click marker chỉ chọn
đúng nến để trader đọc thông tin và chủ động mở preview; thao tác này không tạo
setup, không ghi database và không gửi lệnh.

Action `Add setup preview to chart` trên thẻ thông tin nến cũng chỉ xuất hiện
khi playbook đang bật và nến được Backend trả về trong marker layer, gồm cả sao
vàng `eligible` lẫn sao xám `needs review`. Nến H1 không đạt Body threshold vẫn
xem được OHLC nhưng không thể tạo preview từ UI.

## Signal candle

Hướng setup theo màu của nến H1 được chọn:

- Nến bullish tạo candidate LONG.
- Nến bearish tạo candidate SHORT.
- Doji bị chặn.

Calculator còn kiểm tra các ngưỡng chất lượng tạm thời:

- Body tối thiểu `0.8 ATR(14) H1`.
- Range từ `0.9` tới `2.5 ATR H1`.
- Body chiếm tối thiểu `60%` range.
- Close nằm ít nhất `75%` về phía hướng signal.
- Râu phía close không quá `20%` range.
- Râu ngược hướng vẫn được đo để audit nhưng không chặn setup.
- Nến phải close phá high/low của H1 liền trước theo đúng hướng.

Các ngưỡng này là tham số preview để tiếp tục hiệu chỉnh, chưa phải kết luận
strategy có edge. Source of truth nằm tại
`[strategy.playbooks.h1_impulse_retest_v1]` trong `config/trading.toml`; API trả
lại snapshot `parameters` để mỗi preview vẫn audit được đúng bộ config đã dùng.

## Stop loss cố định

SL luôn neo ngoài râu signal candle và không thay đổi theo Entry:

```text
LONG  SL = signal low  - 0.1 * ATR H1
SHORT SL = signal high + 0.1 * ATR H1
```

## Entry thích ứng

Candidate ban đầu lấy từ nến H1 liền trước:

```text
LONG  candidate = previous H1 high
SHORT candidate = previous H1 low
```

Khoảng cách Entry-SL hợp lệ tạm thời là `0.5–1.2 ATR H1`:

1. Nếu candidate nằm trong khoảng này, dùng candidate của nến trước.
2. Nếu candidate tạo stop ngắn hơn `0.5 ATR`, fallback về Fib 0.5, tức midpoint
   `(signal high + signal low) / 2` của signal candle.
3. Nếu candidate tạo stop dài hơn `1.2 ATR`, cap Entry tại đúng khoảng cách
   `1.2 ATR` tính từ SL.

Nếu Fib 0.5 fallback vẫn tạo stop dài hơn `1.2 ATR`, calculator tiếp tục cap
Entry và ghi source `fib_0.5_then_atr_1.2_cap` để audit đủ cả hai bước.

Sau khi chọn Entry, calculator kiểm tra lại khoảng stop cuối cùng. Vì Fib 0.5
không được ép nhân tạo ra xa SL, setup vẫn có thể bị chặn nếu midpoint còn gần
hơn minimum stop.

## Take profit và limit validity

Trader có thể preview và chỉnh RR trong cùng khoảng với Manual AI: `1.5–4.0`:

```text
LONG  TP = Entry + RR * (Entry - SL)
SHORT TP = Entry - RR * (SL - Entry)
```

So với close của signal H1 — giá khả dụng khi setup vừa được tạo — LONG chỉ hợp
lệ như BUY LIMIT khi Entry thấp hơn market; SHORT chỉ hợp lệ như SELL LIMIT khi Entry cao hơn market. Sai
geometry không được tự đổi thành market/stop order mà được trả về dưới dạng
blocked reason.

## Expiry, renewal và Telegram

Body/ATR vẫn tạo **TTL gợi ý** ban đầu:

- Body dưới `1.2 ATR`: 6 giờ.
- Body từ `1.2` tới dưới `1.6 ATR`: 12 giờ.
- Body từ `1.6 ATR` trở lên: 18 giờ.

TTL của pending order tách biệt với tuổi của signal. Khi trader arm/re-order,
TTL được tính lại từ thời điểm xác nhận hiện tại; UI có preset
`6/12/18/24/48h` và cho nhập custom trong khoảng `1–48h`. Một signal H1 chỉ có
thể được renew trong tối đa `48h` kể từ lúc nến đóng. Các giới hạn này nằm trong
config dưới tên `min_order_ttl_hours`, `max_order_ttl_hours` và
`max_signal_age_hours`.

Plan đã expired vẫn là terminal để giữ đúng lịch sử. `Revalidate & re-order`
không hồi sinh plan cũ mà tạo plan con mới, lưu `renewed_from_plan_id` và
`renewal_count`. Trước khi tạo, Backend duyệt M5 từ lúc signal đóng (fallback H1)
và trả cảnh báo cho trader nếu:

- giá đã chạm Entry — setup đã được thị trường consume;
- giá đã chạm SL/invalidation;
- giá đã tới TP mà chưa chạm Entry;
- signal quá `max_signal_age_hours`;
- signal cũ nhưng không có candle sau signal để audit an toàn.

Các cảnh báo renewal này không tự khóa execution. UI vẫn hiển thị rõ ràng để
trader biết setup có thể đã bị consume/invalidation/TP trong lịch sử, nhưng
quyết định cuối cùng thuộc về trader sau khi tick checklist kỷ luật. Backend vẫn
lưu snapshot `revalidations` vào payload để audit sau này.

Expiry của plan `draft/approved` có thể sửa trực tiếp. Nếu pending order đã
`armed`, thay đổi expiry tạo `replace_requested`; worker xác nhận order cũ chưa
fill, hủy ticket cũ rồi đặt lại cùng levels với broker expiry mới.

Worker lưu mốc H1 đã xử lý và chỉ đánh giá khi xuất hiện nến H1 đóng mới; lúc
khởi động, nến đang có trong database chỉ được dùng làm baseline nên không gửi
lại alert cũ. Body từ `0.8 ATR(14)` trở lên dùng chung calculator với marker
chart rồi queue Telegram theo hai cấp:

- `⭐ ELIGIBLE LONG/SHORT`: tương ứng ngôi sao vàng, không có blocked reason.
- `☆ NEEDS REVIEW LONG/SHORT`: tương ứng ngôi sao xám, message liệt kê các rule
  còn bị chặn.

Message còn có Body/ATR, Range/ATR, Body/range, Entry source, OHLC và TTL gợi ý.
Global system claim theo symbol + close time bảo đảm nhiều account worker
dùng chung database chỉ queue một message cho cùng cây H1; worker claim đầu tiên
sẽ dùng Telegram connection của account đó để gửi.

Khi H1 Impulse limit thật sự khớp, alert setup `WAIT` trước đó không được xem là
fill confirmation. Worker chỉ gửi message `[FILLED]` sau khi MT5 xác nhận bằng
open position hoặc order history. Event fill dùng lifecycle chung của mọi
playbook, mang theo account, playbook, direction, actual/planned Entry, SL, TP,
lot, Entry source, broker IDs và fill time; dedupe theo `trade_order_id` để mỗi
lệnh chỉ báo một lần.

Setup card hiển thị cả timestamp và duration của limit, ví dụ
`Hết hạn 06:00 13-08 (6h)`. Preview local đọc `expiry_hours` từ calculator;
execution plan persisted giữ lại duration từ `expires_in_minutes` trong payload.

Sau khi trader đã approve một H1 Impulse setup, worker không tự hủy plan chỉ vì
điều kiện `price_reached_target_without_fill` đã đúng. Với playbook này, trạng
thái “TP đã từng chạm trước fill” thuộc nhóm cảnh báo discretionary trong
revalidation audit. Worker vẫn giữ các guard runtime như hết TTL, news blackout,
M5 close vượt invalidation/SL và giới hạn account trước khi gửi hoặc giữ lệnh
pending trên MT5.

## Human approval và MT5

Khi chọn riêng playbook H1 Impulse Retest trên chart, UI tự bật layer
`Structure + ZigZag` và ẩn các zone không thuộc playbook để trader đọc impulse,
pullback và cấu trúc liên quan rõ hơn. Đây là default khi chọn playbook hoặc tải
lại trang, không phải layer bắt buộc; trader vẫn có thể tắt trong menu Layers để
đọc chart trống hơn trong phiên hiện tại.

Setup preview không tự gửi lệnh. Trader chọn Entry source (previous H1 edge,
Fib 0.382/0.5/0.618, min/max Stop ATR hoặc custom), có thể chỉnh Entry/SL/TP rồi bấm
`Send limit to MT5`. UI tạo một plan `h1_impulse_retest_v1`, yêu cầu checklist
tâm lý/risk và account đích trước khi approve. Worker sau đó vẫn áp dụng spread,
news blackout, exposure, position limit và dynamic sizing trước khi đặt pending
order.

H1 Impulse dùng chung giới hạn vị thế theo account tại
`MAX_OPEN_POSITIONS_PER_SYMBOL`, nhưng giới hạn này chỉ áp dụng cho position đã
khớp. Pending limit là kế hoạch chờ nên không giữ slot; trader có thể stage nhiều
limit cùng lúc. Worker vẫn kiểm tra số position đang mở ngay trước khi gửi MT5 và
ở các vòng poll sau, nên nếu đã đạt số position tối đa thì setup còn lại sẽ tiếp
tục chờ tới khi hết hạn hoặc tới khi có slot trống.

Khi pending order đã tồn tại, chỉnh levels tạo `replace_requested`; worker hủy
pending cũ rồi đặt lại levels mới. Entry source được lưu cùng payload để Setup UI
và audit trail luôn giải thích Entry đến từ đâu.

Mỗi H1 plan mới khóa Partial TP mặc định tại `+1.25R`: đóng `50%` volume, sau đó
dời SL của phần còn lại về Entry với BE buffer `0`. TP cuối của setup được giữ
nguyên. Snapshot đã khóa không bị account-level setting thay đổi giữa vòng đời
trade.

### Blocked setup review

Calculator phân loại lý do block thành hai nhóm và vẫn giữ `blocked_reason` tổng
để tương thích với chart/Telegram:

- `soft_blocked_reason`: rule đánh giá chất lượng signal như Body/ATR,
  Range/ATR, Body/range, close location, close-side wick và breakout nến H1
  trước. Trader có thể gửi dưới dạng discretionary override sau khi nhập lý do
  tối thiểu 20 ký tự và xác nhận đã đọc từng soft block.
- `hard_blocked_reason`: doji, geometry Entry/SL/TP sai hoặc stop size ngoài
  `0.5–1.2 ATR`. Những lỗi kỹ thuật này khóa execution cho tới khi levels được
  sửa hoặc setup bị loại bỏ. Revalidation sau signal close như setup đã consume,
  invalidation/TP đã chạm, signal quá tuổi hoặc thiếu lịch sử xác minh chỉ còn
  là cảnh báo discretionary và được lưu vào payload.

`Review blocked setup` mở màn hình audit để trader thấy cả hai nhóm. Mỗi lần
Entry/SL/TP thay đổi, UI tính lại geometry, RR và stop/ATR;
Backend kiểm tra lại geometry, RR, H1 ATR stop bounds, override acknowledgement
và override reason trước khi tạo draft. Worker còn kiểm tra BUY LIMIT/SELL LIMIT
so với giá broker ngay trước khi gửi MT5.

Plan lưu `original_status`, toàn bộ blocked reasons, soft/hard reasons,
`human_override` và `override_reason` trong raw payload/context snapshot. Setup
đã persist hiển thị badge `HUMAN OVERRIDE`, giúp journal phân biệt signal eligible
tự nhiên với quyết định discretionary.

## Historical outcome preview

Sau khi dựng một setup eligible, calculator duyệt các nến H1 đã đóng sau signal
tới `as_of`:

- `UNFILLED`: chưa chạm Entry.
- `OPEN`: đã fill nhưng chưa chạm SL/TP.
- `WIN`: đã fill rồi chạm TP trước trên một nến sau.
- `LOSS`: đã fill rồi chạm SL.
- `AMBIGUOUS`: OHLC H1 chạm các mức theo cách không xác định được thứ tự; ví dụ
  Entry và TP cùng nằm trong range của fill candle, hoặc SL và TP cùng bị chạm.
- `BLOCKED`: signal không đạt rule nên không được tính như một trade.

Outcome chỉ giúp kiểm tra trực quan, không thay thế backtest. Đặc biệt,
`AMBIGUOUS` cần dữ liệu M15/M5 nếu muốn phân giải thứ tự intrabar.

## API preview

`POST /api/playbooks/h1-impulse-retest/preview` nhận symbol, timestamp chính xác
của signal candle H1, RR và `as_of` tùy chọn. Backend tải signal candle, H1 liền
trước và ATR lịch sử đúng tại thời điểm signal để tránh look-ahead trong replay.

Response luôn có `preview_only: true` và bao gồm toàn bộ levels, metrics,
parameters, entry source, outcome cùng blocked reasons để UI và test có thể
audit công thức. Frontend chuyển response thành research setup local, hiển thị
trong tab `Setups` và vẽ risk/reward box trên chart.
