"""Streamlit glue for the custom React terminal.

Order of one rerun:
1. read the component's last event from session state (before rendering),
2. validate + apply it once (events carry unique ids),
3. resolve dataset/timeframe, load and filter data, calculate indicators,
4. build and validate the payload, render the component.

Python owns every value in the payload. The frontend only renders it.
"""
from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from services.market_datasets import MarketDataset, all_datasets, dataset
from strategies.registry import StrategyRegistry, discover_builtin_strategies
from utils.data_validation import load_ohlcv_csv
from ..indicators import INDICATORS, calculate_indicator
from ..timeframes import (
    TimeframeResolution,
    UnsupportedTimeframeError,
    available_timeframes,
    load_resolution_data,
    resolve_timeframe,
    timeframe_seconds,
)
from ..workspace import watchlist_groups
from . import render_terminal_component
from . import tester
from .protocol import (
    CONTRACT_VERSION,
    TESTER_EVENTS,
    EventValidationError,
    FrontendEvent,
    bars_from_frame,
    bars_revision,
    parse_event,
    price_precision,
    series_points,
    validate_payload,
)
from .state import (
    CHARTABLE_INDICATORS,
    MAX_BARS,
    IndicatorInstance,
    LogEntry,
    TerminalContext,
    TerminalState,
    apply_event,
    default_range_days,
)

COMPONENT_KEY = "tv_terminal_component"
STATE_KEY = "tv_terminal_state"
LOGS_KEY = "tv_terminal_logs"
LAST_EVENT_KEY = "tv_terminal_last_event_id"
READY_KEY = "tv_terminal_ready"
TESTER_KEY = "tv_terminal_tester"
TESTER_RESULT_KEY = "tv_terminal_tester_result"
MAX_LOGS = 200
_RSI_LEVELS = (70.0, 50.0, 30.0)
_SECONDARY_COLORS = {"signal": "#f5a623", "histogram": "#7d8799"}


# ---------------------------------------------------------------------------
# Cached loading (keyed by file mtime so edits on disk are picked up)
# ---------------------------------------------------------------------------

def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


@st.cache_data(show_spinner=False, max_entries=16)
def _resolved_frame(dataset_key: str, timeframe: str, _mtime_marker: float) -> pd.DataFrame:
    resolution = resolve_timeframe(dataset(dataset_key), timeframe)
    return load_resolution_data(resolution, load_ohlcv_csv)


@st.cache_data(show_spinner=False, max_entries=32)
def _last_closes(path_text: str, _mtime_marker: float) -> tuple[float | None, float | None, int]:
    closes = load_ohlcv_csv(Path(path_text))["close"]
    last = float(closes.iloc[-1]) if len(closes) else None
    previous = float(closes.iloc[-2]) if len(closes) > 1 else None
    return last, previous, price_precision(closes)


@st.cache_data(show_spinner=False, max_entries=32)
def _file_bounds(path_text: str, _mtime_marker: float) -> tuple[date, date] | None:
    stamps = load_ohlcv_csv(Path(path_text))["timestamp"]
    return (stamps.iloc[0].date(), stamps.iloc[-1].date()) if len(stamps) else None


def dataset_bounds(entry: MarketDataset) -> tuple[date, date] | None:
    return _file_bounds(str(entry.path), _mtime(entry.path)) if entry.exists else None


# ---------------------------------------------------------------------------
# Pure payload pieces
# ---------------------------------------------------------------------------

def context_for(bounds: tuple[date, date] | None = None) -> TerminalContext:
    keys = {entry.key for entry in all_datasets()}
    return TerminalContext(
        dataset_exists=lambda key: key in keys and dataset(key).exists,
        native_timeframe=lambda key: dataset(key).timeframe,
        available_timeframes=lambda key: available_timeframes(dataset(key)),
        timeframe_seconds=timeframe_seconds,
        data_bounds=bounds,
    )


def effective_range(state: TerminalState, bounds: tuple[date, date], tf_seconds: int
                    ) -> tuple[date, date, list[dict[str, str]]]:
    """Resolve the requested range against data bounds, reporting any clipping."""
    low, high = bounds
    if state.date_range is None:
        start = max(low, high - timedelta(days=default_range_days(tf_seconds) - 1))
        return start, high, []
    start, end = state.date_range
    notices = []
    if start < low or end > high:
        clipped = (max(start, low), min(end, high))
        if clipped[0] > clipped[1]:
            fallback = max(low, high - timedelta(days=default_range_days(tf_seconds) - 1))
            notices.append({"level": "warning", "message": f"Requested range {start}..{end} has no data "
                            f"({low}..{high} available); showing default window {fallback}..{high}."})
            return fallback, high, notices
        notices.append({"level": "warning", "message": f"Requested range {start}..{end} clipped to available data "
                        f"{clipped[0]}..{clipped[1]}."})
        start, end = clipped
    return start, end, notices


