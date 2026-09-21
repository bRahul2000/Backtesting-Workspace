# BTC Core V2 — Phase B: structural opportunity ablation

Controlled ablation on DEVELOPMENT only. Phase A's conclusion is carried in unchanged:
A4 and T3 body thresholds stay at 0.70 and the reward multiple stays at 3R. Frozen files
are byte-for-byte unchanged; arms are wrappers that subclass the frozen strategy.

| | |
|---|---|
| DEVELOPMENT | 2023-11-10 23:15 UTC → 2025-06-30 23:45 UTC |
| HOLDOUT | 2025-07-01 00:00 UTC → 2026-09-20 07:15 UTC |
| **Holdout touched** | **NO** |
| Dataset | `data/exness/btc/phase_r1/processed/btcusdm_M15.csv`, fingerprint `80735a2c…` verified per arm |

At each baseline value every wrapper produces a trade log identical to the frozen
strategy on real data — asserted for A4, T3 and both Core compositions.

## A correction that reshapes Experiment A

**A4 has no one-bar confirmation window to widen.** An armed pullback is not given one
bar to confirm: it stays armed indefinitely and is cleared only by the frozen
invalidation rules — trend/EMA50 context loss, excess depth, session end, the daily cap,
or a confirmation firing. Measured on the development split, over the 103 A4 signals:

| confirmation arrives on pullback bar | 2 | 3 | 4 | 5 | 6 | 7–10 | 11–21 |
|---|---|---|---|---|---|---|---|
| signals | 27 | 11 | 14 | 12 | 8 | 18 | 13 |
| cumulative | 26.2 % | 36.9 % | 50.5 % | 62.1 % | 69.9 % | 87.4 % | 100 % |

The median confirmation arrives on the **fourth** bar of the pullback and the tail runs
to twenty-one. Only 26 % arrive on the first testable bar — which is what a "1-bar
window" would mean.

A bounded window is therefore **tighter** than the frozen behaviour, so these arms remove
opportunity rather than adding it. Widening is not available: the wait is already
unbounded, and the only way to admit more A4 trades through timing would be to relax an
invalidation rule, which this experiment explicitly holds fixed. The sweep is run as
requested at 2 and 3 bars, plus 1 bar (the behaviour the brief assumed was current) and
unbounded (the behaviour that actually is current, and the baseline).

Because these arms subtract, both directions of the delta are reported: trades the arm
**admits** (the position slot frees earlier, so a later setup can be reached) and trades
it **withdraws**. The acceptance rule is applied in both directions — admitted trades
must have positive expectancy, and withdrawn trades must have negative expectancy, or
the change is destroying value.

The window is applied by withdrawing the confirmation *opportunity* once the pullback is
older than N bars, never by touching pullback state. Pullback low, depth, structure level
and every invalidation rule behave exactly as frozen, so the arm isolates timing alone.


### A4 confirmation-window table (standalone)

| window | trades | trades/mo | WR % | PF | Avg R | total R | PnL | Max DD % | longest losing streak | orders | fills | expired | cancelled |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **UNBOUNDED** *(baseline)* | 93 | 5.10 | 25.81 | 1.0425 | +0.0354 | +3.29 | +74.02 | 1.71 | 6 | 103 | 93 | 10 | 0 |
| **3** | 50 | 2.74 | 22.00 | 0.8353 | -0.1270 | -6.35 | -162.41 | 1.76 | 6 | 55 | 50 | 5 | 0 |
| **2** | 37 | 2.03 | 24.32 | 0.9553 | -0.0319 | -1.18 | -31.61 | 1.27 | 4 | 40 | 37 | 3 | 0 |
| **1** | 27 | 1.48 | 18.52 | 0.6763 | -0.2668 | -7.20 | -179.22 | 2.02 | 8 | 28 | 27 | 1 | 0 |

### A4 incremental-trade table

| window | admitted | WR % | PF | Avg R | total R | mean MFE (R) | mean MAE (R) | ≥1R | ≥2R | months (+/−) | withdrawn | withdrawn Avg R | withdrawn total R | net ΔR | ΔDD % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **UNBOUNDED** *(baseline)* | 0 | — | — | — | 0.00 | — | — | — | — | — | 0 | — | 0.00 | 0.00 | 0.00 |
| **3** | 5 | 20.00 | 0.7383 | -0.2104 | -1.05 | 1.083 | 1.151 | 2 | 1 | 4 (1/3) | 48 | 0.1790 | +8.59 | -9.64 | +0.05 |
| **2** | 3 | 0.00 | 0.0000 | -1.0173 | -3.05 | 0.654 | 1.538 | 1 | 0 | 3 (0/3) | 59 | 0.0241 | +1.42 | -4.47 | -0.44 |
| **1** | 4 | 0.00 | 0.0000 | -1.0159 | -4.06 | 1.159 | 1.478 | 2 | 1 | 4 (0/4) | 70 | 0.0919 | +6.43 | -10.50 | +0.31 |

