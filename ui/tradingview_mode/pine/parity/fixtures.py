"""Parity fixtures: Pine scripts that run UNCHANGED in TradingView and in this engine.

Two tracks:

* ``synthetic`` - the data is a pure function of ``bar_index`` defined in the
  script itself (``PRELUDE``); the chart's own prices are never read, so any
  TradingView symbol/timeframe produces the same values. Every price is a
  multiple of 0.25 (exact in binary floating point).
* ``chart`` - built-ins that read the chart's prices (``ta.atr``, ``ta.vwma``,
  default-source overloads). The exported TradingView CSV carries the bars, and
  this engine re-runs the script on exactly those bars.

Every fixture plots ``bi`` (bar_index) first so rows are aligned by bar, and
exposes booleans as ``cond ? 1 : 0`` plots (Data Window / CSV export friendly).
``python -m ui.tradingview_mode.pine.parity`` writes the ``.pine`` files.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PERIOD = 240                           # the synthetic series repeats every 240 bars

PRELUDE = """\
// ---- fixture data: a pure function of bar_index; the chart's own prices are NOT used ----
// Every price is a multiple of 0.25, so TradingView and the local engine start from identical values.
fxClose(int i) =>
    int kk = i % 240
    int noise = (kk * 37 + 11) % 17 - 8
    int tri = kk % 80 < 40 ? kk % 80 : 80 - kk % 80
    float amp = kk >= 150 and kk < 170 ? 8.0 : 1.0
    kk >= 210 and kk < 222 ? 110.0 : 100.0 + tri * 0.5 + noise * 0.25 * amp
fxWick(int kk, int mult, int add, int m) =>
    kk >= 211 and kk < 222 ? 0.0 : ((kk * mult + add) % m) * 0.25
int k = bar_index % 240
float c = fxClose(bar_index)
float o = bar_index == 0 ? c - 0.5 : fxClose(bar_index - 1)
bool topTie = k == 184 or k == 186 or k == 190 or k == 191 or k == 196 or k == 199
bool bottomTie = k == 203 or k == 205 or k == 226 or k == 227
float h = topTie ? 120.0 : k % 37 == 0 ? math.max(o, c) : math.max(o, c) + fxWick(k, 53, 5, 13)
float l = bottomTie ? 95.0 : k % 37 == 0 ? math.min(o, c) : math.min(o, c) - fxWick(k, 29, 3, 11)
float v = 100.0 + ((k * 29) % 41) * 5
// ---- end of fixture data ----
"""

#: Equal-value pattern for pivot / extreme tie tests (period 24): ties at distance 1, 2 and 3 on both sides.
TIE_PATTERN = [3, 5, 5, 2, 6, 6, 6, 1, 4, 7, 2, 7, 3, 9, 1, 1, 9, 2, 4, 8, 3, 4, 8, 1]
#: The periodic series used by the third-party TradingView capture (see external/pinets_pr322_ties.json).
PINETS_PATTERN = [1, 2, 7, 4, 7, 3, 2, 3, 3, 5, 9, 6, 4, 3, 9, 8, 2, 5, 2, 6, 7, 8, 6, 1, 5, 7, 8, 8]


def _pattern_switch(name: str, pattern: list[int], period: int) -> str:
    cases = "\n".join(f"    {i} => {float(v)}" for i, v in enumerate(pattern))
    return f"float {name} = switch bar_index % {period}\n{cases}\n    => na\n"


@dataclass(frozen=True)
class Fixture:
    name: str
    title: str
    track: str                          # synthetic | chart
    covers: tuple[str, ...]             # requirement letters A..Z and features
    body: str
    version: int = 6
    #: our-render timing checks: rendered output title -> reference condition column (1 = drawn on that bar)
    timing: dict = field(default_factory=dict)
    notes: str = ""

    @property
    def source(self) -> str:
        header = (f"//@version={self.version}\n"
                  f"// Pine parity fixture `{self.name}` ({self.track} track). Paste into TradingView's Pine Editor,\n"
                  f"// add to chart, then export the chart data (see parity/README.md).\n"
                  f'indicator("parity {self.name}", overlay=false, precision=10)\n')
        prelude = PRELUDE if self.track == "synthetic" else ""
        return header + prelude + 'plot(bar_index, "bi")\n' + self.body.strip("\n") + "\n"


FIXTURES: list[Fixture] = [
    Fixture("s00_data", "fixture OHLCV", "synthetic", ("data",), """
