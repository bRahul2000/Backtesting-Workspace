"""P2.1 step 1: a self-checking TradingView script that ESTABLISHES request.security() historical semantics.

Nothing here uses this engine's request.security() (it does not exist yet). The fixture is built so the
expected values are independently knowable inside the chart context:

* every source value is a pure function of ``time`` (``fAt`` / ``gAt``), so the value any requested bar
  would have can be computed from that bar's open time alone;
* the chart context computes, per chart bar, the value of the *current* requested bar (open time Hc) and
  of the *previous* one (Hc - P) with ordinary Pine code (no ``request.*``), including the requested-
  context SMA / EMA / RSI / user function / var state;
* the mapping under test (which requested bar is visible on which chart bar, per gaps / lookahead) is a
  HYPOTHESIS taken from TradingView's documentation. The checker compares ``request.security`` (the value
  under test) with it, and separately records, for every position inside a requested period, which
  requested bar TradingView actually showed (``C`` current, ``P`` previous, ``n`` na). That observed
  pattern establishes the semantics even if the hypothesis is wrong.

Chart: BINANCE:BTCUSDT, 1-minute, historical bars only (the forming bar is excluded).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).parent
QUICK_DIR = ROOT / "quick"
SCRIPT_NAME = "q4_security_historical"
SYMBOL = "BINANCE:BTCUSDT"
CHART_TF = "1"
MINUTE_MS = 60_000

WINDOW = 1200            # historical chart bars checked (20 hours: 240 5m periods, 80 15m periods)
WARMUP = 1500            # chart bars required before the window (15m RSI converges over 90 x 15 = 1350 minutes)
EMA_LEN = 3
RSI_LEN = 3
EMA_DEPTH = 60           # requested bars used to reproduce ta.ema: error <= 0.5^57 of the value range
RSI_DEPTH = 90           # requested bars used to reproduce ta.rsi: error <= (2/3)^87 of the averages
ABS_TOL = 5e-9
REL_TOL = 1e-12
MAX_FAILURES = 10


@dataclass(frozen=True)
class Combo:
    key: str
    period_ms: int
    gaps: bool          # True = barmerge.gaps_on
    lookahead: bool     # True = barmerge.lookahead_on

    @property
    def tf(self) -> str:
        return str(self.period_ms // MINUTE_MS)

    @property
    def label(self) -> str:
        return (f"{self.tf}m gaps_{'on' if self.gaps else 'off'} "
                f"lookahead_{'on' if self.lookahead else 'off'}")


#: requested-context expressions (one tuple per request.security call)
ELEMENTS = (
    ("direct", "fAt(time)"),
    ("hist1", "srcG[1]"),
    ("arith", "fAt(time) * 2 + 7"),
    ("sma3", f"ta.sma(srcG, 3)"),
    ("ema3", f"ta.ema(srcG, {EMA_LEN})"),
    ("rsi3", f"ta.rsi(srcG, {RSI_LEN})"),
    ("udf", "udfDelta(srcG)"),
    ("var", "keepAlt(srcG)"),
    ("hiLike", "fAt(time) + 1.5"),
    ("loLike", "fAt(time) - 2.25"),
    ("closeLike", "gAt(time_close)"),
    ("globalDep", "srcG"),
)

SAME_TF = Combo("tf1", MINUTE_MS, False, False)
COMBOS = tuple(Combo(f"tf{p}_{'gon' if g else 'goff'}_{'lon' if la else 'loff'}", p * MINUTE_MS, g, la)
               for p in (5, 15) for g in (False, True) for la in (False, True))
SINGLE = tuple(c for c in COMBOS if c.period_ms == 5 * MINUTE_MS)     # the same 4 combos, single-value calls


def hypothesis_pattern(combo: Combo) -> str:
    """TradingView's documented historical mapping, per position inside a requested period (0 = first
    chart bar of the period). C = current requested bar, P = previous, n = na."""
    size = combo.period_ms // MINUTE_MS
    if size == 1:
        return "C"
    if not combo.lookahead:
        return ("n" if combo.gaps else "P") * (size - 1) + "C"
    return "C" + ("n" if combo.gaps else "C") * (size - 1)


# ---- Python mirror of the deterministic source and of the expected values (independent of the Pine code) ----

def f_at(t: int) -> float:
    m = t // MINUTE_MS
    return 100.0 + ((m % 997) * 37 % 101) * 0.25


def g_at(t: int) -> float:
    m = t // MINUTE_MS
    return 50.0 + ((m % 991) * 13 % 89) * 0.5


def expected_values(H: int, P: int) -> list[float]:
    """The 12 element values of the requested bar that opens at H (period P ms)."""
    series = [f_at(H - k * P) for k in range(max(EMA_DEPTH, RSI_DEPTH) + 1)][::-1]   # oldest .. newest (H)
    ema_src = series[-(EMA_DEPTH + 1):]
    ema = sum(ema_src[:EMA_LEN]) / EMA_LEN
    for value in ema_src[EMA_LEN:]:
        ema = (2 / (EMA_LEN + 1)) * value + (1 - 2 / (EMA_LEN + 1)) * ema
    rsi_src = series[-(RSI_DEPTH + 1):]
    changes = [b - a for a, b in zip(rsi_src, rsi_src[1:])]
    ups, downs = [max(c, 0.0) for c in changes], [max(-c, 0.0) for c in changes]
    up, down = sum(ups[:RSI_LEN]) / RSI_LEN, sum(downs[:RSI_LEN]) / RSI_LEN
    for u, d in zip(ups[RSI_LEN:], downs[RSI_LEN:]):
        up, down = (u + (RSI_LEN - 1) * up) / RSI_LEN, (d + (RSI_LEN - 1) * down) / RSI_LEN
    rsi = 100.0 if down == 0 else 0.0 if up == 0 else 100.0 - 100.0 / (1.0 + up / down)
    f0, f1, f2 = f_at(H), f_at(H - P), f_at(H - 2 * P)
    keep = next(f_at(H - j * P) for j in range(11) if ((H - j * P) // MINUTE_MS) % 10 < 5)
    return [f0, f1, f0 * 2 + 7, (f0 + f1 + f2) / 3, ema, rsi, f0 - f1, keep, f0 + 1.5, f0 - 2.25, g_at(H + P), f0]


def expected_at(combo: Combo, t: int) -> list[float | None]:
    """Hypothesised request.security() result on the chart bar that opens at t (1-minute chart)."""
    P = combo.period_ms
    Hc = t - t % P
    position = (t - Hc) // MINUTE_MS
    which = hypothesis_pattern(combo)[position]
    if which == "n":
        return [None] * len(ELEMENTS)
    return expected_values(Hc if which == "C" else Hc - P, P)


# ---- Pine generation -------------------------------------------------------------------------------------------

def _num(x: float) -> str:
    return format(Decimal(repr(x)), "f")


def _gaps(c: Combo) -> str:
    return "barmerge.gaps_on" if c.gaps else "barmerge.gaps_off"


def _look(c: Combo) -> str:
    return "barmerge.lookahead_on" if c.lookahead else "barmerge.lookahead_off"


FUNCTIONS = f"""\
// ---- deterministic, time-derived source (identical in the chart and in every requested context) ----
fAt(int t) =>
    int m = int(math.floor(t / 60000))
    100.0 + ((m % 997) * 37 % 101) * 0.25
