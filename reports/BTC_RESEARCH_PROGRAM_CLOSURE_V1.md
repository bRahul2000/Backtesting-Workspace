# BTC Research Program Closure — V1

**Status: CLOSED.** Consolidates Phases A–G, Architecture Resets A and B, and the
T3 2.0R out-of-sample validation. Written for whoever picks up BTC research next.
No backtest was run to produce this document; every number is taken from the
committed reports listed under *Commits*.

---

## 1. FINAL PROGRAM STATUS

| item | status |
|---|---|
| **Frozen Core (A4 + T3)** | **RESEARCH REFERENCE ONLY** |
| **T3 2.0R** | **OOS REJECTED** |
| **24–30 trades/month on current Exness BTCUSDm M15 architecture** | **NOT SUPPORTED BY EVIDENCE** |
| **M5 execution reset** | **REJECTED ON COST GEOMETRY** |
| **CURRENT DEPLOYMENT STATUS** | **NO NEW BTC STRATEGY APPROVED FOR LIVE/DEMO EXECUTION** |

The programme set out to raise the frozen Core from ~9.7 trades/month to 24–30
while keeping positive expectancy. It did not succeed, and the reason is now
understood rather than merely observed: the high-capacity opportunity pools on
this instrument and timeframe are statistically indistinguishable from a
driftless path at every reward multiple tested, and the broker's spread is
larger than any drift that might be in them.

---

## 2. DATA GOVERNANCE

| | |
|---|---|
| Primary dataset | `data/exness/btc/phase_r1/processed/btcusdm_M15.csv` |
| M15 fingerprint | `80735a2cf521363747f48368814267ad6ca146eb294bb7bd7252666d06c76af3` |
| Secondary (Reset B cost geometry only) | `data/exness/btc/phase_r1/processed/btcusdm_H1.csv` |
| H1 fingerprint | `6d35fe9d7feb7635e0973084fb6520ccbc0f99f7b17fc49760692a97dec55658` |
| Broker / symbol | Exness Technologies Ltd · BTCUSDm · MT5 `CopyRates` |
| Spread model | `BROKER_NATIVE_PER_BAR` (median 28.80, p95 53.90, max 88.09) |

### Validation periods

| period | range | status |
|---|---|---|
| DEVELOPMENT | 2023-11-10 23:15 → 2025-06-30 23:45 UTC (57,403 bars, 19.65 months) | used throughout |
| **HOLDOUT** | **2025-07-01 00:00 → 2026-09-20 07:15 UTC** | **CONSUMED — one candidate, one run, 2026-09-21** |
| Forward/paper | none | never opened |

**The holdout was untouched through Phases A–G and both Architecture Resets** —
every phase report records `Holdout touched: NO` and every phase's test suite
asserts no arm's end date crosses `HOLDOUT_START`. It was opened exactly once,
for the predeclared T3 2.0R candidate, after the gates were committed.

### Protected hashes — unchanged for the entire programme

| strategy | fingerprint |
|---|---|
| `BTC_V3_A4_PULLBACK_LONG_FROZEN` | `55fedf8564537549f076e726916286256f504749283a2b587b3cdc964926f3d9` |
| `BTC_V3_T3_BREAKOUT_SHORT_FROZEN` | `4c4ab845852ff973530f30ebee86061ea72bd29d68ff6165970dd5a9efde7910` |
| `BTC_V3_CORE_V1_FROZEN` | `631374d50cfa75d46349c0e7e8b2f26ac482e2bbf6dc1cf74dc8e1a00e16a9fd` |

Stage 3, Stage 4, Stage 5 and all MT5 strategy sources were never modified.
Every research arm was an isolated wrapper in a per-phase registry that never
reached the production workspace.

---

## 3. DEVELOPMENT RESULTS

### Frozen Core reference (3R, as inherited)

| metric | value |
|---|---|
| closed trades | 177 |
| trades/month | 9.70 |
| profit factor | 1.0812 |
| Avg R | +0.0634 |
| total R | +11.23 |
| Max drawdown | 2.95% |
| longest losing streak | 10 |

### Best development configurations found

