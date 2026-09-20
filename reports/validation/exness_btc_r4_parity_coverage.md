# R4 Stage 2 — parity coverage census

Scan of the full validated Exness BTCUSDm R1 M15 dataset with the frozen Core,
to establish which execution paths the two certified windows actually exercise.

Scanned: `data/exness/btc/phase_r1/processed/btcusdm_M15.csv`, 100,229 audit
rows, 2023-11-10 23:15 → 2026-09-20 07:15 UTC. Bitstamp was not used. No
parameter was changed and no strategy file was touched.

## Correction: T3 SHORT is already certified

A previous conversational summary stated that T3 produced zero signals in both
certified windows and that its execution path was uncovered. **That was wrong.**
T3 is not merely exercised — it is the dominant component of both runs.

| | Window 1 (2026-01-01…03-01) | Window 2 (2025-09-01…12-01) |
|---|---|---|
| T3 signals | 21 | 25 |
| T3 pending orders created | 21 | 25 |
| T3 entries (filled) | 18 | 21 |
| T3 pendings expired | 3 | 4 |
| T3 closed trades | 18 | 20 |
| T3 exits | 14 SL / 4 TP | 13 SL / 7 TP |
| A4 closed trades | 4 | 14 |
| **T3 share of closed trades** | **18 of 22** | **20 of 34** |

Every T3 trade is byte-identical between Python and MT5 in both windows, on
entry time, entry price, stop, target, exit time, exit price, exit reason and
realized R. Short geometry is correct on all of them (stop > entry > target).

The claim came from reading a `t3_signal 100%` parity line as agreement over an
empty sample, without ever counting the signals. The two certified runs already
prove T3 signal → pending → entry → exit parity on **46 signals and 39 filled
short trades**. A third window for T3 coverage is not needed.

## Full-period T3 census

| | Count |
|---|---|
| T3 signals (`t3_signal_pass` = 1, all promoted to Core signals) | 195 |
| T3 pending orders created | 195 |
| T3 entries (filled) | 163 |
| T3 pendings expired | 32 |
| T3 pendings cancelled | 0 |
| T3 closed trades | 162 |

For contrast, A4 over the same period: 177 signals, 158 entries, 16 expired,
3 cancelled, 158 closed trades. T3 is the busier component throughout.

## What the certified windows do and do not cover

Covered by the two certified windows: every pending status
(`CREATED`/`FILLED`/`EXPIRED`/`CANCELLED`), both exit reasons, 19 of 21 A4
reject codes and 14 of 15 T3 reject codes seen anywhere in the dataset, the
segment-reset path, and an abandoned position across a data gap.

Not covered:

| Code | Occurrences in full dataset | Days |
|---|---|---|
| `A4_MAX_TRADES_PER_DAY` | 46 bars | 2024-07-04, 2026-04-14 |
| `T3_MAX_TRADES_PER_DAY` | 46 bars | 2024-07-04, 2026-04-14 |
| `A4_CLOSE_BELOW_EMA20` | 12 bars | 11 days |

The daily cap is the material one: it gates trading after three fills in a UTC
day *and* is one of the three conditions that cancel a live pending order. It is
reached on only two days in 2.9 years.

Never produced by real data at all, so there is nothing to certify:
`A4_WARMUP`, `T3_WARMUP` (the warmup-window gate now fires first, making the
indicator-warmup codes unreachable), `A4_SAME_BAR_AS_PULLBACK_START`,
`A4_STOP_TOO_TIGHT`, `T3_STOP_TOO_TIGHT`, `T3_NOT_BEARISH_CANDLE`. The
opening-gap and ambiguous-bar exit branches also never fire: BTC M15 on
continuous broker data does not gap through a level in this dataset.

## Optional third window — daily cap, not T3

Reference audit generated and self-verified against `run_universal_backtest`:

| | |
|---|---|
| From / To | **2026-03-01 → 2026-05-10** UTC |
| Bars | 6,721 |
| Segments | 1 (no gaps) |
| Pending orders created | 19 (A4 17, T3 2) |
| Entries | 16 (A4 14, T3 2) |
| Expired / cancelled | 2 / 1 |
| Closed trades | 16 — 10 stop loss, 6 take profit |
| `A4_MAX_TRADES_PER_DAY` | 18 bars, 2026-04-14 |
| `T3_MAX_TRADES_PER_DAY` | 18 bars, 2026-04-14 |
| `A4_CLOSE_BELOW_EMA20` | 3 bars, 2026-04-18 / 05-02 / 05-05 |
| Daily cap genuinely reached | 3 fills on 2026-04-14 |
| Pending cancellation | 1, at 2026-04-08 17:15Z |
| Python audit | `data/exness/btc/r4/python_core_audit_20260301_20260510.csv` |
| SHA-256 | `89a1a2f61a9b1f6ed35935937e68f7430070b0a3dbf81829102c6ecb9355b3cd` |

A more compact alternative, `2026-04-01 → 2026-05-01` (2,881 bars), still covers
all three codes but carries only 7 fills and no T3 activity.

This window is worth one run only if the daily-cap gate matters before live
trading. It adds nothing to T3 coverage, which is already certified.
