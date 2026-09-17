# Frozen Setup A long-history cross-feed robustness

**FROZEN STRATEGY — NO OPTIMIZATION.** Setup A standalone, original Pine V2.2 rules, original pending order, structural stop, fixed 3R, both directions, zero-cost primary results. Phase 4K volatility gate is inactive.

**BITSTAMP PRE-2023 HISTORY IS CROSS-FEED EVIDENCE, NOT EXNESS BROKER-NATIVE PERFORMANCE.** The hypothetical fixed-spread sensitivities are not historical Exness prices. Commission is zero in those sensitivities.

Source 2021-01-01 00:00:00+00:00 to 2026-09-17 01:30:00+00:00; 200,084 M15 candles; 24 continuous segments, 21 usable and 3 excluded after calculated warm-up. Every segment resets indicators, strategy state, pending orders, positions and account; no gap is filled.

Year, period and pre-Exness membership use the completed signal candle's UTC year/time. Counts of signals and fills are attributed to that signal. Drawdown uses closed trades, starts from the audited account balance in each independent segment, and never compounds across gaps. Observed months count each UTC month containing usable candles once, including partial months.

## Yearly zero-cost results

| year | partial_year | signals | fills | observed_months | signals_per_observed_month | fills_per_observed_month | trades_per_observed_month | trades | long_trades | short_trades | wins | losses | win_rate_percent | profit_factor | average_r | net_pnl | median_r | max_losing_streak | worst_segment_dd_percent |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2021 | False | 303 | 195 | 12 | 25.2500 | 16.2500 | 16.1667 | 194 | 100 | 94 | 55 | 139 | 28.3505 | 1.1841 | 0.1338 | 645.1548 | -1.0000 | 9 | 2.9627 |
| 2022 | False | 309 | 192 | 12 | 25.7500 | 16.0000 | 16.0000 | 192 | 69 | 123 | 51 | 141 | 26.5625 | 1.0976 | 0.0682 | 330.4482 | -1.0000 | 19 | 4.6450 |
| 2023 | False | 393 | 246 | 12 | 32.7500 | 20.5000 | 20.5000 | 246 | 134 | 112 | 76 | 170 | 30.8943 | 1.3364 | 0.2163 | 1345.0233 | -0.9936 | 14 | 3.6697 |
| 2024 | False | 335 | 238 | 12 | 27.9167 | 19.8333 | 19.7500 | 237 | 134 | 103 | 82 | 155 | 34.5992 | 1.5925 | 0.3756 | 2370.4172 | -1.0000 | 11 | 2.9474 |
| 2025 | False | 351 | 231 | 12 | 29.2500 | 19.2500 | 19.2500 | 231 | 113 | 118 | 66 | 165 | 28.5714 | 1.1223 | 0.0862 | 484.9144 | -1.0000 | 15 | 4.8406 |
| 2026 | True | 253 | 154 | 9 | 28.1111 | 17.1111 | 17.1111 | 154 | 72 | 82 | 56 | 98 | 36.3636 | 1.7242 | 0.4472 | 1863.9996 | -0.9938 | 9 | 2.2223 |

## Period zero-cost results

| period | signals | fills | observed_months | signals_per_observed_month | fills_per_observed_month | trades_per_observed_month | trades | long_trades | short_trades | wins | losses | win_rate_percent | profit_factor | average_r | net_pnl | median_r | max_losing_streak | worst_segment_dd_percent |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2021–2022 | 612 | 387 | 24 | 25.5000 | 16.1250 | 16.0833 | 386 | 169 | 217 | 106 | 280 | 27.4611 | 1.1416 | 0.1012 | 975.6030 | -1.0000 | 19 | 4.6450 |
| 2023–2024 | 728 | 484 | 24 | 30.3333 | 20.1667 | 20.1250 | 483 | 268 | 215 | 158 | 325 | 32.7122 | 1.4645 | 0.2945 | 3715.4404 | -1.0000 | 14 | 3.6697 |
| 2025–2026 | 604 | 385 | 21 | 28.7619 | 18.3333 | 18.3333 | 385 | 185 | 200 | 122 | 263 | 31.6883 | 1.3593 | 0.2306 | 2348.9141 | -1.0000 | 15 | 4.8406 |
| Full 2021–2026 | 1944 | 1256 | 69 | 28.1739 | 18.2029 | 18.1739 | 1254 | 622 | 632 | 386 | 868 | 30.7815 | 1.3286 | 0.2154 | 7039.9575 | -1.0000 | 19 | 4.8406 |

