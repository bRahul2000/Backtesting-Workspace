# Gold V2 round 2 — results (A: round-number continuation · C: Gold-vs-USD residual reversal)

**Bottom line.**
- **A: INDEPENDENT FIRST CONFIRMATION PASSED.** This is not "confirmed". A was result-generated; this is its first
  independent test.
- **C: FAILED** at development and is closed. No replication was run and there is no rescue.
- **Work stops at the hard gate.** A would need a sealed sample for final confirmation, and that requires Rahul's
  approval. No sealed data was read.

All numbers come from the frozen code; the frozen preregistrations define every term.

## Frozen items (SHA-256)

| item | SHA-256 |
|---|---|
| `ROUND2_FAMILY_PREREGISTRATION.md` | `a12e4a9ec015f346769ca18f30525ec9b3ea426dd7f118b066549853368e42ee` |
| `a_round_continuation/A_PREREGISTRATION.md` | `fd7c20bb89a2675e82aac12ee592dd1ea3807180ee90bbc4827f2b3731e0d276` |
| `a_round_continuation/A_M1_REPAIR_PREREGISTRATION.md` | `9195817c00e504b1dd3341bfba30320bdd116d220f2332b60e3e678958d79dfa` |
| `a_round_continuation/A_M1_REPAIR_AMENDMENT_1.md` | `a26c71d458823e207a38aa54eda7592f28c367e7388ca61da42f43ffb988d267` |
| `c_usd_residual/C_PREREGISTRATION.md` | `7f30338932269f9df12bfbcc33a6756c4cfd27a5f96b4054b02b7c6a9e659f3d` |
| `c_usd_residual/C_AMENDMENT_1.md` | `e6f3f357374ea0e9dca6c00765a81ec8f8ad8efd81e6549164d6e17448cf0f8f` |
| `round2_family_decision.py` | `d0c4cf059135f24e819de3a073ea46a46f365f0e2a7547e7bcd15d9af6df62ca` |
| `a_round_continuation/a_study.py` | `7a316469481c83cca695a212a47bf67faa56a131c2ab9fb86ff60da56d014c8e` |
| `c_usd_residual/c_study.py` (after amendment C-1; frozen `7b767a81…`) | `1266a33b25b122fc70de11958467ee6281b08a250449d8fb4d8cd03cf6df9edf` |
| repaired M1 payload (local, gitignored) | `3e1ed07a65542ab58b9137af2de2961516f6328b56c708967a5f21326f618d19` |

Round-1 frozen items are unchanged:
- `GOLD_V2_RESEARCH_DESIGN.md` `3d359d11…`
- `FAMILY_PREREGISTRATION.md` `8268bc15…`

## Disclosed amendments (neither touches an outcome definition)

1. **A M1 repair, amendment 1.** The first repair audit failed rule R6 on six gaps: three preregistered outages
   observed at M1 granularity, and three 122-minute New York daily-break variants on 2019-03-11/12/13.
   - The amendment changes **audit matching only**. Known outages now match on the M15 bucket, and M1 break variants
     are defined (last bar 16:30–17:15 New York, first bar 17:45–19:15, ≤ 150 min).
   - The repair rule and its removals are unchanged.
   - The failed audit is preserved as `m1_repair_audit_run1_FAILED.json`, and the rerun passed.
   - Repair: 1,523,802 → 1,523,635 M1 bars (167 one-bar Sunday 00:00 artifacts removed; timestamps only).
2. **C, amendment C-1.** The day-cluster bootstrap mixed datetime and date keys, so every statistic was NaN.
   - The fix uses string day keys.
   - Events and controls were verified **byte-identical** before and after the fix, and Δ is unchanged.
   - Only the CI and p-value became computable.

## A — round-number continuation (repaired XAUUSDm M1, 2017-06 → 2021-08)

| metric | round $50, from above | placebo ±$17.30 |
|---|---|---|
| continuation / reversal / ambiguous / unresolved | 199 / 141 / 34 / 3 | 362 / 372 / 73 / 7 |
| P(continuation), resolved | **58.5%** (n = 340) | **49.3%** (n = 734) |

- **Primary result.** Δ = **+9.21 pp**, 95% session-clustered CI **+2.97 … +15.23**, one-sided p = **0.0019**.
- **Replication of the origin.** The originating 2023–2025 C1 observation was about +9.9 pp, so this is effectively
  the same size.
- **Pass rules — all true:**
  - Holm rejection (0.0019 ≤ 0.025);
  - Δ ≥ 5 pp;
  - ≥ 300 resolved round events (340);
  - every leave-one-year-out Δ > 0: 2017 +7.0, 2018 +8.6, 2019 +8.1, 2020 +13.3, 2021 +10.4.

### Non-decisional robustness (preregistered list; nothing added)

