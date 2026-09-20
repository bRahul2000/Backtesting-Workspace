"""R4 Stage 4/5 — demo execution gates, reconciliation, monitoring.

No test here can cause an order to be sent, because the MQL5 layer contains no
transmission call. Several tests assert exactly that.
"""
from pathlib import Path

import pandas as pd
import pytest

from tools import stage4_execution as s4
from tools import stage5_monitor as s5
from tools.check_mt5_core_source import check as static_check

ROOT = Path(__file__).resolve().parents[1]
STAGE4_MQH = ROOT / "mt5" / "BTC_V3_Stage4_Demo.mqh"

CERT = {"twin_build": "R4-S2-2 warmup+session-reset+DI+risk-budget",
        "unresolved_issues": "0"}
GOOD = {
    "mode": "DEMO_EXECUTION", "account_is_demo": True, "symbol": "BTCUSDm",
    "broker": "Exness Technologies Ltd", "server": "Exness-MT5Trial5",
    "expected_broker": "Exness Technologies Ltd",
    "expected_server": "Exness-MT5Trial5",
    "stage3_certificate": CERT, "operator_ack": s4.ACK_PHRASE,
    "twin_build": "R4-S2-2 warmup+session-reset+DI+risk-budget",
}


# --- activation gates ------------------------------------------------------------------------


def test_all_eight_gates_pass_only_when_everything_is_right():
    result = s4.evaluate_activation_gates(GOOD)
    assert result.passed is True
    assert len(result.evaluated) == 8
    assert all(ok for _, ok in result.evaluated)


@pytest.mark.parametrize("key, value, code", [
    ("mode", "AUDIT_ONLY", "MODE_NOT_DEMO_EXECUTION"),
    ("account_is_demo", False, "ACCOUNT_NOT_DEMO"),
    ("symbol", "BTCUSD", "SYMBOL_NOT_BTCUSDM"),
    ("broker", "Someone Else Ltd", "BROKER_FINGERPRINT_MISMATCH"),
    ("server", "Exness-Real1", "BROKER_FINGERPRINT_MISMATCH"),
    ("stage3_certificate", None, "STAGE3_CERTIFICATE_ABSENT"),
    ("operator_ack", "yes please", "OPERATOR_ACKNOWLEDGEMENT_ABSENT"),
    ("twin_build", "some-other-build", "STALE_BUILD"),
])
def test_every_gate_refuses_on_its_own(key, value, code):
    result = s4.evaluate_activation_gates(dict(GOOD, **{key: value}))
    assert result.passed is False
    assert result.failed_code == code


def test_unresolved_stage3_issues_refuse_activation():
    cert = dict(CERT, unresolved_issues="2")
    result = s4.evaluate_activation_gates(dict(GOOD, stage3_certificate=cert))
    assert result.failed_code == "STAGE3_ISSUES_UNRESOLVED"


def test_a_real_account_can_never_pass():
    """The gate that matters most."""
    for flag in (False, None, "true", 1, "DEMO"):
        result = s4.evaluate_activation_gates(dict(GOOD, account_is_demo=flag))
        assert result.passed is False, f"account_is_demo={flag!r} must refuse"


def test_the_acknowledgement_must_match_exactly():
    for phrase in ("", "i authorise exness demo execution",
                   s4.ACK_PHRASE + " ", s4.ACK_PHRASE.lower()):
        result = s4.evaluate_activation_gates(dict(GOOD, operator_ack=phrase))
        assert result.failed_code == "OPERATOR_ACKNOWLEDGEMENT_ABSENT"


#: The MQL5 layer refers to gates by macro; this is the mapping.
GATE_MACROS = {
    "MODE_NOT_DEMO_EXECUTION": "G_MODE",
    "ACCOUNT_NOT_DEMO": "G_ACCOUNT_DEMO",
    "SYMBOL_NOT_BTCUSDM": "G_SYMBOL",
    "BROKER_FINGERPRINT_MISMATCH": "G_BROKER",
    "STAGE3_CERTIFICATE_ABSENT": "G_STAGE3",
    "STAGE3_ISSUES_UNRESOLVED": "G_STAGE3_ISSUES",
    "OPERATOR_ACKNOWLEDGEMENT_ABSENT": "G_ACK",
    "STALE_BUILD": "G_BUILD",
}


