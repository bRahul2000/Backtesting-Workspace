"""Manual parity mode (TradingView Basic plan): generated table scripts and their expected values."""
import json
import re

import pandas as pd
import pytest

from ui.tradingview_mode.pine import compile_script
from ui.tradingview_mode.pine.errors import ERROR
from ui.tradingview_mode.pine.parity import harness as H
from ui.tradingview_mode.pine.parity import manual as M
from ui.tradingview_mode.pine.parity.fixtures import BY_NAME
from ui.tradingview_mode.pine.parser import parse

REQUIRED = {"s01_averages", "s02_oscillators", "s03_history", "s04_cross", "s05_extremes", "s06_pivots",
            "s08_loops_v6", "s09_loops_v5", "s10_control", "s11_na"}


def test_required_fixtures_have_manual_scripts_with_readable_tables():
    assert REQUIRED <= set(M.BY_FIXTURE)
    for spec in M.SPECS:
        outputs = set(re.findall(r'^plot\(.*, "(\w+)"\)$', BY_NAME[spec.fixture].body, re.M))
        shown = {name for part in spec.parts for name in part}
        assert shown == outputs, spec.fixture                         # every fixture output is displayed
        assert all(1 <= len(part) <= 7 for part in spec.parts)       # <= 7 value columns (1440 px)
        assert all(0 <= start for start, _ in spec.pages) and len(spec.pages) >= 2


def test_manual_scripts_are_valid_pine_whose_only_gaps_are_the_table_display():
    for spec in M.SPECS:
        source = (M.MANUAL_DIR / f"{spec.fixture}.pine").read_text()
        assert source == M.manual_source(spec)
        parse(source)                                                 # full Pine syntax parses
        diagnostics = compile_script(source).diagnostics
        assert not [d for d in diagnostics if d.kind == ERROR], [d.text() for d in diagnostics]
        assert {d.feature for d in diagnostics} <= {"drawing-objects", "core"}   # table.*, position.*, text.*
        assert all(("table" in d.message or "position." in d.message or "text." in d.message) for d in diagnostics)
        assert f"//@version={BY_NAME[spec.fixture].version}" in source.splitlines()[0]
    for name, source in ((M.VISUAL_NA_GAP, M.na_gap_visual_source()), (M.LIVE_TABLE, M.live_table_source())):
        assert (M.MANUAL_DIR / f"{name}.pine").read_text() == source
        parse(source)
        assert not [d for d in compile_script(source).diagnostics if d.kind == ERROR]
    assert compile_script(M.na_gap_visual_source()).ok                 # the visual check runs in this engine too


def test_manual_calculations_are_the_fixture_calculations():
    for spec in M.SPECS:
        fixture = BY_NAME[spec.fixture]
        core = M.core_source(spec)
        assert compile_script(core).ok and M.PRELUDE in core
        # same statements, in the same order: only `plot(expr, "n")` became `float v_n = expr`
        body = [line for line in fixture.body.strip().splitlines() if not line.startswith("plot(")]
        manual_body = [line for line in M.manual_source(spec).splitlines() if not line.startswith("float v_")]
        position = 0
        for line in body:
            position = manual_body.index(line, position) + 1


def test_expected_rows_match_the_authoritative_fixture_outputs_exactly():
    for spec in M.SPECS:
        rows = M.expected_rows(spec)
        ours = H.run_ours(BY_NAME[spec.fixture], H.synthetic_frame(int(rows["bar"].max()) + 1))
        for _, row in rows.iterrows():
            for name in rows.columns[2:]:
                value = ours.at[row["bar"], name]
                assert row[name] == M.fmt(None if pd.isna(value) else float(value)), (spec.fixture, row["bar"], name)


def test_expected_files_are_deterministic_and_up_to_date():
    for spec in M.SPECS:
        rows = M.expected_rows(spec)
        assert rows.equals(M.expected_rows(spec))
        assert (M.EXPECTED_DIR / f"{spec.fixture}.csv").read_text() == rows.to_csv(index=False, lineterminator="\n")
        assert (M.EXPECTED_DIR / f"{spec.fixture}.md").read_text() == M.expected_markdown(spec, rows)
        assert len(rows) == len(spec.pages) * M.ROWS


