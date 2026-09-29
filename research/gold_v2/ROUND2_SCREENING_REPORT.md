# Gold V2 — round 2: new-data audit and candidate screening

Status: **data acquired, hashed, audited; non-outcome screening complete. Stopped at the hypothesis-selection hard
gate.** No directional outcome has been computed on the new data. No sealed row exists in any snapshot file; a text
check found 0.

## 1. Acquisition and provenance

- **Probes.** `V2_DataProbe_Fast` took 68 s. The original `V2_DataProbe` was stopped by Rahul; its partial files are
  kept as evidence only.
- **Exports.** `V2_Export_M1` and `V2_Export_Ticks` wrote to MT5 Common Files. The files were copied read-only to
  `data/raw/` and **hashed before parsing**: 82 files, 603 MB, listed in `data/raw/SHA256SUMS`.
- **Seal handling.** The exporters refuse sealed dates internally, and the Python loader skips sealed lines by text.
  A check over every snapshot M1 and tick file found **0 sealed rows**.

## 2. Usable M1 spans (real M1, unsealed)

| symbol | real M1 starts | unsealed usable spans | pre-M1 filler |
|---|---|---|---|
| XAUUSDm | 2017-04-27 10:52 | **2017-05-01 → 2021-08-31 21:59** (needs the preregistered one-bar-session repair at M1) · **2022-11-27 23:00 → 2026-06-02** | 2014–2016 daily bars; 2017-04-27 00:00–10:00 hourly bars |
| USDJPYm | 2017-04-27 | **2017-05 → 2021-08** · **2022-11-27 → 2026-06-02** | 2014–2016 daily bars |
| XAGUSDm | 2021-07-05 | 2021-07-05 → 2021-08-31 (42 days) · **2022-11-27 → 2026-06-02** (≈ 905 days) | 2018–2020 daily bars |
| EURUSDm | 2021-07-05 | same as XAGUSDm (≈ 911 days) | 2018–2020 daily bars |
| DXYm | 2021-07-05 | same as XAGUSDm (≈ 911 days) | 2019–2020 daily bars |

**Integrity.** For every symbol: monotonic timestamps, 0 duplicates, 0 invalid OHLC and 0 misaligned timestamps.
Real volume is 0 everywhere. The XAU spread field is 0 for 2017–2020 and populated from 2021-09 onward, 200 → 160 →
280 points by era. FX and DXY spreads are populated whenever M1 is real.

## 3. Aggregation parity

| check | result |
|---|---|
| XAUUSDm M1 → M15 vs the audited development M15 (2022-11-27 → 2025-12-22) | **72,521 / 72,521 bars identical** (O, H, L, C and tick volume) |
| XAUUSDm M1 → M15 vs the repaired M15 (2017-06 → 2021-08) | all **98,318** reference bars identical. M1 adds 1,551 bars: 163 Sunday-00:00 pseudo-bars and 5 holiday 00:00 bars (**the same future-bar artifact exists in the broker M1 base**), plus **1,390 bars of 2019-12-01 → 2019-12-22 missing from the M15 export** |
| XAUUSDm M1 → H1 vs `raw_full` H1 | 2022–2025: **18,150 / 18,150** identical. 2017–2021: **24,757 / 24,757** identical (M1 has 350 more hours, from the same two causes) |

**Erratum for frozen Gold V1 (disclosed; V1 not modified).**
- **What happened.** The XAUUSDm M15 deep export (`raw_full`) has a **data hole from 2019-11-29 to 2019-12-23**, at
  the seam between the older deep load and the 2019-12-23 `raw/` export. V1's gap classifier labels any multi-day gap
  that spans a US holiday date as a "holiday/early close". This hole spans Thanksgiving Friday, so repair criterion A5
  ("every era gap explained") passed incorrectly.
- **Impact.** It is missing data, not leaked data. H3 replication #2 simply had about 3 fewer weeks of December 2019
  events, and some lookback windows spanned the hole. No V1 classification changes.
- **For V2.** The M1 export contains those days in full (20,716 M1 bars, 2019-12-01 → 12-22).

## 4. M1 cleanliness for 2017–2021 (XAUUSDm)

- **Artifact.** 177 isolated one-bar M1 sessions: 163 Sunday 00:00, 5 holiday 00:00, and 9 hourly filler bars on
  2017-04-27 before real M1 begins. The preregistered timestamp rule (a one-bar session: both neighbouring bar starts
  ≥ 60 min away) identifies all of them.
- **Other defects.** Only 7–40 intraday holes of 2–59 minutes per year.
- **Verdict: clean enough for a newly registered test**, provided the **same preregistered one-bar-session repair is
  applied at M1**, with its own frozen preregistration and audit (like the M15 repair) before any outcome. The window
  would be 2017-05-01 → 2021-08-31 21:59; that repair has not been run. No cost data exists for 2017–2020 (spread = 0).

## 5. Tick sample (2026-02-18/19; unsealed; XAU, XAG, EUR, DXY)

