# EXNESS STANDARD COST-CALIBRATED APPROXIMATION

Bitstamp BTC/USD historical prices remain the market source. The synthetic view treats each Bid OHLC as a synthetic Bid and adds a constant $10 Ask. Neither view is a broker-native historical Exness backtest. Segments reset independently; no equity curve crosses missing candles.

Observed calibration: 5 real files, 541,647 ticks, $10/BTC spread; commission $0. The spread sensitivity is hypothetical outside the observed samples.

The cost-only view retains exact frozen fills and exits. The synthetic view replays pending triggers and exits on the appropriate quote side, with the audited conservative same-bar convention. Its reported one-spread equivalent is embedded in trade PnL and is never subtracted twice.

## Original frozen control

| Scope | Model | Trades | WR % | PF | Avg R | Net PnL | Cost R/trade | Worst segment DD % |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| all | old_0.05pct_per_side cost-only | 955 | 26.49 | 0.8474 | -0.1102 | -2636.44 | 0.1583 | 9.0682 |
| all | spread_$10 cost-only | 955 | 26.60 | 1.0144 | 0.0113 | 219.04 | 0.0368 | 4.3757 |
| all | $10 synthetic Bid/Ask | 980 | 24.69 | 0.9887 | -0.0065 | -203.28 | 0.0437 | 5.4453 |
| development | old_0.05pct_per_side cost-only | 639 | 26.92 | 0.8742 | -0.0893 | -1454.46 | 0.1480 | 4.8185 |
| development | spread_$10 cost-only | 639 | 27.07 | 1.0175 | 0.0138 | 181.67 | 0.0450 | 4.2677 |
| development | $10 synthetic Bid/Ask | 656 | 24.85 | 1.0025 | 0.0036 | 30.08 | 0.0531 | 4.6589 |
| forward-validation | old_0.05pct_per_side cost-only | 316 | 25.63 | 0.7929 | -0.1527 | -1181.98 | 0.1792 | 9.0682 |
| forward-validation | spread_$10 cost-only | 316 | 25.63 | 1.0078 | 0.0062 | 37.38 | 0.0203 | 4.3757 |
| forward-validation | $10 synthetic Bid/Ask | 324 | 24.38 | 0.9607 | -0.0271 | -233.36 | 0.0246 | 5.4453 |

## Fixed-spread cost-only sensitivity · all usable segments

| Spread USD/BTC | Trades | PF | Avg R | Net PnL | Spread cost | Worst segment DD % |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 955 | 1.0750 | 0.0481 | 1091.74 | 0.00 | 4.1366 |
| 5 | 955 | 1.0441 | 0.0297 | 655.39 | 436.35 | 4.2021 |
| 10 | 955 | 1.0144 | 0.0113 | 219.04 | 872.70 | 4.3757 |
| 15 | 955 | 0.9860 | -0.0071 | -217.31 | 1309.05 | 4.6169 |
| 20 | 955 | 0.9586 | -0.0255 | -653.66 | 1745.40 | 4.8583 |
| 30 | 955 | 0.9070 | -0.0623 | -1526.35 | 2618.10 | 5.3412 |
| 50 | 955 | 0.8149 | -0.1359 | -3271.75 | 4363.49 | 6.3083 |

## $10 spread bps at frozen trade entry

| Year | Trades | Median bps |
|---:|---:|---:|
| 2021 | 162 | 2.1251 |
| 2022 | 136 | 4.4852 |
| 2023 | 171 | 3.6539 |
| 2024 | 170 | 1.5675 |
| 2025 | 193 | 0.9822 |
| 2026 | 123 | 1.3944 |

## Quote-side mechanics

Frozen cost-only pending fills: 958; expiries: 267; completed trades: 955.
Synthetic $10 pending fills: 983; expiries: 234; completed trades: 980.
The change includes altered trigger timing, exits, account state, and risk-lock feedback; it is not a broker-native Exness execution result.

## Previously frozen Phase 4E candidates · secondary $10 cost-only view

| Candidate | Scope | Trades | PF | Avg R | Net PnL |
|---|---|---:|---:|---:|---:|
| ORIGINAL | all | 955 | 1.0144 | 0.0113 | 219.04 |
| ORIGINAL | development | 639 | 1.0175 | 0.0138 | 181.67 |
| ORIGINAL | forward-validation | 316 | 1.0078 | 0.0062 | 37.38 |
| C2 | all | 489 | 1.0968 | 0.0633 | 747.31 |
| C2 | development | 326 | 1.1200 | 0.0788 | 624.80 |
| C2 | forward-validation | 163 | 1.0487 | 0.0324 | 122.51 |
| C3 | all | 564 | 1.1014 | 0.0643 | 889.81 |
| C3 | development | 388 | 1.1634 | 0.1036 | 993.61 |
| C3 | forward-validation | 176 | 0.9615 | -0.0225 | -103.81 |
| minimum_adx=25 | all | 559 | 1.0698 | 0.0464 | 621.17 |
| minimum_adx=25 | development | 380 | 1.0833 | 0.0557 | 511.01 |
| minimum_adx=25 | forward-validation | 179 | 1.0398 | 0.0266 | 110.17 |

The old 0.05%-per-side research and all frozen strategy reports are preserved. No candidate is selected for deployment.
