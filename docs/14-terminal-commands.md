# Terminal Commands

File này gom các câu lệnh hay dùng khi phát triển và test hệ thống semi-bot trading.

Chạy mọi lệnh từ root project:

```bash
cd /Users/thang.nd/Documents/semi-bot-trading
```

## 1. Cài đặt môi trường

Cài Python package local:

```bash
python -m pip install -e .
```

Cài frontend dependencies:

```bash
cd frontend
npm install
cd ..
```

Sau khi cài editable package, có thể dùng một trong hai kiểu lệnh:

```bash
python -m semi_bot_trading.cli <command>
semi-bot <command>
```

Trong docs này ưu tiên `python -m semi_bot_trading.cli` để chạy ổn ngay cả khi console script chưa được refresh.

## 2. Start backend và frontend

Start FastAPI backend:

```bash
python -m semi_bot_trading.cli serve-api --port 8000
```

Start backend với auto reload khi sửa Python:

```bash
python -m semi_bot_trading.cli serve-api --port 8000 --reload
```

Start React/Vite frontend:

```bash
cd frontend
npm run dev -- --port 5173
```

Mở UI:

```text
Realtime dashboard: http://127.0.0.1:5173/
Replay chart:       http://127.0.0.1:5173/replay-chart
Backend health:     http://127.0.0.1:8000/api/health
```

Nếu port bị chiếm:

```bash
lsof -iTCP:8000 -sTCP:LISTEN -n -P
lsof -iTCP:5173 -sTCP:LISTEN -n -P
```

Dừng process theo PID:

```bash
kill <PID>
```

## 3. Database và import data

Khởi tạo hoặc migrate SQLite schema:

```bash
python -m semi_bot_trading.cli init-db
```

Import dữ liệu từ folder `data`:

```bash
python -m semi_bot_trading.cli import-data --data-dir data
```

Xem số nến, range thời gian và gap:

```bash
python -m semi_bot_trading.cli db-summary
```

Kiểm tra nhanh số nến trong DB:

```bash
python - <<'PY'
from semi_bot_trading.config import load_config
from semi_bot_trading.db import connect

config = load_config()
with connect(config.database) as conn:
    for timeframe in ["H1", "M15"]:
        row = conn.execute(
            "select count(*) c, min(open_time) mn, max(open_time) mx from candles where symbol=? and timeframe=?",
            (config.symbol, timeframe),
        ).fetchone()
        print(timeframe, dict(row))
PY
```

## 4. Full detect pipeline

Pipeline detect thường dùng sau khi import data hoặc đổi config detector.

Detect H1 structure:

```bash
python -m semi_bot_trading.cli detect-structure --timeframe H1
python -m semi_bot_trading.cli detect-breaks --timeframe H1
```

Detect M15 structure:

```bash
python -m semi_bot_trading.cli detect-structure --timeframe M15
python -m semi_bot_trading.cli detect-breaks --timeframe M15
```

Detect H1 context:

```bash
python -m semi_bot_trading.cli detect-bias --timeframe H1
python -m semi_bot_trading.cli detect-regime --timeframe H1
```

Detect H1 support/resistance và lifecycle:

```bash
python -m semi_bot_trading.cli detect-zones --timeframe H1
python -m semi_bot_trading.cli apply-zone-lifecycle --timeframe H1
```

Detect M15 support/resistance và lifecycle:

```bash
python -m semi_bot_trading.cli detect-zones --timeframe M15
python -m semi_bot_trading.cli apply-zone-lifecycle --timeframe M15
```

Detect SMC zones:

```bash
python -m semi_bot_trading.cli detect-smc-zones --timeframe H1
python -m semi_bot_trading.cli detect-smc-zones --timeframe M15
```

Detect M15 price action:

```bash
python -m semi_bot_trading.cli detect-price-action --timeframe M15
```

Một lệnh copy nhanh toàn pipeline:

```bash
python -m semi_bot_trading.cli detect-structure --timeframe H1
python -m semi_bot_trading.cli detect-breaks --timeframe H1
python -m semi_bot_trading.cli detect-structure --timeframe M15
python -m semi_bot_trading.cli detect-breaks --timeframe M15
python -m semi_bot_trading.cli detect-bias --timeframe H1
python -m semi_bot_trading.cli detect-regime --timeframe H1
python -m semi_bot_trading.cli detect-zones --timeframe H1
python -m semi_bot_trading.cli apply-zone-lifecycle --timeframe H1
python -m semi_bot_trading.cli detect-zones --timeframe M15
python -m semi_bot_trading.cli apply-zone-lifecycle --timeframe M15
python -m semi_bot_trading.cli detect-smc-zones --timeframe H1
python -m semi_bot_trading.cli detect-smc-zones --timeframe M15
python -m semi_bot_trading.cli detect-price-action --timeframe M15
```

