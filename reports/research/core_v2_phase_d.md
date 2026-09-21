# BTC Core V2 — Phase D: complementary setup family discovery

Phases A–C closed parameter-level work on the frozen children: every body relaxation,
timing change and lookback change was rejected. Phase D stops adjusting A4 and T3 and
looks for an additive third source of trades. DEVELOPMENT only; the holdout was not read.

| | |
|---|---|
| DEVELOPMENT | 2023-11-10 23:15 UTC → 2025-06-30 23:45 UTC |
| HOLDOUT | 2025-07-01 00:00 UTC → 2026-09-20 07:15 UTC |
| **Holdout touched** | **NO** |
| Dataset | `data/exness/btc/phase_r1/processed/btcusdm_M15.csv`, fingerprint `80735a2c…` verified per arm |
| Fixed | 3R reward, structural stop, one position at a time, signals on closed M15 bars, confirmed H1 only |

## PRIOR RESEARCH AUDIT

Eight BTC families have already been closed as REJECTED. The audit found two things that
changed what was worth testing.

**The frozen T3 source already contains two unused engines.** `btc_v3_t3_breakout_short.py`
ships a complete long trend-breakout branch behind `longs_enabled=False` and a complete
range-sweep branch behind `range_enabled=False`. `btc_v3_regime_adaptive.py` is the same
architecture with both switched on. So two of the three briefed candidates did not need
inventing — they needed enabling, which also means a negative result is a fact about the
market rather than about new code.

**Every prior rejection was established on different data and different costs.**

| family | status | rejection basis | data | spread | period |
|---|---|---|---|---|---|
| PB1 shallow pullback | REJECTED | cross-regime robustness failure (810 trades, PF 0.927) | Bitstamp | $10 constant | 2021–2023 |
| PB2 reclaim LONG | REJECTED | 29 trades, negative in 2022 | Bitstamp | $10 constant | 2021–2023 |
| PB2 reclaim SHORT | REJECTED | 14 trades, no stable expectancy | Bitstamp | $10 constant | 2021–2023 |
| PB3 pivot acceptance LONG | REJECTED | 48 trades, negative 2022 and 2023 | Bitstamp | $10 constant | 2021–2023 |
| V3-M1 momentum expansion (compression→expansion) | REJECTED | historical V3 branch | Bitstamp | $10 constant | 2021–2024 |
| V3-MR1 intraday overshoot | REJECTED | historical V3 branch | Bitstamp | $10 constant | 2021–2024 |
| V3-R2 range liquidity sweep | REJECTED | historical V3 branch | Bitstamp | $10 constant | 2021–2024 |
| V3 regime adaptive (longs + range on) | not registered | superseded by frozen T3 | Bitstamp | $10 constant | 2021–2024 |

Current DEVELOPMENT is Exness BTCUSDm at the real per-bar spread — median $21.60, about
2.16× the $10 those rejections assumed — over a later, largely non-overlapping period.
That is materially different, but it is not a reason to re-litigate eight closed families;
it is a reason not to treat any single one as permanently settled.

**Direct consequences for the briefed candidates.** Candidate 1 (T3 LONG mirror) and the
range engine are already implemented and unevaluated on this data. Candidate 3 as briefed
— independent compression → expansion breakout — is **already implemented and REJECTED**
as `BTC_V3_M1_MOMENTUM_EXPANSION`. The opportunity map below identified a better third
family, and it is substituted with that justification.

## OPPORTUNITY MAP

57,403 completed DEVELOPMENT M15 bars. The frozen Core holds a position on **5,767 of them (10.047 %)**.

### H1 regime

| bucket | bars | % of bars | bars inside a Core position | % of bucket covered |
|---|---|---|---|---|
| TRANSITION | 28,879 | 50.31 | 2,212 | 7.66 |
| NEUTRAL_RANGE | 11,504 | 20.04 | 0 | 0.00 |
| BULLISH_TREND | 10,192 | 17.75 | 1,897 | 18.61 |
| BEARISH_TREND | 6,769 | 11.79 | 1,658 | 24.49 |
| WARMUP | 59 | 0.10 | 0 | 0.00 |

### Volatility

| bucket | bars | % of bars |
|---|---|---|
| NORMAL_VOL | 24,771 | 43.15 |
| HIGH_VOL_EXPANSION | 16,399 | 28.57 |
| LOW_VOL_COMPRESSION | 16,100 | 28.05 |
| WARMUP | 133 | 0.23 |

### Candidate events

