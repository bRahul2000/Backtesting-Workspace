# TradingView Mode terminal contract (v1)

Python is authoritative. The React terminal renders the payload and sends
explicit events. It never calculates indicators, trade outcomes, stops,
targets or metrics, and never falls back to another provider or timeframe.

- Python side: `protocol.py` (payload + event schema), `state.py` (semantic
  validation, `apply_event`), `terminal.py` (Streamlit glue).
- Frontend side: `frontend/src/events.js`, `frontend/src/chart/ChartEngine.js`.

## Transport: data files and fragment reruns

- The terminal runs in an `st.fragment` (ui/tradingview_mode/page.py): a terminal event reruns the terminal only,
  never the whole app. The fragment re-validates the login session on every run (`gate.recheck_session`).
- Large payload values are sent once as content-addressed data files (component/blobs.py): a list of 64+ items
  becomes `{"$blob": "/media/<hash>.json", "tail": [last 2 items]}`, any other value over 16 KB becomes
  `{"$json": "/media/<hash>.json"}`. The frontend (src/blobs.js) rebuilds the identical payload before rendering and
  keeps each file by URL. While files load, no event is sent; a file that cannot be loaded keeps the previous view
  and sends `resync`.

## Time

Every chart time is an **integer Unix epoch in seconds, UTC**. Python converts
UTC pandas timestamps with `protocol.epoch_seconds` and rejects naive or
non-UTC timestamps instead of reinterpreting them. The frontend formats times
as UTC and applies no local-timezone conversion. Date ranges in events are ISO
`YYYY-MM-DD` UTC dates, inclusive at both ends.

## Payload (Python → frontend)

`terminal.build_terminal_payload` builds the payload and `protocol.validate_payload` checks it before it is sent.

| Field | Meaning |
|---|---|
| `contract` | `1`. The frontend refuses other versions. |
| `mode` | `"historical"` (the only mode this phase). |
| `dataset_key`, `symbol`, `provider`, `instrument` | Identity of the selected registry dataset. |
| `timeframe` | Resolved canonical label, e.g. `"4h"`. Always one of `timeframes`. |
| `timeframes` | Timeframes Python can serve for this provider/symbol (native or safely derived). |
| `view_key` | `instrument\|provider\|symbol\|timeframe`. The frontend resets the view only when this changes. |
| `source` | `{dataset_key, label, provider, symbol, timeframe, native, description, read_only}`. The provider and symbol must equal the payload's own. |
| `range` | `{start, end, min, max, is_default}` as ISO dates. |
| `bars` | `[{time, open, high, low, close, volume}]`. Strictly increasing int `time`, finite floats. |
| `bars_rev` | Fingerprint of `bars`. The frontend calls `setData` only when it changes. |
| `price_precision` | Display decimals derived from the data. |
| `overlays` | Price-pane indicators, as generic plot definitions (ui/tradingview_mode/indicators.py): `[{id, key, name, label, params, visible, status: ok\|limited\|unavailable, note, scale, series:[{name, title, type: line\|histogram, color, width, style: solid\|dashed\|dotted, data:[{time, value, color?}]}], fills:[{upper, lower, color}], levels:[{value, title, color, style}], markers:[{time, position, shape, color, text}]}]`. Hidden instances are included (`visible: false`) so showing one is instant; an `unavailable` one carries no data and says why in `note`. |
| `panes` | Lower-pane indicators, same shape; each gets its own pane (unless unavailable). |
| `indicators` | All active instances, including hidden ones: `{id, key, name, enabled, params, pane, color}`. |
| `indicator_catalog` | The Indicators menu: `{key, name, category, pane, defaults, params:[{name, label, kind, default, min, max, step, choices}], status, note, description}`. `unavailable` items are listed disabled with their reason (never clickable, never silently empty). |
| `datasets`, `watchlist` | Registry entries; watchlist rows carry `last_close`, `change_pct`, `price_precision`, `selected`. |
| `ui` | `{bottom_panel, bottom_open, show_volume}`. |
| `logs`, `notices` | Python log entries and current warnings or errors (clipping, truncation, rejected events). |
| `capabilities` | `drawings / strategy_tester / trades / replay / live`, all `false` for now. |
| `strategy`, `trades` | Reserved for Python-computed results (`null` / `[]`). |
| `max_bars` | Bar cap per payload (50,000). |
| `ack` | Id of the last frontend event Python processed. |

Indicator series `data` contains only bars with a value. Warm-up NaNs are
omitted, never zero-filled, and every point time is an existing bar time.

## Events (frontend → Python)

Shape: `{"id": "<nonce>-<seq>", "type": "<type>", "data": {...}}`. Unknown types
and unknown or missing fields are rejected (`protocol.parse_event`).

