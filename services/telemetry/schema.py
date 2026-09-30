"""Telemetry V1 raw event schema: field list, validation and the self-checking JSON-lines encoding.

One event = one line:  {"schema_version":1, ... ,"crc32":"1a2b3c4d"}\n
The CRC-32 covers the exact UTF-8 bytes of the line before the ``,"crc32":"`` marker, so a torn or altered line is
detected without re-serialising anything (the MQL5 writer and this module need not format numbers identically).

Timestamps are UTC ISO-8601 strings ending in "Z", with milliseconds where the source has them (broker deal/order
times, DEAL_TIME_MSC) and whole seconds where it does not (the terminal's TimeGMT()). ``broker_time_server`` keeps the
broker's own server-clock value untouched; ``server_utc_offset_s`` is the offset the writer measured when converting.
Unknown / not applicable values are null - never guessed.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
import zlib

SCHEMA_VERSION = 1
CRC_MARKER = b',"crc32":"'

EVENT_TYPES = frozenset({
    "ea_started", "ea_stopped", "heartbeat",
    "signal_generated",
    "order_requested", "order_accepted", "order_rejected", "order_cancelled", "order_expired",
    "position_opened", "position_modified", "exit_requested", "position_closed",
    "broker_disconnect", "broker_reconnect",
    "error",
})
# events that describe a broker deal (a fill); reconciliation matches these to MT5 deal history by deal_id
DEAL_EVENTS = frozenset({"position_opened", "position_closed"})
# events that describe a broker order; matched to MT5 order history by order_id
ORDER_EVENTS = frozenset({"order_accepted", "order_rejected", "order_cancelled", "order_expired"})

DIRECTIONS = frozenset({"buy", "sell"})
# factual exit reasons, straight from MT5 DEAL_REASON (never inferred)
EXIT_REASONS = frozenset({"sl", "tp", "stop_out", "client", "mobile", "web", "expert", "rollover", "vmargin",
                          "split", "other"})
CAPTURE_MODES = frozenset({"realtime", "strategy"})

_STR, _INT, _NUM, _TS, _OBJ = "str", "int", "num", "ts", "obj"
# name -> (type, required)
FIELDS: dict[str, tuple[str, bool]] = {
    "schema_version": (_INT, True),
    "telemetry_event_id": (_STR, True),
    "writer_id": (_STR, True),            # which program wrote it (one spool directory per writer)
    "writer_run_id": (_STR, True),        # one value per program start
    "sequence": (_INT, True),             # 1, 2, 3 ... within a run
    "event_type": (_STR, True),
    "capture_mode": (_STR, True),         # realtime = observer saw it happen; strategy = the strategy EA reported it
    "strategy_id": (_STR, True),
    "strategy_version": (_STR, False),
    "strategy_parameters_hash": (_STR, False),
    "broker": (_STR, False),              # ACCOUNT_COMPANY
    "account_server": (_STR, False),      # ACCOUNT_SERVER
    "account_environment": (_STR, False), # demo | real | contest
    "account_ref": (_STR, False),         # SHA-256(login|server)[:16] - the login itself is never written
    "symbol": (_STR, False),
    "magic_number": (_INT, False),
    "order_id": (_INT, False),
    "ticket_id": (_INT, False),
    "deal_id": (_INT, False),
    "position_id": (_INT, False),
    "signal_utc": (_TS, False),
    "request_utc": (_TS, False),
    "broker_time_server": (_STR, False),  # broker server clock, as reported (no zone)
    "server_utc_offset_s": (_INT, False),
    "broker_utc": (_TS, False),
    "fill_utc": (_TS, False),
    "local_capture_utc": (_TS, True),
    "direction": (_STR, False),           # buy | sell; for fills: the deal's own side (a long closes with a sell)
    "signal_price": (_NUM, False),
    "requested_price": (_NUM, False),
    "fill_price": (_NUM, False),
    "bid": (_NUM, False),
    "ask": (_NUM, False),
    "spread_points": (_INT, False),
    "requested_volume": (_NUM, False),
    "filled_volume": (_NUM, False),
    "stop_loss": (_NUM, False),
    "take_profit": (_NUM, False),
    "broker_return_code": (_INT, False),  # MqlTradeResult.retcode
    "broker_error_code": (_INT, False),   # GetLastError() after the trade call
    "exit_reason": (_STR, False),
    "raw_error_code": (_INT, False),
    "deal_entry": (_STR, False),          # in | out | inout | out_by (MT5 DEAL_ENTRY)
    "runtime": (_OBJ, False),             # heartbeat / start / stop facts (status, connection, counters)
    "strategy_state": (_OBJ, False),      # OPTIONAL strategy decision state, explicitly labelled as such
    "message": (_STR, False),
    "crc32": (_STR, True),
}
# interpretations that must never be stored as raw truth (derived later from market data)
FORBIDDEN_FIELDS = frozenset({"regime", "market_regime", "trend_regime", "volatility_regime", "session",
                              "session_classification", "mfe", "mae", "r_multiple", "trade_quality", "setup_quality"})

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class SchemaError(ValueError):
    pass


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def format_ts(moment: datetime, ms: bool = True) -> str:
    moment = moment.astimezone(timezone.utc)
    text = moment.strftime("%Y-%m-%dT%H:%M:%S")
    return text + (f".{moment.microsecond // 1000:03d}" if ms else "") + "Z"


def validate(event: dict) -> list[str]:
    """Every problem with an event (empty list = valid). Unknown fields are refused so nothing slips in untyped."""
    problems = []
    for name in event:
        if name not in FIELDS:
            problems.append(f"unknown field {name!r}" + (" (an interpretation, not a raw fact)"
                                                          if name in FORBIDDEN_FIELDS else ""))
    for name, (kind, required) in FIELDS.items():
        value = event.get(name)
        if value is None:
            if required:
                problems.append(f"missing {name}")
            continue
        ok = {_STR: isinstance(value, str), _INT: isinstance(value, int) and not isinstance(value, bool),
              _NUM: isinstance(value, (int, float)) and not isinstance(value, bool),
              _TS: isinstance(value, str) and bool(_TS_RE.match(value)), _OBJ: isinstance(value, dict)}[kind]
        if not ok:
            problems.append(f"{name} has the wrong type/format: {value!r}")
    if event.get("schema_version") not in (None, SCHEMA_VERSION):
        problems.append(f"unsupported schema_version {event.get('schema_version')!r}")
    if event.get("event_type") is not None and event["event_type"] not in EVENT_TYPES:
        problems.append(f"unknown event_type {event['event_type']!r}")
    if event.get("capture_mode") is not None and event["capture_mode"] not in CAPTURE_MODES:
        problems.append(f"unknown capture_mode {event['capture_mode']!r}")
    if event.get("direction") is not None and event["direction"] not in DIRECTIONS:
        problems.append(f"direction must be buy/sell, not {event['direction']!r}")
    if event.get("exit_reason") is not None and event["exit_reason"] not in EXIT_REASONS:
        problems.append(f"unknown exit_reason {event['exit_reason']!r}")
    for name in ("telemetry_event_id", "writer_id", "writer_run_id", "strategy_id"):
        if isinstance(event.get(name), str) and not _ID_RE.match(event[name]):
            problems.append(f"{name} has characters outside [A-Za-z0-9._:-]")
    if isinstance(event.get("account_ref"), str) and not re.fullmatch(r"[0-9a-f]{16}", event["account_ref"]):
        problems.append("account_ref must be 16 lowercase hex characters (a hash, never the login)")
    for name in ("runtime", "strategy_state"):
        if isinstance(event.get(name), dict):
            bad = FORBIDDEN_FIELDS & set(event[name])
            if bad and name == "runtime":
                problems.append(f"runtime may not carry interpretations: {sorted(bad)}")
    if event.get("event_type") in DEAL_EVENTS and event.get("capture_mode") == "realtime" and event.get("deal_id") is None:
        problems.append(f"{event['event_type']} captured from the broker must carry deal_id")
    return problems


def crc_of(prefix: bytes) -> str:
    return f"{zlib.crc32(prefix) & 0xFFFFFFFF:08x}"


def encode(event: dict) -> bytes:
    """Serialise one event as a self-checking line (the Python twin of the MQL5 writer)."""
    body = {k: v for k, v in event.items() if k != "crc32" and v is not None}
    body.setdefault("schema_version", SCHEMA_VERSION)
    ordered = {"schema_version": body.pop("schema_version"), **body}
    prefix = json.dumps(ordered, separators=(",", ":"), ensure_ascii=False, allow_nan=False)[:-1].encode("utf-8")
    return prefix + CRC_MARKER + crc_of(prefix).encode() + b'"}\n'


class LineDefect(Exception):
    """A complete line that is not a valid event (torn write, bit rot, hand edit)."""


def decode(line: bytes) -> dict:
    """Parse and check one complete line (without its newline). Raises LineDefect."""
    line = line.rstrip(b"\r")
    at = line.rfind(CRC_MARKER)
    if at < 0 or not line.endswith(b'"}') or len(line) - at != len(CRC_MARKER) + 10:
        raise LineDefect("no crc32 trailer")
    expected = line[at + len(CRC_MARKER):-2].decode("ascii", "replace")
    if crc_of(line[:at]) != expected:
        raise LineDefect("crc32 mismatch")
    try:
        event = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise LineDefect(f"not JSON: {exc}") from None
    if not isinstance(event, dict):
        raise LineDefect("not a JSON object")
    problems = validate(event)
    if problems:
        raise LineDefect("; ".join(problems[:5]))
    return event


def salvage(line: bytes) -> tuple[bytes, dict | None]:
    """A torn write followed by a good append leaves ``<partial><good line>`` on one line. Return (garbage, event)
    where event is the last complete, valid event embedded in the line (or None)."""
    start = line.rfind(b'{"schema_version":')
    while start > 0:
        try:
            return line[:start], decode(line[start:])
        except LineDefect:
            start = line.rfind(b'{"schema_version":', 0, start)
    return line, None
