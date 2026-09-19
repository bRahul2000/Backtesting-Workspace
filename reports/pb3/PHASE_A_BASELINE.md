# PB3 Phase A — Confirmed Pivot Reclaim & Acceptance (LONG) — DEVELOPMENT baseline

**Strategy:** `BTC_PB3_PIVOT_ACCEPTANCE_LONG_V1` · status `RESEARCH` · LONG only
**Evidence base:** DEVELOPMENT 2021-01-01 .. 2023-12-31 only
**Runs:** exactly one, at frozen defaults. No optimization, no variants, no validation.

This is an observation record. It recommends no parameter change, and it makes no claim
about behaviour outside 2021–2023 or across regimes.

---

## 1. Hypothesis

PB1 (`BTC_PB1_SHALLOW_PULLBACK_V1`, REJECTED) produced adequate opportunity frequency but
weak continuation quality across regimes. PB2 (`BTC_PB2_RECLAIM_*_V1`, REJECTED) produced a
strict acceptance gate that demonstrably rejected losing LONG setups, but its opportunity
generator — a 1.30-ATR displacement through a rolling 12-bar extreme — yielded only 29 LONG
trades in three years.

PB3 keeps the proof-of-acceptance idea and replaces the opportunity generator:

    H1 bullish context
    -> break of a *confirmed* M15 swing/pivot high
    -> retest of that actual pivot level
    -> strict reclaim
    -> strict next-bar acceptance
    -> stop entry above the acceptance bar

**Research question:** can structural opportunities be materially increased without
weakening the proof-of-acceptance gate that PB2 showed was doing real selection work?

## 2. Architecture

| Stage | Rule |
|---|---|
| H1 context | H1 EMA50 > EMA200 (ordering only; separation and both slopes are measured but unfiltered) |
| Structure | latest **confirmed** M15 pivot high, left 2 / right 2, at most 24 bars old |
| Breakout | bullish, close > pivot high, range ≥ 1.00 ATR, body ≥ 60% of range, close in upper 30% |
| Duplication | one confirmed pivot may generate at most one structure attempt, ever |
| Retest | within 6 completed bars, bar low ≤ pivot level + 0.15 ATR (the level itself, not a percentage retracement) |
| Invalidation | completed close < breakout candle low, or the retest window expires |
| Reclaim | bullish, close > pivot level, body ≥ 50%, close in upper 35%, range ≤ 2.00 ATR |
| Acceptance | **exactly** the next completed bar: close > pivot level **and** close ≥ reclaim close |
| Entry | pending LONG stop at acceptance high + 0.05 ATR, expiring after 2 completed bars |
| Stop | lowest completed low across retest / reclaim / acceptance, − 0.20 ATR, bounded to [0.50, 2.50] ATR |
| Target | fixed 3.0R, applied by the audited engine; no breakeven, trailing, partial or time exit |

State machine: `SEARCHING_PIVOT_BREAKOUT → WAITING_RETEST → WAITING_RECLAIM →
WAITING_ACCEPTANCE → PENDING_ENTRY → IN_TRADE`, resetting on invalidation, retest expiry,
failed reclaim, failed acceptance, risk rejection, pending expiry, entry and trade close.
One structure at a time; no new structure is detected while pending or in a trade.

### PB1 / PB2 lessons incorporated

- **From PB2, kept:** strict acceptance is a *separate completed bar*, and the sequence can
  never collapse into one candle. The same-bar retest/reclaim chronology argument is reused:
  a bar's close is by construction its last price, so a low inside the retest tolerance
  necessarily precedes a reclaiming close — no intrabar path is invented.
- **From PB2, changed:** the opportunity generator. A confirmed pivot occurs far more often
  than a 1.30-ATR displacement through a 12-bar extreme, and the retest targets the pivot
  level itself.
- **From PB2's instrumentation bugs:** PB3 never emits `trade_entered` / `trade_exited`
  (the generic observer owns them, and duplicating them broke entry reconciliation), clears
  its tracked pending when it fills (phantom-expiry bug), and tags pendings created before
  the warmup boundary so the funnel reconciles against the engine's order book.
- **From PB1:** no percentage retracement of a measured leg anywhere; nothing in PB3 both
  confirms and triggers on the same candle.
