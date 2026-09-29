# H3 independent replication — methodology

## Order of work

1. **Verify the seals.** The H3 preregistration (`c481f8a1…`), H1–H5 (67 files), the raw exports, the tracked tree
   (= HEAD `d56f304`) and the experiment ledger (`bcc4b4d1dc844d93`) were all verified unchanged.
2. **Build the slice.** `prepare_slice.py` cuts the replication slice out of the raw M15 export **by timestamp text
   before any parsing**: `2022.11.27 23:00:00 ≤ t < 2025.12.22 23:00:00`, 72,521 bars (`a6a503ff…`). The reserved
   holdout, the artifact era, development, the sealed Validation/OOS and later bars never leave the raw file.
3. **Write the runner.** `run_replication.py` imports the frozen functions unchanged (bytecode writing disabled).
4. **Detection-only dry run.** This printed detection counts and 526 window events. No forward race, control or rate
   was computed. It proved the frozen implementation runs unchanged on the older data.
5. **One pre-freeze fix.** The dry run showed that `h3_gate`'s prefix-invariance check must receive the unfiltered
   detection (`all_events`); otherwise the 4 warm-up events would cause a spurious mismatch. The fix was made before
   the runner was hashed. It concerns the gate input only; no rule or outcome code was changed.
6. **Freeze.** `H3_REPLICATION_PREREGISTRATION.md` was written with every hash and frozen (`4200ea85…`).
7. **Run.** The outcome run was followed by a second identical run (slice rebuilt from raw, same hash). All 7 outputs
   were byte-identical. A first attempt to hash the outputs failed on a shell word-splitting error, so the comparison
   is between the second and third complete runs.

## What is frozen development code

| function | from | role |
|---|---|---|
| `features` (ATR, `rng8`, `rng8_pct`, `expansion`, sessions, ER, `vol_regime`, …) | `h1_study.py` | causal features |
| `h3_features`, `detect`, `_event` | `h3_study.py` | H3 rules 1–15 |
| `controls` | `h3_study.py` | matched controls |
| `h3_gate` | `h3_study.py` | prefix invariance and structure causality |
| `forward`, `wilson` | `h1_study.py` | target race, MFE/MAE, Wilson CI |
| `lift`, `p_win` | `h1_report.py` | event-clustered bootstrap CI |

## Replication-specific code (data window only)

- **Loading the slice.** The slice is loaded, and its bounds, ordering and duplicates are asserted.
- **Event window.** Only events whose acceptance bar time is in [2023-01-01 00:00, 2025-12-22 23:00) UTC are kept.
  There were 4 warm-up events, which were excluded.
- **Control pool.** Warm-up bars are removed from the control pool by setting `atr_pct` to NaN in a copy of the
  feature frame. The frozen `controls()` already requires `atr_pct`, so warm-up bars cannot be drawn.
- **Hole flag.** Each event gets a provenance flag `lookback_contains_hole`: its 20-session lookback contains one of
  the 5 known missing-bar holes. It is never used to exclude events.
- **Reporting.** Year, month and side tables; the preregistered decision function; and the descriptive comparison
  with the frozen development result, recomputed from the frozen development CSVs with the same functions.

## Forward resolution boundary

The slice ends at the 2025-12-22 21:45 bar. `forward()` stops at the end of the loaded data, so a race that would need
later bars is `truncated` (11 events at +2R, excluded from P(...), as in development). **No development-period bar
enters any outcome.**

## Reproduce

```
venv/bin/python research/gold_v1/history_expansion/h3_replication/prepare_slice.py
venv/bin/python research/gold_v1/history_expansion/h3_replication/run_replication.py
cd research/gold_v1/history_expansion/h3_replication && shasum -a 256 -c SHA256SUMS
```
