// Browser acceptance: Rahul's exact "Gold Range Hunter - Monthly Profiles V2" strategy (572-line fixture) in the real
// terminal (production build): paste -> Compile -> Add to chart -> Pine Strategy report -> remove / re-add.
//
//   node gold_range_hunter.mjs <app-url> <chrome-binary> <fixture.pine>
//
// The strategy executes only inside Replay with the cursor before 2026-06-03 (Gold V2 sealed windows start there), so
// no bar from that date on is ever executed by the script. Simulation only: no broker order exists anywhere.
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, chromePath, fixture] = process.argv.slice(2);
const SOURCE = readFileSync(fixture, "utf8");
const CURSOR = "2026-06-01";
const SEALED_MS = Date.parse("2026-06-03T00:00:00Z");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "tv-grh-"));
const chrome = spawn(chromePath, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "--window-size=1440,900", "about:blank"], { stdio: "ignore" });
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail: String(detail).slice(0, 700) }); };
const note = (name, detail) => results.push({ name, ok: true, detail: String(detail).slice(0, 700) });

async function cdp() {
  const portFile = join(profile, "DevToolsActivePort");
  for (let i = 0; i < 100 && !existsSync(portFile); i++) await sleep(100);
  const port = readFileSync(portFile, "utf8").split("\n")[0];
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve) => { ws.onopen = resolve; });
  let id = 0;
  const pending = new Map();
  ws.onmessage = (message) => {
    const data = JSON.parse(message.data);
    if (data.id && pending.has(data.id)) { pending.get(data.id)(data); pending.delete(data.id); }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const n = ++id;
    pending.set(n, (data) => (data.error ? reject(new Error(`${method}: ${data.error.message}`)) : resolve(data.result)));
    ws.send(JSON.stringify({ id: n, method, params }));
  });
  return { ws, send };
}

const HELPERS = `window.__tv = {
  frameEl() { return document.querySelector('iframe[title*="tradingview_terminal"]'); },
  doc() { const f = this.frameEl(); return f && f.contentDocument; },
  win() { const f = this.frameEl(); return f && f.contentWindow; },
  find(sel, text) { const d = this.doc(); if (!d) return null; const all = [...d.querySelectorAll(sel)];
    return text === undefined ? all[0] || null : all.find((e) => e.innerText.trim().startsWith(text)) || null; },
  box(sel, text) { const el = this.find(sel, text); if (!el) return { found: false };
    const r = el.getBoundingClientRect(); const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
    const top = this.doc().elementFromPoint(cx, cy); const f = this.frameEl().getBoundingClientRect();
    return { found: true, x: f.x + cx, y: f.y + cy, disabled: !!el.disabled,
             visible: r.width > 0 && r.height > 0 && !!top && (top === el || el.contains(top)), text: el.innerText.trim() }; },
  synced() { const s = this.find('.sync'); return !!s && s.innerText.trim() === 'Synced'; },
  text(sel) { const e = this.find(sel); return e ? e.innerText.replace(/\\s+/g, ' ').trim() : null; },
  pine() { const c = this.win().__tvChart; return c.pine.scripts.map((s) => ({ id: s.id, title: s.title })); },
  drawings() { const s = this.win().__tvChart.pine.scripts[0]; const d = s && s.drawings && s.drawings.data;
    return d ? { lines: d.lines.length, labels: d.labels.length, boxes: d.boxes.length,
                 maxBar: Math.max(-1, ...[...d.lines, ...d.labels, ...d.boxes].map((i) => i.bar)) } : null; },
  strategyMarkers() { const m = this.win().__tvChart.pine.strategyMarkers; return m ? m.markers().length : 0; },
  markerTexts() { const m = this.win().__tvChart.pine.strategyMarkers; return m ? m.markers().map((x) => x.text) : []; },
  lastMarkerTime() { const m = this.win().__tvChart.pine.strategyMarkers; const all = m ? m.markers() : []; return all.length ? all[all.length - 1].time : null; },
  reportRows() { return [...this.doc().querySelectorAll('.pine-trades tbody tr')].length; },
  reportText() { const e = this.doc().querySelector('.pine-strategy'); return e ? e.innerText.replace(/\\s+/g, ' ').trim() : null; },
  lastBar() { const b = this.win().__tvChart.bars; return b.length ? b[b.length - 1].time : null; },
  setText(value) { const t = this.doc().querySelector('.pine-text'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(t, value);
    t.dispatchEvent(new Event('input', { bubbles: true })); return t.value.length; },
  problems() { return [...this.doc().querySelectorAll('.pine-diag')].map((d) => d.innerText.replace(/\\s+/g, ' ').trim()); },
  logs() { return [...this.doc().querySelectorAll('.log-msg')].map((d) => d.innerText.trim()); },
  timeInputs() { return [...this.doc().querySelectorAll('.pine-input input[type=datetime-local]')].map((i) => i.value); },
};`;

