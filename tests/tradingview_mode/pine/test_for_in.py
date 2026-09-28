"""P2.2-A2 `for ... in`: the semantics recorded on real TradingView (P22_FORIN_EVIDENCE.md: q6, q6r, q6n, q6e,
q6c_x, q6c_i, q6d). Runtime observations were identical in Pine v5 and v6, so every semantic case runs in both.

Each case records what the loop saw into an `out` array and plots it; `g()` returns -1 past the end.
"""
import hashlib
from pathlib import Path

import pytest

from ui.tradingview_mode.pine import PineExecution, compile_script, run_script
from ui.tradingview_mode.pine.builtins.arrays import RE10051, RE10052
from ui.tradingview_mode.pine.errors import ERROR

from .helpers import bars, context, plots, run
from .test_arrays import Live

PARITY = Path("ui/tradingview_mode/pine/parity")
VERSIONS = pytest.mark.parametrize("version", [5, 6])
WIDTH = 8


def source(body: str, version: int, observe_a: bool = True) -> str:
    lines = [f"//@version={version}", 'indicator("t")',
             "g(array<int> o, int k) => k < array.size(o) ? array.get(o, k) : -1",
             "out = array.new_int()", body.strip("\n"), 'plot(array.size(out), "n")']
    lines += [f'plot(g(out, {k}), "s{k}")' for k in range(WIDTH)]
    if observe_a:
        lines += ['plot(array.size(a), "an")'] + [f'plot(g(a, {k}), "a{k}")' for k in range(WIDTH)]
    return "\n".join(lines) + "\n"


def observe(body: str, version: int, observe_a: bool = True):
    """(sequence recorded in `out`, contents of `a` after the loop) on the last bar."""
    out, _ = run(source(body, version, observe_a), bars(3))
    p = {k: v[-1] for k, v in plots(out).items()}
    seq = [int(p[f"s{k}"]) for k in range(int(p["n"]))]
    after = [int(p[f"a{k}"]) for k in range(int(p["an"]))] if observe_a else None
    return seq, after


def compile_errors(body: str, version: int) -> list[tuple[int, str]]:
    result = compile_script(f'//@version={version}\nindicator("t")\n' + body.strip("\n") + "\n")
    return [(d.line, d.message) for d in result.diagnostics if d.kind == ERROR]


def runtime_error(body: str, version: int):
    result = compile_script(f'//@version={version}\nindicator("t")\n' + body.strip("\n") + "\n")
    assert result.ok, [d.text() for d in result.diagnostics]
    return run_script(PineExecution(result.program, {}), context(bars(3)), ("t",), "t").error


# ---- q6 main (v5 = v6) ----------------------------------------------------------------------------------------------

@VERSIONS
def test_q1_iterates_every_element_in_order(version):
    assert observe("a = array.from(10, 20, 30)\nfor x in a\n    array.push(out, x)", version) == ([10, 20, 30],
                                                                                                    [10, 20, 30])


@VERSIONS
def test_q1b_the_item_is_the_value_bound_when_the_iteration_starts(version):
    body = """
a = array.from(10, 20, 30)
for x in a
    if array.size(out) == 0
        array.set(a, 0, 999)
    array.push(out, x)
"""
    assert observe(body, version) == ([10, 20, 30], [999, 20, 30])


@VERSIONS
def test_q2_index_and_item(version):
    body = "a = array.from(10, 20, 30)\nfor [i, x] in a\n    array.push(out, i * 100 + x)"
    assert observe(body, version)[0] == [10, 120, 230]          # 0:10 1:20 2:30


@VERSIONS
def test_q3_later_elements_are_read_live(version):
    body = """
a = array.from(10, 20, 30, 40)
for x in a
    if array.size(out) == 0
        array.set(a, 2, 99)
    array.push(out, x)
"""
    assert observe(body, version) == ([10, 20, 99, 40], [10, 20, 99, 40])


@VERSIONS
def test_q9_an_empty_array_runs_zero_times(version):
    assert observe("a = array.new_int()\nfor x in a\n    array.push(out, x)", version) == ([], [])


@VERSIONS
def test_q12_nested_loops(version):
    body = """
a = array.from(1, 2)
b = array.from(10, 20)
for x in a
    for y in b
        array.push(out, x * 100 + y)
"""
    assert observe(body, version)[0] == [110, 120, 210, 220]    # 1/10 1/20 2/10 2/20


@VERSIONS
def test_q13_continue_and_break(version):
    body = """
a = array.from(1, 2, 3, 4, 5)
for x in a
    if x == 2
        continue
    if x == 4
        break
    array.push(out, x)
"""
    assert observe(body, version)[0] == [1, 3]


@VERSIONS
def test_q14a_iterating_a_copy_while_mutating_the_original(version):
    body = """
a = array.from(1, 2, 3)
c = array.copy(a)
for x in c
    if array.size(out) == 0
        array.set(a, 1, 77)
        array.push(a, 8)
    array.push(out, x)
"""
    assert observe(body, version) == ([1, 2, 3], [1, 77, 3, 8])


