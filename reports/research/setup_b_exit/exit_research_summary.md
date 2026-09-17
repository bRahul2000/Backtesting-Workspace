# Setup B frozen-entry exit research

**RESEARCH ONLY — NOT ACTIVE STRATEGY.** No entry, strategy, or generic engine rule was changed.

Development: 2021–2024. Forward-validation: 2025–latest available 2026; previously viewed summary data, not a pristine holdout.

Source SHA256: `aa7031999b1905751b09ac5d64e97fe5bb77d19b0a1a5b0e0100c0b260223eba`. Frozen entries: 955.

Each experiment uses the exact signal, pending trigger, actual fill, structural initial stop, direction, quantity, and planned risk of each frozen completed trade.
Alternative exits may overlap other frozen entries. These are trade-level counterfactuals, not feasible account backtests. Drawdown is worst within a continuous source segment, starting at $10,000 each segment; no equity continuity across gaps.

Opening stop gaps fill at open; opening target gaps fill at target. Intrabar stop wins over target, partial, or BE activation. A newly activated price-BE stop wins over another target on the same ambiguous candle. Partial exits charge commission on each leg; entry commission is charged once. Open positions at segment end remain open and are excluded from completed PnL.

MFE reach sanity check: the lower bound is Phase 4C's path-known excursion. The OHLC possible upper bound includes fill/exit bar extremes that might occur before entry or after exit, so it is not an observed fillable rate.

- +1R: lower 50.99%, possible upper 51.83%
- +1.5R: lower 42.09%, possible upper 42.51%
- +2R: lower 35.08%, possible upper 35.39%
- +3R: lower 26.60%, possible upper 26.70%

## Development results

| Model | Trades | Wins | Losses | BE | WR % | Gross $ | Costs $ | Net $ | PF | Avg R | Median R | Worst segment DD % | Max losses | Avg bars | Full initial stop % | Price BE exits % | Partial exits % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| E0 | 639 | 172 | 467 | 0 | 26.92 | 898.59 | 2353.05 | -1454.46 | 0.874 | -0.089 | -1.000 | 4.82 | 13 | 25.2 | 72.9 | 0.0 | 0.0 |
| E1 | 639 | 219 | 420 | 0 | 34.27 | 329.47 | 2353.01 | -2023.54 | 0.805 | -0.126 | -1.000 | 4.62 | 13 | 17.7 | 65.6 | 0.0 | 0.0 |
| E2 | 639 | 269 | 370 | 0 | 42.10 | 641.68 | 2353.03 | -1711.35 | 0.813 | -0.107 | -1.000 | 4.44 | 7 | 12.7 | 57.7 | 0.0 | 0.0 |
| E3 | 639 | 78 | 561 | 0 | 12.21 | -1579.75 | 2352.92 | -3932.67 | 0.546 | -0.246 | -0.384 | 8.87 | 45 | 13.0 | 48.5 | 39.1 | 0.0 |
| E4 | 639 | 108 | 531 | 0 | 16.90 | -973.40 | 2352.79 | -3326.19 | 0.660 | -0.207 | -1.000 | 6.72 | 25 | 18.4 | 57.7 | 25.2 | 0.0 |
| E5 | 639 | 172 | 467 | 0 | 26.92 | 597.14 | 2353.15 | -1756.01 | 0.788 | -0.109 | -0.279 | 4.35 | 13 | 25.2 | 48.5 | 0.0 | 51.5 |
| E6 | 639 | 314 | 325 | 0 | 49.14 | -642.03 | 2353.08 | -2995.11 | 0.613 | -0.187 | -0.080 | 6.51 | 7 | 13.0 | 48.5 | 39.1 | 51.5 |
| E7 | 639 | 105 | 534 | 0 | 16.43 | -2077.61 | 2353.13 | -4430.74 | 0.484 | -0.278 | -0.384 | 8.58 | 20 | 11.2 | 48.5 | 34.9 | 0.0 |

## Original-exit cost sensitivity · full frozen history

| Scenario | Fee % per side | Trades | Gross $ | Costs $ | Net $ | PF | Avg R | Required WR % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A Current | 0.050 | 955 | 1091.74 | 3728.18 | -2636.44 | 0.847 | -0.110 | 29.79 |
| B Zero | 0.000 | 955 | 1091.74 | 0.00 | 1091.74 | 1.075 | 0.048 | 25.16 |
| C 0.01% | 0.010 | 955 | 1091.74 | 745.64 | 346.11 | 1.023 | 0.016 | 26.11 |
| D 0.025% | 0.025 | 955 | 1091.74 | 1864.09 | -772.35 | 0.951 | -0.031 | 27.53 |
| E 0.05% | 0.050 | 955 | 1091.74 | 3728.18 | -2636.44 | 0.847 | -0.110 | 29.79 |
| F 0.10% | 0.100 | 955 | 1091.74 | 7456.35 | -6364.61 | 0.682 | -0.269 | 34.53 |

Development-robust rule, fixed before viewing validation: at least 100 completed trades, average R > 0, PF > 1, positive net PnL in at least 2 development calendar years, and worst segment DD no more than 1.25× E0. This is a descriptive label, not a live recommendation.

Development-robust models: none

Only these models were simulated on forward-validation after development selection. E0 full-history costs are a separate unchanged-exit sensitivity audit.

The optional ATR trailing experiment was omitted: it requires extra path-sensitive exit state and adds a trailing parameter beyond the clean E0–E7 isolation.
