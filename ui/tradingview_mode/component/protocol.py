"""Validated Python <-> frontend contract for the custom TradingView Mode terminal.

Python is authoritative. The frontend receives a JSON-compatible payload that
it only renders, and sends back small explicit events that Python validates
before anything changes. See ``CONTRACT.md`` beside this file.

Canonical time: every chart time is an integer Unix epoch in seconds, UTC.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import math
from typing import Any

import numpy as np
import pandas as pd

from .replay import SPEEDS as REPLAY_SPEEDS, is_utc_text


CONTRACT_VERSION = 1
MODES = ("historical", "replay", "live")
BOTTOM_PANELS = ("indicators", "strategy_tester", "trades", "logs", "pine")
_BAR_FIELDS = ("time", "open", "high", "low", "close", "volume")
_REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


class PayloadValidationError(ValueError):
    """The payload Python is about to send violates the contract."""


class EventValidationError(ValueError):
    """A frontend event is malformed or not part of the contract."""


# ---------------------------------------------------------------------------
# Bars and series
# ---------------------------------------------------------------------------

def epoch_seconds(timestamps: pd.Series) -> np.ndarray:
    """Convert a UTC timestamp column to integer epoch seconds.

    Naive or non-UTC timestamps are rejected rather than reinterpreted.
    """
    if not pd.api.types.is_datetime64_any_dtype(timestamps):
        raise ValueError("Chart timestamps must be datetimes.")
    if timestamps.dt.tz is None or str(timestamps.dt.tz) != "UTC":
        raise ValueError("Chart timestamps must be UTC.")
    utc = timestamps.dt.tz_convert("UTC").dt.tz_localize(None)
    return utc.to_numpy(dtype="datetime64[s]").astype(np.int64)


def bars_from_frame(data: pd.DataFrame) -> list[dict[str, float | int]]:
    """Convert an exact UTC OHLCV dataframe to epoch-second bar records."""
    missing = [column for column in _REQUIRED_COLUMNS if column not in data.columns]
    if missing:
        raise ValueError(f"Missing chart column(s): {', '.join(missing)}")
    timestamps = data["timestamp"]
    times = epoch_seconds(timestamps)
    if timestamps.duplicated().any():
        raise ValueError("Chart timestamps must not contain duplicates.")
    if len(times) > 1 and not bool(np.all(np.diff(times) > 0)):
        raise ValueError("Chart timestamps must be chronological.")
    values = {}
    for column in ("open", "high", "low", "close", "volume"):
        array = data[column].to_numpy(dtype=float)
        if not np.all(np.isfinite(array)):
            raise ValueError(f"{column} must be finite.")
        values[column] = array.tolist()
    time_list = times.tolist()
    return [
        {"time": int(time_list[i]), "open": values["open"][i], "high": values["high"][i],
         "low": values["low"][i], "close": values["close"][i], "volume": values["volume"][i]}
        for i in range(len(time_list))
    ]


def series_points(times: list[int], values: pd.Series) -> list[dict[str, float | int]]:
    """Pair indicator values with bar times, omitting warm-up NaNs."""
    array = values.to_numpy(dtype=float)
    if len(array) != len(times):
        raise ValueError("Indicator series length does not match bars.")
    if np.isinf(array).any():
        raise ValueError("Indicator values must be finite.")
    return [{"time": int(times[i]), "value": float(array[i])}
            for i in range(len(times)) if not math.isnan(array[i])]


def price_precision(values: pd.Series | list[float], *, minimum: int = 2, maximum: int = 6) -> int:
    """Smallest decimal count that represents recent prices exactly (display only)."""
    array = np.asarray(values, dtype=float)[-500:]
    array = array[np.isfinite(array)]
    for digits in range(minimum, maximum + 1):
        scaled = array * 10 ** digits
        # Tolerance covers float representation error only (~1e-16 relative).
        if np.all(np.abs(scaled - np.round(scaled)) < np.maximum(1e-6, np.abs(scaled) * 1e-10)):
            return digits
    return maximum


def bars_revision(bars: list[dict[str, Any]], *identity: object) -> str:
    """Stable fingerprint so the frontend can skip unchanged data."""
    digest = hashlib.sha1(repr(identity).encode())
    if bars:
        digest.update(np.array([[bar[f] for f in _BAR_FIELDS] for bar in bars], dtype=float).tobytes())
    return digest.hexdigest()[:16]


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PayloadValidationError(message)


def _validate_points(points: Any, where: str, bar_times: set[int]) -> None:
    _require(isinstance(points, list), f"{where}.data must be a list.")
    previous = None
    for point in points:
        _require(isinstance(point, dict) and set(point) == {"time", "value"}, f"{where}: bad point {point!r}.")
        _require(type(point["time"]) is int and point["time"] in bar_times, f"{where}: time {point['time']!r} is not a bar time.")
        _require(isinstance(point["value"], float) and math.isfinite(point["value"]), f"{where}: value must be a finite float.")
        _require(previous is None or point["time"] > previous, f"{where}: times must increase.")
        previous = point["time"]


def _validate_series_list(series_list: Any, where: str, bar_times: set[int]) -> None:
    _require(isinstance(series_list, list) and series_list, f"{where}.series must be a non-empty list.")
    for index, series in enumerate(series_list):
        label = f"{where}.series[{index}]"
        _require(isinstance(series, dict), f"{label} must be an object.")
        _require(series.get("type") in ("line", "histogram"), f"{label}.type must be line or histogram.")
        _require(isinstance(series.get("name"), str) and series["name"], f"{label}.name is required.")
        _require(isinstance(series.get("color"), str), f"{label}.color is required.")
        _validate_points(series.get("data"), label, bar_times)


def validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a complete payload before it is sent. Returns it unchanged."""
    _require(isinstance(payload, dict), "Payload must be an object.")
    _require(payload.get("contract") == CONTRACT_VERSION, "Unsupported contract version.")
    _require(payload.get("mode") in MODES, f"Unsupported mode {payload.get('mode')!r}.")
    for key in ("symbol", "provider", "dataset_key", "timeframe", "bars_rev"):
        _require(isinstance(payload.get(key), str) and payload[key], f"{key} is required.")
    timeframes = payload.get("timeframes")
    _require(isinstance(timeframes, list) and payload["timeframe"] in timeframes,
             "timeframe must be one of the Python-resolved timeframes.")

    source = payload.get("source")
    _require(isinstance(source, dict), "source is required.")
    _require(source.get("provider") == payload["provider"], "source provider must match payload provider.")
    _require(source.get("symbol") == payload["symbol"], "source symbol must match payload symbol.")
    _require(isinstance(source.get("native"), bool), "source.native must be a boolean.")
    _require(isinstance(source.get("dataset_key"), str), "source.dataset_key is required.")

    bars = payload.get("bars")
    _require(isinstance(bars, list), "bars must be a list.")
    previous = None
    for bar in bars:
        _require(isinstance(bar, dict) and tuple(bar) == _BAR_FIELDS, f"Bad bar fields: {bar!r}.")
        _require(type(bar["time"]) is int, "bar.time must be integer epoch seconds.")
        _require(previous is None or bar["time"] > previous, "bars must be strictly increasing.")
        previous = bar["time"]
        for field in _BAR_FIELDS[1:]:
            _require(isinstance(bar[field], float) and math.isfinite(bar[field]), f"bar.{field} must be a finite float.")
    bar_times = {bar["time"] for bar in bars}

    ids = set()
    for group in ("overlays", "panes"):
        items = payload.get(group)
        _require(isinstance(items, list), f"{group} must be a list.")
        for item in items:
            _require(isinstance(item, dict) and isinstance(item.get("id"), str), f"{group} item needs an id.")
            _require(item["id"] not in ids, f"Duplicate indicator id {item['id']!r}.")
            ids.add(item["id"])
            _validate_series_list(item.get("series"), f"{group}[{item['id']}]", bar_times)

    watchlist = payload.get("watchlist")
    _require(isinstance(watchlist, list), "watchlist must be a list.")
    for item in watchlist:
        _require(isinstance(item, dict) and isinstance(item.get("dataset_key"), str), "watchlist item needs dataset_key.")
    _require(payload.get("ui", {}).get("bottom_panel") in BOTTOM_PANELS, "ui.bottom_panel is invalid.")
    _require(type(payload.get("price_precision")) is int, "price_precision must be an integer.")
    _validate_replay(payload, bar_times)
    _validate_live(payload)
    _validate_sources(payload)
    _validate_pine(payload, bar_times)
    _validate_tester(payload.get("tester"), payload.get("trade_overlay"), bar_times)
    _require(payload.get("ack") is None or isinstance(payload["ack"], str), "ack must be an event id or null.")
    return payload


