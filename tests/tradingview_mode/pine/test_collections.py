"""P2.3b: arrays of drawing IDs, `*.all`, current / superseded linefills, chart.point and the oracle-support tables-core
(parity/P23B_COLLECTIONS_RESEARCH.md §16). Unit behaviour first, then the frozen oracle scripts run in full (q8 Cases
0-7, q8g r4 Cases 0-2, q8c, q8e, m07, q9 r2 Cases 0-2, q9v) against the real TradingView observations.
"""
import hashlib
import re
from pathlib import Path

import pytest

from ui.tradingview_mode.component import protocol
from ui.tradingview_mode.pine import PineExecution, compile_script, run_script
from ui.tradingview_mode.pine.engine import resolve_inputs
from ui.tradingview_mode.pine.errors import ERROR, GAP
from ui.tradingview_mode.pine.values import ChartPoint, DrawingRef

from .helpers import bars, context, plots
from .test_drawings import LiveChart, errors, execute, failure, last, src

PARITY = Path("ui/tradingview_mode/pine/parity")


def gaps(body: str, extra: str = "") -> list[str]:
    return [d.message for d in compile_script(src(body, extra)).diagnostics if d.kind == GAP]


def payload(body: str, n: int = 12, extra: str = "") -> dict:
    out, _ = execute(body, n, extra)
    assert out.error is None, out.error
    return out.drawings


# ---- arrays of drawing IDs (§16.1) --------------------------------------------------------------------------------------

def test_arrays_of_all_four_drawing_kinds():
    p = last("""
array<line> ls = array.new<line>()
label[] lbs = array.new_label(0)
array<box> bs = array.new<box>(1, box.new(0, 2.0, 1, 1.0))
l1 = line.new(bar_index, 1.0, bar_index + 1, 1.0)
l2 = line.new(bar_index, 2.0, bar_index + 1, 2.0)
ls.push(l1)
ls.push(l2)
lbs.push(label.new(bar_index, 1.0, "x"))
array<linefill> fs = array.from(linefill.new(l1, l2, color.red))
fromIds = array.from(l1, l2)
plot(ls.size() + lbs.size() + bs.size() + fs.size(), "sizes")
plot(line.get_y1(ls.get(1)), "get")
ls.set(0, l2)
plot(ls.get(0) == l2 ? 1 : 0, "set")
plot(line.get_y1(ls.pop()), "pop")
plot(line.get_y1(fromIds.last()), "from")
plot(box.get_top(bs.first()), "boxTop")
plot(fs.get(0).get_line2() == l2 ? 1 : 0, "fillLine2")
plot(lbs.get(0).get_text() == "x" ? 1 : 0, "labelMethod")
""")
    assert p == {"sizes": 5, "get": 2.0, "set": 1, "pop": 2.0, "from": 2.0, "boxTop": 2.0, "fillLine2": 1,
                 "labelMethod": 1}


def test_array_element_kinds_are_checked():
    assert any("array holds `line`" in e for e in errors("""
array<line> ls = array.new<line>()
ls.push(label.new(0, 0.0, "x"))
plot(0)
"""))
    assert "`array.from()` needs values of one type." in errors("""
l = line.new(0, 0.0, 1, 0.0)
b = label.new(0, 0.0, "x")
a = array.from(l, b)
plot(a.size())
""")


def test_array_aliases_share_and_copies_share_the_ids():
    p = last("""
a = array.new<line>()
b = a
b.push(line.new(bar_index, 1.0, bar_index + 1, 1.0))
c = a.copy()
line.set_y1(c.get(0), 42)
c.push(line.new(bar_index, 2.0, bar_index + 1, 2.0))
plot(a.size(), "aliasSize")
plot(c.size(), "copySize")
plot(line.get_y1(a.get(0)), "sharedObject")
""")
    assert p == {"aliasSize": 1, "copySize": 2, "sharedObject": 42}


def test_history_is_a_read_only_container_of_live_ids_q9_row_b():
    p = last("""
var array<line> held = array.new<line>()
if bar_index <= 1
    held.push(line.new(bar_index, 1.0 + bar_index, bar_index + 1, 1.0))
int histSize = na
if bar_index == 2
    prev = held[1]
    line.set_y1(prev.get(0), 21)
    histSize := prev.size()
plot(histSize, "histSize")
plot(line.get_y1(held.get(0)), "liveY1")
""", n=3)
    assert p == {"histSize": 2, "liveY1": 21}
    assert "Cannot modify the elements of a historical array" in failure("""
var array<line> held = array.new<line>()
held.push(line.new(bar_index, 1.0, bar_index + 1, 1.0))
if bar_index == 3
    array<line> prev = held[1]
    prev.push(line.new(bar_index, 2.0, bar_index + 1, 2.0))
plot(0)
""")["message"]


