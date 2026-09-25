// Browser acceptance for Live mode (production build, real Binance network).
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
    while (Date.now() - t0 < ms) { try { if (await evaluate(expression)) return true; } catch { /* page loading */ } await sleep(200); }
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
  // Streaming selects are controlled by Python's payload: the value holds only once Python confirms it.
  const choose = async (label, value) => {
    const sent = await evaluate(`__tv.choose(${JSON.stringify(label)}, ${JSON.stringify(value)})`);
    await settle();
    return sent && await waitFor(`__tv.value(${JSON.stringify(label)}) === ${JSON.stringify(value)}`, 10000);
  };
  const waitStatus = (status, ms = 40000) => waitFor(`__tv.text('.live-state') === ${JSON.stringify(status)}`, ms);
  const state = async () => ({ status: await text(".live-state"), header: await text(".live-header"),
    quotes: await evaluate("__tv.quotes()"), source: await evaluate("__tv.source()"), note: await text(".lg-note"),
    legend: await text(".lg-symbol"), watch: await evaluate("__tv.watch()"), empty: await text(".chart-empty") });

  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Page.enable");
  await send("Page.navigate", { url });
  check("terminal loaded", await waitFor(`(() => { const f = document.querySelector('iframe[title*="tradingview_terminal"]'); return !!(f && f.contentDocument && f.contentDocument.querySelector('.terminal')); })()`, 90000));
  await evaluate(HELPERS);
  await settle();

  // A. MT5 OFF · BTC · Binance Futures · 15m · Go Live -> LIVE
  await click("watchlist BTCUSDm", ".wl-row", "BTCUSDm"); await settle();
  await click("Live mode button", ".mode-btn", "Live"); await settle();
  check("A: Live button active", (await box(".mode-btn", "Live")).active);
  const setup = await box(".live-bar.is-setup");
  check("A: Live setup visible", setup.found && setup.visible, JSON.stringify(setup));
  check("A: BTC preselected, Binance Futures default, 15m",
    (await evaluate("[__tv.value('Live market'), __tv.value('Live source'), __tv.value('Live timeframe')].join('|')")) === "BTC|binance|15m");
  check("A: setup names the contract", (await text(".live-contract")) === "BTCUSDT Perpetual · Binance Futures");
  await click("A: Go Live", ".go-live"); await settle();
  check("A: BTCUSDT Binance reaches LIVE with MT5 off", await waitStatus("LIVE"), await text(".live-bar"));
  // markPrice@1s may land up to a second after the first kline: wait for every quote.
  const allQuotes = (keys) => waitFor(`(() => { const q = __tv.quotes(); return ${JSON.stringify(keys)}.every((k) => q[k] && q[k] !== "—"); })()`, 8000);
  await allQuotes(["last", "mark", "bid", "ask", "spread"]);
  let s = await state();
  check("A: header BTCUSDT Perpetual · Binance Futures · LIVE", s.header === "BTCUSDT Perpetual · Binance Futures · LIVE", s.header);
  check("A: source is binance", s.source === "binance", JSON.stringify(s));
  const exitBox = await box(".live-bar .rp-btn", "✕ Exit");
  check("A: Exit stays visible with every Binance quote shown", exitBox.found && exitBox.visible, JSON.stringify(exitBox));
  const header = await box(".symbol-btn");
  check("A: header readable (not dimmed)", await evaluate("getComputedStyle(__tv.find('.symbol-btn')).opacity === '1'"), JSON.stringify(header));
  check("A: Exness warning note shown", s.note === "Reference market feed — execution prices may differ from Exness.", s.note);
  check("A: Binance quotes present", ["last", "mark", "bid", "ask", "spread"].every((k) => s.quotes[k] && s.quotes[k] !== "—"), JSON.stringify(s.quotes));
  check("A: legend names the source", s.legend === "BTCUSDT Perpetual · Binance Futures", s.legend);
  check("A: chart has bars", s.empty === null, s.empty);
  check("A: watchlist Binance rows labelled", s.watch.some((r) => r.startsWith("BTCUSDT PERP") && r.includes("BINANCE LIVE"))
    && s.watch.some((r) => r.startsWith("BTCUSDm") && r.includes("EXNESS OFF")), JSON.stringify(s.watch));
  const updated1 = await text(".live-meta");
  await sleep(3000);
  const updated2 = await text(".live-meta");
  check("A: last update changes", updated1 !== updated2, `${updated1} -> ${updated2}`);
  note("A: observed", `${s.header} · ${JSON.stringify(s.quotes)} · ${updated2}`);

  // B. MT5 OFF · Gold · Binance Futures · 15m · Go Live -> LIVE (through setup again)
  await click("A: Exit Live", ".live-bar .rp-btn", "✕ Exit"); await settle();
  await click("B: Live mode button", ".mode-btn", "Live"); await settle();
  check("B: choose Gold", await choose("Live market", "GOLD"));
  check("B: setup names the Gold contract", (await text(".live-contract")) === "XAUUSDT Perpetual · Binance Futures");
  await click("B: Go Live", ".go-live"); await settle();
  check("B: XAUUSDT Binance reaches LIVE with MT5 off", await waitStatus("LIVE"), await text(".live-bar"));
  await allQuotes(["last", "mark", "bid", "ask", "spread"]);
  s = await state();
  check("B: header XAUUSDT Perpetual · Binance Futures · LIVE", s.header === "XAUUSDT Perpetual · Binance Futures · LIVE", s.header);
  check("B: Gold quotes present", ["last", "mark", "bid", "ask"].every((k) => s.quotes[k] && s.quotes[k] !== "—"), JSON.stringify(s.quotes));
  check("B: Gold watchlist row labelled", s.watch.some((r) => r.startsWith("XAUUSDT PERP") && r.includes("BINANCE LIVE")), JSON.stringify(s.watch));
  note("B: observed", `${s.header} · ${JSON.stringify(s.quotes)}`);

  // C. BTC: Binance -> Exness while MT5 is offline -> clear DISCONNECTED, nothing Binance left.
  check("C: switch market to BTC", await choose("Live market", "BTC"));
  check("C: BTC Binance LIVE again", await waitStatus("LIVE"), await text(".live-bar"));
  const binanceBtc = await state();
  check("C: switch source to Exness MT5", await choose("Live source", "exness"));
  check("C: Exness offline is DISCONNECTED", await waitStatus("DISCONNECTED", 15000), await text(".live-bar"));
  s = await state();
  check("C: header BTCUSDm · Exness MT5 · DISCONNECTED", s.header === "BTCUSDm · Exness MT5 · DISCONNECTED", s.header);
  check("C: no Binance value masquerading as Exness", s.source === "exness" && Object.values(s.quotes).every((v) => v === "—")
    && !("mark" in s.quotes) && !("last" in s.quotes), JSON.stringify(s.quotes));
  check("C: no Binance note on Exness", s.note === null, s.note);
  check("C: no Binance bars kept", s.empty !== null, s.empty);
  check("C: reason explains MT5 is off", /MT5 live feed not found/.test(await text(".live-reason") || ""), await text(".live-reason"));
  note("C: observed", `${s.header} · binance before: ${JSON.stringify(binanceBtc.quotes)}`);

  // D. Start the MT5 bridge -> Exness LIVE.
  feed = spawn(python, [feedScript, mt5Folder, "--seconds", "600"], { stdio: "ignore" });
  check("D: Exness MT5 BTCUSDm reaches LIVE once the bridge runs", await waitStatus("LIVE", 20000), await text(".live-bar"));
  s = await state();
  check("D: header BTCUSDm · Exness MT5 · LIVE", s.header === "BTCUSDm · Exness MT5 · LIVE", s.header);
  check("D: Exness quotes are bid/ask/spread only", JSON.stringify(Object.keys(s.quotes)) === '["bid","ask","spread"]'
    && s.quotes.bid !== "—", JSON.stringify(s.quotes));
  check("D: Exness watchlist row live", s.watch.some((r) => r.startsWith("BTCUSDm") && r.includes("EXNESS LIVE")), JSON.stringify(s.watch));
  check("D: chart has MT5 bars", s.empty === null, s.empty);
  note("D: observed", `${s.header} · ${JSON.stringify(s.quotes)}`);

  // E. Exness -> Binance: clean reload.
  check("E: switch source to Binance", await choose("Live source", "binance"));
  check("E: Binance LIVE again", await waitStatus("LIVE"), await text(".live-bar"));
  await allQuotes(["last", "mark", "bid", "ask"]);
  s = await state();
  check("E: header back to BTCUSDT Perpetual · Binance Futures · LIVE", s.header === "BTCUSDT Perpetual · Binance Futures · LIVE", s.header);
  check("E: Binance quotes, not MT5 values", s.source === "binance" && s.quotes.mark !== "—" && s.quotes.bid !== "—", JSON.stringify(s.quotes));
  check("E: legend reloaded for Binance", s.legend === "BTCUSDT Perpetual · Binance Futures", s.legend);
  note("E: observed", `${s.header} · ${JSON.stringify(s.quotes)}`);

  // F. Historical afterwards.
  await click("F: Historical button", ".mode-btn", "Historical"); await settle();
  check("F: Historical active", (await box(".mode-btn", "Historical")).active);
  check("F: no live strip", !(await box(".live-bar")).found);
  check("F: historical dataset symbol back", (await text(".symbol-name")) === "BTCUSDm", await text(".symbol-name"));
  check("F: no live watchlist rows", (await evaluate("__tv.watch().length")) === 0);

  // Bitstamp: explicit message (not a silent no-op), BTC preselected, different instrument stated.
  await click("watchlist BTC/USD", ".wl-row", "BTC/USD"); await settle();
  await click("Bitstamp: Live mode button", ".mode-btn", "Live"); await settle();
  const msg = await box(".live-unsupported");
  check("Bitstamp: explicit message", msg.found && msg.text.startsWith("BTC/USD (Bitstamp) has no live feed."), JSON.stringify(msg));
  check("Bitstamp: BTC preselected", (await evaluate("__tv.value('Live market')")) === "BTC");
  await click("Bitstamp: Exit Live", ".live-bar .rp-btn", "✕ Exit"); await settle();
  check("Bitstamp: historical view kept", (await text(".symbol-name")) === "BTC/USD");

  // G. Replay afterwards.
  await click("G: Replay mode button", ".mode-btn", "Replay"); await sleep(400);
  const replayMenu = await box(".popover .btn.primary", "Start replay");
  check("G: Replay start popover visible", replayMenu.found && replayMenu.visible, JSON.stringify(replayMenu));
  await evaluate(`(() => { const i = __tv.doc().querySelector('.popover input[type=date]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, '2026-06-10'); i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await click("G: Start replay", ".popover .btn.primary", "Start replay"); await settle();
  check("G: Replay started", (await box(".replay-bar")).visible && (await box(".mode-btn", "Replay")).active);
  await click("G: Exit Replay", ".replay-bar .rp-btn", "✕ Exit"); await settle();
  check("G: Historical after Replay", (await box(".mode-btn", "Historical")).active);
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