## Direction results

| period | direction | trades | long_trades | short_trades | wins | losses | win_rate_percent | profit_factor | average_r | net_pnl | median_r | max_losing_streak |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Full | LONG | 622 | 622 | 0 | 195 | 427 | 31.3505 | 1.3576 | 0.2314 | 3805.8437 | -1.0000 | 13 |
| Full | SHORT | 632 | 0 | 632 | 191 | 441 | 30.2215 | 1.2999 | 0.1996 | 3234.1138 | -1.0000 | 18 |
| 2021 | LONG | 100 | 100 | 0 | 27 | 73 | 27.0000 | 1.1076 | 0.0803 | 198.8796 | -1.0000 | 8 |
| 2021 | SHORT | 94 | 0 | 94 | 28 | 66 | 29.7872 | 1.2693 | 0.1908 | 446.2752 | -1.0000 | 11 |
| 2022 | LONG | 69 | 69 | 0 | 17 | 52 | 24.6377 | 1.0027 | -0.0011 | 3.4633 | -1.0000 | 13 |
| 2022 | SHORT | 123 | 0 | 123 | 34 | 89 | 27.6423 | 1.1555 | 0.1071 | 326.9849 | -1.0000 | 9 |
| 2023 | LONG | 134 | 134 | 0 | 43 | 91 | 32.0896 | 1.4060 | 0.2553 | 889.2154 | -1.0000 | 8 |
| 2023 | SHORT | 112 | 0 | 112 | 33 | 79 | 29.4643 | 1.2521 | 0.1697 | 455.8078 | -0.9404 | 9 |
| 2024 | LONG | 134 | 134 | 0 | 47 | 87 | 35.0746 | 1.6245 | 0.3955 | 1416.9472 | -1.0000 | 6 |
| 2024 | SHORT | 103 | 0 | 103 | 35 | 68 | 33.9806 | 1.5505 | 0.3497 | 953.4700 | -1.0000 | 11 |
| 2025 | LONG | 113 | 113 | 0 | 34 | 79 | 30.0885 | 1.2091 | 0.1389 | 390.0573 | -1.0000 | 12 |
| 2025 | SHORT | 118 | 0 | 118 | 32 | 86 | 27.1186 | 1.0452 | 0.0357 | 94.8571 | -1.0000 | 18 |
| 2026 | LONG | 72 | 72 | 0 | 27 | 45 | 37.5000 | 1.7632 | 0.4591 | 907.2808 | -1.0000 | 8 |
| 2026 | SHORT | 82 | 0 | 82 | 29 | 53 | 35.3659 | 1.6906 | 0.4368 | 956.7188 | -0.9199 | 8 |

## MFE and MAE after actual fill

