# Parity checklist (TradingView Basic plan)

## Fast self-checking scripts (do these first)

Paste, add to chart, send one screenshot of the summary table. See README → *FAST TRADINGVIEW PARITY*.

| done | script | covers | cells |
|---|---|---|---|
| [x] | `quick/q1_main_v6.pine` | s00_data, s05_extremes (complete), s06_pivots, s07_var_varip (historical), s10_control, s11_na | 3824 |
| [x] | `quick/q2_s08_loops_v6.pine` | s08_loops_v6 | 180 |
| [x] | `quick/q3_s09_loops_v5.pine` | s09_loops_v5 | 180 |
| [x] | `quick/q4_security_historical.pine` (BINANCE:BTCUSDT, 1-minute chart) | P2.1 request.security historical semantics — establishes TradingView's rule, not an engine comparison | 134400 |

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

## P2.1 REAL TERMINAL (request.security in our own Pine Editor)

Paste each script from `manual/` into **our** terminal's Pine Editor → **Add to chart**. About 20 minutes in
total. Chart settings differ from TradingView's 1-minute examples because this terminal has no 1-minute
charts (finest: 15m), shows Binance only in **Live**, and runs **Replay** only on the historical datasets —
so 1h / 4h are requested from a 15m chart (1h = 4 chart bars, the same boundary logic as 5m from 1m).

**Where provenance is shown:** Pine Editor → **On chart** tab → the script's grey status line ends with
`· N requested contexts`. **Hover that line**: the tooltip lists one line per context —
`symbol timeframe · provider · native | aggregated from <base> · <bars> bars [· forming bar] · <dataset/stream>`.

| done | # | script | chart source | symbol | timeframe | mode | what to look for | pass condition |
|---|---|---|---|---|---|---|---|---|
| [x] | 1 | `manual/p21_terminal_binance_history.pine` + `manual/p21_terminal_binance_history_pane.pine` | Binance Futures | BTCUSDT | 15m | Live | 5 step-lines on the price pane (1h close, 1h close[1], 1h EMA 5, 4h close, 1h mid from a user function); a pane with the 4h RSI 5 and the 1h high-low histogram. Tooltip of each status line | both scripts added, no red error; status `· 3 requested contexts` / `· 2 requested contexts`; every tooltip line says `Binance Futures · native` with timeframe `60` or `240` |
| [x] | 2 | `manual/p21_terminal_replay.pine` | Exness (historical dataset) | BTCUSDm | 15m | Replay (start **2026-09-10 09:30**, then **Next bar** ×6) | the green/red/blue step-lines (1h high/low/close with `lookahead_on`) on the 4 bars of the yellow-marked 10:00 hour | at every step the 1h **high = highest high so far this hour**, **low = lowest low so far**, **close = the current bar's close**; the final hour values (high 78019.79, low 77785.69, close 77834.76) appear **only once their bars are revealed** (high/low at 10:30, close at 10:45); the orange `lookahead_off` line stays at the previous hour's close until 10:45 |
| [x] | 3 | `manual/p21_terminal_binance_live.pine` | Binance Futures | BTCUSDT | 15m | Live (stay ≥ 1 minute inside one hour) | the right-most values of `HTF close (forming)` / high / low (hover the latest candle) across several updates | the forming 1h close follows the chart's close on every update; high/low widen when price makes a new high/low for the hour; they restart at the next hour's first bar; tooltip shows `60 · Binance Futures · native · … · forming bar`; no red error |
| [x] | 4 | `manual/p21_terminal_exness_history.pine` | Exness (historical dataset) | XAUUSDm | 15m | Historical | 4 lines (H1 close/EMA 5, H4 close/EMA 5); the status-line tooltip | tooltip line 1: `EXNESS:XAUUSDm 60 · Exness MT5 · native · … · EXNESS_XAUUSDM_H1`; line 2: `EXNESS:XAUUSDm 240 · Exness MT5 · aggregated from 15m · … · EXNESS_XAUUSDM_M15`; nothing mentions Binance |
| [x] | 5a | `manual/p21_terminal_gap_lower_tf.pine` | Exness (historical dataset) | XAUUSDm | **1h** | Historical | the script row / notice | red error: `request.security() for a lower timeframe (15) than the chart (60) is not implemented yet …` |
| [x] | 5b | `manual/p21_terminal_gap_cross_family.pine` | Exness (historical dataset) | XAUUSDm | 15m | Historical | the script row / notice | red error before anything is drawn: `Line 5: request.security(): symbol BINANCE:BTCUSDT belongs to Binance Futures, but this chart's source is Exness MT5. Requests across data sources are not allowed.` |

**Result 2026-09-27 (Zoneflow terminal, run by the user): all six checks PASS** — recorded in
`terminal/p21_terminal_results.json`. This is terminal evidence, not TradingView evidence (only q4 is). Check 4's
per-context hover tooltip was not captured manually (the chart footer showed the M15 dataset); the detailed
provenance text is covered by automated tests only.

Notes: in check 1 the `lookahead_off` lines (1h close, close[1], EMA) change only when an hour completes —
that is correct, not a stall. Check 2's numbers are from the stored Exness BTCUSDm dataset (a dry run of this
exact script through the terminal); another start time works too with the same rules.