gAt(int t) =>
    int m = int(math.floor(t / 60000))
    50.0 + ((m % 991) * 13 % 89) * 0.5
udfDelta(float s) => s - s[1]
keepAlt(float s) =>
    var float kept = na
    if int(math.floor(time / 60000)) % 10 < 5
        kept := s
    kept
float srcG = fAt(time)
"""

EXPECTED = f"""\
// ---- EXPECTED VALUES: plain Pine in the chart context; this section never calls request.* ----
// `active` is false outside the checked window, so the EMA / RSI loops only run where values are compared.
expAll(int H, int P, bool active) =>
    float f0 = fAt(H)
    float f1 = fAt(H - P)
    float f2 = fAt(H - 2 * P)
    float ema = na
    float rsi = na
    float keep = na
    if active
        ema := 0.0
        for k = {EMA_DEPTH} to {EMA_DEPTH - EMA_LEN + 1}
            ema += fAt(H - k * P) / {EMA_LEN}
        for k = {EMA_DEPTH - EMA_LEN} to 0
            ema := {_num(2 / (EMA_LEN + 1))} * fAt(H - k * P) + {_num(1 - 2 / (EMA_LEN + 1))} * ema
        float up = 0.0
        float down = 0.0
        for k = {RSI_DEPTH - 1} to {RSI_DEPTH - RSI_LEN}
            float ch = fAt(H - k * P) - fAt(H - (k + 1) * P)
            up += math.max(ch, 0.0) / {RSI_LEN}
            down += math.max(-ch, 0.0) / {RSI_LEN}
        for k = {RSI_DEPTH - RSI_LEN - 1} to 0
            float ch = fAt(H - k * P) - fAt(H - (k + 1) * P)
            up := (math.max(ch, 0.0) + {RSI_LEN - 1} * up) / {RSI_LEN}
            down := (math.max(-ch, 0.0) + {RSI_LEN - 1} * down) / {RSI_LEN}
        rsi := down == 0 ? 100.0 : up == 0 ? 0.0 : 100.0 - 100.0 / (1.0 + up / down)
        for j = 0 to 10
            if na(keep) and int(math.floor((H - j * P) / 60000)) % 10 < 5
                keep := fAt(H - j * P)
    [f0, f1, f0 * 2 + 7, (f0 + f1 + f2) / 3, ema, rsi, f0 - f1, keep, f0 + 1.5, f0 - 2.25, gAt(H + P), f0]
