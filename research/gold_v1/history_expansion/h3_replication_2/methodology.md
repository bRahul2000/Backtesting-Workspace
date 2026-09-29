# H3 second independent replication — methodology

## Order of work

1. **Verify the seals.** The repair preregistration (`b1720e9b…`), the repaired dataset and manifest, `raw_full/`,
   replication #1, H1–H5, the original H3 preregistration, the tracked tree (= HEAD) and the ledger
   (`bcc4b4d1dc844d93`) were all verified unchanged.
2. **Write the code.** `run_replication_2.py` (outcomes, tables, gates) and `synthesis.py` (the secondary synthesis)
   were written before any outcome existed.
3. **Detection-only dry run.** It reproduced the approved count exactly: 1,007 events (481 long / 526 short) and 5
   warm-up events. It computed no forward race, control or rate.
4. **Freeze.** `H3_REPLICATION_2_PREREGISTRATION.md` was frozen (`2bf602e6…`), with the hashes of both scripts and
   all inputs.
5. **Outcome run.** The standalone result was computed and then recomputed from scratch. All 10 standalone outputs
   were byte-identical.
6. **Synthesis.** Only after the standalone outputs were frozen was `synthesis.py` run (twice, byte-identical). It
   matches its preregistered hash.

## Frozen components (imported unchanged)

- **`h1/h1_study.py`:** `features`, `forward`, `wilson`, `trading_days`.
- **`h3/h3_study.py`:** `h3_features`, `detect`, `controls`, `h3_gate`.
- **`h1/h1_report.py`:** `lift`, the event-clustered bootstrap with 5,000 resamples, seed 20260603.
- **Controls:** identical to development and replication #1. Warm-up bars are removed from the control pool by
  masking `atr_pct`, which is the same data-window step used in replication #1.

## Replication-specific code (data window and reporting only)

- **Loading.** The repaired M15 file is loaded, with its bounds, ordering and duplicates asserted.
- **Event window.** Acceptance bars must fall in [2017-06-01, 2021-08-31 22:00) UTC.
- **Provenance flags.** These are descriptive and exclude nothing:
  - the 20-session lookback contains a repaired pseudo-session location (767 events, because the artifact was
    weekly from mid-2018);
  - the lookback contains a genuine outage (47);
  - the race is near a weekly-open regime transition or a break-variant day (41).
- **Tables.** Year, leave-one-year-out, month and side tables, each with its own bootstrap CI for year, LOYO and side.
- **Classification.** The two-gate classification is applied exactly as preregistered.

## Forward boundary

The data end at 2021-08-31 20:45 UTC. At +2R, 23 events are unresolved (`none` or `truncated`) and are excluded from
P(...). No bar of the sealed 2021-09 holdout exists in the input.

## Reproduce

```
venv/bin/python research/gold_v1/history_expansion/h3_replication_2/run_replication_2.py
venv/bin/python research/gold_v1/history_expansion/h3_replication_2/synthesis.py
cd research/gold_v1/history_expansion/h3_replication_2 && shasum -a 256 -c SHA256SUMS
```
