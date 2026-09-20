# PB3 v1 — Research Summary and Closure

**Strategy:** `BTC_PB3_PIVOT_ACCEPTANCE_LONG_V1` (LONG only; no SHORT component was ever built)
**Final status:** `REJECTED`
**Evidence base:** DEVELOPMENT 2021-01-01 .. 2023-12-31 only.

PB3 v1 is closed after a single Phase A baseline. All parameters, defaults and source
behaviour are preserved unchanged so every historical PB3 result stays reproducible.

---

## Final decision

> **REJECTED — DEVELOPMENT insufficient sample and negative expectancy after opportunity
> expansion.** The confirmed-pivot generator increased frequency relative to PB2 but produced
> only 48 closed trades across 2021–2023, with negative overall expectancy and negative
> results in both 2022 and 2023. The sample does not justify parameter optimization, and the
> added opportunity population did not preserve PB2 LONG's localized selectivity.

## Hypothesis

PB2 showed that a strict reclaim + acceptance gate was doing real selection work on the long
side, but its opportunity generator — a 1.30-ATR displacement through a rolling 12-bar M15
extreme — yielded only 29 LONG trades in three years. PB3 kept the gate and replaced the
generator with a far more common structural event:

    H1 bullish context
    -> break of a *confirmed* M15 swing/pivot high
    -> retest of that actual pivot level
    -> strict reclaim
    -> strict next-bar acceptance
    -> stop entry above the acceptance bar

**Research question:** can structural opportunities be materially increased *without*
weakening the proof-of-acceptance gate?

## Architecture

| Stage | Rule |
|---|---|
| H1 context | H1 EMA50 > EMA200 (ordering only; separation and both slopes measured, unfiltered) |
| Structure | latest **confirmed** M15 pivot high, left 2 / right 2, at most 24 bars old |
| Breakout | bullish, close > pivot high, range >= 1.00 ATR, body >= 60% of range, close in upper 30% |
| Duplication | one confirmed pivot may generate at most one structure attempt, ever |
| Retest | within 6 completed bars, bar low <= pivot level + 0.15 ATR (the level itself, not a percentage retracement) |
| Invalidation | completed close < breakout candle low, or the retest window expires |
| Reclaim | bullish, close > pivot level, body >= 50%, close in upper 35%, range <= 2.00 ATR |
| Acceptance | **exactly** the next completed bar: close > pivot level **and** close >= reclaim close |
| Entry | pending LONG stop at acceptance high + 0.05 ATR, expiring after 2 completed bars |
| Stop | lowest completed low across retest / reclaim / acceptance, − 0.20 ATR, bounded to [0.50, 2.50] ATR |
| Target | fixed 3.0R, applied by the audited engine; no breakeven, trailing, partial or time exit |

State machine: `SEARCHING_PIVOT_BREAKOUT -> WAITING_RETEST -> WAITING_RECLAIM ->
WAITING_ACCEPTANCE -> PENDING_ENTRY -> IN_TRADE`, one structure at a time. The acceptance
rule is PB2's STRICT rule re-expressed in PB3's own architecture; **no PB1 or PB2 module is
imported** and none of their parameter candidates or optimizer results were reused.

## No-lookahead proof

A pivot does not exist for PB3 until **both** right-side confirmation bars have completed,
and pivot registration runs *after* the current bar's decisions — so at any bar PB3 can only
consult a pivot whose confirmation timestamp is strictly in the past.

**Fixture proof** (`tests/test_pb3_pivot_acceptance.py`): candidate bar completed → `None`;
first right bar completed → `None`; second right bar completed → available; next bar → may
break out on it. Plus, a mutated continuation with far higher highs leaves the already
emitted signal, every diagnostic event and every X-Ray row in the shared prefix
byte-identical, and a later higher bar cannot unmake or revise an already-confirmed pivot.

**Dataset proof** (asserted by the runner, which aborts on failure):

| | |
|---|---|
| Breakout decisions checked | **26,709** |
| Decisions using a pivot not yet confirmed | **0** |
| Minimum confirmation→decision lag | **1 bar** (tight bound) |

The one-bar minimum is the tight bound: registration is neither leaking into the same bar
nor being delayed beyond what the rule states.

## Phase A results (commit `0166924`)

One primary DEVELOPMENT-only run at frozen defaults. No variants, no optimization.

**48 closed trades · 1.51 trades/month · PF 0.7197 · Avg R −0.2211 · total R −10.62** ·
PnL −$266.53 · win rate 18.75% · max DD 1.92% · max losing streak 7. Entries reconcile
exactly: 48 entries = 48 closed trades + 0 open at end.

| Year | Trades | PF | Avg R | Total R |
|---|---|---|---|---|
| 2021 | 9 | 1.494 | **+0.333** | +3.00 |
| **2022** | 13 | 0.247 | **−0.702** | −9.13 |
| **2023** | **26** | 0.772 | **−0.173** | −4.49 |

**Positive DEVELOPMENT years: 1/3.** 2023 alone holds 54% of the trades and 56% of gross
positive R while itself being negative; 2022 alone loses more than the whole-period total.

**Break-even context.** At a fixed 3R target against a 1R stop the break-even win rate is
25.0%. PB3's 18.75% (9 winners of 48) sits below that line — the negative expectancy comes
from too few winners, not from oversized losers.

**Funnel.** 14,527 confirmed pivots → 4,153 eligible (actually consulted) → 783 breakouts →
490 retests → 254 reclaims → 112 acceptances → 73 pendings (66 tradeable) → **48 entries**.
The funnel reconciles exactly against the engine's order book: 66 tradeable pendings = 48
triggered + 18 expired.

