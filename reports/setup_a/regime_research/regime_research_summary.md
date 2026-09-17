# Setup A low-volatility regime robustness

**REGIME RESEARCH — NOT ACTIVE STRATEGY.** Frozen Pine V2.2 Setup A standalone, original stop/pending/3R, both directions, zero commission. No active strategy or generic engine code changed.

Development: 2023-11-09 through 2024-12-31. Validation set for Phase 4K: 2025-01-01 through latest 2026. The latter was observed in earlier phases and is not an untouched holdout.

Threshold percentiles were computed from all original Setup A development signals, using causal signal-time ATR% and recent 24-hour volatility. A signal passes only when its value is strictly above the stored development threshold. Each candidate is a research-only strategy wrapper that suppresses a signal after frozen Setup A has evaluated it. The audited engine then handles positions, pending orders, risk locks and sizing without alteration. Continuous source segments reset indicators and accounts; no gap is filled.

## Development one-factor results

| feature | percentile | threshold | trades | retention_percent | profit_factor | average_r | net_pnl | worst_segment_dd_percent | average_mfe_r | never_reached_0.5r_percent | low_sample |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| control | 0 | nan | 258 | 100.0000 | 1.2760 | 0.1882 | 1282.7307 | 3.9474 | 1.4416 | 36.0465 | False |
| atr_percent | 10 | 0.2077 | 236 | 91.4729 | 1.2684 | 0.1858 | 1144.3449 | 4.2054 | 1.4464 | 35.1695 | False |
| atr_percent | 20 | 0.2644 | 212 | 82.1705 | 1.3608 | 0.2453 | 1363.1379 | 3.2415 | 1.5165 | 33.0189 | False |
| atr_percent | 30 | 0.2873 | 191 | 74.0310 | 1.2771 | 0.1937 | 949.9453 | 4.6767 | 1.4784 | 33.5079 | False |
| atr_percent | 40 | 0.3253 | 161 | 62.4031 | 1.2724 | 0.1925 | 780.8426 | 5.1456 | 1.4843 | 33.5404 | False |
| recent_volatility_24h_percent | 10 | 1.4446 | 235 | 91.0853 | 1.2484 | 0.1723 | 1059.6427 | 3.2451 | 1.4450 | 35.3191 | False |
| recent_volatility_24h_percent | 20 | 1.7177 | 204 | 79.0698 | 1.2207 | 0.1547 | 818.4674 | 3.9618 | 1.4314 | 34.8039 | False |
| recent_volatility_24h_percent | 30 | 1.8976 | 182 | 70.5426 | 1.1044 | 0.0769 | 350.0934 | 5.3898 | 1.4327 | 34.0659 | False |
| recent_volatility_24h_percent | 40 | 2.1068 | 149 | 57.7519 | 1.1765 | 0.1275 | 476.7952 | 4.4306 | 1.4871 | 32.2148 | True |

## Threshold stability

| feature | percentile | candidate_id | pf_improves | average_r_improves | mfe_improves | fewer_never_reaching_half_r | adequate_sample | neighboring_pf_and_r_improvement | possible_overfit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| atr_percent | 10 | atr_percent_p10 | False | False | True | True | True | True | False |
| atr_percent | 20 | atr_percent_p20 | True | True | True | True | True | True | False |
| atr_percent | 30 | atr_percent_p30 | True | True | True | True | True | True | False |
| atr_percent | 40 | atr_percent_p40 | False | True | True | True | True | True | False |
| recent_volatility_24h_percent | 10 | recent_volatility_24h_percent_p10 | False | False | True | True | True | False | False |
| recent_volatility_24h_percent | 20 | recent_volatility_24h_percent_p20 | False | False | False | True | True | False | False |
| recent_volatility_24h_percent | 30 | recent_volatility_24h_percent_p30 | False | False | False | True | True | False | False |
| recent_volatility_24h_percent | 40 | recent_volatility_24h_percent_p40 | False | False | True | True | False | False | False |

ATR% p20–p40 had adjacent aggregate PF and average-R values above control, but the meaningful gain was concentrated at p20. Drawdown worsened at p30/p40 and the long direction deteriorated there. The result is overfit-like rather than a convincing broad plateau. The 24-hour volatility thresholds did not show adjacent PF/average-R improvement. The p40 24-hour setting also fell below 150 development trades.

## Candidate freeze

SHA-256: `5729d9ea26d2493da0afdc55d3a8f57eb2be545c3ec67e07626ba190487e7ac9`