| Type | Data | Python rule |
|---|---|---|
| `chart_ready` | – | Logged; clears the handshake notice. |
| `frontend_error` | `message` | Logged as an error. |
| `select_dataset` | `dataset_key` | The key must exist and have data. It selects that dataset's **native** timeframe and resets the range to the default. |
| `select_watchlist_item` | `dataset_key` | Same as `select_dataset`. |
| `select_timeframe` | `timeframe` | Must be in `available_timeframes(dataset)`. Otherwise it is rejected and the state is unchanged. |
| `set_date_range` | `start`, `end` (ISO or both `null`) | Requires start ≤ end, an overlap with the data, and ≤ 50,000 estimated bars. Both `null` restores the default window. |
| `add_indicator` | `key`, `params?` | The key must be chartable (not `volume`). Params are typed and bounded, and MACD needs fast < slow. |
| `update_indicator` | `id`, `params` | Merged, then fully revalidated. |
| `toggle_indicator` | `id`, `enabled` | – |
| `remove_indicator` | `id` | Ids are never reused. |
| `set_bottom_panel` | `panel`, `open?` | `panel` is one of `indicators, strategy_tester, trades, logs`. |
| `set_chart_setting` | `show_volume` | – |
| `resync` | – | No state change: the next payload is sent fresh (the frontend could not load a data file). |

A rejected event leaves the state untouched, adds an `error` log entry, and
shows up as a notice on the next payload. Nothing is silently substituted.

### Exactly-once delivery

A Streamlit v1 component keeps its last value across reruns, and a new value
restarts an in-flight rerun. For that reason:

1. Python reads the pending event from `st.session_state` **before** building
   the payload, applies it only if its `id` differs from the last processed
   id, and echoes that id back as `ack`.
2. The frontend sends one event at a time and queues the rest until `ack`
   matches. A 60 s safety valve unblocks the queue and logs a warning.

## Default range

When no explicit range is set, the window is the latest
`max(30 days, ≈2,000 bars)`. An explicit range that falls partly outside the
data is clipped, and the clipping is reported as a notice.

## Client-only state (never sent to Python)

Zoom, pan and the visible range (stored in `sessionStorage` per `view_key`),
crosshair mode, open menus and legend values. The frontend never calls
`fitContent` on rerun. It fits only on the explicit "Fit" action.

## Strategy Tester

Pipeline: `run_backtest` event → `tester.validate_run_request` → `core.config.BacktestConfig`
→ `core.adapters.audited_engine.run_universal_backtest` → `UniversalBacktestResult`
→ `tester.build_run_payload`, which only reshapes the result for display. There is no
second engine, and results are not cached.

**`run_backtest`** takes `{strategy_id, dataset_key, broker_profile, dataset_role, start, end, ledger_mode, parameters?, settings?}`.
- **Strategy:** must come from `discover_builtin_strategies()`.
- **Dataset:** must be registered and exist. Its instrument must be in the strategy's
  `supported_instruments` and its timeframe in `supported_timeframes`. A backtest
  timeframe is never derived from the chart timeframe.
- **Broker profile:** only profiles the audited adapter accepts (`EXNESS_STANDARD`).
- **Parameters:** typed per `StrategyParameter` and checked with `validate()` and
  `descriptor.create()`. Frozen parameters can't change, and only values that
  differ from the defaults are passed as overrides.
- **Settings:** limited to the `BacktestConfig` fields the adapter reads.
- **Range:** `end` includes the last bar of that UTC date. Dates outside the
  dataset are rejected, not clipped.

**Ledger mode (required, never inferred).** `scratch` is the UI default and records
into `experiments/scratch/tradingview_mode.sqlite3` (git-ignored). It can never
resolve to the research ledger. `research` records into `experiments/experiments.sqlite3`
and must be chosen explicitly for each run. The mode appears in the status, the
Properties tab and the exports.

**Other events:**
- `clear_backtest`: hides the displayed result.
- `restore_run {history_id}`: shows a result from the in-memory session history
  (the last 10 runs) without executing anything.
- `export_run {history_id, kind: trades_csv|summary_json}`: Python generates the
  file and puts it in the payload once as `tester.export {id, filename, mime, content}`.
  The frontend downloads it by `id`.
- `trades_csv` is the complete `trade_log` with every field unchanged, plus a
  leading `segment` column.
- `summary_json` contains run metadata, ledger, fingerprints, all `BacktestConfig`
  properties, the result's summary, directional, yearly, monthly, diagnostics and
  ambiguity data, and a separate `python_derived` block.

**Exactly once.** A run executes synchronously inside the rerun that consumes its
event id, and the id is persisted afterwards. Selecting a trade, filtering,
searching, sorting and Previous/Next are frontend-only and send no event.