| configuration | trades/mo | PF | Avg R | total R | Max DD |
|---|---:|---:|---:|---:|---:|
| Frozen Core @ 2.00R | 10.20 | 1.1266 | +0.0829 | +15.42 | 2.71% |
| Frozen Core @ 1.75R | 10.31 | 1.1116 | +0.0699 | +13.14 | 2.85% |
| **Frozen T3 alone @ 2.00R** | **4.82** | **1.2596** | **+0.1596** | **+14.05** | **1.46%** |
| Frozen Core @ 3.00R (incumbent) | 9.70 | 1.0812 | +0.0634 | +11.23 | 2.95% |

None reaches the frequency objective. The only configuration that did —
Core + F3a at 26.75–32.40 trades/month — was below break-even at every reward
multiple from 1.0R to 3.0R.

---

## 4. HOLDOUT RESULTS (consumed)

**Candidate:** frozen T3 SHORT, entries / filters / structural stop unchanged,
reward multiple fixed at 2.00R. Predeclared and committed at `43ddb05` **before**
the split was opened. One configuration; zero alternative reward multiples
tested out of sample.

| metric | development | **holdout** |
|---|---:|---:|
| trades | 88 | **85** |
| trades/month | 4.82 | **6.03** |
| win rate | 38.64% | **35.29%** |
| profit factor | 1.2596 | **1.0889** |
| Avg R | +0.1596 | **+0.0596** |
| total R | +14.05 | **+5.07** |
| PnL | — | **+122.93** |
| Max drawdown | 1.46% | **2.51%** |
| longest losing streak | 6 | **7** |

### Locked gate table

| gate | required | observed | result |
|---|---|---|---|
| Profit factor | ≥ 1.10 | **1.0889** | **FAIL** |
| Avg R | > 0 | +0.0596 | PASS |
| Total R | > 0 | +5.0693 | PASS |
| Max drawdown | < 4% | 2.5149% | PASS |

**1 of 4 failed → REJECT T3 2.0R.** The miss is 0.011. It was not reinterpreted:
the gate was fixed and committed before the data was read precisely so a near
miss could not be argued into a pass. Supporting diagnostics point the same way
— June 2026 alone is +7.00R of the +5.07R total (138%), 2026Q2 carries the whole
result, 7 of 13 months are negative, the final subperiod is 0-for-4 at −4.00R,
and a 0.02% slippage assumption turns +5.07R into −6.28R at PF 0.8852.

---

## 5. EVERY REJECTED RESEARCH BRANCH

### Phase A — local quality-gate ablation · REJECT ALL

Body threshold 0.70 (baseline) → 0.60 / 0.50 / 0.40, on A4 and T3, standalone
and inside Core. Judged on newly admitted trades, not headline metrics.

| arm | newly admitted | PF | total R |
|---|---:|---:|---:|
| A4 @ 0.60 / 0.50 / 0.40 | 57 / 98 / 115 | 0.634 / 0.774 / 0.798 | −16.94 / −17.08 / −17.68 |
| T3 @ 0.60 / 0.50 / 0.40 | 35 / 57 / 69 | 0.751 / 0.420 / 0.450 | −6.82 / −28.77 / −32.66 |

**Reason:** every relaxation's newly admitted trades have clearly negative
expectancy. The quality gate is excluding trades that deserve excluding.

### Phase B — structural opportunity ablation · REJECT ALL

A4 confirmation timing window (1 / 2 / 3 bars / unbounded) and T3 structure
lookback (6 / 5 / 4 / 3). **Reason:** every bounded A4 window fails the
acceptance rule in both directions; every T3 lookback change fails on local
stability. One observation flagged for follow-up: T3 lookback 4.

*Correction recorded during this phase:* the brief assumed A4 used a one-bar
confirmation window. Measurement showed the wait is **unbounded** — median
confirmation on the 4th pullback bar, tail to 21, only 26.2% on the first
testable bar. The arms were rebuilt around the real behaviour.

### Phase C — T3 lookback-4 stability · REJECT

Subperiods, rolling windows, 10,000-sample block bootstrap, leave-one-month-out,
break-definition sensitivity, execution stress, Core impact. **Reason:** the
entire lead comes from a single 2024 cluster across 12 admitted trades. Rejected
on evidence, not returned as inconclusive.

### Phase D — complementary setup families

