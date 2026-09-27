# Parity checklist (TradingView Basic plan)

## Fast self-checking scripts (do these first)

Paste, add to chart, send one screenshot of the summary table. See README → *FAST TRADINGVIEW PARITY*.

| done | script | covers | cells |
|---|---|---|---|
| [x] | `quick/q1_main_v6.pine` | s00_data, s05_extremes (complete), s06_pivots, s07_var_varip (historical), s10_control, s11_na | 3824 |
| [x] | `quick/q2_s08_loops_v6.pine` | s08_loops_v6 | 180 |
| [x] | `quick/q3_s09_loops_v5.pine` | s09_loops_v5 | 180 |

Still manual (cannot be checked numerically): the plot na-gap visual and the live var / varip table (below).

**Status 2026-09-28: all checks above done on real TradingView** — see `PARITY_REPORT.md` → Status. Not covered by any check: `c01_chart` (needs the chart-data export) and the numeric values of `s12_plots`; the live check covered updates within one forming bar, not the opening of the next bar.

## Manual tables

Tick a box (`[x]`) when every page of that script matched. Steps: `README.md` → *TradingView Basic plan —
manual parity*. Record the result in `tradingview/manual_results.json` too, so `PARITY_REPORT.md` shows it.

| done | check | script to paste | pages (Page input → bars) | column groups | expected values |
|---|---|---|---|---|---|
| [x] via quick | s00 fixture data | `manual/s00_data.pine` | 0 → 0-9 · 1 → 182-191 · 2 → 196-205 · 3 → 208-217 · 4 → 222-231 | 1 | `ours_manual/s00_data.md` |
| [x] | s01 averages | `manual/s01_averages.pine` | 0 → 0-9 · 1 → 10-19 · 2 → 17-26 · 3 → 150-159 | 2 | `ours_manual/s01_averages.md` |
| [x] | s02 oscillators | `manual/s02_oscillators.pine` | 0 → 0-9 · 1 → 17-26 · 2 → 28-37 · 3 → 208-217 | 3 | `ours_manual/s02_oscillators.md` |
| [x] | s03 history | `manual/s03_history.pine` | 0 → 0-9 · 1 → 100-109 | 2 | `ours_manual/s03_history.md` |
| [x] | s04 cross | `manual/s04_cross.pine` | 0 → 84-93 · 1 → 96-105 · 2 → 150-159 · 3 → 203-212 · 4 → 216-225 | 2 | `ours_manual/s04_cross.md` |
| [x] via q1 | s05 extremes | `manual/s05_extremes.pine` | 0 → 0-9 · 1 → 10-19 · 2 → 182-191 · 3 → 196-205 | 3 | `ours_manual/s05_extremes.md` |
| [x] via quick | s06 pivots (incl. 3/3, 2/1, 1/3) | `manual/s06_pivots.pine` | 0 → 0-9 · 1 → 10-19 · 2 → 16-25 · 3 → 184-193 · 4 → 200-209 | 3 | `ours_manual/s06_pivots.md` |
| [x] via quick | s07 var (historical) | `manual/s07_var_varip.pine` | 0 → 0-9 · 1 → 45-54 · 2 → 84-93 | 1 | `ours_manual/s07_var_varip.md` |
| [x] via quick | s08 loops v6 | `manual/s08_loops_v6.pine` | 0 → 0-9 · 1 → 10-19 | 2 | `ours_manual/s08_loops_v6.md` |
| [x] via quick | s09 loops v5 | `manual/s09_loops_v5.pine` | 0 → 0-9 · 1 → 10-19 | 2 | `ours_manual/s09_loops_v5.md` |
| [x] via quick | s10 control | `manual/s10_control.pine` | 0 → 0-9 · 1 → 14-23 | 2 | `ours_manual/s10_control.md` |
| [x] via quick | s11 na | `manual/s11_na.pine` | 0 → 0-9 · 1 → 8-17 | 2 | `ours_manual/s11_na.md` |
| [x] | plot na-gap visual | `manual/m02_na_gap_visual.pine` | any bars | — | blue line bridges the gaps; red line has gaps |
| [x] within one bar | live var / varip | `manual/m03_live_var_varip_table.pine` | 1-minute live chart | — | see README, *live var / varip* |
