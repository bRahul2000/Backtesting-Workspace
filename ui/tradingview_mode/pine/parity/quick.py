"""Fast self-checking TradingView parity scripts (generated; see README "FAST TRADINGVIEW PARITY").

Each quick script contains, for one or more fixtures:

* the fixture's calculations, exactly as in ``fixtures.py`` (``plot(expr, "name")`` becomes
  ``float q_<fixture>_<name> = expr``; statements, order and call sites are unchanged), so TradingView
  computes every value itself at runtime;
* this engine's expected values for a fixed set of (bar, output) cells, embedded as generated data
  (``ours/`` output of the authoritative fixture run - never typed by hand);
* a comparison of the two on every checked bar and one summary table: cells expected / checked /
  passed / failed, the largest difference, PASS / FAIL per fixture, key rows and the first failures.

Comparison rule (``compare()`` below mirrors the Pine code exactly):

* both na -> pass; exactly one na -> fail;
* otherwise pass iff ``|tv - ours| <= ABS_TOL + REL_TOL * |ours|`` with ``ABS_TOL = 5e-9`` (half a unit
  of the 8th decimal, the manual-table standard) and ``REL_TOL = 1e-12`` (floating-point noise on large
  values). Booleans are plotted as 1 / 0 and integers are whole numbers, so any real difference there is
  >= 1 and always fails.

A fixture is PASS only if every expected cell was checked (the chart must have at least ``PERIOD`` bars
of history) and none failed.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .fixtures import BY_NAME, PERIOD, PRELUDE
from .manual import BY_FIXTURE as MANUAL

ABS_TOL = 5e-9
REL_TOL = 1e-12
MAX_FAILURES = 10
MAX_LITERAL = 1500                  # characters per embedded string literal (kept well inside Pine limits)
ROOT = Path(__file__).parent
QUICK_DIR = ROOT / "quick"

_PLOT = re.compile(r'^plot\((?P<expr>.*), "(?P<name>[A-Za-z_][A-Za-z0-9_]*)"\)$')
_DECL = re.compile(r'^(?:var\s+|varip\s+)?(?:int|float|bool|string|color)?\s*([A-Za-z_]\w*)\s*=(?!=)'
                   r'|^([A-Za-z_]\w*)\(.*\)\s*=>|^\[(.*)\]\s*=')


@dataclass(frozen=True)
class QuickScript:
    name: str
    fixtures: tuple[str, ...]
    #: extra bars checked beyond the manual pages, per fixture
    extra_bars: dict = field(default_factory=dict)
    #: (fixture, output, bar): the TradingView value is shown by name in the summary
    keys: tuple[tuple[str, str, int], ...] = ()
    title: str = ""


TIE_PERIODS = tuple(range(0, 48))   # two full periods of the 24-bar tie pattern (every tie case, every window)
OHLC_TIES = tuple(range(180, 240))  # equal highs 184-199, equal lows 203-227 and the pivots they confirm (to 230)

QUICK_SCRIPTS: list[QuickScript] = [
    QuickScript("q1_main_v6", ("s00_data", "s05_extremes", "s06_pivots", "s07_var_varip", "s10_control", "s11_na"),
                extra_bars={"s00_data": OHLC_TIES, "s05_extremes": TIE_PERIODS + OHLC_TIES,
                            "s06_pivots": TIE_PERIODS + OHLC_TIES},
                keys=(("s06_pivots", "ph33", 19), ("s06_pivots", "ph22_h", 188), ("s05_extremes", "hib5", 14),
                      ("s11_na", "na_max", 5)),
                title="data, extremes, pivots, var (historical), control flow, na"),
    QuickScript("q2_s08_loops_v6", ("s08_loops_v6",),
                keys=(("s08_loops_v6", "for_dynamic_end", 0), ("s08_loops_v6", "div_const", 0),
                      ("s08_loops_v6", "and_stateful", 6)),
                title="loops and operators, Pine v6 semantics"),
    QuickScript("q3_s09_loops_v5", ("s09_loops_v5",),
                keys=(("s09_loops_v5", "for_dynamic_end", 0), ("s09_loops_v5", "div_const", 0),
                      ("s09_loops_v5", "and_stateful", 6)),
                title="loops and operators, Pine v5 semantics"),
]
BY_QUICK = {q.name: q for q in QUICK_SCRIPTS}


# ---- the comparison rule (mirrored in Pine) -------------------------------------------------------------------

def compare(tv, ours) -> bool:
    tv_na, ours_na = tv is None or tv != tv, ours is None or ours != ours
    if tv_na or ours_na:
        return tv_na and ours_na
    return abs(tv - ours) <= ABS_TOL + REL_TOL * abs(ours)


# ---- cells and expected values ---------------------------------------------------------------------------------

def check_bars(quick: QuickScript, fixture: str) -> list[int]:
    spec = MANUAL[fixture]
    bars = {bar for start, _ in spec.pages for bar in range(start, start + 10)}
    bars |= set(quick.extra_bars.get(fixture, ()))
    return sorted(bars)


def outputs(fixture: str) -> list[str]:
    return [m["name"] for line in BY_NAME[fixture].body.splitlines() if (m := _PLOT.match(line))]


def expected_table(fixture: str):
    """This engine's output for the fixture (the same run that writes ``ours/<fixture>.csv``)."""
    from .harness import run_ours, synthetic_frame

    return run_ours(BY_NAME[fixture], synthetic_frame(PERIOD))