| family | standalone | incremental | verdict |
|---|---|---|---|
| **D1** T3 LONG mirror | 125 tr, PF 0.9295, −6.39R | 77 tr @ 3.92/mo, PF 1.0295, +2.81R net | **REJECT** — PF below 1.10, frequency below 4/mo, entire incremental total from one month |
| **D2** A4 SHORT mirror | 56 tr, PF 1.2819, +11.20R | 28 tr @ 1.43/mo, PF 1.8883, Avg R +0.5428, +4.54R net | carried to Phase E (only failure: frequency) |
| **D3** T3 RANGE sweep | 58 tr, PF 0.6423, −16.18R | 58 tr @ 2.95/mo, PF 0.6436, Avg R −0.2790, −15.18R net | **REJECT** — negative expectancy |

*Audit finding:* the briefed third candidate (compression → expansion) was
already implemented and REJECTED as `BTC_V3_M1_MOMENTUM_EXPANSION`. All eight
prior BTC rejections were established on **Bitstamp data at a $10 constant
spread over 2021–2023/24** — roughly half the real Exness per-bar spread, over a
different period.

### Phase E — D2 stability and integration · REJECT D2

**Reason:** the contention ledger dissolved the headline. Of D2's trades inside
the Core, **20 were genuinely additive and worth +3.20R (Avg R +0.160)**, while
**9 blocked T3 trades worth +10.66R (Avg R +1.185)**. D2 adds +0.16R trades and
removes +1.19R ones. Rolling 3M and 6M median deltas were both **−0.52R**;
removing 2025 H1 took +15.20R to +3.00R; a 0.05 step on the body threshold
flipped the sign; 0.05% slippage gave −3.39R. Five of eight acceptance
conditions failed, structurally rather than statistically.

*Measured, not assumed:* Policy 2 (frozen-Core priority) was identical to Policy
1 because **zero of D2's 29 orders were created during a baseline-busy interval**
— a policy gating D2's entry cannot reach a cost arising from its holding.

### Phase F — transition-regime families · REJECT ALL

TRANSITION was found to be a **residual bucket**, not a state — no frozen module
names it. Decomposition of its 28,879 bars (50.31% of development):
`WIDE_BUT_M15_OPPOSED` 42.56%, `WIDE_BUT_WEAK_ADX` 40.48%, `EMERGING_SEPARATION`
10.64%, `WIDE_BUT_H1_UNALIGNED` 6.32%. Measured: **0 A4 setups and 0 T3 setups**
on any transition bar (of 161 and 142 unconstrained setups respectively).

| family | standalone PF (3 variants) | verdict |
|---|---|---|
| **F1** Emerging-Trend Breakout | 0.7383 / 0.6572 / 0.6965 | **REJECT** — negative at every variant and subperiod |
| **F2** EMA Trend-Initiation | 0.8273 / 0.8880 / 1.4123 | **REJECT** — the positive arm is 12 trades at 0.61/mo whose best month is 1,127% of its total |
| **F3** Failed-Break Reversal | 0.8919 / 0.9161 / 0.9757 | **REJECT** — incremental PF 0.9123, Avg R −0.0645, DD 2.95% → 8.45% |

The briefed breakout → retest → continuation family was **not rebuilt**: the
audit showed it is PB2/PB3's mechanism, and PB3 had already run 20 of its 50
development trades on transition bars.

**The programme's most consequential single number:** Core + F3a reached
**26.75 trades/month** — inside the 24–30 objective — with **16.13 genuinely free
trades/month** and only **5.7%** frozen-child interference, at **PF 0.9849**.
Capacity and contention were both solved. Edge was not.

*Prior-research audit (re-run on Exness DEVELOPMENT):*

| family | trades | PF | total R | % on transition bars |
|---|---:|---:|---:|---:|
| PB1 shallow pullback | 494 | 0.811 | **−71.23** | 50.2% |
| PB2 reclaim SHORT / LONG | 8 / 2 | — / 3.07 | −8.00 / +2.07 | 37.5% / 0% |
| PB3 pivot acceptance | 50 | 1.061 | +2.42 | 40.0% |
| V3-R2 range sweep | 14 | 1.182 | +1.91 | **0.0%** |
| V3-M1 momentum expansion | 72 | 0.704 | **−17.06** | 55.6% |
| V3-MR1 overshoot | 27 | 0.729 | −5.79 | 44.4% |

### Phase G — fixed-3R feasibility · SEARCH EXHAUSTED

