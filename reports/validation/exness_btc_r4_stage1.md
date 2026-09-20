# R4 Stage 1 + Stage 2 — MT5 digital twin for the frozen BTC Core

**Stage 1 status: COMPLETE (source).** `mt5/BTC_V3_Core_V1.mq5` exists, defaults to
`AUDIT_ONLY`, and contains no order-transmission call anywhere in its code.
**Stage 2 status: COMPLETE.** `tools/compare_mt5_core.py` exists with the full divergence
taxonomy and an offline fixture suite.

**No order was placed. No trading is enabled.** The only outstanding item is a manual
MetaEditor compile, which cannot be performed on this machine.

---

## 1. Architecture

```
  Exness BTCUSDm M15/H1                      data/exness/btc/phase_r1/  (R1, validated)
            |                                              |
            v                                              v
  mt5/BTC_V3_Core_V1.mq5                    tools/export_python_core_audit.py
  (AUDIT_ONLY, MT5 terminal)                (frozen Core + audited engine primitives)
            |                                              |
            +--- btc_core_v1_audit.csv        python_core_audit.csv ---+
                                |                          |
                                v                          v
                        tools/compare_mt5_core.py  ->  parity report
```

Both sides emit the identical 76-column schema declared once in
`tools/core_audit_schema.py`, one row per **closed** M15 bar. That module is the contract;
neither side may drift from it without the comparator refusing to load.

## 2. AUDIT_ONLY safety

| Control | Implementation |
|---|---|
| Default mode | `input ExecutionMode InpMode = AUDIT_ONLY;` |
| Hard guard | Every hypothetical order path calls `SendOrderGuard()` **first**. In `AUDIT_ONLY` it refuses unconditionally. In `DEMO_EXECUTION` it *also* refuses — transmission is deliberately unimplemented in Stage 1. |
| No transmission code | `OrderSend`, `OrderSendAsync`, `PositionOpen`, `PositionClose`, `OrderModify`, `OrderDelete`, `CTrade` appear **nowhere** in the source. Enforced by `tools/check_mt5_core_source.py`, which strips comments and strings before scanning, and by a test. |
| Chart status | `Comment("BTC CORE V1 — AUDIT ONLY — NO ORDERS")` on init and every new bar. |
| Startup asserts | Symbol is `BTCUSDm`, digits 2, point 0.01, and the server clock is UTC (R1 recorded offset 0). Any failure halts the EA with a visible reason instead of trading on wrong assumptions. |

`DEMO_EXECUTION` exists as a declared enum state only, so the structure is ready for a later
authorized stage; selecting it today changes nothing except a warning in the log.

## 3. Strategy-porting mapping

Every rule was ported from the authoritative Python source, read in full — not from memory.

| MQL5 | Python source |
|---|---|
| `PineEma` / `PineRma` / `PineAtr` / `PineRsi` / `PineDmi` | `strategies/pine_indicators.py` |
| `H1Regime`, `H1CompleteBucket`, `H1Bullish` | `strategies/confirmed_h1_regime.py`, `h1_bullish()` |
| `EvaluateA4` | `strategies/btc_v3_l2_trend_pullback_long.py` + `btc_v3_a4_pullback_long.py` overlay |
| `EvaluateT3` | `strategies/btc_v3_t3_breakout_short.py` (`classify_regime`, `evaluate_v3`) |
| A4-before-T3 priority | `strategies/btc_v3_core_v1.py` `on_candle` |
| `TryFill` / `TryExit` / `CreateAuditOrder` / `AuditQuantity` | `engine/execution.py` |

**Deliberately not using `iMA` / `iATR` / `iRSI` / `iADX`.** MT5's built-ins seed differently
(SMA seeding for EMA, Wilder seeding for ATR) and would not reproduce `pine_indicators.py`.
The EA implements the Python seeding exactly: EMA seeds with the first price; RMA seeds with
the simple mean of its first `length` observations; ATR's first true range is `high − low`;
RSI returns nothing on the first close; DMI's first bar feeds only the TR average.

