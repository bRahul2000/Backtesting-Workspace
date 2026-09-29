# Gold V2 — research design

Status: **design and non-outcome screening complete. Stopped at HARD GATE 1 (hypothesis selection).** No V2
outcome, forward return, race or directional statistic has been computed. No sealed sample has been read.

Gold V1 is frozen at `gold-v1-research-v1.0` → `fd39cdf`. It is read-only here and nothing in `research/gold_v1/` is
modified.

## 1. Methodological lessons from Gold V1 (lessons only — no V1 variants)

Sources: `research/gold_v1/GOLD_V1_FINAL_RESEARCH_REVIEW.md`, the H1–H5 reports and both H3 replication reports.

- **What failed.**
  - Continuation after an "acceptance" signal: H2 pullback-rejection, H3 compression breakout, H5 opening-range
    acceptance.
  - Fades toward a dynamic value anchor: H1 sweep + TVWAP reclaim, H4 ±2σ → TVWAP.
  - Every one anchored to **price structure the event itself created**: a session range, a box, a band, a sweep.
    None had an exogenous reason for order flow to be different at that point.
- **What the controls exposed.** Matched bars in the same session, volatility and trend context already reached +2R
  at 32–41%. Most "setups" simply reproduced the base rate of the context they selected (H2, H5 were worse; H3
  equalled it in 1,007 events). **The control, not break-even, is the opponent.**
- **MFE up, MAE up.** H3's replications raised MFE and MAE together (#1 1.74 vs 1.65 MAE; #2 1.87 vs 1.54). H5 had
  equal MFE with larger MAE. A setup that only widens the distribution is not an edge.
- **Regime instability.** H3 was +9.0 pp in 2024 and −6.5 pp in 2021, with 2017–2021 net −0.1. Year-level swings of
  ±5–9 pp are the normal noise floor.
- **Target-distance instability.** H3 development's +1R lift (+7.2) collapsed to +0.7 in replication #1. H4's
  natural target was a median 0.36R, far below the design's assumed 1–1.5R.
- **Session instability.** Apparent strengths (H1 shorts and PD references, H3 Asia, H4 long-only) were post-hoc
  slices and were never promoted. None are revisited here.
- **Sample size.** Development samples of 27–102 events (MDE ±15–29 pp) produced a best-of-five +7.6 pp that shrank
  to −0.1 pp. **V2 computes power before any test and does not run a test that cannot detect its own practical
  threshold.**
- **Data limits.**
  - No order flow or footprint. Tick volume is a broker proxy that rose about 3.5× from 2020 to 2026.
  - The spread is recorded only from 2022 (empty 2014–2020), with semantics unresolved.
  - Bid-only OHLC. M15 cannot order same-bar stops and targets.
- **Why event selection alone was insufficient.** Event definitions without an **exogenous mechanism**
  (information, institutional order placement, scheduled flow) select bars that are already volatile or trending.
  The matched control then absorbs the apparent edge. **V2 requires every candidate to name a mechanism that makes
  the event bar different from a matched control bar for a reason unrelated to recent price structure.**

## 2. V2 principles

1. **Edge before engineering.** The first test is structural: does the event beat its natural counterfactual? No R:R,
   win-rate or frequency target shapes a hypothesis.
2. **Mechanism-first candidates.** Every candidate names an economic or microstructure mechanism with published
   support, and a **hypothesis-specific counterfactual** that removes exactly that mechanism.
3. **Power before outcome.** The MDE is computed on non-outcome counts. A candidate whose development sample cannot
   detect its practical threshold is not tested.
4. **Costs enter at screening.** The spread/volatility ratio of the trade horizon is screened before selection.
   Horizons where the median spread is a large share of the expected move are rejected.
5. **Preregistration, replication, sealed confirmation.** Each is frozen before outcomes. Replication happens on
   temporally independent history before any strategy work, and sealed data are used only after Rahul approves.
6. **Few hypotheses.** Multiplicity is controlled by testing at most **2** hypotheses in the first round, each needing
   its own independent replication. The count is disclosed.

