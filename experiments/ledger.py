from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT UNIQUE,
    timestamp_utc TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    strategy_status TEXT NOT NULL,
    strategy_fingerprint TEXT NOT NULL,
    parameter_fingerprint TEXT NOT NULL,
    dataset_fingerprint TEXT NOT NULL,
    broker_fingerprint TEXT NOT NULL,
    instrument_fingerprint TEXT NOT NULL DEFAULT '',
    broker_profile TEXT NOT NULL,
    instrument TEXT NOT NULL,
    date_start TEXT NOT NULL,
    date_end TEXT NOT NULL,
    dataset_role TEXT NOT NULL,
    config_json TEXT NOT NULL,
    results_json TEXT,
    notes TEXT NOT NULL DEFAULT ''
    ,strategy_version TEXT NOT NULL DEFAULT ''
    ,first_seen_at TEXT NOT NULL DEFAULT ''
    ,exposure_count INTEGER NOT NULL DEFAULT 1
);
"""


class ExperimentLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(experiments)")}
            if "instrument_fingerprint" not in columns:
                conn.execute(
                    "ALTER TABLE experiments ADD COLUMN instrument_fingerprint TEXT NOT NULL DEFAULT ''"
                )
            for column, definition in (("strategy_version", "TEXT NOT NULL DEFAULT ''"),
                                       ("first_seen_at", "TEXT NOT NULL DEFAULT ''"),
                                       ("exposure_count", "INTEGER NOT NULL DEFAULT 1")):
                if column not in columns:
                    conn.execute(f"ALTER TABLE experiments ADD COLUMN {column} {definition}")

    def _connect(self):
        return sqlite3.connect(self.path)

    def start_run(self, *, strategy_id: str, strategy_name: str, strategy_status: str,
                  strategy_fingerprint: str, parameter_fingerprint: str,
                  dataset_fingerprint: str, broker_fingerprint: str,
                  broker_profile: str, instrument: str, date_start: str,
                  date_end: str, dataset_role: str, config: dict[str, Any],
                  notes: str = "", instrument_fingerprint: str = "",
                  strategy_version: str = "") -> str:
        with self._connect() as conn:
            first_seen = datetime.now(timezone.utc).isoformat()
            exposure_count = conn.execute(
                "SELECT COUNT(*) FROM experiments WHERE strategy_id=? AND parameter_fingerprint=? AND dataset_role IN ('FORWARD_VALIDATION','HOLDOUT')",
                (strategy_id, parameter_fingerprint),
            ).fetchone()[0] + 1
            cursor = conn.execute(
                """INSERT INTO experiments (
                                timestamp_utc,strategy_id,strategy_name,strategy_status,
                strategy_fingerprint,parameter_fingerprint,dataset_fingerprint,
                broker_fingerprint,instrument_fingerprint,broker_profile,instrument,date_start,date_end,
                                dataset_role,config_json,notes,strategy_version,first_seen_at,exposure_count
                                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    datetime.now(timezone.utc).isoformat(), strategy_id, strategy_name,
                    strategy_status, strategy_fingerprint, parameter_fingerprint,
                    dataset_fingerprint, broker_fingerprint, instrument_fingerprint, broker_profile, instrument,
                    date_start, date_end, dataset_role,
                    json.dumps(config, sort_keys=True, default=str), notes, strategy_version,
                    first_seen, exposure_count,
                ),
            )
            seq = cursor.lastrowid
            run_id = f"BT-{datetime.now(timezone.utc).year}-{seq:06d}"
            conn.execute("UPDATE experiments SET run_id=? WHERE sequence=?", (run_id, seq))
        return run_id

    def finish_run(self, run_id: str, result: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE experiments SET results_json=? WHERE run_id=?",
                (json.dumps(result, sort_keys=True, default=str), run_id),
            )

    def forward_run_count(self, strategy_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM experiments WHERE strategy_id=? AND dataset_role='FORWARD_VALIDATION'",
                (strategy_id,),
            ).fetchone()
        return int(row[0])

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM experiments WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs(self, *, instrument: str | None = None,
                  strategy_id: str | None = None,
                  dataset_role: str | None = None) -> list[dict[str, Any]]:
        clauses = []
        values: list[str] = []
        for column, value in (("instrument", instrument), ("strategy_id", strategy_id),
                              ("dataset_role", dataset_role)):
            if value is not None:
                clauses.append(f"{column}=?")
                values.append(value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM experiments" + where + " ORDER BY sequence DESC", values
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["results_json"] = json.loads(item["results_json"]) if item["results_json"] else {}
            output.append(item)
        return output

    def exposure_warning(self, strategy_id: str, parameter_fingerprint: str,
                         dataset_role: str) -> str | None:
        if dataset_role not in {"FORWARD_VALIDATION", "HOLDOUT"}:
            return None
        with self._connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM experiments WHERE strategy_id=? AND parameter_fingerprint=? AND dataset_role IN ('FORWARD_VALIDATION','HOLDOUT')",
                (strategy_id, parameter_fingerprint),
            ).fetchone()[0]
        if count > 1:
            return "FORWARD DATA HAS BEEN EXPOSED TO THIS CONFIGURATION"
        return None
