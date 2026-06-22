# Semi Bot Trading

Hệ thống trade bán tự động kết hợp Human + Python Bot Executor, tập trung MVP vào Forex XAUUSD trên Exness/MT5.

Mục tiêu chính:

- Bot phân tích chart theo multi-timeframe, trước mắt tập trung H1 + M15 cho XAUUSD.
- Bot nhận diện bias, regime, support/resistance, order block, FVG, liquidity sweep, consolidation, HH/HL/LH/LL và các vùng giá quan trọng.
- UI realtime vẽ các vùng bot phát hiện lên chart.
- Human có thể overwrite nhận định/vùng giá của bot, chỉnh biên vùng, trọng số, độ tin cậy và thời gian hết hạn.
- Telegram gửi cảnh báo khi xuất hiện vùng giá hoặc điều kiện trade đáng chú ý.
- Giai đoạn Macbook MVP dùng mock/historical data và replay/backtest trước, chưa connect account thật.
- Live phase sau này dùng Python `MetaTrader5` connect MT5 Exness; executor chỉ thực thi khi đủ điều kiện risk, context và quyền xác nhận trên UI.

## Bộ tài liệu

- [00 - Tổng quan sản phẩm](docs/00-tong-quan-san-pham.md)
- [01 - Kiến trúc hệ thống](docs/01-kien-truc-he-thong.md)
- [02 - Mô hình dữ liệu và Human Override](docs/02-mo-hinh-du-lieu-va-override.md)
- [03 - Market Intelligence Engine](docs/03-market-intelligence-engine.md)
- [04 - Chart UI và Human Workflow](docs/04-chart-ui-human-workflow.md)
- [05 - Telegram Alerting](docs/05-alerting-telegram.md)
- [06 - Strategy Playbooks H1 + M15](docs/06-strategy-playbooks-h1-m15.md)
- [07 - Risk, Execution và Operations](docs/07-risk-execution-operations.md)
- [08 - Development Phases](docs/08-development-phases.md)
- [09 - Open Questions và Decision Log](docs/09-open-questions-decision-log.md)

## Ghi chú

File hướng dẫn `RTK.md` được reference trong `AGENTS.md` nhưng hiện chưa có trong repo hoặc trong `/Users/thang.nd/Documents`. Các tài liệu hiện tại được viết theo giả định sản phẩm và có thể cập nhật sau khi `RTK.md` được bổ sung.

## Development Quickstart

Import dữ liệu XAUUSD H1/M15 vào SQLite local:

```bash
python3 -m semi_bot_trading.cli import-data --data-dir data
```

Các tham số linh động nằm ở [config/trading.toml](config/trading.toml), gồm database path, data dir và swing window theo timeframe.

Xem summary và gap check:

```bash
python3 -m semi_bot_trading.cli db-summary
```

Replay thử vài candle:

```bash
python3 -m semi_bot_trading.cli replay --symbol XAUUSD --timeframe M15 --limit 10
```

Detect swing structure:

```bash
python3 -m semi_bot_trading.cli detect-structure --timeframe H1
python3 -m semi_bot_trading.cli detect-structure --timeframe M15
python3 -m semi_bot_trading.cli detect-breaks --timeframe H1
python3 -m semi_bot_trading.cli detect-breaks --timeframe M15
python3 -m semi_bot_trading.cli structure-summary --symbol XAUUSD --timeframe H1
```

Detect H1 bias:

```bash
python3 -m semi_bot_trading.cli detect-bias
python3 -m semi_bot_trading.cli context-summary --context-type bias
```

Detect H1 regime:

```bash
python3 -m semi_bot_trading.cli detect-regime
python3 -m semi_bot_trading.cli context-summary --context-type regime
```

Detect support/resistance zones:

```bash
python3 -m semi_bot_trading.cli detect-zones --timeframe H1
python3 -m semi_bot_trading.cli apply-zone-lifecycle --timeframe H1
python3 -m semi_bot_trading.cli zone-summary --timeframe H1 --limit 10
```

Detect H1 SMC zones và M15 price action:

```bash
python3 -m semi_bot_trading.cli detect-smc-zones --timeframe H1
python3 -m semi_bot_trading.cli detect-price-action --timeframe M15
```

Export chart-ready JSON:

```bash
python3 -m semi_bot_trading.cli export-chart-json --timeframe M15 --limit 300 --output var/chart_xauusd_m15.json
```

Chạy local chart UI:

```bash
python3 -m semi_bot_trading.cli serve-chart --port 8765
```

Mở [http://127.0.0.1:8765](http://127.0.0.1:8765). UI hiện đọc trực tiếp SQLite qua `/api/chart`, render nến, structure marker, support/resistance zones, H1 bias/regime và chuẩn bị sẵn trade layer.

Chạy stack FE mới theo hướng TradingView-style:

```bash
python3 -m pip install -e .
python3 -m semi_bot_trading.cli serve-api --port 8000
```

Ở terminal khác:

```bash
cd frontend
npm install
npm run dev -- --port 5173
```

Mở [http://127.0.0.1:5173](http://127.0.0.1:5173). Frontend React/Vite dùng TradingView Lightweight Charts, TanStack Query, Zustand và Tailwind. API FastAPI phục vụ `/api/chart` và `/api/health`.

Override nhanh window từ CLI nếu cần thử nghiệm:

```bash
python3 -m semi_bot_trading.cli detect-structure --timeframe M15 --window 4
```

Chạy test:

```bash
python3 -m unittest discover -s tests
cd frontend && npm run build
```
