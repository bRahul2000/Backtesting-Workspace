"""ta.* built-ins, following the reference implementations in Pine's docs.

Semantics that matter for parity:
* Series arguments are recorded per call site on each execution, so
  ``src[i]`` inside a function is the history *seen by that call*; calling a
  ta function conditionally therefore behaves like Pine (it only sees the bars
  it ran on).
* ema/rma seed with the SMA of the first ``length`` values (Pine's
  ``na(sum[1]) ? ta.sma(src, length) : ...``).
* na inputs inside a series (confirmed on TradingView, parity fixture
  s01_averages, na source at bars 20-22):
  - sma skips them: the average of the last ``length`` non-na values, so it
    keeps its value through a gap;
  - ema/rma return na on an na input but keep their state and resume on the
    next valid input;
  - wma returns na on an na input; inside its window an na counts as the last
    non-na value before it.
  - highest / lowest return na on an na input and skip an older na inside the
    window (fixture s11_na, na_highest).
  Leading na (warm-up) gives the same first valid bar as before.
* ta.vwap (variable and function) is anchored to the start of each UTC day.
"""
from __future__ import annotations

import math

from ..errors import PineRuntimeError
from ..registry import Param as P, builtin, variable
from ..runtime import MISSING
from ..values import NA, is_na, truthy

F, I, B = "series float", "series int", "series bool"
SIMPLE_INT = "simple int"


# ---- helpers ---------------------------------------------------------------------------------------------

def _length(value, name: str = "length") -> int | None:
    if is_na(value):
        return None
    if value != int(value) or value < 1:
        raise PineRuntimeError(f"`{name}` must be a positive whole number (got {value}).", 0)
    return int(value)


def _clean(window):
    return None if window is None or any(is_na(v) for v in window) else window


def _prev(buffer, bar):
    value = buffer.before(bar)
    return NA if value is MISSING else value


def _valid(site, bar, value, name="valid"):
    """Buffer of the non-na inputs only (bar-tagged, so rollback still works)."""
    buffer = site.buf(name)
    if not is_na(value):
        buffer.set(bar, value)
    return buffer


def sma_step(rt, site, value, length):
    """TradingView skips na inputs: the mean of the last ``length`` non-na values."""
    buffer = _valid(site, rt.bar, value)
    if length is None:
        return NA
    window = buffer.window(length)
    return NA if window is None else math.fsum(window) / length


def smoothed_step(rt, site, value, length, alpha):
    """ema (alpha = 2/(n+1)) and rma (alpha = 1/n) with Pine's SMA seed.

    An na input returns na without touching the state: the next valid input
    continues from the last valid output (TradingView)."""
    buffer = _valid(site, rt.bar, value)
    if length is None or is_na(value):
        return NA
    previous = _prev(site.buf("out"), rt.bar)
    if is_na(previous):
        window = buffer.window(length)
        result = NA if window is None else math.fsum(window) / length
    else:
        result = alpha * value + (1 - alpha) * previous
    if not is_na(result):
        site.push("out", rt.bar, result)
    return result


def ema_step(rt, site, value, length):
    return smoothed_step(rt, site, value, length, 2 / (length + 1) if length else 0)


def rma_step(rt, site, value, length):
    return smoothed_step(rt, site, value, length, 1 / length if length else 0)


def wma_step(rt, site, value, length):
    """na on an na input; inside the window an na counts as the last non-na value before it (TradingView)."""
    filled = value if not is_na(value) else _prev(site.buf("x"), rt.bar)
    buffer = site.push("x", rt.bar, filled)
    if length is None or is_na(value):
        return NA
    window = _clean(buffer.window(length))
    if window is None:
        return NA
    norm = length * (length + 1) / 2
    return math.fsum(v * (i + 1) for i, v in enumerate(window)) / norm


def change_step(rt, site, value, length=1):
    buffer = site.push("x", rt.bar, value)
    previous = buffer.back(length)
    if is_na(value) or is_na(previous):
        return NA
    if isinstance(value, bool):
        return value != previous
    return value - previous


def window_of(rt, site, value, length, name="x"):
    buffer = site.push(name, rt.bar, value)
    return None if length is None else buffer.window(length)


