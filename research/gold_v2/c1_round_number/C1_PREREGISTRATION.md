# C1 — Round-number barrier reaction: preregistration

Frozen before any C1 outcome was computed. The only prior execution was `c1_study.py --dry`, which printed event
counts: development 963 round / 2,167 placebo events; replication 690 / 1,477. Part of the two-hypothesis family in
`../FAMILY_PREREGISTRATION.md` (Holm). Implementation: `c1_study.py` (hash recorded in the family file).

## Mechanism

Order clustering at conspicuous prices:
- take-profit orders cluster **at** round numbers, so trends tend to stop and reverse there (Osler 2003, *JF*);
- gold-specific psychological barriers at round levels (Aggarwal & Lucey 2007, *RFE*).

**Prediction:** at its first interaction with a $50 round level, price reverses away from the level more often than
at a geometrically equivalent non-round level.

## Data

- **Development.** The committed slice `research/gold_v1/history_expansion/h3_replication/data/xauusd_XAUUSDm_M15_h3_replication_slice.csv`
  (`a6a503ff…`). Events have touch-bar time in [2023-01-01 00:00, 2025-12-22 23:00) UTC. Bars from 2022-11-27 23:00
  initialise ATR only.
- **Replication.** `research/gold_v1/history_expansion/repaired/xauusd_XAUUSDm_M15_repaired.csv` (`e4dc5770…`).
  Events have touch-bar time in [2017-06-01, 2021-08-31 22:00). The data end at 2021-08-31 20:45, so no sealed bar
  exists in either input.
- **Missing data.** The frozen session rule applies: a new session starts when bar starts are ≥ 60 min apart. Nothing
  is interpolated, and races stop at the session end.

## Exact definitions

| item | definition |
|---|---|
| round level | L = k × $50 (k integer) |
| **primary placebo** (one construction, fixed) | the level set {k × $50 + 17.30, k × $50 + 32.70}: levels exactly $17.30 above and below every round level. The $50 spacing is identical, the placement is symmetric about the round grid, no level lies on a $5 multiple, and each placebo level is equidistant from its nearest round level on the approach side, whatever the approach direction |
| secondary placebos (robustness only) | offset +17.30 alone; offset +32.70 alone |
| touch / first-touch | bar t is a touch of level L **from below** if close[t−1] < L ≤ high[t], **from above** if close[t−1] > L ≥ low[t]. Only the first such bar per (session, L, approach side) counts. The session's first bar is excluded (it has no in-session prior close). There is no re-arm within a session; a new session re-arms every level |
| approach direction | from below (+1) or from above (−1); both are pooled in the primary |
| minimum distance travelled | none (no extra degree of freedom). Comparability comes from the placebo sharing the same bars and grid geometry |
| event timestamp | the touch bar t |
| reference price | the level L itself |
| risk normalisation | d = Wilder ATR(14) of bar t−1, known before the touch |
| race | reversal target = L − side × d; continuation target = L + side × d |
| touch-bar resolution | if bar t reaches the reversal target, the result is `ambiguous` (the extreme may precede the touch). If bar t reaches **only** the continuation target, the result is `continuation` (unambiguous, because price had to cross L) |
| later bars | bars t+1 … t+32 of the same session. A bar reaching both targets is `ambiguous`; the first single hit decides; none is `unresolved`. The session end also gives `unresolved` |
| duplicates | one event per (session, level, side). Round and placebo levels never coincide (placebo levels are never multiples of $50) |
| validity | no event is excluded on any post-touch price information; ambiguity and unresolved are classified, not filtered by outcome direction |

## Primary metric (one)

**Δ = P(reversal | round) − P(reversal | primary placebo)**, in percentage points. P(reversal) = reversals /
(reversals + continuations). Ambiguous and unresolved events are excluded identically in both groups and counted.

- **CI.** A session-clustered bootstrap: resample sessions with replacement, 5,000 draws, seed 20260929, 95%
  percentile interval.
- **p-value.** One-sided (H1: Δ > 0), normal approximation Δ / SE_boot. It enters the Holm family.

## Secondary (they cannot rescue a failed primary)

- the conservative variant (ambiguous counted as continuation, both groups);
- Δ by approach side and by year, and leave-one-year-out;
- each secondary placebo offset alone;
- $100 levels vs the primary placebo;
- bars-to-result;
- the cost break-even.

## Power and minimum sample

- **Expected sample.** Development has 963 round events (~27/month) against 2,167 placebo events.
- **Power.** Ignoring clustering, detectable Δ ≈ 2.8 × √(0.25 × (1/963 + 1/2167)) ≈ **5.4 pp**. After the expected
  exclusion of ambiguous and unresolved events, and with clustering, about 6–7 pp. **Power at the 5 pp practical
  threshold is therefore only about 50–60%. This is disclosed now: a true 5 pp effect may be missed.**
- **Minimum usable sample.** ≥ 400 resolved round events in development, else the test is declared underpowered and
  C1 does not pass.

## Cost screening (before outcomes)

- **Horizon.** Up to 32 bars (8 h).
- **Scale.** d = 1 M15 ATR (development medians $1.87 / $2.76 / $4.86 in 2023 / 24 / 25).
- **Spread coverage.** Recorded in development; empty in replication.
- **Burden.** The median spread / ATR is 10.7% / 7.2% / 3.3% by year. A 1:1 fade at d breaks even at
  P(reversal) ≈ 0.5 + median(spread/d)/2 ≈ 52–55%.
- **Consequence.** A structural Δ of +5 pp at a ~50% placebo rate reaches roughly this break-even, so a C1 edge is
  economic only if Δ is at least around the practical threshold.

## Practical threshold

**Δ ≥ +5.0 pp**, the same bar as Gold V1, fixed a priori.

## Pass rules

- **Development: STRUCTURAL PASS**, only if **all** of these hold:
  1. Holm-adjusted rejection within the family (α = 0.05, one-sided);
  2. Δ ≥ +5.0 pp;
  3. Δ ≥ 0 for both approach sides;
  4. every leave-one-year-out Δ > 0;
  5. ≥ 400 resolved round events.
- **Cost plausibility** (development, recorded spread). The point estimate P(reversal | round) must be ≥
  0.5 + median(spread/d)/2. If it is not, C1 is *structural but not economic* and does not proceed to strategy work.
- **Replication** (repaired 2017-06 → 2021-08; identical code and parameters; runs only after a development pass).
  It **PASSES** only if one-sided p < 0.05 (a single confirmatory test), Δ ≥ +5.0 pp, and both approach sides
  Δ ≥ 0. Otherwise **FAILED** (Δ ≤ 0) or **INCONCLUSIVE**, and C1 is closed without rescue.
- **Forbidden after outcomes:**
  - other grids ($25, $10, $100-only as primary);
  - touch-depth, wick or body rules, or "strong touches";
  - session, side or year subsets;
  - a different d or horizon;
  - a different placebo.
