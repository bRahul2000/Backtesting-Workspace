"""R4 Stage 3 — live forward shadow validation support.

Stage 2 proved the twin against recorded history. Stage 3 proves it against
bars that did not exist when the code was written, and against the operational
events a Strategy Tester run can never produce: restarts, reconnects, tick
outages and back-filled bars.

Nothing here sends an order or can cause one to be sent. Everything is read-only
over evidence files produced by the EA, except the evidence ledger, which is
strictly append-only.

Design notes that matter for reading the rest of this module:

* The EA's audit log holds every bar it replayed from its anchor plus every bar
  that has closed since. Bars at or after the session's first start are
  genuinely forward; earlier ones are replayed history. Parity is checked over
  all of them, but the Stage 3 gate only counts the forward ones.
* Two comparison modes exist. FULL re-derives the Python side from an
  independent fresh broker export, so it tests market data and logic together.
  LOGIC_ONLY re-derives it from the market columns of the MT5 audit itself, so
  it tests only the decision path and says so.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.core_audit_schema import AUDIT_COLUMNS, KEY  # noqa: E402

STEP = pd.Timedelta(minutes=15)

#: Where the operator drops evidence copied out of the terminal.
STAGE3_DIR = ROOT / "data/exness/btc/stage3"
AUDIT_FILE = STAGE3_DIR / "btc_core_v1_audit.csv"
SESSION_FILE = STAGE3_DIR / "btc_core_v1_session.csv"
EVENT_FILE = STAGE3_DIR / "btc_core_v1_events.csv"
MARKET_FILE = STAGE3_DIR / "btcusdm_M15_forward.csv"
PYTHON_AUDIT = STAGE3_DIR / "python_core_audit_forward.csv"
LEDGER = ROOT / "reports/validation/stage3_evidence_ledger.jsonl"

#: Session keys that identify what produced an audit. A change in any of them
#: between collections means two different things wrote one evidence file.
IDENTITY_KEYS = (
    "session_id", "twin_build", "compiled_utc", "core_fingerprint",
    "a4_fingerprint", "t3_fingerprint", "symbol", "broker", "server",
    "digits", "point", "tick_size", "anchor_utc", "mode",
)

#: Fingerprints the twin must still carry. A mismatch means the EA was built
#: against different frozen strategy files.
EXPECTED_FINGERPRINTS = {
    "core_fingerprint": "631374d50cfa75d46349c0e7e8b2f26ac482e2bbf6dc1cf74dc8e1a00e16a9fd",
    "a4_fingerprint": "55fedf8564537549f076e726916286256f504749283a2b587b3cdc964926f3d9",
    "t3_fingerprint": "4c4ab845852ff973530f30ebee86061ea72bd29d68ff6165970dd5a9efde7910",
}

BLOCKING = "BLOCKING"
WARNING = "WARNING"
INFO = "INFO"


@dataclass
class Issue:
    severity: str
    code: str
    detail: str

    def as_dict(self) -> dict:
        return {"severity": self.severity, "code": self.code, "detail": self.detail}


@dataclass
class Stage3State:
    session: dict = field(default_factory=dict)
    events: pd.DataFrame | None = None
    audit: pd.DataFrame | None = None
    issues: list[Issue] = field(default_factory=list)

    def add(self, severity: str, code: str, detail: str) -> None:
        self.issues.append(Issue(severity, code, detail))

    @property
    def blocking(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == BLOCKING]


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _utc(value: str) -> pd.Timestamp | None:
    if not value:
        return None
    try:
        stamp = pd.Timestamp(value)
    except ValueError:
        return None
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def load_session(path: Path = SESSION_FILE) -> dict:
    """The EA's key,value session file. Missing file is not an error here."""
    if not path.exists():
        return {}
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    if list(frame.columns[:2]) != ["key", "value"]:
        raise ValueError(f"{path.name}: expected a key,value session file")
    return dict(zip(frame["key"], frame["value"]))


def load_events(path: Path = EVENT_FILE) -> pd.DataFrame:
    columns = ["event_time_utc", "session_id", "schema_version", "kind", "detail"]
    if not path.exists():
        return pd.DataFrame(columns=columns)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise ValueError(f"{path.name}: missing event columns {missing}")
    return frame


def load_audit(path: Path = AUDIT_FILE) -> pd.DataFrame:
    """Stage 2 schema, unchanged. Stage 3 adds files, never columns."""
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in AUDIT_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"{path.name}: audit is missing columns {missing}")
    return frame[AUDIT_COLUMNS].copy()


