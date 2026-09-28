"""Browser acceptance: P3.1 Pine strategies in the real terminal (production build): the broker emulator's fills as
chart markers and the Pine Strategy report (historical), nothing after the cursor (Replay) and Live paper - simulated
orders only, never a broker order."""
import json
from pathlib import Path
import subprocess

import pytest

from .conftest import CHROME, binance_reachable, browser_available

SCRIPT = Path(__file__).with_name("browser") / "strategy.mjs"

pytestmark = pytest.mark.skipif(not (browser_available() and binance_reachable()),
                                reason="needs node, Google Chrome and the Binance public API")


def test_pine_strategy_in_historical_replay_and_live_paper(app):
    url, _ = app
    completed = subprocess.run(["node", str(SCRIPT), url, CHROME], capture_output=True, text=True, timeout=600)
    results = json.loads(completed.stdout or "[]")
    failures = [r for r in results if not r["ok"]]
    assert results and not failures, json.dumps(failures, indent=1) + completed.stderr[-2000:]
    names = {r["name"] for r in results}
    assert {"historical: strategy fills are chart markers", "historical: report lists the trades",
            "historical: report is labelled simulation only", "replay: no strategy fill after the cursor",
            "live paper: the report is present", "no page errors"} <= names
