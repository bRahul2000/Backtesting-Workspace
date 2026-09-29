"""Login brute-force protection: temporary, increasing lockouts - never a permanent one.

Per client address: after 5 failures within 15 minutes the address is locked for 30 s, and every further failure
while it keeps failing doubles the lockout (60 s, 120 s, ...) up to 15 minutes. Per username (any address) a looser
limit (20 failures / 15 min) slows distributed guessing the same way. A success clears the address's record; records
also expire 15 minutes after the last failure. State persists in a small JSON file (a restart does not reset it).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time

WINDOW = 15 * 60
IP_LIMIT = 5
USER_LIMIT = 20
BASE_LOCK = 30
MAX_LOCK = 15 * 60


class LoginLimiter:
    def __init__(self, path: Path | None, clock=time.time):
        self.path, self.clock = (Path(path) if path else None), clock
        self._lock = threading.Lock()
        self._state = self._load()

    def _load(self) -> dict:
        if self.path and self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                return {}
        return {}

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_text(json.dumps(self._state), encoding="utf-8")
        os.replace(temporary, self.path)

    def _entry(self, key: str, now: float) -> dict:
        entry = self._state.get(key)
        if entry is None or now - entry["last"] > WINDOW and now >= entry["until"]:
            entry = {"fails": [], "last": now, "until": 0.0, "lock": 0}
        entry["fails"] = [t for t in entry["fails"] if now - t <= WINDOW]
        return entry

    def locked_for(self, ip: str, username: str) -> int:
        """Seconds the attempt must wait (0 = allowed)."""
        now = self.clock()
        with self._lock:
            waits = [self._entry(f"ip:{ip}", now)["until"] - now, self._entry(f"user:{username.lower()}", now)["until"] - now]
        return max(0, int(max(waits) + 0.999))

    def failure(self, ip: str, username: str) -> None:
        now = self.clock()
        with self._lock:
            for key, limit in ((f"ip:{ip}", IP_LIMIT), (f"user:{username.lower()}", USER_LIMIT)):
                entry = self._entry(key, now)
                entry["fails"].append(now)
                entry["last"] = now
                if len(entry["fails"]) >= limit:
                    entry["lock"] = min(MAX_LOCK, BASE_LOCK if not entry["lock"] else entry["lock"] * 2)
                    entry["until"] = now + entry["lock"]
                self._state[key] = entry
            self._save()

    def success(self, ip: str, username: str) -> None:
        with self._lock:
            self._state.pop(f"ip:{ip}", None)
            self._save()
