// P2.2 real-Live validation of request.security_lower_tf() in the actual terminal (headless Chrome, real clicks).
//
//   node live_lower_tf.mjs <app-url> <chrome> <binance|exness> <minutes> <scripts-dir>
//
// Adds the live oracle scripts (l1 for Binance; l2 + l3 for Exness), goes Live and samples every ~3 s what the
// terminal shows: the live state, the chart's own stream counters (no reload), the last Pine plot values of the
// forming and previous chart bars, the requested-context provenance and script errors. Then exits and re-enters
// Live (lease release / re-acquire). Prints one JSON document; the Python runner evaluates it. Nothing trades.
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, chromePath, mode, minutesArg, scriptsDir] = process.argv.slice(2);
const minutes = Number(minutesArg);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "tv-live-ltf-"));
const chrome = spawn(chromePath, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "--window-size=1440,900", "about:blank"], { stdio: "ignore" });
const out = { mode, started_utc: new Date().toISOString(), steps: [], samples: [], history: null, relive: [], after_switch: [] };
const step = (name, ok, detail = "") => { out.steps.push({ name, ok: !!ok, detail: String(detail).slice(0, 900) }); };
const log = (m) => process.stderr.write(`[${new Date().toISOString().slice(11, 19)}] ${m}\n`);

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
  choose(label, value) { const s = this.doc().querySelector('select[aria-label="' + label + '"]'); if (!s) return false;
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, value);
    s.dispatchEvent(new Event('change', { bubbles: true })); return true; },
  value(label) { const s = this.doc().querySelector('select[aria-label="' + label + '"]'); return s ? s.value : null; },
  setText(value) { const t = this.doc().querySelector('.pine-text'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(t, value);
    t.dispatchEvent(new Event('input', { bubbles: true })); return true; },
  chart() { const c = this.win().__tvChart; const s = c.debugState();
    return { count: s.count, last: s.last ? s.last.time : null, lastClose: s.last ? s.last.close : null, stats: s.stats }; },
  pine(tail) { return this.win().__tvChart.pine.scripts.map((s) => ({ title: s.title,
    plots: Object.fromEntries([...s.plots.values()].map((p) => [p.title, p.data.slice(-tail).map((d) => [d.time, d.value === undefined ? null : d.value])])) })); },
  rows() { return [...this.doc().querySelectorAll('.pine-script')].map((r) => ({ id: r.dataset.script,
    title: r.querySelector('.pine-script-title')?.innerText.trim(), meta: r.querySelector('.pine-script-meta')?.innerText.trim(),
    contexts: r.querySelector('.pine-script-meta')?.title || null, error: r.querySelector('.pine-script-error')?.innerText.trim() || null })); },
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
    while (Date.now() - t0 < ms) { try { if (await evaluate(expression)) return true; } catch { /* loading */ } await sleep(250); }
    return false;
  };
  const settle = async () => { await sleep(250); await waitFor("window.__tv && __tv.synced()"); await sleep(350); };
  const click = async (name, sel, label) => {
    const b = await evaluate(`__tv.box(${JSON.stringify(sel)}, ${label === undefined ? "undefined" : JSON.stringify(label)})`);
    const ok = b.found && b.visible && !b.disabled;
    step(`click ${name}`, ok, JSON.stringify(b));
    if (!ok) return false;
    for (const type of ["mouseMoved", "mousePressed", "mouseReleased"])
      await send("Input.dispatchMouseEvent", { type, x: b.x, y: b.y, button: "left", clickCount: 1 });
    return true;
  };
  const choose = async (label, value) => {
    const sent = await evaluate(`__tv.choose(${JSON.stringify(label)}, ${JSON.stringify(value)})`);
    await settle();
    const ok = sent && await waitFor(`__tv.value(${JSON.stringify(label)}) === ${JSON.stringify(value)}`, 15000);
    step(`choose ${label} = ${value}`, ok, await evaluate(`__tv.value(${JSON.stringify(label)})`));
    return ok;
  };
  const status = () => evaluate("__tv.text('.live-state')");
  const sample = async (into) => {
    try {
      into.push({ wall_ms: Date.now(), status: await status(), reason: await evaluate("__tv.text('.live-reason')"),
        chart: await evaluate("__tv.chart()"), pine: await evaluate("__tv.pine(2)"), rows: await evaluate("__tv.rows()") });
    } catch (error) { into.push({ wall_ms: Date.now(), error: String(error) }); }
  };
  const goLive = async (market, source, timeframe) => {
    await click("Live mode", ".mode-btn", "Live"); await settle();
    await choose("Live market", market); await choose("Live source", source); await choose("Live timeframe", timeframe);
    await click("Go Live", ".go-live"); await settle();
    const live = await waitFor(`__tv.text('.live-state') === 'LIVE'`, 90000);
    step(`LIVE ${market} ${source} ${timeframe}`, live, JSON.stringify({ bar: await evaluate("__tv.text('.live-bar')"),
      setup: await evaluate("__tv.text('.popover')"), notices: await evaluate("__tv.text('.notices') || __tv.text('.notice')") }));
    if (!live && process.env.LIVE_SHOTS) {
      const { writeFileSync } = await import("node:fs");
      writeFileSync(`${process.env.LIVE_SHOTS}/golive_${source}.png`, Buffer.from((await send("Page.captureScreenshot", { format: "png" })).data, "base64"));
    }
    return live;
  };
  const exitLive = async () => { await click("Exit Live", ".live-bar .rp-btn", "✕ Exit"); await settle(); };

  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Page.enable");
  await send("Page.navigate", { url });
  step("terminal loaded", await waitFor(`(() => { const f = document.querySelector('iframe[title*="tradingview_terminal"]'); return !!(f && f.contentDocument && f.contentDocument.querySelector('.terminal')); })()`, 120000));
  await evaluate(HELPERS);
  await settle();
  await click("watchlist BTCUSDm", ".wl-row", "BTCUSDm"); await settle();

  // Add the live oracle scripts through the Pine Editor (Compile, Add to chart).
  const scripts = mode === "binance" ? ["l1_binance_lower_tf.pine"] : ["l2_exness_lower_tf.pine", "l3_exness_below_m15.pine"];
  await click("Pine Editor tab", ".bottom-tab", "Pine Editor"); await settle();
  for (const [index, name] of scripts.entries()) {
    await evaluate(`__tv.setText(${JSON.stringify(readFileSync(join(scriptsDir, name), "utf8"))})`); await settle();
    await click(`Add ${name}`, ".pine-add"); await settle();
  }
  await click("On chart tab", ".pine-tab", "On chart"); await settle();
  step("scripts on chart", await waitFor(`__tv.rows().length === ${scripts.length}`, 20000), JSON.stringify(await evaluate("__tv.rows()")));

  const [market, source, timeframe] = mode === "binance" ? ["BTC", "binance", "15m"] : ["BTC", "exness", "1h"];
  if (!await goLive(market, source, timeframe)) return;
  await waitFor(`__tv.win().__tvChart.pine.scripts.every((s) => [...s.plots.values()].every((p) => p.data.length > 0)) || __tv.rows().some((r) => r.error)`, 60000);
  log(`LIVE; sampling ${minutes} min`);
  const end = Date.now() + minutes * 60000;
  while (Date.now() < end) { await sample(out.samples); await sleep(3000); }
  out.history = await evaluate("__tv.pine(40)");

  if (mode === "exness") {                     // 15m inside 30m and the same timeframe on a 30m chart (Live setup)
    await exitLive();
    if (await goLive(market, source, "30m")) {
      await sleep(4000);
      for (let i = 0; i < 20; i++) { await sample(out.after_switch); await sleep(3000); }
      out.after_switch_history = await evaluate("__tv.pine(40)");
    }
  }

  // Lease release and re-acquire: exit Live, re-enter, sample again.
  await exitLive();
  out.after_exit = { status: await status(), rows: await evaluate("__tv.rows()") };
  await sleep(5000);
  if (await goLive(market, source, timeframe)) {
    await sleep(5000);
    for (let i = 0; i < 12; i++) { await sample(out.relive); await sleep(3000); }
  }
  await exitLive();
  ws.close();
}

try {
  await main();
} catch (error) {
  step("harness completed", false, String(error && error.stack || error));
} finally {
  chrome.kill("SIGKILL");
  await sleep(300);
  try { rmSync(profile, { recursive: true, force: true }); } catch { /* ignore */ }
  out.finished_utc = new Date().toISOString();
  console.log(JSON.stringify(out));
}
