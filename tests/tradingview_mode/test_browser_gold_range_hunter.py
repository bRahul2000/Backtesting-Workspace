"""Browser acceptance: Rahul's exact 572-line "Gold Range Hunter - Monthly Profiles V2" strategy pasted into the Pine
Editor, compiled, added to the XAUUSDm chart (inside Replay, cursor before 2026-06-03), its Pine Strategy report,
inputs, remove / re-add - simulation only, never a broker order."""
import json
from pathlib import Path
import subprocess

import pytest

from .conftest import CHROME, browser_available

SCRIPT = Path(__file__).with_name("browser") / "gold_range_hunter.mjs"
FIXTURE = Path(__file__).parent / "pine" / "fixtures" / "gold_range_hunter_monthly_profiles_v2.pine"

pytestmark = pytest.mark.skipif(not browser_available(), reason="needs node and Google Chrome")


def test_gold_range_hunter_compiles_adds_to_chart_and_backtests(app):
    url, _ = app
    completed = subprocess.run(["node", str(SCRIPT), url, CHROME, str(FIXTURE)], capture_output=True, text=True,
                               timeout=900)
    results = json.loads(completed.stdout or "[]")
    failures = [r for r in results if not r["ok"]]
    assert results and not failures, json.dumps(failures, indent=1) + completed.stderr[-2000:]
    names = {r["name"] for r in results}
    assert {"replay cursor is before the sealed windows", "compile reports success", "no problems listed",
            "script on chart", "strategy fills are chart markers",
            "markers show the order comments (SETUP_* entries, TP / FULL_SL / TRAIL_SL exits)",
            "range boxes and entry / SL / TP lines are drawn",
            "input.time fields show 2025-08-31 18:30 and 2030-12-31 18:29 UTC", "report lists the trades",
            "re-added report has the same trades", "no 'Pine script not added' rejection", "no page errors"} <= names
