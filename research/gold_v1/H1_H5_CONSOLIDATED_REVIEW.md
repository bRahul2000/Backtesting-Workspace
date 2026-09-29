# Gold V1 — Consolidated H1–H5 review

**Scope.** This is analysis only. Every figure comes from the five frozen, preregistered development studies
(2025-12-23 → 2026-06-02, Exness XAUUSDm M15, bid):
- the H1–H5 folders: `report.md`, `*_summary.json`, and the event and control CSVs;
- the preregistration of each study.

No variant was recomputed and no filter was applied. Validation (2026-06-03 → 2026-07-26) and final OOS
(2026-07-27 → 2026-09-18) were not loaded. The H1–H5 folders are unchanged.

A few figures are derived here from those frozen outputs, and each is labelled as such:
- the monthly matrix;
- the detectable effects;
- the break-even rates;
- the multiplicity estimate.

They use the preregistered metric definitions and the power formula already printed in the H2–H5 reports.

## 1. Summary

| | H1 sweep + reclaim | H2 trend pullback | H3 compression breakout | H4 σ-band fade | H5 NY opening range |
|---|---|---|---|---|---|
| preregistered class | **NO EDGE** | **NO EDGE** | **WEAK** | **WEAK** | **NO EDGE** |
| family | reversal | continuation | continuation | mean reversion | continuation |
| primary lift vs control | −1.3 pp @2R | −23.0 pp @2R | +7.6 pp @2R | +11.5 pp (TVWAP first) | −13.2 pp @2R |
| 95% CI | −11.8 … +9.8 | **−42.2 … −2.2** | −4.8 … +21.1 | −6.4 … +27.8 | **−24.5 … −2.0** |
| what the evidence says | no evidence of edge | evidence the setup underperforms | no evidence of edge; positive point estimate | no statistical edge, **negative economics** | evidence the setup underperforms |

1. **What Gold taught us.**
   - **Continuation after structural "acceptance" did not beat plain bars.** H2 and H5 were clearly worse than
     comparable bars. H3 was the only continuation idea with a positive point estimate, and it is not significant.
   - **Reversal and fade ideas either did nothing (H1) or produced hit rate without payoff (H4).**
   - **TVWAP-anchored ideas did worst.** H1, H2 and H4 all use the tick-volume VWAP proxy, and none produced a usable
     edge.
   - **The development window is one short, unusual regime.** It holds a rally to the dataset's high, a crash on the
     same day and a correction, so all five verdicts are conditional on it.
2. **Is anything strong enough to consume Validation?** No. See §5 and §8.
3. **Is H3 the best candidate or the least bad?** It is the best of five by point estimate, but the evidence cannot
   separate it from the least bad. Its lift has z ≈ 1.15. With five hypotheses tested, at least one would reach this
   by chance about half the time.
4. **Is H4 economically viable?** No. Its 76.7% hit rate sits exactly on the break-even rate implied by its small
   wins, and it falls below break-even after spread.
5. **Is 9 months of history too short?** Yes, for decisions of the size now in question. See §7.
6. **Next investment:** expanding Gold history comes first (§9). Validation stays sealed.

## 2. Normalized comparison (continuation and reversal metrics)

All rates are P(+tR before −1R), with ambiguous and unresolved events excluded, as preregistered. The control is the
matched control of each study. MFE and MAE are 32-bar medians in R.

