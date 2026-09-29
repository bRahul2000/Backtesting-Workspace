"""Browser acceptance: Historical data freshness + automatic / manual Refresh on XAUUSDm (production build, real clicks).

The app reads a SYNTHETIC MT5 Common/Files folder (a CopyRates export and a Live feed seed extending XAUUSDm past the
frozen 2026-09-18 20:30 bar, the seed's last row still forming) and writes only to the test's temporary workspace
folder. Checks: stale detection, closed bars only, no duplicate or missing appended bars, the date picker, a built-in
indicator, a Pine plot and a Pine strategy recalculating without re-adding, and the frozen dataset unchanged."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from services.market_datasets import EXNESS_XAUUSDM_M15, dataset

from .conftest import CHROME, browser_available

SCRIPT = Path(__file__).with_name("browser") / "data_refresh.mjs"
FROZEN_LAST = pd.Timestamp("2026-09-18 20:30", tz="UTC")

pytestmark = pytest.mark.skipif(not browser_available(), reason="needs node and Google Chrome")


def synthetic_bars() -> pd.DataFrame:
    """Friday 20:45 (the week's last bar) then Sunday 22:00 ... Monday 06:15 (M15)."""
    times = [pd.Timestamp("2026-09-18 20:45", tz="UTC")]
    times += list(pd.date_range("2026-09-20 22:00", "2026-09-21 06:15", freq="15min", tz="UTC"))
    rng = np.random.default_rng(7)
    close = 4380.893 + np.cumsum(rng.normal(0, 2.0, len(times)))
    open_ = np.r_[4380.893, close[:-1]]
    high = np.maximum(open_, close) + rng.uniform(0.1, 2.0, len(times))
    low = np.minimum(open_, close) - rng.uniform(0.1, 2.0, len(times))
    return pd.DataFrame({"timestamp": times, "open": open_, "high": high, "low": low, "close": close})


def write_sources(folder: Path, frame: pd.DataFrame) -> None:
    export = frame[frame["timestamp"] <= pd.Timestamp("2026-09-21 03:00", tz="UTC")]
    lines = ["timestamp,open,high,low,close,tick_volume,spread,real_volume"] + [
        f"{r.timestamp.strftime('%Y.%m.%d %H:%M:%S')},{r.open:.3f},{r.high:.3f},{r.low:.3f},{r.close:.3f},1000,240,0"
        for r in export.itertuples()]
    (folder / "xauusd_XAUUSDm_M15.csv").write_text("\n".join(lines) + "\n")
    (folder / "xauusd_XAUUSDm_M15.csv.metadata.json").write_text(json.dumps({
        "symbol": "XAUUSDm", "timeframe": "M15", "server_utc_offset_seconds_at_capture": 0,
        "current_incomplete_bar_excluded": True, "capture_server_time": "2026.09.21 03:20:00"}))
    seed = frame[frame["timestamp"] >= pd.Timestamp("2026-09-21 00:00", tz="UTC")]     # last row 06:15 is forming
    lines = ["time,open,high,low,close,tick_volume,spread"] + [
        f"{int(r.timestamp.timestamp())},{r.open:.3f},{r.high:.3f},{r.low:.3f},{r.close:.3f},900,240"
        for r in seed.itertuples()]
    path = folder / "tv_live_XAUUSDm_M15_seed.csv"
    path.write_text("\n".join(lines) + "\n")
    written = pd.Timestamp("2026-09-21 06:15:02", tz="UTC").timestamp()
    os.utime(path, (written, written))
    (folder / "tv_live_XAUUSDm_quote.json").write_text(json.dumps(
        {"symbol": "XAUUSDm", "server_time": int(written), "gmt_time": int(written)}))


def test_historical_refresh_extends_chart_indicators_and_strategy(app, tmp_path):
    url, mt5_folder = app
    frozen = dataset(EXNESS_XAUUSDM_M15).path
    before_hash = hashlib.sha256(frozen.read_bytes()).hexdigest()
    frame = synthetic_bars()
    staged = tmp_path / "staged"                     # copied into the MT5 folder by the browser script, mid-test
    staged.mkdir()
    write_sources(staged, frame)
    closed = frame[frame["timestamp"] <= pd.Timestamp("2026-09-21 06:00", tz="UTC")]
    expected = {"before_last": int(FROZEN_LAST.timestamp()),
                "new_times": [int(t.timestamp()) for t in closed["timestamp"]],
                "after_last": int(closed["timestamp"].iloc[-1].timestamp()), "after_last_text": "2026-09-21 06:00",
                "after_date": "2026-09-21", "staged": str(staged), "mt5_folder": str(mt5_folder),
                "seed_written": pd.Timestamp("2026-09-21 06:15:02", tz="UTC").timestamp()}
    expected_path = tmp_path / "expected.json"
    expected_path.write_text(json.dumps(expected))
    completed = subprocess.run(["node", str(SCRIPT), url, CHROME, str(expected_path)], capture_output=True, text=True,
                               timeout=600)
    results = json.loads(completed.stdout or "[]")
    failures = [r for r in results if not r["ok"]]
    assert results and not failures, json.dumps(failures, indent=1) + completed.stderr[-2000:]
    names = {r["name"] for r in results}
    assert {"stale: status chip shows Stale with the last local bar", "log reports the automatic refresh",
            "after: last bar is the newest CLOSED source bar "
            "(forming bar excluded)", "after: every appended bar present once, strictly increasing, nothing extra",
            "after: indicator recalculated to the new last bar",
            "after: Pine plot recalculated to the new last bar (script not re-added)",
            "after: strategy recalculated (fills include the new bars)", "after: date picker allows the new dates",
            "no page errors"} <= names
    # the frozen research dataset is byte-identical; refreshed bars live only in the test's workspace folder
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == before_hash
    workspace = tmp_path / "workspace"
    assert sorted(p.name for p in workspace.iterdir()) == ["EXNESS_XAUUSDM_M15.csv", "EXNESS_XAUUSDM_M15.metadata.json"]
    stored = pd.read_csv(workspace / "EXNESS_XAUUSDM_M15.csv")
    assert len(stored) == len(closed) and stored["timestamp"].is_unique
