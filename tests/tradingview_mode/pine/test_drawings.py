"""P2.3a drawing-object core (line, label, box, linefill): the frozen TradingView observations of
P23_DRAWING_RESEARCH.md (m07, q8 Cases 0-7, q8g revisions 3-4, q8c, q8e, CE10128, RE10020) reproduced through the
engine. The q8 / q8g oracle scripts themselves need arrays of drawing IDs and `*.all` (P2.3b), so their observations
are checked here at store / runtime / analyzer level; full-script parity is a P2.3b requirement.
"""
import hashlib
from pathlib import Path

import pandas as pd
import pytest

from ui.tradingview_mode.component import protocol
from ui.tradingview_mode.pine import PineExecution, compile_script, run_script
from ui.tradingview_mode.pine.drawings import DrawingStore
from ui.tradingview_mode.pine.errors import ERROR
from ui.tradingview_mode.pine.values import DrawingRef

from .helpers import bars, context, plots, run

PARITY = Path("ui/tradingview_mode/pine/parity")
V6 = '//@version=6\nindicator("t", overlay=true{extra})\n'


def src(body: str, extra: str = "", version: int = 6) -> str:
    return V6.replace("6", str(version), 1).format(extra=extra) + body.strip("\n") + "\n"


def execute(body: str, n: int = 12, extra: str = "", version: int = 6):
    result = compile_script(src(body, extra, version))
    assert result.ok, [d.text() for d in result.diagnostics]
    execution = PineExecution(result.program, {})
    out = run_script(execution, context(bars(n)), ("t",), "t")
    return out, execution


def last(body: str, n: int = 12, extra: str = "", version: int = 6) -> dict:
    out, _ = execute(body, n, extra, version)
    assert out.error is None, out.error
    return {k: v[-1] for k, v in plots(out).items()}


def errors(body: str) -> list[str]:
    return [d.message for d in compile_script(src(body)).diagnostics if d.kind == ERROR]


def failure(body: str, n: int = 6):
    out, _ = execute(body, n)
    return out.error


# ---- identity, aliasing, copy, history (q8 Case 0, Case 5, q8e) --------------------------------------------------------

def test_equality_is_identity_q8e():
    p = last("""
a = line.new(bar_index, 1.0, bar_index + 1, 1.0)
b = a
c = line.copy(a)
plot(a == b ? 1 : 0, "eq")
plot(a == c ? 1 : 0, "copyEq")
plot(a != c ? 1 : 0, "copyNe")
""")
    assert (p["eq"], p["copyEq"], p["copyNe"]) == (1, 0, 1)
    assert DrawingRef("line", 3) == DrawingRef("line", 3) and DrawingRef("line", 3) != DrawingRef("label", 3)


def test_alias_mutation_and_independent_copy_q8_case0():
    p = last("""
al = line.new(bar_index, 1.0, bar_index + 1, 1.0)
al2 = al
line.set_y1(al2, 55)
cp = line.copy(al)
line.set_y1(cp, 77)
plot(line.get_y1(al), "orig")
plot(line.get_y1(cp), "copy")
""")
    assert (p["orig"], p["copy"]) == (55, 77)


def test_history_holds_ids_resolved_live_and_mutable_q8_cases_0_5():
    p = last("""
var line h = line.new(0, 0.0, 1, 0.0)
line.set_y2(h, bar_index)
p = line.new(bar_index, 0.0, bar_index + 1, 1.0)
plot(line.get_y2(h[1]), "hLive")
plot(line.get_x1(p[1]), "pPrev")
line.set_y1(p[1], 5)
plot(line.get_y1(p[1]), "setThroughHistory")
""", n=20, extra=", max_lines_count=500")
    assert p["hLive"] == 19 and p["pPrev"] == 18 and p["setThroughHistory"] == 5


# ---- delete and dead IDs (q8 Cases 0-3, q8g r4) --------------------------------------------------------------------------

