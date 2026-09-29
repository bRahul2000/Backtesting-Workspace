# Gold V1 — H3 second independent replication (repaired 2017-06 → 2021-08)

- **Data:** the approved repaired Exness XAUUSDm M15 history (`repaired/xauusd_XAUUSDm_M15_repaired.csv`), warm-up
  from 2017-05-01.
- **Event window:** events whose acceptance bar is in [2017-06-01 00:00, 2021-08-31 22:00) UTC.
- **End of data:** forward data stops at 2021-08-31 20:45, before the sealed holdout. Races reaching it are
  `truncated` and excluded from P(...).
- **Rules:** the frozen H3 rules, forward race, controls and bootstrap, unchanged. Preregistered in
  [H3_REPLICATION_2_PREREGISTRATION.md](H3_REPLICATION_2_PREREGISTRATION.md) before any outcome.
- **Gate:** PASS.
- **Costs:** spread is unavailable for most of this era, so this is a structural-edge test only.

## Counts

- **Replication events:** **1007** (481 long / 526 short).
  Warm-up events excluded: 5.
- **Controls:** 5035 draws, 4676 unique bars.
- **Risk:** median 1.86 ATR (IQR 1.41–2.43), 2.08 USD.
- **AMBIGUOUS_INTRABAR** (any target): 18 events, 99 controls. Excluded from
  P(...) for the affected target.
- **Unresolved at +2R** (`none` or `truncated`): 23.
- **Provenance flags** (descriptive; nothing excluded):
  - 20-session lookback contains a repaired pseudo-session location: 767;
  - lookback contains a genuine outage: 47;
  - race within a day of a weekly-open regime transition or a break-variant day: 41.

## Primary result (standalone)

P(+2R before −1R): H3 **33.2%** vs controls **33.2%** →
lift **-0.05 pp**, 95% CI **-3.17 … +3.25** (event-clustered bootstrap,
5,000 samples, seed 20260603).

| target | H3 | controls | lift (pp) | 95% CI |
|---|---|---|---|---|
| +1R | 49.8% (46.7%–52.9%, n=996) | 50.7% (49.3%–52.1%, n=4959) | -0.9 | -4.2 … +2.6 |
| +2R | 33.2% (30.3%–36.2%, n=980) | 33.2% (31.9%–34.6%, n=4892) | -0.1 | -3.2 … +3.3 |
| +3R | 23.8% (21.2%–26.5%, n=964) | 25.1% (23.9%–26.3%, n=4783) | -1.3 | -4.3 … +1.7 |
| +4R | 17.4% (15.2%–20.0%, n=940) | 18.9% (17.8%–20.1%, n=4645) | -1.5 | -4.1 … +1.3 |

## Decision gates (preregistered)

| gate | criterion | result |
|---|---|---|
| A. statistical persistence | pooled +2R lift > 0 | FAIL (-0.05 pp) |
| | 95% CI lower bound > 0 | FAIL (-3.17 pp) |
| | long and short point estimates ≥ 0 | FAIL (long +2.2, short -2.1) |
| | not dependent on one year: every leave-one-year-out lift > 0 | FAIL (minimum -1.4 pp) |
| **A overall** | | **FAIL** |
| **B. practical size** | pooled +2R lift ≥ +5.0 pp | **FAIL** |

## Classification: **FAILED TO REPLICATE**

## Year by year

| year | events | long / short | +1R | +2R | +3R | +4R | control +2R | +2R lift (pp) | 95% CI | MFE32 med | MAE32 med |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2017 | 167 | 88 / 79 | 47.2% | 32.3% | 25.2% | 17.1% | 34.0% | -1.7 | -9.2 … +5.9 | 2.30 | 2.01 |
| 2018 | 241 | 104 / 137 | 55.9% | 36.2% | 27.4% | 19.9% | 32.0% | +4.1 | -2.1 … +10.6 | 1.82 | 1.76 |
| 2019 | 215 | 98 / 117 | 47.9% | 34.3% | 22.1% | 17.2% | 31.9% | +2.3 | -4.9 … +9.8 | 1.78 | 1.88 |
| 2020 | 221 | 114 / 107 | 47.5% | 32.2% | 22.9% | 18.0% | 33.3% | -1.0 | -7.8 … +5.9 | 1.53 | 1.92 |
| 2021 | 163 | 77 / 86 | 49.1% | 29.3% | 20.3% | 13.8% | 35.8% | -6.5 | -14.4 … +1.1 | 1.63 | 1.62 |

