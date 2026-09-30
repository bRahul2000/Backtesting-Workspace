"""Zoneflow's telemetry store: an append-only SQLite copy of every raw line, plus what ingestion found wrong.

Append-only is enforced by the database itself (triggers refuse UPDATE and DELETE on every evidence table), so no code
path - including a buggy future one - can rewrite raw telemetry, corrections or explanations. The only mutable table
is ``ingest_state`` (how far each spool file has been read), which is bookkeeping, not evidence.

Ingestion is idempotent and crash-safe: a spool file's new complete lines and its new read offset are committed in one
transaction. Re-reading bytes that were already ingested (lost state, a copied spool, a rerun) adds nothing; the same
event id arriving with different bytes is recorded as a conflict, never overwritten.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from .schema import LineDefect, decode, salvage

_EVIDENCE = ("events", "defects", "conflicts", "corrections", "annotations")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY, writer_id TEXT NOT NULL, event_type TEXT NOT NULL, strategy_id TEXT NOT NULL,
    magic_number INTEGER, symbol TEXT, deal_id INTEGER, order_id INTEGER, position_id INTEGER,
    capture_mode TEXT, day TEXT NOT NULL, broker_utc TEXT, local_capture_utc TEXT NOT NULL,
    raw BLOB NOT NULL, source_file TEXT NOT NULL, source_offset INTEGER NOT NULL, ingested_utc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_day ON events(strategy_id, day);
CREATE INDEX IF NOT EXISTS events_writer ON events(writer_id, event_type, local_capture_utc);
CREATE TABLE IF NOT EXISTS defects (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source_file TEXT NOT NULL, source_offset INTEGER NOT NULL,
    reason TEXT NOT NULL, raw BLOB NOT NULL, ingested_utc TEXT NOT NULL, UNIQUE(source_file, source_offset));
CREATE TABLE IF NOT EXISTS conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, source_file TEXT NOT NULL,
    source_offset INTEGER NOT NULL, raw BLOB NOT NULL, ingested_utc TEXT NOT NULL, UNIQUE(source_file, source_offset));
CREATE TABLE IF NOT EXISTS corrections (
    correction_id TEXT PRIMARY KEY, day TEXT NOT NULL, strategy_id TEXT NOT NULL, kind TEXT NOT NULL,
    item_key TEXT NOT NULL, telemetry_view TEXT, broker_view TEXT, created_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS annotations (
    annotation_id TEXT PRIMARY KEY, day TEXT NOT NULL, strategy_id TEXT NOT NULL, kind TEXT NOT NULL,
    item_key TEXT NOT NULL, explanation TEXT NOT NULL, author TEXT NOT NULL, created_utc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ingest_state (
    source_file TEXT PRIMARY KEY, offset INTEGER NOT NULL, prefix_sha256 TEXT NOT NULL, updated_utc TEXT NOT NULL);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript(_SCHEMA)
    for table in _EVIDENCE:
        for action in ("UPDATE", "DELETE"):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} "
                       f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END")
    db.commit()
    return db


def event_day(event: dict) -> str:
    """The UTC day an event belongs to: its broker time when it has one (fills, orders), else its capture time."""
    stamp = event.get("broker_utc") or event["local_capture_utc"]
    return stamp[:10]


@dataclass
class IngestReport:
    files: int = 0
    new_events: int = 0
    reingested: int = 0            # already present with identical bytes (safe to see again)
    conflicts: int = 0             # same id, different bytes
    defects: int = 0
    salvaged: int = 0
    waiting_tail_bytes: int = 0    # incomplete last line, left for the next run
    problems: list[str] = field(default_factory=list)


def _insert_event(db, event: dict, raw: bytes, rel: str, offset: int, report: IngestReport) -> None:
    existing = db.execute("SELECT raw FROM events WHERE event_id=?", (event["telemetry_event_id"],)).fetchone()
    if existing is not None:
        if bytes(existing[0]) == raw:
            report.reingested += 1
        else:
            db.execute("INSERT OR IGNORE INTO conflicts(event_id, source_file, source_offset, raw, ingested_utc) "
                       "VALUES (?,?,?,?,?)", (event["telemetry_event_id"], rel, offset, raw, _now()))
            report.conflicts += 1
        return
    db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        event["telemetry_event_id"], event["writer_id"], event["event_type"], event["strategy_id"],
        event.get("magic_number"), event.get("symbol"), event.get("deal_id"), event.get("order_id"),
        event.get("position_id"), event.get("capture_mode"), event_day(event), event.get("broker_utc"),
        event["local_capture_utc"], raw, rel, offset, _now()))
    report.new_events += 1


def _defect(db, rel: str, offset: int, reason: str, raw: bytes, report: IngestReport) -> None:
    cursor = db.execute("INSERT OR IGNORE INTO defects(source_file, source_offset, reason, raw, ingested_utc) "
                        "VALUES (?,?,?,?,?)", (rel, offset, reason, raw, _now()))
    report.defects += cursor.rowcount


def ingest(spool_root: Path, db: sqlite3.Connection, *, today: datetime | None = None) -> IngestReport:
    """Read every spool file from where the last run stopped. Safe to run at any time, any number of times."""
    report = IngestReport()
    today = (today or datetime.now(timezone.utc)).date()
    if not spool_root.exists():
        report.problems.append(f"spool folder not found: {spool_root}")
        return report
    for path in sorted(spool_root.glob("*/*.jsonl")):
        report.files += 1
        rel = path.relative_to(spool_root).as_posix()
        data = path.read_bytes()
        state = db.execute("SELECT offset, prefix_sha256 FROM ingest_state WHERE source_file=?", (rel,)).fetchone()
        offset = 0
        if state:
            offset, digest = state
            if len(data) < offset or hashlib.sha256(data[:offset]).hexdigest() != digest:
                # never "fix" it: record once per observed size (negative offset = whole-file finding), and read
                # nothing further from this file
                _defect(db, rel, -len(data) - 1,"spool file shrank or was rewritten after ingestion", b"", report)
                report.problems.append(f"{rel}: spool file changed behind the reader - not re-read")
                db.commit()
                continue
        chunk = data[offset:]
        end = chunk.rfind(b"\n") + 1
        try:
            file_day = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            file_day = today
        if end < len(chunk) and file_day < today - timedelta(days=1):
            end = len(chunk)                 # an old file can no longer be appended to: its tail is final
        region = chunk[:end]
        lines = (region[:-1] if region.endswith(b"\n") else region).split(b"\n") if region else []
        position = offset
        for raw in lines:
            line_offset, position = position, position + len(raw) + 1
            if not raw.strip():
                continue
            try:
                _insert_event(db, decode(raw), raw.rstrip(b"\r"), rel, line_offset, report)
            except LineDefect as exc:
                garbage, event = salvage(raw)
                if event is not None:
                    _defect(db, rel, line_offset, f"torn write before a valid event: {exc}", garbage, report)
                    _insert_event(db, event, raw[len(garbage):].rstrip(b"\r"), rel, line_offset + len(garbage),
                                  report)
                    report.salvaged += 1
                else:
                    _defect(db, rel, line_offset, str(exc), raw, report)
        new_offset = offset + end
        report.waiting_tail_bytes += len(chunk) - end
        db.execute("INSERT INTO ingest_state VALUES (?,?,?,?) ON CONFLICT(source_file) DO UPDATE SET "
                   "offset=excluded.offset, prefix_sha256=excluded.prefix_sha256, updated_utc=excluded.updated_utc",
                   (rel, new_offset, hashlib.sha256(data[:new_offset]).hexdigest(), _now()))
        db.commit()                           # events + offset together: a crash never half-ingests a file
    return report


def events(db, *, strategy_id: str | None = None, days: list[str] | None = None,
           event_types: list[str] | None = None) -> list[dict]:
    sql, args = "SELECT raw FROM events WHERE 1=1", []
    if strategy_id:
        sql += " AND strategy_id=?"
        args.append(strategy_id)
    if days:
        sql += f" AND day IN ({','.join('?' * len(days))})"
        args += days
    if event_types:
        sql += f" AND event_type IN ({','.join('?' * len(event_types))})"
        args += event_types
    rows = db.execute(sql + " ORDER BY local_capture_utc, writer_id, event_id", args).fetchall()
    return [json.loads(bytes(r[0]).decode("utf-8")) for r in rows]


def add_annotation(db, *, day: str, strategy_id: str, kind: str, item_key: str, explanation: str,
                   author: str) -> str:
    """Explain a discrepancy (e.g. a heartbeat gap during a planned VPS reboot). Explanations are evidence too:
    append-only, never edited; a later one can supersede an earlier one only by being added."""
    if not explanation.strip():
        raise ValueError("an explanation must say something")
    created = _now()
    annotation_id = hashlib.sha256(f"{day}|{strategy_id}|{kind}|{item_key}|{explanation}|{created}".encode()).hexdigest()[:24]
    db.execute("INSERT INTO annotations VALUES (?,?,?,?,?,?,?,?)",
               (annotation_id, day, strategy_id, kind, item_key, explanation.strip(), author, created))
    db.commit()
    return annotation_id


def annotations(db, day: str, strategy_id: str) -> dict[tuple[str, str], str]:
    rows = db.execute("SELECT kind, item_key, explanation FROM annotations WHERE day=? AND strategy_id=? "
                      "ORDER BY created_utc", (day, strategy_id)).fetchall()
    return {(kind, key): text for kind, key, text in rows}


def add_correction(db, *, day: str, strategy_id: str, kind: str, item_key: str, telemetry_view, broker_view) -> bool:
    """Record what telemetry captured next to what the broker reports. Deterministic id: a rerun adds nothing."""
    correction_id = hashlib.sha256(f"{day}|{strategy_id}|{kind}|{item_key}".encode()).hexdigest()[:24]
    cursor = db.execute("INSERT OR IGNORE INTO corrections VALUES (?,?,?,?,?,?,?,?)", (
        correction_id, day, strategy_id, kind, item_key,
        None if telemetry_view is None else json.dumps(telemetry_view, sort_keys=True),
        None if broker_view is None else json.dumps(broker_view, sort_keys=True), _now()))
    return cursor.rowcount == 1
