"""Drawing objects P2.3a: line, label, box, linefill (see parity/P23_DRAWING_RESEARCH.md §15.14).

Every function works on the runtime's DrawingStore through ``DrawingRef``s. Semantics recorded on real TradingView:
getters of a deleted / collected / na ID return na, setters and ``delete`` are no-ops (q8, q8g); ``xloc.bar_index``
x-coordinates may not be more than 500 bars in the future (RE10020, q8 Case 6) nor, as documented, more than 10,000
bars in the past. ``copy`` of a dead ID returns na and ``linefill.new`` with a dead line returns na: engine policies.
Only the x/y overloads exist (``chart.point`` is P2.3b). Parameters whose rendering is not implemented
(``force_overlay``, fonts, text formatting, text wrapping) are accepted only with their default value.
"""
from __future__ import annotations

from ..errors import PineRuntimeError
from ..registry import Param as P, builtin, constant
from ..values import NA, Color, DrawingRef, is_na

RE10020 = "Objects positioned using xloc.bar_index cannot be drawn further than 500 bars into the future."
PAST_LIMIT = "Objects positioned using xloc.bar_index cannot be drawn further than 10000 bars into the past."
MAX_FUTURE, MAX_PAST = 500, 10_000

BLUE, BLACK, WHITE = Color.from_hex("#2196F3"), Color.from_hex("#363A45"), Color.from_hex("#FFFFFF")
_VERSION_DEFAULT = object()          # label textcolor: black in v5, white in v6 (v6 migration guide)

# ---- constants -------------------------------------------------------------------------------------------------------
for _name in ("bar_index", "bar_time"):
    constant(f"xloc.{_name}", _name, "string")
for _name in ("price", "abovebar", "belowbar"):
    constant(f"yloc.{_name}", _name, "string")
for _name in ("none", "left", "right", "both"):
    constant(f"extend.{_name}", _name, "string")
for _name in ("solid", "dotted", "dashed", "arrow_left", "arrow_right", "arrow_both"):
    constant(f"line.style_{_name}", _name, "string")
for _name in ("none", "xcross", "cross", "triangleup", "triangledown", "flag", "circle", "arrowup", "arrowdown",
              "label_up", "label_down", "label_left", "label_right", "label_lower_left", "label_lower_right",
              "label_upper_left", "label_upper_right", "label_center", "square", "diamond", "text_outline"):
    constant(f"label.style_{_name}", _name, "string")
for _name in ("left", "center", "right", "top", "bottom"):
    constant(f"text.align_{_name}", _name, "string")

I, F, S, C = "series int", "series float", "series string", "series color"


def _store(rt):
    return rt.drawings


def _check_x(rt, x, xloc) -> None:
    if is_na(x) or xloc != "bar_index":
        return
    if int(x) > rt.bar + MAX_FUTURE:
        raise PineRuntimeError(RE10020, 0)
    if int(x) < rt.bar - MAX_PAST:
        raise PineRuntimeError(PAST_LIMIT, 0)


def _int(value):
    return NA if is_na(value) else int(value)


def _float(value):
    return NA if is_na(value) else float(value)


def _defaults_only(name: str, a: dict, *params: str) -> None:
    for param in params:
        value = a.get(param, NA)
        if not (is_na(value) or value is False):
            raise PineRuntimeError(f"`{name}()`: the `{param}` argument is not implemented yet (only its default).", 0)


def _getter(kind: str, key: str, returns: str, convert=lambda v: v):
    def impl(rt, site, a):
        drawing = _store(rt).get(a["id"])
        return NA if drawing is None or is_na(drawing.props.get(key, NA)) else convert(drawing.props[key])
    builtin(f"{kind}.get_{key}", P("id", f"series {kind}"), returns=returns)(impl)


def _setter(kind: str, name: str, keys: tuple, types: tuple, x_keys: tuple = (), convert: dict | None = None):
    """``kind.set_<name>(id, *values)``: sets ``keys``; x-coordinates in ``x_keys`` are range-checked."""
    convert = convert or {}

    def impl(rt, site, a):
        store = _store(rt)
        drawing = store.get(a["id"])
        if drawing is None:
            return NA                                   # dead / na: no-op
        values = {key: convert.get(key, lambda v: v)(a[key]) for key in keys}
        xloc = values.get("xloc", drawing.props.get("xloc"))
        for key in x_keys:
            _check_x(rt, values.get(key, drawing.props.get(key)), xloc)
        for key, value in values.items():
            store.set(a["id"], key, value)
        return NA
    builtin(f"{kind}.set_{name}", P("id", f"series {kind}"), *(P(k, t) for k, t in zip(keys, types)),
            returns="void")(impl)


