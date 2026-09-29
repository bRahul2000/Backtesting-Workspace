# Gold V1 — H5 methodology (NEW YORK OPENING-RANGE ACCEPTANCE, event study)

The event rules are the ones in [preregistration.md](preregistration.md), frozen and hashed before any H5 code ran.
SHA-256: `cfeda52f3b7c2b98db1bdc1582042db9cd1d7611cdaf17ef881bf0564a2e7a96`.

## Order of work

1. Verify that H1–H3 are byte-identical and that the 22 existing tests pass.
2. Read the design's H5 row. It gives the range as 13:30–14:00 UTC, "DST-adjusted to 09:30–10:00 New York", which is
   the EDT offset. So its "before 17:00 UTC" cutoff means 13:00 New York in the same convention.
3. Write and hash the preregistration, fixing all 15 items. The stop is the design's OR midpoint.
4. Implement `h5_study.py` and `tests/test_h5.py`, including the dedicated DST test, and run the tests. They use
   detection only.
5. Run the study, then check the one risk outlier (2026-01-29) against the raw M15 and H1 data.
6. Run the report.

## Pipeline reuse

`h5_study.py` imports the following from `research/gold_v1/h1/h1_study.py`:
- `load_dev`, with the development cut;
- `features`, which provides ATR, the ATR percentile and volatility regime, TVWAP, PDH/PDL, the Asia range, H1 ER and
  the tick-volume ratio;
- `quality_gate`, `forward` and the `NEW_YORK` zone.

`h5_report.py` uses the H1 report's `lift`, `p_win`, `md_breakdown` and chart helpers. The measurement and decision
framework are therefore identical to H1–H3.

## Detection

For each trading day, the OR is taken from the 09:30 and 09:45 New York bars, selected by wall-clock time. Bars from
10:00 to 12:45 New York are then scanned in order, keeping a streak count for each direction:
- **Streak:** a strictly-outside close extends the streak if the previous bar is adjacent (15 minutes earlier) and
  also outside; any other close resets it.
- **Confirmation:** a streak of 2 or more on a bar starting at 10:15 or later is a confirmation.
- **Duplicates:** the first confirmation per direction per day is the event; later ones are suppressed.
- **Entry and stop:** entry is the next bar's open; the stop is the OR midpoint.
- **Both directions:** if both directions confirm, both events are kept and flagged.

## Forward measurement and controls

Forward measurement is identical to H1–H3:
- targets +0.5R to +4R raced against −1R over 96 bars;
- a same-bar target and stop is `ambiguous`, and that target is excluded for that event;
- MFE and MAE over 4, 8, 16 and 32 bars, and until −1R.

Controls: 5 per event, deterministic (seed 20260603). They are bars starting 10:15–12:45 New York on OR days, with:
- the same volatility regime, and an ATR percentile within ±10 of the event's;
- the same OR-width tercile where practical, with documented relaxations;
- the event's direction and risk in ATR units;
- no confirming bars, and more than 8 bars from any event.

Controls never require two outside closes.

## Decision rule

This is the H1–H3 rule, unchanged. The month criterion applies the same two-thirds proportion, which gives 5 of 7
here, as fixed in the preregistration before outcomes. The slices are long and short.

## Descriptive special analysis

- **Trade-through breaks:** from 10:00 New York to the day's end: up, down, first side, and
  P(opposite break after the first).
- **Close-based:** P(opposite confirmation | first confirmation).
- **Outcomes by day type:** event outcomes by single versus double break. These use post-entry information and are
  descriptive only.

## Reproduce

```
venv/bin/python research/gold_v1/h5/h5_study.py      # gate + opening ranges + events + controls
venv/bin/python research/gold_v1/h5/h5_report.py     # report, charts, decision
venv/bin/python -m pytest -q -p no:cacheprovider research/gold_v1/tests
```

The scripts are deterministic and use only numpy and pandas. Two consecutive runs are byte-identical, checked by
SHA-256.

## Artifacts

| file | content |
|---|---|
| `preregistration.md` | frozen rules |
| `h5_study.py`, `h5_report.py` | analysis code |
| `h5_events_dev.csv` | 98 events, with every recorded feature and forward outcome |
| `h5_controls_dev.csv` | 490 matched control draws |
| `h5_opening_ranges_dev.csv` | 113 opening ranges (UTC start, high/low/mid/width, width/ATR, width percentile) |
| `h5_days_dev.csv` | per-day break and confirmation table for the special analysis |
| `h5_counts_dev.json` | days, outside closes, confirmations, suppressed repeats, rejections |
| `data_quality.json`, `data_quality.md` | gate |
| `report.md`, `h5_summary.json` | results and decision |
| `chart_target_curve.svg`, `chart_months_2R.svg` | P(+tR) against control and break-even; monthly +2R |
| `../tests/test_h5.py` | H5 regression tests, including the DST mapping |
