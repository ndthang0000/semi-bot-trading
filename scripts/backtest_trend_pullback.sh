#!/usr/bin/env bash
set -euo pipefail

LIMIT="${LIMIT:-30000}"
ENGINE="${ENGINE:-incremental}"
MAX_ROWS="${MAX_ROWS:-20}"
HTML_OUTPUT="${HTML_OUTPUT:-}"
PERSIST="${PERSIST:-0}"

HTML_ARGS=()
if [[ -n "$HTML_OUTPUT" ]]; then
  HTML_ARGS=(--html-output "$HTML_OUTPUT")
fi

if [[ "$PERSIST" == "1" || "$PERSIST" == "true" ]]; then
  python -m semi_bot_trading.cli backtest-strategies \
    --limit "$LIMIT" \
    --engine "$ENGINE" \
    --playbook trend_pullback \
    --persist \
    --clear-backtest-trades \
    "$@"
else
  python -m semi_bot_trading.cli backtest-report \
    --limit "$LIMIT" \
    --engine "$ENGINE" \
    --playbook trend_pullback \
    --max-rows "$MAX_ROWS" \
    "${HTML_ARGS[@]}" \
    "$@"
fi
