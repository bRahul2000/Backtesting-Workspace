"""Pine parity: fixtures, the TradingView comparison harness, and every behaviour confirmed so far.

Evidence levels are named in each test: a third-party TradingView capture (external/*.json) or
TradingView's documentation (v6 migration guide, Loops and Plots pages). Our own TradingView captures,
once placed in parity/tradingview/, are compared by the report test below.
"""
import json
import math

import numpy as np
import pandas as pd
import pytest

from ui.tradingview_mode.pine import PineExecution, compile_script, run_script
from ui.tradingview_mode.pine.parity import harness as H
from ui.tradingview_mode.pine.parity.fixtures import BY_NAME, FIXTURES, MANUAL_CHECKS, PERIOD, synthetic_row

from .helpers import bars, context, plots, run


def ours(name, n=PERIOD):
    return H.run_ours(BY_NAME[name], H.synthetic_frame(n))


def series(source_body, version=6, n=60):
    source = f'//@version={version}\nindicator("t")\n' + source_body.strip("\n") + "\n"
    out, _ = run(source, bars(n))
    return plots(out)


# ---- fixtures and generated files ----------------------------------------------------------------------------

def test_every_fixture_compiles_and_runs_without_warnings():
    for fixture in FIXTURES:
        result = compile_script(fixture.source)
        assert result.ok and not result.diagnostics, (fixture.name, [d.text() for d in result.diagnostics])
        assert ours(fixture.name).columns[5] == "bi"
    for name, source in MANUAL_CHECKS.items():
        assert compile_script(source).ok, name


def test_fixture_data_prelude_matches_the_stored_dataset_exactly():
    table = ours("s00_data")
    mirror = pd.DataFrame([synthetic_row(i) for i in range(PERIOD)])
    for pine, py in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"), ("v", "volume")):
        assert table[pine].tolist() == mirror[py].tolist()                 # bit-for-bit, no tolerance
    assert all((x * 4).is_integer() for x in table[["o", "h", "l", "c"]].to_numpy().ravel())
    stored = pd.read_csv(H.DATA_DIR / "synthetic_ohlcv.csv")
    assert stored[["open", "high", "low", "close", "volume"]].to_numpy().tolist() == \
        mirror[["open", "high", "low", "close", "volume"]].to_numpy().tolist()
    k = np.arange(PERIOD)
    flat = (k >= 211) & (k < 222)                                            # zero-range candles
    assert (table.loc[flat, "h"] == table.loc[flat, "l"]).all()
    assert table["h"][184] == table["h"][186] == table["l"][203] + 25 == 120.0


def test_generated_parity_files_are_up_to_date():
    for fixture in FIXTURES:
        assert (H.FIXTURE_DIR / f"{fixture.name}.pine").read_text() == fixture.source, fixture.name
        assert (H.OURS_DIR / f"{fixture.name}.csv").read_text() == H.ours_csv(fixture), fixture.name
    for name, source in MANUAL_CHECKS.items():
        assert (H.FIXTURE_DIR / f"{name}.pine").read_text() == source
    assert H.REPORT.read_text() == H.report(H.compare_all()), "run: python -m ui.tradingview_mode.pine.parity"


def test_every_captured_reference_matches_or_is_classified():
    for result in H.compare_all():
        assert not result.problem, (result.fixture.name, result.problem)
        for output in result.outputs + result.timing:
            if output.mismatches:
                assert (result.fixture.name, output.title) in H.CLASSIFICATIONS, (result.fixture.name, output.title)


# ---- pivots / extremes: third-party TradingView capture ---------------------------------------------------------

def test_third_party_tradingview_tie_capture_matches_bar_for_bar():
    results = [r for r in H.compare_all() if r.reference.source == "third-party-capture"]
    assert len(results) == 1 and results[0].verdict == "PASS"
    result = results[0]
    assert result.bars == 84 and len(result.outputs) == 8
    assert all(o.compared == 84 and o.mismatches == 0 for o in result.outputs)


