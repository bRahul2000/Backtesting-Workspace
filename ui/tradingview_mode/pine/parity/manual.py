"""Manual parity (TradingView Basic plan: no chart-data export).

Each manual script is GENERATED from an authoritative fixture in ``fixtures.py``: the fixture's
``plot(expr, "name")`` lines become ``float v_name = expr`` (the same expressions, in the same order,
so TradingView computes exactly the same values) and a ``table.new()`` shows 10 chosen bars at a time.

* ``Page`` input      - which 10-bar window is shown (each window targets a semantic event)
* ``Columns`` input   - which group of outputs is shown (at most 6 value columns, readable at 1440 px)
* ``First bar`` input - any other window (-1 = use Page)

Values are printed with ``str.tostring(x, "0.########")`` (8 decimals, trailing zeros dropped); ``na`` is
printed as ``na``; booleans are the fixture's 1 / 0 plots. ``ours_manual/<fixture>.csv`` (and ``.md``)
hold what this engine computes for exactly those cells, formatted the same way.

Tables are TradingView-only here (this engine reports ``table.*`` as not implemented yet), so the
expected values come from the *core* variant of the same script: identical code with ``plot()`` calls
instead of the table.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

import pandas as pd

from .fixtures import BY_NAME, MANUAL_CHECKS, PRELUDE

ROWS = 10
DECIMALS = 8
FORMAT = "0." + "#" * DECIMALS
ROOT = Path(__file__).parent
MANUAL_DIR, EXPECTED_DIR = ROOT / "manual", ROOT / "ours_manual"
CHECKLIST = ROOT / "MANUAL_CHECKLIST.md"

_PLOT = re.compile(r'^plot\((?P<expr>.*), "(?P<name>[A-Za-z_][A-Za-z0-9_]*)"\)$')


@dataclass(frozen=True)
class ManualSpec:
    fixture: str
    pages: tuple[tuple[int, str], ...]       # (first bar, what the window shows)
    parts: tuple[tuple[str, ...], ...]       # column groups (fixture output names)
    focus: str = ""                          # what to look at first


SPECS: list[ManualSpec] = [
    ManualSpec("s00_data", (
        (0, "first bars (bar 0 open = close - 0.5)"),
        (182, "equal highs 120 at bars 184, 186, 190, 191"),
        (196, "equal highs at 196, 199; equal lows 95 at 203, 205"),
        (208, "zero-range candles o=h=l=c=110 from bar 211"),
        (222, "after the flat run; equal lows at 226, 227")),
        (("o", "h", "l", "c", "v"),),
        "the input data itself: if this differs, every other fixture will differ too"),
    ManualSpec("s01_averages", (
        (0, "warm-up: first sma5 at bar 4, ema9 at 8, wma10 at 9"),
        (10, "first rma14 at 13, first sma20 / ema20 at 19"),
        (17, "na source values at bars 20-22 (gappy columns)"),
        (150, "sudden volatility (bars 150-169)")),
        (("sma5", "sma20", "ema1", "ema9", "ema20", "rma14"),
         ("wma10", "sma5_gappy", "ema9_gappy", "rma14_gappy", "wma10_gappy")),
        "first non-na bar of each average, and what the averages do across the na bars 20-22"),
    ManualSpec("s02_oscillators", (
        (0, "warm-up: rsi2 from 2, atr from 13, rsi14 from 14"),
        (17, "stdev / stoch / cci / bb from 19, macd from 25"),
        (28, "macd signal / histogram from 33"),
        (208, "zero-range candles from bar 211 (no movement)")),
        (("rsi14", "rsi2", "atr14_formula", "change1", "change3", "mom10"),
         ("stdev20", "stoch14", "cci20", "macd", "macd_signal", "macd_hist"),
         ("bb_mid", "bb_up", "bb_lo")),
        "first non-na bar of each oscillator"),
    ManualSpec("s03_history", (
        (0, "history warm-up: na until enough bars exist"),
        (100, "mid-series")),
        (("c_1", "c_2", "acc", "acc_1", "diff_3"), ("range_1", "sma3_2", "udf_hist", "bi_5")),
        "na on the first bars, then values shifted by exactly 1 / 2 / 3 / 5 bars"),
    ManualSpec("s04_cross", (
        (84, "first ema/sma crossover at bar 88"),
        (96, "k - 100 touches 0 at bar 100, crosses at 101"),
        (150, "volatility: crosses at 154, 155, 160, 161, 165"),
        (203, "crossunder at 207; closes sit exactly on 110 from 210"),
        (216, "crossover of 110 at bar 222")),
        (("xover", "xunder", "xany", "xover_touch", "xunder_touch", "xover_flat"),
         ("rising3", "falling3", "since_xover", "valuewhen0", "valuewhen1")),
        "the exact bar each 1 appears on (xover_touch must be 1 on bar 101 only)"),
    ManualSpec("s05_extremes", (
        (0, "warm-up and the repeating tie pattern"),
        (10, "tie pattern: equal values at distance 1, 2 and 3"),
        (182, "equal highs at 184, 186, 190, 191"),
        (196, "equal highs at 196, 199; equal lows at 203, 205")),
        (("tp", "hi3", "lo3", "hib3", "lob3"), ("tp", "hi5", "lo5", "hib5", "lob5"),
         ("hi10_h", "lo10_l", "hib10_h", "lob10_l")),
        "the *bars columns (hib/lob): with equal values TradingView should point at the OLDEST one"),
    ManualSpec("s06_pivots", (
        (0, "tie pattern, first pivots"),
        (10, "tie pattern continued"),
        (16, "first 3/3 pivot high at bar 19"),
        (184, "2/2 pivot highs on equal highs 184/186 (reported at 188) and 190/191 (at 193)"),
        (200, "equal lows 95 at 203/205: 2/2 pivot low reported at 207, 3/3 at 208")),
        (("tp", "ph33", "pl33", "ph21", "pl13"), ("tp", "ph11", "pl11", "ph22", "pl22"),
         ("ph22_h", "pl22_l", "ph33_h", "pl33_l")),
        "which of two equal values becomes the pivot (3/3, 2/1 and 1/3 are not yet confirmed anywhere)"),
    ManualSpec("s07_var_varip", (
        (0, "first bars"),
        (45, "var_resets goes back to 0 at bar 50"),
        (84, "var_last_cross is set at bar 88")),
        (("var_count", "varip_count", "var_last_cross", "var_resets", "udf_var_a", "udf_var_b", "no_var"),),
        "udf_var_b counts only on even bars (its own call site); no_var is always 1"),
    ManualSpec("s08_loops_v6", (
        (0, "first bars"),
        (10, "later bars")),
        (("for_dynamic_end", "div_const", "and_stateful", "for_value", "for_desc_by2"),
         ("for_sum10", "for_break", "while_steps", "div_series")),
        "v6: for_dynamic_end = 7 (end re-read every iteration), div_const = 3.5, and_stateful = 1 on bar 6"),
    ManualSpec("s09_loops_v5", (
        (0, "first bars"),
        (10, "later bars")),
        (("for_dynamic_end", "div_const", "and_stateful", "for_value", "for_desc_by2"),
         ("for_sum10", "for_break", "while_steps", "div_series")),
        "v5: for_dynamic_end = 4 (end fixed before the loop), div_const = 3, and_stateful always 0"),
    ManualSpec("s10_control", (
        (0, "first bars"),
        (14, "ternary_na becomes a number from bar 18")),
        (("switch_nosubject", "switch_subject", "ternary_chain", "ternary_na", "if_expr", "if_noelse_na"),
         ("udf_default", "udf_arg", "tuple_mid", "tuple_up", "tuple_lo", "tuple2_up")),
        "switch_subject is na every 4th bar; if_noelse_na is na unless bar % 3 == 0"),
    ManualSpec("s11_na", (
        (0, "na at bars 0, 5, 10 (every 5th bar)"),
        (8, "next na transitions")),
        (("gappy", "nz_default", "nz_repl", "is_na", "fixnan", "na_plus"),
         ("na_compare", "na_max", "na_hist", "na_change", "cum_nz", "na_highest")),
        "what each function returns ON the na bars (0, 5, 10, 15)"),
]
BY_FIXTURE = {spec.fixture: spec for spec in SPECS}

VISUAL_NA_GAP = "m02_na_gap_visual"
LIVE_TABLE = "m03_live_var_varip_table"


# ---- script generation -------------------------------------------------------------------------------------------

def _split(fixture) -> tuple[str, list[str], dict[str, str]]:
    """(fixture body without its plot() calls, variable lines, output name -> variable)."""
    body, names = [], {}
    for line in fixture.body.strip("\n").splitlines():
        match = _PLOT.match(line)
        if match:
            variable = f"v_{match['name']}"
            if match["name"] not in names:
                names[match["name"]] = variable
                body.append(f"float {variable} = {match['expr']}")
            continue
        body.append(line)
    return "\n".join(body) + "\n", list(names), names


def _header(spec: ManualSpec, kind: str) -> str:
    fixture = BY_NAME[spec.fixture]
    return (f"//@version={fixture.version}\n"
            f"// Pine parity MANUAL script for fixture `{fixture.name}` ({kind}). Generated from fixtures.py - do not edit.\n"
            f"// Same calculations as fixtures/{fixture.name}.pine; the values are shown in a table (TradingView Basic plan).\n"
            f'indicator("parity {fixture.name} (manual)", overlay=true, precision=8)\n')


def core_source(spec: ManualSpec) -> str:
    """The manual script's calculations with plot() outputs instead of the table (runs in this engine)."""
    body, _, names = _split(BY_NAME[spec.fixture])
    plots = "".join(f'plot({variable}, "{name}")\n' for name, variable in names.items())
    return _header(spec, "core") + PRELUDE + body + plots


