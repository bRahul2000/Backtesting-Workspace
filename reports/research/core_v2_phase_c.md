# BTC Core V2 — Phase C: T3 lookback-4 stability study

Phase B found one arm whose newly admitted trades had clearly positive expectancy —
T3 structure lookback 4 against the frozen 5 — and declined to promote it on stability
grounds. Phase C exists only to settle that, and is built so a null result is a real
outcome rather than a failure.

## DEVELOPMENT SPLIT CONFIRMATION

| | |
|---|---|
| DEVELOPMENT | 2023-11-10 23:15 UTC → 2025-06-30 23:45 UTC |
| HOLDOUT | 2025-07-01 00:00 UTC → 2026-09-20 07:15 UTC |
| **Holdout touched** | **NO** — every run is refused if its end date reaches `HOLDOUT_START`; no rolling window ends past `DEVELOPMENT_END` |
| Dataset | `data/exness/btc/phase_r1/processed/btcusdm_M15.csv`, fingerprint `80735a2c…` re-verified before every arm |
| Carried from Phase A/B | A4 body 0.70, T3 body 0.70, reward multiple 3R — all unchanged |

Full-development reference: L5 84 trades / PF 1.1265 / +7.93R; L4 88 trades / PF 1.1916 /
+12.27R; 12 admitted (+16.00R), 8 withdrawn (+11.66R), net +4.34R.

### Method note

Subperiods and rolling windows **slice the trades of one continuous DEVELOPMENT run**
rather than re-running the strategy on truncated data. Re-running would give each window
its own warmup and cold-start state, so a difference between windows could come from the
warmup rather than from the market. Slicing measures what the strategy actually did.

Slice drawdown walks the sliced PnL stream from the run's starting balance. It is
approximate for a slice, because position sizes were set by the running balance of the
full run; it is comparable between the two arms over the same slice, which is the only
use it is put to.

## T3 L4 vs L5 SUBPERIOD TABLE

| period | L5 tr | L5 PF | L5 Avg R | L5 total R | L5 DD % | L5 streak | L4 tr | L4 PF | L4 Avg R | L4 total R | L4 DD % | L4 streak | admitted | admitted R | withdrawn | withdrawn R | net ΔR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2023 partial | 2 | 0.0000 | -1.0000 | -2.00 | 0.50 | 2 | 2 | 0.0000 | -1.0000 | -2.00 | 0.50 | 2 | 0 | +0.00 | 0 | +0.00 | **+0.00** |
| 2024 H1 | 27 | 1.0525 | 0.0425 | +1.15 | 1.73 | 7 | 27 | 1.2664 | 0.1906 | +5.15 | 1.49 | 6 | 5 | +7.00 | 5 | +3.00 | **+4.00** |
| 2024 H2 | 23 | 1.2962 | 0.2081 | +4.79 | 1.46 | 6 | 26 | 1.3372 | 0.2356 | +6.13 | 1.50 | 6 | 5 | +7.00 | 2 | +5.66 | **+1.34** |
| 2025 H1 | 32 | 1.1710 | 0.1250 | +4.00 | 1.98 | 8 | 33 | 1.1215 | 0.0909 | +3.00 | 1.98 | 8 | 2 | +2.00 | 1 | +3.00 | **-1.00** |
| *(year 2023)* | 2 | 0.0000 | -1.0000 | -2.00 | 0.50 | 2 | 2 | 0.0000 | -1.0000 | -2.00 | 0.50 | 2 | 0 | +0.00 | 0 | +0.00 | **+0.00** |
| *(year 2024)* | 50 | 1.1609 | 0.1187 | +5.93 | 1.73 | 7 | 53 | 1.3011 | 0.2127 | +11.27 | 1.49 | 6 | 10 | +14.00 | 7 | +8.66 | **+5.34** |
| *(year 2025)* | 32 | 1.1710 | 0.1250 | +4.00 | 1.98 | 8 | 33 | 1.1215 | 0.0909 | +3.00 | 1.98 | 8 | 2 | +2.00 | 1 | +3.00 | **-1.00** |

