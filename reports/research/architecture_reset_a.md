# BTC Architecture Reset A — Reward/Exit Feasibility Study

**Split:** DEVELOPMENT 2023-11-10 23:15 → 2025-06-30 23:45 UTC, 19.65 months.
**Holdout touched: NO.** **Dataset:** `data/exness/btc/phase_r1/processed/btcusdm_M15.csv`,
fingerprint `80735a2cf521363747f48368814267ad6ca146eb294bb7bd7252666d06c76af3`.
M15 unchanged, entries unchanged, no filters added, no family built.

## Decision

**MOVE RESEARCH TO LOWER FIXED RR — to the 1.75R–2.00R region, with 1.75R as the
stress-robust point.**

Fixed-RR architecture is **not** unsuitable, and 3R is **not** the best point on
the curve. But the gain is a quality improvement to the existing ~9.7
trades/month system, **not** a route to 24–30/month: the only configuration that
reaches that frequency is negative at every target on the grid and collapses
under execution stress.

---

## Two things that must be read correctly

**The break-even rate moves with the target.** A target of R against a 1R stop
needs w = 1/(1+R). Comparing raw win rates across targets means nothing; only
the distance from each target's *own* break-even does.

| target | 1.00R | 1.25R | 1.50R | 1.75R | 2.00R | 2.50R | 3.00R |
|---|---|---|---|---|---|---|---|
| **break-even win rate** | 50.00% | 44.44% | 40.00% | 36.36% | 33.33% | 28.57% | 25.00% |

**Lowering the target is not a pure exit change.** In a single-position system
trades finish sooner, the slot frees sooner, and setups previously blocked become
reachable. Frozen A4 produces **93** filled trades at 3.00R and **101** at 1.50R
from an identical *signal* stream — no frozen source reads `risk_reward_ratio`,
so entries are target-independent, but *fills* are not. Section A therefore
measures events independently (the pure payoff curve) and sections B–C measure
the real system (including slot recycling). They answer different questions.

Ambiguous same-bar outcomes are scored as losses throughout, matching the
engine's own `SameBarResolution.SL_FIRST`, so the raw and backtested curves are
on one convention.

---

## 1. Payoff feasibility curve — raw event pools

Phase G's event population and structural stops, net of the dataset's own per-bar
spread. **Negative at every target, in every pool.**

| pool | n | 1.00R | 1.25R | 1.50R | 1.75R | 2.00R | 2.50R | 3.00R |
|---|---:|---|---|---|---|---|---|---|
| ALL EVENTS \| TOWARD_H1 | 11,472 | −0.149 | −0.146 | −0.139 | −0.137 | −0.137 | −0.133 | −0.132 |
| ALL EVENTS \| AGAINST_H1 | 10,092 | −0.086 | −0.086 | −0.079 | −0.088 | −0.085 | −0.080 | −0.079 |
| OPPOSED \| TOWARD_H1 | 5,198 | −0.120 | −0.117 | −0.101 | −0.091 | −0.094 | −0.080 | −0.060 |
| OPPOSED \| AGAINST_H1 | 4,526 | −0.116 | −0.115 | −0.123 | −0.135 | −0.126 | −0.128 | −0.122 |
| WEAK_ADX \| TOWARD_H1 | 6,274 | −0.174 | −0.170 | −0.170 | −0.175 | −0.173 | −0.176 | −0.191 |
| WEAK_ADX \| AGAINST_H1 | 5,566 | −0.061 | −0.061 | −0.043 | −0.050 | −0.052 | −0.041 | −0.044 |

*(net expectancy in R per trade; every cell's binomial p ≥ 0.97 against its own
break-even)*

Edge over break-even runs from **−1.12pp to −8.69pp** — negative in all 42 cells.
The most favourable cell in the entire grid is WEAK_ADX against H1 at 2.50R, at
−1.19pp and −0.041R.

**The structural reason, and the finding that settles section A:** the spread
cost drag is **flat across targets**, +0.061R to +0.136R per trade everywhere. It
is a fixed fraction of the stop distance, so it does not shrink when the target
shrinks. Gross expectancy is ≈0 at every target (−0.071 to +0.042) — the Phase G
random-walk result, which the curve shows holds at *every* reward multiple, not
just at 3R. Lowering the target moves along a flat null and pays the same toll.

## 2. A4 exit curve

