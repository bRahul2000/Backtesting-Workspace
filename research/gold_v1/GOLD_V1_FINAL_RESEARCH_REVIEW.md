# Gold V1 — final research review

**Status: CLOSED. Gold V1 does not justify strategy or algo construction.** No live or paper execution is enabled
from Gold V1.

| hypothesis | final classification |
|---|---|
| H1 Sweep + TVWAP reclaim | **NO EDGE** |
| H2 Trend pullback to TVWAP | **NO EDGE** |
| H3 Compression → displacement → acceptance | **FAILED TO REPLICATE** (closed) |
| H4 TVWAP ±2σ exhaustion fade | **WEAK / NO DEMONSTRATED ECONOMIC EDGE** |
| H5 New York opening-range acceptance | **NO EDGE** |

This document summarises frozen results. It does not re-derive or rewrite any of them. Every number cites an artifact
listed in §16.

## 1. Original objective

The objective was to find, by preregistered event studies on Exness XAUUSDm, an intraday Gold setup with a structural
edge over comparable bars. The target was a setup large enough (a +2R lift of ≥ 5 pp over matched controls) to
justify cost-inclusive strategy construction later. The research targets (frequency, R:R, win rate) were guides, not
acceptance criteria. Execution stayed disabled throughout.

## 2. Data and limitations

- **Phase 2A** (the development source): Exness-MT5Trial5 XAUUSDm, MT5 CopyRates (bid), 2025-12-23 → 2026-09-18.
  M15 has 17,480 bars and H1 4,372.
  - Split: development 2025-12-23 → 2026-06-02; Validation 2026-06-03 → 07-26; Final OOS 2026-07-27 → 09-18.
- **Expanded exports** (same server and symbol), verified byte-identical to Phase 2A on every overlapping line:
  - `raw/`: 2019-12-23 → 2026-09-29;
  - `raw_full/`: 2014-01-14 → 2026-09-29.
- **Limitations:**
  - There is no order-flow or footprint data. **Tick volume is only a proxy**, and TVWAP is a tick-volume proxy.
    Real volume is always 0.
  - The spread field's semantics are unresolved, and it is **empty (0) for 2014–2020**.
  - 2014-01 → 2017-02 is daily bars only.
  - 2018-07 → 2021-08 carried a Sunday future-bar artifact (§7).
  - The session regime changed: the weekly open was 1–2 h later in 2017–18.
  - All development results come from one ~5-month, unusual regime: a rally to the dataset high, a same-day crash on
    2026-01-29, and a correction.

## 3. H1–H5 definitions

The exact rules are in each `h*/preregistration.md` (H2–H5) and in `h1/methodology.md`.

- **H1:** a sweep of the Asia high/low or PDH/PDL, then a close back through session TVWAP within 4 bars. The stop is
  the sweep extreme.
- **H2:** in an H1-ER ≥ 0.35 trend, with TVWAP slope in the trend direction, the first touch of TVWAP or the
  trend-side 1σ after a new session extreme. A rejection candle is required (close location ≥ 0.65, body ≥ 0.5). The
  stop is the pullback extreme.
- **H3:** an 8-bar same-day compression at or below the 20th percentile of the trailing 20 sessions, then a
  displacement (≥ 1.5 × ATR(14), body ≥ 0.6, breakout-direction body) closing beyond an intact box, then acceptance on
  the next bar. The stop is the opposite side of the displacement bar; entry is the next open.
- **H4:** in the range regime (ER ≤ 0.15), a close outside TVWAP ± 2σ, then a close inside ± 1σ within 2 bars. The
  target is the live TVWAP; the stop is the streak extreme.
- **H5:** the New York 09:30–10:00 opening range, then two consecutive closes strictly outside by the 12:45 New York
  bar. The stop is the OR midpoint.

## 4. Development results (2025-12-23 → 2026-06-02; frozen)

| | events | primary metric | event vs control | lift (pp) | 95% CI | class |
|---|---|---|---|---|---|---|
| H1 | 102 | P(+2R before −1R) | 34.0% vs 35.4% | −1.3 | −11.8 … +9.8 | NO EDGE |
| H2 | 27 | P(+2R) | 18.5% vs 41.5% | −23.0 | −42.2 … −2.2 | NO EDGE |
| H3 | 77 | P(+2R) | 41.3% vs 33.8% | +7.6 | −4.8 … +21.1 | WEAK |
| H4 | 33 | P(TVWAP before −1R) | 76.7% vs 65.2% | +11.5 | −6.4 … +27.8 | WEAK; expectancy −0.030R gross, −0.048R after spread; natural target a median 0.36R |
| H5 | 98 | P(+2R) | 27.7% vs 40.8% | −13.2 | −24.5 … −2.0 | NO EDGE |

