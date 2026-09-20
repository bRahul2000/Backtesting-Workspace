"""R4 Stage 4/5 operator command line.

    python -m tools.stage4 gate       can demo execution be activated?
    python -m tools.stage4 status     Stage 4 execution status
    python -m tools.stage4 reconcile  twin intention vs broker reality
    python -m tools.stage4 readiness  Stage 5 deployment-readiness report

Read-only. No subcommand can place, modify or cancel an order — the
transmission call does not exist in the MQL5 layer at all.
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

from tools import stage3_forward as s3                                    # noqa: E402
from tools import stage4_execution as s4                                  # noqa: E402
from tools import stage5_monitor as s5                                    # noqa: E402


def _context(args) -> dict:
    session = s3.load_session(Path(args.session))
    cert_path = Path(args.certificate)
    certificate = None
    if cert_path.exists():
        frame = pd.read_csv(cert_path, dtype=str, keep_default_na=False)
        certificate = dict(zip(frame["key"], frame["value"]))
    return {
        "mode": session.get("mode"),
        "account_is_demo": session.get("account_trade_mode") == "0",
        "symbol": session.get("symbol"),
        "broker": session.get("broker"), "server": session.get("server"),
        "expected_broker": args.expected_broker,
        "expected_server": args.expected_server,
        "stage3_certificate": certificate,
        "operator_ack": args.ack,
        "twin_build": session.get("twin_build"),
    }


def cmd_gate(args) -> int:
    result = s4.evaluate_activation_gates(_context(args))
    print("R4 STAGE 4 — ACTIVATION GATES")
    print("=" * 62)
    for code, ok in result.evaluated:
        print(f"  [{'x' if ok else ' '}] {code}")
    print("-" * 62)
    if result.passed:
        print("All eight activation gates pass.")
        print("Transmission is STILL refused: the MQL5 layer has no send call.")
        print("Enabling it is a separate authorised change.")
    else:
        print(f"REFUSED: {result.failed_code}")
        print(f"  {result.detail}")
    return 0 if result.passed else 1


def cmd_reconcile(args) -> int:
    executions = s4.load_executions(Path(args.executions))
    if executions.empty:
        print("No demo executions recorded yet — nothing to reconcile.")
        return 0
    audit = s3.load_audit(Path(args.audit)) if Path(args.audit).exists() else pd.DataFrame()
    report = s4.reconcile(audit, executions)
    print(f"submissions          : {report['submissions']}")
    print(f"duplicate client tags: {report['duplicate_client_tags'] or 'none'}")
    print(f"partial fills        : {report['partial_fills']}")
    print(f"SL mismatches        : {report['sl_mismatches']}")
    print(f"TP mismatches        : {report['tp_mismatches']}")
    print(f"slippage             : {report['slippage']}")
    print(f"commission / swap    : {report['commission_total']} / {report['swap_total']}")
    print(f"CLEAN                : {report['clean']}")
    rows = report.pop("rows")
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2, default=str) + "\n")
    if not args.no_ledger:
        s4.append_ledger({"kind": "reconciliation", "report": report}, Path(args.ledger))
    report["rows"] = rows
    return 0 if report["clean"] else 1


def cmd_status(args) -> int:
    executions = s4.load_executions(Path(args.executions))
    gate = s4.evaluate_activation_gates(_context(args))
    print("R4 STAGE 4 — STATUS")
    print("=" * 62)
    print(f"activation gates     : {'ALL PASS' if gate.passed else gate.failed_code}")
    print(f"transmission         : NOT IMPLEMENTED (no send call exists)")
    print(f"executions recorded  : {len(executions)}")
    if not executions.empty:
        print(f"  submissions        : {int((executions.action == 'SUBMIT').sum())}")
        print(f"  accepted           : {int((executions.outcome == 'ACCEPTED').sum())}")
        print(f"  rejected           : {int((executions.outcome != 'ACCEPTED').sum())}")
        print(f"  closes             : {int((executions.action == 'CLOSE').sum())}")
    print(f"ledger entries       : {len(s4.read_ledger(Path(args.ledger)))}")
    return 0


def cmd_readiness(args) -> int:
    executions = s4.load_executions(Path(args.executions))
    recon = s4.reconcile(pd.DataFrame(), executions) if not executions.empty else {
        "rows": [], "duplicate_client_tags": [], "sl_mismatches": 0,
        "tp_mismatches": 0, "commission_total": 0.0, "swap_total": 0.0}
    report = s5.readiness(executions, recon, divergences=args.divergences)
    print("R4 STAGE 5 — DEPLOYMENT READINESS")
    print("=" * 62)
    print(f"completed demo trades: {report['completed_trades']}")
    print(f"slippage             : {report['slippage']}")
    print(f"max drawdown         : {report['risk']['max_drawdown']}")
    print(f"longest losing streak: {report['risk']['longest_losing_streak']}")
    print(f"commission / swap    : {report['commission_total']} / {report['swap_total']}")
    print("-" * 62)
    print("  MUST")
    for label, ok in report["must"]:
        print(f"    [{'x' if ok else ' '}] {label}")
    print("  OBSERVED")
    for label, ok, value in report["observed"]:
        print(f"    [{'x' if ok else ' '}] {label}  ({value})")
    for week in report["weekly"]:
        print(f"    {week}")
    print("-" * 62)
    print(f"VERDICT              : {report['verdict']}")
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, indent=2, default=str) + "\n")
    return 0 if report["must_ok"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", default=str(s3.SESSION_FILE))
    parser.add_argument("--executions", default=str(s4.EXECUTION_FILE))
    parser.add_argument("--audit", default=str(s3.AUDIT_FILE))
    parser.add_argument("--ledger", default=str(s4.LEDGER))
    parser.add_argument("--certificate",
                        default=str(ROOT / "reports/validation/stage3_certificate.csv"))
    parser.add_argument("--expected-broker", default="Exness Technologies Ltd")
    parser.add_argument("--expected-server", default="Exness-MT5Trial5")
    parser.add_argument("--ack", default="")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("gate").set_defaults(func=cmd_gate)
    sub.add_parser("status").set_defaults(func=cmd_status)
    rec = sub.add_parser("reconcile")
    rec.add_argument("--report",
                     default=str(ROOT / "reports/validation/stage4_reconciliation.json"))
    rec.add_argument("--no-ledger", action="store_true")
    rec.set_defaults(func=cmd_reconcile)
    ready = sub.add_parser("readiness")
    ready.add_argument("--report",
                       default=str(ROOT / "reports/validation/stage5_readiness.json"))
    ready.add_argument("--divergences", type=int, default=0)
    ready.set_defaults(func=cmd_readiness)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