| event | bars | % of bars | inside a Core position | % covered |
|---|---|---|---|---|
| PULLBACK_TOUCH_LONG | 15,166 | 26.42 | 1,700 | 11.21 |
| PULLBACK_TOUCH_SHORT | 13,359 | 23.27 | 1,105 | 8.27 |
| BREAKOUT_UP | 6,399 | 11.15 | 639 | 9.99 |
| BREAKDOWN | 5,753 | 10.02 | 635 | 11.04 |
| FAILED_BREAKOUT_RECLAIM_DOWN | 2,007 | 3.50 | 194 | 9.67 |
| FAILED_BREAKDOWN_RECLAIM_UP | 1,931 | 3.36 | 223 | 11.55 |

### Where the frozen children actually enter

| setup | regime at entry | entries |
|---|---|---|
| BTC_V3_A4_PULLBACK_LONG_FROZEN | BULLISH_TREND | 86 |
| BTC_V3_A4_PULLBACK_LONG_FROZEN | TRANSITION | 7 |
| BTC_V3_T3_BREAKOUT_SHORT_FROZEN | BEARISH_TREND | 83 |
| BTC_V3_T3_BREAKOUT_SHORT_FROZEN | TRANSITION | 1 |

## STANDALONE METRICS

| family | setups | orders | fills | closed | trades/mo | WR % | PF | Avg R | total R | PnL | Max DD % | losing streak |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| *Core baseline* | 207 | 207 | 177 | 177 | 9.70 | 26.55 | 1.0812 | +0.0634 | +11.23 | +265.83 | 2.95 | 10 |
| **D1 — T3 LONG mirror** | 139 | 139 | 126 | 125 | 6.85 | 24.00 | 0.9295 | -0.0511 | -6.39 | -166.30 | 5.06 | 7 |
| **D2 — A4 SHORT mirror** | 64 | 64 | 56 | 56 | 3.07 | 30.36 | 1.2819 | +0.2000 | +11.20 | +276.14 | 1.49 | 6 |
| **D3 — T3 RANGE sweep** | 67 | 67 | 58 | 58 | 3.18 | 17.24 | 0.6423 | -0.2790 | -16.18 | -402.22 | 3.82 | 12 |

### Standalone by subperiod

| family | period | trades | PF | Avg R | total R | Max DD % |
|---|---|---|---|---|---|---|
| D1 | 2023 partial | 11 | 1.109 | 0.0839 | +0.92 | 0.75 |
| D1 | 2024 H1 | 33 | 0.409 | -0.5252 | -17.33 | 4.29 |
| D1 | 2024 H2 | 44 | 1.386 | 0.2688 | +11.83 | 1.76 |
| D1 | 2025 H1 | 37 | 0.936 | -0.0490 | -1.81 | 2.74 |
| D2 | 2023 partial | 0 | — | — | +0.00 | 0.00 |
| D2 | 2024 H1 | 21 | 0.933 | -0.0476 | -1.00 | 1.50 |
| D2 | 2024 H2 | 12 | 1.494 | 0.3333 | +4.00 | 0.75 |
| D2 | 2025 H1 | 23 | 1.538 | 0.3564 | +8.20 | 0.99 |
| D3 | 2023 partial | 3 | 1.480 | 0.3276 | +0.98 | 0.25 |
| D3 | 2024 H1 | 12 | 0.617 | -0.3261 | -3.91 | 1.30 |
| D3 | 2024 H2 | 23 | 0.465 | -0.4445 | -10.22 | 2.74 |
| D3 | 2025 H1 | 20 | 0.779 | -0.1514 | -3.03 | 2.46 |

## CORE + FAMILY

| composition | closed | trades/mo | WR % | PF | Avg R | total R | PnL | Max DD % | losing streak |
|---|---|---|---|---|---|---|---|---|---|
| *Core baseline* | 177 | 9.70 | 26.55 | 1.0812 | +0.0634 | +11.23 | +265.83 | 2.95 | 10 |
| **Core + D1** | 241 | 13.21 | 26.56 | 1.0748 | +0.0582 | +14.03 | +332.29 | 3.31 | 11 |
| **Core + D2** | 196 | 10.74 | 27.04 | 1.1051 | +0.0804 | +15.76 | +379.66 | 3.19 | 11 |
| **Core + D3** | 234 | 12.83 | 24.36 | 0.9731 | -0.0169 | -3.96 | -116.85 | 3.91 | 14 |

## INCREMENTAL CORE CONTRIBUTION

