"""na inside a series for ta.sma / ta.ema / ta.rma / ta.wma — confirmed on REAL TradingView.

Evidence: manual parity fixture s01_averages (Page 2, Columns 2) run on TradingView 2026-09-27; the
source is valid through bar 19, na at bars 20-22 and valid again from bar 23. TradingView printed 8
decimals, so values are compared within half a unit of the 8th decimal.
"""
import math

import pytest

from ui.tradingview_mode.pine import PineExecution, compile_script, run_script
from ui.tradingview_mode.pine.parity.fixtures import PRELUDE
from ui.tradingview_mode.pine.parity.harness import synthetic_frame

from .helpers import bars, context, plots, run

TV_PRINT = 5e-9 + 1e-12          # half a unit of TradingView's 8th printed decimal

GAPPY = '''//@version=6
indicator("na gap")
''' + PRELUDE + '''float gappy = k % 23 >= 20 ? na : c
plot(ta.sma(gappy, 5), "sma")
plot(ta.ema(gappy, 9), "ema")
plot(ta.rma(gappy, 14), "rma")
plot(ta.wma(gappy, 10), "wma")
'''

#: TradingView's table, bars 17-26 (None = na)
TRADINGVIEW = {
    "sma": [107.6, 108.0, 108.4, 108.4, 108.4, 108.4, 109.55, 110.7, 111.0, 111.3],
    "ema": [106.62460594, 107.39968475, 107.4197478, None, None, None, 108.43579824, 109.49863859, 109.74891087,
            110.1991287],
    "rma": [104.45734618, 104.88896431, 105.07546686, None, None, None, 105.60579065, 106.18751989, 106.51341133,
            106.90531052],
    "wma": [107.12272727, 107.90909091, 108.0, None, None, None, 108.77272727, 109.77272727, 110.07727273,
            110.53636364],
}


def gap_plots():
    out, _ = run(GAPPY, synthetic_frame(40), seconds=86_400)
    return plots(out)


def test_the_real_tradingview_gap_is_reproduced_bar_for_bar():
    p = gap_plots()
    for name, expected in TRADINGVIEW.items():
        for bar, tv in zip(range(17, 27), expected):
            ours = p[name][bar]
            if tv is None:
                assert ours is None, (name, bar, ours)
            else:
                assert ours is not None and abs(ours - tv) <= TV_PRINT, (name, bar, ours, tv)


def test_the_asserted_gap_bars():
    p = gap_plots()
    assert [round(p["sma"][b], 8) for b in (20, 21, 22, 23)] == [108.4, 108.4, 108.4, 109.55]
    for name, at23 in (("ema", 108.43579824), ("rma", 105.60579065), ("wma", 108.77272727)):
        assert p[name][20:23] == [None, None, None]
        assert p[name][23] == pytest.approx(at23, abs=TV_PRINT)


def _values(body, closes):
    frame = bars(len(closes))
    frame["close"] = closes
    source = '//@version=6\nindicator("t")\nfloat s = close == -1 ? na : close\n' + body
    out, _ = run(source, frame)
    return plots(out)


def test_rules_in_general_form():
    closes = [10.0, 11, 12, 13, -1, -1, 14, 15, 16, -1, 17]   # -1 -> na
    valid = [x for x in closes if x != -1]
    p = _values('plot(ta.sma(s, 3), "sma")\nplot(ta.ema(s, 3), "ema")\nplot(ta.wma(s, 3), "wma")\n', closes)
    # sma: mean of the last 3 non-na values, also on na bars
    assert p["sma"][4] == p["sma"][5] == pytest.approx(12.0) and p["sma"][6] == pytest.approx((12 + 13 + 14) / 3)
    # ema: na on na bars, otherwise identical to the ema of the series with the na bars removed
    reference, alpha = [], 2 / 4
    for i, x in enumerate(valid):
        reference.append(sum(valid[:3]) / 3 if i == 2 else None if i < 2 else alpha * x + (1 - alpha) * reference[-1])
    ours = [v for v, x in zip(p["ema"], closes) if x != -1]
    assert [v is None for v, x in zip(p["ema"], closes) if x == -1] == [True, True, True]
    assert ours[2:] == pytest.approx(reference[2:])
    # wma: na on na bars; inside the window an na counts as the last value before it (13 at bars 4, 5)
    assert p["wma"][4] is None and p["wma"][6] == pytest.approx((13 * 1 + 13 * 2 + 14 * 3) / 6)


def test_leading_na_warm_up_is_unchanged():
    closes = [-1, -1, 5.0, 6, 7, 8, 9]
    p = _values('plot(ta.sma(s, 3), "sma")\nplot(ta.ema(s, 3), "ema")\nplot(ta.rma(s, 3), "rma")\n'
                'plot(ta.wma(s, 3), "wma")\n', closes)
    for name in ("sma", "ema", "rma", "wma"):
        assert p[name][:4] == [None] * 4 and p[name][4] is not None, name     # first value after 3 valid inputs
    assert p["ema"][4] == p["rma"][4] == pytest.approx(6.0)                  # seeded with the SMA


def test_na_on_a_forming_bar_rolls_back_cleanly():
    source = '//@version=6\nindicator("t")\nfloat s = close > 1000 ? na : close\n' \
             'plot(ta.sma(s, 3), "sma")\nplot(ta.ema(s, 3), "ema")\nplot(ta.wma(s, 3), "wma")\n'
    program = compile_script(source).program
    frame = bars(30, seed=2)
    live = PineExecution(program, {})
    run_script(live, context(frame.iloc[:21], forming_last=True), ("l",), "t")
    forming = frame.iloc[:21].copy()
    for price in (5000.0, forming.loc[20, "close"] + 1, 5000.0, forming.loc[20, "close"]):   # na, valid, na, valid
        forming.loc[20, "close"] = price
        out = run_script(live, context(forming, forming_last=True), ("l",), "t")
        full = run_script(PineExecution(program, {}), context(forming), ("l",), "t")
        assert plots(out) == plots(full)                                     # no stale state from earlier ticks
    assert all(v is not None and not math.isnan(v) for v in plots(out)["ema"][2:])
