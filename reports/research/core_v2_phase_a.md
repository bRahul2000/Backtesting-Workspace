# BTC Core V2 — Phase A: local quality-gate ablation

Controlled ablation, not an optimizer search. One number moves per experiment; every
other rule is inherited from the frozen strategy by subclassing. The frozen files are
byte-for-byte unchanged and no run touched the holdout.

## Locked research split

| | |
|---|---|
| DEVELOPMENT | 2023-11-10 23:15 UTC → 2025-06-30 23:45 UTC |
| HOLDOUT / OOS | 2025-07-01 00:00 UTC → 2026-09-20 07:15 UTC |
| **Holdout touched** | **NO** |
| Dataset | `data/exness/btc/phase_r1/processed/btcusdm_M15.csv` |
| Fingerprint | `80735a2cf521363747f48368814267ad6ca146eb294bb7bd7252666d06c76af3` (verified at run time) |
| Risk / reward | 0.25 % per trade, 3R fixed |

`research/core_v2_phase_a.py` refuses to run if the configured end date reaches
`HOLDOUT_START`, and re-verifies the dataset fingerprint before every arm.

## Method

Arms are wrappers in `strategies/btc_core_v2_variants.py`. Each subclasses the frozen
strategy and overrides exactly one parameter, so the H1 regime, ADX, structure logic,
pullback state machine, RSI bands, EMA extension, stop band, 3R target, session and
daily cap are inherited unchanged. The A4 upper body cap stays at 0.90.

The arms are never registered globally. `phase_a_registry()` builds an isolated registry
holding the builtins plus the sixteen arms, and `run_universal_backtest` now accepts a
registry argument. Registering them globally put all sixteen into the Universal Workspace
strategy dropdown the moment anything imported the module — caught by the existing UI
registry test, and now pinned by a test of its own.

At the frozen 0.70 default every wrapper produces a trade log identical to the frozen
strategy on real data — asserted for A4, T3 and both Core compositions. If that ever
fails, the wrapper is doing something other than moving one number.

The decision rule is the incremental one. Aggregate metrics are dominated by the legacy
baseline trades that every arm shares, so each arm is judged on the trades it *newly
admits* against the 0.70 control, and additionally band by band against the next-tighter
arm. Trades the relaxation *displaces* — a baseline trade that no longer happens because
an earlier admitted trade took the single global position slot — are reported separately,
because otherwise a relaxation looks free.


### A4 standalone

| body | closed trades | trades/mo | win % | PF | Avg R | total R | PnL | Max DD % | longest losing streak | orders created |
|---|---|---|---|---|---|---|---|---|---|---|
| **0.70** *(baseline)* | 93 | 5.10 | 25.81 | 1.0425 | +0.0354 | +3.29 | +74.02 | 1.71 | 6 | 103 |
| **0.60** | 135 | 7.40 | 22.22 | 0.8565 | -0.1088 | -14.69 | -373.62 | 3.96 | 11 | 147 |
| **0.50** | 158 | 8.66 | 22.78 | 0.8878 | -0.0835 | -13.19 | -340.06 | 3.94 | 11 | 167 |
| **0.40** | 171 | 9.37 | 23.39 | 0.9208 | -0.0572 | -9.78 | -256.47 | 3.54 | 8 | 181 |

### A4 incremental

| body | incremental trades | win % | PF | Avg R | total R | PnL | stream max DD (R) | months (pos/neg) | displaced | displaced R | run DD delta |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **0.70** *(baseline)* | 0 | — | — | — | 0.00 | 0.00 | 0.00 | — | 0 | 0.00 | — |
| **0.60** | 57 | 17.54 | 0.6337 | -0.2972 | -16.94 | -426.14 | -22.16 | 17 (4/13) | 15 | +1.04 | +2.25 |
| **0.50** | 98 | 20.41 | 0.7736 | -0.1743 | -17.08 | -435.53 | -22.87 | 18 (6/12) | 33 | -0.60 | +2.24 |
| **0.40** | 115 | 20.87 | 0.7982 | -0.1538 | -17.68 | -450.72 | -23.68 | 18 (6/12) | 37 | -4.60 | +1.83 |

### A4 marginal bands

| band | trades in band | win % | PF | Avg R | total R | stream max DD (R) |
|---|---|---|---|---|---|---|
| 0.70 → 0.60 | 57 | 17.54 | 0.6337 | -0.2972 | -16.94 | -22.16 |
| 0.60 → 0.50 | 49 | 24.49 | 0.9923 | -0.0031 | -0.15 | -8.70 |
| 0.50 → 0.40 | 27 | 25.93 | 1.0978 | +0.0744 | +2.01 | -7.15 |

