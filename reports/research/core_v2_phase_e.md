# BTC Core V2 — Phase E: D2 A4-SHORT stability and integration study

Phase D produced one survivor. Phase E asks the Phase C questions of it, and adds the
question Phase D raised but could not answer: D2 displaced nine frozen T3 trades that
averaged +1.185R, so is D2 an addition or a substitution?

## D2 SOURCE HASH

D2 was frozen before any Phase E work. The hash covers the three source objects that
constitute it — `h1_bearish`, `short_confirmation_passes` and `D2A4ShortMirror` in
`strategies/btc_core_v2_phase_d_families.py`:

```
16b07458a0049b118cbb0003b9250e4653d6706460ab1e4c601a14679cde6a6e
```

Every Phase E run re-verifies it and refuses to proceed on a mismatch. Sensitivity arms
are separate subclasses in `strategies/btc_core_v2_phase_e_variants.py`; D2 itself was
not edited.

## DEVELOPMENT CONFIRMATION

| | |
|---|---|
| DEVELOPMENT | 2023-11-10 23:15 UTC → 2025-06-30 23:45 UTC |
| HOLDOUT | 2025-07-01 00:00 UTC → 2026-09-20 07:15 UTC |
| **Holdout touched** | **NO** — runs refuse an end date reaching `HOLDOUT_START`; no rolling window ends past `DEVELOPMENT_END` |
| Dataset | `data/exness/btc/phase_r1/processed/btcusdm_M15.csv`, fingerprint `80735a2c…` verified per arm |

Reference reproduced exactly: Core 177 trades / PF 1.0812 / +11.23R; D2 standalone 56 /
1.2819 / +11.20R; Core+D2 196 / 1.1051 / +15.76R; incremental 28 trades / PF 1.8883 /
Avg R +0.5428 / MFE 2.03R / MAE 0.93R.

As in Phase C, subperiods and rolling windows slice the trades of one continuous run
rather than re-running on truncated data, so a cold start cannot masquerade as a regime
difference.

## SUBPERIOD RESULTS

### D2 standalone

| period | trades | trades/mo | WR % | PF | Avg R | total R | Max DD % | losing streak |
|---|---|---|---|---|---|---|---|---|
| 2023 partial | 0 | 0.00 | — | — | — | +0.00 | 0.00 | 0 |
| 2024 H1 | 21 | 3.51 | 23.81 | 0.9332 | -0.0476 | -1.00 | 1.50 | 6 |
| 2024 H2 | 12 | 1.99 | 33.33 | 1.4939 | 0.3333 | +4.00 | 0.75 | 3 |
| 2025 H1 | 23 | 3.87 | 34.78 | 1.5384 | 0.3564 | +8.20 | 0.99 | 4 |

### D2 integrated into Core

| period | baseline total R | Core+D2 total R | Δ total R | D2 trades added | A4 displaced | T3 displaced | displaced R | incremental PF | incremental Avg R |
|---|---|---|---|---|---|---|---|---|---|
| 2023 partial | +0.99 | +0.99 | **+0.00** | 0 | 0 | 0 | +0.00 | — | — |
| 2024 H1 | -2.73 | -0.73 | **+2.00** | 10 | 0 | 4 | +0.00 | 1.2895 | 0.2000 |
| 2024 H2 | +7.04 | +5.38 | **-1.66** | 7 | 0 | 1 | +2.66 | 1.1980 | 0.1429 |
| 2025 H1 | +5.93 | +10.13 | **+4.20** | 11 | 0 | 4 | +8.00 | 3.4110 | 1.1089 |

## ROLLING 3M

17 windows, 3-month length, 1-month step.

