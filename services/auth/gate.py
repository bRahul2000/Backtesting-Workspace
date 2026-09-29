"""Streamlit side of the Zoneflow login: called once at the top of app.py, before any page is built.

Caddy's forward_auth already blocks unauthenticated requests before they reach Streamlit; this gate re-checks on
every rerun (defence in depth) so that a logout or an expired session also ends an already-open tab at its next
interaction. Modes (ZONEFLOW_AUTH_MODE):

  proxy  production: every request needs Caddy's proxy token AND a live session cookie
  auto   (default) requests that came through a proxy are treated as `proxy`; direct local use (a developer's
         machine, no proxy headers) is allowed
  off    local development / tests only: no login (a banner says so)
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass

from .config import AUTH_PREFIX, COOKIE_NAME, PROXY_HEADER, AuthConfig, ConfigError, environment
from .sessions import SessionStore, StoreUnavailable

_PROXY_MARKERS = ("x-zoneflow-proxy", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "forwarded")


@dataclass(frozen=True)
class Decision:
    allowed: bool
    user: str | None = None
    reason: str = ""
    local: bool = False                       # allowed without login (direct local use or auth off)


def _lower(headers) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in dict(headers or {}).items()}


def decide(headers, cookies, env: dict[str, str] | None = None, store: SessionStore | None = None) -> Decision:
    env = environment() if env is None else env
    mode = (env.get("ZONEFLOW_AUTH_MODE") or "auto").strip().lower()
    h = _lower(headers)
    if mode == "off":
        return Decision(True, None, "auth off (development)", local=True)
    proxied = any(marker in h for marker in _PROXY_MARKERS)
    if mode == "auto" and not proxied:
        return Decision(True, None, "direct local access", local=True)
    try:
        config = AuthConfig.from_env(env)
    except ConfigError as exc:
        return Decision(False, None, f"login is not configured ({exc})")
    if not hmac.compare_digest(h.get(PROXY_HEADER.lower(), "").encode(), config.proxy_token.encode()):
        return Decision(False, None, "request did not come through the Zoneflow proxy")
    store = store or SessionStore(config.state_dir / "sessions.json", config.session_secret)
    try:
        user = store.validate(dict(cookies or {}).get(COOKIE_NAME))
    except StoreUnavailable:
        return Decision(False, None, "session store temporarily unavailable - reload the page")
    if not user:
        return Decision(False, None, "no valid session")
    return Decision(True, user, "session")


_STARTED = False


def require_login() -> Decision:
    """Stop the script (only the sign-in notice renders) unless the request is allowed; show the account control."""
    import streamlit as st

    global _STARTED
    if not _STARTED:
        _STARTED = True
        try:
            from .logs import setup
            mode = (environment().get("ZONEFLOW_AUTH_MODE") or "auto").strip().lower()
            setup("app").info("Zoneflow app started (auth mode: %s, execution disabled)", mode)
        except Exception:  # noqa: BLE001
            pass

    context = getattr(st, "context", None)
    decision = decide(getattr(context, "headers", {}) or {}, getattr(context, "cookies", {}) or {})
    if not decision.allowed:
        _log_denial(decision.reason)
        st.markdown(_DENIED_HTML, unsafe_allow_html=True)
        st.stop()
    if decision.user:
        st.markdown(_account_html(decision.user), unsafe_allow_html=True)
    elif (environment().get("ZONEFLOW_AUTH_MODE") or "").strip().lower() == "off":
        st.sidebar.caption("Login disabled (development mode)")
    return decision


def _log_denial(reason: str) -> None:
    try:
        from .logs import setup
        setup("app").warning("access denied: %s", reason)
    except Exception:  # noqa: BLE001 - logging must never break the gate
        pass


_DENIED_HTML = f"""
<style>[data-testid="stSidebar"], [data-testid="stSidebarNav"], header {{ display: none !important; }}</style>
<div style="min-height: 70vh; display: grid; place-items: center;">
  <div style="text-align: center; font-family: Inter, -apple-system, sans-serif;">
    <div style="font-size: 20px; letter-spacing: 3px; font-weight: 700;">ZONEFLOW</div>
    <div style="margin: 6px 0 18px; color: #6f7a8c;">Sign in required</div>
    <a href="{AUTH_PREFIX}/login" target="_top" style="color: #3d8bfd;">Go to the login page</a>
  </div>
</div>"""


def _account_html(user: str) -> str:
    """A fixed-position account control (bottom-left, above Streamlit's menu). It is NOT sidebar content: in Streamlit
    1.37 any sidebar content collapses the page list behind "View more"."""
    from html import escape
    return f"""<div class="zf-account" data-zf-account="1">
<style>
.zf-account {{ position: fixed; left: 10px; bottom: 46px; width: 216px; z-index: 1000100; display: flex; align-items: center;
  justify-content: space-between; gap: 8px; font: 12.5px/1.3 Inter, -apple-system, sans-serif; color: #aab3c2;
  padding: 6px 8px; border-radius: 6px; background: rgba(128,128,128,.08); border: 1px solid rgba(128,128,128,.18); }}
.zf-account a {{ color: #3d8bfd !important; text-decoration: none; font-weight: 600; }}
body:has([data-testid="stSidebar"][aria-expanded="false"]) .zf-account {{ width: 34px; left: 9px; padding: 6px 4px; justify-content: center; }}
body:has([data-testid="stSidebar"][aria-expanded="false"]) .zf-account .zf-user {{ display: none; }}
body:has(iframe[data-tv-layout="chart"]) .zf-account {{ display: none; }}
</style>
<span class="zf-user" title="Signed in">&#128100; {escape(user)}</span>
<a href="{AUTH_PREFIX}/logout" target="_top" title="Log out">Log out</a></div>"""
