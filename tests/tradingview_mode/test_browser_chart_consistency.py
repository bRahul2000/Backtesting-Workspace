"""Browser acceptance (Rahul's screen recording), on every installed Streamlit that serves the real app:
the chart rectangle is pixel-identical across bottom-dock tabs (one persistent dock height; a drag-resized height
and the collapsed state survive tab changes, symbol switches and a reload); after the price axis was dragged on BTC,
switching BTC/USD -> XAUUSDm -> BTCUSDm -> XAUUSDm -> BTC/USD (with different tabs open) resets the vertical scale
to the new data, keeps the time window, clears the previous symbol's selected trade / price lines and rebuilds the
strategy markers; no volume histogram by default and no space reserved for it."""
import json
from pathlib import Path
import subprocess

import pytest

from .conftest import CHROME, browser_available, streamlit_pythons

SCRIPT = Path(__file__).with_name("browser") / "chart_consistency.mjs"
SHELLS = streamlit_pythons() if browser_available() else []

pytestmark = pytest.mark.skipif(not browser_available(), reason="needs node and Google Chrome")


@pytest.mark.parametrize("python, version", SHELLS, ids=[f"streamlit-{v}" for _, v in SHELLS])
def test_chart_consistency(app_with, python, version):
    url, _ = app_with(python)
    completed = subprocess.run(["node", str(SCRIPT), url, CHROME], capture_output=True, text=True, timeout=900)
    results = json.loads(completed.stdout or "[]")
    failures = [r for r in results if not r["ok"]]
    assert results and not failures, f"Streamlit {version}: " + json.dumps(failures, indent=1) + completed.stderr[-2000:]
    names = {r["name"] for r in results}
    assert {"default chart: no volume histogram and no Vol in the legend", "default chart: no vertical space reserved for volume",
            "tab Pine Editor: chart, watchlist and dock rectangles unchanged", "resized dock, tab Logs: height and chart unchanged",
            "BTC/USD: dragging the price axis turned autoScale off (the recorded state)",
            "XAUUSDm (Indicators open): right price scale fits the new symbol, candles visible",
            "BTCUSDm (Strategy Tester open): right price scale fits the new symbol, candles visible",
            "XAUUSDm: the horizontal time window is kept", "XAUUSDm: strategy markers rebuilt for the new symbol",
            "collapsed dock survives a reload", "the resized height is remembered after a reload",
            "Settings -> Volume shows the histogram and reserves its space", "unticking Volume removes it again",
            "no page errors"} <= names
