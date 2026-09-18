from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pandas as pd

from utils.data_validation import (DataQualityReport, continuous_segments,
                                   invalid_ohlcv_mask, normalize_columns,
                                   prepare_ohlcv, save_ohlcv_csv, validate_ohlcv)


TIMEFRAME_MINUTES = {"M15": 15, "H1": 60}


@dataclass(frozen=True)
class GoldDatasetMetadata:
    instrument: str
    symbol: str
    timeframe: str
    source: str
    source_file_sha256: str
    dataset_sha256: str
    first_timestamp_utc: str
    last_timestamp_utc: str
    candles: int
    invalid_rows_removed: int
    duplicates_removed: int
    incomplete_bars_removed: int
    missing_candles: int
    continuous_segments: int
    captured_at_utc: str


def _timestamps(values: pd.Series, source_timezone: str | None) -> pd.Series:
    parsed = pd.to_datetime(values, errors="coerce", format="mixed")
    if parsed.dt.tz is None:
        if not source_timezone:
            raise ValueError("Naive timestamps require source_timezone; do not guess UTC.")
        parsed = parsed.dt.tz_localize(source_timezone)
    return parsed.dt.tz_convert("UTC")


def import_gold_ohlcv_csv(
    source: str | Path, output: str | Path, *, timeframe: str,
    source_timezone: str | None = None, as_of: pd.Timestamp | None = None,
    source_label: str = "MT5 exported CSV; broker identity unverified",
) -> GoldDatasetMetadata:
    """Canonicalize broker-exported Gold OHLCV without mislabeling its source."""
    if timeframe not in TIMEFRAME_MINUTES:
        raise ValueError("timeframe must be M15 or H1")
    source = Path(source)
    raw = normalize_columns(pd.read_csv(source))
    if "timestamp" not in raw:
        raise ValueError("Gold CSV requires a timestamp/date/time column.")
    raw["timestamp"] = _timestamps(raw["timestamp"], source_timezone)
    prepared, stats = prepare_ohlcv(raw)
    invalid = invalid_ohlcv_mask(prepared)
    invalid_removed = int(invalid.sum())
    prepared = prepared.loc[~invalid].reset_index(drop=True)
    if as_of is None:
        as_of = pd.Timestamp.now(tz="UTC")
    as_of = pd.Timestamp(as_of)
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware.")
    cutoff = as_of.tz_convert("UTC") - pd.Timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
    before = len(prepared)
    prepared = prepared.loc[prepared.timestamp <= cutoff].reset_index(drop=True)
    incomplete_removed = before - len(prepared)
    quality: DataQualityReport = validate_ohlcv(
        prepared, expected_step_seconds=TIMEFRAME_MINUTES[timeframe] * 60)
    if not quality.is_expected_timeframe:
        raise ValueError(f"Expected {timeframe} candles; detected {quality.detected_timeframe_minutes} minutes.")
    if prepared.empty:
        raise ValueError("Gold dataset is empty after validation and incomplete-bar exclusion.")
    save_ohlcv_csv(prepared, Path(output))
    digest = sha256(Path(output).read_bytes()).hexdigest()
    metadata = GoldDatasetMetadata(
        instrument="XAUUSD", symbol="XAUUSDm", timeframe=timeframe, source=source_label,
        source_file_sha256=sha256(source.read_bytes()).hexdigest(), dataset_sha256=digest,
        first_timestamp_utc=prepared.timestamp.iloc[0].isoformat(),
        last_timestamp_utc=prepared.timestamp.iloc[-1].isoformat(), candles=len(prepared),
        invalid_rows_removed=invalid_removed, duplicates_removed=stats.duplicates_removed,
        incomplete_bars_removed=incomplete_removed, missing_candles=quality.missing_candles,
        continuous_segments=len(continuous_segments(prepared, TIMEFRAME_MINUTES[timeframe] * 60)),
        captured_at_utc=datetime.now(timezone.utc).isoformat(),
    )
    Path(str(output) + ".metadata.json").write_text(
        json.dumps(asdict(metadata), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return metadata