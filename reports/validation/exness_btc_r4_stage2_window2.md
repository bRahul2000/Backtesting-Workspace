# R4 Stage 2 — Second certification window (segment reset)

**Verdict: CERTIFIED.** Full parity across a real Exness M15 data gap, with the
segment-reset path exercised against observed MT5 output for the first time.

Window 1 (`btc-core-r4-stage2-certified`, commit `12777e9`) covered one
contiguous stretch. This window exists to test what that one could not: what
happens when the feed breaks and both sides restart.

## The run

| | |
|---|---|
| Window | 2025-09-01 → 2025-12-01 UTC |
| Symbol | BTCUSDm (Exness, broker-native), M15 |
| Spread | `BROKER_NATIVE_PER_BAR`, real per-bar `iSpread` |
| Mode | AUDIT_ONLY, DEMO_EXECUTION disabled |
| EA | `mt5/BTC_V3_Core_V1.mq5` at commit `d14e95d` (unchanged since certification) |
| MT5 audit | `data/exness/btc/r4/mt5_btc_core_v1_audit_20250901_20251201.csv` |
| SHA-256 | `8ff7313e2a5d2965c8e5f01cd1dbb217f85fdde41e034d9f681377203291305a` |
| Size | 6,273,511 bytes, written 2025-09-20 17:09 |
| Python audit | `data/exness/btc/r4/python_core_audit_20250901_20251201.csv` |

Neither CSV is committed: `data/exness/btc/r4/` is gitignored (`.gitignore:30`).
The Python side regenerates from committed code with
`tools/export_python_core_audit.py --start 2025-09-01 --end 2025-12-01`.

## Result

| | |
|---|---|
| Aligned bars | 8,725 |
| Segments | 2 on both sides |
| Gap detected at | 2025-10-16 15:00Z → 17:45Z, identical on both sides |
| Mismatches | 0 |
| Whole-bar decision parity | 100.000% |
| Python trades / MT5 trades | 35 / 35 |
| Full-trade parity | 35 / 35 |
| **FULL PARITY** | **True** |

Every dimension 100% across all 8,725 bars: OHLC, volume and spread, H1 context,
indicators, carried state, A4 context and signal, T3 context and signal, signal,
pending lifecycle, entry, stop/target, exit. All 76 columns verified identical
by a pass written independently of the comparator. Summed realized R matches to
ten decimals (+2.2818234091 across 34 closed trades).

The two trailing Python bars past `2025-11-30T23:30Z` are the usual
`WINDOW_BOUNDARY`: the EA evaluates `ProcessClosedBar(1)`, so a run can never log
the final bar of its own range. Both are decision-free.

## Segment-reset verification

| Check | Result |
|---|---|
| Segment structure | 2 segments on both sides; the single interior discontinuity is identical |
| Pre-gap state parity | all 76 columns identical over the 200 bars before the gap |
| Reset-bar parity | all 76 columns identical on `2025-10-16T17:45Z` |
| Indicators reseed | `ema20` returns to that bar's close (108315.26) on both; `atr`, `rsi`, `adx`, `h1_*` blank and then reappear on exactly the same bars |
| Post-gap warmup | 817 `A4_BEFORE_WINDOW` bars on both, first searchable bar `2025-10-25T06:00Z` on both, `T3_BEFORE_WINDOW` identical |
| Warmup re-derived | segment 1 warms for 816 bars, segment 2 for 817 — a per-segment derivation, not a constant |
| Open position cleared | both sides abandon the same trade: entry `2025-10-16T14:15Z` @ 110215.5477525319, stop 111584.3389898726, target 106109.1740405097, with no exit recorded on either side |
| Blocked state ends at the gap | last `A4_BLOCKED_POSITION` is `2025-10-16T15:00Z` on both |
| No state leak | across the whole 817-bar post-gap warmup, both sides record zero pending statuses, zero entries, zero exits and zero blocked-state codes |
| Day counters | `a4_trades_today` is 0 at the reset bar and identical on all 8,725 bars |
| Balance reset | `realized_r` is identical on all 34 exits, including the first post-gap exit (`2025-10-25T10:00Z`, −0.7070726579). Since R is pnl ÷ (balance × risk %), post-gap R can only agree if the sizing balance reset identically on both sides |

The abandoned position is the most valuable single fact here. A gap arrived
while a short was open; the Python exporter starts each segment with
`pending = position = None` and `balance = starting_balance`, and the EA's
`ResetAll()` clears `g_position.active`, `g_order.active` and `g_balance`. Both
drop the trade with no exit row and no leak into the next segment. That
behaviour had never been observed against real MT5 output before this run.

## One comparator defect found and fixed

`full_trade_parity` reported **34 of 35** on a run where both sides agreed
exactly. The metric paired entries with exits positionally. That is valid only
while every entry has an exit; the abandoned position breaks the alignment, and
`min(len(entries), len(exits))` also capped the comparison at 34, so the last
trade was never checked at all.

`_trade_table` now walks the bars and pairs each entry with the exit that closes
it — correct because only one position exists at a time — and records a trade
that is abandoned or still open with a null exit. It also surfaces
`python_unclosed_trades` / `mt5_unclosed_trades` and any unmatched exit, so a
lost order is visible rather than absorbed.

This was a false negative: it understated a perfect run. It never had the power
to pass a bad one. Six tests now pin the pairing, including the abandoned-position
regression and a case proving a *differing* abandoned position still fails.

Re-running window 1 with the corrected metric leaves it unchanged: 22 / 22
trades, 0 unclosed, FULL PARITY True. The certification at `12777e9` stands.

## Final state

* **770 tests pass** (764 → 770). All 35 static checks pass.
* Protected fingerprints unchanged: A4 `55fedf85…`, T3 `4c4ab845…`, Core
  `631374d5…`, PB1 `c3c1bc5b…`, PB2 LONG `668674ac…`, PB2 SHORT `1caf727a…`,
  PB3 `7ad6dc8a…`. PB1/PB2/PB3 remain REJECTED.
* `AUDIT_ONLY` is the default; `SendOrderGuard` refuses unconditionally;
  forbidden-call scan returns empty; DEMO_EXECUTION not enabled.
* No frozen strategy logic, indicator, timestamp or execution semantic changed.
  The EA was not modified for this window.
* Tolerances unchanged: `EXACT_TOLERANCE = 1e-09`, `INDICATOR_TOLERANCE = 1e-06`,
  `ROUNDING_TOLERANCE = 0.01` as a label only.

## Scope

Two windows are now certified, 8,725 + 5,663 bars, covering a continuous stretch
and a stretch containing a real 10-bar feed gap with a position open across it.
This certifies twin equivalence only. Over this window the frozen Core returned
+2.28R across 34 closed trades; over window 1 it returned −5.83R across 22. Those
are properties of the strategy, not of the twin, and neither is a validation
result.