def test_expected_values_cover_the_semantic_events():
    table = lambda name: pd.read_csv(M.EXPECTED_DIR / f"{name}.csv", dtype=str).set_index("bar")
    v6, v5 = table("s08_loops_v6"), table("s09_loops_v5")
    assert set(v6["for_dynamic_end"]) == {"7"} and set(v5["for_dynamic_end"]) == {"4"}
    assert set(v6["div_const"]) == {"3.5"} and set(v5["div_const"]) == {"3"}
    cross = table("s04_cross")
    assert cross.loc[["101"], "xover_touch"].iloc[0] == "1" and cross.loc[["100"], "xover_touch"].iloc[0] == "0"
    assert cross.loc[["88"], "xover"].iloc[0] == "1"
    averages = table("s01_averages")
    assert averages.loc[["3"], "sma5"].iloc[0] == "na" and averages.loc[["4"], "sma5"].iloc[0] != "na"
    pivots = table("s06_pivots")
    assert pivots.loc[["19"], "ph33"].iloc[0] == "9"          # bar 16 (9) with an equal 9 three bars left and pivots.loc[["188"], "ph22_h"].iloc[0] == "120"
    na = table("s11_na")
    assert na.loc[["5"], "gappy"].iloc[0] == "na" and na.loc[["5"], "is_na"].iloc[0] == "1"


@pytest.mark.parametrize("value,text", [(None, "na"), (float("nan"), "na"), (3.0, "3"), (3.5, "3.5"),
                                        (105.123456789, "105.12345679"), (-0.0, "-0"), (1e-10, "0"),
                                        (0.125, "0.125"), (-2.25, "-2.25"), (1234567.000000004, "1234567")])
def test_value_format_mirrors_the_table_format(value, text):
    assert M.fmt(value) == text


def test_checklist_references_valid_files_and_the_real_pages():
    checklist = M.CHECKLIST.read_text()
    root = M.ROOT
    for path in re.findall(r"`((?:manual|ours_manual)/[^`]+)`", checklist):
        assert (root / path).exists(), path
    for spec in M.SPECS:
        row = next(line for line in checklist.splitlines() if f"`manual/{spec.fixture}.pine`" in line)
        pages = " · ".join(f"{i} → {start}-{start + M.ROWS - 1}" for i, (start, _) in enumerate(spec.pages))
        assert pages in row and f"`ours_manual/{spec.fixture}.md`" in row and f"| {len(spec.parts)} |" in row
    for name in (M.VISUAL_NA_GAP, M.LIVE_TABLE):
        assert f"`manual/{name}.pine`" in checklist
    readme = (root / "README.md").read_text()
    assert "## TradingView Basic plan — manual parity" in readme and "MANUAL_CHECKLIST.md" in readme


def test_manual_results_feed_the_report(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "TV_DIR", tmp_path)
    assert "| `manual/s01_averages.pine` | 4 × 2 = 8 | not checked |" in H.report([])
    (tmp_path / "manual_results.json").write_text(json.dumps(
        {"s01_averages": {"status": "match", "checked": ["0/1", "0/2"]}, "s04_cross": {"status": "mismatch", "note": "bar 88"},
         "s03_history": {"status": "match", "checked": ["0/1", "0/2", "1/1", "1/2"]}}))
    text = H.report([])
    assert "| `manual/s01_averages.pine` | 4 × 2 = 8 | match (partial: 2 of 8) | 0/1, 0/2 |" in text
    assert "| `manual/s03_history.pine` | 2 × 2 = 4 | match | 0/1, 0/2, 1/1, 1/2 |" in text
    assert "| `manual/s04_cross.pine` | 5 × 2 = 10 | mismatch | — | bar 88 |" in text
