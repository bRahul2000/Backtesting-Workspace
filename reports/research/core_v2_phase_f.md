# BTC Core V2 — Phase F: Transition-Regime Opportunity Discovery

**Split:** DEVELOPMENT 2023-11-10 23:15 → 2025-06-30 23:45 UTC (57,403 bars, 19.65 months).
**Holdout touched: NO.** **Dataset:** `data/exness/btc/phase_r1/processed/btcusdm_M15.csv`,
fingerprint `80735a2cf521363747f48368814267ad6ca146eb294bb7bd7252666d06c76af3`.
**Baseline Core:** 177 closed trades, 9.70/month, PF 1.0812, Avg R +0.0634, total R +11.23,
Max DD 2.95%, longest losing streak 10.

**Verdict: REJECT ALL THREE FAMILIES.** The transition pool has more than enough
capacity to reach 24–30 trades/month — F3a alone delivers 16.13 genuinely free
Core trades per month on top of the Core's 9.70 — and almost no contention with
the frozen children. What it does not have is an edge. Every one of the nine
arms has standalone PF below 1, and eight of nine make the Core worse.

---

## 1. Transition definition

The brief asked me to inspect the frozen regime classifier and document what
TRANSITION means in source. It means nothing in source: **no frozen module names
it.** `strategies/confirmed_h1_regime.py` emits no regime labels at all — only
`fast_ema`, `slow_ema`, `slope` and `separation_atr`. A test asserts the string
`TRANSITION` appears in none of A4, T3, Core, L2 or the H1 classifier.

The label exists in exactly one place, `research/core_v2_opportunity_map.py`,
where it is the **`else` branch** of a four-way census:

| bucket | condition |
|---|---|
| `WARMUP` | separation, slope, ADX or ATR not yet available |
| `BULLISH_TREND` | `separation ≥ 1.00` **and** `ADX ≥ 18` **and** `h1.fast > h1.slow` **and** `slope > 0` **and** `ema20 > ema50` |
| `BEARISH_TREND` | the same, mirrored |
| `NEUTRAL_RANGE` | `separation ≤ 0.80` |
| **`TRANSITION`** | **everything else** |

Every threshold is lifted from the frozen children: 1.00 is `V3T3FrozenParameters.trend_min_h1_separation_atr`
and `V3L2Parameters.h1_min_separation_atr`, 18.0 is `trend_min_adx` / `min_adx`,
0.80 is `range_max_h1_separation_atr`.

Two consequences follow, and both matter more than the bar count.

**TRANSITION is a residual, not a state.** A bar lands there for any of four
unrelated reasons, so "51% of the market is transitional" is not one opportunity.

**A4 and T3 structurally cannot fire there.** Both require `separation ≥ 1.00`,
`ADX ≥ 18` and an aligned M15 stack — a strict superset of the frozen TREND
condition. Measured, not assumed: driving both frozen children across all 57,403
development bars with a permanently flat execution state produces 161 A4 setups
and 142 T3 setups, and **0 of either on a TRANSITION bar**.

The census reproduces the Phase D map **bar for bar, 0 bucket mismatches**, and
the strategy-side `frozen_bucket()` is verified against it on every development
bar.

## 2. Transition sub-bucket map

28,879 bars, 50.31% of development, 7.66% inside a Core position, 26,667 of them
with the Core flat.

**Why each bar is TRANSITION** — disjoint and exhaustive, each naming the frozen
gate it failed:

| reason | bars | % of transition | what it is |
|---|---|---|---|
| `WIDE_BUT_M15_OPPOSED` | 12,292 | **42.56%** | H1 agrees with itself, M15 stack faces the other way |
| `WIDE_BUT_WEAK_ADX` | 11,689 | **40.48%** | trend geometry present, momentum below ADX 18 |
| `EMERGING_SEPARATION` | 3,072 | 10.64% | separation between 0.80 and 1.00 |
| `WIDE_BUT_H1_UNALIGNED` | 1,826 | 6.32% | H1 EMAs and H1 slope disagree — a trend rolling over |