| candidate_id | rules |
| --- | --- |
| C1_ATR_P20 | [{"feature": "atr_percent", "percentile": 20, "threshold": 0.2643797440641696}] |

C1 was frozen from development because p20 and p30 met the neighboring aggregate criterion, p20 retained 82.2% of control trades, reduced development drawdown, and improved both directions. The isolated magnitude of the p20 gain is explicitly treated as an overfit risk. No 24-hour or combined candidate qualified.

## Validation set

| candidate_id | period | trades | retention_percent | profit_factor | average_r | net_pnl | worst_segment_dd_percent | long_pf | long_average_r | short_pf | short_average_r | average_mfe_r | never_reached_0.5r_percent |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| control | 2025 | 251 | 100.0000 | 0.9226 | -0.0551 | -353.5992 | 5.5828 | 0.8852 | -0.0810 | 0.9586 | -0.0302 | 1.3278 | 39.0438 |
| control | 2026 | 163 | 100.0000 | 1.3778 | 0.2598 | 1074.1236 | 3.4835 | 1.3937 | 0.2701 | 1.3630 | 0.2500 | 1.5140 | 28.2209 |
| control | 2025–2026 | 414 | 100.0000 | 1.0972 | 0.0689 | 720.5244 | 5.5828 | 1.0786 | 0.0563 | 1.1149 | 0.0808 | 1.4011 | 34.7826 |
| C1_ATR_P20 | 2025 | 148 | 58.9641 | 0.9253 | -0.0541 | -210.3410 | 3.7103 | 0.8047 | -0.1475 | 1.0144 | 0.0115 | 1.2933 | 39.1892 |
| C1_ATR_P20 | 2026 | 105 | 64.4172 | 1.1904 | 0.1432 | 369.8995 | 2.9553 | 1.1783 | 0.1327 | 1.2028 | 0.1538 | 1.5309 | 28.5714 |
| C1_ATR_P20 | 2025–2026 | 253 | 61.1111 | 1.0335 | 0.0278 | 159.5585 | 3.7103 | 0.9731 | -0.0172 | 1.0845 | 0.0647 | 1.3919 | 34.7826 |

The frozen gate did not materially improve 2025 PF or average R and removed much of 2026's positive result. Its lower 2025 absolute loss reflects fewer trades, not better per-trade quality. Validation does not support this gate.

## Cost sensitivity

| candidate_id | period | spread_usd_per_btc | trades | profit_factor | average_r | net_pnl |
| --- | --- | --- | --- | --- | --- | --- |
| control | development | 0.0000 | 258 | 1.2760 | 0.1882 | 1282.7307 |
| control | 2025 | 0.0000 | 251 | 0.9226 | -0.0551 | -353.5992 |
| control | 2026 | 0.0000 | 163 | 1.3778 | 0.2598 | 1074.1236 |
| control | 2025–2026 | 0.0000 | 414 | 1.0972 | 0.0689 | 720.5244 |
| control | development | 10.0000 | 258 | 1.2221 | 0.1557 | 1066.7444 |
| control | 2025 | 10.0000 | 251 | 0.8943 | -0.0778 | -494.1633 |
| control | 2026 | 10.0000 | 163 | 1.3200 | 0.2285 | 939.0211 |
| control | 2025–2026 | 10.0000 | 414 | 1.0585 | 0.0428 | 444.8578 |
| control | development | 20.0000 | 258 | 1.1716 | 0.1231 | 850.7582 |
| control | 2025 | 20.0000 | 251 | 0.8672 | -0.1005 | -634.7275 |
| control | 2026 | 20.0000 | 163 | 1.2656 | 0.1972 | 803.9187 |
| control | 2025–2026 | 20.0000 | 414 | 1.0217 | 0.0167 | 169.1911 |
| control | development | 30.0000 | 258 | 1.1242 | 0.0906 | 634.7720 |
| control | 2025 | 30.0000 | 251 | 0.8412 | -0.1232 | -775.2917 |
| control | 2026 | 30.0000 | 163 | 1.2144 | 0.1659 | 668.8162 |
| control | 2025–2026 | 30.0000 | 414 | 0.9867 | -0.0093 | -106.4755 |
| C1_ATR_P20 | development | 0.0000 | 212 | 1.3608 | 0.2453 | 1363.1379 |
| C1_ATR_P20 | 2025 | 0.0000 | 148 | 0.9253 | -0.0541 | -210.3410 |
| C1_ATR_P20 | 2026 | 0.0000 | 105 | 1.1904 | 0.1432 | 369.8995 |
| C1_ATR_P20 | 2025–2026 | 0.0000 | 253 | 1.0335 | 0.0278 | 159.5585 |
| C1_ATR_P20 | development | 10.0000 | 212 | 1.3106 | 0.2168 | 1207.4078 |
| C1_ATR_P20 | 2025 | 10.0000 | 148 | 0.9054 | -0.0704 | -270.5886 |
| C1_ATR_P20 | 2026 | 10.0000 | 105 | 1.1552 | 0.1206 | 308.3910 |
| C1_ATR_P20 | 2025–2026 | 10.0000 | 253 | 1.0078 | 0.0088 | 37.8024 |
| C1_ATR_P20 | development | 20.0000 | 212 | 1.2632 | 0.1883 | 1051.6777 |
| C1_ATR_P20 | 2025 | 20.0000 | 148 | 0.8861 | -0.0868 | -330.8362 |
| C1_ATR_P20 | 2026 | 20.0000 | 105 | 1.1216 | 0.0979 | 246.8825 |
| C1_ATR_P20 | 2025–2026 | 20.0000 | 253 | 0.9830 | -0.0101 | -83.9537 |
| C1_ATR_P20 | development | 30.0000 | 212 | 1.2183 | 0.1598 | 895.9476 |
| C1_ATR_P20 | 2025 | 30.0000 | 148 | 0.8674 | -0.1031 | -391.0838 |
| C1_ATR_P20 | 2026 | 30.0000 | 105 | 1.0893 | 0.0753 | 185.3741 |
| C1_ATR_P20 | 2025–2026 | 30.0000 | 253 | 0.9591 | -0.0291 | -205.7098 |

