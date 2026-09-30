"""Telemetry V1: schema, spool, ingestion, reconciliation, corrections, tracker, watchdog, safety."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess

import pytest

from services.telemetry import reconcile, store, tracker, watchdog
from services.telemetry.schema import (CRC_MARKER, FIELDS, LineDefect, crc_of, decode, encode, format_ts, parse_ts,
                                       salvage, validate)
from services.telemetry.writer import SpoolWriter

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "telemetry"
MQL = ROOT / "services" / "telemetry" / "mql5"
DAY = "2026-10-05"
MAGIC = 515010220
STRATEGY = {"strategy_id": "btc_setup_a", "magic_numbers": [MAGIC], "symbols": ["BTCUSDm"]}


class Clock:
    def __init__(self, start: datetime):
        self.now = start

    def __call__(self):
        return self.now


def utc(text: str) -> datetime:
    return parse_ts(text)


# ---- fixtures: a writer, a store, a broker export --------------------------------------------------------------------

@pytest.fixture
def env(tmp_path):
    spool, broker = tmp_path / "spool", tmp_path / "broker"
    db = store.connect(tmp_path / "store" / "telemetry.sqlite3")
    return {"spool": spool, "broker": broker, "db": db, "tmp": tmp_path}


def observer(spool, clock):
    return SpoolWriter(spool, "observer.btc_setup_a", "btc_setup_a", clock=clock, broker="Exness Technologies Ltd",
                       account_server="Exness-MT5Trial5", account_environment="demo", account_ref="0" * 16)


def heartbeats(writer, clock, start: datetime, end: datetime, every=60):
    clock.now = start
    while clock.now <= end:
        writer.emit("heartbeat", runtime={"status": "running", "terminal_connected": True, "trade_allowed": True,
                                          "write_failures": writer.write_failures})
        clock.now += timedelta(seconds=every)


def fill(writer, clock, deal_id, *, entry="in", price=65000.5, volume=0.01, at="2026-10-05T10:00:00.250Z",
         order_id=None, position_id=None, reason=None, side="buy"):
    clock.now = utc(at) + timedelta(seconds=1)
    return writer.emit("position_opened" if entry == "in" else "position_closed", symbol="BTCUSDm",
                       magic_number=MAGIC, deal_id=deal_id, ticket_id=deal_id, order_id=order_id or deal_id + 1000,
                       position_id=position_id or 7, direction=side, deal_entry=entry, broker_utc=at, fill_utc=at,
                       fill_price=price, filled_volume=volume, exit_reason=reason)


def broker_deal(deal_id, *, entry="in", price=65000.5, volume=0.01, at="2026-10-05T10:00:00.250Z", order_id=None,
                position_id=None, reason="expert", side="buy", magic=MAGIC):
    return {"deal_id": deal_id, "order_id": order_id or deal_id + 1000, "position_id": position_id or 7,
            "symbol": "BTCUSDm", "magic_number": magic, "type": side, "entry": entry, "reason": reason,
            "volume": volume, "price": price, "broker_utc": at, "time_server": at[:19].replace("-", ".").replace("T", " "),
            "digits": 2}


def write_export(broker_root, day, deals, orders=()):
    folder = broker_root / ("0" * 16)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{day}.json").write_text(json.dumps({
        "export_version": 1, "day": day, "account_ref": "0" * 16, "server_utc_offset_s": 0,
        "deals": list(deals), "orders": list(orders), "complete": True}))


def full_day(env, fills=(), deals=(), orders=(), *, gap=None):
    """A day with continuous heartbeats (optionally a gap), the given telemetry fills and broker deals."""
    clock = Clock(utc(f"{DAY}T00:00:00Z"))
    writer = observer(env["spool"], clock)
    start, end = utc(f"{DAY}T00:00:00Z") - timedelta(minutes=2), utc(f"{DAY}T23:59:59Z") + timedelta(minutes=2)
    if gap:
        heartbeats(writer, clock, start, gap[0])
        heartbeats(writer, clock, gap[1], end)
    else:
        heartbeats(writer, clock, start, end)
    for kwargs in fills:
        fill(writer, clock, **kwargs)
    write_export(env["broker"], DAY, deals, orders)
    return writer, clock


def run(env, now=None):
    store.ingest(env["spool"], env["db"], today=now or utc("2026-10-07T00:00:00Z"))
    return reconcile.reconcile_day(env["db"], DAY, [STRATEGY], env["broker"], now=now or utc("2026-10-06T06:00:00Z"))


def strat(result):
    return result["strategies"][0]


# ---- schema and serialisation ------------------------------------------------------------------------------------------

def test_schema_requires_the_raw_minimum_and_refuses_interpretations():
    writer = SpoolWriter(Path("/nonexistent"), "w", "s")
    base = {"schema_version": 1, "telemetry_event_id": "w:r:1", "writer_id": "w", "writer_run_id": "r", "sequence": 1,
            "event_type": "heartbeat", "capture_mode": "realtime", "strategy_id": "s",
            "local_capture_utc": "2026-10-05T00:00:00Z", "crc32": "00000000"}
    assert validate(base) == []
    for field in ("telemetry_event_id", "event_type", "strategy_id", "local_capture_utc", "schema_version"):
        assert any(field in p for p in validate({k: v for k, v in base.items() if k != field}))
    for interpretation in ("market_regime", "mfe", "mae", "r_multiple", "session", "trade_quality", "setup_quality"):
        assert any("interpretation" in p for p in validate({**base, interpretation: 1}))
    assert validate({**base, "event_type": "regime_changed"})
    assert validate({**base, "local_capture_utc": "2026-10-05 00:00:00"})           # must be ISO UTC with Z
    assert validate({**base, "account_ref": "123456789"})                           # a login is not a reference
    assert validate({**base, "direction": "long"})
    assert validate({**base, "exit_reason": "stopped_out_probably"})
    # strategy decision state is allowed, clearly labelled, and kept out of the typed raw fields
    assert validate({**base, "strategy_state": {"ema_fast": 1.2, "note": "strategy's own state"}}) == []
    assert "strategy_state" in FIELDS and writer.capture_mode == "realtime"


def test_serialisation_round_trip_and_crc_detects_any_change():
    event = {"telemetry_event_id": "w:r:1", "writer_id": "w", "writer_run_id": "r", "sequence": 1,
             "event_type": "position_opened", "capture_mode": "realtime", "strategy_id": "s", "deal_id": 5,
             "fill_price": 65000.5, "message": 'quote " and \\ and ünïcode', "local_capture_utc": "2026-10-05T00:00:01Z"}
    line = encode(event)
    assert line.endswith(b'"}\n') and line.count(b"\n") == 1
    decoded = decode(line[:-1])
    assert decoded["fill_price"] == 65000.5 and decoded["message"] == event["message"]
    for i in range(0, len(line) - 12, 7):                   # flip bytes across the whole line
        damaged = bytearray(line[:-1])
        damaged[i] ^= 0x01
        with pytest.raises(LineDefect):
            decode(bytes(damaged))
    with pytest.raises(LineDefect):
        decode(line[:-20])                                  # torn


def test_event_ids_are_unique_across_events_writers_and_restarts(tmp_path):
    clock = Clock(utc("2026-10-05T00:00:00Z"))
    ids = set()
    for restart in range(3):
        writer = observer(tmp_path, clock)
        for _ in range(300):
            ids.add(writer.emit("heartbeat")["telemetry_event_id"])
        clock.now += timedelta(seconds=1)
    other = SpoolWriter(tmp_path, "observer.other", "other", clock=clock)
    ids.add(other.emit("heartbeat")["telemetry_event_id"])
    assert len(ids) == 901


def test_timestamps_are_utc_with_honest_precision_and_days_follow_broker_time():
    moment = datetime(2026, 10, 5, 23, 59, 59, 999000, tzinfo=timezone.utc)
    assert format_ts(moment) == "2026-10-05T23:59:59.999Z" and format_ts(moment, ms=False) == "2026-10-05T23:59:59Z"
    assert parse_ts("2026-10-05T23:59:59.999Z") == moment
    ist = moment.astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert format_ts(ist) == "2026-10-05T23:59:59.999Z"                # any zone in, UTC out
    # a fill at 23:59:59.999 captured after midnight still belongs to the broker's day
    assert store.event_day({"broker_utc": "2026-10-05T23:59:59.999Z", "local_capture_utc": "2026-10-06T00:00:02Z"}) == DAY
    assert store.event_day({"local_capture_utc": "2026-10-06T00:00:02Z"}) == "2026-10-06"


# ---- spool: append-only, partial writes, failures ----------------------------------------------------------------------

def test_spool_is_append_only_and_a_write_failure_never_raises(tmp_path):
    clock = Clock(utc(f"{DAY}T00:00:00Z"))
    writer = observer(tmp_path / "spool", clock)
    first = writer.emit("heartbeat")
    path = writer.path_for(clock.now)
    before = path.read_bytes()
    writer.emit("heartbeat")
    assert path.read_bytes().startswith(before)                           # earlier bytes never change
    blocked = SpoolWriter(tmp_path / "file-not-dir", "w", "s", clock=clock)
    (tmp_path / "file-not-dir").write_text("x")                           # the spool root is a file: cannot write
    assert blocked.emit("heartbeat") is None and blocked.write_failures == 1
    assert writer.emit("heartbeat", market_regime="trend") is None        # refused, counted, not raised
    assert first["sequence"] == 1


def test_store_refuses_update_and_delete_of_evidence(env):
    clock = Clock(utc(f"{DAY}T00:00:00Z"))
    observer(env["spool"], clock).emit("heartbeat")
    store.ingest(env["spool"], env["db"])
    store.add_annotation(env["db"], day=DAY, strategy_id="s", kind="telemetry_gaps", item_key="k", explanation="x",
                         author="t")
    store.add_correction(env["db"], day=DAY, strategy_id="s", kind="k", item_key="1", telemetry_view=None,
                         broker_view={"deal_id": 1})
    store._defect(env["db"], "w/x.jsonl", 0, "test", b"x", store.IngestReport())
    env["db"].commit()
    for sql in ("UPDATE events SET raw = x'00'", "DELETE FROM events", "DELETE FROM annotations",
                "UPDATE annotations SET explanation='y'", "DELETE FROM corrections", "DELETE FROM defects"):
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            env["db"].execute(sql)


def test_partial_write_is_recovered_without_losing_or_inventing_events(env):
    clock = Clock(utc(f"{DAY}T00:00:00Z"))
    writer = observer(env["spool"], clock)
    for _ in range(3):
        writer.emit("heartbeat")
    path = writer.path_for(clock.now)
    torn = encode({**json.loads(path.read_bytes().splitlines()[0]), "telemetry_event_id": "x:y:99", "sequence": 99})
    with open(path, "ab") as handle:                                       # crash mid-line
        handle.write(torn[:40])
    report = store.ingest(env["spool"], env["db"], today=clock.now)
    assert report.new_events == 3 and report.waiting_tail_bytes == 40      # the torn tail waits, nothing invented
    writer.emit("heartbeat")                                               # the writer seals the tail and appends
    report = store.ingest(env["spool"], env["db"], today=clock.now)
    assert report.new_events == 1 and report.defects == 1                  # torn bytes kept as a defect
    # the same crash WITHOUT the sealing newline (an older writer): the good event is salvaged from the joined line
    good = encode({**json.loads(path.read_bytes().splitlines()[0]), "telemetry_event_id": "x:y:100", "sequence": 100})
    garbage, event = salvage(b'{"schema_version":1,"telemetry_ev' + good[:-1])
    assert event["telemetry_event_id"] == "x:y:100" and garbage.startswith(b'{"schema_version":1,"tel')
    with open(path, "ab") as handle:
        handle.write(b'{"schema_version":1,"telemetry_ev' + good)
    report = store.ingest(env["spool"], env["db"], today=clock.now)
    assert report.new_events == 1 and report.salvaged == 1 and report.defects == 1
    assert env["db"].execute("SELECT COUNT(*) FROM events").fetchone()[0] == 5


def test_an_old_files_unterminated_tail_is_finally_recorded_as_a_defect(env):
    clock = Clock(utc(f"{DAY}T00:00:00Z"))
    writer = observer(env["spool"], clock)
    writer.emit("heartbeat")
    with open(writer.path_for(clock.now), "ab") as handle:
        handle.write(b'{"schema_version":1,"trunc')
    assert store.ingest(env["spool"], env["db"], today=clock.now).waiting_tail_bytes > 0
    report = store.ingest(env["spool"], env["db"], today=clock.now + timedelta(days=3))
    assert report.defects == 1 and report.waiting_tail_bytes == 0


# ---- ingestion: consumer offline, duplicates, restarts -------------------------------------------------------------------

def test_consumer_offline_then_catch_up_loses_nothing(env):
    clock = Clock(utc(f"{DAY}T00:00:00Z"))
    writer = observer(env["spool"], clock)
    heartbeats(writer, clock, utc(f"{DAY}T00:00:00Z"), utc(f"{DAY}T03:00:00Z"))      # Zoneflow down for 3 hours
    report = store.ingest(env["spool"], env["db"], today=clock.now)
    assert report.new_events == 181 and report.problems == []


def test_duplicate_ingestion_is_idempotent_and_conflicts_are_never_overwritten(env):
    clock = Clock(utc(f"{DAY}T00:00:00Z"))
    writer = observer(env["spool"], clock)
    for _ in range(5):
        writer.emit("heartbeat")
    db = env["db"]
    assert store.ingest(env["spool"], db).new_events == 5
    assert store.ingest(env["spool"], db).new_events == 0                  # rerun: nothing new
    db.execute("DELETE FROM ingest_state")                                  # lost bookkeeping (not evidence)
    db.commit()
    again = store.ingest(env["spool"], db)
    assert (again.new_events, again.reingested) == (0, 5)
    copy = env["spool"] / "observer.copy" / f"{DAY}.jsonl"                  # the same lines delivered twice
    copy.parent.mkdir()
    copy.write_bytes(writer.path_for(clock.now).read_bytes())
    report = store.ingest(env["spool"], db)
    assert (report.new_events, report.reingested, report.conflicts) == (0, 5, 0)
    first = json.loads(writer.path_for(clock.now).read_bytes().splitlines()[0])
    forged = env["spool"] / "observer.forged" / f"{DAY}.jsonl"             # same id, different content
    forged.parent.mkdir()
    forged.write_bytes(encode({**first, "sequence": 999}))
    report = store.ingest(env["spool"], db)
    assert report.conflicts == 1
    kept = json.loads(bytes(db.execute("SELECT raw FROM events WHERE event_id=?",
                                       (first["telemetry_event_id"],)).fetchone()[0]))
    assert kept["sequence"] == 1                                            # the original stays
    assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 5


def test_a_rewritten_spool_file_is_flagged_not_reingested(env):
    clock = Clock(utc(f"{DAY}T00:00:00Z"))
    writer = observer(env["spool"], clock)
    writer.emit("heartbeat")
    writer.emit("heartbeat")
    store.ingest(env["spool"], env["db"])
    path = writer.path_for(clock.now)
    path.write_bytes(path.read_bytes().splitlines(keepends=True)[1])        # someone edited the raw file
    report = store.ingest(env["spool"], env["db"])
    assert report.problems and report.new_events == 0 and report.defects == 1


def test_writer_restart_recovery(env):
    clock = Clock(utc(f"{DAY}T00:00:00Z"))
    first = observer(env["spool"], clock)
    first.emit("ea_started")
    first.emit("heartbeat")
    first.emit("ea_stopped", runtime={"status": "stopped", "deinit_reason": 1})
    second = observer(env["spool"], clock)                                  # restarted program, same writer id
    started = second.emit("ea_started")
    assert started["sequence"] == 1 and started["writer_run_id"] != first.run_id
    assert store.ingest(env["spool"], env["db"]).new_events == 4
    runs = {r for (r,) in env["db"].execute("SELECT DISTINCT json_extract(raw, '$.writer_run_id') FROM events")}
    assert runs == {first.run_id, second.run_id}


# ---- reconciliation --------------------------------------------------------------------------------------------------------

EXACT_FILLS = [dict(deal_id=11, entry="in", price=65000.5, at=f"{DAY}T10:00:00.250Z", order_id=21, side="buy"),
               dict(deal_id=12, entry="out", price=65400.25, at=f"{DAY}T12:30:00.500Z", order_id=22, reason="tp",
                    side="sell")]
EXACT_DEALS = [broker_deal(11, entry="in", price=65000.5, at=f"{DAY}T10:00:00.250Z", order_id=21, side="buy"),
               broker_deal(12, entry="out", price=65400.25, at=f"{DAY}T12:30:00.500Z", order_id=22, reason="tp",
                           side="sell")]


def test_exact_reconciliation_passes(env):
    full_day(env, EXACT_FILLS, EXACT_DEALS)
    result = strat(run(env))
    assert result["status"] == "PASS", result["reasons"]
    assert (result["broker_deal_count"], result["telemetry_deal_count"], result["matched_count"]) == (2, 2, 2)
    assert result["entry_fills"] == {"broker": 1, "telemetry": 1, "matched": 1}
    assert result["exit_fills"] == {"broker": 1, "telemetry": 1, "matched": 1}
    assert result["positions"] == {"broker": [7], "telemetry": [7]}
    assert result["telemetry_gaps"] == [] and result["heartbeat_count"] > 1400


def test_other_strategies_and_manual_trades_are_not_ours(env):
    full_day(env, EXACT_FILLS, EXACT_DEALS + [broker_deal(99, magic=0), broker_deal(98, magic=123)])
    assert strat(run(env))["status"] == "PASS"


def test_missing_telemetry_event_fails_and_records_a_correction_without_touching_raw(env):
    full_day(env, EXACT_FILLS[:1], EXACT_DEALS)
    raw_before = env["db"].execute("SELECT COUNT(*) FROM events").fetchone()[0]
    result = strat(run(env))
    assert result["status"] == "FAIL" and [m["deal_id"] for m in result["missing_from_telemetry"]] == [12]
    correction = env["db"].execute("SELECT kind, item_key, telemetry_view, broker_view FROM corrections").fetchall()
    assert correction == [("missing_from_telemetry", "12", None, json.dumps(EXACT_DEALS[1], sort_keys=True))]
    assert env["db"].execute("SELECT COUNT(*) FROM events WHERE deal_id=12").fetchone()[0] == 0   # not patched in
    assert env["db"].execute("SELECT COUNT(*) FROM events").fetchone()[0] >= raw_before


def test_missing_broker_event_fails(env):
    full_day(env, EXACT_FILLS + [dict(deal_id=13, entry="in", at=f"{DAY}T15:00:00.000Z")], EXACT_DEALS)
    result = strat(run(env))
    assert result["status"] == "FAIL" and [u["deal_id"] for u in result["unmatched_telemetry"]] == [13]


@pytest.mark.parametrize("change, bucket", [
    ({"price": 65000.75}, "price_mismatches"),
    ({"volume": 0.02}, "volume_mismatches"),
    ({"at": f"{DAY}T10:00:01.250Z"}, "timestamp_mismatches"),
    ({"side": "sell"}, "field_mismatches"),
])
def test_field_mismatches_fail(env, change, bucket):
    fills = [dict(EXACT_FILLS[0], **change), EXACT_FILLS[1]]
    full_day(env, fills, EXACT_DEALS)
    result = strat(run(env))
    assert result["status"] == "FAIL" and len(result[bucket]) == 1


def test_price_within_half_a_point_matches(env):
    fills = [dict(EXACT_FILLS[0], price=65000.504), EXACT_FILLS[1]]
    full_day(env, fills, EXACT_DEALS)
    assert strat(run(env))["status"] == "PASS"


def test_exit_reason_is_compared_as_a_fact(env):
    fills = [EXACT_FILLS[0], dict(EXACT_FILLS[1], reason="sl")]
    full_day(env, fills, EXACT_DEALS)
    result = strat(run(env))
    assert [m["field"] for m in result["field_mismatches"]] == ["exit_reason"]


def test_duplicate_telemetry_is_detected(env):
    full_day(env, EXACT_FILLS + [EXACT_FILLS[0]], EXACT_DEALS)
    result = strat(run(env))
    assert result["status"] == "FAIL" and [d["deal_id"] for d in result["duplicate_telemetry"]] == [11]
    assert result["matched_count"] == 2                                   # counted once, not twice


def test_missing_orders_are_reported(env):
    order = {"order_id": 21, "symbol": "BTCUSDm", "magic_number": MAGIC, "setup_utc": f"{DAY}T10:00:00.000Z",
             "state": "filled"}
    full_day(env, EXACT_FILLS, EXACT_DEALS, [order])
    result = strat(run(env))
    assert result["status"] == "FAIL" and result["broker_order_count"] == 1 and result["missing_orders"]


def test_heartbeat_gap_fails_until_explained_then_passes_with_both_views_kept(env):
    full_day(env, EXACT_FILLS, EXACT_DEALS, gap=(utc(f"{DAY}T02:00:00Z"), utc(f"{DAY}T02:10:00Z")))
    result = strat(run(env))
    assert result["status"] == "FAIL" and len(result["telemetry_gaps"]) == 1
    gap = result["telemetry_gaps"][0]
    assert gap["seconds"] >= 600 and gap["writer_id"] == "observer.btc_setup_a"
    key = f"{gap['writer_id']}@{gap['from_utc']}"
    store.add_annotation(env["db"], day=DAY, strategy_id="btc_setup_a", kind="telemetry_gaps", item_key=key,
                         explanation="planned VPS reboot for Windows update", author="Rahul")
    again = strat(run(env))
    assert again["status"] == "PASS" and again["explained"][0]["explanation"].startswith("planned VPS reboot")
    assert again["telemetry_gaps"][0]["explained"] is True                # the gap itself is still reported
    assert env["db"].execute("SELECT COUNT(*) FROM corrections WHERE kind='telemetry_gaps'").fetchone()[0] == 1


def test_no_telemetry_at_all_is_a_full_day_gap(env):
    write_export(env["broker"], DAY, EXACT_DEALS)
    result = strat(run(env))
    assert result["status"] == "FAIL" and result["telemetry_gaps"][0]["seconds"] == 86400
    assert len(result["missing_from_telemetry"]) == 2


def test_incomplete_when_day_unfinished_or_broker_export_missing(env):
    full_day(env, EXACT_FILLS, EXACT_DEALS)
    assert strat(run(env, now=utc(f"{DAY}T18:00:00Z")))["status"] == "INCOMPLETE"
    (env["broker"] / ("0" * 16) / f"{DAY}.json").unlink()
    result = strat(run(env))
    assert result["status"] == "INCOMPLETE" and "export" in result["reasons"][0]
    folder = env["broker"] / ("0" * 16)
    (folder / f"{DAY}.json").write_text(json.dumps({"day": DAY, "deals": [], "complete": False}))
    assert strat(run(env))["status"] == "INCOMPLETE"


def test_reconciliation_rerun_is_byte_identical_and_adds_no_corrections(env):
    full_day(env, EXACT_FILLS[:1], EXACT_DEALS)
    out = env["tmp"] / "reconciliation"
    first = reconcile.write_result(run(env), out, now=utc("2026-10-06T01:00:00Z")).read_bytes()
    corrections = env["db"].execute("SELECT COUNT(*) FROM corrections").fetchone()[0]
    second = reconcile.write_result(run(env), out, now=utc("2026-10-09T01:00:00Z")).read_bytes()
    assert first == second
    assert env["db"].execute("SELECT COUNT(*) FROM corrections").fetchone()[0] == corrections
    runs = [json.loads(line) for line in (out / "runs.jsonl").read_text().splitlines()]
    assert [r["late"] for r in runs] == [False, True] and runs[0]["result_sha256"] == runs[1]["result_sha256"]


# ---- the real MT5 writer's bytes -----------------------------------------------------------------------------------------

def test_genuine_mql5_observer_output_parses_and_matches_its_broker_export(env):
    """60 lines written by ZoneflowTelemetryObserver in the MT5 Strategy Tester (account_ref blanked, CRC resealed)
    and that run's own daily broker export: every fill in the sample matches the broker exactly."""
    lines = (FIXTURES / "mql5_observer_tester_sample.jsonl").read_bytes().splitlines()
    events = [decode(line) for line in lines]
    assert events[0]["event_type"] == "ea_started" and events[0]["runtime"]["program"] == "ZoneflowTelemetryObserver"
    export = json.loads((FIXTURES / "mql5_broker_export_sample.json").read_text())
    deals = {d["deal_id"]: d for d in export["deals"]}
    fills = [e for e in events if e["event_type"] in ("position_opened", "position_closed")]
    assert fills
    for event in fills:
        broker = deals[event["deal_id"]]
        assert (event["fill_price"], event["filled_volume"], event["broker_utc"], event["direction"],
                event["deal_entry"]) == (broker["price"], broker["volume"], broker["broker_utc"], broker["type"],
                                         broker["entry"])
        if event["event_type"] == "position_closed":
            assert event["exit_reason"] == broker["reason"]
    assert all(e["capture_mode"] == "realtime" and e["account_ref"] == "0" * 16 for e in events)


