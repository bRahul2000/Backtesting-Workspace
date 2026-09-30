// Private Beta acceptance B/C/D: indicators from the menu, on-chart eye / gear / X controls, duplicate instances,
// markets. Real mouse clicks at screen coordinates; each target must be the topmost element at its centre.
//
//   node beta_indicators.mjs <app-url> <chrome> <screenshot-dir>
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, chromePath, shots] = process.argv.slice(2);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "zf-ind-"));
const chrome = spawn(chromePath, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "--window-size=1440,900", "about:blank"], { stdio: "ignore" });
const results = [];
const check = (name, ok, detail = "") => results.push({ name, ok: !!ok, detail: String(detail).slice(0, 700) });

async function cdp() {
  const portFile = join(profile, "DevToolsActivePort");
  for (let i = 0; i < 100 && !existsSync(portFile); i++) await sleep(100);
  const port = readFileSync(portFile, "utf8").split("\n")[0];
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve) => { ws.onopen = resolve; });
  let id = 0;
  const pending = new Map();
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const n = ++id;
    pending.set(n, (d) => (d.error ? reject(new Error(`${method}: ${d.error.message}`)) : resolve(d.result)));
    ws.send(JSON.stringify({ id: n, method, params }));
  });
  return { send };
}

const HELPERS = `window.__t = {
  f() { return document.querySelector('iframe[title*="tradingview_terminal"]'); },
  d() { const f = this.f(); return f && f.contentDocument; },
  w() { const f = this.f(); return f && f.contentWindow; },
  idle() { const w = this.w(); return !!(w && w.__zfTerm && w.__zfTerm.isIdle() && this.d().querySelector('.terminal canvas')); },
  box(sel, text) { const d = this.d(); const all = [...d.querySelectorAll(sel)];
    const el = text === undefined ? all[0] : all.find((e) => (e.getAttribute('aria-label') || e.innerText || '').trim().startsWith(text));
    if (!el) return { found: false }; el.scrollIntoView({ block: 'nearest' }); const r = el.getBoundingClientRect(); const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
    const top = d.elementFromPoint(cx, cy); const fr = this.f().getBoundingClientRect();
    return { found: true, x: fr.x + cx, y: fr.y + cy, disabled: !!el.disabled,
      visible: r.width > 0 && !!top && (top === el || el.contains(top)), topmost: top ? top.tagName + '.' + top.className : null }; },
  rows() { return [...this.d().querySelectorAll('.lg-ind.is-native')].map((r) => ({ id: r.dataset.indicator,
    pane: !!r.closest('.pane-legend'), hidden: r.classList.contains('is-hidden'), text: r.innerText.replace(/\\s+/g, ' ').trim() })); },
  chartRect() { const c = this.d().querySelector('.chart-panel'); const r = c.getBoundingClientRect();
    return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)].join(','); },
  engine() { return this.w().__tvChart; },
  seriesVisible(id) { const e = this.engine(); const entry = e.overlays.get(id) || e.panes.find((p) => p.id === id);
    return entry ? entry.series.map((s) => s.api.options().visible) : null; },
  paneCount() { return this.engine().chart.panes().length; },
  status(id) { const e = this.engine(); const entry = e.overlays.get(id) || e.panes.find((p) => p.id === id); return entry ? entry.status : null; },
};`;

