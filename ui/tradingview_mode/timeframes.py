"""Native and safely derived timeframes for TradingView Mode."""
from __future__ import annotations

from dataclasses import dataclass
import re

import pandas as pd

from services.market_datasets import MarketDataset, datasets_for_instrument


_TIMEFRAME_RE = re.compile(r"^(\d+)([mhdw])$")
_KNOWN_TIMEFRAMES = ("1m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "1w")
_REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


class UnsupportedTimeframeError(ValueError):
    """Raised when a timeframe cannot be loaded or safely derived."""


@dataclass(frozen=True)
class TimeframeResolution:
    target: str
    target_seconds: int
    source: MarketDataset
    native: bool

    @property
    def source_label(self) -> str:
        return "Native" if self.native else f"Derived from {self.source.timeframe}"


def timeframe_seconds(label: str) -> int:
    match = _TIMEFRAME_RE.fullmatch(label.strip().lower())
    if match is None:
        raise UnsupportedTimeframeError(f"Unsupported timeframe label: {label!r}")
    amount, unit = int(match.group(1)), match.group(2)
    if amount <= 0:
        raise UnsupportedTimeframeError(f"Unsupported timeframe label: {label!r}")
    return amount * {"m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]


def _identity(entry: MarketDataset) -> tuple[str, str, str]:
    return entry.instrument, entry.broker, entry.symbol


def _same_identity(selected: MarketDataset, candidate: MarketDataset) -> bool:
    return _identity(selected) == _identity(candidate)


def _entries_for(selected: MarketDataset) -> tuple[MarketDataset, ...]:
    return tuple(
        entry for entry in datasets_for_instrument(selected.instrument)
        if _same_identity(selected, entry)
    )


def available_timeframes(selected: MarketDataset) -> tuple[str, ...]:
    """Return native and derivable canonical labels for one provider/instrument."""
    entries = _entries_for(selected)
    native_seconds = {timeframe_seconds(entry.timeframe) for entry in entries}
    available = set(entry.timeframe for entry in entries)
    for target in _KNOWN_TIMEFRAMES:
        target_seconds = timeframe_seconds(target)
        if target_seconds in native_seconds or any(
            source < target_seconds and target_seconds % source == 0
            for source in native_seconds
        ):
            available.add(target)
    return tuple(sorted(available, key=timeframe_seconds))


def resolve_timeframe(selected: MarketDataset, target: str) -> TimeframeResolution:
    """Resolve a target without changing provider, symbol, or instrument."""
    target_seconds = timeframe_seconds(target)
    target_label = target.strip().lower()
    entries = _entries_for(selected)
    native = [
        entry for entry in entries
        if timeframe_seconds(entry.timeframe) == target_seconds
    ]
    if native:
        return TimeframeResolution(target_label, target_seconds, native[0], True)

    lower = [
        entry for entry in entries
        if timeframe_seconds(entry.timeframe) < target_seconds
        and target_seconds % timeframe_seconds(entry.timeframe) == 0
    ]
    if not lower:
        raise UnsupportedTimeframeError(
            f"{target_label} is unavailable for {selected.label}; no exact native or "
            "valid lower timeframe source exists."
        )
    source = max(lower, key=lambda entry: timeframe_seconds(entry.timeframe))
    return TimeframeResolution(target_label, target_seconds, source, False)


def aggregate_ohlcv(data: pd.DataFrame, source_seconds: int, target_seconds: int) -> pd.DataFrame:
    """Aggregate complete source bars into fixed UTC target bars."""
    if target_seconds <= source_seconds or target_seconds % source_seconds:
        raise UnsupportedTimeframeError("Target timeframe must be an exact upward multiple of source timeframe.")
    missing = [column for column in _REQUIRED_COLUMNS if column not in data.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {', '.join(missing)}")
    if data["timestamp"].dt.tz is None:
        raise ValueError("TradingView timeframe data requires UTC timestamps.")
    if str(data["timestamp"].dt.tz) != "UTC":
        raise ValueError("TradingView timeframe data requires UTC timestamps.")
    if data["timestamp"].duplicated().any():
        raise ValueError("Duplicate timestamps cannot be aggregated.")

    source = data.loc[:, _REQUIRED_COLUMNS].copy()
    source = source.sort_values("timestamp", kind="stable")
    timestamps = source["timestamp"]
    if target_seconds == 604800:
        # Fixed ISO week boundary: Monday 00:00 UTC. Seven-day flooring would
        # inherit the Unix epoch's Thursday boundary.
        source["_bucket"] = timestamps.dt.normalize() - pd.to_timedelta(
            timestamps.dt.weekday, unit="D"
        )
    else:
        source["_bucket"] = timestamps.dt.floor(f"{target_seconds}s")
    bars_per_group = target_seconds // source_seconds
    rows: list[dict[str, object]] = []
    for bucket, group in source.groupby("_bucket", sort=True):
        timestamps = group["timestamp"].sort_values()
        expected = pd.date_range(
            start=bucket, periods=bars_per_group,
            freq=pd.Timedelta(seconds=source_seconds), tz="UTC",
        )
        if len(group) != bars_per_group or not timestamps.reset_index(drop=True).equals(expected.to_series().reset_index(drop=True)):
            continue
        ordered = group.sort_values("timestamp")
        rows.append({
            "timestamp": bucket,
            "open": ordered["open"].iloc[0],
            "high": ordered["high"].max(),
            "low": ordered["low"].min(),
            "close": ordered["close"].iloc[-1],
            "volume": ordered["volume"].sum(),
        })
    return pd.DataFrame(rows, columns=_REQUIRED_COLUMNS)


def load_resolution_data(resolution: TimeframeResolution, loader) -> pd.DataFrame:
    """Load native data or derive it from the resolved lower timeframe."""
    source = loader(resolution.source.path)
    if resolution.native:
        return source.copy()
    return aggregate_ohlcv(source, resolution.source.step_seconds, resolution.target_seconds)
