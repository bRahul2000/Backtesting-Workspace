# Gold V1 — H4 preregistration (TVWAP BAND EXHAUSTION FADE)

This file was frozen before any H4 code ran and before any H4 outcome was computed. No definition was chosen from
forward returns. It is not edited after the study runs.

## Source of truth

`research/gold_v1/GOLD_V1_RESEARCH_DESIGN.md`, section 6, H4 row:

> stretched moves in balanced sessions revert to value | RANGE regime (ER ≤ 0.15), not the New York open hour |
> close outside TVWAP ± 2σ, then a close back inside ± 1σ within 2 bars | beyond the extreme + 0.1 × ATR |
> TVWAP (≈ 1–1.5 R), i.e. naturally LOW R:R / high win rate

## Resolving design vs brief

- **Stop.** The design says "beyond the extreme + 0.1 × ATR". The brief's preferred baseline is the extreme itself, with
  "no ATR optimization, no arbitrary buffer". This follows the brief, as H1 did (structure stop, no buffer): the stop
  is the extreme of the exhaustion episode. It is fixed now and no second stop is computed.
- **Context "not the New York open hour".** This is in the design and was fixed before any data was seen, so it is
  kept. Reentry bars starting 09:30–10:15 New York local time (the hour 09:30–10:30, DST-aware via `zoneinfo`) are
  excluded. They are counted, but their outcomes are never computed.
- **Target.** The design says "TVWAP", with no suggestion that the level is frozen at entry. Session TVWAP is by
  definition the evolving session mean. So the target is the **live causal TVWAP** (item 15). No frozen-target
  variant is computed.

## Definitions

- **Session:** the TVWAP session, i.e. the broker trading day of the H1 pipeline.
- **Bands:** `U2 = TVWAP + 2σ`, `U1 = TVWAP + 1σ`, `L1 = TVWAP − 1σ`, `L2 = TVWAP − 2σ`, all evaluated at each bar's own
  close. They include that bar and are known at its close.
- **Bars:** X = exhaustion bar, R = reentry bar, E = entry bar.

| # | item | fixed definition |
|---|---|---|
| 1 | H1 efficiency ratio | The existing pipeline `er_h1`: \|C_k − C_{k−20}\| / Σ\|C_i − C_{i−1}\| over the 20 H1 bars completed before the bar's hour (H1 closes = last M15 close of each hour). This is the same as H1–H3/H5. |
| 2 | Range-regime timing | `er_h1 ≤ 0.15` at the reentry bar R. It is not required at X. |
| 3 | Outside ±2σ | Upper: `close > U2`, strictly. Lower: `close < L2`, strictly. Equality is not outside. |
| 4 | Back inside ±1σ | `L1 < close < U1`, strictly on both sides. Equality is not inside. |
| 5 | Exhaustion bar as reentry | Not possible: a close cannot be both outside ±2σ and inside ±1σ. |
| 6 | 2-bar window | X is the most recent bar closing outside ±2σ on that side. R must be X+1 or X+2. A bar in between may close anywhere except outside the same side's 2σ; such a close would make it the new X, and the window restarts. |
| 7 | Direction | Upper exhaustion → SHORT. Lower exhaustion → LONG. |
| 8 | Stop anchor | SHORT: the highest high from the first bar of the current streak of consecutive outside-U2 closes (the episode start), through R. LONG: the lowest low over the same span for L2. No buffer and no ATR component. |
| 9 | Entry | The open of E = R + 1, in the same session. Risk = \|entry − stop\|. Risk ≤ 0 is rejected and counted. |
| 10 | Duplicate suppression | At most one event per exhaustion streak. The streak's first qualifying reentry is the event. |
| 11 | Reset after a failed reentry | If neither X+1 nor X+2 is a reentry, the candidate expires. Only a new outside-2σ close on that side starts a new candidate. |
| 12 | Reset after an event | The same side needs a new outside-2σ close after R. The other side is independent. Events may overlap in time (event study). |
| 13 | Move across both sides | Each side is tracked independently. A close beyond the opposite 2σ is not inside ±1σ, so it cannot be the reentry; it cancels the pending candidate and starts a candidate on the other side. |
| 14 | New session before resolution | X, R and E must all be in one session; a pending candidate expires at the session end. In the outcome race, if the session ends before TVWAP or the stop is reached, the outcome is `session_end`, marked to market at the session's last close (in R). |
| 15 | Target | Live causal TVWAP. During bar j the target level is `TVWAP[j−1]`, the value at the previous bar's close, which is the latest known when bar j trades. LONG: hit if `high[j] ≥ level_j`. SHORT: hit if `low[j] ≤ level_j`. Realized R at a hit = `(level_j − entry)/risk` (LONG), or the mirror for SHORT. If bar j already opens beyond the level, realized R uses `open[j]`. |
| 16 | Natural target at entry | `target_R = (TVWAP[R] − entry)/risk` for LONG (mirror for SHORT); `TVWAP[R]` is the live level for the entry bar. If `target_R ≤ 0`, the entry is already at or beyond the target, so there is no natural target. Such events are rejected and counted, like risk ≤ 0. |
| 17 | Session warm-up (degenerate σ) | σ is 0 on a session's first bar and tiny for a few bars afterwards. X must therefore be at least the 5th bar of its session, so TVWAP has at least 4 earlier bars. This guard is fixed now, a priori. |
| 18 | New York open hour | Excluded as described above. |

