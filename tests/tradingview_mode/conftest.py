"""Shared fixtures for the TradingView Mode browser tests."""
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
CHROME = os.environ.get("CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def binance_reachable() -> bool:
    try:
        urllib.request.urlopen("https://fapi.binance.com/fapi/v1/time", timeout=5)
        return True
    except OSError:
        return False


def browser_available() -> bool:
    return bool(shutil.which("node")) and Path(CHROME).exists()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def app(tmp_path):
    """The real app (production build in dist/) with MT5 OFF: an empty MT5
    Common/Files folder that nothing writes to. Yields (url, mt5_folder)."""
    mt5_folder = tmp_path / "mt5files"
    mt5_folder.mkdir()
    port = _free_port()
    # Workspace chart history (workspace_data.py) is isolated per test too: a real refresh in data/workspace/ never
    # leaks into the browser tests, and the tests never write there.
    env = {**os.environ, "TV_MT5_COMMON_FILES": str(mt5_folder), "TV_WORKSPACE_DATA": str(tmp_path / "workspace")}
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
        yield f"http://127.0.0.1:{port}/render_tradingview_mode", mt5_folder
    finally:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:           # a busy rerun can delay shutdown: never leave a stray server
            server.kill()
            server.wait(10)