## Leave one year out (descriptive; no year is excluded from the primary result)

| sample | events | H3 +2R | control +2R | lift (pp) | 95% CI |
|---|---|---|---|---|---|
| excluding 2017 | 840 | 33.3% | 33.1% | +0.3 | -3.3 … +3.8 |
| excluding 2018 | 766 | 32.2% | 33.6% | -1.4 | -5.1 … +2.3 |
| excluding 2019 | 792 | 32.9% | 33.6% | -0.7 | -4.1 … +2.8 |
| excluding 2020 | 786 | 33.4% | 33.2% | +0.2 | -3.4 … +3.8 |
| excluding 2021 | 844 | 33.9% | 32.7% | +1.2 | -2.3 … +4.7 |

## Long / short

| side | events | H3 +2R | control +2R | lift (pp) | 95% CI | MFE32 med | MAE32 med |
|---|---|---|---|---|---|---|---|
| LONG | 481 | 33.8% | 31.6% | +2.2 | -2.2 … +6.6 | 1.70 | 1.66 |
| SHORT | 526 | 32.6% | 34.7% | -2.1 | -6.7 … +2.4 | 1.77 | 2.01 |

## MFE / MAE (R)

| sample | bars | MFE median | MFE mean | MAE median | MAE mean |
|---|---|---|---|---|---|
| H3 events | 4 | 0.56 | 0.83 | 0.52 | 0.84 |
| H3 events | 8 | 0.78 | 1.19 | 0.75 | 1.22 |
| H3 events | 16 | 1.08 | 1.66 | 1.09 | 1.71 |
| H3 events | 32 | 1.74 | 2.68 | 1.87 | 2.77 |
| H3 events | until −1R | 0.99 | 2.32 | — | — |
| controls | 4 | 0.45 | 0.69 | 0.44 | 0.70 |
| controls | 8 | 0.67 | 1.03 | 0.64 | 1.02 |
| controls | 16 | 1.03 | 1.61 | 1.00 | 1.57 |
| controls | 32 | 1.62 | 2.52 | 1.54 | 2.39 |
| controls | until −1R | 1.03 | 2.35 | — | — |

## Month by month (descriptive)

Months with lift > 0: **25**, = 0: **1**, < 0: **25**, undefined: 0, out of 51.

