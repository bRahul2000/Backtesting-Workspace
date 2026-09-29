# Gold Range Hunter — Zoneflow custom-Pine compatibility evidence

**Scope.** Rahul's exact strategy "Gold Range Hunter - Monthly Profiles V2" must compile, add to the chart, execute and
backtest in Zoneflow TradingView Mode. The script is never edited.

## Acceptance fixture

| item | value |
|---|---|
| fixture | `tests/tradingview_mode/pine/fixtures/gold_range_hunter_monthly_profiles_v2.pine` |
| SHA-256 | `d30ea9ea63000d3c59c55c47cd2022b813a3fc203586d57764057fbfae17d5d4` |
| lines | 572 as the editor counts them (571 newline-terminated lines plus the empty line 572) |
| source | `~/Documents/Codex/2026-08-15/…/GoldRangeHunter_v49.pine` ("Packaged v49 trading core"), copied byte for byte |

**Why this is believed to be the editor's script.**
- It reproduces all three reported diagnostics exactly (lines 6, 7 and 137).
- The Pine Editor buffer itself lives in browser localStorage (`tvterm:pine:draft`) and was not read.

**If the editor text differs** from this file, paste it into the fixture and rerun `test_gold_range_hunter.py`. The
fixture test pins the SHA-256.

## Compatibility failures and root causes

| # | failure (before) | root cause | fix |
|---|---|---|---|
| 1 | L6, L7: `input.time()` is not implemented yet | `input.time` was not registered | real `input.time`, described below |
| 2 | L137: `input.color` defval "a `series color` was used" | every builtin declared one fixed return qualifier, so `color.new(color.blue, 85)` was always `series color` | a `polymorphic` builtin flag makes the result qualifier the strongest argument qualifier; set on `color.new` and `color.rgb` |
| 3 | runtime, L163/208/209/377/378: `month/hour/minute/dayofweek(t, "Asia/Kolkata")` raised "Time zone … not implemented" | calendar functions accepted UTC only | IANA names and UTC/GMT offsets |
| 4 | runtime, L215/216: `time(timeframe.period, "0330-0545", tz)` raised "time() with a session argument is not implemented yet" | sessions were not implemented | session parsing plus an in-session test |
| 5 | analyzer crash (TypeError) for a non-constant argument inside a const color default | `const_value` called `color.new`/`color.rgb` with an unevaluated (None) argument | returns None; the qualifier error is reported instead |
| 6 | a constant ternary color default (`true ? color.red : color.blue`) was rejected | `const_value` could not fold `?:` | a constant condition selects its branch |
| 7 | chart markers and trade list showed order IDs (`BUY EXIT SL`) where TradingView shows comments (`TRAIL_SL`) | presentation ignored `comment` / `comment_profit` / `comment_loss` | a non-empty comment replaces the ID; the ID stays in the tooltip |

Failures 3 and 4 were **runtime** gaps: the script compiled after fixes 1–2 but could not execute. Failure 7 is
display-only; the trades themselves were unaffected.

## Implemented semantics and sources

**`input.time(defval, title, tooltip, inline, group, confirm, display, active)`.**
- The result is an `input int`, a UNIX time in milliseconds.
- `defval` must be a `const int`: a series value (`time`) or a string is rejected, and the result is not const.
- Users override it through the inputs panel, which edits the value as a **UTC** date and time; the backend validates
  it as whole milliseconds.
- Source: Pine manual, Time page: "returns a UNIX timestamp corresponding to the user-specified date and time"
  (milliseconds).

**Qualifier propagation (`const < input < simple < series`).**
- `color.new` and `color.rgb` return the strongest qualifier among their arguments. Omitted arguments count as const;
  an argument of unknown type makes the result series (the conservative choice).
- Every other builtin keeps its declared return qualifier. Nothing is weakened globally.

**Time zones.**
- Accepted forms: `"UTC±H"`, `"UTC±HH:MM"`, `"GMT±HHMM"` and IANA names (`Asia/Kolkata`, `Asia/Calcutta`,
  `America/New_York` with DST).
- An unknown zone is a runtime error.
- With no argument, the exchange time zone is used, which is UTC in this engine.
- Source: Pine manual, Time page ("UTC-5", "UTC+05:30", "GMT+0100", "America/New_York", "Asia/Calcutta").