### T3 lookback table (standalone)

| lookback | trades | trades/mo | WR % | PF | Avg R | total R | PnL | Max DD % | longest losing streak | orders | fills | expired | cancelled |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **6** | 70 | 3.84 | 28.57 | 1.1923 | +0.1401 | +9.81 | +239.87 | 1.74 | 7 | 87 | 70 | 17 | 0 |
| **5** *(baseline)* | 84 | 4.60 | 27.38 | 1.1265 | +0.0944 | +7.93 | +192.19 | 1.98 | 8 | 104 | 84 | 20 | 0 |
| **4** | 88 | 4.82 | 28.41 | 1.1916 | +0.1395 | +12.27 | +302.13 | 1.98 | 8 | 106 | 88 | 18 | 0 |
| **3** | 97 | 5.32 | 26.80 | 1.0977 | +0.0750 | +7.27 | +173.39 | 2.21 | 8 | 119 | 97 | 22 | 0 |

### T3 incremental-trade table

| lookback | admitted | WR % | PF | Avg R | total R | mean MFE (R) | mean MAE (R) | ≥1R | ≥2R | months (+/−) | withdrawn | withdrawn Avg R | withdrawn total R | net ΔR | ΔDD % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **6** | 3 | 33.33 | 1.4923 | 0.3333 | +1.00 | 1.579 | 0.945 | 1 | 1 | 3 (1/2) | 17 | -0.0515 | -0.87 | +1.87 | -0.25 |
| **5** *(baseline)* | 0 | — | — | — | 0.00 | — | — | — | — | — | 0 | — | 0.00 | 0.00 | 0.00 |
| **4** | 12 | 58.33 | 4.1954 | 1.3333 | +16.00 | 2.335 | 0.908 | 9 | 8 | 8 (6/2) | 8 | 1.4576 | +11.66 | +4.34 | +0.00 |
| **3** | 26 | 30.77 | 1.3283 | 0.2308 | +6.00 | 1.598 | 1.099 | 15 | 11 | 13 (6/7) | 13 | 0.5124 | +6.66 | -0.66 | +0.23 |

### Core impact — A4 window varied, T3 frozen

| window | trades | trades/mo | WR % | PF | Avg R | total R | PnL | Max DD % | longest losing streak | orders | fills | expired | cancelled |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **UNBOUNDED** *(baseline)* | 177 | 9.70 | 26.55 | 1.0812 | +0.0634 | +11.23 | +265.83 | 2.95 | 10 | 207 | 177 | 30 | 0 |
| **3** | 134 | 7.35 | 25.37 | 1.0112 | +0.0118 | +1.58 | +28.07 | 2.47 | 9 | 159 | 134 | 25 | 0 |
| **2** | 121 | 6.63 | 26.45 | 1.0715 | +0.0558 | +6.75 | +159.56 | 2.20 | 9 | 144 | 121 | 23 | 0 |
| **1** | 111 | 6.08 | 25.23 | 1.0050 | +0.0066 | +0.73 | +10.26 | 2.25 | 9 | 132 | 111 | 21 | 0 |

### Core incremental — A4 window varied

| window | admitted | WR % | PF | Avg R | total R | mean MFE (R) | mean MAE (R) | ≥1R | ≥2R | months (+/−) | withdrawn | withdrawn Avg R | withdrawn total R | net ΔR | ΔDD % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **UNBOUNDED** *(baseline)* | 0 | — | — | — | 0.00 | — | — | — | — | — | 0 | — | 0.00 | 0.00 | 0.00 |
| **3** | 5 | 20.00 | 0.7448 | -0.2104 | -1.05 | 1.083 | 1.151 | 2 | 1 | 4 (1/3) | 48 | 0.1790 | +8.59 | -9.64 | -0.48 |
| **2** | 3 | 0.00 | 0.0000 | -1.0173 | -3.05 | 0.654 | 1.538 | 1 | 0 | 3 (0/3) | 59 | 0.0241 | +1.42 | -4.47 | -0.75 |
| **1** | 4 | 0.00 | 0.0000 | -1.0159 | -4.06 | 1.159 | 1.478 | 2 | 1 | 4 (0/4) | 70 | 0.0919 | +6.43 | -10.50 | -0.70 |