def test_gate_order_matches_the_mql5_layer():
    """Both halves must refuse for the same reason in the same order.

    Read from the evaluation function, not the #define block: the order that
    matters is the order the gates are actually checked in.
    """
    import re
    body = STAGE4_MQH.read_text().split("Stage4Gate Stage4EvaluateGates(")[1]
    body = body.split("\n  }")[0]
    seen = []
    for macro in re.findall(r"gate\.failed_code=(G_[A-Z0-9_]+);", body):
        if macro not in seen:
            seen.append(macro)
    expected = [GATE_MACROS[code] for code, _ in s4.GATE_ORDER]
    assert seen == expected, f"gate order drifted: {seen} != {expected}"


# --- reconciliation --------------------------------------------------------------------------


def _exec(**over):
    row = {c: "" for c in s4.EXECUTION_COLUMNS}
    row.update({"event_time_utc": "2026-10-01T00:00:00Z", "session_id": "s",
                "schema_version": "1", "client_tag": "S4|A4|1", "magic": "20260921",
                "setup_id": "BTC_V3_A4_PULLBACK_LONG_FROZEN", "direction": "1",
                "action": "SUBMIT", "outcome": "ACCEPTED", "reject_class": "",
                "requested_volume": "0.10", "filled_volume": "0.10",
                "requested_price": "100.00", "filled_price": "100.00",
                "requested_sl": "99.00", "broker_sl": "99.00",
                "requested_tp": "103.00", "broker_tp": "103.00",
                "commission": "-0.50", "swap": "0.00", "profit": "0.00"})
    row.update(over)
    return row


def _frame(rows):
    return pd.DataFrame(rows, columns=s4.EXECUTION_COLUMNS)


def test_a_clean_execution_reconciles():
    report = s4.reconcile(pd.DataFrame(), _frame([_exec()]))
    assert report["clean"] is True
    assert report["sl_mismatches"] == 0
    assert report["slippage"]["count"] == 1
    assert report["slippage"]["mean"] == 0.0


def test_entry_slippage_is_measured_not_absorbed():
    report = s4.reconcile(pd.DataFrame(), _frame([_exec(filled_price="100.40")]))
    assert report["slippage"]["worst"] == pytest.approx(0.40)


def test_a_broker_moved_stop_is_a_mismatch():
    report = s4.reconcile(pd.DataFrame(), _frame([_exec(broker_sl="98.00")]))
    assert report["sl_mismatches"] == 1
    assert report["clean"] is False


def test_a_broker_moved_target_is_a_mismatch():
    report = s4.reconcile(pd.DataFrame(), _frame([_exec(broker_tp="110.00")]))
    assert report["tp_mismatches"] == 1
    assert report["clean"] is False


def test_a_partial_fill_is_detected():
    report = s4.reconcile(pd.DataFrame(), _frame([_exec(filled_volume="0.04")]))
    assert report["partial_fills"] == 1


def test_a_duplicate_client_tag_is_never_clean():
    """Exactly-once is the property the magic number and tag exist to protect."""
    report = s4.reconcile(pd.DataFrame(), _frame([_exec(), _exec()]))
    assert report["duplicate_client_tags"] == ["S4|A4|1"]
    assert report["clean"] is False


def test_commission_and_swap_are_captured():
    report = s4.reconcile(pd.DataFrame(),
                          _frame([_exec(commission="-0.50", swap="-0.20")]))
    assert report["commission_total"] == pytest.approx(-0.50)
    assert report["swap_total"] == pytest.approx(-0.20)


def test_an_execution_log_missing_a_column_is_refused(tmp_path):
    path = tmp_path / "ex.csv"
    _frame([_exec()]).drop(columns=["swap"]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="missing columns"):
        s4.load_executions(path)


def test_the_stage4_ledger_is_append_only(tmp_path):
    path = tmp_path / "l.jsonl"
    s4.append_ledger({"kind": "reconciliation", "n": 1}, path)
    s4.append_ledger({"kind": "reconciliation", "n": 2}, path)
    assert [e["n"] for e in s4.read_ledger(path)] == [1, 2]


# --- Stage 5 monitoring ----------------------------------------------------------------------


def test_drawdown_and_losing_streak():
    risk = s5.drawdown_and_streaks([2.0, -1.0, -1.0, -1.0, 0.5])
    assert risk["max_drawdown"] == pytest.approx(3.0)
    assert risk["longest_losing_streak"] == 3


def test_slippage_distribution_reports_tail_not_just_mean():
    dist = s5.slippage_distribution([0.1, 0.1, 0.1, 0.1, 5.0])
    assert dist["mean"] == pytest.approx(1.08)
    assert dist["worst"] == pytest.approx(5.0)
    assert dist["p95_abs"] == pytest.approx(5.0)


