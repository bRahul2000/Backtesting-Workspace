"""Pine compatibility, tracked by LANGUAGE FEATURE (not by indicator).

Status meanings:
  supported - implemented and covered by the conformance suite
  partial   - implemented with documented limits (see ``note``)
  gap       - valid Pine, parsed, but not executed yet: a script using it fails
              with this feature's message and the line number

No claim of full Pine compatibility is made; ``matrix()`` reports exactly
what is covered.
"""
from __future__ import annotations

from dataclasses import dataclass

SUPPORTED, PARTIAL, GAP = "supported", "partial", "gap"


@dataclass(frozen=True)
class Feature:
    id: str
    category: str      # parser | runtime | builtins | outputs | drawings | request | strategy | types
    status: str
    description: str
    note: str = ""


FEATURES: dict[str, Feature] = {f.id: f for f in (
    # Parser (the whole v5/v6 surface is parsed so gaps are reported precisely)
    Feature("syntax", "parser", SUPPORTED, "Pine v5/v6 syntax: indentation blocks, line wrapping, operators, literals"),
    Feature("version", "parser", PARTIAL, "//@version=5 and 6", "Scripts for v4 and earlier are not translated."),
    # Runtime / language
    Feature("declarations", "runtime", SUPPORTED, "variable declarations (`=`), typed declarations"),
    Feature("var", "runtime", SUPPORTED, "`var` persistent variables"),
    Feature("varip", "runtime", SUPPORTED, "`varip` intrabar-persistent variables"),
    Feature("reassignment", "runtime", SUPPORTED, "`:=` and compound assignment (`+=` ...)"),
    Feature("history", "runtime", SUPPORTED, "history references `x[n]` on variables, built-ins and expressions"),
    Feature("if", "runtime", SUPPORTED, "`if` / `else if` / `else` (statement and expression)"),
    Feature("ternary", "runtime", SUPPORTED, "ternary `? :`"),
    Feature("switch", "runtime", SUPPORTED, "`switch` with and without a subject"),
    Feature("for", "runtime", SUPPORTED, "`for ... to ... by` loops (v6 re-evaluates the end bound each iteration)"),
    Feature("while", "runtime", SUPPORTED, "`while` loops"),
    Feature("break-continue", "runtime", SUPPORTED, "`break` / `continue`"),
    Feature("functions", "runtime", SUPPORTED, "user-defined functions (single-line and block, defaults, series state per call site)"),
    Feature("tuples", "runtime", SUPPORTED, "tuple returns and `[a, b] = f()` declarations"),
    Feature("realtime", "runtime", SUPPORTED, "realtime bar re-execution with rollback (varip survives)"),
    Feature("for-in", "runtime", PARTIAL, "`for ... in` loops over arrays (`for x in a`, `for [i, x] in a`)",
            "Maps and matrices are not implemented, so loops over them are gaps."),
    Feature("builtin-methods", "runtime", PARTIAL, "built-in method syntax (`a.push(x)` for `array.push(a, x)`)",
            "Arrays only (the engine's only values with built-in methods); unimplemented `array.*` functions stay "
            "gaps in either form."),
    Feature("methods", "runtime", GAP, "user-defined methods (`method` declarations)"),
    Feature("function-overloads", "runtime", GAP, "user-defined function overloading"),
    Feature("libraries", "runtime", GAP, "libraries (`import` / `library()`)"),
    # Types
    Feature("types-basic", "types", PARTIAL, "int/float/bool/string/color with const/input/simple/series qualifiers",
            "Qualifier and type mismatches are reported where the types are known; unknown types are not rejected."),
    Feature("user-defined-types", "types", GAP, "user-defined types (`type`) and object fields"),
    Feature("enums", "types", GAP, "enums (`enum`)"),
    Feature("generics", "types", PARTIAL, "generic type arguments (`array.new<float>()`)",
            "Only `array.new<T>()` and `array<T>` with int/float/bool/string/color elements."),
    # Collections
    Feature("arrays", "builtins", PARTIAL, "arrays (`array.*`)",
            "P2.2-A1 core: new_*/new<T>/from, size, get, set, push, pop, shift, unshift, first, last, copy, clear "
            "(and remove, P2.2-A2); `array<T>` / `T[]` of int/float/bool/string/color; persistent-slot snapshots and "
            "read-only history per P22_ARRAY_ARCHITECTURE.md; `for ... in` per P22_FORIN_EVIDENCE.md. Other array "
            "functions, method syntax and nested arrays are not implemented yet."),
    Feature("matrices", "builtins", GAP, "matrices (`matrix.*`)"),
    Feature("maps", "builtins", GAP, "maps (`map.*`)"),
    # Built-in namespaces
    Feature("ta", "builtins", PARTIAL, "technical-analysis built-ins (`ta.*`)", "See the built-in coverage list."),
    Feature("math", "builtins", PARTIAL, "math built-ins (`math.*`)", "See the built-in coverage list."),
    Feature("strings", "builtins", PARTIAL, "string built-ins (`str.*`)", "See the built-in coverage list."),
    Feature("color", "builtins", SUPPORTED, "colors (`color.*`, `#RRGGBBAA` literals)"),
    Feature("inputs", "builtins", PARTIAL, "inputs (`input.*`)", "Defaults, editable values; session/symbol/time inputs are gaps."),
    Feature("time", "builtins", PARTIAL, "time variables and functions (UTC)", "time() with a session argument is a gap."),
    Feature("chart-info", "builtins", PARTIAL, "barstate.*, syminfo.*, timeframe.*", "Fundamental syminfo fields are gaps."),
    Feature("logging", "builtins", GAP, "Pine logs (`log.*`)"),
    Feature("alerts", "builtins", PARTIAL, "alert() / alertcondition()", "Accepted; no alerts are delivered."),
    # Outputs
    Feature("plot", "outputs", SUPPORTED, "plot() (line, stepline, linebr, histogram, columns, area, circles, cross)"),
    Feature("plotshape", "outputs", SUPPORTED, "plotshape()"),
    Feature("plotchar", "outputs", SUPPORTED, "plotchar()"),
    Feature("plotarrow", "outputs", GAP, "plotarrow()"),
    Feature("plotcandle", "outputs", GAP, "plotcandle() / plotbar()"),
    Feature("hline", "outputs", SUPPORTED, "hline()"),
    Feature("fill", "outputs", SUPPORTED, "fill() between plots or hlines"),
    Feature("bgcolor", "outputs", SUPPORTED, "bgcolor()"),
    Feature("barcolor", "outputs", SUPPORTED, "barcolor()"),
    # Drawing objects
    Feature("drawings-core", "drawings", PARTIAL, "drawing objects (`line.*`, `label.*`, `box.*`, `linefill.*`)",
            "P2.3a object core per P23_DRAWING_RESEARCH.md: IDs, aliasing, history, copy, delete, garbage collection "
            "(roots: scalar `var` variables), realtime rollback, x/y and `chart.point` constructors, setters/getters, "
            "methods. P2.3b (P23B_COLLECTIONS_RESEARCH.md): arrays of drawing IDs, `*.all` (a fresh array per read), "
            "current/superseded linefills. `*.all[n]`, `force_overlay`, fonts and text formatting are not implemented "
            "yet."),
    Feature("chart-points", "drawings", PARTIAL, "chart points (`chart.point.*`, `p.time` / `p.index` / `p.price`)",
            "Constructors, shared references (aliases, history, arrays), field writes with realtime rollback and "
            "`varip` persistence. `==` on points and points in `request.*` (engine limit) are not implemented."),
    Feature("tables-core", "drawings", PARTIAL, "P2.3b oracle-support tables-core (`table.new`, `table.cell`)",
            "Only the subset the frozen parity oracles use: `position.top_right`, cell text, colors, size and "
            "horizontal alignment, realtime rollback of cell writes. Not TradingView table parity (P2.4)."),
    Feature("drawing-objects", "drawings", GAP, "polylines and the rest of the table API (`polyline.*`, `table.*`)"),
    # Data requests
    Feature("request", "request", PARTIAL,
            "data requests (`request.security()` for same and higher timeframes, `request.security_lower_tf()`)",
            "Same-source symbols only; expressions over global scalars, ta.*, tuples and user functions; nesting "
            "<= 2; at most 10,000 intrabars per lower-timeframe request (TradingView: 100K-200K). `currency`, "
            "seconds/tick/range timeframes, other request.* and ticker.* are not implemented yet."),
    # Strategies
    Feature("strategy", "strategy", GAP, "strategy scripts (`strategy()`, `strategy.*` order simulation)"),
)}