def test_deleted_ids_read_na_setters_and_deletes_are_no_ops():
    p = last("""
x = line.new(bar_index, 4.0, bar_index + 1, 4.0)
line.delete(x)
plot(line.get_y1(x), "get")
line.delete(x)
line.set_y1(x, 5)
plot(line.get_y1(x), "afterSet")
plot(na(x) ? 1 : 0, "na")
line nl = na
line.delete(nl)
plot(1, "deleteNa")
""")
    assert p["get"] is None and p["afterSet"] is None and p["na"] == 1 and p["deleteNa"] == 1


def test_copy_of_a_dead_id_is_na_engine_policy():
    p = last("""
x = label.new(bar_index, 1.0, "x")
label.delete(x)
c = label.copy(x)
plot(na(c) ? 1 : 0, "copyNa")
""")
    assert p["copyNa"] == 1


# ---- garbage collection: roots and eviction (q8g r3 / r4, q8 Case 0) ------------------------------------------------------

def test_unreferenced_objects_are_evicted_oldest_created_first_q8g_r3():
    body = """
int n = bar_index + 1
int x = 100 + (n % 2 == 0 ? n : -n)
label.new(x, 1.0, "U" + str.tostring(n))
plot(0)
"""
    out, execution = execute(body, n=40, extra=", max_labels_count=5")
    store = execution.runtime.drawings
    texts = [d.props["text"] for d in store.objects() if d.kind == "label"]
    assert texts == ["U36", "U37", "U38", "U39", "U40"]            # creation order decides, not the x position


def test_a_scalar_var_root_survives_while_old_unreferenced_objects_go_q8g_r3():
    body = """
var box firstBox = box.new(0, 1000.0, 1, 999.0)
box.new(bar_index, 100.0 + bar_index, bar_index + 1, 99.0 + bar_index)
plot(box.get_top(firstBox), "first")
"""
    out, execution = execute(body, n=40, extra=", max_boxes_count=5")
    tops = [d.props["top"] for d in execution.runtime.drawings.objects()]
    assert tops == [1000.0, 136.0, 137.0, 138.0, 139.0] and plots(out)["first"][-1] == 1000.0     # first + B37..B40


def test_ids_held_elsewhere_do_not_protect_and_a_collected_id_behaves_as_deleted_q8g_r4():
    p = last("""
r = line.new(bar_index, bar_index + 1.0, bar_index + 1, bar_index + 1.0)
dead = r[39]
plot(na(dead) ? 1 : 0, "na")
plot(line.get_y1(dead), "get")
line.set_y1(dead, 999)
plot(line.get_y1(dead), "afterSet")
line.delete(dead)
plot(line.get_y1(r[1]), "neighbour")
""", n=40, extra=", max_lines_count=5")
    assert (p["na"], p["get"], p["afterSet"], p["neighbour"]) == (1, None, None, 39)


def test_roots_are_kept_above_the_limit():
    body = """
var line a = line.new(0, 1.0, 1, 1.0)
var line b = line.new(0, 2.0, 1, 2.0)
var line c = line.new(0, 3.0, 1, 3.0)
line.new(bar_index, 9.0, bar_index + 1, 9.0)
plot(0)
"""
    _, execution = execute(body, n=10, extra=", max_lines_count=2")
    ys = [d.props["y1"] for d in execution.runtime.drawings.objects()]
    assert ys == [1.0, 2.0, 3.0, 9.0]              # 3 roots kept (limit 2); the newest is not evicted by its creation


def test_store_level_eviction_ignores_non_roots_and_default_limit():
    store = DrawingStore(roots=lambda: {1})
    refs = [store.create("label", {"text": str(i)}, 0) for i in range(60)]
    assert store.limits["label"] == 50 and len(store.order["label"]) == 50
    assert store.alive(refs[0]) and not store.alive(refs[1]) and store.alive(refs[-1])


def test_declared_limits_are_read_from_indicator():
    _, execution = execute("plot(0)", extra=", max_lines_count=7, max_labels_count=600")
    assert execution.runtime.drawings.limits == {"line": 7, "label": 500, "box": 50}


# ---- linefill (manual; q8 Case 4) -------------------------------------------------------------------------------------------