The consolidated review ranked H3 best by point estimate but noted that its z ≈ 1.15 was what a best-of-five null
would produce about half the time. It recommended expanding history rather than spending Validation.

## 5. Expanded-history work

- **History loading.** A history-only MQL5 loader (`history_expansion/tools/`, no trading code) loaded XAUUSDm back to
  the server's first date (2014-01-14). The unchanged `Export_XAUUSD_History` exported it. `Export_XAUUSD_Spec` does
  not compile as committed (`DAY_SUNDAY`/`DAY_SATURDAY`) and was left unfixed.
- **Quality audits.** `HISTORY_QUALITY_AUDIT.md` and `DEEP_HISTORY_AUDIT.md` established:
  - exact equality with Phase 2A on all overlaps;
  - the eras: daily-only 2014 → 2017-02; clean intraday 2017-06 → 2018-06; artifact 2018-07 → 2021-08; clean
    2021-09 onward;
  - a consistent 3-decimal precision;
  - a New York 17:00 → 18:00 daily break in all years;
  - the missing-bar holes and the session-regime differences.

## 6. H3 replication #1 (2023-01-01 → 2025-12-22)

Preregistered (`4200ea85…`): 526 events. **+2R: 36.8% vs 32.3%, lift +4.5 pp, 95% CI +0.04 … +9.1.**
- Positive in all three years (2023 +0.7, 2024 +9.0, 2025 +3.7).
- Long +4.5, short +4.4 pp.
- **INCONCLUSIVE:** it passed the statistical tests only by a 0.04 pp margin and failed the ≥ +5 pp practical bar.
- The +1R lift collapsed to +0.7 pp, and spread was about 4.1% of 1R in that era.

## 7. Deep-history repair methodology

- **The defect.** From 2018-07-01 to 2021-08-15 every weekend had a lone Sunday 00:00 UTC bar carrying the next
  session's high, low and close (147 of 159). It leaked future prices into Wilder ATR.
- **The repair.** Preregistered (`b1720e9b…`) before any repaired file existed. The rule used **timestamps only**:
  remove an M15 bar iff it forms a one-bar session under the frozen session rule (neighbouring bar starts ≥ 60 min
  away). No prices and no H3 information were used.