**Sessions: `time(timeframe, session, timezone)`.**
- Format: `"HHmm-HHmm[,HHmm-HHmm…][:days]"`, with days 1 (Sunday) to 7 (Saturday); `"24x7"` is also accepted.
- **No days means every day.**
- Each period is `[start, end)`, read in the given time zone.
- An **overnight** period (end ≤ start) belongs to the day on which it ends.
- The result is the bar's open time inside the session, and `na` outside.
- Only the chart's own timeframe is supported with a session; any other timeframe gives a clear runtime error.
- Source: Pine manual, Sessions page ("If unspecified, the session applies every day"; the overnight
  `"1700-1700:23456"` example; time() "returns … the opening time of the current bar, or na if the bar is not in the
  specified session").
- **POLICY (not documented).** A bar is judged by its **open time**. On this script's M15 chart every session boundary
  (03:30, 05:45, 17:00 and 18:30 IST) is a 15-minute boundary, so no bar straddles one. Straddling bars on other
  timeframes are unverified.

**Order comments on markers and in the trade list.**
- A non-empty order comment is shown instead of the order ID.
- This comes from the Pine reference for `strategy.entry` / `strategy.exit` / `strategy.order` `comment`; the manual
  pages fetched did not state it.
- It is display-only and awaits TradingView visual confirmation (manual step 1 below).

## Strategy feature audit (P3.1)

`strategy()` settings used by the script:

| argument | value | handling |
|---|---|---|
| `initial_capital` | 10000 | supported |
| `default_qty_type` / `default_qty_value` | `percent_of_equity`, 10 | supported: the first headless trade is 0.221633 lots = 10% × $10,000 / 4511.963 |
| `pyramiding` | 0 | one entry per direction, the same as 1 |
| `commission_type` / `commission_value` | percent, 0 | supported |
| `process_orders_on_close` | true | market entries fill at the signal bar's close |
| `calc_on_order_fills` / `use_bar_magnifier` | false | defaults |
| `max_boxes_count` / `max_labels_count` / `max_lines_count` | 500 | supported |

Strategy calls and state:
- `strategy.entry(id, strategy.long|short, comment=…)` — supported.
- `strategy.exit(id, from_entry=…, stop=…, limit=…, comment_profit=…, comment_loss=…)` — supported. It is re-issued
  every bar with a moved stop, and P3.1 **updates the same exit ID in place** (`Broker.exit`).
- `strategy.position_size`, `strategy.closedtrades` and `strategy.closedtrades.exit_bar_index()` — supported.

Not used by the script: `strategy.close`, `strategy.cancel`, trailing arguments, slippage and reversal orders.

## Language and runtime audit

All of the following compile and run, with outcomes shown by the acceptance run:
- a `const string` declaration;
- `input.bool` / `input.color` / `input.time`;
- a user function returning a tuple with history references (`[plusDI[1], …]`);
- `ta.dmi`, `ta.ema`, `ta.atr`, `ta.sma(ta.atr())`, `ta.lowest`/`ta.highest` on `low[1]`/`high[1]`;
- `request.security` of the chart symbol on "60" with `lookahead_on` and `[1]`/`[2]`, including a tuple from a user
  function;
- a `switch` expression with a default;
- nested ternaries;
- `var` scalars, `var box`/`line`, `var array<int|float>` with `array.push`;
- `+=`;
- block-local declarations repeated in sibling blocks;
- `syminfo.mintick`, `barstate.isconfirmed`, `time`, `time_close`, `bar_index`;
- `dayofweek.friday`/`saturday`;
- `box.new` (named arguments, `xloc.bar_index`), `box.set_right/top/bottom`;
- `line.new`, `line.set_x2/y1/y2`, `na` IDs;
- `label.new` (off by default);
- `plot` of `na`.

## Acceptance results

**Headless run** (`test_exact_script_runs_and_backtests_on_xauusdm`):
- **Data:** EXNESS XAUUSDm M15, with native H1 for `request.security`, 2025-12-23 → 2026-06-02 (10,355 bars). Rows
  from 2026-06-03 on are never read.
- **No runtime error.**
- **155 closed trades**, 108 winners (69.7%).
- **Net +$242.71 (+2.43%), profit factor 2.605.**
- 107 long and 48 short trades.
- **Drawings:** 226 boxes, 465 lines (3 per trade), 0 labels.
- **Remove/re-add:** a fresh execution reproduces the identical report.

**Browser** (`test_browser_gold_range_hunter.py`, real clicks on the production build):
- The run happens **inside Replay with the cursor at 2026-06-01**.
- Paste → Compile ("✓ Compiled", no problems) → Add to chart all succeed.
- Markers show the comments. The chart has boxes and lines, and the `input.time` fields show 2025-08-31 18:30 and
  2030-12-31 18:29 UTC.
- The Pine Strategy report lists **19 trades** for the 1,501-bar Replay window.
- Remove and re-add give the same 19 trades.
- The log has no "Pine script not added" rejection, and the page has no errors.

## TradingView comparison

### PINE SEMANTIC PARITY (feed-independent): pending the TradingView run

`strategies/grh_semantics_probe_v6.pine` logs, per M15 bar from 2026-05-07 21:00 to 2026-05-08 21:00 UTC:
- the `input.time` filter;
- both session times;
- IST month, weekday, hour and minute;
- both colour inputs.

`python -m ui.tradingview_mode.pine.parity.grh_probe TV_LOGS.txt` compares those values bar by bar. Bars that exist on
only one feed are listed separately as a DATA-SOURCE DIFFERENCE and never count as semantic.

Zoneflow's own values have been checked by hand: 9 morning-range bars (22:00–00:00 UTC) and 6 NY-range bars
(11:30–12:45 UTC) on Friday IST, and colour (33,150,243) with transparency 85.

### Full-strategy trade parity (same bars): tooling ready, pending TradingView exports

`strategy_parity.py` now accepts `--security-bars 60=FILE.csv`, so both engines can run on TradingView's own OANDA
M15 and H1 bars. `test_parity_harness_frozen_security_bars_reproduce_the_terminal_run` checks that this path
reproduces the terminal run trade for trade.

### DATA-SOURCE DIFFERENCE: indicative only, not parity

Zoneflow (Exness, v49 fixture, one continuous run, months by IST entry time) compared with TradingView figures in
Rahul's notes (OANDA, separate monthly Deep Backtests, **earlier script versions** v25/v35):

| month | Zoneflow trades / win % | TradingView trades / win % (version) |
|---|---|---|
| Jan 2026 | 31 / 67.7% | 32 / 75.0% (v25) |
| Feb 2026 | 33 / 69.7% | 27 / 77.8% (v35) |
| Mar 2026 | 30 / 63.3% | 24 / 70.8% (v35) |
| Apr 2026 | 29 / 72.4% | 26 / 69.2% (v25) |
| May 2026 | 22 / 72.7% | 24 / 75.0% (v25) |

The feed, the script version and the run structure all differ, so **no trade parity is claimed**. The only conclusion
is that the orders of magnitude are consistent.

## Manual TradingView steps (Rahul)

1. **Semantics.** Open OANDA:XAUUSD at 15 minutes and add `grh_semantics_probe_v6.pine`. Open Pine Logs, copy every
   `ZF|GRH|` line into a text file, then run `python -m ui.tradingview_mode.pine.parity.grh_probe that_file.txt`.
   While there, note whether the chart's strategy markers show "SETUP_A_BUY" / "TRAIL_SL" (the comments) or the IDs.
2. **Optional full parity.** Export chart data for OANDA:XAUUSD at 15 and 60 minutes over one pre-2026-06-03 window,
   plus the Strategy Tester's List of trades for v49 on the same window. Then run `strategy_parity.py FIXTURE.pine
   trades.csv --bars m15.csv --security-bars 60=h1.csv --mintick 0.001 --timeframe-seconds 900
   --tickerid OANDA:XAUUSD --currency USD`.

## Remaining limitations (script-specific)

- **Time inputs are UTC.** The inputs panel edits `input.time` in UTC, while TradingView's dialog uses the chart's
  time zone. The stored milliseconds are identical.
- **Chart timeframe only.** `time()` with a session works on the chart's timeframe only.
- **Bar-open rule.** Session membership uses the bar's open time (POLICY above).
- **`timestamp()` with a time zone** is still a gap, and `timestamp("…")` is not a `const int`, so
  `input.time(timestamp("…"))` is rejected. The script doesn't use either.
- **Comment display** is taken from the reference and not yet visually confirmed on TradingView.
- **Exchange time zone.** The exchange zone is UTC, so `syminfo.timezone` is `Etc/UTC`. TradingView's OANDA:XAUUSD
  uses America/New_York. That only matters for calls without a time-zone argument; the script passes "Asia/Kolkata"
  everywhere.

## Custom strategy workspace acceptance (Historical, full calculation range)

Test: `test_browser_gold_range_hunter.py`.

- **Setup:** the date range is 2026-05-01 → 2026-06-02, so Pine calculates on 2025-12-23 → 2026-06-02 (10,355
  bars, all before the Gold V2 sealed windows) while the chart renders May.
- **Trades:** **155**, matching the headless run on the same bars. Net +242.71 (+2.43%), win rate 69.68%, profit
  factor 2.605, max drawdown 27.00, max run-up 248.78, average bars in trade 5.2.
- **Fill → marker reconciliation:**

  | stage | fills | fills on loaded bars | markers rendered | fills outside loaded bars |
  |---|---|---|---|---|
  | May window | 310 (155 entries, 155 exits) | 46 | 46 | 264 |
  | after lazy-loading the oldest trade (#1, 2025-12-26) | 310 | 310 | 310 | 0 |

- **One instance by default:** an identical second Add to chart is refused, with Focus existing / Add another instance
  offered.
- **Layout:** the Strategy Tester opens by itself with the Pine source badge, and there is no separate Pine Strategy tab.
  Dock resize and collapse and all four focus modes pass. The frozen datasets are byte-identical after the run.
