"""Read-only Exness MT5 live market data for TradingView Mode.

Transport: the MQL5 service ``ui/tradingview_mode/mt5_bridge/TradingViewLiveFeed.mq5``
writes files into MetaTrader's Common/Files folder (the same file bridge the
Stage 3 tooling reads). This module only *reads* those files. It has no way to
place, modify or cancel an order, and it never substitutes another data source:
without a valid MT5 file the state is DISCONNECTED / ERROR, not "some price".

Files, per live symbol:
  tv_live_<SYMBOL>_quote.json      rewritten every ~500 ms (tick, spread, clock, last bars)
  tv_live_<SYMBOL>_<TF>_seed.csv   last 500 broker bars, rewritten when a bar opens

Times: MT5 bar/tick times are broker server time. Exness runs UTC+0 (the
validated M15 dataset and the Stage 3 EA both check this); a feed whose
server clock is not UTC+0 is an ERROR, never silently shifted.
"""
from __future__ import annotations

from dataclasses import dataclass
import io
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

#: Live symbols and their registry identity (instrument, provider, symbol).
LIVE_SYMBOLS: dict[str, dict[str, str]] = {
    "BTCUSDm": {"instrument": "BTCUSD", "provider": "Exness Technologies Ltd", "dataset_key": "EXNESS_BTCUSDM_M15"},
    "XAUUSDm": {"instrument": "XAUUSDm", "provider": "Exness Technologies Ltd", "dataset_key": "EXNESS_XAUUSDM_M15"},
}
#: Broker-native MT5 periods only (no derivation in Phase 1).
LIVE_TIMEFRAMES: dict[str, tuple[str, int]] = {"15m": ("M15", 900), "30m": ("M30", 1800), "1h": ("H1", 3600)}
SEED_BARS = 500
HEARTBEAT_STALE_S = 5.0        # the service writes every ~0.5 s
HEARTBEAT_DISCONNECTED_S = 60.0
TICK_STALE_S = 60.0            # no tick for a minute: not LIVE (market closed or feed stalled)
MAX_FUTURE_SKEW_S = 5.0
STATUSES = ("DISCONNECTED", "CONNECTING", "LIVE", "STALE", "ERROR")
DEFAULT_COMMON_FILES = (Path.home() / "Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/users/user"
                        "/AppData/Roaming/MetaQuotes/Terminal/Common/Files")
_BAR_COLUMNS = ("time", "open", "high", "low", "close", "tick_volume", "spread")


class LiveFeedError(ValueError):
    """A feed file that cannot be trusted as written."""


@dataclass(frozen=True)
class LiveState:
    """Live mode. ``streaming`` is False while the user is still choosing the
    symbol/timeframe (setup); nothing is read from MT5 until Go Live."""

    symbol: str | None
    timeframe: str
    streaming: bool = False


UNSUPPORTED_MESSAGE = "Live mode supports Exness BTCUSDm and XAUUSDm only."


@dataclass(frozen=True)
class Snapshot:
    writer_id: str
    seq: int
    symbol: str
    written_utc: float          # heartbeat (seconds)
    server_offset_s: int        # server time - GMT, as reported by the terminal
    connected: bool
    digits: int
    point: float
    tick_time_ms: int
    bid: float
    ask: float
    spread_points: int
    bars: dict[str, pd.DataFrame]  # MT5 period -> newest bars (oldest first)


def common_files_dir() -> Path:
    return Path(os.environ.get("TV_MT5_COMMON_FILES") or DEFAULT_COMMON_FILES)


def quote_path(folder: Path, symbol: str) -> Path:
    return folder / f"tv_live_{symbol}_quote.json"


def seed_path(folder: Path, symbol: str, timeframe: str) -> Path:
    return folder / f"tv_live_{symbol}_{LIVE_TIMEFRAMES[timeframe][0]}_seed.csv"


# ---------------------------------------------------------------------------
# Parsing / validation
# ---------------------------------------------------------------------------

def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise LiveFeedError(f"{name} must be a finite number.")
    return float(value)


