# P3.1 — TradingView strategy engine (research, design, evidence)

Base: P2.3 frozen at `b828855` (`pine-p2.3-v1.0`). Labels: **DOC** (TradingView manual: *Strategies* concept page,
*Strategies* FAQ, v5→v6 migration guide), **OBS** (real TradingView q12 / q13 / q14 / Donchian runs, §9),
**ENGINE POLICY** / POLICY (engine choice where evidence is absent — never presented as parity), **ENGINE LIMIT** /
LIMIT (known unsupported or different behaviour), **DATA-SOURCE DIFFERENCE** (a bar value differing between
TradingView's feed and the frozen Binance bars — not an engine rule; §9.1).

**Acceptance (Donchian):** 246/246 trade sequence matched · 244/246 exact all-field matches · 2/246 data-source-only
one-tick differences (#103, #150) · 0 unexplained strategy-semantic mismatches. q12 (13 trades), q13 (6) and q14 (4):
exact in every logged trade and summary field.

**Scope of authority:** `ui/tradingview_mode/pine/strategy.py` is authoritative only for TradingView Mode Pine
strategy semantics. The audited backtester (`engine/`, `core/`) and its workflow are unchanged and not used by P3.1.

SIMULATION ONLY. The engine computes hypothetical orders, fills, positions and P&L from chart data. No code path
reaches MT5, Exness, Binance order/account endpoints, webhooks or alerts; execution stays disabled.

## 1. Architecture

* The existing authoritative backtester (`engine/backtester.py` → `core/adapters/audited_engine.py`) was inspected.
  Its semantics are fixed by design and by frozen research results: one global position and pending order
  (`BacktestConfig` rejects `max_simultaneous_positions != 1`), risk-based sizing, a fixed-R take-profit, SL-first /
  TP-first same-bar resolution, 15-minute contiguity, synthetic bid/ask Exness costs, registry strategies only, and
  every run recorded in an experiment ledger. TradingView strategies need reversals, pyramiding, fixed / cash /
  percent-of-equity sizing, multiple entry IDs, persistent `strategy.exit` brackets, trailing stops, the broker
  emulator's intrabar path and TradingView's cost model. None of this can be expressed through the audited adapter's
  API, and changing it would alter protected modules and frozen research results.
* Decision: a dedicated **TradingView broker emulator** inside TradingView Mode (`ui/tradingview_mode/pine/strategy.py`,
  not a protected area) is the authoritative simulator for Pine strategies. It reuses the Pine runtime (bar loop,
  realtime rollback, Replay / Live data paths) and TradingView Mode's presentation layer; it does not touch
  `app.py`, `strategies/`, `core/`, `engine/`, `mt5/` or the experiment ledgers (Pine runs write no ledger rows).
* Flow: Pine script → runtime (per bar: broker processes the bar's working orders along the intrabar path, then the
  script executes and issues `strategy.*` commands) → broker emulator (orders, fills, trades, equity) → state fed back
  to Pine (`strategy.position_size` …) → `RunResult.strategy` report → Pine Strategy tab + chart markers.

## 2. Documentation findings (DOC)

| # | finding | source |
|---|---|---|
| D1 | The broker emulator fills orders from chart data only; on historical bars after the bar closes; the earliest fill is the next tick, i.e. the next bar's open for orders placed at the close | Strategies › Broker emulator, Orders and trades |
| D2 | Intrabar path: open → high → low → close if the open is closer to the high than to the low, otherwise open → low → high → close; no gaps inside a bar; a level crossed between bars fills at the next open | Broker emulator |
| D3 | Market orders fill on the next tick; limit fills at its price or better; a limit placed worse than the market fills on the next tick; a stop placed better than the market activates immediately; stop+limit on entry/order = stop-limit (limit becomes active after the stop) | Order types |
| D4 | strategy.entry reverses: the order size adds the open position's size (15 long + 5 short → a 20 transaction, −5 position) | Reversing positions |
| D5 | Pyramiding (default 1) caps open trades from strategy.entry; price orders placed on one tick can all fill regardless | Pyramiding |
| D6 | strategy.order ignores pyramiding and nets the position (no automatic reversal) | strategy.order() |
| D7 | strategy.exit: profit/loss in ticks, limit/stop absolute; the level expected first is used when both are given; one call → an OCA bracket per entry; qty/qty_percent; calls reserve quantity in order; exits belong to an oca.reduce group | strategy.exit() |
| D8 | from_entry: exits for entries with that ID created on/before the call bar; unknown ID → no order. Without from_entry the call persists for every trade until the position closes | Exits for multiple entries |
| D9 | Trailing: activation at trail_price or entry ± trail_points ticks, offset trail_offset ticks; the stop follows the best price and triggers on a pullback; both activation parameters → the one reached first | Trailing stops, FAQ |
| D10 | strategy.close / close_all: market orders, next tick; `immediately = true` fills on the same tick (entry-bar close) | close/close_all, FAQ |
| D11 | strategy.cancel / cancel_all cancel unfilled orders; a market order can only be cancelled in the execution that placed it | cancel |
| D12 | Sizing: default_qty_type / default_qty_value; a non-na qty overrides; na qty → default | Position sizing |
| D13 | FIFO: exits close the oldest open trade first regardless of the exit's from_entry (close_entries_rule "ANY" changes it) | Closing a market position |
| D14 | OCA cancel / reduce / none for entry and order | OCA groups |
| D15 | A strategy executes once per closed bar unless calc_on_every_tick / calc_on_order_fills / calc_on_every_history_tick; process_orders_on_close lets orders placed at the close fill on that tick | Altering calculation behavior |
| D16 | Commission: percent of transaction value, cash per contract, cash per order; slippage: a fixed number of ticks against the order | Simulating trading costs |
| D17 | backtest_fill_limits_assumption: limits fill only when the price moves N ticks beyond, at the limit price | Slippage and unfilled limits |
| D18 | Margin: margin_long/short; margin-call liquidation algorithm (×4 cover amount) | Margin and leverage |
| D19 | v6: default margin 100 (v5: 0 = funds not checked); strategy.exit evaluates absolute and relative pairs (v5 uses the absolute one); `when` removed; >9000 trades trimmed (v5: error) | Migration guide to v6 |
| D20 | A trade can exit on its entry bar through price-level exits placed with the entry; position_avg_price is na until the entry bar's close | FAQ: exit in the same bar |
| D21 | Report limits: the latest 9000 trades | Trade limit |

## 3. Engine model

The status column is the pre-evidence classification; §9 records what the real TradingView runs settled and the
rules changed as a result (pyramiding at the fill, close order names, cash sizing, excursions, max drawdown, tick
rounding). Every other POLICY row that an oracle covered is now OBS-confirmed there.

| topic | model | status |
|---|---|---|
| order timing | commands at a bar's close → orders working from the next bar's open (market orders fill there); process_orders_on_close → market orders (and price orders already crossed) fill at that close | DOC (price orders at the close: POLICY) |
| historical path | D2; an exact tie between the open's distances is treated as "not closer to the high" | DOC; tie POLICY (no tie day in the oracle range) |
| price orders | limit / stop / stop-limit / gaps per D3; mid-path newly working orders that are already crossed fill at the current path price | DOC; mid-path POLICY |
| same-ID orders | a pending order with the same ID and command is modified in place (keeps its place in the queue) | DOC (manual reference behaviour) — OBS q12 S11 |
| reversal | D4, one transaction; the closed trade's exit signal is the new entry's ID | DOC |
| pyramiding | checked when strategy.entry places the order (open trades of that direction) | DOC notice — two market entries on one bar: POLICY, OBS q12 S8 |
| strategy.exit | per-trade brackets, reservation in call order, OCA inside a bracket, FIFO closing, v5/v6 level precedence, persistence rules D8; repeated calls with the same ID update the command in place | DOC; persistence across a reversal: POLICY (removed when the position closes), OBS q12 S7 |
| trailing | activation and offset D9; the best price is tracked along the intrabar path, so activation and stop-out can happen on the entry bar and a bar that activates on its way up can stop out on its way down | DOC + POLICY — OBS q12 S4 / S5 / S6, Donchian |
| market cancellation | only within the placing execution | DOC |
| sizing | fixed; cash = value / price; percent_of_equity = equity × value% / price, where price = the close of the bar that places the order; no rounding | fixed DOC; reference price and rounding POLICY — OBS q13 |
| commission | percent × fill value, per contract × qty, per order per fill; a reversal is one order (per-order fee split by quantity) | DOC; reversal split POLICY — OBS q13 C4 |
| slippage | market and stop fills (incl. stop-loss, trailing, stop entries) move `slippage` ticks against the order; limit fills do not | direction DOC; classes POLICY — OBS q13 |
| margin | margin 0 → no checks (v5 default); margin > 0 → an entry needing more than the available funds is not filled; margin calls are not simulated | v5 DOC; entry check POLICY — OBS q14; margin calls LIMIT |
| state | position_size / avg price / trade counts / net, gross, open profit / equity / max run-up and drawdown / per-trade functions; history `[n]` returns the state the script saw on that bar | DOC names; open profit excludes commissions: POLICY |
| execution settings | calc_on_every_tick, calc_on_order_fills, calc_on_every_history_tick, use_bar_magnifier, close_entries_rule "ANY", currency ≠ NONE, calc_bars_count: compile-time capability gaps | LIMIT |
| strategy.risk.* | capability gaps | LIMIT |

## 4. Realtime, Replay, Live paper

* Historical: deterministic — same bars, script, inputs, settings and symbol data → identical orders, fills, trades,
  equity (tested).
* Replay: one execution per revealed bar; the broker only sees bars up to the cursor, so no order, fill, trailing
  update or trade can use N+1 (tested: no event after the cursor, incremental Replay == fresh truncated run).
* Live paper: a strategy executes once per closed bar (DOC). On the open realtime bar only the broker runs, over the
  bar received so far with the historical path model, restarting from the committed state on every poll (the broker
  state is snapshot at the start of the last bar and restored on rollback); the script executes when the bar closes.
  LIMIT: TradingView fills realtime orders on the actual tick sequence; the engine sees successive OHLC snapshots,
  so realtime fills follow the path model over the received bar (never synthesised future ticks).

## 5. request.security

`strategy.*` commands and state never run in a requested context: they are side effects (slicing rejects them in
the expression or its dependency slice); the child runtime has no broker. P2.1–P2.3 restrictions unchanged.

## 6. Oracle package (run on TradingView; results in §9)

All on **BINANCE:BTCUSDT.P, 1D** (the whole history since 2019-09-08 loads, so TradingView and the frozen bars start
on the same bar). Result of each run: Strategy Tester → *List of trades* → *Download* (CSV). The comparison tool
reads the CSV from `~/Downloads`, detects the chart timezone and compares trade by trade.

| file | SHA-256 | questions |
|---|---|---|
| `strategies/q12_strategy_orders_v6.pine` | `27369559a27873c47998262bbb8079547a906d1dc6c470e9a2898eb4db027947` | S1 next-open market fills; S2/S3 same-bar bracket by path; S4/S5/S6 trailing (same bar, path vs "high first", across bars); S7 exit persistence across a reversal; S8 two market entries, pyramiding 1; S9 limit above the market; S10 stop below the market; S11 same-ID modification; S13 close(immediately) |
| `strategies/q13_strategy_costs_v6.pine` | `a6b72b2b486adaa3ec9fc01ed9a3573c85692b3eebc1f5f322f69058035415ca` | cash sizing reference price and rounding; commission per order (incl. a reversal); slippage on market / limit / stop / trailing fills |
| `strategies/q14_strategy_margin_close_v6.pine` | `2ce88cb27cd7f0a5f446dfe8641ce03f3d26e38a882a86a5d7e90c43261b7f0f` | v6 default margin (100 %): an entry larger than the funds, a second entry beyond the funds; process_orders_on_close for market, stop and limit entries |
| `strategies/s01_donchian_trailing_v5.pine` | `009965e7becc2ffd27fe371cb1950c850582d9972ba4975b33c7e0945397bb99` | acceptance strategy, unchanged source (v5) |
| `strategies/data/BINANCE_BTCUSDT.P_1D.csv` | `61a51be41596f75da8075130271eb9fb8f8ddcbfed08197d864d20aecc066b82` | frozen bars: Binance USD-M futures public klines, 2019-09-08 … 2026-09-27 (2577 closed daily bars); tick 0.1 |

Engine predictions on the frozen bars before the runs (see §9 for the observed results):

* q12: S1 98173.2→98340.2; S2 TP 94999.9 on 2025-01-13; S3 SL 100811.5 on 2025-01-20; S4 trail 101629.3 on the entry
  bar; S5 trail 97590.9 on 2025-02-13 (not on the entry bar); S7 long reversed at 96218.4, the short stays open until
  the flatten (exit not carried over); S8 both entries fill; S9 fills at the 03-27 open 86873.9; S10 at the 04-02 open
  85121.0; S11 one trade at 78140.0; S6 trail 91904.3 on 2025-04-23; S13 closes at the 06-03 close 105330.1.
* q13: C1 qty 10000/105637.9 = 0.0946630…, entry 105639.9 (+2 slippage), exit 109543.1 (−2); C2 limit fill without
  slippage; C3 stop fills ±2; C4 reversal fee split; C5 trailing exit −2.
* q14: M1 and M5b not filled (margin); M2/M3/M4 fill on the signal bar's close.
* Donchian: 246 closed trades on the frozen bars.

Donchian v5 vs v6: not run twice — the migration guide settles the only differences that could matter (margin,
absolute/relative precedence); the acceptance script uses neither.

### 6.1 Pine Logs workflow (TradingView Basic: no CSV export)

The frozen oracles stay unchanged. Each has a `*_logged.pine` copy = the frozen file byte for byte + an appended,
read-only observation block (no order, `strategy()` setting or input change; tested: the original is an exact byte
prefix and the trades are identical with and without the block). On `barstate.islastconfirmedhistory` the block
emits `ZF|<TAG>|BEGIN`, one `ZF|<TAG>|TRADE|n|entry_id=…|size=…|entry_time=<UTC ms>|entry_bar=…|entry_price=…|
exit_id=…|exit_time=…|exit_bar=…|exit_price=…|profit=…|commission=…|runup=…|drawdown=…` per closed trade (from
`strategy.closedtrades.*`), `ZF|<TAG>|OPEN|…` per open trade and `ZF|<TAG>|SUMMARY|…`; numbers use
`str.tostring(v, "#.########")` (no locale grouping). q12–q14 also draw one compact table (screenshot fallback).

| logged copy | SHA-256 | log lines on the frozen bars |
|---|---|---|
| `strategies/q12_strategy_orders_v6_logged.pine` | `073277f6372bf0eda0edd4039f66ce3f0bdc423eb1df0857e56ee0b360910de4` | 16 |
| `strategies/q13_strategy_costs_v6_logged.pine` | `6ca0d106e58b92732223208397402c847345756270f936000673661415639d25` | 8 |
| `strategies/q14_strategy_margin_close_v6_logged.pine` | `d7499e06f92728144707de1faa0fd29fa593eb74b55632b381be661ec7c7319e` | 6 |
| `strategies/s01_donchian_trailing_v5_logged.pine` | `6e279756db6671eebc85504579abe1102767fdf88c512f06f03483664fb65cba` | 248 (far below the 10,000 Pine Logs limit; one run) |

`strategy_parity.py` reads either TradingView's CSV or copied Pine Logs (lines from the first `ZF|`; timestamp
prefixes and other lines are ignored) into the same trade records. The engine now implements `log.info()`,
`log.warning()` and `log.error()` (collected on the run) so the logged copies also run locally.

## 7. Maintenance note (pandas 3)

The baseline failure `test_harness_reads_spot_checks_and_iso_times` (pandas 3 parses ISO times at microsecond
resolution) is not needed by P3.1: the strategy comparison tool parses TradingView's CSV with `datetime` directly
and never uses that harness. The baseline is left untouched.

## 8. Engine limits and policies (P3.1)

ENGINE POLICIES (not TradingView-proven): the 6-decimal quantity step outside BINANCE:BTCUSDT.P; percent_of_equity
sizing at the fill price; limit fills on the nearest tick; max run-up (mirror of the observed max drawdown rule); an
exact tie in the open's distance to high/low; Live paper fills over the received bar (not TradingView's tick
stream). `log.*` is supported for runtime collection and parity tooling; the terminal does not display logs yet.

