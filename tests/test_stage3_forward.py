"""R4 Stage 3 — live forward shadow validation.

Evidence fixtures are built in-memory or written to tmp_path. They are never
placed under data/ and never presented as broker output. The one test that uses
real Exness bars uses them read-only and says so.
"""
from pathlib import Path

import pandas as pd
import pytest

from tools import stage3_forward as s3
from tools.check_mt5_core_source import check as static_check
from tools.core_audit_schema import AUDIT_COLUMNS, KEY
from tools.stage3_gate import evaluate_gate

ROOT = Path(__file__).resolve().parents[1]
EXNESS_M15 = ROOT / "data/exness/btc/phase_r1/processed/btcusdm_M15.csv"

GOOD_SESSION = {
    "schema_version": "1", "session_id": "2026-09-21T00:00:00Z",
    "twin_build": "R4-S2-2 warmup+session-reset+DI+risk-budget",
    "compiled_utc": "2026.09.20 16:48:27",
    "core_fingerprint": s3.EXPECTED_FINGERPRINTS["core_fingerprint"],
    "a4_fingerprint": s3.EXPECTED_FINGERPRINTS["a4_fingerprint"],
    "t3_fingerprint": s3.EXPECTED_FINGERPRINTS["t3_fingerprint"],
    "mode": "AUDIT_ONLY", "symbol": "BTCUSDm", "digits": "2", "point": "0.0100000000",
    "server_utc_offset_secs": "0", "anchor_utc": "2026-09-01T00:00:00Z",
    "first_start_utc": "2026-09-21T00:00:00Z", "restarts": "0", "reconnects": "0",
    "duplicate_bars": "0", "reversed_bars": "0", "backfilled_bars": "0",
}


def _row(stamp: str, **overrides) -> dict:
    row = {column: "" for column in AUDIT_COLUMNS}
    row.update({
        KEY: stamp, "symbol": "BTCUSDm",
        "open": "100.00", "high": "101.00", "low": "99.00", "close": "100.50",
        "tick_volume": "10", "spread_points": "1000", "spread_price": "10.00",
        "a4_context_pass": "0", "a4_signal_pass": "0",
        "t3_context_pass": "0", "t3_signal_pass": "0",
        "commission_status": s3.UNVERIFIED if hasattr(s3, "UNVERIFIED") else "UNVERIFIED",
    })
    row.update(overrides)
    return row


def _audit(stamps, per_row: dict | None = None) -> pd.DataFrame:
    rows = [_row(s) for s in stamps]
    for index, values in (per_row or {}).items():
        rows[index].update(values)
    return pd.DataFrame(rows, columns=AUDIT_COLUMNS)


def _stamps(count, start="2026-09-21T00:00:00Z"):
    base = pd.Timestamp(start)
    return [(base + i * s3.STEP).strftime("%Y-%m-%dT%H:%M:%SZ") for i in range(count)]


def _state(session=None, audit=None, events=None) -> s3.Stage3State:
    state = s3.Stage3State()
    state.session = dict(GOOD_SESSION if session is None else session)
    state.audit = audit
    state.events = events if events is not None else s3.load_events(Path("/nonexistent"))
    s3.check_environment(state.session, state)
    return state


# --- audit integrity -----------------------------------------------------------------------


def test_a_clean_audit_has_no_duplicates_reversals_or_gaps():
    report = s3.audit_integrity(_audit(_stamps(8)))
    assert report["bars"] == report["unique_bars"] == 8
    assert report["duplicate_bars"] == []
    assert report["time_reversals"] == []
    assert report["gaps"] == []


def test_a_duplicated_closed_bar_is_detected():
    stamps = _stamps(4)
    report = s3.audit_integrity(_audit(stamps + [stamps[2]]))
    assert report["duplicate_bars"] == [stamps[2]]
    state = _state(audit=_audit(stamps + [stamps[2]]))
    s3.check_audit(state.audit, state.session, state)
    assert any(i.code == "DUPLICATE_CLOSED_BAR" for i in state.blocking)


def test_time_running_backwards_is_detected():
    stamps = _stamps(4)
    out_of_order = [stamps[0], stamps[1], stamps[3], stamps[2]]
    report = s3.audit_integrity(_audit(out_of_order))
    assert report["time_reversals"]
    state = _state(audit=_audit(out_of_order))
    s3.check_audit(state.audit, state.session, state)
    assert any(i.code == "TIME_REVERSAL" for i in state.blocking)


