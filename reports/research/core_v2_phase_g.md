# BTC Core V2 — Phase G: 3R Edge Feasibility in Opposed/Weak Transition States

**Split:** DEVELOPMENT 2023-11-10 23:15 → 2025-06-30 23:45 UTC, 57,403 bars, 19.65 months.
**Holdout touched: NO.** **Dataset:** `data/exness/btc/phase_r1/processed/btcusdm_M15.csv`,
fingerprint `80735a2cf521363747f48368814267ad6ca146eb294bb7bd7252666d06c76af3`.
**Baseline Core:** 177 trades, 9.70/month, PF 1.0812, Avg R +0.0634, +11.23R, DD 2.95%.

**Target buckets:** `WIDE_BUT_M15_OPPOSED` 12,292 bars · `WIDE_BUT_WEAK_ADX` 11,689 bars.

## Decision

**FIXED-3R HIGH-FREQUENCY DEVELOPMENT SEARCH EXHAUSTED.**

No strategy family was built, because the gate was not met. Across 24 event ×
direction cells and 42,415 measured trades, **not one pool is statistically
distinguishable from the 25% that a driftless price path produces at a 3:1
reward-to-risk ratio** — before costs, and further below it after.

---

## Method

Entry is the **next bar's open**, not a stop trigger, so nothing is lost to
unfilled pending orders and no entry rule is doing hidden selection. The stop is
the repository's own structural stop — T3's two-bar extreme ± 0.20 ATR, kept
inside T3's 0.50–3.00 ATR band — and the target is 3R from entry. Every constant
is a `V3T3FrozenParameters` field; a test asserts it. The horizon is 480 bars,
chosen because the frozen Core's own slowest 3R winner took 425.

Two honesty constraints shape every number below.

**Ambiguity is never resolved by guessing.** A bar whose range spans both the
target and the stop cannot be ordered from OHLC, so it is counted as
`AMBIGUOUS_SAME_BAR`. In practice this is negligible here — 26 and 37 cases out
of 42,415 — so it changes nothing either way.

**The break-even is 25%.** A fixed 3R against a 1R stop pays 3 and costs 1, so
`0.25 × 3 − 0.75 × 1 = 0`. Everything in this phase is read against that line,
not against zero.

The primary measurement is **net of the dataset's own per-bar spread**. The
CSV's OHLC is the bid, so a long buys at ask (entry raised by the spread) and a
short buys back at ask (stop and target lowered by it); each trade pays exactly
one crossing. This is not a detail: **the median development spread is 28.80
price units against a median ATR14 of 229.6, i.e. 0.125 ATR**, and against a
typical ~1.1 ATR stop that is roughly **0.11R of cost per trade** — an order of
magnitude larger than any gross edge found.

---

## 1. Raw event outcome map (net of spread)