| month | events | H3 +2R | control +2R | lift (pp) | MFE32 med | MAE32 med |
|---|---|---|---|---|---|---|
| 2017-06 | 30 | 31.0% | 32.4% | -1.4 | 1.80 | 2.05 |
| 2017-07 | 18 | 38.9% | 33.7% | 5.2 | 3.05 | 1.15 |
| 2017-08 | 15 | 20.0% | 30.1% | -10.1 | 1.87 | 4.29 |
| 2017-09 | 23 | 17.4% | 31.6% | -14.2 | 1.53 | 2.06 |
| 2017-10 | 30 | 25.0% | 34.5% | -9.5 | 1.87 | 2.56 |
| 2017-11 | 23 | 33.3% | 39.6% | -6.3 | 2.20 | 1.38 |
| 2017-12 | 28 | 55.6% | 35.1% | 20.5 | 3.10 | 1.92 |
| 2018-01 | 10 | 50.0% | 34.7% | 15.3 | 1.50 | 1.27 |
| 2018-02 | 16 | 40.0% | 20.5% | 19.5 | 1.62 | 3.66 |
| 2018-03 | 23 | 38.1% | 43.9% | -5.8 | 1.63 | 1.60 |
| 2018-04 | 22 | 33.3% | 29.9% | 3.4 | 1.49 | 2.06 |
| 2018-05 | 26 | 30.8% | 27.6% | 3.2 | 2.69 | 2.47 |
| 2018-06 | 20 | 30.0% | 31.2% | -1.3 | 0.99 | 1.87 |
| 2018-07 | 18 | 33.3% | 31.8% | 1.5 | 2.58 | 2.02 |
| 2018-08 | 25 | 32.0% | 33.9% | -1.9 | 2.68 | 1.79 |
| 2018-09 | 26 | 28.0% | 25.6% | 2.4 | 1.38 | 2.00 |
| 2018-10 | 16 | 60.0% | 36.8% | 23.2 | 2.66 | 0.89 |
| 2018-11 | 22 | 40.9% | 36.8% | 4.1 | 2.49 | 1.26 |
| 2018-12 | 17 | 35.3% | 32.1% | 3.2 | 1.70 | 2.65 |
| 2019-01 | 19 | 36.8% | 37.4% | -0.5 | 1.72 | 1.28 |
| 2019-02 | 25 | 32.0% | 30.6% | 1.4 | 0.95 | 2.41 |
| 2019-03 | 11 | 40.0% | 33.3% | 6.7 | 1.90 | 2.05 |
| 2019-04 | 18 | 33.3% | 29.2% | 4.1 | 2.46 | 1.96 |
| 2019-05 | 21 | 38.1% | 35.6% | 2.5 | 2.22 | 1.10 |
| 2019-06 | 4 | 75.0% | 35.0% | 40.0 | 2.54 | 1.88 |
| 2019-07 | 31 | 32.3% | 33.1% | -0.9 | 2.52 | 1.88 |
| 2019-08 | 21 | 38.1% | 25.0% | 13.1 | 1.63 | 1.66 |
| 2019-09 | 18 | 16.7% | 32.1% | -15.5 | 1.16 | 1.65 |
| 2019-10 | 20 | 35.0% | 24.7% | 10.3 | 1.70 | 2.22 |
| 2019-11 | 18 | 38.9% | 31.8% | 7.1 | 1.87 | 1.72 |
| 2019-12 | 9 | 25.0% | 45.5% | -20.5 | 2.31 | 1.45 |
| 2020-01 | 9 | 22.2% | 22.0% | 0.3 | 1.46 | 2.16 |
| 2020-02 | 11 | 40.0% | 40.0% | 0.0 | 1.81 | 1.25 |
| 2020-03 | 4 | 25.0% | 26.3% | -1.3 | 2.19 | 1.71 |
| 2020-04 | 23 | 42.9% | 27.8% | 15.0 | 1.51 | 1.10 |
| 2020-05 | 28 | 29.6% | 30.2% | -0.6 | 1.25 | 2.08 |
| 2020-06 | 20 | 27.8% | 30.9% | -3.2 | 1.39 | 2.05 |
| 2020-07 | 18 | 33.3% | 35.6% | -2.2 | 1.74 | 2.30 |
| 2020-08 | 12 | 58.3% | 44.1% | 14.3 | 1.69 | 0.99 |
| 2020-09 | 36 | 22.9% | 33.7% | -10.9 | 1.55 | 2.77 |
| 2020-10 | 24 | 29.2% | 37.0% | -7.8 | 1.71 | 3.50 |
| 2020-11 | 17 | 35.3% | 40.7% | -5.4 | 1.44 | 1.02 |
| 2020-12 | 19 | 31.6% | 28.3% | 3.3 | 2.20 | 1.83 |
| 2021-01 | 23 | 31.8% | 38.7% | -6.9 | 1.66 | 1.26 |
| 2021-02 | 13 | 38.5% | 27.0% | 11.5 | 1.92 | 0.90 |
| 2021-03 | 26 | 25.0% | 29.9% | -4.9 | 1.80 | 1.52 |
| 2021-04 | 21 | 28.6% | 38.5% | -9.9 | 1.46 | 2.14 |
| 2021-05 | 20 | 30.0% | 42.0% | -12.0 | 1.40 | 2.76 |
| 2021-06 | 13 | 15.4% | 27.6% | -12.2 | 1.14 | 1.57 |
| 2021-07 | 25 | 39.1% | 37.8% | 1.3 | 1.73 | 1.52 |
| 2021-08 | 22 | 23.8% | 38.9% | -15.1 | 1.43 | 1.61 |
