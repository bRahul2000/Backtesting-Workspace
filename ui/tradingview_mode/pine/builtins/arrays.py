"""Pine arrays, P2.2-A1 core (see parity/P22_ARRAY_ARCHITECTURE.md and P22_ARRAY_EVIDENCE.md).

Values are ``PineArray`` objects shared by every reference within one execution; persistence and history are
handled by the runtime (end-of-execution snapshots). Arrays obtained with the history operator are read-only:
every mutating function raises TradingView's RE10051 message for them.

Only the A1 set is implemented; every other ``array.*`` stays a capability gap. Wording of errors that were not
observed on TradingView (bounds, empty arrays, na arrays, negative indices) is this engine's own.
"""
from __future__ import annotations

from ..errors import PineRuntimeError
from ..registry import Param as P, builtin
from ..values import NA, Color, PineArray, is_na

ELEMENT_TYPES = ("float", "int", "bool", "string", "color")
MAX_ELEMENTS = 100_000        # this engine's limit (TradingView documents the same number; not verified here)

RE10051 = ("Cannot modify the elements of a historical array or any slices of that array. Instead of modifying "
           "an array referenced by an ID retrieved with the `[]` operator, create a shallow copy of the array with "
           "`array.copy()`, then modify the copy or a slice of that copy.")

ARR = "series array"          # any array<T>
I, ANY = "series int", "series any"


def _array(value, name: str) -> PineArray:
    if isinstance(value, PineArray):
        return value
    if is_na(value):
        raise PineRuntimeError(f"`{name}()`: the array is na.", 0)
    raise PineRuntimeError(f"`{name}()`: the `id` argument is not an array.", 0)


def _mutable(value, name: str) -> PineArray:
    arr = _array(value, name)
    if arr.readonly:
        raise PineRuntimeError(RE10051, 0)
    return arr


def coerce_element(value, element: str, name: str):
    """A value stored into an array<element> (int -> float for float arrays; na always allowed)."""
    if is_na(value):
        return NA
    if element == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PineRuntimeError(f"`{name}()`: a float array cannot store {value!r}.", 0)
        return float(value)
    if element == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise PineRuntimeError(f"`{name}()`: an int array cannot store {value!r}.", 0)
        return value
    if element == "bool":
        if not isinstance(value, bool):
            raise PineRuntimeError(f"`{name}()`: a bool array cannot store {value!r}.", 0)
        return value
    if element == "string":
        if not isinstance(value, str):
            raise PineRuntimeError(f"`{name}()`: a string array cannot store {value!r}.", 0)
        return value
    if element == "color":
        if not isinstance(value, Color):
            raise PineRuntimeError(f"`{name}()`: a color array cannot store {value!r}.", 0)
        return value
    raise PineRuntimeError(f"Arrays of `{element}` are not implemented yet.", 0)


def _index(arr: PineArray, index, name: str) -> int:
    if is_na(index):
        raise PineRuntimeError(f"`{name}()`: the index is na.", 0)
    index = int(index)
    if index < 0:
        raise PineRuntimeError(f"`{name}()`: negative array indices are not implemented yet.", 0)
    if index >= len(arr.items):
        raise PineRuntimeError(f"`{name}()`: index {index} is out of bounds; the array size is {len(arr.items)}.", 0)
    return index


def _grow(arr: PineArray, name: str) -> None:
    if len(arr.items) >= MAX_ELEMENTS:
        raise PineRuntimeError(f"`{name}()`: Current Pine engine limit: an array holds at most {MAX_ELEMENTS:,} "
                               "elements.", 0)


def _nonempty(arr: PineArray, name: str) -> None:
    if not arr.items:
        raise PineRuntimeError(f"`{name}()`: the array is empty.", 0)


# ---- constructors ----------------------------------------------------------------------------------------------

def _new(element: str):
    def impl(rt, site, a):
        size = a["size"]
        if is_na(size) or int(size) < 0:
            raise PineRuntimeError(f"`array.new_{element}()`: the size must be a non-negative integer.", 0)
        if int(size) > MAX_ELEMENTS:
            raise PineRuntimeError(f"`array.new_{element}()`: Current Pine engine limit: an array holds at most "
                                   f"{MAX_ELEMENTS:,} elements.", 0)
        initial = coerce_element(a["initial_value"], element, f"array.new_{element}")
        return PineArray([initial] * int(size), element)
    return impl