## 3. Data plan (proposed; part of the gate decision)

| role | span (UTC) | source | notes |
|---|---|---|---|
| **V2 development / first test** | 2023-01-01 → 2025-12-22 (warm-up from 2022-11-27 23:00) | committed slice `research/gold_v1/history_expansion/h3_replication/data/…_slice.csv` (`a6a503ff…`) | modern session structure; spread recorded; 770 sessions |
| **V2 independent replication** | 2017-06-01 → 2021-08-31 (warm-up 2017-05) | committed repaired file `research/gold_v1/history_expansion/repaired/…_M15_repaired.csv` (`e4dc5770…`) | 1,084 sessions; spread unavailable, so structural only; 2017–18 session-hour differences are documented |
| tertiary / descriptive only | 2025-12-23 → 2026-06-02 | Phase 2A development rows | heavily inspected by V1; never confirmatory |
| **SEALED — final confirmation only (HARD GATE 3)** | 2021-09-01 → 2022-11-26; 2026-06-03 → 07-26; 2026-07-27 → 09-18 | — | see `research/gold_v1/SEALED_DATA_REGISTER.md` |

**Disclosure.** The development and replication spans were used by V1 for **H3 outcomes only**: H3 events, their
controls, and year and month tables of H3 lifts. No V2 candidate's event definition or outcome was computed in them.
The residual risk is general familiarity with the price path (e.g. 2024–25 rally years), which is documented. It is
the unavoidable cost of reusing the only unsealed intraday history.

## 4. Candidate register (broad generation)

Primary and high-quality sources were verified by web search; the references are in §8. Each candidate below
states its mechanism, observables, prediction, counterfactual, frequency, cost sensitivity, relationship to V1 and
falsification rule.

