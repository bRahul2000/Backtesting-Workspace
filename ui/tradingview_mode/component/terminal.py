"""Streamlit glue for the custom React terminal.

Order of one rerun:
1. read the component's last event from session state (before rendering),
2. validate + apply it once (events carry unique ids),
3. resolve dataset/timeframe, load and filter data, calculate indicators,
4. build and validate the payload, render the component.

Python owns every value in the payload. The frontend only renders it.
"""
from __future__ import annotations

import dataclasses
from dataclasses import asdict, replace
import time
import uuid
from datetime import date, datetime, timedelta, timezone
import json
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
from . import binance
from . import live as live_model
from . import providers
from . import replay as replay_model
from . import pine_bridge
from . import security_data
from . import source_roles
from . import tester
from . import workspace_data
from .protocol import (
    CONTRACT_VERSION,
    DATA_EVENTS,
    PINE_EVENTS,
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
TESTER_RUNS_KEY = "tv_terminal_tester_runs"
LIVE_BOOKS_KEY = "tv_terminal_live_books"
LIVE_TARGET_KEY = "tv_terminal_live_target"
SECURITY_BINANCE_KEY = "tv_terminal_security_binance"   # request.security() Binance kline cache (per session)
LIVE_SESSION_KEY = "tv_terminal_live_session"
AUTHORITY_KEY = "tv_terminal_signal_authority"
SOURCE_LOG_KEY = "tv_terminal_source_log"
CHART_ROLE_KEY = "tv_terminal_chart_role"
AUTO_REFRESH_KEY = "tv_terminal_auto_refresh"     # symbol family -> last automatic freshness check / error
FRESHNESS_KEY = "tv_terminal_freshness"           # dataset key -> cached data status (throttled)
AUTO_REFRESH_SECONDS = 180                        # at most one automatic check per symbol every 3 minutes
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


def _workspace_loader(path) -> pd.DataFrame:
    """TradingView Mode reads a registered dataset as frozen file + its workspace extension (workspace_data.py)."""
    return workspace_data.load_path(Path(path), all_datasets())


@st.cache_data(show_spinner=False, max_entries=16)
def _resolved_frame(dataset_key: str, timeframe: str, mtime_marker) -> pd.DataFrame:
    resolution = resolve_timeframe(dataset(dataset_key), timeframe)
    return load_resolution_data(resolution, _workspace_loader)


@st.cache_data(show_spinner=False, max_entries=32)
def _last_closes(path_text: str, mtime_marker) -> tuple[float | None, float | None, int]:
    closes = _workspace_loader(path_text)["close"]
    last = float(closes.iloc[-1]) if len(closes) else None
    previous = float(closes.iloc[-2]) if len(closes) > 1 else None
    return last, previous, price_precision(closes)


@st.cache_data(show_spinner=False, max_entries=32)
def _file_bounds(path_text: str, mtime_marker: float) -> tuple[date, date] | None:
    stamps = load_ohlcv_csv(Path(path_text))["timestamp"]
    return (stamps.iloc[0].date(), stamps.iloc[-1].date()) if len(stamps) else None


def dataset_bounds(entry: MarketDataset) -> tuple[date, date] | None:
    return _file_bounds(str(entry.path), _mtime(entry.path)) if entry.exists else None


# ---------------------------------------------------------------------------
# Pure payload pieces
# ---------------------------------------------------------------------------

def context_for(bounds: tuple[date, date] | None = None, bar_times=None) -> TerminalContext:
    keys = {entry.key for entry in all_datasets()}
    return TerminalContext(
        dataset_exists=lambda key: key in keys and dataset(key).exists,
        native_timeframe=lambda key: dataset(key).timeframe,
        available_timeframes=lambda key: available_timeframes(dataset(key)),
        timeframe_seconds=timeframe_seconds,
        data_bounds=bounds,
        bar_times=bar_times,
        dataset_instrument=lambda key: dataset(key).instrument if key in keys else None,
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


def live_quotes(folder: Path, now: float) -> dict[str, dict]:
    """Current MT5 quote per live symbol (read-only); only LIVE/STALE feeds are reported."""
    quotes = {}
    for symbol in live_model.LIVE_SYMBOLS:
        path = live_model.quote_path(folder, symbol)
        if not path.exists():
            continue
        try:
            snapshot = live_model.parse_quote(path.read_text(encoding="utf-8"), symbol)
        except (OSError, live_model.LiveFeedError):
            continue
        status, _ = live_model.connection_status(file_found=True, snapshot=snapshot, error=None, has_bars=True, now=now)
        if status in ("LIVE", "STALE"):
            quotes[symbol] = {"status": status, **live_model.quote_payload(snapshot)}
    return quotes


def live_watchlist(live: providers.LiveState, binance_quotes: dict[str, dict | None], mt5_quotes: dict[str, dict],
                   digits: dict[str, int] | None = None) -> list[dict]:
    """Live rows, one per (market, source), each labelled with its source. A
    source without a current quote shows no price (never another source's)."""
    rows = []
    for source, source_label in providers.SOURCES.items():
        for market in providers.MARKETS:
            ident = providers.identity(market, source)
            symbol = ident["symbol"]
            quote = (binance_quotes if source == "binance" else mt5_quotes).get(symbol)
            precision = (digits or {}).get(symbol) if source == "binance" else (quote or {}).get("digits")
            rows.append({
                "dataset_key": ident["dataset_key"], "kind": "live", "market": market, "source": source,
                "source_label": source_label.split()[0].upper(), "symbol": symbol + (" PERP" if source == "binance" else ""),
                "provider": ident["provider"], "instrument": ident["instrument"], "title": providers.title(ident),
                "native_timeframes": list(providers.LIVE_TIMEFRAMES), "last_close": None, "change_pct": None,
                "price_precision": precision if precision is not None else 2,
                "selected": live.market == market and live.source == source,
                "live": None if quote is None else {"status": quote["status"], "bid": quote["bid"], "ask": quote["ask"],
                                                    "digits": precision},
            })
    return rows


def watchlist_payload(selected: MarketDataset, live_rows: list[dict] | None = None) -> list[dict]:
    """Registered datasets (historical reference closes), preceded by the
    source-labelled live rows while Live is streaming."""
    items = list(live_rows or [])
    for group in watchlist_groups():
        available = [entry for entry in group if entry.exists]
        if not available:
            continue
        primary = available[0]
        last, previous, precision = _last_closes(str(primary.path), workspace_data.marker(primary))
        change = None if last is None or not previous else (last - previous) / previous * 100.0
        items.append({
            "dataset_key": primary.key, "kind": "dataset", "symbol": primary.symbol, "provider": primary.broker,
            "instrument": primary.instrument, "native_timeframes": [entry.timeframe for entry in available],
            "last_close": last, "change_pct": change, "price_precision": precision,
            "selected": not live_rows and any(entry.key == selected.key for entry in group),
            "live": None,
        })
    return items


def build_terminal_payload(*, state: TerminalState, selected: MarketDataset, resolution: TimeframeResolution,
                           frame: pd.DataFrame, bounds: tuple[date, date] | None, shown: tuple[date, date] | None,
                           logs: list[LogEntry], notices: list[dict[str, str]],
                           watchlist: list[dict], ack: str | None = None,
                           tester_payload: dict | None = None, replay_status: dict | None = None,
                           live_status: dict | None = None, sources: dict | None = None,
                           pine: dict | None = None, data_status: dict | None = None) -> dict:
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
        # Replay is its own view, so entering/leaving it never reuses the other's zoom.
        "view_key": f"{selected.instrument}|{selected.broker}|{selected.symbol}|{resolution.target}"
                    + ("|replay" if replay_status else ""),
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
        "replay": replay_status or {"enabled": False},
        "live": live_status or {"enabled": False},
        # Chart / Signal / Execution roles: streaming Live only (never in Replay or Historical).
        "sources": sources,
        # Pine scripts: editor state and each script's outputs on these bars (see pine_bridge.py).
        "pine": pine,
        # Freshness of the chart's local history (Historical / Replay): last local bar vs the newest closed bar a
        # known local source has, and whether Refresh data can fetch it (workspace_data.py).
        "data_status": None if live_status and live_status.get("phase") != "setup" else data_status,
    }
    if live_status and live_status.get("phase") == "setup":
        payload["mode"] = "live"  # setup: the chart still shows the historical dataset
    elif live_status:
        # Live bars come from exactly one provider (never a registry file, never mixed).
        ident, timeframe = live_status["identity"], live_status["timeframe"]
        payload.update({
            "mode": "live", "dataset_key": ident["dataset_key"], "symbol": ident["symbol"],
            "provider": ident["provider"], "instrument": ident["instrument"], "timeframe": timeframe,
            "timeframes": list(providers.LIVE_TIMEFRAMES),
            # A provider switch is a new view: the chart reloads instead of stitching histories.
            "view_key": f"{ident['dataset_key']}|{timeframe}|live",
            "bars_rev": bars_revision(bars, ident["dataset_key"], timeframe),
            "source": {"dataset_key": ident["dataset_key"], "label": f"{live_status['title']} · live (read-only)",
                       "provider": ident["provider"], "symbol": ident["symbol"], "timeframe": timeframe, "native": True,
                       "description": f"{ident['source_label']} live · native", "read_only": True},
        })
        if live_status.get("digits") is not None:
            payload["price_precision"] = live_status["digits"]
    elif replay_status:
        payload["mode"] = "replay"
    tester_payload = tester_payload or {"status": "idle", "options": {}, "form": None, "run": None, "error": None,
                                        "history": [], "active_history_id": None, "export": None}
    payload["tester"] = tester_payload
    payload["trade_overlay"] = {"available": False, "trades": [],
                                "reason": "Strategy Tester markers are hidden in Live mode."} if live_status else tester.trade_overlay(
        tester_payload.get("run"), chart_identity=(selected.instrument, selected.broker, selected.symbol),
        bar_times=times, bar_seconds=resolution.target_seconds,
        chart_label=f"{selected.symbol} · {selected.broker} · {resolution.target}")
    return validate_payload(payload)


# ---------------------------------------------------------------------------
# Session state + event handling
# ---------------------------------------------------------------------------

def _initial_state() -> TerminalState:
    """Seed from any earlier TradingView Mode selection kept in the session."""
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
    if event.type in TESTER_EVENTS or event.type in PINE_EVENTS or event.type in DATA_EVENTS:
        return state, None, event.id, event
    new_state, entry = apply_event(state, event, ctx)
    return new_state, entry, event.id, None


MAX_HISTORY = 10


def empty_tester_session() -> dict:
    return {"status": "idle", "error": None, "form": None, "run": None,
            "history": [], "active_history_id": None, "next_history_id": 1, "export": None}


def _history_row(history_id: int, payload: dict) -> dict:
    return {"history_id": history_id, "run_id": payload["run_id"], "ledger_mode": payload["ledger"]["mode"],
            "strategy": payload["strategy"]["name"], "instrument": payload["config"]["instrument"],
            "dataset": payload["dataset"]["label"], "start": payload["config"]["start"][:10],
            "end": payload["config"]["end"][:10], "total_trades": payload["summary"]["total_trades"],
            "pnl": payload["summary"]["pnl"], "win_rate": payload["summary"]["win_rate"]}


def handle_tester_event(event: FrontendEvent, session: dict, runs: dict, *, registry: StrategyRegistry,
                        lookup_dataset=dataset, bounds=dataset_bounds, runner=None, replay_active: bool = False):
    """Handle one Strategy Tester event. Called once per event id.

    ``runs`` is the in-memory session history {history_id: {payload, result, run}}.
    Only ``run_backtest`` executes anything, through the audited adapter;
    ``restore_run`` and ``export_run`` read results already returned.
    Returns (new_session, new_runs, log_entry, result_or_None).
    """
    session = {**empty_tester_session(), **session, "export": None}
    kind = event.type
    if kind == "clear_backtest":
        return ({**session, "status": "idle", "error": None, "run": None, "active_history_id": None}, runs,
                LogEntry("info", "Strategy Tester result cleared (session history kept)."), None)
    if kind in ("restore_run", "export_run"):
        history_id = event.data["history_id"]
        stored = runs.get(history_id)
        if stored is None:
            return ({**session, "status": "failed", "error": f"Session run {history_id} is no longer available."},
                    runs, LogEntry("error", f"{kind}: unknown session run {history_id}."), None)
        if kind == "restore_run":
            return ({**session, "status": "completed", "error": None, "run": stored["payload"],
                     "form": dict(stored["run"].request), "active_history_id": history_id}, runs,
                    LogEntry("info", f"Restored {stored['payload']['run_id']} from session history (not re-run)."), None)
        if replay_active:
            # An export is the full result, including everything after the replay cursor.
            return (session, runs, LogEntry("error", "Exports are disabled during Replay (they contain the full "
                                                     "backtest result). Exit Replay to export."), None)
        base = f"{stored['payload']['run_id']}_{stored['run'].descriptor.metadata.strategy_id}_{stored['run'].ledger_mode}"
        if event.data["kind"] == "trades_csv":
            export = {"filename": f"{base}_trades.csv", "mime": "text/csv",
                      "content": tester.trades_csv(stored["result"])}
        else:
            export = {"filename": f"{base}_summary.json", "mime": "application/json",
                      "content": json.dumps(tester.summary_export(stored["result"], stored["run"]),
                                            indent=2, allow_nan=False)}
        return ({**session, "export": {"id": event.id, **export}}, runs,
                LogEntry("info", f"Exported {export['filename']} (generated in Python)."), None)

    form = dict(event.data)
    try:
        validated = tester.validate_run_request(event.data, registry=registry, lookup_dataset=lookup_dataset,
                                                bounds=bounds)
    except tester.TesterValidationError as exc:
        return ({**session, "status": "failed", "error": f"Invalid configuration: {exc}", "form": form}, runs,
                LogEntry("error", f"Backtest rejected: {exc}"), None)
    label = (f"{validated.descriptor.metadata.name} on {validated.dataset.key} "
             f"({event.data['start']}..{event.data['end']}) · {tester.LEDGER_MODES[validated.ledger_mode]}")
    try:
        result, seconds = tester.timed_run(validated, runner=runner)
        run_payload = tester.build_run_payload(result, validated, duration_seconds=seconds)
        # Display decimals of the tested dataset (the chart may show another market).
        run_payload["price_precision"] = _last_closes(str(validated.dataset.path), _mtime(validated.dataset.path))[2]
    except Exception as exc:  # the audited adapter's own refusal or failure, shown verbatim
        return ({**session, "status": "failed", "error": f"{type(exc).__name__}: {exc}", "form": form}, runs,
                LogEntry("error", f"Backtest failed: {label}: {exc}"), None)
    history_id = session["next_history_id"]
    run_payload["history_id"] = history_id
    # Session history keeps a slim copy (without the engine's per-segment objects);
    # the returned ``result`` itself is untouched.
    slim = dataclasses.replace(result, legacy_segment_results=[])
    runs = {history_id: {"payload": run_payload, "result": slim, "run": validated}, **runs}
    history = [_history_row(history_id, run_payload), *session["history"]]
    for dropped in history[MAX_HISTORY:]:
        runs.pop(dropped["history_id"], None)
    session = {**session, "status": "completed", "error": None, "form": form, "run": run_payload,
               "history": history[:MAX_HISTORY], "active_history_id": history_id,
               "next_history_id": history_id + 1}
    return (session, runs,
            LogEntry("info", f"Backtest completed: {label} · run {result.run_id} · "
                             f"{result.total_trades} trades · {seconds:.1f}s"), result)


def tester_presentation(session: dict, registry: StrategyRegistry, replay_status: dict | None,
                        bar_seconds: int) -> dict:
    """The Strategy Tester part of the payload. During Replay only what was
    knowable by the close of the newest revealed bar is included."""
    shown = {key: value for key, value in session.items() if key != "next_history_id"}
    shown["options"] = tester.tester_options(registry, all_datasets(), dataset_bounds)
    if replay_status:
        knowable_until = replay_status["cursor_timestamp"] + bar_seconds
        shown["run"] = tester.replay_view(session.get("run"), knowable_until)
        shown["history"] = tester.replay_history(session.get("history", []))
        shown["export"] = None
    return shown


def _bounds(frame: pd.DataFrame) -> tuple[date, date] | None:
    if frame.empty:
        return None
    return frame["timestamp"].iloc[0].date(), frame["timestamp"].iloc[-1].date()


def _load(state: TerminalState) -> tuple[MarketDataset, TimeframeResolution, pd.DataFrame]:
    selected = dataset(state.dataset_key)
    resolution = resolve_timeframe(selected, state.timeframe)
    frame = _resolved_frame(selected.key, resolution.target, workspace_data.marker(resolution.source))
    return selected, resolution, frame


def _family(selected: MarketDataset) -> list[MarketDataset]:
    return [entry for entry in all_datasets() if entry.symbol == selected.symbol and entry.broker == selected.broker
            and workspace_data.refreshable(entry)]


def auto_refresh_workspace(state: TerminalState, session, now: float) -> LogEntry | None:
    """Historical mode keeps locally backed charts current: a lightweight freshness check when the terminal opens,
    when a symbol or timeframe is selected, and otherwise at most every AUTO_REFRESH_SECONDS. Missing CLOSED bars are
    appended to the workspace history (never to a frozen dataset). A failure never breaks the chart: the status stays
    STALE with the error, and the manual Refresh remains."""
    if state.replay is not None or state.live is not None:
        return None
    try:
        selected = dataset(state.dataset_key)
    except KeyError:
        return None
    family = _family(selected)
    if not family:
        return None
    checks = session.setdefault(AUTO_REFRESH_KEY, {})
    key = f"{selected.broker}|{selected.symbol}"
    last = checks.get(key)
    if last is not None and last["view"] == (state.dataset_key, state.timeframe) and now - last["at"] < AUTO_REFRESH_SECONDS:
        return None
    appended, errors = [], []
    for entry in family:
        try:
            result = workspace_data.refresh(entry)
        except workspace_data.RefreshError as exc:
            if not str(exc).startswith("no readable MT5 source"):
                errors.append(f"{entry.timeframe}: {exc}")
            continue
        except OSError as exc:
            errors.append(f"{entry.timeframe}: {exc}")
            continue
        if result["appended"]:
            appended.append(f"{entry.timeframe} +{result['appended']} through {result['last_closed']} UTC")
    checks[key] = {"at": now, "view": (state.dataset_key, state.timeframe), "errors": errors}
    session.pop(FRESHNESS_KEY, None)
    if errors:
        from services.auth.logs import setup as _logs
        _logs("app").warning("automatic data refresh failed for %s: %s", selected.symbol, "; ".join(errors))
        return LogEntry("warning", f"Automatic data refresh failed for {selected.symbol}: {'; '.join(errors)}. "
                                   "The chart keeps the last local bars; use Refresh to retry.")
    if appended:
        return LogEntry("info", f"Automatic data refresh: {selected.symbol} " + " · ".join(appended))
    return None


def refresh_workspace_data(state: TerminalState) -> LogEntry:
    """Refresh data: append the closed bars the local MT5 sources have to the WORKSPACE copies of every refreshable
    dataset of the chart's symbol (M15 and H1 together, so request.security() stays aligned). Frozen research datasets
    are never written (workspace_data.py)."""
    if state.replay is not None or state.live is not None:
        return LogEntry("error", "Rejected: Refresh data is available in Historical mode.")
    selected = dataset(state.dataset_key)
    family = _family(selected)
    if not family:
        return LogEntry("error", f"Rejected: {selected.label} has no local MT5 source to refresh from.")
    parts, failed = [], []
    for entry in family:
        try:
            result = workspace_data.refresh(entry)
        except (workspace_data.RefreshError, OSError) as exc:
            failed.append(f"{entry.timeframe}: not refreshed ({exc}; nothing was written for it)")
            continue
        parts.append(f"{entry.timeframe}: +{result['appended']} closed bars through {result['last_closed']} UTC"
                     if result["appended"] else f"{entry.timeframe}: already current ({result['last_closed']} UTC)")
    if failed:
        from services.auth.logs import setup as _logs
        _logs("app").warning("manual data refresh failed for %s: %s", selected.symbol, " · ".join(failed))
    if not parts:
        return LogEntry("error", f"Refresh failed for {selected.symbol} · " + " · ".join(failed))
    return LogEntry("warning" if failed else "info",
                    f"Refreshed {selected.symbol} workspace history · " + " · ".join(parts + failed))


def data_status(entry: MarketDataset, session=None, now: float | None = None) -> dict:
    """Freshness of the chart's source dataset, cached per dataset until its files change or AUTO_REFRESH_SECONDS pass
    (normal reruns do not touch the MT5 folder). The last automatic refresh error, if any, is attached."""
    cache = session.setdefault(FRESHNESS_KEY, {}) if session is not None else {}
    now = time.time() if now is None else now
    marker = (workspace_data.marker(entry), workspace_data.source_marker(entry))
    cached = cache.get(entry.key)
    if cached is not None and cached["marker"] == marker and now - cached["at"] < AUTO_REFRESH_SECONDS:
        status = dict(cached["status"])
    else:
        status = workspace_data.freshness(entry)
        status["label"] = entry.label
        cache[entry.key] = {"at": now, "marker": marker, "status": dict(status)}
    auto = (session or {}).get(AUTO_REFRESH_KEY, {}).get(f"{entry.broker}|{entry.symbol}")
    status["auto_refresh"] = None if auto is None else {
        "checked": datetime.fromtimestamp(auto["at"], timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "errors": auto["errors"]}
    if auto and auto["errors"]:
        status["problems"] = list(status.get("problems") or []) + [f"automatic refresh: {e}" for e in auto["errors"]]
    return status


def live_setup_status(live: providers.LiveState, selected: MarketDataset) -> dict:
    """Live mode before Go Live: the chart still shows the historical dataset and
    nothing is connected or read."""
    market = providers.market_for_instrument(selected.instrument)
    native = selected.broker == "Exness Technologies Ltd"
    if market is None:
        message = f"{providers.UNSUPPORTED_MESSAGE} {selected.symbol} ({selected.broker}) has no live market — choose one."
    elif not native:
        message = (f"{selected.symbol} ({selected.broker.split(' (')[0]}) has no live feed. Live shows "
                   f"{providers.MARKETS[market]['label']} from the source you choose — a different instrument.")
    else:
        message = None
    return {"enabled": True, "phase": "setup", "status": None, "market": live.market, "source": live.source,
            "timeframe": live.timeframe, "current_supported": market is not None, "message": message,
            "note": providers.BINANCE_NOTE, **providers.catalog()}


def update_source_roles(state: TerminalState, live_status: dict, session, now: float, *,
                        folder: Path | None = None) -> dict:
    """Chart / Signal / Execution roles for a streaming Live chart (read-only).

    The signal source is observed from Exness MT5 for the live market whatever
    the chart shows; the chart role comes from the chart provider's status."""
    live = state.live
    tracker = session.get(AUTHORITY_KEY) or source_roles.AuthorityTracker()
    observation = source_roles.observe_exness(live.market, live.timeframe, now, folder)
    tracker, assessment, events = source_roles.advance(tracker, observation)
    readiness = source_roles.execution_readiness(observation, assessment)
    if readiness.reason != tracker.execution_reason:
        events.append(f"Execution DISABLED: {readiness.reason}")
        tracker = dataclasses.replace(tracker, execution_reason=readiness.reason)
    chart = source_roles.chart_role(live_status)
    chart_key = (chart.source, chart.symbol, chart.timeframe)
    if session.get(CHART_ROLE_KEY) != chart_key:
        session[CHART_ROLE_KEY] = chart_key
        events.insert(0, f"Chart source: {chart.provider} · {chart.symbol} · {chart.timeframe} (signal source unchanged)")
    log = source_roles.append_log(session.get(SOURCE_LOG_KEY, []), events, now)
    session[AUTHORITY_KEY], session[SOURCE_LOG_KEY] = tracker, log
    signal = source_roles.signal_role(observation, assessment, chart)
    return source_roles.source_payload(chart, signal, source_roles.execution_role(live.market, readiness), readiness,
                                       assessment, log)


def release_source_roles(session, now: float) -> None:
    """Leaving Live drops signal authority; re-entering must validate again."""
    if session.pop(AUTHORITY_KEY, None) is not None:
        session.pop(CHART_ROLE_KEY, None)
        session[SOURCE_LOG_KEY] = source_roles.append_log(
            session.get(SOURCE_LOG_KEY, []), ["Live ended: signal authority released, execution DISABLED"], now)


def live_session_id(session) -> str:
    """Stable id of this browser session (lease owner in the Binance hub)."""
    if LIVE_SESSION_KEY not in session:
        session[LIVE_SESSION_KEY] = uuid.uuid4().hex
    return session[LIVE_SESSION_KEY]


def sync_live_connections(state: TerminalState, session, *, hub: binance.BinanceHub) -> LogEntry | None:
    """Tear down the previous provider whenever the live target changes.

    Clears the MT5 books, releases the session's Binance kline lease (the hub
    then closes that socket) and, when Live ends, the quote lease too. Runs
    every rerun but acts only on a change, so reruns never reconnect."""
    target = state.live.target if state.live is not None else None
    previous = session.get(LIVE_TARGET_KEY)
    if target == previous:
        return None
    session[LIVE_TARGET_KEY] = target
    session.pop(LIVE_BOOKS_KEY, None)
    session_id = live_session_id(session)
    if target is None:
        hub.release(session_id)
    elif target[0] != "binance":
        hub.release(session_id, "kline")
    if previous is None:
        return None
    return LogEntry("info", f"Live source changed: {providers.SOURCES[previous[0]]} {previous[1]} {previous[2]} closed "
                            f"and its bars cleared.")


def live_provider(state: TerminalState, session, *, hub: binance.BinanceHub | None = None):
    live = state.live
    if live.source == "binance":
        return providers.BinanceFuturesProvider(live.market, live.timeframe, session_id=live_session_id(session),
                                                hub=hub or binance.hub())
    return providers.ExnessMT5Provider(live.market, live.timeframe, books=session.setdefault(LIVE_BOOKS_KEY, {}))


def live_rows(state: TerminalState, session, now: float, *, hub: binance.BinanceHub | None = None,
              folder: Path | None = None) -> list[dict]:
    hub = hub or binance.hub()
    board = hub.quotes(live_session_id(session))
    binance_quotes = {providers.MARKETS[m]["binance"]: providers.binance_watch_quote(board, providers.MARKETS[m]["binance"], now)
                      for m in providers.MARKETS}
    digits = {symbol: info["digits"] for symbol, info in binance.CONTRACTS.items()}
    return live_watchlist(state.live, {k: v for k, v in binance_quotes.items() if v},
                          live_quotes(folder or live_model.common_files_dir(), now), digits)


def _live_frame(state: TerminalState, notices: list[dict[str, str]], selected: MarketDataset):
    provider = live_provider(state, st.session_state)
    view = provider.view(time.time())
    status = view.status
    if getattr(provider, "last_verdict", None) == "out_of_order":
        _log(LogEntry("warning", f"Live {status['symbol']}: out-of-order MT5 update rejected."))
    if status["status"] in ("ERROR", "DISCONNECTED"):
        notices.append({"level": "error" if status["status"] == "ERROR" else "warning",
                        "message": f"Live {status['title']}: {status['status']} — {status['reason']}"})
    timeframe = state.live.timeframe
    resolution = TimeframeResolution(timeframe, timeframe_seconds(timeframe), selected, True)
    return view.frame, status, resolution


def pine_section(state: TerminalState, frame: pd.DataFrame, selected: MarketDataset, live_status: dict | None,
                 replay_status: dict | None, seconds: int, notices: list[dict[str, str]],
                 calc_frame: pd.DataFrame | None = None) -> dict:
    """Run the chart's Pine scripts. Replay and Live: exactly the bars this payload shows. Historical: on
    ``calc_frame`` (all available history up to the chart's last bar), with outputs for the rendered bars only - a
    strategy backtest is not limited to the visible window."""
    display_from = None
    if calc_frame is not None and len(frame) and len(calc_frame) > len(frame):
        display_from = int(frame["timestamp"].iloc[0].timestamp())
        frame = calc_frame
    streaming = live_status is not None and live_status.get("phase") == "streaming"
    last_open_ms = int(frame["timestamp"].iloc[-1].timestamp() * 1000) if len(frame) else None
    if streaming:
        ident = live_status["identity"]
        identity = ("live", ident["dataset_key"], live_status["timeframe"])
        symbol, provider = ident["symbol"], ident["source_label"]
        digits = live_status.get("digits")
        family, mode = ident["source"], "live"
        knowable_until = last_open_ms                  # the forming bar: only completed bars before it are closed
    else:
        identity = ("replay" if replay_status else "historical", selected.key, state.timeframe)
        symbol, provider = selected.symbol, selected.broker
        digits = price_precision(frame["close"]) if len(frame) else 2
        family = security_data.family_of_dataset(selected)
        mode = "replay" if replay_status else "historical"
        knowable_until = last_open_ms + seconds * 1000 if replay_status and last_open_ms is not None else None
    binance_provider = st.session_state.get(SECURITY_BINANCE_KEY)
    if binance_provider is None:
        binance_provider = st.session_state[SECURITY_BINANCE_KEY] = security_data.BinanceProvider()
    digits = 2 if digits is None else int(digits)
    # Live: lower-timeframe requests see the intrabars this terminal has received on the forming bar (P2.2-A4)
    received = providers.lower_tf_received(family, now=time.time(), session_id=live_session_id(st.session_state),
                                           books=st.session_state.setdefault(LIVE_BOOKS_KEY, {}),
                                           chart=(symbol, seconds, frame)) if streaming else None
    section = pine_bridge.pine_payload(
        state, frame, st.session_state, identity=identity, timeframe_seconds=seconds, ticker=symbol,
        tickerid=f"{provider.split(' ')[0].upper()}:{symbol}", mintick=10.0 ** -digits, forming_last=streaming,
        kind="cfd" if provider.startswith("Exness") else "crypto",
        currency="USDT" if symbol.upper().endswith("USDT") else "USD", chart_family=family, mode=mode,
        knowable_until=knowable_until, display_from=display_from,
        provider=security_data.provider_for(family, binance_provider=binance_provider, received=received))
    for script in section["scripts"]:
        if script["error"] and script["enabled"]:
            where = f" (bar {script['error']['bar_index']})" if script["error"].get("bar_index") is not None else ""
            notices.append({"level": "error", "message": f"Pine `{script['title']}`: {script['error']['message']}{where}"})
    return section


def render_custom_terminal() -> None:
    state: TerminalState = st.session_state.get(STATE_KEY) or _initial_state()
    notices: list[dict[str, str]] = []

    # 1-2. Apply the pending frontend event before building this run's payload.
    try:
        _, _, current_frame = _load(state)
        bounds = _bounds(current_frame)
        current_times = replay_model.frame_times(current_frame)
    except Exception:  # bounds only sharpen validation; replay events then report no bars
        bounds, current_times = None, None
    raw_event = st.session_state.get(COMPONENT_KEY)
    state, entry, last_id, tester_event = consume_event(
        state, raw_event, context_for(bounds, current_times), st.session_state.get(LAST_EVENT_KEY))
    tester_session = st.session_state.get(TESTER_KEY) or empty_tester_session()
    registry = discover_builtin_strategies()
    if tester_event is not None and tester_event.type in DATA_EVENTS:
        entry = refresh_workspace_data(state)
        st.session_state.pop(FRESHNESS_KEY, None)
        if entry.level != "error":           # a successful manual refresh replaces the last automatic check
            chart = dataset(state.dataset_key)
            st.session_state.setdefault(AUTO_REFRESH_KEY, {})[f"{chart.broker}|{chart.symbol}"] = {
                "at": time.time(), "view": (state.dataset_key, state.timeframe), "errors": []}
    elif tester_event is not None and tester_event.type in PINE_EVENTS:
        before = len(state.pine)
        state, entry = pine_bridge.handle_pine_event(tester_event, state, st.session_state)
        added = tester_event.type == "pine_add" and len(state.pine) > before
        if added and not tester_event.data.get("keep_editor"):
            # after a successful Add to chart the editor makes room: a strategy opens the Strategy Tester, an
            # indicator collapses the dock (unless the editor is pinned open)
            strategy = pine_bridge.compiled(state.pine[-1].source).meta.get("kind") == "strategy"
            state = replace(state, bottom_panel="strategy_tester" if strategy else "pine", bottom_open=strategy)
        else:
            state = replace(state, bottom_panel="pine", bottom_open=True)
    elif tester_event is not None:
        # Runs synchronously inside this rerun. The event id is persisted only
        # afterwards, so an interrupted run is retried, never silently dropped.
        tester_session, runs, entry, result = handle_tester_event(
            tester_event, tester_session, st.session_state.get(TESTER_RUNS_KEY, {}), registry=registry,
            replay_active=state.replay is not None)
        st.session_state[TESTER_KEY] = tester_session
        st.session_state[TESTER_RUNS_KEY] = runs
        if result is not None:
            st.session_state[TESTER_RESULT_KEY] = result  # full authoritative result, untruncated
        state = replace(state, bottom_panel="strategy_tester", bottom_open=True)
    st.session_state[LAST_EVENT_KEY] = last_id
    if (entry is not None and entry.level != "error" and isinstance(raw_event, dict)
            and raw_event.get("type") == "load_live_history"):
        _added, message = live_provider(state, st.session_state).load_older()
        entry = LogEntry("info", message)
    if entry is not None:
        _log(entry)
        if entry.level == "error":
            notices.append({"level": "error", "message": entry.message})
        if isinstance(raw_event, dict) and raw_event.get("type") == "chart_ready":
            st.session_state[READY_KEY] = True

    # 2b. Historical: keep locally backed datasets current (throttled; never a frozen dataset).
    auto = auto_refresh_workspace(state, st.session_state, time.time())
    if auto is not None:
        _log(auto)

    # 3. Resolve and load exactly what the state names. No fallback substitution.
    try:
        selected, resolution, frame = _load(state)
    except (UnsupportedTimeframeError, KeyError, FileNotFoundError, ValueError) as exc:
        st.error(f"TradingView Mode could not load {state.dataset_key} @ {state.timeframe}: {exc}")
        return
    st.session_state[STATE_KEY] = state
    switched = sync_live_connections(state, st.session_state, hub=binance.hub())
    if not (state.live is not None and state.live.streaming):
        release_source_roles(st.session_state, time.time())
    if switched is not None:
        _log(switched)
    st.session_state["tv_dataset_selection"] = state.dataset_key
    st.session_state["tv_tf_selection"] = state.timeframe

    bounds = _bounds(frame)
    shown = None
    replay_status = None
    if state.replay is not None:
        # Slice before serialization: bars after the cursor never leave Python,
        # and indicators below are calculated on this revealed frame only.
        try:
            times = replay_model.frame_times(frame)
            replay_status = replay_model.info(state.replay, times)
            frame = replay_model.revealed(frame, state.replay)
            shown = (frame["timestamp"].iloc[0].date(), frame["timestamp"].iloc[-1].date())
        except replay_model.ReplayError as exc:
            state = replace(state, replay=None)
            st.session_state[STATE_KEY] = state
            notices.append({"level": "error", "message": f"Replay ended: {exc}"})
            _log(LogEntry("error", f"Replay ended: {exc}"))
    live_status = None
    rows = None
    sources = None
    calc_frame = None
    streaming = state.live is not None and state.live.streaming
    if state.live is not None and not streaming:
        live_status = live_setup_status(state.live, selected)
    if streaming:
        frame, live_status, resolution = _live_frame(state, notices, selected)
        rows = live_rows(state, st.session_state, time.time())
        sources = update_source_roles(state, live_status, st.session_state, time.time())
        shown = (frame["timestamp"].iloc[0].date(), frame["timestamp"].iloc[-1].date()) if len(frame) else None
    elif replay_status is None and bounds is not None:
        start, end, range_notices = effective_range(state, bounds, resolution.target_seconds)
        notices.extend(range_notices)
        full = frame
        frame = filter_range(frame, start, end)
        if len(frame) and state.live is None:           # Historical only (Live setup still shows these bars)
            calc_frame = full[full["timestamp"] <= frame["timestamp"].iloc[-1]].reset_index(drop=True)
        shown = (start, end)
        if len(frame) > MAX_BARS:
            notices.append({"level": "warning", "message": f"Showing the latest {MAX_BARS:,} of {len(frame):,} bars."})
            frame = frame.iloc[-MAX_BARS:].reset_index(drop=True)
    elif replay_status is None:
        notices.append({"level": "warning", "message": "The selected dataset contains no bars."})

    pine = pine_section(state, frame, selected, live_status, replay_status, resolution.target_seconds, notices,
                        calc_frame=calc_frame)

    # 4. Build, validate, render.
    try:
        payload = build_terminal_payload(
            state=state, selected=selected, resolution=resolution, frame=frame, bounds=bounds, shown=shown,
            logs=st.session_state.get(LOGS_KEY, []), notices=notices, watchlist=watchlist_payload(selected, rows),
            replay_status=replay_status, live_status=live_status, sources=sources, pine=pine, ack=last_id,
            data_status=None if streaming else data_status(resolution.source, st.session_state),
            tester_payload=tester_presentation(tester_session, registry, replay_status, resolution.target_seconds))
    except ValueError as exc:
        st.error(f"TradingView Mode payload rejected: {exc}")
        return
    if not st.session_state.get(READY_KEY):
        st.caption("Waiting for the TradingView Mode frontend… If this persists, the component failed to load "
                   "(check the browser console).")
    render_terminal_component(payload, key=COMPONENT_KEY)
    if tester_session.get("export"):
        # Delivered once; the frontend downloads it by event id.
        st.session_state[TESTER_KEY] = {**tester_session, "export": None}

