import pandas as pd
import pytest

from ui.tradingview_mode.indicators import INDICATORS, calculate_indicator


def frame(periods=80):
    timestamp = pd.date_range("2026-01-01", periods=periods, freq="15min", tz="UTC")
    close = pd.Series(range(100, 100 + periods), dtype=float)
    return pd.DataFrame({"timestamp": timestamp, "open": close - 1, "high": close + 2,
                         "low": close - 2, "close": close, "volume": 10.0})


def test_ema_and_sma():
    data = frame(5)
    assert calculate_indicator(data, "ema", {"length": 3})["value"].iloc[-1] == pytest.approx(103.0625)
    assert calculate_indicator(data, "sma", {"length": 3})["value"].iloc[-1] == pytest.approx(103.0)


def test_vwap_typical_price_and_daily_reset():
    data = frame(4)
    data.loc[0, "timestamp"] = pd.Timestamp("2026-01-01 23:45", tz="UTC")
    data.loc[1, "timestamp"] = pd.Timestamp("2026-01-02 00:00", tz="UTC")
    data.loc[2, "timestamp"] = pd.Timestamp("2026-01-02 00:15", tz="UTC")
    data.loc[3, "timestamp"] = pd.Timestamp("2026-01-02 00:30", tz="UTC")
    value = calculate_indicator(data, "vwap")["value"]
    assert value.iloc[1] == pytest.approx((data.loc[1, "high"] + data.loc[1, "low"] + data.loc[1, "close"]) / 3)
    assert value.iloc[0] != value.iloc[1]


def test_vwap_requires_volume():
    data = frame().drop(columns="volume")
    with pytest.raises(ValueError, match="requires volume"):
        calculate_indicator(data, "vwap")


def test_bollinger_bands():
    values = calculate_indicator(frame(5), "bb", {"length": 3, "stddev": 2})
    assert values["basis"].iloc[-1] == pytest.approx(103)
    assert values["upper"].iloc[-1] > values["basis"].iloc[-1]
    assert values["lower"].iloc[-1] < values["basis"].iloc[-1]


def test_rsi_macd_atr_and_warmup():
    data = frame()
    rsi = calculate_indicator(data, "rsi", {"length": 14})["value"].dropna()
    assert rsi.between(0, 100).all()
    macd = calculate_indicator(data, "macd")
    assert set(macd) == {"macd", "signal", "histogram"}
    assert macd["histogram"].iloc[-1] == pytest.approx(macd["macd"].iloc[-1] - macd["signal"].iloc[-1])
    assert calculate_indicator(data, "atr", {"length": 14})["value"].notna().any()
    assert calculate_indicator(data, "ema", {"length": 20})["value"].iloc[:19].isna().all()


def test_registry_classifies_overlay_and_lower_indicators():
    assert {key for key, value in INDICATORS.items() if value.pane == "overlay"} == {"ema", "sma", "vwap", "bb"}
    assert {key for key, value in INDICATORS.items() if value.pane == "lower"} == {"rsi", "macd", "atr", "volume"}


def test_calculation_preserves_source_and_utc():
    data = frame()
    before = data.copy(deep=True)
    calculate_indicator(data, "ema")
    pd.testing.assert_frame_equal(data, before)
    assert str(data["timestamp"].dt.tz) == "UTC"
