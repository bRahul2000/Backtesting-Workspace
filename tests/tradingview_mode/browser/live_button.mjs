// Browser regression for the "Live button does nothing" bug (production build).
//
//   node live_button.mjs <app-url> <chrome-binary>
//
// Drives Chrome over the DevTools protocol with Node's built-in WebSocket (no
// npm dependencies). Every click is a real mouse event at screen coordinates,
// and before each click the target must be the topmost painted element at its
// centre — so a control hidden by clipping/overlays fails, which is exactly how
// the clipped Live/Replay popovers escaped the earlier DOM-level tests.
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, chromePath] = process.argv.slice(2);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "tv-live-button-"));
const chrome = spawn(chromePath, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "--window-size=1440,900", "about:blank"], { stdio: "ignore" });
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail }); };

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
  // Real mouse click, only if the target is visible and topmost.
  const click = async (name, sel, text) => {
    const b = await box(sel, text);
    check(`${name}: visible and clickable`, b.found && b.visible && !b.disabled, JSON.stringify(b));
    if (!(b.found && b.visible && !b.disabled)) return false;
    for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) {
      await send("Input.dispatchMouseEvent", { type, x: b.x, y: b.y, button: "left", clickCount: 1 });
    }
    return true;
  };

  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Page.enable");
  await send("Page.navigate", { url });
  check("terminal loaded", await waitFor(`(() => { const f = document.querySelector('iframe[title*="tradingview_terminal"]'); return !!(f && f.contentDocument && f.contentDocument.querySelector('.terminal')); })()`, 90000));
  await evaluate(HELPERS);
  await settle();

  // A. Supported market: BTCUSDm / Exness / 15m → Live → controls → Go Live.
  await click("watchlist BTCUSDm", ".wl-row", "BTCUSDm"); await settle();
  await click("Live mode button", ".mode-btn", "Live"); await settle();
  const liveBtn = await box(".mode-btn", "Live");
  check("A: Live button becomes active", liveBtn.active, JSON.stringify(liveBtn));
  const setup = await box(".live-bar.is-setup");
  check("A: Live controls visible", setup.found && setup.visible, JSON.stringify(setup));
  check("A: BTCUSDm preselected", await evaluate(`__tv.find('.live-bar.is-setup select').value === 'BTCUSDm'`));
  await click("Go Live", ".go-live"); await settle(); await sleep(1500);
  const status = await evaluate(`__tv.text('.live-state')`);
  check("A: Go Live reaches a connection state", /^(LIVE|STALE|CONNECTING|DISCONNECTED|ERROR)$/.test(status || ""), status);
  check("A: status strip no longer in setup", !(await box(".live-bar.is-setup")).found);
  results.push({ name: "A: observed status", ok: true, detail: `${status} · ${await evaluate(`__tv.text('.live-bar')`)}` });

  // C. Back to Historical.
  await click("Historical button", ".mode-btn", "Historical"); await settle();
  check("C: Historical active again", (await box(".mode-btn", "Historical")).active);
  check("C: no live strip in Historical", !(await box(".live-bar")).found);

  // B. Unsupported market: BTC/USD Bitstamp → Live → explicit message, no Go Live.
  await click("watchlist BTC/USD", ".wl-row", "BTC/USD"); await settle();
  await click("Live mode button (Bitstamp)", ".mode-btn", "Live"); await settle();
  check("B: Live button becomes active", (await box(".mode-btn", "Live")).active);
  const unsupported = await box(".live-unsupported");
  check("B: unsupported-market message visible", unsupported.found && unsupported.visible
    && unsupported.text.startsWith("Live mode supports Exness BTCUSDm and XAUUSDm only."), JSON.stringify(unsupported));
  check("B: Go Live disabled until a symbol is chosen", (await box(".go-live")).disabled);
  await click("Exit Live", ".live-bar .rp-btn", "✕ Exit"); await settle();
  check("B: historical Bitstamp view kept", (await evaluate(`__tv.text('.symbol-name')`)) === "BTC/USD");

  // D. Replay still works afterwards (its popover must be visible too).
  await click("Replay mode button", ".mode-btn", "Replay"); await sleep(400);
  const replayMenu = await box(".popover .btn.primary", "Start replay");
  check("D: Replay start popover visible", replayMenu.found && replayMenu.visible, JSON.stringify(replayMenu));
  await evaluate(`(() => { const i = __tv.doc().querySelector('.popover input[type=date]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(i, '2026-06-10'); i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await click("Start replay", ".popover .btn.primary", "Start replay"); await settle();
  check("D: Replay started", (await box(".replay-bar")).visible && (await box(".mode-btn", "Replay")).active);
  await click("Exit Replay", ".replay-bar .rp-btn", "✕ Exit"); await settle();
  check("D: Historical after Replay", (await box(".mode-btn", "Historical")).active);
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
