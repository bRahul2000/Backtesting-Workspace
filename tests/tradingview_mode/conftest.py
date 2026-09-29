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


# Interpreters whose Streamlit serves the real app. The page CSS depends on Streamlit's DOM, which changes between
# releases (the project venv has 1.64; Rahul's app runs /opt/anaconda3's 1.37.1), so layout acceptance runs on every
# one installed here. TV_STREAMLIT_PYTHONS (os.pathsep-separated) adds others.
_CANDIDATES = [sys.executable, "/opt/anaconda3/bin/python",
               *[p for p in os.environ.get("TV_STREAMLIT_PYTHONS", "").split(os.pathsep) if p]]


def streamlit_version(python: str) -> str | None:
    try:
        out = subprocess.run([python, "-c", "import streamlit; print(streamlit.__version__)"], capture_output=True,
                             text=True, timeout=60)
    except OSError:
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def streamlit_pythons() -> list[tuple[str, str]]:
    """[(python, streamlit version)] for each distinct installed Streamlit."""
    found, seen = [], set()
    for python in _CANDIDATES:
        if not Path(python).exists() or python in seen:
            continue
        seen.add(python)
        version = streamlit_version(python)
        if version and version not in {v for _, v in found}:
            found.append((python, version))
    return found


def _serve(tmp_path, python: str):
    mt5_folder = tmp_path / "mt5files"
    mt5_folder.mkdir(parents=True)
    port = _free_port()
    # Workspace chart history (workspace_data.py) is isolated per test too: a real refresh in data/workspace/ never
    # leaks into the browser tests, and the tests never write there.
    env = {**os.environ, "TV_MT5_COMMON_FILES": str(mt5_folder), "TV_WORKSPACE_DATA": str(tmp_path / "workspace")}
    server = subprocess.Popen([python, "-m", "streamlit", "run", str(ROOT / "app.py"), "--server.headless", "true",
                               "--server.port", str(port), "--browser.gatherUsageStats", "false"],
                              cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return server, port, mt5_folder


@pytest.fixture
def app_with(tmp_path):
    """Factory: the real app served by a given interpreter's Streamlit. Yields a function python -> (url, mt5_folder)."""
    servers = []

    def start(python: str):
        server, port, mt5_folder = _serve(tmp_path / f"s{len(servers)}", python)
        servers.append(server)
        for _ in range(120):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        return f"http://127.0.0.1:{port}/render_tradingview_mode", mt5_folder

    yield start
    for server in servers:
        server.terminate()
        try:
            server.wait(10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(10)


@pytest.fixture
def app(tmp_path):
    """The real app (production build in dist/) with MT5 OFF: an empty MT5
    Common/Files folder that nothing writes to. Yields (url, mt5_folder)."""
    server, port, mt5_folder = _serve(tmp_path, sys.executable)
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