def validate_bars(frame: pd.DataFrame, bar_seconds: int, where: str) -> pd.DataFrame:
    """UTC, aligned, strictly increasing, sane OHLC. Returns a new frame."""
    if frame.empty:
        return frame
    times = frame["time"].to_numpy(dtype=np.int64)
    if np.any(times % bar_seconds):
        raise LiveFeedError(f"{where}: bar time not aligned to the timeframe.")
    if np.any(np.diff(times) <= 0):
        raise LiveFeedError(f"{where}: bar times must be strictly increasing without duplicates.")
    prices = frame[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.all(np.isfinite(prices)) or np.any(prices <= 0):
        raise LiveFeedError(f"{where}: prices must be finite and positive.")
    if np.any(frame["high"] < frame[["open", "close"]].max(axis=1)) or np.any(frame["low"] > frame[["open", "close"]].min(axis=1)):
        raise LiveFeedError(f"{where}: high/low inconsistent with open/close.")
    out = frame.copy()
    out["timestamp"] = pd.to_datetime(out["time"], unit="s", utc=True)
    return out


def _bars_from_rows(rows: Any, bar_seconds: int, where: str) -> pd.DataFrame:
    if not isinstance(rows, list) or not all(isinstance(r, list) and len(r) == len(_BAR_COLUMNS) for r in rows):
        raise LiveFeedError(f"{where}: bars must be [time, open, high, low, close, tick_volume, spread] rows.")
    frame = pd.DataFrame(rows, columns=_BAR_COLUMNS)
    for column in _BAR_COLUMNS:
        frame[column] = [_finite(v, f"{where}.{column}") for v in frame[column]]
    frame["time"] = frame["time"].astype(np.int64)
    return validate_bars(frame, bar_seconds, where)


def parse_quote(text: str, symbol: str) -> Snapshot:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise LiveFeedError(f"quote file is not valid JSON ({exc.msg}).") from exc
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise LiveFeedError("quote file has an unsupported schema.")
    if data.get("symbol") != symbol:
        raise LiveFeedError(f"quote file is for {data.get('symbol')!r}, expected {symbol!r}.")
    tick = data.get("tick") or {}
    bid, ask = _finite(tick.get("bid"), "bid"), _finite(tick.get("ask"), "ask")
    if bid <= 0 or ask < bid:
        raise LiveFeedError("bid/ask are not a valid quote (ask below bid or non-positive).")
    digits = data.get("digits")
    if type(digits) is not int or not 0 <= digits <= 8:
        raise LiveFeedError("digits must be an integer 0..8.")
    tick_time_ms = tick.get("time_msc")
    if type(tick_time_ms) is not int or tick_time_ms <= 0:
        raise LiveFeedError("tick.time_msc must be epoch milliseconds.")
    bars = {}
    for timeframe, (period, seconds) in LIVE_TIMEFRAMES.items():
        bars[period] = _bars_from_rows((data.get("bars") or {}).get(period, []), seconds, f"{symbol} {period}")
    return Snapshot(
        writer_id=str(data.get("writer_id", "")), seq=int(_finite(data.get("seq"), "seq")), symbol=symbol,
        written_utc=_finite(data.get("written_gmt"), "written_gmt"),
        server_offset_s=int(_finite(data.get("server_time"), "server_time") - _finite(data.get("gmt_time"), "gmt_time")),
        connected=bool(data.get("connected")), digits=digits, point=_finite(data.get("point"), "point"),
        tick_time_ms=tick_time_ms, bid=bid, ask=ask, spread_points=int(_finite(data.get("spread_points"), "spread_points")),
        bars=bars,
    )


def parse_seed(text: str, timeframe: str) -> pd.DataFrame:
    try:
        frame = pd.read_csv(io.StringIO(text))
    except (ValueError, pd.errors.ParserError) as exc:
        raise LiveFeedError(f"seed file is not valid CSV ({exc}).") from exc
    if list(frame.columns) != list(_BAR_COLUMNS):
        raise LiveFeedError(f"seed columns must be {list(_BAR_COLUMNS)}.")
    frame["time"] = frame["time"].astype(np.int64)
    return validate_bars(frame, LIVE_TIMEFRAMES[timeframe][1], f"seed {timeframe}")


# ---------------------------------------------------------------------------
# Session book: duplicate / out-of-order handling and in-memory bar merge
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Book:
    """In-memory live bars for one symbol/timeframe (never written anywhere)."""

    symbol: str
    timeframe: str
    bars: pd.DataFrame
    writer_id: str = ""
    last_seq: int = -1
    last_tick_ms: int = 0
    snapshot: Snapshot | None = None
    rejected: int = 0


def empty_book(symbol: str, timeframe: str) -> Book:
    return Book(symbol, timeframe, pd.DataFrame(columns=[*_BAR_COLUMNS, "timestamp"]))


def classify(book: Book, snapshot: Snapshot) -> str:
    """accept | duplicate | out_of_order. A restarted service (new writer_id) starts a new sequence."""
    if snapshot.writer_id != book.writer_id or book.snapshot is None:
        return "accept"
    if snapshot.seq == book.last_seq:
        return "duplicate"
    if snapshot.seq < book.last_seq or snapshot.tick_time_ms < book.last_tick_ms:
        return "out_of_order"
    return "accept"


def merge_bars(*frames: pd.DataFrame, limit: int = SEED_BARS) -> pd.DataFrame:
    """Merge bar frames keyed by bar time; later frames win (newest data)."""
    usable = [frame for frame in frames if frame is not None and not frame.empty]
    if not usable:
        return pd.DataFrame(columns=[*_BAR_COLUMNS, "timestamp"])
    combined = pd.concat(usable, ignore_index=True)
    combined = combined.drop_duplicates("time", keep="last").sort_values("time", kind="stable")
    return combined.tail(limit).reset_index(drop=True)


def apply_snapshot(book: Book, snapshot: Snapshot, seed: pd.DataFrame | None) -> tuple[Book, str]:
    verdict = classify(book, snapshot)
    if verdict == "duplicate":
        return book, verdict
    if verdict == "out_of_order":
        return Book(**{**book.__dict__, "rejected": book.rejected + 1}), verdict
    period = LIVE_TIMEFRAMES[book.timeframe][0]
    bars = merge_bars(book.bars, seed if seed is not None else None, snapshot.bars[period])
    return Book(book.symbol, book.timeframe, bars, snapshot.writer_id, snapshot.seq, snapshot.tick_time_ms,
                snapshot, book.rejected), verdict


# ---------------------------------------------------------------------------
# Connection status
# ---------------------------------------------------------------------------

def _age(seconds: float) -> str:
    if seconds < 90:
        return f"{seconds:.0f}s"
    if seconds < 5400:
        return f"{seconds / 60:.0f}m"
    if seconds < 172800:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def connection_status(*, file_found: bool, snapshot: Snapshot | None, error: str | None, has_bars: bool,
                      now: float) -> tuple[str, str]:
    """(status, reason). LIVE only when the service is writing, the terminal is
    connected to the broker, the clock is UTC+0, history is present and ticks
    are recent."""
    if not file_found:
        return "DISCONNECTED", "MT5 live feed not found — is MetaTrader running with the TradingView Live Feed service?"
    if error:
        return "ERROR", error
    if snapshot is None:
        return "CONNECTING", "Waiting for the first MT5 quote."
    heartbeat_age = now - snapshot.written_utc
    if heartbeat_age < -MAX_FUTURE_SKEW_S:
        return "ERROR", "Feed heartbeat is in the future; check the terminal clock."
    if heartbeat_age > HEARTBEAT_DISCONNECTED_S:
        return "DISCONNECTED", f"MT5 feed stopped {_age(heartbeat_age)} ago (MetaTrader closed or service stopped)."
    if heartbeat_age > HEARTBEAT_STALE_S:
        return "STALE", f"MT5 feed not updated for {_age(heartbeat_age)}."
    if abs(snapshot.server_offset_s) >= 1800:
        return "ERROR", f"Broker server clock is UTC{snapshot.server_offset_s / 3600:+.1f}h; Exness live data requires UTC+0."
    if not snapshot.connected:
        return "CONNECTING", "MetaTrader is running but not connected to the Exness server."
    if not has_bars:
        return "CONNECTING", "Waiting for MT5 bar history."
    tick_age = now - snapshot.tick_time_ms / 1000
    if tick_age > TICK_STALE_S:
        return "STALE", f"No ticks for {_age(tick_age)} (market closed or feed paused)."
    return "LIVE", "Receiving Exness MT5 quotes."


def forming_bar_time(bars: pd.DataFrame, bar_seconds: int, tick_time_ms: int | None) -> int | None:
    """The newest bar is still forming while the latest tick is inside it."""
    if bars.empty or tick_time_ms is None:
        return None
    last = int(bars["time"].iloc[-1])
    return last if last <= tick_time_ms / 1000 < last + bar_seconds else None


def quote_payload(snapshot: Snapshot | None) -> dict[str, Any]:
    """Broker-native quote fields, exactly as written by MT5."""
    if snapshot is None:
        return {"bid": None, "ask": None, "spread": None, "spread_points": None, "digits": None, "point": None,
                "tick_time_ms": None}
    return {"bid": snapshot.bid, "ask": snapshot.ask,
            # Same-tick ask - bid, rounded to the symbol's digits (no other source).
            "spread": round(snapshot.ask - snapshot.bid, snapshot.digits),
            "spread_points": snapshot.spread_points, "digits": snapshot.digits, "point": snapshot.point,
            "tick_time_ms": snapshot.tick_time_ms}


# ---------------------------------------------------------------------------
# File reader (read-only)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FeedRead:
    file_found: bool
    snapshot: Snapshot | None
    seed: pd.DataFrame | None
    error: str | None


def read_feed(folder: Path, symbol: str, timeframe: str) -> FeedRead:
    """Read (never write) the service's files for one symbol/timeframe."""
    quote = quote_path(folder, symbol)
    if not quote.exists():
        return FeedRead(False, None, None, None)
    try:
        snapshot = parse_quote(quote.read_text(encoding="utf-8"), symbol)
    except (OSError, LiveFeedError) as exc:
        return FeedRead(True, None, None, f"Unreadable MT5 quote: {exc}")
    seed_file = seed_path(folder, symbol, timeframe)
    seed = None
    if seed_file.exists():
        try:
            seed = parse_seed(seed_file.read_text(encoding="utf-8"), timeframe)
        except (OSError, LiveFeedError) as exc:
            return FeedRead(True, snapshot, None, f"Unreadable MT5 bar history: {exc}")
    return FeedRead(True, snapshot, seed, None)
