# Deep-history repair — preregistration (DATA REPAIR ONLY)

Frozen 2026-09-29, **before any repaired file was produced**, and without looking at any H3 signal, H3 outcome,
forward return, R result or profitability. The rule was defined, and its expected selection counted, from **bar
timestamps only**. This file is not edited after the repair runs.

## Hashes (SHA-256)

| item | hash |
|---|---|
| `raw_full/xauusd_XAUUSDm_M15.csv` (immutable evidence) | `4724a019bf2c25c2f03e971034d6986de94174e602c3a15924dc167f3d193e43` |
| `raw_full/xauusd_XAUUSDm_H1.csv` (immutable evidence) | `7de0706efccf16eada36f5e3f26ec255eb9e11eb8407c38a650da6d034fc0bc5` |
| repair / audit / count implementation `history_expansion/repair_history.py` | `6065e681d663ec2140b756ff4ff91f2e4d1aec7ff4bc28dad2e1d8db356f6db7` |
| causality tests `tests/test_repair.py` | `c704e47bc4a9045d992c468a992582dd7963b015f84f0ed97e8c4082951461ed` |
| audit helpers `history_expansion/audit_history.py`, unchanged | `1c328058fbb35b85875feb80d7950ae53975b6fea6d0f3510a045dc868f3153f` |
| frozen H3 `h3/h3_study.py`, unchanged | `a6c8bb400f83a5af41fa92d63931878098c255f37298203a7aa65238a5262e99` |
| frozen pipeline `h1/h1_study.py`, unchanged | `e2ec68842c142987f4c892727ed00393a372227a7d83ad1d9d6a3b3f03a94369` |

## Scope

- **Repair window.** M15 and H1 rows of `raw_full/` with `2017.05.01 00:00:00 ≤ timestamp < 2021.08.31 22:00:00`,
  selected by **text** before parsing:
  - 2017-05 is warm-up only;
  - the era is 2017-06-01 → 2021-08-31;
  - the session opening 2021-08-31 22:00 UTC belongs to the 2021-09-01 trading day of the **sealed holdout**. It and
    everything later are never read.
- **Contaminated span.** 2018-07-01 → 2021-08-15: the Sunday future-bar artifact.
- **Known artifact counts (DEEP_HISTORY_AUDIT.md).** 159 Sunday-00:00-UTC lone bars (2018-07-01 → 2021-08-15), plus the
  holiday bars 2018-12-26 and 2019-12-26. 147 of 159 carry the next session's high, low and close.

## Repair detection rule (structural, timestamps only)

An M15 bar is **removed if and only if it forms a one-bar session under the frozen session rule**:
- the previous bar's start is **≥ 60 minutes** earlier, **and**
- the next bar's start is **≥ 60 minutes** later.

A missing neighbour at the edge of the window counts as ≥ 60 min. The window's first bar (2017-05-01 00:00) and last
bar (2021-08-31 20:45) both have a neighbour 15 minutes away, so neither is removable.

- **Why this rule.** The frozen pipeline starts a new session whenever consecutive bar starts are ≥ 60 min apart. Real
  sessions hold 92 bars, and early closes still hold dozens. A one-bar session is an impossible topology.
- **What it does not use.** Prices, tick volume, spread, the next-session price match, ATR, H3 signals and outcomes.
- **Causality.** The decision needs the *timestamp* of the next bar, which is known at most 60 minutes after the bar
  (the absence of any bar for 45 minutes). It never uses a price. Tests A9 pin that no change after time T alters any
  removal, ATR value or H3 detection at or before T − 60 min.

**Expected selection, counted from timestamps only before freezing: 164 M15 bars.**

| reason code (descriptive; not part of the rule) | expected | NY local time |
|---|---|---|
| `WEEKEND_SATURDAY_NY` | 159 | Sunday 00:00 UTC = Saturday 19:00/20:00 New York (2018-07-01 → 2021-08-15) |
| `CHRISTMAS_DAY` | 2 | 2018-12-25 19:00 and 2019-12-25 19:00 New York (the 2018-12-26 / 2019-12-26 00:00 UTC bars) |
| `NEW_YEARS_DAY` | 1 | 2020-01-01 19:00 New York (2020-01-02 00:00 UTC), newly identified by the rule |
| `GOOD_FRIDAY_EVE_AFTER_CLOSE` | 1 | 2018-03-29 20:00 New York, after that day's 17:00 close (stray one-tick bar) |
| `MEMORIAL_DAY_AFTER_EARLY_CLOSE` | 1 | 2017-05-29 14:45 New York, after the early close (stray bar; warm-up month) |

