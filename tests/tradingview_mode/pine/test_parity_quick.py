"""Fast self-checking TradingView parity scripts: generation, embedded expectations, comparison rule."""
import math
import re

import pytest

from ui.tradingview_mode.pine import compile_script
from ui.tradingview_mode.pine.errors import ERROR
from ui.tradingview_mode.pine.parity import harness as H
from ui.tradingview_mode.pine.parity import manual as M
from ui.tradingview_mode.pine.parity import quick as Q
from ui.tradingview_mode.pine.parity.fixtures import BY_NAME, PERIOD
from ui.tradingview_mode.pine.parser import parse

from .helpers import plots, run

TARGET = {"s00_data", "s05_extremes", "s06_pivots", "s07_var_varip", "s08_loops_v6", "s09_loops_v5",
          "s10_control", "s11_na"}


def text(quick):
    return (Q.QUICK_DIR / f"{quick.name}.pine").read_text()


def tv_from_ours(quick):
    """TradingView stand-in: the authoritative engine output, as lists per bar (None = na)."""
    out = {}
    for fixture in quick.fixtures:
        table = Q.expected_table(fixture)
        out[fixture[:3]] = {name: [None if v != v else float(v) for v in table[name]] for name in Q.outputs(fixture)}
    return out


def expected_total(quick):
    return {i: len(Q.check_bars(quick, f)) * len(Q.outputs(f)) for i, f in enumerate(quick.fixtures)}


def test_scope_and_script_count():
    covered = [f for q in Q.QUICK_SCRIPTS for f in q.fixtures]
    assert set(covered) == TARGET and len(covered) == len(set(covered)) and len(Q.QUICK_SCRIPTS) == 3
    for quick in Q.QUICK_SCRIPTS:
        assert len({BY_NAME[f].version for f in quick.fixtures}) == 1


def test_generator_is_reproducible_and_files_are_current():
    for quick in Q.QUICK_SCRIPTS:
        assert Q.source(quick) == Q.source(quick) == text(quick)


def test_quick_scripts_are_valid_pine():
    for quick in Q.QUICK_SCRIPTS:
        source = text(quick)
        parse(source)
        diagnostics = compile_script(source).diagnostics
        assert not [d for d in diagnostics if d.kind == ERROR], [d.text() for d in diagnostics if d.kind == ERROR]
        # only the TradingView-side checker uses what this engine does not run yet
        assert {d.feature for d in diagnostics} <= {"arrays", "generics", "strings", "drawing-objects", "core"}
        assert f"//@version={BY_NAME[quick.fixtures[0]].version}" == source.splitlines()[0]
        assert all(len(m) <= Q.MAX_LITERAL for m in re.findall(r'str\.split\("(.*)", ","\)', source))


def test_combined_calculations_equal_each_fixture_run_alone():
    for quick in Q.QUICK_SCRIPTS:
        out, _ = run(Q.core_source(quick), H.synthetic_frame(PERIOD), seconds=86_400)
        combined = plots(out)
        for fixture in quick.fixtures:
            table = Q.expected_table(fixture)
            for name in Q.outputs(fixture):
                alone = [None if v != v else float(v) for v in table[name]]
                assert combined[f"{fixture}.{name}"] == alone, (quick.name, fixture, name)


def test_embedded_expectations_are_the_engine_output_exactly():
    for quick in Q.QUICK_SCRIPTS:
        source = text(quick)
        for fixture in quick.fixtures:
            short, table, bars = fixture[:3], Q.expected_table(fixture), Q.check_bars(quick, fixture)
            listed = re.search(rf"qp_bars_{short} = array\.from\((.*)\)", source).group(1)
            assert [int(b) for b in listed.split(",")] == bars
            for name in Q.outputs(fixture):
                embedded = re.search(rf'qp_x_{short}_{name} = str\.split\("(.*)", ","\)', source).group(1).split(",")
                for bar, cell in zip(bars, embedded):
                    ours = table.at[bar, name]
                    if math.isnan(ours):
                        assert cell == "na"
                    else:
                        assert "e" not in cell and float(cell) == ours      # exact round trip, no exponent


def test_every_manual_cell_and_edge_bar_is_covered():
    for quick in Q.QUICK_SCRIPTS:
        for fixture in quick.fixtures:
            spec, bars = M.BY_FIXTURE[fixture], set(Q.check_bars(quick, fixture))
            manual_cells = {(b, n) for start, _ in spec.pages for b in range(start, start + 10) for part in spec.parts
                            for n in part}
            assert manual_cells <= {(b, n) for b in bars for n in Q.outputs(fixture)}, fixture
            assert set(Q.outputs(fixture)) == {n for part in spec.parts for n in part}
    q1 = Q.BY_QUICK["q1_main_v6"]
    for fixture in ("s05_extremes", "s06_pivots"):
        assert set(range(48)) <= set(Q.check_bars(q1, fixture))              # two periods of every tie case
    edge = {"s06_pivots": {19, 188, 193, 202, 207, 229}, "s05_extremes": {184, 186, 190, 191, 196, 199, 203, 205, 226, 227},
            "s00_data": {184, 186, 203, 205, 211, 221, 226, 227}, "s11_na": {0, 5, 10, 15},
            "s07_var_varip": {49, 50, 88}}
    for fixture, bars in edge.items():
        assert bars <= set(Q.check_bars(q1, fixture)), fixture
    names = set(Q.outputs("s06_pivots"))
    assert {"ph11", "pl11", "ph22", "pl22", "ph33", "pl33", "ph21", "pl13", "ph22_h", "pl22_l", "ph33_h", "pl33_l"} <= names
    assert {"hib3", "lob3", "hib5", "lob5", "hib10_h", "lob10_l", "hi3", "lo3", "hi10_h"} <= set(Q.outputs("s05_extremes"))


