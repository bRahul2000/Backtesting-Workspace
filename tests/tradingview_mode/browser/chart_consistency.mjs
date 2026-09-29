// Browser acceptance: chart consistency (Rahul's screen-recording workflow).
//  1. the chart rectangle does not change when the bottom-dock tab changes (one persistent dock height; a
//     drag-resized height and the collapsed state survive tab changes, symbol changes and a reload)
//  2. switching symbol (BTC ~76-80k <-> XAUUSDm ~4k) resets the vertical price scale to the new data and keeps the
//     horizontal time window; nothing from the previous symbol survives (price lines, selected trade, markers)
//  3. no volume histogram by default and no space reserved for it
//
//   node chart_consistency.mjs <app-url> <chrome-binary>
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, chromePath] = process.argv.slice(2);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "tv-consistency-"));
const chrome = spawn(chromePath, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "--window-size=1440,900", "about:blank"], { stdio: "ignore" });
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail: String(detail).slice(0, 900) }); };
const note = (name, detail) => results.push({ name, ok: true, detail: String(detail).slice(0, 900) });

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
  chart() { return this.win().__tvChart; },
  rect(sel) { const e = this.doc().querySelector(sel); if (!e) return null; const r = e.getBoundingClientRect();
    return [r.left, r.top, r.width, r.height].map((v) => Math.round(v * 10) / 10); },
  geometry() { const c = this.chart(); const pane = c.chart.paneSize(0); const ts = c.chart.timeScale();
    return { panel: this.rect('.chart-panel'), host: this.rect('.chart-host'), watch: this.rect('.watchlist'), dock: this.rect('.bottom'),
             pane: [pane.width, pane.height], timeWidth: ts.width() }; },
  scale() { const c = this.chart(); const r = c.chart.priceScale('right').getVisibleRange();
    const lr = c.chart.timeScale().getVisibleLogicalRange(); const bars = c.bars;
    const from = Math.max(0, Math.floor(lr.from)), to = Math.min(bars.length - 1, Math.ceil(lr.to));
    let lo = Infinity, hi = -Infinity; for (let i = from; i <= to; i++) { lo = Math.min(lo, bars[i].low); hi = Math.max(hi, bars[i].high); }
    const t = c.chart.timeScale().getVisibleRange();
    return { from: r && r.from, to: r && r.to, lo, hi, last: bars.length ? bars[bars.length - 1].close : null, n: bars.length,
             time: t ? [t.from, t.to] : null, autoScale: c.chart.priceScale('right').options().autoScale }; },
  volume() { const c = this.chart(); return { visible: c.volume.options().visible, margins: c.candles.priceScale().options().scaleMargins,
    legendVol: /Vol/.test(this.text('.lg-ohlc') || '') }; },
  tabs() { return [...this.doc().querySelectorAll('.bottom-tab')].map((t) => t.innerText.replace(/\\s+/g, ' ').trim()); },
  activeTab() { return this.text('.bottom-tab.is-active'); },
  setText(value) { const t = this.doc().querySelector('.pine-text'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(t, value);
    t.dispatchEvent(new Event('input', { bubbles: true })); return t.value.length; },
  audit() { return this.chart().debugState().strategyAudit; },
  fillsLoaded() { const bars = new Set(this.chart().bars.map((b) => b.time)); return this.chart().pine.strategyFills.filter((f) => bars.has(f.time)).length; },
};`;

const STRATEGY = `//@version=6
strategy("Consistency probe", overlay=true)
fast = ta.sma(close, 5)
slow = ta.sma(close, 20)
plot(fast, "fast")
if ta.crossover(fast, slow)
    strategy.entry("L", strategy.long, comment="UP")