| RR | BE% | trades | /mo | WR% | **edge** | PF | Avg R | total R | DD% | streak |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|
| 1.00 | 50.00 | 107 | 5.87 | 45.79 | −4.21 | 0.8460 | −0.0834 | −8.93 | 3.19 | 5 |
| 1.25 | 44.44 | 104 | 5.70 | 42.31 | −2.13 | 0.9181 | −0.0469 | −4.87 | 2.69 | 5 |
| 1.50 | 40.00 | 101 | 5.54 | 38.61 | −1.39 | 0.9450 | −0.0325 | −3.29 | 1.97 | 5 |
| 1.75 | 36.36 | 99 | 5.43 | 37.37 | +1.01 | 1.0463 | +0.0309 | +3.06 | 1.71 | 5 |
| 2.00 | 33.33 | 98 | 5.37 | 33.67 | +0.34 | 1.0183 | +0.0141 | +1.38 | 2.24 | 5 |
| 2.50 | 28.57 | 95 | 5.21 | 27.37 | −1.20 | 0.9452 | −0.0377 | −3.58 | 1.95 | 6 |
| 3.00 | 25.00 | 93 | 5.10 | 25.81 | +0.81 | 1.0425 | +0.0354 | +3.29 | 1.71 | 6 |

**Stable region: NONE.** The sign alternates − − − + + − +, and every positive
target is carried by a single month: the best month is **163%** of the total at
1.75R, **363%** at 2.00R and **182%** at 3.00R. A4 standalone has no payoff zone
at any reward multiple, including its own frozen baseline. Subperiods: 2024 H1
is negative at all seven targets (−3.88 to −7.96R).

## 3. T3 exit curve

| RR | BE% | trades | /mo | WR% | **edge** | PF | Avg R | total R | DD% | streak |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|
| 1.00 | 50.00 | 95 | 5.21 | 53.68 | +3.68 | 1.1616 | +0.0754 | +7.16 | 1.95 | 4 |
| 1.25 | 44.44 | 93 | 5.10 | 49.46 | +5.02 | 1.2254 | +0.1143 | +10.63 | 1.58 | 4 |
| 1.50 | 40.00 | 92 | 5.04 | 41.30 | +1.30 | 1.0561 | +0.0337 | +3.10 | 1.46 | 6 |
| **1.75** | 36.36 | 89 | 4.88 | 40.45 | **+4.09** | 1.1902 | +0.1132 | +10.07 | 1.46 | 6 |
| **2.00** | 33.33 | 88 | 4.82 | 38.64 | **+5.31** | **1.2596** | **+0.1596** | **+14.05** | 1.46 | 6 |
| **2.50** | 28.57 | 87 | 4.77 | 31.03 | +2.46 | 1.1235 | +0.0861 | +7.49 | 2.08 | 8 |
| **3.00** | 25.00 | 84 | 4.61 | 27.38 | +2.38 | 1.1265 | +0.0944 | +7.93 | 1.98 | 8 |

**Stable region: 1.75R–3.00R** (and positive at 1.00R and 1.25R too — T3 clears
its own break-even at **all seven** targets). 1.50R is excluded only because one
month exceeds its total. This is the broadest payoff region in the study, and
2.00R nearly doubles 3.00R's total R at a lower drawdown.

## 4. Frozen Core exit curve

| RR | BE% | trades | /mo | WR% | **edge** | PF | Avg R | total R | DD% | streak |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|
| 1.00 | 50.00 | 202 | 11.07 | 49.51 | −0.49 | 0.9806 | −0.0088 | −1.77 | 2.92 | 6 |
| 1.25 | 44.44 | 197 | 10.80 | 45.69 | +1.25 | 1.0523 | +0.0292 | +5.76 | 3.16 | 7 |
| 1.50 | 40.00 | 193 | 10.58 | 39.90 | −0.10 | 0.9961 | −0.0009 | −0.18 | 3.04 | 10 |
| **1.75** | 36.36 | 188 | 10.31 | 38.83 | **+2.47** | 1.1116 | +0.0699 | +13.14 | **2.85** | 10 |
| **2.00** | 33.33 | 186 | 10.20 | 36.02 | **+2.69** | **1.1266** | **+0.0829** | **+15.42** | **2.71** | 10 |
| 2.50 | 28.57 | 182 | 9.98 | 29.12 | +0.55 | 1.0271 | +0.0215 | +3.91 | 3.21 | 10 |
| 3.00 | 25.00 | 177 | 9.70 | 26.55 | +1.55 | 1.0812 | +0.0634 | +11.23 | 2.95 | 10 |

**Stable region: 1.75R–2.00R.** Both beat the 3R incumbent on profit factor,
total R **and** drawdown simultaneously. 1.25R and 3.00R also qualify but are not
adjacent to the run.

