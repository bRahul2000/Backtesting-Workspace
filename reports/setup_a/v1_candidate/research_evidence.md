# BTC Setup A V1 Research Candidate — evidence snapshot

**STATUS: RESEARCH FROZEN. NOT LIVE APPROVED.** This document records completed studies; it does not select new parameters or imply forward execution performance. Source checkpoint: `f4a62662368b01519bf32e1345bdff8493cff342` (`btc-setup-a-long-history-v1.0`).

## Exness broker-native Bid M15, standalone Setup A

Real Exness BTCUSDm M15 Bid candles, 2023-11-09 through 2026-09-17; each continuous segment runs independently. Original A-only rules and audited theoretical 0.25%-risk account. [Native validation](../setup_a_validation_summary.md) and [native results](../native_results.csv) are the saved sources.

| View | Completed trades | PF | Average R | Net PnL | Worst segment DD |
| --- | ---: | ---: | ---: | ---: | ---: |
| Zero cost | 672 | 1.1661 | +0.1147 | +$2,003.26 | 5.58% |
| Fixed $10/BTC spread | 672 | 1.1218 | +0.0861 | +$1,511.60 | 5.88% |
| Fixed $20/BTC spread | 672 | 1.0799 | +0.0576 | +$1,019.95 | 6.19% |
| Fixed $30/BTC spread | 672 | 1.0403 | +0.0290 | +$528.30 | 6.83% |

These fixed-spread views are research sensitivities, not tick-exact historical fills. Commission is $0 for Exness Standard in this calibration. Actual full-history Bid/Ask ticks and swap conversion are not available for an execution-equivalent backtest.

| Exness year | Completed trades | Zero-cost PF | Average R | Zero-cost net PnL |
| --- | ---: | ---: | ---: | ---: |
| 2023 partial | 19 | 0.5583 | −0.3684 | −$174.79 |
| 2024 | 239 | 1.3428 | +0.2324 | +$1,457.53 |
| 2025 | 251 | 0.9226 | −0.0551 | −$353.60 |
| 2026 partial | 163 | 1.3778 | +0.2598 | +$1,074.12 |

## Bitstamp long-history cross-feed robustness

Real BTC/USD M15 from 2021-01-01 through 2026-09-17: 200,084 source candles, 24 continuous segments, 21 usable after causal warm-up, three excluded. Segments reset strategy and account; no missing candle is filled. **Bitstamp is cross-feed evidence and is not Exness broker-native performance.** [Long-history report](../long_history/long_history_summary.md) and [yearly CSV](../long_history/yearly_results.csv) are the saved sources.

Full zero-cost result: **1,254 trades, PF 1.3286, average R +0.2154, net +$7,039.96, worst segment closed-trade DD 4.84%**.

| Bitstamp year | Trades | PF | Average R | Net PnL |
| --- | ---: | ---: | ---: | ---: |
| 2021 | 194 | 1.1841 | +0.1338 | +$645.15 |
| 2022 | 192 | 1.0976 | +0.0682 | +$330.45 |
| 2023 | 246 | 1.3364 | +0.2163 | +$1,345.02 |
| 2024 | 237 | 1.5925 | +0.3756 | +$2,370.42 |
| 2025 | 231 | 1.1223 | +0.0862 | +$484.91 |
| 2026 partial | 154 | 1.7242 | +0.4472 | +$1,864.00 |

Both Bitstamp directions contributed over the full period: **long 622 trades, PF 1.3576, average R +0.2314, net +$3,805.84**; **short 632 trades, PF 1.2999, average R +0.1996, net +$3,234.11**. The additional **pre-Exness** period, 2021-01-01 through 2023-11-08, had **610 trades, PF 1.2258, average R +0.1534, net +$2,358.06**. Its long PF/average R were **1.1983/+0.1345** and short **1.2512/+0.1701**.

The saved exact-common-timestamp feed comparison produced **Exness PF 1.1647, average R +0.1129** versus **Bitstamp PF 1.4246, average R +0.2727**, with **71.98% exact** and **78.85% exact-plus-near** signal matches. These differences limit the inference from Bitstamp's positive 2025 to Exness execution.

## Known weaknesses and research limits

- Exness-native 2025 was negative before costs in both directions (overall PF 0.9226, average R −0.0551). Bitstamp 2025 was positive; feed choice materially changes results.
- The Exness M15 signal feed is Bid-only OHLC. A complete historical Bid/Ask tick series is unavailable for every trade, so pending entry, exit, real spread, and intrabar ordering are not tick-exact. Historical 2021–2023 Exness spread is unknown; Bitstamp fixed-spread tables are hypothetical.
- Theoretical audited risk sizing and separate Exness 0.01-lot rounding audit are distinct. The displayed baseline does not claim every theoretical quantity was broker-executable.
- Every gap creates an independent research account/indicator segment. Pooled results are not one continuous compounded equity curve.
- Previous research examined all years, including 2025–2026. This evidence is not an untouched holdout. Backtests cannot establish forward MT5 execution quality, live fills, swaps, operational reliability, or broker availability.

**Next required stage:** MT5 / Exness forward or demo execution validation under the unchanged frozen rules, with actual Bid/Ask execution records. No live approval is granted by this freeze.