def test_dead_and_collected_ids_stay_in_arrays_and_arrays_are_not_roots():
    p = last("""
var array<label> kept = array.new<label>()
kept.push(label.new(bar_index, 1.0, str.tostring(bar_index)))
if bar_index == 9
    label.delete(kept.get(kept.size() - 1))
plot(kept.size(), "size")
plot(na(kept.get(0)) ? 1 : 0, "collectedNa")
plot(na(kept.get(kept.size() - 1)) ? 1 : 0, "deletedNa")
plot(array.size(label.all), "alive")
""", n=10, extra=", max_labels_count=3")
    assert p == {"size": 10, "collectedNa": 1, "deletedNa": 1, "alive": 2}


@pytest.mark.parametrize("decl", ["varip array<line> a = array.new<line>()", "varip label[] a = array.new_label()",
                                  "varip table t = na"])
def test_varip_collections_of_drawings_are_rejected_ce10128(decl):
    assert any("Variables with varip modifier cannot have type" in e for e in errors(decl + "\nplot(0)"))


def test_for_in_over_drawing_arrays_uses_typed_methods():
    p = last("""
a = array.from(label.new(bar_index, 1.0, "p"), label.new(bar_index, 2.0, "q"))
string s = ""
for [i, id] in a
    s += id.get_text() + str.tostring(i)
plot(s == "p0q1" ? 1 : 0, "joined")
""")
    assert p == {"joined": 1}


# ---- *.all (§16.2) ------------------------------------------------------------------------------------------------------

def test_all_is_ordered_oldest_created_first_not_by_position():
    p = last("""
if barstate.islast
    for i = 0 to 3
        label.new(bar_index - (i % 2 == 0 ? i : 10 - i), 1.0, str.tostring(i))
string s = ""
for id in label.all
    s += id.get_text()
plot(s == "0123" ? 1 : 0, "creationOrder")
plot(label.all.size(), "methodSize")
plot(array.size(label.all), "functionSize")
""")
    assert p == {"creationOrder": 1, "methodSize": 4, "functionSize": 4}


def test_all_is_a_fresh_snapshot_per_read_q9_row_a():
    p = last("""
int atRead = na
int afterChanges = na
int firstDead = na
if barstate.islast
    label.new(bar_index, 1.0, "A1")
    label.new(bar_index, 1.0, "A2")
    array<label> view = label.all
    atRead := view.size()
    label.new(bar_index, 1.0, "A3")
    label.delete(view.get(0))
    afterChanges := view.size()
    firstDead := na(view.get(0)) ? 1 : 0
plot(atRead, "atRead")
plot(afterChanges, "afterChanges")
plot(firstDead, "firstDead")
plot(label.all.size(), "fresh")
""")
    assert p == {"atRead": 2, "afterChanges": 2, "firstDead": 1, "fresh": 2}


def test_all_result_is_an_ordinary_mutable_array_q9_case2():
    p = last("""
int pushed = na
if barstate.islast
    label.new(bar_index, 1.0, "A")
    array<label> la = label.all
    la.push(la.get(0))
    la.push(label.new(bar_index, 2.0, "X"))
    pushed := la.size()
plot(pushed, "pushed")
plot(label.all.size(), "store")
""")
    assert p == {"pushed": 3, "store": 2}                           # the push never changes the drawing store


def test_var_keeps_the_snapshot_it_received_q9_row_a2():
    p = last("""
var array<label> early = label.all
var array<label> second = array.new<label>()
label.new(bar_index, 1.0, "x")
if bar_index == 1
    second := label.all
plot(early.size(), "early")
plot(second.size(), "second")
plot(label.all.size(), "now")
""", n=6)
    assert p == {"early": 0, "second": 2, "now": 6}


def test_all_history_and_requests_are_rejected():
    assert any("History of `label.all`" in g for g in gaps("a = label.all[1]\nplot(0)"))
    assert any("label.all" in g for g in gaps('x = request.security(syminfo.tickerid, "60", label.all.size())\nplot(x)'))


# ---- linefills: current / superseded (§16.3, q9 C1-C3, q9v) ------------------------------------------------------------

LINEFILLS = """
var int counts = na
var int redNa = na
var int blueNa = na
var int getters = na
if barstate.islast
    m1 = line.new(bar_index - 5, 2.0, bar_index, 2.0)
    m2 = line.new(bar_index - 5, 1.0, bar_index, 1.0)
    int before = linefill.all.size()
    red = linefill.new(m1, m2, color.red)
    int afterOne = linefill.all.size()
    blue = linefill.new(m2, m1, color.blue)
    counts := before * 100 + afterOne * 10 + linefill.all.size()
    redNa := na(red) ? 1 : 0
    blueNa := na(blue) ? 1 : 0
    getters := linefill.get_line1(red) == m1 and linefill.get_line1(blue) == m2 ? 1 : 0
plot(counts, "counts")
plot(redNa, "redNa")
plot(blueNa, "blueNa")
plot(getters, "getters")
"""


def test_second_fill_on_a_pair_supersedes_reversed_pair_included_q9_c1_c2():
    p = last(LINEFILLS)
    assert p == {"counts": 11, "redNa": 0, "blueNa": 0, "getters": 1}   # 0 / 1 / 1: not listed, still valid