**Special cases.** The Sunday 00:00 UTC pseudo-bars, 2018-12-26 and 2019-12-26 are removed **because the rule
selects them**, not by date. Any other bar the same rule selects is removed and coded the same way. A bar the rule
selects outside a known closure gets `UNCLASSIFIED`, which triggers an abort (A1).

**H1 (derived).** An H1 bar is removed iff no M15 bar remains in its hour after the M15 repair. H3 uses only M15; the
repaired H1 exists only for the M15/H1 consistency audit.

## Repair action

- **New dataset.** The action writes `history_expansion/repaired/`, containing:
  - `xauusd_XAUUSDm_M15_repaired.csv` and `xauusd_XAUUSDm_H1_repaired.csv`: the kept raw lines **byte-for-byte**;
  - `removal_manifest.csv`: every removed row, with its raw line, reason code, gaps and New York time;
  - `repair_summary.json`.
- **Nothing else changes.** No interpolation, no price edits, no other rows touched. Genuine outages stay gaps.
  `raw_full/` is never modified.

## Post-repair audit criteria (all must pass; otherwise the era is UNUSABLE and work stops)

| id | criterion |
|---|---|
| A1 | every removed M15 row is a one-bar session inside a known closure (no `UNCLASSIFIED`) |
| A2 | rows after = rows before − removed, and every kept row is byte-identical to its raw line (untouched-row equality = rows after) |
| A3 | no one-bar sessions remain; no bar remains on a Saturday in New York time |
| A4 | monotonic, 0 duplicates, 0 invalid OHLC, 0 misaligned timestamps; every price has 3 decimals |
| A5 | every gap in the era (2017-06-01 → 2021-08-31) is a daily break or break variant, a weekend, a holiday/early close, or one of the **preregistered known outages**: 2018-01-31 14:00 → 2018-02-02 12:45, 2018-08-16 08:45 → 09:30, 2018-08-27 02:15 → 05:30, 2018-08-27 09:30 → 10:45 |
| A6 | every era session with < 8 bars lies within a day of a known outage or a holiday/early close |
| A7 | M15 aggregated to H1 equals the repaired H1 on every hour (OHLC and tick volume), and no hour exists in only one file |
| A8 | future-leak validation (price evidence, **not** part of the rule): no session-opening bar in the repaired data has high/low/close equal to the following session's aggregate. The share of removed bars with that signature is reported. |
| A9 | the causality tests `tests/test_repair.py` pass: timestamp-only rule; future bars cannot change repairs, ATR, the compression percentile or H3 detection at or before T − 60 min |
| A10 | the H3 implementation hash is unchanged, and frozen detection runs unchanged on the repaired data |

**Also reported, descriptive only:**
- the weekly-open time by year (the 2017–18 session change);
- the daily-break pattern by year;
- year-by-year bars, spread availability and tick volume;
- small sessions;
- holiday gaps.

## Abort criteria

The era is classified **UNUSABLE** and work stops if any of these occurs:
- any A1–A10 fails;
- the rule would need prices or outcomes;
- suspicious bars remain;
- ordinary sessions are altered;
- the repair creates ambiguous session structure;
- substantial unexplained contamination remains;
- the H3 implementation would need to change.

## After a pass only

- **Detection-only count.** Run frozen-H3 **detection only** (`repair_history.py count`): no forward race, no
  controls, no rates. Report expected events by year for 2017-06 → 2021-08.
- **Proposed second independent replication** (not run):
  - **events:** acceptance bar in [2017-06-01 00:00, 2021-08-31 22:00) UTC on the repaired data;
  - **warm-up:** 2017-05 (repaired);
  - **forward races:** truncated at the end of the repaired data (2021-08-31 20:45), so no holdout bar is ever used;
  - **before running:** it would need its own preregistration.