#: Behaviour compared bar by bar with ACTUAL TradingView output (see parity/PARITY_REPORT.md). Only entries
#: backed by a captured TradingView reference belong here; documentation alone is listed separately.
PARITY_VALIDATED = (
    ("ta.pivothigh / ta.pivotlow (source overload; left/right 1/1 and 2/2; equal values)",
     "third-party TradingView capture, 84 bars x 4 series, 0 mismatches"),
    ("ta.highestbars / ta.lowestbars (source overload; length 3 and 5; equal values)",
     "third-party TradingView capture, 84 bars x 4 series, 0 mismatches"),
    ("ta.sma / ta.ema / ta.rma / ta.wma: warm-up, na gap and volatility bars (fixture s01, all pages)",
     "own TradingView check (manual tables, every page and column group of s01_averages), all cells equal"),
    ("ta.rsi, ta.rma of a true-range formula, ta.change, ta.mom, ta.stdev, ta.stoch, ta.cci, ta.macd, ta.bb: "
     "warm-up and zero-range bars (fixture s02)",
     "own TradingView check (manual tables, every page and column group of s02_oscillators), all cells equal"),
    ("history references `x[n]` on variables, expressions, built-in results and inside functions (fixture s03)",
     "own TradingView check (manual tables, every page and column group of s03_history), all cells equal"),
    ("ta.crossover / crossunder / cross (incl. touch-then-cross), ta.rising / falling, ta.barssince, "
     "ta.valuewhen (fixture s04)",
     "own TradingView check (manual tables, every page and column group of s04_cross), all cells equal"),
    ("ta.highest / lowest / highestbars / lowestbars incl. equal values; ta.pivothigh / pivotlow 1/1, 2/2, 3/3, "
     "2/1, 1/3 incl. equal values (fixtures s05, s06)",
     "own TradingView quick check q1_main_v6: 1404 + 1404 cells, 0 failures"),
    ("var / user-function var per call site on historical bars; switch, ternary chains, if / if-without-else "
     "expressions, user functions with defaults, tuple returns (fixtures s07, s10); fixture data (s00)",
     "own TradingView quick check q1_main_v6: 210 + 240 + 350 cells, 0 failures (s07: historical bars only)"),
    ("na handling: na(), nz(), fixnan(), arithmetic / comparison / math.max with na, history of na, ta.change, "
     "ta.cum, ta.highest on na bars (fixture s11)",
     "own TradingView quick check q1_main_v6: 216 cells, 0 failures (after the ta.highest/lowest na fix)"),
    ("loops and version rules: for / for-by / descending for / break / continue / while, loop values; `for` end "
     "re-evaluated each iteration in v6 and once in v5; `const int / const int` = 3.5 in v6 and 3 in v5; `and` "
     "short-circuits in v6 and evaluates both sides in v5 (fixtures s08, s09)",
     "own TradingView quick checks q2 (v6) and q3 (v5): 180 + 180 cells, 0 failures"),
    ("request.security() HISTORICAL mapping: same timeframe; 5m and 15m from a 1m chart with gaps on/off x "
     "lookahead on/off; src[1], arithmetic, ta.sma / ta.ema / ta.rsi, tuples, user functions and scalar var state "
     "in the requested context (fixture q4)",
     "own TradingView quick check q4_security_historical: 134,400 cells, 0 failures; this engine reproduces all "
     "134,400 (Replay / Live knowable-per-bar semantics are engine-defined and not TradingView-verified)"),
    ("plot() default style (plot.style_line) draws across na; plot.style_linebr leaves the gap",
     "own TradingView observation (manual/m02)"),
    ("var keeps its value and varip advances across updates of one realtime bar",
     "own TradingView observation (manual/m03, BTCUSDT 1-minute live chart)"),
    ("ta.sma / ta.ema / ta.rma / ta.wma across an na gap in the source (bars 17-26)",
     "own TradingView capture (s01_averages page 2, columns 2): 50 cells, 0 mismatches after the na fix"),
)
#: Behaviour aligned with TradingView's documentation but NOT yet compared with captured TradingView output.
DOCUMENTED_ONLY = (
    "`timeframe.period` includes the multiplier in v6 (\"1D\")",
    "`barstate.isnew` true on the first execution of each bar; on a new realtime bar var advances and a "
    "barstate.isnew-reset varip counter restarts",
    "explicit `style=plot.style_line` (only the default style, which is plot.style_line, was observed)",
)