| metric | H1 | H2 | H3 | H5 | H4 (comparability only) |
|---|---|---|---|---|---|
| final events | 102 | 27 | 77 | 98 | 33 |
| events / full month (≈ / trading day) | 19.0 (0.90) | 5.0 (0.24) | 18.3 (0.86) | 18.4 (0.87) | 5.8 (0.29) |
| long / short | 49 / 53 | 17 / 10 | 33 / 44 | 53 / 45 | 22 / 11 |
| P(+1R) event / control | 45.5% / 53.0% | 37.0% / 53.7% | 55.8% / 48.7% | 52.1% / 53.9% | 43.8% / 49.4% |
| P(+2R) event / control | 34.0% / 35.4% | 18.5% / 41.5% | 41.3% / 33.8% | 27.7% / 40.8% | 22.6% / 25.0% |
| P(+3R) event / control | 23.9% / 23.9% | 18.5% / 33.8% | 31.5% / 26.1% | 22.6% / 29.4% | 16.1% / 16.2% |
| **+2R control lift** | −1.3 pp | −23.0 pp | +7.6 pp | −13.2 pp | −2.4 pp |
| +2R lift 95% CI | −11.8 … +9.8 | −42.2 … −2.2 | −4.8 … +21.1 | −24.5 … −2.0 | −19.4 … +15.9 |
| median MFE32 event / control | 0.92 / 1.29 | 1.26 / 2.38 | 1.93 / 1.57 | 1.03 / 1.03 | 1.26 / 1.16 |
| median MAE32 event / control | 1.07 / 1.17 | 2.19 / 1.70 | 1.36 / 1.53 | 1.23 / 0.88 | 1.31 / 1.90 |
| months event > control at +2R | 2 of 6 | 1 of 6 | 5 of 6 | 1 of 7 | (primary: 5 of 7) |
| +2R lift long / short | −9.4 / +6.1 | −28.2 / −14.0 | +7.9 / +7.6 | −6.1 / −21.7 | (primary: +18.8 / −1.8) |
| median spread / risk | 0.99% | 1.90% | 1.92% | 0.98% | 1.63% |
| ambiguous events (any target) | 1 | 2 | 2 | 0 | 1 (0 in the TVWAP race) |

The 1:2 break-even is 33.3%. H2 (18.5%) and H5 (27.7%) sit below it even before costs. H1 (34.0%) sits on it. Only
H3 (41.3%) is above it, and so is its own control's rate (33.8%) — right on it.

H3 is the only study where events beat controls in MFE **and** MAE (larger favourable, smaller adverse). H2 and H5
show the reverse pattern: equal or smaller MFE with larger MAE.

## 3. H4 — structural target kept separate

H4 is a mean-reversion hypothesis, so it is **not** ranked on a 2R criterion. Its preregistered primary outcome is
P(live TVWAP reached before −1R).

| H4 metric | value |
|---|---|
| P(TVWAP before stop), events | **76.7%** (23 of 30 resolved; 3 session-end, 0 ambiguous) |
| P(TVWAP before stop), controls | 65.2% (103 of 158) |
| lift | **+11.5 pp**, 95% CI −6.4 … +27.8 |
| natural target at entry | median **0.36R** (IQR 0.16–0.57R); only 3% of events had ≥ 1R available |
| realized R at a hit | median **0.22R**, mean 0.30R |
| time to TVWAP (hits) | median 1 bar (15 min), mean 3.2 bars |
| expectancy, gross | **−0.030R** per trade (controls −0.114R) |
| expectancy, after the indicative spread | **−0.048R** per trade (controls −0.133R) |
| spread as a share of 1R / of the natural target | 1.6% / 5.8% (medians) |
| side consistency | lower-band longs +18.8 pp (22 events); upper-band shorts −1.8 pp (11 events) |

Break-even hit rates, derived here from the frozen outcomes: with a mean realized win of 0.30R against a 1R loss,
the break-even hit rate is 1/(1 + 0.30) = **76.7% gross** and about **78.1% after spread**. The observed 76.7% is
exactly the gross break-even.

**Verdict on H4: neither edge is demonstrated.**
- **No statistical edge:** the lift CI includes zero, and the sample could only detect about ±27 pp.
- **No economic edge:** expectancy is negative even at the observed hit rate. It would stay negative even if the
  +11.5 pp lift were real, because the controls' 65% sits 13 pp below break-even and H4 only reaches break-even
  itself.
- **The long-only slice does not change this.** It is a post-hoc cut of 22 events. The winning months coincide with
  the December–February rally (§6), and the preregistration required both sides.

H4 is a clear example of the design's own warning: a high win rate with a small, structurally limited target.

## 4. Statistical power and sample adequacy

The minimum detectable effect (MDE) is the lift detectable at 95% two-sided with 80% power, for n events and 5n
controls at the control's primary rate. The "events needed" columns use the same formula. These are approximate: the
reuse of control draws, noted in H5 and H4, makes real power somewhat lower.

| | events (resolved at primary) | primary CI width | MDE | events needed for a 5 pp lift | events needed for the observed lift |
|---|---|---|---|---|---|
| H1 | 94 | 21.6 pp | ±15 pp | ~860 | — (lift ≤ 0) |
| H2 | 27 | 40.0 pp | ±29 pp | ~910 | — |
| H3 | 75 | 25.9 pp | ±17 pp | ~840 | **~370** (for +7.6 pp) |
| H4 | 30 | 34.2 pp | ±27 pp | ~850 | **~160** (for +11.5 pp) |
| H5 | 94 | 22.5 pp | ±16 pp | ~910 | — |

