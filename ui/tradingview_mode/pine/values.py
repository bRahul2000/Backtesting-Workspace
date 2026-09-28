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


# ---- arrays (P2.2-A1; see parity/P22_ARRAY_ARCHITECTURE.md) --------------------------------------------------------

class PineArray:
    """A Pine array during ONE execution: a mutable object shared by every reference (``=``, ``:=``, function
    parameters). It never outlives the execution: persistent and history slots keep ``ArraySnapshot``s."""

    __slots__ = ("items", "element", "readonly")

    def __init__(self, items: list, element: str, readonly: bool = False):
        self.items, self.element, self.readonly = items, element, readonly

    def snapshot(self) -> "ArraySnapshot":
        return ArraySnapshot(tuple(self.items), self.element)

    def __repr__(self) -> str:
        return f"array<{self.element}>{self.items!r}{' (historical)' if self.readonly else ''}"


class ArraySnapshot:
    """Immutable array contents stored by a persistent or history slot at the end of an execution."""

    __slots__ = ("items", "element")

    def __init__(self, items: tuple, element: str):
        self.items, self.element = items, element

    def materialize(self, readonly: bool = False) -> PineArray:
        """A fresh, independent array (read-only when it was retrieved with the history operator)."""
        return PineArray(list(self.items), self.element, readonly)

    def __eq__(self, other) -> bool:
        return isinstance(other, ArraySnapshot) and self.items == other.items and self.element == other.element

    def __hash__(self) -> int:
        return hash((self.items, self.element))

    def __repr__(self) -> str:
        return f"snapshot<{self.element}>{self.items!r}"


# ---- drawing objects (P2.3a; see parity/P23_DRAWING_RESEARCH.md §15) -------------------------------------------------

DRAWING_KINDS = ("line", "label", "box", "linefill", "table")      # table: P2.3b oracle-support tables-core
ARRAY_DRAWING_KINDS = ("line", "label", "box", "linefill")          # element types of arrays of drawing IDs (P2.3b)


@dataclass(frozen=True)
class DrawingRef:
    """The ID of a drawing object: an opaque, immutable value that variables, history and aliases hold. The object
    itself lives in the runtime's DrawingStore; a ref whose object was deleted or collected stays a valid value
    (``na()`` of it is true there). ``==`` / ``!=`` compare identity (TradingView q8e)."""

    kind: str
    oid: int

    def __repr__(self) -> str:
        return f"{self.kind}#{self.oid}"


# ---- chart points (P2.3b; see parity/P23B_COLLECTIONS_RESEARCH.md §16.4) ----------------------------------------------

POINT_FIELDS = {"time": "int", "index": "int", "price": "float"}


class ChartPoint:
    """A ``chart.point`` object. Every constructor call creates a new one; variables, history slots, arrays and
    aliases hold references to the same Python object, so a write through any of them (``p[1].price := v`` included)
    is seen through all of them (TradingView q9 D1-D3, Case 1). Field writes go through the runtime so that realtime
    rollback can undo them (``DrawingStore.point_set``)."""

    __slots__ = ("time", "index", "price", "pid")

    def __init__(self, time, index, price, pid: int):
        self.time, self.index, self.price, self.pid = time, index, price, pid

    def __repr__(self) -> str:
        return f"chart.point#{self.pid}(time={self.time!r}, index={self.index!r}, price={self.price!r})"