def audit_integrity(audit: pd.DataFrame) -> dict:
    """Exactly-once, monotonic, and gap structure of an audit file.

    A duplicate or reversed bar is a failure of the EA's scheduler, not a
    market fact, so they are counted separately from genuine data gaps.
    """
    stamps = pd.to_datetime(audit[KEY], utc=True, format="mixed")
    duplicates = audit.loc[stamps.duplicated(keep=False), KEY].tolist()
    reversals = [str(stamps.iloc[i]) for i in range(1, len(stamps))
                 if stamps.iloc[i] < stamps.iloc[i - 1]]
    ordered = stamps.sort_values().drop_duplicates()
    gaps = [(str(ordered.iloc[i - 1]), str(ordered.iloc[i]),
             int((ordered.iloc[i] - ordered.iloc[i - 1]) / STEP) - 1)
            for i in range(1, len(ordered))
            if ordered.iloc[i] - ordered.iloc[i - 1] != STEP]
    return {
        "bars": int(len(audit)),
        "unique_bars": int(ordered.size),
        "duplicate_bars": sorted(set(duplicates)),
        "time_reversals": reversals,
        "gaps": gaps,
        "first_bar": str(ordered.iloc[0]) if len(ordered) else None,
        "last_bar": str(ordered.iloc[-1]) if len(ordered) else None,
    }


def market_frame_from_audit(audit: pd.DataFrame) -> pd.DataFrame:
    """The market data the EA recorded, in the processed M15 layout.

    Used by LOGIC_ONLY comparison. It deliberately feeds Python the EA's own
    view of the market, which isolates decision parity from data parity — and
    therefore cannot detect a data error. Only FULL mode can.
    """
    stamps = pd.to_datetime(audit[KEY], utc=True, format="mixed")
    frame = pd.DataFrame({
        "timestamp_utc": stamps,
        "open": pd.to_numeric(audit["open"]),
        "high": pd.to_numeric(audit["high"]),
        "low": pd.to_numeric(audit["low"]),
        "close": pd.to_numeric(audit["close"]),
        "tick_volume": pd.to_numeric(audit["tick_volume"]),
        "real_volume": 0.0,
        "spread_points": pd.to_numeric(audit["spread_points"]),
        "spread_price": pd.to_numeric(audit["spread_price"]),
    })
    return frame.sort_values("timestamp_utc").drop_duplicates(
        "timestamp_utc").reset_index(drop=True)


def forward_boundary(session: dict) -> pd.Timestamp | None:
    """First bar that is genuinely forward, i.e. at or after the first start.

    session_id is the first-start UTC timestamp, so it doubles as the boundary
    between replayed history and forward observation.
    """
    return _utc(session.get("first_start_utc") or session.get("session_id", ""))


def check_environment(session: dict, state: Stage3State) -> None:
    """Failure conditions that invalidate a run regardless of parity."""
    if not session:
        state.add(BLOCKING, "NO_SESSION_FILE",
                  "No session file collected; run identity cannot be established.")
        return
    for key, expected in EXPECTED_FINGERPRINTS.items():
        actual = session.get(key, "")
        if not actual:
            state.add(BLOCKING, "MISSING_FINGERPRINT", f"session has no {key}")
        elif actual != expected:
            state.add(BLOCKING, "STALE_OR_WRONG_BUILD",
                      f"{key} is {actual[:16]}…, expected {expected[:16]}…")
    if session.get("mode") != "AUDIT_ONLY":
        state.add(BLOCKING, "NOT_AUDIT_ONLY",
                  f"EA mode is {session.get('mode')!r}; Stage 3 requires AUDIT_ONLY.")
    if session.get("symbol") and session["symbol"] != "BTCUSDm":
        state.add(BLOCKING, "WRONG_SYMBOL", f"symbol is {session['symbol']}")
    if session.get("digits") and session["digits"] != "2":
        state.add(BLOCKING, "WRONG_DIGITS", f"digits is {session['digits']}, expected 2")
    point = session.get("point", "")
    if point and abs(float(point) - 0.01) > 1e-12:
        state.add(BLOCKING, "WRONG_POINT", f"point is {point}, expected 0.01")
    offset = session.get("server_utc_offset_secs", "")
    if offset and abs(int(offset)) > 60:
        state.add(BLOCKING, "NON_UTC_SERVER",
                  f"server clock offset is {offset}s; the twin requires UTC")
    version = session.get("schema_version", "")
    if version and version != "1":
        state.add(WARNING, "SESSION_SCHEMA",
                  f"session schema version {version} is newer than this tool expects")
    for count_key, code in (("duplicate_bars", "EA_DUPLICATE_BARS"),
                            ("reversed_bars", "EA_TIME_REVERSAL")):
        raw = session.get(count_key, "0")
        if raw.isdigit() and int(raw) > 0:
            state.add(BLOCKING, code, f"EA reported {raw} {count_key}")