#: Built-in namespace -> feature id (for "not implemented yet" messages).
NAMESPACE_FEATURE = {
    "request": "request", "ticker": "request", "array": "arrays", "matrix": "matrices", "map": "maps",
    "line": "drawings-core", "label": "drawings-core", "box": "drawings-core", "table": "drawing-objects",
    "polyline": "drawing-objects", "linefill": "drawings-core", "chart.point": "chart-points",
    "strategy": "strategy", "log": "logging", "ta": "ta", "math": "math", "str": "strings", "input": "inputs",
    "timeframe": "chart-info", "syminfo": "chart-info", "barstate": "chart-info", "session": "time", "": "core",
}
#: Top-level built-in functions that belong to a gap feature.
FUNCTION_FEATURE = {"plotarrow": "plotarrow", "plotcandle": "plotcandle", "plotbar": "plotcandle",
                    "label": "drawing-objects", "line": "drawing-objects", "box": "drawing-objects",
                    "table": "drawing-objects", "linefill": "drawing-objects", "polyline": "drawing-objects"}


TABLES_CORE = {"table.new", "table.cell", "position.top_right"}    # the P2.3b oracle-support subset


def feature_for_builtin(name: str) -> str:
    if name in TABLES_CORE:
        return "tables-core"
    if name in FUNCTION_FEATURE:
        return FUNCTION_FEATURE[name]
    namespace = name.rsplit(".", 1)[0] if "." in name else ""
    if name.startswith("chart.point"):
        namespace = "chart.point"
    return NAMESPACE_FEATURE.get(namespace, "core")


