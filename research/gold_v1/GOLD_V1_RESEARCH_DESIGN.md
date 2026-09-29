# Gold Strategy V1 — research design (Deliverable #1; no strategy coded, nothing committed)

Scope: XAUUSD (Exness XAUUSDm), research and simulation only. No broker execution; no change to frozen Pine phases
(`pine-p2.2-v1.0`, `pine-p2.3-v1.0`, `pine-p3.1-v1.0`) or to protected areas. All numbers below come from the
**development window only** (see §7) unless stated; validation and final out-of-sample data were not examined.

## 1. Gold data capability audit

Source: `data/exness/gold/phase2a/` — Exness-MT5Trial5, MT5 `CopyRates` broker history (bid-based candles), captured
2026-09-19 by `mt5/Export_XAUUSD_History.mq5`, registered as `EXNESS_XAUUSDM_M15` / `EXNESS_XAUUSDM_H1`.

| item | status | detail |
|---|---|---|
| Exness XAUUSD OHLC | **AVAILABLE** (short) | M15 17,480 bars, H1 4,372 bars, 2025-12-23 → 2026-09-18 (≈ 9 months, 231 trading days). The 8,427 "missing" M15 bars are market closures (daily 75-min break ≈ 21:00–22:15 UTC, weekends), not data holes: full days have 92 M15 bars |
| historical depth | **PARTIAL** | 9 months only. The exporter copies every bar the MT5 terminal holds, so deeper history is a terminal-side limit (Max bars / downloaded history), not a code limit |
| lower timeframes (M1 / M5) | **UNAVAILABLE** | the exporter writes M15 and H1 only; M15 is the finest bar |
| tick data | **UNAVAILABLE** | no Gold tick export exists (BTC has tick files from a separate capture) |
| historical bid / ask | **UNAVAILABLE** | candles are bid-based; the ask series is not stored |
| spread | **PARTIAL** | per-bar MT5 `spread` field (points; one value per bar, not a distribution): min 0.16, median 0.26–0.28, max 0.779 USD |
| tick volume | **PROXY** | MT5 `tick_volume` = number of quote updates per bar (median 2,921 on M15) — activity, not traded quantity |
| real traded volume | **UNAVAILABLE** | `real_volume` = 0 on every bar (OTC spot gold has no consolidated volume) |
| session timestamps | **AVAILABLE** | Exness server time is UTC+0; sessions must be defined DST-aware (New York moved on 2026-03-08 and London on 2026-03-29, both inside this sample) |
| request.security_lower_tf | **PARTIAL** | only M15 intrabars inside H1+ charts (P2.2 A4 native path); nothing below M15 |
| live Exness feed | **AVAILABLE** (live only) | MT5 file bridge `tv_live_XAUUSDm_*` (bid/ask quote every ~500 ms, spread, last 500 bars with tick volume) — read-only, no tick history persisted |
| symbol specification | **AVAILABLE** | digits 3, tick 0.001, contract 100 oz, volume step 0.01; commission / margin / leverage marked **unverified** in the capture |

## 2. Order-flow inputs: real vs proxy vs unavailable

| concept | status | what can honestly be used |
|---|---|---|
| footprint (bid/ask volume per price) | **UNAVAILABLE** | requires trade prints with aggressor side — not in any Zoneflow Gold source |
| delta / cumulative delta | **UNAVAILABLE** | same; an OHLC "up-bar volume minus down-bar volume" is NOT delta and will not be labelled as such |
| volume profile (true) | **UNAVAILABLE** | no traded volume |
| tick-volume profile | **DERIVED PROXY** | tick counts distributed over bar ranges — activity profile only |
| VWAP | **DERIVED PROXY** | "tick-volume-weighted average price" (weights = quote updates, typical price per bar). Called TVWAP in the research to avoid implying traded-volume VWAP |
| VWAP σ-bands | **DERIVED PROXY** | tick-volume-weighted standard deviation around TVWAP |
| participation / climax | **DERIVED PROXY** | tick-volume relative to the same hour's trailing median |
| liquidity sweeps | **REAL DATA** (price) | price exceeding a prior extreme then closing back — measurable from OHLC; the "liquidity" is an interpretation |
| displacement / acceptance | **REAL DATA** (price) | numeric bar definitions (§5) |
| spread regime | **PARTIAL** | per-bar spread field |

