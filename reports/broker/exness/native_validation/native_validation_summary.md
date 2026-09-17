# Exness BTCUSDm native-price Setup B validation

**BROKER-NATIVE PRICE DATA.** The Setup B signal feed uses actual Exness BTCUSDm Bid M15 bars. Strategy defaults, H1 confirmation, pending entry, structural stop, 3R target, and generic execution rules are unchanged.

**BAR SPREAD COST = LOWER-BOUND RESEARCH, NOT TICK-EXACT EXECUTION.** MT5 M15 SPREAD records a bar minimum. Charging one entry-bar minimum spread per completed trade is optimistic. The $10/$15/$20/$30 scenarios are separate fixed-spread sensitivities; none claims the same spread throughout history. Zero-cost results isolate the broker price feed.

Each contiguous data segment is backtested independently after the programmatic confirmed-H1/M15 warm-up; account and indicator state reset at gaps. An open position at a segment's last candle remains open and is excluded from completed-trade PnL under existing end-of-test semantics. Results pooled across segments are trade sums, not one compounded equity curve.

Exact timestamp intersection: 100,086 candles; Exness-only 94; Bitstamp-only 99,998. Close correlation 0.999999; adjacent-return correlation 0.992809; median absolute close difference $15.55 (0.0203%).

Common-window final signals: Exness 589, Bitstamp 604; exact 412, near 28, opposite 0, Exness-only 149, Bitstamp-only 164. Exact matches are 69.95% of Exness signals; near 4.75%, opposite 0.00%, Exness-only 25.30%; Bitstamp-only 27.15% of Bitstamp signals.

## Frozen Setup B results

| Feed | Scope | Cost view | Signals | Fills | Trades | Long | Short | WR % | PF | Average R | Net PnL |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| exness_native | full_native | zero_cost | 615 | 500 | 498 | 269 | 229 | 25.30 | 1.0071 | 0.0081 | 65.59 |
| exness_native | earlier_2023_2024 | zero_cost | 229 | 184 | 183 | 109 | 74 | 25.14 | 1.0023 | 0.0051 | 7.81 |
| exness_native | later_2025_2026 | zero_cost | 386 | 316 | 315 | 160 | 155 | 25.40 | 1.0099 | 0.0099 | 57.78 |
| exness_native | full_native | bar_minimum_spread_lower_bound | 615 | 500 | 498 | 269 | 229 | 25.30 | 0.9372 | -0.0465 | -611.74 |
| exness_native | earlier_2023_2024 | bar_minimum_spread_lower_bound | 229 | 184 | 183 | 109 | 74 | 25.14 | 0.9104 | -0.0685 | -326.39 |
| exness_native | later_2025_2026 | bar_minimum_spread_lower_bound | 386 | 316 | 315 | 160 | 155 | 25.40 | 0.9532 | -0.0337 | -285.36 |
| exness_native | full_native | fixed_spread_$10 | 615 | 500 | 498 | 269 | 229 | 25.30 | 0.9753 | -0.0159 | -233.75 |
| exness_native | earlier_2023_2024 | fixed_spread_$10 | 229 | 184 | 183 | 109 | 74 | 25.14 | 0.9692 | -0.0204 | -107.41 |
| exness_native | later_2025_2026 | fixed_spread_$10 | 386 | 316 | 315 | 160 | 155 | 25.40 | 0.9789 | -0.0134 | -126.34 |
| exness_native | full_native | fixed_spread_$15 | 615 | 500 | 498 | 269 | 229 | 25.30 | 0.9599 | -0.0280 | -383.43 |
| exness_native | earlier_2023_2024 | fixed_spread_$15 | 229 | 184 | 183 | 109 | 74 | 25.14 | 0.9532 | -0.0331 | -165.02 |
| exness_native | later_2025_2026 | fixed_spread_$15 | 386 | 316 | 315 | 160 | 155 | 25.40 | 0.9639 | -0.0250 | -218.40 |
| exness_native | full_native | fixed_spread_$20 | 615 | 500 | 498 | 269 | 229 | 25.30 | 0.9449 | -0.0400 | -533.10 |
| exness_native | earlier_2023_2024 | fixed_spread_$20 | 229 | 184 | 183 | 109 | 74 | 25.14 | 0.9376 | -0.0458 | -222.63 |
| exness_native | later_2025_2026 | fixed_spread_$20 | 386 | 316 | 315 | 160 | 155 | 25.40 | 0.9492 | -0.0366 | -310.46 |
| exness_native | full_native | fixed_spread_$30 | 615 | 500 | 498 | 269 | 229 | 25.30 | 0.9159 | -0.0640 | -832.44 |
| exness_native | earlier_2023_2024 | fixed_spread_$30 | 229 | 184 | 183 | 109 | 74 | 25.14 | 0.9074 | -0.0712 | -337.86 |
| exness_native | later_2025_2026 | fixed_spread_$30 | 386 | 316 | 315 | 160 | 155 | 25.40 | 0.9209 | -0.0598 | -494.59 |
| exness_overlap | exact_common_timestamps | zero_cost | 589 | 477 | 475 | 249 | 226 | 25.05 | 0.9950 | -0.0020 | -44.24 |
| bitstamp_overlap | exact_common_timestamps | zero_cost | 604 | 484 | 483 | 252 | 231 | 26.09 | 1.0592 | 0.0438 | 516.02 |

## Exness native yearly

| Year | Cost view | Trades | WR % | PF | Average R | Net PnL |
|---|---|---:|---:|---:|---:|---:|
| 2023 partial | zero_cost | 14 | 14.29 | 0.4981 | -0.4286 | -149.80 |
| 2024 | zero_cost | 169 | 26.04 | 1.0509 | 0.0410 | 157.61 |
| 2025 | zero_cost | 187 | 23.53 | 0.9018 | -0.0715 | -345.02 |
| 2026 partial | zero_cost | 128 | 28.12 | 1.1733 | 0.1287 | 402.80 |
| 2023 partial | bar_minimum_spread_lower_bound | 14 | 14.29 | 0.4592 | -0.4924 | -172.04 |
| 2024 | bar_minimum_spread_lower_bound | 169 | 26.04 | 0.9535 | -0.0334 | -154.34 |
| 2025 | bar_minimum_spread_lower_bound | 187 | 23.53 | 0.8464 | -0.1190 | -565.20 |
| 2026 partial | bar_minimum_spread_lower_bound | 128 | 28.12 | 1.1158 | 0.0910 | 279.84 |

Price correlation does not imply signal or trade agreement. This remains an M15 OHLC execution-convention comparison, not a tick-replayed broker execution backtest. No parameter was selected or optimized.
