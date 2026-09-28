"""Browser acceptance: Live mode in the production build (headless Chrome).

Starts the real app (built frontend in dist/) with MT5 OFF (an empty MT5
Common/Files folder), then drives flows A-G with real mouse clicks:
Binance BTC and Gold LIVE without MT5, a switch to Exness while MT5 is off
(DISCONNECTED, no Binance data left), the MT5 bridge starting (Exness LIVE), the
switch back to Binance, then Historical and Replay. Uses the real Binance
public network; skipped when Chrome, Node or Binance is unavailable.
"""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from .conftest import CHROME, binance_reachable, browser_available

SCRIPT = Path(__file__).with_name("browser") / "live_button.mjs"
FEED = Path(__file__).with_name("synthetic_mt5_feed.py")

pytestmark = pytest.mark.skipif(not (browser_available() and binance_reachable()),
                                reason="needs node, Google Chrome and the Binance public API")


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