| check | Δ pp | 95% CI |
|---|---|---|
| conservative: ambiguous counted as reversal | +8.4 | +2.4 … +14.2 |
| placebo +32.70 offset alone | +12.2 | +5.3 … +19.2 |
| placebo +17.30 offset alone | +5.7 | −1.9 … +13.3 |
| $100 levels only | +11.2 | +3.5 … +18.8 |
| from below (buy-stop side) | **−5.9** | −12.2 … +0.6 |
| both sides pooled | +1.6 | −1.0 … +4.1 |
| by year: 2017 (n = 20) / 2018 / 2019 / 2020 / 2021 | +36.7 / +10.7 / +14.9 / +3.0 / +4.4 | wide; only 2017 excludes 0 |

**Reading.**
- **Robust:** the from-above effect survives the conservative ambiguity treatment, the $100 subset and the +32.70
  placebo.
- **Weak placebo:** against the +17.30 placebo alone the effect is weaker, and that CI includes 0.
- **The mechanism is not supported symmetrically.**
  - The stop-cascade story predicts continuation from **both** sides.
  - Yet touches from below show *less* continuation than placebo (−5.9 pp), and the pooled effect is about zero.
  - The surviving effect is therefore **one-sided** (downward through round levels). Its causal story is less
    secure than the preregistered mechanism.
- **Year profile.** The effect is smaller in 2020–2021 (+3.0 and +4.4 pp individually, both below the 5 pp bar),
  though every leave-one-year-out estimate stays positive.

### Cost plausibility (scenario only; 2017–2021 spreads are not recorded)

- **Scenario.** The 2026 tick median spread ($0.264) against the 2017–2021 median d ($1.93) gives spread/d = 13.7%.
  A 1:1 continuation race then breaks even at P(continuation) ≈ **56.8%**.
- **Observed.** P(continuation) at round levels is 58.5%, a margin of **+1.7 pp**.
- **Why this is not a trade edge:**
  - The binomial SE for n = 340 is about 2.7 pp, so the break-even lies well inside its uncertainty.
  - Under the conservative ambiguity treatment, P = 53.2%, which is **below** break-even.
  - The scenario excludes slippage at a stop-triggered level, which is exactly where slippage is worst.
- **Conclusion.** Δ versus placebo is a **structural** finding. As a standalone 1:1 trade at the touch it is **not
  economically established**: at best marginal, plausibly negative after costs.
- **Design choice needed.** Turning it into a strategy would need a material design choice (entry, stop and target
  geometry). That choice is outside this preregistration and is a Rahul decision.

### Reproducibility

- Reran `a_study.py`, `c_study.py dev` and `round2_family_decision.py`.
- All outputs are **byte-identical**: events, result.json, controls and the family decision.

## C — Gold-vs-USD residual reversal (DXYm primary, development 2023–2024)

- **Primary result.** Δ = **−0.187 σ**, CI −0.552 … +0.218, one-sided p = **0.828**, n = 614 paired events.
  - Of the 766 events, 152 had no matched control in the frozen pool and are excluded by the frozen code. This is
    disclosed.
  - For 575 events the size tolerance had to be relaxed to ±30%.
- **Pass rules.** The threshold was 0.224 σ, frozen formula.
  - Up-moves: −0.747 σ. Down-moves: +0.282 σ.
  - Leave-one-year-out: excluding 2023 −0.239, excluding 2024 −0.134.
- **Decision: FAILED** (Δ ≤ 0). Only the ≥ 500-events rule held. **C is closed; the replication was not run** (it
  requires a development pass).
- **USDJPYm secondary (non-decisional).** Δ = −0.676 σ, CI −1.071 … −0.286. The direction is the same (no residual
  reversal) and the result cannot change the decision.

## Holm (α = 0.05, one-sided, two tests)

| test | p | Holm threshold | decision |
|---|---|---|---|
| A | 0.0019 | 0.025 | **reject** → INDEPENDENT FIRST CONFIRMATION PASSED |
| C | 0.8281 | 0.05 | not rejected → FAILED, closed |

## Sealed-data status and the gate

- **Never read:**
  - 2021-09-01 → 2022-11-26 (historical holdout);
  - 2026-06-03 → 2026-07-26 (Validation);
  - 2026-07-27 → 2026-09-18 (Final OOS).
- **How that is enforced.** Exports refused sealed bars, and `v2_data.is_sealed` skips lines before they are parsed.
- **Only candidate for a final A confirmation: the 2021-09 → 2022-11 holdout.**
  - The 2026 windows are too short to test on (about 8 weeks each).
  - The estimate below uses unsealed event rates only (about 80 resolved round and 173 placebo events per year).
    The holdout would give about **100 round / 215 placebo** resolved events.
  - Power is roughly 45% at the observed Δ = 9.2 pp and roughly 20% at 5 pp.
  - A's own "≥ 300 resolved round events" rule **cannot** be met there.
  - A sealed confirmation would therefore need a new pre-specified rule. Given the low power and the weak cost
    picture above, **opening the holdout may not be worthwhile.** That is Rahul's decision.
