# Gold V1 — expanded XAUUSDm history: quality and coverage audit

Audit date: 2026-09-29. This is data quality only. **No H3 or other strategy outcome was computed**, and no older
history beyond the loaded span was requested.

Reproduce with `venv/bin/python research/gold_v1/history_expansion/audit_history.py`. It writes
`audit_results.json`, `gaps_M15.csv` and `gaps_H1.csv`.

## Sealed-data handling

The new export runs to 2026-09-29, so it contains the sealed 2026 Validation and OOS windows. The audit splits each
file **by timestamp text before parsing anything**:

| group | span | treatment |
|---|---|---|
| NEW | < 2025-12-23 | full quality audit (never-seen history) |
| DEV | 2025-12-23 … 2026-06-02 | full value comparison against Phase 2A (already-studied development rows) |
| SEALED | 2026-06-03 … 2026-09-18 | **line-text equality counts only**: no value parsed, no statistic, nothing printed |
| POST | 2026-09-18 20:45 → 2026-09-29 | row count only (596 M15 rows), unused |

The Phase 2A files are unchanged, and their hashes match `manifest.json`.

## 1. Raw export hashes

The files were copied from MT5 Common Files (read-only), byte-compared with the source, and hashed before analysis.
The hashes are also in `raw/SHA256SUMS`.

| file | SHA-256 |
|---|---|
| `xauusd_XAUUSDm_M15.csv` | `010ac87504b2686ffd140764d19057611c1ffed2af4f8563b7407becab35aaf2` |
| `xauusd_XAUUSDm_M15.csv.metadata.json` | `8208e20ee04f9cd20005f489e6e88a5de83c536055be45a0c22e66e969071328` |
| `xauusd_XAUUSDm_H1.csv` | `07d5d50fd12447845503a5aacf0089bca7b9073dbee056d69581cfdfde67f18f` |
| `xauusd_XAUUSDm_H1.csv.metadata.json` | `47ab9ed05c02677ceb0e1d740dc750e732e64cb75aab124cac5971ef7c8fd15e` |
| `xauusd_history_loader_status.json` | `0bf4f5a5bc9606444b02b57b3287fd385349c373d7d1ef55d53b1f5f7bece8fc` |

Provenance: Exness-MT5Trial5, XAUUSDm, MT5 CopyRates, server offset UTC+0, current bar excluded, captured
2026-09-29 09:00 server time.
- **M15:** 159,893 bars, 2019-12-23 00:00 → 2026-09-29 08:30.
- **H1:** 40,070 bars, 2019-12-23 00:00 → 2026-09-29 07:00.
- **Server's first date:** 2014-01-14. Nothing older than 2019-12-23 was requested.

## 2. Overlap with Phase 2A

| | M15 | H1 |
|---|---|---|
| header | identical | identical |
| DEV rows (2025-12-23 → 2026-06-02) | 10,355 vs 10,355: **all timestamps shared; open/high/low/close text, tick volume, spread and real volume all equal; 10,355 identical lines** | 2,591 vs 2,591: all identical |
| SEALED rows (text-only) | 7,125 Phase 2A lines, **7,125 identical**; one extra timestamp in the new export, `2026-09-18 20:45` | 1,781 identical; one extra timestamp |

The extra timestamp is the bar that was still forming when Phase 2A was captured on 2026-09-19, which the exporter
excludes. Phase 2A is therefore an exact subset of the new export: **same feed, same timestamp basis, same
precision.**

## 3. Coverage and year-by-year bar counts (NEW + DEV rows only)

| year | M15 bars | H1 bars | sessions | bars per full session | notes |
|---|---|---|---|---|---|
| 2019 (from 12-23) | 490 | 124 | 8 | 92 / 76 | includes 3 artifact bars (below) |
| 2020 | 23,729 | 5,973 | 312 | 92 (248 sessions) | **53 one-bar pseudo-sessions = Sunday artifact** |
| 2021 | 23,650 | 5,940 | 291 | 92 (250) | **33 artifact pseudo-sessions**, until 2021-08-15 |
| 2022 | 23,630 | 5,912 | 259 | 92 (249) | clean |
| 2023 | 23,538 | 5,890 | 257 | 92 (249) | clean |
| 2024 | 23,704 | 5,932 | 259 | 92 (250) | clean |
| 2025 | 23,609 | 5,911 | 260 | 92 (244) | 4 missing-bar holes (below) |
| 2026 (to 06-02, dev) | 9,821 | 2,457 | 108 | 92 (103) | identical to Phase 2A |