## ROLLING 3M RESULTS

17 windows, 3-month length, 1-month step.

| window | L5 tr | L5 PF | L5 total R | L4 tr | L4 PF | L4 total R | Δ trades | Δ total R | admitted | admitted expectancy |
|---|---|---|---|---|---|---|---|---|---|---|
| 2023-11-10→2024-02-10 | 8 | 0.995 | -0.00 | 8 | 0.995 | -0.00 | +0 | **+0.00** | 0 | — |
| 2023-12-10→2024-03-10 | 7 | 1.193 | +1.00 | 7 | 1.193 | +1.00 | +0 | **+0.00** | 0 | — |
| 2024-01-10→2024-04-10 | 10 | 0.749 | -2.00 | 9 | 0.855 | -1.00 | -1 | **+1.00** | 1 | -1.000 |
| 2024-02-10→2024-05-10 | 11 | 1.120 | +1.00 | 10 | 1.280 | +2.00 | -1 | **+1.00** | 4 | 1.000 |
| 2024-03-10→2024-06-10 | 12 | 0.995 | -0.00 | 11 | 1.120 | +1.00 | -1 | **+1.00** | 4 | 1.000 |
| 2024-04-10→2024-07-10 | 23 | 1.062 | +1.15 | 25 | 1.414 | +7.15 | +2 | **+6.00** | 5 | 2.200 |
| 2024-05-10→2024-08-10 | 19 | 1.078 | +1.15 | 22 | 1.408 | +6.15 | +3 | **+5.00** | 3 | 1.667 |
| 2024-06-10→2024-09-10 | 23 | 1.299 | +4.81 | 27 | 1.506 | +9.15 | +4 | **+4.34** | 5 | 1.400 |
| 2024-07-10→2024-10-10 | 14 | 1.641 | +5.79 | 16 | 1.372 | +4.13 | +2 | **-1.66** | 3 | 0.333 |
| 2024-08-10→2024-11-10 | 12 | 0.971 | -0.21 | 13 | 0.907 | -0.87 | +1 | **-0.66** | 2 | 1.000 |
| 2024-09-10→2024-12-10 | 7 | 0.507 | -2.87 | 7 | 0.507 | -2.87 | +0 | **+0.00** | 0 | — |
| 2024-10-10→2025-01-10 | 6 | 0.604 | -2.00 | 6 | 0.610 | -2.00 | +0 | **+0.00** | 1 | 3.000 |
| 2024-11-10→2025-02-10 | 14 | 0.818 | -2.00 | 14 | 0.822 | -2.00 | +0 | **+0.00** | 1 | 3.000 |
| 2024-12-10→2025-03-10 | 21 | 1.499 | +7.00 | 22 | 1.400 | +6.00 | +1 | **-1.00** | 3 | 1.667 |
| 2025-01-10→2025-04-10 | 22 | 1.709 | +10.00 | 23 | 1.594 | +9.00 | +1 | **-1.00** | 2 | 1.000 |
| 2025-02-10→2025-05-10 | 13 | 2.557 | +11.00 | 14 | 2.236 | +10.00 | +1 | **-1.00** | 2 | 1.000 |
| 2025-03-10→2025-06-10 | 12 | 0.998 | -0.00 | 12 | 0.998 | -0.00 | +0 | **-0.00** | 0 | — |

**Summary** — improved 6, degraded 5, neutral 6 (|Δ| ≤ 0.33R). Worst -1.66R, median +0.00R, best +6.00R. 13 of 17 windows contain at least one admitted trade.

## ROLLING 6M RESULTS

14 windows, 6-month length, 1-month step.