@pytest.mark.parametrize("left,right", [(1, 1), (2, 2), (3, 3)])
def test_pivot_left_tie_keeps_the_pivot_right_tie_cancels_it(left, right):
    # candidate 9 at bar 10; an equal 9 sits `left` bars before it, or `right` bars after it
    for tie_side in ("left", "right"):
        values = [1.0] * 25
        values[10] = 9.0
        values[10 - left if tie_side == "left" else 10 + right] = 9.0
        cases = "\n".join(f"    {i} => {v}" for i, v in enumerate(values))
        p = series(f"float s = switch bar_index\n{cases}\n    => 1.0\n"
                   f"plot(ta.pivothigh(s, {left}, {right}), \"ph\")\nplot(ta.pivotlow(-s, {left}, {right}), \"pl\")", n=25)
        confirm = 10 + right                                                   # reported `right` bars later
        if tie_side == "left":
            assert p["ph"][confirm] == 9.0 and p["pl"][confirm] == -9.0         # left tie keeps the pivot
        else:
            assert p["ph"][confirm] is None and p["pl"][confirm] is None       # right tie cancels it ...
            assert p["ph"][confirm + right] == 9.0                              # ... the later bar pivots


def test_highestbars_and_lowestbars_report_the_oldest_tie():
    p = series("float s = bar_index % 4 == 1 ? 5.0 : 1.0\n"
               "plot(ta.highestbars(s, 5), \"hb\")\nplot(ta.lowestbars(-s, 5), \"lb\")", n=12)
    # bars 5 and 9 both hold 5.0; on bar 9 the window 5..9 has the tie -> offset of bar 5 = -4
    assert p["hb"][9] == -4 and p["lb"][9] == -4 and p["hb"][10] == -1


# ---- documented v5/v6 semantics ---------------------------------------------------------------------------------

def test_for_end_expression_is_reevaluated_in_v6_and_fixed_in_v5():
    loop = """
int limit = 3
int iters = 0
for i = 0 to limit
    iters += 1
    if i == 1
        limit := 6
plot(iters, "n")
int down = 0
int stop = 5
for i = 0 to stop
    down += 1
    stop := -10
plot(down, "shrink")
"""
    v6, v5 = series(loop, 6, 3), series(loop, 5, 3)
    assert set(v6["n"]) == {7.0} and set(v5["n"]) == {4.0}
    # v6: the end shrinks below the counter -> the loop stops; the direction set at the start never flips
    assert set(v6["shrink"]) == {1.0} and set(v5["shrink"]) == {6.0}


def test_const_int_division_truncates_only_in_v5():
    body = 'plot(7 / 2, "a")\nplot(-7 / 2, "b")\nplot(bar_index / 2, "c")\nint n = 7\nplot(n / 2, "d")'
    v5, v6 = series(body, 5, 3), series(body, 6, 3)
    assert v5["a"][0] == 3 and v5["b"][0] == -3 and v5["c"][1] == 0.5 and v5["d"][0] == 3.5
    assert v6["a"][0] == 3.5 and v6["b"][0] == -3.5 and v6["d"][0] == 3.5


def test_and_or_are_strict_in_v5_and_lazy_in_v6():
    body = ('bool a = bar_index % 2 == 0 and ta.cum(1) % 4 == 0\nplot(a ? 1 : 0, "and")\n'
            'bool o = bar_index % 2 == 0 or ta.cum(1) % 4 == 0\nplot(o ? 1 : 0, "or")')
    v5, v6 = series(body, 5, 16), series(body, 6, 16)
    assert [i for i, x in enumerate(v5["and"]) if x] == []                      # cum counts every bar
    assert [i for i, x in enumerate(v6["and"]) if x] == [6, 14]                 # cum counts even bars only
    assert [i for i, x in enumerate(v5["or"]) if x and i % 2] == [3, 7, 11, 15]
    assert [i for i, x in enumerate(v6["or"]) if x and i % 2] == [7, 15]        # odd bars 1,3,5,7 -> cum 1,2,3,4


def test_timeframe_period_includes_the_multiplier_in_v6():
    body = 'plot(timeframe.period == "1D" ? 1 : 0, "one")\nplot(timeframe.period == "D" ? 1 : 0, "bare")'
    source = lambda v: f'//@version={v}\nindicator("t")\n{body}\n'
    daily = bars(5, freq="1D")
    for version, one, bare in ((6, 1.0, 0.0), (5, 0.0, 1.0)):
        out, _ = run(source(version), daily, seconds=86_400)
        assert plots(out)["one"][0] == one and plots(out)["bare"][0] == bare