Frozen values carried as `#define`, matching the Python constants: A4 body 0.70–0.90,
normalized H1 EMA200 slope ≥ 0.15, max stop 3.00 ATR, material-below-EMA50 0.20 ATR, pullback
depth ≤ 1.00 ATR, RSI 48–70; T3 H1 separation ≥ 1.00 ATR, body ≥ 0.70, range 0.60–2.00 ATR,
RSI 24–50, EMA20 extension ≤ 2.50 ATR, stop lookback 2. Session 00:00–22:00 UTC, 3 trades/day,
2-bar pending expiry, 3R target — shared by both components.

## 4. Timestamp semantics

- **Shift 0 is the forming M15 bar and is never evaluated.** A new bar is detected when
  `iTime(_Symbol, PERIOD_M15, 0)` changes; the bar then processed is **shift 1**, the bar
  that just closed. `ProcessClosedBar(1)` is the only call site.
- **The confirmed H1 bar** is the previous complete four-bar hour. It becomes visible only
  once a bar belonging to the *next* hour has closed, and a bucket missing any of its
  `:00/:15/:30/:45` bars is **discarded, not partially aggregated** — the same rule
  `ConfirmedH1Regime._complete_bucket` applies. This is what makes the context non-repainting.
- **Alignment key** is the M15 bar's **open** time in UTC, ISO-8601 with `Z`. A test asserts
  the comparator does not silently align on close times.
- **Gaps.** A missing M15 bar breaks indicator continuity. The Python engine splits the
  dataset into continuous segments and resets; the EA mirrors that by resetting indicators
  and state when `bar.time - previous != 900s`.
- The EA refuses to start unless `TimeTradeServer() − TimeGMT()` is within 60s of zero.
  R1 recorded exactly 0 for Exness-MT5Trial5.

## 5. Bid/Ask semantics

Candles are broker **Bid**. The synthetic Ask is Bid + per-bar spread, taken from
`iSpread(_Symbol, PERIOD_M15, shift)` × point — the broker's own recorded bar spread, not a
constant. `SideCandle()` selects the stream:

| | Entry | Exit |
|---|---|---|
| Long | **Ask** | Bid |
| Short | Bid | **Ask** |

This matches `research/exness_cost_calibrated.py` `entry_candle` / `exit_candle`, which the
audited engine uses.

Fill and exit rules mirror `engine/execution.py`: long fills when `high ≥ trigger` at
`max(trigger, open)`, short when `low ≤ trigger` at `min(trigger, open)`; opening-gap stop
and target cases are checked before intrabar hits; an ambiguous bar resolves **SL first**;
the 3R target is derived from the **actual fill**, never from the planned trigger.

## 6. Logging schema

76 columns, written to MT5 Common Files as `btc_core_v1_audit.csv`. Groups: market data,
confirmed H1 (time + OHLC + EMAs + ATR + slope + separation), M15 indicators, A4 block,
T3 block, order lifecycle, and cost status. Column names and order are fixed by
`tools/core_audit_schema.py`; a static check asserts the EA's log row has exactly as many
fields as its header.

**Rejection codes** are deterministic labels tied to actual frozen rules, so a divergence can
be traced to the clause that caused it:

