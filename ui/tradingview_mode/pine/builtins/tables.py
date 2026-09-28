"""P2.3b oracle-support tables-core (parity/P23B_COLLECTIONS_RESEARCH.md §9) - NOT TradingView table parity.

Exactly the subset the frozen P2.3 / q9 oracle scripts use: ``table.new(position.top_right, columns, rows, bgcolor,
border_color, border_width)`` and ``table.cell(table_id, column, row, text, text_color, bgcolor, text_size,
text_halign)``. A table is an object of the runtime's DrawingStore (kind ``table``), so cell writes on the forming bar
roll back like any drawing change (m07). Every other parameter is accepted only at its default; every other
``table.*`` function, ``table.all`` and the other ``position.*`` constants stay P2.4 capability gaps.
"""
from __future__ import annotations

from ..errors import PineRuntimeError
from ..registry import Param as P, builtin, constant
from ..values import NA, Color, is_na

BLACK = Color.from_hex("#000000")
I, S, C = "series int", "series string", "series color"

constant("position.top_right", "top_right", "string")


def _only_default(name: str, a: dict, defaults: dict) -> None:
    for param, default in defaults.items():
        value = a[param]
        if not (value == default or (is_na(value) and is_na(default))):
            raise PineRuntimeError(f"`{name}()`: the `{param}` argument is not implemented yet (only its default).", 0)


@builtin("table.new", P("position", S), P("columns", I), P("rows", I), P("bgcolor", C, NA), P("frame_color", C, NA),
         P("frame_width", I, 0), P("border_color", C, NA), P("border_width", I, 0),
         P("force_overlay", "const bool", False), returns="series table")
def _table_new(rt, site, a):
    _only_default("table.new", a, {"frame_color": NA, "frame_width": 0, "force_overlay": False})
    if a["position"] != "top_right":
        raise PineRuntimeError("`table.new()`: only `position.top_right` is implemented yet.", 0)
    columns, rows = a["columns"], a["rows"]
    if is_na(columns) or is_na(rows) or int(columns) < 1 or int(rows) < 1:
        raise PineRuntimeError("`table.new()`: `columns` and `rows` must be positive integers.", 0)
    props = {"position": "top_right", "columns": int(columns), "rows": int(rows), "bgcolor": a["bgcolor"],
             "border_color": a["border_color"], "border_width": 0 if is_na(a["border_width"]) else int(a["border_width"])}
    return rt.drawings.create("table", props, rt.bar)


@builtin("table.cell", P("table_id", "series table"), P("column", I), P("row", I), P("text", S, ""),
         P("width", "series float", 0), P("height", "series float", 0), P("text_color", C, BLACK),
         P("text_halign", S, "center"), P("text_valign", S, "center"), P("text_size", S, "normal"),
         P("bgcolor", C, NA), P("tooltip", S, ""), P("text_font_family", S, NA),
         P("text_formatting", S, NA), returns="void")
def _table_cell(rt, site, a):
    _only_default("table.cell", a, {"width": 0, "height": 0, "text_valign": "center", "tooltip": "",
                                    "text_font_family": NA, "text_formatting": NA})
    store = rt.drawings
    table = store.get(a["table_id"])
    if table is None:
        return NA                                   # na / deleted table: a no-op (engine policy, like drawings)
    column, row = a["column"], a["row"]
    if is_na(column) or is_na(row) or not (0 <= int(column) < table.props["columns"]
                                           and 0 <= int(row) < table.props["rows"]):
        raise PineRuntimeError(f"`table.cell()`: cell ({column}, {row}) is outside the table's "
                               f"{table.props['columns']} x {table.props['rows']} cells.", 0)
    cell = {"text": "" if is_na(a["text"]) else a["text"], "text_color": a["text_color"], "bgcolor": a["bgcolor"],
            "text_size": a["text_size"], "text_halign": a["text_halign"]}
    store.set(a["table_id"], ("cell", int(column), int(row)), cell)
    return NA
