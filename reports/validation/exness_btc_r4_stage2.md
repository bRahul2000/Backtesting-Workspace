# R4 Stage 2 — Backtester ↔ MT5 parity run (BTC Core V1, AUDIT_ONLY)

> **Run 4 (final, 16:54) is the certified run — FULL PARITY: True.**
>
> **Run 3 (certification, 16:37) reached 99.965% and 22/22 matching trades, but
> one defect remains: the twin never cancels a pending order.** See "Run 3".
>
> **Run 2 (2026-09-20 16:10) did not exercise the corrected EA.** The submitted
> `..._corrected.csv` is byte-for-byte identical to run 1 after collapsing an
> appended duplicate of every bar. Cause: MetaTrader runs the compiled `.ex5`,
> and the deployed binary is dated 15:02 while the deployed source — which does
> match repo HEAD — is dated 15:39. The source was copied across but never
> recompiled, so the stale pre-correction binary ran. See "Run 2" at the end.

**Verdict: CERTIFIED on run 4** (`..._final.csv`, 2026-09-20 16:54). All 76
audit columns agree on all 5,663 commonly logged bars and all 22 trades match
end to end. The history below is kept: it took four runs and eight corrections,
and each one is recorded with the evidence that found it. See "Run 4".

## What was compared

| | |
|---|---|
| Window | 2026-01-01 → 2026-03-01 UTC |
| Symbol | BTCUSDm (Exness, broker-native) |
| Spread | `BROKER_NATIVE_PER_BAR`, real per-bar `iSpread` |
| MT5 audit | `data/exness/btc/r4/mt5_btc_core_v1_audit_20260101_20260301.csv`, 5,663 bars, compiled 0 errors / 0 warnings |
| Python audit | `data/exness/btc/r4/python_core_audit_20260101_20260301.csv`, 5,665 bars |
| Bars compared | **5,663** (intersection) |
| Only in Python | 2 (`2026-02-28T23:45Z`, `2026-03-01T00:00Z`) |
| Only in MT5 | 0 |

The Python exporter self-verifies: it re-runs `run_universal_backtest` over the
same data and refuses to emit an audit whose trade log differs. It also now
raises if its derived A4 reject code disagrees with whether the frozen strategy
actually emitted a signal. Both passed on all 5,665 bars.

Tolerances are unchanged: `EXACT_TOLERANCE = 1e-09`, `INDICATOR_TOLERANCE =
1e-06`, `ROUNDING_TOLERANCE = 0.01` as a *labelling* threshold only. Nothing was
loosened to close a gap.

## Parity by dimension — pre-correction baseline

These are the numbers for the EA **as it ran**. They are the problem statement,
not the result.

| Dimension | Matching bars | Parity |
|---|---|---|
| `ohlc` | 5,663 / 5,663 | 100.0% |
| `volume_and_spread` | 5,663 / 5,663 | 100.0% |
| `h1_context` | 5,663 / 5,663 | 100.0% |
| `indicators` | 5,650 / 5,663 | 99.770% |
| `carried_state` | 5,118 / 5,663 | 90.376% |
| `a4_context` | 4,830 / 5,663 | 85.290% |
| `a4_signal` | 5,654 / 5,663 | 99.841% |
| `t3_context` | 4,847 / 5,663 | 85.591% |
| `t3_signal` | 5,663 / 5,663 | 100.0% |
| `signal` | 5,657 / 5,663 | 99.894% |
| `pending` | 5,648 / 5,663 | 99.735% |
| `entry` | 5,658 / 5,663 | 99.912% |
| `stop_and_target` | 5,658 / 5,663 | 99.912% |
| `exit` | 5,655 / 5,663 | 99.859% |

Whole-bar decision parity 84.99%. Trades: Python 22, MT5 27, 0 matching
end-to-end in order.

**Market data and H1 aggregation are already exact.** Both sides read identical
OHLC, tick volume and per-bar spread, and build the identical confirmed-H1
context, on every one of 5,663 bars. The port of the Pine-equivalent indicators
and the H1 bucket rule is sound; every defect below is in surrounding logic.

Two facts hide inside the low `a4_context` / `t3_context` numbers: 803 of the
833 disagreeing bars are *before the warmup window*, and the 22 post-warmup
trades agree exactly on entry time, entry price, stop and target. The strategy
core was never the problem.

## Divergence classes and root causes