def test_version_keys_are_shown():
    v6, v5 = text(Q.BY_QUICK["q2_s08_loops_v6"]), text(Q.BY_QUICK["q3_s09_loops_v5"])
    assert 'KEY s08_loops_v6 for_dynamic_end @ bar 0' in v6 and '"ours 7"' in v6 and '"ours 3.5"' in v6
    assert 'KEY s09_loops_v5 for_dynamic_end @ bar 0' in v5 and '"ours 4"' in v5 and '"ours 3"' in v5


@pytest.mark.parametrize("tv,ours,ok", [
    (None, None, True), (float("nan"), None, True), (1.0, None, False), (None, 1.0, False),
    (0.0, 0.0, True), (1.0, 0.0, False), (0.0, 1.0, False),                       # booleans
    (100.0 + 4.9e-9, 100.0, True), (100.0 + 5.2e-9, 100.0, False),                 # half a unit of the 8th decimal
    (1e7 + 1e-5 * 0.5, 1e7, True), (1e7 + 2e-5, 1e7, False),                       # relative noise only
    (3.0, 3.0, True), (-3.0, -2.0, False)])
def test_comparison_rule(tv, ours, ok):
    assert Q.compare(tv, ours) is ok


def test_pine_rule_uses_the_documented_constants():
    for quick in Q.QUICK_SCRIPTS:
        source = text(quick)
        assert "float QP_ABS = 0.000000005" in source and "float QP_REL = 0.000000000001" in source
        assert "math.abs(tv - expected) <= QP_ABS + QP_REL * math.abs(expected)" in source
        assert "(na(tv) and na(expected)) or (not na(tv) and not na(expected)" in source


def test_simulated_checker_passes_on_identical_values_and_counts_every_cell():
    for quick in Q.QUICK_SCRIPTS:
        result = Q.simulate(text(quick), tv_from_ours(quick))
        assert result["fail"] == {} and result["count"] == expected_total(quick)


def test_simulated_checker_reports_failures():
    quick = Q.BY_QUICK["q1_main_v6"]
    tv = tv_from_ours(quick)
    tv["s06"]["ph33"][19] = None                            # TV na / ours value
    tv["s11"]["gappy"][5] = 1.0                             # TV value / ours na
    tv["s05"]["hib3"][14] = tv["s05"]["hib3"][14] - 1       # a tie resolved to the other bar
    tv["s00"]["c"][3] += 1e-8                               # just outside the tolerance
    tv["s10"]["tuple_up"][12] += 4e-9                       # inside the tolerance: must still pass
    result = Q.simulate(text(quick), tv)
    fixtures = quick.fixtures
    assert result["fail"] == {fixtures.index("s06_pivots"): 1, fixtures.index("s11_na"): 1,
                              fixtures.index("s05_extremes"): 1, fixtures.index("s00_data"): 1}
    listed = {(bar, field) for bar, field, _, _ in result["failures"]}
    assert listed == {(19, "s06 ph33"), (5, "s11 gappy"), (14, "s05 hib3"), (3, "s00 c")}
    assert result["count"] == expected_total(quick)


def test_self_test_mode_fails_exactly_one_cell():
    for quick in Q.QUICK_SCRIPTS:
        result = Q.simulate(text(quick), tv_from_ours(quick), inject=True)
        assert result["fail"] == {0: 1} and len(result["failures"]) == 1
    assert 'input.bool(false, "Self-test: corrupt one expected value (must FAIL)")' in text(Q.QUICK_SCRIPTS[0])


def test_checklist_readme_and_report_reference_the_quick_scripts():
    checklist, readme = M.CHECKLIST.read_text(), (M.ROOT / "README.md").read_text()
    for quick in Q.QUICK_SCRIPTS:
        cells = sum(expected_total(quick).values())
        assert f"`quick/{quick.name}.pine`" in checklist and f"| {cells} |" in checklist
        assert f"`quick/{quick.name}.pine`" in readme
    assert "## FAST TRADINGVIEW PARITY" in readme
    report = H.REPORT.read_text()
    assert "## Fast self-checking TradingView scripts" in report
    for quick in Q.QUICK_SCRIPTS:
        for fixture in quick.fixtures:
            assert f"| `quick/{quick.name}.pine` | {fixture} |" in report


def test_verification_status_is_never_broader_than_the_recorded_evidence(tmp_path, monkeypatch):
    status = H.verification_status()
    verified = {name for name, text in status.items() if text.startswith("VERIFIED")}
    assert verified == {"s00_data", "s01_averages", "s02_oscillators", "s03_history", "s04_cross", "s05_extremes",
                        "s06_pivots", "s07_var_varip", "s08_loops_v6", "s09_loops_v5", "s10_control", "s11_na"}
    assert status["c01_chart"].startswith("NOT VERIFIED") and status["s12_plots"].startswith("NOT VERIFIED")
    assert "historical bars only" in status["s07_var_varip"] and not status["x01_pinets_ties"].startswith("VERIFIED")
    observations = H.observations()
    assert "var_increments_on_new_bar" not in observations and "isnew_first_update_only" not in observations
    # without recorded results nothing is verified, whatever the local tests say
    monkeypatch.setattr(H, "TV_DIR", tmp_path)
    assert not any(text.startswith("VERIFIED") for text in H.verification_status().values())