Fixed spreads are research sensitivities on the same completed trades, not tick-exact execution. Costs did not select the threshold.

## Original signal participation and blocked-trade counterfactual

| candidate_id | year | control_signals | signals_allowed | signals_blocked | signal_allowed_percent | control_trades_allowed | control_trades_blocked | allowed_counterfactual_pnl | blocked_counterfactual_pnl | allowed_counterfactual_pf | blocked_counterfactual_pf | gated_run_trades | gated_run_pnl |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| control | 2023 | 31 | 31 | 0 | 100.0000 | 19 | 0 | -174.7947 | 0.0000 | 0.5583 | nan | 19 | -174.7947 |
| control | 2024 | 368 | 368 | 0 | 100.0000 | 239 | 0 | 1457.5254 | 0.0000 | 1.3428 | nan | 239 | 1457.5254 |
| control | 2025 | 362 | 362 | 0 | 100.0000 | 251 | 0 | -353.5992 | 0.0000 | 0.9226 | nan | 251 | -353.5992 |
| control | 2026 | 253 | 253 | 0 | 100.0000 | 163 | 0 | 1074.1236 | 0.0000 | 1.3778 | nan | 163 | 1074.1236 |
| control | All | 1014 | 1014 | 0 | 100.0000 | 672 | 0 | 2003.2551 | 0.0000 | 1.1661 | nan | 672 | 2003.2551 |
| C1_ATR_P20 | 2023 | 31 | 24 | 7 | 77.4194 | 15 | 4 | -75.2961 | -99.4986 | 0.7458 | 0.0000 | 15 | -75.9255 |
| C1_ATR_P20 | 2024 | 368 | 295 | 73 | 80.1630 | 193 | 46 | 1343.9937 | 113.5317 | 1.3934 | 1.1357 | 197 | 1439.0634 |
| C1_ATR_P20 | 2025 | 362 | 210 | 152 | 58.0110 | 144 | 107 | -403.5045 | 49.9054 | 0.8549 | 1.0279 | 148 | -210.3410 |
| C1_ATR_P20 | 2026 | 253 | 162 | 91 | 64.0316 | 101 | 62 | 261.1764 | 812.9472 | 1.1355 | 1.8878 | 105 | 369.8995 |
| C1_ATR_P20 | All | 1014 | 691 | 323 | 68.1460 | 453 | 219 | 1126.3695 | 876.8857 | 1.1338 | 1.2409 | 465 | 1522.6964 |

Allowed/blocked control trades and their PnL are counterfactual classifications of the frozen original run. Gated-run trade and PnL columns are from independent strategy/engine reruns; they can differ because suppressing an order changes later position availability and account state. Drawdown is closed-trade, per source segment, with no synthetic equity continuity across gaps.

Monthly removals and direction breakdowns are provided in CSV files. No entry, exit, or cost assumption was selected using validation performance.
