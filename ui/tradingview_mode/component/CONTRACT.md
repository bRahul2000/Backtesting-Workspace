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

## Reserved for later phases

`capabilities`, the drawing toolbar and the disabled
Replay/Live mode buttons are placeholders. When those features arrive,
Python supplies the results through new payload fields (bump `contract`) and
the frontend only renders them.
