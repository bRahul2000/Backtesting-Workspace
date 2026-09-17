# Frozen Pine V2.2.0 Setup A standalone validation

FROZEN ORIGINAL V2.2 RULES · NO OPTIMIZATION. Setup B is disabled in this run. The strategy, 3R exit, pending entry, and generic execution code are unchanged.

Exness Bid M15 source; each contiguous segment starts a fresh account, indicator state, and pending/position state. Pooled trade sums are not a continuous compounded equity curve.

Zero cost isolates the Bid feed. Historical M15 spread is a bar-minimum lower-bound descriptor, not a tick-exact execution cost. Fixed spreads are separate sensitivity views. Commission is $0.

Theoretical completed trades and 0.01-lot executable counts are reported separately. Post-hoc lot rounding does not rerun strategy permissions or the account path; native PnL tables use the audited theoretical sizing convention for Setup B comparability.

Completed trades: 672 theoretical, 672 at/above 0.01 lot, 0 below minimum.

Filled positions including one open final position: 673 theoretical, 673 at/above 0.01 lot, 0 below minimum.

Rounding down retains 91.13% of theoretical quantity on average. A trade-by-trade zero-cost PnL rescale gives $1,881.96; this is a sizing audit, not an account-path rerun, so it is excluded from strategy comparison metrics.

## Pine risk and permission impact

The original daily/monthly and session permissions are active. Risk-block counts are diagnostic candles, not cancelled filled positions.

- Blocked: Daily consecutive closed-loss limit reached.: 22
- Blocked: Maximum trades per UTC day reached.: 534
- Blocked: UTC session: 43627
- Blocked: active position or pending order: 8855

Pending cancellation reasons: {'UTC trading session ended.': 8}.

## Native and same-period results

| feed | scope | cost_view | signals | orders | fills | expired | cancelled | trades | long_trades | short_trades | wins | losses | win_rate_percent | profit_factor | average_r | net_pnl | median_r | max_losing_streak | worst_segment_dd_percent |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| exness_native | full_native | zero_cost | 1014 | 1014 | 673 | 333 | 8 | 672 | 362 | 310 | 188 | 484 | 27.9762 | 1.1661 | 0.1147 | 2003.2551 | -1.0000 | 16 | 5.5828 |
| exness_native | full_native | bar_minimum_spread_lower_bound | 1014 | 1014 | 673 | 333 | 8 | 672 | 362 | 310 | 188 | 484 | 27.9762 | 1.0655 | 0.0470 | 844.5385 | -1.0342 | 16 | 6.4057 |
| exness_native | full_native | fixed_spread_$10 | 1014 | 1014 | 673 | 333 | 8 | 672 | 362 | 310 | 188 | 484 | 27.9762 | 1.1218 | 0.0861 | 1511.6022 | -1.0155 | 16 | 5.8786 |
| exness_native | full_native | fixed_spread_$15 | 1014 | 1014 | 673 | 333 | 8 | 672 | 362 | 310 | 188 | 484 | 27.9762 | 1.1006 | 0.0719 | 1265.7758 | -1.0234 | 16 | 6.0274 |
| exness_native | full_native | fixed_spread_$20 | 1014 | 1014 | 673 | 333 | 8 | 672 | 362 | 310 | 188 | 484 | 27.9762 | 1.0799 | 0.0576 | 1019.9494 | -1.0314 | 16 | 6.1937 |
| exness_native | full_native | fixed_spread_$30 | 1014 | 1014 | 673 | 333 | 8 | 672 | 362 | 310 | 188 | 484 | 27.9762 | 1.0403 | 0.0290 | 528.2965 | -1.0479 | 16 | 6.8316 |
| exness_native | earlier_2023_2024 | zero_cost | 399 | 399 | 258 | 134 | 7 | 258 | 160 | 98 | 77 | 181 | 29.8450 | 1.2760 | 0.1882 | 1282.7307 | -1.0000 | 11 | 3.9474 |
| exness_native | earlier_2023_2024 | fixed_spread_$10 | 399 | 399 | 258 | 134 | 7 | 258 | 160 | 98 | 77 | 181 | 29.8450 | 1.2221 | 0.1557 | 1066.7444 | -1.0211 | 11 | 4.2699 |
| exness_native | later_2025_2026 | zero_cost | 615 | 615 | 415 | 199 | 1 | 414 | 202 | 212 | 111 | 303 | 26.8116 | 1.0972 | 0.0689 | 720.5244 | -1.0000 | 16 | 5.5828 |
| exness_native | later_2025_2026 | fixed_spread_$10 | 615 | 615 | 415 | 199 | 1 | 414 | 202 | 212 | 111 | 303 | 26.8116 | 1.0585 | 0.0428 | 444.8578 | -1.0138 | 16 | 5.8786 |
| exness_overlap | exact_common_timestamps | zero_cost | 960 | 960 | 638 | 315 | 7 | 636 | 334 | 302 | 178 | 458 | 27.9874 | 1.1647 | 0.1129 | 1867.6890 | -1.0000 | 16 | nan |
| bitstamp_overlap | exact_common_timestamps | zero_cost | 944 | 944 | 621 | 317 | 6 | 619 | 318 | 301 | 201 | 418 | 32.4717 | 1.4246 | 0.2727 | 4450.3011 | -1.0000 | 15 | nan |

