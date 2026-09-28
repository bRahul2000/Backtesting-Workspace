"""Diagnostics: real errors worded like Pine, and capability gaps that name the
missing language feature and line (never "indicator unsupported")."""
import pytest

from ui.tradingview_mode.pine import compile_script
from ui.tradingview_mode.pine.compat import FEATURES, matrix

from .helpers import diagnostics, run, script


def only(source):
    found = [d for d in diagnostics(source) if d[0] != "warning"]
    assert len(found) == 1, found
    return found[0]


@pytest.mark.parametrize("body, line, message", [
    ("d = request.dividends(syminfo.tickerid)", 3,
     "`request.dividends()` is not implemented yet (data requests)."),
    ("a = array.avg(array.from(1.0, 2.0))", 3, "`array.avg()` is not implemented yet (arrays)."),
    ("p = polyline.new(na)", 3, "`polyline.new()` is not implemented yet (tables, polylines and chart points)."),
    ("type Pivot\n    float price\n    int bar", 3, "User-defined types (`type Pivot`) are not implemented yet."),
    ("method twice(float x) => x * 2", 3, "Methods (`method twice`) are not implemented yet."),
    ("import TradingView/ta/7 as tv", 3, "Libraries (`import TradingView/ta/7`) are not implemented yet."),
    ("m = matrix.new<float>(2, 2)", 3, None),
    ("x = ta.percentile_nearest_rank(close, 10, 50)", 3, None),
    ("v = syminfo.shares_outstanding_total", 3, "`syminfo.shares_outstanding_total` is not implemented yet."),
    ("plotarrow(close - open)", 3, "`plotarrow()` is not implemented yet."),
])
def test_capability_gaps_name_the_feature_and_line(body, line, message):
    source = script(body + "\nplot(close)")
    result = compile_script(source)
    assert not result.ok
    gaps = [d for d in result.diagnostics if d.kind == "gap"]
    assert gaps and gaps[0].line == line
    if message:
        assert gaps[0].message == message
    assert gaps[0].feature in FEATURES
    assert "unsupported" not in gaps[0].message.lower()


def test_for_in_over_a_scalar_and_gaps_for_strategy_and_old_versions():
    # P2.2-A2: `for ... in` over arrays is implemented; iterating a scalar series is a compile error
    assert only(script("for x in close\n    y = x\nplot(close)"))[:2] == ("error", 3)
    assert only(script("for x in close\n    y = x\nplot(close)"))[2] == ("`for ... in` needs an array; `float` cannot be "
                                                                    "iterated.")
    kind, line, message = only("//@version=5\nstrategy('S')\nplot(close)\n")
    assert (kind, line) == ("gap", 2) and "`strategy()` scripts are not implemented yet" in message
    kind, line, message = only("//@version=4\nindicator('Old')\nplot(close)\n")
    assert kind == "gap" and "Pine v4 scripts are not translated yet" in message


@pytest.mark.parametrize("body, text", [
    ("plot(foo)", "Undeclared identifier `foo`."),
    ("x := 1", "Undeclared identifier `x`: declare it with `=` before reassigning it with `:=`."),
    ("x = 1\nx = 2", "`x` is already declared in this scope; use `:=` to reassign it."),
    ("if close > open\n    plot(close)", "Cannot use `plot` in local scope."),
    ("f(x) => f(x - 1)", "Recursive calls are not allowed (`f` calls itself)."),
    ("g = 0\nf() =>\n    g := 1\n    g", "Cannot modify global variable `g` in a function."),
    ("plot(ta.sma(close))", "Cannot call `ta.sma`: missing required argument `length`."),
    ("plot(ta.sma(close, 5, foo = 1))", "Cannot call `ta.sma`: unknown argument `foo` (valid: source, length)."),
    ("n = bar_index\nplot(ta.ema(close, n))",
     "Cannot call `ta.ema` with argument `length`: a `series int` was used but a `simple int` is expected."),
    ("plot(ta.sma('abc', 5))",
     "Cannot call `ta.sma` with argument `source`: a `const string` was used but a `series float` is expected."),
    ("x = foo.bar", "Undeclared identifier `foo.bar`."),
    ("x = ta.nosuch(close)", "Could not find function or function reference `ta.nosuch`."),
    ("break", "`break` can only be used inside a loop."),
    ("x = 'a' + 1", "Cannot add `string` and `int` (convert with str.tostring())."),
])
def test_errors_are_pine_worded(body, text):
    kind, line, message = only(script(body + ("\nplot(close)" if "plot" not in body else "")))
    assert kind == "error" and message == text and line >= 3


