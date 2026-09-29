# Gold V1 — H1 methodology (SWEEP + TVWAP RECLAIM, event study)

This document fixes the event definition, the forward measurement, the control sample and the decision rule. All of
them were fixed before the results were computed. Nothing was tuned afterwards.

## Data and boundary

- Exness XAUUSDm M15, bid (`data/exness/gold/phase2a/raw/xauusd_XAUUSDm_M15.csv`).
- Development window: 2025-12-23 → 2026-06-02. `load_dev()` drops every row at or after 2026-06-03 00:00 UTC before
  any feature is computed, so validation (2026-06-03 → 2026-07-26) and final OOS (2026-07-27 → 2026-09-18) never
  enter memory. Forward windows are cut at the end of the development data; an event whose race is cut off is
  labelled `truncated`.
- Trading day: a new day starts at the first bar after a break of 60 minutes or more (the 17:00 New York close,
  weekends, holidays).

## Features (all causal)

| feature | definition |
|---|---|
| ATR | Wilder ATR(14) on M15, like `ta.atr` |
| TVWAP, σ | cumulative tick-volume-weighted typical price since the trading-day start; weighted population σ; ±1σ/±2σ bands |
| TVWAP slope | (TVWAP − TVWAP 4 bars earlier) / ATR |
| Asia high/low | trading-day bars 00:00–07:00 UTC; usable only from the first bar ≥ 07:00 UTC after that day's Asia bars |
| PDH/PDL | high/low of the previous complete trading day |
| H1 ER(20) | efficiency ratio of H1 closes, taken from the last *completed* hour; ≥ 0.35 trend, ≤ 0.15 range |
| ATR percentile | rank of current ATR among all bars of the previous 20 trading days; ≥ 70 high, ≤ 30 low, else mid |
| compression | 8-bar range at or below the 20th percentile of the previous 20 trading days |
| expansion | bar range ≥ 1.5 × previous ATR and body/range ≥ 0.6 |
| tick-volume ratio | tick volume / median tick volume of the same UTC hour over the previous 20 occurrences |
| session, hour, weekday | see data_quality.md check 5 |

## Event definition

- **Sweep bar**
  - High-side reference (Asia high, PDH): `high > ref and close <= ref`.
  - Low-side reference (Asia low, PDL): `low < ref and close >= ref`.
  - No depth filter. Depth = |sweep extreme − ref| / ATR.
- **Reclaim**
  - High-side sweep → short: the first bar j in [sweep bar, sweep bar + 4] of the same trading day whose close is
    below TVWAP.
  - Low-side sweep → long: the same, with the close above TVWAP.
  - The sweep bar itself may be the reclaim bar, because its close and its TVWAP are both known at the close.
- **One event per trading day and reference**: the first sweep that achieves a reclaim.
  - All sweep bars are counted as raw sweeps.
- **Entry reference** = open of bar j + 1.
- **Stop anchor** = the sweep extreme from the sweep bar through the reclaim bar.
- **Risk** = |entry − stop|. Events with risk ≤ 0 are rejected; none occurred.
- **Recorded, not filtered**: signal close, next open, spread at the entry bar, risk, spread/risk, reclaim delay,
  distance from TVWAP (ATR and σ units), TVWAP slope, and every context feature above.

## Forward measurement (no exits)

- For each target t ∈ {0.5, 1, …, 4}R:
  - `win`: +tR reached before −1R.
  - `loss`: −1R reached first.
  - `ambiguous`: both touched inside the same M15 bar; AMBIGUOUS_INTRABAR, reported separately.
  - `none`: neither within 96 bars (one trading day).
  - `truncated`: the development data ends first.
- MFE and MAE in R over 4, 8, 16 and 32 bars, and MFE until −1R.
- Excursions are measured from the entry open on bid OHLC; spread is not deducted.
- P(+tR) = wins / (wins + losses). The conservative variant counts `ambiguous` as a loss.

## Control sample

- For each event, 5 bars are drawn with replacement, with fixed seed 20260603, from all M15 bars that:
  - have the same session and the same volatility regime as the event's signal bar;
  - are more than 8 bars from any event signal;
  - have a next bar in the same trading day.
- Each control gets the event's direction and the event's risk in ATR units (risk = event risk_atr × control ATR).
  Its entry is the next open.
- The control therefore asks: does the sweep + reclaim context beat a random bar with the same session, volatility,
  direction and stop size?

## Statistics

- Wilson intervals for single proportions.
- The event-minus-control difference uses a 5,000-sample bootstrap that resamples events together with their own
  controls, giving a 95% percentile CI.

## Decision rule (pre-registered)

- **PROMISING** requires all of:
  - a +2R lift of at least 5 pp over the control, with a 95% CI above 0;
  - event > control at +2R in at least 4 of the 6 development months;
  - a positive +2R lift in the long, short, Asia-reference and PD-reference slices.
- **WEAK**: a positive lift at +2R or +3R that fails the PROMISING tests.
- **NO EDGE**: no positive lift at +2R or +3R. H1 stops.
- Validation and OOS may not be used to rescue a WEAK or NO EDGE result.

## Reproduce

```
venv/bin/python research/gold_v1/h1/h1_study.py      # gate + events + controls
cd research/gold_v1/h1 && ../../../venv/bin/python h1_report.py   # report, charts, decision
```

Both scripts are deterministic, use only pandas and numpy, and run in about 2 s.

## Artifacts

| file | content |
|---|---|
| `h1_study.py` | loader, gate, features, events, forward race, controls |
| `h1_report.py` | tables, bootstrap, charts, decision |
| `h1_events_dev.csv` | 102 events with every recorded field and forward outcome |
| `h1_controls_dev.csv` | 510 matched controls |
| `h1_raw_sweeps_dev.json` | raw sweep counts by reference |
| `data_quality.json` / `data_quality.md` | gate record |
| `report.md`, `h1_summary.json` | results and decision |
| `chart_target_curve.svg`, `chart_months_2R.svg` | P(+tR) curve vs control and break-even; monthly +2R |