LIVE_SOURCES = {"binance": ("Binance Futures", "BINANCE_LIVE:"), "exness": ("Exness MT5", "MT5_LIVE:")}
LIVE_STATUSES = ("CONNECTING", "LIVE", "STALE", "DISCONNECTED", "ERROR")


PINE_OUTPUT_KINDS = ("plot", "shape", "char", "hline", "fill", "bgcolor", "barcolor")


def _validate_pine(payload: dict[str, Any], bar_times: set[int]) -> None:
    """Pine outputs only ever sit on bars the chart has (so Replay cannot leak)."""
    pine = payload.get("pine")
    if pine is None:
        return
    _require(isinstance(pine, dict) and isinstance(pine.get("scripts"), list), "pine.scripts is required.")
    script_ids = set()
    for script in pine["scripts"]:
        _require(isinstance(script.get("id"), str) and script["id"] not in script_ids, "pine script ids must be unique.")
        script_ids.add(script["id"])
        outputs = script.get("outputs") or []
        kinds = {}
        for output in outputs:
            _require(output.get("kind") in PINE_OUTPUT_KINDS, f"unknown pine output kind {output.get('kind')!r}.")
            _require(isinstance(output.get("id"), str) and output["id"] not in kinds, "pine output ids must be unique.")
            kinds[output["id"]] = output["kind"]
            previous = None
            for point in output.get("data", []):
                _require(type(point.get("time")) is int and point["time"] in bar_times,
                         f"pine output {output['id']}: time {point.get('time')!r} is not a chart bar.")
                if output["kind"] == "plot":
                    _require(previous is None or point["time"] > previous, f"pine output {output['id']}: times must increase.")
                    value = point.get("value")
                    _require(value is None or (isinstance(value, float) and math.isfinite(value)),
                             f"pine output {output['id']}: values must be finite or null.")
                previous = point["time"]
        for output in outputs:
            if output["kind"] == "fill":
                between = output.get("between") or []
                _require(len(between) == 2 and all(ref in kinds for ref in between)
                         and kinds[between[0]] == kinds[between[1]] and kinds[between[0]] in ("plot", "hline"),
                         "a pine fill must reference two plots or two hlines of the same script.")