def test_syntax_errors_carry_a_line():
    result = compile_script(script("x = (1 + \nplot(close)"))
    assert not result.ok and result.diagnostics[0].kind == "error" and result.diagnostics[0].line == 3
    assert result.diagnostics[0].message == "`(` is never closed."
    unmatched = compile_script(script("x = 1)\nplot(close)")).diagnostics[0]
    assert (unmatched.line, unmatched.message) == (3, "Unexpected `)` (no matching `(`).")


def test_missing_declaration_and_version_warning():
    kinds = diagnostics("plot(close)\n")
    assert ("error", 1, "The script must declare its type with `indicator()`, `strategy()` or `library()`.") in kinds
    assert any(k == "warning" and "No `//@version`" in m for k, _, m in kinds)


def test_compatibility_matrix_is_by_feature_and_makes_no_blanket_claim():
    m = matrix()
    assert set(m["features"]) >= {"parser", "runtime", "builtins", "outputs", "drawings", "request", "strategy", "types"}
    statuses = {f["id"]: f["status"] for group in m["features"].values() for f in group}
    # request.security() is implemented (P2.1); the rest of request.* stays a gap inside the partial feature
    assert statuses["request"] == "partial" and statuses["drawing-objects"] == "gap" and statuses["strategy"] == "gap"
    assert "request.dividends" in m["builtins"]["by_namespace"]["request"]["missing"]
    assert statuses["functions"] == "supported" and statuses["ta"] == "partial"
    ta = m["builtins"]["by_namespace"]["ta"]
    assert 0 < ta["implemented"] < ta["known"] and "ta.percentile_nearest_rank" in ta["missing"]


# ---- a corpus of community-style scripts (written for these tests; no indicator-specific code) -----------

