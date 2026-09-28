"""Browser acceptance: Pine Editor -> Compile -> Add to chart (production build).

Loads examples, compiles, adds an overlay and a pane script, checks precise
capability-gap and error reporting, input edits, hide/remove, Replay (revealed
bars only) and Live (real Binance; only the forming bar re-runs per poll).
"""
import json
from pathlib import Path
import subprocess

import pytest

from .conftest import CHROME, binance_reachable, browser_available

SCRIPT = Path(__file__).with_name("browser") / "pine_editor.mjs"

pytestmark = pytest.mark.skipif(not (browser_available() and binance_reachable()),
                                reason="needs node, Google Chrome and the Binance public API")


def test_pine_editor_with_real_clicks(app):
    url, _ = app
    completed = subprocess.run(["node", str(SCRIPT), url, CHROME], capture_output=True, text=True, timeout=600)
    results = json.loads(completed.stdout or "[]")
    failures = [r for r in results if not r["ok"]]
    assert results and not failures, json.dumps(failures, indent=1) + completed.stderr[-2000:]
    names = {r["name"] for r in results}
    assert {"script on chart", "second script on its own pane", "gap names request.dividends() and its line",
            "undeclared identifier reported", "input edit re-runs the script",
            "request.security: one requested context with same-source provenance",
            "replay: request.security output ends at the cursor", "replay: pine output ends at the cursor",
            "live: only the forming bar is re-executed per poll"} <= names
