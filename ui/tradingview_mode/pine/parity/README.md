# Pine parity: comparing this engine with real TradingView output

This folder checks, bar by bar, that the Pine engine gives the same numbers as TradingView for the Pine
subset it supports. Only real TradingView runs count as evidence. `PARITY_REPORT.md` → *Status* says exactly
which fixtures have been verified and which have not.

**Status (2026-09-28, real TradingView, Basic plan):** 12 of 15 fixtures verified — s01–s04 through the
manual tables; s00, s05, s06, s07 (historical bars), s10, s11 through `quick/q1_main_v6` (3824 cells, 0
failed); s08 / s09 through `quick/q2` / `quick/q3` (180 + 180 cells). The quick checker's self-test failed
exactly one cell as designed. Manual observations: `m02` (default line bridges na, `linebr` breaks) and
`m03` (within one live bar: var fixed, varip advancing). **Not verified:** `c01_chart` (needs the chart-data
export: ta.atr, ta.tr, ta.vwma, ta.supertrend on chart prices), the numeric values of `s12_plots`, and the
live behaviour when a new bar opens (`barstate.isnew`). `x01` is a third-party capture, not our own run.
Real TradingView found three engine bugs, all fixed: na inside ta.sma/ema/rma/wma, ta.highest/lowest on an
na bar, and (earlier, third-party capture) pivot / highestbars tie handling.

## What is in here

| path | what it is |
|---|---|
| `fixtures/*.pine` | Pine scripts to paste into TradingView (generated — do not edit by hand) |
| `data/synthetic_ohlcv.csv` | the fixture price data, for reference (the `s*` scripts generate the same values themselves) |
| `ours/*.csv` | what this engine outputs for each fixture, in TradingView's export layout |
| `manual/*.pine` | Basic-plan scripts: the same calculations shown in an on-chart table (generated) |
| `ours_manual/*.md`, `*.csv` | what this engine computes for every manual table cell |
| `MANUAL_CHECKLIST.md` | the checks to do (quick scripts first), with pages and expected files |
| `quick/*.pine` | fast self-checking scripts: TradingView compares itself with this engine (generated) |
| `tradingview/` | **you put TradingView's exports here** |
| `external/` | TradingView values captured and published by third parties (provenance inside each file) |
| `PARITY_REPORT.md` | the comparison result |
| `fixtures.py`, `harness.py` | the fixture definitions and the comparison code |

### Why the scripts don't need special data

You cannot upload your own candles to TradingView. So every `s*` fixture computes its own prices from
`bar_index` at the top of the script (the "fixture data" block): every price is a multiple of 0.25 and it
never reads the chart's prices. **Any symbol and any timeframe on TradingView gives identical values.**

The one `c01_chart` fixture tests built-ins that must use the chart's own prices (`ta.atr`, `ta.vwma`,
`ta.tr` ...). For it, the export itself carries the candles, and this engine re-runs the script on those
exact candles.

## Capturing TradingView's values (about 2 minutes per fixture)

You need a TradingView account. Repeat these steps for each file in `fixtures/` whose name starts with
`s`, `c` or `x`:

1. Open <https://www.tradingview.com/chart/>. Pick **BINANCE:BTCUSDT** with the **1D** (daily) timeframe.
   (Any symbol works for the `s*`/`x*` fixtures; `c01_chart` needs a chart whose full history loads, which
   daily BTCUSDT does.)
2. Remove other indicators from the chart (right-click an indicator → Remove), so only one script is exported.
3. Open the **Pine Editor** tab at the bottom of the screen. Select everything in it and delete it.
4. Open the fixture file (for example `fixtures/s01_averages.pine`) in any text editor, copy **all** of it,
   and paste it into the Pine Editor.
5. Click **Add to chart**. A pane with several lines appears under the price chart. If TradingView shows a
   red error instead, stop and note the message: that is itself a parity finding.
6. For `c01_chart` only: drag the chart to the right (or zoom out) until no more old candles load, so the
   very first candle of the symbol is loaded.
7. Open the layout menu (the arrow next to the layout name, top right) → **Export chart data…**.
   Choose the current chart, set **Time format** to **UNIX timestamp**, and click **Export**.
8. A `.csv` file downloads. Rename it to the fixture's name with `.csv`, for example
   `s01_averages.csv`, and move it into this folder's `tradingview/` directory.

Then run, from the repository root:

```
python -m ui.tradingview_mode.pine.parity
```

(or ask Claude: "rerun the Pine parity report"). Open `PARITY_REPORT.md`.

## FAST TRADINGVIEW PARITY

The fastest way to check the remaining fixtures: **3 scripts, one screenshot each.** Each script in
`quick/` runs the fixtures' calculations on TradingView, compares every value with what this engine
produced (embedded in the script, generated — never typed by hand) and shows one summary table.