@VERSIONS
def test_q14b_iterating_the_original_while_mutating_a_copy(version):
    body = """
a = array.from(1, 2, 3)
d = array.copy(a)
for x in a
    if array.size(out) == 0
        array.set(d, 1, 77)
        array.push(d, 8)
    array.push(out, x)
plot(array.size(d), "dn")
plot(array.get(d, 1), "d1")
"""
    out, _ = run(source(body, version), bars(3))
    p = {k: v[-1] for k, v in plots(out).items()}
    assert observe(body, version) == ([1, 2, 3], [1, 2, 3]) and (p["dn"], p["d1"]) == (4, 77)


# ---- q6r: the size is re-read before every iteration (v5 = v6) -------------------------------------------------------

@VERSIONS
@pytest.mark.parametrize("start,mutation,sequence,after", [
    ("1, 2, 3", "array.push(a, 4)", [1, 2, 3, 4], [1, 2, 3, 4]),            # Case 4 (observed)
    ("1, 2, 3, 4", "array.pop(a)", [1, 2, 3], [1, 2, 3]),                   # Case 5 (observed)
    ("1, 2, 3, 4", "array.shift(a)", [1, 3, 4], [2, 3, 4]),                 # Q6 (derived from Q3 + Case 5)
    ("1, 2, 3, 4", "array.clear(a)", [1], []),                              # Q8 (derived from Q3 + Case 5)
])
def test_q6r_growth_and_shrinkage_during_the_loop(version, start, mutation, sequence, after):
    body = f"""
a = array.from({start})
for x in a
    if array.size(out) == 0
        {mutation}
    array.push(out, x)
"""
    assert observe(body, version) == (sequence, after)


@VERSIONS
def test_q6r_case7_remove_ahead_in_the_indexed_form(version):
    body = """
a = array.from(1, 2, 3, 4, 5)
for [i, x] in a
    if i == 1
        array.remove(a, 3)
    array.push(out, i * 100 + x)
"""
    assert observe(body, version) == ([1, 102, 203, 305], [1, 2, 3, 5])      # 0:1 1:2 2:3 3:5


# ---- q6n / q6e: na arrays and the bound object ---------------------------------------------------------------------

@VERSIONS
def test_q6n_an_na_array_is_re10052_at_the_loop(version):
    body = """
array<int> a = na
s = 0
for x in a
    s += 1
plot(s)
"""
    assert runtime_error(body, version) == {"message": RE10052, "line": 5, "bar_index": 0}


@VERSIONS
def test_q6e_reassigning_the_variable_does_not_redirect_the_loop(version):
    body = """
a = array.from(1, 2, 3)
for x in a
    if array.size(out) == 0
        a := array.from(7, 8, 9, 10)
    array.push(out, x)
"""
    assert observe(body, version) == ([1, 2, 3], [7, 8, 9, 10])


@VERSIONS
def test_the_array_expression_is_evaluated_once(version):
    body = """
calls = array.new_int()
src() =>
    array.push(calls, 1)
    array.from(5, 6, 7)
for x in src()
    array.push(out, x)
plot(array.size(calls), "calls")
"""
    out, _ = run(source(body, version, observe_a=False), bars(3))
    p = {k: v[-1] for k, v in plots(out).items()}
    assert p["calls"] == 1 and observe(body, version, observe_a=False)[0] == [5, 6, 7]


# ---- q6c_x / q6c_i / q6d: read-only loop variables and scopes -------------------------------------------------------

@VERSIONS
@pytest.mark.parametrize("statement,name", [("x := x * 2", "x"), ("i := i + 10", "i"), ("x += 1", "x"),
                                            ("i -= 1", "i")])
def test_q6c_loop_variables_are_read_only_ce10174(version, statement, name):
    errors = compile_errors(f"a = array.from(10, 20, 30)\nfor [i, x] in a\n    {statement}\nplot(0)", version)
    assert errors == [(5, f'Variable "{name}" cannot be mutable: `for ... in` loop variables are read-only.')]


@VERSIONS
def test_q6c_the_single_item_form_is_read_only_too(version):
    errors = compile_errors("a = array.from(1)\nfor x in a\n    x := 2\nplot(0)", version)
    assert len(errors) == 1 and 'Variable "x" cannot be mutable' in errors[0][1]


@VERSIONS
def test_q6d_same_name_nested_loops_shadow_and_restore(version):
    body = """
a = array.from(1, 2)
b = array.from(10, 20)
for x in a
    for x in b
        array.push(out, x)
    array.push(out, 1000 + x)
"""
    assert observe(body, version)[0] == [10, 20, 1001, 10, 20, 1002]    # "after inner 1" / "after inner 2"
    assert compile_errors("out = array.new_int()" + body + "plot(0)", version) == []


@VERSIONS
def test_a_loop_variable_does_not_leak_and_an_outer_variable_stays_mutable(version):
    body = """
x = 0
a = array.from(4, 5)
for x in a
    array.push(out, x)
x := 9
array.push(out, x)
"""
    assert observe(body, version)[0] == [4, 5, 9]


