// Browser acceptance: P3.1 Pine strategies (broker emulator, simulation only) in the real terminal (production build):
// historical report and markers, Replay (no trade after the cursor), Live paper.
//
//   node chart_view.mjs <app-url> <chrome-binary>
//
// Real mouse input only (drag to pan, wheel to zoom, move for the crosshair).
// Chart state is read through the engine's read-only test hook (window.__tvChart).
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, chromePath] = process.argv.slice(2);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "tv-pine-"));
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
    return { found: true, x: f.x + cx, y: f.y + cy, disabled: !!el.disabled, active: el.classList.contains('is-active'),
             visible: r.width > 0 && r.height > 0 && !!top && (top === el || el.contains(top)), text: el.innerText.trim() }; },
  synced() { const s = this.find('.sync'); return !!s && s.innerText.trim() === 'Synced'; },
  text(sel) { const e = this.find(sel); return e ? e.innerText.replace(/\\s+/g, ' ').trim() : null; },
  chart() { const c = this.win() && this.win().__tvChart; return c ? c.debugState() : null; },
  host() { const r = this.find('.chart-host').getBoundingClientRect(); const f = this.frameEl().getBoundingClientRect();
    return { x: f.x + r.x, y: f.y + r.y, w: r.width, h: r.height }; },
  xOf(time) { return this.win().__tvChart.coordinateOf(time); },
  bar(index) { return this.win().__tvChart.bars[index]; },
  pine() { const c = this.win().__tvChart; return c.pine.scripts.map((s) => ({ id: s.id, title: s.title, pane: s.pane,
    plots: [...s.plots.values()].map((p) => ({ title: p.title, n: p.data.length, last: p.data.filter((d) => d.value !== undefined).at(-1) })),
    fills: s.fills.size, shapes: s.shapes.size, hlines: s.hlines.size })); },
  panes() { return this.win().__tvChart.chart.panes().length; },
  drawings() { const s = this.win().__tvChart.pine.scripts[0]; const d = s && s.drawings && s.drawings.data;
    return d ? { lines: d.lines.length, labels: d.labels.length, boxes: d.boxes.length, linefills: d.linefills.length,
                 first: d.first_bar_index, maxBar: Math.max(-1, ...[...d.lines, ...d.labels, ...d.boxes, ...d.linefills].map((i) => i.bar)),
                 lineX2: d.lines.length ? d.lines[0].x2 : null, tables: (d.tables || []).length,
                 cells: (d.tables || []).flatMap((t) => t.cells.map((c) => c.text)) } : null; },
  barCount() { return this.win().__tvChart.bars.length; },
  strategyMarkers() { const m = this.win().__tvChart.pine.strategyMarkers; return m ? m.markers().length : 0; },
  lastMarkerTime() { const m = this.win().__tvChart.pine.strategyMarkers; const all = m ? m.markers() : []; return all.length ? all[all.length - 1].time : null; },
  reportRows() { return [...this.doc().querySelectorAll('.pine-trades tbody tr')].length; },
  reportText() { const e = this.doc().querySelector('.pine-strategy'); return e ? e.innerText.replace(/\\s+/g, ' ').trim() : null; },
  lastBar() { const b = this.win().__tvChart.bars; return b.length ? b[b.length - 1].time : null; },
  setText(value) { const t = this.doc().querySelector('.pine-text'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(t, value);
    t.dispatchEvent(new Event('input', { bubbles: true })); return true; },
  example(name) { const s = this.doc().querySelector('.pine-examples'); Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, name);
    s.dispatchEvent(new Event('change', { bubbles: true })); return this.doc().querySelector('.pine-text').value.length; },
  problems() { return [...this.doc().querySelectorAll('.pine-diag')].map((d) => d.innerText.replace(/\\s+/g, ' ').trim()); },
  legendNames() { return [...this.doc().querySelectorAll('.lg-ind-name')].map((d) => d.innerText.trim()); },
  legend() { const d = this.doc(); const row = d.querySelector('.lg-ohlc'); if (!row) return null;
    const spans = [...row.querySelectorAll('span')].map((s) => s.innerText.trim());
    return { time: d.querySelector('.lg-time')?.innerText.trim(), hover: d.querySelector('.lg-time')?.classList.contains('is-hover'), spans }; },
};`;

const SCRIPT = `//@version=5
strategy("Donchian Breakout", overlay=true, initial_capital=10000,
     default_qty_type=strategy.fixed, default_qty_value=1)
