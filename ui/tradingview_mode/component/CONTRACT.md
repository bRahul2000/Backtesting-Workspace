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

## Strategy Tester (Phase 1)

Pipeline: `run_backtest` event → `tester.validate_run_request` → `core.config.BacktestConfig`
→ `core.adapters.audited_engine.run_universal_backtest` → `UniversalBacktestResult`
→ `tester.build_run_payload`, which only reshapes the result for display. There is no
second engine, and results are not cached.

**`run_backtest`** takes `{strategy_id, dataset_key, broker_profile, dataset_role, start, end, parameters?, settings?}`.
- **Strategy:** must come from `discover_builtin_strategies()`.
- **Dataset:** must be registered and exist. Its instrument must be in the strategy's
  `supported_instruments` and its timeframe in `supported_timeframes`. A backtest
  timeframe is never derived from the chart timeframe.
- **Broker profile:** only profiles the audited adapter accepts (`EXNESS_STANDARD`).
- **Parameters:** typed per `StrategyParameter` and checked with `validate()` and
  `descriptor.create()`. Frozen parameters can't change, and only values that
  differ from the defaults are passed as overrides.
- **Settings:** limited to the `BacktestConfig` fields the adapter reads:
  `initial_capital, risk_mode, risk_per_trade_percent, fixed_risk_dollars, risk_reward_ratio, spread,
  spread_multiplier, commission_percent, slippage_percent, leverage`. `risk_mode` takes the `RiskMode` names.
- **Spread:** a dataset with a per-bar broker spread rejects a typed spread.
- **Range:** `end` includes the last bar of that UTC date. Dates outside the
  dataset are rejected, not clipped.

`clear_backtest` clears the displayed result.

**Exactly once.** A run executes synchronously inside the rerun that consumes its
event id. The id is persisted after the run finishes, so an interrupted run is
retried, never dropped, and later reruns never execute it again. Each run is
recorded in the experiment ledger, as the Universal Workspace does.
`TV_TESTER_LEDGER` redirects the ledger, for example for manual UI checks.

**Payload `tester`:** `{status: idle|completed|failed, error, form, options, run}`.
The frontend shows "Running backtest…" while its `run_backtest` event is unacknowledged.
`run` contains:
- `run_id` and `fingerprints`
- `strategy`, `dataset` and the exact executed `config`
- `summary`, which uses the result's values. `winning_trades`, `losing_trades` and
  `pnl_percent` are counted or derived in Python and listed in `derived_in_python`.
- `directional`, `periods`
- `trades`: every trade from `trade_log`. Prices and P&L are copied unchanged,
  times are epoch seconds UTC, and `exit_label` (TP/SL/Exit) comes from the
  engine's exit reason text.
- `curves`: equity and drawdown from `equity_curve`. Downsampling above 4,000
  points affects drawing only.
- `open_positions`, `diagnostics`, `price_precision`

Infinite values are sent as `"inf"`/`"-inf"`.

**Payload `trade_overlay`:** `{available, reason, trades: [{trade_id, entry_bar, exit_bar}]}`.
- Markers are only drawn when the chart shows the same instrument, provider and
  symbol as the tested dataset.
- Each exact time maps to the chart bar that contains it. Only trades that lie
  entirely inside the loaded bars are included.

Selecting a trade is client-side. The chart centers on it and draws Entry, SL
and TP as limited segments from the entry bar to the exit bar. When the trade is
outside the loaded bars, the frontend sends only a `set_date_range` around it;
it never reruns the backtest.

## Reserved for later phases

`capabilities`, the drawing toolbar and the disabled
Replay/Live mode buttons are placeholders. When those features arrive,
Python supplies the results through new payload fields (bump `contract`) and
the frontend only renders them.
