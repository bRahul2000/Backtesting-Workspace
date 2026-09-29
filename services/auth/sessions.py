"""Server-side sessions for the single admin.

The browser only holds an opaque random token (HttpOnly cookie). The store keeps HMAC-SHA256(session secret, token)
- never the token itself - with the user, creation time and last activity, in a JSON file shared by the login
service and the Streamlit gate. Sessions end after 12 h, after 2 h without activity, or on logout (the entry is
deleted). Rotating ZONEFLOW_SESSION_SECRET invalidates every session.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time

from .config import SESSION_ABSOLUTE_SECONDS, SESSION_IDLE_SECONDS

TOUCH_EVERY_SECONDS = 60          # last-activity writes are throttled
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    """One lock per store file for every SessionStore in this process (Streamlit runs reruns on many threads)."""
    key = str(Path(path).resolve())
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


class StoreUnavailable(RuntimeError):
    """The session store could not be read (transient); never treated as "logged out" silently."""


class SessionStore:
    def __init__(self, path: Path, secret: bytes, *, absolute: int = SESSION_ABSOLUTE_SECONDS,
                 idle: int = SESSION_IDLE_SECONDS, clock=time.time):
        self.path, self.secret, self.absolute, self.idle, self.clock = Path(path), secret, absolute, idle, clock
        self._lock = _lock_for(self.path)

    def _key(self, token: str) -> str:
        return hmac.new(self.secret, token.encode("utf-8"), hashlib.sha256).hexdigest()

    def _read(self) -> dict:
        """The store (empty if it does not exist yet). Writers replace the file atomically; a read that still fails
        (another process mid-replace on some file systems) is retried, then reported instead of returning {}."""
        for attempt in range(5):
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                return {}
            except (OSError, ValueError):
                time.sleep(0.02 * (attempt + 1))
        raise StoreUnavailable(f"session store {self.path} unreadable")

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # a unique temporary name per write: the login service and every Streamlit thread may write concurrently
        temporary = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(4)}.tmp")
        temporary.write_text(json.dumps(data), encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(temporary, self.path)
                return
            except PermissionError:                  # Windows: the target is briefly open in another process
                time.sleep(0.02 * (attempt + 1))
        temporary.unlink(missing_ok=True)

    def _alive(self, entry: dict, now: float) -> bool:
        return now < entry["created"] + self.absolute and now < entry["last_seen"] + self.idle

    def create(self, user: str) -> str:
        token = secrets.token_urlsafe(32)
        now = self.clock()
        with self._lock:
            data = {k: v for k, v in self._read().items() if self._alive(v, now)}
            data[self._key(token)] = {"user": user, "created": now, "last_seen": now}
            self._write(data)
        return token

    def validate(self, token: str | None, *, touch: bool = True) -> str | None:
        """The session's user, or None if unknown, expired (absolute or idle) or logged out."""
        if not token or len(token) > 200:
            return None
        key, now = self._key(token), self.clock()
        with self._lock:
            data = self._read()
            entry = data.get(key)
            if entry is None:
                return None
            if not self._alive(entry, now):
                data.pop(key, None)
                self._write(data)
                return None
            if touch and now - entry["last_seen"] >= TOUCH_EVERY_SECONDS:
                entry["last_seen"] = now
                self._write(data)
            return entry["user"]

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            data = self._read()
            if data.pop(self._key(token), None) is not None:
                self._write(data)

    def remaining(self, token: str) -> int | None:
        """Seconds until the session ends (absolute or idle, whichever first)."""
        entry = self._read().get(self._key(token))
        if entry is None:
            return None
        now = self.clock()
        return int(max(0, min(entry["created"] + self.absolute, entry["last_seen"] + self.idle) - now))
