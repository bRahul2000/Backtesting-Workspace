// Private Beta round 1: rerun / flicker / timing measurement on the real Streamlit shell, through the production
// proxy (Caddy + login), so the logged-in account control is present exactly as on zoneflow.in.
//
//   node beta_perf.mjs <proxy-url> <chrome> <user> <password> <perf-log> <python> <feed-script> <mt5-folder>
//
// Prints one JSON object: {results:[{name, ok, detail}], metrics:{...}}. Rerun counts come from the server's
// ZONEFLOW_PERF_LOG (full_run = the whole app script ran; terminal_run = the TradingView terminal ran).
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [proxyUrl, chromePath, username, password, perfLog, python, feedScript, mt5Folder, pineFixture] = process.argv.slice(2);
const IDLE_S = Number(process.env.ZF_IDLE_SECONDS || 60);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "zf-beta-"));
const chrome = spawn(chromePath, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "--window-size=1440,900", "about:blank"], { stdio: "ignore" });
const results = [];
const metrics = {};
const net = { mediaBytes: 0, mediaFiles: 0, wsBytes: 0 };
const mediaUrls = new Map();
const check = (name, ok, detail = "") => results.push({ name, ok: !!ok, detail: String(detail).slice(0, 800) });
let feed = null;

async function cdp() {
  const portFile = join(profile, "DevToolsActivePort");
  for (let i = 0; i < 100 && !existsSync(portFile); i++) await sleep(100);
  const port = readFileSync(portFile, "utf8").split("\n")[0];
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
  await new Promise((resolve) => { ws.onopen = resolve; });
  let id = 0;
  const pending = new Map();
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); return; }
    // data files (component/blobs.py) and Streamlit's websocket, byte counts as transferred (after compression)
    if (d.method === "Network.responseReceived") mediaUrls.set(d.params.requestId, d.params.response.url);
    if (d.method === "Network.loadingFinished" && /\/media\//.test(mediaUrls.get(d.params.requestId) || "")) {
      net.mediaBytes += d.params.encodedDataLength; net.mediaFiles += 1;
    }
    if (d.method === "Network.webSocketFrameReceived") net.wsBytes += (d.params.response.payloadData || "").length;
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const n = ++id;
    pending.set(n, (d) => (d.error ? reject(new Error(`${method}: ${d.error.message}`)) : resolve(d.result)));
    ws.send(JSON.stringify({ id: n, method, params }));
  });
  return { ws, send };
}

function perfLines(since, until = Infinity) {
  if (!existsSync(perfLog)) return [];
  return readFileSync(perfLog, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l))
    .filter((l) => l.t >= since && l.t <= until);
}

// Watches the main document for the Streamlit status widget ("Running…/Stop"), the account control being
// replaced/hidden, the terminal iframe being recreated, and the sidebar moving.
const WATCH = `(() => {
  const w = window.__zfWatch = { running: 0, runningNow: false, runningVisible: 0, shownNow: false, terminalDimmed: 0, accountSwaps: 0, accountHidden: 0, iframeSwaps: 0,
    sidebarMoves: 0, samples: 0 };
  const acc = () => document.querySelector('.zf-account');
  const frame = () => document.querySelector('iframe[title*="tradingview_terminal"]');
  const side = () => document.querySelector('[data-testid="stSidebar"]');
  let a0 = acc(), f0 = frame(), s0 = side() ? JSON.stringify(side().getBoundingClientRect()) : null;
  w.timer = setInterval(() => {
    w.samples++;
    const s = document.querySelector('[data-testid="stStatusWidget"]');
    const running = !!s && /running/i.test(s.innerText || '');
    const shown = running && s.getBoundingClientRect().width > 0 && getComputedStyle(s).visibility !== 'hidden';
    if (running && !w.runningNow) w.running++;
    if (shown && !w.shownNow) w.runningVisible++;
    w.runningNow = running; w.shownNow = shown;
    const opacity = (el) => { let o = 1; for (let e = el; e && e.nodeType === 1; e = e.parentElement) o *= Number(getComputedStyle(e).opacity); return o; };
    const a = acc();
    if (a !== a0) { w.accountSwaps++; a0 = a; }
    if (a0 && (a0.getBoundingClientRect().width === 0 || opacity(a0) < 0.99)) w.accountHidden++;
    if (frame() && opacity(frame()) < 0.99) w.terminalDimmed++;
    const f = frame();
    if (f !== f0) { w.iframeSwaps++; f0 = f; }
    const sb = side() ? JSON.stringify(side().getBoundingClientRect()) : null;
    if (sb !== s0) { w.sidebarMoves++; s0 = sb; }
  }, 50);
  return true;
})()`;

