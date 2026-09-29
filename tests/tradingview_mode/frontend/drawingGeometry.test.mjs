// P2.3a drawing geometry: raw Pine coordinates -> chart logical indices and canvas geometry.
import assert from "node:assert/strict";
import test from "node:test";
import { dashFor, extendBox, extendSegment, labelPrice, logicalFromTime, logicalOf, tableLayout }
  from "../../../ui/tradingview_mode/component/frontend/src/chart/drawingGeometry.js";

const times = [1000, 1060, 1120, 1300];            // seconds; the last gap is a session gap

test("xloc.bar_index maps to the chart logical index, future bars included", () => {
  assert.equal(logicalOf(5, "bar_index", 0, times), 5);
  assert.equal(logicalOf(5, "bar_index", 20, times), 25);          // the Pine window starts at chart bar 20
  assert.equal(logicalOf(503, "bar_index", 0, times), 503);        // future bars stay logical indices
  assert.equal(logicalOf(null, "bar_index", 0, times), null);
});

test("xloc.bar_time: exact bars, interpolation between bars, extrapolation outside", () => {
  assert.equal(logicalOf(1060_000, "bar_time", 0, times), 1);
  assert.equal(logicalFromTime(times, 1090), 1.5);
  assert.equal(logicalFromTime(times, 1210), 2.5);                 // inside the session gap
  assert.equal(logicalFromTime(times, 1480), 4);                   // beyond the last bar: last spacing (180 s)
  assert.equal(logicalFromTime(times, 940), -1);
  assert.equal(logicalFromTime([], 1000), null);
});

test("extend.left / right / both reach the canvas edges along the segment", () => {
  const [a, b] = extendSegment({ x: 10, y: 10 }, { x: 20, y: 20 }, "right", 100);
  assert.deepEqual([a, b], [{ x: 10, y: 10 }, { x: 100, y: 100 }]);
  const [c, d] = extendSegment({ x: 20, y: 20 }, { x: 10, y: 10 }, "both", 100);
  assert.deepEqual([c, d], [{ x: 0, y: 0 }, { x: 100, y: 100 }]);
  assert.deepEqual(extendSegment({ x: 1, y: 1 }, { x: 2, y: 2 }, "none", 100), [{ x: 1, y: 1 }, { x: 2, y: 2 }]);
  assert.deepEqual(extendBox(30, 10, "left", 100), [0, 30]);
  assert.deepEqual(extendBox(10, 30, "right", 100), [10, 100]);
});

test("label anchors and line dashes", () => {
  assert.equal(labelPrice({ yloc: "price", y: 5 }, { high: 9, low: 1 }), 5);
  assert.equal(labelPrice({ yloc: "abovebar", y: 5 }, { high: 9, low: 1 }), 9);
  assert.equal(labelPrice({ yloc: "belowbar", y: 5 }, { high: 9, low: 1 }), 1);
  assert.deepEqual(dashFor("solid", 2), []);
  assert.deepEqual(dashFor("dashed", 2), [8, 6]);
});

test("P2.3b tables: top-right layout sized by the largest cell of each column and row", () => {
  const measure = (text, px) => text.length * px / 2;                     // deterministic stand-in for canvas
  const table = { columns: 2, rows: 3, cells: [
    { column: 0, row: 0, text: "key", text_size: "small" },
    { column: 1, row: 0, text: "a longer value", text_size: "small" },
    { column: 0, row: 2, text: "two\nlines", text_size: "normal" },
  ] };
  const layout = tableLayout(table, measure, 500, { small: 10, normal: 14 }, { pad: 4, margin: 8 });
  const [a, b, c] = layout.cells;
  assert.equal(a.w, Math.max(3 * 5, 5 * 7) + 8);                          // column 0: widest of "key", "lines"
  assert.equal(b.w, 14 * 5 + 8);
  assert.equal(layout.width, a.w + b.w);
  assert.equal(layout.x + layout.width, 500 - 8);                          // anchored at the top-right corner
  assert.equal(layout.y, 8);
  assert.equal(a.y, 8);
  assert.equal(c.y, 8 + 10 * 1.25 + 8);                                    // row 1 is empty: it takes no space
  assert.equal(c.h, 2 * 14 * 1.25 + 8);
  assert.deepEqual(c.lines, ["two", "lines"]);
});

test("P3.1 strategy fills become chart markers (presentation only)", async () => {
  const { strategyMarkers } = await import("../../../ui/tradingview_mode/component/frontend/src/chart/strategyMarkers.js");
  const markers = strategyMarkers([
    { key: "s:fill:1", time: 200, side: -1, qty: 2, kind: "reversal", exit_kind: "reversal", id: "Short" },
    { key: "s:fill:0", time: 100, side: 1, qty: 1, kind: "entry", exit_kind: null, id: "Long" },
    { key: "s:fill:2", time: 300, side: 1, qty: 1, kind: "exit", exit_kind: "trail", id: "Trail" },
    { key: "s:fill:3", time: 400, side: 1, qty: 1, kind: "entry", exit_kind: null, id: "BUY", comment: "SETUP_A_BUY" },
    { key: "s:fill:4", time: 500, side: -1, qty: 1, kind: "exit", exit_kind: "stop", id: "BUY EXIT", comment: "TRAIL_SL" },
    { key: "s:fill:5", time: 600, side: -1, qty: 1, kind: "exit", exit_kind: "stop", id: "BUY EXIT", comment: null },
  ]);
  assert.deepEqual(markers.map((m) => [m.time, m.position, m.shape, m.text]), [
    [100, "belowBar", "arrowUp", "Long +1"],
    [200, "aboveBar", "arrowDown", "Short -2"],
    [300, "belowBar", "arrowUp", "Trail +1"],
    [400, "belowBar", "arrowUp", "SETUP_A_BUY +1"],          // a comment replaces the order ID
    [500, "aboveBar", "arrowDown", "TRAIL_SL -1"],
    [600, "aboveBar", "arrowDown", "BUY EXIT SL -1"],
  ]);
});