| id | candidate | mechanism (source) | observables in our data | predicted direction | natural counterfactual | freq (dev) | cost sensitivity | distinct from V1? | falsified if |
|---|---|---|---|---|---|---|---|---|---|
| C1 | **Round-number barrier reaction** | Order clustering at round prices: take-profit orders cluster *at* round numbers (reversals), stop-loss orders just beyond them (acceleration) (Osler 2003, JF). Gold-specific psychological barriers at the $100s (Aggarwal & Lucey 2007, RFE) | first in-session touch of k×$50 levels; ATR | at first touch, price **reverses** away from the round level more often than from an arbitrary level | **placebo price grids** with identical geometry and timing (k×$50 + 17.30 and + 32.70), i.e. the same bars, volatility and direction, with only "roundness" removed | ~27/month (963) | medium: race distance must be ≥ 1 ATR (spread 3–11% of ATR) | yes: static exogenous price levels; V1 used only event-created or session-anchored levels, and V1 never had a placebo-level counterfactual | Δ(round − placebo) ≤ 0, or below the practical threshold, or not replicated |
| C4 | **Cross-session momentum (US → next Asia)** | Session-return decomposition in gold: continuation from the prior session into the Asian session (lag-1 ≈ +0.13 for gold; Wei, SSRN 7257240). Consistent with eastward shift of marginal physical pricing post-2022 and late-informed / infrequent-rebalancing flows (Gao et al. 2018; Bogousslavsky 2016) | US window return (08:00–17:00 NY); next Asia window (00:00–07:00 UTC) | the next Asia return has the **same sign** as the US-window return | a **sign-shuffled** benchmark: the same Asia windows with the US sign taken from a different day. This removes predictive content and keeps drift | ~21/month (741 pairs) | low: multi-hour hold, spread ≪ window σ | yes: a daily return-predictability relation across sessions; V1 tested only intraday structural setups | b ≤ 0, or below the cost-based threshold, or not replicated (the pre-2022 replication is a genuine regime test) |
| C3 | Intraday time-series momentum (first → last half-hour) | Gao, Han, Li & Zhou 2018 (JFE): SPY first half-hour predicts last half-hour; also documented in commodity ETFs including gold (Resources Policy 2020) and Chinese precious-metal futures | NY 09:30–10:00 (from the prior 17:00 close) and 15:30–16:00 NY windows | same sign | sign-shuffled benchmark | ~21/month (743) | **high**: 30-min hold, where the spread is ~2–8% of window σ ≈ the expected edge | yes | as C4 |
| C2 | LBMA auction window pressure | Caminschi & Heaney 2014 (JFM): leakage and returns in the minutes after the PM fix start (pre-2015). Nilsson 2015: negative pressure into auctions outside US hours; no persistent pressure in US hours; unchanged by the 2015 ICE auction | M15 bars 10:15–10:30 / 14:45–15:00 London | negative pre-AM-auction drift | time-of-day placebo windows | ~21/month × 2 | **very high**: the documented effects are minutes long, M15 cannot isolate them, and the spread is 3–11% of one bar's ATR | yes | — |
| C5 | Unconditional session drift (Asia up / US down) | Practitioner / press reports of an H1-2026 Asia-vs-US divergence (FXStreet 2026); Wei (SSRN) | session returns | Asia long / US short | none clean (unconditional drift) | daily | low | yes | — |
| C6 | 08:30 ET release-shock drift or reversal | US macro news moves gold "swiftly" (Elder, Miao & Ramchander 2012, JBF); no calendar is available locally | 08:30 NY bar range ≥ 2 ATR | drift or reversal (theory ambiguous) | same-size shocks at non-release times | ~9/month (315) | medium–high | partly (V1 H3 used large-bar displacement) | — |
| C7 | Weekly-reopen gap fill | illiquid reopen quotes and dealer inventory | Sunday 18:00 NY gap | fill | same-size intraday gaps | ~3/month (97) | **very high** (the widest spreads are at reopen) | yes | — |
| C8 | Jump / realized-volatility reversal | jump-robust RV literature (bipower variation) | bars ≥ k × local σ | reversal | non-jump large bars | frequent | high | **no**: a disguised H4 (fade) / H3 (displacement) | — |
| C9 | Cross-market lead-lag (USD, silver, yields) | USD numéraire; gold/silver relative value | **not in local data**; needs new MT5 exports | — | — | — | — | yes | — |
| C10 | Month- or quarter-end USD rebalancing | FX fixing flows | calendar | — | — | 12 / year | — | yes | — |
| C11 | Volatility seasonality / HAR | RV is predictable, direction is not | ATR, RV | none (non-directional) | — | — | — | yes | — |

## 5. Screening without outcome mining

Script `screening/screen_candidates.py` → `screening/screening_results.json`. It uses counts, volatility and spread
only; no returns.

| | V2 development 2023–2025 | V2 replication 2017-06 → 2021-08 |
|---|---|---|
| sessions | 770 | 1,084 |
| C1 $50 first touches (of which $100) | **963** (454) | **690** (411) |
| C1 placebo-grid touches (+17.30 / +32.70) | 1,063 / 1,104 | 701 / 776 |
| C1 MDE, Δ proportion vs 2 placebo grids | ±5.5 pp | ±6.5 pp |
| C4 US → next-Asia pairs; detectable correlation | 741; 0.103 | 1,042; 0.087 |
| C3 valid days; detectable correlation | 743; 0.103 | 1,046; 0.087 |
| C6 08:30 shocks (placebo pool) | 315 (1,212) | 377 (1,596) |
| C7 weekly gaps ≥ 0.5 ATR | 97 | 155 |
| median spread / median M15 ATR | 2023 10.7% · 2024 7.2% · 2025 3.3% | unavailable (spread field empty) |

**Screening scores** (mechanism quality, counterfactual cleanliness, data availability, independence from V1,
power, cost, degrees of freedom):

