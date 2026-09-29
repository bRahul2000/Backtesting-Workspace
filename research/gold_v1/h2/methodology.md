# Gold V1 — H2 methodology (TREND PULLBACK TO TVWAP, event study)

The event rules are those in [preregistration.md](preregistration.md), frozen before any H2 outcome was computed;
its SHA-256 is `89e22514b241c409bce4b63187b83b33164f5eb14b568160353d9bfe96900b1f`. This file describes how
they are implemented and measured.

## Order of work

1. Read the design's H2 row. Trend direction, pullback start/end, zone eligibility, first touch, rejection window,
   stop anchor and duplicate suppression were not objectively defined there.
2. Write and hash `preregistration.md`. No H2 statistic existed at that point.
3. Add the pipeline regression tests (see data_quality.md).
4. Implement `h2_study.py` from the preregistration.
5. Hand-check two events bar by bar against the rules: event 0, a short zone-A same-bar rejection, and event 13, a
   short zone-A T+1 rejection.
6. Run the study and the report.

## Pipeline reuse

`h2_study.py` imports the following from `research/gold_v1/h1/h1_study.py`:
- `load_dev`: cuts at 2026-06-03 00:00 UTC before any computation;
- `features`: ATR, TVWAP/σ, sessions, PDH/PDL, H1 ER, ATR percentile, tick-volume ratio;
- `quality_gate`, `forward` (the target race and MFE/MAE) and `wilson`.

`h2_report.py` imports `lift` (the event-clustered bootstrap), `p_win`, `md_breakdown` and the SVG helpers from
`h1_report.py`. Measurement and decision are therefore identical to H1. The only new code is the H2 features, the
detection, the controls and the H2 gate checks.

## Detection (preregistration rule numbers)

Each session and each direction d are scanned bar by bar:
- A new session extreme in d starts a sequence (rule 4). The sequence keeps the zones that the extreme bar lay
  entirely beyond (rule 5).
- On each later bar, the deepest eligible zone not yet consumed that the bar touches is its first touch (rules 6–7).
  A zone-B touch also consumes zone A.
- The event fires if, at that bar, the trend regime holds and the bar is a rejection candle against the touched
  level (rules 1–3, 8).
- Otherwise the touch is pending for one bar. The next bar fires if it makes no new extreme in either direction,
  does not touch the deeper zone, and meets the regime and rejection conditions (rule 9).
- The sequence ends at an event, a new extreme, the session end, or when every eligible zone is consumed
  (rules 10, 13).
- Stop = the extreme of the bars after the pullback-start bar, up to and including the signal bar (rule 11).
  Entry = the open of the next bar in the same session (rule 12).

## Forward measurement and controls

- **Forward measurement:** identical to H1: targets +0.5R to +4R raced against −1R over 96 bars, `ambiguous` for a
  same-bar target and stop, and MFE/MAE over 4, 8, 16 and 32 bars and until −1R.
- **Controls:** 5 per event, drawn with replacement using the fixed seed 20260603. Each control bar must meet all of:
  - ER ≥ 0.35, the same H1 direction as the event, and TVWAP slope in that direction;
  - the same session and volatility regime as the event;
  - not a raw qualifying H2 bar in that direction;
  - more than 8 bars from any H2 signal;
  - a next bar in the same session.

  Each control takes the event's direction and the event's risk in ATR units, so stop sizes are comparable.
  The defining pullback and rejection are exactly what the controls lack.

## Decision rule

This is the H1 rule unchanged, with H2's own slices (long, short, zone A, zone B) in place of H1's reference
slices. A power note is added, but it does not change the rule.

## Reproduce

```
venv/bin/python research/gold_v1/h2/h2_study.py     # gate + events + controls
venv/bin/python research/gold_v1/h2/h2_report.py    # report, charts, decision
venv/bin/python -m pytest -q -p no:cacheprovider research/gold_v1/tests
```

Both scripts are deterministic, use only numpy and pandas, and run in a few seconds. Two consecutive runs
produce byte-identical outputs (SHA-256 checked).

## Artifacts

| file | content |
|---|---|
| `preregistration.md` | frozen rules |
| `h2_study.py`, `h2_report.py` | analysis code |
| `h2_events_dev.csv` | 27 events, with every recorded feature and forward outcome |
| `h2_controls_dev.csv` | 135 matched controls |
| `h2_counts_dev.json` | sequences started, unique sequences, raw qualifying bars, rejections |
| `data_quality.json`, `data_quality.md` | gate |
| `report.md`, `h2_summary.json` | results and decision |
| `chart_target_curve.svg`, `chart_months_2R.svg` | P(+tR) against control and break-even; monthly +2R |
| `../tests/test_pipeline.py` | pipeline and H2 regression tests |