- **What was removed:** exactly the predicted **164 M15 rows** (159 Saturday-NY pseudo-bars, 2 Christmas Day, 1 New
  Year's Day, 1 Good Friday eve stray bar, 1 Memorial Day stray bar) plus 164 derived H1 hours.
  - 100,393 of 100,393 kept rows are byte-identical to raw.
  - The audit A1–A10 passed, including 0 of 1,107 remaining session openers carrying the future signature.
  - The causality tests (10/10) show that nothing after T changes repairs, ATR, the compression percentile or H3
    detection at or before T − 60 min.

## 8. H3 replication #2 (repaired 2017-06-01 → 2021-08-31)

Preregistered (`2bf602e6…`), with separate gates for statistical persistence (A) and practical size (B, ≥ +5 pp,
unchanged).

- **Result:** 1,007 events. **+2R: 33.2% vs 33.2%, lift −0.05 pp, 95% CI −3.2 … +3.3.**
- **Targets:** H3 is at or below controls at every target (+1R −0.9, +3R −1.3, +4R −1.5).
- **Years:** 2017 −1.7, 2018 +4.1, 2019 +2.3, 2020 −1.0, 2021 −6.5.
- **Sides:** long +2.2, short −2.1.
- **Months:** 25 positive, 25 negative, 1 zero.
- **Leave one year out:** −1.4 … +1.2 pp.
- **Excursions:** median MAE32 is worse than the controls' (1.87 vs 1.54).
- **Classification:** Gates A and B both fail → **FAILED TO REPLICATE**.

## 9. Independent evidence synthesis (replications only; development never pooled)

The method was preregistered: fixed-effect inverse-variance pooling of the two standalone lifts, with SEs from their
bootstrap CIs.

| | events | +2R lift | 95% CI |
|---|---|---|---|
| replication #1 (2023–2025) | 526 | +4.49 | +0.04 … +9.09 |
| replication #2 (2017–2021) | 1,007 | −0.05 | −3.17 … +3.25 |
| **pooled (fixed effect)** | **1,533** | **+1.47** | **−1.15 … +4.09** |
| random effects (DerSimonian–Laird) | | +1.92 | −2.49 … +6.34 |

Heterogeneity: Q = 2.57 (1 df, p ≈ 0.11), I² = 61%.

## 10. Statistical limitations

- **Small samples.** Development samples of 27–102 events had detectable effects of ±15–29 pp. Point estimates of
  ±5–20 pp were routinely noise.
- **Multiplicity.** Five hypotheses were tested; the best-of-five H3 estimate shrank from +7.6 to +4.5 to −0.1 pp
  across independent samples, the signature of a selection effect.
- **Controls.** The controls reused draws in thin pools (H5: 139 unique bars behind 490 draws). The event-clustered
  bootstrap does not model draws shared between events.
- **Ambiguity and truncation.** M15 cannot resolve same-bar stop-and-target ordering, so those cases were excluded,
  never resolved favourably. Races at data ends were truncated.
- **Regime dependence.** It cannot be separated from noise: replication #1 vs #2 disagreement has p ≈ 0.11.

## 11. Practical and economic interpretation

- **No hypothesis cleared a +5 pp structural lift out of sample.** Even the most favourable independent estimate,
  replication #1 at +4.5 pp, implied only about +0.06R per trade after an indicative spread. Spread was about 4% of
  1R at 2023–25 price levels.
- **Costs could not be tested in the older eras.** The spread field is empty there. A structural edge that fails
  without costs cannot survive with them.
- **H4 shows a high hit rate is not an edge.** It hit TVWAP 77% of the time but earned 0.22R per median win, so it
  sat exactly at break-even before costs.

## 12. Why H3 is closed

The confirmatory, better-powered replication (#2) found no effect: its interval excludes lifts above about 3.3 pp.
The pooled independent interval (−1.2 … +4.1) excludes the frozen +5 pp practical threshold. H3 had its
preregistered chance in two independent samples totalling 1,533 events. Further H3 tests would be post-hoc searching.

## 13. Why no holdout, Validation or OOS should be spent

- **No candidate survived.** Sealed samples exist to confirm a candidate that has already passed; here none did.
- **The samples are too small to decide the question.** The reserved holdout (about 220 events, ±10 pp) and
  Validation (about 31, ±26 pp) cannot settle a sub-5 pp effect.
- **Spending them would leave nothing clean.** Using them on H3 would be a rescue attempt, and it would leave no clean
  data for genuinely new hypotheses. They stay sealed; see [SEALED_DATA_REGISTER.md](SEALED_DATA_REGISTER.md).

## 14. Lessons for Gold V2 (lessons only — no V2 design)

1. **Weak raw event-study lifts are insufficient.** A +5–8 pp point estimate with a CI spanning zero predicted nothing
   out of sample. Future candidates need a larger-sample first test, or a much larger development effect, before a
   replication is worth running.
2. **Small samples created unstable estimates.** 27–102 development events could only detect effects of ±15–29 pp.
   Power should be computed before a hypothesis is run, and a study aborted in advance if it cannot detect the
   practical threshold.
3. **High-R continuation is hard to separate from matched controls.** Matched trending or volatile bars already reach
   +2R at 32–41%. Structure-based entries mostly reproduced the base rate of their context. The controls, not break-even,
   are the real opponent.
4. **Adverse excursion matters, not just MFE.** H3's replications improved MFE while worsening MAE (#1: 1.74 vs 1.65;
   #2: 1.87 vs 1.54). H5 had equal MFE and larger MAE. Both sides of the distribution must be judged.
5. **Session- or regime-specific strength can vanish over longer history.** Apparent strengths in dev slices (H1
   shorts and PD references, H3 Asia, H4 long-only) were never promoted. The longer history showed that year-level
   swings of ±5–9 pp are normal.
6. **Target selection after observing data must be avoided.** The preregistration discipline, the fixed thresholds
   and the refusal to rescue kept every conclusion interpretable. Continue it.
7. **Order-flow and footprint data are unavailable.** Any "order-flow" idea on this feed is a price and tick-count
   proxy and must be labelled as such.
8. **Tick volume is only a proxy.** It is broker-specific and rose about 3.5× from 2020 to 2026. TVWAP-anchored ideas
   (H1, H2, H4) all failed on it.
9. **Realistic costs must enter earlier.** Spread was about 1–4% of 1R, and larger for tight structural stops. The
   next research stage should include a defensible cost model as soon as a structural effect survives its first
   independent test, and should use eras where spread is recorded (2022 onward).
10. **Future hypotheses should be structurally different, not H1–H5 variants.** Parameter or filter variants of
    closed hypotheses would reuse the same data and inherit their selection bias.
11. **Data provenance must be audited before use.** The Sunday future-bar artifact would have leaked future prices
    into ATR if the older history had been used unaudited. Loading and repairing history takes its own preregistered
    audit.

## 15. Forbidden post-hoc H3 rescue ideas

None of these may be tested on any Gold V1 data or sealed sample:
- long-only H3 (replication #2's long +2.2 pp) or short-only;
- year, month or regime filters (e.g. "2023–2025 only", excluding 2021 or 2017, trend-only or range-only);
- session filters (e.g. Asia-only, which was a dev observation) or hour/weekday filters;
- changing the compression percentile, the 8-bar window, the 20-day lookback, the 1.5 × ATR or 0.6 body thresholds,
  the ATR period, the same-day rule, the intact-box rule or the body-direction rule;
- changing the acceptance definition (e.g. 2-bar acceptance, closing beyond a buffer) or the acceptance-shape
  subsets (`continues`, `stalls`, `wick_inside`);
- changing the stop (ATR buffers, box-side stops), the entry (limit or retest entries) or the targets (e.g.
  re-selecting +3R, which was +5.0 pp in replication #1);
- re-weighting or re-matching controls, or changing the CI method after seeing results;
- pooling development into confirmatory inference, or re-running the synthesis with a different weighting;
- using the reserved 2021-09 → 2022-11 holdout, the 2026 Validation or the Final OOS to "break the tie";
- adding volume, TVWAP, spread or volatility filters to H3;
- re-repairing the 2018–2021 history, or using the unrepaired era.

## 16. Artifact and hash references (SHA-256)

| artifact | hash / location |
|---|---|
| research design | `GOLD_V1_RESEARCH_DESIGN.md` `acb8c421…` |
| H1–H5 frozen folders | `h1/`–`h5/`, 67 files; hashes in `history_expansion/gold_v1_state_hashes.txt` |
| H2 / H3 / H4 / H5 preregistrations | `89e22514…` / **`c481f8a1…`** / `92f25167…` / `cfeda52f…` |
| consolidated H1–H5 review | `H1_H5_CONSOLIDATED_REVIEW.md` `ec031000…` |
| Phase 2A M15 / H1 | `dee9fb6f…` / `824a2ce0…` (`data/exness/gold/phase2a/`) |
| expanded export `raw/` M15 / H1 | `010ac875…` / `07d5d50f…` |
| deep export `raw_full/` M15 / H1 | `4724a019…` / `7de0706e…` |
| history loader v2 (.mq5 / .ex5) | `7697a439…` / `971e1953…` (v1 archived: `4f91f5c1…` / `9e3da862…`) |
| H3 replication #1 preregistration / slice | **`4200ea85…`** / `a6a503ff…` (`history_expansion/h3_replication/SHA256SUMS`) |
| repair preregistration | **`b1720e9b45f135b17dce39f7d4119cbedd4f75ee3c4bfd434b74b46c4c224934`** |
| repaired M15 / H1 / removal manifest | `e4dc5770…` / `0d1fb20d…` / `9716c063…` (`history_expansion/repaired/SHA256SUMS`) |
| H3 replication #2 preregistration | **`2bf602e6fea1aa403be521f3cc726c0344b7fee416c0af5650324f7fcfe662e7`** |
| replication #2 outputs | `history_expansion/h3_replication_2/SHA256SUMS` (17 files; events `287bf29b…`, decision_gate `8e2a265b…`) |
| frozen code | `h1/h1_study.py` `e2ec6884…`, `h1/h1_report.py` `71232d22…`, `h3/h3_study.py` `a6c8bb40…` |
| research tests | `research/gold_v1/tests/`: 51 passed |
| sealed samples | [SEALED_DATA_REGISTER.md](SEALED_DATA_REGISTER.md) |