`A4_OUT_OF_SESSION`, `A4_MAX_TRADES_PER_DAY`, `A4_WARMUP`, `A4_H1_NOT_BULLISH`,
`A4_EMA_STACK_FAIL`, `A4_ADX_FAIL`, `A4_H1_SLOPE_NORM_FAIL`, `A4_MATERIAL_BELOW_EMA50`,
`A4_PULLBACK_TOO_DEEP`, `A4_NO_PULLBACK`, `A4_SAME_BAR_AS_PULLBACK_START`,
`A4_STRUCTURE_BREAK_BAR`, `A4_CONFIRM_NOT_BULLISH`, `A4_BODY_TOO_SMALL`,
`A4_CLOSE_BELOW_EMA20`, `A4_NO_BREAK_PREV_HIGH`, `A4_RSI_OUT_OF_BAND`, `A4_BODY_TOO_LARGE`,
`A4_STOP_TOO_TIGHT`, `A4_STOP_TOO_WIDE`, `A4_SIGNAL_OK`, `A4_BLOCKED_PENDING`,
`A4_BLOCKED_POSITION`, `A4_BEFORE_WINDOW`.

`T3_OUT_OF_SESSION`, `T3_MAX_TRADES_PER_DAY`, `T3_WARMUP`, `T3_REGIME_NOT_TREND`,
`T3_DIRECTION_LONG_DISABLED`, `T3_NO_BREAK_PREV_LOW`, `T3_NOT_BEARISH_CANDLE`, `T3_BODY_FAIL`,
`T3_RANGE_TOO_SMALL`, `T3_RANGE_TOO_LARGE`, `T3_RSI_OUT_OF_BAND`, `T3_EXTENSION_FAIL`,
`T3_STOP_TOO_TIGHT`, `T3_STOP_TOO_WIDE`, `T3_SIGNAL_OK`, `T3_BLOCKED_PENDING`,
`T3_BLOCKED_POSITION`, `T3_BEFORE_WINDOW`.

Commission, swap and realized cost are written as **`UNVERIFIED`** on every row. No rate is
invented; they stay unverified until a real demo account statement supplies them.

## 7. Python audit exporter

`tools/export_python_core_audit.py` drives the **real** `BtcV3CoreV1Frozen` through the
audited engine's own primitives (`create_pending_order`, `fill_pending_order`,
`exit_decision`, `close_position`), so lifecycle behaviour is identical by construction
rather than by imitation. Gate outcomes come from calling the frozen predicates themselves
(`h1_bullish`, `classify_regime`, `body_percent`), and indicator values come from a parallel
instance of the same `pine_indicators` classes.

**Self-verification:** after replaying, the exporter re-runs `run_universal_backtest` over
the same data and raises unless the trade count and every entry/exit price match. A
successfully produced audit is therefore itself evidence that the replay has not drifted.

Observed on real R1 data (2026-01-01 → 2026-03-01, broker-native spread): 5,665 bars,
26 signals, 22 entries, 22 exits. Largest A4 rejection buckets `A4_H1_NOT_BULLISH` (3,694)
and `A4_EMA_STACK_FAIL` (243); largest T3 buckets `T3_REGIME_NOT_TREND` (2,910) and
`T3_NO_BREAK_PREV_LOW` (920).

## 8. Comparator behaviour

Aligns on `bar_time_utc` and reports the **first** divergence per bar, in causal order, so a
cascade is diagnosed at its cause:

`DATA_MISMATCH` → `SPREAD_MISMATCH` → `H1_ALIGNMENT` → `INDICATOR_MISMATCH` →
`CONTEXT_MISMATCH` → `SIGNAL_MISMATCH` → `PENDING_STATE_MISMATCH` → `ENTRY_PRICE_MISMATCH` →
`SL_MISMATCH` → `TP_MISMATCH` → `EXIT_MISMATCH`, plus `TIMESTAMP_ALIGNMENT` for a bar present
on only one side, `ROUNDING_MISMATCH` for a sub-point difference on a *derived* price, and
`UNKNOWN`.

**Tolerances are explicit and do not hide failures:**

| Group | Tolerance | Rationale |
|---|---|---|
| Raw OHLC, volume, spread, H1 OHLC | `1e-09` (bit-identical) | Both sides read the same broker bars |
| Indicators | `1e-06` relative | float64 vs double accumulation over thousands of bars |
| Derived prices (pending/entry/SL/TP/exit) | `1e-09` for equality | A sub-point gap is still **reported**, labelled `ROUNDING_MISMATCH` |

