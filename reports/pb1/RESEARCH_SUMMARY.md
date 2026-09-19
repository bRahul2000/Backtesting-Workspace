# PB1 v1 — Research Summary and Closure

**Strategy:** `BTC_PB1_SHALLOW_PULLBACK_V1` · BTC PB1 — Shallow Trend Pullback Continuation
**Final status:** `REJECTED`
**Rejection reason:** REJECTED — DEVELOPMENT cross-regime robustness failure.
**Closed on evidence from:** DEVELOPMENT 2021-01-01 .. 2023-12-31 only.

PB1 showed a localized, repeatable signal. It was rejected because no configuration
of it was robust across the three DEVELOPMENT years — not because the hypothesis was
baseless or the work was wasted. The source, parameter schema and defaults are
preserved unchanged so every historical PB1 result remains reproducible.

---

## Hypothesis

A strong trend impulse, followed by a shallow and controlled retracement, followed by
a continuation trigger, should produce a tradeable continuation edge on BTCUSD M15
with H1 trend context. Structurally distinct from the frozen A4 (EMA/structure-touch
pullback) and T3 (breakout) components: PB1's setup is defined by a *measured* impulse
and a *bounded percentage retracement of that specific impulse*, not by touching a
moving average or breaking a prior swing.

## Baseline (Phase A / A.1)

Untouched defaults, DEVELOPMENT 2021-2023:

| Metric | Value |
|---|---|
| Closed trades | 810 |
| Profit factor | 0.9267538477539468 |
| Avg R | -0.05081890315227994 |
| Total R | -41.16 |
| Max drawdown | 8.41% |
| Win rate | 23.21% |

Phase A.1 hardened the research instrumentation before any optimization: the parameter
fingerprint was hashing an empty override mapping rather than the effective
configuration; MFE/MAE were normalized by a quantity-scaled dollar risk instead of the
price distance to stop; and entries were not reconciled against closed trades and
positions still open at a segment boundary. Baseline execution results were unchanged
by those fixes, confirmed by exact reproduction.

## Phase B.1 — Core structure search (DEVELOPMENT only)

Grid over four core-structure parameters: impulse minimum range, pullback retracement
bounds, confirmation minimum body. 144 candidates, all executed, all fingerprints
unique.

- 26 / 144 candidates with PF > 1 and Avg R > 0
- 18 / 144 met the full viability screen (≥300 trades, ≥8 trades/month, PF > 1, Avg R > 0, DD ≤ 10%)
- **0 / 18 were profitable in every DEVELOPMENT year**
- **All 18 viable candidates were negative in 2022**; all 18 were positive in 2023; only 6 were positive in 2021
- Every viable candidate shared `impulse_minimum_range_atr = 1.8` and `pullback_maximum_retracement_percent = 0.35`

The profitable region was narrow and boundary-sensitive: locally stable by
neighbourhood robustness, but occupying one corner of the tested space, with the
pullback ceiling pinned at the tightest value tested.

## Phase B.2 — Regime failure diagnosis (DEVELOPMENT only)

Diagnosed why the three B.1 stable-region representatives fail in 2022.

A coherent, repeatable failure signature was identified. In all three representatives,
2022's losing trades travel *further* before failing than in 2021 or 2023 (median MFE
0.55-0.60R vs 0.33-0.40R), are least likely to be rejected immediately, and are most
likely to reach 2R of a 3R target and then stop out. **2022 is a false-continuation
regime, not a no-signal regime.**

No stable signal-time condition repaired it:

- Of twelve candidate features, **zero** separated winners from losers with a
  consistent sign across all three years.
- Of 48 screened quartile buckets, exactly one was positive in every
  representative-year cell — a narrow middle band of M15 ATR relative to its 24h mean,
  whose immediate neighbours flip sign between years.
- A three-threshold probe on that feature **relocated the failure rather than removing
  it**: the loosest threshold left 2022 negative for two representatives, while tighter
  thresholds fixed 2022 but turned 2021 negative in all three.

Direction dependence was unstable: the bleeding side in 2022 differed by
representative (one long-driven, one short-driven, one mixed) and flipped between
years within a representative.

Classification recorded: **B — REGIME DEPENDENCE UNRESOLVED**.

## Phase B.3 — Exit horizon sensitivity (DEVELOPMENT only)

Tested whether the fixed 3R target itself was mismatched. Four predeclared targets
(1.5R / 2.0R / 2.5R / 3.0R) across the same three representatives — 12 runs.