| period | trades | losing_trades | mean_mfe_r | median_mfe_r | mean_mae_r | median_mae_r | reached_0.5r_percent | losers_reached_0.5r_percent | reached_1r_percent | losers_reached_1r_percent | reached_1.5r_percent | reached_2r_percent | losers_reached_2r_percent | reached_3r_percent |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Full | 1254 | 868 | 1.5020 | 1.1752 | 0.8149 | 1.0000 | 68.6603 | 54.7235 | 53.1898 | 32.3733 | 45.2951 | 39.2344 | 12.2120 | 30.7815 |
| 2021 | 194 | 139 | 1.4910 | 1.1672 | 0.8407 | 1.0000 | 71.1340 | 59.7122 | 53.0928 | 34.5324 | 43.8144 | 38.6598 | 14.3885 | 28.3505 |
| 2022 | 192 | 141 | 1.4006 | 1.0402 | 0.8450 | 1.0000 | 63.5417 | 50.3546 | 51.5625 | 34.0426 | 41.1458 | 36.9792 | 14.1844 | 26.5625 |
| 2023 | 246 | 170 | 1.4973 | 1.1274 | 0.8119 | 1.0000 | 68.2927 | 54.1176 | 52.0325 | 30.5882 | 46.3415 | 39.0244 | 11.7647 | 30.8943 |
| 2024 | 237 | 155 | 1.5896 | 1.5199 | 0.8140 | 1.0000 | 69.1983 | 52.9032 | 55.6962 | 32.2581 | 50.2110 | 42.1941 | 11.6129 | 34.5992 |
| 2025 | 231 | 165 | 1.4535 | 1.0476 | 0.7912 | 1.0000 | 68.8312 | 56.3636 | 51.5152 | 32.1212 | 43.7229 | 37.6623 | 12.7273 | 28.5714 |
| 2026 | 154 | 98 | 1.5878 | 1.2764 | 0.7863 | 1.0000 | 71.4286 | 55.1020 | 55.8442 | 30.6122 | 45.4545 | 40.9091 | 7.1429 | 36.3636 |

M15 OHLC excursion uses the established conservative intrabar convention; unknown entry/exit-bar extremes are censored, so reach rates can be understated.

## Pre-Exness 2021-01-01 through 2023-11-08

| period | direction | trades | long_trades | short_trades | wins | losses | win_rate_percent | profit_factor | average_r | net_pnl | median_r | max_losing_streak |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Full pre-Exness | ALL | 610 | 286 | 324 | 177 | 433 | 29.0164 | 1.2258 | 0.1534 | 2358.0593 | -1.0000 | 19 |
| Full pre-Exness | LONG | 286 | 286 | 0 | 82 | 204 | 28.6713 | 1.1983 | 0.1345 | 993.1236 | -1.0000 | 13 |
| Full pre-Exness | SHORT | 324 | 0 | 324 | 95 | 229 | 29.3210 | 1.2512 | 0.1701 | 1364.9357 | -1.0000 | 11 |
| 2021 | ALL | 194 | 100 | 94 | 55 | 139 | 28.3505 | 1.1841 | 0.1338 | 645.1548 | -1.0000 | 9 |
| 2021 | LONG | 100 | 100 | 0 | 27 | 73 | 27.0000 | 1.1076 | 0.0803 | 198.8796 | -1.0000 | 8 |
| 2021 | SHORT | 94 | 0 | 94 | 28 | 66 | 29.7872 | 1.2693 | 0.1908 | 446.2752 | -1.0000 | 11 |
| 2022 | ALL | 192 | 69 | 123 | 51 | 141 | 26.5625 | 1.0976 | 0.0682 | 330.4482 | -1.0000 | 19 |
| 2022 | LONG | 69 | 69 | 0 | 17 | 52 | 24.6377 | 1.0027 | -0.0011 | 3.4633 | -1.0000 | 13 |
| 2022 | SHORT | 123 | 0 | 123 | 34 | 89 | 27.6423 | 1.1555 | 0.1071 | 326.9849 | -1.0000 | 9 |
| 2023 | ALL | 224 | 117 | 107 | 71 | 153 | 31.6964 | 1.3892 | 0.2434 | 1382.4563 | -0.9474 | 14 |
| 2023 | LONG | 117 | 117 | 0 | 38 | 79 | 32.4786 | 1.4206 | 0.2608 | 790.7807 | -1.0000 | 8 |
| 2023 | SHORT | 107 | 0 | 107 | 33 | 74 | 30.8411 | 1.3538 | 0.2243 | 591.6757 | -0.8969 | 9 |

## Signal-time regime descriptors, yearly medians