def test_only_the_current_fill_is_rendered_q9v():
    drawings = payload(LINEFILLS)
    assert [f["color"] for f in drawings["linefills"]] == ["rgba(33,150,243,1.0)"]


def test_deleting_the_current_fill_does_not_restore_the_previous_q9_c3_q9v():
    p = last("""
c1 = line.new(bar_index - 5, 2.0, bar_index, 2.0)
c2 = line.new(bar_index - 5, 1.0, bar_index, 1.0)
orange = linefill.new(c1, c2, color.orange)
teal = linefill.new(c1, c2, color.teal)
linefill.delete(teal)
plot(na(orange) ? 1 : 0, "orangeNa")
plot(na(teal) ? 1 : 0, "tealNa")
plot(linefill.all.size(), "listed")
""")
    assert p == {"orangeNa": 1, "tealNa": 1, "listed": 0}


def test_source_line_death_kills_current_and_superseded_fills():
    p = last("""
l1 = line.new(bar_index - 5, 2.0, bar_index, 2.0)
l2 = line.new(bar_index - 5, 1.0, bar_index, 1.0)
f1 = linefill.new(l1, l2, color.red)
f2 = linefill.new(l1, l2, color.blue)
line.delete(l1)
plot(na(f1) and na(f2) ? 1 : 0, "bothDead")
""")
    assert p == {"bothDead": 1}


def test_superseded_engine_policies():
    p = last("""
var linefill f1 = na
var linefill f2 = na
if bar_index == 0
    l1 = line.new(0, 2.0, 5, 2.0)
    l2 = line.new(0, 1.0, 5, 1.0)
    f1 := linefill.new(l1, l2, color.red)
    f2 := linefill.new(l1, l2, color.blue)
    linefill.set_color(f1, color.green)
    linefill.delete(f1)
plot(na(f1) ? 1 : 0, "supersededDeleted")
plot(na(f2) ? 1 : 0, "currentAlive")
plot(linefill.all.size(), "listed")
""")
    assert p == {"supersededDeleted": 1, "currentAlive": 0, "listed": 1}


def test_supersede_is_rolled_back_on_realtime_ticks():
    live = LiveChart(src("""
var line a = line.new(0, 2.0, 1, 2.0)
var line b = line.new(0, 1.0, 1, 1.0)
var linefill first = linefill.new(a, b, color.red)
int before = linefill.all.size()
if barstate.isrealtime
    linefill.new(a, b, color.blue)
plot(before, "before")
plot(na(first) ? 1 : 0, "firstNa")
"""))
    live._run()
    assert live.tick() == {"before": 1, "firstNa": 0}
    fills = [d for d in live.store.objects() if d.kind == "linefill"]
    assert [d.superseded for d in fills] == [True, False]           # the tick's state
    live.execution.runtime.rollback(live.n - 1)
    fills = [d for d in live.store.objects() if d.kind == "linefill"]
    assert [d.superseded for d in fills] == [False]                 # rolled back: the first fill is current again
    assert live.store.pairs == {(1, 2): fills[0].oid}


def test_line_garbage_collection_does_not_kill_linefills_q11_row_g():
    p = last("""
var array<line> ls = array.new<line>()
var array<linefill> fs = array.new<linefill>()
if bar_index == 0
    ls.push(line.new(0, 2.0, 1, 2.0))
    ls.push(line.new(0, 1.0, 1, 1.0))
    fs.push(linefill.new(ls.get(0), ls.get(1), color.green))
line.new(bar_index, close, bar_index + 1, close)
plot(na(ls.get(0)) and na(ls.get(1)) ? 1 : 0, "linesCollected")
plot(na(fs.get(0)) ? 1 : 0, "fillNa")
plot(na(linefill.get_line1(fs.get(0))) ? 1 : 0, "getLine1Na")
plot(linefill.get_line1(fs.get(0)) == ls.get(0) ? 1 : 0, "storedRef")
plot(linefill.all.size(), "listed")
""", extra=", max_lines_count=3")
    assert p == {"linesCollected": 1, "fillNa": 0, "getLine1Na": 1, "storedRef": 1, "listed": 1}


def test_explicit_line_delete_still_kills_linefills_q8_case4():
    p = last("""
var array<line> ls = array.new<line>()
var array<linefill> fs = array.new<linefill>()
if bar_index == 0
    ls.push(line.new(0, 2.0, 1, 2.0))
    ls.push(line.new(0, 1.0, 1, 1.0))
    fs.push(linefill.new(ls.get(0), ls.get(1), color.green))
if bar_index == 5
    line.delete(ls.get(1))
plot(na(fs.get(0)) ? 1 : 0, "fillNa")
plot(linefill.all.size(), "listed")
""")
    assert p == {"fillNa": 1, "listed": 0}


def test_fill_with_a_collected_line_is_listed_but_not_rendered():
    drawings = payload("""
var array<line> ls = array.new<line>()
if bar_index == 0
    ls.push(line.new(0, 2.0, 1, 2.0))
    ls.push(line.new(0, 1.0, 1, 1.0))
    linefill.new(ls.get(0), ls.get(1), color.green)
line.new(bar_index, close, bar_index + 1, close)
plot(linefill.all.size())
""", extra=", max_lines_count=3")
    assert drawings["linefills"] == [] and len(drawings["lines"]) == 3
    protocol._validate_drawings({"drawings": {**drawings, "first_bar_index": 0}}, 12)


