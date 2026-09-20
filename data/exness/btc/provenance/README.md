# Broker history provenance check

The third parity window (2026-03-01 → 2026-05-10) matched on every decision
column but differed on `tick_volume` for one bar: the validated R1 export
records 271 for `2026-04-19T07:30:00Z`, the Strategy Tester read 270. The R1
history was exported at 13:14 and that run was made at 17:33.

Volume feeds no gate, indicator or execution rule, so it cannot change a
decision. The reason this is being chased is different: it shows the two sides
did not read an identical history snapshot, and whatever moved a tick count
could move a price. This folder answers whether it did.

## Rules

* The validated R1 export in `data/exness/btc/phase_r1/raw/` is **never**
  touched. `R1_BASELINE_HASHES.txt` records its SHA-256s; verify with
  `shasum -a 256 -c data/exness/btc/provenance/R1_BASELINE_HASHES.txt`.
  A test (`test_the_validated_r1_export_still_matches_its_recorded_hashes`)
  fails the suite if any of the five files changes.
* The fresh export lands in `raw/` here, under a different filename prefix, and
  never overwrites or is merged into R1.
* Differences are reported, never repaired. No bar is patched, reconciled or
  back-filled.
* R1 remains the authoritative dataset unless and until a comparison says
  otherwise.

`raw/` is gitignored: it is multi-megabyte terminal output.

## Does the audit need H1?

**No — M15 alone is sufficient.** Both halves of the twin derive the H1 context
from M15 bars rather than reading broker H1:

* Python: `tools/export_python_core_audit.py` opens exactly one file, the M15
  CSV, and builds H1 through `strategies/confirmed_h1_regime.ConfirmedH1Regime`,
  which buckets M15 bars by `floor("h")` and completes a bucket only when its
  four bars are exactly `:00/:15/:30/:45`.
* MQL5: `mt5/BTC_V3_Core_V1.mq5` reads only `PERIOD_M15` and feeds `H1Update`
  the same way. There is no `PERIOD_H1` call anywhere in the EA.

H1 is still worth exporting in the same session, because the R1 manifest
includes an H1 file that `services/btc_broker_data.reconcile_m15_h1` checks
against M15. If the broker is revising history, it is worth knowing whether H1
moved too. The existing export script produces both in one run at no extra
effort, so there is no reason not to.
