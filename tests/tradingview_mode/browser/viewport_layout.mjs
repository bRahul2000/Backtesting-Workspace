// Browser acceptance: TradingView Mode uses the whole browser viewport (desktop trading terminal, not a centered card).
// Measures, at several window sizes, the real DOM: Streamlit sidebar, main container padding / max-width, the terminal
// iframe and the terminal itself; outer margins on all four sides; horizontal overflow; panel collapse behaviour.
//
//   node viewport_layout.mjs <app-url> <chrome-binary> [WxH,WxH,...]
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, chromePath, sizesArg] = process.argv.slice(2);
const SIZES = (sizesArg || "1920x1080,1728x1117,1440x900,1280x800").split(",").map((s) => s.split("x").map(Number));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "tv-viewport-"));
const chrome = spawn(chromePath, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "--window-size=1920,1200", "about:blank"], { stdio: "ignore" });
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

// Everything in page (top document) coordinates.
const MEASURE = `(() => {
  const r = (el) => { if (!el) return null; const b = el.getBoundingClientRect();
    return { left: Math.round(b.left), top: Math.round(b.top), right: Math.round(b.right), bottom: Math.round(b.bottom),
             width: Math.round(b.width), height: Math.round(b.height) }; };
  const frame = document.querySelector('iframe[title*="tradingview_terminal"]');
  const doc = frame && frame.contentDocument;
  const term = doc && doc.querySelector('.terminal');
  const f = frame.getBoundingClientRect();
  const t = term ? term.getBoundingClientRect() : null;
  const terminal = t && { left: Math.round(f.left + t.left), top: Math.round(f.top + t.top), right: Math.round(f.left + t.right),
    bottom: Math.round(f.top + t.bottom), width: Math.round(t.width), height: Math.round(t.height) };
  const sidebar = document.querySelector('[data-testid="stSidebar"]');
  const sidebarShown = sidebar && getComputedStyle(sidebar).display !== 'none' && sidebar.getBoundingClientRect().width > 0
    && sidebar.getAttribute('aria-expanded') !== 'false';
  // Streamlit renames its hooks between releases (1.64 stMainBlockContainer, 1.37 stAppViewBlockContainer)
  const block = document.querySelector('[data-testid="stMainBlockContainer"], [data-testid="stAppViewBlockContainer"], .block-container');
  // Deploy (by its text, whatever the release calls it) must not be visible
  const deploy = [...document.querySelectorAll('button, a')].filter((e) => e.innerText && e.innerText.trim() === 'Deploy')
    .some((e) => { const b = e.getBoundingClientRect(); const cs = getComputedStyle(e); return b.width > 0 && b.height > 0 && cs.visibility !== 'hidden'
      && b.bottom > 0 && b.right > 0 && b.top < innerHeight && b.left < innerWidth; });
  const cs = block && getComputedStyle(block);
  const part = (sel) => { const e = doc && doc.querySelector(sel); if (!e) return null; const b = e.getBoundingClientRect();
    return { left: Math.round(f.left + b.left), right: Math.round(f.left + b.right), width: Math.round(b.width), height: Math.round(b.height) }; };
  const vw = window.innerWidth, vh = window.innerHeight;
  const leftEdge = sidebarShown ? r(sidebar).right : 0;
  return {
    viewport: { width: vw, height: vh },
    sidebar: sidebarShown ? r(sidebar) : null,
    header: r(document.querySelector('[data-testid="stHeader"]')),
    block: block && { ...r(block), maxWidth: cs.maxWidth, padding: [cs.paddingTop, cs.paddingRight, cs.paddingBottom, cs.paddingLeft].join(' ') },
    iframe: r(frame), terminal, deployVisible: deploy, streamlit: window.__streamlitVersion || null,
    chart: part('.chart-panel'), watch: part('.watchlist'), dock: part('.bottom'), rail: part('.right-rail'),
    margins: terminal && { top: terminal.top, right: vw - terminal.right, bottom: vh - terminal.bottom, left: terminal.left - leftEdge },
    usable: { width: vw - leftEdge, height: vh },
    areaRatio: terminal ? +((terminal.width * terminal.height) / ((vw - leftEdge) * vh)).toFixed(3) : null,
    overflowX: document.documentElement.scrollWidth > vw || document.body.scrollWidth > vw,
    overflowY: document.documentElement.scrollHeight > vh + 1,
  };
})()`;

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
  const inFrame = (expr) => `(() => { const d = document.querySelector('iframe[title*="tradingview_terminal"]').contentDocument; return ${expr}; })()`;
  const clickIn = async (sel) => {
    const p = await evaluate(`(() => { const f = document.querySelector('iframe[title*="tradingview_terminal"]'); const e = f.contentDocument.querySelector(${JSON.stringify(sel)});
      if (!e) return null; const a = f.getBoundingClientRect(), b = e.getBoundingClientRect(); return { x: a.left + b.left + b.width / 2, y: a.top + b.top + b.height / 2 }; })()`);
    if (!p) return false;
    for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x: p.x, y: p.y, button: "left", clickCount: 1 });
    return true;
  };
  const shot = async (name) => { if (!process.env.PINE_SHOTS) return; const { writeFileSync } = await import("node:fs");
    writeFileSync(`${process.env.PINE_SHOTS}/${name}.png`, Buffer.from((await send("Page.captureScreenshot", { format: "png" })).data, "base64")); };
  // Open TradingView Mode the way a user does: the app's root, then the sidebar link. (Direct page URLs differ between
  // Streamlit releases: 1.64 derives /render_tradingview_mode from the function name, 1.37 does not.)
  const origin = new URL(url).origin;
  const openTerminal = async () => {
    await send("Page.navigate", { url: origin + "/" });
    await waitFor(`[...document.querySelectorAll('[data-testid="stSidebarNav"] a')].some((a) => a.innerText.trim() === 'TradingView Mode')`, 90000);
    const link = await evaluate(`(() => { const a = [...document.querySelectorAll('[data-testid="stSidebarNav"] a')].find((x) => x.innerText.trim() === 'TradingView Mode');
      const r = a.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
    for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x: link.x, y: link.y, button: "left", clickCount: 1 });
    return waitFor(inFrame("!!(d && d.querySelector('.terminal'))"), 90000);
  };
  const settle = async () => { await sleep(300); await waitFor(inFrame("d && d.querySelector('.sync') && d.querySelector('.sync').innerText.trim() === 'Synced'"), 60000); await sleep(700); };
  const errors = [];
  await send("Runtime.enable");
  ws.addEventListener("message", (m) => { const d = JSON.parse(m.data); if (d.method === "Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.text); });
  await send("Page.enable");

  for (const [width, height] of SIZES) {
    await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
    check(`${width}x${height}: terminal loaded from the sidebar`, await openTerminal());
    await settle();
    const m = await evaluate(MEASURE);
    note(`${width}x${height}: measured`, JSON.stringify(m));
    const dialog = await evaluate(`(() => [...document.querySelectorAll('[role="dialog"]')].some((d) => d.getBoundingClientRect().width > 0))()`);
    check(`${width}x${height}: no Streamlit dialog over the terminal`, !dialog, String(dialog));
    const mg = m.margins;
    check(`${width}x${height}: outer margins <= 10 px on all four sides`, mg && [mg.top, mg.right, mg.bottom, mg.left].every((v) => v >= 0 && v <= 10), JSON.stringify(mg));
    check(`${width}x${height}: workspace fills >= 96% of the usable area`, m.areaRatio >= 0.96, String(m.areaRatio));
    check(`${width}x${height}: no horizontal or vertical page overflow`, !m.overflowX && !m.overflowY, JSON.stringify([m.overflowX, m.overflowY]));
    check(`${width}x${height}: main block container found (release-specific hook)`, !!m.block, JSON.stringify(m.block));
    check(`${width}x${height}: no max-width cap on the main container`, m.block && (m.block.maxWidth === "none" || parseInt(m.block.maxWidth, 10) >= width), m.block && m.block.maxWidth);
    check(`${width}x${height}: Deploy is not visible`, !m.deployVisible, String(m.deployVisible));
    const menu = await evaluate(`(() => { const b = document.querySelector('[data-testid="stMainMenuButton"], [data-testid="stMainMenu"] button'); if (!b) return null; const r = b.getBoundingClientRect();
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return { left: Math.round(r.left), bottom: Math.round(r.bottom), reachable: !!top && b.contains(top) }; })()`);
    check(`${width}x${height}: Streamlit's main menu stays reachable (bottom-left, over the sidebar)`, menu && menu.reachable && menu.left <= 20 && menu.bottom >= height - 20, JSON.stringify(menu));
    check(`${width}x${height}: sidebar expanded 220-240 px`, m.sidebar && m.sidebar.width >= 220 && m.sidebar.width <= 240, JSON.stringify(m.sidebar));
    check(`${width}x${height}: dock aligned with the chart+watchlist width`, m.dock && m.chart && Math.abs(m.dock.left - m.chart.left) <= 1
      && Math.abs(m.dock.right - (m.watch ? m.watch.right : m.chart.right)) <= 1, JSON.stringify({ dock: m.dock, chart: m.chart, watch: m.watch }));
    await shot(`viewport_${width}x${height}`);
  }

  // At 1440x900: collapsing panels hands their space to the chart immediately.
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await openTerminal(); await settle();
  const base = await evaluate(MEASURE);
  check("watchlist default width 230-260 px", base.watch && base.watch.width >= 230 && base.watch.width <= 260, JSON.stringify(base.watch));
  await clickIn(".watch-collapse"); await settle();
  const noWatch = await evaluate(MEASURE);
  check("collapsing the watchlist widens the chart by its width (small rail left)", noWatch.chart.width >= base.chart.width + base.watch.width - 20
    && noWatch.rail && noWatch.rail.width <= 16, JSON.stringify({ before: base.chart.width, after: noWatch.chart.width, rail: noWatch.rail }));
  await clickIn(".right-rail"); await settle();
  const dockBefore = await evaluate(MEASURE);
  await clickIn(".bottom-tabs .icon-btn:last-child"); await settle();
  const noDock = await evaluate(MEASURE);
  check("collapsing the dock gives the chart the freed height", noDock.chart.height > dockBefore.chart.height + 50
    && Math.abs(noDock.terminal.height - dockBefore.terminal.height) <= 1, JSON.stringify({ before: dockBefore.chart.height, after: noDock.chart.height }));
  await clickIn(".bottom-tabs .icon-btn:last-child"); await settle();
  // Streamlit sidebar collapsed: 48-56 px icon rail (or hidden); the workspace grows.
  const collapse = await evaluate(`(() => { const b = document.querySelector('[data-testid="stSidebarCollapseButton"] button, [data-testid="stSidebarCollapseButton"], [data-testid="stSidebarHeader"] button');
    if (!b) return null; const r = b.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
  if (collapse) {
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 120, y: 300 });           // hover the sidebar
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: 120, y: 20 });            // ... and its header
    await sleep(400);                                   // Streamlit reveals the collapse button on hover
    const shown = await evaluate(`(() => { const b = document.querySelector('[data-testid="stSidebarCollapseButton"] button, [data-testid="stSidebarCollapseButton"], [data-testid="stSidebarHeader"] button');
      const r = b.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
    Object.assign(collapse, shown);
    await send("Input.dispatchMouseEvent", { type: "mouseMoved", x: collapse.x, y: collapse.y });
    await sleep(300);
    for (const type of ["mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x: collapse.x, y: collapse.y, button: "left", clickCount: 1 });
    await sleep(900); await settle();
    const narrow = await evaluate(MEASURE);
    // the collapsed rail is the main area's left padding (page.py draws it behind Streamlit's expand button)
    const rail = await evaluate(`(() => { const s = document.querySelector('[data-testid="stSidebar"]'); const m = document.querySelector('[data-testid="stMain"], section.main');
      const side = s && getComputedStyle(s).display !== 'none' ? Math.max(0, s.getBoundingClientRect().right) : 0;
      return Math.round(side + parseFloat(getComputedStyle(m).paddingLeft)); })()`);
    const expand = await evaluate(`(() => { const b = document.querySelector('[data-testid="stExpandSidebarButton"], [data-testid="collapsedControl"]'); if (!b) return null; const r = b.getBoundingClientRect(); return { left: Math.round(r.left), right: Math.round(r.right), visible: r.width > 0 }; })()`);
    note("sidebar collapsed", JSON.stringify({ rail, terminal: narrow.terminal, margins: narrow.margins }));
    check("collapsed sidebar is a 48-56 px rail with the expand button, and the workspace grows", rail >= 48 && rail <= 56
      && expand && expand.visible && expand.right <= rail && narrow.terminal.width > dockBefore.terminal.width + 150
      && narrow.terminal.left - rail <= 10, JSON.stringify({ rail, expand, before: dockBefore.terminal.width, after: narrow.terminal.width }));
    await shot("viewport_sidebar_collapsed");
  } else {
    check("sidebar collapse control present", false, "no stSidebarCollapseButton");
  }
  // Chart only: virtually the full viewport.
  await clickIn(".layout-btn"); await sleep(300);
  await clickIn('.layout-mode[data-mode="chart"]'); await settle();
  const chartOnly = await evaluate(MEASURE);
  note("chart only", JSON.stringify({ terminal: chartOnly.terminal, margins: chartOnly.margins, chart: chartOnly.chart }));
  check("chart only: terminal covers >= 97% of the viewport", chartOnly.terminal.width * chartOnly.terminal.height >= 0.97 * 1440 * 900,
    JSON.stringify(chartOnly.terminal));
  check("chart only: margins <= 10 px, no dock, watchlist or tools", [chartOnly.margins.top, chartOnly.margins.right, chartOnly.margins.bottom,
    chartOnly.terminal.left].every((v) => v >= 0 && v <= 10) && !chartOnly.dock && !chartOnly.watch, JSON.stringify(chartOnly.margins));
  await shot("viewport_chart_only");
  await clickIn(".layout-btn"); await sleep(300);
  await clickIn('.layout-mode[data-mode="normal"]'); await settle();
  const reopen = await evaluate(`(() => { const b = document.querySelector('[data-testid="stExpandSidebarButton"], [data-testid="collapsedControl"]'); if (!b) return null; const r = b.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
  if (reopen) {
    for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await send("Input.dispatchMouseEvent", { type, x: reopen.x, y: reopen.y, button: "left", clickCount: 1 });
    await sleep(900); await settle();
    const back = await evaluate(MEASURE);
    check("the rail's expand button restores the 240 px sidebar", back.sidebar && back.sidebar.width === 240 && back.margins.left <= 10, JSON.stringify({ sidebar: back.sidebar, margins: back.margins }));
  }
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