# ---- history, crossover, warm-up, var ---------------------------------------------------------------------------

def test_history_references_and_warm_up():
    t = ours("s03_history")
    c = ours("s00_data")["c"]
    assert t["c_1"].iloc[1:].tolist() == c.iloc[:-1].tolist() and math.isnan(t["c_1"][0])
    assert t["c_2"].isna().sum() == 2 and t["bi_5"].isna().sum() == 5 and t["bi_5"][5] == 0
    assert t["acc_1"].iloc[1:].tolist() == t["acc"].iloc[:-1].tolist()
    a = ours("s01_averages")
    first = {col: int(a[col].first_valid_index()) for col in ("sma5", "sma20", "ema9", "rma14", "wma10", "ema1")}
    assert first == {"sma5": 4, "sma20": 19, "ema9": 8, "rma14": 13, "wma10": 9, "ema1": 0}
    assert a["ema9"][8] == pytest.approx(c.iloc[:9].mean(), abs=1e-12)          # EMA seeded with the SMA
    o = ours("s02_oscillators")
    assert int(o["rsi14"].first_valid_index()) == 14 and int(o["atr14_formula"].first_valid_index()) == 13


def test_crossover_fires_on_the_bar_after_a_touch_only():
    x = ours("s04_cross")
    assert x.index[x["xover_touch"] == 1].tolist() == [101] and x.index[x["xunder_touch"] == 1].tolist() == [101]
    assert ((x["xover"] + x["xunder"]) == x["xany"]).all()


