import assert from "node:assert/strict";
import test from "node:test";
import {
  controls, intervalMs, statusText, tickAction, utcParts, utcText,
} from "../../../ui/tradingview_mode/component/frontend/src/replayControls.js";

const replay = (over = {}) => ({
  enabled: true, cursor_timestamp: 1781101800, cursor_index: 411, total_available_bars: 2840,
  speed: 5, playing: false, at_start: false, at_end: false, ...over,
});

test("speeds map to bar intervals", () => {
  assert.deepEqual([1, 2, 5, 10].map(intervalMs), [1000, 500, 200, 100]);
  assert.equal(intervalMs(99), 1000);
});

test("boundaries disable previous / next / play", () => {
  assert.equal(controls(replay({ at_start: true })).back, false);
  assert.equal(controls(replay({ at_end: true })).forward, false);
  assert.equal(controls(replay({ at_end: true })).play, false);
  assert.equal(controls(replay({ playing: true })).forward, false);
  assert.equal(controls(replay({ playing: true })).pause, true);
  assert.equal(controls(replay(), true).forward, false); // waiting for Python
  assert.equal(controls({ enabled: false }).exit, false);
});

test("playback steps only when playing, idle and not at the end", () => {
  assert.equal(tickAction(replay({ playing: true }), true), "step");
  assert.equal(tickAction(replay({ playing: true }), false), "wait");
  assert.equal(tickAction(replay({ playing: true, at_end: true }), true), "stop");
  assert.equal(tickAction(replay(), true), "stop");
});

test("status and UTC helpers", () => {
  assert.equal(statusText(replay()), "REPLAY · 2026-06-10 14:30 UTC · 412 / 2,840 · 5x · PAUSED");
  assert.deepEqual(utcParts(1781101800), { date: "2026-06-10", time: "14:30" });
  assert.equal(utcText("2026-06-10", "14:37"), "2026-06-10T14:37");
  assert.equal(utcText("2026-06-10", ""), "2026-06-10T00:00");
});
