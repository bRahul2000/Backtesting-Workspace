# H3 replication #2 — interpretation (written after the result)

This file was written by hand after the frozen run. It changes nothing: the preregistered classification is
**FAILED TO REPLICATE**.

## The result

- **Primary.** On 1,007 independent events from 2017-06 to 2021-08, frozen H3 reached +2R before −1R **33.2%** of the
  time. Its matched controls did so **33.2%** of the time. The lift is −0.05 pp, 95% CI −3.2 … +3.3. H3 is at or
  slightly below the controls at every target: +1R −0.9, +3R −1.3, +4R −1.5 pp.
- **Precision.** The sample was large enough to detect about ±4.5 pp. The CI now rules out a true +2R lift above about
  +3.3 pp in this era, which is below the +5 pp practical bar and below replication #1's +4.5 pp point estimate.
- **Stability.** There is no stable pattern to rescue:
  - years: 2018 +4.1 and 2019 +2.3, but 2017 −1.7, 2020 −1.0 and 2021 −6.5;
  - sides: long +2.2, short −2.1;
  - months: 25 positive, 25 negative, 1 zero;
  - leave one year out: −1.4 to +1.2 pp.
- **Excursions.** Median MFE32 is slightly above the controls' (1.74 vs 1.62), but median MAE32 is worse (1.87 vs
  1.54). Continuation does not dominate the adverse side.

## The evidence path

| sample | events | +2R lift | 95% CI |
|---|---|---|---|
| development (selected as best of 5 hypotheses) | 77 | +7.6 | −4.8 … +21.1 |
| replication #1 (2023–2025) | 526 | +4.5 | +0.04 … +9.1 |
| replication #2 (2017–2021) | 1,007 | −0.1 | −3.2 … +3.3 |
| independent synthesis (#1 + #2, fixed effect) | 1,533 | +1.5 | −1.2 … +4.1 |

The estimate shrinks with each independent sample, which is the classic signature of a selection effect.
Heterogeneity between the two replications is moderate (I² = 61%, Q = 2.6 on 1 df, p ≈ 0.11).

That leaves two readings, and this data cannot choose between them:
- **A regime-dependent effect:** it existed in 2023–2025 but not in 2017–2021.
- **Noise:** replication #1's borderline +0.04 pp lower bound was chance.

Either way, the confirmatory test that was designed to settle it did not show a persistent structural edge, and the
pooled independent estimate is well below the +5 pp practical bar.

## What this does not do

- It does not look at the reserved 2021-09 → 2022-11 holdout, the 2026 Validation or the Final OOS. All stay sealed.
- It does not modify H3, search year, side or month filters, or proceed to strategy or cost work.

Stopped for review.