| window | baseline total R | Core+D2 total R | Δ R | D2 added | baseline displaced | incremental PF | incremental Avg R |
|---|---|---|---|---|---|---|---|
| 2023-11-10→2024-02-10 | -1.04 | -4.04 | **-3.00** | 3 | 0 | 0.000 | -1.000 |
| 2023-12-10→2024-03-10 | +0.22 | -2.78 | **-3.00** | 3 | 0 | 0.000 | -1.000 |
| 2024-01-10→2024-04-10 | -2.85 | -5.85 | **-3.00** | 4 | 1 | 0.000 | -1.000 |
| 2024-02-10→2024-05-10 | +3.18 | +4.18 | **+1.00** | 2 | 3 | 3.007 | 1.000 |
| 2024-03-10→2024-06-10 | -4.10 | -3.10 | **+1.00** | 2 | 3 | 3.007 | 1.000 |
| 2024-04-10→2024-07-10 | -0.88 | +5.12 | **+6.00** | 9 | 3 | 2.398 | 0.778 |
| 2024-05-10→2024-08-10 | +5.12 | +10.12 | **+5.00** | 8 | 1 | 1.798 | 0.500 |
| 2024-06-10→2024-09-10 | +12.86 | +16.20 | **+3.34** | 11 | 2 | 1.710 | 0.455 |
| 2024-07-10→2024-10-10 | +7.76 | +5.10 | **-2.66** | 4 | 1 | 1.002 | 0.000 |
| 2024-08-10→2024-11-10 | -3.00 | -5.67 | **-2.66** | 4 | 1 | 1.002 | 0.000 |
| 2024-09-10→2024-12-10 | -7.72 | -8.72 | **-1.00** | 1 | 0 | 0.000 | -1.000 |
| 2024-10-10→2025-01-10 | +0.28 | +0.28 | **-0.00** | 0 | 0 | — | — |
| 2024-11-10→2025-02-10 | +0.05 | +0.05 | **+0.00** | 0 | 0 | — | — |
| 2024-12-10→2025-03-10 | +9.05 | +8.05 | **-1.00** | 3 | 2 | 5.941 | 1.667 |
| 2025-01-10→2025-04-10 | +10.00 | +9.48 | **-0.52** | 8 | 4 | 2.850 | 0.935 |
| 2025-02-10→2025-05-10 | +13.93 | +13.41 | **-0.52** | 8 | 4 | 2.850 | 0.935 |
| 2025-03-10→2025-06-10 | -0.07 | +0.41 | **+0.48** | 5 | 2 | 1.824 | 0.496 |

**Summary** — improved 6, degraded 9, neutral 2 (|Δ| ≤ 0.33R). Worst **-3.00R**, median **-0.52R**, best **+6.00R**.

## ROLLING 6M

14 windows, 6-month length, 1-month step.

| window | baseline total R | Core+D2 total R | Δ R | D2 added | baseline displaced | incremental PF | incremental Avg R |
|---|---|---|---|---|---|---|---|
| 2023-11-10→2024-05-10 | +2.14 | +0.14 | **-2.00** | 5 | 3 | 0.755 | -0.200 |
| 2023-12-10→2024-06-10 | -3.88 | -5.88 | **-2.00** | 5 | 3 | 0.755 | -0.200 |
| 2024-01-10→2024-07-10 | -3.73 | -0.73 | **+3.00** | 13 | 4 | 1.336 | 0.231 |
| 2024-02-10→2024-08-10 | +8.30 | +14.30 | **+6.00** | 10 | 4 | 1.999 | 0.600 |
| 2024-03-10→2024-09-10 | +8.77 | +13.11 | **+4.34** | 13 | 5 | 1.870 | 0.538 |
| 2024-04-10→2024-10-10 | +6.88 | +10.22 | **+3.34** | 13 | 4 | 1.867 | 0.538 |
| 2024-05-10→2024-11-10 | +2.11 | +4.45 | **+2.34** | 12 | 2 | 1.495 | 0.333 |
| 2024-06-10→2024-12-10 | +5.14 | +7.48 | **+2.34** | 12 | 2 | 1.495 | 0.333 |
| 2024-07-10→2025-01-10 | +8.04 | +5.38 | **-2.66** | 4 | 1 | 1.002 | 0.000 |
| 2024-08-10→2025-02-10 | -2.96 | -5.62 | **-2.66** | 4 | 1 | 1.002 | 0.000 |
| 2024-09-10→2025-03-10 | +1.33 | -0.67 | **-2.00** | 4 | 2 | 2.959 | 1.000 |
| 2024-10-10→2025-04-10 | +10.28 | +9.76 | **-0.52** | 8 | 4 | 2.850 | 0.935 |
| 2024-11-10→2025-05-10 | +13.97 | +13.46 | **-0.52** | 8 | 4 | 2.850 | 0.935 |
| 2024-12-10→2025-06-10 | +8.97 | +8.46 | **-0.52** | 8 | 4 | 2.850 | 0.935 |

