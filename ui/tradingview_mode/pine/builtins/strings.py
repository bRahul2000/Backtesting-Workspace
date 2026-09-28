"""str.* built-ins (the array-returning str.split is a gap until arrays exist)."""
from __future__ import annotations

import math
import re

from ..registry import Param as P, builtin, constant
from ..values import NA, Color, is_na

S = "series string"

constant("format.mintick", "format.mintick", "string")
constant("format.percent", "format.percent", "string")
constant("format.volume", "format.volume", "string")
constant("format.price", "format.price", "string")
constant("format.inherit", "format.inherit", "string")


def _plain_number(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = f"{value:.8f}".rstrip("0").rstrip(".")
    return text if text not in ("-0", "") else "0"


def tostring(value, fmt=NA, mintick: float = 0.01) -> str:
    if is_na(value):
        return "NaN"
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Color):
        return value.css()
    if not isinstance(value, (int, float)):
        return str(value)
    if is_na(fmt) or fmt in ("format.inherit", "format.price"):
        return _plain_number(value)
    if fmt == "format.mintick":
        decimals = max(0, -int(math.floor(math.log10(mintick)))) if mintick > 0 else 2
        return f"{value:.{decimals}f}"
    if fmt == "format.percent":
        return f"{value:.2f}%"
    if fmt == "format.volume":
        for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
            if abs(value) >= limit:
                return f"{value / limit:.3f}".rstrip("0").rstrip(".") + suffix
        return _plain_number(value)
    # A pattern such as "#.##", "0.00" or "#,###.0"
    decimals_part = fmt.split(".", 1)[1] if "." in fmt else ""
    fixed = decimals_part.count("0")
    optional = decimals_part.count("#")
    text = f"{value:,.{fixed + optional}f}" if "," in fmt else f"{value:.{fixed + optional}f}"
    if optional and "." in text:
        head, tail = text.split(".")
        tail = tail[:fixed] + tail[fixed:].rstrip("0")
        text = head + ("." + tail if tail else "")
    return text


@builtin("str.tostring", P("value", "series any"), P("format", S, NA), returns=S)
def _tostring(rt, site, a):
    return tostring(a["value"], a["format"], rt.data.mintick if rt is not None else 0.01)


def _string_fn(name: str, fn, *params: P, returns: str = S):
    def impl(rt, site, a):
        args = [a[p.name] for p in (P("source", S), *params)]
        if is_na(args[0]):
            return NA
        return fn(*args)
    builtin(f"str.{name}", P("source", S), *params, returns=returns)(impl)


_string_fn("length", len, returns="series int")
_string_fn("upper", str.upper)
_string_fn("lower", str.lower)
_string_fn("trim", str.strip)
_string_fn("contains", lambda s, x: x in s, P("str", S), returns="series bool")
_string_fn("startswith", lambda s, x: s.startswith(x), P("str", S), returns="series bool")
_string_fn("endswith", lambda s, x: s.endswith(x), P("str", S), returns="series bool")
_string_fn("pos", lambda s, x: s.find(x) if x in s else NA, P("str", S), returns="series int")
_string_fn("replace_all", lambda s, t, r: s.replace(t, r), P("target", S), P("replacement", S))
_string_fn("repeat", lambda s, n, sep: sep.join([s] * int(n)), P("repeat", "series int"), P("separator", S, ""))


@builtin("str.replace", P("source", S), P("target", S), P("replacement", S), P("occurrence", "series int", 0), returns=S)
def _replace(rt, site, a):
    source, target, replacement, n = a["source"], a["target"], a["replacement"], int(a["occurrence"])
    if is_na(source):
        return NA
    start = -1
    for _ in range(n + 1):
        start = source.find(target, start + 1)
        if start < 0:
            return source
    return source[:start] + replacement + source[start + len(target):]


@builtin("str.substring", P("source", S), P("begin_pos", "series int"), P("end_pos", "series int", NA), returns=S)
def _substring(rt, site, a):
    source = a["source"]
    if is_na(source):
        return NA
    end = None if is_na(a["end_pos"]) else int(a["end_pos"])
    return source[int(a["begin_pos"]):end]


@builtin("str.tonumber", P("string", S))
def _tonumber(rt, site, a):
    try:
        return float(a["string"])
    except (TypeError, ValueError):
        return NA


_PLACEHOLDER = re.compile(r"\{(\d+)(?:,\s*number\s*(?:,\s*([^}]*))?)?\}")


@builtin("str.format", P("formatString", S), variadic="args", returns=S)
def _format(rt, site, a):
    args = a.get("*", [])

    def replace(match):
        index = int(match.group(1))
        if index >= len(args):
            return match.group(0)
        pattern = match.group(2)
        return tostring(args[index], pattern.strip() if pattern else NA, rt.data.mintick if rt else 0.01)

    return _PLACEHOLDER.sub(replace, a["formatString"])


# ---- Pine logs (P3.1: used by the log-instrumented parity oracles) ---------------------------------------------------

def _log(level: str):
    def impl(rt, site, a):
        message = a["message"]
        if a.get("*"):
            message = _format(rt, site, {"formatString": message, "*": a["*"]})
        # Collected on the run (bar, level, text); like TradingView, logs are not rolled back on realtime re-runs.
        rt.logs.append((rt.bar, level, "" if is_na(message) else str(message)))
        return NA
    builtin(f"log.{level}", P("message", S), variadic="args", returns="void")(impl)


for _level in ("info", "warning", "error"):
    _log(_level)