def _validate_sources(payload: dict[str, Any]) -> None:
    """Hard guards for the Chart / Signal / Execution roles (see source_roles.py)."""
    sources = payload.get("sources")
    live = payload.get("live") or {}
    if sources is None:
        return
    _require(payload["mode"] == "live" and live.get("phase") == "streaming" and not (payload.get("replay") or {}).get("enabled"),
             "source roles are shown for a streaming Live chart only (never in Replay or Historical).")
    signal, chart, execution = sources.get("signal") or {}, sources.get("chart") or {}, sources.get("execution") or {}
    _require(signal.get("provider") == "Exness MT5" and signal.get("source") == "exness" and signal.get("is_authoritative") is True,
             "the signal source must be Exness MT5; Binance can never be authoritative for Exness triggers.")
    _require(chart.get("is_authoritative") is False, "the chart source is never authoritative.")
    _require(chart.get("source") == live.get("source"), "the chart role must describe the chart being drawn.")
    ready = sources.get("signal_authority_ready")
    _require(isinstance(ready, bool), "signal_authority_ready must be a boolean.")
    _require(not ready or (signal.get("state") == "LIVE" and signal.get("feed_state") == "LIVE"),
             "signal authority requires a LIVE Exness signal feed.")
    _require((sources.get("readiness") or {}).get("enabled") is False and execution.get("state") == "DISABLED",
             "execution must stay disabled in this phase.")


