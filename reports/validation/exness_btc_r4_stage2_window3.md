# R4 Stage 2 — third window: daily cap and rare rejection paths

**Verdict: NOT CERTIFIED**, on one bar, in one column, that no strategy reads.

Every path this run was built to exercise matched exactly. The single residual
is a `tick_volume` difference of one tick on `2026-04-19T07:30:00Z`, where OHLC
and spread are bit-identical. Raw broker data is required to be bit-identical,
so it is a hard failure and is reported as one.

## The run

| | |
|---|---|
| Window | 2026-03-01 → 2026-05-10 UTC |
| Symbol / mode | BTCUSDm M15, AUDIT_ONLY, DEMO_EXECUTION disabled |
| EA | `mt5/BTC_V3_Core_V1.mq5` at `d14e95d`, unchanged |
| MT5 audit | `data/exness/btc/r4/mt5_btc_core_v1_audit_20260301_20260510.csv` |
| MT5 SHA-256 | `26294dc9dce16ac70ed3956b2bf7115413cb6c2a33695c38be76aaa337e9d89b` |
| Python audit | `data/exness/btc/r4/python_core_audit_20260301_20260510.csv` |
| Python SHA-256 | `89a1a2f61a9b1f6ed35935937e68f7430070b0a3dbf81829102c6ecb9355b3cd` |
| Aligned bars | 6,719 |
| Mismatches | 1 |

Neither CSV is committed; `data/exness/btc/r4/` is gitignored.

## Parity

| Dimension | Parity |
|---|---|
| `ohlc` | 100% |
| `volume_and_spread` | 99.985% — **1 bar** |
| `h1_context`, `indicators`, `carried_state` | 100% |
| `a4_context`, `a4_signal` | 100% |
| `t3_context`, `t3_signal` | 100% |
| `signal`, `pending`, `entry`, `stop_and_target`, `exit` | 100% |

Trades 16 / 16, all 16 matching end to end, 0 unclosed. Exits 10 stop loss,
6 take profit. Whole-bar decision parity 99.985%; on every decision-bearing
column it is 100%.

## The paths this run existed to test

| Target | Result |
|---|---|
| `A4_MAX_TRADES_PER_DAY` | 18 bars on both sides, identical bar-for-bar, 2026-04-14 |
| `T3_MAX_TRADES_PER_DAY` | 18 bars on both sides, identical bar-for-bar, 2026-04-14 |
| `A4_CLOSE_BELOW_EMA20` | 3 bars on both sides, identical, 2026-04-18 / 05-02 / 05-05 |
| Three-fill day 2026-04-14 | 3 fills at 04:00, 06:15, 15:45 on both; `a4_trades_today` reaches 3 on both; **all 76 columns identical across all 96 bars of that day** |
| Cap engagement | from 17:30Z to 21:45Z, 18 bars, `a4_trades_today` = 3 at onset on both |
| No leakage under the cap | zero pending statuses, zero entries, zero signal flags on both. One exit occurs — correct: the cap blocks new entries, not the management of an open position, and both sides record the same exit |
| Day rollover | `a4_trades_today` back to 0 on 2026-04-15 on both |
| Cancellation 2026-04-08T17:15Z | `CANCELLED` on both, `a4_reject_code` = `A4_BLOCKED_PENDING` on both, all 76 columns identical on that bar, exactly one cancellation in the window on each side, and the pending is gone on the next bar on both |

All verified by a pass written independently of the comparator.

## The one mismatch

`2026-04-19T07:30:00Z` — `tick_volume`: Python 271, MT5 270.

```
open 75019.57  high 75133.98  low 75019.57  close 75062.29  spread 1400   <- identical
tick_volume    271 (Python)    270 (MT5)                                  <- differs
```

The Python side is faithful to its source: the raw export
`data/exness/btc/phase_r1/raw/btcusd_BTCUSDm_M15.csv` records 271 for that bar,
and the processed dataset carries 271 through. The M15 history was exported at
13:14; the tester ran at 17:33 and read 270.

Two possible causes, and the evidence does not distinguish them: the broker
revised its tick history for that bar between the export and the run, or the
history exporter and the tester count that bar's ticks differently. What can be
said is that the divergence is isolated — across all 6,719 bars, `tick_volume`
is the only column that differs, and it differs on one bar by one tick.

### Why it is not excused

`volume` is carried on `Candle` and summed into the H1 bucket, but no gate,
indicator or execution rule reads it, and `H1RegimeValue` has no volume field
at all. It cannot change a decision, and every decision input on that bar is
bit-identical.

It is still reported as a hard `DATA_MISMATCH`, for two reasons. The acceptance
criterion requires raw broker data to be bit-identical, and relaxing it here —
on the one run where it is inconvenient — would be fitting the standard to the
result. More practically, the field is a canary: it shows the two sides did not
read an identical history snapshot, and the same mechanism that moved a tick
count could move a price. A test now pins `tick_volume` to the raw-data
standard so the exemption cannot be introduced quietly later.

This does not affect the two certified windows. Their bars were compared with
zero mismatches, and this bar (April 2026) falls outside both.

## Final state

* **771 tests pass** (770 → 771). All 35 static checks pass.
* Protected fingerprints unchanged; PB1/PB2/PB3 remain REJECTED.
* No frozen strategy logic, indicator, timestamp or execution semantic changed.
  The EA was not modified for this window.
* Tolerances unchanged. `AUDIT_ONLY` default intact; DEMO_EXECUTION disabled.

## To certify this window

Re-export the BTCUSDm M15 history from the same terminal so both sides read one
snapshot, regenerate the Python audit for 2026-03-01 → 2026-05-10, and re-run
the comparison. If only `tick_volume` changes, the window certifies. If any OHLC
value has also moved, that is a materially larger finding and would put the
provenance of the two certified windows in question too — worth knowing either
way before live trading.

This window is optional coverage. Stage 2 certification rests on
`btc-core-r4-stage2-certified` (5,663 bars) and
`btc-core-r4-stage2-window2-certified` (8,725 bars), both unaffected.
