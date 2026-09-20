# Phase R1 readiness — Exness BTCUSDm broker-native dataset

**Status: BLOCKED on a manual MT5 export.** Two of the three required real
inputs do not exist in the repository. Nothing has been inferred or
substituted in their place.

| Required input | Present | Path |
|---|---|---|
| BTCUSDm **symbol specification** | **NO** | `data/exness/btc/phase_r1/raw/btcusd_mt5_spec.json` |
| BTCUSDm **M15** broker history | partial — see below | `data/exness/btc/phase_r1/raw/btcusd_BTCUSDm_M15.csv` |
| BTCUSDm **H1** broker history | **NO** | `data/exness/btc/phase_r1/raw/btcusd_BTCUSDm_H1.csv` |

## What already exists

| Asset | Detail |
|---|---|
| Real Exness BTCUSDm M15 history | `data/exness/raw/BTCUSDm_M15_202311090000_202609171715.csv` — an MT5 terminal "Save as CSV" dump, **100,180 bars, 2023-11-09 00:00 → 2026-09-17 17:15 UTC** |
| Canonicalized copy | `data/exness/processed/btcusdm_m15.csv` |
| Five real BTCUSDm tick samples | `s01`–`s05`, 541,647 ticks total, five 24-hour windows 2026-08-01 → 2026-09-16 |
| Gold Phase 2A reference pipeline | `services/gold_data.py`, `data/exness/gold/phase2a/manifest.json` |
| Generic validators / fingerprints | `utils/data_validation.py`, `core/fingerprints.py` |
| Broker / instrument profiles | `brokers/exness_standard_btcusdm.py`, `instruments/btcusd.py` |

The existing M15 dump is genuine broker data and it is clean, but it **cannot
complete Phase R1 on its own**: it carries no symbol specification and has no
H1 companion, so R1.6 (M15↔H1 reconciliation), the H1 half of R1.7/R1.8, and
R3.2's "verified BTCUSDm symbol specification" all remain unsatisfiable.

## Validation of the existing M15 dump (R1.5, real result)

Run through the new pipeline, read-only:

| Check | Result |
|---|---|
| Rows | 100,180 |
| Coverage | 2023-11-09T00:00:00Z → 2026-09-17T17:15:00Z |
| Timestamps monotonic increasing | yes |
| Unparsable timestamps | 0 |
| Duplicate timestamps | 0 |
| Duplicate full rows | 0 |
| Invalid OHLC rows | 0 |
| Non-numeric rows | 0 |
| Off-grid timestamps | 0 |
| Negative spreads | 0 |
| Zero spreads | 0 |
| Negative tick/real volume | 0 |
| **Overall** | **PASSED** |

Continuity: **7 continuous segments**, largest **32,255** candles, median
**10,961**, smallest 10. **6 gaps totalling 18 missing candles**, largest gap
10 candles. Gap sizes: three 1-candle, two 2–4, one 5–16, none above 16.

## Spread (R1.7, M15 only — H1 still missing)

`spread_price = spread_points × point`. The point size **0.01** here is derived
from the existing 2-digit broker profile, **not** from a verified specification
export; the manifest will recompute it from the real spec once that exists.

| | min | p25 | median | mean | p75 | p90 | p95 | p99 | max |
|---|---|---|---|---|---|---|---|---|---|
| spread_points | 243 | 1,800 | 2,160 | 2,400.6 | 2,896 | 3,395 | 4,531 | 6,442 | 8,809 |
| spread_price ($/BTC) | 2.43 | 18.00 | 21.60 | 24.01 | 28.96 | 33.95 | 45.31 | 64.42 | 88.09 |

5,938 distinct spread values. **Descriptive comparison with the tick samples:**
the five recent 24-hour tick windows sit around **$10/BTC**, far below the
**$21.60** full-history median — consistent with spreads having tightened over
time. The two are **not** forced to agree, and the recent tick observation is
not extended backwards.

MT5 bar spread is a bar-level descriptor, not the spread guaranteed at an
execution tick.

## Not yet computable

| Item | Blocked on |
|---|---|
| R1.6 M15↔H1 reconciliation | H1 export |
| R1.7 H1 spread distribution | H1 export |
| R1.8 manifest + full fingerprint set | spec + H1 |
| R2 Bitstamp vs Exness comparison | R1 |
| R3 frozen Core on broker-native data | R1 (R3.2 needs the verified spec) |

## Prepared in this commit

- `mt5/Export_BTCUSD_Spec.mq5` — BTCUSDm specification capture. Emits the Gold
  Phase 2A schema plus the fields R1.2 requires (currency_profit,
  currency_margin, trade mode, filling modes). Leverage, commission and margin
  are emitted as explicit `UNVERIFIED` markers.
- `mt5/Export_BTCUSD_History.mq5` — maximum available M15 and H1 history with a
  metadata sidecar. The forming bar is always excluded.
- `services/btc_broker_data.py` — ingestion, R1.5 validation, segmentation,
  R1.6 reconciliation, R1.7 spread statistics, R1.8 fingerprints and manifest.
  Reads both the exporter layout and the terminal-dump layout. Reuses the
  generic validators; no Gold machinery was duplicated.
- `tests/test_btc_broker_data.py` — 30 tests including the gate itself.
- `data/exness/btc/phase_r1/` — directory scaffold and README.

## Integrity note on R1.9

The specification asked for a fix to a duplicated guard message,
`WALK-FORWARD DISABLED — WALK-FORWARD DISABLED — REJECTED STRATEGY`.
**No such duplication exists in the codebase.** `research/walk_forward.py:271`
and `ui/research_lab.py:286` both read `WALK-FORWARD DISABLED — REJECTED
STRATEGY`, and the runtime exception string was verified to be the single form.
The duplication appeared only in a previous chat summary. No code was changed.
