# Gold V2 round-2 hypothesis family — preregistration

Frozen before **any** outcome of A or C. The selection was approved by Rahul: test both A and C as a new
two-primary-test family, with Holm correction. **No further primary hypothesis may be added after outcomes.**

## Members

| id | role | primary test | preregistration | SHA-256 |
|---|---|---|---|---|
| A | round-number continuation, **RESULT-GENERATED** (origin: C1 development 2023–2025); first **independent** test | Δ P(continuation) round − placebo, from above, repaired M1 2017-06 → 2021-08 | `a_round_continuation/A_PREREGISTRATION.md` | `fd7c20bb89a2675e82aac12ee592dd1ea3807180ee90bbc4827f2b3731e0d276` |
| C | Gold-vs-USD residual reversal, **DXYm** primary | paired Δ (event − matched USD-explained control) in gold-σ, development 2023–2024 | `c_usd_residual/C_PREREGISTRATION.md` | `7f30338932269f9df12bfbcc33a6756c4cfd27a5f96b4054b02b7c6a9e659f3d` |

Supporting frozen items:

| item | SHA-256 |
|---|---|
| A M1 repair preregistration | `9195817c00e504b1dd3341bfba30320bdd116d220f2332b60e3e678958d79dfa` |
| A M1 repair amendment 1 (audit matching correction, disclosed) | `a26c71d458823e207a38aa54eda7592f28c367e7388ca61da42f43ffb988d267` |
| repaired M1 (local payload) | `3e1ed07a65542ab58b9137af2de2961516f6328b56c708967a5f21326f618d19` |
| repair summary / audit (PASS) | `e4bc11bf…` / `6b58d84c…` |
| `a_study.py` / `repair_m1.py` / `c_study.py` | `7a316469…` / `69f6e783…` / `7b767a81…` |
| `round2_family_decision.py` (Holm and pass rules) | `d0c4cf059135f24e819de3a073ea46a46f365f0e2a7547e7bcd15d9af6df62ca` |
| `tests/test_v2_round2.py` / `data/v2_data.py` | `e428eb82…` / `7927ead1…` |
| raw snapshot | `data/raw/SHA256SUMS` (82 files), verified before every analysis |

## Multiplicity: Holm across A and C

- **Levels.** α = 0.05, with one-sided p-values as defined in each preregistration. The smaller p must be ≤ 0.025,
  and the larger ≤ 0.05 only if the first rejects.
- **Reporting.** The raw p, the Holm decision, the ordinary 95% CI and the practical threshold with its pass/fail.
- **Secondary checks never become primary.** This covers A's non-decisional robustness and C's USDJPYm proxy.
- **Replication.** C's replication (2025 → 2026-06-02) is a single confirmatory test at one-sided α = 0.05. It runs
  only after a C development pass, with no tuning. A has no unsealed replication sample: a pass is **INDEPENDENT FIRST
  CONFIRMATION PASSED**, and the work then stops before any sealed sample.

## Sealed (never read)

2021-09-01 → 2022-11-26 · 2026-06-03 → 2026-07-26 · 2026-07-27 → 2026-09-18.

## Execution order

1. A first test.
2. C development, then the USDJPYm secondary (non-decisional).
3. `round2_family_decision.py`.
4. C replication, automatically, only if C passes development.
5. Non-sealed robustness and cost work only for passing hypotheses.
6. Stop at the next hard gate.
