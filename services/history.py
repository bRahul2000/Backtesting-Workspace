"""Resumable canonical Bitstamp BTC/USD 15-minute history synchronization."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd

from services.bitstamp import BITSTAMP_MAX_CANDLES, BITSTAMP_STEP_SECONDS, BitstampClient, latest_complete_candle_open
from utils.data_validation import (
    DataValidationError, find_missing_ranges, load_ohlcv_csv, merge_ohlcv,
    save_ohlcv_csv, validate_ohlcv,
)


CANONICAL_DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "btcusd_15m.csv"
Progress = Callable[[int, int, int], None]


@dataclass(frozen=True)
class HistorySyncResult:
    requested_chunks: int
    completed_chunks: int
    received_rows: int
    saved_candles: int
    remaining_candles: int


def _utc(value: pd.Timestamp) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def sync_btc_history(
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    path: Path = CANONICAL_DATA_FILE,
    client: BitstampClient | None = None,
    progress: Progress | None = None,
) -> HistorySyncResult:
    """Fetch only absent candles and atomically checkpoint every API chunk.

    Repeating this call after an interruption recomputes missing timestamps
    from the saved CSV. Empty API responses remain gaps rather than candles.
    """
    step = pd.Timedelta(seconds=BITSTAMP_STEP_SECONDS)
    start = _utc(start).ceil(step)
    end = min(_utc(end).floor(step), latest_complete_candle_open())
    if start > end:
        return HistorySyncResult(0, 0, 0, 0, 0)
    existing = load_ohlcv_csv(path) if path.exists() else pd.DataFrame()
    if not existing.empty and validate_ohlcv(existing).invalid_ohlcv_rows:
        raise DataValidationError("The saved BTC history has invalid OHLCV rows.")
    missing = find_missing_ranges(existing, start, end, BITSTAMP_STEP_SECONDS)
    chunks: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for gap_start, gap_end in missing:
        cursor = gap_start
        while cursor <= gap_end:
            finish = min(cursor + (BITSTAMP_MAX_CANDLES - 1) * step, gap_end)
            chunks.append((cursor, finish))
            cursor = finish + step
    api = client or BitstampClient()
    received = 0
    for completed, (chunk_start, chunk_end) in enumerate(chunks, 1):
        part = api.download_ohlc(chunk_start, chunk_end)
        if not part.empty:
            merged = merge_ohlcv(existing, part)
            if validate_ohlcv(merged).invalid_ohlcv_rows:
                raise DataValidationError("Bitstamp returned invalid OHLCV rows; previous checkpoint retained.")
            save_ohlcv_csv(merged, path)
            existing = merged
        received += len(part)
        if progress is not None:
            progress(completed, len(chunks), len(existing))
    remaining = find_missing_ranges(existing, start, end, BITSTAMP_STEP_SECONDS)
    remaining_count = sum(int((finish - begin) / step) + 1 for begin, finish in remaining)
    return HistorySyncResult(len(chunks), len(chunks), received, len(existing), remaining_count)
