# Gold V1 — H3 methodology (COMPRESSION → DISPLACEMENT → ACCEPTANCE, event study)

The event rules are the ones in [preregistration.md](preregistration.md), frozen and hashed before any H3 code ran.
SHA-256: `c481f8a11da8428df4892d32c9ca3044e292726cb3f0320965f4fcc25339c59e`.

## Order of work

1. Verify that H1 and H2 are byte-identical and that the 17 pipeline tests pass.
2. Read the design's compression and expansion definitions and the H3 row.
3. Write and hash the preregistration. It fixes the box formula, percentile lookback, ATR, direction, close-beyond,
   two-sided handling, acceptance, shape labels, entry, stop, duplicates, reset and lifetime.
4. Implement `h3_study.py` and `tests/test_h3.py`. Run the tests; they use detection only, never outcomes.
5. Hand-check one event bar by bar: event 10, 2026-02-23 12:30, long, box 5145.089–5163.447, labelled
   `wick_inside`.
6. Run the study and the report.

## Pipeline reuse

`h3_study.py` imports the following from `research/gold_v1/h1/h1_study.py`:
- `load_dev`, with the development cut;
- `features`, which provides `rng8`, the causal 20-day `rng8_pct`, Wilder `atr`, `expansion` against ATR[D−1],
  TVWAP, sessions, PDH/PDL, H1 ER, the volatility regime and the tick-volume ratio;
- `quality_gate` and `forward`.

`h3_report.py` uses the H1 report's `lift` (event-clustered bootstrap), `p_win`, `md_breakdown` and chart helpers.
The measurement and the decision rule are therefore identical to H1 and H2.

## Detection

Bars are scanned in order. For each bar D:
- **Context:** D needs a most recent compressed bar k with 1 ≤ D − k ≤ 8 in the same trading day.
- **Box:** the box is bars k−7..k, and no close between k and D may lie outside it.
- **Displacement:** D must be an expansion bar whose body points out of the box, and it must close beyond the box.
  This makes it a candidate.
- **Acceptance:** A = D + 1 must close beyond the same boundary.
- **Duplicates:** the first accepted breakout per (structure, direction) is kept.
- **Entry and stop:** entry = open of D + 2; stop = the opposite side of D.
- **Records:** everything is recorded, including `two_sided` and the acceptance shape.

## Forward measurement and controls

Forward measurement is identical to H1 and H2:
- targets +0.5R to +4R raced against −1R over 96 bars;
- a same-bar target and stop is `ambiguous`, and that target is excluded for that event;
- MFE and MAE over 4, 8, 16 and 32 bars, and until −1R.

The conservative variant, which counts `ambiguous` as a loss, is identical at +1R to +3R, because no event is
ambiguous there.

Controls: 5 per event, deterministic (seed 20260603). They match on:
- session and volatility regime;
- an ATR percentile within ±10 of the event's (never relaxed in this run);
- direction and risk in ATR units, both copied from the event.

They exclude H3 acceptance bars and bars within ±8 of any event. They are never required to have compression,
displacement or acceptance.

## Decision rule

This is the H1/H2 rule, unchanged. The slices are long and short, as preregistered.

## Reproduce

```
venv/bin/python research/gold_v1/h3/h3_study.py      # gate + events + controls
venv/bin/python research/gold_v1/h3/h3_report.py     # report, charts, decision
venv/bin/python -m pytest -q -p no:cacheprovider research/gold_v1/tests
```

The scripts are deterministic and use only numpy and pandas. Two consecutive runs are byte-identical, checked by
SHA-256.

## Artifacts

| file | content |
|---|---|
| `preregistration.md` | frozen rules |
| `h3_study.py`, `h3_report.py` | analysis code |
| `h3_events_dev.csv` | 77 events, with every recorded feature and forward outcome |
| `h3_controls_dev.csv` | 385 matched controls |
| `h3_counts_dev.json` | structures, displacement bars, candidates, acceptance failures, accepted breakouts, suppressed |
| `data_quality.json`, `data_quality.md` | gate |
| `report.md`, `h3_summary.json` | results and decision |
| `chart_target_curve.svg`, `chart_months_2R.svg` | P(+tR) against control and break-even; monthly +2R |
| `../tests/test_h3.py` | H3 regression tests |