def filter_range(frame: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Inclusive UTC-date filter. Returns a new frame; ``frame`` is not mutated."""
    days = frame["timestamp"].dt.date
    return frame.loc[(days >= start) & (days <= end)].reset_index(drop=True)


def indicator_payload(frame: pd.DataFrame, times: list[int], instances: tuple[IndicatorInstance, ...]
                      ) -> tuple[list[dict], list[dict], list[dict[str, str]]]:
    """Calculate enabled indicators in Python and convert them to overlays/panes."""
    overlays, panes, notices = [], [], []
    for instance in instances:
        if not instance.enabled:
            continue
        definition = INDICATORS[instance.key]
        try:
            values = calculate_indicator(frame, instance.key, instance.params)
        except ValueError as exc:
            notices.append({"level": "error", "message": f"{instance.id}: {exc}"})
            continue
        series = []
        for name, column in values.items():
            points = series_points(times, column)
            if not points:
                continue
            series.append({
                "name": name,
                "type": "histogram" if name == "histogram" else "line",
                "color": _SECONDARY_COLORS.get(name, instance.color),
                "data": points,
            })
        if not series:
            notices.append({"level": "warning", "message": f"{instance.id}: not enough bars to calculate."})
            continue
        item = {"id": instance.id, "key": instance.key, "name": definition.display_name,
                "params": instance.params, "series": series}
        if definition.pane == "overlay":
            overlays.append(item)
        else:
            panes.append({**item, "levels": list(_RSI_LEVELS) if instance.key == "rsi" else []})
    return overlays, panes, notices


def watchlist_payload(selected: MarketDataset) -> list[dict]:
    items = []
    for group in watchlist_groups():
        available = [entry for entry in group if entry.exists]
        if not available:
            continue
        primary = available[0]
        last, previous, precision = _last_closes(str(primary.path), _mtime(primary.path))
        change = None if last is None or not previous else (last - previous) / previous * 100.0
        items.append({
            "dataset_key": primary.key, "symbol": primary.symbol, "provider": primary.broker,
            "instrument": primary.instrument, "native_timeframes": [entry.timeframe for entry in available],
            "last_close": last, "change_pct": change, "price_precision": precision,
            "selected": any(entry.key == selected.key for entry in group),
        })
    return items


def build_terminal_payload(*, state: TerminalState, selected: MarketDataset, resolution: TimeframeResolution,
                           frame: pd.DataFrame, bounds: tuple[date, date] | None, shown: tuple[date, date] | None,
                           logs: list[LogEntry], notices: list[dict[str, str]],
                           watchlist: list[dict], ack: str | None = None,
                           tester_payload: dict | None = None) -> dict:
    bars = bars_from_frame(frame)
    times = [bar["time"] for bar in bars]
    overlays, panes, indicator_notices = indicator_payload(frame, times, state.indicators)
    source = resolution.source
    payload = {
        "contract": CONTRACT_VERSION,
        "mode": "historical",
        "dataset_key": selected.key,
        "symbol": selected.symbol,
        "provider": selected.broker,
        "instrument": selected.instrument,
        "timeframe": resolution.target,
        "timeframes": list(available_timeframes(selected)),
        "view_key": f"{selected.instrument}|{selected.broker}|{selected.symbol}|{resolution.target}",
        "source": {
            "dataset_key": source.key, "label": source.label, "provider": source.broker, "symbol": source.symbol,
            "timeframe": source.timeframe, "native": resolution.native, "description": resolution.source_label,
            "read_only": source.read_only,
        },
        "range": {
            "start": shown[0].isoformat() if shown else None, "end": shown[1].isoformat() if shown else None,
            "min": bounds[0].isoformat() if bounds else None, "max": bounds[1].isoformat() if bounds else None,
            "is_default": state.date_range is None,
        },
        "bars": bars,
        "bars_rev": bars_revision(bars, selected.key, resolution.target),
        "price_precision": price_precision(frame["close"]) if len(frame) else 2,
        "overlays": overlays,
        "panes": panes,
        "indicators": [
            {"id": item.id, "key": item.key, "name": INDICATORS[item.key].display_name, "enabled": item.enabled,
             "params": item.params, "pane": INDICATORS[item.key].pane, "color": item.color}
            for item in state.indicators
        ],
        "indicator_catalog": [
            {"key": key, "name": INDICATORS[key].display_name, "category": INDICATORS[key].category,
             "pane": INDICATORS[key].pane, "defaults": INDICATORS[key].defaults}
            for key in CHARTABLE_INDICATORS
        ],
        "datasets": [
            {"dataset_key": entry.key, "label": entry.label, "symbol": entry.symbol, "provider": entry.broker,
             "timeframe": entry.timeframe, "available": entry.exists}
            for entry in all_datasets()
        ],
        "watchlist": watchlist,
        "ui": {"bottom_panel": state.bottom_panel, "bottom_open": state.bottom_open, "show_volume": state.show_volume},
        "logs": [asdict(entry) for entry in logs[-MAX_LOGS:]],
        "notices": notices + indicator_notices,
        # Declared so the frontend can show honest placeholders; Python will
        # own all of these results when they are built.
        "capabilities": {"drawings": False, "strategy_tester": True, "trades": True, "replay": False, "live": False},
        "max_bars": MAX_BARS,
        # Id of the last frontend event Python processed; the frontend serializes on it.
        "ack": ack,
    }
    tester_payload = tester_payload or {"status": "idle", "options": {}, "form": None, "run": None, "error": None}
    payload["tester"] = tester_payload
    payload["trade_overlay"] = tester.trade_overlay(
        tester_payload.get("run"), chart_identity=(selected.instrument, selected.broker, selected.symbol),
        bar_times=times, bar_seconds=resolution.target_seconds,
        chart_label=f"{selected.symbol} · {selected.broker} · {resolution.target}")
    return validate_payload(payload)


# ---------------------------------------------------------------------------
# Session state + event handling
# ---------------------------------------------------------------------------

def _initial_state() -> TerminalState:
    """Seed from the shared Plotly-path selection so switching renderers keeps context."""
    datasets = [entry for entry in all_datasets() if entry.exists] or list(all_datasets())
    key = st.session_state.get("tv_dataset_selection", datasets[0].key)
    if key not in {entry.key for entry in datasets}:
        key = datasets[0].key
    timeframe = st.session_state.get("tv_tf_selection", dataset(key).timeframe)
    if timeframe not in available_timeframes(dataset(key)):
        timeframe = dataset(key).timeframe
    return TerminalState(dataset_key=key, timeframe=timeframe)


def _log(entry: LogEntry) -> None:
    logs = st.session_state.setdefault(LOGS_KEY, [])
    logs.append(entry)
    del logs[:-MAX_LOGS]


def consume_event(state: TerminalState, raw, ctx: TerminalContext, last_id: str | None
                  ) -> tuple[TerminalState, LogEntry | None, str | None, FrontendEvent | None]:
    """Apply ``raw`` exactly once. Streamlit keeps a component's last value across
    reruns, so an event already processed (same id) is ignored.

    Strategy Tester events are returned (not applied) for ``handle_tester_event``.
    """
    if not raw:
        return state, None, last_id, None
    event_id = raw.get("id") if isinstance(raw, dict) else None
    if event_id is not None and event_id == last_id:
        return state, None, last_id, None
    try:
        event = parse_event(raw)
    except EventValidationError as exc:
        return state, LogEntry("error", f"Rejected malformed event: {exc}"), event_id, None
    if event.type in TESTER_EVENTS:
        return state, None, event.id, event
    new_state, entry = apply_event(state, event, ctx)
    return new_state, entry, event.id, None


def empty_tester_session() -> dict:
    return {"status": "idle", "error": None, "form": None, "run": None}


def handle_tester_event(event: FrontendEvent, session: dict, *, registry: StrategyRegistry,
                        lookup_dataset=dataset, bounds=dataset_bounds, runner=None,
                        ledger_path: Path = tester.LEDGER_PATH):
    """Validate and execute one Strategy Tester event through the audited adapter.

    Returns (new_session, log_entry, result_or_None). Called once per event id.
    """
    if event.type == "clear_backtest":
        return empty_tester_session(), LogEntry("info", "Strategy Tester result cleared."), None
    form = dict(event.data)
    try:
        validated = tester.validate_run_request(event.data, registry=registry, lookup_dataset=lookup_dataset,
                                                bounds=bounds)
    except tester.TesterValidationError as exc:
        return ({**session, "status": "failed", "error": f"Invalid configuration: {exc}", "form": form},
                LogEntry("error", f"Backtest rejected: {exc}"), None)
    label = f"{validated.descriptor.metadata.name} on {validated.dataset.key} ({event.data['start']}..{event.data['end']})"
    try:
        result, seconds = tester.timed_run(validated, runner=runner, ledger_path=ledger_path)
        run_payload = tester.build_run_payload(result, validated, duration_seconds=seconds)
        # Display decimals of the tested dataset (the chart may show another market).
        run_payload["price_precision"] = _last_closes(str(validated.dataset.path), _mtime(validated.dataset.path))[2]
    except Exception as exc:  # the audited adapter's own refusal or failure, shown verbatim
        return ({**session, "status": "failed", "error": f"{type(exc).__name__}: {exc}", "form": form},
                LogEntry("error", f"Backtest failed: {label}: {exc}"), None)
    return ({"status": "completed", "error": None, "form": form, "run": run_payload},
            LogEntry("info", f"Backtest completed: {label} · run {result.run_id} · "
                             f"{result.total_trades} trades · {seconds:.1f}s"), result)


def _bounds(frame: pd.DataFrame) -> tuple[date, date] | None:
    if frame.empty:
        return None
    return frame["timestamp"].iloc[0].date(), frame["timestamp"].iloc[-1].date()


def _load(state: TerminalState) -> tuple[MarketDataset, TimeframeResolution, pd.DataFrame]:
    selected = dataset(state.dataset_key)
    resolution = resolve_timeframe(selected, state.timeframe)
    frame = _resolved_frame(selected.key, resolution.target, _mtime(resolution.source.path))
    return selected, resolution, frame


def render_custom_terminal() -> None:
    state: TerminalState = st.session_state.get(STATE_KEY) or _initial_state()
    notices: list[dict[str, str]] = []

    # 1-2. Apply the pending frontend event before building this run's payload.
    try:
        _, _, current_frame = _load(state)
        bounds = _bounds(current_frame)
    except Exception:  # bounds only sharpen date validation
        bounds = None
    raw_event = st.session_state.get(COMPONENT_KEY)
    state, entry, last_id, tester_event = consume_event(
        state, raw_event, context_for(bounds), st.session_state.get(LAST_EVENT_KEY))
    tester_session = st.session_state.get(TESTER_KEY) or empty_tester_session()
    registry = discover_builtin_strategies()
    if tester_event is not None:
        # Runs synchronously inside this rerun. The event id is persisted only
        # afterwards, so an interrupted run is retried, never silently dropped.
        tester_session, entry, result = handle_tester_event(tester_event, tester_session, registry=registry)
        st.session_state[TESTER_KEY] = tester_session
        if result is not None:
            st.session_state[TESTER_RESULT_KEY] = result  # full authoritative result, untruncated
        state = replace(state, bottom_panel="strategy_tester", bottom_open=True)
    st.session_state[LAST_EVENT_KEY] = last_id
    if entry is not None:
        _log(entry)
        if entry.level == "error":
            notices.append({"level": "error", "message": entry.message})
        if isinstance(raw_event, dict) and raw_event.get("type") == "chart_ready":
            st.session_state[READY_KEY] = True

    # 3. Resolve and load exactly what the state names. No fallback substitution.
    try:
        selected, resolution, frame = _load(state)
    except (UnsupportedTimeframeError, KeyError, FileNotFoundError, ValueError) as exc:
        st.error(f"Custom terminal could not load {state.dataset_key} @ {state.timeframe}: {exc}")
        return
    st.session_state[STATE_KEY] = state
    st.session_state["tv_dataset_selection"] = state.dataset_key
    st.session_state["tv_tf_selection"] = state.timeframe

    bounds = _bounds(frame)
    shown = None
    if bounds is not None:
        start, end, range_notices = effective_range(state, bounds, resolution.target_seconds)
        notices.extend(range_notices)
        frame = filter_range(frame, start, end)
        shown = (start, end)
        if len(frame) > MAX_BARS:
            notices.append({"level": "warning", "message": f"Showing the latest {MAX_BARS:,} of {len(frame):,} bars."})
            frame = frame.iloc[-MAX_BARS:].reset_index(drop=True)
    else:
        notices.append({"level": "warning", "message": "The selected dataset contains no bars."})

    # 4. Build, validate, render.
    try:
        payload = build_terminal_payload(
            state=state, selected=selected, resolution=resolution, frame=frame, bounds=bounds, shown=shown,
            logs=st.session_state.get(LOGS_KEY, []), notices=notices, watchlist=watchlist_payload(selected),
            ack=last_id, tester_payload={
                **tester_session,
                "options": tester.tester_options(registry, all_datasets(), dataset_bounds),
            })
    except ValueError as exc:
        st.error(f"Custom terminal payload rejected: {exc}")
        return
    if not st.session_state.get(READY_KEY):
        st.caption("Waiting for the custom frontend handshake… If this persists, the component failed to load "
                   "(check the browser console) — Plotly is not being substituted.")
    render_terminal_component(payload, key=COMPONENT_KEY)

