"""Browser acceptance: the private login through the real production chain - Caddy running deployment/Caddyfile
(forward_auth), the login service (services/auth/server.py) and Streamlit in production auth mode - on every
installed Streamlit. Needs Caddy (ZONEFLOW_TEST_CADDY=/path/to/caddy, or `caddy` on PATH), node and Chrome."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

import pytest

from services.auth.passwords import hash_password

from .conftest import CHROME, ROOT, _free_port, browser_available, streamlit_pythons

SCRIPT = Path(__file__).with_name("browser") / "login_flow.mjs"
CADDY = os.environ.get("ZONEFLOW_TEST_CADDY") or shutil.which("caddy")
SHELLS = streamlit_pythons() if browser_available() else []
USER, PASSWORD = "rahul", "Test-Login-Pass-2026!"

pytestmark = pytest.mark.skipif(not (browser_available() and CADDY), reason="needs node, Chrome and Caddy")


def _wait(url: str, seconds: int = 60) -> None:
    for _ in range(seconds * 2):
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except urllib.error.HTTPError:
            return                                    # it answered
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"{url} did not start")


@pytest.mark.parametrize("python, version", SHELLS, ids=[f"streamlit-{v}" for _, v in SHELLS])
def test_login_through_the_production_proxy(tmp_path, python, version):
    app_port, auth_port, proxy_port = _free_port(), _free_port(), _free_port()
    (tmp_path / "mt5").mkdir()
    env = {**os.environ,
           "ZONEFLOW_ADMIN_USERNAME": USER, "ZONEFLOW_ADMIN_PASSWORD_HASH": hash_password(PASSWORD),
           "ZONEFLOW_SESSION_SECRET": os.urandom(32).hex(), "ZONEFLOW_PROXY_TOKEN": os.urandom(32).hex(),
           "ZONEFLOW_AUTH_STATE_DIR": str(tmp_path / "auth"), "ZONEFLOW_LOG_DIR": str(tmp_path / "logs"),
           "ZONEFLOW_AUTH_MODE": "proxy", "ZONEFLOW_AUTH_PORT": str(auth_port), "ZONEFLOW_APP_PORT": str(app_port),
           "ZONEFLOW_SITE_ADDRESS": f"http://localhost:{proxy_port}", "ZONEFLOW_PUBLIC_BASE_URL": f"http://localhost:{proxy_port}",
           "ZONEFLOW_COOKIE_SECURE": "1",                     # Chrome accepts Secure cookies on http://localhost
           "TV_MT5_COMMON_FILES": str(tmp_path / "mt5"), "TV_WORKSPACE_DATA": str(tmp_path / "workspace"),
           "XDG_DATA_HOME": str(tmp_path / "caddy-data"), "XDG_CONFIG_HOME": str(tmp_path / "caddy-config"),
           "HOME": os.environ.get("HOME", str(tmp_path))}
    procs = []
    try:
        out = {name: open(tmp_path / f"{name}.out", "w") for name in ("auth", "streamlit", "caddy")}
        procs.append(subprocess.Popen([sys.executable, "-m", "services.auth.server"], cwd=ROOT, env=env,
                                      stdout=out["auth"], stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen([python, "-m", "streamlit", "run", str(ROOT / "app.py"), "--server.headless", "true",
                                       "--server.address", "127.0.0.1", "--server.port", str(app_port),
                                       "--browser.gatherUsageStats", "false"],
                                      cwd=ROOT, env=env, stdout=out["streamlit"], stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen([CADDY, "run", "--config", str(ROOT / "deployment" / "Caddyfile"), "--adapter", "caddyfile"],
                                      cwd=tmp_path, env={**env, "ZONEFLOW_CADDY_ADMIN": "off"},
                                      stdout=out["caddy"], stderr=subprocess.STDOUT))
        _wait(f"http://127.0.0.1:{auth_port}/zoneflow-auth/health")
        _wait(f"http://127.0.0.1:{app_port}/_stcore/health")
        _wait(f"http://localhost:{proxy_port}/zoneflow-auth/health")
        completed = subprocess.run(["node", str(SCRIPT), f"http://localhost:{proxy_port}/", f"http://127.0.0.1:{app_port}/",
                                    CHROME, USER, PASSWORD], capture_output=True, text=True, timeout=600)
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
    results = json.loads(completed.stdout or "[]")
    failures = [r for r in results if not r["ok"]]
    tails = "".join(f"\n--- {n} ---\n" + (tmp_path / f"{n}.out").read_text()[-3000:] for n in ("streamlit", "auth", "caddy"))
    assert results and not failures, f"Streamlit {version}: " + json.dumps(failures, indent=1) + completed.stderr[-2000:] + tails
    logs = "".join(p.read_text() for p in (tmp_path / "logs").glob("*.log"))
    assert "login success user=rahul" in logs and "login failure" in logs
    for secret in (PASSWORD, env["ZONEFLOW_ADMIN_PASSWORD_HASH"], env["ZONEFLOW_SESSION_SECRET"], env["ZONEFLOW_PROXY_TOKEN"]):
        assert secret not in logs
