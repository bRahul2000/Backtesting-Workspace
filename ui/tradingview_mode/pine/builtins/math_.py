"""math.* built-ins (na in -> na out, as in Pine)."""
from __future__ import annotations

import math
import random

from ..registry import Param as P, builtin, constant
from ..values import NA, is_na

N = "series float"

constant("math.pi", math.pi, "float")
constant("math.e", math.e, "float")
constant("math.phi", (1 + 5 ** 0.5) / 2, "float")
constant("math.rphi", (5 ** 0.5 - 1) / 2, "float")


def _unary(name: str, fn, returns: str = N):
    def impl(rt, site, a):
        x = a["number"]
        if is_na(x):
            return NA
        try:
            result = fn(x)
        except (ValueError, OverflowError):
            return NA
        return NA if isinstance(result, float) and (math.isnan(result) or math.isinf(result)) else result
    builtin(f"math.{name}", P("number", N), returns=returns)(impl)


_unary("abs", abs)
_unary("ceil", lambda x: int(math.ceil(x)), "series int")
_unary("floor", lambda x: int(math.floor(x)), "series int")
_unary("sqrt", math.sqrt)
_unary("exp", math.exp)
_unary("log", math.log)
_unary("log10", math.log10)
_unary("sign", lambda x: float((x > 0) - (x < 0)))
_unary("sin", math.sin)
_unary("cos", math.cos)
_unary("tan", math.tan)
_unary("asin", math.asin)
_unary("acos", math.acos)
_unary("atan", math.atan)
_unary("todegrees", math.degrees)
_unary("toradians", math.radians)


@builtin("math.round", P("number", N), P("precision", "series int", NA))
def _round(rt, site, a):
    x, precision = a["number"], a["precision"]
    if is_na(x):
        return NA
    if is_na(precision):
        return int(math.floor(x + 0.5))                  # Pine: ties round up
    factor = 10 ** int(precision)
    return math.floor(x * factor + 0.5) / factor


@builtin("math.round_to_mintick", P("number", N))
def _round_to_mintick(rt, site, a):
    x = a["number"]
    if is_na(x):
        return NA
    tick = rt.data.mintick
    return math.floor(x / tick + 0.5) * tick


@builtin("math.pow", P("base", N), P("exponent", N))
def _pow(rt, site, a):
    base, exponent = a["base"], a["exponent"]
    if is_na(base) or is_na(exponent):
        return NA
    try:
        result = math.pow(base, exponent)
    except (ValueError, OverflowError, ZeroDivisionError):
        return NA
    return result


def _variadic(name: str, fn):
    def impl(rt, site, a):
        values = [a["number0"], a["number1"], *a.get("*", [])]
        return NA if any(is_na(v) for v in values) else fn(values)
    builtin(f"math.{name}", P("number0", N), P("number1", N), variadic="numbers")(impl)


_variadic("max", max)
_variadic("min", min)
_variadic("avg", lambda values: math.fsum(values) / len(values))


@builtin("math.sum", P("source", N), P("length", "series int"), stateful=True)
def _sum(rt, site, a):
    length = a["length"]
    buffer = site.push("x", rt.bar, a["source"])
    if is_na(length) or length < 1:
        return NA
    window = buffer.window(int(length))
    return NA if window is None or any(is_na(v) for v in window) else math.fsum(window)


@builtin("math.random", P("min", N, 0.0), P("max", N, 1.0), P("seed", "simple int", NA), stateful=True)
def _random(rt, site, a):
    generator = site.scratch.get("rng")
    if generator is None:
        generator = site.scratch["rng"] = random.Random(None if is_na(a["seed"]) else int(a["seed"]))
    return generator.uniform(a["min"], a["max"])
