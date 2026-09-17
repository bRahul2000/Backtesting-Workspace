# Frozen Pine V2.2 Setup A+B priority baseline

Source: 2023-11-09 00:00:00+00:00 through 2026-09-17 17:15:00+00:00; processed dataset SHA-256 `3abad99b42813b675b19a2016aca9ee79154262fa8e00bc88410dcb15fa9a2e9`.

Exness BTCUSDm Bid M15; six source gaps remain unfilled. Each usable continuous segment resets account, indicators, pending order, position, and risk permissions. A long, A short, B long, B short priority follows Pine section 43. No standalone setup, parameter, or generic execution code changed.

Zero cost is the primary feed comparison. Fixed $10 and $20 spreads are separate completed-trade sensitivities, not tick-exact execution. Commission is zero. Drawdowns are worst within a segment, never a compounded curve across gaps.

## Standalone versus combined

| setup | cost_view | trades | profit_factor | average_r | net_pnl | worst_segment_dd_percent |
| --- | --- | --- | --- | --- | --- | --- |
| A | zero_cost | 672 | 1.1661 | 0.1147 | 2003.2551 | 5.5828 |
| A | fixed_spread_$10 | 672 | 1.1218 | 0.0861 | 1511.6022 | 5.8786 |
| A | fixed_spread_$20 | 672 | 1.0799 | 0.0576 | 1019.9494 | 6.1937 |
| B | zero_cost | 498 | 1.0071 | 0.0081 | 65.5911 | 6.1013 |
| B | fixed_spread_$10 | 498 | 0.9753 | -0.0159 | -233.7540 | 6.7380 |
| B | fixed_spread_$20 | 498 | 0.9449 | -0.0400 | -533.0990 | 7.3755 |
| A+B | zero_cost | 787 | 1.1188 | 0.0805 | 1702.0133 | 9.7436 |
| A+B | fixed_spread_$10 | 787 | 1.0775 | 0.0527 | 1141.9932 | 10.4990 |
| A+B | fixed_spread_$20 | 787 | 1.0385 | 0.0248 | 581.9732 | 11.3032 |

## Combined trade attribution

| setup | cost_view | trades | long_trades | short_trades | wins | losses | win_rate_percent | profit_factor | average_r | net_pnl |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | zero_cost | 609 | 326 | 283 | 173 | 436 | 28.4072 | 1.1860 | 0.1277 | 2022.3131 |
| B | zero_cost | 178 | 98 | 80 | 41 | 137 | 23.0337 | 0.9074 | -0.0810 | -320.2998 |
| A | fixed_spread_$10 | 609 | 326 | 283 | 173 | 436 | 28.4072 | 1.1411 | 0.0992 | 1578.0567 |
| B | fixed_spread_$10 | 178 | 98 | 80 | 41 | 137 | 23.0337 | 0.8770 | -0.1065 | -436.0635 |
| A | fixed_spread_$20 | 609 | 326 | 283 | 173 | 436 | 28.4072 | 1.0986 | 0.0707 | 1133.8003 |
| B | fixed_spread_$20 | 178 | 98 | 80 | 41 | 137 | 23.0337 | 0.8480 | -0.1320 | -551.8271 |

## Marginal B contribution

{'combined_minus_a_pnl': -301.24178248602766, 'combined_minus_a_sum_r': -13.7095644574324, 'combined_minus_a_average_r': -0.034176164673034706, 'combined_b_attributed_pnl': -320.29979298585033, 'combined_b_attributed_sum_r': -14.421498236534468}

Combined B trade attribution is not the same as combined-minus-A marginal change: A+B changes which trades can occur and the account path.

## B displacement

Same-candle B signals suppressed by A priority: 177.
B candidates blocked by A pending/position: 1 / 472.
Frozen standalone B completed trades among those blocked candidates: 183.
Of those, 0 coincide with A pending and 183 with an A position.

## Yearly

| year | partial_year | cost_view | trades | long_trades | short_trades | wins | losses | win_rate_percent | profit_factor | average_r | net_pnl | worst_segment_dd_percent |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2023 | True | zero_cost | 23 | 21 | 2 | 5 | 18 | 21.7391 | 0.8285 | -0.1304 | -76.6673 | 1.7369 |
| 2023 | True | fixed_spread_$10 | 23 | 21 | 2 | 5 | 18 | 21.7391 | 0.7795 | -0.1770 | -103.2263 | 1.8436 |
| 2023 | True | fixed_spread_$20 | 23 | 21 | 2 | 5 | 18 | 21.7391 | 0.7348 | -0.2235 | -129.7853 | 1.9503 |
| 2024 | False | zero_cost | 277 | 166 | 111 | 83 | 194 | 29.9639 | 1.2782 | 0.1933 | 1403.6844 | 4.4306 |
| 2024 | False | fixed_spread_$10 | 277 | 166 | 111 | 83 | 194 | 29.9639 | 1.2274 | 0.1627 | 1182.8412 | 4.7894 |
| 2024 | False | fixed_spread_$20 | 277 | 166 | 111 | 83 | 194 | 29.9639 | 1.1796 | 0.1321 | 961.9980 | 5.1505 |
| 2025 | False | zero_cost | 294 | 146 | 148 | 65 | 229 | 22.1088 | 0.8362 | -0.1270 | -892.2830 | 9.7436 |
| 2025 | False | fixed_spread_$10 | 294 | 146 | 148 | 65 | 229 | 22.1088 | 0.8110 | -0.1494 | -1052.9089 | 10.4990 |
| 2025 | False | fixed_spread_$20 | 294 | 146 | 148 | 65 | 229 | 22.1088 | 0.7868 | -0.1718 | -1213.5347 | 11.3032 |
| 2026 | True | zero_cost | 193 | 91 | 102 | 61 | 132 | 31.6062 | 1.3739 | 0.2598 | 1267.2792 | 3.7252 |
| 2026 | True | fixed_spread_$10 | 193 | 91 | 102 | 61 | 132 | 31.6062 | 1.3194 | 0.2299 | 1115.2872 | 4.0032 |
| 2026 | True | fixed_spread_$20 | 193 | 91 | 102 | 61 | 132 | 31.6062 | 1.2680 | 0.2000 | 963.2951 | 4.2891 |

## Earlier and later

| period | cost_view | trades | long_trades | short_trades | wins | losses | win_rate_percent | profit_factor | average_r | net_pnl | worst_segment_dd_percent |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| earlier_2023_2024 | zero_cost | 300 | 187 | 113 | 88 | 212 | 29.3333 | 1.2416 | 0.1685 | 1327.0171 | 4.4306 |
| earlier_2023_2024 | fixed_spread_$10 | 300 | 187 | 113 | 88 | 212 | 29.3333 | 1.1905 | 0.1367 | 1079.6149 | 4.7894 |
| earlier_2023_2024 | fixed_spread_$20 | 300 | 187 | 113 | 88 | 212 | 29.3333 | 1.1424 | 0.1049 | 832.2127 | 5.1505 |
| later_2025_2026 | zero_cost | 487 | 237 | 250 | 126 | 361 | 25.8727 | 1.0424 | 0.0263 | 374.9962 | 9.7436 |
| later_2025_2026 | fixed_spread_$10 | 487 | 237 | 250 | 126 | 361 | 25.8727 | 1.0069 | 0.0009 | 62.3783 | 10.4990 |
| later_2025_2026 | fixed_spread_$20 | 487 | 237 | 250 | 126 | 361 | 25.8727 | 0.9731 | -0.0245 | -250.2396 | 11.3032 |