### Core impact — T3 lookback varied, A4 frozen

| lookback | trades | trades/mo | WR % | PF | Avg R | total R | PnL | Max DD % | longest losing streak | orders | fills | expired | cancelled |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **6** | 163 | 8.94 | 26.99 | 1.1046 | +0.0804 | +13.10 | +313.78 | 2.49 | 8 | 190 | 163 | 27 | 0 |
| **5** *(baseline)* | 177 | 9.70 | 26.55 | 1.0812 | +0.0634 | +11.23 | +265.83 | 2.95 | 10 | 207 | 177 | 30 | 0 |
| **4** | 181 | 9.92 | 27.07 | 1.1126 | +0.0860 | +15.56 | +376.16 | 2.95 | 10 | 209 | 181 | 28 | 0 |
| **3** | 190 | 10.42 | 26.32 | 1.0702 | +0.0556 | +10.56 | +247.83 | 3.19 | 11 | 222 | 190 | 32 | 0 |

### Core incremental — T3 lookback varied

| lookback | admitted | WR % | PF | Avg R | total R | mean MFE (R) | mean MAE (R) | ≥1R | ≥2R | months (+/−) | withdrawn | withdrawn Avg R | withdrawn total R | net ΔR | ΔDD % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **6** | 3 | 33.33 | 1.4774 | 0.3333 | +1.00 | 1.579 | 0.945 | 1 | 1 | 3 (1/2) | 17 | -0.0515 | -0.87 | +1.87 | -0.46 |
| **5** *(baseline)* | 0 | — | — | — | 0.00 | — | — | — | — | — | 0 | — | 0.00 | 0.00 | 0.00 |
| **4** | 12 | 58.33 | 4.1741 | 1.3333 | +16.00 | 2.335 | 0.908 | 9 | 8 | 8 (6/2) | 8 | 1.4576 | +11.66 | +4.34 | +0.00 |
| **3** | 26 | 30.77 | 1.3253 | 0.2308 | +6.00 | 1.598 | 1.099 | 15 | 11 | 13 (6/7) | 13 | 0.5124 | +6.66 | -0.66 | +0.24 |

### Marginal bands (each arm against the previous value in the sweep)

| family | band | trades | PF | Avg R | total R |
|---|---|---|---|---|---|
| A4 | 3 → 2 | 0 | n/a | n/a | +0.00 |
| A4 | 2 → 1 | 1 | 0.0000 | -1.0117 | -1.01 |
| T3 | 6 → 5 | 17 | 0.9296 | -0.0515 | -0.87 |
| T3 | 5 → 4 | 12 | 4.1954 | 1.3333 | +16.00 |
| T3 | 4 → 3 | 15 | 0.2132 | -0.7333 | -11.00 |

## MFE/MAE of incremental trades

Excursions are `BAR_BASED_APPROXIMATION`: OHLC cannot reveal the intrabar path, so an
extreme is the bar's extreme, not a tick-exact one.

The A4 arms admit 3–5 trades each whose mean MFE is 0.65–1.16R against a mean MAE of
1.15–1.54R — they go against the position further than they ever go for it. Only 1–2 of
each set ever reached 1R. The trades they withdraw are the opposite: mean MFE 1.47–1.57R
against mean MAE 1.06–1.08R.

T3 lookback 4 admits 12 trades with mean MFE 2.34R against mean MAE 0.91R, 9 of 12
reaching 1R and 8 reaching 2R — genuinely good excursion behaviour. But the 8 trades it
withdraws are indistinguishable: mean MFE 2.39R, mean MAE 0.82R, 3R winners at the same
rate. The arm is exchanging one set of high-quality trades for another.

## Month / year stability

A4: no arm admits enough trades for a distribution to mean anything (3–5 trades over 3–4
months), and every admitted set is negative in most of its months.

T3 admitted streams:

| arm | admitted | months | positive | negative | best month | worst month | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|
| 6 | 3 | 3 | 1 | 2 | 2024-06 +3.00R | 2024-05 −1.00R | 3tr +1.00R | none |
| 4 | 12 | 8 | 6 | 2 | 2024-04 +5.00R (31.2 % of total) | 2024-03 −1.00R | 10tr +14.00R | 2tr +2.00R |
| 3 | 26 | 13 | 6 | 7 | 2024-04 +5.00R | 2024-08 −3.00R | 21tr +3.00R | 5tr +3.00R |