# ---- tracker -----------------------------------------------------------------------------------------------------------

def _result(out: Path, day: str, status: str):
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{day}.json").write_text(json.dumps({"date": day, "status": status, "strategies": [], "reasons": []}))


def test_tracker_counts_consecutive_passes_and_shows_missed_days(tmp_path):
    out = tmp_path / "reconciliation"
    start = date(2026, 10, 1)
    validation = {"validation_start": start.isoformat(), "target_days": 14}
    for i in range(3):
        _result(out, (start + timedelta(days=i)).isoformat(), "PASS")
    summary = tracker.summarise(out, validation, now=utc("2026-10-04T08:00:00Z"))
    assert [d["status"] for d in summary["days"]] == ["PASS"] * 3 and summary["qualifying_streak"] == 3
    assert summary["target_completion_date"] == "2026-10-14" and summary["status"] == "COLLECTING"
    text = tracker.render(summary)
    assert "Day 1   2026-10-01  PASS" in text and "Qualifying: 3 / 14" in text
    # day 4 never reconciled: MISSED, and the run restarts
    _result(out, "2026-10-05", "PASS")
    summary = tracker.summarise(out, validation, now=utc("2026-10-06T08:00:00Z"))
    assert [d["status"] for d in summary["days"]][3:] == ["PENDING", "PASS"]   # day 4 may still be caught up
    summary = tracker.summarise(out, validation, now=utc("2026-10-07T08:00:00Z"))
    assert [d["status"] for d in summary["days"]][3:] == ["MISSED", "PASS", "PENDING"]
    assert summary["qualifying_streak"] == 1 and summary["longest_streak"] == 3
    assert "MISSED" in tracker.render(summary)


