# Gold V1 — H3 independent multi-year replication

- **Data:** Exness XAUUSDm M15, the expanded MT5 history. Only the text slice `data/…_h3_replication_slice.csv` was
  loaded: warm-up from the session opening 2022-11-27 23:00 UTC, and events in sessions from 2023-01-02 23:00 UTC
  through the session ending 2025-12-22 21:45 UTC.
- **Never loaded:** the artifact era, the reserved 2021-09 → 2022-11 holdout, the development period, the sealed 2026
  validation/OOS windows and later bars.
- **Rules:** the H3 rules, forward race, controls and bootstrap are the frozen development functions, unchanged. The
  replication was preregistered in [H3_REPLICATION_PREREGISTRATION.md](H3_REPLICATION_PREREGISTRATION.md) before any
  outcome was computed.
- **Gate:** PASS (prefix invariance and structure causality, as in development).

## Counts

- **Detection over the whole loaded slice**, including warm-up:
  - compression structures 2414;
  - displacement bars 5458;
  - candidates 709;
  - acceptance failed 157;
  - accepted 550;
  - suppressed duplicates 19; no entry bar 1; risk ≤ 0 0.
- **Events with the acceptance bar in warm-up (excluded):** 4.
- **Replication events:** **526** (281 long / 245 short).
- **Controls:** 2630 draws, 2495 unique bars.
- **Risk:**
  - in ATR units: median 1.81, IQR 1.35–2.41;
  - in USD: median 4.34.
- **Spread / risk** (indicative): median 4.12%.
- **AMBIGUOUS_INTRABAR** (any target): 18 events, 84 controls. Excluded from P(...) for the affected
  target.
- **Unresolved at +2R** (`none` or `truncated` at the end of the replication data): 11.
- **Hole flag:** events whose 20-session lookback contains a known missing-bar hole: 57.
  These are flagged for provenance and not excluded.

## Primary result

P(+2R before −1R), H3 minus matched controls: **+4.5 pp**, 95% CI
+0.0 … +9.1 (event-clustered bootstrap, 5,000 samples). The
detectable lift at this sample size is about ±6.3 pp.

| target | H3 | controls | difference (pp) | 95% CI | conservative H3 (ambiguous = loss) |
|---|---|---|---|---|---|
| +1R | 52.2% (47.9%–56.5%, n=517) | 51.6% (49.6%–53.5%, n=2577) | +0.7 | -3.9 … +5.4 | 51.5% |
| +2R | 36.8% (32.7%–41.1%, n=511) | 32.3% (30.5%–34.2%, n=2529) | +4.5 | +0.0 … +9.1 | 36.5% |
| +3R | 28.2% (24.5%–32.3%, n=503) | 23.2% (21.6%–24.9%, n=2483) | +5.0 | +0.8 … +9.4 | 28.1% |
| +4R | 21.1% (17.8%–25.0%, n=492) | 17.2% (15.7%–18.7%, n=2419) | +4.0 | +0.1 … +7.9 | 21.1% |

+2R lift by side: long +4.5 pp, short +4.4 pp.

## Year by year

| period | events | controls | +1R | +2R | +3R | +4R | control +2R | +2R lift (pp) | 95% CI | MFE32 med | MAE32 med | long / short |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023 | 171 | 855 | 50.0% | 32.1% | 23.8% | 19.6% | 31.4% | +0.7 | -7.0 … +8.5 | 1.93 | 2.10 | 94 / 77 |
| 2024 | 172 | 860 | 56.2% | 41.0% | 31.5% | 21.5% | 31.9% | +9.0 | +0.8 … +17.2 | 1.83 | 1.74 | 96 / 76 |
| 2025 | 183 | 915 | 50.6% | 37.2% | 29.4% | 22.2% | 33.5% | +3.7 | -3.8 … +11.5 | 1.83 | 1.53 | 91 / 92 |
| 2023-2025 pooled | 526 | 2630 | 52.2% | 36.8% | 28.2% | 21.1% | 32.3% | +4.5 | +0.0 … +9.1 | 1.88 | 1.74 | 281 / 245 |

## MFE / MAE (R)

| sample | bars | MFE median | MFE mean | MAE median | MAE mean |
|---|---|---|---|---|---|
| H3 events | 4 | 0.57 | 0.88 | 0.54 | 0.83 |
| H3 events | 8 | 0.82 | 1.24 | 0.76 | 1.28 |
| H3 events | 16 | 1.20 | 1.71 | 1.08 | 1.82 |
| H3 events | 32 | 1.88 | 2.77 | 1.74 | 2.83 |
| H3 events | until −1R | 1.09 | 2.47 | — | — |
| controls | 4 | 0.48 | 0.75 | 0.48 | 0.76 |
| controls | 8 | 0.72 | 1.09 | 0.69 | 1.12 |
| controls | 16 | 1.10 | 1.64 | 1.05 | 1.67 |
| controls | 32 | 1.66 | 2.48 | 1.65 | 2.54 |
| controls | until −1R | 1.06 | 2.24 | — | — |

## Month by month (descriptive)

