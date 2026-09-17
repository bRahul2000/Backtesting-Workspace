from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


OHLCV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]
NUMERIC_COLUMNS = ["open", "high", "low", "close", "volume"]


class DataValidationError(ValueError):
    """Raised when input cannot be represented as an OHLCV dataset."""


@dataclass(frozen=True)
class PreparationStats:
    source_rows: int
    invalid_timestamps_removed: int
    duplicates_removed: int


@dataclass(frozen=True)
class DataQualityReport:
    total_candles: int
    first_candle: Optional[pd.Timestamp]
    last_candle: Optional[pd.Timestamp]
    detected_timeframe_minutes: Optional[float]
    is_expected_timeframe: bool
    missing_candles: int
    invalid_ohlcv_rows: int
    expected_candles: int = 0
    duplicate_timestamps: int = 0


@dataclass(frozen=True)
class ContinuousSegment:
    start: pd.Timestamp
    end: pd.Timestamp
    candles: int


@dataclass(frozen=True)
class MissingGap:
    start: pd.Timestamp
    end: pd.Timestamp
    missing_candles: int


def normalize_columns(data: pd.DataFrame) -> pd.DataFrame:
    normalized = data.copy()
    normalized.columns = [
        str(column).strip().lower().replace(" ", "_") for column in normalized.columns
    ]
    aliases = {
        "time": "timestamp",
        "datetime": "timestamp",
        "date_time": "timestamp",
        "date": "timestamp",
        "timestamp_utc": "timestamp",
        "vol": "volume",
        "tick_volume": "volume",
    }
    return normalized.rename(columns=aliases)