def test_a_missing_bar_is_reported_as_a_gap_not_a_duplicate():
    stamps = _stamps(6)
    del stamps[3]
    report = s3.audit_integrity(_audit(stamps))
    assert len(report["gaps"]) == 1
    assert report["gaps"][0][2] == 1
    assert report["duplicate_bars"] == []


def test_an_audit_missing_a_schema_column_is_refused(tmp_path):
    frame = _audit(_stamps(3)).drop(columns=["realized_r"])
    path = tmp_path / "audit.csv"
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError, match="missing columns"):
        s3.load_audit(path)


# --- run identity and failure conditions ---------------------------------------------------


def test_a_matching_session_raises_no_environment_issue():
    assert _state().issues == []


@pytest.mark.parametrize("key, value, code", [
    ("core_fingerprint", "0" * 64, "STALE_OR_WRONG_BUILD"),
    ("a4_fingerprint", "0" * 64, "STALE_OR_WRONG_BUILD"),
    ("t3_fingerprint", "0" * 64, "STALE_OR_WRONG_BUILD"),
    ("mode", "DEMO_EXECUTION", "NOT_AUDIT_ONLY"),
    ("symbol", "BTCUSD", "WRONG_SYMBOL"),
    ("digits", "5", "WRONG_DIGITS"),
    ("point", "0.00001", "WRONG_POINT"),
    ("server_utc_offset_secs", "10800", "NON_UTC_SERVER"),
    ("duplicate_bars", "2", "EA_DUPLICATE_BARS"),
    ("reversed_bars", "1", "EA_TIME_REVERSAL"),
])
def test_each_invalidating_condition_blocks(key, value, code):
    session = dict(GOOD_SESSION, **{key: value})
    state = _state(session=session)
    assert any(i.code == code for i in state.blocking), [i.code for i in state.issues]


def test_a_missing_session_file_blocks():
    state = s3.Stage3State()
    s3.check_environment({}, state)
    assert any(i.code == "NO_SESSION_FILE" for i in state.blocking)


def test_a_stale_ea_build_is_caught_even_if_everything_else_is_clean():
    """The EA runs the compiled .ex5; the fingerprints are how a stale one shows."""
    state = _state(session=dict(GOOD_SESSION, core_fingerprint="9" * 64))
    assert state.blocking
    assert "STALE_OR_WRONG_BUILD" in {i.code for i in state.blocking}


# --- operational events --------------------------------------------------------------------


def _events(kinds) -> pd.DataFrame:
    return pd.DataFrame(
        [{"event_time_utc": "2026-09-21T00:00:00Z", "session_id": "s",
          "schema_version": "1", "kind": kind, "detail": ""} for kind in kinds],
        columns=["event_time_utc", "session_id", "schema_version", "kind", "detail"])


def test_restarts_and_reconnects_are_counted():
    state = _state()
    summary = s3.summarise_events(
        _events(["SESSION_START", "RESTART", "RECONNECT", "RECONNECT", "DISCONNECT",
                 "TICK_OUTAGE", "DATA_GAP", "BACKFILL"]), state)
    assert summary["restarts"] == 1
    assert summary["reconnects"] == 2
    assert summary["disconnects"] == 1
    assert summary["tick_outages"] == 1
    assert summary["data_gaps"] == 1
    assert summary["backfills"] == 1
    assert state.blocking == []


def test_a_scheduler_anomaly_event_blocks():
    state = _state()
    s3.summarise_events(_events(["DUPLICATE_BAR"]), state)
    assert any(i.code == "EA_SCHEDULER_ANOMALY" for i in state.blocking)


def test_an_unreachable_anchor_blocks():
    state = _state()
    s3.summarise_events(_events(["ANCHOR_UNREACHABLE"]), state)
    assert any(i.code == "ANCHOR_UNREACHABLE" for i in state.blocking)


# --- forward boundary and lifecycle ---------------------------------------------------------


def test_forward_bars_are_counted_from_the_first_start_not_the_anchor():
    """Replayed history is compared, but only forward bars count toward the gate."""
    stamps = _stamps(4, start="2026-09-20T23:00:00Z") + _stamps(6)
    audit = _audit(stamps)
    boundary = s3.forward_boundary(GOOD_SESSION)
    assert str(boundary) == "2026-09-21 00:00:00+00:00"
    assert s3.lifecycle_counts(audit)["bars"] == 10
    assert s3.lifecycle_counts(audit, since=boundary)["bars"] == 6