plot(o, "o")
plot(h, "h")
plot(l, "l")
plot(c, "c")
plot(v, "v")
""", notes="Proves TradingView sees exactly the fixture data stored in data/synthetic_ohlcv.csv."),

    Fixture("s01_averages", "moving averages + warm-up", "synthetic", ("A", "B", "E", "F", "warm-up", "na"), """
plot(ta.sma(c, 5), "sma5")
plot(ta.sma(c, 20), "sma20")
plot(ta.ema(c, 1), "ema1")
plot(ta.ema(c, 9), "ema9")
plot(ta.ema(c, 20), "ema20")
plot(ta.rma(c, 14), "rma14")
plot(ta.wma(c, 10), "wma10")
float gappy = k % 23 >= 20 ? na : c
plot(ta.sma(gappy, 5), "sma5_gappy")
plot(ta.ema(gappy, 9), "ema9_gappy")
plot(ta.rma(gappy, 14), "rma14_gappy")
plot(ta.wma(gappy, 10), "wma10_gappy")
"""),

    Fixture("s02_oscillators", "oscillators", "synthetic", ("C", "D-formula", "flat-range", "volatility"), """
plot(ta.rsi(c, 14), "rsi14")
plot(ta.rsi(c, 2), "rsi2")
float trManual = na(c[1]) ? h - l : math.max(h - l, math.abs(h - c[1]), math.abs(l - c[1]))
plot(ta.rma(trManual, 14), "atr14_formula")
plot(ta.change(c), "change1")
plot(ta.change(c, 3), "change3")
plot(ta.mom(c, 10), "mom10")
plot(ta.stdev(c, 20), "stdev20")
plot(ta.stoch(c, h, l, 14), "stoch14")
plot(ta.cci(c, 20), "cci20")
[macdLine, signalLine, histLine] = ta.macd(c, 12, 26, 9)
plot(macdLine, "macd")
plot(signalLine, "macd_signal")
plot(histLine, "macd_hist")
[bbMid, bbUp, bbLo] = ta.bb(c, 20, 2)
plot(bbMid, "bb_mid")
plot(bbUp, "bb_up")
plot(bbLo, "bb_lo")
""", notes="Bars k=211..221 are zero-range (o=h=l=c=110): RSI with no movement, zero stdev, zero TR."),

    Fixture("s03_history", "history references", "synthetic", ("H",), """
plot(c[1], "c_1")
plot(c[2], "c_2")
float acc = na
acc := nz(acc[1]) + (c - o)
plot(acc, "acc")
plot(acc[1], "acc_1")
float diff = c - o
plot(diff[3], "diff_3")
plot((h - l)[1], "range_1")
plot(ta.sma(c, 3)[2], "sma3_2")
delta(float x) => x - x[1]
plot(delta(c), "udf_hist")
plot(bar_index[5], "bi_5")
"""),

    Fixture("s04_cross", "crossovers", "synthetic", ("I", "crossover exactly on one bar"), """
float fast = ta.ema(c, 5)
float slow = ta.sma(c, 20)
plot(ta.crossover(fast, slow) ? 1 : 0, "xover")
plot(ta.crossunder(fast, slow) ? 1 : 0, "xunder")
plot(ta.cross(fast, slow) ? 1 : 0, "xany")
plot(ta.crossover(k - 100, 0) ? 1 : 0, "xover_touch")
plot(ta.crossunder(100 - k, 0) ? 1 : 0, "xunder_touch")
plot(ta.crossover(c, 110.0) ? 1 : 0, "xover_flat")
plot(ta.rising(c, 3) ? 1 : 0, "rising3")
plot(ta.falling(c, 3) ? 1 : 0, "falling3")
plot(ta.barssince(ta.crossover(fast, slow)), "since_xover")
plot(ta.valuewhen(ta.crossover(fast, slow), c, 0), "valuewhen0")
plot(ta.valuewhen(ta.crossover(fast, slow), c, 1), "valuewhen1")
""", notes="`k - 100` touches 0 on k=100 and is above it on k=101: crossover must fire on k=101 only."),

    Fixture("s05_extremes", "highest / lowest with ties", "synthetic", ("J", "equal highs/lows"),
            _pattern_switch("tp", TIE_PATTERN, len(TIE_PATTERN)) + """
