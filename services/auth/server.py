"""Zoneflow login service (127.0.0.1 only; Caddy is its only client in production).

    python -m services.auth.server          (settings from the environment / ZONEFLOW_ENV_FILE; see config.py)

Routes (all under /zoneflow-auth):
  GET  /login    the login page (sets a CSRF cookie)
  POST /login    username + password -> HttpOnly session cookie, redirect to `next`; generic error otherwise
  GET  /logout   ends the session (server-side) and clears the cookie
  GET  /verify   Caddy forward_auth: 200 + X-Zoneflow-User for a valid session; else 302 to /login for page
                 navigations, 401 for WebSockets / data requests
  GET  /health   liveness ({"status": "ok"}), no details
"""
from __future__ import annotations

from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import sys
import time
from urllib.parse import parse_qs, quote, urlparse

from .config import AUTH_PREFIX, COOKIE_NAME, CSRF_COOKIE, SESSION_ABSOLUTE_SECONDS, USER_HEADER, AuthConfig, ConfigError
from .logs import setup as setup_logging
from .pages import login_page
from .passwords import verify_login
from .ratelimit import LoginLimiter
from .sessions import SessionStore

GENERIC_ERROR = "Invalid username or password"
MAX_FORM_BYTES = 4096
LOOPBACK = ("127.0.0.1", "::1", "localhost")
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; "
                               "frame-ancestors 'none'",
}


def safe_next(value: str | None) -> str:
    """Only same-site relative paths (no scheme, no //host, no backslashes, not the login routes)."""
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value or "\r" in value \
            or "\n" in value or value.startswith(AUTH_PREFIX):
        return "/"
    return value


class AuthApp:
    """Everything the request handler needs (so tests can build one with a temporary state directory)."""

    def __init__(self, config: AuthConfig, *, clock=time.time):
        self.config = config
        config.state_dir.mkdir(parents=True, exist_ok=True)
        self.sessions = SessionStore(config.state_dir / "sessions.json", config.session_secret, clock=clock)
        self.limiter = LoginLimiter(config.state_dir / "lockouts.json", clock=clock)
        self.log = setup_logging("auth", config.log_dir)

    def cookie(self, name: str, value: str, *, max_age: int, path: str = "/", same_site: str = "Lax") -> str:
        parts = [f"{name}={value}", f"Path={path}", f"Max-Age={max_age}", "HttpOnly", f"SameSite={same_site}"]
        if self.config.cookie_secure:
            parts.append("Secure")
        return "; ".join(parts)