| window | L5 tr | L5 PF | L5 total R | L4 tr | L4 PF | L4 total R | Δ trades | Δ total R | admitted | admitted expectancy |
|---|---|---|---|---|---|---|---|---|---|---|
| 2023-11-10→2024-05-10 | 19 | 1.066 | +1.00 | 18 | 1.148 | +2.00 | -1 | **+1.00** | 4 | 1.000 |
| 2023-12-10→2024-06-10 | 19 | 1.066 | +1.00 | 18 | 1.148 | +2.00 | -1 | **+1.00** | 4 | 1.000 |
| 2024-01-10→2024-07-10 | 33 | 0.961 | -0.85 | 34 | 1.251 | +6.15 | +1 | **+7.00** | 6 | 1.667 |
| 2024-02-10→2024-08-10 | 30 | 1.093 | +2.15 | 32 | 1.367 | +8.15 | +2 | **+6.00** | 7 | 1.286 |
| 2024-03-10→2024-09-10 | 35 | 1.189 | +4.81 | 38 | 1.387 | +10.15 | +3 | **+5.34** | 9 | 1.222 |
| 2024-04-10→2024-10-10 | 37 | 1.262 | +6.93 | 41 | 1.398 | +11.27 | +4 | **+4.34** | 8 | 1.500 |
| 2024-05-10→2024-11-10 | 31 | 1.036 | +0.93 | 35 | 1.207 | +5.27 | +4 | **+4.34** | 5 | 1.400 |
| 2024-06-10→2024-12-10 | 30 | 1.084 | +1.93 | 34 | 1.257 | +6.27 | +4 | **+4.34** | 5 | 1.400 |
| 2024-07-10→2025-01-10 | 20 | 1.269 | +3.79 | 22 | 1.135 | +2.13 | +2 | **-1.66** | 4 | 1.000 |
| 2024-08-10→2025-02-10 | 26 | 0.887 | -2.21 | 27 | 0.863 | -2.87 | +1 | **-0.66** | 3 | 1.667 |
| 2024-09-10→2025-03-10 | 28 | 1.203 | +4.13 | 29 | 1.144 | +3.13 | +1 | **-1.00** | 3 | 1.667 |
| 2024-10-10→2025-04-10 | 28 | 1.418 | +8.00 | 29 | 1.348 | +7.00 | +1 | **-1.00** | 3 | 1.667 |
| 2024-11-10→2025-05-10 | 27 | 1.498 | +9.00 | 28 | 1.420 | +8.00 | +1 | **-1.00** | 3 | 1.667 |
| 2024-12-10→2025-06-10 | 33 | 1.302 | +7.00 | 34 | 1.249 | +6.00 | +1 | **-1.00** | 3 | 1.667 |

**Summary** — improved 8, degraded 6, neutral 0 (|Δ| ≤ 0.33R). Worst -1.66R, median +1.00R, best +7.00R. 14 of 14 windows contain at least one admitted trade.

## BLOCK BOOTSTRAP RESULTS

Circular block bootstrap of the 12 admitted trades, 10,000 samples per block length, seed 20260921. Primary block length **3**.