24 event × direction cells, 42,415 measured trades, entered at next-bar open with
the frozen structural stop. A fixed 3R against a 1R stop breaks even at exactly
**25%**.

**Net of the broker's own spread, zero cells fall below the 5% significance
level** where 1.2 were expected by chance; best net p = 0.1619. The only
marginal gross results — rotation toward H1 in the opposed bucket (25.89%,
p = 0.0243) and continuation against H1 in the weak-ADX bucket (25.66%,
p = 0.0504) — are edges of **+0.89 and +0.66 percentage points**, and one spread
crossing costs **≈0.11R**. Both go to p = 0.999 and p = 0.987 once it is paid.

**Instrument calibration (why the negative result is readable):**

| control pool | n | +3R first | p |
|---|---:|---:|---:|
| Every development bar, no filter, toward H1 | 42,385 | 24.43% | 0.997 |
| TREND buckets | 6,635 | 25.09% | 0.434 |
| NEUTRAL_RANGE | 4,799 | 24.48% | 0.800 |
| Frozen A4's own setups | 161 | 26.09% | 0.404 |
| **Frozen T3's own setups** | 142 | **31.69%** | **0.043** |

The unfiltered null lands on 24.4% — 25% less cost drag — and exactly one pool in
the entire phase clears the line: the frozen T3's own setups, the one component
that passed validation. The measurement finds the edge known to exist and nothing
in the transition pools.

### Architecture Reset A — reward/exit feasibility · MOVE TO LOWER FIXED RR

Seven targets from 1.0R to 3.0R, entries untouched.

- **Raw event pools: negative at every target in all 42 cells.** The spread cost
  drag is **flat across targets** (0.061–0.136R) because it is a fixed fraction
  of the stop; gross expectancy is ≈0 at every target. Phase G's random walk
  holds at *every* reward multiple.
- **A4: no stable region** — every positive target is carried by one month
  (163% / 363% / 182% of its own total).
- **T3: region 1.75R–3.00R**, clearing its own break-even at **7 of 7** targets.
- **Core: region 1.75R–2.00R**, beating the 3R incumbent on PF, total R and
  drawdown simultaneously.
- **Stress:** under spread ×1.20 + 0.02% slippage every Core target sits at or
  below break-even (1.008 / 0.977 / 0.993). **1.75R beats 3.00R in all five
  arms**; the native-best 2.00R loses the two hardest.
- **It bought quality, not frequency.** The only ≥24/month configuration is below
  break-even at all seven targets and loses 52R under combined stress.

*A caveat recorded then and still standing:* lowering the target is not a pure
exit change in a single-position system. Frozen A4 fills 93 trades at 3.0R and
101 at 1.5R from an identical **signal** stream, because trades finish sooner and
free the slot.

### Architecture Reset B — M5 execution · REJECTED ON COST GEOMETRY

**Data:** no validated broker-native Exness BTCUSDm M5 history exists. The
registry holds only `15m` and `1h`, a filesystem sweep finds nothing, and
`mt5/Export_BTCUSD_History.mq5` emits `PERIOD_M15` and `PERIOD_H1` only.
Acquisition needs a Windows MT5 terminal on `Exness-MT5Trial5`. Bitstamp was not
substituted and M15 was not resampled downward. **Sections B–G of that brief were
not run and no numbers were reported for them.**

**Cost:** the gate needed no M5 bar, because two of its three components are
measured to be scale-invariant.

| component | finding |
|---|---|
| broker bar spread vs bar size | **invariant** — median 28.80 on both M15 and H1, ratio 1.0000 |
| structural stop in ATR units | **invariant** — 0.952–0.971 ATR across a 16× duration range |
| ATR vs duration | fitted `ATR ∝ duration^0.5354`, worst error 0.75% over six durations; M15→H1 aggregate matches the independent broker H1 to 100.00% |

Only ATR moves, so **M5 costs 1.73× more per unit of risk than M15** at the
random-walk bound most favourable to M5 (1.80× at the fitted exponent). Applying
exactly that to the frozen Core: **+13.14R → −0.16R at 1.75R**, **+15.42R →
+1.25R at 2.00R**, **+11.23R → +0.37R at 3.00R**, before any slippage.

