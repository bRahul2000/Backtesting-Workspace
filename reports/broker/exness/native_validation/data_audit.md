# Exness BTCUSDm MT5 Bid M15 data audit

Source: `BTCUSDm_M15_202311090000_202609171715.csv`; SHA-256 `f75f09935fe5dcf68f8ad545ae3d9733ee07c672a6bac83bdaa74ee3658a0f45`. Raw source unchanged.

100,180 rows, 2023-11-09 00:00:00+00:00 to 2026-09-17 17:15:00+00:00; 100,198 expected, 18 missing across 6 gaps (largest 10).
Duplicate full rows 0; duplicate timestamps 0; invalid OHLC 0; off-grid timestamps 0.

Tick cross-check: 480 overlapping M15 bars; 480 exact Bid OHLC matches, 0 mismatches; 480 spread-minimum matches, 0 mismatches.

**MT5 bar SPREAD is a historical bar-level minimum spread descriptor, not the spread guaranteed at an execution tick.** `spread_price = spread_points × 0.01` for this 2-digit symbol. Bar spread may be used only as an optimistic lower-bound cost descriptor; tick-exact execution requires historical Bid/Ask quotes at the relevant times.

No M15 candle was interpolated or forward-filled. Timestamps are Exness server UTC+0; the original CSV has no embedded offset.

## Historical minimum-spread changes

| Year | Candles | Median $/BTC | Mean $/BTC | P95 $/BTC | Max $/BTC |
|---|---:|---:|---:|---:|---:|
| 2023 | 5,087 | 16.64 | 17.04 | 26.40 | 33.68 |
| 2024 | 35,130 | 29.76 | 32.94 | 58.06 | 88.09 |
| 2025 | 35,029 | 21.60 | 23.47 | 29.00 | 36.00 |
| 2026 | 24,934 | 14.00 | 13.59 | 18.00 | 18.00 |

The 480 tick-sample overlap bars have median minimum spread $10.00/BTC. The annual medians differ substantially, so the recent $10 tick-sample observation is not extended to earlier years.
