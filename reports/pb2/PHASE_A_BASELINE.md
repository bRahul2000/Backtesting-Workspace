# PB2 Phase A — Reclaim & Acceptance Baseline

**Components:** `BTC_PB2_RECLAIM_LONG_V1`, `BTC_PB2_RECLAIM_SHORT_V1` (both `RESEARCH`)
**Dataset:** DEVELOPMENT 2021-01-01 .. 2023-12-31 only
**Status:** baseline established, nothing optimized, nothing validated.

Observations only. No parameter change is proposed here.

---

## Hypothesis

PB1 established that *impulse → shallow percentage retracement → confirmation candle*
produces localized signal whose continuation quality is not stable across DEVELOPMENT
regimes. PB2 tests a different premise: an entry should be permitted only after price
has **proved it can hold a level it broke**.

    H1 trend context
    -> structural displacement through a prior M15 structure level
    -> retest of the broken level
    -> reclaim of the level
    -> one further completed bar of acceptance beyond it
    -> stop entry above/below the acceptance bar

PB2 never enters because a pullback reached a percentage depth. Every decision is keyed
to a *price level*, and the sequence cannot complete inside a single candle.

## Architecture

| Stage | Rule |
|---|---|
| H1 context | EMA50 > EMA200 (LONG) / EMA50 < EMA200 (SHORT). Separation/ATR and both EMA slopes are measured but **not filtered on** in Phase A. |
| Structure level | Highest high (LONG) / lowest low (SHORT) of the **12 completed bars preceding** the displacement candle. The displacement bar is excluded. |
| Displacement | One completed M15 candle: directional, range ≥ 1.30 ATR, body ≥ 70% of range, close in the extreme 20% of range, closing beyond the structure level. |
| Retest | Within 5 completed bars: bar low ≤ level + 0.10 ATR (LONG) / bar high ≥ level − 0.10 ATR (SHORT). A level retest, not a retracement percentage. |
| Invalidation | A completed close beyond the displacement candle's far extreme, or window expiry. |
| Reclaim | Directional candle closing back beyond the level, body ≥ 50%, close in the extreme 35% of range, range ≤ 2.00 ATR. |
| Acceptance | **Exactly the next completed candle**: close beyond the level *and* holding the reclaim close. Anything else resets the structure. |
| Entry | Stop entry at acceptance extreme ± 0.05 ATR, expiring after 2 completed bars. |
| Stop | Beyond the lowest/highest price across the retest, reclaim and acceptance bars ± 0.20 ATR; setups outside 0.50–2.50 ATR are rejected. |
| Target | Fixed 3.0R applied by the audited engine. No breakeven, trailing, partial or time exit. |

State machine: `SEARCHING_DISPLACEMENT → WAITING_RETEST → WAITING_RECLAIM →
WAITING_ACCEPTANCE → PENDING_ENTRY → IN_TRADE`, resetting on invalidation, expiry,
failed acceptance, pending expiry and trade completion. One displacement can produce at
most one pending order.

### Same-bar retest and reclaim

A single bar may serve as both retest and reclaim. This is not an intrabar-path
assumption: a bar's close is by construction its last price, so a low inside the retest
tolerance necessarily precedes the reclaiming close. The conservative part of the rule
is that **acceptance is never collapsed into the same candle** — it always requires the
following completed bar, so the sequence spans at least two bars after displacement.
This is covered by an explicit test.

## How PB2 differs from PB1

| | PB1 (REJECTED) | PB2 |
|---|---|---|
| Trigger concept | Percentage retracement depth of a measured leg | Reclaim and acceptance of a broken price level |
| Impulse | 3-candle measured leg, range ≥ 1.5 ATR | 1 displacement candle vs. a 12-bar structure level |
| Pullback | 20–45% retracement of the impulse range | Retest within 0.10 ATR of the level, no percentage at all |
| Confirmation | One candle both confirms and triggers the order | Reclaim candle, then a **separate** acceptance bar |
| Entry basis | Confirmation candle extreme + 0.10 ATR | Acceptance bar extreme + 0.05 ATR |
| Stop anchor | Deepest pullback price − 0.20 ATR | Extreme across retest/reclaim/acceptance − 0.20 ATR |
| Direction | One component trading both sides | Two independent components, researched separately |

PB2 imports no PB1 module and reuses none of its parameters, stored candidates,
optimizer results or rejection filters. It reuses only generic platform infrastructure:
indicators, the audited execution engine, the diagnostics/X-Ray layer, the risk engine,
fingerprinting and the experiment ledger.