def test_lifecycle_counts_track_the_whole_order_path():
    a4 = "BTC_V3_A4_PULLBACK_LONG_FROZEN"
    audit = _audit(_stamps(6), {
        0: {"signal_setup_id": a4, "signal_side": "LONG", "a4_signal_pass": "1",
            "pending_status": "CREATED"},
        1: {"pending_status": "FILLED", "entry_time_utc": "x", "entry_price": "100"},
        2: {"exit_time_utc": "y", "exit_price": "103", "exit_reason": "Take profit",
            "realized_r": "3.0"},
        3: {"pending_status": "EXPIRED"},
        4: {"pending_status": "CANCELLED"}})
    counts = s3.lifecycle_counts(audit)
    assert counts["a4_signals"] == 1
    assert counts["pending_created"] == 1
    assert counts["fills"] == 1
    assert counts["exits"] == 1
    assert counts["take_profit_exits"] == 1
    assert counts["expirations"] == 1
    assert counts["cancellations"] == 1


def test_an_open_simulated_position_is_reported_as_open():
    audit = _audit(_stamps(3), {
        0: {"pending_status": "FILLED", "entry_time_utc": "t",
            "entry_price": "100", "entry_stop": "99", "entry_target": "103"}})
    live = s3.open_state(audit)
    assert live["position"] is not None
    assert live["pending"] is None


def test_a_closed_position_is_not_reported_as_open():
    audit = _audit(_stamps(3), {
        0: {"pending_status": "FILLED", "entry_time_utc": "t", "entry_price": "100"},
        1: {"exit_time_utc": "u", "exit_price": "103", "realized_r": "3.0"}})
    assert s3.open_state(audit)["position"] is None


def test_a_live_pending_order_is_reported():
    audit = _audit(_stamps(2), {
        1: {"pending_status": "ACTIVE", "pending_trigger": "101", "pending_stop": "99"}})
    assert s3.open_state(audit)["pending"]["status"] == "ACTIVE"


# --- market frame ---------------------------------------------------------------------------


def test_the_logic_only_market_frame_mirrors_the_audit_exactly():
    audit = _audit(_stamps(4))
    frame = s3.market_frame_from_audit(audit)
    assert list(frame.columns) == ["timestamp_utc", "open", "high", "low", "close",
                                   "tick_volume", "real_volume", "spread_points",
                                   "spread_price"]
    assert len(frame) == 4
    assert frame["close"].iloc[0] == 100.5


# --- evidence ledger --------------------------------------------------------------------------


def test_the_ledger_is_append_only(tmp_path):
    path = tmp_path / "ledger.jsonl"
    s3.append_ledger({"kind": "forward_comparison", "n": 1}, path)
    s3.append_ledger({"kind": "forward_comparison", "n": 2}, path)
    entries = s3.read_ledger(path)
    assert [e["n"] for e in entries] == [1, 2]
    assert all("recorded_at_utc" in e for e in entries)


def test_ledger_entries_carry_artifact_hashes(tmp_path):
    artifact = tmp_path / "a.csv"
    artifact.write_text("x")
    digest = s3.sha256(artifact)
    assert digest and len(digest) == 64
    path = tmp_path / "ledger.jsonl"
    s3.append_ledger({"artifacts": {"mt5_audit": {"sha256": digest}}}, path)
    assert s3.read_ledger(path)[0]["artifacts"]["mt5_audit"]["sha256"] == digest


# --- certification gate -----------------------------------------------------------------------


def _gate(forward_bars=2000, signals=5, pendings=5, fills=2, exits=2,
          restarts=1, reconnects=1, mismatches=0, full_parity=True, blocking=False):
    state = _state(session=dict(GOOD_SESSION,
                                **({"symbol": "WRONG"} if blocking else {})))
    integrity = {"duplicate_bars": [], "time_reversals": [], "gaps": []}
    events = {"counts": {}, "restarts": restarts, "reconnects": reconnects,
              "disconnects": 0, "tick_outages": 0, "data_gaps": 0, "backfills": 0}
    forward = {"bars": forward_bars, "a4_signals": signals, "t3_signals": 0,
               "pending_created": pendings, "fills": fills, "exits": exits,
               "expirations": 0, "cancellations": 0,
               "stop_loss_exits": 0, "take_profit_exits": 0}
    latest = {"parity": {"bars_compared": forward_bars + 500,
                         "bars_mismatching": mismatches, "full_parity": full_parity}}
    return evaluate_gate(state, integrity, events, forward, latest)


def test_the_gate_is_ready_only_when_every_condition_is_met():
    assert _gate()["verdict"] == "READY TO CERTIFY"


