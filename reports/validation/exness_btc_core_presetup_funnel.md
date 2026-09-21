# BTC V3 Core v1 [Frozen] — pre-setup diagnostic funnel

Diagnostic instrumentation only. No frozen decision logic changed; `strategies/btc_v3_core_v1.py`,
`btc_v3_a4_pullback_long.py`, `btc_v3_t3_breakout_short.py` and `btc_v3_l2_trend_pullback_long.py`
are byte-for-byte unchanged. No parameter was optimised or proposed for change.

Dataset: `data/exness/btc/phase_r1/processed/btcusdm_M15.csv`
(Exness BTCUSDm M15, validated R1, fingerprint `80735a2c…`), full range, per-bar broker spread,
risk 0.25%, frozen Core defaults.

## How the instrumentation stays inert

`strategies/btc_v3_core_diagnostics.py` wraps the frozen Core and returns its action unchanged.
Every pass/fail decision is taken by calling the frozen strategy's **own pure predicates**
(`h1_bullish`, `_context_valid`, `_materially_below_ema50`, the A4 `confirmation_passes` overlay,
`classify_regime`, `evaluate_v3`). The hand-written decomposition is used only to *name* which
source condition failed. RSI and DMI are recomputed and discarded each bar by the frozen children,
so the observer runs a shadow indicator set fed the same candles in the same order rather than
re-calling `update` on the strategy's own instances, which would corrupt them.

Every bar, the observer compares its own verdict with the action the Core actually returned —
setup owner and both pending prices. Over the full dataset: **90,563 bars cross-checked,
0 signal mismatches, 0 price mismatches**.

## Baseline before vs after instrumentation

| | Before | After |
|---|---|---|
| Closed trades | 320 | 320 |
| Entries | 321 | 321 |
| Profit factor | 1.0214090139009886 | 1.0214090139009886 |
| Average R | 0.019219421763180713 | 0.019219421763180713 |
| Max drawdown | 3.6520839303374584 % | 3.6520839303374584 % |
| Trades / month | 9.808973699946497 | 9.808973699946497 |
| A4 LONG | 158 trades · PF 0.9619 · avg R −0.0239 | identical |
| T3 SHORT | 162 trades · PF 1.0811 · avg R +0.0613 | identical |

The full trade log — every entry, exit, price, stop, target, quantity, PnL, R and exit reason —
compares equal element by element between an instrumented run and a control run with the
observer removed from the registry.

## A4 pre-setup funnel (LONG) — 100,229 M15 bars

| Gate | Entered | Passed | Failed | Conv. from prior |
|---|---|---|---|---|
| Bars evaluated | 100,229 | 100,229 | 0 | — |
| Warmup / backtest window | 100,229 | 95,323 | 4,906 | 95.11 % |
| No pending order | 95,323 | 95,247 | 76 | 99.92 % |
| No open position | 95,247 | 85,657 | 9,590 | 89.93 % |
| UTC session open | 85,657 | 78,513 | 7,144 | 91.66 % |
| Daily trade cap | 78,513 | 78,467 | 46 | 99.94 % |
| Indicators seeded | 78,467 | 78,467 | 0 | 100.00 % |
| Confirmed H1 bullish | 78,467 | 29,224 | 49,243 | 37.24 % |
| M15 EMA20 > EMA50 | 29,224 | 16,666 | 12,558 | 57.03 % |
| ADX >= min_adx | 16,666 | 11,339 | 5,327 | 68.04 % |
| Normalized H1 slope | 11,339 | 8,152 | 3,187 | 71.89 % |
| Close not far below EMA50 | 8,152 | 7,290 | 862 | 89.43 % |
| Pullback depth within limit | 7,290 | 7,090 | 200 | 97.26 % |
| Armed pullback to confirm | 7,090 | 4,677 | 2,413 | 65.97 % |
| **Confirmation candle** | **4,677** | **231** | **4,446** | **4.94 %** |
| Stop distance in band | 231 | 177 | 54 | 76.62 % |
| Setup detected / order created | 177 | 177 | 0 | 100.00 % |

Lifecycle: 177 orders created → 158 filled, 16 expired, 3 cancelled
(all three "V3-L2 bullish trend context invalidated.").

### A4 top 10 reject codes

| # | Code | Bars | % of all bars |
|---|---|---|---|
| 1 | A4_H1_EMA50_BELOW_EMA200 | 35,991 | 35.91 % |
| 2 | A4_M15_EMA20_BELOW_EMA50 | 12,558 | 12.53 % |
| 3 | A4_POSITION_OPEN | 9,590 | 9.57 % |
| 4 | A4_OUTSIDE_SESSION | 7,144 | 7.13 % |
| 5 | A4_H1_CLOSE_BELOW_EMA200 | 6,568 | 6.55 % |
| 6 | A4_H1_SEPARATION_BELOW_MIN | 6,204 | 6.19 % |
| 7 | A4_ADX_BELOW_MINIMUM | 5,327 | 5.31 % |
| 8 | A4_OUTSIDE_WARMUP_WINDOW | 4,906 | 4.89 % |
| 9 | A4_NORMALIZED_H1_SLOPE_BELOW_MIN | 3,187 | 3.18 % |
| 10 | A4_CONFIRM_CANDLE_NOT_BULLISH | 2,195 | 2.19 % |