- **Independence (section 28):** PB3 imports no PB1 or PB2 module and reuses none of their
  parameter candidates or optimizer results. PB1 and PB2 sources are byte-unchanged.

## 3. Exact defaults

```
h1_fast_ema                      50     retest_tolerance_atr            0.15
h1_slow_ema                     200     retest_maximum_bars                6
h1_atr_length                    14     reclaim_minimum_body_percent    0.50
h1_slope_lookback                 4     reclaim_close_location_percent  0.35
m15_atr_length                   14     reclaim_maximum_range_atr       2.00
m15_ema20_length                 20     entry_buffer_atr                0.05
m15_ema50_length                 50     pending_expiry_bars                2
pivot_left_bars                   2     stop_buffer_atr                 0.20
pivot_right_bars                  2     minimum_stop_atr                0.50
maximum_pivot_age_bars           24     maximum_stop_atr                2.50
breakout_minimum_range_atr     1.00     reward_multiple                  3.0
breakout_minimum_body_percent  0.60
breakout_close_location_percent 0.30
```

All 24 effective fields — including the indicator lengths that are not exposed as tunable
parameters — participate in the effective-parameter fingerprint.

## 4. No-lookahead proof (Phase A release blocker)

A pivot does not exist for PB3 until **both** right-side confirmation bars have completed,
and pivot registration runs *after* the current bar's decisions. At any bar, PB3 can
therefore only consult a pivot whose confirmation timestamp is strictly in the past.

**Fixture proof** (`tests/test_pb3_pivot_acceptance.py`):

| Stage | `active_pivot` |
|---|---|
| candidate bar completed, visible only historically | `None` |
| first right bar completed | `None` |
| second right bar completed | available (price, pivot timestamp, confirmation timestamp) |
| next bar | may break out on it |

Plus: a mutated continuation with far higher highs leaves the already-emitted signal, every
diagnostic event and every X-Ray row in the shared prefix byte-identical; and a later,
higher bar cannot unmake or revise an already-confirmed pivot.

**Dataset proof** (asserted by the runner, which aborts on failure):

| | |
|---|---|
| breakout decisions checked (evaluations + confirmations) | **26,709** |
| decisions using a pivot not yet confirmed | **0** |
| minimum confirmation→decision lag | **1 bar** |

The minimum lag of exactly one bar is the tight bound: it shows registration is neither
leaking into the same bar nor being delayed further than the rule states.

## 5. Fingerprints

| | |
|---|---|
| Strategy source | `7ad6dc8a9eb347d1db2e09536af5e9576c0c94ae3ef89aa93335ed1ddf3de966` |
| Effective parameters | `2749cbd02856f3ff325aee731e2239f3e23460d4c64a9ae2884eae3bd000542b` |
| Dataset | `3ab2cc48c91106e7b1bdd755a525fcc2b595cdf158259cee0c2889d00aab46f2` |

Both fingerprints were frozen before results were interpreted. PB3's source fingerprint is
distinct from PB1's and from both PB2 components'.

## 6. DEVELOPMENT baseline results

| Metric | Value |
|---|---|
| Closed trades | **48** |
| Total entries | 48 |
| Open at end | 0 |
| Trades / month | 1.51 |
| Win rate | **18.75%** |
| Profit factor | **0.7197** |
| Average R | **−0.2211** |
| Total R | **−10.62** |
| PnL | **−$266.53** |
| Max drawdown | 1.92% |
| Max losing streak | 7 |
| Average hold | 243.75 min |
| Median hold | 105 min |

Entries reconcile exactly: `total_entries (48) = closed trades (48) + open at end (0)`.

**Break-even context.** At a fixed 3R target against a 1R stop, the break-even win rate is
25.0% before costs. The observed 18.75% (9 winners of 48) sits below that line, which is
the arithmetic source of the negative expectancy — not an unusually large average loser.

### Yearly

| Year | Trades | Win rate | PF | Avg R | Total R | Max DD within year |
|---|---|---|---|---|---|---|
| 2021 | 9 | 33.33% | 1.494 | **+0.3333** | **+3.00** | 1.00% |
| 2022 | 13 | 7.69% | 0.247 | **−0.7022** | **−9.13** | 2.51% |
| 2023 | **26** | 19.23% | 0.772 | −0.1726 | −4.49 | 1.92% |

