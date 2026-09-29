"""Zoneflow auth configuration from the server environment (never from Git, never from the browser).

Variables (deployment/.env.example lists them; the real file lives outside the repository, e.g.
C:\\ZoneflowData\\zoneflow.env, and is read when ZONEFLOW_ENV_FILE points at it):

  ZONEFLOW_ADMIN_USERNAME        the single admin user
  ZONEFLOW_ADMIN_PASSWORD_HASH   Argon2id hash (tools/create_zoneflow_admin.py); never the password
  ZONEFLOW_SESSION_SECRET        >= 32 random bytes, hex; signs session ids at rest (rotating it logs everyone out)
  ZONEFLOW_PROXY_TOKEN           random token Caddy adds to every request it forwards to Streamlit
  ZONEFLOW_PUBLIC_BASE_URL       https://your.domain (used for Origin checks)
  ZONEFLOW_AUTH_STATE_DIR        where the session store and lockout state live
  ZONEFLOW_LOG_DIR               rotating logs
  ZONEFLOW_COOKIE_SECURE         1 (default) = Secure cookies (HTTPS only)
  ZONEFLOW_AUTH_PORT             login service port on 127.0.0.1 (default 8601)
  ZONEFLOW_AUTH_MODE             Streamlit gate: proxy (production: always require login) | auto (default) | off
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

SESSION_ABSOLUTE_SECONDS = 12 * 3600
SESSION_IDLE_SECONDS = 2 * 3600
COOKIE_NAME = "zf_session"
CSRF_COOKIE = "zf_csrf"
USER_HEADER = "X-Zoneflow-User"
PROXY_HEADER = "X-Zoneflow-Proxy"
AUTH_PREFIX = "/zoneflow-auth"


class ConfigError(RuntimeError):
    """The auth configuration is missing or unsafe (the service refuses to start)."""


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines; '#' comments; no variable expansion (Argon2 hashes contain '$')."""
    values = {}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def environment() -> dict[str, str]:
    """os.environ, with the private env file (ZONEFLOW_ENV_FILE) filling variables not already set."""
    env = dict(os.environ)
    file = env.get("ZONEFLOW_ENV_FILE")
    if file and Path(file).exists():
        for key, value in read_env_file(Path(file)).items():
            env.setdefault(key, value)
    return env


@dataclass(frozen=True)
class AuthConfig:
    username: str
    password_hash: str
    session_secret: bytes
    proxy_token: str
    public_base_url: str
    state_dir: Path
    log_dir: Path | None
    cookie_secure: bool
    port: int

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "AuthConfig":
        env = environment() if env is None else env
        username = env.get("ZONEFLOW_ADMIN_USERNAME", "").strip()
        password_hash = env.get("ZONEFLOW_ADMIN_PASSWORD_HASH", "").strip()
        secret_hex = env.get("ZONEFLOW_SESSION_SECRET", "").strip()
        if not username or not password_hash.startswith("$argon2id$"):
            raise ConfigError("ZONEFLOW_ADMIN_USERNAME / ZONEFLOW_ADMIN_PASSWORD_HASH are not set (run "
                              "tools/create_zoneflow_admin.py).")
        try:
            secret = bytes.fromhex(secret_hex)
        except ValueError:
            raise ConfigError("ZONEFLOW_SESSION_SECRET must be hex.") from None
        if len(secret) < 32:
            raise ConfigError("ZONEFLOW_SESSION_SECRET must be at least 32 random bytes (64 hex characters).")
        proxy_token = env.get("ZONEFLOW_PROXY_TOKEN", "").strip()
        if len(proxy_token) < 32:
            raise ConfigError("ZONEFLOW_PROXY_TOKEN must be set (at least 32 characters).")
        state = Path(env.get("ZONEFLOW_AUTH_STATE_DIR") or (Path.home() / ".zoneflow" / "auth"))
        log_dir = env.get("ZONEFLOW_LOG_DIR")
        return cls(username=username, password_hash=password_hash, session_secret=secret, proxy_token=proxy_token,
                   public_base_url=env.get("ZONEFLOW_PUBLIC_BASE_URL", "").rstrip("/"), state_dir=state,
                   log_dir=Path(log_dir) if log_dir else None,
                   cookie_secure=env.get("ZONEFLOW_COOKIE_SECURE", "1").strip() not in ("0", "false", "no"),
                   port=int(env.get("ZONEFLOW_AUTH_PORT", "8601")))