| | XAUUSDm | XAGUSDm | EURUSDm | DXYm |
|---|---|---|---|---|
| ticks/day | ~185k | ~107k | ~40k | ~37k |
| bid and ask present | 100% | 100% | 100% | 100% |
| millisecond timestamps | 99.9% | 99.9% | 99.9% | 99.9% |
| monotonic / crossed or locked | yes / 0 | yes / 0 | yes / 0 | yes / 0 |
| median spread (p99) | 0.264 (0.55) | 0.044 (0.055) | 0.00008 (0.0002) | 0.064 (0.11) |
| unchanged-quote ticks | 0.02% | 0.3% | 2–2.5% | 2.3–2.9% |
| NY 08–17 median inter-tick (p99; max gap) | 0.08 s (1.7; 7.9) | 0.45 s (3.0; 34) | 0.95 s (11.6; 52) | 1.0 s (12.4; 57) |
| flags | {4, 130, 134}: bid/ask change flags present; the 128 bit is undocumented (recorded, unresolved) | same | same | same |

- **Tick depth.** Broker tick history begins 2026-01-07 (XAG, EUR, DXY, JPY) and about 2026-02-11 (XAU). **Unsealed
  tick history is therefore only about Feb → June 2026.**
- **Uses.** Ticks support execution and spread modelling. They cannot support multi-year hypothesis tests.

## 6. Does M1 resolve C1 touch ordering? (counts only, development events 2023–2025)

| | events | touch ordering unresolvable at **M15** | unresolvable at **M1** |
|---|---|---|---|
| round $50 levels | 963 | 50.9% | **4.7%** |
| placebo levels | 2,167 | 44.4% | **5.1%** |

M1 resolves about **90%** of the ambiguity. The measurement reports resolvability only, never which side won.

## 7. Cross-market alignment with XAUUSDm (inside each series' valid span)

| pair | XAU minutes with a same-minute bar | XAU M15 with an M15 bar | notes |
|---|---|---|---|
| XAGUSDm 2022-11 → 2026-06 | 99.6% | 99.96% | misses concentrate at 18–19 NY (the reopen) and 16 NY |
| EURUSDm 2022-11 → 2026-06 | 99.8% | 100% | FX opens Sun 17:05 NY vs metals 18:05; FX has extra bars outside XAU hours |
| DXYm 2022-11 → 2026-06 | 99.98% | 99.98% | same FX schedule |
| USDJPYm 2022-11 → 2026-06 | 99.9% | 100% | — |
| USDJPYm 2017-05 → 2021-08 | 99.8% | 99.98% | worst NY-hour coverage 87.7% |

Alignment is sufficient for M1/M15 cross-market work on the same broker clock (UTC+0).

## 8. Candidate families — screening verdicts (no outcomes)

| family | verdict | reason |
|---|---|---|
| **A. Round-number continuation (stop cascade)** — RESULT-GENERATED origin, disclosed | **viable, with a constraint** | M1 resolves ordering (≈5% ambiguous). The first test must be on **2017-05 → 2021-08 M1** (repaired), where no C1 outcome was ever computed: ≈ 690 round / 1,477 placebo events, detectable Δ ≈ ±5.5–6 pp. **Constraint:** 2023–2025 generated the idea and cannot confirm it. A second independent sample would be 2026-01 → 06 (≈ 150 events, too small) or a sealed sample, so confirmation would eventually need a sealed-data decision. |
| **C. Gold vs USD decomposition (residual reversal)** | **viable (strongest mechanism among the cross-market families)** | Liquidity-driven non-fundamental moves reverse, fundamental ones persist (Da, Liu & Schaumburg 2014, *MS*). Events are gold M15 moves unexplained by the USD proxy. About 630 events per year per proxy. Designs: **DXYm** development 2023–24 (~1,300) → replication 2025–26H1 (~935), or **USDJPYm** development 2023–25 (~1,900) → replication 2017–21 (~2,700, M1 repair needed). Detectable ≈ ±4–6 pp. **Caveats:** the proxy explains only about 13–22% of gold M15 variance, so "residual" ≠ "non-fundamental" for gold; USDJPY carries a safe-haven (JPY) confound. |
| B. Gold–silver lead-lag / dislocation | reject for a gold-only algo | the literature says silver adjusts and gold leads; a ratio trade needs two legs; no pre-2021 M1 for silver |
| D. Yield-conditional response | reject (data) | no intraday yields at the broker; only external daily data |
| E. Cross-market shock propagation | reject | FX and gold are simultaneous on one broker clock; minute-horizon edges would be spread-dominated (XAU spread ≈ 0.26 vs M1 ranges) |
| F. Quote / spread / liquidity state | reject (data) | tick history is only about Feb → Jun 2026 unsealed, far too short |
| G. Session transitions at M1 | reject | a weak mechanism, close to rejected drift ideas; no clean counterfactual |

## 9. Decision required (hard gate)

1. **Which family, or families, to preregister:**
   - **A** (round-number continuation, first test on repaired 2017–2021 M1), which needs an M1 repair preregistration
     first;
   - **C** (USD-residual reversal), with a proxy and split choice: DXYm within-era, or USDJPYm cross-era;
   - both, as a new Holm family;
   - or neither.
2. **Storage of the 603 MB raw snapshot.** It is currently **uncommitted** (hashes recorded). The options are to keep
   it local with SHA256SUMS-only commits, to use Git LFS, or to commit it as-is.
