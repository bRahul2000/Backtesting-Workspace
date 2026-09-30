"""Zoneflow indicator engine: a generic, market-independent indicator contract.

An indicator is an ``IndicatorSpec``: typed parameters, a ``compute`` over a standard OHLCV frame, and presentation
as plot definitions - never code specific to a market, broker, asset class or to Pine. Anything with a valid OHLC
series (BTC, gold, forex, equities...) can use every indicator whose data requirements the series meets.

Presentation primitives (rendered generically by frontend/src/chart/ChartEngine.js):
    Plot    a line or histogram output; its own colour/width/style, per-point colours for conditional colouring,
            positive/negative colours for histograms
    Fill    a band between two outputs or between two horizontal levels
    Level   a horizontal reference line (e.g. RSI 70 / 30)
    markers shapes above/below/on bars (e.g. confirmed pivots, trend flips)
    placement "overlay" (price pane) or "pane" (its own pane below); scale "price" or "own"

Data requirements are declared, never faked: "ohlc" (every chart), "volume" (bar volume of any kind). Exness MT5
bars carry TICK volume (price-change counts), not traded volume; a volume indicator on tick volume is marked LIMITED
and says so. Missing data makes an indicator unavailable with a reason - it is never filled in.

Higher-timeframe input (``timeframe`` parameter): the indicator runs on bars aggregated from the chart's own bars and
each value becomes visible on the chart only once that higher-timeframe bar has CLOSED (no lookahead).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Callable

import numpy as np
import pandas as pd

TIMEFRAME_CHOICES = ("chart", "15m", "30m", "1h", "4h", "1d")
_TF_SECONDS = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
UP, DOWN = "#26a69a", "#ef5350"
LEVEL_COLOR = "#5b6474"


# ---- contract --------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Param:
    name: str
    label: str
    default: object
    kind: str = "int"                      # int | float | choice
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    choices: tuple = ()


@dataclass(frozen=True)
class Plot:
    key: str
    title: str
    type: str = "line"                     # line | histogram
    color: str | None = None               # None = the instance's colour
    width: int = 1
    style: str = "solid"                   # solid | dashed | dotted
    colors: tuple[str, str] | None = None  # histogram (positive, negative) when no per-point colours are given


@dataclass(frozen=True)
class Fill:
    upper: object                          # an output key, or a number (a horizontal level)
    lower: object
    color: str


@dataclass(frozen=True)
class Level:
    value: float
    title: str = ""
    color: str = LEVEL_COLOR
    style: str = "dotted"


@dataclass
class DataContext:
    """What the series offers. volume: "traded" | "tick" | "none"."""
    volume: str = "traded"
    timeframe_seconds: int | None = None


@dataclass
class Output:
    series: dict[str, pd.Series]
    colors: dict[str, pd.Series] = field(default_factory=dict)       # per-point colour strings (conditional colour)
    markers: list[dict] = field(default_factory=list)                  # {index, position, shape, color, text}


@dataclass(frozen=True)
class IndicatorSpec:
    key: str
    display_name: str
    category: str
    placement: str                          # overlay | pane
    params: tuple[Param, ...]
    plots: tuple[Plot, ...]
    compute: Callable[[pd.DataFrame, dict, DataContext], Output]
    fills: tuple[Fill, ...] = ()
    levels: tuple[Level, ...] = ()
    requires: frozenset = frozenset({"ohlc"})
    scale: str = "price"                    # price | own
    description: str = ""
    label: Callable[[dict], str] | None = None
    validate: Callable[[dict], None] | None = None
    status: str = "working"                 # working | disabled
    disabled_reason: str = ""
    chartable: bool = True

    # compatibility with the earlier IndicatorDefinition
    @property
    def pane(self) -> str:
        return "overlay" if self.placement == "overlay" else "lower"

    @property
    def defaults(self) -> dict:
        return {param.name: param.default for param in self.params}

    def short_label(self, params: dict) -> str:
        params = {**self.defaults, **(params or {})}
        if self.label is not None:
            return self.label(params)
        shown = [str(params[p.name]) for p in self.params if p.name != "timeframe"]
        tf = params.get("timeframe", "chart")
        return " ".join([self.display_name, *shown] + ([tf] if tf not in (None, "chart") else []))


def availability(spec: IndicatorSpec, ctx: DataContext) -> tuple[str, str]:
    """("ok" | "limited" | "unavailable", explanation) for this spec on data described by ctx."""
    if spec.status != "working":
        return "unavailable", spec.disabled_reason
    if "volume" in spec.requires:
        if ctx.volume == "none":
            return "unavailable", f"{spec.display_name} needs bar volume; this data source has none."
        if ctx.volume == "tick":
            return "limited", (f"{spec.display_name} uses TICK volume here (price-change counts from the broker), "
                               "not traded volume.")
    return "ok", ""


# ---- maths (no lookahead: every value uses only its own and earlier bars) ------------------------------------------

def _length(value) -> int:
    length = int(value)
    if length < 1:
        raise ValueError("Indicator length must be at least 1.")
    return length


def _ema(values: pd.Series, length: int) -> pd.Series:
    return values.ewm(span=_length(length), adjust=False, min_periods=_length(length)).mean()


def _rma(values: pd.Series, length: int) -> pd.Series:
    return values.ewm(alpha=1 / _length(length), adjust=False, min_periods=_length(length)).mean()


def _sma(values: pd.Series, length: int) -> pd.Series:
    return values.rolling(_length(length), min_periods=_length(length)).mean()


def _wma(values: pd.Series, length: int) -> pd.Series:
    length = _length(length)
    weights = np.arange(1, length + 1, dtype=float)
    array = values.to_numpy(dtype=float)
    out = np.full(len(array), np.nan)
    if len(array) >= length:
        out[length - 1:] = np.convolve(array, weights[::-1], mode="valid") / weights.sum()
    return pd.Series(out, index=values.index)


def _true_range(data: pd.DataFrame) -> pd.Series:
    previous_close = data["close"].shift(1)
    return pd.concat([data["high"] - data["low"], (data["high"] - previous_close).abs(),
                      (data["low"] - previous_close).abs()], axis=1).max(axis=1)


def _atr(data: pd.DataFrame, length: int) -> pd.Series:
    return _rma(_true_range(data), length)


def _color_by_sign(values: pd.Series, up: str = UP, down: str = DOWN) -> pd.Series:
    return pd.Series(np.where(values >= 0, up, down), index=values.index).where(values.notna())


# ---- the indicators ------------------------------------------------------------------------------------------------

def _p_length(default: int, maximum: int = 1000, label: str = "Length") -> Param:
    return Param("length", label, default, "int", 1, maximum, 1)


_P_TF = Param("timeframe", "Timeframe", "chart", "choice", choices=TIMEFRAME_CHOICES)


def _ma(kind):
    def compute(data, params, ctx):
        close = data["close"]
        length = params["length"]
        value = {"ema": _ema, "sma": _sma, "wma": _wma}[kind](close, length)
        return Output({"value": value})
    return compute


def _vwap(data, params, ctx):
    typical = (data["high"] + data["low"] + data["close"]) / 3.0
    anchor = params.get("anchor", "day")
    stamps = data["timestamp"]
    if anchor == "day":
        session = stamps.dt.normalize()
    elif anchor == "week":
        session = (stamps - pd.to_timedelta(stamps.dt.weekday, unit="D")).dt.normalize()
    else:
        session = stamps.dt.tz_localize(None).dt.to_period("M").astype(str)
    volume = data["volume"].astype(float)
    numerator = (typical * volume).groupby(session.values, sort=False).cumsum()
    denominator = volume.groupby(session.values, sort=False).cumsum()
    return Output({"value": (numerator / denominator.replace(0, np.nan))})


def _bands(data, params, ctx):
    close = data["close"]
    length, multiplier = params["length"], float(params["stddev"])
    basis = _sma(close, length)
    deviation = close.rolling(length, min_periods=length).std(ddof=0)
    return Output({"basis": basis, "upper": basis + multiplier * deviation, "lower": basis - multiplier * deviation})


def _keltner(data, params, ctx):
    basis = _ema(data["close"], params["length"])
    width = float(params["multiplier"]) * _atr(data, params["atr_length"])
    return Output({"basis": basis, "upper": basis + width, "lower": basis - width})


def _donchian(data, params, ctx):
    length = _length(params["length"])
    upper = data["high"].rolling(length, min_periods=length).max()
    lower = data["low"].rolling(length, min_periods=length).min()
    return Output({"upper": upper, "basis": (upper + lower) / 2, "lower": lower})


def _rsi(data, params, ctx):
    length = _length(params["length"])
    change = data["close"].diff()
    average_gain = _rma(change.clip(lower=0), length)
    average_loss = _rma(-change.clip(upper=0), length)
    relative_strength = average_gain / average_loss.replace(0, float("nan"))
    value = 100 - (100 / (1 + relative_strength))
    return Output({"value": value.where(average_loss.ne(0) | average_loss.isna(), 100.0)})


def _macd(data, params, ctx):
    close = data["close"]
    line = _ema(close, params["fast"]) - _ema(close, params["slow"])
    signal = _ema(line, params["signal"])
    histogram = line - signal
    rising = histogram >= histogram.shift(1)
    colors = pd.Series(np.select([(histogram >= 0) & rising, histogram >= 0, rising],
                                 ["#26a69a", "#b2dfdb", "#ffcdd2"], "#ef5350"), index=histogram.index)
    return Output({"macd": line, "signal": signal, "histogram": histogram},
                  colors={"histogram": colors.where(histogram.notna())})


def _stochastic(data, params, ctx):
    length = _length(params["length"])
    lowest = data["low"].rolling(length, min_periods=length).min()
    highest = data["high"].rolling(length, min_periods=length).max()
    raw = 100 * (data["close"] - lowest) / (highest - lowest).replace(0, np.nan)
    k = _sma(raw, params["smooth_k"])
    return Output({"k": k, "d": _sma(k, params["smooth_d"])})


def _atr_indicator(data, params, ctx):
    return Output({"value": _atr(data, params["length"])})


def _supertrend(data, params, ctx):
    atr = _atr(data, params["atr_length"]).to_numpy()
    factor = float(params["factor"])
    high, low, close = (data[c].to_numpy(dtype=float) for c in ("high", "low", "close"))
    mid = (high + low) / 2
    n = len(close)
    line = np.full(n, np.nan)
    direction = np.zeros(n)
    upper_prev = lower_prev = np.nan
    markers = []
    for i in range(n):
        if math.isnan(atr[i]):
            continue
        upper, lower = mid[i] + factor * atr[i], mid[i] - factor * atr[i]
        if not math.isnan(lower_prev) and lower < lower_prev and close[i - 1] >= lower_prev:
            lower = lower_prev                 # the band only tightens while price respects it
        if not math.isnan(upper_prev) and upper > upper_prev and close[i - 1] <= upper_prev:
            upper = upper_prev
        if i == 0 or direction[i - 1] == 0:
            direction[i] = -1                  # TradingView starts in a downtrend (the line is the upper band)
        elif direction[i - 1] == 1:
            direction[i] = -1 if close[i] < lower else 1
        else:
            direction[i] = 1 if close[i] > upper else -1
        line[i] = lower if direction[i] == 1 else upper
        if i and direction[i - 1] != 0 and direction[i] != direction[i - 1]:
            markers.append({"index": i, "position": "belowBar" if direction[i] == 1 else "aboveBar",
                            "shape": "arrowUp" if direction[i] == 1 else "arrowDown",
                            "color": UP if direction[i] == 1 else DOWN, "text": "Buy" if direction[i] == 1 else "Sell"})
        upper_prev, lower_prev = upper, lower
    value = pd.Series(line, index=data.index)
    colors = pd.Series(np.where(direction > 0, UP, DOWN), index=data.index).where(value.notna())
    return Output({"value": value}, colors={"value": colors}, markers=markers)


def _pivots(data, params, ctx):
    """Confirmed swing highs/lows: a bar is a pivot high when no bar within `left` before and `right` after is higher.
    It can only be known `right` bars later, so the newest `right` bars never carry a pivot (no lookahead)."""
    left, right = _length(params["left"]), _length(params["right"])
    high, low = data["high"].to_numpy(dtype=float), data["low"].to_numpy(dtype=float)
    markers = []
    for i in range(left, len(high) - right):
        window_h, window_l = high[i - left:i + right + 1], low[i - left:i + right + 1]
        if high[i] == window_h.max() and (window_h == high[i]).sum() == 1:
            markers.append({"index": i, "position": "aboveBar", "shape": "arrowDown", "color": DOWN,
                            "text": f"{high[i]:g}"})
        if low[i] == window_l.min() and (window_l == low[i]).sum() == 1:
            markers.append({"index": i, "position": "belowBar", "shape": "arrowUp", "color": UP, "text": f"{low[i]:g}"})
    return Output({}, markers=markers)


def _macd_check(params):
    if params["fast"] >= params["slow"]:
        raise ValueError("MACD: fast length must be shorter than slow length.")


INDICATOR_REGISTRY: tuple[IndicatorSpec, ...] = (
    IndicatorSpec("ema", "EMA", "Trend", "overlay", (_p_length(20), _P_TF), (Plot("value", "EMA", width=2),),
                  _ma("ema"), description="Exponential moving average of close."),
    IndicatorSpec("sma", "SMA", "Trend", "overlay", (_p_length(50), _P_TF), (Plot("value", "SMA", width=2),),
                  _ma("sma"), description="Simple moving average of close."),
    IndicatorSpec("wma", "WMA", "Trend", "overlay", (_p_length(20),), (Plot("value", "WMA", width=2),),
                  _ma("wma"), description="Linearly weighted moving average of close."),
    IndicatorSpec("supertrend", "Supertrend", "Trend", "overlay",
                  (Param("atr_length", "ATR length", 10, "int", 1, 500, 1),
                   Param("factor", "Factor", 3.0, "float", 0.1, 20.0, 0.1)),
                  (Plot("value", "Supertrend", width=2),), _supertrend,
                  description="ATR trailing band; colour by direction, markers on direction changes."),
    IndicatorSpec("bb", "Bollinger Bands", "Volatility", "overlay",
                  (_p_length(20), Param("stddev", "StdDev", 2.0, "float", 0.1, 10.0, 0.1)),
                  (Plot("basis", "Basis", color="#f5a623", style="dashed"), Plot("upper", "Upper", color="#4aa3ff"),
                   Plot("lower", "Lower", color="#4aa3ff")), _bands,
                  fills=(Fill("upper", "lower", "rgba(74,163,255,0.08)"),),
                  description="SMA basis ± standard deviations of close (population)."),
    IndicatorSpec("keltner", "Keltner Channels", "Volatility", "overlay",
                  (_p_length(20), Param("multiplier", "Multiplier", 2.0, "float", 0.1, 10.0, 0.1),
                   Param("atr_length", "ATR length", 10, "int", 1, 500, 1)),
                  (Plot("basis", "Basis", color="#c678dd"), Plot("upper", "Upper", color="#c678dd", style="dashed"),
                   Plot("lower", "Lower", color="#c678dd", style="dashed")), _keltner,
                  fills=(Fill("upper", "lower", "rgba(198,120,221,0.07)"),),
                  description="EMA basis ± multiplier × ATR."),
    IndicatorSpec("donchian", "Donchian Channels", "Volatility", "overlay", (_p_length(20),),
                  (Plot("upper", "Upper", color="#56d4bc"), Plot("basis", "Basis", color="#ff7a90"),
                   Plot("lower", "Lower", color="#56d4bc")), _donchian,
                  fills=(Fill("upper", "lower", "rgba(86,212,188,0.06)"),),
                  description="Highest high / lowest low over the length."),
    IndicatorSpec("vwap", "VWAP", "Volume", "overlay",
                  (Param("anchor", "Anchor", "day", "choice", choices=("day", "week", "month")),),
                  (Plot("value", "VWAP", width=2),), _vwap, requires=frozenset({"ohlc", "volume"}),
                  label=lambda p: f"VWAP {p['anchor']}",
                  description="Volume-weighted average of typical price, reset each UTC day/week/month."),
    IndicatorSpec("pivots", "Pivots High/Low", "Structure", "overlay",
                  (Param("left", "Left bars", 10, "int", 1, 200, 1), Param("right", "Right bars", 10, "int", 1, 200, 1)),
                  (), _pivots, description="Confirmed swing highs and lows, marked once `right` bars have closed."),
    IndicatorSpec("rsi", "RSI", "Momentum", "pane", (_p_length(14), _P_TF), (Plot("value", "RSI", width=2),), _rsi,
                  levels=(Level(70, "Overbought"), Level(50, "Middle", style="dashed"), Level(30, "Oversold")),
                  fills=(Fill(70, 30, "rgba(126,87,194,0.08)"),), description="Wilder RSI of close."),
    IndicatorSpec("macd", "MACD", "Momentum", "pane",
                  (Param("fast", "Fast", 12, "int", 1, 500, 1), Param("slow", "Slow", 26, "int", 1, 1000, 1),
                   Param("signal", "Signal", 9, "int", 1, 500, 1)),
                  (Plot("histogram", "Histogram", "histogram"), Plot("macd", "MACD", color="#2962ff", width=2),
                   Plot("signal", "Signal", color="#ff6d00")), _macd, validate=_macd_check,
                  levels=(Level(0, "Zero", style="dashed"),),
                  description="EMA(fast) − EMA(slow), its EMA signal, and the histogram (4-colour)."),
    IndicatorSpec("stoch", "Stochastic", "Momentum", "pane",
                  (_p_length(14, label="%K length"), Param("smooth_k", "%K smoothing", 1, "int", 1, 100, 1),
                   Param("smooth_d", "%D smoothing", 3, "int", 1, 100, 1)),
                  (Plot("k", "%K", color="#2962ff", width=2), Plot("d", "%D", color="#ff6d00")), _stochastic,
                  levels=(Level(80, "Upper"), Level(20, "Lower")), fills=(Fill(80, 20, "rgba(33,150,243,0.07)"),),
                  description="Close within the high-low range of the length, smoothed."),
    IndicatorSpec("atr", "ATR", "Volatility", "pane", (_p_length(14),), (Plot("value", "ATR", width=2),),
                  _atr_indicator, description="Wilder average true range."),
    # Volume is the chart's own histogram (Settings -> Show volume), not an indicator instance.
    IndicatorSpec("volume", "Volume", "Volume", "pane", (), (Plot("value", "Volume", "histogram"),),
                  lambda data, params, ctx: Output({"value": data["volume"].astype(float)}),
                  requires=frozenset({"ohlc", "volume"}), chartable=False),
)

INDICATORS = {spec.key: spec for spec in INDICATOR_REGISTRY}
CHARTABLE = tuple(spec.key for spec in INDICATOR_REGISTRY if spec.chartable)


# ---- parameters ----------------------------------------------------------------------------------------------------

def validate_params(key: str, params: dict | None) -> dict:
    """Complete, typed params for ``key`` or ValueError (bounds, choices, whole numbers, cross-parameter rules)."""
    spec = INDICATORS[key]
    params = dict(params or {})
    unknown = set(params) - {p.name for p in spec.params}
    if unknown:
        raise ValueError(f"{spec.display_name}: unknown parameter(s) {', '.join(sorted(unknown))}.")
    result = {}
    for p in spec.params:
        value = params.get(p.name, p.default)
        if p.kind == "choice":
            if value not in p.choices:
                raise ValueError(f"{spec.display_name}: {p.label} must be one of {', '.join(map(str, p.choices))}.")
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{spec.display_name}: {p.label} must be a number.")
            if p.kind == "int":
                if float(value) != int(value):
                    raise ValueError(f"{spec.display_name}: {p.label} must be a whole number.")
                value = int(value)
            else:
                value = float(value)
            if not p.minimum <= value <= p.maximum:
                raise ValueError(f"{spec.display_name}: {p.label} must be between {p.minimum:g} and {p.maximum:g}.")
        result[p.name] = value
    if spec.validate:
        spec.validate(result)
    return result


# ---- higher-timeframe input ----------------------------------------------------------------------------------------

def _epoch_seconds(stamps: pd.Series) -> pd.Series:
    """Integer UTC epoch seconds whatever the datetime resolution (ns, us, ms or s)."""
    return (stamps - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)


def _higher(data: pd.DataFrame, seconds: int) -> tuple[pd.DataFrame, pd.Series]:
    """Aggregate chart bars into `seconds` buckets (UTC-aligned) and, for every chart bar, the index of the last
    higher-timeframe bar that has CLOSED by the end of that chart bar (-1 = none yet)."""
    epoch = _epoch_seconds(data["timestamp"])
    buckets = (epoch // seconds) * seconds
    grouped = data.assign(_bucket=buckets.values).groupby("_bucket", sort=True)
    higher = pd.DataFrame({"open": grouped["open"].first(), "high": grouped["high"].max(),
                           "low": grouped["low"].min(), "close": grouped["close"].last(),
                           "volume": grouped["volume"].sum() if "volume" in data else 0.0})
    higher["timestamp"] = pd.to_datetime(higher.index, unit="s", utc=True)
    higher = higher.reset_index(drop=True)
    step = int(data["timestamp"].diff().dt.total_seconds().median()) if len(data) > 1 else seconds
    chart_end = epoch + step
    closes = _epoch_seconds(higher["timestamp"]) + seconds
    visible = np.searchsorted(closes.to_numpy(), chart_end.to_numpy(), side="right") - 1
    return higher, pd.Series(visible, index=data.index)


def compute(data: pd.DataFrame, key: str, params: dict | None = None, ctx: DataContext | None = None) -> Output:
    """Run one indicator on ``data`` (never modified)."""
    spec = INDICATORS[key]
    params = validate_params(key, params)
    ctx = ctx or DataContext()
    if "volume" in spec.requires and ("volume" not in data or data["volume"].isna().all()):
        raise ValueError(f"{spec.display_name} requires volume data.")
    tf = params.get("timeframe", "chart")
    if tf in (None, "chart"):
        return spec.compute(data, params, ctx)
    seconds = _TF_SECONDS[tf]
    chart_seconds = ctx.timeframe_seconds or (int(data["timestamp"].diff().dt.total_seconds().median()) if len(data) > 1 else 0)
    if chart_seconds and (seconds < chart_seconds or seconds % chart_seconds):
        raise ValueError(f"{spec.display_name}: timeframe {tf} must be a multiple of the chart timeframe.")
    if seconds == chart_seconds:
        return spec.compute(data, params, ctx)
    higher, visible = _higher(data, seconds)
    result = spec.compute(higher, params, ctx)
    mapped = {}
    for name, values in result.series.items():
        array = values.to_numpy(dtype=float)
        mapped[name] = pd.Series([array[i] if i >= 0 else np.nan for i in visible], index=data.index)
    return Output(mapped)


def calculate_indicator(data: pd.DataFrame, key: str, params: dict | None = None,
                        ctx: DataContext | None = None) -> dict[str, pd.Series]:
    """Earlier API: the output series only."""
    if key not in INDICATORS:
        raise ValueError(f"Unknown indicator: {key}")
    return compute(data, key, params, ctx).series


# ---- capability matrix -------------------------------------------------------------------------------------------

def capability_matrix() -> list[dict]:
    """Machine-readable record of every indicator the Indicators menu lists (docs/INDICATOR_CAPABILITY_MATRIX.json)."""
    rows = []
    for spec in INDICATOR_REGISTRY:
        if not spec.chartable:
            continue
        rows.append({
            "key": spec.key, "name": spec.display_name, "category": spec.category,
            "placement": spec.placement, "scale": spec.scale,
            "inputs": [{"name": p.name, "label": p.label, "kind": p.kind, "default": p.default,
                        **({"min": p.minimum, "max": p.maximum} if p.kind != "choice" else {"choices": list(p.choices)})}
                       for p in spec.params],
            "outputs": [{"key": plot.key, "title": plot.title, "type": plot.type} for plot in spec.plots]
                       + ([{"key": "markers", "title": "markers", "type": "markers"}]
                          if spec.key in ("pivots", "supertrend") else []),
            "fills": len(spec.fills), "levels": [level.value for level in spec.levels],
            "data_requirements": sorted(spec.requires),
            "supported_markets": "any series with valid OHLC" + (" and bar volume" if "volume" in spec.requires else ""),
            "volume_note": ("tick volume (Exness MT5) -> LIMITED; traded volume (Bitstamp, Binance) -> OK; none -> "
                            "unavailable") if "volume" in spec.requires else None,
            "supported_timeframes": "any chart timeframe" + (
                "; optional higher-timeframe input (closed bars only)" if any(p.name == "timeframe" for p in spec.params) else ""),
            "implementation_status": "WORKING" if spec.status == "working" else "DISABLED",
            "disabled_reason": spec.disabled_reason or None,
            "test_status": "tests/tradingview_mode/test_indicator_engine.py: BTC, Gold and synthetic OHLC",
        })
    return rows