def _q(text: str) -> str:
    return text.replace('"', "'")


def manual_source(spec: ManualSpec) -> str:
    fixture = BY_NAME[spec.fixture]
    body, _, names = _split(fixture)
    width = max(len(part) for part in spec.parts) + 1
    pages = " | ".join(f"{i}: bars {start}-{start + ROWS - 1} {why}" for i, (start, why) in enumerate(spec.pages))
    parts = " | ".join(f"{i + 1}: {', '.join(part)}" for i, part in enumerate(spec.parts))
    lines = [
        "// ---- manual parity table (TradingView only) ----",
        f'int page = input.int(0, "Page", minval=0, maxval={len(spec.pages) - 1}, tooltip="{_q(pages)}")',
        f'int part = input.int(1, "Columns", minval=1, maxval={len(spec.parts)}, tooltip="{_q(parts)}")',
        'int firstBarInput = input.int(-1, "First bar (-1 = use Page)", minval=-1)',
        "int pageStart = switch page",
        *[f"    {i} => {start}" for i, (start, _) in enumerate(spec.pages)],
        "    => 0",
        "int firstBar = firstBarInput >= 0 ? firstBarInput : pageStart",
        f"var table grid = table.new(position.top_right, {width}, {ROWS + 2}, bgcolor=color.white, "
        "border_color=color.gray, border_width=1, frame_color=color.gray, frame_width=1)",
        "put(int col, int row, string txt) =>",
        "    table.cell(grid, col, row, txt, text_color=color.black, text_size=size.normal, text_halign=text.align_right)",
        f'fmt(float value) => na(value) ? "na" : str.tostring(value, "{FORMAT}")',
        "if barstate.isfirst",
        f'    put(0, 0, "{fixture.name} · columns " + str.tostring(part) + " · bars " + str.tostring(firstBar) + "-" + '
        f"str.tostring(firstBar + {ROWS - 1}))",
        f"    table.merge_cells(grid, 0, 0, {width - 1}, 0)",
        '    put(0, 1, "bar")',
    ]
    for index, part in enumerate(spec.parts, start=1):
        lines.append(f"    if part == {index}")
        lines += [f'        put({col}, 1, "{name}")' for col, name in enumerate(part, start=1)]
    lines += ["int row = bar_index - firstBar + 2",
              f"if row >= 2 and row <= {ROWS + 1}",
              "    put(0, row, str.tostring(bar_index))"]
    for index, part in enumerate(spec.parts, start=1):
        lines.append(f"    if part == {index}")
        lines += [f"        put({col}, row, fmt({names[name]}))" for col, name in enumerate(part, start=1)]
    lines.append('plot(bar_index, "bi", display=display.data_window)')
    return _header(spec, "table") + PRELUDE + body + "\n".join(lines) + "\n"