ENGINE LIMITS:

calc_on_every_tick; calc_on_order_fills; calc_on_every_history_tick; bar magnifier; close_entries_rule "ANY";
account-currency conversion; strategy.risk.*; margin calls; percentage metrics other than net/gross profit; realtime
fills on true ticks (Live paper uses OHLC snapshots); alerts from order fills (never sent).

## 9. Reconciliation with the real TradingView runs (authoritative OBS)

Evidence (Pine Logs exports of the `*_logged.pine` copies, TradingView Basic, BINANCE:BTCUSDT.P 1D, default
settings), frozen in `strategies/evidence/`:

| file | SHA-256 |
|---|---|
| `tradingview_q12_pine_logs.csv` | `5b1f76be89e0dd4c953ec8ff16056b893ab43f5c8d568d7319e027c622daf4c5` |
| `tradingview_q13_pine_logs.csv` | `fc334a00efc0676e54f48f9ae7ec2feb3de1b9f34ff1ae755b1ed45f9416bf69` |
| `tradingview_q14_pine_logs.csv` | `8a424cf7784ea973947c717981a0be8e9becaef85f4279f5da33bda09a498fb4` |
| `tradingview_donchian_pine_logs.csv` | `ca4805c1951c721a61c11439072b1e573acfe42e099446e2cf9c467cea4c589b` |
| `donchian_parity_report.json` | machine-readable Donchian report (generated by `strategy_parity.py --json`) |