Consequence: V1 is a **price-structure + session + TVWAP-proxy** strategy. Footprint/order-flow claims are out of
scope unless tick or trade data is obtained (§9, data risk).

## 3. Recommended research timeframes

* **Signal/execution: M15.** Spread ≈ 3 % of a median M15 range (0.28 vs 9.8 USD) — costs are tolerable; ≈ 30
  trades/month (≈ 1.4 per trading day) is reachable at M15; M5/M1 do not exist in the data.
* **Context: H1** (trend/range regime, efficiency ratio) and **D1** (previous-day high/low, daily range).
* **Perturbation only:** M30 built from M15 and H1 signal variants (robustness, §8), never as selection.

## 4. Regimes and sessions (objective definitions; development-window observations)

Sessions (DST-aware local times, converted to UTC per bar): **Asia** 00:00–07:00 UTC (fixed); **London** 08:00–16:30
Europe/London; **New York** 08:00–17:00 America/New_York; **Overlap** = London ∩ New York. Observed M15 median range by
UTC hour: highest 13–15 UTC (≈ 15–16 USD, New York open / overlap) and 01 UTC (≈ 14 USD, Asia open); 03–11 UTC is
the quietest (≈ 6–9 USD); spread is flat (0.28) except the 21:00 UTC maintenance hour.

| regime | definition (fixed a priori, not tuned) |
|---|---|
| TREND / RANGE | H1 Kaufman efficiency ratio over 20 bars: ≥ 0.35 trend, ≤ 0.15 range (dev quartiles 0.10 / 0.21 / 0.35) |
| HIGH / LOW VOLATILITY | M15 ATR(14) percentile within the trailing 20 trading days: ≥ 70th high, ≤ 30th low |
| COMPRESSION | 8-bar M15 range ≤ 20th percentile of its trailing 20-day distribution |
| EXPANSION | bar range ≥ 1.5 × ATR(14) and body/range ≥ 0.6 (dev: ≈ 5.8 bars/day — a building block, not a signal) |
| REVERSAL / EXHAUSTION | close outside TVWAP ± 2σ followed within 2 bars by a close back inside the ±1σ band |

Policy: regimes are used as **context filters that must earn their place out-of-sample**, never as separate
per-regime rule sets tuned to history.

## 5. Candidate feature library

| group | feature (exact definition) | data class |
|---|---|---|
| TVWAP | session TVWAP (reset at the session open); distance = (close − TVWAP) / ATR; σ-band position; slope = TVWAP change over 4 bars / ATR; reclaim = close crosses back over TVWAP after ≥ 2 closes on the other side | proxy |
| structure | swing high/low = pivot with 3 bars each side (confirmed 3 bars late — no lookahead); break of structure = close beyond the last confirmed swing; previous-day high/low; session high/low so far | real |
| liquidity | sweep = high > reference extreme (Asia high, PDH, last swing) and close < it on the same or next bar; failed breakout = close beyond a range then close back inside within 2 bars; reclaim after sweep | real |
| momentum | body/range; close location = (close − low)/(high − low); ATR expansion = range / ATR(14); consecutive directional closes | real |
| participation | tick-volume ratio = tick_volume / median tick_volume of the same UTC hour over 20 days | proxy |
| volatility | ATR(14); realized session range; compression / expansion percentiles | real |
| time | session, UTC hour, day of week | real |
| cost | per-bar spread (for cost modelling and a "spread spike" guard only) | partial |