Remaining A4 codes: CONFIRM_BODY_BELOW_MIN 2,014 · NO_PULLBACK_TOUCH 953 ·
CLOSE_MATERIALLY_BELOW_EMA50 862 · PULLBACK_STARTED_THIS_BAR 742 ·
H1_EMA200_SLOPE_NOT_POSITIVE 480 · STRUCTURE_BREAK_IMPULSE_BAR 386 ·
PULLBACK_START_TOO_DEEP 332 · PULLBACK_TOO_DEEP 200 · CONFIRM_RSI_ABOVE_BAND 94 ·
CONFIRM_NO_BREAK_OF_PREVIOUS_HIGH 90 · STOP_DISTANCE_TOO_WIDE 54 ·
BLOCKED_BY_T3_PENDING 51 · DAILY_TRADE_CAP 46 · CONFIRM_BODY_ABOVE_MAX 41 ·
BLOCKED_BY_OWN_PENDING 25 · CONFIRM_CLOSE_BELOW_EMA20 12.

## T3 pre-setup funnel (SHORT) — 100,229 M15 bars

| Gate | Entered | Passed | Failed | Conv. from prior |
|---|---|---|---|---|
| Bars evaluated | 100,229 | 100,229 | 0 | — |
| Warmup / backtest window | 100,229 | 95,323 | 4,906 | 95.11 % |
| UTC session open | 95,323 | 87,379 | 7,944 | 91.67 % |
| Daily trade cap | 87,379 | 87,238 | 141 | 99.84 % |
| No open position | 87,238 | 78,543 | 8,695 | 90.03 % |
| No pending order | 78,543 | 78,467 | 76 | 99.90 % |
| Indicators seeded | 78,467 | 78,467 | 0 | 100.00 % |
| H1 regime inputs present | 78,467 | 78,467 | 0 | 100.00 % |
| H1 separation >= min | 78,467 | 57,103 | 21,364 | 72.77 % |
| ADX >= min | 57,103 | 41,120 | 15,983 | 72.01 % |
| TREND SHORT alignment | 41,120 | 8,833 | 32,287 | 21.48 % |
| Shorts enabled | 8,833 | 8,833 | 0 | 100.00 % |
| **Break of 5-bar low** | **8,833** | **1,000** | **7,833** | **11.32 %** |
| Bearish candle | 1,000 | 1,000 | 0 | 100.00 % |
| **Body >= min** | **1,000** | **386** | **614** | **38.60 %** |
| Candle range in ATR band | 386 | 290 | 96 | 75.13 % |
| RSI in short band | 290 | 241 | 49 | 83.10 % |
| Extension from EMA20 | 241 | 197 | 44 | 81.74 % |
| Stop distance in band | 197 | 195 | 2 | 98.99 % |
| Setup detected / order created | 195 | 195 | 0 | 100.00 % |

Lifecycle: 195 orders created → 163 filled, 32 expired, 0 cancelled.
(163 fills, 162 closed trades: one short was still open when its data segment ended.)

### T3 top 10 reject codes

| # | Code | Bars | % of all bars |
|---|---|---|---|
| 1 | T3_H1_SEPARATION_BELOW_MIN | 21,364 | 21.32 % |
| 2 | T3_ADX_BELOW_MINIMUM | 15,983 | 15.95 % |
| 3 | T3_H1_EMA50_ABOVE_EMA200 | 11,344 | 11.32 % |
| 4 | T3_TREND_DIRECTION_LONG | 11,343 | 11.32 % |
| 5 | T3_POSITION_OPEN | 8,695 | 8.68 % |
| 6 | T3_M15_EMA20_ABOVE_EMA50 | 8,272 | 8.25 % |
| 7 | T3_OUTSIDE_SESSION | 7,944 | 7.93 % |
| 8 | T3_NO_BREAKDOWN_OF_STRUCTURE_LOW | 7,833 | 7.82 % |
| 9 | T3_OUTSIDE_WARMUP_WINDOW | 4,906 | 4.89 % |
| 10 | T3_H1_EMA200_SLOPE_NOT_NEGATIVE | 1,328 | 1.32 % |

Remaining T3 codes: BODY_BELOW_MIN 614 · DAILY_TRADE_CAP 141 · RANGE_ABOVE_MAX 94 ·
BLOCKED_BY_OWN_PENDING 51 · RSI_BELOW_MIN 47 · OVEREXTENDED_FROM_EMA20 44 ·
BLOCKED_BY_A4_PENDING 25 · RSI_ABOVE_MAX 2 · RANGE_BELOW_MIN 2 · STOP_DISTANCE_TOO_WIDE 2.

