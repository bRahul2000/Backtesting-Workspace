"""Pine language semantics: the runtime executes the language, not indicators."""
import numpy as np
import pytest

from ui.tradingview_mode.pine import PineExecution, compile_script, run_script
from ui.tradingview_mode.pine.lexer import tokenize
from ui.tradingview_mode.pine.parser import parse

from .helpers import bars, context, plots, run, script

FRAME = bars(200, seed=2)


def values(body: str, frame=FRAME, inputs=None):
    out, _ = run(script(body), frame, inputs)
    return plots(out)


def test_lexer_layout_rules():
    lexed = tokenize("//@version=6\nx = 1 +\n     2\nif x\n    y = 3\n")
    kinds = [t.kind for t in lexed.tokens]
    assert lexed.annotations == {"version": "6"}
    assert kinds.count("NEWLINE") == 3 and kinds.count("INDENT") == 1 and kinds.count("DEDENT") == 1  # wrapped line joined
    assert [t.value for t in tokenize("c = #FF000080\n").tokens if t.kind == "COLOR"] == ["FF000080"]
    assert parse("//@version=5\nindicator('x')\nplot(f(\n  close,\n  2))\n").body[1].expr.func.name == "plot"


def test_var_persists_and_plain_variables_reset_each_bar():
    p = values("""
var int counter = 0
counter += 1
plain = 0
plain += 1
plot(counter, "counter")
plot(plain, "plain")
plot(bar_index, "bi")
""")
    assert p["counter"] == [float(i + 1) for i in range(len(FRAME))]
    assert set(p["plain"]) == {1.0} and p["bi"][-1] == len(FRAME) - 1


def test_history_references_on_variables_builtins_and_expressions():
    p = values("""
x = close * 2
plot(x[1], "x1")
plot(close[3], "c3")
plot((close - open)[2], "expr2")
plot(ta.sma(close, 3)[1], "sma1")
""")
    c, o = FRAME["close"].to_numpy(), FRAME["open"].to_numpy()
    assert p["x1"][0] is None and p["x1"][5] == pytest.approx(c[4] * 2)
    assert p["c3"][:3] == [None, None, None] and p["c3"][10] == pytest.approx(c[7])
    assert p["expr2"][10] == pytest.approx(c[8] - o[8])
    assert p["sma1"][10] == pytest.approx(c[7:10].mean())


def test_local_block_history_is_per_execution_like_pine():
    p = values("""
var int n = 0
v = na
if bar_index % 2 == 0
    local = bar_index
    v := local[1]
plot(v, "v")
""")
    # local[1] inside the block is the value from the block's previous EXECUTION (two bars earlier).
    assert p["v"][4] == 2.0 and p["v"][6] == 4.0 and p["v"][0] is None and p["v"][3] is None


def test_user_functions_have_per_call_site_state_defaults_and_tuples():
    p = values("""
avg(src, len = 3) => ta.sma(src, len)
both(a, b) =>
    s = a + b
    [s, s * 2]
plot(avg(close), "a3")
plot(avg(open, 5), "a5")
[s, d] = both(1, 2)
plot(s, "s")
plot(d, "d")
""")
    c, o = FRAME["close"].to_numpy(), FRAME["open"].to_numpy()
    assert p["a3"][10] == pytest.approx(c[8:11].mean())        # two call sites, two independent ta.sma states
    assert p["a5"][10] == pytest.approx(o[6:11].mean())
    assert set(p["s"]) == {3.0} and set(p["d"]) == {6.0}


def test_control_flow_if_switch_for_while_break_continue_ternary():
    p = values("""
total = 0
for i = 1 to 10
    if i == 8
        break
    if i % 2 == 0
        continue
    total += i
down = 0
for j = 5 to 1
    down += j
w = 0
while w < 4
    w += 1
kind = switch
    close > open => 1
    close < open => -1
    => 0
named = switch kind
    1 => 10
    -1 => 20
    => 30
label_ = if kind == 1
    "up"
else if kind == -1
    "down"
else
    "flat"
plot(total, "total")
plot(down, "down")
plot(w, "w")
plot(named, "named")
plot(label_ == "up" ? 1 : 0, "t")
""")
    assert set(p["total"]) == {1 + 3 + 5 + 7} and set(p["down"]) == {15} and set(p["w"]) == {4}
    c, o = FRAME["close"].to_numpy(), FRAME["open"].to_numpy()
    expected = [10.0 if a > b else 20.0 if a < b else 30.0 for a, b in zip(c, o)]
    assert p["named"] == expected and p["t"] == [1.0 if a > b else 0.0 for a, b in zip(c, o)]


def test_na_arithmetic_int_division_strings_and_colors():
    p = values("""
a = na + 1
b = 7 / 2
c = 6 / 3
d = nz(close[500], -1)
e = na(close[500]) ? 1 : 0
s = "a" + str.tostring(12.5) + str.tostring(3)
f = s == "a12.53" ? 1 : 0
col = color.new(color.red, 50)
g = color.t(col)
plot(a, "a")
plot(b, "b")
plot(c, "c")
plot(d, "d")
plot(e, "e")
plot(f, "f")
plot(g, "g")
plot(math.round(2.5), "r")
plot(math.max(1, 5, 3), "m")
""")
    # v5: `const int / const int` truncates (TradingView v6 migration guide); v6 keeps the fraction
    assert set(p["a"]) == {None} and set(p["b"]) == {3.0} and set(p["c"]) == {2.0}
    assert set(p["d"]) == {-1.0} and set(p["e"]) == {1.0} and set(p["f"]) == {1.0} and set(p["g"]) == {50.0}
    assert set(p["r"]) == {3.0} and set(p["m"]) == {5.0}


