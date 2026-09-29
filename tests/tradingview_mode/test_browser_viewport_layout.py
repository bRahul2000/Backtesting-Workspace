"""Browser acceptance: TradingView Mode fills the browser viewport like a desktop trading terminal. At 1920x1080,
1728x1117, 1440x900 and 1280x800: outer margins <= 10 px on all four sides, >= 95% of the usable area, no page overflow,
no max-width cap, 240 px sidebar, dock spanning chart + watchlist; collapsing the watchlist, the dock or the sidebar
(a 52 px rail) hands the space to the chart; Chart only covers the viewport."""
import json
from pathlib import Path
import subprocess

import pytest

from .conftest import CHROME, browser_available

SCRIPT = Path(__file__).with_name("browser") / "viewport_layout.mjs"

pytestmark = pytest.mark.skipif(not browser_available(), reason="needs node and Google Chrome")


def test_workspace_fills_the_viewport(app):
    url, _ = app
    completed = subprocess.run(["node", str(SCRIPT), url, CHROME], capture_output=True, text=True, timeout=900)
    results = json.loads(completed.stdout or "[]")
    failures = [r for r in results if not r["ok"]]
    assert results and not failures, json.dumps(failures, indent=1) + completed.stderr[-2000:]
    names = {r["name"] for r in results}
    for size in ("1920x1080", "1728x1117", "1440x900", "1280x800"):
        assert {f"{size}: outer margins <= 10 px on all four sides", f"{size}: workspace fills >= 95% of the usable area",
                f"{size}: no horizontal or vertical page overflow"} <= names
    assert {"collapsing the watchlist widens the chart by its width (small rail left)",
            "collapsing the dock gives the chart the freed height",
            "collapsed sidebar is a 48-56 px rail with the expand button, and the workspace grows",
            "chart only: terminal covers >= 97% of the viewport", "no page errors"} <= names