| event | direction | n | med MFE | med MAE | mean MFE | mean MAE | %+1R first | %+2R first | **%+3R first** | %−1R first | amb |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| EMA20_REJECTION | AGAINST_H1 | 5,746 | 0.86 | −1.20 | 1.44 | −1.29 | 45.35 | 29.93 | 22.68 | 77.01 | 10 |
| EMA20_REJECTION | TOWARD_H1 | 6,840 | 0.77 | −1.18 | 1.37 | −1.27 | 43.26 | 29.47 | 22.27 | 77.56 | 8 |
| EMA50_REJECTION | AGAINST_H1 | 3,975 | 0.87 | −1.19 | 1.45 | −1.28 | 45.38 | 30.54 | 22.57 | 77.01 | 11 |
| EMA50_REJECTION | TOWARD_H1 | 4,568 | 0.79 | −1.18 | 1.36 | −1.28 | 43.08 | 28.79 | 21.63 | 78.26 | 2 |
| EMA_CROSS_AGAINST_H1 | AGAINST_H1 | 396 | 0.90 | −1.13 | 1.50 | −1.13 | 46.46 | 32.32 | **27.27** | 72.73 | 0 |
| EMA_CROSS_AGAINST_H1 | TOWARD_H1 | 309 | 0.74 | −1.25 | 1.34 | −1.36 | 41.75 | 26.86 | 19.09 | 80.91 | 0 |
| EMA_REALIGN_WITH_H1 | AGAINST_H1 | 88 | 1.11 | −1.25 | 1.60 | −1.32 | 48.86 | 38.64 | **27.27** | 72.73 | 0 |
| EMA_REALIGN_WITH_H1 | TOWARD_H1 | 158 | 0.74 | −1.11 | 1.40 | −1.16 | 46.84 | 29.11 | 24.68 | 75.32 | 0 |
| STRONG_CLOSE_AGAINST_H1 | AGAINST_H1 | 1,697 | 1.03 | −1.11 | 1.55 | −1.09 | 50.32 | 33.94 | **25.75** | 74.01 | 0 |
| STRONG_CLOSE_AGAINST_H1 | TOWARD_H1 | 502 | 0.57 | −1.39 | 1.03 | −1.64 | 28.49 | 18.33 | 14.34 | 85.26 | 2 |
| STRONG_CLOSE_TOWARD_H1 | AGAINST_H1 | 330 | 0.70 | −1.24 | 1.27 | −1.45 | 37.88 | 27.27 | 20.61 | 79.09 | 0 |
| STRONG_CLOSE_TOWARD_H1 | TOWARD_H1 | 1,754 | 0.93 | −1.12 | 1.47 | −1.14 | 47.43 | 32.10 | 24.12 | 75.66 | 1 |
| STRUCTURE_BREAK_3_AGAINST_H1 | AGAINST_H1 | 3,255 | 0.95 | −1.11 | 1.51 | −1.10 | 47.99 | 32.07 | 24.12 | 75.61 | 3 |
| STRUCTURE_BREAK_3_AGAINST_H1 | TOWARD_H1 | 1,619 | 0.76 | −1.31 | 1.25 | −1.56 | 37.06 | 23.97 | 18.28 | 81.28 | 6 |
| STRUCTURE_BREAK_3_TOWARD_H1 | AGAINST_H1 | 1,034 | 0.70 | −1.30 | 1.37 | −1.49 | 37.91 | 27.08 | 20.12 | 79.21 | 6 |
| STRUCTURE_BREAK_3_TOWARD_H1 | TOWARD_H1 | 3,198 | 0.84 | −1.12 | 1.40 | −1.14 | 44.65 | 30.27 | 23.20 | 76.55 | 2 |
| STRUCTURE_BREAK_5_AGAINST_H1 | AGAINST_H1 | 2,509 | 0.94 | −1.11 | 1.50 | −1.10 | 47.55 | 31.81 | 23.28 | 76.48 | 2 |
| STRUCTURE_BREAK_5_AGAINST_H1 | TOWARD_H1 | 1,306 | 0.78 | −1.32 | 1.26 | −1.57 | 37.52 | 24.35 | 18.68 | 80.93 | 4 |
| STRUCTURE_BREAK_5_TOWARD_H1 | AGAINST_H1 | 792 | 0.71 | −1.30 | 1.41 | −1.49 | 38.13 | 28.03 | 21.09 | 78.16 | 5 |
| STRUCTURE_BREAK_5_TOWARD_H1 | TOWARD_H1 | 2,339 | 0.84 | −1.11 | 1.39 | −1.13 | 44.55 | 29.54 | 22.70 | 77.04 | 1 |
| **ALL EVENTS** | **TOWARD_H1** | **22,593** | 0.80 | −1.18 | 1.36 | −1.28 | 42.78 | 28.68 | **21.76** | 78.02 | 26 |
| **ALL EVENTS** | **AGAINST_H1** | **19,822** | 0.88 | −1.16 | 1.47 | −1.23 | 45.73 | 30.80 | **23.11** | 76.55 | 37 |