def test_linefill_replacement_and_cascade():
    p = last("""
l1 = line.new(bar_index, 2.0, bar_index + 1, 2.0)
l2 = line.new(bar_index, 3.0, bar_index + 1, 3.0)
f1 = linefill.new(l1, l2, color.red)
f2 = linefill.new(l2, l1, color.blue)
plot(na(f1) ? 1 : 0, "firstReplaced")
plot(line.get_y1(linefill.get_line1(f2)), "line1")
line.delete(l2)
plot(na(f2) ? 1 : 0, "cascade")
plot(na(linefill.get_line1(f2)) ? 1 : 0, "getLine1Na")
""")
    assert (p["firstReplaced"], p["line1"], p["cascade"], p["getLine1Na"]) == (1, 3.0, 1, 1)


# ---- realtime rollback and commit (m07) ---------------------------------------------------------------------------------------

class LiveChart:
    """A live chart: confirmed bars, then realtime ticks on a forming bar (the real PineExecution path)."""

    def __init__(self, source: str, history: int = 8):
        self.program = compile_script(source).program
        self.frame = bars(history + 10, seed=5)
        self.n = history + 1
        self.execution = PineExecution(self.program, {})
        self.price = 100.0

    def _run(self):
        out = run_script(self.execution, context(self.frame.iloc[:self.n], forming_last=True), ("live",), "t")
        assert out.error is None, out.error
        return {k: v[-1] for k, v in plots(out).items()}

    @property
    def store(self):
        return self.execution.runtime.drawings

    def tick(self):
        self.price += 0.5
        self.frame.loc[self.n - 1, "close"] = self.price
        return self._run()

    def new_bar(self):
        self.n += 1
        return self._run()


M07 = src("""
varip int execs = 0
if barstate.isrealtime
    execs += 1
var line lineA = line.new(0, 0.0, 1, 0.0)
var label labelR = label.new(0, 0.0, "0")
var box boxD = box.new(0, 1.0, 1, 0.0)
float aBefore = line.get_y2(lineA)
string rBefore = label.get_text(labelR)
bool dBefore = not na(boxD)
if barstate.isrealtime
    line.set_y2(lineA, execs)
    line n = line.new(bar_index, close, bar_index + 1, close)
    n := line.new(bar_index, open, bar_index + 1, open)
    labelR := label.new(bar_index, close, str.tostring(execs))
    box.delete(boxD)
plot(aBefore, "A")
plot(str.tonumber(rBefore), "R")
plot(dBefore ? 1 : 0, "D")
""", ", max_lines_count=500, max_labels_count=500, max_boxes_count=500")


def test_m07_every_open_bar_change_rolls_back_and_the_final_execution_commits():
    live = LiveChart(M07)
    first = live._run()                                          # tick 1 of the forming bar
    counts = lambda: {k: len(v) for k, v in live.store.order.items()}                      # noqa: E731
    assert (first["A"], first["R"], first["D"]) == (0, 0, 1)
    assert counts() == {"line": 3, "label": 2, "box": 0, "linefill": 0}                    # state after tick 1
    oids = sorted(live.store.live)
    second = live.tick()                                         # tick 2: everything from tick 1 was rolled back
    assert (second["A"], second["R"], second["D"]) == (0, 0, 1)
    assert counts() == {"line": 3, "label": 2, "box": 0, "linefill": 0}
    assert sorted(live.store.live) == oids                       # the ID counter rolled back: same IDs each tick
    third = live.new_bar()                                       # the previous bar's final execution (exec 2) commits
    assert (third["A"], third["R"], third["D"]) == (2, 2, 0)


def test_incremental_ticks_equal_a_fresh_run_on_the_same_bars():
    source = src("""
var line trend = line.new(bar_index, close, bar_index, close)
line.set_xy2(trend, bar_index, close)
label.new(bar_index, high, str.tostring(close))
if close > open
    box.new(bar_index, high, bar_index + 1, low)
plot(0)
""", ", max_labels_count=4, max_boxes_count=3")
    live = LiveChart(source)
    live._run()
    for _ in range(4):
        live.tick()
    live.new_bar()
    live.tick()
    fresh = PineExecution(live.program, {})
    run_script(fresh, context(live.frame.iloc[:live.n], forming_last=True), ("live",), "t")
    snapshot = lambda store: [(d.kind, d.oid, d.props, d.created_bar) for d in store.objects()]   # noqa: E731
    assert snapshot(fresh.runtime.drawings) == snapshot(live.store)