| family | new trades added | by the candidate | baseline displaced | displaced from | net trades | net trades/mo | inc WR % | inc PF | inc Avg R | inc total R | MFE R | MAE R | net ΔR | ΔDD % |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **D1** | 77 | 72 | 13 | LONG:13 | +64 | +3.26 | 25.97 | 1.0295 | 0.0227 | +1.74 | 1.398 | 1.033 | +2.81 | +0.35 |
| **D2** | 28 | 28 | 9 | SHORT:9 | +19 | +0.97 | 39.29 | 1.8883 | 0.5428 | +15.20 | 2.034 | 0.928 | +4.54 | +0.24 |
| **D3** | 58 | 58 | 1 | SHORT:1 | +57 | +2.90 | 17.24 | 0.6436 | -0.2790 | -16.18 | 1.116 | 1.281 | -15.18 | +0.96 |

### Incremental net R by subperiod

| family | period | added | added R | displaced | displaced R | net R |
|---|---|---|---|---|---|---|
| D1 | 2023 partial | 8 | +3.94 | 0 | +0.00 | **+3.94** |
| D1 | 2024 H1 | 17 | -9.21 | 3 | -3.01 | **-6.19** |
| D1 | 2024 H2 | 24 | +3.86 | 3 | -3.00 | **+6.86** |
| D1 | 2025 H1 | 28 | +3.15 | 7 | +4.95 | **-1.80** |
| D2 | 2023 partial | 0 | +0.00 | 0 | +0.00 | **+0.00** |
| D2 | 2024 H1 | 10 | +2.00 | 4 | +0.00 | **+2.00** |
| D2 | 2024 H2 | 7 | +1.00 | 1 | +2.66 | **-1.66** |
| D2 | 2025 H1 | 11 | +12.20 | 4 | +8.00 | **+4.20** |
| D3 | 2023 partial | 3 | +0.98 | 0 | +0.00 | **+0.98** |
| D3 | 2024 H1 | 12 | -3.91 | 0 | +0.00 | **-3.91** |
| D3 | 2024 H2 | 23 | -10.22 | 0 | +0.00 | **-10.22** |
| D3 | 2025 H1 | 20 | -3.03 | 1 | -1.00 | **-2.03** |

### Incremental monthly concentration

| family | months | positive | negative | best month | worst month |
|---|---|---|---|---|---|
| D1 | 19 | 9 | 10 | 2024-11 +8.00R | 2024-03 -7.13R |
| D2 | 11 | 7 | 4 | 2025-02 +5.00R | 2024-01 -3.00R |
| D3 | 16 | 4 | 11 | 2024-11 +4.98R | 2024-10 -5.21R |

## COMPARISON TABLE

| | Core baseline | + D1 | + D2 | + D3 |
|---|---|---|---|---|
| closed trades | 177 | 241 | 196 | 234 |
| trades/month | 9.70 | 13.21 | 10.74 | 12.83 |
| PF | 1.0812 | 1.0748 | 1.1051 | 0.9731 |
| Avg R | +0.0634 | +0.0582 | +0.0804 | -0.0169 |
| total R | +11.23 | +14.03 | +15.76 | -3.96 |
| Max DD % | 2.95 | 3.31 | 3.19 | 3.91 |
| incremental PF | — | 1.0295 | 1.8883 | 0.6436 |
| incremental trades/month | — | 3.92 | 1.43 | 2.95 |

### Why the third family was substituted

The briefed third candidate was compression → expansion breakout. That is `V3-M1`, already
built and already rejected. The map shows a better target: **NEUTRAL_RANGE is 20.0 % of all
development bars and has literally zero Core coverage** — the largest genuinely uncontested
pool in the dataset. The frozen T3 source already contains a range-sweep engine gated on
`separation_atr <= 0.80`, which is exactly that bucket's definition. So D3 tests the empty
pool with code that already exists, rather than re-running a closed family.

The map also confirms the two frozen children are regime specialists with no overlap: A4
enters in bullish H1 trend 86 times of 93, T3 in bearish 83 of 84. That is why they never
contend with each other, and why a third family that shares a regime with one of them will
contend.

## CANDIDATE FAMILY 1 — T3 LONG mirror · **REJECT**

The frozen T3 trend-breakout structure run long. No new decision logic.

Standalone it loses money: 125 trades, **PF 0.9295, Avg R −0.0511, −6.39R**, max drawdown
5.06 % — the worst drawdown of anything measured in Phases A–D. Its subperiods do not
agree with each other at all: 2024 H1 PF 0.409 (−17.33R), 2024 H2 PF 1.386 (+11.83R).

Inside Core it adds 77 trades at **incremental PF 1.0295 and Avg R +0.0227** — 1.74R across
nineteen months, with nine positive and ten negative months and a best month (+8.00R) more
than four times the entire total. Net subperiod contribution alternates sign: +3.94, −6.19,
+6.86, −1.80R. It also displaces 13 A4 trades.