async function main() {
  const { send } = await cdp();
  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
    return r.result.value;
  };
  const waitFor = async (expression, ms = 60000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { try { if (await evaluate(expression)) return true; } catch { /* loading */ } await sleep(50); }
    return false;
  };
  const term = (js) => `(() => { const f = document.querySelector('iframe[title*="tradingview_terminal"]');
    const w = f && f.contentWindow; const d = f && f.contentDocument; if (!w || !d || !w.__zfTerm) return null; return (${js}); })()`;
  const idle = () => waitFor(term("w.__zfTerm.isIdle() && !!d.querySelector('.terminal')"), 120000);
  // one action = the event the UI sends -> Python processes it -> the terminal is idle again and has painted
  const act = async (label, type, data = {}) => {
    await idle();
    const n0 = { ...net };
    const t0 = Date.now();
    const since = t0 / 1000;
    await evaluate(term(`w.__zfTerm.sendEvent(${JSON.stringify(type)}, ${JSON.stringify(data)})`));
    await sleep(30);
    const ok = await idle();
    await evaluate(term("new Promise((r) => w.requestAnimationFrame(() => w.requestAnimationFrame(r)))"));
    const ms = Date.now() - t0;
    const runs = perfLines(since - 0.05).filter((l) => l.name === "terminal_run" && l.event === type);
    const server = runs[0] || {};
    metrics[label] = { ms, server_ms: server.total_ms ?? null, payload_bytes: server.payload_bytes ?? null,
      sent_bytes: server.sent_bytes ?? null, bar_count: server.bar_count ?? null, indicators_ms: server.indicators ?? null,
      full_runs: perfLines(since - 0.05).filter((l) => l.name === "full_run").length,
      ws_bytes: net.wsBytes - n0.wsBytes, media_bytes: net.mediaBytes - n0.mediaBytes, media_files: net.mediaFiles - n0.mediaFiles };
    check(`${label}: completed`, ok, JSON.stringify(metrics[label]));
    return metrics[label];
  };
  const idleWindow = async (label) => {
    await evaluate(WATCH);
    const n0 = { ...net };
    const since = Date.now() / 1000;
    await sleep(IDLE_S * 1000);
    const until = Date.now() / 1000;
    const w = await evaluate("(() => { clearInterval(window.__zfWatch.timer); return window.__zfWatch; })()");
    const lines = perfLines(since, until);
    metrics[label] = { seconds: IDLE_S, full_runs: lines.filter((l) => l.name === "full_run").length,
      terminal_runs: lines.filter((l) => l.name === "terminal_run").length,
      terminal_events: [...new Set(lines.filter((l) => l.name === "terminal_run").map((l) => l.event))],
      running_status_runs: w.running, running_widget_visible: w.runningVisible, terminal_dimmed_samples: w.terminalDimmed, account_swaps: w.accountSwaps, account_hidden_samples: w.accountHidden,
      iframe_swaps: w.iframeSwaps, sidebar_moves: w.sidebarMoves, samples: w.samples,
      ws_bytes: net.wsBytes - n0.wsBytes, media_bytes: net.mediaBytes - n0.mediaBytes };
    return metrics[label];
  };

  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Page.enable");
  await send("Network.enable");
  // log in through the real login page
  await send("Page.navigate", { url: proxyUrl });
  check("login page", await waitFor("!!document.querySelector('#username')", 30000));
  await evaluate(`(() => { const set = (id, v) => { const e = document.querySelector(id);
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(e, v);
    e.dispatchEvent(new Event('input', { bubbles: true })); }; set('#username', ${JSON.stringify(username)});
    set('#password', ${JSON.stringify(password)}); document.querySelector('form').submit(); return true; })()`);
  await waitFor("!!document.querySelector('[data-testid=\"stApp\"]')", 60000);
  // TradingView Mode, cold
  const t0 = Date.now();
  await send("Page.navigate", { url: proxyUrl.replace(/\/$/, "") + "/render_tradingview_mode" });
  const loaded = await waitFor(term("w.__zfTerm.isIdle() && !!d.querySelector('.terminal canvas') && !!d.querySelector('.sync')"), 180000);
  metrics.initial_load = { ms: Date.now() - t0 };
  check("TradingView Mode loads", loaded, JSON.stringify(metrics.initial_load));
  check("account control present", await evaluate("!!document.querySelector('.zf-account')"));

  await act("btc_15m_load", "select_dataset", { dataset_key: "EXNESS_BTCUSDM_M15" });
  await act("xau_15m_load", "select_dataset", { dataset_key: "EXNESS_XAUUSDM_M15" });
  await act("btc_to_xau_switch_back", "select_dataset", { dataset_key: "EXNESS_BTCUSDM_M15" });
  await act("btc_to_xau_switch", "select_dataset", { dataset_key: "EXNESS_XAUUSDM_M15" });
  await act("xau_timeframe_1h", "select_timeframe", { timeframe: "1h" });
  await act("xau_timeframe_15m", "select_timeframe", { timeframe: "15m" });
  await act("ema_add", "add_indicator", { key: "ema" });
  await act("rsi_add", "add_indicator", { key: "rsi" });
  await act("bottom_tab_change", "set_bottom_panel", { panel: "strategy_tester", open: true });
  await act("bottom_tab_back", "set_bottom_panel", { panel: "indicators", open: true });
  // ~20k bars: BTC 15m over ~210 days
  await act("btc_15m_select", "select_dataset", { dataset_key: "EXNESS_BTCUSDM_M15" });
  await act("btc_15m_20k_range", "set_date_range", { start: "2025-09-01", end: "2026-03-31" });
  await act("ema_add_20k", "add_indicator", { key: "ema" });
  await act("rsi_add_20k", "add_indicator", { key: "rsi" });

  if (pineFixture) {
    await act("xau_select_for_strategy", "select_dataset", { dataset_key: "EXNESS_XAUUSDM_M15" });
    // the strategy's test range ends before the sealed Gold V2 windows (it is fixed from the chart range when added)
    await act("xau_range_before_sealed", "set_date_range", { start: "2026-05-01", end: "2026-06-02" });
    await act("strategy_add_run", "pine_add", { source: readFileSync(pineFixture, "utf8") });
    await act("tester_tab_change_with_strategy", "set_bottom_panel", { panel: "indicators", open: true });
    await act("tester_tab_back_with_strategy", "set_bottom_panel", { panel: "strategy_tester", open: true });
    await act("ema_add_with_strategy", "add_indicator", { key: "ema" });
  }
  const hist = await idleWindow("idle_historical");
  check("historical idle: no full reruns", hist.full_runs === 0, JSON.stringify(hist));

  // Live (Exness MT5, synthetic bridge)
  feed = spawn(python, [feedScript, mt5Folder, "--seconds", "900"], { stdio: "ignore" });
  await sleep(3000);
  await act("live_enter", "enter_live");
  await act("live_go", "go_live", { market: "BTC", source: "exness", timeframe: "15m" });
  const live = await waitFor(term("(d.querySelector('.live-state') || {}).innerText === 'LIVE'"), 30000);
  check("Exness MT5 live reaches LIVE", live);
  metrics.live_note = await evaluate(term("d.querySelector('.live-bar') ? d.querySelector('.live-bar').innerText.slice(0, 200) : null"));
  const liveIdle = await idleWindow("idle_live");
  check("live idle: no full reruns", liveIdle.full_runs === 0, JSON.stringify(liveIdle));
}

main().catch((e) => check("harness", false, e.stack || e.message)).finally(() => {
  if (feed) feed.kill();
  chrome.kill();
  console.log(JSON.stringify({ results, metrics }, null, 1));
  process.exit(0);
});
