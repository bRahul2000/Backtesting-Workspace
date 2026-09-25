// Browser acceptance: Chart / Signals / Execution source roles (production build, real Binance).
//
//   node live_button.mjs <app-url> <chrome-binary> <python> <synthetic-feed-script> <mt5-folder>
//
// Drives Chrome over the DevTools protocol with Node's built-in WebSocket (no
// npm dependencies). Every button click is a real mouse event at screen
// coordinates, and before each click the target must be the topmost painted
// element at its centre — so a control hidden by clipping/overlays fails (this
// is how the clipped Live/Replay popovers once escaped DOM-level tests).
// <select> values are set the way a keyboard choice would set them.
//
// MT5 is OFF at the start: <mt5-folder> is empty and nothing writes to it until
// flow D starts the synthetic MT5 bridge.
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, chromePath, python, feedScript, mt5Folder] = process.argv.slice(2);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "tv-live-"));
const chrome = spawn(chromePath, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "--window-size=1440,900", "about:blank"], { stdio: "ignore" });
let feed = null;
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail: String(detail).slice(0, 600) }); };
const note = (name, detail) => results.push({ name, ok: true, detail: String(detail).slice(0, 600) });

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
  doc() { const f = document.querySelector('iframe[title*="tradingview_terminal"]'); return f && f.contentDocument; },
  frame() { return document.querySelector('iframe[title*="tradingview_terminal"]').getBoundingClientRect(); },
  find(sel, text) { const d = this.doc(); if (!d) return null; const all = [...d.querySelectorAll(sel)];
    return text === undefined ? all[0] || null : all.find((e) => e.innerText.trim().startsWith(text)) || null; },
  box(sel, text) { const el = this.find(sel, text); if (!el) return { found: false };
    const r = el.getBoundingClientRect(); const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
    const top = this.doc().elementFromPoint(cx, cy); const f = this.frame();
    return { found: true, x: f.x + cx, y: f.y + cy, disabled: !!el.disabled, active: el.classList.contains('is-active'),
             visible: r.width > 0 && r.height > 0 && !!top && (top === el || el.contains(top)), text: el.innerText.trim(),
             topmost: top ? (top.tagName + '.' + String(top.className)).slice(0, 80) : null }; },
  synced() { const s = this.find('.sync'); return !!s && s.innerText.trim() === 'Synced'; },
  text(sel) { const e = this.find(sel); return e ? e.innerText.replace(/\\s+/g, ' ').trim() : null; },
  texts(sel) { const d = this.doc(); return d ? [...d.querySelectorAll(sel)].map((e) => e.innerText.replace(/\\s+/g, ' ').trim()) : []; },
  choose(label, value) { const s = this.doc().querySelector('select[aria-label="' + label + '"]'); if (!s) return false;
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, value);
    s.dispatchEvent(new Event('change', { bubbles: true })); return true; },
  value(label) { const s = this.doc().querySelector('select[aria-label="' + label + '"]'); return s ? s.value : null; },
  quotes() { return Object.fromEntries([...this.doc().querySelectorAll('.live-q')].map((q) => [q.dataset.quote, q.querySelector('b').innerText.trim()])); },
  watch() { return [...this.doc().querySelectorAll('.wl-row.is-live-row')].map((r) => r.innerText.replace(/\\s+/g, ' ').trim()); },
  source() { const b = this.find('.live-bar'); return b ? b.dataset.source || null : null; },
  role(name) { const r = this.doc().querySelector('.src-role[data-role="' + name + '"]'); if (!r) return null;
    return { name: r.querySelector('.src-name').innerText.trim(), state: r.querySelector('.src-state').innerText.replace(/[●○]/g, '').trim(),
             detail: r.querySelector('.src-detail')?.innerText.trim() || null }; },
  strip() { const s = this.find('.source-strip'); return s ? { ready: s.classList.contains('is-ready'), note: s.querySelector('.src-note').innerText.trim() } : null; },
  updates() { return this.doc().defaultView.__tvChart.debugState().stats.updates; },
};`;

async function main() {
  const { ws, send } = await cdp();
  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
    return r.result.value;
  };
  const waitFor = async (expression, ms = 30000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { try { if (await evaluate(expression)) return true; } catch { /* page loading */ } await sleep(150); }
    return false;
  };
  const settle = async () => { await sleep(250); await waitFor("window.__tv && __tv.synced()"); await sleep(300); };
  const box = (sel, text) => evaluate(`__tv.box(${JSON.stringify(sel)}, ${text === undefined ? "undefined" : JSON.stringify(text)})`);
  const text = (sel) => evaluate(`__tv.text(${JSON.stringify(sel)})`);
  const click = async (name, sel, label) => {
    const b = await box(sel, label);
    check(`${name}: visible and clickable`, b.found && b.visible && !b.disabled, JSON.stringify(b));
    if (!(b.found && b.visible && !b.disabled)) return false;
    for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) {
      await send("Input.dispatchMouseEvent", { type, x: b.x, y: b.y, button: "left", clickCount: 1 });
    }
    return true;
  };
  const choose = async (label, value) => {
    await evaluate(`__tv.choose(${JSON.stringify(label)}, ${JSON.stringify(value)})`);
    await settle();
    return waitFor(`__tv.value(${JSON.stringify(label)}) === ${JSON.stringify(value)}`, 10000);
  };
  const roles = async () => ({ chart: await evaluate("__tv.role('chart')"), signal: await evaluate("__tv.role('signal')"),
    execution: await evaluate("__tv.role('execution')"), strip: await evaluate("__tv.strip()") });
  const signalIs = (state, ms = 20000) => waitFor(`(__tv.role('signal') || {}).state === ${JSON.stringify(state)}`, ms);
  const startFeed = () => spawn(python, [feedScript, mt5Folder, "--seconds", "900"], { stdio: "ignore" });

  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Page.enable");
  await send("Page.navigate", { url });
  check("terminal loaded", await waitFor(`(() => { const f = document.querySelector('iframe[title*="tradingview_terminal"]'); return !!(f && f.contentDocument && f.contentDocument.querySelector('.terminal')); })()`, 90000));
  await evaluate(HELPERS);
  await settle();
  check("Historical: no source roles", !(await box(".source-strip")).found);

  // A. MT5 OFF: Gold, chart Binance LIVE; signals Exness UNAVAILABLE; execution DISABLED.
  await click("watchlist XAUUSDm", ".wl-row", "XAUUSDm"); await settle();
  await click("Live", ".mode-btn", "Live"); await settle();
  await click("Go Live", ".go-live"); await settle();
  check("A: Binance chart LIVE", await waitFor(`(__tv.role('chart') || {}).state === 'LIVE'`, 40000), await text(".source-strip"));
  let r = await roles();
  check("A: chart = Binance Futures · XAUUSDT", r.chart.name === "Binance Futures · XAUUSDT", JSON.stringify(r.chart));
  check("A: signals = Exness MT5 · XAUUSDm UNAVAILABLE (MT5 DISCONNECTED)",
    r.signal.name === "Exness MT5 · XAUUSDm" && r.signal.state === "UNAVAILABLE" && r.signal.detail === "DISCONNECTED", JSON.stringify(r.signal));
  check("A: execution DISABLED", r.execution.name === "Exness MT5" && r.execution.state === "DISABLED", JSON.stringify(r.execution));
  check("A: offline message", r.strip.note.startsWith("Exness signal feed unavailable. Binance chart remains live, but Exness strategy signals are disabled."), r.strip.note);
  const strip = await box(".source-strip");
  check("A: strip visible", strip.found && strip.visible, JSON.stringify(strip));
  const details = await box(".src-toggle");
  check("A: Details button fully visible at 1440 px", details.found && details.visible, JSON.stringify(details));
  note("A: observed", await text(".source-strip"));

  // B. MT5 ON: signals LIVE (authority ready); execution still DISABLED.
  let feed = startFeed();
  check("B: signal source LIVE once the bridge runs", await signalIs("LIVE"), JSON.stringify(await roles()));
  r = await roles();
  check("B: signal_authority_ready", r.strip.ready === true);
  check("B: execution still DISABLED", r.execution.state === "DISABLED");
  check("B: chart/signal mismatch note", r.strip.note === "Chart data and signal data come from different markets. Exness remains authoritative for strategy triggers.", r.strip.note);
  note("B: observed", await text(".source-strip"));

  // C. Chart Binance -> Exness -> Binance: the signal source never changes.
  const sampled = [];
  for (const source of ["exness", "binance"]) {
    check(`C: chart source -> ${source}`, await choose("Live source", source));
    await waitFor(`(__tv.role('chart') || {}).name.startsWith(${JSON.stringify(source === "exness" ? "Exness MT5" : "Binance Futures")})`, 20000);
    for (let i = 0; i < 4; i++) { sampled.push(await roles()); await sleep(400); }
  }
  check("C: chart role followed the chart", sampled.some((x) => x.chart.name === "Exness MT5 · XAUUSDm") && sampled.at(-1).chart.name === "Binance Futures · XAUUSDT");
  check("C: signal source stayed Exness MT5 · XAUUSDm and LIVE throughout",
    sampled.every((x) => x.signal.name === "Exness MT5 · XAUUSDm" && x.signal.state === "LIVE" && x.strip.ready), JSON.stringify(sampled.map((x) => x.signal)));
  check("C: no mismatch note while the chart is Exness", sampled.filter((x) => x.chart.name.startsWith("Exness")).every((x) => x.strip.note === ""));

  // D. Stop the MT5 feed: authority drops within the stale timeout; the Binance chart keeps updating.
  const updatesBefore = await evaluate("__tv.updates()");
  feed.kill("SIGTERM");
  const stopped = Date.now();
  check("D: signal authority disabled", await signalIs("UNAVAILABLE", 15000), JSON.stringify(await roles()));
  const took = (Date.now() - stopped) / 1000;
  check("D: within the stale timeout (5 s heartbeat + one poll)", took <= 8, `${took.toFixed(1)} s`);
  r = await roles();
  check("D: signals show MT5 STALE, execution DISABLED", r.signal.detail === "STALE" && r.execution.state === "DISABLED" && !r.strip.ready, JSON.stringify(r));
  check("D: Binance chart still LIVE", r.chart.state === "LIVE" && r.chart.name === "Binance Futures · XAUUSDT");
  await sleep(3000);
  check("D: Binance chart keeps updating", (await evaluate("__tv.updates()")) > updatesBefore + 3);
  note("D: observed", `${took.toFixed(1)} s · ${await text(".source-strip")}`);

  // E. Restart the MT5 feed: authority comes back only after fresh Exness data is revalidated.
  feed = startFeed();
  const seen = new Set();
  const t0 = Date.now();
  while (Date.now() - t0 < 20000) {
    const s = await evaluate("__tv.role('signal')");
    if (s) seen.add(`${s.state}|${s.detail}`);
    if (s && s.state === "LIVE") break;
    await sleep(100);
  }
  check("E: signal authority restored", (await roles()).signal.state === "LIVE", [...seen].join(", "));
  await click("E: open details", ".src-toggle");
  const log = await evaluate(`[...__tv.doc().querySelectorAll('.src-log li')].map((li) => li.innerText.trim()).reverse()`);
  const idx = (prefix, after = -1) => log.findIndex((line, i) => i > after && line.slice(9).startsWith(prefix));
  const stale = idx("Exness signal source STALE");
  const disabled = idx("Signal authority disabled", stale - 1);
  const live = idx("Exness signal source LIVE", stale);
  const restored = idx("Signal authority restored", live - 1);
  check("E: log shows STALE -> disabled -> LIVE -> restored", stale >= 0 && disabled >= 0 && live > stale && restored >= live, JSON.stringify(log));
  check("E: restore needed more than the first file (revalidation observed or logged separately)",
    [...seen].some((v) => v.includes("revalidating") || v.includes("STALE")) && restored >= live, [...seen].join(", "));
  check("E: execution still DISABLED", (await roles()).execution.state === "DISABLED");
  note("E: log", log.join(" | "));
  feed.kill("SIGTERM");
  feed = null;

  // Replay: no live readiness while replaying; Historical: none.
  await click("Exit Live", ".live-bar .rp-btn", "✕ Exit"); await settle();
  check("Historical after Live: no source roles", !(await box(".source-strip")).found);
  await click("Replay", ".mode-btn", "Replay"); await sleep(400);
  await evaluate(`(() => { const i = __tv.doc().querySelector('.popover input[type=date]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, '2026-06-10'); i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await click("Start replay", ".popover .btn.primary", "Start replay"); await settle();
  check("Replay: started", (await box(".replay-bar")).visible);
  check("Replay: no live signal/execution readiness shown", !(await box(".source-strip")).found);
  await click("Exit Replay", ".replay-bar .rp-btn", "✕ Exit"); await settle();
  ws.close();
}

try {
  await main();
} catch (error) {
  check("script completed", false, String(error && error.stack || error));
} finally {
  if (feed) feed.kill("SIGTERM");
  chrome.kill("SIGKILL");
  await sleep(300);
  try { rmSync(profile, { recursive: true, force: true }); } catch { /* ignore */ }
  console.log(JSON.stringify(results, null, 1));
  process.exit(results.every((r) => r.ok) ? 0 : 1);
}
