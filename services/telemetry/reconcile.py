"""Daily broker reconciliation: telemetry vs MT5's own order/deal history, per strategy, per UTC day.

MT5 history is the authority. Nothing here edits telemetry: every discrepancy becomes a separate correction record
(what telemetry captured next to what the broker reports), and a discrepancy only stops counting against the day when
an explanation (an append-only annotation) names it exactly.

Status per strategy and day:
    INCOMPLETE  the day is not over yet, the strategy is not configured, or the broker export for the day is missing
    FAIL        at least one unexplained discrepancy (missing/extra/duplicate fills, price/volume/time/side/reason
                mismatches, missing orders, heartbeat gaps, spool defects or id conflicts)
    PASS        counts and every compared field agree, and nothing is unexplained

The result is deterministic: rerunning over the same inputs produces the same bytes (run times go to runs.jsonl).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from . import store
from .schema import DEAL_EVENTS, ORDER_EVENTS, format_ts, parse_ts

RESULT_VERSION = 1
DAY_GRACE = timedelta(minutes=30)          # a day is reconciled only after it has ended plus this margin
MAX_HEARTBEAT_GAP_S = 180                  # heartbeats every 60 s; three missed in a row is a gap
TIME_TOLERANCE_MS = 0                      # broker deal time comes from the same DEAL_TIME_MSC on both sides
VOLUME_TOLERANCE = 1e-8


# ---- configuration --------------------------------------------------------------------------------------------------

def load_strategies(path: Path) -> list[dict]:
    """strategies.json: [{"strategy_id": ..., "magic_numbers": [...], "symbols": [...] (empty = any)}, ...]"""
    if not path.exists():
        return []
    items = json.loads(path.read_text(encoding="utf-8"))
    for item in items:
        if not item.get("strategy_id") or not isinstance(item.get("magic_numbers"), list):
            raise ValueError(f"{path}: every strategy needs strategy_id and magic_numbers")
    return items


# ---- broker history export ------------------------------------------------------------------------------------------

def load_broker_day(broker_root: Path, day: str) -> tuple[dict | None, str | None]:
    """The observer's export for one UTC day (any account folder). (export, problem)"""
    found = sorted(broker_root.glob(f"*/{day}.json")) if broker_root.exists() else []
    if not found:
        return None, f"no MT5 broker history export for {day}"
    if len(found) > 1:
        return None, f"more than one account exported {day}: {[p.parent.name for p in found]}"
    try:
        export = json.loads(found[0].read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"unreadable broker export {found[0].name}: {exc}"
    if export.get("complete") is not True or export.get("day") != day:
        return None, f"broker export for {day} is incomplete"
    return export, None


# ---- helpers --------------------------------------------------------------------------------------------------------

def _ms(ts: str | None) -> int | None:
    return None if ts is None else int(parse_ts(ts).timestamp() * 1000)


def _price_equal(a, b, digits) -> bool:
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= 0.5 * 10 ** -(int(digits) if digits is not None else 8)


def _deal_view(event: dict) -> dict:
    keep = ("telemetry_event_id", "writer_id", "event_type", "deal_id", "order_id", "position_id", "symbol",
            "magic_number", "direction", "deal_entry", "fill_price", "filled_volume", "broker_utc", "exit_reason",
            "local_capture_utc")
    return {k: event.get(k) for k in keep}


def heartbeat_gaps(beats: dict[str, list[datetime]], day_start: datetime, day_end: datetime,
                   max_gap_s: int = MAX_HEARTBEAT_GAP_S) -> list[dict]:
    """Stretches of the day with no sign of life from a writer (heartbeat, start or stop)."""
    gaps = []
    for writer, times in sorted(beats.items()):
        points = sorted(t for t in times)
        edges = [day_start] + [t for t in points if day_start < t < day_end] + [day_end]
        before = [t for t in points if t <= day_start]
        after = [t for t in points if t >= day_end]
        edges[0] = before[-1] if before else day_start
        edges[-1] = after[0] if after else day_end
        for a, b in zip(edges, edges[1:]):
            if (b - a).total_seconds() > max_gap_s:
                start, end = max(a, day_start), min(b, day_end)
                if end > start:
                    gaps.append({"writer_id": writer, "from_utc": format_ts(start, ms=False),
                                 "to_utc": format_ts(end, ms=False), "seconds": int((end - start).total_seconds())})
    return gaps


# ---- the comparison -------------------------------------------------------------------------------------------------

def reconcile_strategy(db, strategy: dict, day: str, export: dict | None, export_problem: str | None,
                       now: datetime) -> dict:
    sid = strategy["strategy_id"]
    magics = set(strategy["magic_numbers"])
    symbols = set(strategy.get("symbols") or [])
    day_start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    result = {"date": day, "strategy": sid, "status": None, "reasons": [],
              "broker_deal_count": 0, "telemetry_deal_count": 0, "matched_count": 0,
              "broker_order_count": 0, "telemetry_order_count": 0,
              "entry_fills": {"broker": 0, "telemetry": 0, "matched": 0},
              "exit_fills": {"broker": 0, "telemetry": 0, "matched": 0},
              "positions": {"broker": [], "telemetry": []},
              "missing_from_telemetry": [], "unmatched_telemetry": [], "duplicate_telemetry": [],
              "price_mismatches": [], "volume_mismatches": [], "timestamp_mismatches": [],
              "field_mismatches": [], "missing_orders": [], "telemetry_gaps": [], "spool_defects": [],
              "id_conflicts": [], "heartbeat_count": 0, "capture_latency_ms": None, "explained": []}
    if now < day_end + DAY_GRACE:
        result["status"], result["reasons"] = "INCOMPLETE", [f"{day} has not finished (UTC) yet"]
        return result

    # --- telemetry side ---
    neighbours = [(day_start + timedelta(days=d)).date().isoformat() for d in (-1, 0, 1)]
    around = store.events(db, strategy_id=sid, days=neighbours)
    todays = [e for e in around if store.event_day(e) == day]
    deal_events = [e for e in todays if e["event_type"] in DEAL_EVENTS and e.get("capture_mode") == "realtime"]
    order_events = [e for e in todays if e["event_type"] in ORDER_EVENTS and e.get("capture_mode") == "realtime"]
    beats: dict[str, list[datetime]] = {}
    for e in around:
        if e["event_type"] in ("heartbeat", "ea_started", "ea_stopped"):
            beats.setdefault(e["writer_id"], []).append(parse_ts(e["local_capture_utc"]))
    result["heartbeat_count"] = sum(1 for e in todays if e["event_type"] == "heartbeat")
    result["telemetry_deal_count"] = len({e.get("deal_id") for e in deal_events})
    result["telemetry_order_count"] = len({e.get("order_id") for e in order_events
                                           if e["event_type"] == "order_accepted"})

    if export is None:
        result["status"], result["reasons"] = "INCOMPLETE", [export_problem or "no broker export"]
        return result

    # --- broker side ---
    def mine(item):
        return item.get("magic_number") in magics and (not symbols or item.get("symbol") in symbols)
    deals = {d["deal_id"]: d for d in export.get("deals", []) if mine(d)}
    orders = {o["order_id"]: o for o in export.get("orders", []) if mine(o) and (o.get("setup_utc") or "")[:10] == day}
    result["broker_deal_count"], result["broker_order_count"] = len(deals), len(orders)
    for d in deals.values():
        result["entry_fills"]["broker"] += d.get("entry") in ("in", "inout")
        result["exit_fills"]["broker"] += d.get("entry") in ("out", "out_by", "inout")
    for e in deal_events:
        result["entry_fills"]["telemetry"] += e["event_type"] == "position_opened"
        result["exit_fills"]["telemetry"] += e["event_type"] == "position_closed"
    result["positions"]["broker"] = sorted({d["position_id"] for d in deals.values() if d.get("position_id")})
    result["positions"]["telemetry"] = sorted({e["position_id"] for e in deal_events if e.get("position_id")})

    by_deal: dict[int, list[dict]] = {}
    for e in deal_events:
        by_deal.setdefault(e.get("deal_id"), []).append(e)
    all_deals_any_magic = {d["deal_id"]: d for d in export.get("deals", [])}
    latencies = []
    for deal_id, items in sorted(by_deal.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)):
        if len(items) > 1:
            result["duplicate_telemetry"].append({"deal_id": deal_id, "events": [_deal_view(e) for e in items]})
        event = items[0]
        broker = deals.get(deal_id)
        if broker is None:
            elsewhere = all_deals_any_magic.get(deal_id)
            result["unmatched_telemetry"].append({"deal_id": deal_id, "telemetry": _deal_view(event),
                                                  "broker_other_magic_or_symbol": elsewhere})
            continue
        result["matched_count"] += 1
        opened = event["event_type"] == "position_opened"
        if broker.get("entry") in ("in", "inout") and opened:
            result["entry_fills"]["matched"] += 1
        if broker.get("entry") in ("out", "out_by", "inout") and not opened:
            result["exit_fills"]["matched"] += 1
        if not _price_equal(event.get("fill_price"), broker.get("price"), broker.get("digits")):
            result["price_mismatches"].append({"deal_id": deal_id, "telemetry": event.get("fill_price"),
                                               "broker": broker.get("price")})
        if event.get("filled_volume") is None or abs(float(event["filled_volume"]) - float(broker["volume"])) > VOLUME_TOLERANCE:
            result["volume_mismatches"].append({"deal_id": deal_id, "telemetry": event.get("filled_volume"),
                                                "broker": broker.get("volume")})
        t_ms, b_ms = _ms(event.get("broker_utc")), _ms(broker.get("broker_utc"))
        if t_ms is None or b_ms is None or abs(t_ms - b_ms) > TIME_TOLERANCE_MS:
            result["timestamp_mismatches"].append({"deal_id": deal_id, "telemetry": event.get("broker_utc"),
                                                   "broker": broker.get("broker_utc")})
        elif event.get("local_capture_utc"):
            latencies.append(_ms(event["local_capture_utc"]) - b_ms)
        expected_type = {"in": "position_opened", "out": "position_closed", "out_by": "position_closed"}.get(broker.get("entry"))
        checks = {"symbol": (event.get("symbol"), broker.get("symbol")),
                  "magic_number": (event.get("magic_number"), broker.get("magic_number")),
                  "position_id": (event.get("position_id"), broker.get("position_id")),
                  "order_id": (event.get("order_id"), broker.get("order_id")),
                  "direction": (event.get("direction"), broker.get("type")),
                  "deal_entry": (event.get("deal_entry"), broker.get("entry")),
                  "event_type": (event["event_type"], expected_type or event["event_type"])}
        if not opened:                        # the factual exit reason (MT5 DEAL_REASON) of a closing fill
            checks["exit_reason"] = (event.get("exit_reason"), broker.get("reason"))
        for name, (t_value, b_value) in checks.items():
            if t_value != b_value:
                result["field_mismatches"].append({"deal_id": deal_id, "field": name, "telemetry": t_value,
                                                   "broker": b_value})
    for deal_id, broker in sorted(deals.items()):
        if deal_id not in by_deal:
            result["missing_from_telemetry"].append({"deal_id": deal_id, "broker": broker})
    seen_orders = {e.get("order_id") for e in order_events}
    for order_id, order in sorted(orders.items()):
        if order_id not in seen_orders:
            result["missing_orders"].append({"order_id": order_id, "broker": order})
    if latencies:
        latencies.sort()
        result["capture_latency_ms"] = {"min": latencies[0], "median": latencies[len(latencies) // 2],
                                        "max": latencies[-1]}

    # --- liveness and spool integrity ---
    result["telemetry_gaps"] = heartbeat_gaps(beats, day_start, day_end)
    if not beats:
        result["telemetry_gaps"] = [{"writer_id": None, "from_utc": format_ts(day_start, ms=False),
                                     "to_utc": format_ts(day_end, ms=False), "seconds": 86400}]
    writers = sorted(beats) or sorted({e["writer_id"] for e in todays})
    for writer in writers:
        for source, offset, reason in db.execute(
                "SELECT source_file, source_offset, reason FROM defects WHERE source_file=? ORDER BY source_offset",
                (f"{writer}/{day}.jsonl",)):
            result["spool_defects"].append({"source_file": source, "offset": offset, "reason": reason})
    for (event_id,) in db.execute("SELECT DISTINCT event_id FROM conflicts WHERE event_id IN "
                                  "(SELECT event_id FROM events WHERE strategy_id=? AND day=?) ORDER BY event_id",
                                  (sid, day)):
        result["id_conflicts"].append({"event_id": event_id})

    return _judge(db, result)


# each discrepancy list -> (annotation kind, how to name one item)
_KINDS = {
    "missing_from_telemetry": lambda i: str(i["deal_id"]),
    "unmatched_telemetry": lambda i: str(i["deal_id"]),
    "duplicate_telemetry": lambda i: str(i["deal_id"]),
    "price_mismatches": lambda i: str(i["deal_id"]),
    "volume_mismatches": lambda i: str(i["deal_id"]),
    "timestamp_mismatches": lambda i: str(i["deal_id"]),
    "field_mismatches": lambda i: f"{i['deal_id']}:{i['field']}",
    "missing_orders": lambda i: str(i["order_id"]),
    "telemetry_gaps": lambda i: f"{i['writer_id']}@{i['from_utc']}",
    "spool_defects": lambda i: f"{i['source_file']}@{i['offset']}",
    "id_conflicts": lambda i: i["event_id"],
}


def _judge(db, result: dict) -> dict:
    notes = store.annotations(db, result["date"], result["strategy"])
    unexplained = 0
    for kind, key_of in _KINDS.items():
        for item in result[kind]:
            key = key_of(item)
            explanation = notes.get((kind, key))
            item["explained"] = explanation is not None
            if explanation is not None:
                result["explained"].append({"kind": kind, "key": key, "explanation": explanation})
            else:
                unexplained += 1
            store.add_correction(db, day=result["date"], strategy_id=result["strategy"], kind=kind, item_key=key,
                                 telemetry_view=item.get("telemetry") or item.get("events"),
                                 broker_view=item.get("broker"))
    db.commit()
    if unexplained:
        counts = {k: sum(1 for i in result[k] if not i["explained"]) for k in _KINDS}
        result["status"] = "FAIL"
        result["reasons"] = [f"{n} unexplained {k.replace('_', ' ')}" for k, n in counts.items() if n]
    else:
        result["status"] = "PASS"
    return result


# ---- daily files --------------------------------------------------------------------------------------------------

def reconcile_day(db, day: str, strategies: list[dict], broker_root: Path, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    export, problem = load_broker_day(broker_root, day)
    results = [reconcile_strategy(db, s, day, export, problem, now) for s in sorted(strategies, key=lambda s: s["strategy_id"])]
    order = {"FAIL": 2, "INCOMPLETE": 1, "PASS": 0}
    status = max((r["status"] for r in results), key=order.get) if results else "INCOMPLETE"
    return {"result_version": RESULT_VERSION, "date": day, "status": status,
            "broker_export": None if export is None else {k: export.get(k) for k in
                                                          ("account_ref", "account_server", "account_environment",
                                                           "broker", "server_utc_offset_s", "exported_utc")},
            "strategies": results if strategies else [],
            "reasons": [] if strategies else ["no strategies configured (strategies.json)"]}


def write_result(result: dict, out_dir: Path, *, now: datetime | None = None) -> Path:
    """Write <day>.json (deterministic) and append the run to runs.jsonl (with whether it ran late)."""
    now = now or datetime.now(timezone.utc)
    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    path = out_dir / f"{result['date']}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
    due = datetime.fromisoformat(result["date"]).replace(tzinfo=timezone.utc) + timedelta(days=2)
    run = {"run_utc": format_ts(now, ms=False), "date": result["date"], "status": result["status"],
           "result_sha256": hashlib.sha256(text.encode()).hexdigest(), "late": now > due}
    with open(out_dir / "runs.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(run, sort_keys=True) + "\n")
    return path


def completed_days(start: date, now: datetime) -> list[str]:
    last = (now - DAY_GRACE).date() - timedelta(days=1)
    days, current = [], start
    while current <= last:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days
