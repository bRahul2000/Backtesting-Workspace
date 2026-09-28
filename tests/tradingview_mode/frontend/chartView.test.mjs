import { test } from "node:test";
import assert from "node:assert/strict";
import {
  diffSeries, isAtLatest, samePoint, shiftedRange, tickLabel, utcLabel, wantsOlderHistory,
} from "../../../ui/tradingview_mode/component/frontend/src/chart/chartView.js";

const T0 = 1790319600; // 2026-09-25 07:00 UTC
const bar = (i, close = 100, volume = 1) => ({ time: T0 + i * 900, open: 100, high: 110, low: 90, close, volume });
const bars = (from, to, overrides = {}) => Array.from({ length: to - from }, (_, k) => overrides[from + k] ?? bar(from + k));

test("forming candle change is a single series.update", () => {
  const prev = bars(0, 2000);
  const next = bars(0, 2000, { 1999: bar(1999, 104, 3) });
  assert.deepEqual(diffSeries(prev, next), { kind: "tail", updates: [bar(1999, 104, 3)] });
  assert.deepEqual(diffSeries(prev, bars(0, 2000)), { kind: "none" });
});

test("a new candle appends once (with the finalized previous candle)", () => {
  const prev = bars(0, 2000);
  const next = bars(0, 2001, { 1999: bar(1999, 101) });
  const diff = diffSeries(prev, next);
  assert.equal(diff.kind, "tail");
  assert.deepEqual(diff.updates.map((b) => b.time), [bar(1999).time, bar(2000).time]);
  assert.deepEqual(diffSeries(prev, bars(0, 2001)).updates.map((b) => b.time), [bar(2000).time]); // unchanged final: append only
});

test("a changed completed candle is never skipped: full replace", () => {
  const prev = bars(0, 2000);
  assert.deepEqual(diffSeries(prev, bars(0, 2000, { 1500: bar(1500, 99) })), { kind: "replace", shift: 0 });
  assert.deepEqual(diffSeries(prev, bars(0, 2001, { 10: bar(10, 1) })), { kind: "replace", shift: 0 });
});

test("prepended history replaces with the exact shift; a slid window shifts back", () => {
  const prev = bars(1000, 3000);
  assert.deepEqual(diffSeries(prev, bars(0, 3000)), { kind: "replace", shift: 1000 });
  assert.deepEqual(diffSeries(prev, bars(1001, 3001)), { kind: "replace", shift: -1 });
  assert.deepEqual(diffSeries(prev, bars(5000, 5010)), { kind: "replace", shift: null }); // nothing shared
  assert.deepEqual(diffSeries([], bars(0, 3)), { kind: "replace", shift: null });
});

test("indicator points diff the same way", () => {
  const points = (n, last = 1) => Array.from({ length: n }, (_, i) => ({ time: T0 + i * 900, value: i === n - 1 ? last : i }));
  assert.deepEqual(diffSeries(points(50), points(50, 7), samePoint), { kind: "tail", updates: [{ time: T0 + 49 * 900, value: 7 }] });
  assert.equal(diffSeries(points(50), points(51, 50), samePoint).kind, "tail");
  const warm = points(50).slice(5);  // warm-up shifted after prepending history
  assert.equal(diffSeries(warm, points(50), samePoint).kind, "replace");
});

test("visible range is shifted, never reset", () => {
  assert.deepEqual(shiftedRange({ from: 120.5, to: 300.5 }, 1000), { from: 1120.5, to: 1300.5 });
  assert.deepEqual(shiftedRange({ from: 120.5, to: 300.5 }, 0), { from: 120.5, to: 300.5 });
  assert.equal(shiftedRange({ from: 1, to: 2 }, null), null);
  assert.equal(shiftedRange(null, 3), null);
});

test("follow mode only while the newest candle is in view", () => {
  assert.equal(isAtLatest({ from: 1800, to: 2005 }, 2000), true);   // right offset past the last bar
  assert.equal(isAtLatest({ from: 1800, to: 1998.2 }, 2000), true);  // right at it
  assert.equal(isAtLatest({ from: 1500, to: 1700 }, 2000), false);   // panned back
  assert.equal(isAtLatest(null, 2000), false);
});

test("older history is requested once per left edge", () => {
  const first = T0;
  assert.equal(wantsOlderHistory({ from: 10, to: 200 }, { more: true, firstTime: first, requestedFor: null }), true);
  assert.equal(wantsOlderHistory({ from: 10, to: 200 }, { more: true, firstTime: first, requestedFor: first }), false);
  assert.equal(wantsOlderHistory({ from: 500, to: 700 }, { more: true, firstTime: first, requestedFor: null }), false);
  assert.equal(wantsOlderHistory({ from: 10, to: 200 }, { more: false, firstTime: first, requestedFor: null }), false);
});

test("explicit UTC labels", () => {
  assert.equal(utcLabel(1790323200), "2026-09-25 08:00 UTC");
  assert.equal(utcLabel(null), "—");
  assert.equal(tickLabel(1790323200, 3), "08:00");       // intraday time
  assert.equal(tickLabel(1790294400, 2), "Sep 25");      // day transition shows the date
  assert.equal(tickLabel(1790294400, 1), "Sep 2026");
  assert.equal(tickLabel(1767225600, 0), "2026");
  // Independent of the process time zone.
  const tz = process.env.TZ;
  process.env.TZ = "Asia/Kolkata";
  assert.equal(utcLabel(1790323200), "2026-09-25 08:00 UTC");
  process.env.TZ = tz;
});
