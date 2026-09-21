# BTC Final Candidate Validation — T3 SHORT @ 2.00R, Locked HOLDOUT

## FINAL OOS DECISION: **REJECT T3 2.0R**

The candidate failed one of the four locked gates: **profit factor 1.0889 against
a required 1.10**. The other three passed. Per the predeclared rule, the
candidate is rejected and nothing about it is adjusted.

---

## 1. Predeclared configuration

Committed at **`43ddb05`, before the holdout was opened**, so the gates exist in
history ahead of the results.

| | |
|---|---|
| Entry architecture | frozen T3 SHORT, unchanged |
| Stop | frozen T3 structural stop, unchanged |
| Filters | all frozen T3 filters, unchanged |
| Reward multiple | **fixed 2.00R** (selected on DEVELOPMENT in Architecture Reset A) |
| Risk per trade | 0.25% of running balance |
| A4 | not part of the candidate |
| Dataset | `data/exness/btc/phase_r1/processed/btcusdm_M15.csv`, fingerprint `80735a2cf521…` |
| Holdout window | 2025-07-01 00:00 → 2026-09-20 07:15 UTC |

**Locked gates:** PF ≥ 1.10 · Avg R > 0 · total R > 0 · Max DD < 4%.
Everything else — frequency, win rate, streaks, monthly and subperiod
breakdowns, MFE/MAE and the four execution-stress arms — is recorded as a
diagnostic and has no path to the verdict. `apply_gates()` receives only the
native holdout summary.

## 2. Development reference and reproduction guard

The harness re-ran the DEVELOPMENT arm first and would have refused to open the
holdout had it not matched. It matched exactly:

| metric | observed | Reset A reference |
|---|---|---|
| trades | 88 | 88 |
| profit factor | 1.2595728 | 1.2596 |
| Avg R | +0.1596092 | +0.1596 |
| total R | +14.0456 | +14.05 |
| Max DD | 1.4598% | 1.46% |

## 3. Holdout results — native

| metric | value |
|---|---|
| trades | **85** |
| trades/month | **6.03** |
| win rate | **35.29%** |
| **profit factor** | **1.0889** |
| Avg R | **+0.0596** |
| total R | **+5.07** |
| PnL | **+122.93** |
| **Max drawdown** | **2.51%** |
| longest losing streak | **7** |
| positive / negative months | **6 / 7** |

Degradation from development, for context only: PF 1.2596 → 1.0889, Avg R
+0.1596 → +0.0596 (−63%), trades/month 4.82 → 6.03.

## 4. Monthly and subperiod stability

| month | trades | total R | | month | trades | total R |
|---|---:|---:|---|---|---:|---:|
| 2025-08 | 9 | +3.00 | | 2026-02 | 12 | −3.00 |
| 2025-09 | 5 | −2.00 | | 2026-03 | 1 | +2.00 |
| 2025-10 | 3 | −3.00 | | 2026-04 | 1 | −0.78 |
| 2025-11 | 16 | +5.00 | | 2026-05 | 6 | +3.00 |
| 2025-12 | 5 | +1.00 | | **2026-06** | **17** | **+7.00** |
| 2026-01 | 6 | −3.15 | | 2026-08 | 2 | −2.00 |
| | | | | 2026-09 | 2 | −2.00 |

**June 2026 alone is +7.00R against a +5.07R holdout total — 138% of the
result.** Remove that single month and the holdout is negative. Seven of
thirteen months are losers.

**Quarterly:** 2025Q3 +1.00 · 2025Q4 +3.00 · 2026Q1 **−4.15** · 2026Q2 **+9.22**
· 2026Q3 **−4.00**. One quarter carries the entire out-of-sample result.

**Subperiods:**

| period | trades | total R | PF | win rate | DD |
|---|---:|---:|---:|---:|---:|
| 2025 H2 | 38 | +4.00 | 1.1636 | 36.84% | 2.73% |
| 2026 H1 | 43 | +5.07 | 1.1869 | 37.21% | 1.81% |
| 2026 partial (Jul–Sep) | 4 | **−4.00** | — | **0%** | 1.02% |

