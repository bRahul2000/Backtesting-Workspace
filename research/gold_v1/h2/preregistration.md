# Gold V1 — H2 preregistration (TREND PULLBACK TO TVWAP)

Frozen 2026-09-29, **before any H2 outcome statistic was computed**. No threshold below was chosen by looking at
H2 forward returns. After the study runs, this file is not edited; any later change would be a new hypothesis.

## Source of truth

`research/gold_v1/GOLD_V1_RESEARCH_DESIGN.md`, section 6, H2 row:

> in an efficient H1 trend, pullbacks to value continue | H1 ER ≥ 0.35, TVWAP slope in trend direction | first touch
> of TVWAP or the ±1σ band after a new session extreme, rejection bar: close location ≥ 0.65, body/range ≥ 0.5 |
> beyond the pullback swing or 1.0 × ATR

The design's thresholds (0.35, 0.65, 0.5) are used unchanged. The items below were not objectively defined in the
design and are fixed here. Each one takes the simplest causal reading and adds at most one new constant.

## Definitions

"Session" means the TVWAP session: the broker trading day, starting with the first bar after a break of 60 minutes
or more. This is the same reset as H1.

| # | rule | fixed definition | status |
|---|---|---|---|
| 1 | Trend regime | H1 Kaufman efficiency ratio over the 20 H1 bars completed before the signal bar's hour ≥ 0.35 (identical to H1 `er_h1`). | design |
| 2 | Trend direction | Sign of the net move in the same ER window: `close_H1[k] − close_H1[k−20]`, with k the last completed H1 bar. > 0 is UP, < 0 is DOWN. It uses the same 21 completed H1 closes as the ER, so it adds no new constant. | **new** |
| 3 | TVWAP slope in the trend direction | slope = (TVWAP − TVWAP 4 bars earlier) / ATR, the design's feature-library definition. Required at the signal bar: > 0 for UP, < 0 for DOWN. Its value is also recorded. | design |
| 4 | Pullback start (new session extreme) | UP: a bar whose high exceeds every earlier high of the same session. DOWN: a bar whose low is below every earlier low of the same session. The first bar of a session cannot be an extreme, because it has no earlier bar. Each new extreme starts a new pullback sequence and ends the previous one. | **new** |
| 5 | Eligible zones | Zone A = trend-side 1σ band (UP: TVWAP + 1σ; DOWN: TVWAP − 1σ). Zone B = session TVWAP. A zone is eligible in a sequence only if the extreme bar lay entirely on the trend side of it (UP: extreme-bar low > zone level at that bar; DOWN: extreme-bar high < zone level). Otherwise price never left the zone, so there is nothing to pull back to. | **new** |
| 6 | Touch | UP: bar low ≤ zone level at that bar. DOWN: bar high ≥ zone level. The bands are evaluated at the touching bar, with that bar's close included, which is known at the close. | **new** |
| 7 | First-touch rule | Each eligible zone can be first-touched only once per sequence. If one bar touches both zones (UP: low ≤ TVWAP implies low ≤ +1σ), the bar is assigned to the deeper zone, B, and zone A's first touch is consumed without an event. The zone touched first in the sequence is recorded as `first_zone`. | **new** |
| 8 | Rejection bar | UP: close > open, close > touched zone level, (close − low)/(high − low) ≥ 0.65 and \|close − open\|/(high − low) ≥ 0.5. DOWN: the mirror image, with (high − close)/(high − low) ≥ 0.65. Bars with high = low never qualify. | design + mirror |
| 9 | Rejection window | The rejection bar is the first-touch bar T itself or bar T + 1, which counts only if T + 1 makes no new session extreme in either direction and does not touch the other, deeper zone. Anything later is not an event for that touch. This is one new constant: one bar. | **new** |
| 10 | Pullback end / invalidation | A sequence ends at the first of: an event; a new session extreme in the trend direction (a new sequence starts); the session end; both zones' first touches consumed. Regime and slope are checked only at the rejection bar. | **new** |
| 11 | Stop anchor | UP: the lowest low of the bars after the extreme bar, up to and including the rejection bar. DOWN: the highest high over the same bars. Every one of these bars is complete at the signal close, and no pivot confirmation is used. The design's alternative "or 1.0 × ATR" is **not** used as a stop, for comparability with H1 (structure stop, no buffer). Risk in ATR is recorded instead. | **new (choice)** |
| 12 | Entry reference | Open of the bar after the rejection bar, which must be in the same session. Risk = \|entry − stop\|. Events with risk ≤ 0 are rejected and counted. | brief |
| 13 | Duplicate suppression | At most one event per pullback sequence: the first rejection. A new sequence needs a new session extreme. Both directions can occur in one session only if the trend direction changes; that is allowed, and each counts separately. | **new** |
| 14 | Counts reported | raw qualifying bars = bars meeting rules 1–3, 6 and 8 (touch plus rejection in the trend regime) regardless of sequence and first touch; unique pullback sequences = sequences in the trend regime that first-touch at least one eligible zone; final events = rule 13 output. | brief |

Recorded, not filtered:
- H1 ER, ATR percentile, volatility regime, TVWAP slope, zone, first_zone;
- pullback depth = (extreme − stop)/ATR, distance travelled = (extreme − TVWAP at the extreme bar)/ATR, and the number of bars from the extreme to the rejection;
- rejection body/range and close location;
- tick-volume ratio, session, UTC hour, weekday, spread/risk, long/short;
- distance to PDH and PDL in ATR;
- H1 expansion before the pullback: the last H1 bar completed before the extreme bar has range ≥ 1.5 × H1 ATR(14) of the previous bar, and body/range ≥ 0.6. This is the design's expansion definition applied to H1.

## Forward measurement

This is identical to H1:
- targets +0.5R to +4R raced against −1R over 96 bars;
- AMBIGUOUS_INTRABAR when a target and −1R fall in the same M15 bar, never resolved favourably;
- `none` and `truncated` handled as in H1;
- MFE and MAE over 4, 8, 16 and 32 bars, and MFE until −1R.

## Control sample

Five controls per event, drawn with fixed seed 20260603 from M15 bars that meet all of these:
- the trend regime holds (ER ≥ 0.35);
- the trend direction is the same as the event's;
- the TVWAP slope is in the trend direction (rule 3; the regime as the design defines it);
- the session and volatility regime are the same as the event's;
- the bar is not a raw qualifying H2 bar;
- the bar is more than 8 bars from any H2 event signal;
- the next bar is in the same session.

Each control takes the event's direction and the event's risk in ATR units. This asks whether the pullback
rejection beats a random bar in the same trend context.

## Decision rule (the H1 rule, unchanged)

- **PROMISING** requires all of:
  - a +2R lift of at least 5 pp over the control, with the 95% CI above 0 (event-clustered bootstrap, 5,000 samples, seed 20260603);
  - event > control at +2R in at least 4 of the 6 development months;
  - a positive +2R lift in the long, short, zone-A and zone-B slices. The zone slices replace H1's Asia-reference and PD-reference slices as the setup's own two sub-types.
- **WEAK**: a positive lift at +2R or +3R that fails the PROMISING tests.
- **NO EDGE**: no positive lift at +2R or +3R.

Validation and OOS are not inspected, whatever the result.
