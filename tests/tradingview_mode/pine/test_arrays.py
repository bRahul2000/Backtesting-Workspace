"""P2.2-A1 array core: the semantics recorded on real TradingView (P22_ARRAY_EVIDENCE.md: m04, m05, q5, q5b-q5e).

Historical cases run bar by bar; realtime cases drive the real PineExecution forming-bar path: every tick changes
the forming bar and re-executes it (rollback), and appending a bar starts the next one.
"""
import hashlib
from pathlib import Path

import pytest

from ui.tradingview_mode.pine import PineExecution, compile_script, run_script
from ui.tradingview_mode.pine.builtins.arrays import RE10051
from ui.tradingview_mode.pine.errors import ERROR

from .helpers import bars, context, plots, run, script

PARITY = Path("ui/tradingview_mode/pine/parity")


def values(body, n=12, version=6):
    source = f'//@version={version}\nindicator("t")\n' + body.strip("\n") + "\n"
    out, _ = run(source, bars(n))
    return plots(out)


def errors(body):
    result = compile_script(script(body))
    return [d.message for d in result.diagnostics if d.kind == ERROR]


class Live:
    """A live chart: `history` confirmed bars, then realtime ticks on a forming bar (P1 commit/rollback)."""

    def __init__(self, body, history=20):
        self.program = compile_script('//@version=6\nindicator("t")\n' + body.strip("\n") + "\n").program
        assert self.program is not None
        self.frame = bars(history + 10, seed=7)
        self.n = history + 1
        self.execution = PineExecution(self.program, {})
        self.tick_price = 100.0

    def _run(self):
        out = run_script(self.execution, context(self.frame.iloc[:self.n], forming_last=True), ("live",), "t")
        assert out.error is None, out.error
        return {k: v[-1] for k, v in plots(out).items()}

    def start(self):
        return self._run()

    def tick(self):
        self.tick_price += 0.25
        self.frame.loc[self.n - 1, "close"] = self.tick_price
        return self._run()

    def new_bar(self):
        self.n += 1
        return self._run()


# ---- H1: persistent aliases split across historical bars ---------------------------------------------------------

def test_h1_persistent_alias_slots_separate_across_historical_bars():
    p = values("""
var array<float> A = array.new_float()
var array<float> B = A
if bar_index >= 5 and bar_index < 8
    array.push(B, bar_index)
plot(array.size(A), "A")
plot(array.size(B), "B")
""")
    assert p["B"][5:9] == [1, 2, 3, 3] and set(p["A"]) == {0}        # B grows, A stays independent


def test_h1_same_bar_as_the_alias_initialisation_shares_the_object():
    p = values("""
var array<float> A = array.new_float()
var array<float> B = A
if bar_index == 0
    array.push(B, 1)
plot(array.size(A), "A")
""")
    assert p["A"][0] == 1 and p["A"][1] == 1                         # one execution: one object; then A keeps [1]


# ---- H2 / H3: same-execution aliasing and := ---------------------------------------------------------------------

def test_h2_local_alias_shares_within_the_execution():
    p = values("""
var array<float> a = array.new_float()
x = a
array.push(x, bar_index)
plot(array.size(a), "a")
plot(array.size(x), "x")
plot(array.last(a), "last")
""")
    assert p["a"] == p["x"] == list(range(1, 13)) and p["last"] == list(range(12))


def test_h3_reassignment_aliases_in_the_execution_and_slots_split_at_the_boundary():
    p = values("""
var array<float> A = array.new_float()
var array<float> B = array.new_float()
if bar_index == 3
    B := A
if bar_index >= 3
    array.push(B, bar_index)
plot(array.size(A), "A")
plot(array.size(B), "B")
""")
    assert p["A"][3] == p["B"][3] == 1                               # same execution: shared
    assert p["A"][4:] == [1] * 8                                     # next executions: A keeps its own [3]
    assert p["B"][4:] == list(range(2, 10))                          # B keeps the preserved contents and grows alone


# ---- H4: array.copy ------------------------------------------------------------------------------------------------

def test_h4_copy_is_independent_and_direct_alias_is_not():
    p = values("""
a = array.from(1.0)
d = a
c = array.copy(a)
array.push(d, 2)
array.push(c, 3)
plot(array.size(a), "a")
plot(array.size(c), "c")
plot(array.last(a), "la")
plot(array.last(c), "lc")
""")
    assert set(p["a"]) == {2} and set(p["c"]) == {2} and set(p["la"]) == {2} and set(p["lc"]) == {3}


# ---- H5 / H6: function parameters ---------------------------------------------------------------------------------