CORPUS = {
    "supertrend_manual": """
//@version=5
indicator("Manual SuperTrend", overlay = true)
atrLen = input.int(10, "ATR length")
mult = input.float(3.0, "Factor", step = 0.1)
atr = ta.atr(atrLen)
up = hl2 - mult * atr
dn = hl2 + mult * atr
var float trendUp = na
var float trendDn = na
var int dir = 1
trendUp := close[1] > nz(trendUp[1], up) ? math.max(up, nz(trendUp[1], up)) : up
trendDn := close[1] < nz(trendDn[1], dn) ? math.min(dn, nz(trendDn[1], dn)) : dn
dir := close > nz(trendDn[1], dn) ? 1 : close < nz(trendUp[1], up) ? -1 : dir
line = dir == 1 ? trendUp : trendDn
plot(line, "Trend", color = dir == 1 ? color.teal : color.red, linewidth = 2, style = plot.style_linebr)
plotshape(dir == 1 and dir[1] == -1, "Buy", shape.labelup, location.belowbar, color.teal, text = "B")
""",
    "ma_selector": """
//@version=5
indicator("MA ribbon", overlay = true)
maType = input.string("EMA", "Type", options = ["SMA", "EMA", "WMA", "RMA", "HMA", "VWMA"])
ma(src, len, kind) =>
    switch kind
        "SMA" => ta.sma(src, len)
        "EMA" => ta.ema(src, len)
        "WMA" => ta.wma(src, len)
        "RMA" => ta.rma(src, len)
        "HMA" => ta.hma(src, len)
        => ta.vwma(src, len)
m1 = ma(close, 10, maType)
m2 = ma(close, 20, maType)
m3 = ma(close, 50, maType)
p1 = plot(m1, "Fast", color.green)
p3 = plot(m3, "Slow", color.red)
plot(m2, "Mid", color.orange)
fill(p1, p3, color = m1 > m3 ? color.new(color.green, 85) : color.new(color.red, 85))
""",
    "squeeze_style": """
//@version=5
indicator("Squeeze-style momentum")
length = input.int(20, "BB length")
mult = input.float(2.0, "BB mult")
kcMult = input.float(1.5, "KC mult")
[basis, upperBB, lowerBB] = ta.bb(close, length, mult)
[kcBasis, upperKC, lowerKC] = ta.kc(close, length, kcMult)
sqzOn = lowerBB > lowerKC and upperBB < upperKC
val = ta.linreg(close - math.avg(math.avg(ta.highest(high, length), ta.lowest(low, length)), ta.sma(close, length)), length, 0)
bcolor = val > 0 ? (val > nz(val[1]) ? color.lime : color.green) : (val < nz(val[1]) ? color.red : color.maroon)
plot(val, "Momentum", color = bcolor, style = plot.style_histogram, linewidth = 4)
plotshape(true, "Squeeze", shape.xcross, location.absolute, sqzOn ? color.black : color.gray)
hline(0, "Zero")
""",
    "rsi_bands_divergence_lite": """
//@version=5
indicator("RSI with pivots")
len = input.int(14, minval = 1)
r = ta.rsi(close, len)
ph = ta.pivothigh(r, 5, 5)
pl = ta.pivotlow(r, 5, 5)
var float lastPh = na
if not na(ph)
    lastPh := ph
upper = hline(70, "Overbought", color = color.red)
lower = hline(30, "Oversold", color = color.green)
fill(upper, lower, color = color.new(color.purple, 92))
plot(r, "RSI", color.purple)
plot(lastPh, "Last pivot high", color.gray, style = plot.style_circles)
plotchar(not na(pl), "PL", "•", location.bottom, color.green, offset = -5)
bgcolor(r > 70 ? color.new(color.red, 90) : r < 30 ? color.new(color.green, 90) : na)
""",
    "zscore_loop_function": """
//@version=5
indicator("Z-score (loop)")
n = input.int(30, "Window")
mean(src, len) =>
    total = 0.0
    for i = 0 to len - 1
        total += src[i]
    total / len
sd(src, len) =>
    mu = mean(src, len)
    acc = 0.0
    for i = 0 to len - 1
        acc += math.pow(src[i] - mu, 2)
    math.sqrt(acc / len)
z = (close - mean(close, n)) / sd(close, n)
plot(z, "Z", z > 2 ? color.red : z < -2 ? color.green : color.gray, style = plot.style_columns)
hline(2)
hline(-2)
""",
    "heikin_ashi_colors": """
//@version=5
indicator("HA trend bars", overlay = true)
var float haOpen = na
haClose = ohlc4
haOpen := na(haOpen[1]) ? (open + close) / 2 : (haOpen[1] + haClose[1]) / 2
bull = haClose >= haOpen
barcolor(bull ? color.teal : color.maroon)
plot(haOpen, "HA open", color.new(color.gray, 50))
""",
    "session_like_time": """
//@version=5
indicator("Daily open + stats", overlay = true)
newDay = timeframe.change("D")
var float dayOpen = na
if newDay
    dayOpen := open
plot(dayOpen, "Day open", color.orange, style = plot.style_stepline)
isMonday = dayofweek == dayofweek.monday
bgcolor(isMonday ? color.new(color.blue, 94) : na)
plotchar(hour == 0 and minute == 0, "Midnight", "|", location.top)
""",
    "donchian_dmi": """
//@version=5
indicator("Donchian + DMI", overlay = false)
len = input.int(20)
upper = ta.highest(len)
lower = ta.lowest(len)
[plusDI, minusDI, adx] = ta.dmi(14, 14)
plot(adx, "ADX", color.orange)
plot(plusDI, "+DI", color.green)
plot(minusDI, "-DI", color.red)
plot((close - lower) / (upper - lower) * 100, "Position %", color.blue)
""",
}


@pytest.mark.parametrize("name", sorted(CORPUS))
def test_community_style_scripts_compile_and_run(name):
    out, frame = run(CORPUS[name])
    assert out.outputs and out.bars == len(frame)
    assert all(o["kind"] in ("plot", "shape", "char", "hline", "fill", "bgcolor", "barcolor") for o in out.outputs)
    numeric = [p["value"] for o in out.outputs if o["kind"] == "plot" for p in o["data"] if p["value"] is not None]
    assert numeric, "every script plots real values"


def test_compatibility_document_is_generated_and_current():
    from pathlib import Path

    from ui.tradingview_mode.pine.compat import markdown
    document = Path(__file__).resolve().parents[3] / "ui/tradingview_mode/pine/COMPATIBILITY.md"
    assert document.read_text() == markdown(), "run `python -m ui.tradingview_mode.pine.compat` to regenerate"
    assert "No claim of full Pine compatibility is made" in document.read_text()