length     = input.int(20, "Channel length", minval=2, maxval=200, group="Channel")
trailTicks = input.int(300, "Trail offset (ticks)", minval=1, group="Exit")
trailStart = input.int(150, "Trail trigger (ticks)", minval=1, group="Exit")
upper = ta.highest(high, length)
lower = ta.lowest(low, length)
if close >= upper[1]
    strategy.entry("Long", strategy.long)
if close <= lower[1]
    strategy.entry("Short", strategy.short)
strategy.exit("Trail", trail_points=trailStart, trail_offset=trailTicks)
plot(upper, title="Upper", color=color.green)
plot(lower, title="Lower", color=color.red)
`;

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
  const settle = async () => { await sleep(250); await waitFor("window.__tv && __tv.synced()"); await sleep(350); };
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

  // Historical: the strategy runs, its fills become chart markers and the report lists the trades.
  await click("Pine Editor tab", ".bottom-tab", "Pine Editor"); await settle();
  await evaluate(`__tv.setText(${JSON.stringify(SCRIPT)})`); await settle();
  await click("Add to chart", ".pine-add"); await settle();
  check("historical: strategy fills are chart markers", await waitFor(`__tv.strategyMarkers() > 10`, 20000), String(await evaluate("__tv.strategyMarkers()")));
  await click("Pine Strategy tab", ".bottom-tab", "Pine Strategy"); await settle();
  check("historical: report lists the trades", await waitFor(`__tv.reportRows() > 5`, 15000), String(await evaluate("__tv.reportRows()")));
  const text = await evaluate("__tv.reportText()");
  check("historical: report is labelled simulation only", /simulated \(broker emulator\) · no broker orders/.test(text || ""), text);
  check("historical: report shows net profit and profit factor", /Net profit/.test(text) && /Profit factor/.test(text), text);
  if (process.env.PINE_SHOTS) {
    const { writeFileSync } = await import("node:fs");
    writeFileSync(`${process.env.PINE_SHOTS}/strategy_historical.png`, Buffer.from((await send("Page.captureScreenshot", { format: "png" })).data, "base64"));
  }

  // Replay: nothing after the cursor.
  await click("Replay", ".mode-btn", "Replay"); await sleep(400);
  await evaluate(`(() => { const i = __tv.doc().querySelector('.popover input[type=date]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, '2026-06-10'); i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await click("Start replay", ".popover .btn.primary", "Start replay"); await settle();
  await waitFor(`__tv.strategyMarkers() > 0`, 15000);
  const lastBar = await evaluate("__tv.lastBar()"), lastMarker = await evaluate("__tv.lastMarkerTime()");
  check("replay: no strategy fill after the cursor", lastMarker !== null && lastMarker <= lastBar, JSON.stringify({ lastBar, lastMarker }));
  await click("Next bar", ".replay-bar .rp-btn", "▶︎|"); await settle();
  check("replay step: still nothing after the cursor", (await evaluate("__tv.lastMarkerTime()")) <= (await evaluate("__tv.lastBar()")));
  await click("Exit Replay", ".replay-bar .rp-btn", "✕ Exit"); await settle();

  // Live paper (real Binance data, simulated orders only).
  await click("Live", ".mode-btn", "Live"); await settle();
  await click("Go Live", ".go-live"); await settle();
  check("live: LIVE", await waitFor(`__tv.text('.live-state') === 'LIVE'`, 40000), await evaluate("__tv.text('.live-bar')"));
  check("live paper: the report is present", await waitFor(`__tv.reportRows() > 0`, 20000), String(await evaluate("__tv.reportRows()")));
  await sleep(3000);
  check("live paper: no fill after the latest bar", (await evaluate("__tv.lastMarkerTime()")) <= (await evaluate("__tv.lastBar()")));
  await click("Exit Live", ".live-bar .rp-btn", "✕ Exit"); await settle();
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
