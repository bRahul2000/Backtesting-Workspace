# Deep-history repair — result and post-repair audit

This is data repair plus a **detection-only** H3 event count. **No H3 outcome, forward race, control or R-rate was
computed.**

- **Repair preregistration:** [DEEP_HISTORY_REPAIR_PREREGISTRATION.md](DEEP_HISTORY_REPAIR_PREREGISTRATION.md),
  SHA-256 `b1720e9b45f135b17dce39f7d4119cbedd4f75ee3c4bfd434b74b46c4c224934`. It was frozen before any repaired file
  existed and is unchanged.
- **Implementation:** `repair_history.py` (`6065e681…`), with the causality tests `tests/test_repair.py`
  (`c704e47b…`).

## Rule and removals

**Rule, timestamps only:** remove an M15 bar iff it forms a one-bar session under the frozen session rule. That
means the previous and the next bar starts are both ≥ 60 minutes away. H1 bars are removed iff their hour has no
M15 bar left.

| | rows before | removed | rows after | untouched rows byte-identical to raw |
|---|---|---|---|---|
| M15 (2017-05-01 → 2021-08-31 20:45) | 100,557 | **164** | 100,393 | **100,393 / 100,393** |
| H1 (derived) | 25,277 | 164 | 25,113 | — |

| M15 removal category | count | expected |
|---|---|---|
| `WEEKEND_SATURDAY_NY` (Sunday 00:00 UTC pseudo-bars, 2018-07-01 → 2021-08-15) | 159 | 159 |
| `CHRISTMAS_DAY` (2018-12-26 and 2019-12-26 00:00 UTC) | 2 | 2 |
| `NEW_YEARS_DAY` (2020-01-02 00:00 UTC) | 1 | 1 |
| `GOOD_FRIDAY_EVE_AFTER_CLOSE` (2018-03-30 00:00 UTC, one tick) | 1 | 1 |
| `MEMORIAL_DAY_AFTER_EARLY_CLOSE` (2017-05-29 18:45 UTC, warm-up month) | 1 | 1 |

Every removal is listed with its raw line in `repaired/removal_manifest.csv`. The selection matches the
preregistered expectation exactly: 164 rows, with no `UNCLASSIFIED`.

## Post-repair audit — PASS (A1–A10)

| id | result |
|---|---|
| A1 removals all in known closures | PASS |
| A2 untouched rows identical (100,393 / 100,393; no removed line remains) | PASS |
| A3 no one-bar sessions; no bar on a Saturday in New York time | PASS |
| A4 monotonic, 0 duplicates, 0 invalid OHLC, 0 misaligned timestamps; 3 decimals throughout | PASS |
| A5 every era gap explained or a preregistered known outage (0 unexplained beyond the 4 known outages) | PASS |
| A6 no era session under 8 bars | PASS |
| A7 M15 = H1 on all 25,113 hours (OHLC and tick volume); no hour in only one file | PASS |
| A8 future-leak validation: **0 of 1,107** remaining session-opening bars carry the next-session H/L/C signature, while **150 of the 164** removed bars do | PASS |
| A9 causality tests: 10 / 10 (the full research suite passes 51 / 51) | PASS |
| A10 H3 implementation hash unchanged (`a6c8bb40…`); detection runs unchanged | PASS |

**Era gaps, 2017-06-01 → 2021-08-31:**
- 826 daily breaks, 210 weekends, 39 holiday/early closes, and the 4 known outages.
- 6 daily-break variants: 2017-06-06 and 2017-07-11 (45-minute breaks), 2018-09-20, and **2019-03-11/12/13**. On those
  three days, just after the US DST change, the break ran New York 17:00 → 19:00 (120 min).
- Warm-up (May 2017): 4 unexplained gaps, the patchy tail of the transition. It is used for warm-up only.

**Missing-data holes.** The frozen session rule starts a new session at every gap ≥ 60 minutes, so no compression box
can span the 2-day outage or the 180- and 60-minute holes. The only sub-60-minute hole in the era is 2018-08-16
(30 min). As in the first replication, a same-session box *can* span it. This is frozen H3 behaviour and was left
unchanged.

**Session regime (descriptive; handled by the timestamp-based session rule without any change):**

| year | weekly open (New York) | typical session bars | spread field |
|---|---|---|---|
| 2017 | Sunday 20:00 (27), 19:00 (7) | 92, with 84 / 88 variants | empty (0) |
| 2018 | Sunday 19:00 (35) → 18:00 (17) | 92, with 88 variants | empty |
| 2019 | Sunday 18:00 (46) | 92 | empty |
| 2020 | Sunday 18:00 (51) | 92 | empty |
| 2021 (to 08-31) | Sunday 18:00 (35) | 92 | 75% empty |

Christmas and New Year 2017/18 reopened at Tuesday 01:00 New York. There is no precision change. Real volume is 0
throughout, and the median tick volume per M15 bar is about 600–900.

**Future leakage is eliminated.** The mechanism was the lone pseudo-bars. None remain (A3), no remaining session
opener carries the signature (A8), and the tests show that nothing after T can change repairs, ATR, the compression
percentile or H3 detection at or before T − 60 min (A9).

## Frozen-H3 expected events (DETECTION ONLY — `forward()` never called)

| year | long | short | total |
|---|---|---|---|
| 2017 (from 06-01) | 88 | 79 | 167 |
| 2018 | 104 | 137 | 241 |
| 2019 | 98 | 117 | 215 |
| 2020 | 114 | 107 | 221 |
| 2021 (to 08-31) | 77 | 86 | 163 |
| **2017-06 → 2021-08** | **481** | **526** | **1,007** |

These come from 1,084 era sessions (1,078 full). 5 warm-up events are excluded.

## Proposed second independent replication (not run)

- **Events:** acceptance bar in **[2017-06-01 00:00, 2021-08-31 22:00) UTC** on `repaired/xauusd_XAUUSDm_M15_repaired.csv`.
- **Warm-up:** 2017-05 (repaired). The pre-2017 history is daily bars only and unusable.
- **Data end:** 2021-08-31 20:45. Forward races truncate there, so no holdout bar is used.
- **Everything else:** the frozen H3 rules, controls and decision framework, under a new replication preregistration
  frozen before any outcome.
- **Power:** with about 1,007 events and a control rate near 32%, the detectable +2R lift is about **±4.5 pp** (95%
  two-sided, 80% power). A true +4.5 pp effect needs about 1,016 events, so this sample sits right at the threshold
  for the effect size seen in the first replication.

## Seals and integrity

- **Sealed data never read:** the 2021-09-01 → 2022-11-26 holdout (the repair window stops at 2021-08-31 22:00 UTC),
  the 2026 Validation and the Final OOS.
- **Evidence unchanged:** `raw_full/` and `raw/` remain unchanged evidence.
- **Studies and code unchanged:** H1–H5, the original H3 preregistration, the first H3 replication, Phase 2A,
  `mt5/`, Pine P1–P3.1 and the ledger. Nothing is committed.