| Class | Bars | Root cause | Fix |
|---|---:|---|---|
| `CONTEXT_MISMATCH` | 287 | EA searched from bar 15; Python's descriptor searches from 2026-01-09 12:00 | C1 |
| `STATE_MISMATCH` | 545 | 521 from the same warmup gap; 24 from a pullback surviving the session close | C1, C9 |
| `INDICATOR_MISMATCH` | 13 | EA withheld `plus_di`/`minus_di` until ADX seeded | C2 |
| `PENDING_STATE_MISMATCH` | 2 | order created off a stale pullback | C9 |
| `EXIT_MISMATCH` | 3 | `realized_r` divided by the capped loss, not the risk budget | C4 |
| `TIMESTAMP_ALIGNMENT` | 2 | MT5 run stopped at `23:30Z` on 2026-02-28 | window boundary, not a defect |

### Earliest causal divergence

`2026-01-01T00:00:00Z` — `a4_reject_code`: Python `A4_BEFORE_WINDOW`, MT5
`A4_WARMUP`. The twin had no concept of the frozen descriptor's warmup window,
so from bar 15 it evaluated gates, opened pullbacks and took five trades on bars
the Python side declines to trade at all.

The earliest divergence **not** explained by warmup is
`2026-01-13T22:00:00Z` — `a4_pullback_active`: Python `0`, MT5 `1`. 22:00 UTC is
the session close. `btc_v3_l2_trend_pullback_long.on_candle` clears the pullback
on that branch; the EA returned without clearing it. The stale pullback then
produced 17 confirmation decisions and one pending order the frozen strategy
never made. This was invisible until `carried_state` was added to the
comparator, and it is the single most valuable finding of the run.

## Corrections

All seven are in the twin / audit / comparator layer. No frozen strategy file,
indicator, timestamp or execution semantic was touched.

| | Where | Correction |
|---|---|---|
| C1 | EA | Implements the descriptor's warmup contract (`CoreWarmupM15Bars` = 50, `CoreWarmupH1Bars` = 204, `CoreFirstSearchTime`), emits `A4_/T3_BEFORE_WINDOW`, and restarts warmup after a data gap as the Python side restarts per continuous segment |
| C2 | EA | `DmiUpdate` reports `has_di` separately from ADX, matching `pine_indicators.DMI`, which returns +DI/−DI while `adx` is still `None` |
| C4 | EA | `AuditQuantity` keeps `planned_risk` = the risk budget when the leverage cap shrinks quantity, matching `Position.initial_risk` |
| C9 | EA | Clears the pullback on the out-of-session and daily-cap branches |
| C3 | Exporter | Emits the full pending vocabulary `CREATED / FILLED / EXPIRED / ACTIVE` in the twin's precedence, instead of only `CREATED / ACTIVE` |
| C5 | Exporter | Derives the A4 reject code from a **pre-`on_candle`** state snapshot and ports the pullback state machine's own control flow, adding the five codes only MQL5 could emit (`PULLBACK_TOO_DEEP`, `SAME_BAR_AS_PULLBACK_START`, `STOP_TOO_TIGHT`, `STOP_TOO_WIDE`, `STRUCTURE_BREAK_BAR`) |
| C7 | Exporter | Publishes `a4_/t3_trigger/stop/stop_atr` only on bars that computed them, matching `Decision.has_levels`, instead of a hypothetical level on every bar |
| C6 | Comparator | New `STATE_MISMATCH` class, checked **before** context, and `LEVEL_MISMATCH`. Every schema column is now compared; a test enforces that |