| script | fixtures it checks | cells |
|---|---|---|
| `quick/q1_main_v6.pine` | s00_data (every manual page + bars 180-239), s05_extremes and s06_pivots (every manual page + bars 0-47, two periods of every 1/1, 2/2, 3/3, 2/1, 1/3 tie case, + bars 180-239, all equal highs/lows of the data and the pivots they confirm), s07_var_varip (historical bars only), s10_control, s11_na | 3824 |
| `quick/q2_s08_loops_v6.pine` | s08_loops_v6 (Pine v6 semantics) | 180 |
| `quick/q3_s09_loops_v5.pine` | s09_loops_v5 (Pine v5 semantics) | 180 |

s08 and s09 cannot share a script: one file has one Pine version.

1. Open the script file (for example `quick/q1_main_v6.pine`) in a text editor and copy all of it
   (on a Mac: `pbcopy < ui/tradingview_mode/pine/parity/quick/q1_main_v6.pine` in Terminal copies it).
2. On <https://www.tradingview.com/chart/> open the **Pine Editor**, select everything, delete it, paste.
3. **Add to chart** (any symbol and timeframe with at least 240 bars; daily BTCUSDT is fine).
4. Take **one screenshot of the table** at the top right and send it to Claude.
5. Repeat for the other two scripts.

How to read the table:

* One row per fixture: **cells expected**, **checked**, **failed**, the largest difference seen, and
  **RESULT**: `PASS` (every cell checked, none failed), `FAIL`, or `INCOMPLETE` (the chart had too few
  bars, so some cells were never checked).
* **ALL** is the overall result.
* **KEY** rows show headline values by name, e.g. `for_dynamic_end` (7 in v6, 4 in v5) and `div_const`
  (3.5 in v6, 3 in v5), so the version difference is visible at a glance.
* **FIRST FAILURES** lists up to 10 failing cells: bar, field, TradingView's value, this engine's value and
  the difference (`na vs value` when only one side is na).
* To prove the checker can fail, open the script's settings and tick **Self-test: corrupt one expected
  value**: the first fixture must turn `FAIL` with exactly one failure. Untick it again for the real run.

Comparison rule: both `na` → pass; one `na` → fail; otherwise pass when
`|TradingView − ours| ≤ 0.000000005 + 0.000000000001 × |ours|`, i.e. within half a unit of the 8th
decimal (the manual-table standard) plus floating-point noise on large values. Booleans (1 / 0) and
integers differ by at least 1 when they differ, so they are effectively compared exactly.

Results are recorded in `tradingview/quick_results.json` (Claude does this from your screenshot):

```json
{"q1_main_v6": {"fixtures": {"s05_extremes": "PASS", "s06_pivots": "PASS"}, "note": "2026-09-28 screenshot"}}
```

What the quick scripts do **not** replace: the plot na-gap visual check (`manual/m02_na_gap_visual.pine`,
it is about how lines are drawn) and the live var / varip check (`manual/m03_live_var_varip_table.pine`,
it needs ticks of a forming candle). s07 in `q1` covers only historical bars.

## TradingView Basic plan — manual parity

The Basic plan has no "Export chart data". Instead, each script in `manual/` shows its values **in a table
on the chart**, 10 bars at a time, and `ours_manual/<fixture>.md` shows what this engine computes for the
very same cells. The calculations are exactly those of the matching `fixtures/*.pine` file (the scripts are
generated from them); only the way values are displayed differs.

You need about 5 minutes per script. The easiest way to compare: **take a screenshot of the table and give
it to Claude** together with the Page/Columns you used. Or compare by eye as below.

1. **Open TradingView**: <https://www.tradingview.com/chart/>. Any symbol and timeframe (BINANCE:BTCUSDT 1D
   is fine) — these scripts never read the chart's prices.
2. **Open the Pine Editor** tab at the bottom of the screen. Select everything in it and delete it.
3. **Paste one manual script**: open for example `manual/s01_averages.pine` in a text editor, copy all of
   it, paste it into the Pine Editor.
4. **Add to chart**. A white table appears at the top right of the chart. Its first line says which fixture,
   column group and bars you are looking at. (If TradingView shows a red error instead, write it down: that
   is a finding too.)
5. **Read the table.** Open the script's settings (double-click the table or the script's name on the chart
   → *Inputs*):
   * **Page** chooses the 10 bars shown. Each page targets a moment that matters (warm-up, the first
     crossover, equal highs …); the Page tooltip and `MANUAL_CHECKLIST.md` list them.
   * **Columns** chooses the group of outputs (at most 6 at a time).
   * **First bar** shows any other 10 bars (-1 = use Page).
6. **Compare with the local expected file**: open `ours_manual/s01_averages.md`. Find the block with the same
   *Page* and *Columns* and compare every cell. `na` must be `na` on both sides; `1` / `0` columns are
   true / false. Numbers show 8 decimals (trailing zeros are dropped, so `105.5` means `105.50000000`).
   A difference only in the 8th decimal can be a rounding tie — note it, it is checked against the full
   value in `ours/<fixture>.csv`; anything larger is a real difference.