def check_audit(audit: pd.DataFrame, session: dict, state: Stage3State) -> dict:
    integrity = audit_integrity(audit)
    if integrity["duplicate_bars"]:
        state.add(BLOCKING, "DUPLICATE_CLOSED_BAR",
                  f"{len(integrity['duplicate_bars'])} bar(s) appear twice, first "
                  f"{integrity['duplicate_bars'][0]}")
    if integrity["time_reversals"]:
        state.add(BLOCKING, "TIME_REVERSAL",
                  f"{len(integrity['time_reversals'])} bar(s) go backwards in time")
    for start, end, missing in integrity["gaps"]:
        state.add(WARNING, "AUDIT_GAP",
                  f"{missing} bar(s) absent between {start} and {end}")
    last = _utc(integrity["last_bar"] or "")
    recorded = _utc(session.get("last_logged_bar_utc", ""))
    if last is not None and recorded is not None and last != recorded:
        state.add(WARNING, "SESSION_AUDIT_SKEW",
                  f"session says last logged {recorded}, audit ends {last}")
    return integrity


def summarise_events(events: pd.DataFrame, state: Stage3State) -> dict:
    kinds = events["kind"].value_counts().to_dict() if len(events) else {}
    for code in ("ANCHOR_UNREACHABLE",):
        if kinds.get(code):
            state.add(BLOCKING, code, f"EA logged {kinds[code]} {code} event(s)")
    if kinds.get("TIME_REVERSAL") or kinds.get("DUPLICATE_BAR"):
        state.add(BLOCKING, "EA_SCHEDULER_ANOMALY",
                  f"EA logged duplicate/reversed bar events: {kinds}")
    return {
        "counts": kinds,
        "restarts": int(kinds.get("RESTART", 0)),
        "reconnects": int(kinds.get("RECONNECT", 0)),
        "disconnects": int(kinds.get("DISCONNECT", 0)),
        "tick_outages": int(kinds.get("TICK_OUTAGE", 0)),
        "data_gaps": int(kinds.get("DATA_GAP", 0)),
        "backfills": int(kinds.get("BACKFILL", 0)),
    }


def lifecycle_counts(audit: pd.DataFrame, since: pd.Timestamp | None = None) -> dict:
    """Signal and order-lifecycle tallies, optionally only from `since`."""
    frame = audit
    if since is not None:
        stamps = pd.to_datetime(frame[KEY], utc=True, format="mixed")
        frame = frame.loc[stamps >= since]
    a4 = "BTC_V3_A4_PULLBACK_LONG_FROZEN"
    t3 = "BTC_V3_T3_BREAKOUT_SHORT_FROZEN"
    status = frame["pending_status"]
    return {
        "bars": int(len(frame)),
        "a4_signals": int((frame["signal_setup_id"] == a4).sum()),
        "t3_signals": int((frame["signal_setup_id"] == t3).sum()),
        "pending_created": int((status == "CREATED").sum()),
        "fills": int((status == "FILLED").sum()),
        "expirations": int((status == "EXPIRED").sum()),
        "cancellations": int((status == "CANCELLED").sum()),
        "exits": int((frame["exit_time_utc"] != "").sum()),
        "stop_loss_exits": int(frame["exit_reason"].str.startswith("Stop loss").sum()),
        "take_profit_exits": int(frame["exit_reason"].str.startswith("Take profit").sum()),
    }


def open_state(audit: pd.DataFrame) -> dict:
    """Pending order and simulated position as of the last logged bar."""
    if audit.empty:
        return {"pending": None, "position": None, "last_bar": None}
    last = audit.iloc[-1]
    pending = None
    if last["pending_status"] in ("CREATED", "ACTIVE"):
        pending = {"status": last["pending_status"], "trigger": last["pending_trigger"],
                   "stop": last["pending_stop"], "expiry": last["pending_expiry_utc"]}
    position = None
    stamps = pd.to_datetime(audit[KEY], utc=True, format="mixed")
    entries = audit.loc[audit["entry_time_utc"] != ""]
    exits = audit.loc[audit["exit_time_utc"] != ""]
    if len(entries) > len(exits):
        row = entries.iloc[-1]
        position = {"entry_time": row["entry_time_utc"], "entry": row["entry_price"],
                    "stop": row["entry_stop"], "target": row["entry_target"]}
    return {"pending": pending, "position": position, "last_bar": str(stamps.iloc[-1])}


def append_ledger(entry: dict, path: Path = LEDGER) -> None:
    """Append-only. Existing evidence is never rewritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = dict(entry)
    entry.setdefault("recorded_at_utc", datetime.now(timezone.utc).isoformat())
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, default=str, sort_keys=True) + "\n")


def read_ledger(path: Path = LEDGER) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