def true_range(rt, handle_na: bool):
    high, low = rt.series_at("high", rt.bar), rt.series_at("low", rt.bar)
    previous_close = rt.series_at("close", rt.bar - 1)
    if is_na(high) or is_na(low):
        return NA
    if is_na(previous_close):
        return high - low if handle_na else NA
    return max(high - low, abs(high - previous_close), abs(low - previous_close))


def _series(name):
    return lambda rt: rt.series_at(name, rt.bar)


# ---- moving averages ----------------------------------------------------------------------------------------

@builtin("ta.sma", P("source", F), P("length", I), stateful=True)
def _sma(rt, site, a):
    return sma_step(rt, site, a["source"], _length(a["length"]))


@builtin("ta.ema", P("source", F), P("length", SIMPLE_INT), stateful=True)
def _ema(rt, site, a):
    return ema_step(rt, site, a["source"], _length(a["length"]))


@builtin("ta.rma", P("source", F), P("length", SIMPLE_INT), stateful=True)
def _rma(rt, site, a):
    return rma_step(rt, site, a["source"], _length(a["length"]))


@builtin("ta.wma", P("source", F), P("length", I), stateful=True)
def _wma(rt, site, a):
    return wma_step(rt, site, a["source"], _length(a["length"]))


@builtin("ta.vwma", P("source", F), P("length", I), stateful=True)
def _vwma(rt, site, a):
    length = _length(a["length"])
    volume = rt.series_at("volume", rt.bar)
    source = a["source"]
    weighted = NA if is_na(source) or is_na(volume) else source * volume
    numerator = sma_step(rt, site.sub("pv"), weighted, length)
    denominator = sma_step(rt, site.sub("v"), volume, length)
    return NA if is_na(numerator) or is_na(denominator) or denominator == 0 else numerator / denominator