**Trade identity.** The engine restarts `trade_id` in every continuous data segment.
Each trade therefore carries `key`, its position in `trade_log` (unique), and
`segment`, taken from `equity_curve`. Selection, chart markers and `trade_overlay`
items all use `key`. The UI labels trades `segment/trade_id`.

**Payload `tester`:** `{status, error, form, options, run, history, active_history_id, export}`. `run` contains:
- `run_id`, `ledger`, `fingerprints`, `strategy` (with `frozen`), `dataset`, and the
  exact executed `config`
- `summary` (the result's values) and `directional`
- `periods.monthly` / `periods.yearly`: exactly the result's per-period fields, which
  are trades, win_rate, profit_factor, average_r and pnl. There is no per-period
  drawdown.
- `trades`, `curves`, `open_positions`
- `diagnostics`: `execution_diagnostics` fields, slippage from the config, the
  ambiguity count, and the first 200 ambiguities
- `python_derived`: values the result does not carry, derived in Python from it and
  labelled as such. These are winning/losing counts, P&L %, max winning streak
  (the adapter's per-segment rule), gap-through fills, leverage-capped trades,
  entry models and commission totals.

React may filter, search, sort and select these rows. It never computes P&L, win
rate, profit factor or trade outcomes; `tests/tradingview_mode` guards this.

**Payload `trade_overlay`:** `{available, reason, trades: [{key, entry_bar, exit_bar}]}`. Markers are
only drawn on the tested instrument/provider/symbol, and each exact time maps to
the chart bar that contains it. The selected trade gets Entry, SL and TP as bounded
segments from its entry bar to its exit bar, at the exact `trade_log` prices.

## Replay (historical bar replay)

Python owns the replay, which lives in `replay.py` and in `TerminalState.replay`.
The state is `{dataset_key, timeframe, start_timestamp, cursor_timestamp, anchor_timestamp, playing, speed}`.
All times are UTC epoch seconds for bar **open** times. It is stored per Streamlit session.

**No lookahead.** Each run slices the resolved dataset/timeframe frame to
`anchor..cursor` **before** serialization. Indicators (EMA, SMA, VWAP, Bollinger,
RSI, MACD, ATR) and volume are calculated on that slice only. The anchor sits
up to 1,500 bars before the start and stays fixed while stepping, so a step
changes exactly one bar and earlier indicator values stay identical.
`validate_payload` rejects any bar, indicator point or trade marker after the cursor.
A test rewrites every future bar and requires the payload to be byte-identical.

**Events** (exactly once, like every other event):
- `enter_replay {start}`: `start` is UTC text `YYYY-MM-DDTHH:MM`. Replay starts at
  the bar that opens at or before this time. A time before the first bar is rejected.
- `set_replay_start {start}` restarts. `jump_replay {to}` moves the cursor; a jump
  before the start also moves the start.
- `step_forward` / `step_backward` reveal or hide exactly one bar. The bounds are
  the start bar and the last historical bar.
- `play_replay`, `pause_replay`, `set_replay_speed {speed ∈ 1,2,5,10}`.
- `go_to_replay_latest` (view only) and `exit_replay`, which restores the historical view.
- While replay is active, dataset, timeframe and date-range changes are rejected.
  Nothing switches provider or timeframe silently.

**Playback.** A browser timer requests one `step_forward` every `1000/speed` ms,
and only when no event is waiting for Python. The real rate therefore never
exceeds the server round trip. Measured locally with four indicators, it was
1, 5 and about 10 bars/s at 1x, 5x and 10x. Reaching the last bar pauses playback.

**Payload `replay`:** `{enabled, dataset_key, timeframe, start_timestamp, cursor_timestamp,
cursor_index, revealed_bar_count, total_available_bars, playing, speed, speeds, at_start, at_end}`.
It contains no timestamp after the cursor. `total_available_bars` and the date
bounds used by the date pickers are the only information about the rest of the dataset.

**Trades and the Strategy Tester.** A stored backtest result is never changed or
rerun. During replay, anything is "knowable" if it happens before the close of
the newest revealed bar (`cursor_timestamp + bar seconds`). Python sends
`tester.replay_view(run)` instead of the run:
- Trades that closed before that point are shown in full.
- Trades entered before it but closing later are shown as `status: "open"`, with
  entry-time fields only: entry, SL/TP levels, quantity, setup and entry model.
- Later trades are omitted, and so is their count.
- Every whole-run aggregate is removed: summary, curves, monthly/yearly/directional
  statistics, Python-derived values, diagnostics and open positions. The tester
  shows "Full backtest statistics are hidden during Replay to prevent future-data leakage."
- Run history rows lose trades, P&L and win rate, and `export_run` is refused.

`validate_payload` enforces all of this, and exiting replay sends the full run
again. `trade_overlay` draws only trades that closed within the revealed bars,
and the selected trade's SL/TP segments come from that overlay. The watchlist
shows reference last closes, labelled as not replay prices.

## Live (read-only market data: Binance Futures or Exness MT5)

Two markets, each from one of two sources. The sources are **different
instruments** and are never mixed:

| Market | Binance Futures (default) | Exness MT5 |
|---|---|---|
| BTC | BTCUSDT Perpetual (`PERPETUAL`) | BTCUSDm (CFD) |
| Gold | XAUUSDT Perpetual (`TRADIFI_PERPETUAL`) | XAUUSDm (CFD) |

`providers.py` defines the markets, the `LiveState(market, source, timeframe,
streaming)` and the two providers, which share one interface: `view(now) ->
LiveView(frame, status, identity)`. React only renders what a view contains.

- **Binance Futures** (`binance.py`) uses public market data only: no API key,
  account, order or user-data endpoint. REST calls are `GET /fapi/v1/{exchangeInfo,
  klines,time}` on `fapi.binance.com`. WebSockets are
  `wss://fstream.binance.com/market/stream?streams=<sym>@kline_<tf>/<sym>@markPrice@1s`
  (klines and mark price) and `wss://fstream.binance.com/public/stream?streams=<sym>@depth5@500ms`
  (best bid/ask). Kline streams are served on `/market` only and book streams on
  `/public` only. A kline subscription on the legacy `/ws` root is accepted but
  never delivers a message.
- **Exness MT5** (`live.py`) is the read-only file bridge: the MQL5 service
  `mt5_bridge/TradingViewLiveFeed.mq5` writes into MetaTrader's Common/Files and
  Python only reads (see `mt5_bridge/README.md`).

**Events:** Live has two steps, and entering the mode connects nothing.
- `enter_live {}` opens Live **setup**. The chart keeps the historical dataset. The
  market is preselected from the dataset's instrument (BTCUSD → BTC, XAUUSDm → Gold),
  and the source defaults to Binance Futures. A dataset with no live feed of its own
  (Bitstamp BTC/USD) shows an explicit message that Live shows the chosen source, a
  different instrument. An instrument with no live market shows "Live mode supports
  BTC and Gold (Binance Futures or Exness MT5)."
- `go_live {market ∈ BTC, GOLD; source ∈ binance, exness; timeframe ∈ 15m, 30m, 1h}`
  starts streaming. Sent again while streaming, it switches market or source and
  keeps the timeframe. Only native periods are allowed on both sources.
- `exit_live` leaves Live from either step.
- `live_poll`: the browser sends it about once a second while streaming, only when
  no event is in flight. It changes no state and is not logged.
- `load_live_history {}`: the chart sends it when the view reaches the left edge,
  once per edge and only when idle. Binance prepends up to 1,000 older completed
  candles. Exness answers that the MT5 bridge has only its last 500 bars. Outside
  streaming the event is rejected.
- While Live is on, dataset and date-range changes are rejected, and Replay can't
  start. While streaming, `select_timeframe` changes only the live timeframe. Live
  can't start during Replay. The historical selection is restored unchanged on exit.

**Provider switch:** `terminal.sync_live_connections` runs every rerun and acts only
when `(source, symbol, timeframe)` changes. It clears the MT5 books and releases the
session's Binance kline lease, which closes that socket. On exit it releases the quote
lease as well. A switch is a new `view_key`, so the chart reloads instead of
tail-updating across providers, and indicators are recalculated from the new bars.
There is no silent fallback: an offline source shows its own DISCONNECTED/ERROR state.

**Connection ownership (Binance):** sockets live in the process-wide
`binance.hub()`, never in a rerun. A session (id in `st.session_state`) holds at most
one kline lease and one quote lease. Asking again returns the same stream, so there is
no duplicate subscription, and two tabs on the same market share it. A stream stops
when its last lease is released, or by itself when no rerun has touched it for 180 s
(a closed tab cannot leak a thread or socket).

**Binance lifecycle:**
- Each connection is recycled 30 minutes before Binance's 24 h limit and reconnects
  after any close, with exponential backoff (1 → 30 s, jittered). There is no busy loop.
- Server pings are answered with pongs by the `websockets` library, and the client
  sends no pings. `markPrice@1s` makes the socket speak every second, so the stream is
  STALE after 5 s of silence and reconnects after 20 s.
- After every (re)connect, recent klines are fetched over REST and reconciled: gaps are
  filled, and a candle that closed while disconnected finalizes exactly once.

**Kline merge (Binance):**
- A 2,000-bar REST seed (15m ≈ 21 days), paged backwards 1,000 bars per request with
  `endTime`. Pages must not run past their end time; the result is de-duplicated,
  sorted and validated. A REST bar is final once its close time has passed on the
  server clock.
- Older history (`load_live_history`) is prepended: only completed candles strictly
  older than the first loaded one, and loaded candles never change. The window is capped
  at 5,000 bars (15m ≈ 52 days, 1h ≈ 208 days) because the whole window is re-sent
  every poll (about 1.9 MB with four indicators). `live.more_history` is false at the cap
  or at the start of Binance's history.
- WebSocket kline updates replace the forming candle in place. `x: true` finalizes it
  exactly once; a finalized candle never changes again.
- Identical updates are duplicates. An older event time, or an update to an older
  candle, is rejected and counted. Queued messages older than the REST snapshot are
  superseded (ignored, not counted as errors).
- A missed final message or a gap triggers REST reconciliation.
- Malformed messages are rejected, never drawn: wrong symbol or interval, misaligned
  or inconsistent times, non-finite or non-positive prices, high/low inconsistent with
  open/close, negative volume, or ask < bid.

**Exness merge (MT5):** book, then the seed file, then the newest quote bars, keyed by
bar time with later sources winning. Snapshots with the same `seq` are duplicates. A
lower `seq` or an older tick from the same writer is rejected; a new `writer_id` starts
a new sequence.

**Payload (streaming):**
- `mode: "live"`, and `dataset_key` = `source.dataset_key` = `live.identity.dataset_key`,
  which is `BINANCE_LIVE:<symbol>` or `MT5_LIVE:<symbol>`. `symbol`, `provider` and
  `instrument` come from the active provider (e.g. "BTCUSDT", "Binance Futures",
  "BTCUSDT Perpetual").
- `live` = `{status, reason, market, source, source_label, symbol, provider, title
  ("BTCUSDT Perpetual · Binance Futures"), timeframe, identity, note, quotes: [{key,
  label, value, title}], digits, bid, ask, spread, updated_utc, heartbeat_age_s,
  tick_age_s, forming_bar_time, bar_count, rejected_updates, markets, sources,
  timeframes, contracts, indicators_include_forming_bar: true}`.
  - Binance quotes are Last, Mark, Bid, Ask and Spread; Exness quotes are Bid, Ask and
    Spread. Each is labelled with its source.
  - `note` is "Reference market feed — execution prices may differ from Exness." on
    Binance, and `null` on Exness.
  - `identity` keeps venue, contract type, instrument kind, volume unit and time basis
    for a later comparison tool (`providers.comparison_frame` aligns two providers by
    bar time and keeps both identities).
- `validate_payload` refuses a streaming Live payload whose dataset key, provider,
  symbol, source label, title or identity disagree, or which carries backtest markers.
- Indicators (EMA, SMA, VWAP with its daily UTC reset, Bollinger Bands, RSI, MACD,
  ATR, volume) are calculated in Python on the active provider's bars, including the
  forming candle. Binance volume is base-asset volume; Exness volume is tick volume.
- While streaming, the watchlist leads with one `kind: "live"` row per market × source.
  Each has `source` and `source_label` (BINANCE / EXNESS), and `live {status, bid, ask,
  digits}` only while that source has a current quote. Registry rows stay historical
  reference closes.

**States (both sources):** CONNECTING, LIVE, STALE, DISCONNECTED, ERROR.
- Binance:
  - CONNECTING while loading history or reconnecting.
  - STALE when the socket is open but silent for more than 5 s, or there has been no
    kline update for more than 60 s.
  - DISCONNECTED when the socket is closed, with the retry countdown shown.
  - ERROR when the contract is missing, is not TRADING, or has a different contract type.
- Exness:
  - DISCONNECTED when there is no file, or the heartbeat is more than 60 s old.
  - STALE when the heartbeat is 5–60 s old, or there has been no tick for more than 60 s.
  - CONNECTING when the terminal isn't connected, or there is no history yet.
  - ERROR for an invalid file, or a server clock that isn't UTC+0.

**Updates:** each poll is a normal rerun with the full window (`live.bar_count`,
`live.more_history`, `live.history_limit`).

## Source roles: Chart / Signals / Execution (read-only)

This follows the decision from the feed-comparison research (`research/feed_comparison/FINDINGS.md`).
`source_roles.py` keeps three roles separate:

| role | provider | authoritative | notes |
|---|---|---|---|
| Chart | Binance Futures (default) or Exness MT5, as the user chooses | never | context and monitoring only |
| Signals | always Exness MT5, derived from the market (Gold → XAUUSDm, BTC → BTCUSDm) | yes | never inferred from the chart source |
| Execution | Exness MT5 | yes | `enabled` is always `false` in this phase |

**`signal_authority_ready`** is true only when every check passes:
- the provider is Exness MT5 (Binance fails this check whatever its state)
- the symbol matches the market
- the MT5 feed is LIVE (the `live.py` health logic)
- the heartbeat and quote are fresh
- the timeframe has at least 200 bars
- bar times are aligned, increasing and current
- after any start, outage or feed restart, two consecutive fresh updates from one writer have been seen

Readiness drops on the first failing observation. A new file alone never restores it: the
tracker reports "revalidating" until the second fresh update arrives.

**Payload:** `sources` is present only while Live is streaming (`null` in Historical,
Replay and Live setup): `{chart, signal, execution, signal_authority_ready, checks,
readiness, note, log}`.
- Each role has `{role, provider, symbol, state, is_authoritative, last_update, reason,
  timeframe, feed_state, source}`.
- The signal state is `LIVE` or `UNAVAILABLE`; `feed_state` carries the MT5 health (STALE,
  DISCONNECTED, ERROR, …).
- `readiness` = `{enabled: false, broker_connected, signal_authority_ready, symbol_match,
  market_data_fresh, reason}`. The reason is "Live execution not enabled", or "Exness signal
  source unavailable" when authority is not ready.
- `note` is the chart/signal mismatch note when the chart is Binance.
- `log` holds the last 50 source-state events (in session only).

`validate_payload` refuses:
- a signal provider other than Exness MT5
- an authoritative chart role
- authority without a LIVE feed
- execution that is enabled or not DISABLED
- `sources` outside streaming Live, including Replay

The Strategy Tester doesn't read any of this.

## Pine scripts (language-driven engine, P1)

The engine lives in `ui/tradingview_mode/pine/`:

1. The **lexer** and **parser** read the whole v5/v6 language surface.
2. The **analyzer** resolves scopes, names, calls and types, and reports capability gaps.
3. A bar-by-bar **runtime** executes the script, keeping series history, per-call-site
   state and commit/rollback.
4. The **built-in registries** (`builtins/`) implement `ta.*`, `math.*`, `str.*`, `color.*`,
   `input.*`, time and chart info, and the plot family.

Nothing is implemented per indicator. Adding a Pine built-in means registering it; the
parser does not change. Coverage by feature is in `pine/COMPATIBILITY.md`, generated
from the code and checked by a test.

**Events** (the source may be up to 100,000 characters):
- `pine_compile {source}` only compiles; the result goes to the editor.
- `pine_add {source}` adds the script to the chart if it compiles without errors or gaps.
- `pine_update {id, source}` replaces a script's source and resets its inputs.
- `pine_remove {id}` and `pine_toggle {id, enabled}` remove or hide a script.
- `pine_set_input {id, index, value}` is validated against the input's type, `minval`/`maxval` and `options`.

A rejected event changes nothing and says why. A capability gap reads, for example,
"Line 3: `request.security_lower_tf()` is not implemented yet (data requests)."

**Execution:**
- Scripts run on exactly the bars the payload shows:
  - the historical window, capped at the last 10,000 bars (the payload says how many were not executed)
  - the revealed Replay bars, so there is no future data
  - the live provider's bars, whose last bar is forming (`barstate.isrealtime`)
- `pine_bridge.py` caches compiled programs by source hash and keeps one execution per script per session:
  - An unchanged chart executes nothing.
  - A Replay step or new bar executes one bar.
  - A changed live forming bar is rolled back and re-run once (`varip` keeps intrabar updates).
  - Any other change to the bars re-runs from bar 0.

**Payload** `pine` (null outside the terminal render):
`{scripts: [{id, title, shorttitle, overlay, enabled, source, source_hash, inputs:
[{index, kind, title, defval, value, options, minval, maxval, step, tooltip, group, line}],
outputs, error, runtime_ms, bars, executed, incremental, truncated_bars}], editor, examples,
compat, limits}`.

Each output has an `id` and a `kind`:

| kind | fields |
|---|---|
| `plot` | `title`, `style` (line / linebr / stepline / histogram / columns / area / circles / cross), `linewidth`, `offset`, `trackprice`, `histbase`, `data: [{time, value \| null, color \| null}]` |
| `shape` / `char` | `style` or `char`, `location`, `size`, `textcolor`, `data: [{time, color, text, price?}]` |
| `hline` | `price`, `color`, `linestyle`, `linewidth` |
| `fill` | `between: [id, id]` (two plots or two hlines of the same script), `data: [{time, color}]` |
| `bgcolor` / `barcolor` | `data: [{time, color}]` |

Colors are CSS `rgba()` strings, and a na color is `null`. `validate_payload` requires
every output time to be a chart bar time, so Replay cannot leak, and every fill to reference
its own script's plots or hlines.

**Rendering** (`chart/PineLayer.js`):
- **Panes:** overlay scripts draw on the price pane; every other script gets its own pane after the indicator panes.
- **Plots:** map to line, histogram or area series.
- **Primitives:** `fill` bands, `bgcolor` columns and Pine's shape glyphs are custom series primitives.
- **Other outputs:**
  - `hline` is a price line.
  - `barcolor` recolors the candles.
- **Updates:** data updates are incremental, as for the rest of the chart.


### request.security() (P2.1)

`request.security(symbol, timeframe, expression, gaps, lookahead)` runs `expression` in its **own requested
context**: a child runtime (`pine/security.py`) executes the call's security slice (the global statements the
expression depends on, `pine/slicing.py`) over the requested bars, with its own OHLCV, time, `bar_index`,
history, `var` state and `ta.*` state. Results are never resampled from the chart.

- **Mapping** (confirmed on real TradingView, q4: 134,400 / 134,400 cells): `lookahead_off` = latest requested
  bar closed by the chart bar's close; `lookahead_on` = requested bar containing the chart bar's open;
  `gaps_on` = value only where a new requested bar is selected.
- **Historical** reproduces TradingView's historical semantics, including `lookahead_on`'s final values
  (a future bias by design). **Replay and Live** are *knowable per bar*: completed requested bars only
  when closed by that chart bar; the forming requested bar is aggregated from revealed / received chart
  bars; never a final future bar.
- **Data** (`component/security_data.py`, locked policy): Exness native M15/M30/H1, else aggregated from the
  finest Exness dataset on the broker's recorded server-time boundaries; Exness W/M blocked. Binance
  native public klines, else aggregated from Binance data. Cross-family requests are refused (literal
  symbols before running, dynamic ones at run time).
- **Limits** (this engine's): 16 contexts per script, 32 per chart, 10,000 bars per context, nesting 2.

Payload, per script (additive): `contexts: [{provider_family, provider, symbol, timeframe, native,
aggregation_base, bar_count, max_source_time (epoch s), data_identity, fingerprint, depth, line, forming}]`,
and at section level `chart_family` and `mode`. The validator refuses more than 16 / 32 contexts, an unknown
family, a context from another family than the chart's, an invalid timeframe, and - in Replay - any context
whose `max_source_time` is after the cursor bar's close (computed from the payload's own bars).

## Chart view (all modes)

`chart/ChartEngine.js` compares each payload with what is drawn, using
`chart/chartView.js` (tested in Node):
- **Tail update:** when every candle but the last is identical and the last changed
  and/or one was appended, `series.update()` is called; this covers the forming
  candle and rollover.
- **Anything else** (a corrected completed candle, prepended history, a replay jump)
  uses `setData()`. The exact visible logical range is then restored, shifted by the
  number of prepended candles, so the same candles stay on screen at the same zoom.
- Indicator series are updated the same way and rebuilt only when the indicator
  itself changes. Lower panes are never rebuilt by a data update.
- `fitContent` is never called and price-scale options are never re-applied on
  a data update. Autoscale only sees the visible candles, so an off-screen tick
  cannot rescale the view.

**Follow latest:**
- While the newest candle is in view, updates move the view with it
  (`shiftVisibleRangeOnNewBar`).
- Panning back turns following off and shows **Go to latest**, which scrolls to the
  newest candle at the current zoom and follows again.
- A new `view_key` (market, source, timeframe or dataset) resets to the latest candles.

**Time:**
- The legend shows the hovered candle's open time as "YYYY-MM-DD HH:mm UTC" and its
  OHLC and volume, looked up in Python's bars by time. It keeps showing the hovered
  candle across live updates and shows the newest candle when the pointer leaves.
- The crosshair axis label is the same UTC string.
- Axis ticks are UTC: HH:mm intraday, "Sep 25" at a day change, and month/year beyond.

## Reserved for later phases

`capabilities` and the drawing toolbar and the disabled
Replay/Live mode buttons are placeholders. When those features arrive,
Python supplies the results through new payload fields (bump `contract`) and
the frontend only renders them.

## Historical data freshness and Refresh data

- `data_status` (Historical, Replay and Live setup; `null` while streaming) describes the chart's source dataset:
  `{dataset_key, label, last_local, latest_available, status, refreshable, source, source_captured, problems,
  workspace_extended}`. Times are UTC `YYYY-MM-DD HH:MM`.
- `status`:
  - `STALE`: a known local source (MT5 history export or Live feed seed in Common/Files) has newer closed bars.
  - `CURRENT`: no known source is newer; `source_captured` says how recent that knowledge is.
  - `UNKNOWN`: no readable source. An old snapshot is never shown as current.
- `refresh_data {}` (Historical only): Python appends every newer closed bar from those sources to the WORKSPACE
  history of each refreshable dataset of the chart's symbol (e.g. XAUUSDm M15 and H1 together), under
  `data/workspace/` (`workspace_data.py`).
  - The registered research datasets are never written.
  - The chart, the date range, Pine scripts and Exness `request.security()` read frozen file + extension on the next
    rerun.
  - The audited Strategy Tester keeps the frozen, validated dataset.
- Closed-bar policy: a bar is stored only if `open + step <=` its source's capture time. The forming bar is never
  stored.
- Automatic refresh (Historical only): on the first render and whenever a symbol or timeframe is selected, then at most
  every 180 s per symbol, Python runs the same closed-bar append (`terminal.auto_refresh_workspace`).
  - A failure writes nothing and is logged as a warning; the status stays `STALE` with `problems` listing the error.
  - `data_status.auto_refresh = {checked, errors}`. The freshness status itself is cached for the same interval, so
    normal reruns do not read the MT5 folder.

## Pine strategies in the custom workspace

- Historical calculation range:
  - Pine scripts calculate on every available bar from the dataset's first bar to the chart's last bar (at most
    `MAX_PINE_BARS` = 20,000, TradingView Premium's bar limit). The chart may render fewer:
    `pine.scripts[i].display_from` is the first rendered bar's time and `calc_bars` the number of calculated bars.
  - Plots, shapes and colors are sent for the rendered bars only. Drawings keep their Pine coordinates, with a
    `first_bar_index` that may be negative (left of the chart).
  - The strategy report covers the whole calculation range. The protocol accepts report events before `display_from`
    in Historical mode only, and never after the last rendered bar. Replay and Live calculate on exactly the rendered
    bars, as before.
- Lazy navigation: a Strategy Tester trade on bars that are not loaded moves the date range's start back and keeps its
  end. The calculation range, and so every trade, is unchanged.
- Strategy report additions:
  - Trades: `bars_held` (exit bar − entry bar) and `profit_percent` (net P&L / entry price × quantity). Both are engine
    conventions, not TradingView-verified.
  - Metrics: `avg_bars_in_trade`.
  - Report: `fill_count`, `fills_reported` and `calc_range {bars, first_time, last_time}`.
- Chart markers: the source of truth is the Pine strategy's fills.
  - Every fill on a loaded bar is exactly one compact marker: an arrow, plus a short tag on exits (TP / SL / TS / X /
    R / MC). Fills on unloaded bars are counted, not drawn.
  - The full comment, price and trade P&L appear in the hover tooltip.
  - `__tvChart.debugState().strategyAudit` reports `{fills, entries, exits, inside, outside, rendered}`.
- `pine_add {source, another?, keep_editor?}`:
  - An identical script (same compiled source, default inputs) already on the chart is not added again. The editor
    result carries `duplicate_of` unless `another` is true.
  - After a successful add, the dock opens the Strategy Tester for a strategy, or collapses for an indicator, unless
    `keep_editor`.
- Bottom panels: `indicators`, `strategy_tester`, `trades`, `logs`, `pine`. The separate `pine_strategy` panel is gone:
  the Strategy Tester shows one source at a time, **Pine · TradingView Emulator** or **Python Audited Engine**, never
  combined. The audited engine keeps the frozen, validated datasets.

## Strategy test range and trade-list export (Pine strategies, Historical)

- `pine_set_range {id, start, end}`: UTC `YYYY-MM-DDTHH:MM`, both inclusive on bar OPEN time; both `null` = full
  available history. The strategy is evaluated on exactly those bars - it starts fresh at `start` (indicators warm up
  inside the range) and a trade still open at `end` stays open. This changes the evaluation; it is not a filter of a
  longer run. The chart's visible window is independent: zooming or changing the chart range never changes the test.
- A strategy added while the chart has an explicit date range starts with the custom range dataset start → chart
  range end (shown in the tester header, editable). A range with no bars on a new symbol/timeframe is reset to the
  full history with a notice; otherwise it is kept.
- Each strategy script carries `test_range {mode: full|custom, start, end, first_time, last_time, bars}`.
- `pine_export {id}`: Python builds the CURRENT result's trade list as CSV (component/tester_export.py) and sends it
  once as `pine.export {id, filename, mime, content}`; filename
  `<Strategy>_<SYMBOL>_<TF>_<first day>_<last day>_trades.csv`, raw values (full-precision numbers, UTC ISO time and
  epoch seconds), UTF-8.
