"""P2.2-A3 built-in array method syntax: `a.push(x)` is `array.push(a, x)`.

Pine's documentation states that `<namespace>.<function>(<object>, ...)` and `<object>.<function>(...)` are
equivalent (Methods page, v5 and v6), so every test compares the method form with the namespace form, which carries
the A1/A2 real-TradingView evidence (P22_ARRAY_EVIDENCE.md, P22_FORIN_EVIDENCE.md).
"""
import pytest

from ui.tradingview_mode.pine import PineExecution, compile_script, run_script
from ui.tradingview_mode.pine.builtins.arrays import RE10051, RE10052
from ui.tradingview_mode.pine.errors import ERROR, GAP

from .helpers import bars, context, plots, run
from .test_arrays import Live

VERSIONS = pytest.mark.parametrize("version", [5, 6])


def program(body: str, version: int = 6) -> str:
    return f'//@version={version}\nindicator("t")\n' + body.strip("\n") + "\n"


def series(body: str, version: int = 6, n: int = 4) -> dict:
    out, _ = run(program(body, version), bars(n))
    return plots(out)


def failure(body: str, version: int = 6):
    result = compile_script(program(body, version))
    assert result.ok, [d.text() for d in result.diagnostics]
    return run_script(PineExecution(result.program, {}), context(bars(3)), ("t",), "t").error


def diagnostics(body: str, version: int = 6) -> list[tuple[str, str]]:
    return [(d.kind, d.message) for d in compile_script(program(body, version)).diagnostics
            if d.kind in (ERROR, GAP)]


OBSERVE = """
g(array<int> o, int k) => k < array.size(o) ? array.get(o, k) : -1
a = array.from(bar_index, 2, 3)
{op}
plot(r, "r")
plot(array.size(a), "n")
plot(g(a, 0), "a0")
plot(g(a, 1), "a1")
plot(g(a, 2), "a2")
plot(g(a, 3), "a3")
"""

# (name, namespace form, method form, expected on bar 2: (r, size, a0..a3))
OPERATIONS = [
    ("size", "r = array.size(a)", "r = a.size()", (3, 3, 2, 2, 3, -1)),
    ("push", "array.push(a, 4)\nr = 0", "a.push(4)\nr = 0", (0, 4, 2, 2, 3, 4)),
    ("pop", "r = array.pop(a)", "r = a.pop()", (3, 2, 2, 2, -1, -1)),
    ("shift", "r = array.shift(a)", "r = a.shift()", (2, 2, 2, 3, -1, -1)),
    ("unshift", "array.unshift(a, 9)\nr = 0", "a.unshift(9)\nr = 0", (0, 4, 9, 2, 2, 3)),
    ("get", "r = array.get(a, 2)", "r = a.get(2)", (3, 3, 2, 2, 3, -1)),
    ("set", "array.set(a, 1, 7)\nr = 0", "a.set(1, 7)\nr = 0", (0, 3, 2, 7, 3, -1)),
    ("first", "r = array.first(a)", "r = a.first()", (2, 3, 2, 2, 3, -1)),
    ("last", "r = array.last(a)", "r = a.last()", (3, 3, 2, 2, 3, -1)),
    ("copy", "c = array.copy(a)\narray.push(c, 5)\nr = array.size(c)", "c = a.copy()\nc.push(5)\nr = c.size()",
     (4, 3, 2, 2, 3, -1)),
    ("clear", "array.clear(a)\nr = 0", "a.clear()\nr = 0", (0, 0, -1, -1, -1, -1)),
    ("remove", "r = array.remove(a, 1)", "r = a.remove(1)", (2, 2, 2, 3, -1, -1)),
]


@VERSIONS
@pytest.mark.parametrize("name,namespace,method,expected", OPERATIONS, ids=[o[0] for o in OPERATIONS])
def test_every_array_method_equals_its_namespace_call(version, name, namespace, method, expected):
    by_namespace = series(OBSERVE.format(op=namespace), version, n=3)
    by_method = series(OBSERVE.format(op=method), version, n=3)
    assert by_method == by_namespace
    assert tuple(by_method[k][-1] for k in ("r", "n", "a0", "a1", "a2", "a3")) == expected