"""


def _expected_block(periods: tuple[int, ...]) -> list[str]:
    """Per period: position inside the requested period and the current / previous requested bar values."""
    lines = []
    for p in periods:
        P = p * MINUTE_MS
        names = ", ".join(f"ec{p}_{i}" for i in range(len(ELEMENTS)))
        prev = ", ".join(f"ep{p}_{i}" for i in range(len(ELEMENTS)))
        lines += [f"int hc{p} = time - time % {P}",
                  f"int pos{p} = int((time - hc{p}) / 60000)",
                  f"[{names}] = expAll(hc{p}, {P}, qp_inWindow)"]
        if p != 1:
            lines.append(f"[{prev}] = expAll(hc{p} - {P}, {P}, qp_inWindow)")
    return lines


def _expected_value(combo: Combo, index: int) -> str:
    """Pine expression for the hypothesised value of element ``index`` under ``combo``."""
    p = combo.period_ms // MINUTE_MS
    if p == 1:
        return f"ec1_{index}"
    cur, prev = f"ec{p}_{index}", f"ep{p}_{index}"
    if not combo.lookahead:
        return f"(pos{p} == {p - 1} ? {cur} : {'na' if combo.gaps else prev})"
    return f"(pos{p} == 0 ? {cur} : {'na' if combo.gaps else cur})"


def groups() -> list[tuple[str, str, list[tuple[str, str, str]]]]:
    """(group key, label, [(case label, value-under-test var, expected expression)])."""
    out = []
    for combo in (SAME_TF,) + COMBOS:
        tag = f"{combo.tf}m" if combo is SAME_TF else \
            f"{combo.tf}m g-{'on' if combo.gaps else 'off'} la-{'on' if combo.lookahead else 'off'}"
        cases = [(f"{tag} {name}", f"r_{combo.key}_{i}", _expected_value(combo, i))
                 for i, (name, _) in enumerate(ELEMENTS)]
        out.append((combo.key, combo.label if combo is not SAME_TF else "1m same timeframe", cases))
    out.append(("single", "5m single-value calls (4 combos)",
                [(f"single {c.label}", f"s_{c.key}", _expected_value(c, 0)) for c in SINGLE]))
    return out


def under_test_block() -> list[str]:
    lines = ["// ---- VALUES UNDER TEST: request.security() (the only request.* calls in this script) ----"]
    tuple_expr = "[" + ", ".join(expr for _, expr in ELEMENTS) + "]"
    for combo in (SAME_TF,) + COMBOS:
        names = ", ".join(f"r_{combo.key}_{i}" for i in range(len(ELEMENTS)))
        lines.append(f'[{names}] = request.security(syminfo.tickerid, "{combo.tf}", {tuple_expr}, '
                     f"gaps={_gaps(combo)}, lookahead={_look(combo)})")
    for combo in SINGLE:
        lines.append(f'float s_{combo.key} = request.security(syminfo.tickerid, "{combo.tf}", fAt(time), '
                     f"gaps={_gaps(combo)}, lookahead={_look(combo)})")
    return lines


def pattern_rows() -> list[tuple[str, str, str, int]]:
    """(row label, value-under-test var, hypothesis pattern, period minutes) for the timing evidence rows."""
    rows = [("1m same tf (tuple direct)", f"r_{SAME_TF.key}_0", hypothesis_pattern(SAME_TF), 1)]
    rows += [(f"{c.label} (tuple direct)", f"r_{c.key}_0", hypothesis_pattern(c), c.period_ms // MINUTE_MS)
             for c in COMBOS]
    rows += [(f"{c.label} (single call)", f"s_{c.key}", hypothesis_pattern(c), c.period_ms // MINUTE_MS)
             for c in SINGLE]
    return rows


def source() -> str:
    g = groups()
    n = len(g)
    rows = pattern_rows()
    out = [
        "//@version=6",
        "// Pine P2.1 parity - request.security() HISTORICAL semantics. Generated by",
        "// `python -m ui.tradingview_mode.pine.parity` (security_fixture.py) - do not edit.",
        f"// Add to {SYMBOL} on the 1-minute chart. Every value derives from `time`, so the chart can compute",
        "// the value of any requested bar itself; request.security() is only the value under test.",
        f'indicator("parity q4 request.security historical", overlay=true)',
        FUNCTIONS.rstrip("\n"),
        *under_test_block(),
        EXPECTED.rstrip("\n"),
        "// ---- checker (TradingView only) ----",
        'bool qp_inject = input.bool(false, "Self-test: corrupt one expected value (must FAIL)")',
        f"int QP_WINDOW = {WINDOW}",
        f"int QP_WARMUP = {WARMUP}",
        f"float QP_ABS = {_num(ABS_TOL)}",
        f"float QP_REL = {_num(REL_TOL)}",
        "bool qp_chartOk = timeframe.period == \"1\"",
        "bool qp_inWindow = not barstate.isrealtime and bar_index >= last_bar_index - QP_WINDOW and bar_index <= last_bar_index - 1",
        "bool qp_inLookback = not barstate.isrealtime and bar_index >= last_bar_index - QP_WINDOW - QP_WARMUP and bar_index <= last_bar_index - 1",
        "var int qp_gaps = 0",
        "if qp_inLookback and bar_index > 0 and time - time[1] != 60000",
        "    qp_gaps += 1",
        f"var array<int> qp_count = array.new<int>({n}, 0)",
        f"var array<int> qp_fail = array.new<int>({n}, 0)",
        f"var array<float> qp_maxdiff = array.new<float>({n}, 0.0)",
        "var array<string> qp_ftime = array.new<string>()",
        "var array<string> qp_fcase = array.new<string>()",
        "var array<string> qp_ftv = array.new<string>()",
        "var array<string> qp_fexp = array.new<string>()",
        "var array<string> qp_fdiff = array.new<string>()",
        'qp_text(float value) => na(value) ? "na" : str.tostring(value, "0.##########")',
        "qp_same(float tv, float expected) =>",
        "    (na(tv) and na(expected)) or (not na(tv) and not na(expected) and math.abs(tv - expected) <= QP_ABS + QP_REL * math.abs(expected))",
        "qp_check(int grp, string label, float tv, float expectedIn) =>",
        "    float expected = expectedIn",
        "    if qp_inject and grp == 0 and array.get(qp_count, 0) == 0",
        "        expected := nz(expected) + 0.001",
        "    bool ok = qp_same(tv, expected)",
        "    array.set(qp_count, grp, array.get(qp_count, grp) + 1)",
        "    if not na(tv) and not na(expected)",
        "        array.set(qp_maxdiff, grp, math.max(array.get(qp_maxdiff, grp), math.abs(tv - expected)))",
        "    if not ok",
        "        array.set(qp_fail, grp, array.get(qp_fail, grp) + 1)",
        f"        if array.size(qp_ftime) < {MAX_FAILURES}",
        '            array.push(qp_ftime, str.format_time(time, "yyyy-MM-dd HH:mm", "UTC"))',
        "            array.push(qp_fcase, label)",
        "            array.push(qp_ftv, qp_text(tv))",
        "            array.push(qp_fexp, qp_text(expected))",
        '            array.push(qp_fdiff, na(tv) or na(expected) ? "na vs value" : qp_text(math.abs(tv - expected)))',
        "    ok",
        # observed timing: counts per (row, position, category)
        f"var array<int> qp_pat = array.new<int>({len(rows)} * 15 * 4, 0)",
        "qp_classify(int row, int pos, float tv, float cur, float prev) =>",
        "    if not (not na(tv) and not na(cur) and not na(prev) and cur == prev)",
        "        int cat = na(tv) ? 2 : qp_same(tv, cur) ? 0 : qp_same(tv, prev) ? 1 : 3",
        "        int slot = (row * 15 + pos) * 4 + cat",
        "        array.set(qp_pat, slot, array.get(qp_pat, slot) + 1)",
        "qp_pattern(int row, int size) =>",
        '    string s = ""',
        "    for pos = 0 to size - 1",
        "        int c0 = array.get(qp_pat, (row * 15 + pos) * 4)",
        "        int c1 = array.get(qp_pat, (row * 15 + pos) * 4 + 1)",
        "        int c2 = array.get(qp_pat, (row * 15 + pos) * 4 + 2)",
        "        int c3 = array.get(qp_pat, (row * 15 + pos) * 4 + 3)",
        "        int total = c0 + c1 + c2 + c3",
        '        s += total == 0 ? "-" : c0 == total ? "C" : c1 == total ? "P" : c2 == total ? "n" : c3 == total ? "?" : "*"',
        "    s",
    ]
    out += _expected_block((1, 5, 15))
    out.append("if qp_inWindow and qp_chartOk")
    for index, (_, _, cases) in enumerate(g):
        for label, tv, expected in cases:
            out.append(f'    qp_check({index}, "{label}", {tv}, {expected})')
    for row, (_, tv, _, size) in enumerate(rows):
        if size == 1:
            out.append(f"    qp_classify({row}, 0, {tv}, ec1_0, ec1_1)")
        else:
            out.append(f"    qp_classify({row}, pos{size}, {tv}, ec{size}_0, ep{size}_0)")
    cells = {key: len(cases) * WINDOW for key, _, cases in g}
    table_rows = 4 + n + 1 + 2 + len(rows) + 2 + 2 + MAX_FAILURES
    out += [
        f"var table qp_table = table.new(position.top_right, 6, {table_rows}, bgcolor=color.white, "
        "border_color=color.gray, border_width=1, frame_color=color.gray, frame_width=1)",
        "qp_put(int col, int row, string txt, color bg) =>",
        "    table.cell(qp_table, col, row, txt, text_color=color.black, bgcolor=bg, text_size=size.small)",
        "if barstate.islast",
        '    qp_put(0, 0, "PINE P2.1 REQUEST.SECURITY - HISTORICAL SEMANTICS" + (qp_inject ? " - SELF-TEST (1 failure expected)" : ""), color.white)',
        "    table.merge_cells(qp_table, 0, 0, 5, 0)",
        f'    qp_put(0, 1, qp_chartOk ? "chart ok: " + syminfo.tickerid + " 1m · window " + str.tostring(QP_WINDOW) + " bars · data gaps " + str.tostring(qp_gaps) + (bar_index - QP_WINDOW < QP_WARMUP ? " · NOT ENOUGH HISTORY" : "") : "WRONG CHART: use {SYMBOL} on the 1-minute timeframe", qp_chartOk and qp_gaps == 0 ? color.white : color.red)',
        "    table.merge_cells(qp_table, 0, 1, 5, 1)",
        '    qp_put(0, 2, "case", color.silver)',
        '    qp_put(1, 2, "cells expected", color.silver)',
        '    qp_put(2, 2, "checked", color.silver)',
        '    qp_put(3, 2, "failed", color.silver)',
        '    qp_put(4, 2, "max diff", color.silver)',
        '    qp_put(5, 2, "RESULT", color.silver)',
        "    int qp_allFail = 0",
        "    bool qp_complete = qp_chartOk and qp_gaps == 0 and bar_index - QP_WINDOW >= QP_WARMUP",
    ]
    for index, (key, label, _) in enumerate(g):
        row = 3 + index
        expected_cells = cells[key]
        out += [
            f"    int qp_c{index} = array.get(qp_count, {index})",
            f"    int qp_f{index} = array.get(qp_fail, {index})",
            f"    bool qp_ok{index} = qp_f{index} == 0 and qp_c{index} == {expected_cells}",
            f"    qp_allFail += qp_f{index}",
            f"    qp_complete := qp_complete and qp_c{index} == {expected_cells}",
            f'    qp_put(0, {row}, "{label}", color.white)',
            f'    qp_put(1, {row}, "{expected_cells}", color.white)',
            f"    qp_put(2, {row}, str.tostring(qp_c{index}), color.white)",
            f"    qp_put(3, {row}, str.tostring(qp_f{index}), color.white)",
            f"    qp_put(4, {row}, qp_text(array.get(qp_maxdiff, {index})), color.white)",
            f'    qp_put(5, {row}, qp_ok{index} ? "PASS" : qp_c{index} < {expected_cells} ? "INCOMPLETE" : "FAIL", '
            f"qp_ok{index} ? color.lime : color.red)",
        ]
    row = 3 + n
    out += [
        f'    qp_put(0, {row}, "ALL", color.silver)',
        f'    qp_put(1, {row}, "{sum(cells.values())}", color.silver)',
        f"    qp_put(3, {row}, str.tostring(qp_allFail), color.silver)",
        f'    qp_put(5, {row}, qp_allFail == 0 and qp_complete ? "PASS" : "FAIL", qp_allFail == 0 and qp_complete ? color.lime : color.red)',
        f'    qp_put(0, {row + 1}, "KEY SEMANTICS - which requested bar is visible at each position of the requested period '
        f'(0 = first chart bar of the period). C current, P previous, n na, * mixed, - not seen", color.silver)',
        f"    table.merge_cells(qp_table, 0, {row + 1}, 5, {row + 1})",
        f'    qp_put(0, {row + 2}, "mapping", color.silver)',
        f"    table.merge_cells(qp_table, 0, {row + 2}, 2, {row + 2})",
        f'    qp_put(3, {row + 2}, "observed on TradingView", color.silver)',
        f'    qp_put(4, {row + 2}, "documented hypothesis", color.silver)',
        f'    qp_put(5, {row + 2}, "same?", color.silver)',
    ]
    for index, (label, _, pattern, size) in enumerate(rows):
        r = row + 3 + index
        out += [
            f"    string qp_obs{index} = qp_pattern({index}, {size})",
            f'    qp_put(0, {r}, "{label}", color.white)',
            f"    table.merge_cells(qp_table, 0, {r}, 2, {r})",
            f"    qp_put(3, {r}, qp_obs{index}, color.white)",
            f'    qp_put(4, {r}, "{pattern}", color.white)',
            f'    qp_put(5, {r}, qp_obs{index} == "{pattern}" ? "same" : "DIFFERENT", qp_obs{index} == "{pattern}" ? color.white : color.red)',
        ]
    r = row + 3 + len(rows)
    out += [
        f'    qp_put(0, {r}, array.size(qp_ftime) == 0 ? "no failures" : "FIRST FAILURES", color.silver)',
        f"    table.merge_cells(qp_table, 0, {r}, 5, {r})",
        f'    qp_put(0, {r + 1}, "chart time (UTC)", color.silver)',
        f'    qp_put(1, {r + 1}, "case", color.silver)',
        f'    qp_put(2, {r + 1}, "TV", color.silver)',
        f'    qp_put(3, {r + 1}, "expected", color.silver)',
        f'    qp_put(4, {r + 1}, "diff", color.silver)',
        "    for qp_j = 0 to array.size(qp_ftime) - 1",
        "        if array.size(qp_ftime) > 0",
        f"            qp_put(0, {r + 2} + qp_j, array.get(qp_ftime, qp_j), color.white)",
        f"            qp_put(1, {r + 2} + qp_j, array.get(qp_fcase, qp_j), color.white)",
        f"            qp_put(2, {r + 2} + qp_j, array.get(qp_ftv, qp_j), color.white)",
        f"            qp_put(3, {r + 2} + qp_j, array.get(qp_fexp, qp_j), color.white)",
        f"            qp_put(4, {r + 2} + qp_j, array.get(qp_fdiff, qp_j), color.white)",
        'plot(bar_index, "bi", display=display.data_window)',
    ]
    return "\n".join(out) + "\n"


def expected_core_source() -> str:
    """The script's EXPECTED section alone, with plots, so this engine can verify it against the Python mirror
    (no request.*, no arrays, no tables)."""
    plots = []
    for key, _, cases in groups():
        for index, (label, _, expected) in enumerate(cases):
            plots.append(f'plot({expected}, "{key}.{index}")')
    return ("//@version=6\nindicator(\"q4 expected core\")\n" + FUNCTIONS + EXPECTED + "bool qp_inWindow = true\n"
            + "\n".join(_expected_block((1, 5, 15))) + "\n" + "\n".join(plots) + "\n")


def write() -> Path:
    QUICK_DIR.mkdir(exist_ok=True)
    path = QUICK_DIR / f"{SCRIPT_NAME}.pine"
    path.write_text(source())
    return path


# ---- engine parity: this engine's request.security() against the frozen q4 oracle --------------------------------

ENGINE_HISTORY = 240          # requested bars available before the chart's first bar (EMA/RSI convergence)


def engine_core_source() -> str:
    """The q4 calculations and request.security() calls, with plots instead of the TradingView checker."""
    plots = [f'plot(r_{c.key}_{i}, "r_{c.key}_{i}")' for c in (SAME_TF,) + COMBOS for i in range(len(ELEMENTS))]
    plots += [f'plot(s_{c.key}, "s_{c.key}")' for c in SINGLE]
    return ("//@version=6\nindicator(\"q4 engine core\")\n" + FUNCTIONS + "\n".join(under_test_block()) + "\n"
            + "\n".join(plots) + "\n")


class TimeGridProvider:
    """A deterministic provider for the q4 fixture: 24/7 bars on a UTC grid (their prices are irrelevant - every
    q4 value derives from ``time``)."""

    family = "binance"

    def __init__(self, first_ms: int, last_ms: int):
        self.first_ms, self.last_ms = first_ms, last_ms

    def request(self, symbol, timeframe, *, parent_tickerid, parent_seconds, knowable, until_ms, chart_end_ms):
        import numpy as np

        from ..security import Bars, BarGrid, Requested

        grid = BarGrid(timeframe)
        size = timeframe.seconds * 1000
        first = grid.bucket(self.first_ms)[0] - ENGINE_HISTORY * size
        opens = np.arange(first, grid.bucket(chart_end_ms)[0] + 1, size, dtype=np.int64)
        closes = opens + size
        if knowable and until_ms is not None:
            keep = closes <= until_ms
            opens, closes = opens[keep], closes[keep]
        values = np.array([f_at(int(t)) for t in opens])
        bars = Bars(opens, closes, values, values, values, values, np.ones(len(opens)))
        return Requested(bars, grid, "BTCUSDT", SYMBOL, {
            "provider_family": "binance", "provider": "q4 time grid (test)", "native": True,
            "aggregation_base": None, "data_identity": f"q4-time-grid:{timeframe.text}", "fingerprint": None})


def engine_parity() -> dict:
    """Run this engine on the q4 fixture (1-minute chart, WARMUP + WINDOW bars) and compare every checked cell
    with the TradingView-confirmed mapping (q4: 134,400 / 134,400 on real TradingView)."""
    import pandas as pd

    from .. import PineExecution, compile_script, run_script
    from ..engine import data_context

    start = pd.Timestamp("2026-03-02 00:00", tz="UTC")
    n = WARMUP + WINDOW + 1                         # the last bar stands in for q4's excluded forming bar
    frame = pd.DataFrame({"timestamp": pd.date_range(start, periods=n, freq="1min", tz="UTC"),
                          "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0})
    times = [int(t.timestamp() * 1000) for t in frame["timestamp"]]
    result = compile_script(engine_core_source())
    if not result.ok:
        raise RuntimeError([d.text() for d in result.errors])
    provider = TimeGridProvider(times[0], times[-1])
    data = data_context(frame, timeframe_seconds=60, ticker="BTCUSDT", tickerid=SYMBOL, mintick=0.1)
    run = run_script(PineExecution(result.program, {}, provider), data, ("q4",), "q4")
    if run.error:
        raise RuntimeError(run.error)
    series = {o["title"]: [p["value"] for p in o["data"]] for o in run.outputs if o["kind"] == "plot"}
    window = range(n - 1 - WINDOW, n - 1)
    combos = {"tf1": SAME_TF, **{c.key: c for c in COMBOS}}
    report = {"cells": 0, "matched": 0, "by_group": {}, "first_mismatches": [], "contexts": len(run.contexts)}
    for key, _, cases in groups():
        checked = matched = 0
        for index, (label, tested, _) in enumerate(cases):
            values = series[tested]
            for bar in window:
                expected = (expected_at(SINGLE[index], times[bar])[0] if key == "single"
                            else expected_at(combos[key], times[bar])[index])
                got = values[bar]
                ok = (got is None and expected is None) or (got is not None and expected is not None and
                                                            abs(got - expected) <= ABS_TOL + REL_TOL * abs(expected))
                checked += 1
                matched += ok
                if not ok and len(report["first_mismatches"]) < 10:
                    report["first_mismatches"].append((times[bar], label, got, expected))
        report["by_group"][key] = (matched, checked)
        report["cells"] += checked
        report["matched"] += matched
    return report