if ta.crossunder(fast, slow)
    strategy.close("L", comment="DOWN")
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
  const settle = async () => { await sleep(250); await waitFor("window.__tv && __tv.synced()", 60000); await sleep(500); };
  const mouse = async (type, x, y) => send("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1 });
  const click = async (name, sel, label) => {
    const b = await evaluate(`__tv.box(${JSON.stringify(sel)}, ${label === undefined ? "undefined" : JSON.stringify(label)})`);
    check(`${name}: visible and clickable`, b.found && b.visible && !b.disabled, JSON.stringify(b));
    if (!(b.found && b.visible && !b.disabled)) return false;
    for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await mouse(type, b.x, b.y);
    return true;
  };
  const shot = async (name) => { if (!process.env.PINE_SHOTS) return; const { writeFileSync } = await import("node:fs");
    writeFileSync(`${process.env.PINE_SHOTS}/${name}.png`, Buffer.from((await send("Page.captureScreenshot", { format: "png" })).data, "base64")); };
  // open TradingView Mode from the sidebar (works on every Streamlit release)
  const origin = new URL(url).origin;
  const openTerminal = async () => {
    await send("Page.navigate", { url: origin + "/" });
    await waitFor(`[...document.querySelectorAll('[data-testid="stSidebarNav"] a')].some((a) => a.innerText.trim() === 'TradingView Mode')`, 90000);
    const link = await evaluate(`(() => { const a = [...document.querySelectorAll('[data-testid="stSidebarNav"] a')].find((x) => x.innerText.trim() === 'TradingView Mode');
      const r = a.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
    for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await mouse(type, link.x, link.y);
    const ok = await waitFor(`(() => { const f = document.querySelector('iframe[title*="tradingview_terminal"]'); return !!(f && f.contentDocument && f.contentDocument.querySelector('.terminal') && f.contentWindow.__tvChart); })()`, 90000);
    await evaluate(HELPERS);
    await settle();
    return ok;
  };
  const openTab = async (label) => {
    if ((await evaluate("__tv.activeTab()") || "").startsWith(label)) return;
    await click(`${label} tab`, ".bottom-tab", label); await settle();
  };
  const TABS = ["Indicators", "Strategy Tester", "Trades", "Pine Editor", "Logs", "Pine Editor", "Trades", "Strategy Tester", "Indicators"];
  const errors = [];
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Runtime.enable");
  ws.addEventListener("message", (m) => { const d = JSON.parse(m.data); if (d.method === "Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.text); });
  await send("Page.enable");
  check("terminal loaded from the sidebar", await openTerminal());
  if (!(await evaluate("(__tv.text('.symbol-name') || '').startsWith('BTC/USD')"))) { await click("watchlist BTC/USD", ".wl-row", "BTC/USD"); await settle(); }
  if (!(await evaluate("!!__tv.find('.tf-btn.is-active', '15m')"))) { await click("15m", ".tf-btn", "15m"); await settle(); }

  // ---- 3. no default volume ------------------------------------------------------------------------------------
  const vol = await evaluate("__tv.volume()");
  check("default chart: no volume histogram and no Vol in the legend", !vol.visible && !vol.legendVol, JSON.stringify(vol));
  check("default chart: no vertical space reserved for volume", vol.margins.bottom <= 0.1, JSON.stringify(vol.margins));

  // ---- 1. the chart rectangle does not depend on the dock tab ---------------------------------------------------
  await openTab("Indicators");
  const base = await evaluate("__tv.geometry()");
  note("geometry (Indicators)", JSON.stringify(base));
  const same = (a, b) => JSON.stringify([a.panel, a.host, a.watch, a.dock, a.pane, a.timeWidth]) === JSON.stringify([b.panel, b.host, b.watch, b.dock, b.pane, b.timeWidth]);
  for (const tab of TABS) {
    await openTab(tab);
    const g = await evaluate("__tv.geometry()");
    check(`tab ${tab}: chart, watchlist and dock rectangles unchanged`, same(g, base), JSON.stringify({ base, now: g }));
  }
  // a drag-resized height survives tab changes (and is the one height for every tab)
  const edge = await evaluate("(() => { const e = __tv.doc().querySelector('.bottom-resize').getBoundingClientRect(); const f = __tv.frameEl().getBoundingClientRect(); return { x: f.x + e.x + 300, y: f.y + e.y + 3 }; })()");
  const target = 280;
  const h0 = (await evaluate("__tv.geometry()")).dock[3];
  await mouse("mouseMoved", edge.x, edge.y); await mouse("mousePressed", edge.x, edge.y);
  await mouse("mouseMoved", edge.x, edge.y - (target - h0)); await mouse("mouseReleased", edge.x, edge.y - (target - h0)); await sleep(400);
  const resized = await evaluate("__tv.geometry()");
  check("dock drag-resized to ~280 px", Math.abs(resized.dock[3] - target) <= 2, JSON.stringify(resized.dock));
  for (const tab of TABS) {
    await openTab(tab);
    const g = await evaluate("__tv.geometry()");
    check(`resized dock, tab ${tab}: height and chart unchanged`, same(g, resized), JSON.stringify({ resized: resized.dock, now: g.dock }));
  }

  // ---- 2. symbol switch: vertical scale reset, time window kept -------------------------------------------------
  await openTab("Pine Editor");
  await evaluate(`__tv.setText(${JSON.stringify(STRATEGY)})`);
  await click("Add to chart", ".pine-add"); await settle();
  check("strategy on chart", await waitFor("__tv.audit().fills > 0", 30000), JSON.stringify(await evaluate("__tv.audit()")));
  const scaleOk = (s) => s.from !== null && s.from < s.hi && s.to > s.lo && s.from > s.lo - (s.hi - s.lo) * 1.5 && s.to < s.hi + (s.hi - s.lo) * 1.5;
  const btc = await evaluate("__tv.scale()");
  note("BTC/USD scale", JSON.stringify(btc));
  check("BTC/USD: price scale fits BTC (~70-90k)", scaleOk(btc) && btc.lo > 50000, JSON.stringify(btc));
  // Rahul's recording: the price axis was dragged on BTC (Lightweight Charts then turns autoScale off)
  const axis = await evaluate(`(() => { const h = __tv.doc().querySelector('.chart-host').getBoundingClientRect(); const f = __tv.frameEl().getBoundingClientRect();
    const c = __tv.chart(); const w = c.chart.priceScale('right').width(); return { x: f.x + h.right - w / 2, y: f.y + h.top + h.height * 0.4 }; })()`);
  await mouse("mouseMoved", axis.x, axis.y); await mouse("mousePressed", axis.x, axis.y);
  for (let i = 1; i <= 6; i++) await mouse("mouseMoved", axis.x, axis.y + i * 15);
  await mouse("mouseReleased", axis.x, axis.y + 90); await sleep(300);
  check("BTC/USD: dragging the price axis turned autoScale off (the recorded state)", (await evaluate("__tv.scale().autoScale")) === false,
    JSON.stringify(await evaluate("__tv.scale()")));
  const switches = [["XAUUSDm", "Indicators", (s) => s.lo > 1000 && s.hi < 10000], ["BTCUSDm", "Strategy Tester", (s) => s.lo > 50000],
    ["XAUUSDm", "Pine Editor", (s) => s.lo > 1000 && s.hi < 10000], ["BTC/USD", "Logs", (s) => s.lo > 50000]];
  let previous = btc;
  for (const [symbol, tab, inRange] of switches) {
    await openTab(tab);
    await evaluate("__tv.chart().selectPineTrade(__tv.chart().pine.strategyTrades[0] || null)");        // a selected trade must not survive
    await click(`watchlist ${symbol}`, ".wl-row", symbol); await settle();
    await waitFor(`(__tv.text('.symbol-name') || '').startsWith(${JSON.stringify(symbol)})`, 30000); await settle();
    const s = await evaluate("__tv.scale()");
    note(`${symbol} scale (${tab} open)`, JSON.stringify(s));
    check(`${symbol} (${tab} open): right price scale fits the new symbol, candles visible`, inRange(s) && scaleOk(s) && s.autoScale, JSON.stringify(s));
    const overlap = previous.time && s.time ? Math.min(previous.time[1], s.time[1]) - Math.max(previous.time[0], s.time[0]) : -1;
    check(`${symbol}: the horizontal time window is kept`, overlap >= 0.8 * (previous.time[1] - previous.time[0]),
      JSON.stringify({ before: previous.time, after: s.time }));
    check(`${symbol}: nothing from the previous symbol survives (selected trade, price lines)`,
      (await evaluate("__tv.chart().debugState().selectedPineTrade")) === null && (await evaluate("__tv.chart().pine.tradeLines.length")) === 0);
    const a = await evaluate("__tv.audit()"), loaded = await evaluate("__tv.fillsLoaded()");
    check(`${symbol}: strategy markers rebuilt for the new symbol`, a.fills > 0 && a.inside === loaded && a.rendered === a.inside, JSON.stringify({ ...a, loaded }));
    const v = await evaluate("__tv.volume()");
    check(`${symbol}: still no volume histogram`, !v.visible && !v.legendVol && v.margins.bottom <= 0.1, JSON.stringify(v));
    const g = await evaluate("__tv.geometry()");
    check(`${symbol}: chart rectangle unchanged by the symbol switch`, same(g, resized), JSON.stringify({ resized: resized.dock, now: g.dock }));
    await shot(`consistency_${symbol.replace("/", "")}`);
    previous = s;
  }

  // ---- collapsed dock persists (symbol switch, reload) ------------------------------------------------------------
  await click("collapse dock", ".bottom-tabs .icon-btn"); await settle();
  check("dock collapsed", await waitFor("__tv.find('.bottom.is-collapsed') !== null", 10000));
  await click("watchlist XAUUSDm", ".wl-row", "XAUUSDm"); await settle();
  check("collapsed dock survives a symbol switch", await evaluate("!!__tv.find('.bottom.is-collapsed')"));
  check("page reloaded", await openTerminal());
  check("collapsed dock survives a reload", await waitFor("__tv.find('.bottom.is-collapsed') !== null", 15000));
  await click("expand dock", ".bottom-tabs .icon-btn"); await settle();
  const reopened = await evaluate("__tv.geometry()");
  check("the resized height is remembered after a reload", Math.abs(reopened.dock[3] - target) <= 2, JSON.stringify(reopened.dock));
  // volume stays available on demand: Settings -> Volume adds the histogram (and its space), unticking removes it
  const volumeToggle = async () => {
    await click("Settings", '.tool-btn[title="Settings"]'); await sleep(300);
    await click("Volume setting", ".popover .check input"); await settle();
    await click("close Settings", '.tool-btn[title="Settings"]'); await sleep(300);
  };
  await volumeToggle();
  const on = await evaluate("__tv.volume()");
  check("Settings -> Volume shows the histogram and reserves its space", on.visible && on.legendVol && on.margins.bottom >= 0.15, JSON.stringify(on));
  await volumeToggle();
  const off = await evaluate("__tv.volume()");
  check("unticking Volume removes it again", !off.visible && !off.legendVol && off.margins.bottom <= 0.1, JSON.stringify(off));
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