def test_h5_mutation_through_a_parameter_is_the_callers_array():
    p = values("""
pushInto(array<float> prm, float val) =>
    array.push(prm, val)
    array.size(prm)
var array<float> q = array.new_float()
inside = pushInto(q, bar_index)
plot(inside, "inside")
plot(array.size(q), "caller")
""")
    assert p["inside"] == p["caller"] == list(range(1, 13))


def test_h6_rebinding_an_array_parameter_is_rejected_scalar_parameters_unchanged():
    assert "Function arguments cannot be mutable (`prm`)." in errors("""
reassign(array<float> prm, float val) =>
    prm := array.new_float()
    array.push(prm, val)
    array.size(prm)
plot(reassign(array.new_float(), 1))
""")
    scalar = compile_script(script("f(float p) =>\n    p := p + 1\n    p\nplot(f(close))"))
    assert scalar.ok and not scalar.diagnostics                      # P1 behaviour for scalars is unchanged


# ---- H7: function-local var arrays --------------------------------------------------------------------------------

def test_h7_function_local_var_arrays_persist_per_call_site():
    p = values("""
f7(float val) =>
    var array<float> localArr = array.new_float()
    array.push(localArr, val)
    [array.size(localArr), array.last(localArr)]
[n1, l1] = f7(70 + bar_index)
[n2, l2] = f7(80 + bar_index)
plot(n1, "n1")
plot(n2, "n2")
plot(l1, "l1")
plot(l2, "l2")
""")
    assert p["n1"] == p["n2"] == list(range(1, 13))
    assert p["l1"][-1] == 81 and p["l2"][-1] == 91


# ---- H8 / H9: history ---------------------------------------------------------------------------------------------

def test_h8_history_is_the_previous_bars_state_and_current_stays_current():
    p = values("""
var array<float> h = array.new_float()
array.push(h, bar_index)
nv = array.from(bar_index * 10.0)
plot(array.size(h), "size")
plot(bar_index > 0 ? array.size(h[1]) : na, "prev size")
plot(bar_index > 0 ? array.last(h[1]) : na, "prev last")
plot(bar_index > 1 ? array.last(h[2]) : na, "prev2 last")
plot(bar_index > 0 ? array.last(nv[1]) : na, "nv prev")
""")
    assert p["size"] == list(range(1, 13))
    assert p["prev size"][1:] == list(range(1, 12)) and p["prev last"][1:] == list(range(0, 11))
    assert p["prev2 last"][2:] == list(range(0, 10)) and p["nv prev"][1:] == [10.0 * i for i in range(11)]


@pytest.mark.parametrize("mutation", ["array.push(m[1], 100)", "array.set(m[1], 0, 1.0)", "array.pop(m[1])",
                                      "array.shift(m[1])", "array.unshift(m[1], 1.0)", "array.clear(m[1])"])
def test_h9_mutating_a_historical_array_is_re10051(mutation):
    source = script(f"""
var array<float> m = array.new_float()
array.push(m, bar_index)
if bar_index >= 2
    {mutation}
plot(array.size(m))
""")
    result = compile_script(source)
    out = run_script(PineExecution(result.program, {}), context(bars(6)), ("t",), "t")
    assert out.error == {"message": RE10051, "line": 6, "bar_index": 2}


def test_h9_a_copy_of_a_historical_array_is_mutable_and_current_arrays_are_not_read_only():
    p = values("""
var array<float> m = array.new_float()
array.push(m, bar_index)
c = bar_index > 0 ? array.copy(m[1]) : array.new_float()
array.push(c, 99)
plot(array.size(c), "c")
plot(array.size(m), "m")
""")
    assert p["c"][1:] == list(range(2, 13)) and p["m"] == list(range(1, 13))


# ---- H10: equality ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("op", ["==", "!="])
def test_h10_array_equality_is_rejected(op):
    messages = errors(f"a = array.new_float()\nb = array.new_float()\nplot(a {op} b ? 1 : 0)")
    assert any(f"Cannot compare arrays with `{op}`" in m for m in messages)
    assert compile_script(script(f"plot(close {op} open ? 1 : 0)")).ok


# ---- H11: realtime m04 cases --------------------------------------------------------------------------------------