**This reframes the phase before a line of strategy code.** Only 10.6% of the
pool is "not yet wide enough"; 42.6% is not emergence at all but the M15
disagreeing with the H1, and 6.3% is a trend ending rather than starting.

**Descriptive overlays:**

| dimension | split |
|---|---|
| H1 lean | bullish 17,160 (59.42%) · bearish 11,719 (40.58%) |
| H1 slope sign | positive 17,140 (59.35%) · negative 11,739 (40.65%) |
| separation | expanding 16,278 (56.37%) · contracting 12,601 (43.63%) |
| slope turn | none 28,322 (98.07%) · turned negative 287 (0.99%) · turned positive 270 (0.94%) |
| M15 vs H1 lean | **opposed 20,432 (70.75%)** · aligned 8,447 (29.25%) |
| EMA cross within 5 bars | no 25,079 (86.84%) · yes 3,800 (13.16%) |
| volatility | normal 12,852 (44.50%) · compression 10,136 (35.10%) · expansion 5,891 (20.40%) |

Cross-tabulated, the pool a directional continuation family can actually address
— M15 aligned with the H1 lean **and** separation expanding — is 7,099 bars
(24.58% of transition, 361/month), and the literal "emerging trend" reading
(`EMERGING_SEPARATION` + aligned + expanding) is 1,293 bars, 4.48%.

## 3. Transition event map

Fixed structural definitions, all causal, every constant from a frozen or
validated source: 5-bar structure and 8-bar sweep window and 0.70 body and
0.60–2.00 ATR range from T3, 5-bar retest window and 0.10 ATR tolerance from PB2.

| event | count | /month | bull lean | bear lean | % Core flat | A4 overlap | T3 overlap |
|---|---|---|---|---|---|---|---|
| `PULLBACK_TOUCH_EMA20_LONG` | 7,799 | 396.95 | 3,706 | 4,093 | 89.0 | **0** | **0** |
| `PULLBACK_TOUCH_EMA20_SHORT` | 7,412 | 377.25 | 5,645 | 1,767 | 93.7 | **0** | **0** |
| `PULLBACK_TOUCH_EMA50_LONG` | 4,503 | 229.19 | 2,255 | 2,248 | 88.7 | **0** | **0** |
| `PULLBACK_TOUCH_EMA50_SHORT` | 4,298 | 218.76 | 3,121 | 1,177 | 93.1 | **0** | **0** |
| `BREAKOUT_UP` | 3,210 | 163.38 | 1,860 | 1,350 | 93.0 | **0** | **0** |
| `BREAKDOWN` | 2,931 | 149.18 | 1,796 | 1,135 | 92.4 | **0** | **0** |
| `SWEEP_REJECTION_UP` | 2,833 | 144.19 | 1,558 | 1,275 | 93.0 | **0** | **0** |
| `SWEEP_REJECTION_DOWN` | 2,696 | 137.22 | 1,759 | 937 | 91.3 | **0** | **0** |
| `RETEST_AFTER_BREAKOUT_UP` | 2,521 | 128.31 | 1,418 | 1,103 | 93.4 | **0** | **0** |
| `RETEST_AFTER_BREAKDOWN` | 2,376 | 120.93 | 1,501 | 875 | 92.5 | **0** | **0** |
| `STRONG_CANDLE_UP` | 2,240 | 114.01 | 1,379 | 861 | 92.2 | **0** | **0** |
| `STRONG_CANDLE_DOWN` | 2,044 | 104.03 | 1,206 | 838 | 92.8 | **0** | **0** |
| `RECLAIM_CONTINUATION_UP` | 1,388 | 70.65 | 769 | 619 | 92.8 | **0** | **0** |
| `RECLAIM_CONTINUATION_DOWN` | 1,233 | 62.76 | 809 | 424 | 91.9 | **0** | **0** |
| `FAILED_BREAKOUT_REVERSAL_DOWN` | 1,037 | 52.78 | 569 | 468 | 93.2 | **0** | **0** |
| `FAILED_BREAKDOWN_REVERSAL_UP` | 975 | 49.62 | 626 | 349 | 92.4 | **0** | **0** |
| `EMA20_CROSS_DOWN` | 375 | 19.09 | 292 | 83 | 92.0 | **0** | **0** |
| `EMA20_CROSS_UP` | 341 | 17.36 | 129 | 212 | 93.3 | **0** | **0** |