| block | metric | p5 | p25 | median | p75 | p95 | tail probability |
|---|---|---|---|---|---|---|---|
| 1 | total_r | 4.000 | 12.000 | 16.000 | 20.000 | 28.000 | P(total R ≤ 0) = 0.0079 |
| 1 | average_r | 0.333 | 1.000 | 1.333 | 1.667 | 2.333 | P(Avg R ≤ 0) = 0.0079 |
| 1 | profit_factor | 1.500 | 3.000 | 4.200 | 6.000 | 15.000 | P(PF ≤ 1) = 0.0161 |
| 2 | total_r | 4.000 | 12.000 | 16.000 | 20.000 | 28.000 | P(total R ≤ 0) = 0.0057 |
| 2 | average_r | 0.333 | 1.000 | 1.333 | 1.667 | 2.333 | P(Avg R ≤ 0) = 0.0057 |
| 2 | profit_factor | 1.500 | 3.000 | 4.200 | 6.000 | 15.000 | P(PF ≤ 1) = 0.0125 |
| 3 **(primary)** | total_r | 8.000 | 12.000 | 16.000 | 20.000 | 24.000 | P(total R ≤ 0) = 0.0000 |
| 3 | average_r | 0.667 | 1.000 | 1.333 | 1.667 | 2.000 | P(Avg R ≤ 0) = 0.0000 |
| 3 | profit_factor | 2.143 | 3.000 | 4.200 | 6.000 | 9.000 | P(PF ≤ 1) = 0.0000 |
| 4 | total_r | 8.000 | 12.000 | 16.000 | 20.000 | 24.000 | P(total R ≤ 0) = 0.0000 |
| 4 | average_r | 0.667 | 1.000 | 1.333 | 1.667 | 2.000 | P(Avg R ≤ 0) = 0.0000 |
| 4 | profit_factor | 2.143 | 3.000 | 4.200 | 6.000 | 9.000 | P(PF ≤ 1) = 0.0000 |

## LEAVE-ONE-MONTH-OUT RESULTS

| month dropped | trades removed | trades remaining | PF | Avg R | total R |
|---|---|---|---|---|---|
| 2024-03 | 1 | 11 | 5.236 | 1.545 | +17.00 |
| 2024-04 | 3 | 9 | 3.749 | 1.222 | +11.00 |
| 2024-06 | 1 | 11 | 3.595 | 1.182 | +13.00 |
| 2024-07 | 1 | 11 | 3.595 | 1.182 | +13.00 |
| 2024-08 | 3 | 9 | 6.008 | 1.667 | +15.00 |
| 2024-12 | 1 | 11 | 3.589 | 1.182 | +13.00 |
| 2025-02 | 1 | 11 | 3.602 | 1.182 | +13.00 |
| 2025-03 | 1 | 11 | 5.249 | 1.545 | +17.00 |

## LEAVE-2024-OUT RESULT

| year dropped | trades removed | trades remaining | PF | Avg R | total R |
|---|---|---|---|---|---|
| 2023 | 0 | 12 | 4.195 | 1.333 | **+16.00** |
| 2024 **←** | 10 | 2 | 2.956 | 1.000 | **+2.00** |
| 2025 | 2 | 10 | 4.507 | 1.400 | **+14.00** |

## BREAK-DEFINITION SENSITIVITY

| definition | L5 tr | L5 PF | L5 total R | L4 tr | L4 PF | L4 total R | admitted | admitted PF | admitted Avg R | admitted total R | net ΔR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| LOOSER_1_TICK | 84 | 1.1265 | +7.93 | 88 | 1.1916 | +12.27 | 12 | 4.1954 | 1.3333 | +16.00 | **+4.34** |
| **FROZEN** | 84 | 1.1265 | +7.93 | 88 | 1.1916 | +12.27 | 12 | 4.1954 | 1.3333 | +16.00 | **+4.34** |
| STRICT_1_TICK | 84 | 1.1265 | +7.93 | 88 | 1.1916 | +12.27 | 12 | 4.1954 | 1.3333 | +16.00 | **+4.34** |
| STRICT_0P01_ATR | 83 | 1.0769 | +4.93 | 87 | 1.2112 | +13.27 | 12 | 6.0079 | 1.6667 | +20.00 | **+8.34** |
| STRICT_0P02_ATR | 83 | 1.0111 | +0.93 | 87 | 1.1433 | +9.27 | 12 | 6.0004 | 1.6667 | +20.00 | **+8.34** |
| STRICT_0P05_ATR | 79 | 1.0119 | +0.93 | 82 | 1.1703 | +10.27 | 11 | 8.0226 | 1.9091 | +21.00 | **+9.34** |

## EXECUTION STRESS