# ---- interaction with P2.2-A1 --------------------------------------------------------------------------------------

@VERSIONS
def test_iterating_a_historical_array_reads_the_previous_bar(version):
    body = """
var array<int> m = array.new_int()
array.push(m, bar_index)
if bar_index > 0
    for x in m[1]
        array.push(out, x)
"""
    assert observe(body, version, observe_a=False)[0] == [0, 1]      # bar 2 sees bar 1's [0, 1]


def test_mutating_a_historical_array_inside_the_loop_is_still_re10051():
    body = """
var array<int> m = array.new_int()
array.push(m, bar_index)
if bar_index > 0
    for x in m[1]
        array.push(m[1], x)
plot(0)
"""
    assert runtime_error(body, 6) == {"message": RE10051, "line": 7, "bar_index": 1}


def test_function_local_var_arrays_iterate_per_call_site():
    body = """
f(int v) =>
    var array<int> acc = array.new_int()
    array.push(acc, v)
    s = 0
    for x in acc
        s += x
    s
plot(f(1), "one")
plot(f(10), "ten")
"""
    out, _ = run('//@version=6\nindicator("t")\n' + body, bars(4))
    p = plots(out)
    assert p["one"] == [1, 2, 3, 4] and p["ten"] == [10, 20, 30, 40]


def test_realtime_ticks_iterate_the_committed_var_array():
    live = Live("""
var array<float> acc = array.new_float()
array.push(acc, 1.0)
float s = 0.0
for x in acc
    s += x
plot(s, "s")
""", history=5)
    first = live.start()["s"]
    assert live.tick()["s"] == first and live.tick()["s"] == first
    assert live.new_bar()["s"] == first + 1


def test_the_loop_limit_stops_endless_growth():
    body = "a = array.from(1)\nfor x in a\n    array.push(a, x)\nplot(0)"
    error = runtime_error(body, 6)
    assert error is not None and ("at most 100,000 elements" in error["message"]
                                  or "Loop exceeded" in error["message"])


def test_discarded_index_float_items_and_a_literal_na():
    out, _ = run('//@version=6\nindicator("t")\na = array.from(1.5, 2.5)\ns = 0.0\nfor [_, x] in a\n    s += x\n'
                 't = 0.0\nfor [i, x] in a\n    t += x * i\nplot(s, "s")\nplot(t, "t")\n', bars(2))
    p = plots(out)
    assert (p["s"][-1], p["t"][-1]) == (4.0, 2.5)
    assert runtime_error("s = 0\nfor x in na\n    s += 1\nplot(s)", 6)["message"] == RE10052


# ---- analyzer boundaries --------------------------------------------------------------------------------------------

def test_iterating_a_scalar_is_a_compile_error():
    assert compile_errors("n = 3\ns = 0\nfor x in n\n    s += 1\nplot(s)", 6) == [
        (5, "`for ... in` needs an array; `int` cannot be iterated.")]


def test_for_in_is_no_longer_a_gap_and_stays_out_of_request_security():
    ok = compile_script('//@version=6\nindicator("t")\na = array.from(1)\ns = 0\nfor x in a\n    s += x\nplot(s)\n')
    assert ok.ok and "for-in" in ok.program.features
    body = """
f() =>
    s = 0
    for x in array.from(1, 2)
        s += x
    s
plot(request.security(syminfo.tickerid, "60", f()))
"""
    result = compile_script('//@version=6\nindicator("t")\n' + body)
    assert not result.ok and any("arrays in a requested expression are not implemented yet" in d.message
                                 for d in result.diagnostics)


@pytest.mark.parametrize("body,compiles", [
    ('f() => array.size(array.from(1.0))\nplot(request.security(syminfo.tickerid, "60", f()))', False),
    ('g() => array.size(array.from(1.0))\nf() => g() + 1\nplot(request.security(syminfo.tickerid, "60", f()))', False),
    ('g() => array.size(array.from(1.0))\nf() => g() + 1\nv = f()\nplot(request.security(syminfo.tickerid, "60", v))',
     False),
    ('f(array<float> a) => array.size(a)\nplot(request.security(syminfo.tickerid, "60", close))', True),
])
def test_arrays_in_functions_reached_by_request_security_are_rejected(body, compiles):
    # closes an A1 hole: array uses inside user functions reached by the requested expression were not scanned
    result = compile_script('//@version=6\nindicator("t")\n' + body + "\n")
    assert result.ok is compiles
    if not compiles:
        assert any("arrays in a requested expression are not implemented yet" in d.message for d in result.diagnostics)


def test_frozen_q6_oracle_scripts_are_byte_identical():
    evidence = (PARITY / "P22_FORIN_EVIDENCE.md").read_text()
    names = sorted(p.name for p in (PARITY / "quick").glob("q6*.pine"))
    assert len(names) == 14
    for name in names:
        digest = hashlib.sha256((PARITY / "quick" / name).read_bytes()).hexdigest()
        assert f"| `quick/{name}` | `{digest}` |" in evidence, name