def test_realtime_garbage_collection_is_rolled_back():
    source = src("""
if barstate.isrealtime
    label.new(bar_index, close, "rt")
else
    label.new(bar_index, close, str.tostring(bar_index))
plot(0)
""", ", max_labels_count=3")
    live = LiveChart(source)
    committed_before = None
    live._run()
    after_first = [d.props["text"] for d in live.store.objects()]
    for _ in range(3):
        live.tick()
        assert [d.props["text"] for d in live.store.objects()] == after_first    # evictions of each tick undone
    committed_before = after_first
    assert committed_before[-1] == "rt" and len(committed_before) == 3


# ---- analyzer rules (CE10128, CE10175) and functions ----------------------------------------------------------------------

@pytest.mark.parametrize("decl,kind", [("varip line x = na", "line"), ("varip x = label.new(0, 1.0)", "label"),
                                       ("varip box b = na", "box"), ("varip linefill f = na", "linefill")])
def test_varip_drawing_variables_are_rejected_ce10128(decl, kind):
    assert f'Variables with varip modifier cannot have type "series {kind}".' in errors(decl + "\nplot(0)")


def test_drawing_parameters_cannot_be_rebound_ce10175_but_may_mutate():
    assert "Function arguments cannot be mutable (`l`)." in errors(
        "f(line l) =>\n    l := line.new(bar_index, 2.0, bar_index + 1, 2.0)\n    l\nplot(0)")
    p = last("""
mkBox(float y) =>
    var box bx = box.new(0, y + 1, 1, y)
    bx
setTop(box b, float v) =>
    box.set_top(b, v)
    b
b1 = mkBox(10.0)
b2 = mkBox(20.0)
r = setTop(b1, 99.0)
plot(box.get_top(b1), "b1")
plot(box.get_top(r), "ret")
plot(box.get_top(b2), "b2")
""")
    assert (p["b1"], p["ret"], p["b2"]) == (99, 99, 21)


def test_function_local_var_drawings_are_per_call_site():
    _, execution = execute("""
mkBox(float y) =>
    var box bx = box.new(0, y + 1, 1, y)
    bx
b1 = mkBox(10.0)
b2 = mkBox(20.0)
plot(0)
""")
    assert len(execution.runtime.drawings.order["box"]) == 2


# ---- coordinates and get_price ------------------------------------------------------------------------------------------------

def test_future_limit_re10020_and_past_limit():
    assert failure("line.new(bar_index, close, bar_index + 501, close)\nplot(0)")["message"] == \
        "Objects positioned using xloc.bar_index cannot be drawn further than 500 bars into the future."
    assert failure("line.new(bar_index, close, bar_index + 500, close)\nplot(0)") is None
    assert failure("label.new(bar_index - 10001, close)\nplot(0)")["message"] == \
        "Objects positioned using xloc.bar_index cannot be drawn further than 10000 bars into the past."
    error = failure("l = line.new(bar_index, close, bar_index + 1, close)\nline.set_x2(l, bar_index + 600)\nplot(0)")
    assert error["message"].startswith("Objects positioned") and error["line"] == 4


def test_get_price_extrapolates_bar_index_lines_and_rejects_bar_time_lines():
    p = last("""
l = line.new(10, 1.0, 20, 2.0)
plot(line.get_price(l, 15), "mid")
plot(line.get_price(l, 30), "beyond")
plot(line.get_price(l, 0), "before")
""")
    assert (p["mid"], p["beyond"], p["before"]) == (1.5, 3.0, 0.0)
    error = failure("l = line.new(time, 1.0, time + 60000, 2.0, xloc = xloc.bar_time)\nplot(line.get_price(l, 3))")
    assert "works only for lines with `xloc.bar_index`" in error["message"]


