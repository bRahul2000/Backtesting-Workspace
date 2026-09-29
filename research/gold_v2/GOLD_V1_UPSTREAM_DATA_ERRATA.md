# Gold V1 — upstream data erratum (recorded in Gold V2; Gold V1 is not modified)

Gold V1 remains frozen at `gold-v1-research-v1.0` → `fd39cdfc9a5f4228eb93d8ce0c9cd54840ec038d`. This document
records a data-quality fact discovered during Gold V2 round 2. **No V1 file, hash, result or conclusion is changed.**

## Finding

- **The hole.** The historical XAUUSDm M15 export used by V1 (`research/gold_v1/history_expansion/raw_full/
  xauusd_XAUUSDm_M15.csv`, and therefore the repaired file derived from it) has a **missing-data hole from
  2019-11-29 to 2019-12-23**. Its last bar before the hole is 2019-11-29 (a Thanksgiving-Friday early close), and the
  next is 2019-12-23 00:00. That date is exactly where V1's earlier `raw/` export (2019-12-23 onward) begins, so the
  hole is a seam between the two history loads.
- **The misclassification.** V1's gap classifier (`history_expansion/audit_history.py` `classify_gaps`) labels a gap
  "holiday/early_close" whenever the gap spans a US holiday date. This gap spans Thanksgiving Friday, so it was
  classified as a holiday and deep-history repair criterion A5 ("every era gap explained") passed.
- **The evidence.** The Gold V2 M1 export (`research/gold_v2/data/raw/v2_m1_XAUUSDm_2019.csv`, hash in
  `data/raw/SHA256SUMS`) contains complete trading days for 2019-12-01 → 2019-12-22 (20,716 M1 bars; ~1,378 per full
  day). Aggregated to M15 it reproduces every existing M15 bar exactly, so the M15 export simply lacked this history.

## Impact

- **Coverage.** H3 replication #2 (repaired 2017-06 → 2021-08) had roughly **three fewer weeks** of December 2019 data,
  and some 20-session compression lookbacks spanned the hole.
- **No leakage.** No evidence suggests future leakage from the missing interval; missing data cannot leak future
  prices.
- **No recomputation.** No V1 result is recomputed. Gold V1 remains frozen.
- **Conclusions stand.** The erratum does not alter the frozen V1 conclusions: H3 FAILED TO REPLICATE, H1/H2/H5 NO
  EDGE, H4 WEAK / NO DEMONSTRATED ECONOMIC EDGE.

## Consequence for Gold V2

V2 studies that need 2017–2021 XAUUSDm use the **M1** export, repaired under its own preregistration (see
`a_round_continuation/A_M1_REPAIR_PREREGISTRATION.md`). It includes December 2019.
