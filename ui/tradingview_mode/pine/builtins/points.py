"""chart.point (P2.3b; see parity/P23B_COLLECTIONS_RESEARCH.md §16.4).

Every constructor call creates a new ``ChartPoint``; references to it are shared by variables, history, arrays and
aliases (TradingView q9 D1-D3, Case 1). ``copy`` creates a new independent point. ``now(price = close)`` takes the
current bar's ``time`` and ``bar_index`` (reference manual: ``price`` is optional and defaults to ``close``);
``from_index`` leaves ``time`` na and ``from_time`` leaves ``index`` na (manual). Field reads and writes are handled
by the runtime (``p.price``, ``p.price := v``).
"""
from __future__ import annotations

from ..errors import PineRuntimeError
from ..registry import Param as P, builtin
from ..values import NA, ChartPoint, is_na

I, F, PT = "series int", "series float", "series chart.point"
_CLOSE = object()                      # `now()` without `price`: the current bar's close


def _int(value):
    return NA if is_na(value) else int(value)


def _float(value):
    return NA if is_na(value) else float(value)


def _point(rt, time, index, price) -> ChartPoint:
    return ChartPoint(_int(time), _int(index), _float(price), rt.drawings.new_pid())


@builtin("chart.point.new", P("time", I), P("index", I), P("price", F), returns=PT)
def _new(rt, site, a):
    return _point(rt, a["time"], a["index"], a["price"])


@builtin("chart.point.now", P("price", F, _CLOSE), returns=PT)
def _now(rt, site, a):
    price = rt.series_at("close", rt.bar) if a["price"] is _CLOSE else a["price"]
    return _point(rt, rt.series_at("time", rt.bar), rt.bar, price)


@builtin("chart.point.from_index", P("index", I), P("price", F), returns=PT)
def _from_index(rt, site, a):
    return _point(rt, NA, a["index"], a["price"])


@builtin("chart.point.from_time", P("time", I), P("price", F), returns=PT)
def _from_time(rt, site, a):
    return _point(rt, a["time"], NA, a["price"])


@builtin("chart.point.copy", P("id", PT), returns=PT)
def _copy(rt, site, a):
    point = a["id"]
    if not isinstance(point, ChartPoint):
        raise PineRuntimeError("`chart.point.copy()`: the chart point is na.", 0)
    return _point(rt, point.time, point.index, point.price)