# ---- method syntax ----------------------------------------------------------------------------------------------------------------

def test_methods_on_typed_drawings_and_unknown_receivers():
    p = last("""
l = line.new(bar_index, 1.0, bar_index + 1, 1.0)
l.set_y1(7)
lb = label.new(bar_index, 1.0, "a")
lb.set_text("b")
bx = box.new(bar_index, 2.0, bar_index + 1, 1.0)
bx.set_top(5)
mkLine() => line.new(bar_index, 3.0, bar_index + 1, 3.0)
mkArray() => array.from(1, 2, 3)
c = mkLine().copy()
a = mkArray().copy()
plot(l.get_y1(), "y1")
plot(box.get_top(bx), "top")
plot(line.get_y1(c), "lineCopy")
plot(a.size(), "arrayCopy")
plot(array.copy(array.from(4)).size() + line.get_y1(line.copy(l)), "explicit")
""")
    assert (p["y1"], p["top"], p["lineCopy"], p["arrayCopy"], p["explicit"]) == (7, 5, 3, 3, 8)


def test_unknown_receiver_na_and_scalars():
    error = failure("f(x) => x.copy()\nplot(na(f(na)) ? 1 : 0)")
    assert error["message"].startswith("Cannot call method `copy()` on an na value of unknown type")
    error = failure("f(x) => x.copy()\nplot(na(f(close)) ? 1 : 0)")
    assert error["message"] == "Cannot call method `copy()` on a `float` value."
    assert "Could not find method `copy()` for a `float` value." in errors("x = close\nplot(x.copy())")
    dead = last("f(x) => x.copy()\nl = line.new(bar_index, 1.0, bar_index + 1, 1.0)\nline.delete(l)\n"
                "plot(na(f(l)) ? 1 : 0, 'deadCopy')")
    assert dead["deadCopy"] == 1                                   # a dead ref keeps its kind: line.copy -> na
    assert "Could not find method `set_x1()` for `label` objects." in errors(
        "lb = label.new(bar_index, 1.0)\nlb.set_x1(3)\nplot(0)")


# ---- request.security, Replay, payload -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    'plot(request.security(syminfo.tickerid, "60", line.get_y1(line.new(bar_index, close, bar_index + 1, close))))',
    'f() =>\n    label.new(bar_index, close)\n    close\nplot(request.security(syminfo.tickerid, "60", f()))',
    'v = line.get_y1(line.new(bar_index, close, bar_index + 1, close))\nplot(request.security(syminfo.tickerid, "60", v))',
    'x = request.security(syminfo.tickerid, "60", line.new(bar_index, close, bar_index + 1, close))\nplot(0)',
])
def test_drawings_never_run_in_requested_contexts(body):
    assert not compile_script(src(body)).ok


def test_render_payload_keeps_raw_coordinates_and_label_defaults_by_version():
    body = """
if barstate.islast
    line.new(bar_index - 2, 1.0, bar_index + 3, 2.0, extend = extend.right, style = line.style_dashed)
    line.new(time, 1.0, time + 60000, 1.5, xloc = xloc.bar_time)
    label.new(bar_index, 1.0, "L")
    b = box.new(bar_index - 1, 2.0, bar_index, 1.0, bgcolor = color.new(color.red, 50))
plot(0)
"""
    out6, _ = execute(body, n=5)
    d = out6.drawings
    assert [l["x1"] for l in d["lines"]] == [2, int(bars(5)["timestamp"].iloc[-1].timestamp() * 1000)]
    assert d["lines"][0]["xloc"] == "bar_index" and d["lines"][0]["extend"] == "right" and d["lines"][1]["xloc"] == "bar_time"
    assert d["labels"][0]["textcolor"] == "rgba(255,255,255,1.0)"                   # v6 default (color.white)
    out5, _ = execute(body, n=5, version=5)
    assert out5.drawings["labels"][0]["textcolor"] == "rgba(54,58,69,1.0)"         # v5 default (color.black)
    assert all(item["key"].startswith("t:") for items in d.values() for item in items)