## 5. MFE / MAE

Bar-based approximation, as the engine labels it.

| metric | value |
|---|---|
| mean MFE | +1.281R |
| mean MAE | −1.020R |
| median MFE | +1.090R |
| median MAE | −1.056R |
| reached +1R | 45 of 85 (52.9%) |
| reached +2R | 29 of 85 (34.1%) |
| capture efficiency | 30.6% |

MFE exceeds MAE, and 34.1% of trades reached the 2R target — above the 33.33%
break-even for a 2R payoff, which is why total R is positive at all. The margin
is 0.8 percentage points.

## 6. Execution stress — diagnostics only

These do not affect the verdict.

| arm | trades | win rate | PF | Avg R | total R | Max DD |
|---|---:|---:|---:|---:|---:|---:|
| **native** | 85 | 35.29% | **1.0889** | +0.0596 | +5.07 | 2.51% |
| spread ×1.10 | 85 | 35.29% | 1.0889 | +0.0596 | +5.07 | 2.51% |
| spread ×1.20 | 84 | 34.52% | 1.0523 | +0.0365 | +3.07 | 2.51% |
| slippage 0.02% | 82 | 31.71% | **0.8852** | −0.0766 | **−6.28** | 2.57% |
| spread ×1.20 + slippage 0.02% | 82 | 31.71% | **0.8852** | −0.0766 | **−6.28** | 2.57% |

The spread multiplier barely moves the result — consistent with Phase C's
finding that T3 is short-only with pending stop entries, so the spread only
decides whether a fixed level is touched. A 0.02% slippage assumption inverts
the sign.

## 7. Pass/fail gate table

| gate | required | observed | result |
|---|---|---|---|
| Profit factor | ≥ 1.10 | **1.0889** | **FAIL** |
| Avg R | > 0 | +0.0596 | PASS |
| Total R | > 0 | +5.0693 | PASS |
| Max drawdown | < 4% | 2.5149% | PASS |

**1 of 4 gates failed → REJECT.**

The profit-factor miss is **0.011**, and it is worth saying plainly that this is
narrow. It is not being reinterpreted. The gate was fixed at 1.10 and committed
before the data was read precisely so that a near miss could not be argued into
a pass afterwards; a threshold that moves when the result lands just under it is
not a threshold. The diagnostics point the same way rather than the other:
138% of the result comes from one month, one quarter carries the whole thing,
seven of thirteen months are negative, the final subperiod is 0-for-4, and a
0.02% slippage assumption turns +5.07R into −6.28R.

## 8. Confirmation that no OOS tuning occurred

- **One** configuration was run on the holdout. `holdout_configurations_run: 1`.
- **Zero** alternative reward multiples were tested out of sample.
  `alternative_reward_multiples_tested_on_holdout: 0`. A test asserts no target
  grid exists in the validation module.
- The gates were committed at `43ddb05` **before** the run that produced these
  numbers, and are pinned literally by `test_the_four_gates_are_exactly_the_declared_ones`.
- No T3 entry parameter, filter, slope threshold, body threshold, structure
  lookback, stop rule or reward multiple was altered before, during or after the
  holdout run. The frozen T3 source is byte-identical, hash
  `4c4ab845852ff973530f30ebee86061ea72bd29d68ff6165970dd5a9efde7910`.
- The holdout was opened once, after the DEVELOPMENT reference reproduced
  exactly.

**No modification to the candidate is proposed here.** The next decision is
yours; the locked rule for this outcome was REJECT, and that is what is recorded.

---

**Frozen hashes unchanged:** A4 `55fedf85…`, T3 `4c4ab845…`, Core `631374d5…`.
Frozen sources, Stage 3/4/5, MT5 and all prior research untouched.
