"""Browser acceptance: P2.3a drawing objects in the real terminal (production build): historical, Replay (revealed
bars only) and Live (real Binance; drawings follow the forming bar without a chart reload)."""
import json
from pathlib import Path
import subprocess

import pytest

from .conftest import CHROME, binance_reachable, browser_available

SCRIPT = Path(__file__).with_name("browser") / "drawings.mjs"

pytestmark = pytest.mark.skipif(not (browser_available() and binance_reachable()),
                                reason="needs node, Google Chrome and the Binance public API")


def test_drawings_in_historical_replay_and_live(app):
    url, _ = app
    completed = subprocess.run(["node", str(SCRIPT), url, CHROME], capture_output=True, text=True, timeout=600)
    results = json.loads(completed.stdout or "[]")
    failures = [r for r in results if not r["ok"]]
    assert results and not failures, json.dumps(failures, indent=1) + completed.stderr[-2000:]
    names = {r["name"] for r in results}
    assert {"historical: drawings on the chart layer", "replay: no drawing from after the cursor",
            "replay step: the trend line advances with the cursor", "live: drawings present",
            "live: polls arrive without a chart reload", "no page errors"} <= names