**Summary** — improved 6, degraded 8, neutral 0 (|Δ| ≤ 0.33R). Worst **-2.66R**, median **-0.52R**, best **+6.00R**.

## LEAVE-ONE-MONTH-OUT

| month dropped | removed | remaining | PF | Avg R | total R |
|---|---|---|---|---|---|
| 2024-01 | 3 | 25 | 2.287 | 0.728 | +18.20 |
| 2024-03 | 1 | 27 | 2.005 | 0.600 | +16.20 |
| 2024-04 | 1 | 27 | 1.713 | 0.452 | +12.20 |
| 2024-06 | 5 | 23 | 1.865 | 0.530 | +12.20 |
| 2024-07 | 3 | 25 | 1.940 | 0.568 | +14.20 |
| 2024-08 | 3 | 25 | 1.942 | 0.568 | +14.20 |
| 2024-10 | 1 | 27 | 2.007 | 0.600 | +16.20 |
| 2025-02 | 3 | 25 | 1.635 | 0.408 | +10.20 |
| 2025-03 | 4 | 24 | 2.118 | 0.655 | +15.72 |
| 2025-04 | 1 | 27 | 1.711 | 0.452 | +12.20 |
| 2025-06 | 3 | 25 | 1.652 | 0.419 | +10.48 |

## LEAVE-2024-OUT / LEAVE-2025-H1-OUT

| dropped | removed | remaining | PF | Avg R | total R |
|---|---|---|---|---|---|
| 2023 | 0 | 28 | 1.888 | 0.543 | +15.20 |
| 2024 | 17 | 11 | 3.411 | 1.109 | +12.20 |
| 2025 | 11 | 17 | 1.251 | 0.176 | +3.00 |
| **2025 H1** | 11 | 17 | 1.251 | 0.176 | **+3.00** |

## BLOCK BOOTSTRAP

Circular block bootstrap of the 28 incremental trades, 10,000 samples per block length. Primary block **3** (n^(1/3) = 3.0 for n = 28).

| block | metric | p5 | p25 | median | p75 | p95 | tail probability |
|---|---|---|---|---|---|---|---|
| 1 | total_r | -0.567 | 7.717 | 15.198 | 22.680 | 31.482 | P(total R ≤ 0) = 0.0766 |
| 1 | average_r | -0.020 | 0.276 | 0.543 | 0.810 | 1.124 | P(Avg R ≤ 0) = 0.0766 |
| 1 | profit_factor | 0.973 | 1.406 | 1.894 | 2.512 | 3.422 | P(PF ≤ 1) = 0.0786 |
| 2 | total_r | -0.283 | 8.000 | 15.198 | 22.113 | 30.866 | P(total R ≤ 0) = 0.0601 |
| 2 | average_r | -0.010 | 0.286 | 0.543 | 0.790 | 1.102 | P(Avg R ≤ 0) = 0.0601 |
| 2 | profit_factor | 0.987 | 1.421 | 1.894 | 2.474 | 3.374 | P(PF ≤ 1) = 0.0621 |
| 3 **(primary)** | total_r | 0.000 | 9.585 | 15.198 | 19.717 | 30.116 | P(total R ≤ 0) = 0.0495 |
| 3 | average_r | 0.000 | 0.342 | 0.543 | 0.704 | 1.076 | P(Avg R ≤ 0) = 0.0495 |
| 3 | profit_factor | 1.000 | 1.532 | 1.894 | 2.232 | 3.317 | P(PF ≤ 1) = 0.0512 |
| 4 | total_r | 2.963 | 10.680 | 15.198 | 19.717 | 27.717 | P(total R ≤ 0) = 0.0414 |
| 4 | average_r | 0.106 | 0.381 | 0.543 | 0.704 | 0.990 | P(Avg R ≤ 0) = 0.0414 |
| 4 | profit_factor | 1.148 | 1.593 | 1.894 | 2.232 | 2.980 | P(PF ≤ 1) = 0.0423 |

