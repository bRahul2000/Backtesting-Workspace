// Run with: node --test tests/tradingview_mode/frontend/
// (tests/tradingview_mode/test_frontend_views.py runs it from pytest.)
import assert from "node:assert/strict";
import test from "node:test";
import {
  filterPeriods, filterTrades, neighbours, pageOf, sortTrades, tradeView,
} from "../../../ui/tradingview_mode/component/frontend/src/tradeView.js";

function deepFreeze(value) {
  if (value && typeof value === "object") {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
}

const trades = () => deepFreeze([
  { key: 0, segment: 1, trade_id: 1, direction: "LONG", pnl: -25.0, r_multiple: -1.0, bars_held: 4, entry_time: 100, exit_time: 200, setup_id: "A4_LONG", exit_reason: "Stop loss" },
  { key: 1, segment: 1, trade_id: 2, direction: "SHORT", pnl: 75.5, r_multiple: 3.0, bars_held: 9, entry_time: 300, exit_time: 900, setup_id: "T3_SHORT", exit_reason: "Take profit" },
  { key: 2, segment: 2, trade_id: 1, direction: "LONG", pnl: 1e-12, r_multiple: 0.0, bars_held: 2, entry_time: 1000, exit_time: 1100, setup_id: "A4_LONG", exit_reason: "Stop loss (opening gap)" },
  { key: 3, segment: 2, trade_id: 2, direction: "LONG", pnl: 40.0, r_multiple: 1.6, bars_held: 9, entry_time: 1200, exit_time: 1500, setup_id: "A4_LONG", exit_reason: "Take profit" },
]);

test("filters select rows without modifying them", () => {
  const rows = trades();
  const snapshot = JSON.stringify(rows);
  assert.deepEqual(filterTrades(rows, "long").map((t) => t.key), [0, 2, 3]);
  assert.deepEqual(filterTrades(rows, "short").map((t) => t.key), [1]);
  assert.deepEqual(filterTrades(rows, "winners").map((t) => t.key), [1, 3]); // breakeven excluded
  assert.deepEqual(filterTrades(rows, "losers").map((t) => t.key), [0]);
  assert.equal(filterTrades(rows, "all").length, 4);
  assert.equal(JSON.stringify(rows), snapshot);
  assert.strictEqual(filterTrades(rows, "long")[0], rows[0]); // same row objects, values untouched
});

test("search matches trade id, segment/id, setup id and exit reason", () => {
  const rows = trades();
  assert.deepEqual(filterTrades(rows, "all", "t3_").map((t) => t.key), [1]);
  assert.deepEqual(filterTrades(rows, "all", "opening gap").map((t) => t.key), [2]);
  assert.deepEqual(filterTrades(rows, "all", "2/1").map((t) => t.key), [2]);
  assert.deepEqual(filterTrades(rows, "long", "take profit").map((t) => t.key), [3]);
});

test("sorting returns a new array and keeps the source order", () => {
  const rows = trades();
  assert.deepEqual(sortTrades(rows, "pnl", "desc").map((t) => t.key), [1, 3, 2, 0]);
  assert.deepEqual(sortTrades(rows, "bars_held", "desc").map((t) => t.key), [1, 3, 0, 2]); // tie keeps log order
  assert.deepEqual(sortTrades(rows, "exit_time", "asc").map((t) => t.key), [0, 1, 2, 3]);
  assert.deepEqual(rows.map((t) => t.key), [0, 1, 2, 3]);
});

test("previous/next navigate within the current view only", () => {
  const view = tradeView(trades(), { filter: "long", sortKey: "r_multiple", sortDir: "desc" });
  assert.deepEqual(view.map((t) => t.key), [3, 2, 0]);
  const middle = neighbours(view, 2);
  assert.equal(middle.previous.key, 3);
  assert.equal(middle.next.key, 0);
  assert.equal(neighbours(view, 3).previous, null);
  assert.equal(neighbours(view, 0).next, null);
  assert.equal(neighbours(view, 1).index, -1); // filtered out
  assert.equal(pageOf(view, 0, 2), 1);
});

test("period filter uses Python pnl only", () => {
  const rows = deepFreeze([{ period: "2026-01", pnl: 10 }, { period: "2026-02", pnl: -3 }, { period: "2026-03", pnl: 0 }]);
  assert.deepEqual(filterPeriods(rows, "winning").map((r) => r.period), ["2026-01"]);
  assert.deepEqual(filterPeriods(rows, "losing").map((r) => r.period), ["2026-02"]);
  assert.equal(filterPeriods(rows, "all").length, 3);
});

test("rows without a value (open in Replay) sort last in both directions", () => {
  const rows = deepFreeze([
    { key: 0, pnl: 5, entry_time: 1 }, { key: 1, status: "open", entry_time: 2 }, { key: 2, pnl: -3, entry_time: 3 },
  ]);
  assert.deepEqual(sortTrades(rows, "pnl", "asc").map((t) => t.key), [2, 0, 1]);
  assert.deepEqual(sortTrades(rows, "pnl", "desc").map((t) => t.key), [0, 2, 1]);
  assert.deepEqual(filterTrades(rows, "winners").map((t) => t.key), [0]); // open trade has no outcome
});