def _parse_timestamp(values: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    non_null = values.notna().sum()
    if non_null and numeric.notna().sum() == non_null:
        median = float(numeric.dropna().abs().median())
        if median >= 1e17:
            unit = "ns"
        elif median >= 1e14:
            unit = "us"
        elif median >= 1e11:
            unit = "ms"
        else:
            unit = "s"
        return pd.to_datetime(numeric, unit=unit, errors="coerce", utc=True)
    return pd.to_datetime(values, errors="coerce", utc=True, format="mixed")


def prepare_ohlcv(data: pd.DataFrame) -> tuple[pd.DataFrame, PreparationStats]:
    if not isinstance(data, pd.DataFrame):
        raise DataValidationError("OHLCV input must be a table.")

    source_rows = len(data)
    normalized = normalize_columns(data)
    missing_columns = [column for column in OHLCV_COLUMNS if column not in normalized.columns]
    if missing_columns:
        raise DataValidationError(
            "Missing required column(s): " + ", ".join(missing_columns)
        )

    prepared = normalized[OHLCV_COLUMNS].copy()
    prepared["timestamp"] = _parse_timestamp(prepared["timestamp"])
    invalid_timestamps = int(prepared["timestamp"].isna().sum())
    prepared = prepared.dropna(subset=["timestamp"])

    for column in NUMERIC_COLUMNS:
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")

    prepared = prepared.sort_values("timestamp", kind="stable")
    before_deduplication = len(prepared)
    prepared = prepared.drop_duplicates(subset=["timestamp"], keep="last")
    duplicates_removed = before_deduplication - len(prepared)
    prepared = prepared.reset_index(drop=True)

    return prepared, PreparationStats(
        source_rows=source_rows,
        invalid_timestamps_removed=invalid_timestamps,
        duplicates_removed=duplicates_removed,
    )


def invalid_ohlcv_mask(data: pd.DataFrame) -> pd.Series:
    if data.empty:
        return pd.Series(False, index=data.index, dtype=bool)

    numeric = data[NUMERIC_COLUMNS]
    non_finite = numeric.isna() | ~np.isfinite(numeric)
    invalid = non_finite.any(axis=1)
    invalid |= (data[["open", "high", "low", "close"]] <= 0).any(axis=1)
    invalid |= data["volume"] < 0
    invalid |= data["high"] < data["low"]
    invalid |= data["high"] < data[["open", "close"]].max(axis=1)
    invalid |= data["low"] > data[["open", "close"]].min(axis=1)
    return invalid


def validate_ohlcv(
    data: pd.DataFrame,
    expected_step_seconds: int = 900,
) -> DataQualityReport:
    if data.empty:
        return DataQualityReport(0, None, None, None, False, 0, 0)

    first = data["timestamp"].min()
    last = data["timestamp"].max()
    differences = data["timestamp"].diff().dropna().dt.total_seconds()
    positive_differences = differences[differences > 0]
    detected_minutes = (
        float(positive_differences.mode().iloc[0] / 60)
        if not positive_differences.empty
        else None
    )
    is_expected = detected_minutes is not None and abs(
        detected_minutes - expected_step_seconds / 60
    ) < 0.01

    expected_index = pd.date_range(
        start=first,
        end=last,
        freq=pd.Timedelta(seconds=expected_step_seconds),
    )
    actual_index = pd.DatetimeIndex(data["timestamp"].drop_duplicates())
    missing_count = len(expected_index.difference(actual_index))

    return DataQualityReport(
        total_candles=len(data),
        first_candle=first,
        last_candle=last,
        detected_timeframe_minutes=detected_minutes,
        is_expected_timeframe=is_expected,
        missing_candles=missing_count,
        invalid_ohlcv_rows=int(invalid_ohlcv_mask(data).sum()),
        expected_candles=len(expected_index),
        duplicate_timestamps=int(data["timestamp"].duplicated().sum()),
    )


def continuous_segments(
    data: pd.DataFrame, step_seconds: int = 900,
) -> list[ContinuousSegment]:
    """Partition sorted unique UTC candles at every missing timestamp."""
    if data.empty:
        return []
    times = pd.DatetimeIndex(pd.to_datetime(data["timestamp"], utc=True)).unique().sort_values()
    step = pd.Timedelta(seconds=step_seconds)
    cuts = [0] + [i for i in range(1, len(times)) if times[i] - times[i - 1] != step]
    ends = cuts[1:] + [len(times)]
    return [ContinuousSegment(times[first], times[last - 1], last - first)
            for first, last in zip(cuts, ends)]


def missing_gaps(
    data: pd.DataFrame, step_seconds: int = 900,
) -> list[MissingGap]:
    segments = continuous_segments(data, step_seconds)
    step = pd.Timedelta(seconds=step_seconds)
    return [MissingGap(left.end + step, right.start - step,
                       int((right.start - left.end) / step) - 1)
            for left, right in zip(segments, segments[1:])]


def largest_continuous_segment(
    data: pd.DataFrame, step_seconds: int = 900,
) -> tuple[pd.DataFrame, ContinuousSegment | None]:
    segments = continuous_segments(data, step_seconds)
    if not segments:
        return data.iloc[0:0].copy(), None
    largest = max(segments, key=lambda item: item.candles)
    timestamps = pd.to_datetime(data["timestamp"], utc=True)
    return data.loc[timestamps.between(largest.start, largest.end)].reset_index(drop=True), largest


def format_timeframe(minutes: Optional[float]) -> str:
    if minutes is None:
        return "Unknown"
    if abs(minutes - round(minutes)) < 0.01:
        return f"{int(round(minutes))} Minutes"
    return f"{minutes:.2f} Minutes"


def merge_ohlcv(*datasets: pd.DataFrame) -> pd.DataFrame:
    non_empty = [data for data in datasets if data is not None and not data.empty]
    if not non_empty:
        return pd.DataFrame(columns=OHLCV_COLUMNS)
    merged, _ = prepare_ohlcv(pd.concat(non_empty, ignore_index=True))
    return merged


def find_missing_ranges(
    existing: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    step_seconds: int = 900,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Return contiguous timestamp ranges absent from the local dataset."""
    step = pd.Timedelta(seconds=step_seconds)
    expected = pd.date_range(start=start, end=end, freq=step)
    if existing.empty:
        missing = expected
    else:
        actual = pd.DatetimeIndex(existing["timestamp"].drop_duplicates())
        missing = expected.difference(actual)

    if missing.empty:
        return []

    ranges: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    range_start = missing[0]
    previous = missing[0]
    for timestamp in missing[1:]:
        if timestamp - previous != step:
            ranges.append((range_start, previous))
            range_start = timestamp
        previous = timestamp
    ranges.append((range_start, previous))
    return ranges


def load_ohlcv_csv(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    prepared, _ = prepare_ohlcv(raw)
    return prepared


def save_ohlcv_csv(data: pd.DataFrame, path: Path) -> None:
    """Atomically save the canonical OHLCV columns without changing timestamps."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    output = data[OHLCV_COLUMNS].copy()
    output["timestamp"] = output["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    output.to_csv(temporary_path, index=False)
    os.replace(temporary_path, path)