def _copy_delete(kind: str, copy: bool = True) -> None:
    if copy:
        builtin(f"{kind}.copy", P("id", f"series {kind}"), returns=f"series {kind}")(
            lambda rt, site, a: _store(rt).copy(a["id"], rt.bar))

    def delete(rt, site, a):
        _store(rt).delete(a["id"])
        return NA
    builtin(f"{kind}.delete", P("id", f"series {kind}"), returns="void")(delete)


# ---- line --------------------------------------------------------------------------------------------------------------

@builtin("line.new", P("x1", I), P("y1", F), P("x2", I), P("y2", F), P("xloc", S, "bar_index"), P("extend", S, "none"),
         P("color", C, BLUE), P("style", S, "solid"), P("width", I, 1), P("force_overlay", "const bool", False),
         returns="series line")
def _line_new(rt, site, a):
    _defaults_only("line.new", a, "force_overlay")
    for key in ("x1", "x2"):
        _check_x(rt, a[key], a["xloc"])
    props = {"x1": _int(a["x1"]), "y1": _float(a["y1"]), "x2": _int(a["x2"]), "y2": _float(a["y2"]), "xloc": a["xloc"],
             "extend": a["extend"], "color": a["color"], "style": a["style"], "width": _int(a["width"])}
    return _store(rt).create("line", props, rt.bar)


for _key, _type, _conv in (("x1", I, _int), ("y1", F, _float), ("x2", I, _int), ("y2", F, _float)):
    _setter("line", _key, (_key,), (_type,), x_keys=(_key,) if _key.startswith("x") else (), convert={_key: _conv})
    _getter("line", _key, _type, _conv)
_setter("line", "xy1", ("x1", "y1"), (I, F), x_keys=("x1",), convert={"x1": _int, "y1": _float})
_setter("line", "xy2", ("x2", "y2"), (I, F), x_keys=("x2",), convert={"x2": _int, "y2": _float})
_setter("line", "xloc", ("x1", "x2", "xloc"), (I, I, S), x_keys=("x1", "x2"), convert={"x1": _int, "x2": _int})
_setter("line", "extend", ("extend",), (S,))
_setter("line", "color", ("color",), (C,))
_setter("line", "style", ("style",), (S,))
_setter("line", "width", ("width",), (I,), convert={"width": _int})
_copy_delete("line")


@builtin("line.get_price", P("id", "series line"), P("x", I), returns="series float")
def _line_get_price(rt, site, a):
    """The line's price at bar index ``x``, extrapolated beyond its endpoints (xloc.bar_index lines only)."""
    drawing = _store(rt).get(a["id"])
    if drawing is None or is_na(a["x"]):
        return NA
    p = drawing.props
    if p["xloc"] != "bar_index":
        raise PineRuntimeError("`line.get_price()` works only for lines with `xloc.bar_index` x-coordinates.", 0)
    if any(is_na(p[k]) for k in ("x1", "y1", "x2", "y2")):
        return NA
    if p["x1"] == p["x2"]:
        return p["y1"] if int(a["x"]) == p["x1"] else NA
    return p["y1"] + (p["y2"] - p["y1"]) * (int(a["x"]) - p["x1"]) / (p["x2"] - p["x1"])


# ---- label -------------------------------------------------------------------------------------------------------------

@builtin("label.new", P("x", I), P("y", F), P("text", S, ""), P("xloc", S, "bar_index"), P("yloc", S, "price"),
         P("color", C, BLUE), P("style", S, "label_down"), P("textcolor", C, _VERSION_DEFAULT), P("size", S, "normal"),
         P("textalign", S, "center"), P("tooltip", S, NA), P("text_font_family", S, NA),
         P("force_overlay", "const bool", False), P("text_formatting", S, NA), returns="series label")