async function main() {
  const { ws, send } = await cdp();
  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + " " + (r.exceptionDetails.exception?.description || ""));
    return r.result.value;
  };
  const waitFor = async (expression, ms = 30000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { try { if (await evaluate(expression)) return true; } catch { /* loading */ } await sleep(200); }
    return false;
  };
  const settle = async () => { await sleep(250); await waitFor("window.__tv && __tv.synced()", 60000); await sleep(350); };
  const click = async (name, sel, label) => {
    const b = await evaluate(`__tv.box(${JSON.stringify(sel)}, ${label === undefined ? "undefined" : JSON.stringify(label)})`);
    check(`${name}: visible and clickable`, b.found && b.visible && !b.disabled, JSON.stringify(b));
    if (!(b.found && b.visible && !b.disabled)) return false;
    for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x: b.x, y: b.y, button: "left", clickCount: 1 });
    return true;
  };
  const errors = [];
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Runtime.enable");
  ws.addEventListener("message", (m) => { const d = JSON.parse(m.data); if (d.method === "Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.text); });
  await send("Page.enable");
  await send("Page.navigate", { url });
  check("terminal loaded", await waitFor(`(() => { const f = document.querySelector('iframe[title*="tradingview_terminal"]'); return !!(f && f.contentDocument && f.contentDocument.querySelector('.terminal')); })()`, 90000));
  await evaluate(HELPERS);
  await settle();
  await click("watchlist XAUUSDm", ".wl-row", "XAUUSDm"); await settle();

  // Replay first: the script will only ever see bars before the cursor.
  await click("Replay", ".mode-btn", "Replay"); await sleep(400);
  await evaluate(`(() => { const i = __tv.doc().querySelector('.popover input[type=date]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, '${CURSOR}'); i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await click("Start replay", ".popover .btn.primary", "Start replay"); await settle();
  const cursorBar = await evaluate("__tv.lastBar()");
  check("replay cursor is before the sealed windows", cursorBar !== null && cursorBar * 1000 < SEALED_MS, String(cursorBar));

  // Paste the exact script, Compile.
  await click("Pine Editor tab", ".bottom-tab", "Pine Editor"); await settle();
  check("exact script pasted", (await evaluate(`__tv.setText(${JSON.stringify(SOURCE)})`)) === SOURCE.length);
  await click("Compile", ".pine-compile"); await settle();
  check("compile reports success", await waitFor(`(__tv.text('.pine-ok') || '').startsWith('✓ Compiled: Gold Range Hunter - Monthly Profiles V2')`, 30000),
    JSON.stringify(await evaluate("__tv.problems()")));
  check("no problems listed", (await evaluate("__tv.problems()")).length === 0, JSON.stringify(await evaluate("__tv.problems()")));

  // Add to chart.
  await click("Add to chart", ".pine-add"); await settle();
  check("script on chart", await waitFor(`__tv.pine().length === 1`, 60000), JSON.stringify(await evaluate("__tv.pine()")));
  check("strategy fills are chart markers", await waitFor(`__tv.strategyMarkers() > 5`, 60000), String(await evaluate("__tv.strategyMarkers()")));
  const drawings = await evaluate("__tv.drawings()");
  check("range boxes and entry / SL / TP lines are drawn", drawings && drawings.boxes > 10 && drawings.lines >= 15 && drawings.lines % 3 === 0 && drawings.labels === 0, JSON.stringify(drawings));
  const texts = await evaluate("__tv.markerTexts()");
  check("markers show the order comments (SETUP_* entries, TP / FULL_SL / TRAIL_SL exits)",
    texts.length > 0 && texts.every((t) => /^(SETUP_[ABC]_(BUY|SELL)|TP|FULL_SL|TRAIL_SL) [+-]/.test(t)), JSON.stringify(texts.slice(0, 8)));
  const lastMarker = await evaluate("__tv.lastMarkerTime()"), lastBar = await evaluate("__tv.lastBar()");
  check("no fill after the replay cursor", lastMarker !== null && lastMarker <= lastBar && lastBar * 1000 < SEALED_MS, JSON.stringify({ lastMarker, lastBar }));

  // Inputs: the two input.time() fields show the defaults as UTC date/times.
  await click("On chart tab", ".pine-tab", "On chart");
  await click("Inputs", ".pine-script[data-script='pine-1'] .rp-btn", "Inputs"); await settle();
  const times = await evaluate("__tv.timeInputs()");
  check("input.time fields show 2025-08-31 18:30 and 2030-12-31 18:29 UTC", JSON.stringify(times) === JSON.stringify(["2025-08-31T18:30", "2030-12-31T18:29"]), JSON.stringify(times));

  // Pine Strategy report and trades.
  await click("Pine Strategy tab", ".bottom-tab", "Pine Strategy"); await settle();
  check("report lists the trades", await waitFor(`__tv.reportRows() >= 5`, 30000), String(await evaluate("__tv.reportRows()")));
  const text = await evaluate("__tv.reportText()");
  check("report is labelled simulation only", /simulated \(broker emulator\) · no broker orders/.test(text || ""), text);
  check("report shows net profit and profit factor", /Net profit/.test(text) && /Profit factor/.test(text), text);
  const rows = await evaluate("__tv.reportRows()");
  note("report", `${rows} trade rows · ${String(text).slice(0, 400)}`);
  if (process.env.PINE_SHOTS) {
    const { writeFileSync } = await import("node:fs");
    writeFileSync(`${process.env.PINE_SHOTS}/gold_range_hunter.png`, Buffer.from((await send("Page.captureScreenshot", { format: "png" })).data, "base64"));
  }

  // Remove, re-add: the identical report comes back.
  await click("Pine Editor tab", ".bottom-tab", "Pine Editor"); await settle();
  await click("On chart tab", ".pine-tab", "On chart");
  await click("Remove", ".pine-script[data-script='pine-1'] .rp-btn.exit"); await settle();
  check("removed script leaves the chart", await waitFor(`__tv.pine().length === 0 && __tv.strategyMarkers() === 0`, 30000));
  await click("Add to chart again", ".pine-add"); await settle();
  check("re-added script on chart", await waitFor(`__tv.pine().length === 1 && __tv.strategyMarkers() > 5`, 60000));
  await click("Pine Strategy tab", ".bottom-tab", "Pine Strategy"); await settle();
  check("re-added report has the same trades", await waitFor(`__tv.reportRows() === ${rows}`, 30000), `${rows} vs ${await evaluate("__tv.reportRows()")}`);

  await click("Logs tab", ".bottom-tab", "Logs"); await settle();
  const logs = await evaluate("__tv.logs()");
  check("no 'Pine script not added' rejection", logs.every((m) => !/Pine script not added/.test(m)), JSON.stringify(logs.slice(-8)));
  // Replay is not exited: that would run the script over every bar, including the sealed windows.
  check("no page errors", errors.length === 0, JSON.stringify(errors));
  ws.close();
}

try {
  await main();
} catch (error) {
  check("script completed", false, String(error && error.stack || error));
} finally {
  chrome.kill("SIGKILL");
  await sleep(300);
  try { rmSync(profile, { recursive: true, force: true }); } catch { /* ignore */ }
  console.log(JSON.stringify(results, null, 1));
  process.exit(results.every((r) => r.ok) ? 0 : 1);
}
