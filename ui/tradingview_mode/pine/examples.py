"""Example Pine scripts for the editor's Examples menu.

Plain Pine source, compiled by the engine like any pasted script; the engine
has no knowledge of them. The last one deliberately uses features that are not
implemented yet, to show capability-gap reporting.
"""

EXAMPLES = {
    "Moving-average crossover": """//@version=5
indicator("MA crossover", overlay = true)
fastLen = input.int(9, "Fast length", minval = 1)
slowLen = input.int(21, "Slow length", minval = 1)
fast = ta.ema(close, fastLen)
slow = ta.ema(close, slowLen)
pFast = plot(fast, "Fast", color = color.new(color.teal, 0), linewidth = 2)
pSlow = plot(slow, "Slow", color = color.new(color.orange, 0), linewidth = 2)
fill(pFast, pSlow, color = fast > slow ? color.new(color.teal, 85) : color.new(color.orange, 85))
plotshape(ta.crossover(fast, slow), "Cross up", shape.triangleup, location.belowbar, color.teal, size = size.small)
plotshape(ta.crossunder(fast, slow), "Cross down", shape.triangledown, location.abovebar, color.orange, size = size.small)
""",
    "RSI with bands": """//@version=5
indicator("RSI with bands")
length = input.int(14, "Length", minval = 1)
src = input.source(close, "Source")
r = ta.rsi(src, length)
top = hline(70, "Overbought", color = color.red, linestyle = hline.style_dashed)
bottom = hline(30, "Oversold", color = color.green, linestyle = hline.style_dashed)
fill(top, bottom, color = color.new(color.purple, 92))
plot(r, "RSI", color = color.purple, linewidth = 2)
bgcolor(r > 70 ? color.new(color.red, 90) : r < 30 ? color.new(color.green, 90) : na)
""",
    "SuperTrend (user function)": """//@version=5
indicator("SuperTrend", overlay = true)
factor = input.float(3.0, "Factor", step = 0.1)
atrLen = input.int(10, "ATR length")
supertrend(f, len) =>
    atr = ta.atr(len)
    upper = hl2 + f * atr
    lower = hl2 - f * atr
    var float up = na
    var float dn = na
    var int dir = 1
    up := na(up) ? lower : close[1] > up ? math.max(lower, up) : lower
    dn := na(dn) ? upper : close[1] < dn ? math.min(upper, dn) : upper
    dir := close > dn[1] ? 1 : close < up[1] ? -1 : dir
    [dir == 1 ? up : dn, dir]
[line, dir] = supertrend(factor, atrLen)
plot(line, "SuperTrend", color = dir == 1 ? color.teal : color.red, linewidth = 2, style = plot.style_linebr)
plotshape(dir == 1 and dir[1] == -1, "Buy", shape.labelup, location.belowbar, color.teal, text = "B", textcolor = color.white)
plotshape(dir == -1 and dir[1] == 1, "Sell", shape.labeldown, location.abovebar, color.red, text = "S", textcolor = color.white)
barcolor(dir == 1 ? color.teal : color.red)
""",
    "MACD histogram": """//@version=5
indicator("MACD")
[macdLine, signalLine, hist] = ta.macd(close, 12, 26, 9)
plot(hist, "Histogram", color = hist >= 0 ? (hist > hist[1] ? color.teal : color.new(color.teal, 50)) : (hist < hist[1] ? color.red : color.new(color.red, 50)), style = plot.style_columns)
plot(macdLine, "MACD", color.blue)
plot(signalLine, "Signal", color.orange)
hline(0, "Zero", color = color.gray)
""",
    "Uses unimplemented features": """//@version=5
indicator("Needs dividend data and polylines", overlay = true)
dividends = request.dividends(syminfo.tickerid)
plot(dividends, "Dividends")
if ta.crossover(close, dividends)
    polyline.new(na)
""",
}