def test_a_decision_mismatch_blocks_certification():
    gate = _gate(mismatches=1, full_parity=False)
    assert gate["must_ok"] is False
    assert gate["verdict"].startswith("BLOCKED")


def test_missing_market_coverage_is_a_limitation_not_a_defect():
    """A lifecycle that did not occur is reported, never manufactured."""
    gate = _gate(fills=0, exits=0)
    assert gate["must_ok"] is True
    assert gate["verdict"].startswith("AWAITING EVIDENCE")
    assert any("fills" in item for item in gate["missing_coverage"])


def test_a_short_sample_is_not_certifiable():
    gate = _gate(forward_bars=10)
    assert gate["verdict"].startswith("AWAITING EVIDENCE")


def test_no_restart_test_blocks_readiness():
    assert _gate(restarts=0)["verdict"].startswith("AWAITING EVIDENCE")


def test_no_reconnect_test_blocks_readiness():
    assert _gate(reconnects=0)["verdict"].startswith("AWAITING EVIDENCE")


def test_a_blocking_environment_issue_blocks_the_gate():
    assert _gate(blocking=True)["must_ok"] is False


# --- recovery model ----------------------------------------------------------------------------


def test_replay_from_a_fixed_anchor_is_deterministic():
    """The claim the whole recovery model rests on, tested on real bars.

    The EA recovers by replaying every closed bar from a fixed anchor rather
    than restoring a serialised checkpoint. That is only sound if replaying to
    time T always yields the same audit as an uninterrupted run to T. Here a
    short run and a longer run share an anchor; every bar they have in common
    must be identical in all 76 columns, including carried pullback state, the
    order lifecycle and the simulated position.
    """
    if not EXNESS_M15.exists():
        pytest.skip("Exness dataset not present in this checkout")
    import pandas as pd
    from core.config import BacktestConfig, DatasetRole
    from tools.export_python_core_audit import STRATEGY_ID, export

    def run(end, out):
        config = BacktestConfig(
            instrument="BTCUSD", broker_profile="EXNESS_STANDARD",
            strategy_id=STRATEGY_ID, timeframe="15m", higher_timeframes=("1h",),
            start_date=pd.Timestamp("2026-01-01", tz="UTC"),
            end_date=pd.Timestamp(end, tz="UTC"), dataset_role=DatasetRole.PAPER,
            spread_source="BROKER_NATIVE_PER_BAR", notes="stage3 replay determinism")
        return export(EXNESS_M15, config, out, verify=False)

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        short = run("2026-01-25", Path(tmp) / "short.csv")
        long = run("2026-02-10", Path(tmp) / "long.csv")
    shared = short[KEY]
    overlap = long[long[KEY].isin(shared)].reset_index(drop=True)
    assert len(overlap) == len(short) > 2_000
    pd.testing.assert_frame_equal(short.reset_index(drop=True), overlap)


# --- EA safety and scheduling properties --------------------------------------------------------


def test_the_ea_never_evaluates_a_forming_bar():
    assert static_check()["never_processes_forming_bar"] is True


def test_the_ea_backfills_every_missed_closed_bar():
    report = static_check()
    assert report["closed_bar_scheduler_present"] is True
    assert report["backfills_missed_bars"] is True


def test_the_ea_refuses_duplicate_and_reversed_bars():
    report = static_check()
    assert report["rejects_duplicate_bar"] is True
    assert report["rejects_time_reversal"] is True


def test_the_ea_emits_each_bar_exactly_once():
    assert static_check()["exactly_once_emission"] is True


def test_the_ea_recovers_by_replay_and_halts_if_the_anchor_is_lost():
    report = static_check()
    assert report["replays_from_fixed_anchor"] is True
    assert report["halts_if_anchor_unreachable"] is True


def test_a_live_restart_cannot_truncate_forward_evidence():
    assert static_check()["live_run_appends_audit"] is True


def test_stage_2_tester_semantics_are_preserved():
    """Certified windows must stay reproducible bar for bar."""
    assert static_check()["tester_path_preserved"] is True


def test_the_ea_records_full_run_identity():
    assert static_check()["records_run_identity"] is True


def test_the_ea_tracks_connectivity_and_logs_operational_events():
    report = static_check()
    assert report["tracks_connectivity"] is True
    assert report["logs_operational_events"] is True


def test_stage3_runtime_files_do_not_touch_the_76_column_schema():
    report = static_check()
    assert report["stage3_files_separate_from_audit_schema"] is True
    assert report["header_columns"] == 76
    assert report["header_matches_python_schema"] is True


