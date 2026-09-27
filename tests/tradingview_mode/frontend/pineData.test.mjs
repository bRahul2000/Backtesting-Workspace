import { test } from "node:test";
import assert from "node:assert/strict";
import { firstColor, seriesData } from "../../../ui/tradingview_mode/component/frontend/src/chart/pineData.js";

const points = [
  { time: 1, value: 1.5, color: "rgba(1,2,3,1)" },
  { time: 2, value: null, color: "rgba(1,2,3,1)" },
  { time: 3, value: 2.5, color: null },
];

test("line connects across na; linebr breaks with whitespace", () => {
  assert.deepEqual(seriesData({ style: "line", data: points }).map((p) => p.time), [1, 3]);
  assert.deepEqual(seriesData({ style: "linebr", data: points }), [
    { time: 1, value: 1.5, color: "rgba(1,2,3,1)" }, { time: 2 }, { time: 3, value: 2.5, color: "rgba(0,0,0,0)" }]);
});

test("na color is transparent; area gets faded fills; histogram skips na", () => {
  const area = seriesData({ style: "area", data: points });
  assert.equal(area[0].lineColor, "rgba(1,2,3,1)");
  assert.equal(area[0].topColor, "rgba(1,2,3,0.35)");
  assert.deepEqual(seriesData({ style: "histogram", data: points }).map((p) => p.time), [1, 3]);
  assert.equal(firstColor({ data: [{ color: null }, { color: "rgba(9,9,9,1)" }] }), "rgba(9,9,9,1)");
});
