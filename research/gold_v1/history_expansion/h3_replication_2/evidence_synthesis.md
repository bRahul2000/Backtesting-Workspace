# H3 evidence synthesis (secondary, descriptive)

Written by `synthesis.py` after the standalone replication #2 outputs were frozen. The standalone replication #2
result in [report.md](report.md) remains primary. Development is shown for comparison only and **is never pooled**.

## Side by side

| study | events | +1R | +2R | +3R | +4R | control +2R | +2R lift (pp) | 95% CI | MFE32 med (H3 / ctrl) | MAE32 med (H3 / ctrl) | long / short lift (pp) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| development 2025-12-23 → 2026-06-02 (not pooled) | 77 | 55.8% | 41.3% | 31.5% | 23.2% | 33.8% | +7.6 | -4.8 … +21.1 | 1.93 / 1.57 | 1.36 / 1.53 | +7.9 / +7.6 |
| replication #1 2023-01 → 2025-12 | 526 | 52.2% | 36.8% | 28.2% | 21.1% | 32.3% | +4.5 | +0.0 … +9.1 | 1.88 / 1.66 | 1.74 / 1.65 | +4.5 / +4.4 |
| replication #2 2017-06 → 2021-08 | 1007 | 49.8% | 33.2% | 23.8% | 17.4% | 33.2% | -0.1 | -3.2 … +3.3 | 1.74 / 1.62 | 1.87 / 1.54 | +2.2 / -2.1 |

## Independent-replication synthesis (replication #1 + replication #2 only)

The method was preregistered: fixed-effect inverse-variance pooling of the two standalone +2R lifts. Each study's
SE is its bootstrap-CI half-width divided by 1.96.

| estimate | +2R lift (pp) | 95% CI |
|---|---|---|
| replication #1 (2023–2025), 526 events, weight 34% | +4.49 | +0.04 … +9.09 |
| replication #2 (2017–2021), 1007 events, weight 66% | -0.05 | -3.17 … +3.25 |
| **fixed-effect pooled**, 1533 independent events | **+1.47** | **-1.15 … +4.09** |
| random-effects (DerSimonian–Laird), sensitivity | +1.92 | -2.49 … +6.34 |

Heterogeneity: Cochran Q = 2.57 (1 df), I² = 61%, τ² = 6.30. Both study estimates are shown so the
pooled figure cannot hide disagreement between them.

This synthesis is secondary and descriptive. It does not change the standalone classification of replication #2,
it does not use development, and it does not authorize strategy construction.