Lookback 4 is **not** concentrated in one month — its best month is 31 % of the total and
six of eight months are positive. It passes that test. It is, however, concentrated in
one *year*: 14 of its 16R come from 2024, with 2 trades and +2R across six months of 2025.

Whole-arm profit factor across the T3 sweep: **6 → 1.1923, 5 → 1.1265, 4 → 1.1916,
3 → 1.0977**. The frozen baseline is a local *minimum* between two better neighbours.
The marginal bands flip sign violently — 6→5 is −0.87R over 17 trades, 5→4 is +16.00R
over 12, 4→3 is −11.00R over 15. A one-bar change in lookback moves marginal expectancy
from +1.33R per trade to −0.73R per trade. That is a noise signature, not a structural
edge: a real one would show a plateau, not an isolated spike flanked by reversals.

## Contention / displacement

The Core trade set is the **exact union** of the two standalone sets — same entry times,
prices and realized R — at all eight arms:

| arm | Core vs standalone union | | arm | Core vs standalone union |
|---|---|---|---|---|
| A4 window unbounded | 0 lost, 0 extra | | T3 lookback 6 | 0 lost, 0 extra |
| A4 window 3 | 0 lost, 0 extra | | T3 lookback 5 | 0 lost, 0 extra |
| A4 window 2 | 0 lost, 0 extra | | T3 lookback 4 | 0 lost, 0 extra |
| A4 window 1 | 0 lost, 0 extra | | T3 lookback 3 | 0 lost, 0 extra |

A4↔T3 contention cost zero trades again, reproducing the Phase A result across a
completely different kind of change — including the arms that *reduce* A4's trade count
by up to 71 %, which freed the shared position slot without T3 picking up a single extra
trade. The children's bullish and bearish H1 opportunity sets do not overlap.

Displacement within a child is real and is what the withdrawn columns measure. For the
A4 window arms it dominates: window 3 withdraws 48 baseline trades worth +8.59R to admit
5 worth −1.05R.

## Phase B decision

**A4 — REJECT ALL.** Every bounded window fails both directions of the acceptance rule.
The trades each window admits have strongly negative expectancy (Avg R −0.21, −1.02,
−1.02; PF 0.74, 0.00, 0.00), and the trades each window withdraws have **positive**
expectancy (Avg R +0.179, +0.024, +0.092; PF 1.25, 1.03, 1.12). Net R change is −9.64,
−4.47 and −10.50 against a baseline of +3.29R, and every arm turns the strategy negative.

This is a positive finding about the frozen strategy: the unbounded wait is doing real
work. Roughly half of A4's profitable signals arrive on the fifth bar of a pullback or
later, and the existing invalidation rules — not a clock — are what should end a setup.
Confirmation timing is not the lever behind the 4,677 → 231 bottleneck.

**T3 — REJECT ALL, with one observation flagged.** Lookback 4 is the only arm in Phase A
or Phase B whose admitted trades have clearly positive expectancy: 12 trades, Avg R
+1.333, PF 4.20, WR 58.3 %, mean MFE 2.34R against MAE 0.91R, spread over eight months
with six positive. It passes the expectancy test and the one-month concentration test.

It is rejected on local stability and sample size, which the brief ranks above picking
the best value. The neighbourhood is not a plateau: lookback 3 is worse than baseline
(−0.66R net) and the marginal bands around 4 reverse sign (−0.87R, +16.00R, −11.00R).
The arm also withdraws 8 baseline trades that were *better* than the ones it admits
(Avg R +1.458 vs +1.333, PF 4.88 vs 4.20), so the +4.34R net is a small residual of two
large opposing flows across roughly twenty trades. Twelve admitted trades, 10 of them in
a single year, cannot distinguish a structural edge from noise.

Lookback 4 is recorded as the single lead worth a dedicated stability study — parameter
neighbourhood, sub-period bootstrap, and sensitivity to the break definition itself —
before it is ever allowed near the holdout. It is not carried forward as a candidate.

**Neither A4 nor T3 modifications are combined. No parameter outside the two under test
moved. The holdout remains unread.**

## Verification

* Frozen fingerprints unchanged: A4 `55fedf85…`, T3 `4c4ab845…`, Core `631374d5…`.
* Every baseline arm reproduces its frozen counterpart's trade log exactly.
* Window semantics proven on real data: no arm emits a confirmation older than its window.
* The frozen baseline is proven to confirm well past any window, or the experiment would
  have been vacuous.
* Machine-readable results: `reports/research/core_v2_phase_b.json`.
