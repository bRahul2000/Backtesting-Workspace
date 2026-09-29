# Gold V2 round-1 hypothesis family — preregistration

Frozen before any outcome of either hypothesis was computed. The selection was approved by Rahul, who chose to test
both C1 and C4 as independent families. The half-hour intraday-momentum reserve (C3) stays **untested** and is not
part of this family.

## Members (exactly two primary tests; none may be added after outcomes)

| id | primary metric | preregistration | SHA-256 |
|---|---|---|---|
| C1 | Δ = P(reversal \| round $50) − P(reversal \| symmetric ±$17.30 placebo grid) | `c1_round_number/C1_PREREGISTRATION.md` | `82100cd57757d1ce072f4a2e1154377a6e65be191e557bddad06e96997fc35a9` |
| C4 | E[s·y] − E[s]E[y] (US sign → next-Asia return, ATR units), exact circular-shift null | `c4_session_momentum/C4_PREREGISTRATION.md` | `56677ca777804744e6db43938662ad319f8c3cfd3def854a1ed5f0073c53bf5e` |

| implementation | SHA-256 |
|---|---|
| `c1_round_number/c1_study.py` | `d5d2896c03cd25d474f64cc824764835b9e5867a504599d36f197ac11fa727e6` |
| `c4_session_momentum/c4_study.py` | `6b9e4783b634534d97965f764d80ba5494fe1758d220090d4d9cac0279f3c5bf` |
| `family_decision.py` (Holm + pass rules) | `db7d4ef618fc45368585e06968ae0a378f3dadfaa58dc2ae38b047723b071f7d` |
| development data slice | `a6a503ff479ba34bbe74e9377cec9787f3f3c39061870fdec405e36de09efa4e` |
| replication data (repaired) | `e4dc5770d61949dfbb8aa32d1bf290042be39aca2ddec1795342634ff4855b09` |
| design `GOLD_V2_RESEARCH_DESIGN.md` | `3d359d11ecf322327e263104eef7cab7d4f8a1d9f791aa6c12fbcd43d981ea5f` |

## Multiplicity: Holm across the two primary development tests

- **Levels.** α = 0.05 family-wise, with one-sided p-values as defined in each preregistration.
- **Order.** The smaller p must be ≤ 0.025. Only if it is, the larger p must be ≤ 0.05.
- **Reporting.** The raw p, the Holm decision, the ordinary 95% CI (for effect-size interpretation) and the practical
  threshold, each reported separately.
- **Pass rule.** A hypothesis passes development only if the Holm test rejects **and** every other development rule
  in its own preregistration holds.
- **Replications.** Each is a separate single confirmatory test at one-sided α = 0.05, run only for a hypothesis that
  passed development, with **no parameter change**. There is no "keep the best of two": each hypothesis stands or
  falls on its own gates.

## Data (approved)

- **Development.** 2023-01-01 → 2025-12-22 (warm-up from 2022-11-27 23:00).
- **Replication.** The repaired 2017-06-01 → 2021-08-31.
- **Disclosed reuse.** Gold V1 used both periods for H3 only.
- **Sealed and unread.** The 2021-09-01 → 2022-11-26 holdout, the 2026 Validation and the Final OOS.

## Order of execution

1. C1 development and C4 development: the outputs are written and hashed.
2. `family_decision.py`: Holm and the pass rules.
3. Replication only for hypotheses that passed.
4. Robustness and cost plausibility only for hypotheses that replicated.
5. Strategy research only after replication.

A hypothesis that fails at any gate is closed and not rescued.
