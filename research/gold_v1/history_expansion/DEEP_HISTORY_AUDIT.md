# Gold V1 — deep XAUUSDm history audit (server earliest → 2019)

Audit date: 2026-09-29. This is history quality plus a **detection-only** H3 event count. **No H3 outcome, forward
race or control was computed.**

Reproduce:

```
venv/bin/python research/gold_v1/history_expansion/audit_deep_history.py
venv/bin/python research/gold_v1/history_expansion/count_h3_events_deep.py 2017.05.01 2017.06.01 2018.06.30
```

The first writes `deep_audit_results.json`, `deep_gaps_*.csv` and `deep_lone_bars_*.csv`.

## Snapshot

The new export (loader v2, target 2014-01-14) was copied read-only from MT5 Common Files into `raw_full/`,
byte-compared, and hashed **before parsing**. The hashes are also in `raw_full/SHA256SUMS`. The previous
2019–2026 snapshot in `raw/` is unchanged.

| file | SHA-256 |
|---|---|
| `xauusd_XAUUSDm_M15.csv` | `4724a019bf2c25c2f03e971034d6986de94174e602c3a15924dc167f3d193e43` |
| `xauusd_XAUUSDm_M15.csv.metadata.json` | `51b7fb51ffe64957a618732a1bd38ee9b0c87dac4deb5150b8a5026a63eb8716` |
| `xauusd_XAUUSDm_H1.csv` | `7de0706efccf16eada36f5e3f26ec255eb9e11eb8407c38a650da6d034fc0bc5` |
| `xauusd_XAUUSDm_H1.csv.metadata.json` | `70fd79aac0101003143a700a85b4be79e2d48525901e22f6ff044f48739aff35` |
| `xauusd_history_loader_status.json` | `eecacaa5df75ee6028f993638028ee70de1e8e3a140f5123d7024f2e0b5a600d` |

- **Loader:** `TARGET_REACHED` for both timeframes, synchronized, error 0.
- **Server first date:** 2014-01-14 00:00, the same as the terminal's first date after the run.
- **M15:** 222,635 bars, 2014-01-14 00:00 → 2026-09-29 09:00.
- **H1:** 57,296 bars, 2014-01-14 00:00 → 2026-09-29 08:00.

## Sealed-data handling and overlap

Rows are split by timestamp **text** before parsing. Only groups below 2021-09-01 were parsed. The reserved holdout,
the replication slice, development and everything later were compared to the `raw/` snapshot as **text lines
only**.

| group | M15 identical lines | H1 identical lines |
|---|---|---|
| ARTIFACT era 2019-12-23 → 2021-08-31 | 39,927 / 39,927 | 10,050 / 10,050 |
| **HOLDOUT 2021-09-01 → 2022-11-27 (sealed, text only)** | 29,364 / 29,364 | 7,347 / 7,347 |
| REPLICATION slice 2022-11-27 23:00 → 2025-12-22 22:59 | 72,521 / 72,521 | 18,150 / 18,150 |
| DEV + Validation + OOS + later (text only) | 18,081 / 18,081, plus 1 new bar (2026-09-29 09:00) | 4,523 / 4,523 |

The new export is an exact superset of the earlier evidence snapshot.

## 1–3. Earliest dates and totals

- **Earliest M15 bar:** 2014-01-14 00:00 UTC. **This is a daily bar**: its OHLC equals the first H1 bar, and its tick
  volume is 68,832.
- **Earliest H1 bar:** 2014-01-14 00:00 UTC, also a daily bar.
- **First genuine intraday M15 bars:** 2017-02-27. **Full intraday coverage** starts in May 2017.

## 6. Year-by-year bar counts (pre-2019-12-23 rows are new; 2020–2021 are from the earlier audit)

| year | M15 bars | H1 bars | sessions | typical bars per session | nature |
|---|---|---|---|---|---|
| 2014 (from 01-14) | 302 | 302 | 302 | 1 | **daily bars only** |
| 2015 | 312 | 312 | 312 | 1 | **daily bars only** |
| 2016 | 310 | 310 | 310 | 1 | **daily bars only** |
| 2017 | 16,853 | 4,996 | 1,214 | 1 (Jan–Apr) / 92 | daily until 02-26, patchy Mar–Apr, full from May |
| 2018 | 23,251 | 5,843 | 289 | 92 | full intraday; Sunday artifact from 07-01 |
| 2019 | 22,203 | 5,587 | 291 | 92 | Sunday artifact every weekend |
| 2020 | 23,729 | 5,973 | 312 | 92 | Sunday artifact |
| 2021 | 23,650 | 5,940 | 291 | 92 | Sunday artifact until 08-15 |

## Integrity checks, 2014-01-14 → 2021-08-31

- **Ordering and values:** strictly increasing, 0 duplicates, 0 misaligned timestamps, 0 invalid OHLC.
- **M15/H1 alignment:** all 27,276 hours agree exactly (OHLC and tick volume). 2,153 hours have fewer than 4 M15 bars:
  the daily-bar and patchy eras.

## 4–5. Eras and the future-bar artifact

