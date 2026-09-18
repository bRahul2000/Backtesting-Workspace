# EXNESS STANDARD COST-CALIBRATED APPROXIMATION — synthetic execution audit

RESEARCH ONLY · BITSTAMP HISTORICAL PRICES · SYNTHETIC EXNESS-LIKE BID/ASK. This is not a broker-native historical Exness backtest.

Calibration: five Exness Standard BTCUSDm samples; 541,647 real ticks across 120 observed hours; observed spread $10/BTC. Synthetic tests also use $5, $15, and $20 as sensitivity scenarios. Commission is $0.

## Order reconciliation hierarchy

One primary category per (segment, signal timestamp, direction, setup ID): synthetic-only fill; original-only fill; timing-changed fill; price-changed fill; exact same fill; expired in both; canceled in both; otherwise different order state. A same-bar fill with a changed price is PRICE_CHANGED_FILL, not SAME_FILL. Counts are disjoint.

| Category | Orders |
|---|---:|
| SAME_FILL | 828 |
| SYNTHETIC_ONLY_FILL | 35 |
| ORIGINAL_ONLY_FILL | 10 |
| TIMING_CHANGED_FILL | 20 |
| PRICE_CHANGED_FILL | 100 |
| EXPIRED_BOTH | 234 |
| CANCELED_BOTH | 5 |
| OTHER_ORDER_STATE | 5 |

## Quote-side mathematics

Long signals use Bid; buy-stop trigger and entry use Ask = Bid + spread; long SL, TP, and exit use Bid. Short signals, sell-stop trigger, and entry use Bid; short SL, TP, and exit use Ask.

Target is derived from actual synthetic fill to original structural stop at 3R. The replay reuses the audited conservative same-bar SL-first decision function.

Every completed synthetic trade was checked against direction × (exit price − entry price) × BTC quantity. Entry and exit commissions were zero. No post-trade spread was deducted. The one-spread equivalent in Phase 4F-B1 is descriptive and already embedded in these prices. DOUBLE-SPREAD CHECK: PASS.

## Three-model comparison, identical Bitstamp source

The single-price model uses 0.05% commission per side. Cost-only keeps its frozen fills and applies one $10 spread per BTC. Synthetic execution replays quote-side fills and exits with zero commission.

| scope | model | pending_fills | trades | profit_factor | average_r | net_pnl |
|---|---|---|---|---|---|---|
| development | original_single_price | 641 | 639 | 0.8742 | -0.0893 | -1454.4589 |
| development | cost_only_$10 | 641 | 639 | 1.0175 | 0.0138 | 181.667 |
| development | synthetic_$10 | 658 | 656 | 1.0025 | 0.0036 | 30.0791 |
| forward-validation | original_single_price | 317 | 316 | 0.7929 | -0.1527 | -1181.9767 |
| forward-validation | cost_only_$10 | 317 | 316 | 1.0078 | 0.0062 | 37.3751 |
| forward-validation | synthetic_$10 | 325 | 324 | 0.9607 | -0.0271 | -233.3577 |
| all | original_single_price | 958 | 955 | 0.8474 | -0.1102 | -2636.4356 |
| all | cost_only_$10 | 958 | 955 | 1.0144 | 0.0113 | 219.0421 |
| all | synthetic_$10 | 983 | 980 | 0.9887 | -0.0065 | -203.2786 |

## Original $10 synthetic result

Completed trades 980; PF 0.9887; average R -0.0065; net PnL $-203.28; worst continuous-segment DD 5.4453%.

## Same-bar completed trades

Entry-candle stop touched: 30; target touched: 4; both touched: 0. These touch counts can overlap and use the appropriate exit quote side.

## Matched-trade absolute price/R effects

