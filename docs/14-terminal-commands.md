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

Start backend và frontend cùng lúc trên Windows PowerShell:

```powershell
.\scripts\start-dev.ps1
```

Start backend, frontend và MT5/Telegram live worker:

```powershell
.\scripts\start-dev.ps1 -WithWorker
```

Bật auto execution cho live worker real account:

```powershell
.\scripts\start-dev.ps1 -WithWorker -EnableExecution
```

Mở UI:

```text
Realtime dashboard: http://127.0.0.1:5173/
Replay chart:       http://127.0.0.1:5173/replay-chart
Backend health:     http://127.0.0.1:8000/api/health
```

Trong Realtime dashboard, nút `Auto 60s` trên toolbar bật/tắt auto refresh chart mỗi 60 giây. Auto refresh chỉ chạy khi candle window đang ở `Latest`; khi xem `Start <index>` lịch sử, UI tự pause để tránh giật viewport.

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

Materialize SR/FVG giống replay/backtest vào DB cho realtime dashboard:

```bash
python -m semi_bot_trading.cli materialize-zones \
  --timeframe H1 \
  --detectors sr,fvg \
  --limit 15000 \
  --progress-every 1000
```

Lệnh này đi từng snapshot nến đã đóng, tính lại SR/FVG theo logic incremental giống backtest/replay rồi lưu vào bảng `price_zones`. Dùng nó khi realtime mode không thấy đủ zone lịch sử, hoặc sau khi thay đổi logic SR/FVG mà muốn dashboard đọc lại từ DB.

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
  --fvg-max-width-atr-ratio 1.5 \
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

Backtest strategy engine incremental cho playbook runtime hien tai:

```bash
python -m semi_bot_trading.cli backtest-strategies \
  --limit 60000 \
  --engine incremental \
  --playbook zone_reaction_v2
```

Backtest report đầy đủ breakdown:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 60000 \
  --engine incremental \
  --playbook zone_reaction_v2
```

Backtest với spread/slippage custom:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 60000 \
  --engine incremental \
  --playbook zone_reaction_v2 \
  --spread 0.30 \
  --slippage 0.10
```

Backtest giới hạn thời gian giữ lệnh:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 60000 \
  --engine incremental \
  --playbook zone_reaction_v2 \
  --max-hold-candles 96
```

Backtest không auto-accept eligible setup:

```bash
python -m semi_bot_trading.cli backtest-strategies \
  --limit 60000 \
  --engine incremental \
  --playbook zone_reaction_v2 \
  --no-auto-accept
```

Backtest có include human zones:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 60000 \
  --engine incremental \
  --playbook zone_reaction_v2 \
  --include-human-zones
```

Persist backtest trades để vẽ lên chart UI:

```bash
python -m semi_bot_trading.cli backtest-strategies \
  --limit 60000 \
  --engine incremental \
  --playbook zone_reaction_v2 \
  --persist \
  --clear-backtest-trades
```

Persist Zone Reaction V2 để review lệnh trên chart:

```bash
python -m semi_bot_trading.cli backtest-strategies \
  --limit 60000 \
  --engine incremental \
  --playbook zone_reaction_v2 \
  --persist \
  --clear-backtest-trades
```

Backtest nhanh ít nến để smoke test:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 3000 \
  --engine incremental \
  --playbook zone_reaction_v2 \
  --max-rows 10
```

Xuất HTML report dễ đọc:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 60000 \
  --engine incremental \
  --playbook zone_reaction_v2 \
  --html-output var/reports/zone_reaction_v2.html
```

Tren macOS/Linux nen dung dau `/` cho `--html-output`. CLI co normalize path kieu Windows nhu `var\reports\file.html`, va ca case zsh nuot dau `\` thanh `varreportsfile.html`, de report van duoc ghi vao `var/reports/`.

Backtest SR Breakout V1:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 60000 \
  --engine incremental \
  --playbook sr_breakout_v1 \
  --html-output var/reports/sr_breakout_v1.html
```

Persist SR Breakout V1 de ve trade len chart UI:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 60000 \
  --engine incremental \
  --playbook sr_breakout_v1 \
  --persist \
  --clear-backtest-trades \
  --html-output var/reports/sr_breakout_v1.html
```

Legacy playbooks nhu `trend_pullback`, `ob_mitigation_continuation`, `fvg_fill_go`, `breakout_retest`, `momentum_expansion_continuation`, `range_boundary_reversal`, `liquidity_sweep_reversal`, va `failed_breakout_trap` da ngung runtime. Playbook runtime/research hien tai la `zone_reaction_v2` va `sr_breakout_v1`; CLI/API se bao loi neu truyen playbook cu.

## 8. Research / edge discovery

Sinh dataset setup-level để thống kê edge trước khi viết strategy:

```bash
python -m semi_bot_trading.cli research-events \
  --limit 60000 \
  --playbook zone_reaction_v2 \
  --output var/research_events.csv
```

Chạy riêng Zone Reaction V2:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 60000 \
  --engine incremental \
  --playbook zone_reaction_v2 \
  --html-output var/reports/zone_reaction_v2.html

python -m semi_bot_trading.cli backtest-report \
  --limit 60000 \
  --engine incremental \
  --playbook zone_reaction_v2 \
  --persist \
  --clear-backtest-trades \
  --html-output var/reports/zone_reaction_v2.html

python -m semi_bot_trading.cli research-events \
  --limit 60000 \
  --playbook zone_reaction_v2 \
  --output var/research_zone_reaction_v2.csv

python -m semi_bot_trading.cli research-report \
  --input var/research_zone_reaction_v2.csv \
  --html-output var/reports/research_zone_reaction_v2.html
```

Mặc định chỉ sample `eligible,waiting_confirmation`. Nếu muốn xem cả setup bị block:

```bash
python -m semi_bot_trading.cli research-events \
  --limit 60000 \
  --playbook zone_reaction_v2 \
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
curl -s 'http://127.0.0.1:8000/api/chart?symbol=XAUUSD&timeframe=H1&limit=1000&playbooks=zone_reaction_v2' \
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
curl -s 'http://127.0.0.1:8000/api/chart?symbol=XAUUSD&timeframe=H1&limit=1000&replay_start=2026-01-18T23:00:00%2B00:00&replay_at=2026-01-22T20:00:00%2B00:00&playbooks=zone_reaction_v2' \
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

## Live MT5 and Telegram

Create local `.env` from `.env.example` and fill real credentials outside git.

Telegram smoke test:

```powershell
python -m semi_bot_trading.cli telegram-test --message-key smoke-1
```

Run one MT5 live-worker iteration without looping:

```powershell
python -m semi_bot_trading.cli live-worker --once
```

Run continuous live worker:

```powershell
python -m semi_bot_trading.cli live-worker
```

Important environment values:

```text
MT5_SYMBOL=XAUUSDm
MT5_PATH=C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe
EXECUTION_ENABLED=false
LIVE_ORDER_VOLUME=0.01
LIVE_EVALUATE_INTRABAR=false
```

`MT5_PATH` must point to `terminal64.exe`, not only the MetaTrader install
folder. This avoids `IPC initialize failed, MetaTrader 5 x64 not found` when the
worker runs as a Windows service.

Set `EXECUTION_ENABLED=true` only when the worker may send real market orders.

Set `LIVE_EVALUATE_INTRABAR=true` only if the live worker should evaluate setup
candidates on every poll using MT5's still-forming live candle. This helps catch
wick touches/rejections before the candle closes, while detectors still update
only on closed candles.