Cost per R across durations runs 0.129 (M15) → 0.090 → 0.062 → 0.043 → 0.030
(H4). M5 moves the wrong way along that gradient.

---

## 6. COMMITS

| commit | content |
|---|---|
| `9e4de31` | Diagnostic-only pre-setup funnel and X-Ray for the frozen Core |
| `2274f28` | Phase A — body-threshold ablation, all relaxations rejected |
| `2ef000f` | Maintenance — trade-log timestamps as UTC ISO text |
| `1d1c7b2` | Phase B — confirmation timing and structure lookback, all rejected |
| `00cab6d` | Phase C — T3 lookback-4 is one 2024 cluster, rejected |
| `7e7497c` | Phase D — D1 and D3 rejected, D2 carried forward |
| `32f7861` | Phase E — D2's edge is a T3 substitution, rejected |
| `0999970` | Phase F — transition has capacity but not edge, all rejected |
| `f284f17` | Phase G — transition pools are a driftless path, 3R search exhausted |
| `6a65ab9` | Architecture Reset A — lower RR helps quality, not frequency |
| `3f4c4a6` | Architecture Reset B — M5 rejected on cost geometry |
| `43ddb05` | **Predeclaration of the T3 2.0R candidate and gates, before the holdout was opened** |
| `dca2e46` | T3 2.0R holdout — PF 1.0889 against a locked 1.10, rejected |

Reports: `reports/research/core_v2_phase_{a,b,c,d,e,f,g}.{md,json}`,
`reports/research/architecture_reset_{a,b}.{md,json}`,
`reports/validation/t3_2r_holdout_validation.{md,json}`,
`reports/validation/exness_btc_core_presetup_funnel.md`.

---

## 7. TEST COUNTS

**Final suite: 1,419 passing.** Programme contribution:

| suite | tests |
|---|---:|
| `test_core_funnel_diagnostics` | 70 |
| `test_core_v2_phase_a` | 55 |
| `test_trade_log_timestamps` | 37 |
| `test_core_v2_phase_b` | 66 |
| `test_core_v2_phase_c` | 48 |
| `test_core_v2_phase_d` | 44 |
| `test_core_v2_phase_e` | 52 |
| `test_core_v2_phase_f` | 41 |
| `test_core_v2_phase_g` | 31 |
| `test_architecture_reset_a` | 24 |
| `test_architecture_reset_b` | 20 |
| `test_t3_2r_holdout_validation` | 20 |
| **total added by this programme** | **508** |

MT5 static source checks: 80 checks, PASS, at every phase.

---

## 8. KNOWN LIMITATIONS

1. **One instrument, one broker, one dataset.** Every conclusion is about
   Exness BTCUSDm M15 between 2023-11-10 and 2026-09-20. Nothing here
   generalises to other symbols, brokers or spread models without re-testing.
2. **The holdout is now spent** (see *Rules*, below).
3. **Single-position architecture throughout.** Every incremental measurement is
   conditioned on one global position slot. A multi-position architecture was
   never tested and could change contention conclusions materially — though not
   the Phase G / Reset A cost findings, which are per-trade.
4. **MFE/MAE are `BAR_BASED_APPROXIMATION`.** OHLC cannot reveal the intrabar
   path. Same-bar ambiguity was always resolved pessimistically (`SL_FIRST`),
   matching the engine, but it is a convention, not a measurement.
5. **The M5 cost projection is an extrapolation** below the shortest bar in hand.
   It rests on two measured invariances and one fitted law, and uses the bound
   most favourable to M5, but no M5 bar was ever observed.
6. **Phase G's controls are underpowered at the small end.** A4's 161 setups at
   26.09% (p = 0.40) is absence of evidence, not evidence of absence. T3's
   31.69% at n = 142 (p = 0.043) is itself a single modest result, offered as
   calibration rather than a fresh claim.
7. **Slippage was modelled as a percentage, not from tick data.** The only tick
   files present are single-day 2026-08 samples inside the holdout window.
8. **Prior-rejection reasons were inherited, not always re-derived.** PB1/PB2/
   PB3/M1/MR1/R2 were re-run on Exness DEVELOPMENT in Phase F, but their original
   rejection rationales came from Bitstamp at a constant $10 spread.
9. **No walk-forward, Monte Carlo or demo-execution validation was performed.**
   The candidate never reached that stage.

---