**Symmetry is not profitable here.** The brief said not to assume it; the measurement says
the long side of T3's structure is a different and worse business than the short side.

## CANDIDATE FAMILY 2 — A4 SHORT mirror · **CARRY TO PHASE E, with a stated shortfall**

A4's trend/pullback/confirmation structure mirrored to the short side — the one family
that needed real implementation, mirrored statement for statement, with the RSI band
reflected about 50 (A4's 48–70 becomes 30–52) and no value chosen by search.

Standalone it is the best-quality component measured anywhere in this research:
**56 trades, PF 1.2819, Avg R +0.2000, +11.20R, max drawdown 1.49 %** — a higher profit
factor than either frozen child (A4 1.0425, T3 1.1265) at a third of the drawdown. Its
subperiods improve over time: 2024 H1 PF 0.933, 2024 H2 PF 1.494, 2025 H1 PF 1.538.

Inside Core it adds 28 trades at **incremental PF 1.8883, Avg R +0.5428, +15.20R**, with
mean MFE 2.03R against mean MAE 0.93R, spread over eleven months of which seven are
positive and whose best month is 32.9 % of the total. Core total R rises +11.23 → +15.76
and PF 1.0812 → 1.1051.

Two things are not good, and both are stated rather than smoothed over:

* **Frequency is 1.43 incremental trades/month, far below the ≥4/month guideline.** The
  binding constraint is contention, not the edge: D2 makes 3.07 trades/month standalone
  and loses more than half of them to the single global position. It shares the bearish
  H1 regime with T3, so it is a quality addition, not the frequency answer.
* **It displaces 9 T3 trades that averaged +1.185R each** — stronger per trade than the
  +0.543R it adds. It adds three times as many trades as it displaces, so the net is
  +4.54R, but this is the one criterion it genuinely fails.

## CANDIDATE FAMILY 3 — T3 RANGE sweep · **REJECT**

The frozen T3 range-sweep engine, both directions, aimed at the 20 %-of-bars pool the Core
never touches.

It does not work: 58 trades, **PF 0.6423, Avg R −0.2790, −16.18R**, win rate 17.24 %, and a
12-trade losing streak. Incremental PF 0.6436 with mean MFE 1.12R against mean MAE 1.28R —
the admitted trades move against the position further than for it. Negative in three of
four subperiods and in eleven of sixteen months. It displaces almost nothing (1 trade), so
this is a clean read: **the uncontested range pool is real, but this sweep design does not
extract from it.** That is worth knowing — the pool stays open for a different mechanism.

## PHASE D DECISION

**Carry forward: D2, the A4 SHORT mirror. Reject D1 and D3.**

D2 is the only family whose incremental trades have clearly positive expectancy, and it is
not marginal: incremental PF 1.89 and Avg R +0.54 against bars of 1.10 and 0, with coherent
excursions, no single-month dependency, and its two best subperiods being the two most
recent. The brief says higher quality is preferred over barely meeting the numbers, and
this is the only candidate that clears any bar by a wide margin.

It is carried to Phase E as a **stability question, not a promotion**, with the shortfall
recorded explicitly: at +0.97 net trades/month it moves Core from 9.70 to 10.74
trades/month and does not by itself approach the 24–30/month objective. Phase E has to
answer whether the edge survives the Phase C standard — rolling windows, leave-one-out,
execution stress, break-definition sensitivity — and whether its displacement of stronger
T3 trades is a persistent cost or an artifact of 9 observations.

D1 and D3 are rejected outright and should not be revisited on this data. D1 loses money
standalone and contributes noise inside Core; D3 loses money decisively. Neither failure is
a sample-size question.

**One caution carried forward from Phase C.** D2's incremental stream is 28 trades. That is
more than the 12 that failed in Phase C, spread over more months, and improving rather than
concentrated in an early cluster — but it is still a small sample, and Phase E exists
precisely to find out whether it behaves like the lookback-4 lead did.

## Verification

* Frozen fingerprints unchanged: A4 `55fedf85…`, T3 `4c4ab845…`, Core `631374d5…`.
* D1 and D3 asserted equal to the frozen T3 parameters field by field except the enable
  flags; D2 asserted equal to the frozen A4 parameter object.
* Each family carries a distinct setup id, and the frozen id is restored after every bar —
  a collision would let one child cancel another's pending order.
* Trades the candidate does not displace are the same *decision* as baseline. Quantity and
  PnL legitimately differ because sizing is a percentage of the running balance, which is
  why R, not PnL, is the comparison used throughout.
* Machine-readable results: `reports/research/core_v2_phase_d.json`,
  `reports/research/core_v2_phase_d_opportunity_map.json`.
