import pandas as pd
import pytest
from pathlib import Path

from services.market_datasets import MarketDataset
from ui.tradingview_mode.timeframes import (
    UnsupportedTimeframeError,
    aggregate_ohlcv,
    available_timeframes,
    resolve_timeframe,
    timeframe_seconds,
)


def entry(key="fixture", timeframe="15m", broker="Fixture"):
    return MarketDataset(key, key, "BTCUSD", "BTCUSD", broker, "fixture", timeframe,
                         timeframe_seconds(timeframe), Path(f"{key}.csv"), "CONSTANT", True, False)


def candles(start="2026-01-01 00:00", periods=8, freq="15min"):
    timestamps = pd.date_range(start, periods=periods, freq=freq, tz="UTC")
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": range(1, periods + 1),
        "high": range(2, periods + 2),
        "low": range(periods),
        "close": range(2, periods + 2),
        "volume": range(10, 10 + periods),
    })


def test_m15_to_m30_aggregation_and_volume():
    result = aggregate_ohlcv(candles(), 900, 1800)
    assert result["timestamp"].tolist() == list(pd.date_range("2026-01-01", periods=4, freq="30min", tz="UTC"))
    assert result.iloc[0][["open", "high", "low", "close", "volume"]].tolist() == [1, 3, 0, 3, 21]


@pytest.mark.parametrize(("source", "target", "freq"), [(900, 3600, "15min"), (1800, 3600, "30min"), (3600, 14400, "1h")])
def test_valid_upward_aggregation(source, target, freq):
    assert target % source == 0
    assert len(aggregate_ohlcv(candles(periods=target // source, freq=freq), source, target)) == 1


def test_downward_and_non_divisible_aggregation_rejected():
    with pytest.raises(UnsupportedTimeframeError):
        aggregate_ohlcv(candles(), 3600, 1800)
    with pytest.raises(UnsupportedTimeframeError):
        aggregate_ohlcv(candles(), 900, 2000)


def test_utc_fixed_boundaries_and_incomplete_trailing_group():
    data = candles(start="2026-01-01 00:15", periods=7)
    result = aggregate_ohlcv(data, 900, 3600)
    assert result["timestamp"].tolist() == [pd.Timestamp("2026-01-01 01:00", tz="UTC")]
    assert result["timestamp"].dt.tz is not None


def test_daily_and_weekly_boundaries_are_fixed_utc_boundaries():
    daily = candles(start="2026-01-05 00:00", periods=7, freq="1D")
    daily_result = aggregate_ohlcv(daily, 86400, 604800)
    assert daily_result["timestamp"].tolist() == [pd.Timestamp("2026-01-05", tz="UTC")]

    hourly = candles(start="2026-01-05 00:00", periods=24, freq="1h")
    hourly_result = aggregate_ohlcv(hourly, 3600, 86400)
    assert hourly_result["timestamp"].tolist() == [pd.Timestamp("2026-01-05", tz="UTC")]


def test_source_is_not_mutated():
    data = candles()
    before = data.copy(deep=True)
    aggregate_ohlcv(data, 900, 1800)
    pd.testing.assert_frame_equal(data, before)


def test_native_target_is_preferred_and_provider_identity_preserved():
    selected = entry("m15", "15m", "Exness")
    native_h1 = entry("h1", "1h", "Exness")
    other_provider = entry("other", "1h", "Other")
    resolution = resolve_timeframe_with_entries(selected, "1h", (selected, native_h1, other_provider))
    assert resolution.native and resolution.source.key == "h1"
    assert resolution.source.broker == selected.broker


def resolve_timeframe_with_entries(selected, target, entries):
    """Small fixture adapter for testing selection rules without registry mutation."""
    import ui.tradingview_mode.timeframes as module
    original = module.datasets_for_instrument
    module.datasets_for_instrument = lambda instrument: entries
    try:
        return module.resolve_timeframe(selected, target)
    finally:
        module.datasets_for_instrument = original


def test_unsupported_target_is_rejected_without_fallback():
    selected = entry("m30", "30m")
    with pytest.raises(UnsupportedTimeframeError):
        resolve_timeframe_with_entries(selected, "15m", (selected,))


def test_available_timeframes_only_contains_native_or_derived():
    selected = entry("m30", "30m")
    options = available_timeframes_with_entries(selected, (selected,))
    assert options == ("30m", "1h", "2h", "4h", "6h", "12h", "1d", "1w")


def available_timeframes_with_entries(selected, entries):
    import ui.tradingview_mode.timeframes as module
    original = module.datasets_for_instrument
    module.datasets_for_instrument = lambda instrument: entries
    try:
        return module.available_timeframes(selected)
    finally:
        module.datasets_for_instrument = original