def test_tracker_is_done_only_after_fourteen_consecutive_passes(tmp_path):
    out = tmp_path / "reconciliation"
    start = date(2026, 10, 1)
    validation = {"validation_start": start.isoformat(), "target_days": 14}
    for i in range(14):
        _result(out, (start + timedelta(days=i)).isoformat(), "FAIL" if i == 5 else "PASS")
    summary = tracker.summarise(out, validation, now=utc("2026-10-15T08:00:00Z"))
    assert summary["qualifying_streak"] == 8 and summary["status"] == "COLLECTING"
    for i in range(14, 20):
        _result(out, (start + timedelta(days=i)).isoformat(), "PASS")
    summary = tracker.summarise(out, validation, now=utc("2026-10-21T08:00:00Z"))
    assert summary["qualifying_streak"] == 14 and summary["status"] == "DONE"


def test_tracker_flags_an_overdue_daily_job_and_late_catch_up(tmp_path):
    out = tmp_path / "reconciliation"
    _result(out, "2026-10-01", "PASS")
    (out / "runs.jsonl").write_text(json.dumps({"run_utc": "2026-10-04T01:00:00Z", "date": "2026-10-01",
                                                "status": "PASS", "late": True}) + "\n")
    summary = tracker.summarise(out, {"validation_start": "2026-10-01"}, now=utc("2026-10-06T08:00:00Z"))
    assert summary["daily_job_overdue"] and summary["days"][0]["late"]
    assert "OVERDUE" in tracker.render(summary) and "reconciled late" in tracker.render(summary)
    assert tracker.summarise(out, {"validation_start": None})["status"] == "NOT STARTED"


