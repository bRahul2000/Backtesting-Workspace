# BTC Architecture Reset B — M5 Execution Feasibility Study

**Split:** DEVELOPMENT 2023-11-10 23:15 → 2025-06-30 23:45 UTC. **Holdout touched: NO.**
**Frozen A4/T3/Core unchanged.** No strategy built.

## Decision

**M5 EXECUTION ARCHITECTURE REJECTED — on cost geometry.**

Two independent findings, and the second does not depend on the first:

1. **No validated broker-native Exness BTCUSDm M5 history exists**, and obtaining
   it is not something I can do from here. Sections B, C, D, E and G of the brief
   were therefore not run, and this report does not pretend otherwise.
2. **M5 costs 1.73× more per unit of risk than M15**, derived from validated data
   without needing a single M5 bar. Applying exactly that cost to the only proven
   edge in this repository — the frozen Core — **erases it**: +13.14R at 1.75R
   becomes −0.16R, and +11.23R at 3.00R becomes +0.37R.

The rejection is on **cost**, not on signal. M5 signal quality was never measured
because it cannot be. What is established is that whatever edge M5 might contain
would have to be ~1.8× larger in R terms than the equivalent M15 edge merely to
break even — and Phase G measured the equivalent M15 edge at zero.

---

## 1. M5 data audit

| check | result |
|---|---|
| M5 dataset registered in `services/market_datasets.py` | **No** — registry holds only `15m` and `1h` |
| M5 files anywhere under `data/` | **None** (filesystem sweep for `_m5`, `m5_`, `_5m`, `5min`) |
| Exporter `mt5/Export_BTCUSD_History.mq5` present | Yes |
| Timeframes that exporter emits | **`PERIOD_M15`, `PERIOD_H1` only** — no `PERIOD_M5` |

The only tick files present (`data/exness/processed/btcusdm_*ticks*.csv`) are
single-day 2026-08 sampling artefacts — 89,341 rows covering 2026-08-01 to
2026-08-02, which is **inside HOLDOUT** and was not read for research.

**Why I cannot obtain it.** Every validated file in this repository came from
MT5 `CopyRates` run inside a Windows MetaTrader 5 terminal logged into
`Exness-MT5Trial5`, writing to `C:\users\user\AppData\Roaming\MetaQuotes\...`
(per `btcusd_BTCUSDm_M15.csv.metadata.json`). That history is reachable only from
the terminal. This session runs on macOS with no terminal and no broker
connection. Per the brief I did **not** substitute Bitstamp or resample M15
downward — the latter would be circular, since M5 bars synthesised from M15 could
not contain intra-bar structure, which is the entire point of an M5 trigger.

**To unblock:** add `ExportTimeframe(symbol, PERIOD_M5, "M5", prefix + "_M5.csv")`
alongside the two existing calls at `mt5/Export_BTCUSD_History.mq5:163-164`, run
it in the Exness terminal, and place the result under
`data/exness/btc/phase_r1/raw/`.

**Acceptance criteria it must meet** — taken from the files already accepted, so
the bar is the one in force:

| | M15 (accepted) | H1 (accepted) |
|---|---|---|
| bars in DEVELOPMENT | 57,403 | 14,352 |
| timezone | UTC | UTC |
| monotonic / duplicates | True / 0 | True / 0 |
| bars on step grid | 57,397 | 14,351 |
| gaps / largest gap | 5 / 4 bars | 0 / 1 bar |
| invalid OHLC rows | 0 | 0 |
| tick volume ≤ 0 | 0 | 0 |
| spread median / p95 / max | 28.80 / 53.90 / 88.09 | 28.80 / 51.79 / 77.63 |
| spread ≤ 0 | 0 | 0 |
| fingerprint | `80735a2cf521…` | `6d35fe9d7feb…` |

## 2. M5 vs M15 cost geometry

M5 helps only if a tighter entry does not make transaction cost proportionally
worse. That decomposes into three quantities, and **two of them are measured to
be scale-invariant on this instrument**, which is what makes the third decisive.

**(a) The broker's bar spread does not change with bar size.** Measured on two
independent broker files:

| | median | mean | p95 | p99 | max |
|---|---|---|---|---|---|
| M15 | **28.80** | 30.00 | 53.90 | 68.86 | 88.09 |
| H1 | **28.80** | 29.07 | 51.79 | 62.96 | 77.63 |

