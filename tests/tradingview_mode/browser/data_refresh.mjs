// Browser acceptance: Historical data freshness and Refresh data (workspace_data.py) in the real terminal (production
// build). The app reads a SYNTHETIC MT5 Common/Files folder prepared by the pytest wrapper (an export and a Live seed
// that extend XAUUSDm past the frozen 2026-09-18 20:30 bar) and writes only to a temporary workspace folder.
//
//   node data_refresh.mjs <app-url> <chrome-binary> <expected.json>
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, chromePath, expectedPath] = process.argv.slice(2);
const EXPECTED = JSON.parse(readFileSync(expectedPath, "utf8"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "tv-refresh-"));
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
  times() { return this.win().__tvChart.bars.map((b) => b.time); },
  chipTitle() { const e = this.find('.tool-btn.data-status'); return e ? e.title : null; },
  follow() { return this.win().__tvChart.debugState().follow; },
  lastVisible() { const c = this.win().__tvChart; const r = c.chart.timeScale().getVisibleRange(); return r ? r.to : null; },
  visible() { const r = this.win().__tvChart.chart.timeScale().getVisibleRange(); return r ? [r.from, r.to] : null; },
  rowEntry(i) { const r = this.doc().querySelectorAll('.pine-trades tbody tr')[i]; if (!r) return null;
    return Date.parse(r.children[3].innerText.trim().replace(' ', 'T') + ':00Z') / 1000; },
  rowSelected(i) { const r = this.doc().querySelectorAll('.pine-trades tbody tr')[i]; return !!r && r.classList.contains('is-selected'); },
  lastBar() { const b = this.win().__tvChart.bars; return b.length ? b[b.length - 1].time : null; },
  overlayLast() { const e = [...this.win().__tvChart.overlays.values()][0]; if (!e) return null;
    const d = e.series[0].api.data(); return d.length ? d[d.length - 1].time : null; },
  pinePlotLast() { const s = this.win().__tvChart.pine.scripts[0]; if (!s) return null;
    const p = [...s.plots.values()][0]; const d = p ? p.data.filter((x) => x.value !== undefined) : []; return d.length ? d[d.length - 1].time : null; },
  lastMarkerTime() { const m = this.win().__tvChart.pine.strategyMarkers; const all = m ? m.markers() : []; return all.length ? all[all.length - 1].time : null; },
  markerCount() { const m = this.win().__tvChart.pine.strategyMarkers; return m ? m.markers().length : 0; },
  reportText() { const e = this.doc().querySelector('.pine-strategy'); return e ? e.innerText.replace(/\\s+/g, ' ').trim() : null; },
  setText(value) { const t = this.doc().querySelector('.pine-text'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(t, value);
    t.dispatchEvent(new Event('input', { bubbles: true })); return t.value.length; },
  rangeMax() { const i = this.doc().querySelector('.popover input[type=date]'); return i ? i.max : null; },
  logs() { return [...this.doc().querySelectorAll('.log-msg')].map((d) => d.innerText.trim()); },
};`;

// A Pine strategy whose plot and fills cover the newest bars (it trades every few bars).
const STRATEGY = `//@version=6
strategy("Refresh probe", overlay=true)
fast = ta.sma(close, 3)
slow = ta.sma(close, 8)
plot(fast, "fast")
if ta.crossover(fast, slow)
    strategy.entry("L", strategy.long)