## 5. High-frequency pool exit curves

The Phase F opportunity streams, entries untouched, target varied.

**F3a — the ~16-free-trades/month pool:**

| RR | BE% | trades | /mo | WR% | **edge** | PF | Avg R | total R | DD% |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|
| 1.00 | 50.00 | 414 | 22.69 | 42.99 | −7.01 | 0.7591 | −0.1362 | −56.40 | 11.15 |
| 1.25 | 44.44 | 406 | 22.26 | 40.39 | −4.05 | 0.8512 | −0.0879 | −35.70 | 8.84 |
| 1.50 | 40.00 | 408 | 22.36 | 37.26 | −2.74 | 0.8932 | −0.0662 | −27.02 | 7.67 |
| 1.75 | 36.36 | 402 | 22.04 | 33.33 | −3.03 | 0.8773 | −0.0804 | −32.34 | 8.14 |
| 2.00 | 33.33 | 387 | 21.21 | 30.75 | −2.58 | 0.8905 | −0.0749 | −28.97 | 8.98 |
| 2.50 | 28.57 | 373 | 20.45 | 26.00 | −2.57 | 0.8879 | −0.0812 | −30.28 | 9.39 |
| 3.00 | 25.00 | 359 | 19.68 | 22.84 | −2.16 | 0.8919 | −0.0803 | −28.82 | 8.92 |

**Core + F3a — the only configuration that reaches the frequency objective:**

| RR | trades/mo | WR% | edge | PF | total R | DD% |
|---|---:|---:|---|---:|---:|---:|
| 1.00 | **32.40** | 45.18 | −4.82 | 0.8312 | −54.69 | 12.00 |
| 1.25 | **31.57** | 42.01 | −2.43 | 0.9125 | −29.44 | 10.72 |
| 1.50 | **31.41** | 38.22 | −1.78 | 0.9324 | −23.40 | 8.32 |
| 1.75 | **30.59** | 35.12 | −1.23 | 0.9528 | −16.40 | 8.13 |
| 2.00 | **29.77** | 32.97 | −0.36 | 0.9887 | −3.24 | 7.60 |
| 2.50 | **28.39** | 27.41 | −1.16 | 0.9550 | −15.95 | 9.58 |
| 3.00 | **26.75** | 24.59 | −0.41 | 0.9849 | −4.02 | 8.45 |

**Stable region: NONE, at either.** This is the study's most consequential
result. 26.75–32.40 trades/month is exactly the frequency objective, and the
configuration is **below break-even at all seven reward multiples**, best case
PF 0.9887, at 2.6–4.4× the frozen Core's drawdown. Lowering the target does not
rescue the high-frequency pool — consistent with section A, where the same bars
are negative at every target.

*(F1a: negative at all seven, edge −5.13 to −9.26pp. F2a: positive at
1.00R–1.50R with edges of +12 to +17pp — but on **21 trades, 1.15/month**. It is
reported for completeness and carries no weight at that sample size or capacity.)*

## 6. Subperiod stability

Total R by subperiod, frozen Core:

| RR | 2023 partial | 2024 H1 | 2024 H2 | 2025 H1 |
|---|---|---|---|---|
| 1.00 | +0.01 | −5.97 | +0.15 | +4.05 |
| 1.25 | +2.02 | −7.67 | −0.40 | +11.81 |
| 1.50 | +0.52 | −8.39 | +2.11 | +5.58 |
| **1.75** | +1.27 | −5.60 | +5.62 | +11.85 |
| **2.00** | +2.02 | −6.81 | +10.10 | +10.11 |
| 2.50 | −0.01 | −10.30 | +2.56 | +11.65 |
| 3.00 | +0.99 | −2.73 | +7.04 | +5.93 |

The 1.75R–2.00R region is positive in three of four subperiods and its
positivity is not one month (best month 53.3% and 52.1% of total). **2024 H1 is
negative at every target** — a persistent structural feature of this system, not
a property of the reward multiple. T3 shows the same shape: positive in 2024 H2
and 2025 H1 at every target, with 2023 partial (2 trades) negative.

## 7. Execution stress

PF / total R. This is where the native ranking changes.

**Frozen Core**

| RR | native | spread ×1.10 | spread ×1.20 | slippage 0.02% | **×1.20 + 0.02%** |
|---|---|---|---|---|---|
| **1.75** | 1.112 / +13.14 | 1.090 / +10.85 | 1.072 / +8.90 | 1.043 / +5.30 | **1.008 / +1.21** |
| 2.00 | 1.127 / +15.42 | 1.105 / +13.12 | 1.087 / +11.14 | 1.035 / +4.46 | **0.977 / −2.59** |
| 3.00 | 1.081 / +11.23 | 1.062 / +8.94 | 1.047 / +6.97 | 1.024 / +3.71 | **0.993 / −0.39** |

