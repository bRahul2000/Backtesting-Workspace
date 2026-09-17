# Frozen Setup A regime and failure diagnostics

**DIAGNOSTIC ONLY — NO OPTIMIZATION.** Real Exness BTCUSDm Bid M15, original V2.2 Setup A standalone. Every source gap resets indicators and the account; no OHLC is filled. The saved zero-cost and $10 baselines were verified exactly before analysis.

Zero-cost baseline: 672 trades; PF 1.1661; average R 0.1147; net $2,003.26; worst segment DD 5.58%.

Signal descriptors use only the completed signal candle and earlier observations. ATR and H1 slope percentiles use trailing histories, including the signal's current known observation. Twenty-four-hour volatility, efficiency and chop use completed M15 history only. These variables never change entry decisions.

MFE/MAE begin after fill. With unknown M15 intrabar order, entry and exit bar extremes are conservatively censored; recorded reach rates can understate the true path. No exit is changed.

## Entry quality by year

| year | signals | pending_orders | fills | completed_trades | fill_rate_percent | win_rate_percent | profit_factor | average_r | median_stop_distance_atr | median_mfe_r | median_mae_r | median_atr_percent | median_adx | median_h1_slope_percent | median_recent_volatility_24h_percent | median_directional_efficiency_24h | never_reached_0.5r_percent | losers_reached_1r_percent |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2023 | 31 | 31 | 19 | 19 | 61.290 | 15.789 | 0.558 | -0.368 | 1.593 | 1.291 | 1.000 | 0.332 | 27.732 | 0.105 | 2.085 | 0.137 | 36.842 | 43.750 |
| 2024 | 368 | 368 | 239 | 239 | 64.946 | 30.962 | 1.343 | 0.232 | 1.516 | 1.066 | 1.000 | 0.360 | 24.329 | 0.144 | 2.332 | 0.107 | 35.983 | 29.697 |
| 2025 | 362 | 362 | 252 | 251 | 69.613 | 23.904 | 0.923 | -0.055 | 1.572 | 0.859 | 1.000 | 0.294 | 24.200 | 0.107 | 1.873 | 0.096 | 39.044 | 30.366 |
| 2026 | 253 | 253 | 163 | 163 | 64.427 | 31.288 | 1.378 | 0.260 | 1.558 | 1.250 | 1.000 | 0.332 | 25.822 | 0.112 | 2.046 | 0.126 | 28.221 | 36.607 |

## Excursions and losing-trade reversals

| year | direction | trades | median_mfe_r | median_mae_r | never_reached_0.5r_percent | losers_reached_0.5r_percent | losers_reached_1r_percent | losers_reached_1.5r_percent | losers_reached_2r_percent |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| All | All | 672 | 1.040 | 1.000 | 35.268 | 51.033 | 32.025 | 20.661 | 11.157 |
| 2023 | All | 19 | 1.291 | 1.000 | 36.842 | 56.250 | 43.750 | 31.250 | 12.500 |
| 2024 | All | 239 | 1.066 | 1.000 | 35.983 | 47.879 | 29.697 | 19.394 | 11.515 |
| 2025 | All | 251 | 0.859 | 1.000 | 39.044 | 48.691 | 30.366 | 21.990 | 12.042 |
| 2026 | All | 163 | 1.250 | 1.000 | 28.221 | 58.929 | 36.607 | 18.750 | 8.929 |

## Long and short by year

| year | direction | trades | win_rate_percent | profit_factor | average_r | net_pnl |
| --- | --- | --- | --- | --- | --- | --- |
| 2023 | LONG | 17 | 17.647 | 0.638 | -0.294 | -125.482 |
| 2023 | SHORT | 2 | 0.000 | 0.000 | -1.000 | -49.313 |
| 2024 | LONG | 143 | 32.867 | 1.469 | 0.307 | 1163.084 |
| 2024 | SHORT | 96 | 28.125 | 1.166 | 0.121 | 294.441 |
| 2025 | LONG | 123 | 23.577 | 0.885 | -0.081 | -257.216 |
| 2025 | SHORT | 128 | 24.219 | 0.959 | -0.030 | -96.383 |
| 2026 | LONG | 79 | 31.646 | 1.394 | 0.270 | 541.554 |
| 2026 | SHORT | 84 | 30.952 | 1.363 | 0.250 | 532.570 |