if ta.crossunder(fast, slow)
    strategy.close("L")
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
  const settle = async () => { await sleep(250); await waitFor("window.__tv && __tv.synced()", 60000); await sleep(350); };
  const click = async (name, sel, label) => {
    const b = await evaluate(`__tv.box(${JSON.stringify(sel)}, ${label === undefined ? "undefined" : JSON.stringify(label)})`);
    check(`${name}: visible and clickable`, b.found && b.visible && !b.disabled, JSON.stringify(b));
    if (!(b.found && b.visible && !b.disabled)) return false;
    for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x: b.x, y: b.y, button: "left", clickCount: 1 });
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

  // Before: the frozen dataset ends at 2026-09-18 20:30 and the chip says it is stale.
  check("before: last bar is the frozen 2026-09-18 20:30", (await evaluate("__tv.lastBar()")) === EXPECTED.before_last, String(await evaluate("__tv.lastBar()")));
  check("before: status chip shows Stale with the last local bar", /^Stale/.test(await evaluate("__tv.text('.tool-btn.data-status')") || "")
    && /Last local bar 2026-09-18 20:30 UTC/.test(await evaluate("__tv.chipTitle()") || ""), await evaluate("__tv.chipTitle()"));
  await click("status details", ".tool-btn.data-status"); await sleep(300);
  const details = await evaluate("__tv.text('.data-status-menu')");
  check("details show last local, latest available and status", /Last local bar 2026-09-18 20:30 UTC/.test(details) &&
    new RegExp(`Latest available ${EXPECTED.after_last_text} UTC`).test(details) && /Status Stale/.test(details), details);
  await shot("refresh_before_details");
  await click("close details", ".tool-btn.data-status"); await sleep(300);

  // An indicator and a Pine strategy on the chart.
  await click("Indicators", ".tool-btn", "Indicators"); await sleep(300);
  await click("SMA", ".menu-row", "SMA"); await settle();
  await click("Pine Editor tab", ".bottom-tab", "Pine Editor"); await settle();
  await evaluate(`__tv.setText(${JSON.stringify(STRATEGY)})`);
  await click("Add to chart", ".pine-add"); await settle();
  check("strategy on chart", await waitFor("__tv.markerCount() > 0", 30000), String(await evaluate("__tv.markerCount()")));
  const before = { overlay: await evaluate("__tv.overlayLast()"), plot: await evaluate("__tv.pinePlotLast()"),
                   markers: await evaluate("__tv.markerCount()") };
  check("before: indicator and Pine plot end at the frozen last bar", before.overlay === EXPECTED.before_last && before.plot === EXPECTED.before_last, JSON.stringify(before));

  // Refresh data.
  await click("Refresh", ".tool-btn.data-refresh"); await settle();
  check("after: last bar is the newest CLOSED source bar (forming bar excluded)", await waitFor(`__tv.lastBar() === ${EXPECTED.after_last}`, 30000), String(await evaluate("__tv.lastBar()")));
  const times = await evaluate("__tv.times()");
  const appended = times.filter((t) => t > EXPECTED.before_last);
  check("after: every appended bar present once, strictly increasing, nothing extra", JSON.stringify(appended) === JSON.stringify(EXPECTED.new_times)
    && times.every((t, i) => i === 0 || t > times[i - 1]), `${appended.length} vs ${EXPECTED.new_times.length}`);
  check("after: status chip shows Current with the new last bar", await waitFor(`/^Current/.test(__tv.text('.tool-btn.data-status') || '') && (__tv.chipTitle() || '').includes('Last local bar ${EXPECTED.after_last_text} UTC')`, 10000),
    await evaluate("__tv.chipTitle()"));
  check("after: the chart follows the newest bar", (await evaluate("__tv.follow()")) && (await evaluate("__tv.lastVisible()")) === EXPECTED.after_last,
    JSON.stringify({ follow: await evaluate("__tv.follow()"), lastVisible: await evaluate("__tv.lastVisible()") }));
  check("after: no Refresh button once current", !(await evaluate("!!__tv.find('.tool-btn.data-refresh')")));
  check("after: indicator recalculated to the new last bar", await waitFor(`__tv.overlayLast() === ${EXPECTED.after_last}`, 15000), String(await evaluate("__tv.overlayLast()")));
  check("after: Pine plot recalculated to the new last bar (script not re-added)", await waitFor(`__tv.pinePlotLast() === ${EXPECTED.after_last}`, 15000), String(await evaluate("__tv.pinePlotLast()")));
  const lastFill = await evaluate("__tv.lastMarkerTime()");
  check("after: strategy recalculated (fills include the new bars)", lastFill !== null && lastFill > EXPECTED.before_last,
    `last fill ${lastFill} · markers ${before.markers} -> ${await evaluate("__tv.markerCount()")}`);
  await click("Pine Strategy tab", ".bottom-tab", "Pine Strategy"); await settle();
  await shot("refresh_after");
  check("after: Pine Strategy report present", /Net profit/.test(await evaluate("__tv.reportText()") || ""));
  // Trade-row navigation: an older trade's row brings it into view.
  const entry = await evaluate("__tv.rowEntry(12)");
  await evaluate("__tv.doc().querySelectorAll('.pine-trades tbody tr')[12].scrollIntoView({ block: 'center' })"); await sleep(200);
  await click("Pine trade row", ".pine-trades tbody tr", String(await evaluate("__tv.doc().querySelectorAll('.pine-trades tbody tr')[12].children[0].innerText.trim()")));
  await sleep(400);
  const view = await evaluate("__tv.visible()");
  check("trade-row navigation: the clicked Pine trade is in view and selected", entry !== null && view && view[0] <= entry && entry <= view[1]
    && (await evaluate("__tv.rowSelected(12)")), JSON.stringify({ entry, view }));
  await click("Date range", '.tool-btn[title="Date range (UTC)"]'); await sleep(300);
  check("after: date picker allows the new dates", (await evaluate("__tv.rangeMax()")) === EXPECTED.after_date, String(await evaluate("__tv.rangeMax()")));
  await click("Logs tab", ".bottom-tab", "Logs"); await settle();
  const logs = await evaluate("__tv.logs()");
  check("log reports the refresh", logs.some((m) => /Refreshed XAUUSDm workspace history · 15m: \+\d+ closed bars through/.test(m)), JSON.stringify(logs.slice(-4)));
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