H1/M15 median ratio = **1.0000**. The descriptor is a typical spread, not a
per-bar maximum, so a shorter bar quotes the same number. **A shorter timeframe
does not buy a cheaper spread.**

**(b) The structural stop is a near-constant multiple of ATR.** The repository's
own stop — T3's 2-bar extreme ± 0.20 ATR, used by every strategy in it:

| frame | ×duration | bars | median ATR | **median stop (ATR)** | inside 0.50–3.00 band | spread/ATR | **cost per R** |
|---|---:|---:|---:|---:|---:|---:|---:|
| M15 | 1 | 57,403 | 229.57 | **0.971** | 75.7% | 0.1255 | **0.1292** |
| M30 | 2 | 28,704 | 332.39 | **0.963** | 75.8% | 0.0866 | 0.0900 |
| H1 | 4 | 14,353 | 486.33 | **0.958** | 75.5% | 0.0592 | 0.0618 |
| H2 | 8 | 7,177 | 706.19 | **0.952** | 76.4% | 0.0408 | 0.0428 |
| H4 | 16 | 3,589 | 1016.18 | **0.956** | 76.1% | 0.0283 | 0.0296 |

The stop varies by **under 2% across a sixteen-fold range of bar durations**, and
the share falling inside the frozen validity band is constant at 75.5–76.4%.

**(c) ATR scales as duration^h, and h is fitted, not assumed.** Across six
durations spanning 24×:

| frame | actual ATR | fitted | error |
|---|---:|---:|---:|
| M15 | 229.57 | 230.22 | +0.29% |
| M30 | 332.39 | 333.67 | +0.38% |
| H1 | 486.33 | 483.59 | −0.56% |
| H2 | 706.19 | 700.87 | −0.75% |
| H4 | 1016.18 | 1015.77 | −0.04% |
| H6 | 1253.32 | 1262.03 | +0.70% |

**h = 0.5354**, worst error 0.75%. Every aggregate is an *upward* aggregation of
the validated M15 file, and the aggregation itself is validated: the M15→H1
aggregate reproduces the independent broker H1 file's median ATR to
**100.00%**.

**The projection.** Only ATR moves, so only the cost ratio moves:

| | ATR_M5/ATR_M15 | median M5 ATR | spread/ATR | **cost per R** | **vs M15** |
|---|---:|---:|---:|---:|---:|
| **h = 0.500 (random walk, most favourable to M5)** | 0.5774 | 132.54 | 0.2173 | **0.2238** | **1.73×** |
| h = 0.535 (fitted) | 0.5553 | 127.49 | 0.2259 | 0.2327 | 1.80× |

The favourable bound is used throughout. A driftless path is the *best* case for
M5; any real trending component makes h larger, M5's ATR smaller and the cost
ratio worse.

**Note the gradient.** Cost per R runs 0.129 → 0.090 → 0.062 → 0.043 → 0.030 as
bar duration rises. It roughly halves every 4× in duration. M5 moves along that
curve in the wrong direction. *(Stated as a measured fact. Per the brief, no
alternative timeframe is proposed.)*

**Required win rates, once the cost is charged** — `w = (1+c)/(1+R)`:

| target | frictionless | M15 (c=0.129) | **M5 (c=0.224)** | M5 uplift over frictionless |
|---|---|---|---|---|
| 1.00R | 50.00% | 56.46% | **61.19%** | +11.19pp |
| 1.25R | 44.44% | 50.19% | **54.39%** | +9.95pp |
| 1.50R | 40.00% | 45.17% | **48.95%** | +8.95pp |
| 1.75R | 36.36% | 41.06% | **44.50%** | +8.14pp |
| 2.00R | 33.33% | 37.64% | **40.79%** | +7.46pp |

## 3. The decisive test — M5-equivalent cost on a known edge

The spread is invariant and the stop is a fixed ATR multiple, so "smaller ATR
with the same spread" and "same ATR with a 1.73× spread" are **the same thing in
R terms**. That makes M5's cost geometry reproducible on M15 data right now.
This does *not* reproduce M5's signal population — nothing here can — but it
answers a sharper question: does our one proven edge survive M5 costs?

**Frozen Core** (PF / total R):