def test_readiness_needs_enough_completed_trades():
    closes = _frame([_exec(action="CLOSE", profit="1.0",
                           event_time_utc=f"2026-10-{d:02d}T00:00:00Z")
                     for d in range(1, 6)])
    recon = s4.reconcile(pd.DataFrame(), closes)
    report = s5.readiness(closes, recon)
    assert report["must_ok"] is True
    assert report["verdict"].startswith("AWAITING EVIDENCE")


def test_readiness_is_blocked_by_an_execution_defect():
    rows = [_exec(action="CLOSE", profit="1.0",
                  event_time_utc=f"2026-10-{d:02d}T00:00:00Z") for d in range(1, 26)]
    rows.append(_exec(broker_sl="90.0"))
    frame = _frame(rows)
    report = s5.readiness(frame, s4.reconcile(pd.DataFrame(), frame))
    assert report["must_ok"] is False
    assert report["verdict"].startswith("BLOCKED")


def test_readiness_reaches_review_with_enough_clean_trades():
    rows = [_exec(action="CLOSE", profit="1.0", client_tag=f"S4|A4|{i}",
                  event_time_utc=f"2026-10-{(i % 28) + 1:02d}T00:00:00Z")
            for i in range(30)]
    frame = _frame(rows)
    report = s5.readiness(frame, s4.reconcile(pd.DataFrame(), frame))
    assert report["completed_trades"] == 30
    assert report["verdict"] == "READY FOR DEPLOYMENT REVIEW"


def test_a_strategy_versus_broker_divergence_blocks_readiness():
    rows = [_exec(action="CLOSE", profit="1.0", client_tag=f"S4|A4|{i}")
            for i in range(30)]
    frame = _frame(rows)
    report = s5.readiness(frame, s4.reconcile(pd.DataFrame(), frame), divergences=1)
    assert report["must_ok"] is False


def test_weekly_summaries_are_produced():
    rows = [_exec(event_time_utc="2026-10-01T00:00:00Z"),
            _exec(event_time_utc="2026-10-09T00:00:00Z", client_tag="S4|A4|2")]
    weeks = s5.weekly_summary(_frame(rows))
    assert len(weeks) == 2


# --- the safety property that matters ---------------------------------------------------------


def test_the_stage4_layer_contains_no_transmission_call():
    """Not gated — absent. A gated send is one edited condition from firing."""
    report = static_check()
    assert report["stage4_layer_present"] is True
    assert report["stage4_forbidden_calls"] == []
    assert report["stage4_transmit_refuses_unconditionally"] is True


def test_transmit_returns_false_on_every_path():
    body = STAGE4_MQH.read_text().split("bool Stage4Transmit(")[1]
    assert "return true" not in body, "Stage4Transmit must never return true"
    assert body.count("return false;") >= 4


def test_the_ea_does_not_include_the_stage4_layer_yet():
    """Stage 4 stays unreachable until it is authorised."""
    assert static_check()["stage4_not_wired_into_ea"] is True


def test_all_eight_gates_exist_in_the_mql5_layer():
    assert static_check()["stage4_declares_all_eight_gates"] is True


def test_the_mql5_layer_demands_a_demo_account_and_the_ack_phrase():
    report = static_check()
    assert report["stage4_requires_demo_account"] is True
    assert report["stage4_requires_operator_phrase"] is True
    assert report["stage4_requires_stage3_certificate"] is True


def test_validation_and_normalisation_are_present():
    report = static_check()
    for key in ("stage4_normalises_volume_and_price", "stage4_validates_stops_level",
                "stage4_has_spread_guardrail", "stage4_classifies_retcodes",
                "stage4_has_magic_ownership", "stage4_detects_orphans",
                "stage4_preflights_with_ordercheck"):
        assert report[key] is True, key


def test_volume_rounds_down_never_up():
    """Rounding up would exceed the risk budget."""
    body = STAGE4_MQH.read_text()
    assert "MathFloor(volume/step)*step" in body
    assert "MathCeil(volume" not in body


def test_stage4_and_stage5_tooling_contain_no_order_call():
    forbidden = ("OrderSend", "PositionOpen", "PositionClose", "CTrade",
                 "order_send", "place_order")
    for name in ("stage4.py", "stage4_execution.py", "stage5_monitor.py"):
        source = (ROOT / "tools" / name).read_text()
        for token in forbidden:
            assert token not in source, f"{name} references {token}"