- Avg R rises **monotonically** with the target for all three representatives.
- **3.0R produced the best overall Avg R for all three representatives.**
- 1.5R lost money in every case (PF 0.86-0.89).
- **0 / 12 representative-target combinations were positive in all three DEVELOPMENT years.**
- 2.0R and 2.5R improved parts of 2022 for every representative, but reduced overall
  expectancy, gutted 2023, and flipped one representative's 2021 negative.

Trade-level matching explained the result exactly: at 2.0R one representative converted
31 losers into winners but paid 1R on each of the 105 trades that would have reached 3R
anyway. No comparison ever turned a winner into a loser. PB1's edge lives in the tail,
not the body — actual win rates clear the theoretical gross break-even line by a
widening margin as the target lengthens.

Classification recorded: **B — EXIT HORIZON HELPS BUT REMAINS FRAGILE**.

---

## What PB1 established (keep these lessons)

- **Impulse ≈ 1.8 ATR was the strongest local region.** The marginal response is
  hump-shaped with a genuine interior peak at 1.8, degrading at both 1.5 and 2.1 — not
  an artifact of the search boundary.
- **Tighter shallow pullbacks performed better locally.** A retracement ceiling of 0.35
  dominated 0.45 and 0.55 throughout the grid.
- **3R remained superior to shorter fixed targets.** The exit horizon is not the
  weakness; shortening it destroys more on the winners than it rescues on the losers.
- **False continuation is a repeatable, measurable failure signature.** It replicated
  across three independent representatives and is detectable from MFE distributions.

## Why PB1 v1 was rejected

- **No configuration was robust across 2021 / 2022 / 2023.** Not one of the 144 B.1
  candidates, nor any of the 12 B.3 representative-target combinations.
- **The 2022 failure persisted throughout the viable structural region** — all 18
  viable candidates were negative in 2022, so it is a property of the structure, not of
  one unlucky parameter choice.
- **Simple regime filters relocated rather than removed the failure.** Tightening a
  volatility condition moved the losing year from 2022 to 2021.
- **Direction dependence was unstable** across both representatives and years, so no
  directional specialization was justified.
- **Exit modification did not solve the problem.** The best available target was the
  one already in use.

The hypothesis showed **localized signal but insufficient cross-regime robustness**.

---

## Data-exposure record

Preserving the research chronology precisely:

| Phase | Data used |
|---|---|
| Phase A / A.1 | DEVELOPMENT 2021-2023, **and** the frozen baseline evaluated once on VALIDATION 2024 after all parameters were frozen in code |
| Phase B.1 | DEVELOPMENT 2021-2023 only |
| Phase B.2 | DEVELOPMENT 2021-2023 only |
| Phase B.3 | DEVELOPMENT 2021-2023 only |

- **2025-2026 FORWARD_VALIDATION was never used for PB1 development at any point.**
- The Phase A VALIDATION 2024 result exists in the record, but **no 2024 result was
  used to justify this rejection**. The decision rests entirely on DEVELOPMENT
  evidence: cross-year robustness failed inside 2021-2023 alone.

## Governance

`BTC_PB1_SHALLOW_PULLBACK_V1` is registered `REJECTED`. The platform's existing status
guards refuse to start new research workflows for it:

- `research.optimizer.guard_optimization` — refuses REJECTED strategies.
- `research.walk_forward.guard_walk_forward` — refuses REJECTED strategies.

Both are mirrored in the Research Lab UI so the controls are disabled rather than
failing on submit. Historical PB1 results stay readable: `run_universal_backtest`
applies no status guard, the universal workspace exposes rejected strategies behind its
"Show rejected/research history" toggle, and the Phase A/B reports and optimizer store
are unmodified.

## Artifacts

| Phase | Commit | Reports |
|---|---|---|
| A — baseline | `4f93812` | `phase_a_development_summary.json`, `phase_a_validation_2024_summary.json` |
| A.1 — integrity hardening | `c10b837` | (same reports, corrected) |
| B.1 — structure search | `9d2839c` | `phase_b1_report.json`, `phase_b1_candidate_metrics.json` |
| B.2 — regime diagnosis | `852c3c5` | `phase_b2_report.json`, `phase_b2_trades.csv` |
| B.3 — exit horizon | `d3c5489` | `phase_b3_report.json` |

Research tag: `btc-pb1-v1-rejected`.
