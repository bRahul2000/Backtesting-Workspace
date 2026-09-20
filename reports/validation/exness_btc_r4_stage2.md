# R4 Stage 2 — Backtester ↔ MT5 parity run (BTC Core V1, AUDIT_ONLY)

**Verdict: NOT CERTIFIED.** The first real parity run diverged, seven defects
were found and corrected, and every residual divergence is now attributed. Four
of the corrections are in the MQL5 twin, so they are not present in the audit
CSV this report measures. Certification requires one more MT5 run.

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

* 31/31 static checks PASS, including `header_matches_python_schema`, 76/76
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