def test_validation_start_is_recorded_once(tmp_path):
    path = tmp_path / "validation.json"
    tracker.start_validation(path, date(2026, 10, 1))
    with pytest.raises(ValueError):
        tracker.start_validation(path, date(2026, 10, 2))


# ---- heartbeat / watchdog ------------------------------------------------------------------------------------------------

def test_watchdog_reports_ok_stale_disconnected_and_stopped_without_acting(tmp_path):
    spool = tmp_path / "spool"
    clock = Clock(utc(f"{DAY}T10:00:00Z"))
    writer = observer(spool, clock)
    writer.emit("heartbeat", runtime={"status": "running", "terminal_connected": True, "trade_allowed": True})
    assert watchdog.check(spool, now=clock.now + timedelta(seconds=30))["writers"][0]["state"] == "OK"
    report = watchdog.check(spool, now=clock.now + timedelta(minutes=10))
    assert report["writers"][0]["state"] == "STALE" and not report["ok"]
    writer.emit("heartbeat", runtime={"status": "running_disconnected", "terminal_connected": False})
    assert watchdog.check(spool, now=clock.now)["writers"][0]["state"] == "MT5 DISCONNECTED"
    writer.emit("ea_stopped", runtime={"status": "stopped"})
    assert watchdog.check(spool, now=clock.now)["writers"][0]["state"] == "STOPPED"
    changes = watchdog.record(watchdog.check(spool, now=clock.now), tmp_path / "wd")
    assert changes and (tmp_path / "wd" / "status.json").exists()
    assert watchdog.record(watchdog.check(spool, now=clock.now), tmp_path / "wd") == []   # only changes logged
    source = (ROOT / "services" / "telemetry" / "watchdog.py").read_text()
    assert not re.search(r"\b(order_send|close|flatten|OrderSend)\s*\(", source.split('"""', 2)[2])


