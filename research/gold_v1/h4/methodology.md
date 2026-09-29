# Gold V1 — H4 methodology (TVWAP BAND EXHAUSTION FADE, event study)

The event rules are the ones in [preregistration.md](preregistration.md), frozen and hashed before any H4 code ran.
SHA-256: `92f25167e26bc6d6b544baf7cdf18ba0539348ad668cf044890ffca08116acd4`.

## Order of work

1. Verify that H1, H2, H3 and H5 are byte-identical and that the 33 existing tests pass.
2. Read the design's H4 row. Two choices come out of it:
   - **Stop:** the brief's no-buffer structural stop, not the design's "+0.1 × ATR".
   - **Kept from the design:** its "not the New York open hour" context.

   The target is the live causal TVWAP. The design names TVWAP without freezing it, and the session TVWAP is by
   definition the evolving mean. Only this one target was computed.
3. Write and hash the preregistration: 18 items, plus the primary race, controls and an H4-specific decision rule.
4. Implement `h4_study.py` and `tests/test_h4.py`, and run the tests. They use detection plus race unit tests on
   crafted bars.
5. Run the study and the report. Two statements in the report were then corrected against the data: the mean
   spread/target figure is noted as outlier-driven, and the development price path is described accurately.

## Pipeline reuse

`h4_study.py` imports the following from `research/gold_v1/h1/h1_study.py`:
- `load_dev`, with the development cut;
- `features`, which provides TVWAP/σ (centred weighted variance), ATR, the ATR percentile, the volatility regime,
  `er_h1`, `expansion`, PDH/PDL, the Asia range and the tick-volume ratio;
- `quality_gate`, `forward` and `NEW_YORK`.

`h4_report.py` uses the H1 report's `lift` (event-clustered bootstrap), `p_win`, `md_breakdown` and `svg_curve`
unchanged. The primary outcome is exposed as column `r_tv` (hit → win, stop → loss), so the same bootstrap computes
its CI.

## Detection

Each side is scanned bar by bar:
- **Exhaustion (X):** a strict close outside that side's 2σ, at the 5th session bar or later.
- **Reentry (R):** the first strict close inside ±1σ within 2 bars of the latest X.
- **Cancellation and expiry:** a close outside the opposite 2σ cancels the candidate, and so does the session end.
  After 2 bars without a reentry it expires.
- **Qualification:** the reentry must be in the range regime (ER ≤ 0.15) and outside the New York open hour.
- **Entry and stop:** entry at R + 1; stop at the extreme from the streak start through R.
- **Rejection:** events with risk ≤ 0 or `target_R ≤ 0` are rejected.

The first reentry consumes the streak's candidate. If that reentry fails the regime or time condition, it is counted
as excluded and the streak produces no event. This is the literal reading of item 10: one event per streak, at its
first reentry.

## Outcomes

- **Primary:** live TVWAP, the previous bar's value, raced against the −1R stop within the session. The outcome is
  `hit`, `stop`, `ambiguous` or `session_end`. Recorded:
  - time to TVWAP, in bars and minutes;
  - realized R at a hit;
  - MTM R at the session end;
  - target_R at entry.
- **Standard:** the H1–H5 race (+0.5R to +4R against −1R, 96 bars) and MFE/MAE over 4, 8, 16 and 32 bars.
- **Economics:** the mean outcome R, gross and after the mean spread/risk; spread as % of 1R and of the natural
  target.

## Controls

Five per event, deterministic (seed 20260603). They are range-regime bars in the same session, with:
- an ATR percentile within ±10 of the event's;
- TVWAP on the trade's target side;
- a TVWAP distance within ±0.25 ATR of the event's, with documented relaxations;
- the event's direction and its risk in ATR units;
- the same primary race and standard study as the events.

They exclude all H4 reentry bars, the New York open hour, the session warm-up and bars within ±8 of any event. They
never require the ±2σ → ±1σ pattern.

## Decision rule

The preregistered rule has four tests:
1. a primary lift ≥ 5 pp with the CI above 0;
2. event > control in at least two-thirds of months, and a positive lift in both slices;
3. uncertainty, covered by the CI in test 1;
4. expectancy after spread > 0.

## Reproduce

```
venv/bin/python research/gold_v1/h4/h4_study.py
venv/bin/python research/gold_v1/h4/h4_report.py
venv/bin/python -m pytest -q -p no:cacheprovider research/gold_v1/tests
```

The scripts are deterministic and use only numpy and pandas. Two consecutive runs are byte-identical, checked by
SHA-256.

## Artifacts

| file | content |
|---|---|
| `preregistration.md` | frozen rules |
| `h4_study.py`, `h4_report.py` | analysis code |
| `h4_events_dev.csv` | 33 events: bands, target_R, primary race, standard race, features |
| `h4_controls_dev.csv` | 164 matched control draws |
| `h4_counts_dev.json` | stage counts per side and control-matching statistics |
| `data_quality.json`, `data_quality.md` | gate |
| `report.md`, `h4_summary.json` | results and decision |
| `chart_target_r.svg` | natural TVWAP target distribution, events vs controls |
| `chart_months_tvwap.svg` | monthly P(TVWAP before −1R), events vs controls |
| `chart_standard_r_curve.svg` | standard P(+tR) curve against break-even |
| `../tests/test_h4.py` | H4 regression tests |