Median MFE sits below +1R and median MAE below −1R in every single cell. Nothing
in this pool reaches its target more often than it reaches its stop.

## 2. 3R feasibility — significance against the 25% line

The whole question is whether any rate beats 25%, and across 20 event cells some
will sit above it by chance. So the exact one-sided binomial tail is what decides,
not the rate. **Gross of costs**, the best four cells:

| cell | n | +3R first | expectancy | exact p |
|---|---:|---:|---:|---:|
| EMA_CROSS_AGAINST_H1 \| AGAINST_H1 | 397 | 27.96% | +0.1184R | **0.0972** |
| STRONG_CLOSE_AGAINST_H1 \| AGAINST_H1 | 1,703 | 25.95% | +0.0428R | 0.1888 |
| STRONG_CLOSE_TOWARD_H1 \| TOWARD_H1 | 1,763 | 25.87% | +0.0401R | 0.2082 |
| EMA_REALIGN_WITH_H1 \| AGAINST_H1 | 98 | 27.55% | +0.1020R | 0.3151 |

Not one reaches 5%. With 20 cells tested, **one is expected below 5% by chance
alone and zero were observed**; the best p-value Bonferroni-adjusts to 1.000.
The Z-scores across all 20 cells run from −2.34 to +1.36 and centre slightly
below zero — the distribution of noise around 25%, shifted down by cost.

**The two pooled bucket-level cells were the only results that looked
marginally real, and the spread removes them:**

| pool | gross n | gross +3R | gross p | gross E | net n | net +3R | **net p** | **net E** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| WIDE_BUT_M15_OPPOSED \| **TOWARD_H1** | 9,335 | 25.89% | **0.0243** | +0.0408R | 9,934 | 23.68% | **0.9989** | −0.0490R |
| WIDE_BUT_WEAK_ADX \| **AGAINST_H1** | 11,856 | 25.66% | **0.0504** | +0.0296R | 11,460 | 24.11% | **0.9867** | −0.0321R |
| WIDE_BUT_M15_OPPOSED \| AGAINST_H1 | 8,491 | 23.30% | 0.9999 | −0.0597R | 8,362 | 21.74% | 1.0000 | −0.1253R |
| WIDE_BUT_WEAK_ADX \| TOWARD_H1 | 11,830 | 23.14% | 1.0000 | −0.0728R | 12,659 | 20.26% | 1.0000 | −0.1874R |

**This is the direct answer to the question the phase was asked.** Rotation back
toward H1 in the opposed bucket is worth +0.89 percentage points gross, and
continuation against H1 in the weak-ADX bucket +0.66pp gross. One spread
crossing costs ~0.11R. Both edges are smaller than the cost of taking them.

Note also that the two directions of each bucket sum to ≈49%, not 50% — the
missing point is exactly the cost and the ambiguity. Neither direction is
"the wrong side of" a real edge; there is no edge to be on a side of.

**Net of spread, zero of 24 cells fall below the 5% level (1.2 expected by
chance), and the best net p-value is 0.1619.**

## 3. Subperiod stability

Gross rates, so the leads are given the most favourable reading:

| cell | 2023 partial | 2024 H1 | 2024 H2 | 2025 H1 |
|---|---|---|---|---|
| ALL EVENTS \| TOWARD_H1 | 1,473n 17.65% | 7,253n 24.80% | 6,311n 25.50% | 6,128n 24.27% |
| ALL EVENTS \| AGAINST_H1 | 1,329n 29.50% | 6,777n 22.37% | 6,089n 27.36% | 6,152n 23.50% |
| EMA_CROSS_AGAINST_H1 \| AGAINST_H1 | 33n 39.39% | 129n 27.91% | 112n **19.64%** | 123n 32.52% |
| STRONG_CLOSE_AGAINST_H1 \| AGAINST_H1 | 88n 35.23% | 453n **22.30%** | 585n 29.57% | 577n **23.74%** |
| EMA20_REJECTION \| TOWARD_H1 | 473n **19.24%** | 2,406n 25.35% | 1,852n 25.59% | 1,795n 25.91% |
| STRUCTURE_BREAK_5_TOWARD_H1 \| TOWARD_H1 | 147n **19.05%** | 728n 26.24% | 769n 25.36% | 709n **22.57%** |

