"""Zoneflow private login: Argon2id credentials, server-side sessions, brute-force protection, the login service over
real HTTP, the Streamlit gate, and that no secret reaches a page, a cookie value, a log or Git."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import re
import subprocess
import threading
from urllib.parse import urlencode

import pytest

from services.auth import gate as G
from services.auth.config import AuthConfig, ConfigError, read_env_file
from services.auth.passwords import hash_password, strength_problems, verify_login
from services.auth.ratelimit import BASE_LOCK, IP_LIMIT, MAX_LOCK, LoginLimiter
from services.auth.server import AuthApp, GENERIC_ERROR, make_handler, safe_next
from services.auth.sessions import SessionStore

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "Correct-Horse-9-battery"
USER = "rahul"


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture(scope="module")
def password_hash():
    return hash_password(PASSWORD)


def env_for(tmp_path, password_hash, **extra):
    return {"ZONEFLOW_ADMIN_USERNAME": USER, "ZONEFLOW_ADMIN_PASSWORD_HASH": password_hash,
            "ZONEFLOW_SESSION_SECRET": "ab" * 32, "ZONEFLOW_PROXY_TOKEN": "p" * 40,
            "ZONEFLOW_AUTH_STATE_DIR": str(tmp_path / "state"), "ZONEFLOW_LOG_DIR": str(tmp_path / "logs"),
            "ZONEFLOW_COOKIE_SECURE": "1", "ZONEFLOW_AUTH_PORT": "0", **extra}


# ---- credentials -----------------------------------------------------------------------------------------------------

def test_argon2id_hash_and_constant_time_verification(password_hash):
    assert password_hash.startswith("$argon2id$") and PASSWORD not in password_hash
    assert verify_login(USER, PASSWORD, USER, password_hash)
    assert not verify_login(USER, "wrong-Password-1", USER, password_hash)
    assert not verify_login("someone", PASSWORD, USER, password_hash)          # right password, wrong user
    assert not verify_login(USER, PASSWORD, USER, "not-a-hash")


def test_password_strength_rules():
    assert strength_problems("short1A!")
    assert strength_problems("alllowercaseletters")
    assert strength_problems("Rahul-Password-2026", "rahul")
    assert strength_problems(PASSWORD, USER) == []


def test_admin_tool_writes_only_a_hash_and_fresh_secrets(tmp_path):
    from tools import create_zoneflow_admin as tool

    path = tmp_path / "zoneflow.env"
    path.write_text("ZONEFLOW_DOMAIN=zoneflow.example.com\nZONEFLOW_ADMIN_USERNAME=old\n")
    values = tool.credential_values(USER, PASSWORD)
    tool.write_env(path, values)
    text = path.read_text()
    assert PASSWORD not in text and "ZONEFLOW_DOMAIN=zoneflow.example.com" in text and "=old" not in text
    env = read_env_file(path)
    assert env["ZONEFLOW_ADMIN_PASSWORD_HASH"].startswith("$argon2id$") and len(bytes.fromhex(env["ZONEFLOW_SESSION_SECRET"])) == 32
    assert verify_login(USER, PASSWORD, env["ZONEFLOW_ADMIN_USERNAME"], env["ZONEFLOW_ADMIN_PASSWORD_HASH"])
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    again = tool.credential_values(USER, PASSWORD)
    assert again["ZONEFLOW_SESSION_SECRET"] != values["ZONEFLOW_SESSION_SECRET"]
    with pytest.raises(ValueError, match="too weak"):
        tool.credential_values(USER, "weak")


def test_admin_tool_refuses_to_write_secrets_inside_the_repository(monkeypatch):
    from tools import create_zoneflow_admin as tool
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("must not prompt"))
    assert tool.main(["--env-file", str(ROOT / "zoneflow.env")]) == 2


def test_config_fails_closed(tmp_path, password_hash):
    good = env_for(tmp_path, password_hash)
    assert AuthConfig.from_env(good).username == USER
    for broken in ({"ZONEFLOW_ADMIN_PASSWORD_HASH": ""}, {"ZONEFLOW_SESSION_SECRET": "ab" * 8},
                   {"ZONEFLOW_PROXY_TOKEN": "short"}, {"ZONEFLOW_ADMIN_PASSWORD_HASH": "plaintext-password"}):
        with pytest.raises(ConfigError):
            AuthConfig.from_env({**good, **broken})


# ---- sessions ---------------------------------------------------------------------------------------------------------

def test_sessions_expire_idle_absolute_and_on_logout(tmp_path):
    clock = Clock()
    store = SessionStore(tmp_path / "s.json", b"k" * 32, clock=clock)
    token = store.create(USER)
    assert store.validate(token) == USER
    raw = (tmp_path / "s.json").read_text()
    assert token not in raw                                          # only HMAC(secret, token) is stored
    clock.t += 3600                                                   # active within the idle window
    assert store.validate(token) == USER
    clock.t += 2 * 3600 + 1                                           # idle for more than 2 h
    assert store.validate(token) is None
    t2 = store.create(USER)
    for _ in range(13):                                               # busy, but 12 h is the absolute limit
        clock.t += 3600 - 1
        store.validate(t2)
    assert store.validate(t2) is None
    t3 = store.create(USER)
    store.revoke(t3)
    assert store.validate(t3) is None
    t4 = store.create(USER)
    assert SessionStore(tmp_path / "s.json", b"other" * 8, clock=clock).validate(t4) is None   # secret rotation
    assert store.validate("x" * 500) is None and store.validate(None) is None


# ---- brute force -------------------------------------------------------------------------------------------------------

def test_lockout_is_temporary_and_escalates_but_never_permanent(tmp_path):
    clock = Clock()
    limiter = LoginLimiter(tmp_path / "l.json", clock=clock)
    for _ in range(IP_LIMIT - 1):
        limiter.failure("1.2.3.4", USER)
    assert limiter.locked_for("1.2.3.4", USER) == 0
    limiter.failure("1.2.3.4", USER)
    assert limiter.locked_for("1.2.3.4", USER) == BASE_LOCK
    assert limiter.locked_for("5.6.7.8", "other") == 0                          # other clients unaffected
    clock.t += BASE_LOCK
    limiter.failure("1.2.3.4", USER)
    assert limiter.locked_for("1.2.3.4", USER) == 2 * BASE_LOCK                  # keeps failing: doubles
    for _ in range(20):
        clock.t += MAX_LOCK
        limiter.failure("1.2.3.4", USER)
    assert limiter.locked_for("1.2.3.4", USER) <= MAX_LOCK                      # capped
    clock.t += MAX_LOCK + 16 * 60
    assert limiter.locked_for("1.2.3.4", USER) == 0                             # never permanent
    assert LoginLimiter(tmp_path / "l.json", clock=clock).locked_for("1.2.3.4", USER) == 0
    limiter.failure("9.9.9.9", USER)
    limiter.success("9.9.9.9", USER)
    assert "ip:9.9.9.9" not in json.loads((tmp_path / "l.json").read_text())


def test_safe_next_blocks_open_redirects():
    assert safe_next("/render_tradingview_mode?x=1") == "/render_tradingview_mode?x=1"
    for bad in ("https://evil.example", "//evil.example", "/\\evil", "evil", "/zoneflow-auth/logout", None, "/a\r\nSet-Cookie: x"):
        assert safe_next(bad) == "/"


# ---- the login service over HTTP ------------------------------------------------------------------------------------------

@pytest.fixture
def service(tmp_path, password_hash):
    from http.server import ThreadingHTTPServer

    config = AuthConfig.from_env(env_for(tmp_path, password_hash))
    app = AuthApp(config)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], app, tmp_path
    server.shutdown()


def request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    data = response.read().decode("utf-8", "replace")
    return response.status, response.getheaders(), data


def set_cookies(headers):
    return [v for k, v in headers if k.lower() == "set-cookie"]


def cookie_value(headers, name):
    for value in set_cookies(headers):
        if value.startswith(name + "="):
            return value.split(";", 1)[0].split("=", 1)[1]
    return None


def login(port, username, password, *, next_path="/", origin=None, ip=None):
    status, headers, page = request(port, "GET", "/zoneflow-auth/login")
    csrf = cookie_value(headers, "zf_csrf")
    form = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    hdrs = {"Content-Type": "application/x-www-form-urlencoded", "Cookie": f"zf_csrf={csrf}", "Host": "zoneflow.test"}
    if origin:
        hdrs["Origin"] = origin
    if ip:
        hdrs["X-Forwarded-For"] = ip
    body = urlencode({"csrf": form, "next": next_path, "username": username, "password": password})
    return request(port, "POST", "/zoneflow-auth/login", body, hdrs)


def test_login_page_is_the_only_thing_without_a_session(service):
    port, *_ = service
    status, headers, page = request(port, "GET", "/zoneflow-auth/login")
    assert status == 200 and "ZONEFLOW" in page and "Private Trading Research Terminal" in page
    assert 'type="password"' in page and "<script" not in page
    assert dict(headers)["X-Frame-Options"] == "DENY" and "no-store" in dict(headers)["Cache-Control"]
    csrf = [c for c in set_cookies(headers) if c.startswith("zf_csrf=")][0]
    assert "HttpOnly" in csrf and "SameSite=Strict" in csrf and "Secure" in csrf
    assert request(port, "GET", "/zoneflow-auth/verify", headers={"Accept": "text/html", "X-Forwarded-Uri": "/x"})[0] == 303
    assert request(port, "GET", "/zoneflow-auth/verify", headers={"Upgrade": "websocket", "X-Forwarded-Uri": "/_stcore/stream"})[0] == 401
    assert request(port, "GET", "/zoneflow-auth/health")[2] == '{"status": "ok"}'


def test_valid_login_session_verify_and_logout(service):
    port, app, _ = service
    status, headers, _ = login(port, USER, PASSWORD, next_path="/render_tradingview_mode", origin="https://zoneflow.test")
    assert status == 303 and dict(headers)["Location"] == "/render_tradingview_mode"
    cookie = [c for c in set_cookies(headers) if c.startswith("zf_session=")][0]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Lax" in cookie and "Max-Age=43200" in cookie
    token = cookie_value(headers, "zf_session")
    status, headers, _ = request(port, "GET", "/zoneflow-auth/verify", headers={"Cookie": f"zf_session={token}"})
    assert status == 200 and dict(headers)["X-Zoneflow-User"] == USER
    # a page reload keeps the session (the login page just forwards)
    assert request(port, "GET", "/zoneflow-auth/login?next=/", headers={"Cookie": f"zf_session={token}"})[0] == 303
    status, headers, _ = request(port, "GET", "/zoneflow-auth/logout", headers={"Cookie": f"zf_session={token}"})
    assert status == 303 and "out=1" in dict(headers)["Location"]
    assert any(c.startswith("zf_session=;") and "Max-Age=0" in c for c in set_cookies(headers))
    assert request(port, "GET", "/zoneflow-auth/verify", headers={"Cookie": f"zf_session={token}"})[0] == 401


def test_wrong_credentials_get_one_generic_message(service):
    port, *_ = service
    wrong_password = login(port, USER, "Wrong-Password-99")
    unknown_user = login(port, "not-rahul", PASSWORD)
    for status, headers, page in (wrong_password, unknown_user):
        assert status == 401 and GENERIC_ERROR in page and cookie_value(headers, "zf_session") is None
    strip = lambda p: re.sub(r'value="[^"]*"', "", p)                     # noqa: E731 (CSRF values differ)
    assert strip(wrong_password[2]) == strip(unknown_user[2])              # nothing reveals whether the user exists


def test_csrf_and_cross_origin_posts_are_rejected(service):
    port, *_ = service
    body = urlencode({"csrf": "forged", "username": USER, "password": PASSWORD})
    status, headers, _ = request(port, "POST", "/zoneflow-auth/login", body,
                                 {"Content-Type": "application/x-www-form-urlencoded", "Cookie": "zf_csrf=other"})
    assert status == 400 and cookie_value(headers, "zf_session") is None
    status, headers, _ = login(port, USER, PASSWORD, origin="https://evil.example")
    assert status == 400 and cookie_value(headers, "zf_session") is None


def test_brute_force_lockout_over_http(service):
    port, *_ = service
    for _ in range(IP_LIMIT):
        assert login(port, USER, "Wrong-Password-99", ip="203.0.113.7")[0] == 401
    status, headers, page = login(port, USER, PASSWORD, ip="203.0.113.7")        # even the right password waits
    assert status == 429 and "Too many attempts" in page and cookie_value(headers, "zf_session") is None
    assert login(port, USER, PASSWORD, ip="198.51.100.2")[0] == 303              # another address is not locked


def test_logs_never_contain_the_password_hash_secret_or_tokens(service, password_hash):
    port, app, tmp_path = service
    login(port, USER, "Wrong-Password-99")
    status, headers, _ = login(port, USER, PASSWORD)
    token = cookie_value(headers, "zf_session")
    request(port, "GET", "/zoneflow-auth/logout", headers={"Cookie": f"zf_session={token}"})
    log = "".join(p.read_text() for p in (tmp_path / "logs").glob("*.log"))
    assert "login success user=rahul" in log and "login failure" in log and "logout user=rahul" in log
    for secret in (PASSWORD, "Wrong-Password-99", password_hash, "ab" * 32, "p" * 40, token):
        assert secret not in log


# ---- the Streamlit gate -----------------------------------------------------------------------------------------------------

def test_gate_decisions(tmp_path, password_hash):
    env = env_for(tmp_path, password_hash)
    config = AuthConfig.from_env(env)
    store = SessionStore(config.state_dir / "sessions.json", config.session_secret)
    token = store.create(USER)
    proxied = {"X-Forwarded-For": "203.0.113.7", "X-Zoneflow-Proxy": "p" * 40}
    # direct local use (no proxy headers): allowed in auto mode, refused in production mode
    assert G.decide({}, {}, env).allowed and G.decide({}, {}, env).local
    assert not G.decide({}, {}, {**env, "ZONEFLOW_AUTH_MODE": "proxy"}).allowed
    # through the proxy: token AND live session required
    assert G.decide(proxied, {"zf_session": token}, env, store) == G.Decision(True, USER, "session")
    assert not G.decide(proxied, {}, env, store).allowed
    assert not G.decide({**proxied, "X-Zoneflow-Proxy": "forged"}, {"zf_session": token}, env, store).allowed
    assert not G.decide({"X-Forwarded-For": "1.2.3.4"}, {"zf_session": token}, env, store).allowed
    store.revoke(token)
    assert not G.decide(proxied, {"zf_session": token}, env, store).allowed      # logout ends the open tab too
    # proxied traffic with no login configured fails closed
    assert not G.decide(proxied, {}, {"ZONEFLOW_AUTH_MODE": "auto"}).allowed
    assert G.decide(proxied, {}, {"ZONEFLOW_AUTH_MODE": "off"}).allowed


# ---- secrets never in Git or the frontend ------------------------------------------------------------------------------------

SECRET_PATTERNS = [re.compile(p) for p in (
    r"\$argon2id?\$v=\d+\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/]{10,}\$[A-Za-z0-9+/]{10,}",   # a real Argon2 hash
    r"ZONEFLOW_(SESSION_SECRET|ADMIN_PASSWORD_HASH|PROXY_TOKEN)[ \t]*=[ \t]*\S{8,}",          # a filled secret variable
    r"AKIA[0-9A-Z]{16}", r"aws_secret_access_key\s*=\s*\S+", r"gh[pousr]_[A-Za-z0-9]{36,}", r"github_pat_[A-Za-z0-9_]{40,}",
    r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")]


def test_no_secrets_in_tracked_files_or_the_frontend_bundle():
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    assert not [f for f in tracked if Path(f).name in (".env", "zoneflow.env") or f.endswith((".pem", ".key"))]
    hits = []
    for name in tracked:
        path = ROOT / name
        if path.suffix in (".png", ".jpg", ".sqlite3", ".parquet", ".gz", ".zip", ".ex5") or not path.is_file() \
                or path.stat().st_size > 5_000_000 or name.startswith("tests/test_zoneflow_auth.py"):
            continue
        text = path.read_text(errors="ignore")
        hits += [f"{name}: {p.pattern[:30]}" for p in SECRET_PATTERNS if p.search(text)]
    assert hits == []


def test_gitignore_keeps_real_env_files_out():
    for name in ("deployment/.env", "zoneflow.env", "x/.env.production", "C/zoneflow.env"):
        assert subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT).returncode == 0, name
    assert subprocess.run(["git", "check-ignore", "-q", "deployment/.env.example"], cwd=ROOT).returncode == 1


def test_session_store_survives_concurrent_writers(tmp_path):
    """The login service and many Streamlit threads read and write one store at once: no lost session, no errors."""
    from concurrent.futures import ThreadPoolExecutor

    clock = Clock()
    path = tmp_path / "sessions.json"
    token = SessionStore(path, b"k" * 32, clock=clock).create(USER)
    errors, results = [], []

    def worker(i):
        store = SessionStore(path, b"k" * 32, clock=lambda: clock.t + (i % 7) * 61)      # every call wants to write
        try:
            for _ in range(20):
                results.append(store.validate(token))
                if i % 5 == 0:
                    store.create("other")                                               # the login service
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    with ThreadPoolExecutor(16) as pool:
        list(pool.map(worker, range(32)))
    assert errors == [] and set(results) == {USER}
    assert not list(tmp_path.glob("*.tmp"))                                               # no stray temporary files


# ---- deployment files ----------------------------------------------------------------------------------------------------

def test_deployment_keeps_internal_ports_private_and_login_mandatory():
    windows = ROOT / "deployment" / "windows"
    run_app = (windows / "run-app.ps1").read_text()
    assert "'--server.address', '127.0.0.1'" in run_app and "ZONEFLOW_AUTH_MODE = 'proxy'" in run_app
    caddy = (ROOT / "deployment" / "Caddyfile").read_text()
    assert "request_header -X-Zoneflow-User" in caddy and "request_header -X-Zoneflow-Proxy" in caddy
    assert caddy.index("forward_auth") < caddy.index("reverse_proxy 127.0.0.1:{$ZONEFLOW_APP_PORT")
    install = (windows / "Install-Zoneflow.ps1").read_text()
    assert "-LocalPort 80, 443 -Action Allow" in install and "-LocalPort 8501, 8601, 2019 -Action Block" in install
    assert "3389" not in install.replace("RDP (3389) is NOT touched", "")        # RDP rules are never changed
    assert re.search(r"CaddySha512 = '[0-9a-f]{128}'", install)                 # the download is checksum-verified
    for script in windows.glob("*.ps1"):                                        # no secret is ever echoed
        text = script.read_text()
        assert not re.search(r"Write-(Host|Output).*(PASSWORD|SECRET|PROXY_TOKEN)", text), script.name


def test_health_check_reports_services_and_refuses_unauthenticated_access(service, monkeypatch):
    import importlib.util

    port, _app, _tmp = service
    spec = importlib.util.spec_from_file_location("zoneflow_health", ROOT / "tools" / "zoneflow_health.py")
    health = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(health)
    local = health.check_local({"ZONEFLOW_AUTH_PORT": str(port), "ZONEFLOW_APP_PORT": "1"})
    assert local["auth_service"]["ok"] and not local["streamlit"]["ok"]
    # the public check treats a page served without a session as a failure
    monkeypatch.setattr(health, "_get", lambda url, timeout=5: (200, "") if url.endswith("/login") else (200, "<html>"))
    assert not health.check_public("zoneflow.test")["app_requires_login"]["ok"]
    monkeypatch.setattr(health, "_get", lambda url, timeout=5: (200, "") if url.endswith("/login") else (303, ""))
    assert all(item["ok"] for item in health.check_public("zoneflow.test").values())