plot(tp, "tp")
plot(ta.highest(tp, 3), "hi3")
plot(ta.lowest(tp, 3), "lo3")
plot(ta.highest(tp, 5), "hi5")
plot(ta.lowest(tp, 5), "lo5")
plot(ta.highestbars(tp, 3), "hib3")
plot(ta.lowestbars(tp, 3), "lob3")
plot(ta.highestbars(tp, 5), "hib5")
plot(ta.lowestbars(tp, 5), "lob5")
plot(ta.highest(h, 10), "hi10_h")
plot(ta.lowest(l, 10), "lo10_l")
plot(ta.highestbars(h, 10), "hib10_h")
plot(ta.lowestbars(l, 10), "lob10_l")
"""),

    Fixture("s06_pivots", "pivots with ties", "synthetic", ("K", "equal highs/lows"),
            _pattern_switch("tp", TIE_PATTERN, len(TIE_PATTERN)) + """
plot(tp, "tp")
plot(ta.pivothigh(tp, 1, 1), "ph11")
plot(ta.pivotlow(tp, 1, 1), "pl11")
plot(ta.pivothigh(tp, 2, 2), "ph22")
plot(ta.pivotlow(tp, 2, 2), "pl22")
plot(ta.pivothigh(tp, 3, 3), "ph33")
plot(ta.pivotlow(tp, 3, 3), "pl33")
plot(ta.pivothigh(tp, 2, 1), "ph21")
plot(ta.pivotlow(tp, 1, 3), "pl13")
plot(ta.pivothigh(h, 2, 2), "ph22_h")
plot(ta.pivotlow(l, 2, 2), "pl22_l")
plot(ta.pivothigh(h, 3, 3), "ph33_h")
plot(ta.pivotlow(l, 3, 3), "pl33_l")
"""),

    Fixture("s07_var_varip", "var / varip (historical)", "synthetic", ("L", "M"), """
var int count = 0
count += 1
plot(count, "var_count")
varip int ipCount = 0
ipCount += 1
plot(ipCount, "varip_count")
var float lastCross = na
if ta.crossover(ta.ema(c, 5), ta.sma(c, 20))
    lastCross := c
plot(lastCross, "var_last_cross")
var int sinceReset = 0
sinceReset := k % 50 == 0 ? 0 : sinceReset + 1
plot(sinceReset, "var_resets")
counter() =>
    var int n = 0
    n += 1
    n
plot(counter(), "udf_var_a")
plot(k % 2 == 0 ? counter() : -1, "udf_var_b")
float plain = 0.0
plain += 1
plot(plain, "no_var")
""", notes="On historical bars varip behaves like var; realtime varip needs the manual live check (README)."),

    Fixture("s08_loops_v6", "loops (v6 semantics)", "synthetic", ("N", "O", "P", "switch", "v6"), """
float sum10 = 0.0
for i = 0 to 9
    sum10 += c[i]
plot(sum10, "for_sum10")
int evens = 0
for i = 10 to 0 by 2
    evens += i
plot(evens, "for_desc_by2")
int firstUp = -1
for i = 0 to 20
    if nz(c[i]) - nz(o[i]) <= 0
        continue
    firstUp := i
    break
plot(firstUp, "for_break")
int steps = 0
float x = c
while x > 100
    x -= 3.5
    steps += 1
plot(steps, "while_steps")
int limit = 3
int iters = 0
for i = 0 to limit
    iters += 1
    if i == 1
        limit := 6
plot(iters, "for_dynamic_end")
lastVal = for i = 0 to 4
    i * 2