| Direction | Field | Count | Mean | Median | P75 | P90 | P95 | Max |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| ALL | entry_price_delta | 945 | 0.5954 | 0.0000 | 0.0000 | 1.6074 | 5.4132 | 10.0000 |
| ALL | exit_price_delta | 945 | 11.1538 | 0.0000 | 0.0000 | 0.0000 | 3.6897 | 2498.7360 |
| ALL | risk_distance_delta | 945 | 0.5954 | 0.0000 | 0.0000 | 1.6074 | 5.4132 | 10.0000 |
| ALL | target_price_delta | 945 | 2.3816 | 0.0000 | 0.0000 | 6.4295 | 21.6527 | 40.0000 |
| ALL | stop_price_delta | 945 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| ALL | realized_r_delta | 945 | 0.2040 | 0.0000 | 0.3130 | 0.6826 | 0.9114 | 3.5713 |
| LONG | entry_price_delta | 458 | 1.2285 | 0.0000 | 0.0000 | 5.5273 | 8.6787 | 10.0000 |
| LONG | exit_price_delta | 458 | 2.1574 | 0.0000 | 0.0000 | 0.0000 | 8.4077 | 352.6582 |
| LONG | risk_distance_delta | 458 | 1.2285 | 0.0000 | 0.0000 | 5.5273 | 8.6787 | 10.0000 |
| LONG | target_price_delta | 458 | 4.9140 | 0.0000 | 0.0000 | 22.1091 | 34.7147 | 40.0000 |
| LONG | stop_price_delta | 458 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| LONG | realized_r_delta | 458 | 0.1987 | 0.0000 | 0.3490 | 0.7428 | 0.9154 | 3.3145 |
| SHORT | entry_price_delta | 487 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| SHORT | exit_price_delta | 487 | 19.6146 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 2498.7360 |
| SHORT | risk_distance_delta | 487 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| SHORT | target_price_delta | 487 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| SHORT | stop_price_delta | 487 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| SHORT | realized_r_delta | 487 | 0.2089 | 0.0000 | 0.2689 | 0.6186 | 0.8875 | 3.5713 |

## Frozen candidate $10 development and forward results

| Candidate | Scope | Signals | Fills | Trades | Long | Short | WR % | PF | Avg R | Median R | Net | Worst DD % | Max losses |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ORIGINAL | development | 824 | 658 | 656 | 328 | 328 | 24.85 | 1.0025 | 0.0036 | -1.0000 | 30.08 | 4.6589 | 14 |
| ORIGINAL | forward-validation | 398 | 325 | 324 | 159 | 165 | 24.38 | 0.9607 | -0.0271 | -1.0000 | -233.36 | 5.4453 | 12 |
| ORIGINAL | all | 1222 | 983 | 980 | 487 | 493 | 24.69 | 0.9887 | -0.0065 | -1.0000 | -203.28 | 5.4453 | 14 |
| C2 | development | 414 | 337 | 336 | 164 | 172 | 27.08 | 1.1181 | 0.0872 | -1.0000 | 714.72 | 3.9316 | 14 |
| C2 | forward-validation | 196 | 166 | 166 | 78 | 88 | 25.30 | 1.0208 | 0.0182 | -1.0000 | 64.00 | 3.4504 | 10 |
| C2 | all | 610 | 503 | 502 | 242 | 260 | 26.49 | 1.0854 | 0.0644 | -1.0000 | 778.72 | 3.9316 | 14 |
| C3 | development | 478 | 396 | 395 | 206 | 189 | 27.34 | 1.1510 | 0.1079 | -1.0000 | 1064.17 | 2.9725 | 10 |
| C3 | forward-validation | 214 | 178 | 178 | 87 | 91 | 24.16 | 0.9716 | -0.0185 | -1.0000 | -92.52 | 4.2794 | 12 |
| C3 | all | 692 | 574 | 573 | 293 | 280 | 26.35 | 1.0944 | 0.0686 | -1.0000 | 971.65 | 4.2794 | 12 |
| ADX25 | development | 486 | 393 | 392 | 185 | 207 | 26.28 | 1.0675 | 0.0514 | -1.0000 | 483.60 | 3.7141 | 11 |
| ADX25 | forward-validation | 228 | 184 | 184 | 86 | 98 | 24.46 | 0.9688 | -0.0205 | -1.0000 | -107.75 | 3.4504 | 10 |
| ADX25 | all | 714 | 577 | 576 | 271 | 305 | 25.69 | 1.0354 | 0.0284 | -1.0000 | 375.85 | 3.7141 | 11 |

## Robustness flags (descriptive; no selection)

