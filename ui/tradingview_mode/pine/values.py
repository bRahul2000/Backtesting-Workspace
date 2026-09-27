"""Pine runtime values: na, colors and na-aware operators.

Values are ordinary Python objects (int, float, bool, str, tuple, Color, NA,
plot references; objects/arrays later). Nothing is forced into float arrays.
"""
from __future__ import annotations

from dataclasses import dataclass
import math


class _Na:
    """Pine's ``na``. Falsy; propagates through arithmetic and comparisons."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "na"

    def __bool__(self) -> bool:
        return False


NA = _Na()


def is_na(value) -> bool:
    return value is NA or (type(value) is float and value != value)


def truthy(value) -> bool:
    return False if is_na(value) else bool(value)


@dataclass(frozen=True)
class Color:
    r: int
    g: int
    b: int
    t: float = 0.0            # Pine transparency, 0 (opaque) .. 100 (invisible)

    @classmethod
    def from_hex(cls, text: str) -> "Color":
        text = text.lstrip("#")
        r, g, b = int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
        alpha = int(text[6:8], 16) if len(text) == 8 else 255
        return cls(r, g, b, round((1 - alpha / 255) * 100, 4))

    def with_transp(self, t: float) -> "Color":
        return Color(self.r, self.g, self.b, max(0.0, min(100.0, float(t))))

    def css(self) -> str:
        alpha = round(1 - self.t / 100, 4)
        return f"rgba({self.r},{self.g},{self.b},{alpha})"


@dataclass(frozen=True)
class OutputRef:
    """What plot()/hline() return: a reference usable by fill()."""

    node_id: int
    kind: str                 # plot | hline


# ---- arithmetic (na propagates; int/int stays int only when exact) ------------------------------

def _numeric(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def add(a, b):
    if a is NA or b is NA:
        return NA
    if isinstance(a, str) or isinstance(b, str):
        if isinstance(a, str) and isinstance(b, str):
            return a + b
        raise TypeError("Cannot add a string and a non-string.")
    return a + b


def sub(a, b):
    return NA if a is NA or b is NA else a - b


def mul(a, b):
    return NA if a is NA or b is NA else a * b


def div(a, b):
    if a is NA or b is NA or b == 0:
        return NA
    if isinstance(a, int) and isinstance(b, int) and not isinstance(a, bool) and a % b == 0:
        return a // b
    return a / b


def int_div(a, b):
    """Pine v5 division of two `const int` values: the fraction is discarded (towards zero)."""
    if a is NA or b is NA or b == 0:
        return NA
    quotient = abs(a) // abs(b)
    return quotient if (a >= 0) == (b > 0) else -quotient


def mod(a, b):
    if a is NA or b is NA or b == 0:
        return NA
    result = math.fmod(a, b)               # Pine keeps the dividend's sign
    return int(result) if isinstance(a, int) and isinstance(b, int) else result


def neg(a):
    return NA if a is NA else -a


def compare(op: str, a, b):
    if a is NA or b is NA:
        return NA          # any comparison with na is na (falsy), as in Pine; use na(x) to test
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    if op == "<":
        return a < b
    if op == ">":
        return a > b
    if op == "<=":
        return a <= b
    return a >= b


def nz(value, replacement=0):
    return replacement if is_na(value) else value


def to_float(value):
    if is_na(value):
        return NA
    return float(value)