## Primary outcome (H4-specific race)

Starting from E, bar by bar within the session, TVWAP (item 15) is raced against the stop:
- **`hit`:** TVWAP reached first.
- **`stop`:** the stop is reached first.
- **`ambiguous`:** both are inside one bar (AMBIGUOUS_INTRABAR, never resolved favourably).
- **`session_end`:** neither is reached before the session ends.

Recorded:
- the outcome;
- time to TVWAP, in bars (`hit_bar − E + 1`) and minutes (× 15);
- `target_R` at entry;
- realized R at a hit;
- MTM R at `session_end`.

P(TVWAP before −1R) = hits / (hits + stops). Ambiguous and `session_end` are excluded and reported separately. The
conservative variant counts ambiguous as a stop.

## Standard R study

This is identical to H1–H3/H5, for comparability only:
- targets +0.5R to +4R raced against −1R over 96 bars;
- MFE and MAE over 4, 8, 16 and 32 bars.

It is not the primary H4 criterion.

## Controls

Five controls per event, drawn deterministically with replacement using seed 20260603 from bars j that meet all of:
- **Regime:** `er_h1 ≤ 0.15`.
- **Session:** the same session as the event's R.
- **Volatility:** an ATR percentile within ±10 of the event's.
- **TVWAP side:** TVWAP lies on the event's target side of `close[j]` (below it for SHORT, above it for LONG).
- **TVWAP distance** (where practical): `|close[j] − TVWAP[j]|/ATR` within ±0.25 of the event's R-bar value. If fewer
  than 5 candidates meet this, the distance condition is dropped (flag `dist_relaxed`). If still fewer than 5, the
  ATR condition is also dropped (flag `atr_relaxed`).
- **Not an H4 bar:** it is not an H4 reentry bar on either side, whatever the regime or time.
- **Distance from events:** it is more than 8 bars from any event's R.
- **Timing:** it is not in the New York open hour and is at least the 5th bar of its session.
- **Entry available:** the next bar is in the same session.

Each control takes the event's direction and the event's risk in ATR units. It runs the same primary race (live TVWAP
against the stop, within the session) and the standard R study. A control draw with `target_R ≤ 0` at its entry
open is discarded and counted, without a redraw. Controls are never required to show the ±2σ → ±1σ pattern.

## Decision rule (fixed now)

This is the H1–H5 framework, with H4's structural outcome as the primary criterion.

**PROMISING** requires all of:
1. **Lift:** P(TVWAP before −1R) event minus control ≥ 5 pp, with the event-clustered bootstrap 95% CI (5,000
   samples, seed 20260603) above 0.
2. **Stability:** event > control on that primary rate in at least two-thirds of the development months that contain
   events (4 of 6, 5 of 7). The lift must also be positive in both slices: LONG (lower band) and SHORT (upper band).
3. **Uncertainty:** covered by the CI requirement in 1.
4. **Economics:** indicative expectancy > 0 after spread. Expectancy = the mean over all events of the outcome R,
   minus the mean spread/risk. Outcome R is realized R at a hit, −1 at a stop, −1 when ambiguous (conservative) and
   MTM at `session_end`.

**WEAK:** a positive primary lift that fails any PROMISING test. **NO EDGE:** a primary lift ≤ 0.

The standard +1R…+4R results are reported but do not enter the decision. Validation and OOS are not inspected,
whatever the result.

## Recorded, not filtered

- **Exhaustion:** distance beyond 2σ (in σ and in ATR), reentry delay (R − X), streak length.
- **Band and regime context:** TVWAP slope, σ/ATR, H1 ER, ATR percentile, volatility regime.
- **Participation:** tick-volume ratio at R.
- **Time:** session, UTC hour, weekday.
- **Trade:** long/short, spread/risk, spread as % of the natural target (`spread / (target_R × risk)`), target_R.
- **Distances in ATR:** to PDH/PDL and to the Asia high/low.
- **Expansion before exhaustion:** any expansion bar from the bar before the streak start through X.
- **Earlier touches:** the number of earlier outside-2σ streaks on the same side in the session.
