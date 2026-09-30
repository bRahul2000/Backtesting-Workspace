// Private Beta acceptance E/F: the redesigned Strategy Tester with Rahul's Gold Range Hunter - custom test range
// (changes the evaluation), tabs, chart geometry, trade navigation, and the Export Trades CSV download.
//
//   node beta_tester.mjs <app-url> <chrome> <fixture.pine> <download-dir> <screenshot-dir>
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, chromePath, fixture, downloads, shots] = process.argv.slice(2);
const SEALED = Date.parse("2026-06-03T00:00:00Z") / 1000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "zf-tester-"));
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
    if (!el) return { found: false }; el.scrollIntoView({ block: 'nearest' }); const r = el.getBoundingClientRect();
    const cx = r.x + r.width / 2, cy = r.y + r.height / 2; const top = d.elementFromPoint(cx, cy); const fr = this.f().getBoundingClientRect();
    return { found: true, x: fr.x + cx, y: fr.y + cy, disabled: !!el.disabled, visible: r.width > 0 && !!top && (top === el || el.contains(top)) }; },
  text(sel) { const e = this.d().querySelector(sel); return e ? e.innerText.replace(/\\s+/g, ' ').trim() : null; },
  chartRect() { const r = this.d().querySelector('.chart-panel').getBoundingClientRect(); return [r.x, r.y, r.width, r.height].map(Math.round).join(','); },
  trades() { return (this.w().__tvChart.pine.strategyTrades || []).map((t) => ({ number: t.number, open: t.open, entry_time: t.entry_time,
    entry_price: t.entry_price, exit_time: t.exit_time, exit_price: t.exit_price, qty: t.qty, profit: t.profit, direction: t.direction })); },
  rows() { return this.d().querySelectorAll('.st-trades tbody tr').length; },
  setInput(label, value) { const i = this.d().querySelector('input[aria-label="' + label + '"]');
    Object.getOwnPropertyDescriptor(this.w().HTMLInputElement.prototype, 'value').set.call(i, value);
    i.dispatchEvent(new (this.w().Event)('input', { bubbles: true })); i.dispatchEvent(new (this.w().Event)('change', { bubbles: true })); return i.value; },
  bars() { return this.w().__tvChart.bars.map((b) => b.time); },
};`;

// RFC 4180 CSV (quoted fields may contain commas, quotes and newlines)
function parseCsv(text) {
  const rows = []; let row = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; } else if (c === '"') quoted = false; else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
    else if (c !== "\r") field += c;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  return rows;
}

async function main() {
  const { send } = await cdp();
  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  };
  const waitFor = async (expression, ms = 30000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { try { if (await evaluate(expression)) return true; } catch { /* loading */ } await sleep(100); }
    return false;
  };
  const settle = async (ms = 120000) => { await sleep(150); await waitFor("__t.idle()", ms); await sleep(300); };
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
  const send_ = (type, data) => evaluate(`__t.w().__zfTerm.sendEvent(${JSON.stringify(type)}, ${JSON.stringify(data)})`);
  const shot = async (name) => { const { data } = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(shots, `${name}.png`), Buffer.from(data, "base64")); };

  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Page.enable");
  await send("Page.setDownloadBehavior", { behavior: "allow", downloadPath: downloads });
  await send("Page.navigate", { url });
  await waitFor("!!document.querySelector('iframe[title*=\"tradingview_terminal\"]')", 90000);
  await evaluate(HELPERS);
  check("terminal ready", await waitFor("__t.idle()", 120000));
  for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) {      // headless first-input activation
    await send("Input.dispatchMouseEvent", { type, x: 120, y: 700, button: "left", clickCount: 1 });
  }
  // XAUUSDm 15m, chart window May 2026 -> 2026-06-02 (never the sealed Gold V2 windows), then Gold Range Hunter
  await send_("select_dataset", { dataset_key: "EXNESS_XAUUSDM_M15" }); await settle();
  await send_("set_date_range", { start: "2026-05-01", end: "2026-06-02" }); await settle();
  await send_("pine_add", { source: readFileSync(fixture, "utf8") }); await settle(240000);
  check("Strategy Tester shows Gold Range Hunter", await waitFor("(__t.text('.st-name') || '').startsWith('Gold Range Hunter')", 60000), await evaluate("__t.text('.st-head')"));
  const head = await evaluate("__t.text('.st-head')");
  check("E: header: name, symbol, timeframe, status, range, export", /XAUUSDm · 15m/.test(head) && /Calculated/.test(head)
    && /Test range/.test(head) && /Export Trades CSV/.test(head), head);
  check("E: the added strategy's range ends at the chart's range end (2026-06-02)", /Custom · \d{4}-\d{2}-\d{2} → 2026-06-02/.test(await evaluate("__t.text('.st-range')") || ""),
    await evaluate("__t.text('.st-range')"));
  const full = await evaluate("__t.trades()");
  check("E: full-range trades exist and none touch the sealed window", full.length > 10 && full.every((t) => t.entry_time < SEALED && (t.exit_time ?? 0) < SEALED), full.length);
  const rect0 = await evaluate("__t.chartRect()");
  await shot("tester_overview");

  // custom range 2026-01-01 00:00 -> 2026-03-31 23:59 through the range editor
  await click("E: open range editor", ".st-range");
  await waitFor("!!__t.d().querySelector('.st-range-editor')", 5000);
  await click("E: choose Custom range", ".st-radio", "Custom range");
  await evaluate(`__t.setInput('Test from date', '2026-01-01')`); await evaluate(`__t.setInput('Test from time', '00:00')`);
  await evaluate(`__t.setInput('Test to date', '2026-03-31')`); await evaluate(`__t.setInput('Test to time', '23:59')`);
  await click("E: apply range", ".st-range-editor .btn", "Apply");
  await settle(240000);
  check("E: header shows the custom range", /Custom · 2026-01-0\d → 2026-03-3\d/.test(await evaluate("__t.text('.st-range')") || ""), await evaluate("__t.text('.st-range')"));
  const custom = await evaluate("__t.trades()");
  const from = Date.parse("2026-01-01T00:00:00Z") / 1000, to = Date.parse("2026-03-31T23:59:00Z") / 1000;
  check("E: the result changed (evaluation, not a list filter)", custom.length > 0 && custom.length !== full.length, `${full.length} -> ${custom.length}`);
  check("E: every trade lies inside the range", custom.every((t) => t.entry_time >= from && t.entry_time <= to && (t.exit_time === null || t.exit_time <= to + 900)),
    JSON.stringify(custom.filter((t) => t.entry_time < from || t.entry_time > to).slice(0, 3)));
  check("E: the chart window did not move with the test range", (await evaluate("__t.bars()")).at(-1) < SEALED
    && (await evaluate("__t.bars()"))[0] >= Date.parse("2026-05-01T00:00:00Z") / 1000);

  // tabs: geometry and range stay
  for (const tab of ["Performance", "List of Trades", "Properties", "Overview"]) {
    await click(`E: ${tab} tab`, ".st-tabs .subtab", tab); await sleep(250);
    check(`E: ${tab}: chart rectangle unchanged`, (await evaluate("__t.chartRect()")) === rect0);
    check(`E: ${tab}: range kept`, /Custom · 2026-01/.test(await evaluate("__t.text('.st-range')") || ""));
  }
  await click("E: List of Trades", ".st-tabs .subtab", "List of Trades"); await sleep(250);
  check("E: the table lists every trade", (await evaluate("__t.rows()")) === custom.length, `${await evaluate("__t.rows()")} vs ${custom.length}`);
  await click("E: sort by P&L", ".st-sort", "P&L"); await sleep(200);
  const pnls = await evaluate("[...__t.d().querySelectorAll('.st-trades tbody tr')].map((r) => r.children[7].innerText)");
  const nums = pnls.map((v) => (v === "—" ? -Infinity : Number(v.replace(/[,+]/g, ""))));
  check("E: sorting by P&L orders the rows", nums.every((v, i) => i === 0 || nums[i - 1] <= v), JSON.stringify(pnls.slice(0, 6)));
  await click("E: select a trade", ".st-trades tbody tr");
  await settle();
  check("E: the selected trade is highlighted", await waitFor("!!__t.d().querySelector('.st-trades tbody tr.is-selected')", 10000));
  await shot("tester_trades");

  // F. export the CSV and compare it with the tester's current result
  await click("F: Export Trades CSV", ".st-export", "Export Trades CSV");
  let file = null;
  for (let i = 0; i < 100 && !file; i++) { await sleep(200); file = readdirSync(downloads).find((f) => f.endsWith("_trades.csv")); }
  check("F: CSV downloaded", !!file, JSON.stringify(readdirSync(downloads)));
  if (file) {
    check("F: deterministic filename", /^Gold_Range_Hunter_Monthly_Profiles_V2_XAUUSDm_M15_2026-01-0\d_2026-03-3\d_trades\.csv$/.test(file), file);
    const text = readFileSync(join(downloads, file), "utf8");
    const [cols, ...records] = parseCsv(text);
    const rows = records.map((values) => Object.fromEntries(values.map((v, i) => [cols[i], v])));
    check("F: one row per trade", rows.length === custom.length, `${rows.length} vs ${custom.length}`);
    const byNumber = new Map(custom.map((t) => [t.number, t]));
    const bad = rows.filter((r) => { const t = byNumber.get(Number(r.trade_number));
      return !t || Number(r.entry_price) !== t.entry_price || Number(r.entry_time_epoch) !== t.entry_time
        || (t.profit !== null && Number(r.pnl) !== t.profit) || Number(r.quantity) !== t.qty
        || (r.exit_price === "") !== (t.exit_price === null) || r.direction !== (t.direction > 0 ? "long" : "short"); });
    check("F: raw values equal the tester's data (prices, times, qty, P&L)", bad.length === 0, JSON.stringify(bad.slice(0, 2)));
    check("F: rows carry strategy, symbol, timeframe and the test range", rows.every((r) => r.strategy.startsWith("Gold Range Hunter")
      && r.symbol === "XAUUSDm" && r.timeframe === "15m" && r.test_mode === "custom" && r.test_start_utc.startsWith("2026-01-0")
      && r.test_end_utc.startsWith("2026-03-3")), JSON.stringify(rows[0]));
  }
  const fatal = await evaluate("(() => { const f = __t.d().querySelector('.fatal'); return f ? f.textContent.slice(0, 600) : null; })()");
  check("no frontend fatal errors", fatal === null, fatal);
}

main().catch((e) => check("harness", false, e.stack || e.message)).finally(() => {
  chrome.kill();
  console.log(JSON.stringify(results));
  process.exit(0);
});
