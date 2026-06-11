# Semi Bot Trading Agent Guide

This file gives AI coding agents the minimum project context needed to work productively in this repo.

## RTK CLI Token Saver

RTK is installed on this machine and can reduce noisy terminal output before it reaches the AI context.

Use RTK when a command is expected to produce large or repetitive output:

```bash
rtk git status
rtk git diff
rtk npm run build
rtk pytest -q
rtk test python -m unittest discover -s tests
rtk ls
rtk find . -name "*.py"
rtk read semi_bot_trading/strategy.py
rtk grep "zone_reaction_v2" semi_bot_trading
```

Use raw commands when exact output matters, when the developer instructions require a specific tool such as `rg`, or when RTK does not support the command cleanly. For raw but tracked execution:

```bash
rtk proxy <command>
```

Useful RTK diagnostics:

```bash
rtk --version
rtk gain
which rtk
```

## Project

Semi-automated XAUUSD trading research system.

- Backend: Python, FastAPI, SQLite.
- Frontend: React, TypeScript, Vite, `lightweight-charts`.
- MVP market: XAUUSD on H1 context and M15 reaction/trigger.
- Current focus: replay/backtest, zone/reaction debugging, and human review before live MT5 execution.

## Important Docs

Read these before touching related code:

- Product overview: `docs/00-tong-quan-san-pham.md`
- Architecture: `docs/01-kien-truc-he-thong.md`
- Data model and override: `docs/02-mo-hinh-du-lieu-va-override.md`
- Chart UI workflow: `docs/04-chart-ui-human-workflow.md`
- Strategy/playbooks: `docs/06-strategy-playbooks-h1-m15.md`
- Project status: `docs/11-project-status.md`
- Terminal commands: `docs/14-terminal-commands.md`
- SR formula: `docs/10-support-resistance-formula.md`
- SMC/FVG/OB formula: `docs/12-smc-detectors-formula.md`
- Price action formula: `docs/13-price-action-detectors-formula.md`
- Bias formula: `docs/16-bias-formula.md`
- Zone Reaction V2: `docs/19-zone-reaction-v2.md`

## Core Principles

- H1 is the main context timeframe for bias, regime, structure, and zones in the MVP.
- M15 is used for price reaction, trigger, and strategy execution.
- Replay/backtest must avoid look-ahead bias. Only use candles, zones, contexts, and confirmed structure available at or before the signal candle close.
- Human-edited zones and overrides are first-class data. Do not overwrite or delete them unless explicitly requested.
- Bot zones and backtest snapshots are different concepts:
  - Realtime/dashboard reads persisted zones from `price_zones`.
  - Incremental backtest recomputes point-in-time zone snapshots to avoid look-ahead.
  - If debugging a persisted backtest trade, prefer the trade metadata zone snapshot over current `price_zones`.

## Commands

Run from repo root:

```bash
cd /Users/thang.nd/Documents/semi-bot-trading
```

Start backend:

```bash
rtk proxy python -m semi_bot_trading.cli serve-api --port 8000
```

Start frontend:

```bash
cd frontend
rtk npm run dev -- --port 5173
```

Run Python tests:

```bash
rtk test python -m unittest discover -s tests
```

Build frontend:

```bash
cd frontend
rtk npm run build
```

Regenerate core detector data after config changes:

```bash
python -m semi_bot_trading.cli detect-structure --timeframe H1
python -m semi_bot_trading.cli detect-breaks --timeframe H1
python -m semi_bot_trading.cli detect-structure --timeframe M15
python -m semi_bot_trading.cli detect-breaks --timeframe M15
python -m semi_bot_trading.cli detect-bias --timeframe H1
python -m semi_bot_trading.cli detect-regime --timeframe H1
python -m semi_bot_trading.cli detect-zones --timeframe H1
python -m semi_bot_trading.cli apply-zone-lifecycle --timeframe H1
python -m semi_bot_trading.cli detect-smc-zones --timeframe H1
python -m semi_bot_trading.cli detect-price-action --timeframe M15
```

Run Zone Reaction V2 backtest and persist trades:

```bash
python -m semi_bot_trading.cli backtest-report \
  --limit 60000 \
  --engine incremental \
  --playbook zone_reaction_v2 \
  --persist \
  --clear-backtest-trades \
  --html-output var/reports/zone_reaction_v2.html
```

See more commands in `docs/14-terminal-commands.md`.

## Code Map

- CLI: `semi_bot_trading/cli.py`
- API: `semi_bot_trading/api.py`
- DB schema: `semi_bot_trading/db.py`
- Chart payload: `semi_bot_trading/chart.py`
- Replay payload: `semi_bot_trading/replay_chart.py`
- SR zones: `semi_bot_trading/zones.py`
- FVG/OB/liquidity/consolidation: `semi_bot_trading/smc_zones.py`
- Bias/regime context: `semi_bot_trading/context.py`
- Price action: `semi_bot_trading/price_action.py`
- Strategy engine: `semi_bot_trading/strategy.py`
- Backtest: `semi_bot_trading/backtest.py`
- Reports: `semi_bot_trading/backtest_report.py`, `semi_bot_trading/research_report.py`
- Frontend chart: `frontend/src/components/TradingChart.tsx`
- Frontend inspector/panels: `frontend/src/components/Inspector.tsx`

## Editing Rules

- Prefer small, focused changes.
- Use existing config in `config/trading.toml`; add config before hardcoding thresholds.
- Use structured parsing and typed models where the codebase already has them.
- Do not remove user-created zones, reviews, comments, or overrides.
- If changing detector or strategy logic, update the matching doc in `docs/`.
- If changing frontend behavior, run `npm run build`.
- If changing backend logic, run relevant unit tests or the full test suite.

## Current Strategy Notes

- Runtime, research, and backtest focus is `zone_reaction_v2`.
- Legacy playbooks are disabled/removed from candidate generation and UI selection. Keep old trade rows readable for review, but do not use legacy playbooks to judge current edge.
- `zone_reaction_v2` uses single-zone reactions first: support, resistance, FVG. Consolidation is currently excluded from the strategy because it created too many noisy trades.
- OB and consolidation can still be displayed for human context/research, but they do not create `zone_reaction_v2` trades.
- Backtest trades should be persisted with `source='backtest'` and `metadata_json.backtest=true` so they can be filtered and cleared.

## UX Expectations

- Chart should not autoscale or jump when selecting/editing zones/trades.
- Click a trade in history should pan to that trade without changing vertical scale.
- UI state such as visible layers and trade filters should be retained in local storage.
- Human review/comment on trades is important for future optimization.
