"""Private Beta round 1 browser acceptance on every installed Streamlit (Rahul's deployment runs 1.37.1):

A  idle terminal for 60 s through the production proxy + login: no full-app reruns, no Streamlit RUNNING/Stop
   status, nothing dimmed, account control / sidebar / chart iframe untouched (Historical and Live)
B-D indicators from the menu, on-chart eye / gear / X, duplicate instances, markets (beta_indicators.mjs)
E-F the redesigned Strategy Tester with Gold Range Hunter: custom test range, tabs, trade navigation, CSV export
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from .conftest import CHROME, ROOT, browser_available, streamlit_pythons
from .proxy_stack import CADDY, PASSWORD, USER, proxy_stack

BROWSER = Path(__file__).with_name("browser")
FEED = Path(__file__).with_name("synthetic_mt5_feed.py")
GRH = Path(__file__).with_name("pine") / "fixtures" / "gold_range_hunter_monthly_profiles_v2.pine"
SHELLS = streamlit_pythons() if browser_available() else []
IDS = [f"streamlit-{v}" for _, v in SHELLS]

pytestmark = pytest.mark.skipif(not browser_available(), reason="needs node and Chrome")


def _run(script, *args, timeout=1800):
    completed = subprocess.run(["node", str(BROWSER / script), *map(str, args)], capture_output=True, text=True,
                               timeout=timeout)
    results = json.loads(completed.stdout or "[]")
    return results, completed.stderr


@pytest.mark.skipif(not CADDY, reason="needs Caddy (ZONEFLOW_TEST_CADDY)")
@pytest.mark.parametrize("python, version", SHELLS, ids=IDS)
def test_idle_terminal_never_reruns_the_app_or_flashes(tmp_path, python, version):
    perf = tmp_path / "perf.jsonl"
    with proxy_stack(tmp_path, python, {"ZONEFLOW_PERF_LOG": str(perf)}) as (url, env):
        completed = subprocess.run(["node", str(BROWSER / "beta_perf.mjs"), url, CHROME, USER, PASSWORD, str(perf),
                                    sys.executable, str(FEED), env["TV_MT5_COMMON_FILES"], str(GRH)],
                                   capture_output=True, text=True, timeout=1800,
                                   env={**os.environ, "ZF_IDLE_SECONDS": "60"})
    out = json.loads(completed.stdout or "{}")
    failures = [r for r in out.get("results", []) if not r["ok"]]
    assert out.get("results") and not failures, json.dumps(failures, indent=1) + completed.stderr[-2000:]
    for window in ("idle_historical", "idle_live"):
        m = out["metrics"][window]
        assert m["full_runs"] == 0, (version, window, m)
        assert m["running_status_runs"] == 0 and m["running_widget_visible"] == 0, (version, window, m)
        assert m["terminal_dimmed_samples"] == 0 and m["account_swaps"] == 0 and m["account_hidden_samples"] == 0
        assert m["iframe_swaps"] == 0 and m["sidebar_moves"] == 0
    assert out["metrics"]["idle_historical"]["terminal_runs"] == 0          # Historical idle: nothing runs at all
    # every measured action ran the terminal only, never the whole app
    assert all(v.get("full_runs", 0) == 0 for v in out["metrics"].values() if isinstance(v, dict) and "ms" in v)
    (tmp_path / "metrics.json").write_text(json.dumps(out["metrics"], indent=1))
    print(json.dumps({"streamlit": version, "metrics": out["metrics"]}))


@pytest.mark.parametrize("python, version", SHELLS, ids=IDS)
def test_indicator_controls_markets_and_duplicates(app_with, tmp_path, python, version):
    url, _ = app_with(python)
    results, stderr = _run("beta_indicators.mjs", url, CHROME, tmp_path)
    failures = [r for r in results if not r["ok"]]
    assert results and not failures, json.dumps(failures, indent=1) + stderr[-2000:]
    assert len(results) >= 80


@pytest.mark.parametrize("python, version", SHELLS, ids=IDS)
def test_strategy_tester_range_tabs_and_csv(app_with, tmp_path, python, version):
    url, _ = app_with(python)
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    results, stderr = _run("beta_tester.mjs", url, CHROME, GRH, downloads, tmp_path)
    failures = [r for r in results if not r["ok"]]
    assert results and not failures, json.dumps(failures, indent=1) + stderr[-2000:]
    names = {r["name"] for r in results}
    assert {"E: the result changed (evaluation, not a list filter)", "E: every trade lies inside the range",
            "F: raw values equal the tester's data (prices, times, qty, P&L)", "F: deterministic filename"} <= names
