# TradingView Mode terminal contract (v1)

Python is authoritative. The React terminal renders the payload and sends
explicit events. It never calculates indicators, trade outcomes, stops,
targets or metrics, and never falls back to another provider or timeframe.

- Python side: `protocol.py` (payload + event schema), `state.py` (semantic
  validation, `apply_event`), `terminal.py` (Streamlit glue).
- Frontend side: `frontend/src/events.js`, `frontend/src/chart/ChartEngine.js`.

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
| `overlays` | Price-pane indicators: `[{id, key, name, params, series:[{name, type, color, data:[{time, value}]}]}]`. |
| `panes` | Lower-pane indicators with the same shape plus `levels` (e.g. RSI 70/50/30). |
| `indicators` | All active instances, including hidden ones: `{id, key, name, enabled, params, pane, color}`. |
| `indicator_catalog` | Addable indicators with their defaults. |
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
- A 500-bar REST seed; a REST bar is final once its close time passed on the server clock.
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

**Updates:** each poll is a normal rerun with the full window of about 500 bars. The
chart updates the forming candle in place, or appends at rollover, whenever the window
did not slide, and resets otherwise.

## Reserved for later phases

`capabilities` and the drawing toolbar and the disabled
Replay/Live mode buttons are placeholders. When those features arrive,
Python supplies the results through new payload fields (bump `contract`) and
the frontend only renders them.
