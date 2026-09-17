# Exness Standard BTCUSDm cost recalibration — research only

**COST-CALIBRATED RESEARCH — NOT A BROKER-NATIVE BACKTEST**

This is NOT a broker-native Exness historical backtest. Signals and market movement remain from Bitstamp BTC/USD. Only trading-cost and lot-size assumptions are replaced with a calibrated Exness Standard approximation. A broker-native result requires longer Exness Bid/Ask history and chronological tick-level execution replay.

Frozen source: `trade_diagnostics.csv` SHA-256 `aa7031999b1905751b09ac5d64e97fe5bb77d19b0a1a5b0e0100c0b260223eba`; 955 completed trades. No signals, pending orders, fills, stops, targets, or exits were regenerated.

Exness Standard BTCUSDm: 1 lot = 1 BTC; minimum 0.01 lot; step 0.01 lot; commission $0. Five observed 24-hour samples had a $10/BTC spread. The $10 value is a **CALIBRATED FIXED-SPREAD APPROXIMATION**, not a claim about 2021–2026 spread history.

One full spread is charged per complete round trip: `spread cost = spread USD/BTC × BTC quantity`. At 1 BTC and $10 spread, cost is about $10 total, not $10 on entry plus $10 on exit. This reprices completed trade PnL without changing fill prices or stop/target events.

Cost-only keeps theoretical BTC quantity. Executable floors quantity to 0.01-lot steps, excludes results below 0.01 lot, and scales price PnL and planned risk by the quantity ratio. It does not replay balance-dependent future sizing or risk locks. `final_balance_arithmetic_reference` is $10,000 plus summed trade PnL, not a compounded cross-gap equity curve.

## All-history comparison

| View | Scenario | Trades | Executable | Gross pre-cost | Cost | Net PnL | PF | Average R | Cost/trade | Cost R/trade | Arithmetic balance |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| cost_only | old_0.05pct_per_side | 955 | 955 | 1091.74 | 3728.18 | -2636.44 | 0.8474 | -0.1102 | 3.9038 | 0.1583 | 7363.56 |
| cost_only | zero_cost | 955 | 955 | 1091.74 | 0.00 | 1091.74 | 1.0750 | 0.0481 | 0.0000 | 0.0000 | 11091.74 |
| cost_only | spread_$5 | 955 | 955 | 1091.74 | 436.35 | 655.39 | 1.0441 | 0.0297 | 0.4569 | 0.0184 | 10655.39 |
| cost_only | spread_$10 | 955 | 955 | 1091.74 | 872.70 | 219.04 | 1.0144 | 0.0113 | 0.9138 | 0.0368 | 10219.04 |
| cost_only | spread_$15 | 955 | 955 | 1091.74 | 1309.05 | -217.31 | 0.9860 | -0.0071 | 1.3707 | 0.0552 | 9782.69 |
| cost_only | spread_$20 | 955 | 955 | 1091.74 | 1745.40 | -653.66 | 0.9586 | -0.0255 | 1.8276 | 0.0736 | 9346.34 |
| cost_only | spread_$30 | 955 | 955 | 1091.74 | 2618.10 | -1526.35 | 0.9070 | -0.0623 | 2.7415 | 0.1104 | 8473.65 |
| executable | old_0.05pct_per_side | 955 | 955 | 1179.57 | 3457.22 | -2277.64 | 0.8542 | -0.1102 | 3.6201 | 0.1583 | 7722.36 |
| executable | zero_cost | 955 | 955 | 1179.57 | 0.00 | 1179.57 | 1.0900 | 0.0481 | 0.0000 | 0.0000 | 11179.57 |
| executable | spread_$5 | 955 | 955 | 1179.57 | 413.05 | 766.52 | 1.0572 | 0.0297 | 0.4325 | 0.0184 | 10766.52 |
| executable | spread_$10 | 955 | 955 | 1179.57 | 826.10 | 353.47 | 1.0258 | 0.0113 | 0.8650 | 0.0368 | 10353.47 |
| executable | spread_$15 | 955 | 955 | 1179.57 | 1239.15 | -59.58 | 0.9957 | -0.0071 | 1.2975 | 0.0552 | 9940.42 |
| executable | spread_$20 | 955 | 955 | 1179.57 | 1652.20 | -472.63 | 0.9669 | -0.0255 | 1.7301 | 0.0736 | 9527.37 |
| executable | spread_$30 | 955 | 955 | 1179.57 | 2478.30 | -1298.73 | 0.9126 | -0.0623 | 2.5951 | 0.1104 | 8701.27 |

## Lot sizing

Below 0.01 lot: 0 trades. Mean quantity: 0.091382 BTC theoretical, 0.086503 BTC floored. Mean planned risk: $24.70 before, $22.42 after. Mean risk reduction: 9.25%.

## Development and forward validation · $10 spread

| View | Set | Trades | PF | Average R | Net PnL |
|---|---|---:|---:|---:|---:|
| cost_only | development | 639 | 1.0175 | 0.0138 | 181.67 |
| cost_only | forward-validation | 316 | 1.0078 | 0.0062 | 37.38 |
| executable | development | 639 | 1.0369 | 0.0138 | 350.56 |
| executable | forward-validation | 316 | 1.0007 | 0.0062 | 2.91 |

## Calibrated $10 by year

| View | Year | Trades | PF | Average R | Net PnL |
|---|---:|---:|---:|---:|---:|
| cost_only | 2021 | 162 | 0.9256 | -0.0504 | -212.73 |
| cost_only | 2022 | 136 | 0.8916 | -0.0729 | -252.24 |
| cost_only | 2023 | 171 | 1.1371 | 0.0845 | 353.40 |
| cost_only | 2024 | 170 | 1.1118 | 0.0731 | 293.23 |
| cost_only | 2025 | 193 | 0.8674 | -0.0847 | -398.58 |
| cost_only | 2026 | 123 | 1.2446 | 0.1489 | 435.96 |
| executable | 2021 | 162 | 0.9550 | -0.0504 | -112.07 |
| executable | 2022 | 136 | 0.8914 | -0.0729 | -239.26 |
| executable | 2023 | 171 | 1.1416 | 0.0845 | 352.15 |
| executable | 2024 | 170 | 1.1505 | 0.0731 | 349.74 |
| executable | 2025 | 193 | 0.8539 | -0.0847 | -378.65 |
| executable | 2026 | 123 | 1.2386 | 0.1489 | 381.57 |

## Calibrated $10 by direction

| View | Direction | Trades | PF | Average R | Net PnL |
|---|---|---:|---:|---:|---:|
| cost_only | LONG | 466 | 1.0069 | 0.0083 | 50.37 |
| cost_only | SHORT | 489 | 1.0215 | 0.0141 | 168.67 |
| executable | LONG | 466 | 1.0205 | 0.0083 | 136.97 |
| executable | SHORT | 489 | 1.0309 | 0.0141 | 216.50 |

The old-cost net PnL is negative, while the $10 calibrated cost-only and lot-rounded approximations are slightly positive. Thus the headline sign changes under this assumption, but the edge is thin: the $15 spread case is negative, 2021/2022/2025 remain losing years, and the lot-rounded 2025–2026 result is close to flat. No live-deployment conclusion follows.

The 2025–2026 forward-validation set has been seen in prior research and is not a pristine holdout. No parameter or exit selection is made here.
