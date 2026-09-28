"""Built-in, read-only indicators for the TradingView historical chart."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class IndicatorDefinition:
    key: str
    display_name: str
    category: str
    pane: str
    defaults: dict[str, float | int]


INDICATOR_REGISTRY = (
    IndicatorDefinition("ema", "EMA", "Trend", "overlay", {"length": 20}),
    IndicatorDefinition("sma", "SMA", "Trend", "overlay", {"length": 50}),
    IndicatorDefinition("vwap", "VWAP", "Volume", "overlay", {}),
    IndicatorDefinition("bb", "Bollinger Bands", "Volatility", "overlay", {"length": 20, "stddev": 2.0}),
    IndicatorDefinition("rsi", "RSI", "Momentum", "lower", {"length": 14}),
    IndicatorDefinition("macd", "MACD", "Momentum", "lower", {"fast": 12, "slow": 26, "signal": 9}),
    IndicatorDefinition("atr", "ATR", "Volatility", "lower", {"length": 14}),
    IndicatorDefinition("volume", "Volume", "Volume", "lower", {}),
)

INDICATORS = {definition.key: definition for definition in INDICATOR_REGISTRY}


def _length(value: int | float) -> int:
    length = int(value)
    if length < 1:
        raise ValueError("Indicator length must be at least 1.")
    return length


def _ema(values: pd.Series, length: int) -> pd.Series:
    return values.ewm(span=_length(length), adjust=False, min_periods=_length(length)).mean()


def _true_range(data: pd.DataFrame) -> pd.Series:
    previous_close = data["close"].shift(1)
    return pd.concat(
        [data["high"] - data["low"],
         (data["high"] - previous_close).abs(),
         (data["low"] - previous_close).abs()], axis=1,
    ).max(axis=1)


def calculate_indicator(data: pd.DataFrame, key: str, params: dict[str, float | int] | None = None) -> dict[str, pd.Series]:
    """Calculate one indicator without changing ``data``."""
    if key not in INDICATORS:
        raise ValueError(f"Unknown indicator: {key}")
    params = dict(params or {})
    close = data["close"]

    if key == "ema":
        return {"value": _ema(close, _length(params.get("length", 20)))}
    if key == "sma":
        length = _length(params.get("length", 50))
        return {"value": close.rolling(length, min_periods=length).mean()}
    if key == "vwap":
        if "volume" not in data or data["volume"].isna().all():
            raise ValueError("VWAP requires volume data.")
        typical = (data["high"] + data["low"] + close) / 3.0
        session = data["timestamp"].dt.normalize()
        weighted = typical * data["volume"]
        numerator = weighted.groupby(session, sort=False).cumsum()
        denominator = data["volume"].groupby(session, sort=False).cumsum()
        return {"value": numerator / denominator}
    if key == "bb":
        length = _length(params.get("length", 20))
        multiplier = float(params.get("stddev", 2.0))
        basis = close.rolling(length, min_periods=length).mean()
        deviation = close.rolling(length, min_periods=length).std(ddof=0)
        return {"basis": basis, "upper": basis + multiplier * deviation, "lower": basis - multiplier * deviation}
    if key == "rsi":
        length = _length(params.get("length", 14))
        change = close.diff()
        gain = change.clip(lower=0)
        loss = -change.clip(upper=0)
        average_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
        average_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
        relative_strength = average_gain / average_loss.replace(0, float("nan"))
        value = 100 - (100 / (1 + relative_strength))
        value = value.where(average_loss.ne(0), 100.0)
        return {"value": value}
    if key == "macd":
        fast = _length(params.get("fast", 12))
        slow = _length(params.get("slow", 26))
        signal = _length(params.get("signal", 9))
        line = _ema(close, fast) - _ema(close, slow)
        signal_line = _ema(line, signal)
        return {"macd": line, "signal": signal_line, "histogram": line - signal_line}
    if key == "atr":
        length = _length(params.get("length", 14))
        value = _true_range(data).ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
        return {"value": value}
    raise ValueError(f"Indicator calculation is not implemented: {key}")
