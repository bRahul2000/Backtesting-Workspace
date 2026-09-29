# H3 second independent replication — preregistration (CONFIRMATION)

Frozen 2026-09-29 **before any forward race, control outcome or R-rate was computed on this sample**. The only prior
execution was `run_replication_2.py --detect-only`. It printed detection counts: 1,007 window events (481 long /
526 short) and 5 warm-up events. Those are counts, not outcomes. This file is not edited after the outcome run.

## Hashes (SHA-256)

| item | hash |
|---|---|
| raw_full M15 (immutable evidence) | `4724a019bf2c25c2f03e971034d6986de94174e602c3a15924dc167f3d193e43` |
| raw_full H1 (immutable evidence) | `7de0706efccf16eada36f5e3f26ec255eb9e11eb8407c38a650da6d034fc0bc5` |
| deep-history repair preregistration | `b1720e9b45f135b17dce39f7d4119cbedd4f75ee3c4bfd434b74b46c4c224934` |
| repaired M15 `repaired/xauusd_XAUUSDm_M15_repaired.csv` (the sole input) | `e4dc5770d61949dfbb8aa32d1bf290042be39aca2ddec1795342634ff4855b09` |
| repaired H1 (not used by H3) | `0d1fb20d6e753343ffed0b2fb2547bb8237dd8c87cd5db7fc9fc19b4519d55e0` |
| removal manifest (164 M15 + 164 H1 rows) | `9716c0635ee5aaa989bc598963d480c70d834dd324b8f05bc0ba3fe9848c1428` |
| original H3 preregistration | `c481f8a11da8428df4892d32c9ca3044e292726cb3f0320965f4fcc25339c59e` |
| frozen H3 implementation `h3/h3_study.py` (`h3_features`, `detect`, **`controls`**, `h3_gate`) | `a6c8bb400f83a5af41fa92d63931878098c255f37298203a7aa65238a5262e99` |
| frozen pipeline `h1/h1_study.py` (`features`, `forward`, `wilson`, `trading_days`) | `e2ec68842c142987f4c892727ed00393a372227a7d83ad1d9d6a3b3f03a94369` |
| CI implementation `h1/h1_report.py` (`lift`: event-clustered bootstrap) | `71232d22e49e5ae73c9f3f39dfe63fccc70abb1d8c7aa40206b1c9df0e93d428` |
| runner `h3_replication_2/run_replication_2.py` | `20563d074266963d3f6b2a7c09f507f8d09ac6755757e0b1f314d9b5dbdc5ae4` |
| synthesis `h3_replication_2/synthesis.py` | `2de42aa50b7c1b56266d49cf3c2d1e0168bde9000f22a836a67ab9a1142d683f` |
| replication #1 summary (synthesis input) | `8cdee83b476d161e0e87bc342c933a1b728f357fffddf63848f2f7f013089a4e` |

## Data and intervals

- **Input.** The approved 164-row repair, used exactly: no extra removals, no restorations, no interpolation, no new
  price-based cleaning, and no change to sessions.
- **Warm-up.** 2017-05-01 00:00 → 2017-05-31 (repaired). It initialises ATR(14), the 20-session percentile and the
  other causal state. Warm-up bars are never events, and they are **excluded from the control pool** by masking
  `atr_pct` in a copy of the feature frame. This is identical to replication #1.
- **Eligible events.** The acceptance (signal) bar must fall in **[2017-06-01 00:00, 2021-08-31 22:00) UTC**.
- **Forward-data cutoff.** The data end at **2021-08-31 20:45 UTC**, the last bar before the session that opens the
  sealed 2021-09 holdout. `forward()` stops at the end of the data. A race needing later bars is `truncated` and
  excluded from P(...), and MFE/MAE horizons beyond the data are NaN. No holdout bar can enter any outcome.
- **Never read.** The 2021-09-01 → 2022-11-26 holdout, the 2026 Validation and the 2026 Final OOS.

## Rules and controls (frozen)

- **Rules.** The original H3 preregistration applies, every rule unchanged, via the functions hashed above:
  - an 8-bar same-day compression window at or below the 20th percentile of the trailing 20 sessions; Wilder ATR(14);
  - displacement ≥ 1.5 × ATR[D−1] with body/range ≥ 0.60 in the breakout direction; the box intact until D; D and
    the acceptance bar close beyond the box;
  - entry at the next open; stop at the opposite side of D; one event per structure and direction;
  - the same reset, long/short treatment and missing-hole handling (a new session at gaps ≥ 60 min).