def test_named_arguments_after_the_receiver():
    p = series('a = array.from(1, 2, 3)\na.set(index = 0, value = 8)\nplot(a.get(index = 0), "v")')
    assert set(p["v"]) == {8}


# ---- persistence, aliases, functions (A1 rules through the method form) --------------------------------------------

def test_var_array_methods_persist_like_namespace_calls():
    method = series('var array<int> m = array.new_int()\nm.push(bar_index)\nplot(m.size(), "n")\nplot(m.last(), "l")')
    namespace = series('var array<int> m = array.new_int()\narray.push(m, bar_index)\nplot(array.size(m), "n")\n'
                       'plot(array.last(m), "l")')
    assert method == namespace and method["n"] == [1, 2, 3, 4] and method["l"] == [0, 1, 2, 3]


def test_realtime_var_rolls_back_and_varip_keeps_ticks_through_methods():
    live = Live("""
var array<float> v = array.new_float()
varip array<float> w = array.new_float()
if barstate.isrealtime
    v.push(1.0)
    w.push(1.0)
plot(v.size(), "v")
plot(w.size(), "w")
""", history=5)
    start = live.start()
    first, second = live.tick(), live.tick()
    assert (start["v"], first["v"], second["v"]) == (1, 1, 1)          # m04 A: var restarts from the committed state
    assert (start["w"], first["w"], second["w"]) == (1, 2, 3)          # m04 B: varip keeps every execution
    assert live.new_bar()["v"] == 2


def test_aliases_share_the_object_through_methods():
    p = series('a = array.from(1, 2)\nb = a\nb.push(3)\narray.push(a, 4)\nplot(a.size(), "a")\nplot(b.size(), "b")')
    assert set(p["a"]) == {4} and set(p["b"]) == {4}


def test_function_local_var_arrays_per_call_site_through_methods():
    p = series("""
f(int v) =>
    var array<int> acc = array.new_int()
    acc.push(v)
    acc.size() * v
plot(f(1), "one")
plot(f(10), "ten")
""")
    assert p["one"] == [1, 2, 3, 4] and p["ten"] == [10, 20, 30, 40]


def test_mutation_through_a_parameter_and_parameter_rebinding_still_rejected():
    p = series('f(array<int> p) =>\n    p.push(7)\n    p.size()\na = array.from(1)\nn = f(a)\nplot(n, "n")\n'
               'plot(a.size(), "a")')
    assert set(p["n"]) == {2} and set(p["a"]) == {2}
    assert ("error", "Function arguments cannot be mutable (`p`).") in diagnostics(
        "f(array<int> p) =>\n    p := array.new_int()\n    p.size()\nplot(f(array.from(1)))")


def test_methods_inside_for_in_keep_the_live_size_rule():
    p = series("""
a = array.from(1, 2, 3)
out = array.new_int()
for x in a
    if out.size() == 0
        a.push(4)
    out.push(x)
plot(out.size(), "n")
plot(out.last(), "l")
""")
    assert set(p["n"]) == {4} and set(p["l"]) == {4}                    # q6r Case 4


# ---- history, na, receivers of unknown type ------------------------------------------------------------------------

@pytest.mark.parametrize("mutation", ["m[1].push(1)", "(m[1]).push(1)", "m[1].set(0, 1)", "m[1].pop()",
                                      "m[1].shift()", "m[1].unshift(1)", "m[1].clear()", "m[1].remove(0)"])
def test_mutating_methods_on_a_historical_array_are_re10051(mutation):
    error = failure(f"var array<int> m = array.new_int()\nm.push(bar_index)\nif bar_index >= 1\n    {mutation}\n"
                    "plot(m.size())")
    assert error == {"message": RE10051, "line": 6, "bar_index": 1}


def test_reading_and_copying_a_historical_array_through_methods():
    p = series("""
var array<int> m = array.new_int()
m.push(bar_index)
int prev = 0
int copied = 0
if bar_index >= 1
    prev := m[1].size()
    c = m[1].copy()
    c.push(99)
    copied := c.last()
plot(prev, "prev")
plot(copied, "copied")
""")
    assert p["prev"] == [0, 1, 2, 3] and p["copied"] == [0, 99, 99, 99]