| id | mechanism | counterfactual | data | V1-independent | power | cost | DoF | verdict |
|---|---|---|---|---|---|---|---|---|
| **C1** | strong (bank order-book evidence plus a gold-specific study) | **excellent** (placebo levels share every confound except roundness) | yes | yes | ±5.5 pp dev, ±6.5 pp rep | OK at d ≥ 1 ATR | low (grid fixed at $50 a priori; d fixed) | **SHORTLIST #1** |
| **C4** | moderate–strong (recent gold-specific evidence; regime-linked) | good (sign-shuffle keeps drift, removes prediction) | yes | yes | r ≥ 0.10 dev, ≥ 0.09 rep | **low** | low (fixed session windows) | **SHORTLIST #2** |
| C3 | strong in equities; weaker for spot gold | good | yes | yes | r ≥ 0.10 | **cost-dominated** at 30 min | medium (window choice for a 23-h market) | reserve (only if C4's family is not chosen) |
| C2 | faded post-2015 per Nilsson; effect minutes long | good | M15 too coarse | yes | fine | **prohibitive** | low | reject |
| C5 | regime drift, no mechanism-specific counterfactual | none | yes | yes | — | low | — | reject (a V1 lesson-5 risk; C4's shuffle benchmark covers the drift) |
| C6 | literature says the response is complete within minutes | OK | no calendar | partial | ~±9 pp | high | medium | reject |
| C7 | plausible | OK | yes | yes | **too low** (97) | prohibitive | low | reject |
| C8 | — | — | yes | **no** | — | high | — | reject (V1 variant) |
| C9 | plausible | — | **missing data** | yes | — | — | — | defer (needs XAG/EURUSD/US10Y export approval) |
| C10 / C11 | — | — | — | — | too low / non-directional | — | — | reject |

## 6. Shortlist and draft preregistration outlines (NOT frozen)

These drafts show the intended design. **Nothing is frozen and no outcome has been computed.** The exact texts are
frozen and hashed only after Rahul selects (HARD GATES 1 → 2).

### C1 — Round-number barrier reaction (recommended primary)

- **Levels.** L = k × $50, fixed a priori. $100 levels are a descriptive subset only.
- **Placebo grids.** k × $50 + 17.30 and k × $50 + 32.70 (non-round, and not on any $10 level).
- **Event.** The first touch of L in a session from a side:
  - from below: prior close < L ≤ high;
  - from above: prior close > L ≥ low;
  - the session's first bar is excluded.
- **Race.** Anchored at L with d = 1.0 × ATR(14) of the previous bar, and started from the **next bar**:
  - the touch bar's close must lie strictly inside (L − d, L + d);
  - a touch bar that already reaches L ± d is counted as `resolved_in_touch_bar` and excluded, symmetrically for
    placebo events;
  - **reversal** = away from the approach side, **continuation** = through L;
  - same-bar double hits are `ambiguous`, never resolved favourably;
  - the race runs at most 32 bars within the session, otherwise `none`.
- **Primary metric.** Δ = P(reversal first | round) − P(reversal first | placebo), pooled over both approach sides.
- **Statistics.** A day-clustered bootstrap (resample sessions; 5,000 draws; fixed seed).
- **Practical threshold.** Δ ≥ +5.0 pp (the V1 bar). At d = 1 ATR, a 1:1 fade breaks even near 52–55%.
- **Gates.** CI above 0; both approach sides ≥ 0; every leave-one-year-out Δ > 0; then independent replication on
  2017–2021.
- **Secondary.** Descriptive only: $100 vs $50-only, MFE/MAE from L, and the continuation-after-close-through
  prediction (Osler's stop-loss cascade) reported but not decision-relevant.

### C4 — Cross-session momentum, US → next Asia (recommended secondary, independent family)

- **Windows.**
  - US window: NY 08:00 → 16:59 (bar opens 08:00 … 16:45); r_US = close(16:45 bar) − open(08:00 bar).
  - Asia window: the next trading day's 00:00 → 06:59 UTC (Asia session per the V1 pipeline).
  - Entry at the open of the 00:00 UTC bar; exit at the close of the 06:45 bar.
- **Signal.** s = sign(r_US), with s = 0 excluded. No magnitude threshold.
- **Primary metric.** The edge E[s · r_Asia] minus the sign-shuffled benchmark E[s′ · r_Asia], where s′ is s from a
  randomly permuted day within the same calendar month (fixed seed, 1,000 permutations). It is equivalent to the
  predictive component net of drift, in USD and in ATR units.
- **Statistics.** A week-block bootstrap CI.
- **Practical threshold.** Edge ≥ 2 × median round-trip spread (development era), i.e. costs covered twice.
- **Gates.** CI above 0; long and short signals each ≥ 0; every leave-one-year-out positive; then replication on
  2017–2021, which is **pre-2022, and therefore also tests the regime explanation**.

### Multiplicity

If both are selected, two hypotheses are tested in round 1. Each must pass its own gates **and** its own independent
replication. No combined or best-of-two selection is used for confirmation.

## 7. HARD GATE 1 — decision required

Rahul selects which hypothesis or hypotheses to preregister: **C1**, **C4**, **both** (recommended), or C3 instead of
C4. He also approves the §3 data plan (development 2023–2025, replication 2017–2021, sealed samples untouched).
After selection, the preregistration(s) are frozen and hashed (HARD GATE 2 is satisfied by that act), and the event
studies, replication and later stages proceed autonomously until the next hard gate.

## 8. Sources (verified by search, 2026-09-29)

- Osler, C. L. (2003). Currency orders and exchange rate dynamics: An explanation for the predictive success of
  technical analysis. *Journal of Finance* 58(5), 1791–1819.
  [Wiley](https://onlinelibrary.wiley.com/doi/abs/10.1111/1540-6261.00588) ·
  [NY Fed staff report 125](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr125.pdf)
- Osler, C. L. (2005). Stop-loss orders and price cascades in currency markets. *Journal of International Money and
  Finance* 24(2), 219–241. [RePEc](https://ideas.repec.org/a/eee/jimfin/v24y2005i2p219-241.html)
- Aggarwal, R. & Lucey, B. M. (2007). Psychological barriers in gold prices? *Review of Financial Economics* 16(2),
  217–230. [Wiley](https://onlinelibrary.wiley.com/doi/10.1016/j.rfe.2006.04.001)
- Gao, L., Han, Y., Li, S. Z. & Zhou, G. (2018). Market intraday momentum. *Journal of Financial Economics* 129(2),
  394–414. [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0304405X18301351)
- Intraday return predictability: evidence from commodity ETFs and their related volatility indices (2020).
  *Resources Policy*. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC7480318/)
- Wei, W. Who moves the price? Trading-session return decomposition and cross-session momentum in gold and silver
  markets. SSRN 7257240 (working paper; abstract via search snippet, full text not accessed).
  [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7257240)
- Caminschi, A. & Heaney, R. (2014). Fixing a leaky fixing: short-term market reactions to the London PM gold price
  fixing. *Journal of Futures Markets* 34, 1003–1039. [Wiley](https://onlinelibrary.wiley.com/doi/10.1002/fut.21636)
- Nilsson, L. (2015). Did the new fix, fix the fix? An intraday exploration of the precious metal fixing. SSRN 2657767.
  [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2657767)
- Elder, J., Miao, H. & Ramchander, S. (2012). Impact of macroeconomic news on metal futures. *Journal of Banking &
  Finance* 36(1), 51–65. [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0378426611001968)
- ICE Benchmark Administration: the LBMA Gold Price replaced the London Gold Fix on 2015-03-20.
  [ICE](https://ir.theice.com/press/news-details/2015/ICE-Benchmark-Administration-to-Administer-the-LBMA-Gold-Price-from-March-2015-LBMA-Gold-Price-to-replace-the-London-Gold-Fix/default.aspx)
- FXStreet (2026-07). Gold up on the year in Asian markets, down big in the West (practitioner report, context only).
  [FXStreet](https://www.fxstreet.com/analysis/a-strange-dichotomy-gold-up-on-the-year-in-asian-markets-down-big-in-the-west-202607131959)