**Positive DEVELOPMENT years: 1/3.**

## 7. Year consistency

| Year | % of trades | Total R | % of gross positive R |
|---|---|---|---|
| 2021 | 18.75% | +3.00 | 32.75% |
| 2022 | 27.08% | −9.13 | 10.92% |
| 2023 | **54.17%** | −4.49 | **56.33%** |

- **One-year concentration: flagged.** 2023 holds 54.17% of trades and 56.33% of gross
  positive R (flag rule: ≥50% of trades or ≥60% of gross positive R).
- **Negative-year dependency: flagged.** Two of three years are negative, and 2022 alone
  (−9.13R) exceeds the whole-period total R in magnitude.

No claim about behaviour across regimes is made from this. Phase A is descriptive.

## 8. Funnel and frequency

| Stage | Count |
|---|---|
| Confirmed pivots | 14,527 |
| Eligible pivots (actually consulted for a breakout) | 4,153 |
| Pivots expired on age | 12 |
| Breakout evaluations | 25,926 |
| **Breakout confirmations** | **783** |
| Retests detected | 490 |
| Retests expired | 315 |
| Structures invalidated | 218 |
| **Reclaim confirmations** | **254** |
| Acceptance evaluations | 250 |
| Acceptance failures | 138 |
| **Acceptance confirmations** | **112** |
| Risk evaluations | 112 |
| Risk rejections | 39 |
| **Risk-valid setups (pendings created)** | **73** |
| — of which inside the tradeable window | 66 |
| Expired pendings | 18 |
| **Entries** | **48** |
| Exits | 48 |

*"Eligible" means PB3 actually consulted the pivot: it was the latest confirmed pivot, still
inside the age cap, on a bar where H1 context qualified and no structure was in progress.
Most confirmed pivots are never consulted because a newer pivot supersedes them first.*

**Engine reconciliation.** Tradeable pendings 66 = engine triggered 48 + engine expired 18.
Strategy-side `pending_expired` (18) equals the engine's expiry count, and the generic
`trade_entered` / `trade_exited` counts (48 / 48) match the closed trade log — so no stage
is double-counted and no phantom expiry is recorded.

### Largest rejection reasons

| Reason | Count |
|---|---|
| context: H1 EMA50 not above EMA200 | 34,902 |
| breakout: candle not bullish | 12,606 |
| breakout: close did not break the pivot high | 10,926 |
| breakout: insufficient range | 1,075 |
| reclaim: candle not bullish | 799 |
| context: H1 regime not yet warmed up | 621 |
| breakout: insufficient body | 478 |
| reclaim: insufficient body | 285 |
| retest expired: pivot level never retested | 221 |
| structure invalidated: close below the breakout candle low | 218 |
| reclaim: close did not reclaim the pivot level | 118 |
| acceptance failed: close did not hold the reclaim close | 113 |
| retest expired: no reclaim within the retest window | 94 |
| breakout: close not in the upper range | 58 |
| risk: stop distance outside the safety range | 39 |

### Frequency versus the PB2 LONG historical baseline

| | PB2 LONG (historical) | PB3 |
|---|---|---|
| Closed trades / 3 years | 29 | **48** |
| Trades / month | 0.91 | **1.51** |
| Opportunity generator confirmations | 540 displacements | 783 breakouts |
| Acceptance confirmations | 58 | 112 |

Historical context only. PB2 is REJECTED and closed; nothing about PB3 was changed on
account of this comparison, and no PB2 result contributes to PB3's scoring.

## 9. Sample-size classification

| | |
|---|---|
| Closed trades | 48 |
| Band | **VERY_SMALL** (30–59) |
| Research policy | **DO NOT OPTIMIZE PB3** (<60 trades) |

Bands: <30 INSUFFICIENT · 30–59 VERY_SMALL · 60–119 SMALL · 120–249 MODERATE · ≥250
SUBSTANTIAL. The policy is not overridable by profit factor.

## 10. MFE / MAE

Corrected normalization: excursion **price distance** ÷ initial **stop price distance**.
Model: `BAR_BASED_APPROXIMATION`.

| | n | mean | median | p75 | p90 | p95 | max |
|---|---|---|---|---|---|---|---|
| MFE (R) | 48 | 1.258 | 0.689 | 1.841 | 3.220 | 3.479 | 7.198 |
| MAE (R) | 48 | 1.139 | 1.195 | 1.351 | 1.613 | 1.720 | 2.221 |