**No evidence of edge vs evidence of no edge.** The two are different: a study can fail to find an edge because it
is too small, or it can actively show the setup is worse.

- **H2 is evidence of no edge**, strongly in sign but with a small n. The whole +2R CI is below zero (upper bound
  −2.2 pp). Every preregistered slice is negative. The absolute +2R rate (18.5%) is far below break-even. A positive
  edge is implausible. With 27 events, the size of the shortfall is imprecise.
- **H5 is evidence of no edge**, and the strongest rejection of the five. With n = 98 the CI is entirely below zero
  (upper bound −2.0 pp), both sides are negative, 1 of 7 months is positive, and the absolute +2R rate (27.7%) is
  below break-even. A modest real edge is very unlikely to be hiding here.
- **H1 is no evidence of edge.** The CI (−11.8 … +9.8) rules out a large edge above about 10 pp. It does **not** rule
  out a modest one (0–10 pp); about 860 events would be needed to see 5 pp. It is also not weak in the other
  direction: the setup is worse at +1R (−7.6 pp), and its MFE is lower than the controls'.
- **H3 is no evidence of edge, with substantial remaining uncertainty.** Plausible true lifts run from −5 to +21 pp.
  A modest real edge could have gone undetected, and so could no edge at all.
- **H4 is no evidence of edge on the primary outcome, with very wide uncertainty.** The economic test fails
  regardless (§3).

**Multiplicity** (derived here). Five hypotheses were tested.
- H3's +2R lift has z ≈ 1.15 (one-sided p ≈ 0.13). If all five setups were truly null, the chance that at least one
  shows a z this large is about **49%**.
- H4's primary lift has z ≈ 1.32 (p ≈ 0.09), about 39% under the same reasoning.

The best of five WEAK results is therefore exactly what chance alone would often produce.

## 5. H3 under special scrutiny

| item | value |
|---|---|
| events | 77 (33 long, 44 short); about 0.86 per trading day once the 20-day percentile warm-up ends (late January) |
| +1R lift | +7.2 pp, CI −4.1 … +19.1 |
| +2R lift | **+7.6 pp**, CI −4.8 … +21.1 |
| +3R lift | +5.4 pp, CI −5.6 … +17.3 |
| +4R lift | +1.2 pp, CI −8.9 … +11.9 |
| full-month consistency (Feb–May) | Feb +23.5, **Mar −15.1**, Apr +0.5, May +12.6. Two clear positives, one flat, one negative. The 5-of-6 count includes January and June, which hold 2 events each. |
| long / short | +7.9 / +7.6 pp. Consistent, while longs and shorts had very different base rates (the controls show the same gap). |
| MFE / MAE (32-bar medians) | 1.93 / 1.36 vs controls 1.57 / 1.53. Better on both. But mean MAE32 is worse (2.65 vs 2.15): a fatter adverse tail. |
| shape of the effect | the lift shrinks with target distance (+7 → +8 → +5 → +1 pp at 1–4R). Short follow-through, not a larger move. |
| MDE | ±17 pp. The observed +7.6 pp is well inside the noise band. |
| events to detect +7.6 pp | ~370, about 1.8 years at the development rate |

**Would consuming Validation now be justified? No.** The bar is high, and H3 does not clear it:
1. **H3 failed its own preregistered test.** The +2R CI includes zero. WEAK was defined in advance as "not
   established", not as "validate next".
2. **Validation cannot answer the question.** The window is 46 trading days, which gives about **39 H3 events** and
   an MDE of about ±23 pp. A true +7.6 pp lift would most likely look like noise there. Even Validation plus OOS
   together (~79 events) would give ±16 pp. A pass would be weak evidence and a fail uninformative, and either way
   the only sealed data in the dataset would be used up.
3. **Selection effect.** H3 was picked as the best of five, and about half the time chance alone produces a result
   this good (§4).
4. **The effect is regime-sensitive.** March, the first month after the peak, was clearly negative, and Validation
   covers only one further short regime.

H3 is the **best-ranked** hypothesis, not a **demonstrated** one. It is the natural candidate for a larger,
independent test of its frozen specification, which §7 argues should come from additional history.

## 6. Monthly stability matrix

Each cell shows the event count and the **preregistered primary lift in pp**. For H1, H2, H3 and H5 that is the +2R
event-minus-control difference. For H4 it is the TVWAP-before-stop difference, so its column is not comparable in
scale. It was derived here from the frozen CSVs with each study's own month rule: a month's events against the
controls of those events.