## 9. LESSONS LEARNED

1. **Measure the pool before building the strategy.** Phases D, E and F each
   spent a full cycle building families that Phase G's twenty-line outcome map
   could have pre-empted. Once the raw bars were measured directly, the answer
   took one phase.
2. **Compare against the right null.** At a fixed R:1 payoff the break-even hit
   rate is `1/(1+R)`, and a driftless path lands on it exactly. Reading a 25.9%
   rate as promising without that reference is the single easiest way to
   manufacture an edge from noise.
3. **Test the instrument on something known to work.** Phase G's negative result
   only became readable once the same machinery found T3's own setups at 31.69%,
   p = 0.043, and nothing else. A detector that never fires proves nothing.
4. **Contention is not the same as addition.** Phase E's D2 looked like +15.20R
   at PF 1.89 until the ledger showed 9 of those "added" trades were blocked T3
   trades worth +10.66R. Any candidate sharing a position slot needs a
   trade-level ledger, not a metric delta.
5. **Cost is a fixed fraction of the stop, not of the target.** This is why
   lowering the reward multiple does not reduce the drag, and why moving to a
   faster timeframe increases it. It explains Reset A and Reset B with one fact.
6. **Frequency and edge were never the same problem.** Phase F solved frequency
   (26.75 trades/month, 5.7% interference) and failed on edge. No later phase
   changed that; the objective was always going to be decided by edge.
7. **Lock the gate before reading the data, and honour it.** The T3 2.0R holdout
   missed PF 1.10 by 0.011. Because the threshold was committed at `43ddb05`
   first, there was nothing to negotiate — which is the entire value of having
   done it that way.
8. **Verify the premise before testing it.** Phase B's brief assumed a one-bar
   A4 confirmation window; the actual wait is unbounded. Phase F's brief assumed
   TRANSITION was a frozen concept; it is a residual in a research module.
   Correcting both changed what the phases measured.
9. **A rejection with a mechanism is worth more than one without.** "Rejected —
   PF too low" is a dead end. "Rejected — the pool is a driftless path and the
   spread exceeds the drift" tells you which future ideas are also dead.

---

## 10. RULES FOR FUTURE BTC RESEARCH

These are binding on any continuation of this work.

1. **The 2025-07-01 → 2026-09-20 holdout is CONSUMED.** It must never again be
   treated as untouched out-of-sample data. Any future report describing it as
   OOS is wrong.
2. **No parameter may be selected because of performance on that consumed
   holdout.** This includes reward multiple, body threshold, slope threshold,
   structure lookback, RSI bands, ADX minimum, stop geometry, session and daily
   cap. The T3 2.0R result must not be used to justify trying 1.75R, 2.25R or
   any neighbour.
3. **Future validation requires genuinely new unseen data** — bars after
   2026-09-20, a different instrument, or a different broker — captured through
   the existing exporter and data-validation architecture, fingerprinted, and
   reserved before any candidate is defined.
4. **Rejected Phase A–G families must not be silently reintroduced.** PB1, PB2
   LONG/SHORT, PB3, V3-M1, V3-MR1, V3-R2, D1, D2, D3, F1, F2, F3 and every body,
   timing and lookback relaxation are closed. Re-proposing one requires naming it
   and stating what materially new evidence justifies reopening it.
5. **T3 2.0R may be retained only as a fixed research benchmark.** It is a
   reference line for future work, not a candidate, not a baseline to improve on
   by tuning, and not a fallback.
6. **No Stage 4 demo or live activation may be based on these results.** No
   strategy in this programme reached demo readiness. The frozen Core remains a
   research reference only.

Two further constraints follow from the evidence rather than from instruction,
recorded so they are not rediscovered at cost:

7. Any new M15 family must clear a **≈0.11R per-trade cost** and be measured
   against `1/(1+R)`, not against zero. Phase G's machinery
   (`research/core_v2_phase_g_outcomes.py`) is timeframe-agnostic and should be
   run on the raw pool **before** a strategy is written.
8. Any shorter timeframe inherits a **larger cost per unit risk** — 1.73× at M5 —
   because the spread does not shrink with the bar while ATR does. A faster
   execution timeframe needs a proportionally larger edge, not merely more
   signals.

---

**Program closed. No new BTC strategy is approved for live or demo execution.**