## LOCAL PARAMETER STABILITY

### Parameters mechanically mirrored from A4 into D2

| parameter | baseline | perturbed here |
|---|---|---|
| `confirmation_min_body_percent` | 0.70 — body of the bearish reclaim candle | yes |
| `mirrored_rsi_band` | 30–52, reflection of A4's 48–70 about 50 | yes |
| `minimum_normalized_h1_slope` | 0.15 — |H1 EMA200 slope| / H1 ATR | yes |
| `confirmation_max_body_percent` | 0.90 — A4 overlay cap, not perturbed | no |
| `max_pullback_depth_below_ema20_atr` | 1.00 — rally depth above EMA20 | no |
| `material_ema50_close_atr` | 0.20 — close materially above EMA50 invalidates | no |
| `h1_min_separation_atr` | 1.00 — confirmed H1 EMA separation | no |
| `min_adx` | 18.0 — M15 ADX floor | no |
| `local_structure_lookback` | 5 bars — prior low that defines a structure break | no |
| `entry_buffer_atr / stop_buffer_atr` | 0.05 / 0.20 | no |
| `minimum_stop_atr / maximum_stop_atr` | 0.50 / 3.00 | no |
| `pending_bars` | 2 | no |
| `reward_multiple` | 3.0 — fixed, never perturbed | no |

### BODY — `confirmation_min_body_percent` (baseline 0.7)

| value | standalone trades | standalone PF | standalone Avg R | standalone total R | standalone DD % | Core trades | Core PF | Core total R | Core DD % | added | T3 displaced | net ΔR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **0.65** | 64 | 1.1521 | +0.1125 | +7.20 | 1.74 | 201 | 1.0674 | +10.76 | 3.64 | 36 | 12 | **-0.46** |
| **0.7** *(baseline)* | 56 | 1.2819 | +0.2000 | +11.20 | 1.49 | 196 | 1.1051 | +15.76 | 3.19 | 28 | 9 | **+4.54** |
| **0.75** | 36 | 1.3037 | +0.2143 | +7.72 | 1.24 | 191 | 1.0872 | +12.94 | 3.19 | 19 | 5 | **+1.72** |

### RSI — `mirrored_rsi_band_offset` (baseline 0.0)

| value | standalone trades | standalone PF | standalone Avg R | standalone total R | standalone DD % | Core trades | Core PF | Core total R | Core DD % | added | T3 displaced | net ΔR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **-2.0** | 59 | 1.1902 | +0.1390 | +8.20 | 1.49 | 196 | 1.1050 | +15.76 | 3.19 | 29 | 10 | **+4.54** |
| **0.0** *(baseline)* | 56 | 1.2819 | +0.2000 | +11.20 | 1.49 | 196 | 1.1051 | +15.76 | 3.19 | 28 | 9 | **+4.54** |
| **2.0** | 48 | 1.2086 | +0.1500 | +7.20 | 1.74 | 194 | 1.0919 | +13.76 | 3.19 | 25 | 8 | **+2.54** |

### SLOPE — `minimum_normalized_h1_slope` (baseline 0.15)