| year | trades | observed_btc_price_change_percent | median_atr_percent | median_recent_volatility_24h_percent | median_adx | median_h1_directional_slope_percent | median_ema_separation_atr |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2021 | 194 | 60.2732 | 0.5818 | 3.7073 | 24.8460 | 0.2546 | 0.9331 |
| 2022 | 192 | -64.3145 | 0.3733 | 2.6584 | 25.3024 | 0.1394 | 0.7635 |
| 2023 | 246 | 155.8455 | 0.2434 | 1.8684 | 26.4590 | 0.1115 | 0.8470 |
| 2024 | 237 | 119.9218 | 0.3178 | 2.3104 | 24.1760 | 0.1489 | 0.8009 |
| 2025 | 231 | -6.2640 | 0.2683 | 1.8498 | 23.9414 | 0.1042 | 0.7976 |
| 2026 | 154 | -12.6098 | 0.3110 | 2.0959 | 25.6687 | 0.1200 | 0.9865 |

Observed BTC price change uses the first and last available candle in each UTC year as market context; it is not a signal-time feature or a trading filter. Positive zero-cost Setup A years include large upward-price years (2021, 2023, 2024), a large downward-price year (2022), and smaller downward endpoint-change years (2025 and partial 2026). This does not prove performance in every intrayear regime.

## Stability description

Full-period zero-cost expectancy is positive, and every calendar year has positive zero-cost PnL. Both directions contribute over the full history. The weakest period is 2021–2022 and 2022 long average R is near zero; 2025 short is also weak. The two strongest calendar years, 2024 and partial 2026, contribute about 60% of summed segment PnL, so performance is uneven even though it does not depend on one year alone. The maximum observed losing streak is 19 completed losses within a segment (2022). These are descriptive cross-feed results, not broker-native proof or criteria chosen after the run.

## Existing Exness exact-common-timestamp overlap

Exness PF 1.1647, average R 0.1129; Bitstamp PF 1.4246, average R 0.2727. Exact signal match 71.98%; exact plus ±1 M15 near match 78.85%. The overlap comparison comes from unchanged Phase 4H artifacts, not the full Bitstamp run.

## HYPOTHETICAL COST SENSITIVITY