Raw opportunity is not the constraint: ~90% of every event occurs with the Core
flat, and A4/T3 overlap is zero everywhere.

## 4. Prior-research duplication audit

Each previously rejected family re-run on this split, its entry bars mapped to
census buckets. This is the evidence the brief asked for, not a docstring
reading.

| family | status | trades | PF | total R | % on TRANSITION bars |
|---|---|---|---|---|---|
| PB1 shallow pullback | REJECTED | 494 | 0.811 | **−71.23** | **50.2%** |
| PB2 reclaim LONG | REJECTED | 2 | 3.07 | +2.07 | 0.0% |
| PB2 reclaim SHORT | REJECTED | 8 | — | −8.00 | 37.5% |
| PB3 pivot acceptance LONG | REJECTED | 50 | 1.061 | +2.42 | **40.0%** |
| V3-R2 range liquidity sweep | REJECTED | 14 | 1.182 | +1.91 | **0.0%** |
| V3-M1 momentum expansion | REJECTED | 72 | 0.704 | **−17.06** | **55.6%** |
| V3-MR1 intraday overshoot | REJECTED | 27 | 0.729 | −5.79 | 44.4% |

**TRANSITION is not virgin territory.** PB1, PB2 SHORT, PB3, M1 and MR1 all gate
on an H1 EMA *lean* or on nothing at all, so none of them excludes these bars,
and they already traded there — PB1 with 248 transition entries inside a −71R
result. The four families that were free to enter transition lost money overall
on this split.

**Briefed family F2 (breakout → retest → continuation) is materially equivalent
to PB2 and PB3 and was not rebuilt.** PB2 is displacement through a 12-bar
structure level → retest → reclaim → acceptance → stop entry; PB3 is a confirmed
pivot break → retest → reclaim → acceptance → stop entry. Both are the same
four-stage state machine with the same entry model, the same structural stop and
the same fixed 3R, and PB3 already ran 20 of its 50 development trades on
TRANSITION bars. Per the brief, it was rejected without rebuilding and replaced
(§5, F2).

**F3 is cleared.** V3-R2 is the repository's sweep-reversal family and its own
source disables it whenever a strong trend is active or separation exceeds 0.80,
so it entered on **0** transition bars. PB3 reclaims in the *break* direction;
F3 trades the opposite way. Neither duplicates it.

**F1 is cleared.** No prior family conditions on being pre-trend; A4/T3/D1
require established trend, PB1's generator is a measured impulse, M1 ignores H1.

---

## 5. Families

Each family had exactly three predeclared structural variants, fixed before any
was run. No numeric threshold was searched: every constant comes from
`V3T3FrozenParameters` — continuation families use T3's trend band (body 0.70,
range 0.60–2.00 ATR, RSI 50–76 / 24–50, extension 2.50 ATR, 0.05/0.20 ATR
buffers, 2-bar stop lookback, 2-bar pending), the reversal family uses T3's own
reversal band (body 0.35, RSI ≤ 46 long / ≥ 54 short). 3R throughout.

All nine arms fire **only** on TRANSITION bars, verified across the full split.

Which sub-buckets each family reaches was measured rather than assumed, and it
lines up with what each mechanism is:

| baseline arm | setups | sub-buckets reached | M15 alignment |
|---|---|---|---|
| F1a | 220 | `WIDE_BUT_WEAK_ADX` 180 · `EMERGING_SEPARATION` 40 | **100% aligned** |
| F2a | 29 | `WIDE_BUT_WEAK_ADX` 23 · `EMERGING_SEPARATION` 6 | **100% aligned** |
| F3a | 553 | `WIDE_BUT_M15_OPPOSED` 282 · `WIDE_BUT_WEAK_ADX` 155 · `EMERGING_SEPARATION` 68 · `WIDE_BUT_H1_UNALIGNED` 48 | opposed 431 / aligned 122 |

