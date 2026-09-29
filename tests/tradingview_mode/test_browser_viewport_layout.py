"""Browser acceptance: TradingView Mode fills the browser viewport like a desktop trading terminal - on EVERY installed
Streamlit that serves the real app (the page CSS depends on Streamlit's DOM, whose hooks change between releases:
the project venv has 1.64, Rahul's app runs /opt/anaconda3's 1.37.1). The terminal is opened from the sidebar, as a
user does. At 1920x1080, 1728x1117, 1440x900 and 1280x800: outer margins <= 10 px on all four sides, >= 96% of the
usable area, no page overflow, no max-width cap, Deploy not visible, no dialog, 240 px sidebar, dock spanning chart +
watchlist; collapsing the watchlist, the dock or the sidebar (a 52 px rail) hands the space to the chart; Chart only
covers the viewport."""
import json
from pathlib import Path
import subprocess

import pytest

from .conftest import CHROME, browser_available, streamlit_pythons

SCRIPT = Path(__file__).with_name("browser") / "viewport_layout.mjs"
SHELLS = streamlit_pythons() if browser_available() else []

pytestmark = pytest.mark.skipif(not browser_available(), reason="needs node and Google Chrome")


def test_the_real_app_shells_are_covered():
    """Guard: the Streamlit used by Rahul's app (/opt/anaconda3, 1.37.1 when present) is among the tested shells."""
    versions = {version for _, version in SHELLS}
    if Path("/opt/anaconda3/bin/python").exists():
        assert any(python == "/opt/anaconda3/bin/python" for python, _ in SHELLS), SHELLS
    assert versions, "no Streamlit found"


@pytest.mark.parametrize("python, version", SHELLS, ids=[f"streamlit-{v}" for _, v in SHELLS])
def test_workspace_fills_the_viewport(app_with, python, version):
    url, _ = app_with(python)
    completed = subprocess.run(["node", str(SCRIPT), url, CHROME], capture_output=True, text=True, timeout=900)
    results = json.loads(completed.stdout or "[]")
    failures = [r for r in results if not r["ok"]]
    assert results and not failures, f"Streamlit {version}: " + json.dumps(failures, indent=1) + completed.stderr[-2000:]
    names = {r["name"] for r in results}
    for size in ("1920x1080", "1728x1117", "1440x900", "1280x800"):
        assert {f"{size}: outer margins <= 10 px on all four sides", f"{size}: workspace fills >= 96% of the usable area",
                f"{size}: no horizontal or vertical page overflow", f"{size}: Deploy is not visible",
                f"{size}: main block container found (release-specific hook)",
                f"{size}: no Streamlit dialog over the terminal"} <= names
    assert {"collapsing the watchlist widens the chart by its width (small rail left)",
            "collapsing the dock gives the chart the freed height",
            "collapsed sidebar is a 48-56 px rail with the expand button, and the workspace grows",
            "chart only: terminal covers >= 97% of the viewport", "no page errors"} <= names