## Yearly results

| year | partial_year | cost_view | trades | long_trades | short_trades | wins | losses | win_rate_percent | profit_factor | average_r | net_pnl |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2023 | True | zero_cost | 19 | 17 | 2 | 3 | 16 | 15.7895 | 0.5583 | -0.3684 | -174.7947 |
| 2023 | True | fixed_spread_$10 | 19 | 17 | 2 | 3 | 16 | 15.7895 | 0.5230 | -0.4179 | -198.0234 |
| 2024 | False | zero_cost | 239 | 143 | 96 | 74 | 165 | 30.9623 | 1.3428 | 0.2324 | 1457.5254 |
| 2024 | False | fixed_spread_$10 | 239 | 143 | 96 | 74 | 165 | 30.9623 | 1.2883 | 0.2013 | 1264.7679 |
| 2025 | False | zero_cost | 251 | 123 | 128 | 60 | 191 | 23.9044 | 0.9226 | -0.0551 | -353.5992 |
| 2025 | False | fixed_spread_$10 | 251 | 123 | 128 | 60 | 191 | 23.9044 | 0.8943 | -0.0778 | -494.1633 |
| 2026 | True | zero_cost | 163 | 79 | 84 | 51 | 112 | 31.2883 | 1.3778 | 0.2598 | 1074.1236 |
| 2026 | True | fixed_spread_$10 | 163 | 79 | 84 | 51 | 112 | 31.2883 | 1.3200 | 0.2285 | 939.0211 |

## Long and short

| direction | cost_view | trades | long_trades | short_trades | wins | losses | win_rate_percent | profit_factor | average_r | net_pnl |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| LONG | zero_cost | 362 | 362 | 0 | 104 | 258 | 28.7293 | 1.2051 | 0.1389 | 1321.9396 |
| LONG | fixed_spread_$10 | 362 | 362 | 0 | 104 | 258 | 28.7293 | 1.1576 | 0.1093 | 1046.2022 |
| SHORT | zero_cost | 310 | 0 | 310 | 84 | 226 | 27.0968 | 1.1213 | 0.0864 | 681.3155 |
| SHORT | fixed_spread_$10 | 310 | 0 | 310 | 84 | 226 | 27.0968 | 1.0806 | 0.0591 | 465.4001 |

Signal overlap: {'exness_signals': 960, 'bitstamp_signals': 944, 'exact_matches': 691, 'near_matches': 66, 'opposite': 0, 'exness_only': 203, 'bitstamp_only': 187, 'exact_percent_of_exness': 71.97916666666667, 'near_percent_of_exness': 6.875000000000001, 'opposite_percent_of_exness': 0.0, 'exness_only_percent': 21.145833333333332, 'bitstamp_only_percent': 19.809322033898304, 'exact_signal_match_rate': 0.7197916666666667, 'exact_plus_near_match_rate': 0.7885416666666667}