plot(lastVal, "for_value")
d = 7 / 2
plot(d, "div_const")
plot(bar_index / 2, "div_series")
bool lazy = bar_index % 2 == 0 and ta.cum(1) % 4 == 0
plot(lazy ? 1 : 0, "and_stateful")
""", notes="v6: the `for` end is re-read every iteration (for_dynamic_end = 7), 7 / 2 = 3.5, `and` short-circuits."),

    Fixture("s09_loops_v5", "loops (v5 semantics)", "synthetic", ("N", "O", "P", "v5"), "", version=5,
            notes="Same body as s08 under //@version=5: `for` end fixed before the loop (for_dynamic_end = 4), "
                  "7 / 2 = 3 (const int division), `and` evaluates both sides."),

    Fixture("s10_control", "switch / ternary / functions / tuples", "synthetic", ("Q", "R", "S", "T"), """
int dirSwitch = switch
    c > o => 1
    c < o => -1
    => 0
plot(dirSwitch, "switch_nosubject")
float bucket = switch k % 4
    0 => 10.0
    1 => 20.0
    2 => 30.0
    => na
plot(bucket, "switch_subject")
plot(c > o ? 1 : c < o ? -1 : 0, "ternary_chain")
plot(c > 110 ? c : na, "ternary_na")
spread(float a, float b, float scale = 1.0) =>
    float d = a - b
    d * scale
plot(spread(h, l), "udf_default")
plot(spread(h, l, 0.5), "udf_arg")
bands(float src, int len) =>
    float mid = ta.sma(src, len)
    float dev = ta.stdev(src, len)
    [mid, mid + 2 * dev, mid - 2 * dev]
[m1, u1, l1] = bands(c, 10)
plot(m1, "tuple_mid")
plot(u1, "tuple_up")
plot(l1, "tuple_lo")
[m2, u2, l2] = bands(h, 5)
plot(u2, "tuple2_up")
int sgn = if c > o
    1
else
    -1
plot(sgn, "if_expr")
float noElse = if k % 3 == 0
    c
plot(noElse, "if_noelse_na")
"""),

    Fixture("s11_na", "na / nz", "synthetic", ("U",), """
float a = k % 5 == 0 ? na : c
plot(a, "gappy")
plot(nz(a), "nz_default")
plot(nz(a, -1), "nz_repl")
plot(na(a) ? 1 : 0, "is_na")
plot(fixnan(a), "fixnan")
plot(a + 1, "na_plus")
plot(a > 100 ? 1 : 0, "na_compare")
plot(math.max(a, 105), "na_max")
plot(a[1], "na_hist")
plot(ta.change(a), "na_change")
plot(ta.cum(nz(a)), "cum_nz")
plot(ta.highest(a, 3), "na_highest")
"""),

    Fixture("s12_plots", "plot gaps, shapes, chars, colors", "synthetic", ("V", "W", "X", "Y", "Z"), """
float g = k % 10 < 3 ? na : c
plot(g, "line_gappy")
plot(g, "line_explicit", style=plot.style_line)
plot(g, "linebr", style=plot.style_linebr)
bool up = ta.crossover(ta.ema(c, 5), ta.sma(c, 20))
bool dn = ta.crossunder(ta.ema(c, 5), ta.sma(c, 20))
plot(up ? 1 : 0, "up_cond")
plot(dn ? 1 : 0, "dn_cond")
plotshape(up, "shape_up", shape.triangleup, location.belowbar, color.green)
plotchar(dn, "char_dn", "v", location.abovebar, color.red)
bgcolor(up ? color.new(color.green, 80) : na, title="bg_up")
barcolor(dn ? color.orange : na, title="bar_dn")
""", timing={"shape_up": "up_cond", "char_dn": "dn_cond", "bg_up": "up_cond", "bar_dn": "dn_cond"},
            notes="Values are compared numerically; the line-vs-linebr gap drawing is a visual check (README)."),

    Fixture("c01_chart", "built-ins on chart prices", "chart", ("A", "B", "C", "D", "E", "F", "G", "I", "J", "K"), """
