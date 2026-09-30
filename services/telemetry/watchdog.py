"""Watchdog V1 - an independent observer. It reads the newest lines of each spool directly (not the Zoneflow store),
and reports the last heartbeat, MT5 connection state and staleness per writer.

It only reports. It never flattens, closes, disables trading or modifies orders; any automatic action needs a
separately approved policy.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from .schema import LineDefect, decode, format_ts, parse_ts

STALE_AFTER_S = 180
TAIL_BYTES = 64 * 1024


def _tail_events(path: Path) -> list[dict]:
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - TAIL_BYTES))
        data = handle.read()
    lines = data.split(b"\n")
    if size > TAIL_BYTES:
        lines = lines[1:]                    # first line may be cut by the seek
    out = []
    for raw in lines[:-1]:                   # the last piece has no newline yet: maybe mid-write
        try:
            out.append(decode(raw))
        except LineDefect:
            continue
    return out


def check(spool_root: Path, now: datetime | None = None, stale_after_s: int = STALE_AFTER_S) -> dict:
    now = now or datetime.now(timezone.utc)
    report = {"checked_utc": format_ts(now, ms=False), "writers": [], "ok": True, "problems": []}
    if not spool_root.exists():
        report["ok"] = False
        report["problems"].append(f"no telemetry spool at {spool_root} (observer never ran on this machine?)")
        return report
    for folder in sorted(p for p in spool_root.iterdir() if p.is_dir()):
        files = sorted(folder.glob("*.jsonl"))
        events = []
        for path in reversed(files[-2:]):    # today's file, and yesterday's around midnight
            events = _tail_events(path) + events
            if any(e["event_type"] == "heartbeat" for e in events):
                break
        beats = [e for e in events if e["event_type"] == "heartbeat"]
        last = events[-1] if events else None
        entry = {"writer_id": folder.name, "strategy_id": last and last["strategy_id"],
                 "last_event_type": last and last["event_type"], "last_event_utc": last and last["local_capture_utc"],
                 "last_heartbeat_utc": None, "heartbeat_age_s": None, "state": "NO HEARTBEAT",
                 "terminal_connected": None, "trade_allowed": None, "write_failures": None}
        if beats:
            beat = beats[-1]
            runtime = beat.get("runtime") or {}
            age = (now - parse_ts(beat["local_capture_utc"])).total_seconds()
            stopped = last is not None and last["event_type"] == "ea_stopped"
            entry.update(last_heartbeat_utc=beat["local_capture_utc"], heartbeat_age_s=int(age),
                         terminal_connected=runtime.get("terminal_connected"),
                         trade_allowed=runtime.get("trade_allowed"), write_failures=runtime.get("write_failures"),
                         state="STOPPED" if stopped else "STALE" if age > stale_after_s
                         else "MT5 DISCONNECTED" if runtime.get("terminal_connected") is False else "OK")
        if entry["state"] != "OK":
            report["ok"] = False
            report["problems"].append(f"{folder.name}: {entry['state']}")
        report["writers"].append(entry)
    if not report["writers"]:
        report["ok"] = False
        report["problems"].append("no telemetry writers found")
    return report


def record(report: dict, out_dir: Path) -> list[dict]:
    """Save status.json and append state changes to events.jsonl. Returns the changes."""
    out_dir.mkdir(parents=True, exist_ok=True)
    status_path = out_dir / "status.json"
    previous = {}
    if status_path.exists():
        try:
            previous = {w["writer_id"]: w["state"] for w in json.loads(status_path.read_text())["writers"]}
        except (ValueError, KeyError):
            previous = {}
    changes = [{"checked_utc": report["checked_utc"], "writer_id": w["writer_id"], "from": previous.get(w["writer_id"]),
                "to": w["state"]} for w in report["writers"] if previous.get(w["writer_id"]) != w["state"]]
    if changes:
        with open(out_dir / "events.jsonl", "a", encoding="utf-8") as handle:
            for change in changes:
                handle.write(json.dumps(change, sort_keys=True) + "\n")
    temporary = status_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(status_path)
    return changes
