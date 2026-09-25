"""Browser regression: live chart view stability (production build, real Binance XAUUSDT 15m).

1. open XAUUSDT Binance 15m Live (2,000 bars), zoom with the wheel, pan days back;
2-5. through at least 5 live refreshes the visible time/logical range, zoom and
   price scale stay exactly the same (and no setData happens);
6-7. Go to latest shows the newest candle and re-enables following;
8-9. the crosshair shows the candle's exact UTC time and Python OHLC;
plus older history at the left edge (same candles stay on screen) and a
timeframe switch resetting to the latest candle.
"""
import json
from pathlib import Path
import subprocess

import pytest

from .conftest import CHROME, binance_reachable, browser_available

SCRIPT = Path(__file__).with_name("browser") / "chart_view.mjs"

pytestmark = pytest.mark.skipif(not (browser_available() and binance_reachable()),
                                reason="needs node, Google Chrome and the Binance public API")


def test_live_chart_view_is_stable_with_real_input(app):
    url, _ = app
    completed = subprocess.run(["node", str(SCRIPT), url, CHROME], capture_output=True, text=True, timeout=600)
    results = json.loads(completed.stdout or "[]")
    failures = [r for r in results if not r["ok"]]
    assert results and not failures, json.dumps(failures, indent=1) + completed.stderr[-2000:]
    names = {r["name"] for r in results}
    assert {"visible time range unchanged", "zoom (bar spacing) unchanged", "price scale unchanged",
            "latest candle visible", "crosshair shows exact UTC time", "crosshair shows the candle's exact OHLC",
            "older history loaded at the left edge", "timeframe switch resets to latest"} <= names