| candidate | development_pf_gt_1 | development_avg_r_gt_0 | forward_pf_gt_1 | forward_avg_r_gt_0 | long_development_pf_gt_1 | short_development_pf_gt_1 | long_forward_pf_gt_1 | short_forward_pf_gt_1 | adequate_sample |
|---|---|---|---|---|---|---|---|---|---|
| ORIGINAL | True | True | False | False | True | False | False | False | True |
| C2 | True | True | True | True | True | True | False | True | True |
| C3 | True | True | False | False | True | False | False | True | True |
| ADX25 | True | True | False | False | False | True | False | True | True |

## Synthetic spread sensitivity

| candidate | scope | spread_usd_per_btc | trades | profit_factor | average_r | net_pnl |
|---|---|---|---|---|---|---|
| ORIGINAL | development | 5.0 | 648 | 1.0436 | 0.0329 | 515.1505 |
| ORIGINAL | forward-validation | 5.0 | 319 | 0.999 | 0.0007 | -5.5449 |
| ORIGINAL | development | 10.0 | 656 | 1.0025 | 0.0036 | 30.0791 |
| ORIGINAL | forward-validation | 10.0 | 324 | 0.9607 | -0.0271 | -233.3577 |
| ORIGINAL | development | 15.0 | 672 | 0.9408 | -0.0424 | -746.6157 |
| ORIGINAL | forward-validation | 15.0 | 328 | 0.9458 | -0.0387 | -327.5496 |
| ORIGINAL | development | 20.0 | 676 | 0.8811 | -0.0883 | -1532.2677 |
| ORIGINAL | forward-validation | 20.0 | 333 | 0.9444 | -0.0397 | -340.5766 |
| C2 | development | 5.0 | 332 | 1.1799 | 0.1287 | 1056.5512 |
| C2 | forward-validation | 5.0 | 164 | 1.0379 | 0.0307 | 114.6225 |
| C2 | development | 10.0 | 336 | 1.1181 | 0.0872 | 714.7211 |
| C2 | forward-validation | 10.0 | 166 | 1.0208 | 0.0182 | 63.9968 |
| C2 | development | 15.0 | 343 | 1.0559 | 0.0436 | 352.1592 |
| C2 | forward-validation | 15.0 | 168 | 1.006 | 0.007 | 18.7841 |
| C2 | development | 20.0 | 352 | 0.9658 | -0.0229 | -227.0403 |
| C2 | forward-validation | 20.0 | 171 | 0.9852 | -0.0081 | -47.0544 |
| C3 | development | 5.0 | 391 | 1.2088 | 0.1459 | 1432.2081 |
| C3 | forward-validation | 5.0 | 175 | 0.995 | -0.0011 | -15.9054 |
| C3 | development | 10.0 | 395 | 1.151 | 0.1079 | 1064.1746 |
| C3 | forward-validation | 10.0 | 178 | 0.9716 | -0.0185 | -92.5209 |
| C3 | development | 15.0 | 403 | 1.0794 | 0.0579 | 582.9117 |
| C3 | forward-validation | 15.0 | 180 | 0.9576 | -0.029 | -140.1686 |
| C3 | development | 20.0 | 406 | 1.0331 | 0.0257 | 248.5739 |
| C3 | forward-validation | 20.0 | 183 | 0.9401 | -0.0421 | -202.1048 |
| ADX25 | development | 5.0 | 387 | 1.1236 | 0.0903 | 860.0591 |
| ADX25 | forward-validation | 5.0 | 180 | 1.0285 | 0.0236 | 94.7462 |
| ADX25 | development | 10.0 | 392 | 1.0675 | 0.0514 | 483.6027 |
| ADX25 | forward-validation | 10.0 | 184 | 0.9688 | -0.0205 | -107.7503 |
| ADX25 | development | 15.0 | 401 | 1.0078 | 0.008 | 58.2495 |
| ADX25 | forward-validation | 15.0 | 186 | 0.9563 | -0.0301 | -152.7546 |
| ADX25 | development | 20.0 | 407 | 0.9154 | -0.062 | -656.9768 |
| ADX25 | forward-validation | 20.0 | 189 | 0.9389 | -0.0432 | -217.4953 |

No parameters, direction permissions, exit rules, or active strategy settings were changed. No deployment recommendation is made.