Across all NEW and DEV rows:
- **Ordering:** strictly increasing, with 0 duplicate timestamps, 0 misaligned timestamps and 0 invalid OHLC rows,
  in both M15 and H1.
- **M15/H1 alignment:** the M15 bars aggregated to H1 match the H1 file on all **38,139 hours**, with 0 open, high,
  low, close or tick-volume mismatches and no hour present in only one file.
- **Real volume:** 0 in every year.

## 4. Gaps and anomalies

Every M15 gap longer than one bar was classified:
- 1,279 daily breaks;
- 240 weekends;
- 67 US holidays or early closes (Christmas, New Year, Good Friday, MLK, Presidents Day, Memorial Day, Juneteenth
  from 2022, July 4, Labor Day, Thanksgiving; all checked by date);
- 170 not explained by the calendar. They are listed below.

### A. Sunday "future bar" artifact: 86 bars, 2019-12-29 → 2021-08-15, plus 2019-12-26 00:00

- **What it is.** Every weekend until mid-August 2021 has a lone bar stamped **Sunday 00:00 UTC**, isolated by gaps on
  both sides. Its high, low, close and tick volume equal the aggregate of the **Sunday-evening session 22–23 hours
  later**. For example, 2019-12-29 00:00 has the OHLC of 2019-12-29 23:00–23:45, and tick volume 1,799 vs 1,803.
- **How well it matches.** 44 of 86 match the whole Sunday-evening session exactly. The rest match on
  high/low/close and tick volume within a few ticks, with the open differing. The isolated 2019-12-26 00:00 bar
  (tick volume 35,931) is the same kind of artifact.
- **Why it matters.** These bars **contain future prices**, and each forms its own one-bar pseudo-session under the
  pipeline's session rule. They make 2019-12-23 → 2021-08-31 **unusable without a separately approved cleaning
  step**. They account for 165 of the 170 unexplained gaps (both sides of each lone bar).

### B. Missing-bar holes: 6 events, not interpolated

| hole | bars missing | effect under the frozen session rule (new session when bar starts are ≥ 60 min apart) |
|---|---|---|
| 2022-02-08 23:45 → 02-09 01:00 UTC | 4 | splits the session |
| 2025-01-03 11:45 → 12:45 UTC | 3 | splits the session (pseudo-sessions of 52 + 37 bars) |
| 2025-04-14 14:00 → 14:30 UTC | 1 | none |
| 2025-10-16 15:00 → 17:45 UTC | 10 | splits the session (13-bar tail) |
| 2025-11-28 08:00 → 08:45 UTC (Black Friday, but mid-session) | 2 | none |
| 2025-12-07 23:15 → 23:45 UTC | 1 | none |

### C. Other gap notes

No intraday open-to-previous-close jump exceeds 0.5% in any year. The largest intraday jump is 0.227%, in 2021. The
largest discontinuities are all at session reopens and are real market gaps, e.g. the 2021-08-08 22:00 Asian-open
flash crash (+2.47% reopen jump) and weekend gaps in 2022, 2025 and 2026. 11–31 bars a year have a range above 10×
the year's median range; these are volatility events, not errors.

## 5. Price, session and spread consistency

| year | price decimals | last digit 0 | close range | spread = 0 | spread median / p90 / max (points) | tick volume median / M15 bar |
|---|---|---|---|---|---|---|
| 2020 | 3 (100%) | 10.1% | 1,454–2,070 | **100%** | — (field empty) | 861 |
| 2021 | 3 | 9.7% | 1,678–1,958 | **50%** | 0 / 300 / 1,287 | 854 |
| 2022 | 3 | 10.0% | 1,617–2,069 | 0.6% | 200 / 200 / 2,080 | 955 |
| 2023 | 3 | 10.0% | 1,808–2,131 | 0.1% | 200 / 200 / 1,880 | 924 |
| 2024 | 3 | 10.0% | 1,986–2,789 | 0% | 199 / 200 / 1,199 | 1,334 |
| 2025 | 3 | 10.1% | 2,622–4,547 | 0% | 160 / 160 / 3,352 | 2,424 |
| 2026 dev | 3 | 9.9% | 4,131–5,586 | 0% | 280 / 280 / 540 | 3,033 |