## 5. Summary và debug detector

Xem structure summary:

```bash
python -m semi_bot_trading.cli structure-summary --timeframe H1 --limit 20
python -m semi_bot_trading.cli structure-summary --timeframe M15 --limit 20
```

Xem bias/regime:

```bash
python -m semi_bot_trading.cli context-summary --context-type bias
python -m semi_bot_trading.cli context-summary --context-type regime
```

Xem zones:

```bash
python -m semi_bot_trading.cli zone-summary --timeframe H1 --limit 20
python -m semi_bot_trading.cli zone-summary --timeframe M15 --limit 20
```

Test swing loopback/window khác:

```bash
python -m semi_bot_trading.cli detect-structure --timeframe H1 --window 4
python -m semi_bot_trading.cli detect-structure --timeframe M15 --window 4
```

Test FVG filter khác:

```bash
python -m semi_bot_trading.cli detect-smc-zones --timeframe H1 \
  --fvg-middle-candle-atr-multiplier 2.0 \
  --fvg-gap-atr-ratio 0.25 \
  --fvg-third-candle-min-body-ratio 0.20
```

Test OB filter khác:

```bash
python -m semi_bot_trading.cli detect-smc-zones --timeframe H1 \
  --ob-displacement-atr-multiplier 1.5 \
  --ob-min-body-ratio 0.60 \
  --ob-min-width-atr-ratio 0.05 \
  --ob-max-width-atr-ratio 1.0
```

## 6. Replay và chart payload

In candle replay trong terminal:

```bash
python -m semi_bot_trading.cli replay --symbol XAUUSD --timeframe H1 --limit 20
python -m semi_bot_trading.cli replay --symbol XAUUSD --timeframe M15 --limit 20
```

Replay từ một thời điểm:

```bash
python -m semi_bot_trading.cli replay --symbol XAUUSD --timeframe H1 --start 2026-01-01T00:00:00+00:00 --limit 50
```

Export chart JSON:

```bash
python -m semi_bot_trading.cli export-chart-json --timeframe H1 --limit 500 --output var/chart_xauusd_h1.json
python -m semi_bot_trading.cli export-chart-json --timeframe M15 --limit 500 --output var/chart_xauusd_m15.json
```

Export chỉ active zones:

```bash
python -m semi_bot_trading.cli export-chart-json --timeframe H1 --limit 500 --active-zones-only --output var/chart_active_h1.json
```

## 7. Backtest

Backtest strategy engine incremental:

```bash
python -m semi_bot_trading.cli backtest-strategies --limit 30000 --engine incremental
```

Backtest report đầy đủ breakdown:

```bash
python -m semi_bot_trading.cli backtest-report --limit 30000 --engine incremental
```

Backtest riêng Trend Following Pullback, chỉ chạy playbook và entity liên quan:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 30000 \
  --engine incremental \
  --playbook trend_pullback
```

Backtest với spread/slippage custom:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 30000 \
  --engine incremental \
  --spread 0.30 \
  --slippage 0.10
```

Backtest giới hạn thời gian giữ lệnh:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 30000 \
  --engine incremental \
  --max-hold-candles 96
```

Backtest không auto-accept eligible setup:

```bash
python -m semi_bot_trading.cli backtest-strategies \
  --limit 30000 \
  --engine incremental \
  --no-auto-accept
```

Backtest có include human zones:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 30000 \
  --engine incremental \
  --include-human-zones
```

Persist backtest trades để vẽ lên chart UI:

```bash
python -m semi_bot_trading.cli backtest-strategies \
  --limit 30000 \
  --engine incremental \
  --persist \
  --clear-backtest-trades
```

Persist riêng Trend Following Pullback để review lệnh trên chart:

```bash
python -m semi_bot_trading.cli backtest-strategies \
  --limit 30000 \
  --engine incremental \
  --playbook trend_pullback \
  --persist \
  --clear-backtest-trades
```

Hoặc:

```bash
PERSIST=1 ./scripts/backtest_trend_pullback.sh
```

Backtest nhanh ít nến để smoke test:

```bash
python -m semi_bot_trading.cli backtest-report --limit 3000 --engine incremental --max-rows 10
```