plot(volume, "vol")
plot(ta.tr, "tr")
plot(ta.tr(true), "tr_true")
plot(ta.atr(14), "atr14")
plot(ta.sma(close, 20), "sma20")
plot(ta.ema(close, 20), "ema20")
plot(ta.rma(close, 14), "rma14")
plot(ta.wma(close, 10), "wma10")
plot(ta.vwma(close, 20), "vwma20")
plot(ta.rsi(close, 14), "rsi14")
plot(ta.highest(10), "highest10")
plot(ta.lowest(10), "lowest10")
plot(ta.highestbars(10), "highestbars10")
plot(ta.pivothigh(3, 3), "ph33")
plot(ta.pivotlow(3, 3), "pl33")
plot(ta.crossover(close, ta.ema(close, 20)) ? 1 : 0, "xover_ema20")
plot(hl2, "hl2_")
plot(hlc3, "hlc3_")
[st, stDir] = ta.supertrend(3, 10)
plot(st, "supertrend")
plot(stDir, "supertrend_dir")
""", notes="Needs the export to start at the chart's first bar (bi = 0) so warm-up is identical."),

    Fixture("x01_pinets_ties", "third-party TradingView tie capture", "synthetic", ("K", "J"),
            _pattern_switch("src", PINETS_PATTERN, len(PINETS_PATTERN)) + """
plot(ta.pivothigh(src, 2, 2), "ph")
plot(ta.pivotlow(src, 2, 2), "pl")
plot(ta.pivothigh(src, 1, 1), "ph11")
plot(ta.pivotlow(src, 1, 1), "pl11")
plot(ta.highestbars(src, 5), "hb5")
plot(ta.lowestbars(src, 5), "lb5")
plot(ta.highestbars(src, 3), "hb3")
plot(ta.lowestbars(src, 3), "lb3")
""", notes="Same periodic series as the third-party capture in external/pinets_pr322_ties.json."),
]

# s09 is s08's body under v5
_S08 = next(f for f in FIXTURES if f.name == "s08_loops_v6")
FIXTURES = [Fixture(f.name, f.title, f.track, f.covers, _S08.body, f.version, f.timing, f.notes)
            if f.name == "s09_loops_v5" else f for f in FIXTURES]
BY_NAME = {f.name: f for f in FIXTURES}


def synthetic_row(i: int) -> dict:
    """Python mirror of ``PRELUDE`` (tests assert it equals the engine's own run of the prelude)."""
    def close_at(j: int) -> float:
        kk = j % PERIOD
        noise = (kk * 37 + 11) % 17 - 8
        tri = kk % 80 if kk % 80 < 40 else 80 - kk % 80
        amp = 8.0 if 150 <= kk < 170 else 1.0
        return 110.0 if 210 <= kk < 222 else 100.0 + tri * 0.5 + noise * 0.25 * amp

    def wick(kk: int, mult: int, add: int, m: int) -> float:
        return 0.0 if 211 <= kk < 222 else ((kk * mult + add) % m) * 0.25

    k = i % PERIOD
    c = close_at(i)
    o = c - 0.5 if i == 0 else close_at(i - 1)
    top = k in (184, 186, 190, 191, 196, 199)
    bottom = k in (203, 205, 226, 227)
    h = 120.0 if top else max(o, c) if k % 37 == 0 else max(o, c) + wick(k, 53, 5, 13)
    lo = 95.0 if bottom else min(o, c) if k % 37 == 0 else min(o, c) - wick(k, 29, 3, 11)
    return {"bar_index": i, "open": o, "high": h, "low": lo, "close": c, "volume": 100.0 + ((k * 29) % 41) * 5}


#: Scripts for checks that TradingView cannot export (live ticks, line drawing); results are recorded by hand
#: in tradingview/observations.json (see README).
MANUAL_CHECKS = {
    "m01_live_varip": """\
//@version=6
// Pine parity manual check: var vs varip on realtime ticks. Add to a LIVE 1-minute chart and watch the Data Window.
indicator("parity m01 live varip", overlay=false)
varip int ticksThisBar = 0
if barstate.isnew
    ticksThisBar := 0
ticksThisBar += 1
var int varPerBar = 0
varPerBar += 1
varip int varipTotal = 0
varipTotal += 1
plot(bar_index, "bi")
plot(ticksThisBar, "varip ticks this bar")
plot(varPerBar, "var count")
plot(varipTotal, "varip count")
""",
}
