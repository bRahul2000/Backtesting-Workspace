import { test } from "node:test";
import assert from "node:assert/strict";
import { blobUrls, hydrate, isBlob } from "../../../ui/tradingview_mode/component/frontend/src/blobs.js";

const files = new Map([
  ["/media/a.json", [{ time: 1, v: 1 }, { time: 2, v: 2 }]],
  ["/media/big.json", { catalog: [1, 2, 3], inner: { $blob: "/media/a.json", tail: [{ time: 3, v: 3 }] } }],
]);
let fetches = 0;
const fetcher = async (url) => { fetches += 1; return { ok: files.has(url), status: files.has(url) ? 200 : 404, json: async () => structuredClone(files.get(url)) }; };

test("markers rebuild exactly the original payload, nested markers included", async () => {
  const payload = { ack: "x-1", bars: { $blob: "/media/a.json", tail: [{ time: 3, v: 3 }] }, tester: { $json: "/media/big.json" }, small: [1, 2] };
  assert.deepEqual([...blobUrls(payload)].sort(), ["/media/a.json", "/media/big.json"]);
  const full = await hydrate(payload, fetcher);
  assert.deepEqual(full.bars, [{ time: 1, v: 1 }, { time: 2, v: 2 }, { time: 3, v: 3 }]);
  assert.deepEqual(full.tester, { catalog: [1, 2, 3], inner: [{ time: 1, v: 1 }, { time: 2, v: 2 }, { time: 3, v: 3 }] });
  assert.deepEqual(full.small, [1, 2]);
  assert.equal(full.ack, "x-1");
});

test("a file is fetched once while in use; only the inline tail changes in Live", async () => {
  fetches = 0;
  const poll = (v) => ({ bars: { $blob: "/media/a.json", tail: [{ time: 3, v }] } });
  const one = await hydrate(poll(3), fetcher);
  const two = await hydrate(poll(4), fetcher);
  assert.equal(fetches, 0);                                  // already cached by URL above
  assert.equal(one.bars.at(-1).v, 3);
  assert.equal(two.bars.at(-1).v, 4);
  assert.notEqual(one.bars, two.bars);                       // fresh objects every time: no shared mutation
});

test("a missing file rejects (the terminal then keeps its view and asks Python to resync)", async () => {
  await assert.rejects(hydrate({ bars: { $blob: "/media/gone.json", tail: [] } }, fetcher), /404/);
  assert.equal(isBlob({ $blob: "/x", other: 1 }), false);    // ordinary objects are never mistaken for markers
});