- **Precision.** 3 decimals, point 0.001, in every year. The last-digit-zero share of about 10% shows genuine
  3-digit quotes, not 2-digit prices padded with a zero.
- **Timestamps and sessions.** The daily break is **New York 17:00 → 18:00 (60 min)** in every year, moving with US
  DST, which confirms a consistent UTC basis. There is a single 75-minute variant in each of 2025 and 2026. The week
  opens Sunday 18:00 New York from 2021 on; 2020's pattern is distorted by the artifact. Full sessions have 92 M15
  bars in every year.
- **Spread field.** It is not populated before 2021, mixed in 2021 and populated from 2022. The typical level changes
  from 200 (2022–24) to 160 (2025) to 280 (2026). Its semantics are unresolved, as in Phase 2A, so it is descriptive
  only. H3's rules never use spread.
- **Tick volume.** It rises about 3.5× from 2020 to 2026, a feed and participation change. H3's rules never use
  tick volume; the tick-volume ratio is relative to 20 days and is only recorded.
- **Symbol specification.** MT5 keeps no specification history. Nothing in the data suggests a change in digits or
  contract. The current specification is the 2026-09-19 snapshot. `Export_XAUUSD_Spec` was not run, because it does
  not compile as committed.

## 6. Suitability for an independent H3 replication

H3 uses only OHLC, Wilder ATR(14), the session rule and the trailing 20-session percentile of the 8-bar range.
Tick volume and spread are recorded only.
- **From 2021-09 onwards: suitable.** The data are the same feed as development, with consistent precision and
  sessions, and no artifacts.
- **2019-12 → 2021-08: not suitable as-is.** The artifact bars leak future prices and create pseudo-sessions.
- **The missing-bar holes are handled conservatively by the frozen implementation.** It starts a new session at the
  hole, so no compression box can span missing data. The only side effect is one extra short pseudo-session in the
  20-session lookback on two days in 2025. This is **not** an implementation incompatibility, and no rule change is
  needed.

## 7. Replication-period proposal (to be frozen in `H3_REPLICATION_PREREGISTRATION.md` after review)

| option | span | sessions (≥ 60 bars) | approx. H3 events at the dev rate | detectable +2R lift |
|---|---|---|---|---|
| **A (recommended)** | **2023-01-01 → 2025-12-22** | **767** | ~650 | ≈ ±5.7 pp |
| B (largest clean) | 2021-09-01 → 2025-12-22 | 1,111 | ~950 | ≈ ±4.7 pp |

**A is recommended:**
- It is the cleanest span: no artifacts, and the spread field is fully populated.
- It is well powered, since development's +7.6 pp lies beyond its ±5.7 pp detection limit.
- It spans three distinct regimes by price level (1,808 → 4,547): a 2023 range, the start of the 2024 rally, and
  the 2025 surge.
- It leaves **2021-09-01 → 2022-11-26** (320 clean sessions) **untouched as a second sealed holdout** for a later
  confirmation. B would spend it now.

**Proposed boundaries:**
- **Event window:** H3 events whose signal (acceptance) bar lies in the sessions starting **2023-01-02 23:00 UTC**
  (the first 2023 session) through the session ending **2025-12-22 21:45 UTC**.
- **End of data:** the replication stops before the 2025-12-23 trading session, which opens 2025-12-22 23:00 UTC.
  Forward races are truncated there, so **no development bar is used**.
- **Warm-up:** load from the session starting **2022-11-27 23:00 UTC**. That gives 24 full sessions before the first
  event session, against the 20 the percentile needs; it also covers ATR(14). Warm-up bars are never counted as
  events.
- **Excluded:** everything before 2021-09-01 (artifact era) and everything from 2025-12-22 23:00 UTC onward
  (development, sealed validation/OOS, and later bars).

## 8. Seals

- **Validation and OOS:** the 2026-06-03 → 2026-09-18 windows were never parsed. The only operation on them was a
  line-text equality count against Phase 2A.
- **Frozen artifacts:** H1–H5 and the H3 preregistration are unchanged.
- **Code and ledger:** `mt5/` equals HEAD, and `Export_XAUUSD_Spec` was not fixed. The experiment ledger is unchanged.
