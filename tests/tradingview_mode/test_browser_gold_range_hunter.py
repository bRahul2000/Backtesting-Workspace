"""Browser acceptance: Rahul's exact 572-line "Gold Range Hunter - Monthly Profiles V2" strategy in the real terminal
(production build, real clicks) on Historical XAUUSDm M15 with the date range ending 2026-06-02 (the calculation range
is the non-sealed 2025-12-23 -> 2026-06-02; the chart shows May): unified Strategy Tester, exact trade count computed
headless on the same bars, fill -> marker reconciliation, duplicate prevention, lazy navigation to an older trade,
tooltip, dock resize/collapse and focus modes. Simulation only - never a broker order."""
import hashlib
import json
from pathlib import Path
import subprocess

import pandas as pd
import pytest

from services.market_datasets import EXNESS_XAUUSDM_H1, EXNESS_XAUUSDM_M15, dataset
from ui.tradingview_mode.pine import PineExecution, compile_script, run_script
from ui.tradingview_mode.pine.engine import data_context

from .conftest import CHROME, browser_available
from .pine.test_gold_range_hunter import FIXTURE, _truncated, _TruncatedProvider

SCRIPT = Path(__file__).with_name("browser") / "gold_range_hunter.mjs"

pytestmark = pytest.mark.skipif(not browser_available(), reason="needs node and Google Chrome")


def expected_run() -> dict:
    """The same calculation as the terminal: every M15 bar before 2026-06-03 (the chart's range end), native H1."""
    frame = _truncated(dataset(EXNESS_XAUUSDM_M15).path)
    result = compile_script(FIXTURE.read_text())
    provider = _TruncatedProvider("exness")
    out = run_script(PineExecution(result.program, {}, provider), data_context(
        frame, timeframe_seconds=900, ticker="XAUUSDm", tickerid="EXNESS:XAUUSDm", mintick=0.001, kind="cfd"),
        ("expected",), "pine-1", provider)
    assert out.error is None
    trades = out.strategy["trades"]
    return {"trades": len(trades), "fills": out.strategy["fill_count"], "first_entry": trades[0]["entry_time"],
            "first_key": trades[0]["key"], "last_bar": int(frame["timestamp"].iloc[-1].timestamp()),
            "display_start": "2026-05-01", "display_start_ts": int(pd.Timestamp("2026-05-01", tz="UTC").timestamp()),
            "end": "2026-06-02"}


def test_gold_range_hunter_workspace_acceptance(app, tmp_path):
    url, _ = app
    frozen = [dataset(key).path for key in (EXNESS_XAUUSDM_M15, EXNESS_XAUUSDM_H1)]
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in frozen]
    expected = expected_run()
    assert expected["last_bar"] < int(pd.Timestamp("2026-06-03", tz="UTC").timestamp())
    expected_path = tmp_path / "expected.json"
    expected_path.write_text(json.dumps(expected))
    completed = subprocess.run(["node", str(SCRIPT), url, CHROME, str(FIXTURE), str(expected_path)], capture_output=True,
                               text=True, timeout=900)
    results = json.loads(completed.stdout or "[]")
    failures = [r for r in results if not r["ok"]]
    assert results and not failures, json.dumps(failures, indent=1) + completed.stderr[-2000:]
    names = {r["name"] for r in results}
    assert {"chart shows the selected window only, ending before the sealed windows", "no separate Pine Strategy tab",
            "script on chart, one instance", "Strategy Tester opens automatically with the Pine source",
            "exact trade count (full calculation range, not the visible window)",
            "reconciliation: every reported fill is audited (fills = inside + outside)",
            "reconciliation: one rendered marker per fill on a loaded bar", "identical script is not added twice",
            "older bars lazy-load and the chart moves to the trade",
            "reconciliation after loading older bars: no marker lost", "fill tooltip shows side, price and comment",
            "dock resizes by dragging its top edge", "dock collapses",
            "chart only: no dock, watchlist, tools or Streamlit sidebar", "normal layout restored",
            "no page errors"} <= names
    # Historical freshness and refresh never touch the frozen datasets
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in frozen] == before
    print(json.dumps({"expected": expected, "notes": [r for r in results if r["name"].startswith(("overview", "reconciliation ("))]}))
