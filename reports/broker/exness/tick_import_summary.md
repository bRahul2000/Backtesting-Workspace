# Exness BTCUSDm multi-sample quote reconstruction

Timezone status: **EXNESS_MT5_SERVER_TIME_UNVERIFIED**. Timestamps, weekdays, and hours are MT5 server wall time; no UTC conversion was made.

Each CSV was reconstructed independently in original row order. Bid-only and Ask-only updates carry the last known opposite side within the same file and continuous 15-minute sequence. No quote is carried across files, missing 15-minute intervals, or before that side first appears.

Samples: 5; raw rows: 541,647; reconstructed complete ticks: 541,647; 15-minute bars: 480; observed bar-hours: 120.
Partial updates: Bid-only 326; Ask-only 0; both 541,321. Duplicate full rows 0; duplicate timestamps 1,243; malformed rows 0.

Combined spread USD/BTC: min 10.000000, median 10.000000, mean 10.000000, P75 10.000000, P90 10.000000, P95 10.000000, P99 10.000000, max 10.000000; median 1.327502 bps.

| Sample | Date | Type | Raw rows | Ticks | Bars | Missing bars | Bid-only | Ask-only | Both | Full duplicates | Duplicate timestamps | Malformed | Median spread | P95 spread | Max spread | Median bps |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| s01 | 2026-08-01 | weekend | 89,396 | 89,396 | 96 | 0 | 56 | 0 | 89,340 | 0 | 137 | 0 | 10.0000 | 10.0000 | 10.0000 | 1.5866 |
| s02 | 2026-08-05 | weekday | 101,344 | 101,344 | 96 | 0 | 84 | 0 | 101,260 | 0 | 208 | 0 | 10.0000 | 10.0000 | 10.0000 | 1.5483 |
| s03 | 2026-08-15 | weekend | 75,345 | 75,345 | 96 | 0 | 77 | 0 | 75,268 | 0 | 8 | 0 | 10.0000 | 10.0000 | 10.0000 | 1.5873 |
| s04 | 2026-09-01 | weekday | 128,645 | 128,645 | 96 | 0 | 67 | 0 | 128,578 | 0 | 454 | 0 | 10.0000 | 10.0000 | 10.0000 | 1.2925 |
| s05 | 2026-09-15 | weekday | 146,917 | 146,917 | 96 | 0 | 42 | 0 | 146,875 | 0 | 436 | 0 | 10.0000 | 10.0000 | 10.0000 | 1.3178 |

Commission: $0. Spread source: reconstructed historical Bid/Ask quote states. The observed live screenshot spread was approximately $10/BTC. No fixed spread is activated in the generic engine.