7. **If everything matches**, add the Page/Columns settings you compared (`"page/columns"`) to
   `tradingview/manual_results.json`; once every setting of a script matches, tick its box in
   `MANUAL_CHECKLIST.md`:

   ```json
   {
     "s01_averages": {"status": "match", "checked": ["0/1", "0/2", "1/1", "1/2"], "note": "checked 2026-09-28"}
   }
   ```

8. **If a value differs**, write down the bar, the column name and TradingView's value in
   `tradingview/<fixture>.spot.csv` (one line per cell; leave the value empty for `na`):

   ```
   bar_index,output,value
   88,xover,1
   19,ph33,
   ```

   and set `"status": "mismatch"` for that fixture in `manual_results.json`. Then run
   `python -m ui.tradingview_mode.pine.parity`: the report compares those cells automatically and each
   difference gets investigated and classified.

### Plot na-gap visual check

Paste `manual/m02_na_gap_visual.pine`. Every 10 bars, 3 bars have no value. **Expected**: the upper, blue
line (default style = `plot.style_line`) is drawn straight across those bars; the lower, red line
(`plot.style_linebr`) stops and leaves an empty gap. Record `"m02_na_gap_visual": {"status": "match"}` (or
`"mismatch"` with a note), and the answers in `observations.json` (below).

### Live var / varip check

Paste `manual/m03_live_var_varip_table.pine` on a **1-minute** BTCUSDT chart while the market is active
(crypto trades around the clock). The table shows the newest, still-forming candle. Watch it for about a
minute, through the start of the next candle. **Expected**:

| row | while the candle is forming (each price update) | when a new candle starts |
|---|---|---|
| bar_index | stays the same | +1 |
| barstate.isnew | `T` only on the first update of the candle, then `F` | `T` |
| barstate.isrealtime | `T` | `T` |
| var count | does **not** change | +1 |
| varip count | +1 on every update | +1 |
| varip ticks this bar | 1, 2, 3 … | back to 1 |

Record `"m03_live_var_varip_table": {"status": "match"}` (or `"mismatch"` and what you saw) and the two
live answers in `observations.json`.

### If "Export chart data" is not available on your plan

Use the **Data Window** instead (right-hand toolbar → *Object tree and data window* → *Data Window*).
Scroll the chart to its first candles; hovering a candle lists every fixture output with its value — the
`bi` line tells you the bar number. Write what you see into `tradingview/<fixture>.spot.csv`:

```
bar_index,output,value
100,xover_touch,0
101,xover_touch,1
188,ph22_h,120
```

Leave `value` empty when the Data Window shows `n/a`. The script sets 10 decimals so values are precise.
Useful bars to read: `s04_cross` 99–102; `s06_pivots` 184–205; `s02_oscillators` 209–223 (flat candles);
`s08`/`s09` any bar (`for_dynamic_end`, `div_const`); `s01_averages` 0–25 (warm-up) and 20–30 (na gaps).

### Checks that cannot be exported (record by hand)

Create `tradingview/observations.json` and answer with `true` / `false`:

```json
{
  "observer": "your name",
  "observed_on": "2026-09-27",
  "plot_default_bridges_na": true,
  "plot_style_line_bridges_na": true,
  "plot_style_linebr_breaks_at_na": true,
  "varip_counts_ticks_within_bar": true,
  "var_unchanged_within_realtime_bar": true
}
```

* **Lines across `na`** — with `s12_plots` on the chart, look at the bars where the lines have no value
  (3 of every 10 bars). Does `line_gappy` / `line_explicit` draw a straight line across the gap? Does
  `linebr` stop and leave a gap?
* **var / varip live** — add `fixtures/m01_live_varip.pine` to a **1-minute** BTCUSDT chart during trading.
  Watch the Data Window on the newest (still forming) candle for a minute: `varip ticks this bar` should
  climb with every price update; `var count` should not change until a new candle starts, then rise by 1.

## How values are compared

* `na` must match exactly (both empty, or both a number).
* Whole numbers — booleans plotted as 0/1, counters, bar offsets — must be exactly equal.
* Other numbers: `|ours − TradingView| ≤ max(1e-9, 1e-9 × |TradingView|, q)`. `q` is 0 when the file is
  full precision (some value has 12 or more decimals). If TradingView rounded every value to `d` decimals,
  `q` is half a unit of the `d`-th decimal; when that is coarser than 1e-6 the fixture is reported
  INCONCLUSIVE, never PASS.
* `plotshape` / `plotchar` / `bgcolor` / `barcolor` colours are not in the export, so their **timing** is
  checked instead: our renderer must draw them on exactly the bars where TradingView's condition plot is 1.

Every remaining mismatch gets a classification in `harness.py` (`CLASSIFICATIONS`): parser, type/qualifier,
series semantics, built-in formula, warm-up, na behaviour, loop/control-flow, render behaviour, or
TradingView-reference uncertainty. Unclassified mismatches are listed as *UNCLASSIFIED — investigate*.