def matrix() -> dict:
    """Coverage by category and the built-in implementation counts."""
    from . import catalog
    from .registry import CONSTANTS, FUNCTIONS, VARIABLES, load_all

    load_all()
    by_category: dict[str, list[dict]] = {}
    for feature in FEATURES.values():
        by_category.setdefault(feature.category, []).append(
            {"id": feature.id, "status": feature.status, "description": feature.description, "note": feature.note})
    namespaces: dict[str, dict] = {}
    for name in sorted(catalog.KNOWN_FUNCTIONS | catalog.KNOWN_VARIABLES):
        namespace = catalog.namespace_of(name) or "(global)"
        entry = namespaces.setdefault(namespace, {"known": 0, "implemented": 0, "missing": []})
        entry["known"] += 1
        if name in FUNCTIONS or name in VARIABLES:
            entry["implemented"] += 1
        else:
            entry["missing"].append(name)
    return {
        "features": by_category,
        "counts": {status: sum(1 for f in FEATURES.values() if f.status == status) for status in (SUPPORTED, PARTIAL, GAP)},
        "builtins": {"functions": len(FUNCTIONS), "variables": len(VARIABLES), "constants": len(CONSTANTS),
                     "by_namespace": namespaces},
    }


def markdown() -> str:
    """COMPATIBILITY.md, generated from the feature catalog and the registries."""
    m = matrix()
    lines = [
        "# Pine compatibility (P1)",
        "",
        "Generated by `python -m ui.tradingview_mode.pine.compat` from the engine's feature catalog and",
        "built-in registries; a test fails if this file is out of date. Compatibility is tracked by language",
        "feature. **No claim of full Pine compatibility is made**: a script runs only if every feature it",
        "uses is supported, and otherwise fails with the exact feature and line.",
        "",
        f"Features: {m['counts']['supported']} supported, {m['counts']['partial']} partial, {m['counts']['gap']} not "
        f"yet implemented. Built-ins: {m['builtins']['functions']} functions, {m['builtins']['variables']} variables, "
        f"{m['builtins']['constants']} constants.",
        "",
    ]
    for category, features in m["features"].items():
        lines += [f"## {category}", "", "| feature | status | notes |", "|---|---|---|"]
        lines += [f"| {f['description']} | {f['status']} | {f['note']} |" for f in features]
        lines.append("")
    lines += ["## Built-in coverage by namespace", "", "| namespace | implemented / known | not implemented yet |", "|---|---|---|"]
    for namespace, entry in sorted(m["builtins"]["by_namespace"].items()):
        missing = ", ".join(f"`{name}`" for name in entry["missing"][:12])
        more = f" … (+{len(entry['missing']) - 12})" if len(entry["missing"]) > 12 else ""
        lines.append(f"| `{namespace}` | {entry['implemented']} / {entry['known']} | {missing}{more} |")
    lines += ["", "## ACTUAL TRADINGVIEW PARITY VALIDATED", "",
              "Compared bar by bar with values produced by TradingView itself (`parity/PARITY_REPORT.md`). Nothing "
              "outside this list is claimed to match TradingView. Not verified: the chart-price fixture c01 "
              "(ta.atr, ta.tr, ta.vwma, ta.supertrend, default-source overloads) and the numeric values of s12 "
              "(plotshape / plotchar / bgcolor / barcolor timing). Each entry covers only the bars and outputs of "
              "its check.", "", "| behaviour | evidence |", "|---|---|"]
    lines += [f"| {name} | {evidence} |" for name, evidence in PARITY_VALIDATED]
    lines += ["", "Aligned with TradingView's documentation, **not yet confirmed against TradingView output**:", ""]
    lines += [f"- {item}" for item in DOCUMENTED_ONLY]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    from pathlib import Path

    target = Path(__file__).with_name("COMPATIBILITY.md")
    target.write_text(markdown())
    print(f"wrote {target}")