def test_rollback_restores_a_collected_line_under_its_surviving_fill():
    live = LiveChart(src("""
var array<line> ls = array.new<line>()
var array<linefill> fs = array.new<linefill>()
if bar_index == 0
    ls.push(line.new(0, 2.0, 1, 2.0))
    ls.push(line.new(0, 1.0, 1, 1.0))
    fs.push(linefill.new(ls.get(0), ls.get(1), color.green))
if barstate.isrealtime
    for i = 1 to 3
        line.new(bar_index, close, bar_index + 1, close)
plot(na(ls.get(0)) ? 1 : 0, "line1Na")
plot(na(fs.get(0)) ? 1 : 0, "fillNa")
""", ", max_lines_count=4"))
    assert live._run() == {"line1Na": 1, "fillNa": 0}               # the tick collected P's lines, the fill survives
    fill_oid = next(d.oid for d in live.store.objects() if d.kind == "linefill")
    live.execution.runtime.rollback(live.n - 1)
    assert {1, 2} <= set(live.store.live) and fill_oid in live.store.live            # lines restored, same fill
    assert [d.oid for d in live.store.objects() if d.kind == "linefill"] == [fill_oid]
    assert live.tick() == {"line1Na": 1, "fillNa": 0}


@pytest.mark.parametrize("op", ["==", "!="])
def test_linefill_equality_does_not_compile_ce10123(op):
    messages = errors(f"""
l1 = line.new(0, 1.0, 1, 1.0)
l2 = line.new(0, 2.0, 1, 2.0)
fa1 = linefill.new(l1, l2)
fa2 = linefill.new(l1, l2)
b = fa1 {op} fa2
plot(0)
""")
    assert messages == [f'Cannot call "operator {op}" with argument "expr0"="fa1". An argument of "series linefill" '
                        f'type was used but a "simple string" is expected.']


# ---- chart.point (§16.4) ------------------------------------------------------------------------------------------------

def test_point_constructors_fields_and_now_default_close():
    out, execution = execute("""
p1 = chart.point.new(1000, 3, 2.5)
p2 = chart.point.now()
p3 = chart.point.now(7.0)
p4 = chart.point.from_index(5, 1.5)
p5 = chart.point.from_time(2000, 0.5)
plot(p1.time + p1.index + p1.price, "new")
plot(p2.price == close and p2.index == bar_index and p2.time == time ? 1 : 0, "nowDefault")
plot(p3.price == 7.0 and p3.index == bar_index ? 1 : 0, "nowPrice")
plot(na(p4.time) and p4.index == 5 ? 1 : 0, "fromIndex")
plot(na(p5.index) and p5.time == 2000 ? 1 : 0, "fromTime")
""")
    p = {k: v[-1] for k, v in plots(out).items()}
    assert p == {"new": 1005.5, "nowDefault": 1, "nowPrice": 1, "fromIndex": 1, "fromTime": 1}


def test_point_aliases_arrays_and_copy():
    p = last("""
a = chart.point.from_index(0, 1.0)
b = a
b.price := 5.0
arr = array.from(a)
arr.get(0).index += 3
c = a.copy()
c.price := 9.0
d = chart.point.copy(a)
plot(a.price, "aliasPrice")
plot(a.index, "arrayIndex")
plot(c.price, "copyPrice")
plot(d.price, "copy2Price")
""")
    assert p == {"aliasPrice": 5.0, "arrayIndex": 3, "copyPrice": 9.0, "copy2Price": 5.0}


def test_point_history_same_object_and_different_objects_q9_d3_case1():
    p = last("""
var chart.point ph = chart.point.from_index(0, 0.0)
ph.price := bar_index
p = chart.point.from_index(bar_index, bar_index * 10.0)
float samePersistent = na
float differentObjects = na
if bar_index > 0
    samePersistent := (ph[1]).price
    chart.point older = p[1]
    differentObjects := older.price
plot(samePersistent, "samePersistent")
plot(differentObjects, "differentObjects")
if barstate.islast
    chart.point hp = ph[1]
    hp.price := -5
plot(ph.price, "writeThroughHistory")
""")
    assert p == {"samePersistent": 11, "differentObjects": 100, "writeThroughHistory": -5}


def test_points_shared_across_var_slots_and_arrays_q9_d1_d2():
    p = last("""
var chart.point pa = chart.point.from_index(0, 0.0)
var chart.point pb = pa
var array<chart.point> arr = array.from(pa)
pa.price += 1
plot(pb.price, "varAlias")
plot(arr.get(0).price, "arrayElement")
""")
    assert p == {"varAlias": 12, "arrayElement": 12}