A raw-data difference is **never** downgraded to a rounding artefact, however small.
A missing MT5 record is **never** a match.

Outputs: bars compared, python-only/mt5-only counts, decision-parity percent, per-group match
counts (OHLC, indicators, A4 decisions, T3 decisions, signals, pending, entries, exits),
mismatch counts by class, the first 20 mismatches, the ten worst numeric differences, and a
boolean `full_parity`. The CLI exits non-zero unless parity is total.

**Acceptance criterion: 100% strategy decision parity over every compared bar, with no bar
present on only one side.** It has not been lowered.

## 9. Tests

**734 passed** (701 → 734; 33 new). Coverage:

- Schema stability, duplicate-bar rejection, missing-column rejection, `UNVERIFIED` costs.
- The full offline fixture matrix required by the specification: exact match, indicator
  mismatch, H1 timestamp mismatch, missing bar, signal mismatch, entry mismatch, exit
  mismatch, rounding-only mismatch — plus data, spread, context and pending-state cases.
- Tolerance behaviour in both directions: float accumulation is absorbed, a 100× larger
  deviation is not.
- First-divergence-only reporting, worst-difference ranking, "a missing record is never a
  match".
- UTC alignment on bar-open time; a one-bar shift is detected, not absorbed.
- Python exporter against real R1 data, including its engine self-verification and
  deterministic reject-code patterns.
- MQL5 source checks: no forbidden call in code, guard present, `AUDIT_ONLY` default,
  chart status string, log row matches header, closed-bar-only evaluation, structural balance.

BTC Core benchmark **Development 472 / Forward 223 unchanged.**

## 10. Known blockers

1. **MetaEditor compile not performed.** No MetaEditor exists on this machine, so no
   compilation success is claimed. `tools/check_mt5_core_source.py` performs static checks
   only — it is explicit that it is not a compile.
2. **No live or Strategy Tester MT5 audit log exists yet**, so no real parity number has been
   produced. The comparator has been validated against fixtures and against a self-comparison
   of a real 5,665-bar Python audit, not yet against MT5 output.
3. **Commission and swap remain UNVERIFIED.** At the R3 broker-native PF of 1.072 this is
   decisive; it must be resolved from a demo account statement before any profitability
   conclusion.
4. **The EA's `trades_today` counter** increments on a simulated fill. Python increments on
   `state.opened_position`, which is the same event, but this is a like-for-like assumption
   that only a real parity run can confirm.

## 11. Manual MT5 steps required

1. Copy `mt5/BTC_V3_Core_V1.mq5` into `…\MQL5\Experts\` (MetaEditor: **File → Open Data
   Folder → MQL5 → Experts**).
2. Open it in MetaEditor and press **F7**. Expect `0 errors`. Report any error text — do not
   edit the strategy logic to make it compile.
3. Ensure BTCUSDm M15 and H1 deep history is downloaded (open each chart, hold **Home**).
4. **Strategy Tester** → Expert `BTC_V3_Core_V1`, Symbol `BTCUSDm`, Period `M15`, Model
   **Every tick based on real ticks**, a date range inside R1 coverage
   (2023-11-10 → 2026-09-20). Leave `InpMode = AUDIT_ONLY`.
5. Run. The EA writes `btc_core_v1_audit.csv` to
   `C:\Users\<you>\AppData\Roaming\MetaQuotes\Terminal\Common\Files\`.
6. Copy that file to the repository and run:

```bash
python -m tools.export_python_core_audit \
    --start 2026-01-01 --end 2026-03-01 \
    --output reports/validation/python_core_audit.csv
python -m tools.compare_mt5_core \
    --python-audit reports/validation/python_core_audit.csv \
    --mt5-audit <path to btc_core_v1_audit.csv>
```

Use the **same start and end dates** on both sides.