def test_na_arrays_fail_exactly_like_namespace_calls():
    assert failure("array<int> a = na\nplot(a.size())") == failure("array<int> a = na\nplot(array.size(a))")
    assert failure("array<int> a = na\na.push(1)\nplot(0)")["message"] == "`array.push()`: the array is na."
    assert failure("array<int> a = na\nfor x in a\n    x\nplot(0)")["message"] == RE10052      # A2 unchanged


def test_receivers_of_unknown_type_dispatch_to_arrays_and_are_checked_at_run_time():
    p = series("mk() => array.from(4, 5, 6)\nx = mk()\nplot(x.size(), \"n\")\nplot(mk().last(), \"l\")")
    assert set(p["n"]) == {3} and set(p["l"]) == {6}
    error = failure("f(v) => v.size()\nplot(f(close))")
    assert error["message"] == "`array.size()`: the `id` argument is not an array."


# ---- diagnostics -------------------------------------------------------------------------------------------------

def test_unknown_and_unimplemented_methods():
    assert diagnostics("a = array.from(1)\na.nosuch()\nplot(0)") == [
        ("error", "Could not find method `nosuch()` for arrays.")]
    assert diagnostics("a = array.from(1.0)\na.sort()\nplot(0)") == [
        ("gap", "`array.sort()` is not implemented yet (arrays).")]
    assert diagnostics("a = array.from(1.0)\narray.sort(a)\nplot(0)") == [
        ("gap", "`array.sort()` is not implemented yet (arrays).")]


@pytest.mark.parametrize("body,base", [("x = close\nplot(x.size())", "float"), ("n = 3\nplot(n.size())", "int"),
                                       ('s = "a"\nplot(s.size())', "string")])
def test_methods_on_non_arrays_are_compile_errors(body, base):
    assert diagnostics(body) == [("error", f"Could not find method `size()` for a `{base}` value.")]


def test_type_checks_match_the_namespace_form():
    method = diagnostics('a = array.from(1)\na.push("s")\nplot(0)')
    namespace = diagnostics('a = array.from(1)\narray.push(a, "s")\nplot(0)')
    assert method == namespace and len(method) == 1
    assert diagnostics("a = array.from(1)\nplot(a.get())") == diagnostics("a = array.from(1)\nplot(array.get(a))")


def test_mixing_forms_in_one_script():
    p = series('a = array.new_int()\narray.push(a, 1)\na.push(2)\narray.push(a, a.size() + 1)\n'
               'plot(a.size() * 100 + array.last(a), "v")')
    assert set(p["v"]) == {303}


def test_chaining_on_returned_arrays_and_not_on_void():
    p = series('a = array.from(1, 2, 3)\nplot(a.copy().size(), "s")\nplot(array.from(4, 5).copy().pop(), "p")\n'
               'plot(a.size(), "n")')
    assert set(p["s"]) == {3} and set(p["p"]) == {5} and set(p["n"]) == {3}
    assert diagnostics("a = array.from(1)\nplot(a.push(1).size())") == [
        ("error", "Cannot call method `size()`: `array.push()` does not return a value.")]


def test_array_equality_nested_arrays_and_request_security_rules_unchanged():
    assert any("Cannot compare arrays" in m for _, m in diagnostics("a = array.from(1)\nplot(a.copy() == a ? 1 : 0)"))
    assert any("Arrays of arrays" in m for _, m in diagnostics("array<array<float>> n = na\nplot(0)"))
    for body in ['a = array.from(1.0)\nplot(request.security(syminfo.tickerid, "60", a.size()))',
                 'f() => array.from(1.0).size()\nplot(request.security(syminfo.tickerid, "60", f()))']:
        assert any("arrays in a requested expression are not implemented yet" in m for _, m in diagnostics(body))


def test_namespace_calls_and_user_methods_are_unaffected():
    assert series('plot(ta.sma(close, 2), "s")')["s"][1] is not None
    assert diagnostics("method twice(array<int> a) => a.size() * 2\nplot(0)") == [
        ("gap", "Methods (`method twice`) are not implemented yet.")]
