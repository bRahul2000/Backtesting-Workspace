"""ta.highest / ta.lowest with na input — confirmed on REAL TradingView (quick/q1_main_v6.pine).

TradingView: na when the CURRENT value is na (s11 na_highest at bars 5, 10, 15); an older na inside the
window is skipped (bars 6, 11, 16 and bar 2 passed with a value). Every other cell TradingView confirmed in
that run (3821 of 3824) is protected by the snapshot test below, including all 1404 s05_extremes cells.
"""
import json
import math

import pytest

from ui.tradingview_mode.pine.parity import quick as Q
from ui.tradingview_mode.pine.parity.harness import TV_DIR

from .helpers import bars, plots, run

CONFIRMED = json.loads((TV_DIR / "q1_main_v6.confirmed.json").read_text())


def s11(name):
    return Q.expected_table("s11_na")[name]


def test_highest_is_na_on_na_bars_like_tradingview():
    values = s11("na_highest")
    for bar in (5, 10, 15):
        assert math.isnan(values[bar]), bar
    # neighbouring bars: the na one or two bars back is skipped (all confirmed on TradingView)
    expected = {2: 102.0, 3: 102.0, 4: 101.5, 6: 104.0, 7: 105.25, 9: 105.25, 11: 106.0, 12: 107.25, 14: 108.5,
                16: 108.0, 17: 109.25}
    assert {bar: values[bar] for bar in expected} == expected
    assert math.isnan(values[0]) and math.isnan(values[1])


def test_highest_and_lowest_rule_in_general_form():
    frame = bars(12)
    frame["close"] = [5.0, 7, -1, 6, 4, -1, -1, 9, 3, 8, 2, 1]        # -1 -> na
    source = ('//@version=6\nindicator("t")\nfloat s = close == -1 ? na : close\n'
              'plot(ta.highest(s, 3), "hi")\nplot(ta.lowest(s, 3), "lo")\n'
              'plot(ta.highestbars(s, 3), "hib")\nplot(ta.lowestbars(s, 3), "lob")\n')
    out, _ = run(source, frame)
    p = plots(out)
    assert p["hi"][:6] == [None, None, None, 7.0, 6.0, None] and p["lo"][:6] == [None, None, None, 6.0, 4.0, None]
    assert p["hi"][6] is None and p["hi"][7] == 9.0 and p["lo"][7] == 9.0      # window 5..7: only bar 7 is valid
    assert p["hi"][8] == 9.0 and p["lo"][8] == 3.0
    # highestbars / lowestbars are not changed (no TradingView evidence for an na current value yet)
    assert p["hib"][3] == -2 and p["lob"][4] == 0


def test_every_cell_tradingview_confirmed_in_q1_still_matches():
    quick = Q.BY_QUICK["q1_main_v6"]
    total = 0
    for fixture, entry in CONFIRMED["fixtures"].items():
        assert entry["bars"] == Q.check_bars(quick, fixture)
        table = Q.expected_table(fixture)
        for name, cells in entry["values"].items():
            for bar, text in zip(entry["bars"], cells):
                tv = None if text == "na" else float(text)
                ours = table.at[bar, name]
                assert Q.compare(tv, None if math.isnan(ours) else float(ours)), (fixture, name, bar, text, ours)
                total += 1
    assert total == 3824 and set(CONFIRMED["fixtures"]) == set(quick.fixtures)


@pytest.mark.parametrize("fixture,cells", [("s05_extremes", 1404), ("s06_pivots", 1404), ("s00_data", 350)])
def test_verified_fixture_cell_counts_are_unchanged(fixture, cells):
    quick = Q.BY_QUICK["q1_main_v6"]
    assert len(Q.check_bars(quick, fixture)) * len(Q.outputs(fixture)) == cells
    assert sum(len(v) for v in CONFIRMED["fixtures"][fixture]["values"].values()) == cells
