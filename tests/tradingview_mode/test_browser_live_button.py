"""Browser regression: the Live (and Replay) mode buttons work in the production build.

Starts the real app (built frontend in dist/) against a synthetic MT5 feed
folder and drives headless Chrome with real mouse clicks. Skipped when Chrome or
Node is not available.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(__file__).with_name("browser") / "live_button.mjs"
CHROME = os.environ.get("CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

pytestmark = pytest.mark.skipif(not (shutil.which("node") and Path(CHROME).exists()),
                                reason="needs node and Google Chrome")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def app(tmp_path):
    feed_dir = tmp_path / "mt5files"
    feed = subprocess.Popen([sys.executable, str(Path(__file__).with_name("synthetic_mt5_feed.py")), str(feed_dir),
                             "--seconds", "600"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port = _free_port()
    env = {**os.environ, "TV_MT5_COMMON_FILES": str(feed_dir)}
    server = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"), "--server.headless", "true",
                               "--server.port", str(port), "--browser.gatherUsageStats", "false"],
                              cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        yield f"http://127.0.0.1:{port}/render_tradingview_mode"
    finally:
        server.terminate()
        feed.terminate()
        server.wait(10)
        feed.wait(10)


def test_live_and_replay_buttons_work_with_real_clicks(app):
    completed = subprocess.run(["node", str(SCRIPT), app, CHROME], capture_output=True, text=True, timeout=300)
    results = json.loads(completed.stdout or "[]")
    failures = [r for r in results if not r["ok"]]
    assert results and not failures, json.dumps(failures, indent=1) + completed.stderr[-2000:]
    names = {r["name"] for r in results}
    assert {"A: Live button becomes active", "A: Live controls visible", "B: unsupported-market message visible",
            "D: Replay start popover visible"} <= names