### T3 standalone

| body | closed trades | trades/mo | win % | PF | Avg R | total R | PnL | Max DD % | longest losing streak | orders created |
|---|---|---|---|---|---|---|---|---|---|---|
| **0.70** *(baseline)* | 84 | 4.60 | 27.38 | 1.1265 | +0.0944 | +7.93 | +192.19 | 1.98 | 8 | 104 |
| **0.60** | 113 | 6.19 | 24.78 | 0.9851 | -0.0078 | -0.89 | -31.35 | 2.72 | 11 | 142 |
| **0.50** | 133 | 7.29 | 21.05 | 0.7961 | -0.1567 | -20.84 | -528.52 | 3.21 | 12 | 171 |
| **0.40** | 143 | 7.84 | 20.98 | 0.7934 | -0.1589 | -22.73 | -576.21 | 2.97 | 12 | 183 |

### T3 incremental

| body | incremental trades | win % | PF | Avg R | total R | PnL | stream max DD (R) | months (pos/neg) | displaced | displaced R | run DD delta |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **0.70** *(baseline)* | 0 | — | — | — | 0.00 | 0.00 | 0.00 | — | 0 | 0.00 | — |
| **0.60** | 35 | 20.00 | 0.7513 | -0.1948 | -6.82 | -172.64 | -11.82 | 12 (4/7) | 6 | +2.00 | +0.73 |
| **0.50** | 57 | 12.28 | 0.4203 | -0.5048 | -28.77 | -715.83 | -30.77 | 14 (4/9) | 8 | +0.00 | +1.23 |
| **0.40** | 69 | 13.04 | 0.4502 | -0.4733 | -32.66 | -814.15 | -34.66 | 16 (5/11) | 10 | -2.00 | +0.99 |

### T3 marginal bands

| band | trades in band | win % | PF | Avg R | total R | stream max DD (R) |
|---|---|---|---|---|---|---|
| 0.70 → 0.60 | 35 | 20.00 | 0.7513 | -0.1948 | -6.82 | -11.82 |
| 0.60 → 0.50 | 24 | 4.17 | 0.1304 | -0.8315 | -19.96 | -19.96 |
| 0.50 → 0.40 | 16 | 12.50 | 0.4287 | -0.4930 | -7.89 | -8.00 |

### Core, A4 variant + T3 frozen

| body | closed trades | trades/mo | win % | PF | Avg R | total R | PnL | Max DD % | longest losing streak | orders created |
|---|---|---|---|---|---|---|---|---|---|---|
| **0.70** *(baseline)* | 177 | 9.70 | 26.55 | 1.0812 | +0.0634 | +11.23 | +265.83 | 2.95 | 10 | 207 |
| **0.60** | 219 | 12.00 | 24.20 | 0.9549 | -0.0309 | -6.76 | -185.61 | 3.72 | 11 | 251 |
| **0.50** | 242 | 13.27 | 24.38 | 0.9673 | -0.0217 | -5.26 | -148.52 | 3.91 | 14 | 271 |
| **0.40** | 255 | 13.98 | 24.71 | 0.9861 | -0.0073 | -1.85 | -66.24 | 3.59 | 9 | 285 |

### Core/A4 incremental

| body | incremental trades | win % | PF | Avg R | total R | PnL | stream max DD (R) | months (pos/neg) | displaced | displaced R | run DD delta |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **0.70** *(baseline)* | 0 | — | — | — | 0.00 | 0.00 | 0.00 | — | 0 | 0.00 | — |
| **0.60** | 57 | 17.54 | 0.6353 | -0.2972 | -16.94 | -423.85 | -22.16 | 17 (4/13) | 15 | +1.04 | +0.77 |
| **0.50** | 98 | 20.41 | 0.7748 | -0.1743 | -17.08 | -433.57 | -22.87 | 18 (6/12) | 33 | -0.60 | +0.96 |
| **0.40** | 115 | 20.87 | 0.7995 | -0.1538 | -17.68 | -448.23 | -23.68 | 18 (6/11) | 37 | -4.60 | +0.64 |

### Core, T3 variant + A4 frozen

