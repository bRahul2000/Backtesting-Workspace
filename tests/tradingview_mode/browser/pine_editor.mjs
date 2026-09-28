// Browser acceptance: Pine Editor -> Compile -> Add to chart (production build).
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
  const mouse = async (type, x, y) => send("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1 });
  const click = async (name, sel, label) => {
    const b = await evaluate(`__tv.box(${JSON.stringify(sel)}, ${label === undefined ? "undefined" : JSON.stringify(label)})`);
    check(`${name}: visible and clickable`, b.found && b.visible && !b.disabled, JSON.stringify(b));
    if (!(b.found && b.visible && !b.disabled)) return false;
    for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await mouse(type, b.x, b.y);
    return true;
  };
  const pine = () => evaluate("__tv.pine()");
  const snap = async (name) => { if (!process.env.PINE_SHOTS) return;
    const { writeFileSync } = await import("node:fs");
    writeFileSync(`${process.env.PINE_SHOTS}/${name}.png`, Buffer.from((await send("Page.captureScreenshot", { format: "png" })).data, "base64")); };

  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Page.enable");
  await send("Page.navigate", { url });
  check("terminal loaded", await waitFor(`(() => { const f = document.querySelector('iframe[title*="tradingview_terminal"]'); return !!(f && f.contentDocument && f.contentDocument.querySelector('.terminal')); })()`, 90000));
  await evaluate(HELPERS);
  await settle();
  await click("watchlist XAUUSDm", ".wl-row", "XAUUSDm"); await settle();
  const basePanes = await evaluate("__tv.panes()");

  // 1. Open the Pine Editor, load an example, Compile, Add to chart.
  await click("Pine Editor tab", ".bottom-tab", "Pine Editor"); await settle();
  check("editor visible", (await evaluate("__tv.box('.pine-text')")).visible);
  check("example loaded", (await evaluate(`__tv.example("Moving-average crossover")`)) > 100);
  await click("Compile", ".pine-compile"); await settle();
  check("compile reports success", await waitFor(`(__tv.text('.pine-ok') || '').startsWith('✓ Compiled: MA crossover')`, 15000), await evaluate("__tv.text('.pine-pane')"));
  await click("Add to chart", ".pine-add"); await settle();
  check("script on chart", await waitFor(`__tv.pine().length === 1`, 15000), JSON.stringify(await pine()));
  let p = await pine();
  check("overlay script: two plots, a fill and two shape outputs on the price pane",
    p[0].title === "MA crossover" && p[0].pane === 0 && p[0].plots.length === 2 && p[0].fills === 1 && p[0].shapes === 2
    && p[0].plots.every((x) => x.n > 100), JSON.stringify(p));
  check("list switched to the script", (await evaluate("__tv.text('.pine-tab.is-active')")).startsWith("On chart (1)"));
  check("legend names the script", (await evaluate("__tv.legendNames()")).some((n) => n.startsWith("MA crossover")), JSON.stringify(await evaluate("__tv.legendNames()")));
  await snap("pine_1_overlay");

  // 2. A non-overlay script gets its own pane.
  await click("Problems tab", ".pine-tab", "Problems");
  check("load RSI example", (await evaluate(`__tv.example("RSI with bands")`)) > 100);
  await click("Add RSI", ".pine-add"); await settle();
  check("second script on its own pane", await waitFor(`__tv.pine().length === 2 && __tv.panes() === ${basePanes + 1}`, 15000), JSON.stringify(await pine()));
  p = await pine();
  check("RSI pane has the plot, an hline fill and two hlines", p[1].pane === basePanes && p[1].plots.length === 1 && p[1].hlines === 2 && p[1].fills === 1, JSON.stringify(p[1]));
  await snap("pine_2_pane");

  // 3. Capability gaps are reported precisely and the script is not added.
  await click("Problems tab", ".pine-tab", "Problems");
  check("load gap example", (await evaluate(`__tv.example("Uses unimplemented features")`)) > 50);
  await click("Compile gap example", ".pine-compile"); await settle();
  const problems = await evaluate("__tv.problems()");
  check("gap names request.dividends() and its line", problems.some((t) => t === "NOT YET SUPPORTED Line 3 `request.dividends()` is not implemented yet (data requests)."), JSON.stringify(problems));
  check("gap names label.new() and its line", problems.some((t) => t === "NOT YET SUPPORTED Line 6 `label.new()` is not implemented yet (drawing objects)."), JSON.stringify(problems));
  check("no 'unsupported indicator' wording", problems.every((t) => !/indicator unsupported/i.test(t)));
  await click("Try adding gap example", ".pine-add"); await settle();
  check("gap script not added", (await pine()).length === 2);
  await snap("pine_3_gaps");

  // 4. A real error is worded like Pine.
  await evaluate(`__tv.setText("//@version=5\\nindicator('Typo')\\nplot(clsoe)\\n")`);
  await click("Compile typo", ".pine-compile"); await settle();
  check("undeclared identifier reported", (await evaluate("__tv.problems()")).some((t) => t === "ERROR Line 3 Undeclared identifier `clsoe`."), JSON.stringify(await evaluate("__tv.problems()")));

  // 5. Inputs change the chart.
  await click("On chart tab", ".pine-tab", "On chart");
  await click("Inputs", ".pine-script[data-script='pine-1'] .rp-btn", "Inputs");
  const before = (await pine())[0].plots[0].last.value;
  const setFast = await evaluate(`(() => { const i = __tv.doc().querySelector(".pine-script[data-script='pine-1'] .pine-input input"); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, '3'); i.dispatchEvent(new Event('input', { bubbles: true })); i.dispatchEvent(new Event('blur')); i.focus(); i.blur(); return true; })()`);
  await settle();
  check("input edit re-runs the script", setFast && await waitFor(`__tv.pine()[0].plots[0].last.value !== ${before}`, 15000), `${before} -> ${(await pine())[0].plots[0].last.value}`);

  // 6. Hide / remove.
  await evaluate(`__tv.doc().querySelector(".pine-script[data-script='pine-2'] input[type=checkbox]").click()`); await settle();
  check("hidden script leaves the chart and its pane", await waitFor(`__tv.pine().length === 1 && __tv.panes() === ${basePanes}`, 15000));
  await click("Remove MA", ".pine-script[data-script='pine-1'] .rp-btn.exit"); await settle();
  check("removed script leaves the chart", await waitFor(`__tv.pine().length === 0`, 15000));
  await evaluate(`__tv.doc().querySelector(".pine-script[data-script='pine-2'] input[type=checkbox]").click()`); await settle();
  check("re-shown script comes back", await waitFor(`__tv.pine().length === 1`, 15000));

  // 6b. request.security(): a higher-timeframe context, with its provenance in the script row.
  await evaluate(`__tv.setText("//@version=6\\nindicator('HTF close', overlay=true)\\nplot(request.security(syminfo.tickerid, '60', close), 'H1 close')\\n")`);
  await click("Add HTF script", ".pine-add"); await settle();
  check("request.security script on chart", await waitFor(`__tv.pine().length === 2`, 15000), JSON.stringify(await pine()));
  await click("On chart tab", ".pine-tab", "On chart");
  const htfMeta = await evaluate(`__tv.text(".pine-script[data-script='pine-3'] .pine-script-meta")`);
  const htfTitle = await evaluate(`__tv.doc().querySelector(".pine-script[data-script='pine-3'] .pine-script-meta").title`);
  // The chart's own dataset family serves the request (the default chart is the legacy Bitstamp 15m dataset,
  // so H1 is aggregated from it; an Exness chart would use the native Exness H1 file).
  check("request.security: one requested context with same-source provenance",
    /· 1 requested context$/.test(htfMeta || "") && / 60 · (Bitstamp · aggregated from 15m|Exness MT5 · native) · /.test(htfTitle || ""),
    `${htfMeta} | ${htfTitle}`);

  // 7. Replay: scripts run on revealed bars only.
  await click("Replay", ".mode-btn", "Replay"); await sleep(400);
  await evaluate(`(() => { const i = __tv.doc().querySelector('.popover input[type=date]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, '2026-06-10'); i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await click("Start replay", ".popover .btn.primary", "Start replay"); await settle();
  await waitFor(`__tv.pine().length === 1 && __tv.pine()[0].plots[0].n > 0`, 15000);
  let last = await evaluate("__tv.lastBar()");
  check("replay: pine output ends at the cursor", (await pine())[0].plots[0].last.time <= last, JSON.stringify({ last, pine: (await pine())[0].plots[0].last }));
  await click("Next bar", ".replay-bar .rp-btn", "▶︎|"); await settle();
  const next = await evaluate("__tv.lastBar()");
  check("replay step: pine advances with the cursor", next > last && (await pine())[0].plots[0].last.time === next, JSON.stringify({ next, pine: (await pine())[0].plots[0].last }));
  check("replay: request.security output ends at the cursor", (await pine())[1].plots[0].last.time === next, JSON.stringify((await pine())[1]));
  await click("Exit Replay", ".replay-bar .rp-btn", "✕ Exit"); await settle();
  check("historical again", (await evaluate("__tv.box('.mode-btn', 'Historical')")).active);

  // 8. Live (real Binance XAUUSDT): each poll re-runs only the forming bar; the chart never reloads.
  if (process.env.PINE_LIVE !== "0") {
    await click("Live", ".mode-btn", "Live"); await settle();
    await click("Go Live", ".go-live"); await settle();
    check("live: LIVE", await waitFor(`__tv.text('.live-state') === 'LIVE'`, 40000), await evaluate("__tv.text('.live-bar')"));
    check("live: script runs on the live bars", await waitFor(`__tv.pine().length === 2 && __tv.pine()[0].plots[0].n > 1000`, 20000), JSON.stringify(await pine()));
    const start = await evaluate("__tv.win().__tvChart.debugState().stats");
    await sleep(4000);
    const end = await evaluate("__tv.win().__tvChart.debugState().stats");
    check("live: several polls arrived", end.updates >= start.updates + 3, JSON.stringify({ start, end }));
    check("live: no chart reload during polls", end.setData === start.setData, JSON.stringify({ start, end }));
    await click("On chart tab", ".pine-tab", "On chart");
    const meta = await evaluate(`__tv.text(".pine-script[data-script='pine-2'] .pine-script-meta")`);
    // A poll with a new tick re-runs exactly the forming bar; a poll without one re-runs nothing.
    check("live: only the forming bar is re-executed per poll", /· (0 bars|1 bar) re-run$/.test(meta || ""), meta);
    const counts = [];
    for (let i = 0; i < 8; i++) { const m = await evaluate(`__tv.text(".pine-script[data-script='pine-2'] .pine-script-meta")`); counts.push(m.match(/· (\d+) bars? re-run/)?.[1]); await sleep(600); }
    check("live: a tick re-runs exactly one bar", counts.includes("1") && counts.every((c) => c === "0" || c === "1"), JSON.stringify(counts));
    note("live: script meta", meta);
    const liveTitle = await evaluate(`__tv.doc().querySelector(".pine-script[data-script='pine-3'] .pine-script-meta").title`);
    check("live: request.security context comes from Binance (same source family)", / 60 · Binance Futures · native · /.test(liveTitle || ""), liveTitle);
    await click("Exit Live", ".live-bar .rp-btn", "✕ Exit"); await settle();
  }
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
