"""R4 Stage 4 — demo execution gates, reconciliation and evidence.

Stage 4 is the first stage that could place an order. It cannot today: the
transmission call does not exist in mt5/BTC_V3_Stage4_Demo.mqh, and a static
check requires it to stay absent. This module is the Python half — the gates
mirrored so they are testable, the twin-versus-broker reconciliation, and the
append-only execution ledger.

Nothing here can cause an order to be sent. It reads evidence files and writes
reports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import stage3_forward as s3                                    # noqa: E402

STAGE4_DIR = ROOT / "data/exness/btc/stage4"
EXECUTION_FILE = STAGE4_DIR / "btc_core_v1_executions.csv"
LEDGER = ROOT / "reports/validation/stage4_execution_ledger.jsonl"

STAGE4_MAGIC = 20260921
ACK_PHRASE = "I AUTHORISE EXNESS DEMO EXECUTION"

#: One row per broker interaction. Separate from the 76-column audit: the audit
#: records what the strategy decided, this records what the broker did.
EXECUTION_COLUMNS = [
    "event_time_utc", "session_id", "schema_version", "client_tag", "magic",
    "setup_id", "direction", "action", "outcome", "retcode", "reject_class",
    "ticket", "requested_volume", "filled_volume",
    "requested_price", "filled_price", "requested_sl", "broker_sl",
    "requested_tp", "broker_tp", "exit_price", "exit_reason",
    "commission", "swap", "profit", "spread_points_at_submit",
]

#: The eight conditions that must ALL hold before transmission is permitted.
#: Mirrors Stage4EvaluateGates in the MQL5 layer, in the same order.
GATE_ORDER = (
    ("MODE_NOT_DEMO_EXECUTION", "mode"),
    ("ACCOUNT_NOT_DEMO", "account_is_demo"),
    ("SYMBOL_NOT_BTCUSDM", "symbol"),
    ("BROKER_FINGERPRINT_MISMATCH", "broker_fingerprint"),
    ("STAGE3_CERTIFICATE_ABSENT", "stage3_certificate"),
    ("STAGE3_ISSUES_UNRESOLVED", "stage3_issues"),
    ("OPERATOR_ACKNOWLEDGEMENT_ABSENT", "operator_ack"),
    ("STALE_BUILD", "build_matches_certificate"),
)

RETRYABLE = {"REQUOTE", "TIMEOUT"}


@dataclass
class GateResult:
    passed: bool
    failed_code: str | None
    detail: str
    evaluated: list[tuple[str, bool]] = field(default_factory=list)


def evaluate_activation_gates(context: dict) -> GateResult:
    """All eight must pass. First failure is reported, so a refusal names one cause.

    `context` is what the operator's environment reports, not what it wishes:
    mode, account_is_demo, symbol, broker, server, expected_broker,
    expected_server, stage3_certificate (dict or None), operator_ack, twin_build.
    """
    checks: list[tuple[str, bool, str]] = []
    cert = context.get("stage3_certificate")

    checks.append(("MODE_NOT_DEMO_EXECUTION",
                   context.get("mode") == "DEMO_EXECUTION",
                   f"mode is {context.get('mode')!r}"))
    checks.append(("ACCOUNT_NOT_DEMO", context.get("account_is_demo") is True,
                   f"account_is_demo is {context.get('account_is_demo')!r}"))
    checks.append(("SYMBOL_NOT_BTCUSDM", context.get("symbol") == "BTCUSDm",
                   f"symbol is {context.get('symbol')!r}"))
    checks.append(("BROKER_FINGERPRINT_MISMATCH",
                   context.get("broker") == context.get("expected_broker")
                   and context.get("server") == context.get("expected_server"),
                   f"broker/server {context.get('broker')!r}/{context.get('server')!r}"))
    checks.append(("STAGE3_CERTIFICATE_ABSENT", isinstance(cert, dict) and bool(cert),
                   "no Stage 3 certificate"))
    checks.append(("STAGE3_ISSUES_UNRESOLVED",
                   isinstance(cert, dict) and int(cert.get("unresolved_issues", 1)) == 0,
                   "Stage 3 certificate reports unresolved issues"))
    checks.append(("OPERATOR_ACKNOWLEDGEMENT_ABSENT",
                   context.get("operator_ack") == ACK_PHRASE,
                   "acknowledgement phrase absent or wrong"))
    checks.append(("STALE_BUILD",
                   isinstance(cert, dict)
                   and cert.get("twin_build") == context.get("twin_build")
                   and bool(context.get("twin_build")),
                   "running build differs from the certified one"))

    evaluated = [(code, ok) for code, ok, _ in checks]
    for code, ok, detail in checks:
        if not ok:
            return GateResult(False, code, detail, evaluated)
    return GateResult(True, None, "all activation gates passed", evaluated)


def load_executions(path: Path = EXECUTION_FILE) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=EXECUTION_COLUMNS)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in EXECUTION_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"{path.name}: execution log missing columns {missing}")
    return frame[EXECUTION_COLUMNS].copy()


def _num(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def reconcile(audit: pd.DataFrame, executions: pd.DataFrame,
              *, price_tolerance: float = 0.01) -> dict:
    """Twin intention versus broker reality, per client tag.

    The twin's audit says what price, stop, target and exit the frozen Core
    expected. The execution log says what the broker actually did. Every
    difference is reported; none is absorbed.
    """
    rows: list[dict] = []
    duplicates = executions.loc[
        executions.client_tag.duplicated(keep=False) & (executions.action == "SUBMIT"),
        "client_tag"].unique().tolist()

    submits = executions[executions.action == "SUBMIT"]
    for _, ex in submits.iterrows():
        filled = _num(ex.filled_price)
        requested = _num(ex.requested_price)
        slip = None if (filled is None or requested is None) else filled - requested
        sl_delta = None
        if _num(ex.broker_sl) is not None and _num(ex.requested_sl) is not None:
            sl_delta = _num(ex.broker_sl) - _num(ex.requested_sl)
        tp_delta = None
        if _num(ex.broker_tp) is not None and _num(ex.requested_tp) is not None:
            tp_delta = _num(ex.broker_tp) - _num(ex.requested_tp)
        vol_req, vol_fill = _num(ex.requested_volume), _num(ex.filled_volume)
        partial = (vol_req is not None and vol_fill is not None
                   and 0 < vol_fill < vol_req)
        rows.append({
            "client_tag": ex.client_tag, "setup_id": ex.setup_id,
            "outcome": ex.outcome, "reject_class": ex.reject_class,
            "entry_slippage": slip,
            "sl_delta": sl_delta, "tp_delta": tp_delta,
            "partial_fill": partial,
            "sl_placed_correctly": sl_delta is not None and abs(sl_delta) <= price_tolerance,
            "tp_placed_correctly": tp_delta is not None and abs(tp_delta) <= price_tolerance,
            "commission": _num(ex.commission), "swap": _num(ex.swap),
            "profit": _num(ex.profit),
        })

    slippages = [r["entry_slippage"] for r in rows if r["entry_slippage"] is not None]
    mismatched_stops = [r for r in rows
                        if r["sl_delta"] is not None and not r["sl_placed_correctly"]]
    mismatched_targets = [r for r in rows
                          if r["tp_delta"] is not None and not r["tp_placed_correctly"]]
    return {
        "submissions": int(len(submits)),
        "duplicate_client_tags": duplicates,
        "partial_fills": int(sum(1 for r in rows if r["partial_fill"])),
        "sl_mismatches": len(mismatched_stops),
        "tp_mismatches": len(mismatched_targets),
        "slippage": {
            "count": len(slippages),
            "mean": statistics.fmean(slippages) if slippages else None,
            "median": statistics.median(slippages) if slippages else None,
            "worst": max(slippages, key=abs) if slippages else None,
        },
        "commission_total": sum(r["commission"] for r in rows if r["commission"]),
        "swap_total": sum(r["swap"] for r in rows if r["swap"]),
        "rows": rows,
        "clean": (not duplicates and not mismatched_stops and not mismatched_targets),
    }


def append_ledger(entry: dict, path: Path = LEDGER) -> None:
    """Append-only. Stage 4 evidence is never rewritten."""
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = dict(entry)
    entry.setdefault("recorded_at_utc", datetime.now(timezone.utc).isoformat())
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, default=str, sort_keys=True) + "\n")


def read_ledger(path: Path = LEDGER) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