def _validate_live(payload: dict[str, Any]) -> None:
    """A streaming Live payload is exactly one provider's data, labelled as such."""
    live = payload.get("live")
    _require(isinstance(live, dict) and isinstance(live.get("enabled"), bool), "live status is required.")
    for item in payload["watchlist"]:
        quote = item.get("live")
        if quote is not None:
            _require(item.get("source") in LIVE_SOURCES and isinstance(item.get("source_label"), str),
                     "a live watchlist value must name its source.")
    if not live["enabled"]:
        _require(payload["mode"] != "live", "live mode needs live status.")
        return
    _require(payload["mode"] == "live", "live status outside Live mode.")
    _require(live.get("phase") in ("setup", "streaming"), "live.phase must be setup or streaming.")
    if live["phase"] == "setup":
        return
    _require(live.get("status") in LIVE_STATUSES, f"live.status {live.get('status')!r} is invalid.")
    _require(live.get("source") in LIVE_SOURCES, f"live.source {live.get('source')!r} is invalid.")
    label, prefix = LIVE_SOURCES[live["source"]]
    identity = live.get("identity")
    _require(isinstance(identity, dict) and identity.get("source") == live["source"], "live identity must match its source.")
    _require(live.get("source_label") == label and identity.get("source_label") == label, "live source label mismatch.")
    _require(payload["dataset_key"] == identity.get("dataset_key") == payload["source"]["dataset_key"]
             and payload["dataset_key"].startswith(prefix), "live bars must come from the labelled provider only.")
    _require(payload["symbol"] == identity.get("symbol") == live.get("symbol"), "live symbol mismatch.")
    _require(payload["provider"] == identity.get("provider") == live.get("provider"), "live provider mismatch.")
    _require(isinstance(live.get("title"), str) and label in live["title"], "live title must name the source.")
    _require(not (payload.get("trade_overlay") or {}).get("trades"), "backtest markers are not shown on live data.")


def _validate_replay(payload: dict[str, Any], bar_times: set[int]) -> None:
    """In replay, nothing after the cursor bar may be serialized."""
    replay = payload.get("replay")
    _require(isinstance(replay, dict) and isinstance(replay.get("enabled"), bool), "replay status is required.")
    if not replay["enabled"]:
        return
    cursor = replay["cursor_timestamp"]
    _require(type(cursor) is int, "replay.cursor_timestamp must be epoch seconds.")
    _require(bool(bar_times) and max(bar_times) == cursor, "replay bars must end exactly at the cursor bar.")
    for group in ("overlays", "panes"):
        for item in payload[group]:
            for series in item["series"]:
                _require(all(point["time"] <= cursor for point in series["data"]),
                         f"{group}[{item['id']}] has values after the replay cursor.")
    for item in payload.get("trade_overlay", {}).get("trades", []):
        _require(item["exit_bar"] <= cursor and item["entry_bar"] <= cursor, "trade marker after the replay cursor.")
    tester_payload = payload.get("tester") or {}
    if tester_payload.get("run") is not None:
        _require("replay_view" in tester_payload["run"], "replay must send the replay view of a backtest, not the full run.")
    for row in tester_payload.get("history", []):
        _require(not {"pnl", "win_rate", "total_trades"} & set(row), "run history exposes outcomes during replay.")
    _require(not tester_payload.get("export"), "exports are not delivered during replay.")


_TRADE_TIMES = ("entry_time", "exit_time")
_OUTCOME_FIELDS = ("exit_time", "exit_price", "exit_reason", "exit_label", "pnl", "pnl_percent", "r_multiple",
                   "bars_held", "exit_commission")
_RUN_AGGREGATES = ("summary", "curves", "periods", "directional", "python_derived", "derived_in_python",
                   "diagnostics", "open_positions")
_TRADE_NUMBERS = ("entry_price", "stop_loss", "take_profit", "exit_price", "pnl", "r_multiple")