M04 = """
varip int execs = 0
execs += 1
bool rt = barstate.isrealtime
float code = bar_index * 1000000.0 + execs
var array<float> a = array.new_float()
varip array<float> b = array.new_float()
varip array<float> cOrigin = array.new_float()
var array<float> cAlias = cOrigin
var array<float> dOrigin = array.new_float()
varip array<float> dAlias = dOrigin
varip array<float> e = array.new_float()
varip array<float> e2 = na
int aN0 = array.size(a)
int bN0 = array.size(b)
int coN0 = array.size(cOrigin)
int caN0 = array.size(cAlias)
int doN0 = array.size(dOrigin)
int daN0 = array.size(dAlias)
int eN0 = array.size(e)
float eL0 = array.size(e) > 0 ? array.last(e) : na
int e2N0 = na(e2) ? -1 : array.size(e2)
bool e2Created = false
if rt
    array.push(a, code)
    array.push(b, code)
    array.push(cAlias, code)
    array.push(dAlias, code)
    array<float> fresh = array.new_float()
    array.push(fresh, code)
    e := fresh
    if na(e2)
        e2 := array.new_float()
        e2Created := true
    array.push(e2, code)
plot(code, "code")
plot(aN0, "aN0")
plot(array.size(a), "aN1")
plot(array.size(a) > 0 ? array.last(a) : na, "aL1")
plot(bN0, "bN0")
plot(coN0, "coN0")
plot(array.size(cOrigin), "coN1")
plot(caN0, "caN0")
plot(doN0, "doN0")
plot(array.size(dOrigin), "doN1")
plot(daN0, "daN0")
plot(eN0, "eN0")
plot(eL0, "eL0")
plot(e2N0, "e2N0")
plot(e2Created ? 1 : 0, "e2Created")
"""


def test_h11_realtime_m04_cases():
    live = Live(M04)
    ticks = [live.start()] + [live.tick() for _ in range(3)]          # bar R: 4 executions
    for k, t in enumerate(ticks):
        assert t["aN0"] == 0 and t["aN1"] == 1                        # A: var rolls back every tick
        assert t["bN0"] == k                                          # B: varip keeps every tick
        assert t["coN0"] == 0 and t["coN1"] == 0                      # C: varip origin never sees the var alias
        assert t["caN0"] == 0                                         # C: var alias rolls back
        assert t["doN0"] == 0 and t["doN1"] == 0                      # D: var origin never sees the varip alias
        assert t["daN0"] == k                                         # D: varip alias keeps every tick
        assert t["e2Created"] == (1 if k == 0 else 0)                 # E2: allocated once
        assert t["e2N0"] == (-1 if k == 0 else k)
        if k:
            assert t["eN0"] == 1 and t["eL0"] == ticks[k - 1]["code"]  # E: last tick's fresh array survived
    first = live.new_bar()                                            # bar R+1, first execution
    last_code = ticks[-1]["code"]
    assert first["aN0"] == 1 and first["bN0"] == 4 and first["caN0"] == 1 and first["daN0"] == 4
    assert first["coN0"] == 0 and first["doN0"] == 0
    assert first["eN0"] == 1 and first["eL0"] == last_code and first["e2N0"] == 4 and first["e2Created"] == 0
    second = live.tick()
    assert second["aN0"] == 1 and second["bN0"] == 5 and second["caN0"] == 1 and second["daN0"] == 5


def test_h11_var_arrays_equal_a_full_recompute_after_ticks():
    """A script that pushes on every execution: after realtime ticks the var array equals a full recompute on the
    same bars (it committed only the last execution of each bar); the varip array legitimately kept the ticks."""
    live = Live("""
var array<float> a = array.new_float()
varip array<float> b = array.new_float()
array.push(a, close)
array.push(b, close)
plot(array.size(a), "a")
plot(array.last(a), "a last")
plot(array.size(b), "b")
""")
    live.start()
    live.tick()
    live.tick()
    incremental = live.new_bar()
    full_out = run_script(PineExecution(live.program, {}), context(live.frame.iloc[:live.n], forming_last=True),
                          ("full",), "t")
    full = {k: v[-1] for k, v in plots(full_out).items()}
    assert incremental["a"] == full["a"] == live.n and incremental["a last"] == full["a last"]
    assert incremental["b"] == full["b"] + 2                          # the two extra ticks of the previous bar


# ---- H12: realtime m05 cases --------------------------------------------------------------------------------------

M05 = """
varip int execs = 0
execs += 1
bool rt = barstate.isrealtime
float code = bar_index * 1000000.0 + execs
var array<float> oA = array.new_float()
var array<float> aA = array.new_float()
varip array<float> oB = array.new_float()
varip array<float> aB = array.new_float()
var array<float> oC = array.new_float()
varip array<float> aC = array.new_float()
varip array<float> oD = array.new_float()
var array<float> aD = array.new_float()
plot(array.size(oA), "A o0")
plot(array.size(aA), "A a0")
plot(array.size(oB), "B o0")
plot(array.size(aB), "B a0")
plot(array.size(oC), "C o0")
plot(array.size(aC), "C a0")
plot(array.size(oD), "D o0")
plot(array.size(aD), "D a0")
if rt
    aA := oA
    aB := oB
    aC := oC
    aD := oD
plot(array.size(oA), "A o1")
plot(array.size(aA), "A a1")
plot(array.size(oD), "D o1")
plot(array.size(aD), "D a1")
if rt
    array.push(aA, code)
    array.push(aB, code)
    array.push(aC, code)
    array.push(aD, code)
plot(array.size(oA), "A o2")
plot(array.size(aA), "A a2")
plot(array.size(oB), "B o2")
plot(array.size(aB), "B a2")
plot(array.size(oC), "C o2")
plot(array.size(aC), "C a2")
plot(array.size(oD), "D o2")
plot(array.size(aD), "D a2")
plot(array.size(oD) > 0 ? array.last(oD) : na, "D o2 last")
plot(code, "code")
"""