def test_point_field_errors_and_gaps():
    assert "Cannot access the field `price` of an na chart point." in failure("""
chart.point p = na
x = p.price
plot(x)
""")["message"]
    assert any("has no field `x`" in e for e in errors("p = chart.point.now(1.0)\ny = p.x\nplot(0)"))
    assert any("Cannot assign a value of type `float`" in e for e in errors("p = chart.point.now(1.0)\np.index := 1.5\nplot(0)"))
    assert any("History of a chart point field" in g for g in gaps("p = chart.point.now(1.0)\nx = p.price[1]\nplot(x)"))
    assert any("Comparing `chart.point`" in g for g in gaps("a = chart.point.now(1.0)\nb = a == a\nplot(0)"))
    assert any("requires user-defined types" in g for g in gaps("l = line.new(0, 1.0, 1, 1.0)\nx = l.x1\nplot(0)"))


def test_point_overloads_copy_coordinates_at_call_time():
    drawings = payload("""
if barstate.islast
    p1 = chart.point.new(time, bar_index - 2, 10.0)
    p2 = chart.point.now(20.0)
    l = line.new(p1, p2, color = color.red)
    lb = label.new(p2, "p")
    b = box.new(p1, p2, bgcolor = color.gray)
    lt = line.new(p1, p2, xloc.bar_time)
    p1.price := 99.0
    p2.index := 0
plot(0)
""")
    line, bar_time_line = drawings["lines"]
    assert (line["x1"], line["y1"], line["x2"], line["y2"], line["color"]) == (9, 10.0, 11, 20.0, "rgba(255,82,82,1.0)")
    assert bar_time_line["xloc"] == "bar_time" and bar_time_line["x1"] == bar_time_line["x2"]
    assert (drawings["labels"][0]["x"], drawings["labels"][0]["y"]) == (11, 20.0)
    box = drawings["boxes"][0]
    assert (box["left"], box["top"], box["right"], box["bottom"]) == (9, 10.0, 11, 20.0)


def test_point_setters_use_the_objects_xloc():
    drawings = payload("""
if barstate.islast
    p = chart.point.new(time, bar_index - 1, 3.0)
    q = chart.point.new(time, bar_index, 4.0)
    l = line.new(0, 0.0, 1, 0.0)
    line.set_first_point(l, p)
    line.set_second_point(l, q)
    lb = label.new(0, 0.0, "x", xloc = xloc.bar_time)
    label.set_point(lb, p)
    b = box.new(0, 0.0, 1, 0.0)
    box.set_top_left_point(b, p)
    box.set_bottom_right_point(b, q)
plot(0)
""")
    line = drawings["lines"][0]
    assert (line["x1"], line["y1"], line["x2"], line["y2"]) == (10, 3.0, 11, 4.0)
    assert drawings["labels"][0]["x"] > 10_000 and drawings["labels"][0]["y"] == 3.0      # bar_time label: the time
    box = drawings["boxes"][0]
    assert (box["left"], box["top"], box["right"], box["bottom"]) == (10, 3.0, 11, 4.0)


def test_overload_is_chosen_at_run_time_for_untyped_arguments():
    program = compile_script(src("""
mk(a, b) => line.new(a, b)
mk4(a, b, c, d) => line.new(a, b, c, d)
if barstate.islast
    mk(chart.point.from_index(bar_index, 1.0), chart.point.from_index(bar_index + 1, 2.0))
    mk4(bar_index, 3.0, bar_index + 1, 4.0)
    line.new(na, na, na, na)
plot(0)
""")).program
    assert any(entry[0] == "overload" for entry in program.calls.values())
    out = run_script(PineExecution(program, {}), context(bars(5)), ("t",), "t")
    assert out.error is None
    assert [(l["x1"], l["y1"]) for l in out.drawings["lines"]] == [(4, 1.0), (4, 3.0), (None, None)]


# ---- realtime rollback and varip persistence of points -------------------------------------------------------------------

POINTS_LIVE = src("""
var chart.point vp = chart.point.now(0.0)
varip chart.point ip = chart.point.now(0.0)
var array<chart.point> va = array.from(chart.point.now(0.0))
varip array<chart.point> vpa = array.from(chart.point.now(0.0))
varip chart.point shared = chart.point.now(0.0)
var chart.point alias = shared
if barstate.isrealtime
    vp.price += 1
    ip.price += 1
    va.get(0).price += 1
    vpa.get(0).price += 1
    alias.price += 1
plot(vp.price, "var")
plot(ip.price, "varip")
plot(va.get(0).price, "varArray")
plot(vpa.get(0).price, "varipArray")
plot(alias.price, "mixedAlias")
""")


def test_var_points_roll_back_varip_points_persist():
    live = LiveChart(POINTS_LIVE)
    assert live._run() == {"var": 1, "varip": 1, "varArray": 1, "varipArray": 1, "mixedAlias": 1}
    assert live.tick() == {"var": 1, "varip": 2, "varArray": 1, "varipArray": 2, "mixedAlias": 2}
    assert live.tick() == {"var": 1, "varip": 3, "varArray": 1, "varipArray": 3, "mixedAlias": 3}
    # the bar's final execution commits; the new bar starts from it
    assert live.new_bar() == {"var": 2, "varip": 4, "varArray": 2, "varipArray": 4, "mixedAlias": 4}