def _validate_tester(tester: Any, overlay: Any, bar_times: set[int]) -> None:
    _require(isinstance(tester, dict), "tester is required.")
    _require(tester.get("status") in TESTER_STATUSES, f"tester.status {tester.get('status')!r} is invalid.")
    _require(isinstance(tester.get("options"), dict), "tester.options is required.")
    run = tester.get("run")
    keys: set = set()
    if run is not None:
        previous_key = -1
        for trade in run["trades"]:
            label = f"trade {trade.get('segment')}/{trade['trade_id']}"
            _require(type(trade["key"]) is int and trade["key"] > previous_key, f"{label}: keys must be unique trade_log positions in order.")
            previous_key = trade["key"]
            _require(trade["direction"] in ("LONG", "SHORT"), f"{label}: bad direction.")
            _require(type(trade["entry_time"]) is int, f"{label}: entry_time must be epoch seconds.")
            keys.add(trade["key"])
            if trade.get("status") == "open":
                # Replay: an open trade carries no outcome at all.
                _require(not set(trade) & set(_OUTCOME_FIELDS), f"{label}: open trade exposes an outcome.")
                continue
            for name in _TRADE_TIMES:
                _require(type(trade[name]) is int, f"{label}: {name} must be epoch seconds.")
            _require(trade["exit_time"] >= trade["entry_time"], f"{label}: exit precedes entry.")
            for name in _TRADE_NUMBERS:
                value = trade[name]
                _require(isinstance(value, (int, float)) and math.isfinite(value), f"{label}: {name} must be finite.")
        if "replay_view" in run:
            cutoff = run["replay_view"]["knowable_until"]
            _require(not set(run) & set(_RUN_AGGREGATES), "replay view exposes full-run statistics.")
            for trade in run["trades"]:
                _require(trade["entry_time"] < cutoff, "replay view lists a trade entered after the cursor.")
                _require(trade.get("status") == "open" or trade["exit_time"] < cutoff,
                         "replay view shows an outcome after the cursor.")
        else:
            for name in ("equity", "drawdown"):
                times = [point["time"] for point in run["curves"][name]]
                _require(all(type(t) is int for t in times) and times == sorted(set(times)),
                         f"{name} curve times must be strictly increasing epoch seconds.")
    _require(isinstance(tester.get("history", []), list), "tester.history must be a list.")
    _require(isinstance(overlay, dict) and isinstance(overlay.get("trades"), list), "trade_overlay is required.")
    for item in overlay["trades"]:
        _require(item["key"] in keys, f"trade_overlay references unknown trade key {item['key']!r}.")
        _require(item["entry_bar"] in bar_times and item["exit_bar"] in bar_times, "trade_overlay bars must be chart bars.")


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def _is_str(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 128


def _is_source(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 100_000


def _is_input_value(value: Any) -> bool:
    return isinstance(value, (bool, str)) and len(str(value)) <= 1000 or (
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value))


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return len(value) == 10


def _is_params(value: Any) -> bool:
    return isinstance(value, dict) and len(value) <= 8 and all(
        _is_str(k) and isinstance(v, (int, float)) and not isinstance(v, bool) for k, v in value.items())


EXPORT_KINDS = ("trades_csv", "summary_json")
_is_utc_text = is_utc_text


def _is_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _is_scalar_map(value: Any, limit: int) -> bool:
    return isinstance(value, dict) and len(value) <= limit and all(
        _is_str(k) and (isinstance(v, (bool, str)) or (isinstance(v, (int, float)) and math.isfinite(v)))
        for k, v in value.items())


# field -> (required, validator). Unknown fields are rejected.
EVENT_SCHEMAS: dict[str, dict[str, tuple[bool, Any]]] = {
    "chart_ready": {},
    "frontend_error": {"message": (True, lambda v: isinstance(v, str))},
    "select_dataset": {"dataset_key": (True, _is_str)},
    "select_watchlist_item": {"dataset_key": (True, _is_str)},
    "select_timeframe": {"timeframe": (True, _is_str)},
    "set_date_range": {"start": (True, lambda v: v is None or _is_iso_date(v)),
                       "end": (True, lambda v: v is None or _is_iso_date(v))},
    "add_indicator": {"key": (True, _is_str), "params": (False, _is_params)},
    "update_indicator": {"id": (True, _is_str), "params": (True, _is_params)},
    "toggle_indicator": {"id": (True, _is_str), "enabled": (True, lambda v: isinstance(v, bool))},
    "remove_indicator": {"id": (True, _is_str)},
    "set_bottom_panel": {"panel": (True, lambda v: v in BOTTOM_PANELS),
                         "open": (False, lambda v: isinstance(v, bool))},
    "set_chart_setting": {"show_volume": (True, lambda v: isinstance(v, bool))},
    # Replay. Times are UTC 'YYYY-MM-DDTHH:MM'; bar semantics live in replay.py.
    "enter_replay": {"start": (True, _is_utc_text)},
    "set_replay_start": {"start": (True, _is_utc_text)},
    "jump_replay": {"to": (True, _is_utc_text)},
    "step_forward": {},
    "step_backward": {},
    "play_replay": {},
    "pause_replay": {},
    "set_replay_speed": {"speed": (True, lambda v: type(v) is int and v in REPLAY_SPEEDS)},
    "exit_replay": {},
    "go_to_replay_latest": {},
    # Live (read-only market data: Binance Futures or Exness MT5). Market/source/
    # timeframe semantics are validated in state.py.
    "enter_live": {},  # Live mode setup; no feed is read yet
    "go_live": {"market": (True, _is_str), "source": (True, _is_str), "timeframe": (True, _is_str)},
    "exit_live": {},
    "live_poll": {},
    "load_live_history": {},  # older candles for the streaming provider (Binance: REST pages)
    # Pine editor. Compilation and semantics live in the Pine engine (ui/tradingview_mode/pine).
    "pine_compile": {"source": (True, _is_source)},
    "pine_add": {"source": (True, _is_source)},
    "pine_update": {"id": (True, _is_str), "source": (True, _is_source)},
    "pine_remove": {"id": (True, _is_str)},
    "pine_toggle": {"id": (True, _is_str), "enabled": (True, lambda v: isinstance(v, bool))},
    "pine_set_input": {"id": (True, _is_str), "index": (True, lambda v: type(v) is int and 0 <= v < 500),
                       "value": (True, _is_input_value)},
    # Strategy Tester. Semantics (registry, dataset, broker, parameters) are
    # validated in tester.py against the authoritative configuration model.
    "run_backtest": {"strategy_id": (True, _is_str), "dataset_key": (True, _is_str),
                     "broker_profile": (True, _is_str), "dataset_role": (True, _is_str),
                     "start": (True, _is_iso_date), "end": (True, _is_iso_date),
                     "ledger_mode": (True, _is_str),
                     "parameters": (False, lambda v: _is_scalar_map(v, 64)),
                     "settings": (False, lambda v: _is_scalar_map(v, 16))},
    "clear_backtest": {},
    # Session run history: restore an already-returned result (never re-executes).
    "restore_run": {"history_id": (True, _is_int)},
    # Python-generated authoritative export of a session run.
    "export_run": {"history_id": (True, _is_int), "kind": (True, lambda v: v in EXPORT_KINDS)},
}
TESTER_EVENTS = ("run_backtest", "clear_backtest", "restore_run", "export_run")
PINE_EVENTS = ("pine_compile", "pine_add", "pine_update", "pine_remove", "pine_toggle", "pine_set_input")
TESTER_STATUSES = ("idle", "completed", "failed")


@dataclass(frozen=True)
class FrontendEvent:
    id: str
    type: str
    data: dict[str, Any]


def parse_event(raw: Any) -> FrontendEvent:
    """Structurally validate one frontend event. Semantic checks live in state.py."""
    if not isinstance(raw, dict):
        raise EventValidationError("Event must be an object.")
    unexpected = set(raw) - {"id", "type", "data"}
    if unexpected:
        raise EventValidationError(f"Unexpected event field(s): {', '.join(sorted(unexpected))}")
    event_id, event_type, data = raw.get("id"), raw.get("type"), raw.get("data", {})
    if not _is_str(event_id):
        raise EventValidationError("Event id is required.")
    if event_type not in EVENT_SCHEMAS:
        raise EventValidationError(f"Unknown event type {event_type!r}.")
    if not isinstance(data, dict):
        raise EventValidationError("Event data must be an object.")
    schema = EVENT_SCHEMAS[event_type]
    unknown = set(data) - set(schema)
    if unknown:
        raise EventValidationError(f"{event_type}: unexpected field(s) {', '.join(sorted(unknown))}.")
    for field, (required, check) in schema.items():
        if field not in data:
            if required:
                raise EventValidationError(f"{event_type}: missing field {field!r}.")
            continue
        if not check(data[field]):
            raise EventValidationError(f"{event_type}: invalid {field} {data[field]!r}.")
    return FrontendEvent(event_id, event_type, dict(data))