| value | standalone trades | standalone PF | standalone Avg R | standalone total R | standalone DD % | Core trades | Core PF | Core total R | Core DD % | added | T3 displaced | net ΔR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **0.1** | 67 | 1.3511 | +0.2435 | +16.31 | 1.49 | 204 | 1.1295 | +19.88 | 3.19 | 43 | 16 | **+8.65** |
| **0.15** *(baseline)* | 56 | 1.2819 | +0.2000 | +11.20 | 1.49 | 196 | 1.1051 | +15.76 | 3.19 | 28 | 9 | **+4.54** |
| **0.2** | 25 | 1.9953 | +0.6000 | +15.00 | 0.50 | 185 | 1.1080 | +15.23 | 2.95 | 13 | 5 | **+4.00** |

## EXECUTION STRESS

| stress | D2 standalone PF | D2 standalone total R | Core baseline total R | Core+D2 total R | net ΔR | incremental PF | incremental Avg R | incremental total R |
|---|---|---|---|---|---|---|---|---|
| NATIVE | 1.2819 | +11.20 | +11.23 | +15.76 | **+4.54** | 1.8883 | 0.5428 | +15.20 |
| SPREAD_x1.10 | 1.2497 | +10.20 | +8.94 | +13.47 | **+4.54** | 1.7806 | 0.4896 | +14.20 |
| SPREAD_x1.20 | 1.2497 | +10.20 | +6.97 | +11.51 | **+4.54** | 1.7804 | 0.4896 | +14.20 |
| SLIPPAGE_0.02% | 1.2208 | +9.03 | +3.71 | +4.87 | **+1.16** | 1.5815 | 0.3772 | +10.56 |
| SLIPPAGE_0.05% | 0.9768 | -0.82 | -7.16 | -10.55 | **-3.39** | 1.2757 | 0.1891 | +5.30 |
| SPREAD_x1.20_SLIP_0.02% | 1.2208 | +9.03 | -0.39 | +0.77 | **+1.16** | 1.5814 | 0.3772 | +10.56 |

## CONTENTION LEDGER

| class | count | total R | Avg R |
|---|---|---|---|
| `d2_additive` | 20 | +3.20 | 0.1599 |
| `d2_displaces_t3` | 0 | +0.00 | — |
| `d2_displaces_a4` | 0 | +0.00 | — |
| `d2_blocks_later_t3` | 9 | +10.66 | 1.1846 |
| `d2_blocks_later_a4` | 0 | +0.00 | — |
| `baseline_blocks_d2_open_position` | 28 | -4.00 | -0.1429 |
| `baseline_blocks_d2_pending_order` | 0 | +0.00 | — |
| `baseline_trade_lost_other` | 0 | +0.00 | — |

## POLICY 1 / POLICY 2 RESULTS

| | frozen Core | Policy 1 (Phase D ordering) | Policy 2 (frozen-Core priority) |
|---|---|---|---|
| total Core trades | 177 | 196 | 196 |
| trades/month | 9.70 | 10.74 | 10.74 |
| PF | 1.0812 | 1.1051 | 1.1051 |
| Avg R | +0.0634 | +0.0804 | +0.0804 |
| total R | +11.23 | +15.76 | +15.76 |
| Max DD % | 2.95 | 3.19 | 3.19 |
| longest losing streak | 10 | 11 | 11 |
| D2 trades retained | — | 28 | 28 |
| baseline trades displaced | — | 9 | 9 |
| incremental PF | — | 1.8883 | 1.8883 |
| incremental Avg R | — | 0.5428 | 0.5428 |
| incremental total R | — | +15.20 | +15.20 |

### Why Policy 2 is identical to Policy 1

Not a no-op by accident — a measured fact. Of D2's **29 pending orders and 28 trades in
Policy 1, zero were created inside a baseline-busy interval**. The suppression mechanism
works (unit-tested both ways), but on this data it has nothing to suppress.

The reason is in the ledger: `d2_displaces_t3` is **0** and `d2_blocks_later_t3` is **9**.
D2 never takes a slot the frozen Core was using at that moment. It opens in a genuine gap
and is *still holding* when the T3 setup arrives later. Policy 2, as specified, gates D2's
**entry**; the cost comes from its **holding**. So the policy the brief defined cannot
address the contention it was meant to test. That is the answer to the arbitration
question, not a failure to run it.

