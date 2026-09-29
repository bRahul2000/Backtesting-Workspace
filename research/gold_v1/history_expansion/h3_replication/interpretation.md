# H3 replication — interpretation (written after the result)

This file was written by hand **after** the frozen run. It adds context to `report.md`, which is the unedited output
of the preregistered runner. It changes nothing in the decision: **INCONCLUSIVE**.

## What survived

- **Sign.** The pooled +2R lift is **+4.5 pp** (H3 36.8% vs controls 32.3%, 511 vs 2,529 resolved). The +3R and +4R
  lifts are +5.0 and +4.0 pp. All three calendar years are positive, and long (+4.5) and short (+4.4) are almost
  identical.
- **Continuation.** Median MFE is higher than the controls' at every horizon: at 32 bars, 1.88R vs 1.66R.
- **Months.** 24 of 36 months are positive at +2R.

On 526 events from three years that were never seen before, this is the first time any Gold V1 hypothesis kept its
sign out of sample.

## What did not survive

- **Magnitude.** The lift fell from +7.6 pp in development to **+4.5 pp**, below the preregistered practical bar of
  +5 pp (test b). A smaller replication effect is what a best-of-five selection (H1–H5) would predict.
- **Uncertainty.** The 95% CI is **+0.04 … +9.1 pp**. The lower bound clears zero by 0.04 pp, which is within the
  Monte Carlo noise of a 5,000-sample bootstrap. Test (a) is a pass on paper, but it is not robust evidence on its own.
- **Year concentration.** 2023 +0.7 pp, 2024 +9.0 pp, 2025 +3.7 pp. Without 2024 the pooled lift is +2.3 pp, still
  positive (test c2 passes) but small.
- **Shape of the effect.** In development the +1R lift was +7.2 pp. In replication it is **+0.7 pp**: the
  near-term follow-through did not reproduce, and the residual effect sits at 2–4R.
- **Adverse excursions.** Median MAE at 32 bars is slightly *larger* than the controls' (1.74R vs 1.65R). MFE
  improves, but so does the adverse tail.
- **Excluded or flagged events.** 18 events are ambiguous at some target, and 57 events carry the hole flag. Both are
  provenance only; nothing was excluded.

## Indicative costs (not a strategy test)

- **Spread is a larger share of risk here.** Median spread/risk is **4.1% of 1R**, against 1.9% in development.
  Stops are smaller in USD at 2023–2025 price levels, while the spread field stays near 0.16–0.20.
- **The margin over costs is thin.** As a gross +2R race, 36.8% implies about +0.10R per event before costs, and
  roughly +0.06R after the indicative median spread. The controls are about −0.03R. This is arithmetic on the reported
  rates, not a cost-inclusive simulation. It only shows that the margin over costs is thin.

## Power for the options under review (facts, no recommendation)

The replication rate is about 0.68 events per session, and the control rate is about 32%.

| sample | approx. events | detectable lift (80% power) |
|---|---|---|
| this replication | 526 | ±6.3 pp |
| reserved holdout 2021-09-01 → 2022-11-26 (320 sessions) | ~220 | ±9.7 pp |
| 2026 Validation (46 sessions) | ~31 | ±26 pp |
| needed to detect a true +4.5 pp at 80% power | ~1,000 | — |

Neither sealed sample could confirm or refute a +4.5 pp effect on its own.

## Status

Stopped for review, as required. No filter, parameter, month, year, side or session variant was examined. The
reserved holdout, the 2026 Validation and the Final OOS remain sealed.