Smoke test riêng Trend Following Pullback:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 3000 \
  --engine incremental \
  --playbook trend_pullback \
  --max-rows 10
```

Chạy bằng script riêng:

```bash
LIMIT=3000 MAX_ROWS=10 ./scripts/backtest_trend_pullback.sh
./scripts/backtest_trend_pullback.sh
```

Xuất HTML report dễ đọc:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 30000 \
  --engine incremental \
  --playbook trend_pullback \
  --html-output var/reports/trend_pullback.html
```

Hoặc dùng script:

```bash
HTML_OUTPUT=var/reports/trend_pullback.html ./scripts/backtest_trend_pullback.sh
```

## 8. Research / edge discovery

Sinh dataset setup-level để thống kê edge trước khi viết strategy:

```bash
python -m semi_bot_trading.cli research-events \
  --limit 30000 \
  --output var/research_events.csv
```

Chạy riêng một playbook, ví dụ Trend Pullback:

```bash
python -m semi_bot_trading.cli research-events \
  --limit 30000 \
  --playbook trend_pullback \
  --output var/research_trend_pullback.csv
```

Chạy riêng Zone Reaction V2:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 30000 \
  --engine incremental \
  --playbook zone_reaction_v2 \
  --html-output var/reports/zone_reaction_v2.html

python -m semi_bot_trading.cli backtest-report \
  --limit 30000 \
  --engine incremental \
  --playbook zone_reaction_v2 \
  --persist \
  --clear-backtest-trades \
  --html-output var/reports/zone_reaction_v2.html

python -m semi_bot_trading.cli research-events \
  --limit 30000 \
  --playbook zone_reaction_v2 \
  --output var/research_zone_reaction_v2.csv

python -m semi_bot_trading.cli research-report \
  --input var/research_zone_reaction_v2.csv \
  --html-output var/reports/research_zone_reaction_v2.html
```

Mặc định chỉ sample `eligible,waiting_confirmation`. Nếu muốn xem cả setup bị block:

```bash
python -m semi_bot_trading.cli research-events \
  --limit 30000 \
  --statuses eligible,waiting_confirmation,blocked \
  --output var/research_with_blocked.csv
```

Tạo report text và HTML từ CSV:

```bash
python -m semi_bot_trading.cli research-report \
  --input var/research_events.csv \
  --html-output var/reports/research_events.html
```

Chia data mặc định:

```text
train      <= 2024
validation = 2025
test       >= 2026
```

## 9. Test và build

Chạy toàn bộ Python tests:

```bash
python -m unittest discover -s tests
```

Chạy một test file:

```bash
python -m unittest tests.test_api
python -m unittest tests.test_smc_zones
python -m unittest tests.test_strategy
python -m unittest tests.test_backtest
```

Build frontend:

```bash
cd frontend
npm run build
cd ..
```

Chạy frontend tests nếu có:

```bash
cd frontend
npm test
cd ..
```

## 9. API debug bằng curl

Health check:

```bash
curl -s http://127.0.0.1:8000/api/health | python -m json.tool
```

Chart payload H1:

```bash
curl -s 'http://127.0.0.1:8000/api/chart?symbol=XAUUSD&timeframe=H1&limit=1000&playbooks=trend_pullback' \
  | python -m json.tool \
  | sed -n '1,80p'
```

Replay timeline H1 10k candles:

```bash
curl -s 'http://127.0.0.1:8000/api/replay/timeline?symbol=XAUUSD&timeframe=H1&limit=10000' \
  | python -m json.tool \
  | sed -n '1,40p'
```

Replay chart payload:

```bash
curl -s 'http://127.0.0.1:8000/api/chart?symbol=XAUUSD&timeframe=H1&limit=1000&replay_start=2026-01-18T23:00:00%2B00:00&replay_at=2026-01-22T20:00:00%2B00:00&playbooks=trend_pullback' \
  | python -m json.tool \
  | sed -n '1,120p'
```

## 10. Legacy chart server

Server chart cũ, không phải React/Vite dashboard hiện tại:

```bash
python -m semi_bot_trading.cli serve-chart --port 8765
```

Mở:

```text
http://127.0.0.1:8765
```

## 11. Config quan trọng

File config chính:

```text
config/trading.toml
```

Các nhóm config hay chỉnh:

```text
[structure.swing.timeframes]
[zones.support_resistance]
[zones.lifecycle]
[zones.smc]
[price_action]
[strategy]
[backtest]
```

Sau khi đổi config detector hoặc lifecycle, nên chạy lại pipeline detect tương ứng để DB được cập nhật.