- **Controls.** `h3_study.controls()` is used unchanged, exactly as in development and replication #1:
  - 5 per event, with replacement, seed 20260603;
  - the same session and volatility regime, ATR percentile within ±10 (relaxed only as the function does);
  - more than 8 bars from any event, and not an acceptance bar;
  - the event's direction and risk in ATR units.
- **No adjustments.** Nothing is changed for the 2017–18 session differences, the price level, missing spreads or the
  year.

## Metrics

- **Primary.** P(+2R before −1R | H3) − P(+2R before −1R | matched controls) on all eligible events. Reported as the
  H3 rate, the control rate and the lift in pp with its 95% CI.
- **CI method.** The event-clustered bootstrap `h1_report.lift`: 5,000 resamples of events together with their own
  controls, seed 20260603, percentile interval. The same method is used for every subgroup CI.
- **Secondary** (these never change the decision):
  - +1R, +3R and +4R, each with H3 rate, control rate, lift and CI;
  - MFE and MAE at 4, 8, 16 and 32 bars and until −1R;
  - ambiguous and unresolved counts;
  - risk distribution;
  - provenance flags (descriptive, never excluding): the 20-session lookback contains a repaired pseudo-session
    location; it contains a genuine outage (2018-01-31/02-02, 2018-08-16, 2018-08-27 ×2); or the race lies within a
    day of a weekly-open regime transition (a week whose New York open time differs from the previous week's) or of a
    break-variant day (2017-06-06, 2017-07-11, 2018-09-20, 2019-03-11/12/13).
- **Ambiguous policy.** When a target and −1R fall in one M15 bar, that target is `ambiguous`. It is excluded from
  P(...) for that target and never resolved favourably; counts are reported.
- **End-of-data policy.** `truncated` or `none` at a target is excluded from P(...) for that target, and counted.
- **Reporting.**
  - Year tables for 2017 (June–December only), 2018, 2019, 2020 and 2021 (January to 2021-08-31 22:00). Each year's CI
    uses that year's events with their own controls.
  - Leave-one-year-out, excluding each year in turn; descriptive only.
  - Every month from June 2017 to August 2021, with the counts of positive, zero, negative and undefined months.
  - Long and short, with CIs.
- **Costs.** None. Spread is unavailable for most of the era. This is a structural-edge test, with no invented or
  backfilled spreads and no entry changes.

## Decision gates (fixed now)

- **Gate A, statistical persistence.** It passes only if **all** of these hold:
  - the pooled replication #2 +2R lift is > 0;
  - its 95% CI lower bound is > 0;
  - the long and short +2R point estimates are both ≥ 0;
  - the result does not depend on one calendar year, operationalised as **every** leave-one-year-out pooled +2R
    lift being > 0.
- **Gate B, practical size.** It passes only if the pooled replication #2 +2R lift is **≥ +5.0 pp**. The threshold
  is unchanged.

**Classification**, applied in this order:
1. **FAILED TO REPLICATE** if the pooled +2R lift is ≤ 0.
2. **STRONG REPLICATION** if A and B pass.
3. **PERSISTENT BUT SUB-THRESHOLD** if A passes and B fails. This does **not** authorize strategy construction.
4. **INCONCLUSIVE** otherwise: a positive point estimate, but A fails (the CI overlaps zero, or the side or year
   stability condition fails).

## Synthesis (secondary; run only after the standalone outputs are frozen and hashed)

- **Development** is shown side by side but never pooled.
- **Pooling.** The independent synthesis uses only replication #1 (2023–2025) and replication #2 (2017–2021):
  - the standalone +2R lifts d₁ and d₂;
  - SEᵢ = (CI_hi − CI_lo)/(2 × 1.96) from each study's own bootstrap CI;
  - a fixed-effect inverse-variance estimate with 95% CI;
  - Cochran's Q and I² for heterogeneity;
  - a DerSimonian–Laird random-effects estimate as a sensitivity check.
- **Disclosure.** Both study estimates are always shown next to the pooled figure. The synthesis is descriptive and
  never replaces the standalone replication #2 classification.

## Reproducibility and stop

- **Reproducibility.** The complete run is executed twice from scratch. These outputs must be byte-identical:
  events, controls, yearly, monthly, side, leave-one-year-out, summary, decision_gate, gate and report. SHA-256 hashes
  are recorded.
- **Stop.** After the standalone result and the synthesis, the work stops for review. There is no holdout,
  Validation or OOS access, no H3 change, no filters, no strategy construction and no cost optimisation.
