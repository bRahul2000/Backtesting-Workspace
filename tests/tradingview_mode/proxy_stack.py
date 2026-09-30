"""The production chain for browser acceptance: Caddy (deployment/Caddyfile, forward_auth) + the login service +
Streamlit in proxy auth mode, all on free local ports. Used by the Private Beta acceptance and measurement runs."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from services.auth.passwords import hash_password

from .conftest import ROOT, _free_port

CADDY = os.environ.get("ZONEFLOW_TEST_CADDY") or shutil.which("caddy")
USER, PASSWORD = "rahul", "Test-Beta-Pass-2026!"


def _wait(url: str, seconds: int = 90) -> None:
    for _ in range(seconds * 2):
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except urllib.error.HTTPError:
            return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"{url} did not start")


@contextmanager
def proxy_stack(tmp_path: Path, python: str, extra_env: dict | None = None):
    """Yields (proxy_url, env). Server output goes to tmp_path/<name>.out."""
    app_port, auth_port, proxy_port = _free_port(), _free_port(), _free_port()
    (tmp_path / "mt5").mkdir(parents=True, exist_ok=True)
    env = {**os.environ,
           "ZONEFLOW_ADMIN_USERNAME": USER, "ZONEFLOW_ADMIN_PASSWORD_HASH": hash_password(PASSWORD),
           "ZONEFLOW_SESSION_SECRET": os.urandom(32).hex(), "ZONEFLOW_PROXY_TOKEN": os.urandom(32).hex(),
           "ZONEFLOW_AUTH_STATE_DIR": str(tmp_path / "auth"), "ZONEFLOW_LOG_DIR": str(tmp_path / "logs"),
           "ZONEFLOW_AUTH_MODE": "proxy", "ZONEFLOW_AUTH_PORT": str(auth_port), "ZONEFLOW_APP_PORT": str(app_port),
           "ZONEFLOW_SITE_ADDRESS": f"http://localhost:{proxy_port}",
           "ZONEFLOW_PUBLIC_BASE_URL": f"http://localhost:{proxy_port}", "ZONEFLOW_COOKIE_SECURE": "1",
           "TV_MT5_COMMON_FILES": str(tmp_path / "mt5"), "TV_WORKSPACE_DATA": str(tmp_path / "workspace"),
           "XDG_DATA_HOME": str(tmp_path / "caddy-data"), "XDG_CONFIG_HOME": str(tmp_path / "caddy-config"),
           "HOME": os.environ.get("HOME", str(tmp_path)), **(extra_env or {})}
    procs = []
    outs = {name: open(tmp_path / f"{name}.out", "w") for name in ("auth", "streamlit", "caddy")}
    try:
        procs.append(subprocess.Popen([sys.executable, "-m", "services.auth.server"], cwd=ROOT, env=env,
                                      stdout=outs["auth"], stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen([python, "-m", "streamlit", "run", str(ROOT / "app.py"), "--server.headless",
                                       "true", "--server.address", "127.0.0.1", "--server.port", str(app_port),
                                       "--browser.gatherUsageStats", "false"],
                                      cwd=ROOT, env=env, stdout=outs["streamlit"], stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen([CADDY, "run", "--config", str(ROOT / "deployment" / "Caddyfile"), "--adapter",
                                       "caddyfile"], cwd=tmp_path, env={**env, "ZONEFLOW_CADDY_ADMIN": "off"},
                                      stdout=outs["caddy"], stderr=subprocess.STDOUT))
        _wait(f"http://127.0.0.1:{auth_port}/zoneflow-auth/health")
        _wait(f"http://127.0.0.1:{app_port}/_stcore/health")
        _wait(f"http://localhost:{proxy_port}/zoneflow-auth/health")
        yield f"http://localhost:{proxy_port}/", env
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
        for handle in outs.values():
            handle.close()
