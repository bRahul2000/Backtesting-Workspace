"""R4 Stage 3 operator command line.

    python -m tools.stage3 check      # is the evidence usable at all?
    python -m tools.stage3 compare    # run the parity check
    python -m tools.stage3 status     # where does Stage 3 stand?
    python -m tools.stage3 ledger     # show recorded evidence periods

Read-only over the terminal's evidence files. The ledger is append-only. No
subcommand can place, modify or cancel a broker order.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import stage3_forward as s3                                   # noqa: E402
from tools.core_audit_schema import KEY                                  # noqa: E402
from tools.stage3_gate import evaluate_gate                              # noqa: E402

FULL = "FULL"
LOGIC_ONLY = "LOGIC_ONLY"


def _collect(args) -> s3.Stage3State:
    state = s3.Stage3State()
    audit_path = Path(args.audit)
    if not audit_path.exists():
        state.add(s3.BLOCKING, "NO_AUDIT",
                  f"{audit_path} not found. Copy the EA's evidence files first.")
        return state
    state.session = s3.load_session(Path(args.session))
    state.events = s3.load_events(Path(args.events))
    try:
        state.audit = s3.load_audit(audit_path)
    except ValueError as error:
        state.add(s3.BLOCKING, "AUDIT_SCHEMA", str(error))
        return state
    s3.check_environment(state.session, state)
    return state


def _python_audit(market: pd.DataFrame, start, end, out: Path, verify: bool) -> pd.DataFrame:
    """Drive the frozen Core over the forward window. Nothing is reimplemented."""
    from core.config import BacktestConfig, DatasetRole
    from tools.export_python_core_audit import STRATEGY_ID, export

    tmp = out.with_suffix(".market.csv")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    market.to_csv(tmp, index=False)
    config = BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD", strategy_id=STRATEGY_ID,
        timeframe="15m", higher_timeframes=("1h",),
        start_date=pd.Timestamp(start), end_date=pd.Timestamp(end),
        dataset_role=DatasetRole.PAPER, spread_source="BROKER_NATIVE_PER_BAR",
        notes="R4 Stage 3 forward parity")
    return export(tmp, config, out, verify=verify)


def cmd_check(args) -> int:
    state = _collect(args)
    if state.audit is not None:
        s3.check_audit(state.audit, state.session, state)
        s3.summarise_events(state.events, state)
    for issue in state.issues:
        print(f"{issue.severity:8} {issue.code:24} {issue.detail}")
    if not state.issues:
        print("No issues found.")
    print("\nVERDICT:", "INVESTIGATE" if state.blocking else "OK")
    return 1 if state.blocking else 0


def cmd_compare(args) -> int:
    from tools.compare_mt5_core import compare as compare_audits

    state = _collect(args)
    if state.audit is None or state.blocking:
        for issue in state.issues:
            print(f"{issue.severity:8} {issue.code:24} {issue.detail}")
        print("\nRefusing to compare: the evidence is not usable as it stands.")
        return 1
    integrity = s3.check_audit(state.audit, state.session, state)
    events = s3.summarise_events(state.events, state)

    mode = FULL if args.market else LOGIC_ONLY
    if mode is FULL or args.market:
        from services.btc_broker_data import read_broker_ohlcv
        market_path = Path(args.market)
        head = market_path.read_text(errors="replace").splitlines()[:1]
        if head and head[0].startswith("timestamp_utc"):
            market = pd.read_csv(market_path)
            market["timestamp_utc"] = pd.to_datetime(market["timestamp_utc"], utc=True)
        else:
            market = read_broker_ohlcv(market_path, point=0.01)
    else:
        market = s3.market_frame_from_audit(state.audit)

    anchor = s3._utc(state.session.get("anchor_utc", "")) or \
        pd.Timestamp(integrity["first_bar"])
    end = pd.Timestamp(integrity["last_bar"])
    out = Path(args.python_audit)
    _python_audit(market, anchor, end, out, verify=not args.no_verify)
    #--- Read the written CSV rather than the in-memory frame so both sides go
    #--- through identical text formatting; comparing a live DataFrame against a
    #--- parsed CSV would manufacture differences that are not real.
    from tools.compare_mt5_core import load_audit as load_for_compare
    python_audit = load_for_compare(out, label="Python")
    report = compare_audits(python_audit, state.audit)
    detail = report.pop("_detail")
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2, default=str) + "\n")
    detail.to_csv(Path(args.report).with_suffix(".detail.csv"), index=False)

    boundary = s3.forward_boundary(state.session)
    forward = s3.lifecycle_counts(state.audit, since=boundary)
    print(f"mode                 : {mode}"
          f"{'  (decision path only — cannot detect a market-data error)' if mode == LOGIC_ONLY else ''}")
    print(f"bars compared        : {report['bars_compared']:,}")
    print(f"mismatches           : {report['bars_mismatching']}")
    print(f"decision parity      : {report['decision_parity_percent']}%")
    print(f"trades py / mt5      : {report['python_trades']} / {report['mt5_trades']}"
          f"   matching {report['full_trade_matches']}")
    for name, stat in report["dimensions"].items():
        print(f"  {name:20} {stat['matching']:>7}/{stat['of']:<7} {stat['percent']}%")
    if report["first_mismatch"]:
        print(f"earliest divergence  : {report['first_mismatch']}")
    print(f"FULL PARITY          : {report['full_parity']}")

    entry = {
        "kind": "forward_comparison", "mode": mode,
        "window": {"anchor": str(anchor), "end": str(end),
                   "forward_boundary": str(boundary) if boundary is not None else None},
        "session": {k: state.session.get(k) for k in s3.IDENTITY_KEYS},
        "artifacts": {
            "mt5_audit": {"path": str(args.audit), "sha256": s3.sha256(Path(args.audit))},
            "python_audit": {"path": str(out), "sha256": s3.sha256(out)},
            "session_file": {"path": str(args.session), "sha256": s3.sha256(Path(args.session))},
            "event_file": {"path": str(args.events), "sha256": s3.sha256(Path(args.events))},
        },
        "integrity": integrity, "events": events, "forward_lifecycle": forward,
        "parity": {k: report[k] for k in
                   ("bars_compared", "bars_mismatching", "decision_parity_percent",
                    "python_trades", "mt5_trades", "full_trade_matches",
                    "full_trade_parity", "full_parity", "mismatch_counts",
                    "first_mismatch")},
        "issues": [i.as_dict() for i in state.issues],
    }
    if not args.no_ledger:
        s3.append_ledger(entry, Path(args.ledger))
        print(f"\nrecorded in {args.ledger}")
    return 0 if report["full_parity"] and not state.blocking else 1


def cmd_status(args) -> int:
    state = _collect(args)
    ledger = s3.read_ledger(Path(args.ledger))
    latest = next((e for e in reversed(ledger) if e.get("kind") == "forward_comparison"), None)

    print("R4 STAGE 3 — STATUS")
    print("=" * 62)
    if state.audit is None:
        for issue in state.issues:
            print(f"{issue.severity:8} {issue.code:24} {issue.detail}")
        print("\nPASS / INVESTIGATE  : INVESTIGATE (no evidence collected yet)")
        return 1

    integrity = s3.check_audit(state.audit, state.session, state)
    events = s3.summarise_events(state.events, state)
    boundary = s3.forward_boundary(state.session)
    total = s3.lifecycle_counts(state.audit)
    forward = s3.lifecycle_counts(state.audit, since=boundary)
    live = s3.open_state(state.audit)

    print(f"session id           : {state.session.get('session_id', '-')}")
    print(f"twin build           : {state.session.get('twin_build', '-')}")
    print(f"compiled             : {state.session.get('compiled_utc', '-')}")
    print(f"mode                 : {state.session.get('mode', '-')}")
    print(f"anchor               : {state.session.get('anchor_utc', '-')}")
    print(f"forward boundary     : {boundary}")
    print("-" * 62)
    print(f"bars observed        : {integrity['bars']:,}  (unique {integrity['unique_bars']:,})")
    print(f"  of which forward   : {forward['bars']:,}")
    print(f"latest MT5 bar       : {integrity['last_bar']}")
    print(f"latest Python bar    : {latest['window']['end'] if latest else '- (no comparison yet)'}")
    print(f"bars compared        : {latest['parity']['bars_compared'] if latest else 0:,}")
    print(f"duplicate bars       : {len(integrity['duplicate_bars'])}")
    print(f"time reversals       : {len(integrity['time_reversals'])}")
    print(f"internal gaps        : {len(integrity['gaps'])}")
    print(f"mismatch count       : {latest['parity']['bars_mismatching'] if latest else '-'}")
    print("-" * 62)
    print(f"restarts             : {events['restarts']}   (session file: "
          f"{state.session.get('restarts', '-')})")
    print(f"reconnects           : {events['reconnects']}   disconnects: {events['disconnects']}")
    print(f"tick outages         : {events['tick_outages']}   data gaps: {events['data_gaps']}"
          f"   backfills: {events['backfills']}")
    print("-" * 62)
    print(f"forward A4 signals   : {forward['a4_signals']}")
    print(f"forward T3 signals   : {forward['t3_signals']}")
    print(f"forward pendings     : {forward['pending_created']}")
    print(f"forward fills        : {forward['fills']}")
    print(f"forward cancellations: {forward['cancellations']}")
    print(f"forward expirations  : {forward['expirations']}")
    print(f"forward exits        : {forward['exits']}"
          f"   (SL {forward['stop_loss_exits']} / TP {forward['take_profit_exits']})")
    print(f"total (incl. replay) : {total['a4_signals']} A4 / {total['t3_signals']} T3 signals,"
          f" {total['fills']} fills")
    print("-" * 62)
    print(f"current pending      : {live['pending'] or 'none'}")
    print(f"current position     : {live['position'] or 'none'}")
    print("-" * 62)
    gate = evaluate_gate(state, integrity, events, forward, latest)
    for line in gate["lines"]:
        print(line)
    print("-" * 62)
    unresolved = [i for i in state.issues if i.severity in (s3.BLOCKING, s3.WARNING)]
    print(f"unresolved issues    : {len(unresolved)}")
    for issue in unresolved:
        print(f"   {issue.severity:8} {issue.code}: {issue.detail}")
    verdict = "PASS" if (latest and latest["parity"]["full_parity"]
                         and not state.blocking) else "INVESTIGATE"
    print(f"\nPASS / INVESTIGATE  : {verdict}")
    print(f"CERTIFICATION GATE  : {gate['verdict']}")
    return 0 if verdict == "PASS" else 1


def cmd_ledger(args) -> int:
    entries = s3.read_ledger(Path(args.ledger))
    if not entries:
        print("Evidence ledger is empty.")
        return 0
    print(f"{len(entries)} ledger entries\n")
    for entry in entries:
        parity = entry.get("parity", {})
        print(f"{entry.get('recorded_at_utc', '?')}  {entry.get('kind')}  "
              f"{entry.get('mode', '')}")
        if parity:
            print(f"    bars {parity.get('bars_compared')}  mismatches "
                  f"{parity.get('bars_mismatching')}  full_parity {parity.get('full_parity')}")
        art = entry.get("artifacts", {})
        for name, meta in art.items():
            if meta and meta.get("sha256"):
                print(f"    {name:14} {meta['sha256'][:16]}…")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audit", default=str(s3.AUDIT_FILE))
    parser.add_argument("--session", default=str(s3.SESSION_FILE))
    parser.add_argument("--events", default=str(s3.EVENT_FILE))
    parser.add_argument("--ledger", default=str(s3.LEDGER))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="validate collected evidence").set_defaults(func=cmd_check)
    sub.add_parser("status", help="Stage 3 status report").set_defaults(func=cmd_status)
    sub.add_parser("ledger", help="show the evidence ledger").set_defaults(func=cmd_ledger)

    compare = sub.add_parser("compare", help="run the forward parity check")
    compare.add_argument("--market", default=None,
                         help="fresh broker M15 export; omit for a logic-only check")
    compare.add_argument("--python-audit", default=str(s3.PYTHON_AUDIT))
    compare.add_argument("--report",
                         default=str(ROOT / "reports/validation/stage3_forward_parity.json"))
    compare.add_argument("--no-verify", action="store_true")
    compare.add_argument("--no-ledger", action="store_true")
    compare.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