| RR | M15 native | M15 stress ×1.20 | **M5-equiv ×1.73** | M5-equiv ×1.80 | ×1.73 + slip 0.01% |
|---|---|---|---|---|---|
| 1.75 | 1.112 / +13.14 | 1.072 / +8.90 | **0.996 / −0.16** | 0.996 / −0.21 | 0.914 / −10.73 |
| 2.00 | 1.127 / +15.42 | 1.087 / +11.14 | **1.007 / +1.25** | 1.006 / +1.19 | 0.938 / −7.76 |
| 3.00 | 1.081 / +11.23 | 1.047 / +6.97 | **0.998 / +0.37** | 0.969 / −3.67 | 0.949 / −6.43 |

**Frozen T3** (the most cost-robust element in the repository):

| RR | M15 native | ×1.20 | **M5-equiv ×1.73** | ×1.80 | ×1.73 + slip 0.01% |
|---|---|---|---|---|---|
| 2.00 | 1.260 / +14.05 | 1.260 / +14.05 | **1.093 / +5.38** | 1.093 / +5.38 | 0.964 / −1.97 |
| 3.00 | 1.127 / +7.93 | 1.127 / +7.93 | **1.018 / +1.38** | 0.954 / −2.62 | 0.935 / −3.80 |

**At M5 cost the frozen Core's entire 19.65-month development edge disappears** —
+11.23R to +15.42R collapses to −0.16R to +1.25R, PF 0.996 to 1.007 — before any
slippage, and before M5 signal quality is even considered. Add 0.01% slippage and
every Core target is clearly negative. Only T3 alone retains anything (+5.38R at
2.00R), and it loses that too under slippage.

## 4. Sections not run

**M5 event map, raw payoff curves, subperiod stability, frequency capacity, cost
stress on M5 pools, prototypes 1 and 2: not run — no M5 data exists.** I will not
report numbers I did not measure. Each becomes runnable the moment a validated
M5 export lands; the machinery from Phase G and Reset A (event detection,
multi-target forward resolution, binomial gate, cost stress) is timeframe-agnostic
and would need only the new dataset registered.

One thing worth recording for that future run: **frequency was never the doubt.**
M5 gives 3× the bars, and trades resolve in roughly a third of the wall-clock
time, so the one-position constraint would plausibly carry the frozen Core's 9.7
trades/month to somewhere near 29 — inside the 24–30 objective. The M5 case was
always going to stand or fall on cost, and it falls.

---

## ARCHITECTURE RESET B DECISION: **M5 EXECUTION ARCHITECTURE REJECTED**

**Evidence:**

1. **Cost per unit risk is 1.73× M15's**, at the bound most favourable to M5
   (1.80× at the fitted exponent). Built from two measured scale-invariances —
   spread identical on two independent broker files (ratio 1.0000), structural
   stop constant to within 2% across 16× duration — and one scaling law fitted to
   within 0.75% across six durations and validated against an independent file to
   100.00%.
2. **That cost erases the only proven edge here.** The frozen Core goes from
   +13.14R to −0.16R at 1.75R and from +11.23R to +0.37R at 3.00R. The M5 cost
   increase is far beyond the ×1.20 spread stress that Architecture Reset A
   already showed pushes every Core target to break-even.
3. **The required win rate rises 7.5–11.2 percentage points** above frictionless
   break-even, against 4.3–6.5pp on M15 — and Phase G measured the M15 edge on
   high-capacity pools at zero.
4. **No M5 data exists to test signal quality**, so the architecture cannot be
   validated even in principle from this repository as it stands.

**What would overturn this.** Only an M5 signal population whose gross edge
exceeds ~0.224R per trade — roughly 1.8× the best gross edge ever measured on
M15, which was +0.042R and not statistically distinguishable from zero. That is
a high bar, but it is a *measurable* one, and it is the thing to test first if a
validated M5 export is ever produced.

**Per the brief, no alternative timeframe is proposed and no strategy was built.**

---

**Holdout touched: NO.** Frozen hashes unchanged: A4 `55fedf85…`, T3 `4c4ab845…`,
Core `631374d5…`. Frozen sources, Stage 3/4/5, MT5 sources and all Phase A–G and
Reset A research untouched; no strategy module or registry entry added. Bitstamp
was never loaded, and M15 was never resampled downward.