## Baseline parameters (frozen for Phase A)

```
h1_fast_ema = 50            m15_atr_length = 14         structure_lookback = 12
h1_slow_ema = 200           m15_ema20_length = 20
h1_atr_length = 14          m15_ema50_length = 50
h1_slope_lookback = 4

displacement_minimum_range_atr = 1.30       retest_tolerance_atr = 0.10
displacement_minimum_body_percent = 0.70    retest_maximum_bars = 5
displacement_close_location_percent = 0.20

reclaim_minimum_body_percent = 0.50         entry_buffer_atr = 0.05
reclaim_close_location_percent = 0.35       pending_expiry_bars = 2
reclaim_maximum_range_atr = 2.00

stop_buffer_atr = 0.20   minimum_stop_atr = 0.50   maximum_stop_atr = 2.50
reward_multiple = 3.0
```

Thirteen parameters are registered as tunable for a possible later phase;
`reward_multiple` is registered frozen. **Zero optimization was run.**

## Fingerprints

| | Value |
|---|---|
| LONG strategy fingerprint | `5c4a3f8ec34d97d660dae83f783539467d5dba58841b8936c9c7fe5b403a6a72` |
| SHORT strategy fingerprint | `bed29f83b41ec2016033bf925a4a81c157e30bb765ecf6ab8359879b8a9f3eef` |
| Effective parameter fingerprint (both) | `a103f11b2f7f8017a819ac8b35bf944fac859569d367b7131115115511d4a6f1` |
| DEVELOPMENT dataset fingerprint | `3ab2cc48c91106e7b1bdd755a525fcc2b595cdf158259cee0c2889d00aab46f2` |

The two components share a parameter fingerprint because they share one schema and one
set of defaults; they are distinguished by their strategy fingerprints, which cover both
the component file and the shared implementation core. The parameter fingerprint is the
corrected effective-payload hash introduced in PB1 Phase A.1 and covers all 22 dataclass
fields, including those never exposed as tunable.

## Results — DEVELOPMENT 2021-2023

| | LONG | SHORT |
|---|---|---|
| Closed trades | 29 | 14 |
| Total entries | 29 | 14 |
| Open at end | 0 | 0 |
| Trades / month | 0.91 | 0.44 |
| Win rate | 37.93% | 7.14% |
| Profit factor | 1.866 | 0.231 |
| Avg R | +0.5410 | −0.7143 |
| Total R | +15.69 | −10.00 |
| PnL | +$393.18 | −$249.69 |
| Max drawdown | 0.77% | 0.75% |
| Max losing streak | 3 | 3 |
| Avg holding time | 188 min | 223 min |
| Median holding time | 105 min | 172 min |

### Yearly

**LONG**

| Year | Trades | Win rate | PF | Avg R | Total R |
|---|---|---|---|---|---|
| 2021 | 4 | 50.0% | 2.986 | +0.9996 | +4.00 |
| 2022 | 7 | 14.3% | 0.493 | −0.4370 | −3.06 |
| 2023 | 18 | 44.4% | 2.465 | +0.8194 | +14.75 |

**SHORT**

| Year | Trades | Win rate | PF | Avg R | Total R |
|---|---|---|---|---|---|
| 2021 | 5 | 0.0% | 0.000 | −1.0000 | −5.00 |
| 2022 | 6 | 16.7% | 0.600 | −0.3333 | −2.00 |
| 2023 | 3 | 0.0% | 0.000 | −1.0000 | −3.00 |

## Signal funnel

| Stage | LONG | SHORT |
|---|---|---|
| Context-qualified bars | 38,861 | 40,330 |
| Context rejected | 49,297 | 41,630 |
| Displacement evaluations | 38,861 | 40,330 |
| Valid displacements | 540 | 538 |
| Retests detected | 308 | 354 |
| Retest windows expired | 290 | 294 |
| Structures invalidated | 120 | 106 |
| Reclaim evaluations | 895 | 1,091 |
| Reclaims confirmed | 130 | 138 |
| Acceptance evaluations | 130 | 138 |
| Acceptance confirmed | 58 | 62 |
| Acceptance failed | 72 | 76 |
| Risk evaluations | 58 | 62 |
| Risk rejected (stop ATR bounds) | 19 | 34 |
| Pending orders created (rule decisions) | 39 | 28 |
| Pending orders in the tradeable window | 35 | 26 |
| Pending orders expired | 6 | 12 |
| Entries | 29 | 14 |
| Exits | 29 | 14 |