The two directional families are confined by construction to the two genuinely
pre-trend reasons and to the 8,447 M15-aligned bars — 29% of the pool. F3 is the
only family that reaches the large `WIDE_BUT_M15_OPPOSED` bucket, and it reaches
it with 282 of its 553 setups.

### Family F1 — Emerging-Trend Breakout

The frozen T3 trend engine with its regime gate moved and both sides enabled,
and nothing else changed — a diff against `V3T3FrozenParameters` shows exactly
three fields differ (`longs_enabled`, `trend_min_h1_separation_atr`,
`trend_min_adx`), and the real gate is the explicit TRANSITION check. Acts
before the regime becomes a trend. Variants: **F1a** 5-bar structure with
separation expanding (baseline), **F1b** expansion not required, **F1c** 3-bar
structure.

**Standalone**

| arm | trades | /mo | WR | PF | Avg R | total R | PnL | Max DD | streak | L/S |
|---|---|---|---|---|---|---|---|---|---|---|
| F1a | 151 | 8.28 | 19.87% | **0.7383** | −0.2097 | **−31.66** | −785.19 | 7.04% | 12 | 114/37 |
| F1b | 166 | 9.10 | 18.07% | 0.6572 | −0.2816 | −46.74 | −1151.21 | 8.43% | 12 | 127/39 |
| F1c | 174 | 9.54 | 18.97% | 0.6965 | −0.2447 | −42.58 | −1055.89 | 6.85% | 14 | 130/44 |

Win rate 18–20% against a 25% break-even at 3R. **Every subperiod negative** for
every variant (F1a: −0.08 / −6.75 / −16.74 / −8.09 R).

**Inside the Core** — F1a: 294 trades, 16.12/mo, PF 0.9017, Avg R −0.0735, total
R −21.62, DD 7.80%, streak 13. Incremental 130 trades at 6.62/mo, PF 0.7160,
Avg R −0.2291, total R −29.78, **net −32.85R**, DD +4.85pp, MFE 1.21R vs MAE
1.14R.

**Contention** — 118 truly additive (−30.12R), 9 entered flat then blocked a
frozen trade (frozen trades lost worth +3.07R), 0 same-bar displacements. Only
7.1% of its Core trades cost a frozen trade. Net free contribution **−33.19R**.

**Capacity** — 312.6 raw events/mo → 11.20 setups/mo (3.58%) → 7.69 fills/mo
(68.64%) → 6.62 incremental/mo → **6.01 genuinely free Core trades/mo**.

**Verdict: REJECT.** Standalone PF 0.74; incremental PF 0.72; Avg R −0.23. The
frequency target is reachable and the trades are nearly free — they are simply
losing trades. Structural variants move the number, never the sign.

### Family F2 — Transition EMA Trend-Initiation *(substituted)*

Replaces the briefed breakout→retest→continuation, which the audit closed as
PB2/PB3. The M15 EMA20/EMA50 cross itself is the trigger, with the confirmed H1
lean already pointing that way — a mechanism no family in the repository uses.
Variants: **F2a** the cross bar must be the directional candle (baseline),
**F2b** a confirmation bar within 3, **F2c** cross bar with separation expanding.

**Standalone**

| arm | trades | /mo | WR | PF | Avg R | total R | PnL | Max DD | streak | L/S |
|---|---|---|---|---|---|---|---|---|---|---|
| F2a | 19 | 1.04 | 21.05% | 0.8273 | −0.1330 | −2.53 | −63.00 | 1.25% | 5 | 12/7 |
| F2b | 44 | 2.41 | 22.73% | 0.8880 | −0.0859 | −3.78 | −94.80 | 3.24% | 13 | 27/17 |
| F2c | 13 | 0.71 | 30.77% | **1.4123** | **+0.2717** | **+3.53** | +88.17 | 1.00% | 4 | 7/6 |

