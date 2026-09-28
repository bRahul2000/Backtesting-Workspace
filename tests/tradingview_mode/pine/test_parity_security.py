"""P2.1 step 1: the request.security() historical-semantics fixture GENERATOR (no runtime exists yet)."""
import re

import pandas as pd
import pytest

from ui.tradingview_mode.pine import PineExecution, compile_script, run_script
from ui.tradingview_mode.pine.engine import data_context
from ui.tradingview_mode.pine.errors import ERROR
from ui.tradingview_mode.pine.parity import harness as H
from ui.tradingview_mode.pine.parity import security_fixture as S
from ui.tradingview_mode.pine.parser import parse

SOURCE = S.source()


def section(start: str, end: str) -> str:
    return SOURCE[SOURCE.index(start):SOURCE.index(end)]


def code(text: str) -> str:
    """Pine code without // comments."""
    return "\n".join(line.split("//")[0] for line in text.splitlines())


def test_generation_is_deterministic_and_the_file_is_current():
    assert S.source() == SOURCE == (S.QUICK_DIR / f"{S.SCRIPT_NAME}.pine").read_text()
    assert SOURCE.startswith("//@version=6") and S.SYMBOL in SOURCE


def test_the_tradingview_verified_q4_script_is_frozen():
    import hashlib
    import json

    recorded = json.loads((H.TV_DIR / "quick_results.json").read_text())["q4_security_historical"]
    assert recorded["status"] == "PASS"
    assert hashlib.sha256(SOURCE.encode()).hexdigest() == recorded["script_sha256"]     # the exact script TradingView ran


def test_script_is_valid_pine():
    parse(SOURCE)
    diagnostics = compile_script(SOURCE).diagnostics
    assert not [d for d in diagnostics if d.kind == ERROR], [d.text() for d in diagnostics if d.kind == ERROR]
    # request.security() itself is implemented since P2.1; only the TradingView-side checker is not runnable here
    assert {d.feature for d in diagnostics} <= {"arrays", "generics", "strings", "drawing-objects", "core"}


def test_expected_values_never_come_from_request_security():
    expected = code(section("// ---- EXPECTED VALUES", "// ---- checker"))
    assert "request." not in expected and "expAll(int H, int P, bool active)" in expected
    under_test = section("// ---- VALUES UNDER TEST", "// ---- EXPECTED VALUES")
    calls = re.findall(r"request\.security\(", SOURCE)
    assert len(re.findall(r"request\.security\(", under_test)) == len(calls) - SOURCE[:SOURCE.index("indicator(")].count("request.security(")
    assert "request." not in code(SOURCE[SOURCE.index("// ---- checker"):])
    for match in re.finditer(r'qp_check\(\d+, "[^"]+", (\w+), (.+)\)$', SOURCE, re.M):
        tested, expected_expr = match.groups()
        assert re.fullmatch(r"(r_\w+_\d+|s_\w+)", tested)                        # value under test
        assert not re.search(r"\b(r_\w+_\d+|s_\w+)\b", expected_expr)          # expected side never uses it
        assert re.fullmatch(r"(ec1_\d+|\(pos\d+ == \d+ \? ec\d+_\d+ : (na|e[cp]\d+_\d+)\))", expected_expr)


def test_every_mapping_and_expression_is_present():
    under_test = section("// ---- VALUES UNDER TEST", "// ---- EXPECTED VALUES")
    for combo in (S.SAME_TF,) + S.COMBOS:
        gaps = "barmerge.gaps_on" if combo.gaps else "barmerge.gaps_off"
        look = "barmerge.lookahead_on" if combo.lookahead else "barmerge.lookahead_off"
        assert re.search(rf'= request\.security\(syminfo\.tickerid, "{combo.tf}", \[.*\], gaps={gaps}, lookahead={look}\)',
                         under_test), combo.key
    assert {(c.tf, c.gaps, c.lookahead) for c in S.COMBOS} == {(tf, g, la) for tf in ("5", "15") for g in (False, True)
                                                              for la in (False, True)}
    assert len(re.findall(r'^float s_\w+ = request\.security\(syminfo\.tickerid, "5", fAt\(time\)', under_test, re.M)) == 4
    exprs = dict(S.ELEMENTS)
    assert exprs["hist1"] == "srcG[1]" and exprs["sma3"].startswith("ta.sma") and exprs["ema3"].startswith("ta.ema")
    assert exprs["rsi3"].startswith("ta.rsi") and exprs["udf"] == "udfDelta(srcG)" and exprs["var"] == "keepAlt(srcG)"
    assert exprs["closeLike"] == "gAt(time_close)" and exprs["globalDep"] == "srcG"          # tuple of OHLC-likes
    assert "var float kept = na" in SOURCE and "udfDelta(float s) => s - s[1]" in SOURCE


def test_self_test_corrupts_exactly_the_first_checked_cell():
    assert 'input.bool(false, "Self-test: corrupt one expected value (must FAIL)")' in SOURCE
    assert "    if qp_inject and grp == 0 and array.get(qp_count, 0) == 0\n        expected := nz(expected) + 0.001" in SOURCE


