"""Read-only candle sources for the Setup A operator chart.

EXNESS_LIVE is intentionally unconnected until an MT5 bridge is installed.
No source silently falls back to another exchange or invents missing bars.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

import pandas as pd

from services.exness_m15 import PROCESSED
from services.history import CANONICAL_DATA_FILE
from utils.data_validation import load_ohlcv_csv


STEP = pd.Timedelta(minutes=15)
ROOT = Path(__file__).resolve().parents[1]


class ChartSource(str, Enum):
    EXNESS_HISTORY = "EXNESS_HISTORY"
    EXNESS_LIVE = "EXNESS_LIVE"
    BITSTAMP_REFERENCE = "BITSTAMP_REFERENCE"


@dataclass(frozen=True)
class FeedSnapshot:
    source: ChartSource
    candles: pd.DataFrame
    status: str
    is_live: bool = False
    last_bid: float | None = None
    last_ask: float | None = None
    spread: float | None = None
    spread_label: str = "SPREAD UNAVAILABLE"
    server_time: pd.Timestamp | None = None


class ChartFeedProvider(Protocol):
    def read(self, now: pd.Timestamp | None = None) -> FeedSnapshot: ...


def _utc(moment: pd.Timestamp | None) -> pd.Timestamp:
    stamp = pd.Timestamp.now(tz="UTC") if moment is None else pd.Timestamp(moment)
    if stamp.tzinfo is None:
        raise ValueError("Chart clock must be timezone aware UTC")
    return stamp.tz_convert("UTC")


def latest_completed(candles: pd.DataFrame, now: pd.Timestamp | None = None) -> pd.DataFrame:
    """Exclude the unfinished current M15 candle without filling any gap."""
    if candles.empty:
        return candles.copy()
    stamp = _utc(now)
    frame = candles.loc[candles.timestamp + STEP <= stamp].copy()
    return frame.reset_index(drop=True)


def latest_window(candles: pd.DataFrame, count: int) -> pd.DataFrame:
    if count not in (100, 200, 300, 500, 1000):
        raise ValueError("Unsupported chart window")
    return candles.tail(count).copy().reset_index(drop=True)


def freshness(snapshot: FeedSnapshot, now: pd.Timestamp | None = None) -> str:
    if snapshot.candles.empty:
        return "NOT CONNECTED" if snapshot.source is ChartSource.EXNESS_LIVE else "NO DATA"
    stamp = _utc(now)
    if snapshot.is_live:
        if snapshot.server_time is None:
            return "LIVE CLOCK UNAVAILABLE"
        age = stamp - _utc(snapshot.server_time)
        return "LIVE" if pd.Timedelta(0) <= age <= pd.Timedelta(seconds=20) else "STALE LIVE FEED"
    last = snapshot.candles.timestamp.iloc[-1]
    age = stamp - last
    return "HISTORICAL SNAPSHOT" if age <= pd.Timedelta(minutes=30) else "HISTORICAL · STALE"


def load_exness_history(path: Path = PROCESSED,
                        now: pd.Timestamp | None = None) -> FeedSnapshot:
    if not path.exists():
        return FeedSnapshot(ChartSource.EXNESS_HISTORY, pd.DataFrame(),
                            "EXNESS HISTORY — FILE MISSING")
    raw = pd.read_csv(path)
    required = {"timestamp_utc", "open", "high", "low", "close", "tick_volume"}
    if required - set(raw.columns):
        raise ValueError(f"Exness M15 file lacks {sorted(required - set(raw.columns))}")
    raw["timestamp"] = pd.to_datetime(raw.timestamp_utc, utc=True, errors="raise")
    if raw.timestamp.isna().any() or not raw.timestamp.is_monotonic_increasing or raw.timestamp.duplicated().any():
        raise ValueError("Exness M15 timestamps are missing, duplicated, or out of order")
    if (raw[["open", "high", "low", "close"]].le(0).any().any() or
        raw[["open", "high", "low", "close"]].isna().any().any()):
        raise ValueError("Exness M15 prices are invalid")
    frame = latest_completed(raw, now)
    if frame.empty:
        return FeedSnapshot(ChartSource.EXNESS_HISTORY, frame,
                            "EXNESS HISTORY — NO COMPLETED CANDLE")
    last = frame.iloc[-1]
    spread = float(last.spread_price) if "spread_price" in frame else None
    return FeedSnapshot(ChartSource.EXNESS_HISTORY, frame, "EXNESS HISTORY — READ ONLY",
                        last_bid=float(last.close), spread=spread,
                        spread_label="BAR MIN SPREAD" if spread is not None else "SPREAD UNAVAILABLE")


def load_bitstamp_reference(path: Path = CANONICAL_DATA_FILE,
                            now: pd.Timestamp | None = None) -> FeedSnapshot:
    if not path.exists():
        return FeedSnapshot(ChartSource.BITSTAMP_REFERENCE, pd.DataFrame(),
                            "REFERENCE FEED — FILE MISSING")
    frame = latest_completed(load_ohlcv_csv(path), now)
    return FeedSnapshot(ChartSource.BITSTAMP_REFERENCE, frame,
                        "REFERENCE FEED — NOT EXECUTION FEED",
                        last_bid=float(frame.close.iloc[-1]) if not frame.empty else None)


class UnconnectedMT5Feed:
    """Future MT5 transport slot. It never substitutes another feed."""

    def read(self, now: pd.Timestamp | None = None) -> FeedSnapshot:
        return FeedSnapshot(ChartSource.EXNESS_LIVE, pd.DataFrame(),
                            "EXNESS LIVE CONNECTION — NOT CONNECTED")


def load_chart_source(source: ChartSource, now: pd.Timestamp | None = None,
                      *, exness_path: Path = PROCESSED,
                      bitstamp_path: Path = CANONICAL_DATA_FILE,
                      live_provider: ChartFeedProvider | None = None) -> FeedSnapshot:
    if source is ChartSource.EXNESS_HISTORY:
        return load_exness_history(exness_path, now)
    if source is ChartSource.BITSTAMP_REFERENCE:
        return load_bitstamp_reference(bitstamp_path, now)
    if source is ChartSource.EXNESS_LIVE:
        return (live_provider or UnconnectedMT5Feed()).read(now)
    raise ValueError("Unsupported chart data source")