| body | closed trades | trades/mo | win % | PF | Avg R | total R | PnL | Max DD % | longest losing streak | orders created |
|---|---|---|---|---|---|---|---|---|---|---|
| **0.70** *(baseline)* | 177 | 9.70 | 26.55 | 1.0812 | +0.0634 | +11.23 | +265.83 | 2.95 | 10 | 207 |
| **0.60** | 206 | 11.29 | 25.24 | 1.0112 | +0.0117 | +2.41 | +43.18 | 3.44 | 11 | 245 |
| **0.50** | 226 | 12.39 | 23.01 | 0.8953 | -0.0776 | -17.55 | -454.05 | 3.92 | 12 | 274 |
| **0.40** | 236 | 12.94 | 22.88 | 0.8892 | -0.0824 | -19.44 | -502.07 | 3.96 | 12 | 286 |

### Core/T3 incremental

| body | incremental trades | win % | PF | Avg R | total R | PnL | stream max DD (R) | months (pos/neg) | displaced | displaced R | run DD delta |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **0.70** *(baseline)* | 0 | — | — | — | 0.00 | 0.00 | 0.00 | — | 0 | 0.00 | — |
| **0.60** | 35 | 20.00 | 0.7517 | -0.1948 | -6.82 | -173.31 | -11.82 | 12 (4/7) | 6 | +2.00 | +0.48 |
| **0.50** | 57 | 12.28 | 0.4205 | -0.5048 | -28.77 | -719.61 | -30.77 | 14 (4/9) | 8 | -0.00 | +0.97 |
| **0.40** | 69 | 13.04 | 0.4503 | -0.4733 | -32.66 | -818.61 | -34.66 | 16 (5/10) | 10 | -2.00 | +1.01 |

## Contention effects

On the development split the Core's trade set is the **exact union** of the two
standalone trade sets — same entry times, same prices, same realized R — at all four
thresholds. Verified by set comparison, not by counting:

| threshold | Core(A4 variant + T3 frozen) vs standalone union | Core(T3 variant + A4 frozen) vs standalone union |
|---|---|---|
| 0.70 | 0 lost, 0 extra | 0 lost, 0 extra |
| 0.60 | 0 lost, 0 extra | 0 lost, 0 extra |
| 0.50 | 0 lost, 0 extra | 0 lost, 0 extra |
| 0.40 | 0 lost, 0 extra | 0 lost, 0 extra |

**A4↔T3 contention cost zero trades**, even as the relaxations roughly doubled each
child's signal rate. Contention is real at the bar level — the Core funnel counts 9,590
bars where A4 was blocked by an open position and 51 by a T3-owned pending order, and
8,695 / 25 the other way — but on this split it never removed a completed trade. The
children's opportunity sets are bullish and bearish H1 regimes, which do not overlap.

The displacement that *does* occur is **within** a child, not between them: an earlier
relaxed-threshold trade takes the slot that a later baseline trade would have used.
A4 displaces 15 / 33 / 37 baseline trades at 0.60 / 0.50 / 0.40; T3 displaces 6 / 8 / 10.
The displaced R is small in every case (+1.04 to −4.60R), so displacement is not what
drives the results — the admitted trades are.

This is a development-split finding at these relaxation levels. It is not a general
guarantee that contention is free.

## Month / year stability

Whole-arm yearly average R (2023 is a partial year; data starts 2023-11-10):

| arm | 2023 | 2024 | 2025 (to 06-30) |
|---|---|---|---|
| A4 0.70 | +0.598 (5) | −0.025 (66) | +0.088 (22) |
| A4 0.60 | +0.138 (7) | −0.141 (98) | −0.062 (30) |
| A4 0.50 | +0.138 (7) | −0.114 (113) | −0.034 (38) |
| A4 0.40 | +0.323 (9) | −0.111 (122) | +0.023 (40) |
| T3 0.70 | −1.000 (2) | +0.119 (50) | +0.125 (32) |
| T3 0.60 | −1.000 (2) | +0.030 (70) | −0.024 (41) |
| T3 0.50 | −1.000 (4) | −0.121 (82) | −0.148 (47) |
| T3 0.40 | −1.000 (5) | −0.145 (89) | −0.099 (49) |

Relaxation degrades 2024 and 2025 for both children, so the damage is not a single-year
artefact.

The incremental trades are **broadly negative, not concentrated in one bad month**:

| arm | incremental months | positive | negative | best month | worst month |
|---|---|---|---|---|---|
| A4 0.60 | 17 | 4 | 13 | 2024-11 +7.00R | 2024-07 −7.00R |
| A4 0.50 | 18 | 6 | 12 | 2024-11 +6.00R | 2024-09 −7.00R |
| A4 0.40 | 18 | 6 | 12 | 2024-10 +5.57R | 2024-05 −7.03R |
| T3 0.60 | 12 | 4 | 7 | 2024-08 +5.18R | 2024-01 −4.00R |
| T3 0.50 | 14 | 4 | 9 | 2024-08 +3.18R | 2024-01 −9.00R |
| T3 0.40 | 16 | 5 | 11 | 2024-08 +2.18R | 2024-01 −9.00R |