| period | spread_usd_per_btc | cost_label | trades | long_trades | short_trades | wins | losses | win_rate_percent | profit_factor | average_r | net_pnl |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Full 2021–2026 | 0.0000 | ZERO COST | 1254 | 622 | 632 | 386 | 868 | 30.7815 | 1.3286 | 0.2154 | 7039.9575 |
| Pre-Exness | 0.0000 | ZERO COST | 610 | 286 | 324 | 177 | 433 | 29.0164 | 1.2258 | 0.1534 | 2358.0593 |
| 2021 | 0.0000 | ZERO COST | 194 | 100 | 94 | 55 | 139 | 28.3505 | 1.1841 | 0.1338 | 645.1548 |
| 2022 | 0.0000 | ZERO COST | 192 | 69 | 123 | 51 | 141 | 26.5625 | 1.0976 | 0.0682 | 330.4482 |
| 2023 | 0.0000 | ZERO COST | 246 | 134 | 112 | 76 | 170 | 30.8943 | 1.3364 | 0.2163 | 1345.0233 |
| 2024 | 0.0000 | ZERO COST | 237 | 134 | 103 | 82 | 155 | 34.5992 | 1.5925 | 0.3756 | 2370.4172 |
| 2025 | 0.0000 | ZERO COST | 231 | 113 | 118 | 66 | 165 | 28.5714 | 1.1223 | 0.0862 | 484.9144 |
| 2026 | 0.0000 | ZERO COST | 154 | 72 | 82 | 56 | 98 | 36.3636 | 1.7242 | 0.4472 | 1863.9996 |
| Full 2021–2026 | 10.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 1254 | 622 | 632 | 386 | 868 | 30.7815 | 1.2356 | 0.1623 | 5327.3980 |
| Pre-Exness | 10.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 610 | 286 | 324 | 177 | 433 | 29.0164 | 1.1048 | 0.0774 | 1181.3473 |
| 2021 | 10.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 194 | 100 | 94 | 55 | 139 | 28.3505 | 1.1421 | 0.1066 | 511.5837 |
| 2022 | 10.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 192 | 69 | 123 | 51 | 141 | 26.5625 | 0.9748 | -0.0187 | -93.4757 |
| 2023 | 10.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 246 | 134 | 112 | 76 | 170 | 30.8943 | 1.1553 | 0.1118 | 689.3842 |
| 2024 | 10.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 237 | 134 | 103 | 82 | 155 | 34.5992 | 1.5182 | 0.3404 | 2149.6531 |
| 2025 | 10.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 231 | 113 | 118 | 66 | 165 | 28.5714 | 1.0843 | 0.0619 | 342.4946 |
| 2026 | 10.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 154 | 72 | 82 | 56 | 98 | 36.3636 | 1.6500 | 0.4150 | 1727.7580 |
| Full 2021–2026 | 20.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 1254 | 622 | 632 | 386 | 868 | 30.7815 | 1.1519 | 0.1092 | 3614.8385 |
| Pre-Exness | 20.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 610 | 286 | 324 | 177 | 433 | 29.0164 | 1.0004 | 0.0015 | 4.6354 |
| 2021 | 20.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 194 | 100 | 94 | 55 | 139 | 28.3505 | 1.1023 | 0.0793 | 378.0126 |
| 2022 | 20.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 192 | 69 | 123 | 51 | 141 | 26.5625 | 0.8713 | -0.1056 | -517.3996 |
| 2023 | 20.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 246 | 134 | 112 | 76 | 170 | 30.8943 | 1.0069 | 0.0074 | 33.7452 |
| 2024 | 20.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 237 | 134 | 103 | 82 | 155 | 34.5992 | 1.4491 | 0.3053 | 1928.8891 |
| 2025 | 20.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 231 | 113 | 118 | 66 | 165 | 28.5714 | 1.0481 | 0.0376 | 200.0748 |
| 2026 | 20.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 154 | 72 | 82 | 56 | 98 | 36.3636 | 1.5803 | 0.3827 | 1591.5163 |
| Full 2021–2026 | 30.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 1254 | 622 | 632 | 385 | 869 | 30.7018 | 1.0762 | 0.0561 | 1902.2789 |
| Pre-Exness | 30.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 610 | 286 | 324 | 176 | 434 | 28.8525 | 0.9093 | -0.0744 | -1172.0766 |
| 2021 | 30.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 194 | 100 | 94 | 55 | 139 | 28.3505 | 1.0645 | 0.0520 | 244.4414 |
| 2022 | 30.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 192 | 69 | 123 | 51 | 141 | 26.5625 | 0.7831 | -0.1925 | -941.3235 |
| 2023 | 30.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 246 | 134 | 112 | 75 | 171 | 30.4878 | 0.8832 | -0.0971 | -621.8938 |
| 2024 | 30.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 237 | 134 | 103 | 82 | 155 | 34.5992 | 1.3845 | 0.2701 | 1708.1251 |
| 2025 | 30.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 231 | 113 | 118 | 66 | 165 | 28.5714 | 1.0136 | 0.0133 | 57.6550 |
| 2026 | 30.0000 | HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD | 154 | 72 | 82 | 56 | 98 | 36.3636 | 1.5148 | 0.3505 | 1455.2747 |

## Source segments

