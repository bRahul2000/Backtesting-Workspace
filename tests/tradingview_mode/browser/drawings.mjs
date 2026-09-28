// Browser acceptance: P2.3a drawing objects in the real terminal (production build), historical, Replay, Live.
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
                 lineX2: d.lines.length ? d.lines[0].x2 : null } : null; },
  barCount() { return this.win().__tvChart.bars.length; },
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

const fmt = (v, p) => Number(v).toLocaleString("en-US", { minimumFractionDigits: p, maximumFractionDigits: p });
const utc = (t) => { const d = new Date(t * 1000); const z = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${z(d.getUTCMonth() + 1)}-${z(d.getUTCDate())} ${z(d.getUTCHours())}:${z(d.getUTCMinutes())} UTC`; };
const sameRange = (a, b) => !!a && !!b && a.from === b.from && a.to === b.to;

const SCRIPT = `//@version=6
indicator("Drawings smoke", overlay = true, max_lines_count = 50, max_labels_count = 50, max_boxes_count = 50)
var line trend = line.new(bar_index, close, bar_index, close, extend = extend.right, color = color.orange, width = 2)
line.set_xy2(trend, bar_index, close)
var line base = line.new(bar_index, low, bar_index, low, color = color.teal)
line.set_xy2(base, bar_index, low)
var linefill band = linefill.new(trend, base, color.new(color.teal, 85))
if bar_index % 20 == 0
    label.new(bar_index, high, "L" + str.tostring(bar_index), style = label.style_label_down)
    box.new(bar_index, high, bar_index + 5, low, bgcolor = color.new(color.blue, 85))
plot(close, "close", display = display.none)
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

  // Historical: the drawing script is added and its objects reach the chart layer.
  await click("Pine Editor tab", ".bottom-tab", "Pine Editor"); await settle();
  await evaluate(`__tv.setText(${JSON.stringify(SCRIPT)})`); await settle();
  await click("Add to chart", ".pine-add"); await settle();
  check("historical: drawings on the chart layer", await waitFor(`(() => { const d = __tv.drawings(); return d && d.lines === 2 && d.linefills === 1 && d.labels > 0 && d.boxes > 0; })()`, 20000), JSON.stringify(await evaluate("__tv.drawings()")));
  const hist = await evaluate("__tv.drawings()");
  if (process.env.PINE_SHOTS) {
    const { writeFileSync } = await import("node:fs");
    writeFileSync(`${process.env.PINE_SHOTS}/drawings_historical.png`, Buffer.from((await send("Page.captureScreenshot", { format: "png" })).data, "base64"));
  }
  check("historical: trend line ends on the last bar", hist && hist.first + hist.lineX2 === (await evaluate("__tv.barCount()")) - 1, JSON.stringify(hist));

  // Replay: only revealed bars; the trend follows the cursor.
  await click("Replay", ".mode-btn", "Replay"); await sleep(400);
  await evaluate(`(() => { const i = __tv.doc().querySelector('.popover input[type=date]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, '2026-06-10'); i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await click("Start replay", ".popover .btn.primary", "Start replay"); await settle();
  await waitFor(`__tv.drawings() && __tv.drawings().lines === 2`, 15000);
  let r = await evaluate("__tv.drawings()"), bars = await evaluate("__tv.barCount()");
  check("replay: no drawing from after the cursor", r && r.first + r.maxBar <= bars - 1 && r.first + r.lineX2 === bars - 1, JSON.stringify({ r, bars }));
  await click("Next bar", ".replay-bar .rp-btn", "▶︎|"); await settle();
  const r2 = await evaluate("__tv.drawings()"), bars2 = await evaluate("__tv.barCount()");
  check("replay step: the trend line advances with the cursor", r2 && bars2 === bars + 1 && r2.first + r2.lineX2 === bars2 - 1, JSON.stringify({ r2, bars2 }));
  await click("Exit Replay", ".replay-bar .rp-btn", "✕ Exit"); await settle();

  // Live (real Binance): drawings update with the forming bar; the chart is not reloaded.
  await click("Live", ".mode-btn", "Live"); await settle();
  await click("Go Live", ".go-live"); await settle();
  check("live: LIVE", await waitFor(`__tv.text('.live-state') === 'LIVE'`, 40000), await evaluate("__tv.text('.live-bar')"));
  check("live: drawings present", await waitFor(`__tv.drawings() && __tv.drawings().lines === 2`, 20000), JSON.stringify(await evaluate("__tv.drawings()")));
  const start = await evaluate("__tv.win().__tvChart.debugState().stats");
  await sleep(4000);
  const end = await evaluate("__tv.win().__tvChart.debugState().stats");
  const live = await evaluate("__tv.drawings()");
  check("live: polls arrive without a chart reload", end.updates > start.updates && end.setData === start.setData, JSON.stringify({ start, end }));
  check("live: trend line on the forming bar", live && live.first + live.lineX2 === (await evaluate("__tv.barCount()")) - 1, JSON.stringify(live));
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