| month | H1 | H2 | H3 | H4 (TVWAP) | H5 | gold month-end close |
|---|---|---|---|---|---|---|
| 2025-12 (from 12-23) | 7 · −26.3 | 2 · +10.0 | — (warm-up) | 2 · +40.0 | 5 · −38.3 | 4319 |
| 2026-01 | 21 · −5.0 | 3 · 0.0 | 2 · +90.0 | 7 · +29.8 | 19 · −0.4 | 4891 |
| 2026-02 | 16 · −15.4 | 7 · −51.4 | 14 · +23.5 | 8 · +17.1 | 20 · −16.4 | 5279 |
| 2026-03 | 21 · −17.5 | 6 · −46.7 | 16 · −15.1 | 1 · +20.0 | 17 · +4.9 | 4696 |
| 2026-04 | 18 · +18.3 | 6 · 0.0 | 27 · +0.5 | 7 · +1.0 | 18 · −34.7 | 4626 |
| 2026-05 | 19 · +24.8 | 3 · 0.0 | 16 · +12.6 | 6 · −10.0 | 18 · −12.8 | 4539 |
| 2026-06 (1–2 days) | — | — | 2 · +50.0 | 2 · −44.4 | 1 · 0.0 | 4474 |

Month-end closes are from the H4 report's price-path note. Development starts at 4466 and peaks at 5586 (close) on
2026-01-29 06:15 UTC, a few hours before that day's crash.

What the matrix shows (DESCRIPTIVE):
- **Nothing works in every month.** No column is consistently positive, and the monthly cells are small (1–27
  events), so single cells swing by ±15–50 pp.
- **H1 and H4 run in opposite phases.** H1 (sweep fade) was negative December–March and positive April–May. H4
  (band fade) was positive December–March and negative May–June. The two "reversal" ideas did not share a good
  regime.
- **March is bad for continuation.** It was the first decline month after the peak. H2 (−46.7) and H3 (−15.1) both
  had their worst full month then, and H1 was also negative.
- **H5 is negative in most months regardless of regime.** That is consistent with a real structural failure rather
  than bad timing.

## 7. Regime lessons (DESCRIPTIVE — not strategy rules)

These are patterns already reported in the individual studies. None is preregistered, none is statistically
established, and none may be used as a filter.

- **Price path.** Development gold was flat end to end (4466 → 4474). It rallied into late January, peaking at 5586 on
  2026-01-29, crashed about 400 points later that same day, recovered into February, then declined March–May (H4,
  H5 reports). That is one
  rally, one shock and one correction: effectively a single regime cycle.
- **Trend vs range.** In H2, trend-regime M15 bars in the H1 trend direction (the controls) reached +2R 41.5% of the
  time, above break-even. That was not a hypothesis and is **not** a finding (H2 report). In H4, range-regime fades
  toward TVWAP lost money even for the controls (−0.11R gross).
- **Direction.** The long/short base rates differ strongly within every study (e.g. H3 controls: long +2R 25.5%,
  short 40.0%). Period drift dominates raw direction statistics, which is why every study matched direction in its
  controls.
- **Sessions.**
  - H3 Asia events beat their controls and London events trailed theirs (H3 report).
  - H4 events are 67% Asia, because the range regime concentrates there.
  - H1 London events were the weakest group (P(+2R) 18.8%).