def test_var_points_incremental_equal_fresh():
    source = src("""
var chart.point vp = chart.point.now(0.0)
var array<chart.point> pts = array.new<chart.point>()
vp.price += close > open ? 1 : -1
if bar_index % 3 == 0
    pts.push(chart.point.now(high))
if pts.size() > 0
    pts.get(0).price += 0.5
plot(vp.price, "vp")
plot(pts.size(), "n")
plot(pts.size() > 0 ? pts.get(0).price : na, "first")
""")
    live = LiveChart(source)
    live._run()
    for _ in range(3):
        live.tick()
    live.new_bar()
    incremental = live.tick()
    fresh = PineExecution(live.program, {})
    out = run_script(fresh, context(live.frame.iloc[:live.n], forming_last=True), ("live",), "t")
    assert {k: v[-1] for k, v in plots(out).items()} == incremental


# ---- request restrictions (§16.7) ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    'p = chart.point.now(1.0)\nx = request.security(syminfo.tickerid, "60", p)\nplot(0)',
    'x = request.security(syminfo.tickerid, "60", chart.point.now(1.0).price)\nplot(x)',
    'p = chart.point.now(high)\ny = p.price\nx = request.security(syminfo.tickerid, "60", y)\nplot(x)',
    'a = array.from(chart.point.now(1.0))\nx = request.security(syminfo.tickerid, "60", a)\nplot(0)',
    'a = array.from(line.new(0, 1.0, 1, 1.0))\nx = request.security(syminfo.tickerid, "60", a)\nplot(0)',
    'x = request.security(syminfo.tickerid, "60", label.all)\nplot(0)',
])
def test_points_drawing_arrays_and_all_never_run_in_requested_contexts(body):
    result = compile_script(src(body))
    assert not result.ok
    assert any(d.kind == GAP and d.feature == "request" for d in result.diagnostics), \
        [d.message for d in result.diagnostics]


# ---- oracle-support tables-core (§9) --------------------------------------------------------------------------------------

def test_table_payload_and_validation():
    drawings = payload("""
var table t = table.new(position.top_right, 2, 3, bgcolor=color.white, border_color=color.gray, border_width=1)
if barstate.islast
    table.cell(t, 0, 0, "key", text_color=color.black, text_size=size.small, text_halign=text.align_left)
    table.cell(t, 1, 2, "value " + str.tostring(bar_index), bgcolor=color.silver)
    t.cell(1, 0, "method")
plot(0)
""")
    (table,) = drawings["tables"]
    assert (table["position"], table["columns"], table["rows"], table["border_width"]) == ("top_right", 2, 3, 1)
    assert [(c["column"], c["row"], c["text"]) for c in table["cells"]] == [(0, 0, "key"), (1, 0, "method"),
                                                                              (1, 2, "value 11")]
    assert table["cells"][0]["text_halign"] == "left" and table["cells"][0]["text_size"] == "small"
    pine = {"scripts": [{"id": "t", "outputs": [], "drawings": {**drawings, "first_bar_index": 0}}]}
    protocol._validate_drawings(pine["scripts"][0], 12)
    bad = {**drawings, "first_bar_index": 0, "tables": [{**table, "cells": [{**table["cells"][0], "column": 5}]}]}
    with pytest.raises(protocol.PayloadValidationError):
        protocol._validate_drawings({"drawings": bad}, 12)


def test_table_subset_limits():
    assert "outside the table" in failure("""
var table t = table.new(position.top_right, 1, 1)
table.cell(t, 1, 0, "x")
plot(0)
""")["message"]
    assert "not implemented yet (only its default)" in failure("""
var table t = table.new(position.top_right, 1, 1, frame_width = 2)
plot(0)
""")["message"]
    assert gaps("var table t = table.new(position.bottom_right, 1, 1)\nplot(0)")
    assert gaps("var table t = table.new(position.top_right, 1, 1)\ntable.clear(t, 0, 0)\nplot(0)")
    assert gaps("a = table.all\nplot(0)")


def test_table_cell_writes_roll_back_on_realtime_ticks():
    live = LiveChart(src("""
var table t = table.new(position.top_right, 1, 1)
if barstate.isrealtime
    table.cell(t, 0, 0, "rt " + str.tostring(close))
else if bar_index == 0
    table.cell(t, 0, 0, "history")
plot(0)
"""))
    live._run()
    (table,) = [d for d in live.store.objects() if d.kind == "table"]
    assert table.props[("cell", 0, 0)]["text"].startswith("rt ")
    live.execution.runtime.rollback(live.n - 1)
    assert table.props[("cell", 0, 0)]["text"] == "history"


# ---- frozen oracle scripts run in full ------------------------------------------------------------------------------------

def oracle(path: str, case: int | None = None, n: int = 300):
    program = compile_script((PARITY / path).read_text()).program
    inputs = resolve_inputs(program, {0: case} if case is not None else {})[0]
    out = run_script(PineExecution(program, inputs), context(bars(n)), ("t",), "t")
    return out, table_rows(out)