| former policy / question | TradingView (OBS) | engine before | result |
|---|---|---|---|
| q12 S1 market timing (next open, both ways) | 98173.2 → 98340.2 | same | MATCH |
| q12 S2/S3 same-bar bracket by intrabar path | TP 94999.9 / SL 100811.5 on the entry bar | same | MATCH |
| q12 S4 trailing on the entry bar (activation + stop-out, path best price) | exit 101629.3 on the entry bar | same | MATCH |
| q12 S5 trailing: open→low→high→close entry bar is not "high first" | exit 97590.9 on the next bar | same | MATCH (path model confirmed) |
| q12 S6 trailing across bars | exit 91904.3 on 2025-04-23 | same | MATCH |
| q12 S7 exit without from_entry across a reversal | not carried over (the short stays open) | same | MATCH |
| q12 S8 two market entries, pyramiding 1 | only S8a | both filled | **ENGINE BUG → fixed**: a market entry is not filled when the pyramiding limit is reached at the fill |
| q12 S9 buy limit above the market / S10 buy stop below | next open 86873.9 / 85121 | same | MATCH |
| q12 S11 same-ID entry modified | one trade at 78140 | same | MATCH |
| q12 S13 strategy.close(immediately) | entry-bar close 105330.1, exit ID `Close entry(s) order S13` | price same, exit ID `S13` | **ENGINE BUG → fixed**: close order name |
| trade run-up / drawdown | tracked along the intrabar path until the exit (S2: 500 / 0) | whole-bar high/low | **ENGINE BUG → fixed** |
| q13 cash sizing | quantity = cash / fill price (slippage included), truncated to 6 decimals (C1 0.094661, C2 0.086595) | cash / signal close, no truncation | **ENGINE BUG → fixed** (6-decimal step: OBS for BINANCE:BTCUSDT.P only, ENGINE POLICY elsewhere; percent_of_equity uses the same rule: ENGINE POLICY) |
| q13 commission per order, reversal split by quantity | C4L 4.52513641, C4S 4.47486359 | same | MATCH |
| q13 slippage classes | market ±2, stop entry +2, stop-loss −2, trailing −2, limits none | same | MATCH |
| q13 excursions | net of the trade's entry commission; the exit fill (slippage included) counts | gross | **ENGINE BUG → fixed** |
| q14 v6 default margin 100 % | M1 (1 BTC) and M5b (beyond funds) not filled | same | MATCH |
| q14 process_orders_on_close (market, stop below close, limit above close) | all fill on the signal bar's close | same | MATCH |
| strategy max drawdown | peak of closed-trade equity − (closed equity + open trade drawdown net of entry commission): q12 8372.6, q13 195.0878876, q14 324.17, Donchian 2809.9 | intrabar equity peak | **ENGINE BUG → fixed** (max run-up: symmetric, POLICY) |
| prices on 2-decimal data with a 0.1 tick | market fills at the nearest tick; stop levels rounded away from the market; excursions on the nearest tick (Donchian trade 0: 7465.2 / 7367.5, run-up 127.8, drawdown 30.6) | raw prices | **ENGINE BUG → fixed** (limit fills: nearest tick, POLICY) |