def test_inputs_defaults_and_overrides():
    source = script("""
len = input.int(5, "Length", minval = 1)
src = input.source(close, "Source")
plot(ta.sma(src, len), "ma")
""")
    result = compile_script(source)
    assert [(i.kind, i.title, i.defval) for i in result.inputs] == [("int", "Length", 5), ("source", "Source", "close")]
    out, _ = run(source, FRAME)
    assert plots(out)["ma"][10] == pytest.approx(FRAME["close"].to_numpy()[6:11].mean())
    from ui.tradingview_mode.pine.engine import resolve_inputs
    values_, problems = resolve_inputs(result.program, {0: 3, 1: "high"})
    assert not problems
    out = run_script(PineExecution(result.program, values_), context(FRAME), ("x",), "t")
    assert plots(out)["ma"][10] == pytest.approx(FRAME["high"].to_numpy()[8:11].mean())
    _, problems = resolve_inputs(result.program, {0: 0, 1: "nope"})
    assert len(problems) == 2


def test_realtime_updates_equal_a_full_recompute_and_varip_survives():
    source = script("""
var float acc = 0.0
acc += close
varip int ticks = 0
ticks += 1
m = ta.ema(close, 10)
plot(acc, "acc")
plot(m, "ema")
plot(ticks, "ticks")
""")
    program = compile_script(source).program
    frame = bars(120, seed=9)
    live = PineExecution(program, {})
    run_script(live, context(frame.iloc[:100], forming_last=True), ("s",), "t")
    last = frame.iloc[:101].copy()
    for price in (100.0, 101.0, 99.5):                    # three ticks of the forming bar 100
        last.loc[100, ["close", "high", "low"]] = [price, max(price, last.loc[100, "open"]) + 1, min(price, last.loc[100, "open"]) - 1]
        out = run_script(live, context(last, forming_last=True), ("s",), "t")
        assert out.incremental and out.executed == 1      # exactly the forming bar was re-executed
    full = run_script(PineExecution(program, {}), context(last), ("s",), "t")
    p_live, p_full = plots(out), plots(full)
    assert p_live["acc"] == pytest.approx(p_full["acc"]) and p_live["ema"] == pytest.approx(p_full["ema"], nan_ok=True)
    assert p_live["ticks"][-1] == p_full["ticks"][-1] + 2  # varip kept the two extra intrabar updates
    appended = frame.iloc[:103]
    after = run_script(live, context(appended, forming_last=True), ("s",), "t")
    assert after.executed == 3                            # the re-run forming bar 100 plus new bars 101 and 102
    unchanged = run_script(live, context(appended, forming_last=True), ("s",), "t")
    assert unchanged.executed == 0                        # no new tick: nothing re-runs (varip must not count phantom ticks)
    assert after.incremental and plots(after)["acc"] == pytest.approx(plots(run_script(
        PineExecution(program, {}), context(appended), ("s",), "t"))["acc"])


def test_changed_history_rebuilds_instead_of_mixing():
    program = compile_script(script('plot(ta.cum(close), "cum")')).program
    execution = PineExecution(program, {})
    frame = bars(80, seed=4)
    run_script(execution, context(frame), ("s",), "t")
    changed = frame.copy()
    changed.loc[10, "close"] += 5
    out = run_script(execution, context(changed), ("s",), "t")
    assert not out.incremental and plots(out)["cum"][-1] == pytest.approx(changed["close"].sum())


def test_plot_outputs_protocol():
    out, frame = run(script("""
f = ta.sma(close, 5)
p1 = plot(f, "f", color = close > f ? color.green : na, style = plot.style_histogram, linewidth = 3, offset = 2)
p2 = plot(close, "c")
fill(p1, p2, color = color.new(color.blue, 80))
h1 = hline(30)
h2 = hline(70, "Top", color = color.red, linestyle = hline.style_dashed)
fill(h1, h2)
plotshape(close > open, "Up", shape.triangleup, location.belowbar, color.lime, text = "U")
plotchar(close < open, "Dn", "▼", location.abovebar, color.red)
plotshape(ta.crossover(close, f) ? low : na, "Abs", location = location.absolute)
bgcolor(close > open ? color.new(color.green, 90) : na)
barcolor(close < open ? color.purple : na)
"""), FRAME)
    kinds = [o["kind"] for o in out.outputs]
    assert kinds == ["plot", "plot", "fill", "hline", "hline", "fill", "shape", "char", "shape", "bgcolor", "barcolor"]
    f = out.outputs[0]
    assert f["style"] == "histogram" and f["linewidth"] == 3 and f["offset"] == 2
    times = [int(t.timestamp()) for t in FRAME["timestamp"]]
    assert f["data"][0]["time"] == times[2] and len(f["data"]) == len(FRAME) - 2   # offset shifts right
    assert out.outputs[2]["between"] == [f["id"], out.outputs[1]["id"]]
    assert out.outputs[4]["price"] == 70.0 and out.outputs[4]["linestyle"] == "dashed"
    up = out.outputs[6]
    assert all(p["text"] == "U" for p in up["data"]) and len(up["data"]) == int((FRAME["close"] > FRAME["open"]).sum())
    assert all("price" in p for p in out.outputs[8]["data"])
    assert all(p["color"].startswith("rgba(") for p in out.outputs[10]["data"])
