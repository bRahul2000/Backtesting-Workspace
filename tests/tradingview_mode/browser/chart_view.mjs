// Browser regression: stable live pan/zoom, Go to latest, crosshair candle info,
// older history (production build, real Binance XAUUSDT Perpetual 15m).
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
const profile = mkdtempSync(join(tmpdir(), "tv-chart-"));
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
  legend() { const d = this.doc(); const row = d.querySelector('.lg-ohlc'); if (!row) return null;
    const spans = [...row.querySelectorAll('span')].map((s) => s.innerText.trim());
    return { time: d.querySelector('.lg-time')?.innerText.trim(), hover: d.querySelector('.lg-time')?.classList.contains('is-hover'), spans }; },
};`;

const fmt = (v, p) => Number(v).toLocaleString("en-US", { minimumFractionDigits: p, maximumFractionDigits: p });
const utc = (t) => { const d = new Date(t * 1000); const z = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${z(d.getUTCMonth() + 1)}-${z(d.getUTCDate())} ${z(d.getUTCHours())}:${z(d.getUTCMinutes())} UTC`; };
const sameRange = (a, b) => !!a && !!b && a.from === b.from && a.to === b.to;

async function main() {
  const { ws, send } = await cdp();
  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text);
    return r.result.value;
  };
  const waitFor = async (expression, ms = 30000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { try { if (await evaluate(expression)) return true; } catch { /* loading */ } await sleep(200); }
    return false;
  };
  const settle = async () => { await sleep(250); await waitFor("window.__tv && __tv.synced()"); await sleep(300); };
  const mouse = async (type, x, y, extra = {}) => send("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1, ...extra });
  const click = async (name, sel, label) => {
    const b = await evaluate(`__tv.box(${JSON.stringify(sel)}, ${label === undefined ? "undefined" : JSON.stringify(label)})`);
    check(`${name}: visible and clickable`, b.found && b.visible && !b.disabled, JSON.stringify(b));
    if (!(b.found && b.visible && !b.disabled)) return false;
    for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await mouse(type, b.x, b.y);
    return true;
  };
  const chart = () => evaluate("__tv.chart()");
  const host = () => evaluate("__tv.host()");
  const drag = async (dx, pause = 300) => { // pan by dragging the chart (positive dx = back in time)
    const h = await host();
    const y = h.y + h.h * 0.45;
    const x0 = h.x + h.w * (dx > 0 ? 0.25 : 0.75);
    await mouse("mouseMoved", x0, y);
    await mouse("mousePressed", x0, y, { buttons: 1 });
    for (let i = 1; i <= 12; i++) await mouse("mouseMoved", x0 + (dx * i) / 12, y, { buttons: 1 });
    await mouse("mouseReleased", x0 + dx, y, { buttons: 0 });
    await sleep(pause);
  };
  const leaveChart = async () => { const h = await host(); await mouse("mouseMoved", h.x + h.w + 150, h.y + 10); };
  const waitUpdates = async (n) => { const start = (await chart()).stats.updates;
    return waitFor(`__tv.chart().stats.updates >= ${start + n}`, 30000); };

  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Page.enable");
  await send("Page.navigate", { url });
  check("terminal loaded", await waitFor(`(() => { const f = document.querySelector('iframe[title*="tradingview_terminal"]'); return !!(f && f.contentDocument && f.contentDocument.querySelector('.terminal')); })()`, 90000));
  await evaluate(HELPERS);
  await settle();

  // 1. XAUUSDT Binance 15m Live.
  await click("watchlist XAUUSDm", ".wl-row", "XAUUSDm"); await settle();
  await click("Live", ".mode-btn", "Live"); await settle();
  check("setup: Gold · Binance Futures · 15m", (await evaluate(`[...__tv.doc().querySelectorAll('.live-bar select')].map((s) => s.value).join('|')`)) === "GOLD|binance|15m");
  await click("Go Live", ".go-live"); await settle();
  check("XAUUSDT Binance LIVE", await waitFor(`__tv.text('.live-state') === 'LIVE'`, 40000), await evaluate("__tv.text('.live-bar')"));
  let s = await chart();
  check("more than 500 bars loaded (2,000 seed)", s.count >= 2000, s.count);
  check("status bar shows the loaded count", /^2,000 bars · Binance Futures · 15m/.test(await evaluate("__tv.text('.history-status')") || ""),
    await evaluate("__tv.text('.history-status')"));
  check("opens following the latest candle", s.follow && s.logical.to >= s.count - 1, JSON.stringify(s.logical));
  check("no Go to latest while following", !(await evaluate("!!__tv.find('.go-latest')")));
  const firstLoaded = s.first;
  note("loaded", `${s.count} bars from ${utc(s.first)} to ${utc(s.last.time)}`);

  // Zoom with the mouse wheel (real input), then pan several days back.
  const h = await host();
  await mouse("mouseMoved", h.x + h.w * 0.6, h.y + h.h * 0.4);
  await send("Input.dispatchMouseEvent", { type: "mouseWheel", x: h.x + h.w * 0.6, y: h.y + h.h * 0.4, deltaX: 0, deltaY: -240 });
  await sleep(400);
  const zoomed = (await chart()).barSpacing;
  check("wheel zoom changed bar spacing", zoomed !== s.barSpacing, `${s.barSpacing} -> ${zoomed}`);
  for (let i = 0; i < 4; i++) await drag(560);
  await leaveChart();
  await sleep(600);
  const panned = await chart();
  const daysBack = (panned.last.time - panned.time.to) / 86400;
  check("panned several days back", daysBack >= 2, `${daysBack.toFixed(1)} days`);
  check("follow off after panning back", panned.follow === false);
  check("Go to latest shown", (await evaluate("__tv.box('.go-latest')")).visible);

  // 2-5. Five or more live refreshes: nothing about the view may move.
  check("≥5 live refreshes arrived", await waitUpdates(5));
  await waitFor(`__tv.chart().last.close !== ${JSON.stringify(panned.last.close)} || __tv.chart().last.time !== ${panned.last.time}`, 20000);
  const after = await chart();
  check("live data kept updating off-screen", after.stats.updates >= panned.stats.updates + 5 && after.stats.incremental > panned.stats.incremental,
    JSON.stringify({ before: panned.stats, after: after.stats }));
  check("visible time range unchanged", sameRange(panned.time, after.time), JSON.stringify({ before: panned.time, after: after.time }));
  check("visible logical range unchanged", sameRange(panned.logical, after.logical), JSON.stringify({ before: panned.logical, after: after.logical }));
  check("zoom (bar spacing) unchanged", panned.barSpacing === after.barSpacing && after.barSpacing === zoomed, `${panned.barSpacing} / ${after.barSpacing}`);
  check("price scale unchanged", sameRange(panned.price, after.price), JSON.stringify({ before: panned.price, after: after.price }));
  check("no setData during live ticks", after.stats.setData === panned.stats.setData, JSON.stringify(after.stats));
  check("still not following", after.follow === false);

  // 6-7. Go to latest.
  await click("Go to latest", ".go-latest"); await sleep(600);
  const latest = await chart();
  check("latest candle visible", latest.logical.to >= latest.count - 1 && latest.logical.from <= latest.count - 1, JSON.stringify(latest.logical));
  check("follow re-enabled", latest.follow === true);
  check("zoom kept by Go to latest", latest.barSpacing === zoomed, latest.barSpacing);
  check("Go to latest hidden again", !(await evaluate("!!__tv.find('.go-latest')")));
  check("follows new data", await waitUpdates(3) && (await chart()).follow === true);

  // 8-9. Crosshair a candle: exact UTC time and the Python OHLC of that candle.
  const cur = await chart();
  const index = cur.count - 8;
  const target = await evaluate(`__tv.bar(${index})`);
  const x = await evaluate(`__tv.xOf(${target.time})`);
  const hh = await host();
  await mouse("mouseMoved", hh.x + x, hh.y + hh.h * 0.35);
  await sleep(300);
  let legend = await evaluate("__tv.legend()");
  const precision = await evaluate("__tv.win().__tvChart.precision");
  const expected = [`O${fmt(target.open, precision)}`, `H${fmt(target.high, precision)}`, `L${fmt(target.low, precision)}`, `C${fmt(target.close, precision)}`];
  check("crosshair shows exact UTC time", legend.time === utc(target.time) && legend.hover, JSON.stringify(legend));
  check("crosshair shows the candle's exact OHLC", expected.every((v, i) => legend.spans[i + 1] === v), JSON.stringify({ expected, got: legend.spans }));
  check("volume shown", legend.spans.some((v) => v.startsWith("Vol")), JSON.stringify(legend.spans));
  await waitUpdates(2);
  legend = await evaluate("__tv.legend()");
  check("hovered candle stays in the legend across live updates", legend.time === utc(target.time), legend.time);
  await leaveChart(); await sleep(300);
  legend = await evaluate("__tv.legend()");
  const newest = (await chart()).last;
  check("leaving the chart shows the latest candle", legend.time === utc(newest.time) && !legend.hover, JSON.stringify(legend));

  // Older history: pan to the left edge -> more candles, same candles on screen.
  // Pan to just outside the trigger zone (40 bars from the left edge), then cross it once.
  for (let i = 0; i < 40; i++) {
    const c = await chart();
    const room = c.logical.from - 70;
    if (room <= 0) break;
    await drag(Math.min(900, room * c.barSpacing));
  }
  const near = await chart();
  await drag(Math.max(60, (near.logical.from - 20) * near.barSpacing), 0);
  const edge = await chart();  // at release, before Python has answered
  await leaveChart();
  check("history request not yet answered at release", edge.count === near.count, `${near.count} / ${edge.count}`);
  const grew = await waitFor(`__tv.chart().count > ${edge.count}`, 30000);
  await settle(); await sleep(500);
  const more = await chart();
  check("older history loaded at the left edge", grew && more.count === edge.count + 1000 && more.first < edge.first, `${edge.count} -> ${more.count}`);
  check("same candles on screen after prepending", sameRange(edge.time, more.time), JSON.stringify({ before: edge.time, after: more.time }));
  check("zoom unchanged after prepending", edge.barSpacing === more.barSpacing);
  check("status bar shows the new count", (await evaluate("__tv.text('.history-status')") || "").startsWith(`${more.count.toLocaleString("en-US")} bars`),
    await evaluate("__tv.text('.history-status')"));
  const ordered = await evaluate(`(() => { const b = __tv.win().__tvChart.bars; for (let i = 1; i < b.length; i++) if (b[i].time <= b[i - 1].time) return false; return true; })()`);
  check("no duplicate or out-of-order candles", ordered);
  note("history", `${more.count} bars, oldest ${utc(more.first)}`);

  // A timeframe switch is a new view: it intentionally resets to the latest candle.
  await click("30m", ".tf-btn", "30m"); await settle();
  await waitFor(`__tv.chart().viewKey.includes('|30m|')`, 20000);
  await waitFor(`__tv.chart().count >= 2000`, 30000);
  const tf = await chart();
  check("timeframe switch resets to latest", tf.follow && tf.logical.to >= tf.count - 1, JSON.stringify(tf.logical));

  // Replay semantics unchanged: each step reveals one bar and the view follows the
  // cursor; panned back, steps leave the view alone; nothing after the cursor is drawn.
  await click("Exit Live", ".live-bar .rp-btn", "✕ Exit"); await settle();
  await click("Replay", ".mode-btn", "Replay"); await sleep(400);
  await evaluate(`(() => { const i = __tv.doc().querySelector('.popover input[type=date]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, '2026-06-10'); i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await click("Start replay", ".popover .btn.primary", "Start replay"); await settle();
  const r0 = await chart();
  const stepBtn = async () => { await click("Next bar", ".replay-bar .rp-btn", "▶︎|"); await settle(); };
  for (let i = 0; i < 3; i++) await stepBtn();
  const r1 = await chart();
  check("replay: each step reveals exactly one bar", r1.count === r0.count + 3, `${r0.count} -> ${r1.count}`);
  check("replay: view follows the cursor", r1.follow && r1.logical.to >= r1.count - 1, JSON.stringify(r1.logical));
  check("replay: cursor bar is the last drawn bar", r1.last.time === (await evaluate("__tv.win().__tvChart.bars.at(-1).time")));
  await drag(700); await leaveChart(); await sleep(300);
  const r2 = await chart();
  for (let i = 0; i < 2; i++) await stepBtn();
  const r3 = await chart();
  check("replay: panned back, steps keep the view", r3.count === r2.count + 2 && sameRange(r2.time, r3.time) && r3.barSpacing === r2.barSpacing,
    JSON.stringify({ before: r2.time, after: r3.time }));
  await click("Exit Replay", ".replay-bar .rp-btn", "✕ Exit"); await settle();
  check("historical after replay", (await evaluate("__tv.box('.mode-btn', 'Historical')")).active);
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