| stress | L5 tr | L5 PF | L5 total R | L5 PnL | L4 tr | L4 PF | L4 total R | L4 PnL | admitted Avg R | admitted total R | net ΔR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| NATIVE | 84 | 1.1265 | +7.93 | +192.19 | 88 | 1.1916 | +12.27 | +302.13 | 1.3333 | +16.00 | **+4.34** |
| SPREAD_x1.10 | 84 | 1.1265 | +7.93 | +192.19 | 88 | 1.1916 | +12.27 | +302.13 | 1.3333 | +16.00 | **+4.34** |
| SPREAD_x1.20 | 84 | 1.1265 | +7.93 | +192.19 | 88 | 1.1916 | +12.27 | +302.13 | 1.3333 | +16.00 | **+4.34** |
| SPREAD_x3.00_SEVERE | 85 | 0.9242 | -4.62 | -122.33 | 91 | 0.9008 | -6.62 | -172.64 | 0.3333 | +4.00 | **-2.00** |
| SLIPPAGE_0.02% | 83 | 1.0397 | +2.68 | +60.53 | 87 | 1.0986 | +6.50 | +156.03 | 1.2695 | +15.23 | **+3.82** |
| SLIPPAGE_0.05% | 83 | 0.9301 | -4.11 | -108.20 | 87 | 1.0480 | +3.30 | +75.82 | 1.1885 | +14.26 | **+7.41** |
| SPREAD_x1.20_SLIP_0.02% | 83 | 1.0397 | +2.68 | +60.53 | 87 | 1.0986 | +6.50 | +156.03 | 1.2695 | +15.23 | **+3.82** |

## CORE L4 vs L5 IMPACT

| | L5 (baseline) | L4 (lead) |
|---|---|---|
| closed trades | 177 | 181 |
| long / short | 93 / 84 | 93 / 88 |
| trades/month | 9.70 | 9.92 |
| win rate % | 26.55 | 27.07 |
| profit factor | 1.0812 | 1.1126 |
| Avg R | +0.0634 | +0.0860 |
| total R | +11.23 | +15.56 |
| PnL | +265.83 | +376.16 |
| max drawdown % | 2.95 | 2.95 |
| longest losing streak | 10 | 10 |

Admitted 12 trades (+16.00R, Avg R 1.3333); withdrawn 8 (+11.66R); net **+4.34R** — identical to standalone.

**A4 trade set unchanged: True** (93 long trades, same entries, prices and R in both arms). Core is the exact union of the two standalone sets in both arms (0 trades lost to contention).

### Reading the bootstrap

The resampled distribution is narrow and strongly positive at every block length, and at
block 3 the estimated P(total R ≤ 0) is 0.000. **That number should not be believed as
evidence for the lead.** The bootstrap resamples twelve trades of which seven are +3R
wins and five are −1R losses; any resampling of a 58 %-win-rate stream at 3:1 payoff is
positive almost surely. It describes sampling variability *within* this twelve-trade
sample and says nothing about whether the sample represents the process. Note too that
larger blocks *narrow* the distribution here rather than widening it, because blocking
preserves the alternating win/loss pattern — a sign the method has little to work with at
n = 12. No number of resamples repairs that.

Block length 3 is primary because n^(1/3) ≈ 2.3 for n = 12 and the largest observed
monthly cluster in the admitted stream is three trades; blocks of 1, 2 and 4 are reported
beside it so the choice is visible rather than assumed.

### Reading the break-definition sensitivity

The ±1-tick arms return results identical to FROZEN. That is expected, not a bug:
BTCUSDm quotes to two decimals, so `close < low` and `close < low − 0.01` differ only
when the close lands exactly one cent below the prior low, which effectively never
happens. The meaningful sensitivity is the ATR-buffer family, and there the admitted
stream holds up and even strengthens (+16R → +20R → +20R → +21R).