⚠ **BAR_BASED_APPROXIMATION.** Excursions use whole entry-to-exit-bar OHLC, so they include
price action inside the exit bar beyond the modelled fill. They are not an exact tick path
and must not be read as achievable pre-exit movement. Median MAE above 1.0R is a direct
consequence of that: most trades are stopped, and the stop bar's full range is counted.

## 11. Descriptive buckets

Fixed edges, declared in the runner before the run. **Every cell below is small — the
largest holds 36 trades and several hold fewer than five.** No threshold is recommended and
none of these splits was used to change anything.

**Pivot age (bars)**

| Bucket | n | PF | Avg R | Win rate |
|---|---|---|---|---|
| ≤5 | 31 | 0.602 | −0.3236 | 16.1% |
| 5–9 | 14 | 1.244 | +0.1725 | 28.6% |
| 9–15 | 3 | 0.000 | −1.0000 | 0.0% |

**Breakout range (ATR)**

| Bucket | n | PF | Avg R | Win rate |
|---|---|---|---|---|
| ≤1.25 | 12 | 0.000 | −0.9811 | 0.0% |
| 1.25–1.50 | 15 | 0.483 | −0.4263 | 13.3% |
| 1.50–2.00 | 14 | 1.757 | +0.4763 | 35.7% |
| >2.00 | 7 | 1.167 | +0.1263 | 28.6% |

**Breakout distance beyond the pivot (ATR)**

| Bucket | n | PF | Avg R | Win rate |
|---|---|---|---|---|
| ≤0.25 | 14 | 0.515 | −0.4012 | 14.3% |
| 0.25–0.50 | 14 | 1.231 | +0.1615 | 28.6% |
| 0.50–1.00 | 16 | 0.463 | −0.4669 | 12.5% |
| >1.00 | 4 | 1.069 | +0.0530 | 25.0% |

**Bars to retest**

| Bucket | n | PF | Avg R | Win rate |
|---|---|---|---|---|
| ≤1 | 36 | 0.629 | −0.3012 | 16.7% |
| 1–2 | 7 | 2.242 | +0.7143 | 42.9% |
| 2–3 | 2 | 0.000 | −1.0014 | 0.0% |
| >3 | 3 | 0.000 | −0.9231 | 0.0% |

**Retest overshoot beyond the pivot (ATR)** — negative means the low never reached the level

| Bucket | n | PF | Avg R | Win rate |
|---|---|---|---|---|
| ≤−0.10 | 3 | 1.852 | +0.5066 | 33.3% |
| −0.10–0.00 | 7 | 0.519 | −0.3984 | 14.3% |
| 0.00–0.10 | 10 | 0.768 | −0.1767 | 20.0% |
| >0.10 | 28 | 0.667 | −0.2707 | 17.9% |

**Acceptance distance beyond the pivot (ATR)**

| Bucket | n | PF | Avg R | Win rate |
|---|---|---|---|---|
| 0.25–0.50 | 4 | 1.059 | +0.0394 | 25.0% |
| 0.50–1.00 | 21 | 0.528 | −0.3812 | 14.3% |
| >1.00 | 23 | 0.843 | −0.1203 | 21.7% |

**Stop distance (ATR)**

| Bucket | n | PF | Avg R | Win rate |
|---|---|---|---|---|
| ≤1.00 | 1 | 0.000 | −0.9845 | 0.0% |
| 1.00–1.50 | 13 | 0.602 | −0.3166 | 15.4% |
| 1.50–2.00 | 24 | 0.814 | −0.1426 | 20.8% |
| 2.00–2.50 | 10 | 0.739 | −0.2091 | 20.0% |

## 12. Baseline classification

> ## `INSUFFICIENT_SAMPLE`

Rule: closed trades < 60 → `INSUFFICIENT_SAMPLE` regardless of profit factor. Sample size
takes precedence over every performance reading, and at 48 trades the gate binds before any
performance rule is consulted. For the record, the performance rules that would have applied
at ≥60 trades are: Avg R > +0.10 with ≥2 of 3 positive DEVELOPMENT years → `PROMISING_SAMPLE`;
Avg R < −0.10 → `NEGATIVE_SAMPLE`; otherwise `NEAR_BREAKEVEN_SAMPLE`. PB3's Avg R of −0.2211
with 1/3 positive years would have fallen in `NEGATIVE_SAMPLE` — but the sample gate is what
the classification rests on, and that distinction is not a performance verdict.

