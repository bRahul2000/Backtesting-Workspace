"""Historical bar replay: pure state and slicing.

Python owns the replay. The cursor is the open timestamp (UTC epoch seconds)
of the newest revealed bar; every bar after it is removed from the dataframe
*before* serialization, and indicators are calculated on the revealed slice
only, so nothing after the cursor can reach the frontend.

The revealed slice starts at a fixed context anchor (up to CONTEXT_BARS before
the replay start) and ends at the cursor. The anchor does not move while
stepping, so each step adds or removes exactly one bar and recursive
indicators (EMA, RSI, MACD, ATR) keep identical values for earlier bars.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re

import numpy as np
import pandas as pd

CONTEXT_BARS = 1_500
SPEEDS = (1, 2, 5, 10)
DEFAULT_SPEED = 1
_UTC_TEXT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?Z?$")


class ReplayError(ValueError):
    """A replay request that cannot be honoured exactly."""


@dataclass(frozen=True)
class ReplayState:
    dataset_key: str
    timeframe: str
    start_timestamp: int   # open time of the chosen replay start bar
    cursor_timestamp: int  # open time of the newest revealed bar
    anchor_timestamp: int  # open time of the first revealed (context) bar
    playing: bool = False
    speed: int = DEFAULT_SPEED


def is_utc_text(value: object) -> bool:
    return isinstance(value, str) and bool(_UTC_TEXT.match(value))


def parse_utc(value: str) -> int:
    """'YYYY-MM-DDTHH:MM[:SS][Z]' interpreted as UTC -> epoch seconds."""
    if not is_utc_text(value):
        raise ReplayError(f"Replay time must be UTC 'YYYY-MM-DDTHH:MM', got {value!r}.")
    return int(pd.Timestamp(value.rstrip("Z"), tz="UTC").timestamp())


def frame_times(frame: pd.DataFrame) -> np.ndarray:
    utc = frame["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None)
    return utc.to_numpy(dtype="datetime64[s]").astype(np.int64)


def align(times: np.ndarray, requested: int) -> int:
    """Index of the bar opening at or before ``requested`` (deterministic rule)."""
    if len(times) == 0:
        raise ReplayError("The selected dataset has no bars to replay.")
    index = int(np.searchsorted(times, requested, side="right")) - 1
    if index < 0:
        first = pd.Timestamp(int(times[0]), unit="s", tz="UTC")
        raise ReplayError(f"Replay start is before the first bar ({first:%Y-%m-%d %H:%M} UTC).")
    return index


def index_of(times: np.ndarray, timestamp: int) -> int:
    index = int(np.searchsorted(times, timestamp, side="left"))
    if index >= len(times) or int(times[index]) != timestamp:
        raise ReplayError("Replay cursor is no longer a bar of this dataset; restart replay.")
    return index


def start(times: np.ndarray, *, dataset_key: str, timeframe: str, requested: int,
          speed: int = DEFAULT_SPEED) -> ReplayState:
    index = align(times, requested)
    anchor = max(0, index - CONTEXT_BARS)
    return ReplayState(dataset_key, timeframe, int(times[index]), int(times[index]), int(times[anchor]),
                       playing=False, speed=speed)


def jump(state: ReplayState, times: np.ndarray, requested: int) -> ReplayState:
    """Move the cursor to the bar at/before ``requested``; a jump before the
    start also moves the start. The anchor is re-based around the new cursor."""
    index = align(times, requested)
    start_ts = min(state.start_timestamp, int(times[index]))
    anchor = max(0, index - CONTEXT_BARS)
    return replace(state, cursor_timestamp=int(times[index]), start_timestamp=start_ts,
                   anchor_timestamp=int(times[anchor]), playing=False)


def step(state: ReplayState, times: np.ndarray, delta: int) -> ReplayState:
    """Reveal (+1) or hide (-1) exactly one bar, within [start, last bar]."""
    cursor = index_of(times, state.cursor_timestamp)
    lower = index_of(times, state.start_timestamp)
    target = cursor + delta
    if target < lower:
        raise ReplayError("Already at the replay start bar.")
    if target >= len(times):
        raise ReplayError("Already at the last historical bar.")
    return replace(state, cursor_timestamp=int(times[target]))


def info(state: ReplayState, times: np.ndarray) -> dict:
    """Status for the frontend. Contains no timestamp after the cursor."""
    cursor = index_of(times, state.cursor_timestamp)
    lower = index_of(times, state.start_timestamp)
    anchor = index_of(times, state.anchor_timestamp)
    return {
        "enabled": True, "dataset_key": state.dataset_key, "timeframe": state.timeframe,
        "start_timestamp": state.start_timestamp, "cursor_timestamp": state.cursor_timestamp,
        "cursor_index": cursor, "revealed_bar_count": cursor - anchor + 1,
        "total_available_bars": int(len(times)), "playing": state.playing and cursor < len(times) - 1,
        "speed": state.speed, "speeds": list(SPEEDS),
        "at_start": cursor <= lower, "at_end": cursor >= len(times) - 1,
    }


def revealed(frame: pd.DataFrame, state: ReplayState) -> pd.DataFrame:
    """Rows anchor..cursor only (a new frame; ``frame`` is not modified)."""
    times = frame_times(frame)
    anchor = index_of(times, state.anchor_timestamp)
    cursor = index_of(times, state.cursor_timestamp)
    return frame.iloc[anchor:cursor + 1].reset_index(drop=True)