def test_no_order_transmission_path_exists_anywhere():
    """The single most important property of Stage 3."""
    report = static_check()
    assert report["forbidden_calls"] == []
    assert report["has_execution_guard"] is True
    assert report["default_mode_is_audit_only"] is True


def test_stage3_tooling_contains_no_order_transmission_call():
    forbidden = ("OrderSend", "PositionOpen", "PositionClose", "CTrade",
                 "order_send", "place_order")
    for name in ("stage3.py", "stage3_forward.py", "stage3_gate.py"):
        source = (ROOT / "tools" / name).read_text()
        for token in forbidden:
            assert token not in source, f"{name} references {token}"


def test_the_build_timestamp_is_converted_explicitly():
    """__DATETIME__ is a datetime; assigning it to a string is an implicit cast.

    MetaEditor warns on it. The explicit TimeToString call produces the same
    "YYYY.MM.DD HH:MM:SS" text, so the recorded build identity is unchanged.
    """
    source = (ROOT / "mt5" / "BTC_V3_Core_V1.mq5").read_text()
    assert "TimeToString(__DATETIME__,\n" in source
    assert "TIME_DATE|TIME_MINUTES|TIME_SECONDS)" in source
    assert static_check()["no_implicit_datetime_to_string"] is True


# --- session bring-up -------------------------------------------------------------------------
#
# The first live Stage 3 start halted with ANCHOR_UNREACHABLE. The anchor was
# placed at bar InpMaxReplayBars-1, and the reachability loop could only confirm
# bars strictly older than the anchor, which it could never reach. Every first
# start halted, at any input value.


def test_the_anchor_bar_itself_is_reachable_and_replayed():
    report = static_check()
    assert report["anchor_bar_is_reachable"] is True
    assert report["halts_if_anchor_unreachable"] is True


def test_the_reachability_walk_can_reach_an_anchor_at_the_cap():
    """The arithmetic that failed live, reproduced directly.

    shift ends one past the oldest bar to replay. With the anchor at index
    cap-1, a loop bounded by `shift < cap` that only breaks on a bar strictly
    older than the anchor runs out of room before it can confirm anything.
    """
    def walk(cap, anchor_index, inclusive):
        shift, reached = 1, False
        while (shift <= cap) if inclusive else (shift < cap):
            older = shift > anchor_index
            equal = shift == anchor_index
            if older:
                reached = True
                break
            shift += 1
            if inclusive and equal:
                reached = True
                break
        return reached, shift

    assert walk(20_000, 19_999, inclusive=False)[0] is False   # the live failure
    reached, shift = walk(20_000, 19_999, inclusive=True)
    assert reached is True
    assert shift == 20_000                                      # anchor included
    # A normal, shallow anchor works either way; the bug only bit at the cap.
    assert walk(20_000, 1_500, inclusive=True)[0] is True


def test_a_new_session_anchors_at_warmup_depth_not_the_replay_cap():
    """Anchoring at the cap would replay months on every restart."""
    assert static_check()["anchor_depth_is_warmup_based"] is True
    source = (ROOT / "mt5" / "BTC_V3_Core_V1.mq5").read_text()
    assert "input int           InpAnchorWarmupBars = 1500;" in source
    # Whatever the input says, the depth must still cover the frozen warmup.
    from tools.check_mt5_core_source import warmup_h1_bars, warmup_m15_bars
    needed = warmup_h1_bars(source) * 4 + warmup_m15_bars(source) + 64
    assert 1500 >= needed, f"default anchor depth {1500} is below warmup {needed}"


def test_a_failed_bring_up_does_not_persist_its_anchor():
    """Otherwise a plain restart resurrects the same unusable origin."""
    assert static_check()["halted_bringup_is_not_persisted"] is True


def test_starting_a_fresh_session_preserves_the_previous_evidence():
    """Evidence is renamed aside, never deleted."""
    report = static_check()
    assert report["fresh_session_rotates_not_deletes"] is True
    source = (ROOT / "mt5" / "BTC_V3_Core_V1.mq5").read_text()
    assert "input bool          InpNewSession      = false;" in source
    assert "FileDelete" not in source
    for name in ("InpLogFile", "SessionFileName()", "InpEventFile"):
        assert f"RotateStageFile({name});" in source