Every feature is computed causally (values known at the bar's close); pivots carry their confirmation delay.

## 6. Strategy hypotheses (tested independently)

Break-even win rate at a realized R:R of r = 1 / (1 + r): 1:1.5 → 40 %, 1:2 → 33 %, **1:3 → 25 %**, 1:4 → 20 %.

| id | market logic | context | trigger (numeric) | invalidation / stop | initial target | frequency guide (dev) | how it can fail |
|---|---|---|---|---|---|---|---|
| **H1 Sweep + TVWAP reclaim** | stop runs beyond the Asia range / previous-day extreme during London or New York are faded when price re-accepts value | London / New York; not HIGH-vol news spikes (range ≥ 3×ATR) | sweep of Asia high/low or PDH/PDL, then a close back through session TVWAP within 4 bars, close location ≥ 0.6 in the trade direction | beyond the sweep extreme + 0.1 × ATR | fixed R multiple (1.5–4 grid); structural reference = opposite Asia extreme | London sweeps the Asia high on 35 % and the low on 30 % of days (never both); with PDH/PDL and New York ≈ 0.8–1.2 setups/day | sweeps that are genuine breakouts (trend days); reclaim too late (stop too wide); Asia range too small |
| **H2 Trend pullback to TVWAP** | in an efficient H1 trend, pullbacks to value continue | H1 ER ≥ 0.35, TVWAP slope in trend direction | first touch of TVWAP or the ±1σ band after a new session extreme, rejection bar: close location ≥ 0.65, body/range ≥ 0.5 | beyond the pullback swing or 1.0 × ATR | 2–3 R, trail variants later | TVWAP touches 07–20 UTC ≈ 7/day before context | trend exhaustion; late regime detection (ER lag) |
| **H3 Compression → displacement → acceptance** | energy release after compression, confirmed by acceptance beyond the range | COMPRESSION within the prior 8 bars | displacement bar closes beyond the compression range, next bar does not close back inside | opposite side of the displacement bar | 2–3 R | expected ≈ 0.3–0.6/day after the compression filter | false breaks in ranges; news spikes |
| **H4 σ-band exhaustion fade** | stretched moves in balanced sessions revert to value | RANGE regime (ER ≤ 0.15), not the New York open hour | close outside TVWAP ± 2σ, then a close back inside ± 1σ within 2 bars | beyond the extreme + 0.1 × ATR | TVWAP (≈ 1–1.5 R), i.e. naturally LOW R:R / high win rate | ≈ 0.3–0.8/day | trending breakouts; mismatch with the preferred 1:3 R:R |
| **H5 New York opening-range acceptance** | the first 30 minutes of New York define intraday balance; acceptance outside starts the day's move | 13:30–14:00 UTC range (DST-adjusted to 09:30–10:00 New York) | two consecutive M15 closes beyond the opening range before 17:00 UTC | back inside the opening range (range midpoint) | 2–3 R | ranges broke up on 75 % and down on 70 % of days (often both → whipsaw) | double breaks; low-range days |

## 7. Data split (chronological, by trading day)

| part | span | trading days | use |
|---|---|---|---|
| DEVELOPMENT | 2025-12-23 → 2026-06-02 | 138 (60 %) | feature exploration, rule fixing, R:R / BE curves |
| VALIDATION | 2026-06-03 → 2026-07-26 | 46 (20 %) | confirm the fixed rules; choose among ≤ 3 finalists |
| FINAL OOS | 2026-07-27 → 2026-09-18 | 47 (20 %) | examined **once**, after freezing; no changes afterwards |

Walk-forward (after a candidate survives validation): rolling 3-month development / 1-month test, stepping one month
(≈ 5 folds within this sample). With ≈ 30 trades/month the OOS holds ≈ 50 trades: a 65 % win rate would carry a
standard error of ≈ 7 percentage points — this sample cannot confirm a win rate to better than roughly ± 13 pp (95 %).

## 8. Testing plan

1. **Event studies (development only, Python, causal features):** for each hypothesis the raw trigger's forward
   excursion distribution in R (MFE/MAE over 4 / 8 / 16 bars, time to 1R and −1R). A hypothesis whose raw
   distribution shows no edge is dropped before any exit design.
2. **Baseline rules with a-priori parameters** (§4–6 values, no tuning), implemented as a **Pine v6 strategy run on the
   frozen P3.1 engine** (authoritative fills: next-open market orders, intrabar-path stops/targets, gaps at the open).
   One position at a time, fixed 1-contract research size; R per trade from the entry comment (stop distance).
3. **Cost model:** candles are bid prices. Round-trip cost = spread: `slippage` = half the median spread in ticks per
   fill (≈ 140 ticks) as the base case, ×2 and ×3 as stress; short take-profits widened by one spread in the
   conservative variant (a buy limit fills at the ask). Commission 0 (Exness standard account) with a stress case
   (commission per lot) because the captured commission is unverified.
4. **Exits on development:** R:R grid 1.5 / 2 / 2.5 / 3 / 3.5 / 4; then breakeven OFF / 25 / 50 / 75 % of the way to
   target (for 1:3, 50 % = +1.5 R) at the best-*region* R:R (a plateau, not the peak); trailing (ATR / swing / R-based /
   TVWAP) only after the baseline is understood; never BE and trailing tuned together.
5. **Validation:** the frozen rules on the validation window; ≤ 3 finalists.
6. **Robustness (finalists):** each numeric parameter ±20 %; M15 ↔ M30 ↔ H1 signal timeframe; spread/slippage stress;
   one-bar entry delay; ± half-spread price noise on stop/target levels; each calendar month and each regime as a
   separate subperiod. Rejection rule: a candidate whose expectancy turns negative under a ±20 % perturbation of any
   single parameter, or under 2× costs, is rejected.
7. **Walk-forward** (§7) → **final OOS once**.
8. **Reports for every serious candidate:** total trades; win / loss rate; average win / loss R; expectancy R; profit
   factor; net R; max drawdown R; max consecutive losses; average and median holding time; long vs short; by session;
   **month by month** (trades, wins, losses, win rate, net R, profit factor, max drawdown, average trade) and
   **year by year**; trades/month mean, median, min, max; break-even win rate for the realized R:R; percent equity and
   currency P&L as secondary views (1 R = a fixed fraction of a notional research account, never the live size).
9. **Zoneflow validation** of the chosen candidate: Historical, Replay (no leakage), Strategy Tester — orders, fills,
   stops, targets, BE, trailing, ledger, equity, chart markers. No broker execution.

## 9. Overfitting and data risks

* **The targets are jointly implausible as stated.** At 1:3 R:R a 65 % win rate would mean an expectancy of
  0.65 × 3 − 0.35 = **+1.6 R per trade**, ≈ 48 R per month at 30 trades — far outside what robust intraday systems
  show. Typical 1:3 intraday systems land at 30–45 % win rates. A 65 % win rate is compatible with ≈ 1:1 targets,
  or with breakeven management if breakeven exits are counted as wins (they will be reported as a separate
  "scratch" class, never as wins). The research will report where the evidence lands.
* **Short history.** 9 months, one volatility regime (gold ≈ 4,000–4,500, median daily range ≈ 100 USD); no year-by-
  year variation is possible; walk-forward folds are few. Any result is provisional until more history is added.
* **Multiple testing.** 5 hypotheses × exit grids × filters on one short sample — selection bias is the main danger;
  hence a-priori parameters, a plateau criterion, few finalists, one-shot OOS.
* **Proxy confusion.** TVWAP and tick-volume features are activity proxies; any claim of "order flow" would be false.
* **Cost fragility.** Tight structural stops (H1, H3) make the spread a larger share of 1 R; the cost stress decides.
* **Emulator assumptions.** Historical fills use TradingView's broker-emulator path (open → high/low → close). Same-bar
  stop + target ambiguity on M15 is a real limitation without M1/tick data; results that depend on same-bar exits
  will be flagged.
* **Session/DST errors.** Sessions are computed in local exchange time; a fixed-UTC mistake would shift London and
  New York by an hour for part of the sample.

**Recommended human action (not a blocker):** extend the Exness Gold history. The existing exporter already writes
every bar the terminal holds; raising MT5's "Max bars in chart" to unlimited, scrolling the XAUUSDm M15/H1 charts back
and re-running `Export_XAUUSD_History` would deepen the sample with no code change. (An M1/M5 or tick export would
need a new exporter in `mt5/`, a protected area — only with approval.)

## 10. What to test first, and why

**H1 — Sweep of the Asia range / previous-day extreme + TVWAP reclaim.**

* It uses only data that exists (price structure, sessions, TVWAP proxy) — no pretend order flow.
* It has a natural, objective invalidation (the sweep extreme), which makes 1 R small and a 1:2–1:3 target
  structurally plausible, matching the user's preferred R:R without forcing it.
* The raw event frequency is in the right neighbourhood (London alone sweeps the Asia range on ≈ 65 % of days;
  adding previous-day extremes and New York gives ≈ 1 setup/day before filters), so ≈ 20–30 trades/month is
  reachable without loosening definitions.
* Its failure mode (sweeps that become trend breakouts) is measurable (H1 efficiency ratio at the signal), so the one
  regime filter it may need can be tested on validation data rather than invented.
* H2 (trend pullback) is the second candidate and the natural complement (it wins in the regime where H1 fails);
  H4 is kept as the control that shows what a high-win-rate / low-R:R profile looks like on this data.

GOLD V1 RESEARCH DESIGN READY