Every candidate lead has at least one subperiod below break-even, and the best of
them swings 39.4 → 27.9 → 19.6 → 32.5 on samples of 33 to 129. That is the
signature of small-sample noise, not of an edge appearing and disappearing.

## 4. Core-flat capacity

| event | bars | /month | Core busy | Core flat | **free/month** | % flat | A4 overlap | T3 overlap |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| EMA20_REJECTION | 8,744 | 445.0 | 906 | 7,838 | 398.9 | 89.6 | **0** | **0** |
| EMA50_REJECTION | 5,861 | 298.3 | 630 | 5,231 | 266.2 | 89.2 | **0** | **0** |
| STRUCTURE_BREAK_3_AGAINST_H1 | 3,349 | 170.4 | 297 | 3,052 | 155.3 | 91.1 | **0** | **0** |
| STRUCTURE_BREAK_3_TOWARD_H1 | 3,256 | 165.7 | 292 | 2,964 | 150.9 | 91.0 | **0** | **0** |
| STRUCTURE_BREAK_5_AGAINST_H1 | 2,602 | 132.4 | 227 | 2,375 | 120.9 | 91.3 | **0** | **0** |
| STRUCTURE_BREAK_5_TOWARD_H1 | 2,394 | 121.8 | 216 | 2,178 | 110.8 | 91.0 | **0** | **0** |
| STRONG_CLOSE_TOWARD_H1 | 1,766 | 89.9 | 165 | 1,601 | 81.5 | 90.7 | **0** | **0** |
| STRONG_CLOSE_AGAINST_H1 | 1,704 | 86.7 | 156 | 1,548 | 78.8 | 90.8 | **0** | **0** |
| EMA_CROSS_AGAINST_H1 | 465 | 23.7 | 42 | 423 | 21.5 | 91.0 | **0** | **0** |
| EMA_REALIGN_WITH_H1 | 170 | 8.7 | 11 | 159 | 8.1 | 93.5 | **0** | **0** |

Capacity was never the constraint and is not the constraint now: ~90% of every
event occurs with the Core flat and A4/T3 overlap is zero throughout. This
confirms Phase F's conclusion from the opposite direction — the room exists, the
edge does not.

## 5. Control: does this measurement detect an edge that is known to exist?

A gate that returns "no edge" everywhere is worthless unless it can return "edge"
somewhere. The identical machinery, run on pools whose answer is already known:

| control pool | n | +3R first | exact p |
|---|---:|---:|---:|
| **Every development bar, no filter, toward H1** | 42,385 | 24.43% | 0.9969 |
| **Every development bar, no filter, against H1** | 41,860 | 24.65% | 0.9522 |
| TREND buckets, all events, toward H1 | 6,635 | 25.09% | 0.4343 |
| NEUTRAL_RANGE, all events, toward H1 | 4,799 | 24.48% | 0.7998 |
| Frozen A4's own setup bars, long | 161 | 26.09% | 0.4045 |
| **Frozen T3's own setup bars, short** | 142 | **31.69%** | **0.0431** |

The unfiltered null lands on 24.4–24.7%, which is 25% less the cost drag — the
measurement is calibrated. And exactly one pool in the entire phase clears the
line: **the frozen T3's own setups, the one component in this repository that
passed validation and was frozen into production.** The instrument works; it
found the one edge that is known to be there and nothing else.

Two caveats stated rather than buried. A4's 161 samples at 26.09% are
underpowered — that is not evidence of absence, only absence of evidence. And T3
at n=142 with p=0.043 is itself a single modest result; it is offered as
calibration, not as a fresh claim about T3.