**Inside the Core** — F2c: 188 trades, 10.31/mo, PF 1.0876, total R +12.76, DD
2.95%. Incremental 12 trades at **0.61/mo**, PF 1.0542, Avg R +0.0444, total R
+0.53, net **+1.53R**.

**Contention** — F2c: 11 truly additive (+1.53R), 1 entered flat then blocked a
frozen trade (−1.00R), 0 displacements, 8.3% cost rate. Net free **+2.53R**.

**Capacity** — 36.4 raw events/mo → 1.02 setups/mo → 0.66 fills/mo → **0.56
genuinely free Core trades/mo**.

**Verdict: REJECT.** F2c is the only arm in the phase with a positive
incremental result, and it fails on every other axis at once. Its 12 added trades
span 8 months of which **2 are positive and 6 negative**; January 2024 alone is
**+6.00R of a +0.53R total** — the best month is 1,127% of the result. 0.61
trades/month is below even the 2/month viability floor, let alone 4. And the
sign is reversed by a single structural variant: the same family without the
expansion gate (F2a) is PF 0.827 standalone and −1.43R net. This is noise with a
good-looking ratio attached to it, and the raw pool (36 events/month, the
smallest in the map) cannot support more.

### Family F3 — Transition Failed-Break Reversal

A close through the 5-bar structure level that does not hold, then a close back
through it, traded the other way, stopped beyond the extreme the failed break
actually reached. Variants: **F3a** 3-bar reversal window (baseline), **F3b**
5-bar window, **F3c** 3-bar window plus an acceptance bar.

**Standalone**

| arm | trades | /mo | WR | PF | Avg R | total R | PnL | Max DD | streak | L/S |
|---|---|---|---|---|---|---|---|---|---|---|
| F3a | 359 | 19.68 | 22.84% | 0.8919 | −0.0803 | −28.82 | −723.27 | 8.92% | 19 | 180/179 |
| F3b | 334 | 18.31 | 23.35% | 0.9161 | −0.0612 | −20.44 | −524.11 | 6.61% | 20 | 169/165 |
| F3c | 98 | 5.37 | 24.49% | 0.9757 | −0.0154 | −1.51 | −44.07 | 4.14% | 10 | 51/47 |

Almost perfectly balanced long/short, and converging on break-even from below as
the confirmation tightens — 0.892 → 0.916 → 0.976 — without ever crossing it.

**Inside the Core** — F3a: 488 trades, **26.75/mo**, PF 0.9849, Avg R −0.0082,
total R −4.02, DD 8.45%, streak 18. Incremental 337 trades at **17.15/mo**, PF
0.9123, Avg R −0.0645, total R −21.75, net −15.24R, DD +5.50pp, MFE 1.40R vs MAE
1.21R.

**Contention** — F3a: 317 truly additive (−42.14R), 19 entered flat then blocked
a frozen trade, 0 same-bar displacements, **5.7% cost rate** — the lowest
interference of any family in Phases D, E or F. Net free contribution −38.63R.

**Capacity** — 102.4 raw events/mo → 28.15 setups/mo (27.49%) → 18.27 fills/mo →
17.15 incremental/mo → **16.13 genuinely free Core trades/mo**.

**Verdict: REJECT.** F3a is the only family in the whole programme that actually
solves frequency: 26.75 trades/month lands inside the 24–30 target with 94% of
its trades costing the frozen Core nothing. It is rejected purely on edge —
standalone PF 0.892, incremental PF 0.912, Avg R −0.065, negative in three of
four subperiods, and it takes the Core's drawdown from 2.95% to 8.45%.

---

## 6. Comparison table