| era | classification | evidence |
|---|---|---|
| 2014-01-14 → 2017-02-26 | **UNUSABLE** (wrong granularity) | one bar per day stamped 00:00, including Sundays, with daily tick volumes of about 70k. No M15 structure exists. |
| 2017-02-27 → 2017-05-31 | **UNUSABLE for events**; May usable as warm-up only | sparse transition: 494 / 359 unexplained gaps in March and April, 4 in May |
| **2017-06-01 → 2018-06-29** | **USABLE WITH EXPLICIT GAP HANDLING** | 92-bar sessions; daily break New York 17:00 → 18:00. Explicit gaps: a **2-day outage 2018-01-31 14:00 → 2018-02-02 12:45 UTC**, two 45-minute break variants (2017-06-06, 2017-07-11) and a stray one-tick bar on Good Friday 2018-03-30. |
| 2018-07-01 → 2021-08-31 | **CONTAMINATED / UNUSABLE as-is** | Sunday future-bar artifact every weekend (below) |
| 2021-09-01 → 2022-11-26 | CLEAN — **reserved holdout, sealed** | text-identical to the earlier snapshot, not parsed |
| 2022-11-27 → 2025-12-22 | CLEAN — used by the H3 replication | text-identical |

**The future-bar artifact:**
- **Onset.** It does not exist in the intraday era before **2018-07-01**, the first Sunday-00:00 lone bar. That is
  earlier than the December 2019 start previously known.
- **Frequency.** It appears every weekend, about 13 per quarter: 159 Sunday-00:00 bars through 2021-08-15, plus the
  holiday variants 2018-12-26 and 2019-12-26.
- **Signature.** **147 of 159** have high, low and close equal to the next Sunday-evening session up to 24:00 UTC,
  with a median tick-volume ratio of 1.0. The others differ by a few ticks.
- **Isolation.** It is confined to these lone bars. In 2018-07 → 2021-08, **309 of 312** unexplained gaps are the two
  sides of an artifact bar. The only other anomalies are 3 small holes (2018-08-16 30 min, 2018-08-27 180 min and
  60 min) and 4 short break variants. The surrounding ordinary sessions are otherwise clean.
- **Why the era is still unusable.** The frozen pipeline computes Wilder ATR over all bars, so an artifact bar's
  future prices would feed Monday's 1.5 × ATR displacement threshold. It is also counted as a session in the 20-session
  lookback. The era stays **unusable unless an approved repair removes the identified artifact bars**. No repair was
  made.

## 7. Session and specification consistency

- **Price precision:** 3 decimals in every year, with about 10% of last digits zero. There is no precision change.
- **Daily break:** New York 17:00 → 18:00 (60 min) in 2017 and 2018, the same as 2019–2026. This is consistent with
  the UTC basis across US DST.
- **Weekly open (session change).** It was Sunday **19:00–20:00 New York** in 2017–2018, against 18:00 from 2021 on.
  The Christmas and New Year 2017/18 reopenings were at **Tuesday 01:00 New York** (06:00 UTC). This is a
  trading-hours regime change, to be documented in any replication.
- **Spread:** the field is **0 in every year from 2014 to 2020**, so it is unavailable and spread/risk cannot be
  measured for these eras.
- **Real volume:** 0 in every year.
- **Tick volume:** a median of about 800–920 per M15 bar in 2017–2018, comparable to 2020–2023. In the daily-bar era
  it is about 70k per bar.
- **Price level:** about 1,157–1,366 in 2017–2018, the lowest-priced regime in the data.
- **Jumps:** no intraday open jump above 0.5% in 2017–2018. The largest reopen gap is 2017-09-04 (+0.92%).

## 8. H3 events expected (detection only — no outcomes)

These counts come from the frozen `h1_study.features`, `h3_study.h3_features` and `h3_study.detect`, unchanged.
`forward()` was never called.

| era | status | sessions | H3 events (long / short) |
|---|---|---|---|
| **2017-06-01 → 2018-06-29** (warm-up from 2017-05-01) | usable with gap handling | 279 (277 full) | **282** (129 / 153); 2017: 165, 2018: 117 |
| 2018-07-02 → 2019-12-22 | contaminated — **estimate only**, unrepaired | — | 330 (155 / 175) |
| 2019-12-23 → 2021-08-31 | contaminated | ~437 full | ~300 (rate estimate, not counted) |

**Is ~500 additional clean H3 events available? No.** Only **~282** clean events exist before the artifact, and their
detectable +2R lift is about ±8.5 pp, too weak to settle a +4.5 pp effect alone. Reaching 500+ would need an
**approved repair** of 2018-07 → 2021-08, which would add ~630 events for a total of ~910 (detectable about ±4.8 pp).

## 9. Proposed second independent replication period

- **Clean-only proposal:** **2017-06-01 → 2018-06-29**, warm-up from 2017-05-01.
  - **Explicit gap handling:** the frozen session rule breaks at the 2018-01-31 → 02-02 outage, and those events are
    flagged in their lookback.
  - **Documented session change:** the later weekly open.
  - **Spread:** unavailable.
  - **Size:** about 282 events. It is independent and clean, but underpowered on its own.

For review, with no choice made:

| option | events | notes |
|---|---|---|
| A. 2017-06 → 2018-06 only | ~282 | clean; ±8.5 pp |
| B. A + an approved, rule-based removal of the identified artifact bars in 2018-07 → 2021-08 | ~910 | ±4.8 pp. Needs a written repair rule, frozen before any outcome (e.g. drop lone bars isolated by > 60 min whose H/L/C equal the next session), plus re-audit. |
| C. A + the reserved 2021-09 → 2022-11 holdout | ~500 | spends the last clean sealed historical sample |

## 10. Seals

- **Reserved holdout (2021-09-01 → 2022-11-26):** compared as text lines only, never parsed.
- **2026 Validation and Final OOS:** compared as text lines only, never parsed.
- **Frozen artifacts:** H1–H5, the original H3 preregistration, the H3 replication preregistration and artifacts,
  and the `raw/` 2019–2026 snapshot are unchanged.
- **Code, data and ledger:** Phase 2A, `mt5/`, Pine P1–P3.1 and the ledger are unchanged. Nothing is committed.
