"""Telemetry V1 commands (read-only towards MT5; nothing here can trade).

    python -m services.telemetry daily                     ingest + reconcile every finished day + tracker + watchdog
    python -m services.telemetry ingest                    copy new spool lines into the store
    python -m services.telemetry reconcile --date YYYY-MM-DD   (re)reconcile one day - idempotent
    python -m services.telemetry tracker                   print the 14-day validation progress
    python -m services.telemetry watchdog                  heartbeat / MT5 connection status (exit 1 if not OK)
    python -m services.telemetry start-validation --date YYYY-MM-DD
    python -m services.telemetry explain --date D --strategy S --kind K --key KEY --text "why" [--author NAME]

Folders: see services/telemetry/paths.py (ZONEFLOW_TELEMETRY_ROOT, TV_MT5_COMMON_FILES / ZONEFLOW_TELEMETRY_SPOOL).
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
import sys

from . import paths, reconcile, store, tracker, watchdog


def _load_env_file() -> None:
    """Honour ZONEFLOW_ENV_FILE like the other Zoneflow services (only fills variables not already set)."""
    from services.auth.config import environment
    for key, value in environment().items():
        os.environ.setdefault(key, value)


def cmd_ingest(_args) -> int:
    db = store.connect(paths.store_path())
    report = store.ingest(paths.spool_root(), db)
    print(json.dumps(report.__dict__, indent=2))
    return 0 if not report.problems and not report.conflicts else 1


def _reconcile(db, day: str, now: datetime) -> dict:
    strategies = reconcile.load_strategies(paths.telemetry_root() / "strategies.json")
    result = reconcile.reconcile_day(db, day, strategies, paths.broker_root(), now=now)
    reconcile.write_result(result, paths.reconciliation_dir(), now=now)
    return result


def cmd_reconcile(args) -> int:
    db = store.connect(paths.store_path())
    store.ingest(paths.spool_root(), db)
    result = _reconcile(db, args.date, datetime.now(timezone.utc))
    for item in result["strategies"] or [result]:
        print(f"{result['date']}  {item.get('strategy', '-'):<24} {item['status']}  {'; '.join(item['reasons'])}")
    return 0 if result["status"] == "PASS" else 1


def cmd_tracker(_args) -> int:
    summary = tracker.summarise(paths.reconciliation_dir(), tracker.load_validation(paths.telemetry_root() / "validation.json"))
    tracker.write_summary(paths.reconciliation_dir(), summary)
    print(tracker.render(summary), end="")
    return 0


def cmd_watchdog(_args) -> int:
    report = watchdog.check(paths.spool_root())
    watchdog.record(report, paths.watchdog_dir())
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


def cmd_daily(args) -> int:
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
    db = store.connect(paths.store_path())
    ingest = store.ingest(paths.spool_root(), db, today=now)
    validation = tracker.load_validation(paths.telemetry_root() / "validation.json")
    start = (date.fromisoformat(validation["validation_start"]) if validation.get("validation_start")
             else (now - timedelta(days=1)).date())       # before validation starts: dry-run yesterday only
    out = paths.reconciliation_dir()
    for day in reconcile.completed_days(start, now):
        existing = out / f"{day}.json"
        if existing.exists() and json.loads(existing.read_text())["status"] != "INCOMPLETE":
            continue                                     # final results are not recomputed by the schedule
        result = _reconcile(db, day, now)
        print(f"{day}: {result['status']}")
    summary = tracker.summarise(out, validation, now)
    tracker.write_summary(out, summary)
    print(tracker.render(summary), end="")
    report = watchdog.check(paths.spool_root(), now)
    watchdog.record(report, paths.watchdog_dir())
    print(f"ingested {ingest.new_events} new events, {ingest.defects} defects, {ingest.conflicts} conflicts; "
          f"watchdog {'OK' if report['ok'] else 'NOT OK: ' + '; '.join(report['problems'])}")
    return 0


def cmd_start(args) -> int:
    config = tracker.start_validation(paths.telemetry_root() / "validation.json", date.fromisoformat(args.date))
    print(f"live validation starts {config['validation_start']} (target {config['target_days']} consecutive PASS days)")
    return 0


def cmd_explain(args) -> int:
    db = store.connect(paths.store_path())
    annotation_id = store.add_annotation(db, day=args.date, strategy_id=args.strategy, kind=args.kind,
                                         item_key=args.key, explanation=args.text, author=args.author)
    print(f"explanation {annotation_id} recorded; rerun: python -m services.telemetry reconcile --date {args.date}")
    return 0


def main(argv=None) -> int:
    _load_env_file()
    parser = argparse.ArgumentParser(prog="python -m services.telemetry", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("daily")
    p.add_argument("--now", help=argparse.SUPPRESS)          # tests / replay only: pretend the clock reads this UTC time
    p.set_defaults(func=cmd_daily)
    sub.add_parser("ingest").set_defaults(func=cmd_ingest)
    p = sub.add_parser("reconcile")
    p.add_argument("--date", required=True)
    p.set_defaults(func=cmd_reconcile)
    sub.add_parser("tracker").set_defaults(func=cmd_tracker)
    sub.add_parser("watchdog").set_defaults(func=cmd_watchdog)
    p = sub.add_parser("start-validation")
    p.add_argument("--date", required=True)
    p.set_defaults(func=cmd_start)
    p = sub.add_parser("explain")
    for name in ("date", "strategy", "kind", "key", "text"):
        p.add_argument(f"--{name}", required=True)
    p.add_argument("--author", default="Rahul")
    p.set_defaults(func=cmd_explain)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
