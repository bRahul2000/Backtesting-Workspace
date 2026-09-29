# Gold V1 — H3 preregistration (COMPRESSION → DISPLACEMENT → ACCEPTANCE)

This file was frozen before any H3 code ran and before any H3 outcome statistic was computed. No definition was
chosen from forward returns. It is not edited after the study runs.

## Source of truth

`research/gold_v1/GOLD_V1_RESEARCH_DESIGN.md`:
- section 4, COMPRESSION: 8-bar M15 range ≤ 20th percentile of its trailing 20-day distribution;
- section 4, EXPANSION: bar range ≥ 1.5 × ATR(14) and body/range ≥ 0.6;
- section 6, H3: context "COMPRESSION within the prior 8 bars". Trigger "displacement bar closes beyond the
  compression range, next bar does not close back inside". Stop "opposite side of the displacement bar".

These thresholds (8 bars, 20th percentile, 20 days, 1.5 × ATR(14), 0.6) are used unchanged. The design's stop
wording is exactly the brief's preferred baseline, so the stop needs no deviation note.

## Definitions

"Session" and "trading day" both mean the broker trading day used by H1/H2: a new day starts at the first bar after
a break of 60 minutes or more. Bar indices refer to completed M15 bars. D is the displacement bar, A the
acceptance bar and E the entry bar.

| # | item | fixed definition | status |
|---|---|---|---|
| 1 | 8-bar compression range | `rng8[k] = max(high[k−7..k]) − min(low[k−7..k])`: the 8 completed bars ending at k, inclusive. This is the existing pipeline feature `rng8` in `h1_study.features`, unchanged. The window must lie inside one trading day (bar k−7 in the same day as k), so no window spans the daily break. | design + **new** (same-day) |
| 2 | Percentile lookback | `rng8_pct[k]` = % of `rng8` values strictly below `rng8[k]`, among all bars from the first bar of the trading day 20 days before k's day up to bar k−1 (existing `_trailing_percentile`, unchanged). Bars in the first 20 trading days have no percentile and cannot be compressed. | design (existing code) |
| 3 | Compressed bar | Bar k is compressed if `rng8_pct[k] ≤ 20` and rule 1's same-day condition holds. | design |
| 4 | Compression structure and reset | A structure is a maximal run of consecutive compressed bars in one trading day. A non-compressed bar ends the run, and the next compressed bar starts a new structure. The structure's **box** for a candidate D is the 8-bar window of the most recent compressed bar k < D: `box_high = max(high[k−7..k])`, `box_low = min(low[k−7..k])`. D never belongs to its own box. | **new** |
| 5 | Maximum lifetime | D qualifies only if `1 ≤ D − k ≤ 8`, with k the structure's most recent compressed bar before D ("within the prior 8 bars"), and D is in the same trading day as k. | design + **new** (same-day) |
| 6 | Structure still intact | No bar strictly between k and D may have closed outside `[box_low, box_high]`. If one did, the box was already broken and D is not a candidate for this box. | **new** |
| 7 | ATR | Wilder ATR(14) on M15 true range (existing `atr`). The displacement test uses ATR at D − 1, so D does not inflate its own benchmark (existing `expansion` column). | design (existing code) |
| 8 | Displacement bar | `high − low ≥ 1.5 × ATR[D−1]`, `abs(close − open)/(high − low) ≥ 0.6`, and the body points in the breakout direction (close > open for long, close < open for short). This is the existing `expansion` flag plus body direction. | design + **new** (body direction) |
| 9 | Breakout direction / close beyond | LONG if `close[D] > box_high`. SHORT if `close[D] < box_low`. D must close beyond the box; a displacement that closes inside is not a candidate. | design |
| 10 | Both sides | If `high[D] > box_high` and `low[D] < box_low`, the direction is still decided by the close (rule 9). The event is kept, not excluded, and flagged `two_sided = true`. Its results are also reported separately. | **new** |
| 11 | Acceptance | A = D + 1, which must be in the same trading day. LONG accepted if `close[A] > box_high`; SHORT accepted if `close[A] < box_low`. A close at or back inside the box, or beyond the opposite side, fails. | design |
| 12 | Acceptance-bar shape | This label is recorded only, in precedence order. `fail`: rule 11 not met. `wick_inside`: accepted, but the bar traded back into the box (LONG `low[A] ≤ box_high`; SHORT `high[A] ≥ box_low`). `continues`: accepted and `close[A]` beyond `close[D]` in the trade direction. `stalls`: accepted, otherwise. | **new** |
| 13 | Entry reference | E = A + 1, entry = `open[E]`, which must be in the same trading day. Signal confirmation is at A's close. | brief |
| 14 | Stop anchor | LONG: `low[D]`. SHORT: `high[D]`. This is the opposite side of the displacement bar, with no ATR component and no buffer. Risk = abs(entry − stop). Events with risk ≤ 0 are rejected and counted. | design |
| 15 | Duplicate suppression | At most one event per structure and direction. The first accepted breakout in a direction consumes that direction for the structure. A later compressed bar in the same run is the same structure. The opposite direction stays available, subject to rules 5–6. | **new** |