def number_text(value) -> str:
    """Exact, exponent-free text of a float (round-trips through str.tonumber); ``na`` for na."""
    if value is None or value != value:
        return "na"
    if float(value).is_integer():
        return str(int(value))
    return format(Decimal(repr(float(value))), "f")


def expected_cells(quick: QuickScript) -> dict[str, dict[str, list[str]]]:
    """fixture -> output -> expected text per check bar (in ``check_bars`` order)."""
    cells = {}
    for fixture in quick.fixtures:
        table = expected_table(fixture)
        bars = check_bars(quick, fixture)
        cells[fixture] = {name: [number_text(table.at[bar, name]) for bar in bars] for name in outputs(fixture)}
    return cells


# ---- script generation -----------------------------------------------------------------------------------------

def _blocks(body: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    for line in body.strip("\n").splitlines():
        if line[:1] in (" ", "\t") and blocks:
            blocks[-1].append(line)
        else:
            blocks.append([line])
    return blocks


def _declared(block: list[str]) -> set[str]:
    match = _DECL.match(block[0])
    if not match:
        return set()
    return {name.strip() for name in (match.group(1) or match.group(2) or match.group(3)).split(",")}


def combined_body(quick: QuickScript) -> tuple[str, dict[tuple[str, str], str]]:
    """The fixtures' calculations back to back; returns (code, (fixture, output) -> variable)."""
    lines, variables, seen, owner = [], {}, set(), {}
    for fixture in quick.fixtures:
        lines.append(f"// ---- {fixture} ----")
        for block in _blocks(BY_NAME[fixture].body):
            match = _PLOT.match(block[0]) if len(block) == 1 else None
            if match:
                variable = f"q_{fixture[:3]}_{match['name']}"
                variables[(fixture, match["name"])] = variable
                lines.append(f"float {variable} = {match['expr']}")
                continue
            text = "\n".join(block)
            names = _declared(block)
            if text in seen and names:            # an identical pure declaration shared by two fixtures (`tp`)
                continue
            for name in names:
                if name in owner and owner[name] != text:
                    raise ValueError(f"{quick.name}: `{name}` is declared differently by two fixtures")
                owner[name] = text
            seen.add(text)
            lines.extend(block)
    return "\n".join(lines) + "\n", variables


def _literal(text: str) -> str:
    if len(text) > MAX_LITERAL:
        raise ValueError(f"embedded literal of {len(text)} characters exceeds {MAX_LITERAL}")
    return f'"{text}"'


def core_source(quick: QuickScript) -> str:
    """The quick script's calculations with plot() outputs (runs in this engine, used by the tests)."""
    version = BY_NAME[quick.fixtures[0]].version
    body, variables = combined_body(quick)
    plots = "".join(f'plot({variable}, "{fixture}.{name}")\n' for (fixture, name), variable in variables.items())
    return f'//@version={version}\nindicator("quick core {quick.name}")\n' + PRELUDE + body + plots


def source(quick: QuickScript, cells=None) -> str:
    cells = expected_cells(quick) if cells is None else cells
    versions = {BY_NAME[f].version for f in quick.fixtures}
    assert len(versions) == 1, "a quick script cannot mix Pine versions"
    version = versions.pop()
    body, variables = combined_body(quick)
    n = len(quick.fixtures)
    expected_total = [len(check_bars(quick, f)) * len(outputs(f)) for f in quick.fixtures]
    out = [
        f"//@version={version}",
        f"// Pine parity QUICK CHECK `{quick.name}`: {quick.title}.",
        "// Generated by `python -m ui.tradingview_mode.pine.parity` from fixtures.py and this engine's output - do not edit.",
        "// TradingView computes the fixture values itself; they are compared with the embedded expected values",
        "// of the local Pine engine. Add to ANY chart with at least 240 bars; read the table (top right).",
        f'indicator("parity quick {quick.name}", overlay=true)',
        PRELUDE.rstrip("\n"),
        body.rstrip("\n"),
        "// ---- quick parity check (TradingView only) ----",
        'bool qp_inject = input.bool(false, "Self-test: corrupt one expected value (must FAIL)")',
        f"float QP_ABS = {format(Decimal(repr(ABS_TOL)), 'f')}",
        f"float QP_REL = {format(Decimal(repr(REL_TOL)), 'f')}",
        f"var array<int> qp_count = array.new<int>({n}, 0)",
        f"var array<int> qp_fail = array.new<int>({n}, 0)",
        f"var array<float> qp_maxdiff = array.new<float>({n}, 0.0)",
        "var array<string> qp_fbar = array.new<string>()",
        "var array<string> qp_ffield = array.new<string>()",
        "var array<string> qp_ftv = array.new<string>()",
        "var array<string> qp_fours = array.new<string>()",
        "var array<string> qp_fdiff = array.new<string>()",
        "qp_text(float value) => na(value) ? \"na\" : str.tostring(value, \"0.############\")",
        "qp_same(float tv, float expected) =>",
        "    (na(tv) and na(expected)) or (not na(tv) and not na(expected) and math.abs(tv - expected) <= QP_ABS + QP_REL * math.abs(expected))",
        "qp_check(int fx, string field, float tv, string expectedText) =>",
        "    float expected = str.tonumber(expectedText)",
        "    if qp_inject and fx == 0 and array.get(qp_count, 0) == 0",
        "        expected := nz(expected) + 0.001",
        "    bool ok = qp_same(tv, expected)",
        "    array.set(qp_count, fx, array.get(qp_count, fx) + 1)",
        "    if not na(tv) and not na(expected)",
        "        array.set(qp_maxdiff, fx, math.max(array.get(qp_maxdiff, fx), math.abs(tv - expected)))",
        "    if not ok",
        "        array.set(qp_fail, fx, array.get(qp_fail, fx) + 1)",
        f"        if array.size(qp_fbar) < {MAX_FAILURES}",
        "            array.push(qp_fbar, str.tostring(bar_index))",
        "            array.push(qp_ffield, field)",
        "            array.push(qp_ftv, qp_text(tv))",
        "            array.push(qp_fours, qp_text(expected))",
        "            array.push(qp_fdiff, na(tv) or na(expected) ? \"na vs value\" : qp_text(math.abs(tv - expected)))",
        "    ok",
    ]
    for index, fixture in enumerate(quick.fixtures):
        short = fixture[:3]
        bars = check_bars(quick, fixture)
        out.append(f"var array<int> qp_bars_{short} = array.from({', '.join(map(str, bars))})")
        for name in outputs(fixture):
            out.append(f"var array<string> qp_x_{short}_{name} = str.split({_literal(','.join(cells[fixture][name]))}, \",\")")
    for index, fixture in enumerate(quick.fixtures):
        short = fixture[:3]
        out.append(f"int qp_i_{short} = array.indexof(qp_bars_{short}, bar_index)")
        out.append(f"if qp_i_{short} >= 0")
        for name in outputs(fixture):
            out.append(f'    qp_check({index}, "{short} {name}", {variables[(fixture, name)]}, '
                       f"array.get(qp_x_{short}_{name}, qp_i_{short}))")
    # key values: what TradingView computed, shown by name
    for number, (fixture, name, bar) in enumerate(quick.keys):
        out.append(f"var float qp_key{number} = na")
        out.append(f"if bar_index == {bar}")
        out.append(f"    qp_key{number} := {variables[(fixture, name)]}")
    rows = 4 + n + 1 + len(quick.keys) + 2 + MAX_FAILURES
    out += [
        f"var table qp_table = table.new(position.top_right, 6, {rows}, bgcolor=color.white, border_color=color.gray, "
        "border_width=1, frame_color=color.gray, frame_width=1)",
        "qp_put(int col, int row, string txt, color bg) =>",
        "    table.cell(qp_table, col, row, txt, text_color=color.black, bgcolor=bg, text_size=size.normal)",
        "if barstate.islast",
        f'    qp_put(0, 0, "PINE P1 QUICK PARITY · {quick.name}" + (qp_inject ? " · SELF-TEST (1 failure expected)" : ""), color.white)',
        "    table.merge_cells(qp_table, 0, 0, 5, 0)",
        f'    qp_put(0, 1, "tolerance: |TV - ours| <= {format(Decimal(repr(ABS_TOL)), "f")} + {format(Decimal(repr(REL_TOL)), "f")} x |ours|; na must match na", color.white)',
        "    table.merge_cells(qp_table, 0, 1, 5, 1)",
        '    qp_put(0, 2, "fixture", color.silver)',
        '    qp_put(1, 2, "cells expected", color.silver)',
        '    qp_put(2, 2, "checked", color.silver)',
        '    qp_put(3, 2, "failed", color.silver)',
        '    qp_put(4, 2, "max |diff|", color.silver)',
        '    qp_put(5, 2, "RESULT", color.silver)',
        "    int qp_allFail = 0",
        "    bool qp_complete = true",
    ]
    for index, fixture in enumerate(quick.fixtures):
        row = 3 + index
        out += [
            f"    int qp_c{index} = array.get(qp_count, {index})",
            f"    int qp_f{index} = array.get(qp_fail, {index})",
            f"    bool qp_ok{index} = qp_f{index} == 0 and qp_c{index} == {expected_total[index]}",
            f"    qp_allFail += qp_f{index}",
            f"    qp_complete := qp_complete and qp_c{index} == {expected_total[index]}",
            f'    qp_put(0, {row}, "{fixture}", color.white)',
            f'    qp_put(1, {row}, "{expected_total[index]}", color.white)',
            f"    qp_put(2, {row}, str.tostring(qp_c{index}), color.white)",
            f"    qp_put(3, {row}, str.tostring(qp_f{index}), color.white)",
            f"    qp_put(4, {row}, qp_text(array.get(qp_maxdiff, {index})), color.white)",
            f'    qp_put(5, {row}, qp_ok{index} ? "PASS" : qp_c{index} < {expected_total[index]} ? "INCOMPLETE" : "FAIL", '
            f"qp_ok{index} ? color.lime : color.red)",
        ]
    row = 3 + n
    out += [
        f'    qp_put(0, {row}, "ALL", color.silver)',
        f'    qp_put(1, {row}, "{sum(expected_total)}", color.silver)',
        f'    qp_put(3, {row}, str.tostring(qp_allFail), color.silver)',
        f'    qp_put(5, {row}, qp_allFail == 0 and qp_complete ? "PASS" : "FAIL", '
        "qp_allFail == 0 and qp_complete ? color.lime : color.red)",
    ]
    row += 1
    for number, (fixture, name, bar) in enumerate(quick.keys):
        expected = cells[fixture][name][check_bars(quick, fixture).index(bar)]
        out += [f'    qp_put(0, {row}, "KEY {fixture} {name} @ bar {bar}", color.white)',
                f"    table.merge_cells(qp_table, 0, {row}, 2, {row})",
                f'    qp_put(3, {row}, "TV " + qp_text(qp_key{number}), color.white)',
                f'    qp_put(4, {row}, "ours {expected}", color.white)',
                f'    qp_put(5, {row}, qp_same(qp_key{number}, str.tonumber("{expected}")) ? "same" : "DIFFERENT", '
                f"qp_same(qp_key{number}, str.tonumber(\"{expected}\")) ? color.white : color.red)"]
        row += 1
    out += [
        f'    qp_put(0, {row}, array.size(qp_fbar) == 0 ? "no failures" : "FIRST FAILURES", color.silver)',
        f"    table.merge_cells(qp_table, 0, {row}, 5, {row})",
        f'    qp_put(0, {row + 1}, "bar", color.silver)',
        f'    qp_put(1, {row + 1}, "field", color.silver)',
        f'    qp_put(2, {row + 1}, "TV", color.silver)',
        f'    qp_put(3, {row + 1}, "ours", color.silver)',
        f'    qp_put(4, {row + 1}, "diff", color.silver)',
        "    for qp_j = 0 to array.size(qp_fbar) - 1",
        "        if array.size(qp_fbar) > 0",
        f"            qp_put(0, {row + 2} + qp_j, array.get(qp_fbar, qp_j), color.white)",
        f"            qp_put(1, {row + 2} + qp_j, array.get(qp_ffield, qp_j), color.white)",
        f"            qp_put(2, {row + 2} + qp_j, array.get(qp_ftv, qp_j), color.white)",
        f"            qp_put(3, {row + 2} + qp_j, array.get(qp_fours, qp_j), color.white)",
        f"            qp_put(4, {row + 2} + qp_j, array.get(qp_fdiff, qp_j), color.white)",
        'plot(bar_index, "bi", display=display.data_window)',
    ]
    return "\n".join(out) + "\n"


def write_quick() -> None:
    QUICK_DIR.mkdir(exist_ok=True)
    for quick in QUICK_SCRIPTS:
        (QUICK_DIR / f"{quick.name}.pine").write_text(source(quick))


# ---- simulation of the generated checker (tests) --------------------------------------------------------------

_BARS = re.compile(r"^var array<int> qp_bars_(\w+?) = array\.from\((.*)\)$", re.M)
_DATA = re.compile(r'^var array<string> qp_x_(s\d\d)_(\w+) = str\.split\("(.*)", ","\)$', re.M)
_CALL = re.compile(r'^    qp_check\((\d+), "(s\d\d) (\w+)", (\w+), ', re.M)


def simulate(script_text: str, tv: dict, bars: int = PERIOD, inject: bool = False) -> dict:
    """Run the comparison of a generated quick script in Python: the expected values are read back out of
    the script text, ``tv`` maps fixture short name (``s05``) -> {output: list of values per bar}."""
    check_bars_ = {short: [int(b) for b in body.split(",")] for short, body in _BARS.findall(script_text)}
    data = {(short, name): text.split(",") for short, name, text in _DATA.findall(script_text)}
    calls = _CALL.findall(script_text)
    count, fail, failures = {}, {}, []
    for bar in range(bars):
        for fx, short, name, _variable in calls:
            fx = int(fx)
            if bar not in check_bars_[short]:
                continue
            text = data[(short, name)][check_bars_[short].index(bar)]
            expected = None if text == "na" else float(text)
            if inject and fx == 0 and count.get(0, 0) == 0:
                expected = (expected or 0.0) + 0.001
            value = tv[short][name][bar]
            ok = compare(value, expected)
            count[fx] = count.get(fx, 0) + 1
            if not ok:
                fail[fx] = fail.get(fx, 0) + 1
                if len(failures) < MAX_FAILURES:
                    failures.append((bar, f"{short} {name}", value, expected))
    return {"count": count, "fail": fail, "failures": failures}
