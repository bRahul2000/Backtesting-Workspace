# Gold V1 — history expansion audit (deliverable #1)

Audit date: 2026-09-29. **No H3 outcome was computed**, and no older bar was exported or loaded by this audit.
Validation and final OOS remain sealed.

## 1. Frozen state recorded before any history work

- **H3 preregistration** `research/gold_v1/h3/preregistration.md`: SHA-256
  `c481f8a11da8428df4892d32c9ca3044e292726cb3f0320965f4fcc25339c59e`. It matches the hash taken when it was frozen,
  and it is not edited.
- **Frozen study state:** 73 files, hashed into [gold_v1_state_hashes.txt](gold_v1_state_hashes.txt). They are H1–H5
  (67 files, identical to their closed state), `H1_H5_CONSOLIDATED_REVIEW.md`, `GOLD_V1_RESEARCH_DESIGN.md` and the
  four research test files.
- **Phase 2A source files** are unchanged, and their hashes match `manifest.json`:
  - `xauusd_XAUUSDm_M15.csv`: `dee9fb6f…ee4e4`
  - `xauusd_XAUUSDm_H1.csv`: `824a2ce0…d348b`
- **Exporter** `mt5/Export_XAUUSD_History.mq5`: `3379862f0d0ed5299f7c79b743d98f88b1640f12a019caf944bdd41dd257cd3c`.
  It is not modified.

## 2. What is available locally today

| source | XAUUSDm M15 | XAUUSDm H1 |
|---|---|---|
| Phase 2A export (`data/exness/gold/phase2a/raw`), Exness-MT5Trial5, captured 2026-09-19 on a Windows terminal (`C:\Users\LEXODD\…`) | 2025-12-23 00:00 → 2026-09-18 20:30 UTC, **17,480 bars** | 2025-12-23 00:00 → 2026-09-18 19:00 UTC, **4,372 bars** |
| This Mac's MT5 (Wine, `net.metaquotes.wine.metatrader5`), same server Exness-MT5Trial5: bar cache `Bases/Exness-MT5Trial5/history/XAUUSDm/` | **2026 only** (`2026.hcc`); not exported | 2026 only |

**Clean XAUUSDm history available right now is about 9 months, all of it already in Phase 2A.** There is no older
comparable history on disk.

## 3. Evidence on where the limit is

- **The exporter is not the limit.** It calls `Bars(symbol, tf)` and copies every completed bar the terminal holds
  (`CopyRates` from shift 1). It has no date or count argument.
- **Phase 2A was limited by the terminal's local cache, not by a count cap.** M15 and H1 both start at 2025-12-23
  00:00 but have different bar counts. A "Max bars" cap would truncate both to a count; a shared start date means
  that was simply where the terminal's cached M1 history began.
- **The broker server serves multi-year history.** On this Mac's terminal and the same Exness-MT5Trial5 server,
  BTCUSDm has cached history files for **2021, 2022, 2023, 2024, 2025 and 2026**; BCHUSDm has 2024–2026. XAUUSDm has
  only 2026, because older gold history has never been requested. The limit therefore looks **terminal-side**, not
  broker-side. **This is not yet verified for XAUUSDm specifically:** how far back Exness keeps XAUUSDm M1 history
  is unknown until a download is attempted.
- **There is a count cap to raise.** This Mac terminal has `common.ini [Charts] MaxBars=100000`. The earlier BTCUSDm
  M15 export stops at 100,239 bars (from 2023-11-10), which confirms that `Bars()` is capped by this setting. For gold
  (about 92 M15 bars a day, about 23,900 a year) 100,000 M15 bars is **about 4.2 years**. That is enough for the 2- and
  3-year targets but not for 5. For 5+ years, MaxBars must be set to **Unlimited**. This is a terminal setting, not a
  code change.
- **Other feed present, not used.** `MetaQuotes-Demo/history/XAUUSD` has 2025 data. It is a different broker and feed,
  so it is **not** comparable and will not be used or mixed.

## 4. Loading steps (not performed; human action in the MT5 GUI)

The auditor did not drive the MT5 GUI. Launching it logs into the Exness account, and the history download needs
chart interaction. The steps below use only history retrieval, with no trading and no code changes:

1. Open MetaTrader 5, on the account connected to **Exness-MT5Trial5** (the same server as Phase 2A).
2. Go to Tools → Options → Charts and set **Max bars in chart = Unlimited**. Restart the terminal.
3. Open an **XAUUSDm M15** chart. Press **Home**, or hold PageUp / scroll left, until the chart stops extending
   further back. Each step triggers a download of older M1 history from the server. Repeat until no older data
   loads, then check the date of the leftmost bar.
4. Open an XAUUSDm **H1** chart and do the same (it is built from the same M1 history, so it should already be
   deep).
5. Run **`Export_XAUUSD_History` unchanged**, with prefix `xauusd` and Common Files on. It writes
   `xauusd_XAUUSDm_M15.csv`, `xauusd_XAUUSDm_H1.csv` and their `.metadata.json` files into MT5 Common Files. Also run
   `Export_XAUUSD_Spec` to capture the current symbol specification.
6. Tell Claude the export is done. The files are then **read** from Common Files (never written from Python) and
   copied into `research/gold_v1/history_expansion/raw/` with hashes. The Phase 2A export is **never overwritten**.

If step 3 stops near 2025-12, the limit is broker-side for XAUUSDm. More history would then need a different
comparable source or a tick/M1 exporter, which is new work in the protected `mt5/` area and needs approval.

## 5. Planned checks once data is exported (no H3 outcomes until reviewed)

- **Bar quality:** ordering, duplicates, missing bars against the weekend, daily-break and holiday calendar, UTC
  basis, New York-anchored break timing across DST, OHLC validity, and abnormal gaps or price discontinuities.
- **Fields:** spread, tick volume and real volume, and M15/H1 alignment.
- **Overlap check:** the older export's overlap with Phase 2A (2025-12-23 onward) must be byte-for-byte or
  value-identical. This proves the same feed. The overlap is used **only** for this identity check; development,
  validation and OOS rows are not analysed.
- **Symbol consistency:**
  - **Digits:** the exporter formats every bar with the *current* `SYMBOL_DIGITS` (3). A historical 2-digit period
    would appear as trailing zeros; this will be detected from the value distribution.
  - **Session hours:** checked from the daily-break timing by year.
  - **Spread regime:** checked by year.
  - **Contract spec:** MT5 keeps no history of symbol specifications, so only the current spec can be captured.
    Historical changes can only be inferred from the data.

## 6. Proposed replication period (not yet frozen)

- **Preferred:** **2023-01-01 → 2025-12-22**, about 3 years, if the export reaches it cleanly. H3 needs 20 trading days
  of warm-up for the compression percentile, so bars from about **2022-11-25** would be loaded for warm-up only; they
  would not be counted as events.
- **If less is available:** the maximum clean span, with the limitation stated. Below about 2 years, stop, as the
  brief says.
- **Preregistration timing:** the replication preregistration (`H3_REPLICATION_PREREGISTRATION.md`) will be written
  and hashed only after the coverage is known and reviewed, and before any H3 outcome.