No arm has a positive incremental total, so "share of total R from the best month" is
not a meaningful concentration measure here and is deliberately not reported. The
relevant fact is that negative months outnumber positive ones roughly 2:1 to 3:1 in
every incremental stream. There is no single month whose removal would rescue an arm.

**Local stability 0.70 → 0.60 → 0.50 → 0.40.** Cumulative incremental PF against the
baseline is 0.63 → 0.77 → 0.80 for A4 and 0.75 → 0.42 → 0.45 for T3 — non-monotone in
both, and below 1.0 everywhere. The marginal bands are more revealing: A4's worst band
is the one immediately below the frozen threshold (0.70→0.60, PF 0.63, Avg R −0.297),
while the deeper bands are roughly neutral (0.60→0.50, PF 0.99) and slightly positive
(0.50→0.40, PF 1.10, 27 trades). T3 has no such structure: its bands are −0.195, −0.832,
−0.493 Avg R. Neither child shows a stable plateau that would justify a new threshold.

## Phase A conclusion

**A4 — REJECT ALL.** Every candidate's newly admitted trades lose money: 0.60 admits 57
trades at Avg R −0.297 (PF 0.63), 0.50 admits 98 at −0.174 (PF 0.77), 0.40 admits 115 at
−0.154 (PF 0.80). Whole-arm total R falls from +3.29R to −14.69 / −13.19 / −9.78R and
max drawdown roughly doubles, from 1.71 % to 3.54–3.96 %. The stated rejection rule —
reject any relaxation whose newly admitted trades have negative expectancy — rejects all
three, and here the aggregate metrics do not even look temporarily acceptable.

One observation to carry as a *question*, not a candidate: A4's marginal 0.50→0.40 band
is 27 trades at PF 1.10 / Avg R +0.074, and the 0.60→0.50 band is flat. The damage is
concentrated in the 0.60–0.70 band specifically. That is 27 trades on a development
split — far too small to act on, and it does not make any *threshold* better, since every
arm at or below 0.60 must first absorb that bad band. It suggests body percent alone is
the wrong discriminator and that whatever separates the 0.60–0.70 band from the deeper
one is worth identifying before any threshold is moved.

**T3 — REJECT ALL.** Worse and unambiguous: 0.60 admits 35 trades at Avg R −0.195
(PF 0.75), 0.50 admits 57 at −0.505 (PF 0.42), 0.40 admits 69 at −0.473 (PF 0.45).
Incremental win rate collapses from the 27.38 % baseline to 20.0 / 12.3 / 13.0 %. Whole-arm
total R falls from +7.93R to −0.89 / −20.84 / −22.73R. The T3 0.70 body filter is the
single most productive gate in the strategy: it discards 61 % of otherwise-qualifying
breakdown candles, and those candles lose money.

**Neither relaxation is carried forward. The frozen 0.70 thresholds stand on the
development split.** A4 and T3 relaxations were not combined, no other parameter was
touched, the reward multiple remains 3R, and the holdout remains unread.

## Verification

* Frozen fingerprints unchanged: A4 `55fedf85…`, T3 `4c4ab845…`, Core `631374d5…`.
* Each 0.70 arm produces a trade log identical to its frozen counterpart on real data.
* Every non-ablated parameter asserted equal to the frozen value, field by field.
* The production catalog exposes no `RESEARCH_*` arm (checked in a clean subprocess).
* Tests 981 → **1,036** (55 new). Full suite green. MT5 static checks 80, PASS.
* Machine-readable results: `reports/research/core_v2_phase_a.json`.

## Defect found during this phase (not fixed here)

`core/adapters/audited_engine.py::_trade_row` unwraps any value exposing `.value` before
its `isinstance(value, pd.Timestamp)` branch can run. `pd.Timestamp.value` is epoch
nanoseconds, so **every timestamp in `trade_log` is an integer, and the Timestamp branch
is dead code**. The Trades tab and its CSV export therefore show `1701569700000000000`
instead of a date. Phase A parses both forms so its analysis is correct. The fix is one
line, but it changes the trade-log schema for roughly ten consumers, so it does not
belong inside an ablation commit whose artifacts are being compared.