| configuration | trades/mo | PF | Avg R | total R | Max DD |
|---|---|---|---|---|---|
| **BASELINE CORE** | **9.70** | **1.0812** | **+0.0634** | **+11.23** | **2.95%** |
| Core + F1a | 16.12 | 0.9017 | −0.0735 | −21.62 | 7.80% |
| Core + F1b | 16.77 | 0.8568 | −0.1099 | −33.64 | 8.95% |
| Core + F1c | 17.16 | 0.8631 | −0.1037 | −32.47 | 7.83% |
| Core + F2a | 10.47 | 1.0646 | +0.0513 | +9.79 | 2.95% |
| Core + F2b | 11.73 | 1.0106 | +0.0115 | +2.47 | 3.44% |
| Core + F2c | 10.31 | 1.0876 | +0.0679 | +12.76 | 2.95% |
| Core + F3a | 26.75 | 0.9849 | −0.0082 | −4.02 | 8.45% |
| Core + F3b | 25.71 | 1.0108 | +0.0111 | +5.22 | 7.78% |
| Core + F3c | 14.09 | 1.0350 | +0.0293 | +7.52 | 4.67% |

No survivor, so there is no "Core + survivor" row to promote.

## 7. Phase F decision

**REJECT ALL.** All nine arms fail mechanically; the checks were declared before
the runs and applied without exception.

**Exact reasons, per family:**

- **F1 — REJECT.** Standalone PF 0.7383 / 0.6572 / 0.6965, all below 1.
  Incremental PF 0.7160 / 0.6266 / 0.6610, all below 1. Incremental Avg R
  −0.2291 / −0.3094 / −0.2775, all negative. Net contribution positive in 1 of 4
  subperiods. Core total R falls from +11.23 to −21.62 at the baseline variant.
- **F2 — REJECT.** F2a and F2b: standalone PF 0.8273 / 0.8880 and incremental PF
  0.6634 / 0.8208, both below 1, Avg R negative; F2a additionally below the
  2/month viability floor at 0.87. F2c, the only positive arm anywhere in the
  phase: one subperiod carries the entire net contribution, the best single month
  (+6.00R) exceeds the whole incremental total (+0.53R), 6 of 8 traded months are
  negative, incremental frequency 0.61/month is below the viability floor, and a
  single structural variant reverses the sign.
- **F3 — REJECT.** Standalone PF 0.8919 / 0.9161 / 0.9757, all below 1.
  Incremental PF 0.9123 / 0.9608 / 0.8498, all below 1. Incremental Avg R
  −0.0645 / −0.0272 / −0.1173, all negative. Baseline variant negative in 3 of 4
  subperiods and raises Max DD from 2.95% to 8.45%.

**What the phase established, beyond the rejections.**

The transition pool is real, large and genuinely uncontested — 50.31% of
development bars, ~90% of its events occurring with the Core flat, **zero** A4 or
T3 setups on any of them, and cost rates of 5.1–17.6% once a family is placed
inside the Core, against D2's structural conflict in Phase E. Capacity is not the
obstacle: **F3a reaches 26.75 Core trades/month, inside the 24–30 target, with
16.13 genuinely free trades/month.** Phase F is the first phase where the
frequency goal was met.

It was met at PF 0.98. Across nine arms spanning three mechanisms — structure
breakout, EMA-cross initiation, failed-break reversal — long and short, at three
structural settings each, **not one arm produced a standalone PF above 1**, and
win rates cluster at 18–25% against a 25% break-even at 3R. The five prior
families that were free to trade these bars (PB1, PB2 SHORT, PB3, M1, MR1) lost
money there too. Phases D and E rejected candidates because the Core took the
cost back through contention; Phase F rejects these because the bars themselves
do not pay at a fixed 3R, which is a different and more fundamental finding.

The sub-bucket map suggests why, and it is the one result worth carrying into any
future phase: only 10.6% of TRANSITION is separation genuinely emerging, while
42.6% is the M15 opposing the H1 and 6.3% is a trend rolling over. A directional
continuation family is trading a pool that is mostly not resolving in its
direction. That is a statement about the bucket, not a proposal — no replacement
family search was started.

---

**Holdout touched: NO.** Frozen hashes unchanged: A4 `55fedf85…`, T3 `4c4ab845…`,
Core `631374d5…`. Stage 3/4/5, MT5 sources and all Phase A–E research untouched;
Phase F arms live only in an isolated registry and never reach the production
workspace.