def make_handler(app: AuthApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "zoneflow-auth"
        sys_version = ""

        def log_message(self, format, *args):          # noqa: A002 - no raw request logging (query strings)
            return

        # -- helpers --------------------------------------------------------------------------------------------
        def client_ip(self) -> str:
            direct = self.client_address[0]
            forwarded = self.headers.get("X-Forwarded-For")
            if direct in LOOPBACK and forwarded:              # only the local proxy is trusted to name the client
                return forwarded.split(",")[0].strip()
            return direct

        def cookies(self) -> dict[str, str]:
            jar = SimpleCookie()
            try:
                jar.load(self.headers.get("Cookie", ""))
            except Exception:  # noqa: BLE001 - a malformed cookie header is just "no cookies"
                return {}
            return {k: v.value for k, v in jar.items()}

        def send(self, status: int, body: bytes = b"", *, content_type: str = "text/html; charset=utf-8",
                 headers: dict | None = None, cookies: list[str] = ()) -> None:
            self.send_response(status)
            for key, value in {**SECURITY_HEADERS, **(headers or {})}.items():
                self.send_header(key, value)
            for cookie in cookies:
                self.send_header("Set-Cookie", cookie)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def redirect(self, location: str, cookies: list[str] = ()) -> None:
            self.send(HTTPStatus.SEE_OTHER, headers={"Location": location}, cookies=cookies)

        def login_form(self, *, status: int = 200, next_path: str = "/", error: str | None = None,
                       notice: str | None = None) -> None:
            csrf = secrets.token_urlsafe(24)
            page = login_page(csrf=csrf, next_path=next_path, error=error, notice=notice).encode("utf-8")
            self.send(status, page, cookies=[app.cookie(CSRF_COOKIE, csrf, max_age=3600, path=AUTH_PREFIX,
                                                        same_site="Strict")])

        def same_origin(self) -> bool:
            origin = self.headers.get("Origin")
            if not origin or origin == "null":
                return origin != "null"                      # no Origin (older clients): rely on the CSRF cookie
            expected = {app.config.public_base_url} if app.config.public_base_url else set()
            host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host")
            if host:
                expected |= {f"https://{host}", f"http://{host}"}
            return origin.rstrip("/") in expected

        # -- routes -----------------------------------------------------------------------------------------------
        def do_HEAD(self):  # noqa: N802
            self.do_GET()

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path == f"{AUTH_PREFIX}/health":
                self.send(200, json.dumps({"status": "ok"}).encode(), content_type="application/json")
            elif url.path == f"{AUTH_PREFIX}/login":
                token = self.cookies().get(COOKIE_NAME)
                next_path = safe_next(query.get("next", ["/"])[0])
                if app.sessions.validate(token, touch=False):
                    self.redirect(next_path)
                else:
                    notice = "You have been logged out." if query.get("out") else None
                    self.login_form(next_path=next_path, notice=notice)
            elif url.path == f"{AUTH_PREFIX}/logout":
                self.logout()
            elif url.path == f"{AUTH_PREFIX}/verify":
                self.verify()
            else:
                self.send(404, b"Not found", content_type="text/plain")

        def do_POST(self):  # noqa: N802
            url = urlparse(self.path)
            if url.path == f"{AUTH_PREFIX}/logout":
                self.logout()
                return
            if url.path != f"{AUTH_PREFIX}/login":
                self.send(404, b"Not found", content_type="text/plain")
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_FORM_BYTES:
                self.send(413, b"Too large", content_type="text/plain")
                return
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode("utf-8", "replace")).items()}
            next_path = safe_next(form.get("next"))
            csrf_cookie = self.cookies().get(CSRF_COOKIE, "")
            if not self.same_origin() or not csrf_cookie or not secrets.compare_digest(csrf_cookie, form.get("csrf", "")):
                app.log.warning("login rejected: bad origin or CSRF token ip=%s", self.client_ip())
                self.login_form(status=400, next_path=next_path, error="Your sign-in form expired. Please try again.")
                return
            ip, username, password = self.client_ip(), form.get("username", "")[:200], form.get("password", "")[:1024]
            wait = app.limiter.locked_for(ip, username)
            if wait:
                app.log.warning("login blocked (temporary lockout %ss) ip=%s", wait, ip)
                minutes = max(1, (wait + 59) // 60)
                self.login_form(status=429, next_path=next_path,
                                error=f"Too many attempts. Try again in {minutes} minute{'s' if minutes > 1 else ''}.")
                return
            if verify_login(username, password, app.config.username, app.config.password_hash):
                app.limiter.success(ip, username)
                token = app.sessions.create(app.config.username)
                app.log.info("login success user=%s ip=%s", app.config.username, ip)
                self.redirect(next_path, cookies=[
                    app.cookie(COOKIE_NAME, token, max_age=SESSION_ABSOLUTE_SECONDS),
                    app.cookie(CSRF_COOKIE, "", max_age=0, path=AUTH_PREFIX, same_site="Strict")])
                return
            app.limiter.failure(ip, username)
            known = secrets.compare_digest(username.encode(), app.config.username.encode())
            app.log.warning("login failure ip=%s known_username=%s", ip, "yes" if known else "no")
            self.login_form(status=401, next_path=next_path, error=GENERIC_ERROR)

        def logout(self):
            token = self.cookies().get(COOKIE_NAME)
            user = app.sessions.validate(token, touch=False)
            app.sessions.revoke(token)
            if user:
                app.log.info("logout user=%s ip=%s", user, self.client_ip())
            self.redirect(f"{AUTH_PREFIX}/login?out=1", cookies=[app.cookie(COOKIE_NAME, "", max_age=0)])

        def verify(self):
            user = app.sessions.validate(self.cookies().get(COOKIE_NAME))
            if user:
                self.send(200, b"", content_type="text/plain", headers={USER_HEADER: user})
                return
            uri = self.headers.get("X-Forwarded-Uri", "/")
            accept = self.headers.get("Accept", "")
            page = (self.headers.get("X-Forwarded-Method", "GET") == "GET" and "text/html" in accept
                    and self.headers.get("Upgrade", "").lower() != "websocket" and not uri.startswith("/_stcore"))
            if page:
                self.redirect(f"{AUTH_PREFIX}/login?next={quote(safe_next(uri), safe='/')}")
            else:
                self.send(401, b"Unauthorized", content_type="text/plain")

    return Handler


def serve(config: AuthConfig, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    app = AuthApp(config)
    server = ThreadingHTTPServer((host, config.port), make_handler(app))
    server.daemon_threads = True
    app.log.info("login service listening on %s:%s (secure cookies: %s)", host, config.port, config.cookie_secure)
    return server


def main() -> int:
    try:
        config = AuthConfig.from_env()
    except ConfigError as exc:
        print(f"Zoneflow login service not started: {exc}", file=sys.stderr)
        return 2
    server = serve(config)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