C4 is arithmetic, not judgement: the disputed trade lost \$23.30441355 on a
\$24.87515625 budget with a leverage-capped loss of \$22.86318428.
−23.30441355 / 24.87515625 = **−0.9368549616** (Python's value);
−23.30441355 / 22.86318428 = **−1.0192986800** (MT5's value, to the digit).

## Verification

* Static checks PASS (`python -m tools.check_mt5_core_source`), including
  `header_matches_python_schema`, 76/76
  columns, `warmup_m15_bars` = 50 and `warmup_h1_bars` = 204 checked against the
  real `warmup_plan`, `resets_pullback_out_of_session`,
  `resets_pullback_at_daily_cap`, `planned_risk_is_budget`, and
  `reject_codes_match_python` (both vocabularies now identical, 0 codes on
  either side alone).
* **748 tests pass** (740 → 748). Eight new tests pin each correction.
* All seven protected fingerprints unchanged: A4 `55fedf85…`, T3 `4c4ab845…`,
  Core `631374d5…`, PB1 `c3c1bc5b…`, PB2 LONG `668674ac…`, PB2 SHORT
  `1caf727a…`, PB3 `7ad6dc8a…`. PB1/PB2/PB3 remain REJECTED.
* `AUDIT_ONLY` remains the default; `SendOrderGuard` refuses unconditionally;
  no order-submission call exists anywhere in the source. DEMO_EXECUTION was not
  enabled.
* Commission, swap and realized cost remain `UNVERIFIED`. No rate was invented.

## Why this is NOT CERTIFIED

C1, C2, C4 and C9 change the EA. The audit CSV measured here came from the EA
before those changes. Re-deriving what the corrected EA *would* have logged would
mean manufacturing broker-side evidence, so it was not done. The residual is
fully attributed but not yet observed at zero.

The 2-bar tail gap is a window boundary, not a defect: the MT5 run ended at
`2026-02-28T23:30Z`. Both bars are decision-free on the Python side. It is left
visible in the report rather than trimmed away.

## Exact next action

Recompile `mt5/BTC_V3_Core_V1.mq5` in MetaEditor (F7), re-run AUDIT_ONLY over
the same 2026-01-01 → 2026-03-01 window, and re-run:

```
python tools/compare_mt5_core.py \
  --python-audit data/exness/btc/r4/python_core_audit_20260101_20260301.csv \
  --mt5-audit    <new MT5 audit csv>
```

Expected on the corrected EA: `FULL PARITY: True`, 0 bars mismatching, 22 trades
on both sides fully matching. Anything else is a new finding and stays open.

Audit CSVs live in `data/exness/btc/r4/` and are deliberately not committed
(7.8 MB of generated/terminal output).


---

## Run 2 — 2026-09-20 16:10 (`..._corrected.csv`)

The file holds 11,326 rows: every one of the 5,663 bars twice, and the two
copies are identical. After collapsing the repeat, the frame is **byte-for-byte
equal to run 1**. Every parity figure above reproduces to the decimal.

Four falsifiable checks, each of which the corrected EA must change:

| Check | Corrected EA | Run 2 |
|---|---|---|
| `A4_BEFORE_WINDOW` / `T3_BEFORE_WINDOW` rows | > 0 | **0** |
| bars with `plus_di` while `adx` is empty | 13 | **0** |
| entries before 2026-01-09 12:00 | 0 | **5** |
| `a4_pullback_active` at 2026-01-13T22:00Z | 0 | **1** |

All four report the pre-correction behaviour, so the running EA was the
pre-`d618129` build.

**Root cause.** In the wine prefix:

```
MQL5/Experts/BTC_V3_Core_V1.ex5   48,442 b   15:02   <- executed
MQL5/Experts/BTC_V3_Core_V1.mq5   56,255 b   15:39   <- identical to repo HEAD
```

The `.mq5` was copied over but F7 was not pressed, so MetaTrader kept running
the binary compiled from the previous source.

### Two real defects this run exposed

| | Where | Correction |
|---|---|---|
| F1 | EA | `OpenLog` appended into the existing common-files log, writing every bar a second time. It now truncates by default (`FileOpen` without `FILE_READ`); `InpAppendLog` opts back in for a continuous live session |
| F2 | EA | `OnInit` prints `TWIN_BUILD` and `__DATETIME__`, so a stale `.ex5` is visible in the Experts tab instead of being inferred from parity output days later |
| F3 | Comparator | `load_audit` collapses identical repeated bars, reports the count, and still refuses repeats that disagree — recovery happens inside the tool rather than as an untracked manual edit |

Neither F1 nor F2 affects a decision, an indicator, a timestamp or an execution
semantic. 752 tests pass; all seven protected fingerprints unchanged.


---

## Run 3 — certification attempt, `..._certification.csv` (2026-09-20 16:37)

Confirmed fresh from the MT5 Journal (`Twin build R4-S2-2 …, compiled
2026.09.20 16:26:36`, `first signal search at 2026.01.09 12:00`) and from the
file itself: 5,663 distinct bars, no duplicates, 816 `*_BEFORE_WINDOW` rows,
13 bars publishing +DI before ADX, 0 pre-warmup entries, and the pullback
cleared at the 2026-01-13 22:00 session close. All five corrections are live.

| Dimension | Matching | Parity |
|---|---|---|
| `ohlc`, `volume_and_spread`, `h1_context` | 5,663 / 5,663 | **100%** |
| `indicators` | 5,663 / 5,663 | **100%** |
| `carried_state` | 5,663 / 5,663 | **100%** |
| `a4_context`, `a4_signal` | 5,663 / 5,663 | **100%** |
| `t3_context`, `t3_signal` | 5,663 / 5,663 | **100%** |
| `signal` | 5,663 / 5,663 | **100%** |
| `entry`, `stop_and_target`, `exit` | 5,663 / 5,663 | **100%** |
| `pending` | 5,661 / 5,663 | 99.965% |

Whole-bar decision parity **99.965%**. Trades **22 / 22, all 22 matching
end-to-end** on entry time, entry price, stop, target, exit time, exit price,
exit reason and realized R. The warmup, session-reset, DI and risk-budget
corrections are all confirmed effective against real observed MT5 output.

### Earliest causal mismatch

`2026-01-14T13:30:00Z` — `pending_status`: Python `CANCELLED`, MT5 `ACTIVE`.

ADX falls from 18.0103 at 13:15 (the bar that created the order) to 17.3808 at
13:30, below A4's `min_adx` of 18.0. The frozen A4 therefore returns
`CancelPendingOrder("V3-L2 bullish trend context invalidated.")` and the order
is withdrawn. The twin had **no cancellation path at all**: it left the order
live and recorded `EXPIRED` one bar later at 13:45, the second mismatch.

Here the outcome coincided — the order would not have filled either way, which
is why all 22 trades still match. That is luck, not equivalence: on a path where
price reached the trigger at 13:30, the twin would have filled an order the
frozen Core had already pulled. This is a material divergence and blocks
certification.

### Correction C10 — pending-order cancellation

| | Where | Correction |
|---|---|---|
| C10 | EA | `ShouldCancelPending` ports the frozen contract: session end and daily cap cancel for either child, invalidated A4 context (`A4ContextValid` / `A4MaterialBelowEma50`) cancels only an A4-owned order, and only the child that owns the order may cancel it (`btc_v3_core_v1.on_candle`). It is a pure predicate applied *after* the bar's reject codes, so the cancelling bar still reports `A4_BLOCKED_PENDING` as Python does |
| C10 | Exporter | Emits `CANCELLED` instead of a blank cell on the bar the frozen Core withdraws an order |

T3 has no context-invalidation cancel; the asymmetry is in the frozen source and
is pinned by a test.

The Python pending ledger now balances exactly: **26 CREATED = 22 FILLED +
3 EXPIRED + 1 CANCELLED**, with nothing open at the end of the window. A test
enforces that invariant on any audit, so a silently dropped order cannot pass.

### Verification

* Static checks PASS, including `implements_pending_cancellation`,
  `cancellation_respects_order_ownership`, `only_a4_cancels_on_context`.
* **756 tests pass** (752 → 756).
* All seven protected fingerprints unchanged; PB1/PB2/PB3 remain REJECTED.
* AUDIT_ONLY default intact; DEMO_EXECUTION not enabled.

### Still NOT CERTIFIED

C10 is an EA change and is not present in the certification file. Nothing was
reconstructed: the numbers above are measured from the observed MT5 output as
submitted. One more run of the recompiled EA is required.


---

## Run 4 — CERTIFIED (`..._final.csv`, 2026-09-20 16:54)

Confirmed fresh from the MT5 Journal (`compiled 2026.09.20 16:48:27`,
`first signal search at 2026.01.09 12:00`, and
`Pending cancelled at 2026-01-14T13:30:00Z: V3-L2 bullish trend context
invalidated.`) and from the file: 5,663 distinct bars, no duplicates, distinct
from every earlier run, and the MT5 pending ledger now balances exactly as
Python's does — **26 CREATED = 22 FILLED + 3 EXPIRED + 1 CANCELLED**.

| Dimension | Matching | Parity |
|---|---|---|
| `ohlc` | 5,663 / 5,663 | **100%** |
| `volume_and_spread` | 5,663 / 5,663 | **100%** |
| `h1_context` | 5,663 / 5,663 | **100%** |
| `indicators` | 5,663 / 5,663 | **100%** |
| `carried_state` | 5,663 / 5,663 | **100%** |
| `a4_context` / `a4_signal` | 5,663 / 5,663 | **100%** |
| `t3_context` / `t3_signal` | 5,663 / 5,663 | **100%** |
| `signal` | 5,663 / 5,663 | **100%** |
| `pending` | 5,663 / 5,663 | **100%** |
| `entry` | 5,663 / 5,663 | **100%** |
| `stop_and_target` | 5,663 / 5,663 | **100%** |
| `exit` | 5,663 / 5,663 | **100%** |

Whole-bar decision parity **100.000%**, 0 mismatching bars.
Trades **22 / 22, all 22 matching** on entry time, entry price, stop, target,
exit time, exit price, exit reason and realized R. Summed realized R is
identical to ten decimal places on both sides (−5.8348258414). Exits: 18 stop
loss, 4 take profit.

Verified independently of the comparator by a separate pass over all 76 columns
and a separately rebuilt trade table: no column shows any residual difference.

### The window boundary, and why it is not an exemption

The EA evaluates `ProcessClosedBar(1)` — the just-closed bar. That is the
safeguard that stops it reading a forming bar, and it means a run can never log
the final bar of its own range. A Python audit run to the same end date
therefore always carries a short tail past the last MT5 bar; here
`2026-02-28T23:45Z` and `2026-03-01T00:00Z`, both out of session or
not-bullish, with no signal, pending order, entry or exit.

Rather than waive this by hand, the rule is now in the comparator as
`WINDOW_BOUNDARY`, and it is deliberately narrow. These remain hard failures:

* a Python-only bar **inside** the MT5 range, wherever it falls;
* **any** MT5-only bar;
* a trailing bar carrying **any** decision — signal side, setup id, either
  signal flag, a pending status, an entry or an exit.

Nine tests pin those guardrails, including a parametrised case for each of the
seven decision columns.

### Acceptance criterion, as enforced

> 100% strategy decision parity over every compared bar; no MT5-only bar; no
> Python-only bar inside the MT5 range; and any Python bars past the last
> logged MT5 bar must carry no signal, pending order, entry or exit.

**FULL PARITY: True.**

### Final state

* **764 tests pass.** All 35 static checks pass.
* All seven protected fingerprints unchanged; PB1/PB2/PB3 remain REJECTED.
* `AUDIT_ONLY` is the default, `SendOrderGuard` refuses unconditionally, no
  order-submission call exists in the source, DEMO_EXECUTION not enabled.
* Commission, swap and realized cost remain `UNVERIFIED`. No rate was invented.
* Tolerances unchanged throughout: `EXACT_TOLERANCE = 1e-09`,
  `INDICATOR_TOLERANCE = 1e-06`, `ROUNDING_TOLERANCE = 0.01` as a label only.

### What this certifies, and what it does not

It certifies that the MQL5 twin reproduces the frozen BTC Core exactly on
broker-native Exness BTCUSDm data over 2026-01-01 → 2026-03-01: same bars, same
indicators, same carried state, same gates, same orders, same fills, same
exits, same R.

It does not say anything about whether the strategy is worth trading. Over this
window the frozen Core returned −5.83R across 22 trades. That is a property of
the strategy, not of the twin, and it is not a validation result.


---

## Certification freeze

Frozen at commit `12777e9`, annotated tag **`btc-core-r4-stage2-certified`**.

### Observed certification artifact

The MT5 audit is the primary evidence and is **not committed**: it is 3.8 MB of
terminal output under a deliberately gitignored path (`.gitignore:30`
→ `data/exness/btc/r4/`). Its identity is pinned here instead, so the file can
be verified later or shown to have been substituted.

| | |
|---|---|
| Path | `/Users/apple/Documents/Backtesting/data/exness/btc/r4/mt5_btc_core_v1_audit_20260101_20260301_final.csv` |
| SHA-256 | `c6f7e6a57589392af143687973b0fd2a20382f420d9c1b8002763efb92b8a84a` |
| Size | 3,969,903 bytes |
| Written | 2026-09-20 16:54 UTC |
| Produced by | `mt5/BTC_V3_Core_V1.mq5` at commit `d14e95d`, compiled 2026.09.20 16:48:27 |

Verify with:

```
shasum -a 256 data/exness/btc/r4/mt5_btc_core_v1_audit_20260101_20260301_final.csv
```

The Python half of the comparison,
`data/exness/btc/r4/python_core_audit_20260101_20260301.csv`, is regenerable
from committed code:

```
python tools/export_python_core_audit.py \
  --data data/exness/btc/phase_r1/processed/btcusdm_M15.csv \
  --start 2026-01-01 --end 2026-03-01 \
  --spread-source BROKER_NATIVE_PER_BAR \
  --output data/exness/btc/r4/python_core_audit_20260101_20260301.csv
```

### Certified evidence

| | |
|---|---|
| Aligned bars | 5,663 |
| Mismatches | 0 |
| Whole-bar decision parity | 100.000% |
| Python trades / MT5 trades | 22 / 22 |
| Full-trade parity | 22 / 22 |
| **FULL PARITY** | **True** |
| Tests | 764 pass |
| Protected hashes | all seven unchanged, PB1/PB2/PB3 REJECTED |
| DEMO_EXECUTION | disabled |

Every dimension — OHLC, spread, H1 context, indicators, carried state, A4
context and signal, T3 context and signal, signal, pending, entry, stop/target,
exit — is 100% across all 5,663 bars. Realized R matches to ten decimal places
on all 22 trades.

### WINDOW_BOUNDARY: the two trailing Python bars

`2026-02-28T23:45Z` and `2026-03-01T00:00Z` appear in the Python audit and not
in MT5. This is structural, not a defect. The EA evaluates
`ProcessClosedBar(1)` — the just-closed bar — which is the safeguard that stops
it reading a forming bar, so a run can never log the final bar of its own
range. Both bars are out of session or not-bullish and carry no signal, pending
order, entry or exit.

The comparator classifies them `WINDOW_BOUNDARY` under a deliberately narrow
rule. These all remain hard failures: a Python-only bar **inside** the MT5
range; **any** MT5-only bar; a trailing bar carrying any of `signal_side`,
`signal_setup_id`, `a4_signal_pass`, `t3_signal_pass`, `pending_status`,
`entry_time_utc` or `exit_time_utc`. Nine tests pin those guardrails, including
a parametrised case for each of the seven decision columns.

---

## Proposed second certification window (not yet run)

Certification so far covers one contiguous 2-month window. The **segment-reset**
path — indicators, pullback state, day counters, balance and warmup all
restarting after a data gap — has never been exercised against real MT5 output.

### Largest real M15 gap in the validated R1 dataset

`data/exness/btc/phase_r1/processed/btcusdm_M15.csv` holds 100,239 bars from
2023-11-10 23:15 to 2026-09-20 07:15 UTC, in 7 continuous segments with 6 gaps.

| Last bar before | First missing | Last missing | First bar after | Missing | Duration |
|---|---|---|---|---|---|
| 2025-10-16 15:00 | **2025-10-16 15:15** | **2025-10-16 17:30** | 2025-10-16 17:45 | 10 | 2h 30m |

The next largest is 3 bars (2024-12-21 06:30 → 07:00), so this is the only gap
big enough to be unambiguous.

### Proposed window

**MT5 Strategy Tester — From `2025.09.01`, To `2025.12.01`** (BTCUSDm, M15,
AUDIT_ONLY, every tick based on real ticks, same inputs as the certified run).

Confirmed against the real dataset:

| | Segment 1 | Gap | Segment 2 |
|---|---|---|---|
| Range | 2025-09-01 00:00 → 2025-10-16 15:00 | 10 bars | 2025-10-16 17:45 → 2025-12-01 00:00 |
| Bars | 4,381 | — | 4,346 |
| First signal search | 2025-09-09 12:00 | — | 2025-10-25 06:00 |
| Tradable span | 37d 03h | — | 36d 18h |
| Python trades | 13 | — | 22 |

8,727 bars, exactly 2 segments and exactly 1 gap — the largest one — with
warmup completing and trades occurring on both sides.

### Why it exercises segment reset

1. **Warmup restarts.** The second segment re-derives its own first-search time
   (2025-10-25 06:00) from its own start, so `CoreFirstSearchTime` and the
   `*_BEFORE_WINDOW` codes are re-tested on a segment that is not the first.
2. **Indicators reseed.** At 2025-10-16 17:45 `ema20` returns to the bar close
   (108315.26) and `atr` goes blank. EMA/RMA/ATR/RSI/DMI seeding and the H1
   bucket rule are all re-tested mid-file rather than only at file start.
3. **A position is open when the gap hits.** The Python side records 13 entries
   but only 12 exits before the gap: one position is abandoned at the boundary.
   The EA's `ResetAll` clears `g_position.active`, `g_order.active` and
   `g_balance` to match. This is the highest-value case in the window and is
   completely untested today.
4. **Balance and day counters reset**, so position sizing restarts from
   `InpStartBalance` on both sides — and the leverage-cap path that produced the
   `planned_risk` defect is re-tested under a fresh balance.
5. **Both segments trade**, so a reset that quietly disabled the second segment
   would show up as missing trades rather than as silence.

The Python audit for this window is already exported to
`data/exness/btc/r4/python_core_audit_20250901_20251201.csv` (8,727 rows, 35
trades) and is ready for comparison. No MT5 run has been made.
