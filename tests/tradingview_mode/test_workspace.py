from ui.tradingview_mode.indicators import INDICATORS
from ui.tradingview_mode.workspace import quick_timeframe_labels, registered_watchlist, timeframe_value


def test_quick_timeframe_buttons_preserve_safe_values():
    labels = quick_timeframe_labels(("15m", "1h", "1d", "1w"))
    assert labels == ("15m", "1h", "D", "W")
    assert [timeframe_value(label) for label in labels] == ["15m", "1h", "1d", "1w"]


def test_watchlist_uses_registered_local_datasets():
    datasets = registered_watchlist()
    assert datasets
    assert all(entry.key and entry.path for entry in datasets)
    assert {entry.instrument for entry in datasets} >= {"BTCUSD", "XAUUSDm"}


def test_indicator_registry_remains_intact():
    assert set(INDICATORS) == {"ema", "sma", "wma", "supertrend", "vwap", "bb", "keltner", "donchian", "pivots",
                               "rsi", "macd", "stoch", "atr", "volume"}