## Cost resilience by year

| year | spread_usd_per_btc | trades | profit_factor | average_r | net_pnl |
| --- | --- | --- | --- | --- | --- |
| 2023 | 0.000 | 19 | 0.558 | -0.368 | -174.795 |
| 2024 | 0.000 | 239 | 1.343 | 0.232 | 1457.525 |
| 2025 | 0.000 | 251 | 0.923 | -0.055 | -353.599 |
| 2026 | 0.000 | 163 | 1.378 | 0.260 | 1074.124 |
| 2023 | 10.000 | 19 | 0.523 | -0.418 | -198.023 |
| 2024 | 10.000 | 239 | 1.288 | 0.201 | 1264.768 |
| 2025 | 10.000 | 251 | 0.894 | -0.078 | -494.163 |
| 2026 | 10.000 | 163 | 1.320 | 0.228 | 939.021 |
| 2023 | 15.000 | 19 | 0.507 | -0.443 | -209.638 |
| 2024 | 15.000 | 239 | 1.262 | 0.186 | 1168.389 |
| 2025 | 15.000 | 251 | 0.881 | -0.089 | -564.445 |
| 2026 | 15.000 | 163 | 1.292 | 0.213 | 871.470 |
| 2023 | 20.000 | 19 | 0.491 | -0.467 | -221.252 |
| 2024 | 20.000 | 239 | 1.237 | 0.170 | 1072.010 |
| 2025 | 20.000 | 251 | 0.867 | -0.100 | -634.728 |
| 2026 | 20.000 | 163 | 1.266 | 0.197 | 803.919 |
| 2023 | 30.000 | 19 | 0.461 | -0.517 | -244.481 |
| 2024 | 30.000 | 239 | 1.189 | 0.139 | 879.253 |
| 2025 | 30.000 | 251 | 0.841 | -0.123 | -775.292 |
| 2026 | 30.000 | 163 | 1.214 | 0.166 | 668.816 |

Fixed spreads are sensitivities on identical completed trades. They are not tick-exact historical execution costs.

## Signal feed sensitivity by year

| year | exness_signals | bitstamp_signals | exact_matches | near_matches | exness_only | bitstamp_only | opposite | exact_match_rate_percent | exact_plus_near_rate_percent |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2023 | 31 | 30 | 17 | 3 | 11 | 10 | 0 | 54.839 | 64.516 |
| 2024 | 334 | 319 | 228 | 26 | 80 | 65 | 0 | 68.263 | 76.048 |
| 2025 | 350 | 342 | 254 | 24 | 72 | 64 | 0 | 72.571 | 79.429 |
| 2026 | 245 | 253 | 192 | 13 | 40 | 48 | 0 | 78.367 | 83.673 |

## Visible 2025 losing-trade descriptor differences

Comparator: all 2024+2026 completed trades. Median shift is scaled by comparator IQR; these are descriptive associations, not causes or filter proposals.

| descriptor | losing_2025_count | losing_2025_median | other_years_count | other_years_median | median_shift_over_reference_iqr |
| --- | --- | --- | --- | --- | --- |
| atr_percent | 191 | 0.299 | 402 | 0.348 | 0.252 |
| recent_volatility_24h_percent | 191 | 1.930 | 402 | 2.193 | 0.205 |

Profiles, time groups, buckets and every trade are in the accompanying CSV files. Low-sample groups (<20 trades) are flagged. No clustering was added because it would not improve this causal diagnostic audit.
