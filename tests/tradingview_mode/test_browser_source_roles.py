"""Browser acceptance: Chart / Signals / Execution source roles (production build).

A. MT5 off: Binance Gold chart LIVE, Exness signals UNAVAILABLE, execution DISABLED.
B. MT5 bridge started: signal authority ready, execution still DISABLED.
C. Chart Binance -> Exness -> Binance: the signal source stays Exness MT5 throughout.
D. Bridge stopped: authority drops within the stale timeout, the Binance chart keeps updating.
E. Bridge restarted: authority returns only after fresh Exness data is revalidated.
Plus: no source roles in Historical or Replay. The MT5 bridge is the synthetic feed
writing into a temporary folder (the real MetaTrader folder is never touched).
"""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from .conftest import CHROME, binance_reachable, browser_available

SCRIPT = Path(__file__).with_name("browser") / "source_roles.mjs"
FEED = Path(__file__).with_name("synthetic_mt5_feed.py")

pytestmark = pytest.mark.skipif(not (browser_available() and binance_reachable()),
                                reason="needs node, Google Chrome and the Binance public API")


def test_source_roles_with_real_clicks(app):
    url, mt5_folder = app
    completed = subprocess.run(["node", str(SCRIPT), url, CHROME, sys.executable, str(FEED), str(mt5_folder)],
                               capture_output=True, text=True, timeout=600)
    results = json.loads(completed.stdout or "[]")
    failures = [r for r in results if not r["ok"]]
    assert results and not failures, json.dumps(failures, indent=1) + completed.stderr[-2000:]
    names = {r["name"] for r in results}
    assert {"A: signals = Exness MT5 · XAUUSDm UNAVAILABLE (MT5 DISCONNECTED)", "B: signal_authority_ready",
            "C: signal source stayed Exness MT5 · XAUUSDm and LIVE throughout", "D: signal authority disabled",
            "E: signal authority restored", "Replay: no live signal/execution readiness shown"} <= names
