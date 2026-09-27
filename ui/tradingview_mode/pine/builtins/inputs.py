"""input.* built-ins. The analyzer collects each input's definition statically;
at run time an input returns the user's value (or its default) for the whole
run. input.source returns the chosen price series on every bar."""
from __future__ import annotations

from ..registry import VARIABLES, Param as P, builtin
from ..runtime import MISSING
from ..values import NA, Color

COMMON = (P("tooltip", "const string", NA), P("inline", "const string", NA), P("group", "const string", NA),
          P("confirm", "const bool", False), P("display", "const any", NA))
RANGE = (P("minval", "const float", NA), P("maxval", "const float", NA), P("step", "const float", NA))


def _definition(rt, node):
    return rt.program.input_by_node[node.id]


def _value(rt, node, override):
    definition = _definition(rt, node)
    return definition.defval if override is MISSING else override


def _register(name: str, returns: str, *params: P):
    def impl(rt, node, override):
        value = _value(rt, node, override)
        if returns.endswith("float") and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        return value
    builtin(name, *params, returns=returns, kind="input")(impl)


_register("input.int", "input int", P("defval", "const int"), P("title", "const string", NA), *RANGE,
          P("options", "const any", NA), *COMMON)
_register("input.float", "input float", P("defval", "const float"), P("title", "const string", NA), *RANGE,
          P("options", "const any", NA), *COMMON)
_register("input.bool", "input bool", P("defval", "const bool"), P("title", "const string", NA), *COMMON)
_register("input.string", "input string", P("defval", "const string"), P("title", "const string", NA),
          P("options", "const any", NA), *COMMON)
_register("input.color", "input color", P("defval", "const color"), P("title", "const string", NA), *COMMON)
_register("input.price", "input float", P("defval", "const float"), P("title", "const string", NA), *COMMON)
_register("input.text_area", "input string", P("defval", "const string"), P("title", "const string", NA), *COMMON)
_register("input.timeframe", "input string", P("defval", "const string"), P("title", "const string", NA),
          P("options", "const any", NA), *COMMON)
_register("input", "input any", P("defval", "const any"), P("title", "const string", NA), *COMMON)


@builtin("input.source", P("defval", "series float"), P("title", "const string", NA), *COMMON, returns="series float",
         kind="input")
def _source(rt, node, override):
    name = _value(rt, node, override)
    return VARIABLES[name].impl(rt, rt.bar)


def coerce_input(definition, value):
    """Validate a user-supplied input value against its definition (raises ValueError)."""
    kind = definition.kind
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
            raise ValueError("must be a whole number")
        value = int(value)
    elif kind in ("float", "price"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("must be a number")
        value = float(value)
    elif kind == "bool":
        if not isinstance(value, bool):
            raise ValueError("must be true or false")
    elif kind in ("string", "text_area", "timeframe"):
        if not isinstance(value, str):
            raise ValueError("must be text")
    elif kind == "color":
        if not isinstance(value, str):
            raise ValueError("must be a #RRGGBB[AA] color")
        value = Color.from_hex(value)
    elif kind == "source":
        if value not in ("open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4", "hlcc4"):
            raise ValueError("must be a price source")
    if definition.options and value not in definition.options:
        raise ValueError(f"must be one of {definition.options}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if definition.minval is not None and value < definition.minval:
            raise ValueError(f"must be >= {definition.minval}")
        if definition.maxval is not None and value > definition.maxval:
            raise ValueError(f"must be <= {definition.maxval}")
    return value