One definition from the brief does not map cleanly onto the frozen source. `close <=
prior low` cannot be expressed as a level shift, because no finite shift turns a strict
`<` into `<=`, and rewriting the comparison would mean reimplementing `evaluate_v3`. The
one-tick loosening is the narrowest equivalent the architecture supports, and it admits
the `close == prior low` case that `<=` was meant to probe. That is documented and used
in its place.

### Reading the execution stress

The +10 % and +20 % spread rows are *identical* to native. That is a property of the
strategy, not a dead knob: T3 is short-only with pending stop entries, so the entry fills
on the Bid candle at the trigger price and the exits sit at fixed stop/target levels —
spread only decides whether a level is touched inside a bar, and two to four dollars on a
~$60,000 instrument almost never changes that. The ×3.00 row is included precisely to
show the knob binds: it moves L5 from +7.93R to −4.62R and reverses the L4 advantage to
−2.00R. It is not a realistic cost assumption.

Under the realistic stresses that do bind — 0.02 % and 0.05 % slippage — the advantage
survives, at +3.82R and +7.41R net.

## PHASE C DECISION: **REJECT T3 LOOKBACK 4**

### Reason for decision

The brief sets a conjunctive standard. Two of its seven conditions fail, and they fail on
direct measurement rather than on judgement.

**It is essentially a 2024-only phenomenon.** Ten of the twelve admitted trades fall in
2024. Removing 2024 leaves **two trades and +2.00R**. There is almost no evidence for the
lead anywhere else in DEVELOPMENT.

**The rolling windows do not show repeated improvement; they show one cluster.** In the
6-month sweep, every one of the eight improving windows overlaps roughly 2024-03 to
2024-09, and **every one of the six windows that begins after 2024-07 degrades**, uniformly
at −0.66R to −1.66R. The 3-month sweep has a median delta of exactly +0.00R with 6
improved, 5 degraded and 6 neutral. The 2025 H1 subperiod is net **−1.00R**: in the most
recent half-year of DEVELOPMENT, L4 is worse than the frozen baseline. This is the
single isolated cluster the brief said to reject, measured directly.

The conditions that *do* pass are real and worth recording, because they are what made
this lead worth a phase: no single month carries it (dropping any month leaves +11R to
+17R at PF 3.59–6.01); small break-definition changes do not reverse it and ATR buffers
strengthen it; realistic slippage stress does not eliminate it; and Core-level behaviour
is coherent, with the A4 trade set bit-identical between arms and zero contention loss.
The bootstrap's bounded downside is nominally a pass but is uninformative at n = 12 and
carries no weight here.

What remains is a twelve-trade effect confined to one six-month stretch, which also
withdraws eight baseline trades that were *better* per trade (+1.458 vs +1.333 Avg R), so
the +4.34R net is a small residual of two large opposing flows. That is the signature of
noise in a favourable regime, not of structure.

**REJECT** rather than INSUFFICIENT EVIDENCE: the outcome is not an absence of findings.
The study located the effect precisely — one contiguous cluster in 2024, with nothing
before it and a negative tail after it — and that located effect fails the standard.
The frozen lookback of 5 stands.

Nothing about this closes the question permanently. It says this lead cannot be promoted
on the evidence DEVELOPMENT contains. A larger-sample formulation of the same idea, or
more data, could revisit it — but the holdout is not that data and must stay unread.

## Verification

* Frozen fingerprints unchanged: A4 `55fedf85…`, T3 `4c4ab845…`, Core `631374d5…`.
* Lookback 5 with FROZEN break semantics reproduces the frozen T3 trade log exactly.
* Every break-definition arm asserted equal to the frozen parameters field by field, and
  the shift proven to move `trend_previous_low` and no other observation field.
* `spread_multiplier` proven to scale the broker spread (×3 gives exactly 3× the median
  effective spread and a materially worse result), so an unchanged +20 % row reads as
  insensitivity rather than as a broken knob.
* Machine-readable results: `reports/research/core_v2_phase_c.json`.