| segment_id | start | end | candles | minimum_warmup_candles | first_search_time | usable | reason | signals | filled_orders | completed_trades | open_position_at_end | pending_at_end | engine_max_drawdown_percent | long_trades | short_trades | win_rate_percent | profit_factor | average_r | net_pnl |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bitstamp-S01 | 2021-01-01 00:00:00+00:00 | 2021-04-14 08:00:00+00:00 | 9921 | 821 | 2021-01-09 13:00:00+00:00 | True |  | 96.0000 | 56.0000 | 56.0000 | False | False | 1.7553 | 38.0000 | 18.0000 | 28.5714 | 1.1954 | 0.1429 | 196.1696 |
| bitstamp-S02 | 2021-04-14 09:30:00+00:00 | 2021-09-22 10:00:00+00:00 | 15459 | 823 | 2021-04-22 23:00:00+00:00 | True |  | 136.0000 | 95.0000 | 95.0000 | False | False | 2.2437 | 43.0000 | 52.0000 | 28.4211 | 1.1846 | 0.1362 | 318.6471 |
| bitstamp-S03 | 2021-09-22 10:30:00+00:00 | 2021-10-20 08:00:00+00:00 | 2679 | 823 | 2021-10-01 00:00:00+00:00 | True |  | 18.0000 | 12.0000 | 11.0000 | True | False | 1.2438 | 11.0000 | 0.0000 | 45.4545 | 2.4737 | 0.8207 | 226.6287 |
| bitstamp-S04 | 2021-10-20 09:00:00+00:00 | 2021-11-24 09:00:00+00:00 | 3361 | 821 | 2021-10-28 22:00:00+00:00 | True |  | 25.0000 | 16.0000 | 16.0000 | False | False | 2.9627 | 4.0000 | 12.0000 | 6.2500 | 0.1988 | -0.7500 | -296.2719 |
| bitstamp-S05 | 2021-11-24 10:00:00+00:00 | 2022-01-05 08:00:00+00:00 | 4025 | 821 | 2021-12-02 23:00:00+00:00 | True |  | 31.0000 | 18.0000 | 18.0000 | False | False | 0.9963 | 4.0000 | 14.0000 | 33.3333 | 1.4925 | 0.3333 | 149.0451 |
| bitstamp-S06 | 2022-01-05 10:15:00+00:00 | 2022-02-16 09:00:00+00:00 | 4028 | 824 | 2022-01-14 00:00:00+00:00 | True |  | 39.0000 | 28.0000 | 28.0000 | False | False | 4.6450 | 13.0000 | 15.0000 | 14.2857 | 0.5033 | -0.4286 | -297.3932 |
| bitstamp-S07 | 2022-02-16 09:45:00+00:00 | 2022-05-11 08:00:00+00:00 | 8058 | 822 | 2022-02-24 23:00:00+00:00 | True |  | 72.0000 | 43.0000 | 43.0000 | False | False | 1.5383 | 19.0000 | 24.0000 | 27.9070 | 1.1542 | 0.1145 | 119.5284 |
| bitstamp-S08 | 2022-05-11 09:00:00+00:00 | 2022-07-13 10:45:00+00:00 | 6056 | 821 | 2022-05-19 22:00:00+00:00 | True |  | 53.0000 | 30.0000 | 30.0000 | False | False | 2.4522 | 8.0000 | 22.0000 | 26.6667 | 1.0910 | 0.0699 | 49.6029 |
| bitstamp-S09 | 2022-07-13 12:15:00+00:00 | 2022-07-27 08:00:00+00:00 | 1328 | 824 | 2022-07-22 02:00:00+00:00 | True |  | 5.0000 | 5.0000 | 5.0000 | False | False | 1.2438 | 3.0000 | 2.0000 | 0.0000 | 0.0000 | -1.0000 | -124.3766 |
| bitstamp-S10 | 2022-07-27 09:00:00+00:00 | 2022-08-10 08:00:00+00:00 | 1341 | 821 | 2022-08-04 22:00:00+00:00 | True |  | 5.0000 | 4.0000 | 4.0000 | False | False | 0.2500 | 4.0000 | 0.0000 | 50.0000 | 2.9777 | 1.0000 | 99.8731 |
| bitstamp-S11 | 2022-08-10 08:30:00+00:00 | 2022-12-07 08:00:00+00:00 | 11423 | 823 | 2022-08-18 22:00:00+00:00 | True |  | 120.0000 | 71.0000 | 71.0000 | False | False | 2.2025 | 22.0000 | 49.0000 | 32.3944 | 1.4887 | 0.3090 | 556.1204 |
| bitstamp-S12 | 2022-12-07 08:30:00+00:00 | 2023-03-23 10:00:00+00:00 | 10183 | 823 | 2022-12-15 22:00:00+00:00 | True |  | 116.0000 | 72.0000 | 72.0000 | False | False | 3.6697 | 42.0000 | 30.0000 | 27.7778 | 1.1070 | 0.0731 | 126.5433 |
| bitstamp-S13 | 2023-03-23 11:45:00+00:00 | 2023-06-28 09:00:00+00:00 | 9302 | 822 | 2023-04-01 01:00:00+00:00 | True |  | 107.0000 | 66.0000 | 66.0000 | False | False | 2.8683 | 30.0000 | 36.0000 | 30.3030 | 1.3905 | 0.2533 | 419.6282 |
| bitstamp-S14 | 2023-06-28 09:45:00+00:00 | 2023-07-03 10:30:00+00:00 | 484 | 822 | 2023-07-06 23:00:00+00:00 | False | insufficient confirmed-H1 and M15 warm-up | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan |
| bitstamp-S15 | 2023-07-03 11:00:00+00:00 | 2023-07-03 11:00:00+00:00 | 1 | 821 | 2023-07-12 00:00:00+00:00 | False | insufficient confirmed-H1 and M15 warm-up | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan |
| bitstamp-S16 | 2023-07-03 13:15:00+00:00 | 2024-02-18 16:30:00+00:00 | 22094 | 824 | 2023-07-12 03:00:00+00:00 | True |  | 239.0000 | 156.0000 | 156.0000 | False | False | 2.3923 | 88.0000 | 68.0000 | 33.3333 | 1.4950 | 0.3047 | 1244.4960 |
| bitstamp-S17 | 2024-02-18 17:30:00+00:00 | 2024-03-29 10:15:00+00:00 | 3812 | 823 | 2024-02-27 07:00:00+00:00 | True |  | 35.0000 | 25.0000 | 25.0000 | False | False | 0.9963 | 18.0000 | 7.0000 | 36.0000 | 1.6728 | 0.4400 | 275.7129 |
| bitstamp-S18 | 2024-03-29 11:00:00+00:00 | 2024-04-07 08:00:00+00:00 | 853 | 821 | 2024-04-07 00:00:00+00:00 | True |  | 1.0000 | 1.0000 | 0.0000 | True | False | 0.0000 | 0.0000 | 0.0000 | 0.0000 | nan | 0.0000 | 0.0000 |
| bitstamp-S19 | 2024-04-07 09:00:00+00:00 | 2024-12-07 01:15:00+00:00 | 23394 | 821 | 2024-04-15 22:00:00+00:00 | True |  | 234.0000 | 167.0000 | 167.0000 | False | False | 2.9474 | 90.0000 | 77.0000 | 34.7305 | 1.5936 | 0.3735 | 1665.6852 |
| bitstamp-S20 | 2024-12-07 04:30:00+00:00 | 2024-12-11 10:00:00+00:00 | 407 | 823 | 2024-12-15 18:00:00+00:00 | False | insufficient confirmed-H1 and M15 warm-up | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan | nan |
| bitstamp-S21 | 2024-12-11 10:45:00+00:00 | 2025-03-23 08:30:00+00:00 | 9784 | 822 | 2024-12-20 00:00:00+00:00 | True |  | 89.0000 | 60.0000 | 60.0000 | False | False | 3.6764 | 18.0000 | 42.0000 | 28.3333 | 1.1646 | 0.1202 | 175.9930 |
| bitstamp-S22 | 2025-03-23 10:00:00+00:00 | 2025-10-17 12:15:00+00:00 | 19978 | 821 | 2025-03-31 23:00:00+00:00 | True |  | 195.0000 | 129.0000 | 129.0000 | False | False | 4.8406 | 82.0000 | 47.0000 | 29.4574 | 1.1536 | 0.1041 | 330.3707 |
| bitstamp-S23 | 2025-10-17 13:00:00+00:00 | 2026-08-05 09:00:00+00:00 | 28017 | 821 | 2025-10-26 02:00:00+00:00 | True |  | 300.0000 | 186.0000 | 186.0000 | False | False | 2.5456 | 74.0000 | 112.0000 | 34.9462 | 1.6079 | 0.3776 | 1894.9354 |
| bitstamp-S24 | 2026-08-05 09:45:00+00:00 | 2026-09-17 01:30:00+00:00 | 4096 | 822 | 2026-08-13 23:00:00+00:00 | True |  | 28.0000 | 16.0000 | 16.0000 | False | False | 2.2223 | 11.0000 | 5.0000 | 18.7500 | 0.7107 | -0.2254 | -90.9808 |