def _label_new(rt, site, a):
    _defaults_only("label.new", a, "text_font_family", "force_overlay", "text_formatting")
    _check_x(rt, a["x"], a["xloc"])
    textcolor = a["textcolor"]
    if textcolor is _VERSION_DEFAULT:
        textcolor = WHITE if (rt.program.script.version or 5) >= 6 else BLACK
    props = {"x": _int(a["x"]), "y": _float(a["y"]), "text": a["text"], "xloc": a["xloc"], "yloc": a["yloc"],
             "color": a["color"], "style": a["style"], "textcolor": textcolor, "size": a["size"],
             "textalign": a["textalign"], "tooltip": a["tooltip"]}
    return _store(rt).create("label", props, rt.bar)


_setter("label", "x", ("x",), (I,), x_keys=("x",), convert={"x": _int})
_setter("label", "y", ("y",), (F,), convert={"y": _float})
_setter("label", "xy", ("x", "y"), (I, F), x_keys=("x",), convert={"x": _int, "y": _float})
_setter("label", "xloc", ("x", "xloc"), (I, S), x_keys=("x",), convert={"x": _int})
for _key in ("yloc", "text", "style", "size", "textalign", "tooltip"):
    _setter("label", _key, (_key,), (S,))
for _key in ("color", "textcolor"):
    _setter("label", _key, (_key,), (C,))
_getter("label", "x", I, _int)
_getter("label", "y", F, _float)
_getter("label", "text", S)
_copy_delete("label")


# ---- box ---------------------------------------------------------------------------------------------------------------

@builtin("box.new", P("left", I), P("top", F), P("right", I), P("bottom", F), P("border_color", C, BLUE),
         P("border_width", I, 1), P("border_style", S, "solid"), P("extend", S, "none"), P("xloc", S, "bar_index"),
         P("bgcolor", C, BLUE), P("text", S, ""), P("text_size", S, "auto"), P("text_color", C, BLACK),
         P("text_halign", S, "center"), P("text_valign", S, "center"), P("text_wrap", S, NA),
         P("text_font_family", S, NA), P("force_overlay", "const bool", False), P("text_formatting", S, NA),
         returns="series box")
def _box_new(rt, site, a):
    _defaults_only("box.new", a, "text_wrap", "text_font_family", "force_overlay", "text_formatting")
    for key in ("left", "right"):
        _check_x(rt, a[key], a["xloc"])
    props = {"left": _int(a["left"]), "top": _float(a["top"]), "right": _int(a["right"]),
             "bottom": _float(a["bottom"]), "border_color": a["border_color"], "border_width": _int(a["border_width"]),
             "border_style": a["border_style"], "extend": a["extend"], "xloc": a["xloc"], "bgcolor": a["bgcolor"],
             "text": a["text"], "text_size": a["text_size"], "text_color": a["text_color"],
             "text_halign": a["text_halign"], "text_valign": a["text_valign"]}
    return _store(rt).create("box", props, rt.bar)


for _key, _type, _conv in (("left", I, _int), ("top", F, _float), ("right", I, _int), ("bottom", F, _float)):
    _setter("box", _key, (_key,), (_type,), x_keys=(_key,) if _type == I else (), convert={_key: _conv})
    _getter("box", _key, _type, _conv)
_setter("box", "lefttop", ("left", "top"), (I, F), x_keys=("left",), convert={"left": _int, "top": _float})
_setter("box", "rightbottom", ("right", "bottom"), (I, F), x_keys=("right",), convert={"right": _int, "bottom": _float})
for _key in ("bgcolor", "border_color", "text_color"):
    _setter("box", _key, (_key,), (C,))
_setter("box", "border_width", ("border_width",), (I,), convert={"border_width": _int})
for _key in ("border_style", "extend", "text", "text_size", "text_halign", "text_valign"):
    _setter("box", _key, (_key,), (S,))
_copy_delete("box")


# ---- linefill ----------------------------------------------------------------------------------------------------------

@builtin("linefill.new", P("line1", "series line"), P("line2", "series line"), P("color", C, BLUE),
         returns="series linefill")
def _linefill_new(rt, site, a):
    return _store(rt).linefill(a["line1"], a["line2"], {"color": a["color"]}, rt.bar)


_setter("linefill", "color", ("color",), (C,))
_copy_delete("linefill", copy=False)


def _get_line(which: str):
    def impl(rt, site, a):
        drawing = _store(rt).get(a["id"])
        return NA if drawing is None else DrawingRef("line", drawing.props[which])
    builtin(f"linefill.get_{which}", P("id", "series linefill"), returns="series line")(impl)


_get_line("line1")
_get_line("line2")
