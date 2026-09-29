# Gold V1 — H5 preregistration (NEW YORK OPENING-RANGE ACCEPTANCE)

This file was frozen before any H5 code ran and before any H5 outcome was computed. No definition was chosen from
forward returns. It is not edited after the study runs.

## Source of truth

`research/gold_v1/GOLD_V1_RESEARCH_DESIGN.md`, section 6, H5 row:

> the first 30 minutes of New York define intraday balance; acceptance outside starts the day's move | 13:30–14:00
> UTC range (DST-adjusted to 09:30–10:00 New York) | two consecutive M15 closes beyond the opening range before
> 17:00 UTC | back inside the opening range (range midpoint) | 2–3 R | ranges broke up on 75 % and down on 70 % of
> days (often both → whipsaw)

The design states the range as 13:30–14:00 UTC and calls it DST-adjusted to 09:30–10:00 New York, which is the EDT
offset (UTC−4). Its "before 17:00 UTC" cutoff is written in the same convention, so it means **13:00 New York local
time**, DST-adjusted in the same way (item 15).

## Definitions

- **Times:** all times below are America/New_York local times of the bar start, unless marked UTC. Bars are M15 and
  are labelled by their start time; a bar starting at t closes at t + 15 min.
- **Conversion:** UTC ↔ New York uses `zoneinfo` (via pandas `tz_convert`), the same pipeline tested in
  `tests/test_pipeline.py`.
- **Trading day:** the broker trading day from the H1 pipeline (a new day after a break of 60 minutes or more).

| # | item | fixed definition |
|---|---|---|
| 1 | Opening-range bars | The two M15 bars starting at 09:30 and 09:45 New York in the trading day. The day has an OR only if both bars exist. |
| 2 | DST / local time | Each bar's UTC timestamp is converted to America/New_York with `zoneinfo`. OR bars are selected by local wall-clock time, so they are 14:30/14:45 UTC under EST and 13:30/13:45 UTC under EDT (US DST from 2026-03-08). No fixed UTC offset appears anywhere. |
| 3 | Range | `OR_high = max(high)` and `OR_low = min(low)` of the two OR bars. `OR_mid = (OR_high + OR_low)/2`. `OR_width = OR_high − OR_low`. The OR is fully known at the 09:45 bar's close (10:00 New York). |
| 4 | First eligible signal bar | The first bar that can count as an outside close starts at 10:00 New York. The earliest possible second confirming close is therefore the 10:15 bar. |
| 5 | Outside | LONG side: `close > OR_high`, strictly. SHORT side: `close < OR_low`, strictly. A close exactly equal to a boundary is not outside. |
| 6 | Wicks inside | Allowed. Only closes count. How far a wick reaches back into the OR is recorded, not filtered. |
| 7 | Two consecutive closes | Two adjacent M15 bars (index i−1 and i, 15 minutes apart, both starting at or after 10:00) whose closes are both outside on the same side. The confirmation is bar i. |
| 8 | Same direction | Yes: both closes must be outside the same boundary (item 7). |
| 9 | Reset | A direction's streak resets on any bar whose close is not beyond that side: back inside, equal to the boundary, or beyond the opposite side. The two directions are counted independently. An opposite breakout therefore resets the streak only because such a close is not outside the first side. |
| 10 | Stop anchor | `OR_mid`, for both directions. This is the design's "back inside the opening range (range midpoint)". The brief's alternative (the OR boundary itself) is **not** used, and no other stop variant is tested. |
| 11 | Hypothetical entry | The open of bar i + 1, which must be in the same trading day. Risk = `entry − OR_mid` (LONG) or `OR_mid − entry` (SHORT). Risk ≤ 0 is rejected and counted. |
| 12 | Duplicate suppression | Only the first confirmation per direction per day is an event. Later confirmations that day in the same direction are counted as suppressed. |
| 13 | Setups per day | At most one per direction per day, so at most two per day. LONG and SHORT are studied independently. |
| 14 | Both sides confirm on one day | Both events are kept. Both are flagged `both_directions_day = true`; the later one is also flagged `opposite_confirmed_earlier = true`. They are reported separately in the descriptive analysis. |
| 15 | Maximum signal time | The confirming bar i must start at or before 12:45 New York, so it closes by 13:00 New York (the design's "before 17:00 UTC" in the design's DST-adjusted convention). |

