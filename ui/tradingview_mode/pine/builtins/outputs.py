"""Plot-family built-ins (global scope only) and their constants."""
from __future__ import annotations

from ..outputs import Output
from ..registry import Param as P, builtin, constant
from ..runtime import float_or_na
from ..values import NA, Color, OutputRef, is_na, truthy

for _name in ("line", "linebr", "stepline", "stepline_diamond", "steplinebr", "histogram", "columns", "area", "areabr",
              "circles", "cross"):
    constant(f"plot.style_{_name}", _name, "string")
for _name in ("xcross", "cross", "triangleup", "triangledown", "flag", "circle", "arrowup", "arrowdown", "labelup",
              "labeldown", "square", "diamond"):
    constant(f"shape.{_name}", _name, "string")
for _name in ("abovebar", "belowbar", "top", "bottom", "absolute"):
    constant(f"location.{_name}", _name, "string")
for _name in ("auto", "tiny", "small", "normal", "large", "huge"):
    constant(f"size.{_name}", _name, "string")
for _name in ("solid", "dotted", "dashed"):
    constant(f"hline.style_{_name}", _name, "string")
for _name in ("all", "none", "data_window", "status_line", "pane", "price_scale"):
    constant(f"display.{_name}", _name, "string")
for _name in ("right", "left", "none"):
    constant(f"scale.{_name}", _name, "string")

DEFAULT_COLOR = Color.from_hex("2962FF")
COMMON = (P("editable", "const bool", True), P("show_last", "input int", NA), P("display", "input any", "all"),
          P("format", "input string", NA), P("precision", "input int", NA), P("force_overlay", "const bool", False))


def _output(rt, node, kind: str, title) -> Output:
    output = rt.outputs.get(node.id)
    if output is None:
        output = rt.outputs[node.id] = Output(node.id, kind, title if isinstance(title, str) else "")
    return output


def _color(value):
    return value if isinstance(value, Color) else None


@builtin("plot", P("series", "series float"), P("title", "const string", NA), P("color", "series color", DEFAULT_COLOR),
         P("linewidth", "input int", 1), P("style", "input string", "line"), P("trackprice", "input bool", False),
         P("histbase", "input float", 0.0), P("offset", "simple int", 0), P("join", "input bool", False), *COMMON,
         returns="series plot", kind="output")
def _plot(rt, node, a):
    output = _output(rt, node, "plot", a["title"])
    output.options = {"style": a["style"], "linewidth": int(a["linewidth"]) if not is_na(a["linewidth"]) else 1,
                      "offset": 0 if is_na(a["offset"]) else int(a["offset"]), "trackprice": bool(a["trackprice"]),
                      "histbase": float_or_na(a["histbase"]) if not is_na(a["histbase"]) else 0.0,
                      "display": a["display"] if isinstance(a["display"], str) else "all"}
    output.values.set(rt.bar, float_or_na(a["series"]))
    output.colors.set(rt.bar, _color(a["color"]))
    return OutputRef(node.id, "plot")


_SHAPE_COMMON = (P("location", "input string", "abovebar"), P("color", "series color", DEFAULT_COLOR),
                 P("offset", "simple int", 0), P("text", "const string", ""), P("textcolor", "series color", NA),
                 P("editable", "const bool", True), P("size", "const string", "auto"), P("show_last", "input int", NA),
                 P("display", "input any", "all"), P("format", "input string", NA), P("precision", "input int", NA),
                 P("force_overlay", "const bool", False))


def _shape_like(rt, node, a, kind: str, glyph: str):
    output = _output(rt, node, kind, a["title"])
    location = a["location"] if isinstance(a["location"], str) else "abovebar"
    output.options = {"style" if kind == "shape" else "char": glyph, "location": location,
                      "size": a["size"] if isinstance(a["size"], str) else "auto",
                      "offset": 0 if is_na(a["offset"]) else int(a["offset"]),
                      "textcolor": _color(a["textcolor"]).css() if _color(a["textcolor"]) else None}
    series = a["series"]
    hit = float_or_na(series) if location == "absolute" else (truthy(series) if not is_na(series) else False)
    output.values.set(rt.bar, hit)
    output.colors.set(rt.bar, _color(a["color"]))
    output.texts.set(rt.bar, a["text"] if isinstance(a["text"], str) else "")
    return NA


@builtin("plotshape", P("series", "series any"), P("title", "const string", NA), P("style", "input string", "xcross"),
         *_SHAPE_COMMON, returns="void", kind="output")
def _plotshape(rt, node, a):
    return _shape_like(rt, node, a, "shape", a["style"] if isinstance(a["style"], str) else "xcross")


@builtin("plotchar", P("series", "series any"), P("title", "const string", NA), P("char", "input string", "★"),
         *_SHAPE_COMMON, returns="void", kind="output")
def _plotchar(rt, node, a):
    char = a["char"] if isinstance(a["char"], str) and a["char"] else "★"
    return _shape_like(rt, node, a, "char", char[0])


@builtin("hline", P("price", "input float"), P("title", "const string", NA), P("color", "input color", Color.from_hex("787B86")),
         P("linestyle", "input string", "solid"), P("linewidth", "input int", 1), P("editable", "const bool", True),
         P("display", "input any", "all"), returns="series hline", kind="output")
def _hline(rt, node, a):
    output = _output(rt, node, "hline", a["title"])
    output.options = {"linestyle": a["linestyle"] if isinstance(a["linestyle"], str) else "solid",
                      "linewidth": 1 if is_na(a["linewidth"]) else int(a["linewidth"])}
    output.values.set(rt.bar, float_or_na(a["price"]))
    output.colors.set(rt.bar, _color(a["color"]))
    return OutputRef(node.id, "hline")


@builtin("fill", P("hline1", "series any"), P("hline2", "series any"), P("color", "series color", DEFAULT_COLOR.with_transp(90)),
         P("title", "const string", NA), P("editable", "const bool", True), P("show_last", "input int", NA),
         P("fillgaps", "const bool", False), P("display", "input any", "all"), returns="void", kind="output")
def _fill(rt, node, a):
    first, second = a["hline1"], a["hline2"]
    if not isinstance(first, OutputRef) or not isinstance(second, OutputRef):
        rt.fail("fill() needs two plot() or hline() references.", node)
    if first.kind != second.kind:
        rt.fail("fill() between a plot and an hline is not allowed; fill two plots or two hlines.", node)
    output = _output(rt, node, "fill", a["title"])
    output.options = {"refs": (first.node_id, second.node_id), "fillgaps": bool(a["fillgaps"])}
    output.colors.set(rt.bar, _color(a["color"]))
    return NA


@builtin("bgcolor", P("color", "series color"), P("offset", "simple int", 0), P("editable", "const bool", True),
         P("show_last", "input int", NA), P("title", "const string", NA), P("display", "input any", "all"),
         P("force_overlay", "const bool", False), returns="void", kind="output")
def _bgcolor(rt, node, a):
    output = _output(rt, node, "bgcolor", a["title"])
    output.options = {"offset": 0 if is_na(a["offset"]) else int(a["offset"])}
    output.colors.set(rt.bar, _color(a["color"]))
    return NA


@builtin("barcolor", P("color", "series color"), P("offset", "simple int", 0), P("editable", "const bool", True),
         P("show_last", "input int", NA), P("title", "const string", NA), P("display", "input any", "all"),
         returns="void", kind="output")
def _barcolor(rt, node, a):
    output = _output(rt, node, "barcolor", a["title"])
    output.options = {"offset": 0 if is_na(a["offset"]) else int(a["offset"])}
    output.colors.set(rt.bar, _color(a["color"]))
    return NA

