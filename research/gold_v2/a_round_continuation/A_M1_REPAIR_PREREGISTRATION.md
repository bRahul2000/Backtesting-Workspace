# A — XAUUSDm M1 structural repair, 2017–2021: preregistration (DATA REPAIR ONLY)

Frozen before any repaired file was produced, and without any continuation outcome, OHLC-based selection, ATR
comparison or signal information. The expected selection was counted from **timestamps only**.

## Inputs (SHA-256, from `data/raw/SHA256SUMS`, verified by the script before use)

`v2_m1_XAUUSDm_2017.csv` … `v2_m1_XAUUSDm_2021.csv`. Only rows with `2017.05.01 00:00:00 ≤ timestamp <
2021.08.31 22:00:00` are selected, by text. Sealed rows do not exist in the snapshot; the 2021 file stops before
2021-09-01.

| file | sha256 |
|---|---|
| implementation `repair_m1.py` | `0ed93b25d0f9db0868526a51aa9a625810c5d397044e16c4aa9cfe1ffcf482f9` |
| read-only gap helper `research/gold_v1/history_expansion/audit_history.py` (unchanged) | `1c328058fbb35b85875feb80d7950ae53975b6fea6d0f3510a045dc868f3153f` |

## Rule (identical in concept to the approved M15 repair `b1720e9b…`)

Remove an M1 bar **iff** it forms a one-bar session under the frozen session rule: the previous bar's start is ≥ 60
min earlier **and** the next bar's start is ≥ 60 min later. It uses timestamps only, never prices, volume, ATR,
signals or outcomes.

**Expected selection from timestamps: 167 bars.**
- 163 Sunday 00:00 UTC (Saturday in New York);
- 2018-03-30 00:00 (Good Friday eve, after the close);
- 2018-12-26 00:00 and 2019-12-26 00:00 (Christmas Day, New York);
- 2020-01-02 00:00 (New Year's Day, New York).

Window: 1,523,802 bars. The first and last bars have neighbours 1 minute away.

## Action

- **Output.** `data/derived/xauusd_m1_2017_2021_repaired.csv` holds the kept raw lines byte-for-byte. It is a local
  payload and is not committed; its hash is.
- **Manifest.** `m1_repair_removal_manifest.csv` records each removed row with its raw line and a reason code.
- **Nothing else.** No interpolation, no edits and no other rows.

## Audit criteria (all must pass, otherwise A stops)

| id | criterion |
|---|---|
| R1 | every removed bar lies in a known closure: Saturday in New York, or the dated holiday closures above |
| R2 | every kept line is byte-identical to raw, and rows after = rows before − removed |
| R3 | no one-bar session remains, and no bar remains on a Saturday in New York time |
| R4 | monotonic, no duplicates, valid OHLC, whole-minute timestamps |
| R5 | M1 → M15 aggregation reproduces **every** bar of the audited repaired M15 reference (2017-06 → 2021-08) exactly (O, H, L, C). Extra M15 bars are allowed **only** inside the known V1 export hole 2019-11-29 → 2019-12-23 (`GOLD_V1_UPSTREAM_DATA_ERRATA.md`) |
| R6 | every era gap ≥ 60 min is a daily break or variant, a weekend, a holiday/early close **of at most 4 days** (this closes the V1 classifier flaw), or a preregistered known outage (2018-01-31 14:00; 2018-08-16 08:45; 2018-08-27 02:15; 2018-08-27 09:30) |
| R7 | causality tests: the timestamp-only rule is unaffected by prices, and bars after T cannot change removals at or before T − 60 min (`tests/test_v2_round2.py`) |