## Biggest opportunity bottlenecks

1. **A4 confirmation candle — 4,677 armed pullbacks produce 231 confirmations (4.9 %).**
   The single sharpest constriction anywhere in the Core. 94.7 % of those rejects are two codes:
   the bar after the pullback is not bullish at all (2,195) or it is bullish but its body is
   under 0.70 of its range (2,014). RSI, the previous-high break, the 0.90 body cap and the
   EMA20 close together account for 237.

2. **T3 structural breakdown — 8,833 qualified TREND-SHORT bars produce 1,000 breakdowns (11.3 %).**
   T3 spends 8,833 bars in exactly the regime it wants and closes below the prior 5-bar low on
   one bar in nine.

3. **T3 body filter — 614 of 1,000 breakdown candles rejected (61.4 %).** Of every rule T3
   applies *after* a valid breakdown, this one discards more than all the others combined
   (range 96, RSI 49, extension 44, stop 2).

4. **Single-position contention costs both children ~9 % of bars.** A4 loses 9,590 bars to an
   open position and T3 loses 8,695, plus 76 bars each to a pending order (51 of A4's to a
   T3-owned order and 25 of T3's to an A4-owned one). This is the Core's shared execution slot,
   not a child rule.

5. **The daily cap is not a bottleneck.** It binds on 46 A4 bars (0.05 %) and 141 T3 bars
   (0.14 %). Neither is the stop-distance band: it removes 54 A4 and 2 T3 otherwise-valid setups.

6. **Regime filters dominate by volume but are the strategies' premise, not a defect.**
   A4 discards 49,243 bars on confirmed-H1 bullishness; T3 discards 21,364 on H1 separation and
   15,983 on ADX. 11,343 bars are a qualified H1 *up* trend that shorts-only T3 stands down from.

## Yearly reject breakdown

A4, total rejects per year (2023 is a partial year; the dataset starts 2023-11-10):

| Year | Total | H1_EMA50_BELOW_EMA200 | M15_EMA20_BELOW_EMA50 | POSITION_OPEN | OUTSIDE_SESSION | H1_CLOSE_BELOW_EMA200 | H1_SEPARATION_BELOW_MIN | ADX_BELOW_MINIMUM |
|---|---|---|---|---|---|---|---|---|
| 2023 | 4,893 | 682 | 469 | 364 | 248 | 344 | 496 | 232 |
| 2024 | 35,047 | 10,833 | 4,741 | 3,528 | 2,505 | 2,584 | 2,124 | 2,357 |
| 2025 | 34,979 | 13,243 | 3,945 | 3,925 | 2,453 | 2,188 | 2,260 | 1,720 |
| 2026 | 25,133 | 11,233 | 3,403 | 1,773 | 1,938 | 1,452 | 1,324 | 1,018 |

T3:

| Year | Total | H1_SEPARATION_BELOW_MIN | ADX_BELOW_MINIMUM | H1_EMA50_ABOVE_EMA200 | TREND_DIRECTION_LONG | POSITION_OPEN | M15_EMA20_ABOVE_EMA50 | OUTSIDE_SESSION |
|---|---|---|---|---|---|---|---|---|
| 2023 | 4,895 | 1,136 | 436 | 427 | 393 | 332 | 127 | 280 |
| 2024 | 35,057 | 7,104 | 5,600 | 4,394 | 4,585 | 3,202 | 2,470 | 2,792 |
| 2025 | 34,951 | 8,028 | 5,332 | 3,562 | 3,425 | 3,570 | 3,151 | 2,776 |
| 2026 | 25,131 | 5,096 | 4,615 | 2,961 | 2,940 | 1,591 | 2,524 | 2,096 |

A4's H1-bullish rejection rises materially over time — 10,833 (2024) to 13,243 (2025) on a
near-identical bar count, then 11,233 in a three-quarter 2026. Monthly counts at the same
granularity are in the result payload and in the Signal Funnel tab.

## Strategy X-Ray

The frozen Core now emits structured rule evaluations. One row per rule the strategy actually
evaluated, at each child's decision core: A4 bars where the confirmation candle was tested,
T3 bars where the structural breakdown was tested. Source predicates short-circuit, so rules
after the first failure on a bar are absent by design — they were never evaluated, and inventing
them would misrepresent the strategy. Output is capped at 20,000 rows per run because the whole
result is persisted into the experiment ledger; the UI states when a run was truncated.

## Verification

* Tests 911 → **981** (70 new). Full suite green.
* MT5 static checks: 80, PASS, 0 failures.
* Protected fingerprints unchanged: A4 `55fedf85…`, T3 `4c4ab845…`, Core `631374d5…`,
  PB1 `c3c1bc5b…`, PB2 LONG `668674ac…`, PB2 SHORT `1caf727a…`, PB3 `7ad6dc8a…`
  (all four REJECTED, unchanged).
* Stage 3 EA, Stage 4/5 layer and the MT5 sources are untouched.