The funnel reconciles exactly with the engine: tradeable pendings = triggered + expired
(35 = 29 + 6 LONG; 26 = 14 + 12 SHORT). `pending_created` counts every rule decision,
including signals emitted before the warmup boundary that the engine always discards —
4 LONG and 2 SHORT.

**Largest rejection reasons** (both directions): H1 context misalignment dominates
(48,676 LONG / 41,009 SHORT), then displacement failures — candle not directional
(19,139 / 20,080), close did not break the structure level (17,379 / 18,045),
insufficient range (1,141 / 821), insufficient body (558 / 710).

## Excursion (Phase A.1 normalization: excursion price distance / initial stop distance)

| | LONG mean | median | p75 | p90 | p95 | SHORT mean | median | p75 | p90 | p95 |
|---|---|---|---|---|---|---|---|---|---|---|
| MFE (R) | 1.757 | 1.296 | 3.191 | 3.552 | 3.806 | 0.967 | 0.762 | 1.501 | 2.309 | 2.669 |
| MAE (R) | 0.945 | 1.015 | 1.108 | 1.371 | 1.459 | 1.319 | 1.260 | 1.562 | 1.803 | 1.846 |

Model: `BAR_BASED_APPROXIMATION`. These use whole entry-to-exit-bar OHLC and therefore
include price action inside the exit bar beyond the modelled fill. They are not an exact
tick path and must not be read as achievable pre-exit movement.

## Acceptance diagnostics (descriptive only)

Every bucket below holds between 1 and 22 trades. **None of these is interpretable** and
none was used to alter any parameter. They are recorded so a later phase has a starting
point, not a conclusion.

**LONG** — the widest spreads appear in `stop_atr` (1.0–1.5 ATR: n=10, PF 7.02, Avg R
+1.83; 1.5–2.0 ATR: n=11, PF 0.71, Avg R −0.23) and `bars_to_retest` (retest on the
first bar: n=22, PF 2.13; later: n=7, mostly negative). `retest_overshoot_atr` below zero
(price never quite reached the level) shows n=5, PF 11.70 — five trades, no signal.

**SHORT** — 13 of 14 trades lost, so every bucket is negative or empty; no structure is
readable at this sample size.

## Baseline classification

| Component | Classification |
|---|---|
| LONG | `INSUFFICIENT_SAMPLE` |
| SHORT | `INSUFFICIENT_SAMPLE` |

Rule: closed trades < 30 → `INSUFFICIENT_SAMPLE`; otherwise Avg R > +0.05 →
`BASELINE_POSITIVE`, Avg R < −0.05 → `BASELINE_NEGATIVE`, else
`BASELINE_NEAR_BREAKEVEN`.

LONG's PF of 1.87 and Avg R of +0.54 are **not** evidence of an edge: 29 trades across
three years, concentrated in 2023 (18 of 29), with a negative 2022. SHORT's PF of 0.23
is equally uninterpretable at 14 trades. Neither side is robust, and nothing in Phase A
can make any strategy `FROZEN`.

## Limitations

- **Frequency is the headline finding.** 0.91 LONG and 0.44 SHORT trades per month means
  the baseline is far too restrictive to evaluate, let alone deploy. The funnel shows why:
  540 valid displacements produce only 29 LONG trades — a 5.4% conversion — with the
  largest internal losses at the retest stage (540 → 308) and the acceptance stage
  (130 reclaims → 58 accepted, so 55% of reclaims fail acceptance).
- The acceptance bar, PB2's core hypothesis, is doing substantial work: it removes over
  half of all reclaims on both sides (44.6% LONG and 44.9% SHORT pass). Whether that
  removal is selective or merely destructive cannot be judged at this sample size.
- Sample sizes make every yearly, directional and bucket figure descriptive only.
- The 2022 weakness visible on the LONG side echoes PB1's DEVELOPMENT pattern, but with
  n=7 it is not evidence of anything and was not treated as such.
- Excursions are bar-based approximations, not tick paths.
- Two independent components were run; no combined run was performed, so nothing here
  says how a merged strategy would behave.

## Data policy

DEVELOPMENT 2021-01-01 .. 2023-12-31 was the only window used. The runner asserts the
window before executing and re-checks every resulting trade timestamp afterwards; the
report records the years actually present as `[2021, 2022, 2023]`.

**2024 VALIDATION and 2025-2026 FORWARD_VALIDATION were never loaded, queried,
backtested, inspected or summarized for PB2 at any point.** PB2's 2024 dataset remains
genuinely unseen.