## 13. Observations

Stated as observations only. None of these is a recommendation, and none of them was acted on.

1. **The opportunity generator did what it was built to do.** Confirmed pivots plus a
   1.00-ATR breakout produced 783 structure attempts and 48 trades where PB2's displacement
   generator produced 540 and 29 — a 66% increase in trades per month (0.91 → 1.51). The
   frequency question posed in the hypothesis got a positive answer.
2. **It did not reach the sample threshold anyway.** 48 trades over three years is still
   VERY_SMALL, one band above PB2 LONG's INSUFFICIENT and still below the 60-trade line at
   which even narrow architecture diagnosis would be justified.
3. **The additional population is worse, not merely more numerous.** Avg R moved from PB2
   LONG's +0.541 to −0.221 and the win rate (18.75%) sits below the 25% break-even line for
   a 3R target. The acceptance gate was not weakened — its rule is unchanged in substance —
   so the degradation is attributable to what the generator fed it, not to the gate.
4. **This is not a controlled single-variable ablation of PB2.** PB3 changed the structure
   definition, the breakout thresholds (range 1.30 → 1.00 ATR, body 0.70 → 0.60, close
   location 0.20 → 0.30), the retest tolerance (0.10 → 0.15 ATR) and the retest window
   (5 → 6 bars) at the same time. Observation 3 identifies the generator as the locus of the
   change but cannot attribute it to any single one of these.
5. **Loose breakouts were uniformly unprofitable in this sample.** All 12 trades whose
   breakout candle ranged ≤1.25 ATR lost (Avg R −0.98). That is the band PB3 opened up
   relative to PB2's 1.30-ATR floor. n = 12; nothing follows from it.
6. **The result is concentrated and negative-year dependent.** 2023 carries 54% of the
   trades and 56% of gross positive R while itself being negative; 2022 alone loses more
   than the whole-period total. Only 2021 is positive.
7. **Instrumentation is clean.** The funnel reconciles exactly against the engine's order
   book (66 tradeable pendings = 48 triggered + 18 expired), entries reconcile against
   closed trades, and the no-lookahead invariant holds over 26,709 breakout decisions with a
   tight one-bar minimum lag.

## 14. Limitations

- **DEVELOPMENT only.** Three years, one instrument, one timeframe pair, one direction.
- **48 trades.** Every yearly figure rests on 9–26 trades and every descriptive bucket on
  1–36. None of the bucket splits is separable from noise at this size.
- **No SHORT component exists.** Phase A is LONG-only by specification, so nothing here says
  anything about the short side.
- **Excursions are bar-based approximations**, not tick paths (see §10).
- **Execution model.** Results carry the audited engine's `EXNESS_SYNTHETIC_BID_ASK` profile
  and its fill, gap and ambiguity policies; they are not broker-independent.
- **No stability claim of any kind is made.** Phase A is a single descriptive run.
- **The research policy binds:** at <60 trades PB3 must not be parameter-optimized.

## 15. Data exposure

| Phase | Data used |
|---|---|
| Phase A (this baseline) | DEVELOPMENT 2021-01-01 .. 2023-12-31 only |

**2024 VALIDATION and 2025–2026 FORWARD_VALIDATION were never loaded, queried, backtested,
inspected or summarized for PB3 at any point.** The runner refuses to construct a config
reaching 2024 or later, and every produced trade timestamp is verified against the
DEVELOPMENT window after the run (`research/pb3_phase_a_baseline.py`). PB3's out-of-sample
data remains genuinely unseen.

## 16. Artifacts

| Artifact | Path |
|---|---|
| Strategy | `strategies/btc_pb3_pivot_acceptance_long.py` |
| Registration | `strategies/universal_catalog.py` |
| Runner | `research/pb3_phase_a_baseline.py` |
| Machine-readable results | `reports/pb3/phase_a_baseline.json` |
| Tests | `tests/test_pb3_pivot_acceptance.py` (49 tests) |