def _pine_payload(drawings: dict, bar_count: int = 5) -> dict:
    return {"pine": {"scripts": [{"id": "s", "outputs": [], "contexts": [], "drawings": drawings}]}}


def test_payload_validation_of_drawings():
    good = {"first_bar_index": 0, "lines": [{"key": "s:line:1", "kind": "line", "bar": 2, "xloc": "bar_index",
                                             "x1": 1, "x2": 3, "y1": 1.0, "y2": None}],
            "labels": [], "boxes": [],
            "linefills": [{"key": "s:linefill:2", "kind": "linefill", "bar": 2, "line1": "s:line:1", "line2": "s:line:1"}]}
    protocol._validate_drawings(_pine_payload(good)["pine"]["scripts"][0], 5)
    import copy
    for mutate, fragment in [
        (lambda g: g["lines"][0].update(bar=9), "which the chart does not have"),       # Replay: nothing after the cursor
        (lambda g: g["lines"][0].update(xloc="pixels"), "invalid xloc"),
        (lambda g: g["lines"][0].update(x1=1.5), "x-coordinates"),
        (lambda g: g["linefills"][0].update(line2="s:line:9"), "must reference two lines"),
        (lambda g: g["lines"].append(dict(g["lines"][0])), "unique"),
    ]:
        bad = copy.deepcopy(good)
        mutate(bad)
        with pytest.raises(protocol.PayloadValidationError, match=fragment):
            protocol._validate_drawings(_pine_payload(bad)["pine"]["scripts"][0], 5)


def test_terminal_payload_carries_drawings_in_historical_and_replay():
    from tests.tradingview_mode.test_pine_terminal import ev, payload_for
    from ui.tradingview_mode.component import pine_bridge as PB
    from ui.tradingview_mode.component import replay as replay_model
    from ui.tradingview_mode.component import terminal as T
    from ui.tradingview_mode.component.state import TerminalState, apply_event

    source = src("""
var line trend = line.new(bar_index, close, bar_index, close, extend = extend.right)
line.set_xy2(trend, bar_index, close)
if barstate.islast
    label.new(bar_index, high, "last")
plot(close)
""")
    state, session = TerminalState(dataset_key="EXNESS_XAUUSDM_M15", timeframe="15m"), {}
    state, log = PB.handle_pine_event(ev("pine_add", source=source), state, session)
    assert log.level == "info", log.message
    payload, _ = payload_for(state, session)
    drawings = payload["pine"]["scripts"][0]["drawings"]
    assert len(drawings["lines"]) == 1 and len(drawings["labels"]) == 1 and drawings["first_bar_index"] == 0
    _, _, frame = T._load(state)
    times = replay_model.frame_times(frame)
    replaying, _ = apply_event(state, ev("enter_replay", start="2026-09-10T09:30"),
                               T.context_for(T._bounds(frame), times))
    replaying, _ = apply_event(replaying, ev("step_forward"), T.context_for(T._bounds(frame), times))
    revealed = replay_model.revealed(frame, replaying.replay)
    payload, _ = payload_for(replaying, session, revealed, replay_model.info(replaying.replay, times))
    drawings = payload["pine"]["scripts"][0]["drawings"]
    first = drawings["first_bar_index"]
    items = [item for name in ("lines", "labels", "boxes", "linefills") for item in drawings[name]]
    assert items and all(first + item["bar"] < len(revealed) for item in items)   # nothing from after the cursor
    assert first + drawings["lines"][0]["x2"] == len(revealed) - 1               # the trend ends on the cursor bar


def test_frozen_p23_oracle_scripts_are_byte_identical():
    evidence = (PARITY / "P23_DRAWING_RESEARCH.md").read_text()
    for name in ("manual/m07_live_drawing_rollback.pine", "quick/q8_drawing_semantics.pine",
                 "quick/q8c_drawing_param_reassign.pine", "quick/q8e_drawing_equality.pine",
                 "quick/q8g_drawing_gc.pine"):
        assert hashlib.sha256((PARITY / name).read_bytes()).hexdigest() in evidence, name