| month | events | +2R | control +2R | diff (pp) | MFE32 med | MAE32 med |
|---|---|---|---|---|---|---|
| 2023-01 | 10 | 20.0% | 34.7% | -14.7 | 1.05 | 2.35 |
| 2023-02 | 16 | 31.2% | 30.4% | 0.9 | 2.25 | 3.35 |
| 2023-03 | 12 | 25.0% | 33.9% | -8.9 | 1.86 | 2.57 |
| 2023-04 | 20 | 45.0% | 33.0% | 12.0 | 2.19 | 1.87 |
| 2023-05 | 21 | 31.6% | 29.8% | 1.8 | 1.61 | 1.96 |
| 2023-06 | 10 | 11.1% | 31.1% | -20.0 | 1.91 | 2.19 |
| 2023-07 | 13 | 38.5% | 31.0% | 7.4 | 1.40 | 1.36 |
| 2023-08 | 19 | 33.3% | 27.7% | 5.7 | 1.87 | 2.52 |
| 2023-09 | 14 | 64.3% | 36.2% | 28.1 | 2.71 | 1.42 |
| 2023-10 | 7 | 57.1% | 37.1% | 20.0 | 4.17 | 1.79 |
| 2023-11 | 15 | 6.7% | 25.4% | -18.7 | 1.42 | 4.64 |
| 2023-12 | 14 | 16.7% | 32.4% | -15.7 | 2.60 | 2.38 |
| 2024-01 | 13 | 46.2% | 33.8% | 12.3 | 3.37 | 1.31 |
| 2024-02 | 22 | 36.8% | 22.0% | 14.8 | 1.85 | 1.84 |
| 2024-03 | 7 | 14.3% | 41.2% | -26.9 | 1.10 | 2.38 |
| 2024-04 | 11 | 36.4% | 22.6% | 13.7 | 1.71 | 2.36 |
| 2024-05 | 16 | 37.5% | 33.8% | 3.7 | 1.38 | 1.72 |
| 2024-06 | 14 | 21.4% | 34.4% | -12.9 | 1.11 | 1.47 |
| 2024-07 | 11 | 54.5% | 35.8% | 18.7 | 2.49 | 1.71 |
| 2024-08 | 17 | 58.8% | 34.5% | 24.3 | 2.78 | 2.25 |
| 2024-09 | 14 | 30.8% | 35.3% | -4.5 | 0.91 | 1.90 |
| 2024-10 | 15 | 61.5% | 30.1% | 31.4 | 1.96 | 0.76 |
| 2024-11 | 11 | 36.4% | 28.3% | 8.1 | 1.96 | 1.40 |
| 2024-12 | 21 | 42.9% | 36.0% | 6.9 | 1.52 | 2.09 |
| 2025-01 | 16 | 31.2% | 28.6% | 2.7 | 1.37 | 2.43 |
| 2025-02 | 10 | 30.0% | 28.3% | 1.7 | 3.32 | 1.41 |
| 2025-03 | 21 | 23.8% | 38.8% | -15.0 | 1.57 | 2.79 |
| 2025-04 | 6 | 50.0% | 21.4% | 28.6 | 0.74 | 1.04 |
| 2025-05 | 19 | 52.6% | 33.0% | 19.7 | 2.56 | 0.81 |
| 2025-06 | 21 | 42.9% | 32.3% | 10.5 | 2.36 | 2.76 |
| 2025-07 | 20 | 45.0% | 41.4% | 3.6 | 1.76 | 1.08 |
| 2025-08 | 16 | 43.8% | 31.6% | 12.2 | 2.25 | 0.93 |
| 2025-09 | 11 | 27.3% | 34.6% | -7.3 | 2.05 | 1.35 |
| 2025-10 | 4 | 25.0% | 36.8% | -11.8 | 1.53 | 3.28 |
| 2025-11 | 25 | 41.7% | 36.1% | 5.6 | 1.42 | 0.99 |
| 2025-12 | 14 | 21.4% | 26.5% | -5.0 | 0.60 | 1.89 |

Months with H3 > control at +2R: 24 of 36. The row counts include months
where both rates are equal or undefined.

## Decision: **INCONCLUSIVE**

The preregistered rule. **FAILED TO REPLICATE** if the pooled lift is ≤ 0 or its CI upper bound is < +3 pp.
**REPLICATED** only if every test below passes. Otherwise **INCONCLUSIVE**.

| test | result |
|---|---|
| a. pooled +2R lift > 0 and 95% CI lower bound > 0 | PASS: +4.5 pp, CI +0.0 … +9.1 |
| b. pooled +2R lift ≥ +5 pp | FAIL |
| c1. lift > 0 in ≥ 2 of 3 years | PASS: 3 of 3 |
| c2. pooled lift > 0 without the best year (2024) | PASS: +2.3 pp |
| d. neither side's +2R lift < -5 pp | PASS: long +4.5, short +4.4 |
| e. H3 median MFE32 ≥ control median MFE32 | PASS: 1.88 vs 1.66 |

## Development vs replication (descriptive only)

| | events | +1R | +2R | +3R | +4R | control +2R | +2R lift | 95% CI | MFE32 med | MAE32 med | long / short lift at +2R |
|---|---|---|---|---|---|---|---|---|---|---|---|
| development 2025-12-23 → 2026-06-02 (frozen H3 result) | 77 | 55.8% | 41.3% | 31.5% | 23.2% | 33.8% | +7.6 | -4.8 … +21.1 | 1.93 | 1.36 | +7.9 / +7.6 |
| replication 2023-01-01 → 2025-12-22 | 526 | 52.2% | 36.8% | 28.2% | 21.1% | 32.3% | +4.5 | +0.0 … +9.1 | 1.88 | 1.74 | +4.5 / +4.4 |

The development row is recomputed here from the frozen development CSVs with the same functions, and it matches the
frozen H3 report.
