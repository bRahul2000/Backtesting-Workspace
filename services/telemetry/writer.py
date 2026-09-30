"""Python twin of the MQL5 spool writer (ZoneflowTelemetry.mqh): same layout, same line format, same failure rule.

Used by tests and by any future Python-side emitter. A write failure is counted and reported, never raised into the
caller: telemetry must not be able to change what a strategy does.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import secrets

from .schema import SCHEMA_VERSION, encode, format_ts, validate


class SpoolWriter:
    def __init__(self, spool_root: Path, writer_id: str, strategy_id: str, *, capture_mode: str = "realtime",
                 clock=lambda: datetime.now(timezone.utc), **identity):
        self.root, self.writer_id, self.strategy_id = Path(spool_root), writer_id, strategy_id
        self.capture_mode, self.clock, self.identity = capture_mode, clock, identity
        self.run_id = f"r{int(clock().timestamp()):x}{secrets.token_hex(4)}"
        self.sequence = 0
        self.write_failures = 0

    def path_for(self, moment: datetime) -> Path:
        return self.root / self.writer_id / f"{moment.astimezone(timezone.utc):%Y-%m-%d}.jsonl"

    def emit(self, event_type: str, **fields) -> dict | None:
        """Append one event. Returns the event, or None when it could not be written (counted, not raised)."""
        now = self.clock()
        self.sequence += 1
        event = {"schema_version": SCHEMA_VERSION,
                 "telemetry_event_id": f"{self.writer_id}:{self.run_id}:{self.sequence}",
                 "writer_id": self.writer_id, "writer_run_id": self.run_id, "sequence": self.sequence,
                 "event_type": event_type, "capture_mode": self.capture_mode, "strategy_id": self.strategy_id,
                 **self.identity, **fields, "local_capture_utc": format_ts(now, ms=False)}
        try:
            if validate({**event, "crc32": "0" * 8}):
                raise ValueError(validate({**event, "crc32": "0" * 8}))
            line = encode(event)
            path = self.path_for(now)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "ab") as handle:
                if handle.tell() > 0 and not _ends_with_newline(path):
                    handle.write(b"\n")          # seal a torn tail left by a crash, so this line stays intact
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            return event
        except (OSError, ValueError, TypeError):
            self.write_failures += 1
            return None


def _ends_with_newline(path: Path) -> bool:
    with open(path, "rb") as handle:
        handle.seek(-1, os.SEEK_END)
        return handle.read(1) == b"\n"