After the fixes q12 (13 trades), q13 (6) and q14 (4) match TradingView exactly in every logged field (IDs, sizes,
times, bars, prices, profit, commission, run-up, drawdown) and in every SUMMARY field.

### 9.1 Donchian acceptance (frozen original `s01_donchian_trailing_v5.pine` on the frozen bars)

* 246 TradingView trades, 246 engine trades; **244 identical in every field**.
* 246/246 trade sequence matched (order, IDs, direction, size, entry/exit bars and times, exits).
* Trades #103 (2022-08-29, short) and #150 (2024-02-13, long): identical bars, times, IDs, sizes and exits; the entry
  price differs by exactly one tick — TradingView's daily open is 19547.6 / 49943.5, the Binance kline open in the
  frozen bars is 19547.5 / 49943.6 (the engine fills at that open itself). Classification: **data-source difference**
  (provider bar open), not an engine rule, not a broker-emulator divergence and not a tolerance; the emulator is not
  changed to reproduce TradingView's price. It carries into those trades' profit / run-up / drawdown (±0.1) and into
  net profit (TradingView 337469.4 vs 337469.2), gross profit (337496.1 vs 337496.0), gross loss (26.7 vs 26.8) and
  equity; closed 246, wins 241, losses 5, even 0, max drawdown 2809.9, open 0, position 0 are identical.
* The result is a PARITY acceptance case only: it reproduces TradingView's broker-emulator assumptions (very small
  trailing distances on daily bars fill inside the bar along the assumed path). It is not evidence that the strategy
  is profitable in real trading.