## PHASE E DECISION: **REJECT D2**

### Reason for decision

The contention ledger dissolves the headline. D2's incremental stream is +15.20R at PF
1.89, but decomposed:

* **20 genuinely additive D2 trades are worth +3.20R in total, at Avg R +0.160** — barely
  above the Core's own +0.063 and nowhere near the +0.543 headline.
* The remaining apparent gain is the mirror image of **9 blocked T3 trades worth +10.66R
  at Avg R +1.185**. D2 is not adding +0.54R trades; it is adding +0.16R trades and
  removing +1.19R ones, netting +4.54R.

Measured at the level that nets displacement out — Core versus Core — the picture inverts:

* **Rolling 3M: 6 improved, 9 degraded, 2 neutral, median −0.52R.**
* **Rolling 6M: 6 improved, 8 degraded, 0 neutral, median −0.52R.**

In the majority of rolling windows, adding D2 makes the Core worse. An incremental PF of
1.89 and a negative median Core delta are not in conflict: the first counts only what was
added, the second also counts what was lost.

Five of the eight acceptance conditions fail:

| condition | result |
|---|---|
| positive expectancy across multiple periods | marginal — 2 of 4 subperiods positive (2024 H1 +2.00R, 2025 H1 +4.20R; 2024 H2 −1.66R) |
| rolling behaviour not one isolated cluster | **FAIL** — median −0.52R, more degraded than improved windows in both lengths |
| no single period carrying the result | **FAIL** — leave-one-month-out is clean, but removing 2025 H1 takes +15.20R to **+3.00R** |
| moderate execution stress keeps contribution positive | **FAIL** — at 0.05 % slippage D2 standalone is PF 0.9768 and the net contribution is **−3.39R** |
| small parameter perturbations do not collapse it | **FAIL** — body 0.70 → 0.65 takes the net contribution from +4.54R to **−0.46R**, a sign change from one 0.05 step |
| integration not dependent on sacrificing strong T3 trades | **FAIL** — the entire net gain is the difference between +0.16R additions and +1.19R removals, and the specified remedy policy provably cannot change it |
| Core drawdown acceptable | pass — 2.95 % → 3.19 % |
| incremental MFE/MAE coherent | pass — 2.03R against 0.93R |

This is **REJECT**, not INSUFFICIENT EVIDENCE. The sample is small, but the failures are
structural rather than statistical: a one-step parameter change flips the sign, the Core
delta is negative in the median window, and the integration cost is a permanent property
of sharing one position slot with T3 in the same bearish regime — which is exactly what
the Phase D opportunity map predicted when it showed T3 entering in bearish H1 trend 83
times out of 84.

Two findings are worth keeping. The block bootstrap is honest here — P(total R ≤ 0) of
0.041 to 0.077 depending on block length, with the 5th percentile of total R sitting at
0.00 at the primary block — and it is the first bootstrap in this research that did not
merely restate a foregone conclusion. And the slope arm at 0.10 produced the best numbers
of any arm (+8.65R net, 43 added trades); it is **not** a recommendation, because Phase C
showed exactly what an isolated best value is worth, but it does indicate the H1 slope
gate, not the body gate, is where a short-side pullback family's opportunity is.

D2 is not carried forward. No replacement family search was started.

## Verification

* D2 implementation hash verified unchanged at the start of the run.
* Frozen fingerprints unchanged: A4 `55fedf85…`, T3 `4c4ab845…`, Core `631374d5…`.
* Each sensitivity arm asserted to move exactly one threshold, with every other frozen A4
  field equal; the RSI arm additionally asserted to preserve the band's 22-point width.
* Policy 2 asserted to suppress a D2 signal on a baseline-busy bar, to pass one through on
  an idle bar, and never to suppress a frozen child's signal.
* Machine-readable results: `reports/research/core_v2_phase_e.json`.
