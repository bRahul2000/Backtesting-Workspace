// P2.3a drawing geometry: raw Pine coordinates -> chart logical indices and canvas geometry.
import assert from "node:assert/strict";
import test from "node:test";
import { dashFor, extendBox, extendSegment, labelPrice, logicalFromTime, logicalOf }
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
