import assert from "node:assert/strict";
import test from "node:test";
import { formatAge, pollAction, quoteText, statusClass, tailUpdate, utcClock } from "../../../ui/tradingview_mode/component/frontend/src/liveControls.js";

test("polling only while live and idle", () => {
  assert.equal(pollAction({ enabled: true, phase: "streaming" }, true), "poll");
  assert.equal(pollAction({ enabled: true, phase: "streaming" }, false), "wait");
  assert.equal(pollAction({ enabled: true, phase: "setup" }, true), "stop"); // nothing is read before Go Live
  assert.equal(pollAction({ enabled: false }, true), "stop");
  assert.equal(pollAction(undefined, true), "stop");
});

test("status, age, clock and broker digits formatting", () => {
  assert.equal(statusClass("LIVE"), "live");
  assert.equal(statusClass("STALE"), "stale");
  assert.equal(statusClass("nonsense"), "disconnected");
  assert.equal(formatAge(0.84), "0.8s");
  assert.equal(formatAge(125), "2m");
  assert.equal(utcClock(1790277723), "19:22:03 UTC");
  assert.equal(quoteText(80351.2, 2), "80,351.20");
  assert.equal(quoteText(4380.1, 3), "4,380.100");
  assert.equal(quoteText(null, 2), "—");
});

test("tail updates only when the window did not slide", () => {
  const bars = (times, close = 1) => times.map((time) => ({ time, close }));
  assert.deepEqual(tailUpdate(bars([1, 2, 3]), bars([1, 2, 3], 5)), bars([3], 5));        // forming bar changed
  assert.deepEqual(tailUpdate(bars([1, 2, 3]), bars([1, 2, 3, 4])).map((b) => b.time), [3, 4]); // rollover append
  assert.equal(tailUpdate(bars([1, 2, 3]), bars([2, 3, 4])), null);                         // window slid → full reset
  assert.equal(tailUpdate([], bars([1])), null);
  assert.equal(tailUpdate(bars([1, 2, 3]), bars([1, 5, 3])), null);
});