@builtin("ta.hma", P("source", F), P("length", SIMPLE_INT), stateful=True)
def _hma(rt, site, a):
    length = _length(a["length"])
    half = wma_step(rt, site.sub("half"), a["source"], max(1, length // 2) if length else None)
    full = wma_step(rt, site.sub("full"), a["source"], length)
    raw = NA if is_na(half) or is_na(full) else 2 * half - full
    return wma_step(rt, site.sub("out"), raw, max(1, int(math.floor(math.sqrt(length)))) if length else None)


@builtin("ta.swma", P("source", F), stateful=True)
def _swma(rt, site, a):
    window = _clean(window_of(rt, site, a["source"], 4))
    return NA if window is None else (window[0] + 2 * window[1] + 2 * window[2] + window[3]) / 6


@builtin("ta.alma", P("series", F), P("length", SIMPLE_INT), P("offset", "simple float"), P("sigma", "simple float"),
         P("floor", "simple bool", False), stateful=True)
def _alma(rt, site, a):
    length = _length(a["length"])
    window = _clean(window_of(rt, site, a["series"], length))
    if window is None:
        return NA
    m = a["offset"] * (length - 1)
    if a["floor"]:
        m = math.floor(m)
    s = length / a["sigma"]
    norm = total = 0.0
    for i in range(length):
        weight = math.exp(-((i - m) ** 2) / (2 * s * s))
        norm += weight
        total += window[i] * weight
    return total / norm


# ---- oscillators ----------------------------------------------------------------------------------------------

@builtin("ta.rsi", P("source", F), P("length", SIMPLE_INT), stateful=True)
def _rsi(rt, site, a):
    length = _length(a["length"])
    change = change_step(rt, site.sub("chg"), a["source"])
    up = NA if is_na(change) else max(change, 0.0)
    down = NA if is_na(change) else max(-change, 0.0)
    up_avg = rma_step(rt, site.sub("up"), up, length)
    down_avg = rma_step(rt, site.sub("down"), down, length)
    if is_na(up_avg) or is_na(down_avg):
        return NA
    if down_avg == 0:
        return 100.0
    if up_avg == 0:
        return 0.0
    return 100 - 100 / (1 + up_avg / down_avg)


@builtin("ta.change", P("source", "series any"), P("length", I, 1), stateful=True)
def _change(rt, site, a):
    return change_step(rt, site, a["source"], _length(a["length"]) or 1)


@builtin("ta.mom", P("source", F), P("length", I), stateful=True)
def _mom(rt, site, a):
    return change_step(rt, site, a["source"], _length(a["length"]))


@builtin("ta.roc", P("source", F), P("length", I), stateful=True)
def _roc(rt, site, a):
    buffer = site.push("x", rt.bar, a["source"])
    previous = buffer.back(_length(a["length"]))
    source = a["source"]
    return NA if is_na(source) or is_na(previous) or previous == 0 else 100 * (source - previous) / previous


@builtin("ta.cci", P("source", F), P("length", I), stateful=True)
def _cci(rt, site, a):
    length = _length(a["length"])
    window = _clean(window_of(rt, site, a["source"], length))
    if window is None:
        return NA
    mean = math.fsum(window) / length
    deviation = math.fsum(abs(v - mean) for v in window) / length
    return NA if deviation == 0 else (a["source"] - mean) / (0.015 * deviation)


@builtin("ta.cmo", P("series", F), P("length", I), stateful=True)
def _cmo(rt, site, a):
    length = _length(a["length"])
    change = change_step(rt, site.sub("chg"), a["series"])
    gains = window_of(rt, site.sub("g"), NA if is_na(change) else max(change, 0.0), length)
    losses = window_of(rt, site.sub("l"), NA if is_na(change) else max(-change, 0.0), length)
    gains, losses = _clean(gains), _clean(losses)
    if gains is None or losses is None:
        return NA
    up, down = math.fsum(gains), math.fsum(losses)
    return NA if up + down == 0 else 100 * (up - down) / (up + down)


@builtin("ta.stoch", P("source", F), P("high", F), P("low", F), P("length", I), stateful=True)
def _stoch(rt, site, a):
    length = _length(a["length"])
    highs = _clean(window_of(rt, site, a["high"], length, "h"))
    lows = _clean(window_of(rt, site, a["low"], length, "l"))
    source = a["source"]
    if highs is None or lows is None or is_na(source):
        return NA
    top, bottom = max(highs), min(lows)
    return NA if top == bottom else 100 * (source - bottom) / (top - bottom)


@builtin("ta.wpr", P("length", I), stateful=True)
def _wpr(rt, site, a):
    length = _length(a["length"])
    highs = _clean(window_of(rt, site, rt.series_at("high", rt.bar), length, "h"))
    lows = _clean(window_of(rt, site, rt.series_at("low", rt.bar), length, "l"))
    close = rt.series_at("close", rt.bar)
    if highs is None or lows is None or is_na(close):
        return NA
    top, bottom = max(highs), min(lows)
    return NA if top == bottom else 100 * (close - top) / (top - bottom)


@builtin("ta.mfi", P("series", F), P("length", I), stateful=True)
def _mfi(rt, site, a):
    length = _length(a["length"])
    source, volume = a["series"], rt.series_at("volume", rt.bar)
    change = change_step(rt, site.sub("chg"), source)
    if is_na(change) or is_na(volume) or is_na(source):
        up = down = NA
    else:
        up = 0.0 if change <= 0 else volume * source
        down = 0.0 if change >= 0 else volume * source
    ups = _clean(window_of(rt, site.sub("u"), up, length))
    downs = _clean(window_of(rt, site.sub("d"), down, length))
    if ups is None or downs is None:
        return NA
    upper, lower = math.fsum(ups), math.fsum(downs)
    if lower == 0:
        return 100.0
    return 100 - 100 / (1 + upper / lower)


@builtin("ta.tsi", P("source", F), P("short_length", SIMPLE_INT), P("long_length", SIMPLE_INT), stateful=True)
def _tsi(rt, site, a):
    short, long = _length(a["short_length"], "short_length"), _length(a["long_length"], "long_length")
    change = change_step(rt, site.sub("chg"), a["source"])
    double = ema_step(rt, site.sub("pc2"), ema_step(rt, site.sub("pc1"), change, long), short)
    absolute = NA if is_na(change) else abs(change)
    double_abs = ema_step(rt, site.sub("ab2"), ema_step(rt, site.sub("ab1"), absolute, long), short)
    return NA if is_na(double) or is_na(double_abs) or double_abs == 0 else double / double_abs


# ---- tuples -----------------------------------------------------------------------------------------------------

@builtin("ta.macd", P("source", F), P("fastlen", SIMPLE_INT), P("slowlen", SIMPLE_INT), P("siglen", SIMPLE_INT),
         returns="tuple", stateful=True)
def _macd(rt, site, a):
    fast = ema_step(rt, site.sub("fast"), a["source"], _length(a["fastlen"], "fastlen"))
    slow = ema_step(rt, site.sub("slow"), a["source"], _length(a["slowlen"], "slowlen"))
    macd = NA if is_na(fast) or is_na(slow) else fast - slow
    signal = ema_step(rt, site.sub("signal"), macd, _length(a["siglen"], "siglen"))
    return macd, signal, NA if is_na(macd) or is_na(signal) else macd - signal


def _stdev_window(window, biased=True):
    n = len(window)
    mean = math.fsum(window) / n
    variance = math.fsum((v - mean) ** 2 for v in window) / (n if biased else max(n - 1, 1))
    return mean, variance


@builtin("ta.bb", P("series", F), P("length", I), P("mult", "simple float"), returns="tuple", stateful=True)
def _bb(rt, site, a):
    length = _length(a["length"])
    window = _clean(window_of(rt, site, a["series"], length))
    if window is None:
        return NA, NA, NA
    mean, variance = _stdev_window(window)
    deviation = a["mult"] * math.sqrt(variance)
    return mean, mean + deviation, mean - deviation


@builtin("ta.bbw", P("series", F), P("length", I), P("mult", "simple float"), stateful=True)
def _bbw(rt, site, a):
    basis, upper, lower = _bb(rt, site, a)
    return NA if is_na(basis) or basis == 0 else (upper - lower) / basis


@builtin("ta.kc", P("series", F), P("length", SIMPLE_INT), P("mult", "simple float"), P("useTrueRange", "simple bool", True),
         returns="tuple", stateful=True)
def _kc(rt, site, a):
    length = _length(a["length"])
    basis = ema_step(rt, site.sub("basis"), a["series"], length)
    span = true_range(rt, True) if a["useTrueRange"] else (rt.series_at("high", rt.bar) - rt.series_at("low", rt.bar))
    range_ema = ema_step(rt, site.sub("range"), span, length)
    if is_na(basis) or is_na(range_ema):
        return NA, NA, NA
    return basis, basis + range_ema * a["mult"], basis - range_ema * a["mult"]


@builtin("ta.kcw", P("series", F), P("length", SIMPLE_INT), P("mult", "simple float"), P("useTrueRange", "simple bool", True),
         stateful=True)
def _kcw(rt, site, a):
    basis, upper, lower = _kc(rt, site, a)
    return NA if is_na(basis) or basis == 0 else (upper - lower) / basis


@builtin("ta.dmi", P("diLength", SIMPLE_INT), P("adxSmoothing", SIMPLE_INT), returns="tuple", stateful=True)
def _dmi(rt, site, a):
    length, smoothing = _length(a["diLength"], "diLength"), _length(a["adxSmoothing"], "adxSmoothing")
    up = change_step(rt, site.sub("up"), rt.series_at("high", rt.bar))
    low_change = change_step(rt, site.sub("down"), rt.series_at("low", rt.bar))
    down = NA if is_na(low_change) else -low_change
    plus_dm = NA if is_na(up) or is_na(down) else (up if up > down and up > 0 else 0.0)
    minus_dm = NA if is_na(up) or is_na(down) else (down if down > up and down > 0 else 0.0)
    trur = rma_step(rt, site.sub("tr"), true_range(rt, False), length)
    plus_avg = rma_step(rt, site.sub("p"), plus_dm, length)
    minus_avg = rma_step(rt, site.sub("m"), minus_dm, length)
    plus = NA if is_na(plus_avg) or is_na(trur) or trur == 0 else 100 * plus_avg / trur
    minus = NA if is_na(minus_avg) or is_na(trur) or trur == 0 else 100 * minus_avg / trur
    plus = _fixnan(rt, site.sub("fp"), plus)
    minus = _fixnan(rt, site.sub("fm"), minus)
    if is_na(plus) or is_na(minus):
        dx = NA
    else:
        total = plus + minus
        dx = abs(plus - minus) / (1 if total == 0 else total)
    adx = rma_step(rt, site.sub("adx"), dx, smoothing)
    return plus, minus, NA if is_na(adx) else 100 * adx


def _fixnan(rt, site, value):
    if is_na(value):
        value = _prev(site.buf("v"), rt.bar)
    site.push("v", rt.bar, value)
    return value


@builtin("ta.supertrend", P("factor", "series float"), P("atrPeriod", SIMPLE_INT), returns="tuple", stateful=True)
def _supertrend(rt, site, a):
    atr = rma_step(rt, site.sub("atr"), true_range(rt, True), _length(a["atrPeriod"], "atrPeriod"))
    atr_buf = site.push("atr", rt.bar, atr)
    src = (rt.series_at("high", rt.bar) + rt.series_at("low", rt.bar)) / 2
    factor = a["factor"]
    upper = NA if is_na(atr) else src + factor * atr
    lower = NA if is_na(atr) else src - factor * atr
    prev_lower = _prev(site.buf("lower"), rt.bar)
    prev_upper = _prev(site.buf("upper"), rt.bar)
    prev_lower = 0.0 if is_na(prev_lower) else prev_lower
    prev_upper = 0.0 if is_na(prev_upper) else prev_upper
    close_1 = rt.series_at("close", rt.bar - 1)
    if not is_na(lower):
        lower = lower if lower > prev_lower or (not is_na(close_1) and close_1 < prev_lower) else prev_lower
    if not is_na(upper):
        upper = upper if upper < prev_upper or (not is_na(close_1) and close_1 > prev_upper) else prev_upper
    site.push("lower", rt.bar, lower)
    site.push("upper", rt.bar, upper)
    prev_super = _prev(site.buf("super"), rt.bar)
    close = rt.series_at("close", rt.bar)
    if is_na(atr_buf.back(1)):
        direction = 1
    elif not is_na(prev_super) and prev_super == prev_upper:
        direction = -1 if close > upper else 1
    else:
        direction = 1 if close < lower else -1
    trend = lower if direction == -1 else upper
    site.push("super", rt.bar, trend)
    return trend, direction


# ---- statistics / extremes ------------------------------------------------------------------------------------

def _extreme(pick, source_name):
    def impl(rt, site, a):
        source = a["source"] if "source" in a else rt.series_at(source_name, rt.bar)
        window = window_of(rt, site, source, _length(a["length"]))
        # TradingView (parity fixture s11): na when the current value is na; an older na inside the window
        # is skipped
        if window is None or is_na(source):
            return NA
        values = [v for v in window if not is_na(v)]
        return pick(values) if values else NA
    return impl


def _extreme_bars(better, source_name):
    def impl(rt, site, a):
        source = a["source"] if "source" in a else rt.series_at(source_name, rt.bar)
        window = window_of(rt, site, source, _length(a["length"]))
        if window is None:
            return NA
        best_offset, best = NA, None
        for offset, value in enumerate(window[::-1]):         # offset 0 = current bar
            # among equal extremes TradingView reports the OLDEST bar
            if not is_na(value) and (best is None or better(value, best) or value == best):
                best, best_offset = value, offset
        return NA if best is None else -best_offset
    return impl


builtin("ta.highest", P("source", F), P("length", I), overloads=((P("length", I),),), stateful=True)(_extreme(max, "high"))
builtin("ta.lowest", P("source", F), P("length", I), overloads=((P("length", I),),), stateful=True)(_extreme(min, "low"))
builtin("ta.highestbars", P("source", F), P("length", I), overloads=((P("length", I),),), returns="series int",
        stateful=True)(_extreme_bars(lambda v, best: v > best, "high"))
builtin("ta.lowestbars", P("source", F), P("length", I), overloads=((P("length", I),),), returns="series int",
        stateful=True)(_extreme_bars(lambda v, best: v < best, "low"))


@builtin("ta.range", P("source", F), P("length", I), stateful=True)
def _range(rt, site, a):
    window = _clean(window_of(rt, site, a["source"], _length(a["length"])))
    return NA if window is None else max(window) - min(window)


@builtin("ta.stdev", P("source", F), P("length", I), P("biased", "series bool", True), stateful=True)
def _stdev(rt, site, a):
    window = _clean(window_of(rt, site, a["source"], _length(a["length"])))
    return NA if window is None else math.sqrt(_stdev_window(window, truthy(a["biased"]))[1])


@builtin("ta.variance", P("source", F), P("length", I), P("biased", "series bool", True), stateful=True)
def _variance(rt, site, a):
    window = _clean(window_of(rt, site, a["source"], _length(a["length"])))
    return NA if window is None else _stdev_window(window, truthy(a["biased"]))[1]


@builtin("ta.dev", P("source", F), P("length", I), stateful=True)
def _dev(rt, site, a):
    window = _clean(window_of(rt, site, a["source"], _length(a["length"])))
    if window is None:
        return NA
    mean = math.fsum(window) / len(window)
    return math.fsum(abs(v - mean) for v in window) / len(window)


@builtin("ta.median", P("source", F), P("length", I), stateful=True)
def _median(rt, site, a):
    window = _clean(window_of(rt, site, a["source"], _length(a["length"])))
    if window is None:
        return NA
    ordered = sorted(window)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


@builtin("ta.percentrank", P("source", F), P("length", I), stateful=True)
def _percentrank(rt, site, a):
    length = _length(a["length"])
    window = _clean(window_of(rt, site, a["source"], length + 1 if length else None))
    if window is None:
        return NA
    current = window[-1]
    return 100 * sum(1 for v in window[:-1] if v <= current) / length


@builtin("ta.linreg", P("source", F), P("length", I), P("offset", "simple int"), stateful=True)
def _linreg(rt, site, a):
    length = _length(a["length"])
    window = _clean(window_of(rt, site, a["source"], length))
    if window is None:
        return NA
    xs = range(length)
    mean_x = (length - 1) / 2
    mean_y = math.fsum(window) / length
    denominator = sum((x - mean_x) ** 2 for x in xs)
    slope = 0.0 if denominator == 0 else math.fsum((x - mean_x) * (y - mean_y) for x, y in zip(xs, window)) / denominator
    intercept = mean_y - slope * mean_x
    return intercept + slope * (length - 1 - a["offset"])


@builtin("ta.correlation", P("source1", F), P("source2", F), P("length", I), stateful=True)
def _correlation(rt, site, a):
    length = _length(a["length"])
    xs = _clean(window_of(rt, site, a["source1"], length, "a"))
    ys = _clean(window_of(rt, site, a["source2"], length, "b"))
    if xs is None or ys is None:
        return NA
    mx, my = math.fsum(xs) / length, math.fsum(ys) / length
    cov = math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx, vy = math.fsum((x - mx) ** 2 for x in xs), math.fsum((y - my) ** 2 for y in ys)
    return NA if vx == 0 or vy == 0 else cov / math.sqrt(vx * vy)


# ---- volatility ------------------------------------------------------------------------------------------------

@builtin("ta.tr", P("handle_na", "simple bool", False))
def _tr_fn(rt, site, a):
    return true_range(rt, truthy(a["handle_na"]))


@builtin("ta.atr", P("length", SIMPLE_INT), stateful=True)
def _atr(rt, site, a):
    return rma_step(rt, site, true_range(rt, True), _length(a["length"]))


# ---- events ------------------------------------------------------------------------------------------------------

def _pair(rt, site, a, b):
    xa, xb = site.push("a", rt.bar, a), site.push("b", rt.bar, b)
    return a, b, xa.back(1), xb.back(1)


@builtin("ta.crossover", P("source1", F), P("source2", F), returns="series bool", stateful=True)
def _crossover(rt, site, a):
    x, y, px, py = _pair(rt, site, a["source1"], a["source2"])
    return not any(is_na(v) for v in (x, y, px, py)) and x > y and px <= py


@builtin("ta.crossunder", P("source1", F), P("source2", F), returns="series bool", stateful=True)
def _crossunder(rt, site, a):
    x, y, px, py = _pair(rt, site, a["source1"], a["source2"])
    return not any(is_na(v) for v in (x, y, px, py)) and x < y and px >= py


@builtin("ta.cross", P("source1", F), P("source2", F), returns="series bool", stateful=True)
def _cross(rt, site, a):
    x, y, px, py = _pair(rt, site, a["source1"], a["source2"])
    if any(is_na(v) for v in (x, y, px, py)):
        return False
    return (x > y and px <= py) or (x < y and px >= py)


@builtin("ta.rising", P("source", F), P("length", I), returns="series bool", stateful=True)
def _rising(rt, site, a):
    length = _length(a["length"])
    window = _clean(window_of(rt, site, a["source"], length + 1 if length else None))
    return window is not None and all(window[-1] > v for v in window[:-1])


@builtin("ta.falling", P("source", F), P("length", I), returns="series bool", stateful=True)
def _falling(rt, site, a):
    length = _length(a["length"])
    window = _clean(window_of(rt, site, a["source"], length + 1 if length else None))
    return window is not None and all(window[-1] < v for v in window[:-1])


@builtin("ta.cum", P("source", F), stateful=True)
def _cum(rt, site, a):
    previous = _prev(site.buf("sum"), rt.bar)
    total = (0.0 if is_na(previous) else previous) + (0.0 if is_na(a["source"]) else a["source"])
    site.push("sum", rt.bar, total)
    return total


@builtin("ta.barssince", P("condition", B), returns="series int", stateful=True)
def _barssince(rt, site, a):
    previous = _prev(site.buf("n"), rt.bar)
    count = 0 if truthy(a["condition"]) else (NA if is_na(previous) else previous + 1)
    site.push("n", rt.bar, count)
    return count


@builtin("ta.valuewhen", P("condition", B), P("source", "series any"), P("occurrence", "simple int"), stateful=True)
def _valuewhen(rt, site, a):
    """The source value on the n-th most recent execution where condition was true."""
    values = site.push("src", rt.bar, a["source"])
    link = site.buf("link")
    execution = len(values.values) - 1
    previous = _prev(link, rt.bar)
    latest = execution if truthy(a["condition"]) else (-1 if is_na(previous) else previous)
    link.set(rt.bar, latest)
    occurrence = a["occurrence"]
    if is_na(occurrence) or occurrence < 0:
        return NA
    index = latest
    for _ in range(int(occurrence)):
        if index <= 0:
            return NA
        index = link.values[index - 1]
    return NA if index < 0 else values.values[index]


def _pivot(better):
    def impl(rt, site, a):
        source = a["source"] if "source" in a else rt.series_at("high" if better(1, 0) else "low", rt.bar)
        left, right = _length(a["leftbars"], "leftbars"), _length(a["rightbars"], "rightbars")
        window = window_of(rt, site, source, left + right + 1)
        if window is None:
            return NA
        center = window[left]
        if is_na(center):
            return NA
        # TradingView's tie rule is asymmetric: an equal bar on the LEFT does not
        # disqualify the candidate, an equal bar on the RIGHT does (the later bar
        # becomes the pivot instead).
        before, after = window[:left], window[left + 1:]
        if any(is_na(v) for v in before + after):
            return NA
        ok = all(not better(v, center) for v in before) and all(better(center, v) for v in after)
        return center if ok else NA
    return impl


builtin("ta.pivothigh", P("source", F), P("leftbars", "series int"), P("rightbars", "series int"),
        overloads=((P("leftbars", "series int"), P("rightbars", "series int")),), stateful=True)(_pivot(lambda c, v: c > v))
builtin("ta.pivotlow", P("source", F), P("leftbars", "series int"), P("rightbars", "series int"),
        overloads=((P("leftbars", "series int"), P("rightbars", "series int")),), stateful=True)(_pivot(lambda c, v: c < v))


@builtin("ta.sar", P("start", "simple float"), P("inc", "simple float"), P("max", "simple float"), stateful=True)
def _sar(rt, site, a):
    committed = site.buf("state").before(rt.bar)      # state at the end of the previous bar
    state = dict(committed) if committed is not MISSING else {"result": NA, "maxmin": NA, "acc": NA, "below": NA}
    bar = rt.bar
    high, low, close = (rt.series_at(k, bar) for k in ("high", "low", "close"))
    first_trend = False
    if bar == 1:
        if close > rt.series_at("close", bar - 1):
            state.update(below=True, maxmin=high, result=rt.series_at("low", bar - 1))
        else:
            state.update(below=False, maxmin=low, result=rt.series_at("high", bar - 1))
        first_trend = True
        state["acc"] = a["start"]
    result = state["result"]
    if not is_na(result):
        result = result + state["acc"] * (state["maxmin"] - result)
        if state["below"]:
            if result > low:
                first_trend = True
                state["below"] = False
                result = max(high, state["maxmin"])
                state["maxmin"] = low
                state["acc"] = a["start"]
        elif result < high:
            first_trend = True
            state["below"] = True
            result = min(low, state["maxmin"])
            state["maxmin"] = high
            state["acc"] = a["start"]
        if not first_trend:
            if state["below"] and high > state["maxmin"]:
                state["maxmin"] = high
                state["acc"] = min(state["acc"] + a["inc"], a["max"])
            elif not state["below"] and low < state["maxmin"]:
                state["maxmin"] = low
                state["acc"] = min(state["acc"] + a["inc"], a["max"])
        if state["below"]:
            result = min(result, rt.series_at("low", bar - 1))
            if bar > 1:
                result = min(result, rt.series_at("low", bar - 2))
        else:
            result = max(result, rt.series_at("high", bar - 1))
            if bar > 1:
                result = max(result, rt.series_at("high", bar - 2))
    state["result"] = result
    site.push("state", bar, state)
    return result


# ---- volume / session --------------------------------------------------------------------------------------------

def _day(ms: int) -> int:
    return ms // 86_400_000


@builtin("ta.vwap", P("source", F), stateful=True)
def _vwap_fn(rt, site, a):
    return _vwap_step(rt, site, a["source"])


def _vwap_step(rt, site, source):
    day = _day(rt.series_at("time", rt.bar))
    volume = rt.series_at("volume", rt.bar)
    previous = site.buf("acc").before(rt.bar)
    if previous is MISSING or previous[0] != day:
        pv, vv = 0.0, 0.0
    else:
        _, pv, vv = previous
    if not is_na(source) and not is_na(volume):
        pv, vv = pv + source * volume, vv + volume
    site.push("acc", rt.bar, (day, pv, vv))
    return NA if vv == 0 else pv / vv


def _precomputed(name, build):
    """A whole-series built-in variable, rebuilt when the bars change (incl. a live forming bar)."""
    def impl(rt, bar):
        d = rt.data
        key = (d.size, *(float(getattr(d, f)[-1]) for f in ("open", "high", "low", "close", "volume"))) if d.size else (0,)
        entry = rt.cache.get(name)
        if entry is None or entry[0] != key:
            entry = rt.cache[name] = (key, build(rt))
        series = entry[1]
        return series[bar] if 0 <= bar < len(series) else NA
    return impl


def _obv(rt):
    out, total = [], 0.0
    close, volume = rt.data.close, rt.data.volume
    for i in range(rt.data.size):
        if i > 0 and not (math.isnan(close[i]) or math.isnan(close[i - 1]) or math.isnan(volume[i])):
            total += math.copysign(volume[i], close[i] - close[i - 1]) if close[i] != close[i - 1] else 0.0
        out.append(total)
    return out


def _accdist(rt):
    out, total = [], 0.0
    d = rt.data
    for i in range(d.size):
        span = d.high[i] - d.low[i]
        if span > 0:
            total += ((d.close[i] - d.low[i]) - (d.high[i] - d.close[i])) / span * d.volume[i]
        out.append(total)
    return out


def _vwap_series(rt):
    out, day, pv, vv = [], None, 0.0, 0.0
    d = rt.data
    for i in range(d.size):
        current = _day(int(d.time[i]))
        if current != day:
            day, pv, vv = current, 0.0, 0.0
        price = (d.high[i] + d.low[i] + d.close[i]) / 3
        if not (math.isnan(price) or math.isnan(d.volume[i])):
            pv, vv = pv + price * d.volume[i], vv + d.volume[i]
        out.append(NA if vv == 0 else pv / vv)
    return out


variable("ta.tr")(lambda rt, bar: _tr_at(rt, bar))
variable("ta.obv")(_precomputed("obv", _obv))
variable("ta.accdist")(_precomputed("accdist", _accdist))
variable("ta.vwap")(_precomputed("vwap", _vwap_series))


def _tr_at(rt, bar):
    high, low = rt.series_at("high", bar), rt.series_at("low", bar)
    previous_close = rt.series_at("close", bar - 1)
    if is_na(high) or is_na(low) or is_na(previous_close):
        return NA
    return max(high - low, abs(high - previous_close), abs(low - previous_close))