- **Opening range.** The New York OR is traded through on both sides on 42% of days (up 73%, down 69%, which
  reproduces the design's 75% / 70%). After the first break the opposite side follows 39% of the time (H5 report).
- **Volatility.** No study showed a coherent volatility-regime pattern. Cell sizes (9–55) were too small (H1, H3, H4
  context tables).

## 8. Data limitation review

The full Gold history is **2025-12-23 → 2026-09-18, about 9 months (~231 trading days)**. Development is 113 trading
days; H3's effective span is about 90 days after its warm-up.

- **Regimes represented.** About one: a steep rally to the dataset's high, a same-day crash and a correction,
  all at the highest price levels in the data and in a volatile market. There is no low-volatility range year, no rate-cycle turn and no multi-month
  trending decline. All five hypotheses were judged inside this one possibly unusual regime. A setup that fails here
  could work elsewhere, and the reverse is also true.
- **Year-by-year analysis.** Impossible. There is not a single complete year, and no seasonal or cyclical repetition.
- **Power.** At the development rates, even the most frequent setups produce about 100 events. Detectable effects are
  ±15–29 pp, while realistic intraday edges are about 3–10 pp. The current data can reject bad setups (H2, H5) but
  cannot confirm good ones.
- **Remaining sealed data.** Validation plus OOS is about 93 trading days, less than development. It cannot reach
  the power a confirmation needs (§5).

**What more history would buy** (derived; at the development event rates, assuming comparable data):

| history | H3 events | H3 MDE | H4 events | H4 MDE | H1 / H5 MDE |
|---|---|---|---|---|---|
| current dev (≈ 0.36 yr) | 77 | ±17 pp | 33 | ±27 pp | ±15–16 pp |
| 1 year | ~215 | ±10 pp | ~73 | ±17 pp | ±10 pp |
| **2 years** | ~430 | **±7 pp** | ~147 | ±12 pp | ±7 pp |
| **3 years** | ~650 | **±5.7 pp** | ~220 | ±10 pp | ±6 pp |
| **5 years** | ~1,080 | **±4.4 pp** | ~370 | ±7.6 pp | ±4.5 pp |

The tradeoffs:
- **Enough history.** About 2 years is the minimum at which H3's observed +7.6 pp would be detectable. About 3 years
  is the point where a 5–6 pp continuation edge becomes testable. About 5 years spans several distinct gold regimes
  (for example low-volatility range periods and pre-2024 price levels) and allows a first year-by-year stability view.
- **Older data is a different market.** Price levels, volatility, spreads and session behaviour differ. Stationarity
  is a hypothesis to be tested, not assumed. More history adds power **and** heterogeneity.
- **Feed consistency matters.** H1, H2 and H4 depend on broker tick volume (the TVWAP proxy), which is
  feed-specific. H3 and H5 use only OHLC and ATR, with tick volume merely recorded, so they are the most portable to
  a longer history. Before using any other source, its comparability with the Exness feed must be verified; the
  repository already has `research/feed_comparison/` tooling. The first step is to check how far back Exness MT5
  serves XAUUSDm M15, because only Phase 2A exists locally.
- **More history does not create edge.** It only makes the answer trustworthy, in either direction.

Older history also has a methodological advantage. It has **never been looked at**. A preregistered test of H3's
**frozen, unchanged specification** on pre-2025-12 data would be an independent out-of-sample test that is
far better powered than Validation, and it would leave the 2026 Validation and OOS windows sealed for a final
confirmation.

## 9. Validation data policy

**KEEP VALIDATION SEALED.**

- **No hypothesis earns it.** Nothing met its preregistered PROMISING bar.
- **It cannot confirm H3.** Validation cannot confirm or reject H3's +7.6 pp lift (MDE ±23 pp), so it would be spent
  without an informative answer.
- **It is the last clean data.** It and the final OOS are the only untouched 2026 data. They should be kept for a
  final confirmation of a specification that has already passed a well-powered test.
- **This decision was made blind.** Validation and OOS were not inspected to reach it.

## 10. Research decision

The options, weighed against the evidence:

- **1. Advance H3 to Validation — not supported.** H3 is WEAK by its own rule. Its lift is well inside the noise
  band and about as large as the best of five null tests would often be. Validation is too short to be decisive.
- **3. Stop Gold V1 — defensible, but premature.** H2 and H5 are rejected, H4 is economically unviable, and H1 is
  uninformative. But H3's uncertainty band still covers economically meaningful edges, and the reason nothing could be
  confirmed is mainly the sample size.
- **4. New hypothesis after expansion — not yet justified by the evidence.** No result points to a specific new
  mechanism. The patterns in §7 are descriptive and post-hoc, and a new hypothesis now would be built from them. It
  can be reconsidered after a well-powered H3 test.
- **2. Expand Gold history first — follows the evidence.** The binding constraint in all five studies is power and
  regime coverage, not a lack of ideas. Concretely:
  - establish whether at least 2 and preferably 3–5 years of comparable XAUUSD M15 data are available, preferring
    Exness MT5 history, with any other feed verified for comparability first;
  - then preregister a test of H3's frozen specification on that older, unseen history, keeping 2026 Validation
    and OOS sealed;
  - if 2+ comparable years cannot be obtained, option 3 (stop Gold V1) becomes the evidence-consistent fallback.

**Decision: 2. EXPAND GOLD HISTORY FIRST**

This review changes nothing in H1–H5: nothing committed, frozen Pine tags unchanged, execution disabled, Validation
and OOS sealed.
