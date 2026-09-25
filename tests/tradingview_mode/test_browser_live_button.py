"""Browser acceptance: Live mode in the production build (headless Chrome).

Starts the real app (built frontend in dist/) with MT5 OFF (an empty MT5
Common/Files folder), then drives flows A-G with real mouse clicks:
Binance BTC and Gold LIVE without MT5, a switch to Exness while MT5 is off
(DISCONNECTED, no Binance data left), the MT5 bridge starting (Exness LIVE), the
switch back to Binance, then Historical and Replay. Uses the real Binance
public network; skipped when Chrome, Node or Binance is unavailable.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("browser") / "live_button.mjs"
FEED = Path(__file__).with_name("synthetic_mt5_feed.py")
CHROME = os.environ.get("CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def _binance_reachable() -> bool:
    try:
        urllib.request.urlopen("https://fapi.binance.com/fapi/v1/time", timeout=5)
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not (shutil.which("node") and Path(CHROME).exists() and _binance_reachable()),
                                reason="needs node, Google Chrome and the Binance public API")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def app(tmp_path):
    mt5_folder = tmp_path / "mt5files"   # MT5 OFF: exists, but nothing writes to it
    mt5_folder.mkdir()
    port = _free_port()
    env = {**os.environ, "TV_MT5_COMMON_FILES": str(mt5_folder)}
    server = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"), "--server.headless", "true",
                               "--server.port", str(port), "--browser.gatherUsageStats", "false"],
                              cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        yield f"http://127.0.0.1:{port}/render_tradingview_mode", mt5_folder
    finally:
        server.terminate()
        server.wait(10)


def test_live_modes_with_real_clicks(app):
    url, mt5_folder = app
    completed = subprocess.run(["node", str(SCRIPT), url, CHROME, sys.executable, str(FEED), str(mt5_folder)],
                               capture_output=True, text=True, timeout=600)
    results = json.loads(completed.stdout or "[]")
    failures = [r for r in results if not r["ok"]]
    assert results and not failures, json.dumps(failures, indent=1) + completed.stderr[-2000:]
    names = {r["name"] for r in results}
    assert {"A: BTCUSDT Binance reaches LIVE with MT5 off", "B: XAUUSDT Binance reaches LIVE with MT5 off",
            "C: no Binance value masquerading as Exness", "D: Exness MT5 BTCUSDm reaches LIVE once the bridge runs",
            "E: Binance LIVE again", "F: Historical active", "G: Replay started",
            "Bitstamp: explicit message"} <= names
