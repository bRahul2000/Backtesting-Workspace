// Browser acceptance: Rahul's exact "Gold Range Hunter - Monthly Profiles V2" strategy (572-line fixture) in the real
// terminal (production build), Historical XAUUSDm M15 with the date range ending 2026-06-02: the Pine calculation
// range is 2025-12-23 -> 2026-06-02 (non-sealed; Gold V2 sealed windows start 2026-06-03) while the chart shows May.
// Checks: unified Strategy Tester (Pine source), exact trade count, fill -> marker reconciliation, duplicate
// prevention, lazy navigation to an older trade, fill tooltip, dock resize/collapse, focus modes.
// Simulation only: no broker order exists anywhere.
//
//   node gold_range_hunter.mjs <app-url> <chrome-binary> <fixture.pine> <expected.json>
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, chromePath, fixture, expectedPath] = process.argv.slice(2);
const SOURCE = readFileSync(fixture, "utf8");
const EXPECTED = JSON.parse(readFileSync(expectedPath, "utf8"));
const SEALED = Date.parse("2026-06-03T00:00:00Z") / 1000;
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
    return { found: true, x: f.x + cx, y: f.y + cy, top: f.y + r.y, disabled: !!el.disabled,
             visible: r.width > 0 && r.height > 0 && !!top && (top === el || el.contains(top)), text: el.innerText.trim() }; },
  synced() { const s = this.find('.sync'); return !!s && s.innerText.trim() === 'Synced'; },
  text(sel) { const e = this.find(sel); return e ? e.innerText.replace(/\\s+/g, ' ').trim() : null; },
  chart() { return this.win().__tvChart; },
  pine() { return this.chart().pine.scripts.map((s) => ({ id: s.id, title: s.title })); },
  bars() { return this.chart().bars.map((b) => b.time); },
  audit() { return this.chart().debugState().strategyAudit; },
  selectedTrade() { return this.chart().debugState().selectedPineTrade; },
  visible() { const r = this.chart().chart.timeScale().getVisibleRange(); return r ? [r.from, r.to] : null; },
  drawings() { const s = this.chart().pine.scripts[0]; const d = s && s.drawings && s.drawings.data;
    return d ? { lines: d.lines.length, labels: d.labels.length, boxes: d.boxes.length } : null; },
  tabs() { return [...this.doc().querySelectorAll('.bottom-tab')].map((t) => t.innerText.replace(/\\s+/g, ' ').trim()); },
  setText(value) { const t = this.doc().querySelector('.pine-text'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(t, value);
    t.dispatchEvent(new Event('input', { bubbles: true })); return t.value.length; },
  setDate(i, value) { const el = this.doc().querySelectorAll('.popover input[type=date]')[i]; Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); return el.value; },
  tradeRows() { return [...this.doc().querySelectorAll('.pine-trades tbody tr')].length; },
  metric(name) { const m = [...this.doc().querySelectorAll('.pine-metric')].find((e) => e.children[0].innerText.trim() === name); return m ? m.children[1].innerText.trim() : null; },
  logs() { return [...this.doc().querySelectorAll('.log-msg')].map((d) => d.innerText.trim()); },
  sidebarHidden() { const s = document.querySelector('[data-testid="stSidebar"]'); return !s || getComputedStyle(s).display === 'none'; },
  has(sel) { return !!this.doc().querySelector(sel); },
  height(sel) { const e = this.doc().querySelector(sel); return e ? Math.round(e.getBoundingClientRect().height) : null; },
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
  const settle = async () => { await sleep(250); await waitFor("window.__tv && __tv.synced()", 90000); await sleep(350); };
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
  if (!(await evaluate("!!__tv.find('.tf-btn.is-active', '15m')"))) { await click("15m", ".tf-btn", "15m"); await settle(); }

  // Historical range May 2026 -> 2026-06-02: the chart shows May; Pine calculates from the first bar to 2026-06-02.
  await click("Date range", '.tool-btn[title="Date range (UTC)"]'); await sleep(300);
  await evaluate(`__tv.setDate(0, "${EXPECTED.display_start}")`); await evaluate(`__tv.setDate(1, "${EXPECTED.end}")`);
  await click("Apply range", ".popover .btn.primary", "Apply"); await settle();
  const bars0 = await evaluate("__tv.bars()");
  check("chart shows the selected window only, ending before the sealed windows",
    bars0[0] >= EXPECTED.display_start_ts && bars0[bars0.length - 1] === EXPECTED.last_bar && bars0[bars0.length - 1] < SEALED,
    JSON.stringify([bars0[0], bars0[bars0.length - 1], bars0.length]));
  check("no separate Pine Strategy tab", (await evaluate("__tv.tabs()")).every((t) => !/Pine Strategy/.test(t)), JSON.stringify(await evaluate("__tv.tabs()")));

  // Paste, Compile, Add to chart: the dock switches to the Strategy Tester with the Pine source.
  await click("Pine Editor tab", ".bottom-tab", "Pine Editor"); await settle();
  check("exact script pasted", (await evaluate(`__tv.setText(${JSON.stringify(SOURCE)})`)) === SOURCE.length);
  await click("Compile", ".pine-compile"); await settle();
  check("compile reports success", await waitFor(`(__tv.text('.pine-ok') || '').startsWith('✓ Compiled: Gold Range Hunter - Monthly Profiles V2')`, 30000));
  await click("Add to chart", ".pine-add"); await settle();
  check("script on chart, one instance", await waitFor("__tv.pine().length === 1", 120000), JSON.stringify(await evaluate("__tv.pine()")));
  check("Strategy Tester opens automatically with the Pine source", await waitFor(
    "__tv.has('.bottom-tab.is-active') && __tv.text('.bottom-tab.is-active').startsWith('Strategy Tester') && __tv.text('.source-badge') === 'Pine · TradingView Emulator'", 30000),
    JSON.stringify([await evaluate("__tv.text('.bottom-tab.is-active')"), await evaluate("__tv.text('.source-badge')")]));
  check("exact trade count (full calculation range, not the visible window)", await waitFor(`__tv.metric('Total trades') === '${EXPECTED.trades}'`, 30000),
    `${await evaluate("__tv.metric('Total trades')")} vs ${EXPECTED.trades}`);
  const metrics = {}; for (const name of ["Net profit", "Win rate", "Profit factor", "Max drawdown", "Max run-up", "Avg bars in trade"]) metrics[name] = await evaluate(`__tv.metric(${JSON.stringify(name)})`);
  note("overview", JSON.stringify(metrics));

  // Fill -> marker reconciliation on the loaded bars.
  const recon = async () => evaluate(`(() => { const a = __tv.audit(); const bars = new Set(__tv.bars());
    const fills = __tv.chart().pine.strategyFills; const loaded = fills.filter((f) => bars.has(f.time)).length;
    return { ...a, loaded, reported: fills.length }; })()`);
  let r = await recon();
  check("reconciliation: every reported fill is audited (fills = inside + outside)", r.fills === EXPECTED.fills && r.reported === EXPECTED.fills && r.inside + r.outside === r.fills, JSON.stringify(r));
  check("reconciliation: one rendered marker per fill on a loaded bar", r.inside === r.loaded && r.rendered === r.inside && r.inside > 0, JSON.stringify(r));
  note("reconciliation (May window)", JSON.stringify(r));
  const drawings = await evaluate("__tv.drawings()");
  check("range boxes and trade lines are drawn", drawings && drawings.boxes > 10 && drawings.lines > 10, JSON.stringify(drawings));

  // Duplicate prevention: Add to chart again -> not added; the choice is offered.
  await click("Pine Editor tab", ".bottom-tab", "Pine Editor"); await settle();
  await click("Add to chart again", ".pine-add"); await settle();
  check("identical script is not added twice", (await evaluate("__tv.pine().length")) === 1 && await waitFor("__tv.has('.pine-duplicate')", 10000),
    await evaluate("__tv.text('.pine-duplicate')"));
  check("duplicate notice offers focus / add another", /Focus existing/.test(await evaluate("__tv.text('.pine-duplicate')") || "")
    && /Add another instance/.test(await evaluate("__tv.text('.pine-duplicate')") || ""));

  // Trades: the oldest trade (January, far before the loaded May bars) -> older bars load, chart moves, highlight.
  await click("Strategy Tester tab", ".bottom-tab", "Strategy Tester"); await settle();
  await click("Trades section", ".subtab", "Trades"); await settle();
  check("trades table lists every trade", (await evaluate("__tv.tradeRows()")) === EXPECTED.trades, String(await evaluate("__tv.tradeRows()")));
  const header = await evaluate("[...__tv.doc().querySelectorAll('.pine-trades thead th')].map((t) => t.innerText.trim())");
  check("trades table columns", JSON.stringify(header) === JSON.stringify(["#", "Direction", "Entry time", "Entry price", "Exit time", "Exit price",
    "Entry comment", "Exit comment", "Qty", "P&L", "P&L %", "Run-up", "Drawdown", "Bars"]), JSON.stringify(header));
  await evaluate("[...__tv.doc().querySelectorAll('.pine-trades tbody tr')].at(-1).scrollIntoView({ block: 'center' })"); await sleep(200);
  await click("oldest trade row", ".pine-trades tbody tr", "1\t");
  check("older bars lazy-load and the chart moves to the trade", await waitFor(`(() => { const v = __tv.visible(); const b = __tv.bars();
    return b[0] <= ${EXPECTED.first_entry} && v && v[0] <= ${EXPECTED.first_entry} && ${EXPECTED.first_entry} <= v[1]; })()`, 60000),
    JSON.stringify({ bars0: (await evaluate("__tv.bars()"))[0], visible: await evaluate("__tv.visible()"), entry: EXPECTED.first_entry }));
  check("the trade is highlighted (selected fills + price lines)", (await evaluate("__tv.selectedTrade()")) === EXPECTED.first_key
    && (await evaluate("__tv.chart().pine.tradeLines.length")) >= 1, String(await evaluate("__tv.selectedTrade()")));
  check("lazy loading kept the same backtest (calculation unchanged)", (await evaluate(`__tv.metric('Total trades')`)) === null
    || (await evaluate("__tv.tradeRows()")) === EXPECTED.trades, String(await evaluate("__tv.tradeRows()")));
  r = await recon();
  check("reconciliation after loading older bars: no marker lost", r.fills === EXPECTED.fills && r.inside === r.loaded && r.rendered === r.inside
    && r.inside + r.outside === r.fills, JSON.stringify(r));
  note("reconciliation (after lazy load)", JSON.stringify(r));
  await shot("grh_after_navigation");

  // Hover a fill: the compact marker's details appear in a tooltip.
  const hover = await evaluate(`(() => { const c = __tv.chart(); const t = ${EXPECTED.first_entry}; const x = c.coordinateOf(t);
    const host = __tv.doc().querySelector('.chart-host').getBoundingClientRect(); const f = __tv.frameEl().getBoundingClientRect();
    return x === null ? null : { x: f.x + host.x + x, y: f.y + host.y + host.height * 0.4 }; })()`);
  if (hover) { await mouse("mouseMoved", hover.x, hover.y); await sleep(300); }
  check("fill tooltip shows side, price and comment", await waitFor(`/(Buy|Sell) [0-9.]+ @ [0-9,.]+ · SETUP_/.test(__tv.text('.fill-tooltip') || '')`, 5000),
    await evaluate("__tv.text('.fill-tooltip')"));

  // Dock: resize by dragging its top edge, collapse, expand.
  const h0 = await evaluate("__tv.height('.bottom')");
  const edge = await evaluate("(() => { const e = __tv.doc().querySelector('.bottom-resize').getBoundingClientRect(); const f = __tv.frameEl().getBoundingClientRect(); return { x: f.x + e.x + 200, y: f.y + e.y + 3 }; })()");
  await mouse("mouseMoved", edge.x, edge.y); await mouse("mousePressed", edge.x, edge.y);
  await mouse("mouseMoved", edge.x, edge.y - 60); await mouse("mouseReleased", edge.x, edge.y - 60); await sleep(300);
  const h1 = await evaluate("__tv.height('.bottom')");
  check("dock resizes by dragging its top edge", h1 >= h0 + 50, `${h0} -> ${h1}`);
  check("dock height is remembered in this browser", (await evaluate("Object.keys(__tv.win().localStorage).some((k) => k === 'tvterm:dock-height')")));
  await click("collapse dock", ".bottom-tabs .icon-btn"); await settle();
  check("dock collapses", await waitFor("__tv.has('.bottom.is-collapsed')", 10000));
  await click("expand dock", ".bottom-tabs .icon-btn"); await settle();
  check("dock expands", await waitFor("__tv.has('.bottom.is-open')", 10000));

  // Focus modes.
  await click("Layout", ".layout-btn"); await sleep(250);
  await click("Chart only", ".layout-mode", "Chart only"); await settle();
  check("chart only: no dock, watchlist, tools or Streamlit sidebar", await waitFor("!__tv.has('.bottom') && !__tv.has('.watchlist') && !__tv.has('.lefttools') && __tv.sidebarHidden()", 10000),
    JSON.stringify({ dock: await evaluate("__tv.has('.bottom')"), watch: await evaluate("__tv.has('.watchlist')"), sidebar: await evaluate("__tv.sidebarHidden()") }));
  await shot("grh_chart_only");
  await click("Layout", ".layout-btn"); await sleep(250);
  await click("Chart + Strategy Tester", ".layout-mode", "Chart + Strategy Tester"); await settle();
  check("chart + Strategy Tester", await waitFor("__tv.has('.bottom.is-open') && __tv.text('.bottom-tab.is-active').startsWith('Strategy Tester') && !__tv.has('.watchlist')", 10000));
  await click("Layout", ".layout-btn"); await sleep(250);
  await click("Chart + Pine Editor", ".layout-mode", "Chart + Pine Editor"); await settle();
  check("chart + Pine Editor", await waitFor("__tv.has('.bottom.is-open') && __tv.text('.bottom-tab.is-active').startsWith('Pine Editor')", 10000));
  await click("Layout", ".layout-btn"); await sleep(250);
  await click("Normal layout", ".layout-mode", "Normal layout"); await settle();
  check("normal layout restored", await waitFor("__tv.has('.watchlist') && __tv.has('.lefttools') && __tv.has('.bottom') && !__tv.sidebarHidden()", 10000));
  await shot("grh_normal");

  // Historical freshness: no MT5 source in this test -> Unknown, nothing refreshed.
  check("freshness chip without a local source is Unknown", /^Unknown/.test(await evaluate("__tv.text('.tool-btn.data-status')") || ""), await evaluate("__tv.text('.tool-btn.data-status')"));
  await click("Logs tab", ".bottom-tab", "Logs"); await settle();
  const logs = await evaluate("__tv.logs()");
  check("no 'Pine script not added' rejection", logs.every((m) => !/Pine script not added/.test(m)), JSON.stringify(logs.slice(-6)));
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