def test_var_varip_historical_and_function_call_sites():
    v = ours("s07_var_varip")
    assert v["var_count"].tolist() == list(range(1, PERIOD + 1)) == v["varip_count"].tolist()
    assert set(v["no_var"]) == {1.0}
    assert v["udf_var_a"].tolist() == list(range(1, PERIOD + 1))
    evens = v.loc[v.index % 2 == 0, "udf_var_b"].tolist()
    assert evens == list(range(1, PERIOD // 2 + 1)) and set(v.loc[v.index % 2 == 1, "udf_var_b"]) == {-1.0}
    assert v["var_resets"][50] == 0 and v["var_resets"][49] == 49


def test_varip_counts_ticks_and_var_rolls_back_on_the_live_bar():
    program = compile_script(MANUAL_CHECKS["m01_live_varip"]).program
    frame = bars(30, seed=5)
    live = PineExecution(program, {})
    run_script(live, context(frame.iloc[:21], forming_last=True), ("m",), "t")    # bar 20 forming, tick 1
    last = frame.iloc[:21].copy()
    for tick, price in enumerate((101.0, 102.0, 100.5), start=2):
        last.loc[20, "close"] = price
        p = plots(run_script(live, context(last, forming_last=True), ("m",), "t"))
        assert p["varip ticks this bar"][-1] == tick and p["var count"][-1] == 21 and p["varip count"][-1] == 20 + tick
    p = plots(run_script(live, context(frame.iloc[:22], forming_last=True), ("m",), "t"))  # new bar 21 opens
    assert p["varip ticks this bar"][-1] == 1 and p["var count"][-1] == 22


def test_na_gap_plots_render_line_bridged_and_linebr_broken():
    table = ours("s12_plots")
    gap = table["line_gappy"].isna()
    assert gap.sum() == 3 * PERIOD // 10 and gap.equals(table["linebr"].isna())
    fixture = BY_NAME["s12_plots"]
    run_ = run_script(PineExecution(compile_script(fixture.source).program, {}),
                      context(H.synthetic_frame(40), seconds=86_400), ("x",), "p")
    styles = {o["title"]: o.get("style") for o in run_.outputs if o["kind"] == "plot"}
    # TradingView docs: plot.style_line (also the default) joins across na; plot.style_linebr leaves the gap.
    # The chart renderer (pineData.seriesData) bridges "line" and inserts whitespace for "*br" styles.
    assert styles["line_gappy"] == styles["line_explicit"] == "line" and styles["linebr"] == "linebr"


def test_shapes_chars_and_colors_are_drawn_on_their_condition_bars():
    t = ours("s12_plots")
    for drawn, condition in BY_NAME["s12_plots"].timing.items():
        assert t[drawn].fillna(0).tolist() == t[condition].tolist(), drawn
    assert t["up_cond"].sum() > 0 and t["dn_cond"].sum() > 0


# ---- the comparison harness itself (not parity evidence) ----------------------------------------------------------

def _fake_export(tmp_path, name, mutate=None, decimals=17):
    table = ours(name)
    table = table.drop(columns=[c for c in BY_NAME[name].timing])
    if mutate:
        mutate(table)
    path = tmp_path / f"{name}.csv"
    fmt = f"%.{decimals}g" if decimals >= 17 else f"%.{decimals}f"
    table.to_csv(path, index=False, na_rep="", float_format=fmt)
    return H.read_export(path)


def test_harness_reads_the_export_layout_and_flags_every_difference(tmp_path):
    fixture = BY_NAME["s01_averages"]
    same = H.compare_fixture(fixture, _fake_export(tmp_path, "s01_averages"))
    assert same.verdict == "PASS" and same.bars == PERIOD and same.mismatches == 0
    bumped = H.compare_fixture(fixture, _fake_export(
        tmp_path, "s01_averages", lambda t: t.__setitem__("ema9", t["ema9"] + np.where(t.index == 50, 1e-6, 0))))
    ema = next(o for o in bumped.outputs if o.title == "ema9")
    assert bumped.verdict == "FAIL" and ema.mismatches == 1 and ema.first_bar == 50
    assert ema.max_abs_diff == pytest.approx(1e-6, rel=1e-3)
    nas = H.compare_fixture(fixture, _fake_export(tmp_path, "s01_averages",
                                                  lambda t: t.__setitem__("sma5", t["sma5"].where(t.index != 4))))
    assert next(o for o in nas.outputs if o.title == "sma5").na_mismatches == 1
    coarse = H.compare_fixture(fixture, _fake_export(tmp_path, "s01_averages", decimals=2))
    assert coarse.verdict == "INCONCLUSIVE" and coarse.mismatches == 0          # never PASS on 2-decimal data


def test_harness_timing_and_integer_rules(tmp_path):
    fixture = BY_NAME["s12_plots"]
    moved = H.compare_fixture(fixture, _fake_export(tmp_path, "s12_plots",
                                                    lambda t: t.__setitem__("up_cond", t["up_cond"].shift(1).fillna(0))))
    assert moved.verdict == "FAIL" and any(o.mismatches for o in moved.timing)
    assert H.compare_values(3.0, 3.0)[0] and not H.compare_values(3.0, 4.0)[0]
    assert not H.compare_values(1.0, float("nan"))[0] and H.compare_values(float("nan"), float("nan"))[0]
    assert H.compare_values(100.0 + 5e-8, 100.0)[0] and not H.compare_values(100.0 + 5e-7, 100.0)[0]


def test_harness_chart_track_requires_the_first_bar(tmp_path):
    fixture = BY_NAME["c01_chart"]
    ok = H.compare_fixture(fixture, _fake_export(tmp_path, "c01_chart"))
    assert ok.verdict == "PASS" and ok.bars == PERIOD
    late = H.compare_fixture(fixture, _fake_export(tmp_path, "c01_chart", lambda t: t.drop(index=range(10), inplace=True)))
    assert late.verdict == "NOT COMPARED" and "bar_index 10" in late.problem


def test_harness_reads_spot_checks_and_iso_times(tmp_path):
    ours_table = ours("s04_cross")
    spot = tmp_path / "s04_cross.spot.csv"
    spot.write_text("bar_index,output,value\n100,xover_touch,0\n101,xover_touch,1\n102,xover_touch,0\n5,since_xover,\n")
    ref = H.read_spot(spot)
    result = H.compare_fixture(BY_NAME["s04_cross"], ref)
    touch = next(o for o in result.outputs if o.title == "xover_touch")
    assert touch.compared == 3 and touch.mismatches == 0 and math.isnan(ours_table["since_xover"][5])
    export = tmp_path / "iso.csv"
    ours_table.assign(time=pd.to_datetime(ours_table["time"], unit="s", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")).to_csv(
        export, index=False, na_rep="")
    assert H.read_export(export).table["time"].tolist() == ours_table["time"].tolist()
    assert json.loads((H.EXTERNAL_DIR / "pinets_pr322_ties.json").read_text())["fixture"] == "x01_pinets_ties"