Counts reported:
- **days:** days studied (trading days with a 09:30 New York wall-clock time); days with an OR;
- **outside closes:** raw outside closes per side in the signal window (bars 10:00–12:45 New York);
- **confirmations:** two-close confirmations per side, including suppressed ones;
- **events:** unique events;
- **day classes:** long only, short only, both, neither.

## Recorded, not filtered

- **OR:** high, low, width, width/ATR (ATR at the 09:45 bar) and width percentile. The percentile is the % of the
  previous 20 OR days' OR_width/ATR strictly below today's, and needs at least 10 prior OR days.
- **Overnight distance:** `(OR_mid − open of the trading day's first bar)/ATR`.
- **OR position vs PDH/PDL and vs the Asia range:** above / inside / below, by OR_mid.
- **First-break direction:** the side of the first bar from 10:00 whose high > OR_high or low < OR_low (trade-through).
  It is `both` if one bar does both, and `none` if neither happens before the signal.
- **Opposite side swept before the signal:** a trade-through of the opposite boundary by bars from 10:00 up to the
  confirming bar.
- **Per close (first and second):** distance beyond the OR in ATR, wick penetration back into the OR in ATR, body/range
  and close location in the trade direction.
- **Participation:** tick-volume ratio of the confirming bar.
- **Context at the confirming bar:** H1 ER, ATR percentile, volatility regime, TVWAP position `(close − TVWAP)/ATR`,
  TVWAP slope, spread/risk, weekday, long/short, confirmation time (New York).
- **Flag:** `us_short_session` when the trading day's last bar starts before 16:45 New York (holiday or early close).

## Forward measurement

This is identical to H1–H3:
- targets +0.5R to +4R raced against −1R over 96 bars;
- `ambiguous` (AMBIGUOUS_INTRABAR) when a target and −1R fall in one bar. That target is excluded for that event,
  and the favourable ordering is never chosen;
- MFE and MAE over 4, 8, 16 and 32 bars, and MFE until −1R.

## Controls

Five controls per event, drawn deterministically with replacement using seed 20260603 from bars j that meet all of:
- **Time:** the bar starts between 10:15 and 12:45 New York (the same signal window) on a day with an OR.
- **Not an event bar:** it is not an H5 confirming bar of either direction (including suppressed ones).
- **Distance:** it is more than 8 bars from any event's confirming bar.
- **Entry available:** the next bar is in the same trading day.
- **Volatility:** the same volatility regime as the event, and an ATR percentile within ±10 of the event's.
- **Where practical:** the same OR-width-percentile tercile (< 33.3, 33.3–66.7, ≥ 66.7) as the event's day. If fewer
  than 5 candidates meet this, the tercile condition is dropped (flag `or_pct_relaxed`). If still fewer than 5, the
  ATR-percentile condition is also dropped (flag `atr_pct_relaxed`).

Each control takes the event's direction and the event's risk in ATR units. Controls are never required to have
two closes outside the OR.

## Decision rule (the H1/H2/H3 rule, unchanged)

- **PROMISING** requires all of:
  - a +2R lift ≥ 5 pp over the control, with the 95% CI above 0 (event-clustered bootstrap, 5,000 samples, seed
    20260603);
  - event > control at +2R in at least 4 of 6 development months. H1–H3 each had exactly 6 event months. If H5 has
    events in 7 calendar months (December to June), the same two-thirds proportion applies, which is at least 5 of 7.
    This is fixed here, before outcomes;
  - a positive +2R lift in each preregistered slice: long and short.
- **WEAK**: a positive lift at +2R or +3R that fails the PROMISING tests.
- **NO EDGE**: no positive lift at +2R or +3R.

## Descriptive special analysis (not a filter)

- **Break probabilities:** P(opposite-side trade-through after the first trade-through), measured from 10:00 New York to
  the end of the trading day. Also, on a close basis, P(opposite-side confirmation | first confirmation).
- **Single versus double breaks:** event outcomes on single-side-break days versus both-side-break days. The
  both-side flag uses information after the entry. It is descriptive only, labelled as such, and never usable as a
  filter.

Validation and OOS are not inspected, whatever the result.
