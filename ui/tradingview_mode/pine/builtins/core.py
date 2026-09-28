"""Core built-ins: price series, bar index, na handling, casts, declarations."""
from __future__ import annotations

import math
import time as _time

from ..errors import PineRuntimeError
from ..registry import Param as P, builtin, constant, variable
from ..runtime import MISSING, float_or_na
from ..values import DrawingRef, NA, Color, is_na, truthy

ANY = "series any"

# ---- price series and bar info -------------------------------------------------------------------------

for _name in ("open", "high", "low", "close", "volume"):
    variable(_name)(lambda rt, bar, _name=_name: rt.series_at(_name, bar))


def _combo(*fields, divisor):
    def impl(rt, bar):
        parts = [rt.series_at(f, bar) for f in fields]
        return NA if any(p is NA for p in parts) else sum(parts) / divisor
    return impl


variable("hl2")(_combo("high", "low", divisor=2))
variable("hlc3")(_combo("high", "low", "close", divisor=3))
variable("ohlc4")(_combo("open", "high", "low", "close", divisor=4))
variable("hlcc4")(_combo("high", "low", "close", "close", divisor=4))


@variable("bar_index", returns="series int")
def _bar_index(rt, bar):
    return bar if bar >= 0 else NA


@variable("last_bar_index", returns="series int")
def _last_bar_index(rt, bar):
    return rt.data.size - 1


@variable("time", returns="series int")
def _time_var(rt, bar):
    return rt.series_at("time", bar)


@variable("time_close", returns="series int")
def _time_close(rt, bar):
    t = rt.series_at("time", bar)
    if t is NA:
        return NA
    close_time = rt.data.close_time                  # requested contexts: exact close (weeks, months)
    if close_time is not None and 0 <= bar < len(close_time):
        return int(close_time[bar])
    return t + rt.data.timeframe_seconds * 1000


@variable("last_bar_time", returns="series int")
def _last_bar_time(rt, bar):
    return int(rt.data.time[-1]) if rt.data.size else NA


@variable("timenow", returns="series int")
def _timenow(rt, bar):
    return int(_time.time() * 1000)


constant("na", NA, "float")

# ---- na handling ---------------------------------------------------------------------------------------------


@builtin("na", P("x", ANY), returns="series bool")
def _na(rt, site, a):
    x = a["x"]
    if isinstance(x, DrawingRef):                    # a deleted / collected drawing's ID reads as na (q8, q8g)
        return not rt.drawings.alive(x)
    return is_na(x)


@builtin("nz", P("source", ANY), P("replacement", ANY, 0))
def _nz(rt, site, a):
    return a["replacement"] if is_na(a["source"]) else a["source"]


@builtin("fixnan", P("source", ANY), stateful=True)
def _fixnan(rt, site, a):
    """The last non-na value (carried forward)."""
    value = a["source"]
    if is_na(value):
        previous = site.buf("last").before(rt.bar)
        value = NA if previous is MISSING else previous
    site.push("last", rt.bar, value)
    return value


# ---- casts ----------------------------------------------------------------------------------------------------


@builtin("int", P("x", ANY), returns="series int")
def _int(rt, site, a):
    x = a["x"]
    return NA if is_na(x) else int(math.trunc(x))


@builtin("float", P("x", ANY))
def _float(rt, site, a):
    return float_or_na(a["x"])


@builtin("bool", P("x", ANY), returns="series bool")
def _bool(rt, site, a):
    return truthy(a["x"])


@builtin("string", P("x", ANY), returns="series string")
def _string(rt, site, a):
    return a["x"] if isinstance(a["x"], str) else ("" if is_na(a["x"]) else str(a["x"]))


@builtin("color", P("x", ANY), returns="series color")
def _color(rt, site, a):
    return a["x"] if isinstance(a["x"], Color) else NA


# ---- declarations and misc -------------------------------------------------------------------------------------

_DECLARATION = tuple(P(name, "const any", NA) for name in (
    "title", "shorttitle", "overlay", "format", "precision", "scale", "max_bars_back", "timeframe", "timeframe_gaps",
    "explicit_plot_zorder", "max_lines_count", "max_labels_count", "max_boxes_count", "calc_bars_count",
    "max_polylines_count", "dynamic_requests", "behind_chart"))
builtin("indicator", *_DECLARATION, returns="void", kind="declaration")(lambda rt, site, a: NA)


@builtin("max_bars_back", P("var", ANY), P("num", "const int"), returns="void")
def _max_bars_back(rt, site, a):
    return NA


@builtin("runtime.error", P("message", "series string"), returns="void")
def _runtime_error(rt, site, a):
    raise PineRuntimeError(f"runtime.error: {a['message']}", 0, rt.bar)


@builtin("alert", P("message", "series string"), P("freq", "input string", "alert.freq_once_per_bar"), returns="void",
         note="alerts are accepted but not delivered by this engine.")
def _alert(rt, site, a):
    return NA


@builtin("alertcondition", P("condition", "series bool"), P("title", "const string", NA), P("message", "const string", NA),
         returns="void", note="alert conditions are accepted but no alerts are delivered by this engine.")
def _alertcondition(rt, site, a):
    return NA


for _name in ("freq_all", "freq_once_per_bar", "freq_once_per_bar_close"):
    constant(f"alert.{_name}", f"alert.{_name}", "string")