async function main() {
  const { send } = await cdp();
  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  };
  const waitFor = async (expression, ms = 30000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { try { if (await evaluate(expression)) return true; } catch { /* loading */ } await sleep(80); }
    return false;
  };
  const settle = async () => { await sleep(150); await waitFor("__t.idle()", 60000); await sleep(250); };
  const click = async (name, sel, text) => {
    const b = await evaluate(`__t.box(${JSON.stringify(sel)}, ${text === undefined ? "undefined" : JSON.stringify(text)})`);
    const ok = b.found && b.visible && !b.disabled;
    check(`${name}: visible and clickable`, ok, JSON.stringify(b));
    if (!ok) return false;
    for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) {
      await send("Input.dispatchMouseEvent", { type, x: b.x, y: b.y, button: "left", clickCount: 1 });
    }
    return true;
  };
  const hover = async (sel, text) => {
    const b = await evaluate(`__t.box(${JSON.stringify(sel)}, ${JSON.stringify(text)})`);
    if (b.found) await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: b.x, y: b.y });
  };
  const rows = () => evaluate("__t.rows()");
  const row = async (prefix) => (await rows()).find((r) => r.text.startsWith(prefix));
  const shot = async (name) => {
    const { data } = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(shots, `${name}.png`), Buffer.from(data, "base64"));
  };
  const addFromMenu = async (label) => {
    await click(`open Indicators menu for ${label}`, ".topbar button", "Indicators");
    await waitFor("!!__t.d().querySelector('.popover .menu-row')", 5000);
    const ok = await click(`menu: Add ${label}`, ".menu-row", `Add ${label}`);
    if (!ok) check(`menu rows for ${label}`, false, JSON.stringify(await evaluate("[...__t.d().querySelectorAll('.menu-row')].map((e) => e.getAttribute('aria-label') || e.innerText.slice(0, 20))")));
    await settle();
    return ok;
  };

  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Page.enable");
  await send("Page.navigate", { url });
  await waitFor("!!document.querySelector('iframe[title*=\"tradingview_terminal\"]')", 90000);
  await evaluate(HELPERS);
  check("terminal ready", await waitFor("__t.idle()", 120000));
  await evaluate("__t.w().__zfTerm.sendEvent('select_dataset', { dataset_key: 'EXNESS_BTCUSDM_M15' })");
  await settle();
  // headless Chrome swallows the page's very first input event (window activation): one neutral click on the
  // empty sidebar area first, exactly where a user's first click would land without effect
  for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) {
    await send("Input.dispatchMouseEvent", { type, x: 120, y: 700, button: "left", clickCount: 1 });
  }
  const rect0 = await evaluate("__t.chartRect()");

  // B. add EMA, RSI, MACD, Bollinger Bands from the menu
  for (const label of ["EMA", "RSI", "MACD", "Bollinger Bands"]) check(`B: ${label} added from the menu`, await addFromMenu(label));
  let r = await rows();
  const byName = (prefix) => r.find((x) => x.text.startsWith(prefix));
  check("B: EMA and BB in the price legend, RSI and MACD in their pane headers",
    byName("EMA") && !byName("EMA").pane && byName("Bollinger") && !byName("Bollinger").pane
    && byName("RSI")?.pane && byName("MACD")?.pane, JSON.stringify(r));
  check("B: two lower panes created", (await evaluate("__t.paneCount()")) === 3, await evaluate("__t.paneCount()"));
  check("B: chart rectangle unchanged by adding indicators", (await evaluate("__t.chartRect()")) === rect0);
  await shot("indicators_added");

  // hide / show each from its own on-chart control
  for (const x of r) {
    const label = x.text.split(" ").slice(0, x.text.startsWith("Bollinger") ? 4 : 2).join(" ");
    await hover(".lg-ind", x.text.slice(0, 6));
    await click(`B: hide ${x.id}`, ".lg-btn", `Hide ${label}`);
    await sleep(120);
    const hiddenNow = await evaluate(`__t.seriesVisible(${JSON.stringify(x.id)})`);
    check(`B: ${x.id} hidden instantly on the chart`, hiddenNow && hiddenNow.every((v) => v === false), JSON.stringify(hiddenNow));
    await settle();
    check(`B: ${x.id} stays hidden after Python confirms`, (await rows()).find((y) => y.id === x.id)?.hidden);
    await click(`B: show ${x.id}`, ".lg-btn", `Show ${label}`);
    await settle();
    const shown = await evaluate(`__t.seriesVisible(${JSON.stringify(x.id)})`);
    check(`B: ${x.id} shown again`, shown && shown.every((v) => v === true), JSON.stringify(shown));
  }
  check("B: chart rectangle unchanged by hide/show", (await evaluate("__t.chartRect()")) === rect0);

  // settings (gear) -> EMA length 50
  const ema = await row("EMA");
  await click("B: EMA settings", ".lg-btn", "Settings EMA 20");
  await sleep(200);
  check("B: settings editor opens with Length", await waitFor("!!__t.d().querySelector('.ind-settings input[aria-label=\"Length\"]')", 5000));
  await click("B: focus Length", ".ind-settings input", "");
  await evaluate("__t.d().querySelector('.ind-settings input').select()");
  await send("Input.insertText", { text: "50" });
  await sleep(150);
  await click("B: Apply settings", ".ind-settings .btn", "Apply");
  await settle();
  check("B: EMA now EMA 50", (await rows()).find((y) => y.id === ema.id)?.text.startsWith("EMA 50"), JSON.stringify(await rows()));

  // C. duplicate EMA with independent controls
  check("C: second EMA added", await addFromMenu("EMA"));
  r = await rows();
  const emas = r.filter((x) => x.text.startsWith("EMA"));
  check("C: EMA 50 and EMA 20 coexist", emas.length === 2 && emas.some((x) => x.text.startsWith("EMA 50"))
    && emas.some((x) => x.text.startsWith("EMA 20")), JSON.stringify(emas));
  const second = emas.find((x) => x.text.startsWith("EMA 20"));
  await click("C: hide only EMA 20", ".lg-btn", "Hide EMA 20");
  await settle();
  check("C: EMA 20 hidden, EMA 50 untouched", (await evaluate(`__t.seriesVisible(${JSON.stringify(second.id)})`))[0] === false
    && (await evaluate(`__t.seriesVisible(${JSON.stringify(ema.id)})`))[0] === true);

  // remove from the chart: RSI pane reclaimed, others unaffected
  const panesBefore = await evaluate("__t.paneCount()");
  await click("B: remove RSI", ".lg-btn", "Remove RSI 14");
  await settle();
  r = await rows();
  check("B: RSI removed, its pane space reclaimed", !r.some((x) => x.text.startsWith("RSI"))
    && (await evaluate("__t.paneCount()")) === panesBefore - 1, `${panesBefore} -> ${await evaluate("__t.paneCount()")}`);
  check("B: MACD, BB and both EMAs remain", r.some((x) => x.text.startsWith("MACD")) && r.some((x) => x.text.startsWith("Bollinger"))
    && r.filter((x) => x.text.startsWith("EMA")).length === 2, JSON.stringify(r));
  const fatal = await evaluate("(() => { const f = __t.d().querySelector('.fatal'); return f ? f.textContent.slice(0, 900) : null; })()");
  check("B: no render error after remove", fatal === null, fatal);
  await click("B: remove Bollinger Bands", ".lg-btn", "Remove Bollinger Bands 20 2");
  await settle();
  check("B: Bollinger Bands removed", !(await rows()).some((x) => x.text.startsWith("Bollinger")));
  check("B: chart rectangle unchanged by remove", (await evaluate("__t.chartRect()")) === rect0);

  // D. markets: the same indicators on gold, then traded-volume BTC (Bitstamp) with VWAP vs Exness tick volume
  for (const key of ["EXNESS_XAUUSDM_M15", "EXNESS_BTCUSDM_H1", "BITSTAMP_BTCUSD_15M"]) {
    await evaluate(`__t.w().__zfTerm.sendEvent('select_dataset', { dataset_key: '${key}' })`);
    await settle();
    r = await rows();
    const statuses = await evaluate(`__t.rows().map((x) => __t.status(x.id))`);
    check(`D: ${key}: every indicator draws`, r.length === 3 && statuses.every((s) => s === "ok"), JSON.stringify([r, statuses]));
  }
  check("D: VWAP on Bitstamp (traded volume)", await addFromMenu("VWAP"));
  let vwap = (await rows()).find((x) => x.text.startsWith("VWAP"));
  check("D: VWAP is OK on traded volume", vwap && (await evaluate(`__t.status(${JSON.stringify(vwap.id)})`)) === "ok", JSON.stringify(vwap));
  await evaluate("__t.w().__zfTerm.sendEvent('select_dataset', { dataset_key: 'EXNESS_XAUUSDM_M15' })");
  await settle();
  vwap = (await rows()).find((x) => x.text.startsWith("VWAP"));
  check("D: VWAP on Exness tick volume is marked LIMITED", vwap && vwap.text.includes("LIMITED")
    && (await evaluate(`__t.status(${JSON.stringify(vwap.id)})`)) === "limited", JSON.stringify(vwap));
  for (const label of ["Supertrend", "Stochastic", "Pivots High/Low", "Keltner Channels", "Donchian Channels", "WMA", "SMA", "ATR"]) {
    check(`D: ${label} added on gold`, await addFromMenu(label));
  }
  const all = await evaluate(`__t.rows().map((x) => [x.text.split(' ')[0], __t.status(x.id)])`);
  check("D: every listed indicator draws on gold (VWAP limited)", all.every(([name, s]) => s === "ok" || (name === "VWAP" && s === "limited")), JSON.stringify(all));
  check("D: chart rectangle unchanged", (await evaluate("__t.chartRect()")) === rect0);
  await shot("indicators_gold_all");
  const errors = await evaluate("__t.w().__zfTerm && [...__t.d().querySelectorAll('.fatal')].length");
  check("no frontend fatal errors", errors === 0);
}

main().catch((e) => check("harness", false, e.stack || e.message)).finally(() => {
  chrome.kill();
  console.log(JSON.stringify(results));
  process.exit(0);
});