def test_watchdog_without_any_spool_is_not_ok(tmp_path):
    assert not watchdog.check(tmp_path / "missing")["ok"]


# ---- safety: nothing here can trade; strategy EAs untouched; no secrets ------------------------------------------------

def _code(path: Path) -> str:
    text = re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def test_telemetry_mql_cannot_trade():
    forbidden = re.compile(r"\b(OrderSend|OrderSendAsync|CTrade|PositionClose|PositionModify|OrderModify|OrderDelete|"
                           r"OrderCloseBy|PositionOpen|Buy|Sell|BuyStop|SellStop|BuyLimit|SellLimit)\s*\(|Trade\\Trade\.mqh")
    for path in MQL.glob("*.mq*"):
        assert not forbidden.search(_code(path)), path.name


def test_trading_ea_sources_are_byte_identical_to_the_audited_versions():
    """Telemetry V1 instruments no strategy EA: the audited sources are unchanged (hashes pinned 2026-09-30)."""
    pinned = {
        "mt5/BTC_Setup_A_V1.mq5": "08818f62a2eaacb964ea60ff589b31efa4621079415f4dd1ce53e0857b4cd2d3",
        "mt5/BTC_V3_Core_V1.mq5": "163bb2d661d486ae9971a75d5fc3993bee9b4cd5d1b3604226f927f55d9e366b",
        "mt5/BTC_V3_Stage4_Demo.mqh": "c86daa46ff9f65e9df0ae7dbdd6aef7b3d9beee84eb1ccc09f7a122d227e92b9",
        "mt5/BTC_V3_Stage4_CompileCheck.mq5": "dcb9e281ce13ba74da572b9b133599e9bbcb3df3dc49eb61b32ed3ebaa49ec23",
    }
    for name, digest in pinned.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name