**Sample-size classification:** 48 trades → band `VERY_SMALL` → research policy
**DO NOT OPTIMIZE PB3**. Baseline classification: **`INSUFFICIENT_SAMPLE`** (the <60-trade
gate binds before any performance rule is consulted).

## Comparison with PB2 LONG

| | PB2 LONG (historical) | PB3 |
|---|---|---|
| Closed trades / 3 years | 29 | **48** |
| Trades / month | 0.91 | **1.51** |
| Profit factor | **1.866** | 0.7197 |
| Average R | **+0.541** | **−0.2211** |
| Total R | +15.69 | −10.62 |
| Opportunity generator confirmations | 540 displacements | 783 breakouts |
| Acceptance confirmations | 58 | 112 |
| Positive DEVELOPMENT years | 2/3 | 1/3 |

**PB3 increased frequency by ~66% but materially reduced trade quality.** The acceptance
gate itself was not weakened — its rule is unchanged in substance — so the degradation is
attributable to the opportunity population fed to it, not to the gate.

Caveat recorded for honesty: PB3 is **not** a controlled single-variable ablation of PB2. It
changed the structure definition, three breakout thresholds (range 1.30 → 1.00 ATR, body
0.70 → 0.60, close location 0.20 → 0.30), the retest tolerance (0.10 → 0.15 ATR) and the
retest window (5 → 6 bars) at the same time. The comparison locates the change in the
generator but cannot attribute it to any single one of those.

## Transferable lessons

**Strict reclaim + acceptance cannot compensate for a weak upstream opportunity generator.**

Increasing opportunity frequency by replacing PB2's rare displacement structure with more
common pivot breakouts increased sample size but degraded expectancy. Quantity of structure
is not a substitute for quality of structure: the gate can only select from what it is given,
and a more permissive generator handed it a population whose members were, on average,
losing trades. One supporting observation from the Phase A buckets — descriptive only, n=12
— is that every trade whose breakout candle ranged <= 1.25 ATR lost; that is precisely the
band PB3 opened up relative to PB2's 1.30-ATR floor.

**Future research should seek a higher-frequency displacement model without lowering
structural quality.** That is a different problem from either PB2's (too few structures) or
PB3's (too many weak ones), and it is not solved by moving a threshold in either direction.

*No PB4 is designed or implemented here. This section is historical research reasoning only.*

## Historical progression

| Generation | Status | Outcome |
|---|---|---|
| **PB1** — shallow trend pullback | REJECTED | adequate frequency, unstable continuation quality |
| **PB2** — reclaim & acceptance | REJECTED | promising LONG selectivity, severe opportunity scarcity |
| **PB3** — confirmed pivot acceptance | REJECTED | greater opportunity frequency, but lower-quality structures |

PB1 had trades without quality. PB2 had quality signals without trades. PB3 bought trades
and lost the quality — which is the finding that separates it from PB2 rather than repeating
it.

## Fingerprints

| | |
|---|---|
| Strategy source | `7ad6dc8a9eb347d1db2e09536af5e9576c0c94ae3ef89aa93335ed1ddf3de966` |
| Effective parameters | `2749cbd02856f3ff325aee731e2239f3e23460d4c64a9ae2884eae3bd000542b` |
| Dataset | `3ab2cc48c91106e7b1bdd755a525fcc2b595cdf158259cee0c2889d00aab46f2` |

PB3 had a single fingerprint generation: closure is governance only and changed neither the
source nor any default, so both fingerprints above are unchanged by this rejection. All 24
effective fields — indicator lengths included — participate in the parameter fingerprint.

## Data exposure chronology

| Phase | Data used |
|---|---|
| Phase A (baseline) | DEVELOPMENT 2021-2023 only |
| V1 closure (this document) | none — governance only, no backtest run |

**2024 VALIDATION and 2025–2026 FORWARD_VALIDATION were never loaded, queried, backtested,
inspected or summarized for PB3 at any point in its life.** The runner refuses to construct a
config reaching 2024 or later and verifies every produced trade timestamp against the
DEVELOPMENT window afterwards. No out-of-sample result contributed to this rejection — it
rests entirely on DEVELOPMENT evidence, and PB3's out-of-sample data remains genuinely unseen.

## Governance

PB3 is registered `REJECTED`. The platform's existing status guards refuse to start new
research workflows for it — **no new guard was required**:

- `research.optimizer.guard_optimization` → `OPTIMIZATION DISABLED - REJECTED STRATEGY`
- `research.walk_forward.guard_walk_forward` → `WALK-FORWARD DISABLED — REJECTED STRATEGY`

Historical results stay readable and reproducible: `run_universal_backtest` applies no status
guard, the universal workspace exposes rejected strategies behind its "Show rejected/research
history" toggle, and the Phase A report is unmodified.

## Artifacts

| Phase | Commit | Reports |
|---|---|---|
| A — baseline | `0166924` | `PHASE_A_BASELINE.md`, `phase_a_baseline.json` |

| Artifact | Path |
|---|---|
| Strategy | `strategies/btc_pb3_pivot_acceptance_long.py` |
| Registration | `strategies/universal_catalog.py` |
| Runner | `research/pb3_phase_a_baseline.py` |
| Tests | `tests/test_pb3_pivot_acceptance.py` |

Research tag: `btc-pb3-v1-rejected`.
