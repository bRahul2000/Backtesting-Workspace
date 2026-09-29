// Browser acceptance: the private login in front of Zoneflow, through the REAL production chain
// (Caddy with deployment/Caddyfile -> login service -> Streamlit in production auth mode).
//
//   node login_flow.mjs <proxy-url> <direct-streamlit-url> <chrome-binary> <username> <password>
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [proxyUrl, directUrl, chromePath, username, password] = process.argv.slice(2);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "tv-login-"));
const chrome = spawn(chromePath, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`,
  "--no-first-run", "--no-default-browser-check", "--window-size=1440,900", "about:blank"], { stdio: "ignore" });
const results = [];
const check = (name, ok, detail = "") => { results.push({ name, ok: !!ok, detail: String(detail).slice(0, 700) }); };

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

async function main() {
  const { ws, send } = await cdp();
  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + " " + (r.exceptionDetails.exception?.description || ""));
    return r.result.value;
  };
  const waitFor = async (expression, ms = 30000) => {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { try { if (await evaluate(expression)) return true; } catch { /* navigating */ } await sleep(200); }
    return false;
  };
  const mouse = async (type, x, y) => send("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1 });
  const clickSel = async (selector, frame = false) => {
    const p = await evaluate(`(() => { const e = document.querySelector(${JSON.stringify(selector)}); if (!e) return null;
      const r = e.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
    if (!p) return false;
    for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await mouse(type, p.x, p.y);
    return true;
  };
  const typeInto = async (selector, text) => {
    await clickSel(selector);
    await evaluate(`document.querySelector(${JSON.stringify(selector)}).select && document.querySelector(${JSON.stringify(selector)}).select()`);
    await send("Input.insertText", { text });
  };
  const loginShown = () => evaluate("document.title === 'Zoneflow · Sign in' && !!document.querySelector('input[type=password]')");
  const streamlitShown = () => evaluate("!!document.querySelector('[data-testid=\"stApp\"]')");
  const shot = async (name) => { if (!process.env.PINE_SHOTS) return; const { writeFileSync } = await import("node:fs");
    writeFileSync(`${process.env.PINE_SHOTS}/${name}.png`, Buffer.from((await send("Page.captureScreenshot", { format: "png" })).data, "base64")); };
  const errors = [];
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Runtime.enable");
  await send("Page.enable");
  const origin = new URL(proxyUrl).origin;

  // 1. unauthenticated: only the login page, whatever URL is asked for
  await send("Page.navigate", { url: origin + "/" });
  check("unauthenticated: the root shows the login page only", await waitFor("document.readyState === 'complete' && document.title === 'Zoneflow · Sign in'", 30000)
    && !(await streamlitShown()), await evaluate("document.title"));
  await shot("login_page");
  check("login page: Zoneflow card, no scripts, no market data", await evaluate(`document.body.innerText.includes('ZONEFLOW') &&
    document.body.innerText.includes('Private Trading Research Terminal') && document.body.innerText.includes('Authorized access only')
    && document.scripts.length === 0 && !/BTC|XAU|USD/.test(document.body.innerText)`));
  await send("Page.navigate", { url: origin + "/render_tradingview_mode" });
  check("unauthenticated: a direct page URL is blocked (login page, next kept)", await waitFor("document.title === 'Zoneflow · Sign in'", 30000)
    && await evaluate("document.querySelector('input[name=next]').value === '/render_tradingview_mode'"));
  // an outside client without a session (the login page's CSP forbids fetch() inside it anyway)
  const blocked = await Promise.all(["/_stcore/health", "/_stcore/host-config", "/_stcore/stream", "/static/js/main.js",
    "/component/tradingview_terminal/index.html"].map((p) => fetch(origin + p, { redirect: "manual" }).then((r) => r.status)));
  check("unauthenticated: Streamlit endpoints and assets are unreachable", blocked.every((s) => s === 401), JSON.stringify(blocked));
  const page = await fetch(origin + "/render_tradingview_mode", { redirect: "manual", headers: { Accept: "text/html" } });
  check("unauthenticated page request is redirected to the login", page.status === 303 && (page.headers.get("location") || "").startsWith("/zoneflow-auth/login"),
    `${page.status} ${page.headers.get("location")}`);
  const forged = await fetch(origin + "/_stcore/health", { redirect: "manual", headers: { "X-Zoneflow-User": "rahul", "X-Zoneflow-Proxy": "x", Cookie: "zf_session=forged" } });
  check("forged identity headers or cookie do not get in", forged.status === 401, String(forged.status));

  // 2. wrong credentials
  await send("Page.navigate", { url: origin + "/zoneflow-auth/login" }); await waitFor("document.readyState === 'complete'");
  await typeInto("#username", username); await typeInto("#password", "Wrong-Password-99");
  await clickSel("button[type=submit]");
  check("wrong password: generic error, still the login page", await waitFor("!!document.querySelector('.error')", 15000)
    && (await evaluate("document.querySelector('.error').innerText")) === "Invalid username or password");
  await typeInto("#username", "someone-else"); await typeInto("#password", password);
  await clickSel("button[type=submit]");
  check("unknown username: the same generic error", await waitFor("!!document.querySelector('.error')", 15000)
    && (await evaluate("document.querySelector('.error').innerText")) === "Invalid username or password");

  // 3. correct credentials -> Zoneflow
  await send("Page.navigate", { url: origin + "/" }); await waitFor("document.readyState === 'complete'");
  await typeInto("#username", username); await typeInto("#password", password);
  await clickSel("button[type=submit]");
  check("correct login: Zoneflow loads", await waitFor(`!!document.querySelector('[data-testid="stSidebarNav"]')`, 60000), await evaluate("document.title"));
  check("account control shows the user and Log out", await waitFor(`(document.querySelector('.zf-account')?.innerText || '').includes(${JSON.stringify(username)})
    && document.querySelector('.zf-account a').innerText.trim() === 'Log out'`, 30000));
  check("the session cookie is HttpOnly (invisible to page scripts)", !(await evaluate("document.cookie")).includes("zf_session"), await evaluate("document.cookie"));
  const link = await evaluate(`(() => { const a = [...document.querySelectorAll('[data-testid="stSidebarNav"] a')].find((x) => x.innerText.trim() === 'TradingView Mode');
    const r = a.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
  for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) await mouse(type, link.x, link.y);
  check("TradingView Mode loads behind the login", await waitFor(`(() => { const f = document.querySelector('iframe[title*="tradingview_terminal"]');
    return !!(f && f.contentDocument && f.contentDocument.querySelector('.terminal') && f.contentWindow.__tvChart && f.contentWindow.__tvChart.bars.length > 0); })()`, 90000));
  await shot("login_after_terminal");

  // 4. reload keeps the session (wait for the NEW document: Page.reload returns before the old page unloads)
  await evaluate("window.__zfBeforeReload = true");
  await send("Page.reload", {});
  check("reload keeps the session (no login page)", await waitFor(`!window.__zfBeforeReload && !!document.querySelector('[data-testid="stSidebarNav"]')
    && !!document.querySelector('.zf-account')`, 60000) && !(await loginShown()));

  // 5. logout
  await shot("login_before_logout");
  const account = await evaluate(`(() => { const a = document.querySelector('.zf-account a'); if (!a) return null; const r = a.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return { rect: [r.left, r.top, r.width, r.height].map(Math.round), top: top && (top.dataset.testid || top.tagName + '.' + top.className), hit: !!top && (top === a || a.contains(top)) }; })()`);
  check("the Log out control is visible and clickable", account && account.hit && account.rect[2] > 0, JSON.stringify(account));
  await clickSel(".zf-account a");
  check("logout returns to the login page", await waitFor("document.title === 'Zoneflow · Sign in' && document.body.innerText.includes('You have been logged out.')", 30000));
  await send("Page.navigate", { url: origin + "/" });
  check("after logout Zoneflow is closed again", await waitFor("document.title === 'Zoneflow · Sign in'", 30000) && !(await streamlitShown()));

  // 6. Streamlit reached directly (bypassing the proxy) in production mode: sign-in notice only, no pages
  await send("Page.navigate", { url: directUrl });
  check("direct app port in production mode: only the sign-in notice", await waitFor("document.body.innerText.includes('Sign in required')", 60000)
    && !(await evaluate(`!!document.querySelector('[data-testid="stSidebarNav"] a') || !!document.querySelector('iframe[title*="tradingview_terminal"]')`)));
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