def test_telemetry_never_writes_the_account_login():
    header = _code(MQL / "ZoneflowTelemetry.mqh")
    uses = [m.start() for m in re.finditer(r"ACCOUNT_LOGIN", header)]
    hashing = header.index("string ZfAccountRef()")
    assert uses and all(hashing < u < header.index("CryptEncode", hashing) for u in uses)
    for path in list(MQL.glob("*.mq*")) + list((ROOT / "services" / "telemetry").glob("*.py")):
        if path.name != "ZoneflowTelemetry.mqh":
            assert "ACCOUNT_LOGIN" not in _code(path) if path.suffix != ".py" else "ACCOUNT_LOGIN" not in path.read_text()
    for fixture in FIXTURES.iterdir():
        text = fixture.read_text()
        assert not re.search(r'"account_ref":\s*"(?!0{16})', text)
        assert not re.search(r"\b\d{8,10}\b(?=.*login)", text)


def test_telemetry_data_stays_out_of_git():
    for name in ("data/telemetry/store/telemetry.sqlite3", "data/telemetry/reconciliation/2026-10-01.json"):
        assert subprocess.run(["git", "check-ignore", "-q", name], cwd=ROOT).returncode == 0, name


def test_daily_command_runs_end_to_end(env, monkeypatch, capsys):
    from services.telemetry import __main__ as cli
    full_day(env, EXACT_FILLS, EXACT_DEALS)
    root = env["tmp"] / "root"
    root.mkdir()
    (root / "strategies.json").write_text(json.dumps([STRATEGY]))
    tracker.start_validation(root / "validation.json", date.fromisoformat(DAY))
    monkeypatch.setenv("ZONEFLOW_TELEMETRY_ROOT", str(root))
    monkeypatch.setenv("ZONEFLOW_TELEMETRY_SPOOL", str(env["tmp"]))
    assert cli.main(["daily", "--now", "2026-10-06T06:00:00Z"]) == 0
    out = capsys.readouterr().out
    assert f"{DAY}: PASS" in out and "Qualifying:" in out
    assert (root / "reconciliation" / f"{DAY}.json").exists() and (root / "reconciliation" / "SUMMARY.md").exists()
    assert cli.main(["daily", "--now", "2026-10-07T06:00:00Z"]) == 0      # rerun: nothing recomputed
    runs = [json.loads(line) for line in (root / "reconciliation" / "runs.jsonl").read_text().splitlines()]
    assert [r["date"] for r in runs] == [DAY, "2026-10-06"]                # DAY final: not recomputed
    assert "PENDING" in capsys.readouterr().out                            # 10-06 export not there yet
    assert crc_of(b"") == "00000000" and CRC_MARKER


def test_diagnostics_panel_is_read_only_and_renders(env, monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest

    full_day(env, EXACT_FILLS, EXACT_DEALS)
    root = tmp_path / "root"
    monkeypatch.setenv("ZONEFLOW_TELEMETRY_ROOT", str(root))
    monkeypatch.setenv("ZONEFLOW_TELEMETRY_SPOOL", str(env["tmp"]))
    app = AppTest.from_string("from ui.telemetry_diagnostics import render_telemetry_diagnostics\n"
                              "render_telemetry_diagnostics()\n", default_timeout=60)
    app.run()
    assert not app.exception
    assert app.subheader[0].value.startswith("Live algo telemetry")
    assert not root.exists()                                               # viewing creates nothing
    source = (ROOT / "ui" / "telemetry_diagnostics.py").read_text()
    assert "mode=ro" in source and "st.button" not in source