def test_window_is_complete_historical_and_excludes_the_forming_bar():
    assert f"int QP_WINDOW = {S.WINDOW}" in SOURCE and f"int QP_WARMUP = {S.WARMUP}" in SOURCE
    assert ("bool qp_inWindow = not barstate.isrealtime and bar_index >= last_bar_index - QP_WINDOW and "
            "bar_index <= last_bar_index - 1") in SOURCE
    total = 0
    for key, _, cases in S.groups():
        cells = len(cases) * S.WINDOW
        total += cells
        assert f"== {cells}" in SOURCE, key                       # a group is PASS only when every cell was checked
    assert total == 134400 and f'"{total}"' in SOURCE
    assert "qp_complete = qp_chartOk and qp_gaps == 0 and bar_index - QP_WINDOW >= QP_WARMUP" in SOURCE
    # history needed before the window: the slowest reproduced state (15m RSI) must converge inside it
    assert S.WARMUP >= S.RSI_DEPTH * 15 and S.WARMUP >= S.EMA_DEPTH * 15
    assert 0.5 ** (S.EMA_DEPTH - S.EMA_LEN) * 100 < 1e-12 and (2 / 3) ** (S.RSI_DEPTH - S.RSI_LEN) * 100 < 1e-12


def test_boundary_positions_are_all_covered():
    start = pd.Timestamp("2026-06-01 13:37", tz="UTC")
    minutes = [int((start + pd.Timedelta(minutes=i)).timestamp() * 1000) for i in range(S.WINDOW)]
    for period in (5, 15):
        positions = pd.Series([(t // 60_000) % period for t in minutes]).value_counts()
        assert set(positions.index) == set(range(period)) and positions.min() >= S.WINDOW // period - 1
    rows = S.pattern_rows()
    assert {size for *_, size in rows} == {1, 5, 15} and len(rows) == 1 + 8 + 4
    for row, (_, tv, pattern, size) in enumerate(rows):
        assert len(pattern) == size
        call = f"qp_classify({row}, 0, {tv}, ec1_0, ec1_1)" if size == 1 else \
            f"qp_classify({row}, pos{size}, {tv}, ec{size}_0, ep{size}_0)"
        assert call in SOURCE


@pytest.mark.parametrize("tf,gaps,look,pattern", [
    (5, False, False, "PPPPC"), (5, True, False, "nnnnC"), (5, False, True, "CCCCC"), (5, True, True, "Cnnnn"),
    (15, False, False, "P" * 14 + "C"), (15, True, True, "C" + "n" * 14)])
def test_documented_hypotheses(tf, gaps, look, pattern):
    combo = next(c for c in S.COMBOS if c.tf == str(tf) and c.gaps == gaps and c.lookahead == look)
    assert S.hypothesis_pattern(combo) == pattern
    assert S.hypothesis_pattern(S.SAME_TF) == "C"


def test_expected_pine_code_matches_the_independent_python_mirror():
    """The fixture's EXPECTED section, run by this engine, equals the Python mirror on every cell, so a
    mismatch on TradingView is a TradingView semantic, not a bug in the expectation code."""
    result = compile_script(S.expected_core_source())
    assert result.ok, [d.text() for d in result.errors]
    frame = pd.DataFrame({"timestamp": pd.date_range("2026-03-02 23:30", periods=180, freq="1min", tz="UTC"),
                          "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
    out = run_script(PineExecution(result.program, {}), data_context(frame, timeframe_seconds=60, ticker="X",
                     tickerid="X:X", mintick=0.01), ("q4",), "q")
    assert out.error is None
    plots = {o["title"]: [p["value"] for p in o["data"]] for o in out.outputs if o["kind"] == "plot"}
    combos = {"tf1": S.SAME_TF, **{c.key: c for c in S.COMBOS}}
    for key, _, cases in S.groups():
        for index in range(len(cases)):
            for bar, stamp in enumerate(frame["timestamp"]):
                t = int(stamp.timestamp() * 1000)
                expected = (S.expected_at(S.SINGLE[index], t)[0] if key == "single"
                            else S.expected_at(combos[key], t)[index])
                got = plots[f"{key}.{index}"][bar]
                assert (got is None) == (expected is None), (key, index, bar)
                if expected is not None:
                    assert abs(got - expected) <= 1e-9 * max(1.0, abs(expected)), (key, index, bar, got, expected)


def test_contracts_are_documented():
    doc = (S.ROOT / "SECURITY_SEMANTICS.md").read_text()
    for heading in ("## 1. Data policy", "## 2. Timeframe contract", "## 3. Provenance contract",
                    "## 4. Replay contract", "## 5. Live contract", "## 6. Cross-family contract",
                    "## 7. Dependency-slice contract", "## 8. Historical semantics under test"):
        assert heading in doc
    assert "server_utc_offset_seconds_at_capture = 0" in doc and "never" in doc.lower()
    report = H.REPORT.read_text()
    assert "## P2.1 request.security() semantics (historical)" in report
    assert "TradingView result: **PASS**" in report and "**134400 / 134400** cells" in report
