# Breakout Retest Research

## Current Definition In Code

`breakout_retest` currently only uses `consolidation` zones.

The current engine emits this playbook when a consolidation zone gets a confirmed close outside the range:

- Long candidate: candle closes above `range_high + breakout_buffer`.
- Short candidate: candle closes below `range_low - breakout_buffer`.
- Reaction state: `retest_waiting`.
- Candidate status: `waiting_confirmation`.

Important caveat: the current implementation does not yet require an actual retest candle and rejection after breakout. It marks the setup as `waiting_confirmation` at breakout confirmation time, then research measures future outcome from the next M15 open. This means current research is measuring “post-breakout continuation potential”, not a complete strict retest entry.

## Research Dataset

Source:

```bash
python -m semi_bot_trading.cli research-events --limit 30000 --output var/research_events.csv
```

Filtered report:

```bash
python -m semi_bot_trading.cli research-report \
  --input var/research_breakout_retest.csv \
  --html-output var/reports/research_breakout_retest.html
```

Files:

- `var/research_breakout_retest.csv`
- `var/reports/research_breakout_retest.html`

Split:

- Train: signal year <= 2024.
- Validation: signal year = 2025.
- Test: signal year >= 2026.

## Headline Result

| Split | Samples | Win Rate | Total R | Avg R | Profit Factor |
|---|---:|---:|---:|---:|---:|
| Train | 44 | 56.82% | +5.61R | +0.13R | 1.60 |
| Validation | 1229 | 51.51% | +77.54R | +0.06R | 1.23 |
| Test | 276 | 47.10% | +26.55R | +0.10R | 1.44 |

This is the cleanest playbook so far because it stays positive across train, validation, and test.

## Strongest Observations

### Direction

| Direction | Samples | Win Rate | Total R | Avg R | Profit Factor |
|---|---:|---:|---:|---:|---:|
| Long | 1129 | 57.04% | +179.86R | +0.16R | 1.70 |
| Short | 420 | 34.29% | -70.17R | -0.17R | 0.51 |

The current edge is mostly long-side only. Short breakout retests are strongly negative in this dataset.

### H1 Bias

| H1 Bias | Samples | Win Rate | Total R | Avg R | Profit Factor |
|---|---:|---:|---:|---:|---:|
| Bullish | 435 | 57.01% | +84.51R | +0.19R | 1.95 |
| Neutral | 1018 | 50.79% | +43.34R | +0.04R | 1.15 |
| Bearish | 96 | 23.96% | -18.16R | -0.19R | 0.40 |

The best context is bullish H1 bias. Bearish H1 context is poor for this current playbook, especially because short direction is weak.

### H1 Regime

| H1 Regime | Samples | Win Rate | Total R | Avg R | Profit Factor |
|---|---:|---:|---:|---:|---:|
| Ranging | 874 | 53.66% | +81.28R | +0.09R | 1.38 |
| Trending | 675 | 47.26% | +28.41R | +0.04R | 1.15 |

Ranging context is slightly better overall. However, bullish-trending long breakouts are still one of the strongest stable subsets.

### Stable Validation/Test Subsets

These subsets were positive in both validation and test:

| Condition | Validation | Test |
|---|---|---|
| `long + bullish bias + trending regime` | n=339, avg +0.207R, PF 2.08 | n=53, avg +0.257R, PF 2.13 |
| `long + neutral bias + ranging regime` | n=428, avg +0.168R, PF 1.70 | n=106, avg +0.183R, PF 2.52 |
| `long + bullish bias + ranging regime` | n=28, avg +0.044R, PF 1.17 | n=10, avg +0.312R, PF 3.15 |

The first two are the most useful because they have enough samples and stay positive out of sample.

## Trigger Notes

Bullish triggers perform much better than bearish triggers:

- `BOS + displacement_bullish`: n=19, avg +0.40R, PF 3.23.
- `marubozu_bullish`: n=56, avg +0.22R, PF 2.15.
- `displacement_bullish`: n=50, avg +0.15R, PF 1.58.
- `pinbar_bullish`: n=99, avg +0.14R, PF 1.70.

Many no-trigger rows are still positive because current implementation is measuring breakout continuation after confirmed close, not strict retest confirmation.

## Risks / Known Weaknesses

- Current rule may be too permissive because it creates the candidate immediately after breakout confirmation.
- The playbook name says retest, but the current implementation has not yet modeled a true retest lifecycle:
  - breakout confirmed,
  - wait for price to return to broken range boundary,
  - require rejection/continuation trigger,
  - then create eligible trade idea.
- Short-side performance is poor and should be disabled first during optimization.
- Result may be partly caused by long-side XAUUSD drift in this dataset.

## Proposed V2

Start with a narrow `breakout_retest_v2`:

1. Only allow long setups first.
2. Require either:
   - H1 bias bullish + H1 regime trending, or
   - H1 bias neutral + H1 regime ranging.
3. Use only consolidation zones.
4. After breakout confirmed, do not trade immediately.
5. Enter only after retest:
   - price returns to range high after bullish breakout,
   - close remains above range high or rejects back upward,
   - bullish PA/BOS/displacement is preferred.
6. Block short setups until separate research proves short edge.
7. Track breakout candle strength:
   - close outside range by at least `0.15 ATR`,
   - optional body size filter vs ATR,
   - optional avoid overextended candle if breakout is too far from range.

## Next Research Questions

- Does true retest improve or reduce edge compared with entering on next candle after breakout?
- Is the edge mostly from bullish gold drift rather than breakout logic?
- What is the best max wait after breakout: 4, 8, 16, or 24 M15 candles?
- Should TP be fixed 2R, range-height projection, next liquidity, or trailing?
- Does `neutral + ranging + long breakout` outperform because it catches range expansion?
- Should bearish breakout retest be disabled entirely or separately tuned?