def na_gap_visual_source() -> str:
    return """\
//@version=6
// Pine parity manual VISUAL check: how lines are drawn across na values. Generated from manual.py.
// Expected (TradingView documentation): the upper line (default style = plot.style_line) is drawn straight
// across the na bars; the lower line (plot.style_linebr) stops and leaves an empty gap.
indicator("parity m02 na-gap visual", overlay=false)
int k = bar_index % 40
float wave = k < 20 ? k : 40 - k
float gappy = bar_index % 10 < 3 ? na : wave
plot(gappy + 30, "A default / style_line (should bridge gaps)", color=color.blue, linewidth=2)
plot(gappy, "B style_linebr (should leave gaps)", color=color.red, linewidth=2, style=plot.style_linebr)
plot(bar_index % 10 < 3 ? 1 : 0, "na bar (1 = value missing)", display=display.data_window)
"""


def live_table_source() -> str:
    core = MANUAL_CHECKS["m01_live_varip"].replace(
        'indicator("parity m01 live varip", overlay=false)', 'indicator("parity m03 live var/varip", overlay=true)')
    core = core.replace("// Pine parity manual check: var vs varip on realtime ticks. Add to a LIVE 1-minute chart "
                        "and watch the Data Window.",
                        "// Pine parity manual check: var vs varip on realtime ticks, shown in a table. Generated "
                        "from manual.py.\n// Add to a LIVE 1-minute chart and watch the table for one forming candle "
                        "and the start of the next.")
    table = """\
var table grid = table.new(position.top_right, 2, 7, bgcolor=color.white, border_color=color.gray, border_width=1)
put(int row, string name, string value) =>
    table.cell(grid, 0, row, name, text_color=color.black, text_halign=text.align_left)
    table.cell(grid, 1, row, value, text_color=color.black, text_halign=text.align_right)
if barstate.islast
    put(0, "bar_index", str.tostring(bar_index))
    put(1, "barstate.isnew", barstate.isnew ? "T" : "F")
    put(2, "barstate.isrealtime", barstate.isrealtime ? "T" : "F")
    put(3, "var count", str.tostring(varPerBar))
    put(4, "varip count", str.tostring(varipTotal))
    put(5, "varip ticks this bar", str.tostring(ticksThisBar))
    put(6, "time (UTC)", str.format_time(time, "HH:mm", "UTC"))
"""
    return core + table