def test_h12_realtime_m05_realias_every_tick():
    live = Live(M05)
    ticks = [live.start()] + [live.tick() for _ in range(3)]
    for k, t in enumerate(ticks):
        # same execution: `alias := origin` shares, and a push through the alias is seen by the origin
        assert (t["A o1"], t["A a1"]) == (t["A o0"], t["A o0"]) and t["A o2"] == t["A a2"] == t["A o0"] + 1
        assert t["D o1"] == t["D a1"] == t["D o0"] and t["D o2"] == t["D a2"] == t["D o0"] + 1
        assert t["B o2"] == t["B a2"] == t["B o0"] + 1 and t["C o2"] == t["C a2"] == t["C o0"] + 1
        # next tick: var slots roll back, varip slots persist; persistence ignores the mutation path
        assert (t["A o0"], t["A a0"]) == (0, 0)
        assert (t["B o0"], t["B a0"]) == (k, k)
        assert (t["C o0"], t["C a0"]) == (0, 1 if k else 0)          # m05: C = S / S+1
        assert (t["D o0"], t["D a0"]) == (k, 0)                       # m05: D origin grows, var alias = S
        assert t["D o2 last"] == t["code"]
    first = live.new_bar()                                            # the old bar's last execution is committed
    assert (first["A o0"], first["A a0"]) == (1, 1) and (first["B o0"], first["B a0"]) == (4, 4)
    assert (first["C o0"], first["C a0"]) == (1, 1) and (first["D o0"], first["D a0"]) == (4, 4)
    later = live.tick()
    assert (later["C o0"], later["C a0"]) == (1, 2) and (later["D o0"], later["D a0"]) == (5, 4)


# ---- analyzer / builtins / guards ----------------------------------------------------------------------------------

def test_types_generics_legacy_suffix_and_element_checks():
    p = values("""
array<float> g = array.new<float>()
float[] legacy = array.new_float(2, 1.5)
int[] ints = array.from(1, 2, 3)
array.push(g, 1)
plot(array.size(g), "g")
plot(array.get(legacy, 1), "legacy")
plot(array.first(ints) + array.last(ints), "ints")
""", n=3)
    assert set(p["g"]) == {1} and set(p["legacy"]) == {1.5} and set(p["ints"]) == {4}
    assert any("the array holds `float`" in m for m in errors('a = array.new_float()\narray.push(a, "x")\nplot(0)'))
    nested = compile_script(script("array<array<float>> n = na\nplot(0)"))
    assert not nested.ok and any("Arrays of arrays" in d.message for d in nested.diagnostics)


@pytest.mark.parametrize("body,message", [
    ("a = array.new_float()\nplot(array.get(a, 0))", "index 0 is out of bounds; the array size is 0"),
    ("a = array.new_float()\nplot(array.pop(a))", "the array is empty"),
    ("a = array.from(1.0)\nplot(array.get(a, -1))", "negative array indices are not implemented yet"),
    ("array<float> a = na\nplot(array.size(a))", "the array is na"),
])
def test_runtime_errors_are_explicit(body, message):
    result = compile_script(script(body))
    out = run_script(PineExecution(result.program, {}), context(bars(3)), ("t",), "t")
    assert message in out.error["message"] and out.error["line"] == 4       # the calling line (2nd body line)


def test_arrays_stay_out_of_request_security_and_p1_scripts_do_not_snapshot():
    result = compile_script(script('a = array.from(1.0)\nplot(request.security(syminfo.tickerid, "60", array.size(a)))'))
    assert not result.ok and any("arrays in a requested expression are not implemented yet" in d.message
                                 for d in result.diagnostics)
    assert compile_script(script("plot(close)")).program.uses_arrays is False


def test_frozen_oracle_scripts_are_byte_identical():
    evidence = (PARITY / "P22_ARRAY_EVIDENCE.md").read_text()
    for name in ("manual/m04_live_array_rollback.pine", "manual/m05_live_realias_each_tick.pine",
                 "quick/q5_array_reference_historical.pine", "quick/q5b_array_history.pine",
                 "quick/q5c_array_history_mutation.pine", "quick/q5d_array_equality.pine",
                 "quick/q5e_array_param_reassign.pine"):
        digest = hashlib.sha256((PARITY / name).read_bytes()).hexdigest()
        assert f"| `{name}` | `{digest}` |" in evidence, name