Counts reported:
- raw compression structures: the number of rule-4 runs;
- raw displacement bars: every rule-8 bar in development, whatever the context;
- candidate displacements: rule-8 bars that satisfy rules 5, 6 and 9;
- accepted breakouts: candidates that pass rule 11;
- final unique events: after rules 13–15.

## Recorded, not filtered

- **Compression:** high, low, width, width/ATR, percentile of k, duration (length of the run so far) and bars since
  the previous expansion bar before D.
- **Displacement:** range/ATR, body/range, close location in the trade direction, distance beyond the boundary
  `(close[D] − boundary)/ATR`, tick-volume ratio and `two_sided`.
- **Acceptance:** acceptance shape.
- **Context at A's close:** H1 ER, ATR percentile, volatility regime, TVWAP distance `(close − TVWAP)/ATR` and TVWAP
  slope.
- **Other:** session, UTC hour, weekday, spread/risk, long/short, PDH and PDL distance in ATR.
- **TVWAP direction:** `toward_tvwap = true` if TVWAP at bar k lies on the breakout side of the box midpoint.

## Forward measurement

This is identical to H1/H2:
- targets +0.5R to +4R raced against −1R over 96 bars;
- `ambiguous` (AMBIGUOUS_INTRABAR) when a target and −1R fall in one bar. That target is excluded for that event,
  and the favourable ordering is never chosen;
- MFE and MAE over 4, 8, 16 and 32 bars, and MFE until −1R.

## Controls

Five controls per event, drawn deterministically with replacement using seed 20260603 from M15 bars j that:
- have the same session and volatility regime as the event's signal bar A;
- have an ATR percentile within ±10 points of the event's (if fewer than 5 such bars exist, drop the ATR-percentile
  condition and flag `atr_pct_relaxed`);
- lie more than 8 bars from any event's A;
- are not an H3 acceptance bar;
- have a next bar j + 1 in the same trading day.

Each control takes the event's direction and the event's risk in ATR units. The controls are not required to have
compression, displacement or acceptance.

## Decision rule (the H1/H2 rule, unchanged)

- **PROMISING** requires all of:
  - a +2R lift ≥ 5 pp over the control, with the 95% CI above 0 (event-clustered bootstrap, 5,000 samples, seed
    20260603);
  - event > control at +2R in at least 4 of the 6 development months;
  - a positive +2R lift in each preregistered slice. H3 has no design-defined sub-types, so the slices are long and
    short.
- **WEAK**: a positive lift at +2R or +3R that fails the PROMISING tests.
- **NO EDGE**: no positive lift at +2R or +3R.

Validation and OOS are not inspected, whatever the result.