# --- exactly-once across restarts ---------------------------------------------------------
#
# The first live restart appended the entire 1,500-bar replay a second time.
# LastLoggedBar() opened the audit while OpenLog() already held it for writing,
# MQL5 refused the second handle, and the function returned 0 — which the
# emission gate read as "nothing logged yet". The EA recorded the moment in its
# own event log: RESTART ... "last logged bar " (empty).


def _emit(anchor_bars, already_logged, last_logged):
    """The EA's emission gate, modelled exactly.

    Replay always rebuilds state over every bar from the anchor. A bar is
    WRITTEN only when it is newer than the last bar already in the log.
    """
    written, state_rebuilt = [], []
    for bar in anchor_bars:
        state_rebuilt.append(bar)
        if last_logged is None or bar > last_logged:
            written.append(bar)
            last_logged = bar
    return written, state_rebuilt, list(already_logged) + written


BARS = [f"2026-09-{d:02d}T{h:02d}:00:00Z" for d in (5, 6, 7) for h in range(4)]


def test_a_fresh_session_emits_every_replayed_bar_once():
    written, state, log = _emit(BARS, [], None)
    assert written == BARS
    assert state == BARS
    assert len(log) == len(set(log))


def test_an_immediate_restart_emits_nothing_new():
    """The failure case: same bars, nothing closed in between."""
    _, _, log = _emit(BARS, [], None)
    written, state, log2 = _emit(BARS, log, BARS[-1])
    assert written == [], "a restart must not re-emit bars already logged"
    assert state == BARS, "state must still be rebuilt over every bar"
    assert log2 == log
    assert len(log2) == len(set(log2))


def test_the_bug_reproduced_last_logged_lost_duplicates_everything():
    """With last_logged lost, the restart appends the whole replay again."""
    _, _, log = _emit(BARS, [], None)
    written, _, log2 = _emit(BARS, log, None)          # None == the lost value
    assert written == BARS
    assert len(log2) == 2 * len(BARS)
    assert len(set(log2)) == len(BARS)
    reversals = sum(1 for i in range(1, len(log2)) if log2[i] < log2[i - 1])
    assert reversals == 1, "exactly the single reversal seen live"


def test_a_restart_after_one_new_bar_emits_only_that_bar():
    _, _, log = _emit(BARS, [], None)
    new = "2026-09-07T04:00:00Z"
    written, state, log2 = _emit(BARS + [new], log, BARS[-1])
    assert written == [new]
    assert state == BARS + [new]
    assert len(log2) == len(set(log2)) == len(BARS) + 1


def test_a_restart_after_several_missed_bars_emits_each_of_them_once():
    """Bars that closed while MT5 was down must still be emitted, exactly once."""
    _, _, log = _emit(BARS, [], None)
    missed = [f"2026-09-07T{h:02d}:00:00Z" for h in (4, 5, 6)]
    written, state, log2 = _emit(BARS + missed, log, BARS[-1])
    assert written == missed
    assert state == BARS + missed
    assert len(log2) == len(set(log2)) == len(BARS) + 3


def test_no_restart_sequence_produces_a_duplicate_or_a_reversal():
    log, last = [], None
    for extra in (0, 0, 1, 0, 3, 2, 0):
        bars = BARS + [f"2026-09-08T{h:02d}:00:00Z" for h in range(extra)]
        _, state, log = _emit(bars, log, last)
        last = log[-1] if log else None
        assert state == bars, "every restart rebuilds state over the full replay"
    assert len(log) == len(set(log)), "no duplicate audit rows"
    assert all(log[i] > log[i - 1] for i in range(1, len(log))), "no time reversal"


def test_state_after_restart_is_identical_to_an_uninterrupted_run():
    uninterrupted, _, _ = _emit(BARS, [], None)
    _, restarted_state, _ = _emit(BARS, list(BARS), BARS[-1])
    assert restarted_state == uninterrupted == BARS


# --- the EA properties that make the above true ------------------------------------------------


def test_the_last_logged_bar_is_recovered_before_the_log_is_opened_for_writing():
    report = static_check()
    assert report["recovers_last_logged_before_opening_log"] is True
    source = (ROOT / "mt5" / "BTC_V3_Core_V1.mq5").read_text()
    assert source.index("LastLoggedBar(g_last_logged)") < source.index("if(!OpenLog())")


def test_an_unreadable_audit_log_halts_rather_than_reporting_it_empty():
    report = static_check()
    assert report["unreadable_log_halts"] is True
    assert report["distinguishes_absent_log_from_unreadable"] is True


def test_a_disagreement_between_session_file_and_audit_is_reported():
    assert static_check()["session_audit_skew_is_reported"] is True