def table_rows(out) -> dict[int, list[str]]:
    rows: dict[int, dict] = {}
    for table in (out.drawings or {}).get("tables", []):
        for cell in table["cells"]:
            rows.setdefault(cell["row"], {})[cell["column"]] = cell["text"]
    return {row: [text for _, text in sorted(cells.items())] for row, cells in sorted(rows.items())}


def test_q8_case0_full_script():
    out, rows = oracle("quick/q8_drawing_semantics.pine", 0, n=600)
    assert out.error is None
    values = {row: cells[1] for row, cells in rows.items()}
    assert values[1] == "55" and values[2] == "77 / 55"                                   # TV: 55; 77 / 55
    assert values[3] == "599" and "bar_index=599" in rows[3][0]                          # TV: h[1] y2 = bar_index
    assert values[4] == "598"                                                            # TV: bar_index - 1
    assert values[5] == "50 / 0"             # TV 52 / 0 - DIVERGENCE: exact limit vs TradingView's approximate count
    # TV 2: an ISOLATED TradingView observation not reproduced by q9 / q9v / q10 / q11 (twelve controlled probes, all
    # +1): an unresolved oracle/context anomaly, not an accepted engine divergence (research §18). The engine keeps
    # the replicated current/superseded model.
    assert values[6] == "1"
    assert values[7] == "2" and values[8] == "99 / 99 / 21" and values[9] == "completed"  # TV: identical
    assert values[10] == "500"               # TV 504 with max_lines_count 500 - DIVERGENCE: exact limit


@pytest.mark.parametrize("case, expected", [
    (1, "get_y1 after delete = NaN"),
    (2, "second delete completed"),
    (3, "set after delete completed; get_y1 = NaN"),
    (4, "linefill.all size after deleting line1 = 0; na(get_line1) = true"),
    (5, "set through p[1] completed; get_y1(p[1]) = 5"),
    (7, "x of the first (garbage-collected?) label = 0"),
])
def test_q8_cases_full_script(case, expected):
    out, rows = oracle("quick/q8_drawing_semantics.pine", case)
    assert out.error is None and rows[1] == [f"case {case}", expected]                   # TV: identical text


def test_q8_case6_future_limit_full_script():
    out, _ = oracle("quick/q8_drawing_semantics.pine", 6)
    assert out.error["message"] == "Objects positioned using xloc.bar_index cannot be drawn further than 500 bars into the future."
    assert out.error["bar_index"] == 296                                                 # TV: RE10020 on bar K


@pytest.mark.parametrize("case, action", [(0, "none"), (1, "line.set_y1(deadLine, 999) completed"),
                                          (2, "line.delete(deadLine) completed")])
def test_q8g_r4_full_script(case, action):
    out, rows = oracle("quick/q8g_drawing_gc.pine", case)
    assert out.error is None
    values = {row: cells[1] for row, cells in rows.items()}
    assert values[1] == action
    # TV: size 10, U31..U40 / R31..R40 - DIVERGENCE: exact limit 5; the oldest-created are the ones evicted
    assert values[2] == "label.all size 5: U36 U37 U38 U39 U40 "
    assert values[3] == "line.all size 5, kept IDs still readable 5/40: y1 36 37 38 39 40 "
    assert values[4] == "box.all size 5: first B37 B38 B39 B40 "                         # TV: identical
    assert values[5] == "first listed in box.all: yes; id na: no; get_top: 1000"          # TV: identical
    assert values[6] == ("na(deadLine): yes; get_y1: NaN; line.all size before/after: 5/5; "
                         "R1 (y1 1 or 999) in line.all: no")                              # TV: 10/10, otherwise identical


def test_q8c_and_q8e_full_scripts():
    result = compile_script((PARITY / "quick/q8c_drawing_param_reassign.pine").read_text())
    assert [d.message for d in result.diagnostics if d.kind == ERROR] == ["Function arguments cannot be mutable (`l`)."]
    out, rows = oracle("quick/q8e_drawing_equality.pine")
    assert rows[0] == ["compiled; a == b: true, a == copy: false, a != copy: true"]         # TV: identical


def test_m07_full_script_realtime():
    live = LiveChart((PARITY / "manual/m07_live_drawing_rollback.pine").read_text())

    def now():
        out = run_script(live.execution, context(live.frame.iloc[:live.n], forming_last=True), ("live",), "t")
        assert out.error is None, out.error
        return table_rows(out)[2][0]

    assert now() == "NOW (read at the start of this execution): A.y2=0 R.text=0 lines=1 labels=1 boxes=1"
    live.tick()
    assert now().endswith("A.y2=0 R.text=0 lines=1 labels=1 boxes=1")                    # TV: tick 2 identical
    live.n += 1
    # TV: the next bar reads the committed final execution: lines 1 -> 3, labels 1 -> 2, boxes 1 -> 0
    assert re.fullmatch(r".*A\.y2=\d+ R\.text=\d+ lines=3 labels=2 boxes=0", now())


