"""color.* built-ins and Pine's named colors."""
from __future__ import annotations

from ..registry import Param as P, builtin, constant
from ..values import NA, Color, is_na

PINE_COLORS = {
    "aqua": "00BCD4", "black": "363A45", "blue": "2196F3", "fuchsia": "E040FB", "gray": "787B86",
    "green": "4CAF50", "lime": "00E676", "maroon": "880E4F", "navy": "311B92", "olive": "808000",
    "orange": "FF9800", "purple": "9C27B0", "red": "FF5252", "silver": "B2B5BE", "teal": "00897B",
    "white": "FFFFFF", "yellow": "FFEB3B",
}
for _name, _hex in PINE_COLORS.items():
    constant(f"color.{_name}", Color.from_hex(_hex), "color")


@builtin("color.new", P("color", "series color"), P("transp", "series float", 0), returns="series color")
def _new(rt, site, a):
    color, transp = a["color"], a["transp"]
    if is_na(color):
        return NA
    return color.with_transp(0 if is_na(transp) else transp)


@builtin("color.rgb", P("red", "series float"), P("green", "series float"), P("blue", "series float"),
         P("transp", "series float", 0), returns="series color")
def _rgb(rt, site, a):
    parts = [a["red"], a["green"], a["blue"]]
    if any(is_na(p) for p in parts):
        return NA
    clamp = lambda v: int(max(0, min(255, round(v))))  # noqa: E731
    return Color(*(clamp(p) for p in parts), max(0.0, min(100.0, 0.0 if is_na(a["transp"]) else float(a["transp"]))))


def _component(name: str, field: str):
    builtin(f"color.{name}", P("color", "series color"))(
        lambda rt, site, a: NA if is_na(a["color"]) else float(getattr(a["color"], field)))


_component("r", "r")
_component("g", "g")
_component("b", "b")
_component("t", "t")


@builtin("color.from_gradient", P("value", "series float"), P("bottom_value", "series float"), P("top_value", "series float"),
         P("bottom_color", "series color"), P("top_color", "series color"), returns="series color")
def _from_gradient(rt, site, a):
    value, low, high = a["value"], a["bottom_value"], a["top_value"]
    bottom, top = a["bottom_color"], a["top_color"]
    if any(is_na(x) for x in (value, low, high, bottom, top)):
        return NA
    if high == low:
        return top
    f = max(0.0, min(1.0, (value - low) / (high - low)))
    mix = lambda x, y: x + (y - x) * f  # noqa: E731
    return Color(round(mix(bottom.r, top.r)), round(mix(bottom.g, top.g)), round(mix(bottom.b, top.b)), mix(bottom.t, top.t))