**Frozen T3** — unaffected by the spread multiplier (short-only with pending stop
entries, as Phase C established), so only slippage bites:

| RR | native | ×1.10 | ×1.20 | slippage 0.02% | ×1.20 + 0.02% |
|---|---|---|---|---|---|
| 2.00 | 1.260 / +14.05 | 1.260 / +14.05 | 1.260 / +14.05 | 1.149 / +8.34 | **1.095 / +5.41** |
| 3.00 | 1.127 / +7.93 | 1.127 / +7.93 | 1.127 / +7.93 | 1.040 / +2.68 | **1.040 / +2.68** |

**Core + F3a** — the high-frequency configuration, for contrast:

| RR | native | ×1.20 | slippage 0.02% | ×1.20 + 0.02% |
|---|---|---|---|---|
| 2.00 | 0.989 / −3.24 | 0.949 / −18.56 | 0.898 / −37.28 | **0.861 / −52.11** |
| 3.00 | 0.985 / −4.02 | 0.965 / −11.61 | 0.924 / −26.84 | **0.893 / −39.38** |

Three readings, stated plainly:

1. **Under the harshest arm every Core target is at or below break-even** — 1.008,
   0.977, 0.993. The separation between them there (+1.21, −2.59, −0.39 R) is
   inside the noise of which individual trades happen to fill. No Core target
   survives that arm *profitably*.
2. **1.75R beats 3.00R in all five arms** (+13.14/+10.85/+8.90/+5.30/+1.21 against
   +11.23/+8.94/+6.97/+3.71/−0.39). 2.00R beats 3.00R in three of five and loses
   the two hardest. Lower targets degrade faster in absolute R — the cost per
   trade is the same while the per-trade reward is smaller — so 1.75R, not the
   native-best 2.00R, is the defensible point.
3. **T3 alone is the genuinely robust element**, positive under every arm at both
   targets, and the reason the Core's region exists at all.

---

## BROAD STABLE PAYOFF REGION

**1.75R–2.00R** for the frozen Core, and **1.75R–3.00R** for frozen T3.
**NONE** for A4 standalone, for F1a, for F3a, for Core+F3a, and — the section A
result — **none for the raw transition event pools at any target**.

The Core region carries one qualification that belongs in the headline: it is a
region under native and moderately stressed costs, and it flattens to break-even
under spread ×1.20 combined with 0.02% slippage.

## DECISION: **MOVE RESEARCH TO LOWER FIXED RR**

Not `KEEP 3R`: 1.75R beats 3.00R on the frozen Core in **all five** execution
arms, on profit factor, on total R and on drawdown, and the region around it is
adjacent, multi-subperiod and not month-dependent. T3 clears its break-even at
all seven targets with 2.00R nearly doubling 3.00R's total R.

Not `FIXED-RR ARCHITECTURE ITSELF IS UNSUITABLE`: where a real entry edge exists,
the payoff curve is positive across a broad adjacent range of targets. T3 clears
break-even at 7 of 7, the Core at 4 of 7. A fixed reward multiple is a workable
architecture on this instrument and timeframe.

**The qualification that matters more than the decision.** Lowering the reward
multiple improves the *quality* of the existing ~10 trades/month system by
roughly +2R over 19.65 months. It does **nothing** for frequency. The only
configuration in this study that reaches 24–30 trades/month is below break-even
at every one of the seven targets and loses 52R under combined stress. Section A
explains why in one line: **the gross payoff curve of the high-capacity pools is
flat at zero across all reward multiples, and the spread's cost drag is flat too
at ~0.10R.** There is no target at which those bars become profitable, because
there is nothing to harvest at any target.

Phase G concluded the fixed-3R high-frequency search was exhausted. This study
extends that: it is the *high-frequency* half that is exhausted, not the fixed-RR
half. The frequency objective and the edge objective have not been shown to be
jointly reachable on BTCUSDm M15 with the pools examined so far.

**No strategy was built and none is proposed here.**

---

**Holdout touched: NO.** Frozen hashes unchanged: A4 `55fedf85…`, T3 `4c4ab845…`,
Core `631374d5…`. Frozen sources, Stage 3/4/5, MT5 and all Phase A–G research
untouched; no strategy module or registry entry added. Entries were never
altered — no frozen source reads `risk_reward_ratio`, which a test asserts.