def test_q9_r2_case0_full_script():
    out, rows = oracle("quick/q9_collections_points.pine", 0)
    assert out.error is None
    values = {row: cells[1] for row, cells in rows.items()}
    assert values[1] == ("view = label.all after A1, A2: size at read 2; after label.new A3 2; after label.delete A1 2; "
                         "view[0] a deleted ID; label.all.size() now 2")
    assert values[2] == "var earlyAll = label.all read on bar 0: size now 0"
    assert values[3] == "held[1] size 2; after line.set_y1(held[1].get(0), 21): y1 via held.get(0) 21; held.size() 2"
    assert values[4].startswith("band A (red then blue), same bar: size before/after 1st/after 2nd = 1/2/2; "
                                "na(red) no; na(blue) no;")
    assert values[4].endswith("red's line1 is m1 yes; blue's line1 is m1 yes")
    assert "= 0/1/1; na(1st) no; na(2nd) no" in values[5]
    assert "na(orange) yes; na(teal) yes" in values[6]
    pa, pb, bars_so_far = map(int, re.findall(r"pa\.price (\d+); pb\.price (\d+); bars so far (\d+)", values[8])[0])
    assert pa == pb == bars_so_far
    pc, element = re.findall(r"pc\.price (\d+); pArr\.get\(0\)\.price (\d+)", values[9])[0]
    assert pc == element
    bar, price, previous = re.findall(r"bar_index (\d+); ph\.price (\d+); \(ph\[1\]\)\.price (\d+)", values[10])[0]
    assert bar == price == previous


def test_q9_r2_cases_1_and_2_full_script():
    _, rows = oracle("quick/q9_collections_points.pine", 1)
    assert rows[11][1] == "hp = ph[1]; hp.price := -5 completed; hp.price -5; ph.price -5; ph[1] re-read price -5"
    _, rows = oracle("quick/q9_collections_points.pine", 2)
    assert rows[11][1] == "la = label.all; la.push(label.new(...)) completed; la.size() 3; label.all.size() 3"


def test_q9v_full_script_renders_blue_and_no_band_c():
    out, _ = oracle("quick/q9v_linefill_visual.pine")
    assert out.error is None
    fills = out.drawings["linefills"]
    assert [f["color"] for f in fills] == ["rgba(33,150,243,0.5)"]                   # TV: band A blue, band C none
    lines = {l["key"]: l["y1"] for l in out.drawings["lines"]}
    assert {lines[fills[0]["line1"]], lines[fills[0]["line2"]]} == {80.0, 60.0}


def test_q10_full_script_line_limit():
    out, rows = oracle("quick/q10_linefill_line_limit.pine")
    assert out.error is None
    counts = [re.search(r"before/F1/F2 = (\d+/\d+/\d+)", rows[i][0]).group(1) for i in range(4)]
    assert counts == ["0/1/1", "1/2/2", "2/3/3", "3/4/4"]                             # TV: identical
    assert all("na(l1) no, na(l2) no, na(F1) no, na(F2) no" in rows[i][0] for i in range(4))
    # lines alive: TV 0 / 498 / 502 / 501 before the pair - the engine's exact limit gives 0 / 498 / 500 / 500
    assert [int(re.search(r"lines before pair (\d+)", rows[i][0]).group(1)) for i in range(4)] == [0, 498, 500, 500]


def test_q11_full_script_gc_and_discarded_ids():
    out, rows = oracle("quick/q11_linefill_gc_discard.pine")
    assert out.error is None
    assert rows[0][0] == ("G after 600 more lines: na(P line1) yes, na(P line2) yes, na(PF) no, na(get_line1(PF)) yes; "
                          "linefill.all 1; line.all 500")                                 # TV: identical
    assert rows[1][0] == "D1 discarded, opaque: linefill.all before/after = 1/2"
    assert rows[2][0] == "D2 assigned, opaque: linefill.all before/after = 2/3; na(F1) no, na(F2) no"
    assert rows[3][0].endswith("discarded, opaque: linefill.all before/after = 3/4")


def test_frozen_p23b_oracles_are_byte_identical():
    digest = lambda path: hashlib.sha256((PARITY / path).read_bytes()).hexdigest()       # noqa: E731
    assert digest("quick/q9_collections_points.pine") == \
        "ced90e345fab9e1cf5567a218e84a7bc9095828576de7a9f9e945660a0a5e303"
    assert digest("quick/q9v_linefill_visual.pine") == \
        "9ad847725bad97bc907c2cf9bfb7f4bf6e2917468824146ee595bafd3c45948f"
    assert digest("quick/q10_linefill_line_limit.pine") == \
        "edfd8eecf0f1c4639d5e295a946714adda951b7793aa85f99e4f38be6ef66ef9"
    assert digest("quick/q11_linefill_gc_discard.pine") == \
        "101ff02f7fa63f441b254836479fb4eff7d99cc97298d775dfca0a23217e069f"


def test_values_are_plain_references():
    point = ChartPoint(1, 2, 3.0, 1)
    assert point is not ChartPoint(1, 2, 3.0, 1) and DrawingRef("table", 1).kind == "table"