for _element, _param in (("float", "series float"), ("int", "series int"), ("bool", "series bool"),
                         ("string", "series string"), ("color", "series color")):
    builtin(f"array.new_{_element}", P("size", I, 0), P("initial_value", _param, NA),
            returns=f"series array<{_element}>")(_new(_element))


@builtin("array.from", P("value0", ANY), variadic="values", returns="array_from")
def _from(rt, site, a):
    values = [a["value0"], *a.get("*", [])]
    present = [v for v in values if not is_na(v)]
    if not present or all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present):
        element = "int" if present and all(isinstance(v, int) for v in present) else "float"
    elif all(isinstance(v, bool) for v in present):
        element = "bool"
    elif all(isinstance(v, str) for v in present):
        element = "string"
    elif all(isinstance(v, Color) for v in present):
        element = "color"
    else:
        raise PineRuntimeError("`array.from()`: all values must have the same type.", 0)
    if len(values) > MAX_ELEMENTS:
        raise PineRuntimeError(f"`array.from()`: Current Pine engine limit: an array holds at most {MAX_ELEMENTS:,} "
                               "elements.", 0)
    return PineArray([coerce_element(v, element, "array.from") for v in values], element)


# ---- reading --------------------------------------------------------------------------------------------------

@builtin("array.size", P("id", ARR), returns="series int")
def _size(rt, site, a):
    return len(_array(a["id"], "array.size").items)


@builtin("array.get", P("id", ARR), P("index", I), returns="element")
def _get(rt, site, a):
    arr = _array(a["id"], "array.get")
    return arr.items[_index(arr, a["index"], "array.get")]


@builtin("array.first", P("id", ARR), returns="element")
def _first(rt, site, a):
    arr = _array(a["id"], "array.first")
    _nonempty(arr, "array.first")
    return arr.items[0]


@builtin("array.last", P("id", ARR), returns="element")
def _last(rt, site, a):
    arr = _array(a["id"], "array.last")
    _nonempty(arr, "array.last")
    return arr.items[-1]


@builtin("array.copy", P("id", ARR), returns="same_array")
def _copy(rt, site, a):
    arr = _array(a["id"], "array.copy")          # copying a historical array is allowed (RE10051's advice)
    return PineArray(list(arr.items), arr.element)


# ---- mutating (never on a historical array) --------------------------------------------------------------------

@builtin("array.push", P("id", ARR), P("value", ANY), returns="void")
def _push(rt, site, a):
    arr = _mutable(a["id"], "array.push")
    _grow(arr, "array.push")
    arr.items.append(coerce_element(a["value"], arr.element, "array.push"))
    return NA


@builtin("array.unshift", P("id", ARR), P("value", ANY), returns="void")
def _unshift(rt, site, a):
    arr = _mutable(a["id"], "array.unshift")
    _grow(arr, "array.unshift")
    arr.items.insert(0, coerce_element(a["value"], arr.element, "array.unshift"))
    return NA


@builtin("array.set", P("id", ARR), P("index", I), P("value", ANY), returns="void")
def _set(rt, site, a):
    arr = _mutable(a["id"], "array.set")
    arr.items[_index(arr, a["index"], "array.set")] = coerce_element(a["value"], arr.element, "array.set")
    return NA


@builtin("array.pop", P("id", ARR), returns="element")
def _pop(rt, site, a):
    arr = _mutable(a["id"], "array.pop")
    _nonempty(arr, "array.pop")
    return arr.items.pop()


@builtin("array.shift", P("id", ARR), returns="element")
def _shift(rt, site, a):
    arr = _mutable(a["id"], "array.shift")
    _nonempty(arr, "array.shift")
    return arr.items.pop(0)


@builtin("array.clear", P("id", ARR), returns="void")
def _clear(rt, site, a):
    _mutable(a["id"], "array.clear").items.clear()
    return NA