## 6. Prior-research equivalence

No family was built, so nothing could duplicate a rejected one. The audit is
recorded for completeness:

| candidate mechanism in this map | closest prior family | status |
|---|---|---|
| structure break 3/5 toward H1 | T3, D1, **F1** | REJECTED (Phases D, F) |
| structure break 3/5 against H1 | **F3** failed-break reversal | REJECTED (Phase F) |
| EMA20/EMA50 rejection | A4, **D2**, PB1 | A4 frozen; D2 REJECTED (Phase E); PB1 REJECTED |
| EMA cross realign / against | **F2** EMA trend-initiation | REJECTED (Phase F) |
| strong directional close | V3-M1, PB1 | REJECTED |
| break → retest → reclaim | PB2, PB3 | REJECTED; closed again in Phase F §4 |
| range sweep reversal | V3-R2, D3 | REJECTED |

Every mechanism the outcome map covers already has a rejected implementation
behind it. Phase G now supplies the reason those rejections kept happening: the
underlying bars do not clear 25%.

## 7. Strategy families

**None built.** Brief section F permits a family only if the pool shows positive
3R expectancy, a ≥25% 3R-before-1R rate after ambiguity handling, useful
capacity, repeated evidence across subperiods and low Core overlap. Capacity and
overlap pass everywhere. Expectancy, rate and subperiod repetition fail
everywhere. Building on a pool that fails the first three would be exactly the
"rescue" the brief forbids.

---

## Phase G decision

**FIXED-3R HIGH-FREQUENCY DEVELOPMENT SEARCH EXHAUSTED.**

**Exact evidence:**

1. **No pool beats the arithmetic.** 24 cells, 42,415 measured trades, entered at
   next-bar open with the frozen structural stop. Net of the broker's own spread,
   **zero cells fall below the 5% significance level** against the 25% break-even,
   where 1.2 would be expected by chance. Best net p-value 0.1619; best gross
   p-value 0.0972, Bonferroni-adjusted to 1.000.
2. **Both directions fail, so the question is settled either way.** Rotation
   toward H1 in the opposed bucket: 25.89% gross (p = 0.024), 23.68% net
   (p = 0.999). Continuation against H1 in the weak-ADX bucket: 25.66% gross
   (p = 0.050), 24.11% net (p = 0.987). The gross edges are +0.89pp and +0.66pp;
   one spread crossing costs about 0.11R.
3. **The apparent leads are unstable.** Every candidate has a subperiod below
   break-even; the strongest swings 39.4% → 27.9% → 19.6% → 32.5% on 33–129
   samples per period.
4. **The measurement is calibrated.** An unfiltered null over 42,385 bars returns
   24.43%, and the only pool in the phase that clears the line is the frozen T3's
   own setups at 31.69% (p = 0.043). The instrument detects the one edge known to
   exist and finds nothing in the transition pools.
5. **It is not a capacity problem.** ~90% of every event pool occurs with the
   Core flat, with zero A4/T3 setup overlap, exactly as in Phase F. The room is
   there; the edge is not.

Phases A–C closed parameter work. Phases D–E closed mirrored and range families
on contention. Phase F closed transition families on edge. Phase G closes the
question underneath all of them: **at a fixed 3R on M15 with structural stops,
these bars are indistinguishable from a driftless path, and the broker's spread
is larger than any drift that might be there.**

**No Phase H families were invented and no further indicators or thresholds were
mined.** The next decision — lower the frequency objective, reconsider the fixed
3R, or change timeframe/architecture — belongs to you, and this phase does not
make it.

---

**Holdout touched: NO.** Frozen hashes unchanged: A4 `55fedf85…`, T3 `4c4ab845…`,
Core `631374d5…`. Stage 3/4/5, MT5 sources and all Phase A–F research untouched.
No strategy module was added, no registry entry created, and no new third-party
dependency introduced — the exact binomial tail is implemented in the standard
library and cross-checked against `scipy.stats.binomtest`.
