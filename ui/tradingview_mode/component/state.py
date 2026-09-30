"""Pure terminal state and event application for the custom frontend.

Every frontend event passes through ``apply_event``. An invalid event is
rejected with an error log entry and the state is left untouched; nothing is
ever silently substituted.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
import math
from typing import Callable

from ..indicators import CHARTABLE, INDICATORS, validate_params
from . import replay as replay_model
from .protocol import FrontendEvent
from .replay import ReplayError, ReplayState
from .providers import DEFAULT_SOURCE, LIVE_TIMEFRAMES, MARKETS, SOURCES, UNSUPPORTED_MESSAGE, LiveState, market_for_instrument


MAX_BARS = 50_000
DEFAULT_RANGE_BARS = 2_000
DEFAULT_RANGE_DAYS = 30
MAX_INDICATORS = 12
INDICATOR_COLORS = ("#f5a623", "#4aa3ff", "#c678dd", "#56d4bc", "#e5c07b", "#ff7a90", "#98c379", "#61afef")
# Indicators the chart can draw. Volume is a built-in chart setting instead.
CHARTABLE_INDICATORS = CHARTABLE


@dataclass(frozen=True)
class IndicatorInstance:
    id: str
    key: str
    params: dict[str, float | int]
    enabled: bool
    color: str


@dataclass(frozen=True)
class LogEntry:
    level: str  # "debug" | "info" | "warning" | "error"
    message: str
    time: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%H:%M:%S"))


@dataclass(frozen=True)
class PineInstance:
    """A Pine script on the chart: its source, enabled flag and input overrides."""

    id: str
    source: str
    title: str
    enabled: bool = True
    inputs: tuple[tuple[int, object], ...] = ()   # (input index, user value)
    # Strategy Tester range (UTC 'YYYY-MM-DDTHH:MM' start, end), None = full available history (strategies only)
    test_range: tuple[str, str] | None = None


@dataclass(frozen=True)
class TerminalState:
    dataset_key: str
    timeframe: str
    # None means "Python default window"; otherwise an explicit inclusive UTC date range.
    date_range: tuple[date, date] | None = None
    indicators: tuple[IndicatorInstance, ...] = ()
    show_volume: bool = False       # candles only by default; Settings -> "Show volume" adds the histogram
    bottom_panel: str = "indicators"
    bottom_open: bool = True
    next_indicator: int = 1
    # Historical when None; otherwise the session's replay (see replay.py).
    replay: ReplayState | None = None
    # Read-only live view (see providers.py). Never set together with replay.
    live: LiveState | None = None
    # Pine scripts on the chart (see pine_bridge.py); they run on whatever bars the chart shows.
    pine: tuple[PineInstance, ...] = ()
    next_pine: int = 1


@dataclass(frozen=True)
class TerminalContext:
    """Registry facts ``apply_event`` needs, injected so it stays pure."""

    dataset_exists: Callable[[str], bool]
    native_timeframe: Callable[[str], str]
    available_timeframes: Callable[[str], tuple[str, ...]]
    timeframe_seconds: Callable[[str], int]
    # Inclusive UTC date bounds of the currently resolved data, if known.
    data_bounds: tuple[date, date] | None = None
    # Open times (epoch seconds) of every bar of the resolved dataset/timeframe.
    bar_times: object = None
    # Registry instrument of a dataset key (used to preselect the live market).
    dataset_instrument: Callable[[str], str | None] | None = None


def validate_indicator_params(key: str, params: dict | None) -> dict:
    """Return complete, typed params for ``key`` or raise ValueError (the indicator's own parameter specs)."""
    return validate_params(key, params)


def default_range_days(timeframe_seconds: int) -> int:
    """Default window: at least 30 days and roughly 2,000 bars."""
    return max(DEFAULT_RANGE_DAYS, math.ceil(DEFAULT_RANGE_BARS * timeframe_seconds / 86_400))


def _reject(state: TerminalState, message: str) -> tuple[TerminalState, LogEntry]:
    return state, LogEntry("error", f"Rejected: {message}")


def _find(state: TerminalState, indicator_id: str) -> IndicatorInstance | None:
    return next((item for item in state.indicators if item.id == indicator_id), None)


def _replace_indicator(state: TerminalState, updated: IndicatorInstance) -> TerminalState:
    return replace(state, indicators=tuple(updated if item.id == updated.id else item for item in state.indicators))


REPLAY_EVENTS = ("enter_replay", "set_replay_start", "step_forward", "step_backward", "play_replay",
                 "pause_replay", "set_replay_speed", "jump_replay", "exit_replay", "go_to_replay_latest")


LIVE_EVENTS = ("enter_live", "go_live", "exit_live", "live_poll", "load_live_history")


def _apply_live(state: TerminalState, event: FrontendEvent, ctx: TerminalContext) -> tuple[TerminalState, LogEntry | None]:
    """Live mode has two steps: enter (setup: choose market/source/timeframe) and
    Go Live (connect to that one provider). Entering never needs a feed."""
    kind, data = event.type, event.data
    if kind == "live_poll":
        # A refresh request: nothing changes; not logged (it arrives every second).
        return state, None
    if kind == "load_live_history":
        # A data request, not a state change: terminal.py fetches the older candles.
        if state.live is None or not state.live.streaming:
            return _reject(state, "older live history needs a streaming Live chart.")
        return state, LogEntry("debug", "Older live history requested.")
    if kind == "exit_live":
        if state.live is None:
            return _reject(state, "Live mode is not active.")
        return replace(state, live=None), LogEntry("info", "Live mode ended; historical view restored.")
    if state.replay is not None:
        return _reject(state, "exit Replay before entering Live.")
    if kind == "enter_live":
        if state.live is not None:
            return state, LogEntry("debug", "Live mode already active.")
        instrument = ctx.dataset_instrument(state.dataset_key) if ctx.dataset_instrument else None
        market = market_for_instrument(instrument)
        timeframe = state.timeframe if state.timeframe in LIVE_TIMEFRAMES else LIVE_TIMEFRAMES[0]
        note = "" if market else f" {state.dataset_key} has no live market. {UNSUPPORTED_MESSAGE}"
        return (replace(state, live=LiveState(market, DEFAULT_SOURCE, timeframe, streaming=False)),
                LogEntry("info", f"Live mode: choose market, source and timeframe, then Go Live.{note}"))
    # go_live (also used to switch market or source while streaming)
    if state.live is None:
        return _reject(state, "enter Live mode before Go Live.")
    market, source, timeframe = data["market"], data["source"], data["timeframe"]
    if market not in MARKETS:
        return _reject(state, f"{market} is not a live market. {UNSUPPORTED_MESSAGE}")
    if source not in SOURCES:
        return _reject(state, f"{source} is not a live source (sources: {', '.join(SOURCES.values())}).")
    if timeframe not in LIVE_TIMEFRAMES:
        return _reject(state, f"{timeframe} is not a live timeframe (live: {', '.join(LIVE_TIMEFRAMES)}).")
    new = LiveState(market, source, timeframe, streaming=True)
    if new == state.live:
        return state, LogEntry("debug", "Live source unchanged.")
    verb = "switched to" if state.live.streaming else "Go Live:"
    return (replace(state, live=new),
            LogEntry("info", f"Live {verb} {SOURCES[source]} {new.symbol} {timeframe} (read-only market data)."))


def _utc(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _apply_replay(state: TerminalState, event: FrontendEvent, ctx: TerminalContext) -> tuple[TerminalState, LogEntry]:
    kind, data, current = event.type, event.data, state.replay
    if kind == "enter_replay" and current is not None:
        return _reject(state, "Replay is already active; use jump or set start.")
    if kind not in ("enter_replay",) and current is None:
        return _reject(state, f"{kind} requires Replay mode.")
    if kind == "exit_replay":
        return replace(state, replay=None), LogEntry("info", "Replay ended; full historical view restored.")
    times = ctx.bar_times
    if times is None or len(times) == 0:
        return _reject(state, "no bars are available to replay.")
    try:
        if kind in ("enter_replay", "set_replay_start"):
            speed = current.speed if current else replay_model.DEFAULT_SPEED
            new = replay_model.start(times, dataset_key=state.dataset_key, timeframe=state.timeframe,
                                     requested=replay_model.parse_utc(data["start"]), speed=speed)
            verb = "started" if kind == "enter_replay" else "restarted"
            return (replace(state, replay=new),
                    LogEntry("info", f"Replay {verb} on {state.dataset_key} {state.timeframe} at bar {_utc(new.cursor_timestamp)} "
                                     f"(bar at or before {data['start']} UTC)."))
        if kind == "jump_replay":
            new = replay_model.jump(current, times, replay_model.parse_utc(data["to"]))
            return replace(state, replay=new), LogEntry("info", f"Replay jumped to {_utc(new.cursor_timestamp)}.")
        if kind in ("step_forward", "step_backward"):
            new = replay_model.step(current, times, 1 if kind == "step_forward" else -1)
            if kind == "step_backward":
                new = replace(new, playing=False)
            return replace(state, replay=new), LogEntry("debug", f"Replay {kind}: {_utc(new.cursor_timestamp)}.")
    except ReplayError as exc:
        if kind == "step_forward" and current is not None and current.playing:
            # Playing into the last bar stops playback rather than erroring on every tick.
            return replace(state, replay=replace(current, playing=False)), LogEntry("info", f"Replay paused: {exc}")
        return _reject(state, str(exc))
    if kind == "play_replay":
        if replay_model.info(current, times)["at_end"]:
            return _reject(state, "Already at the last historical bar.")
        return replace(state, replay=replace(current, playing=True)), LogEntry("debug", "Replay playing.")
    if kind == "pause_replay":
        return replace(state, replay=replace(current, playing=False)), LogEntry("debug", "Replay paused.")
    if kind == "set_replay_speed":
        return (replace(state, replay=replace(current, speed=data["speed"])),
                LogEntry("debug", f"Replay speed {data['speed']}x."))
    if kind == "go_to_replay_latest":
        return state, LogEntry("debug", "Replay view moved to the latest revealed bar.")
    return _reject(state, f"unhandled replay event {kind!r}.")


def apply_event(state: TerminalState, event: FrontendEvent, ctx: TerminalContext) -> tuple[TerminalState, LogEntry]:
    """Apply one structurally valid event. Invalid requests leave state unchanged."""
    data = event.data
    kind = event.type

    if kind == "resync":
        return state, LogEntry("warning", "Frontend re-requested the chart data (a payload file could not be loaded).")
    if kind == "chart_ready":
        return state, LogEntry("info", "Custom frontend ready.")
    if kind == "frontend_error":
        return state, LogEntry("error", f"Frontend error: {data['message'][:500]}")

    if kind in LIVE_EVENTS:
        return _apply_live(state, event, ctx)
    if kind in REPLAY_EVENTS:
        if state.live is not None:
            return _reject(state, "exit Live before starting or using Replay.")
        return _apply_replay(state, event, ctx)
    if state.live is not None and not state.live.streaming and kind == "select_timeframe":
        return _reject(state, "choose the live timeframe in the Live bar, then Go Live.")
    if state.live is not None and kind == "select_timeframe":
        timeframe = event.data["timeframe"].strip().lower()
        if timeframe not in LIVE_TIMEFRAMES:
            return _reject(state, f"{timeframe} is not a live timeframe (live: {', '.join(LIVE_TIMEFRAMES)}).")
        return (replace(state, live=replace(state.live, timeframe=timeframe)),
                LogEntry("info", f"Live timeframe {timeframe} ({SOURCES[state.live.source]} native)."))
    if state.live is not None and kind in ("select_dataset", "select_watchlist_item", "set_date_range"):
        return _reject(state, "exit Live before changing the dataset or date range.")
    if state.replay is not None and kind in ("select_dataset", "select_watchlist_item", "select_timeframe",
                                             "set_date_range"):
        return _reject(state, "exit Replay before changing the dataset, timeframe or date range.")

    if kind in ("select_dataset", "select_watchlist_item"):
        key = data["dataset_key"]
        if not ctx.dataset_exists(key):
            return _reject(state, f"unknown dataset {key!r}.")
        # A dataset key names one native timeframe; selecting it selects that timeframe.
        timeframe = ctx.native_timeframe(key)
        new = replace(state, dataset_key=key, timeframe=timeframe, date_range=None)
        return new, LogEntry("info", f"Dataset {key} selected at native {timeframe}; date range reset to default.")

    if kind == "select_timeframe":
        timeframe = data["timeframe"].strip().lower()
        available = ctx.available_timeframes(state.dataset_key)
        if timeframe not in available:
            return _reject(state, f"{timeframe} is not available for {state.dataset_key} "
                                  f"(available: {', '.join(available)}).")
        return replace(state, timeframe=timeframe), LogEntry("info", f"Timeframe {timeframe} selected.")

    if kind == "set_date_range":
        if data["start"] is None and data["end"] is None:
            return replace(state, date_range=None), LogEntry("info", "Date range reset to default window.")
        if data["start"] is None or data["end"] is None:
            return _reject(state, "date range needs both start and end, or neither.")
        start, end = date.fromisoformat(data["start"]), date.fromisoformat(data["end"])
        if start > end:
            return _reject(state, "start date is after end date.")
        if ctx.data_bounds is not None:
            low, high = ctx.data_bounds
            if start > high or end < low:
                return _reject(state, f"range {start}..{end} is outside available data {low}..{high}.")
        estimated = ((end - start).days + 1) * 86_400 // ctx.timeframe_seconds(state.timeframe)
        if estimated > MAX_BARS:
            return _reject(state, f"range {start}..{end} is about {estimated:,} {state.timeframe} bars; "
                                  f"the chart limit is {MAX_BARS:,}. Choose a shorter range or higher timeframe.")
        return replace(state, date_range=(start, end)), LogEntry("info", f"Date range set to {start}..{end} (UTC).")

    if kind == "add_indicator":
        key = data["key"]
        if key not in CHARTABLE_INDICATORS:
            return _reject(state, f"unknown indicator {key!r}.")
        if len(state.indicators) >= MAX_INDICATORS:
            return _reject(state, f"at most {MAX_INDICATORS} indicators may be active.")
        try:
            params = validate_indicator_params(key, data.get("params"))
        except ValueError as exc:
            return _reject(state, str(exc))
        instance = IndicatorInstance(
            id=f"{key}-{state.next_indicator}", key=key, params=params, enabled=True,
            color=INDICATOR_COLORS[(state.next_indicator - 1) % len(INDICATOR_COLORS)],
        )
        new = replace(state, indicators=state.indicators + (instance,), next_indicator=state.next_indicator + 1)
        return new, LogEntry("info", f"Added {INDICATORS[key].display_name} ({instance.id}).")

    if kind in ("update_indicator", "toggle_indicator", "remove_indicator"):
        current = _find(state, data["id"])
        if current is None:
            return _reject(state, f"no active indicator {data['id']!r}.")
        if kind == "remove_indicator":
            new = replace(state, indicators=tuple(item for item in state.indicators if item.id != current.id))
            return new, LogEntry("info", f"Removed {current.id}.")
        if kind == "toggle_indicator":
            new = _replace_indicator(state, replace(current, enabled=data["enabled"]))
            return new, LogEntry("info", f"{current.id} {'enabled' if data['enabled'] else 'hidden'}.")
        try:
            params = validate_indicator_params(current.key, {**current.params, **data["params"]})
        except ValueError as exc:
            return _reject(state, str(exc))
        return _replace_indicator(state, replace(current, params=params)), LogEntry("info", f"Updated {current.id}: {params}.")

    if kind == "set_bottom_panel":
        new = replace(state, bottom_panel=data["panel"], bottom_open=data.get("open", True))
        return new, LogEntry("debug", f"Bottom panel: {data['panel']}{'' if new.bottom_open else ' (collapsed)'}.")

    if kind == "set_chart_setting":
        return replace(state, show_volume=data["show_volume"]), LogEntry("info", f"Volume {'shown' if data['show_volume'] else 'hidden'}.")

    return _reject(state, f"unhandled event type {kind!r}.")