# ---- expected values from this engine ------------------------------------------------------------------------------

def fmt(value) -> str:
    """Python mirror of ``str.tostring(x, "0.########")`` (HALF_EVEN on the exact binary value, like DecimalFormat)."""
    if value is None or value != value:
        return "na"
    rounded = Decimal(value).quantize(Decimal(1).scaleb(-DECIMALS), rounding=ROUND_HALF_EVEN)
    text = format(rounded, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", "0") and str(value).startswith("-"):
        return "-0"
    return text


def expected_rows(spec: ManualSpec) -> pd.DataFrame:
    """One row per (page, bar): every output of the fixture formatted as the TradingView table shows it."""
    from .. import PineExecution, compile_script, run_script
    from .harness import _seconds, synthetic_frame

    result = compile_script(core_source(spec))
    if not result.ok:
        raise RuntimeError(f"manual core of {spec.fixture} does not compile: {[d.text() for d in result.errors]}")
    last = max(start for start, _ in spec.pages) + ROWS
    frame = synthetic_frame(max(last, 1))
    from ..engine import data_context
    data = data_context(frame, timeframe_seconds=_seconds(frame), ticker="PARITY", tickerid="PARITY:PARITY",
                        mintick=0.01)
    run = run_script(PineExecution(result.program, {}), data, ("manual", spec.fixture), "m")
    values = {o["title"]: [p["value"] for p in o["data"]] for o in run.outputs if o["kind"] == "plot"}
    order = list(dict.fromkeys(name for part in spec.parts for name in part))
    rows = []
    for page, (start, why) in enumerate(spec.pages):
        for bar in range(start, start + ROWS):
            rows.append({"page": page, "bar": bar, **{name: fmt(values[name][bar]) for name in order}})
    return pd.DataFrame(rows)


def expected_markdown(spec: ManualSpec, rows: pd.DataFrame) -> str:
    fixture = BY_NAME[spec.fixture]
    lines = [f"# Expected table values — `{fixture.name}` ({fixture.title})", "",
             f"Paste `manual/{fixture.name}.pine` into TradingView. Each block below is one **Page** / **Columns** "
             "setting; the numbers must match TradingView's table.", "", f"Look at first: {spec.focus}.", ""]
    for page, (start, why) in enumerate(spec.pages):
        for index, part in enumerate(spec.parts, start=1):
            block = rows[rows["page"] == page]
            lines += [f"## Page {page} · Columns {index} — bars {start}-{start + ROWS - 1}: {why}", "",
                      "| bar | " + " | ".join(part) + " |", "|---|" + "---|" * len(part)]
            lines += ["| " + " | ".join([str(r["bar"])] + [r[name] for name in part]) + " |" for _, r in block.iterrows()]
            lines.append("")
    return "\n".join(lines)


def write_manual() -> None:
    MANUAL_DIR.mkdir(exist_ok=True)
    EXPECTED_DIR.mkdir(exist_ok=True)
    for spec in SPECS:
        (MANUAL_DIR / f"{spec.fixture}.pine").write_text(manual_source(spec))
        rows = expected_rows(spec)
        (EXPECTED_DIR / f"{spec.fixture}.csv").write_text(rows.to_csv(index=False, lineterminator="\n"))
        (EXPECTED_DIR / f"{spec.fixture}.md").write_text(expected_markdown(spec, rows))
    (MANUAL_DIR / f"{VISUAL_NA_GAP}.pine").write_text(na_gap_visual_source())
    (MANUAL_DIR / f"{LIVE_TABLE}.pine").write_text(live_table_source())
