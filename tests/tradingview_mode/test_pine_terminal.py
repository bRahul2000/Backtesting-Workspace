"""Pine scripts inside TradingView Mode: editor events, payload, replay safety."""
import copy
import dataclasses

import pytest

from ui.tradingview_mode.component import pine_bridge as PB
from ui.tradingview_mode.component import replay as replay_model
from ui.tradingview_mode.component import terminal as T
from ui.tradingview_mode.component.protocol import PayloadValidationError, parse_event, validate_payload
from ui.tradingview_mode.component.state import TerminalState, apply_event
from ui.tradingview_mode.pine.examples import EXAMPLES

_ids = iter(range(10**9))
MA = EXAMPLES["Moving-average crossover"]
GAPS = EXAMPLES["Uses unimplemented features"]


def ev(kind, **data):
    return parse_event({"id": f"p-{next(_ids)}", "type": kind, "data": data})


def pine_state(*sources):
    state, session = TerminalState(dataset_key="EXNESS_XAUUSDM_M15", timeframe="15m"), {}
    for source in sources:
        state, log = PB.handle_pine_event(ev("pine_add", source=source), state, session)
        assert log.level == "info", log.message
    return state, session


def payload_for(state, session, frame=None, replay_status=None):
    selected, resolution, full = T._load(state)
    frame = full.iloc[-400:].reset_index(drop=True) if frame is None else frame
    notices = []
    import streamlit as st
    st.session_state.clear()
    st.session_state.update(session)
    pine = T.pine_section(state, frame, selected, None, replay_status, resolution.target_seconds, notices)
    session.update(dict(st.session_state))
    return T.build_terminal_payload(state=state, selected=selected, resolution=resolution, frame=frame, bounds=None,
                                    shown=None, logs=[], notices=notices, watchlist=[], replay_status=replay_status,
                                    pine=pine), notices


def test_compile_add_update_toggle_input_remove():
    state, session = TerminalState(dataset_key="EXNESS_XAUUSDM_M15", timeframe="15m"), {}
    same, log = PB.handle_pine_event(ev("pine_compile", source=MA), state, session)
    assert same == state and session[PB.EDITOR_KEY]["ok"] is True and "ready to add" in log.message
    assert [i["title"] for i in session[PB.EDITOR_KEY]["inputs"]] == ["Fast length", "Slow length"]
    state, log = PB.handle_pine_event(ev("pine_add", source=MA), state, session)
    assert [s.id for s in state.pine] == ["pine-1"] and state.pine[0].title == "MA crossover"
    state, log = PB.handle_pine_event(ev("pine_set_input", id="pine-1", index=0, value=5), state, session)
    assert state.pine[0].inputs == ((0, 5),)
    same, log = PB.handle_pine_event(ev("pine_set_input", id="pine-1", index=0, value=0), state, session)
    assert same == state and log.level == "error" and ">= 1" in log.message          # minval enforced
    same, log = PB.handle_pine_event(ev("pine_set_input", id="pine-1", index=9, value=1), state, session)
    assert same == state and "no input #9" in log.message
    state, _ = PB.handle_pine_event(ev("pine_toggle", id="pine-1", enabled=False), state, session)
    assert state.pine[0].enabled is False
    state, log = PB.handle_pine_event(ev("pine_update", id="pine-1", source=EXAMPLES["RSI with bands"]), state, session)
    assert state.pine[0].title == "RSI with bands" and state.pine[0].inputs == () and "inputs reset" in log.message
    state, _ = PB.handle_pine_event(ev("pine_remove", id="pine-1"), state, session)
    assert state.pine == ()


def test_scripts_with_gaps_or_errors_are_not_added_and_say_why():
    state, session = TerminalState(dataset_key="EXNESS_XAUUSDM_M15", timeframe="15m"), {}
    same, log = PB.handle_pine_event(ev("pine_add", source=GAPS), state, session)
    assert same == state and log.level == "error"
    assert log.message == ("Rejected: Pine script not added. Line 3: `request.security_lower_tf()` is not implemented "
                           "yet (data requests).")
    editor = session[PB.EDITOR_KEY]
    assert editor["ok"] is False and {d["kind"] for d in editor["diagnostics"]} == {"gap"}
    assert [d["line"] for d in editor["diagnostics"]] == [3, 6]
    same, log = PB.handle_pine_event(ev("pine_add", source="//@version=5\nindicator('x')\nplot(nope)"), state, session)
    assert same == state and "Undeclared identifier `nope`" in log.message


def test_payload_carries_outputs_on_chart_bars_and_passes_the_contract():
    state, session = pine_state(MA, EXAMPLES["RSI with bands"])
    payload, notices = payload_for(state, session)
    assert not notices
    scripts = payload["pine"]["scripts"]
    assert [s["title"] for s in scripts] == ["MA crossover", "RSI with bands"] and scripts[0]["overlay"] is True
    kinds = [o["kind"] for o in scripts[0]["outputs"]]
    assert kinds == ["plot", "plot", "fill", "shape", "shape"]
    bar_times = {bar["time"] for bar in payload["bars"]}
    assert all(p["time"] in bar_times for s in scripts for o in s["outputs"] for p in o.get("data", []))
    assert scripts[0]["bars"] == 400 and scripts[0]["executed"] == 400
    again, _ = payload_for(state, session)
    assert again["pine"]["scripts"][0]["executed"] == 0          # rerun with the same bars executes nothing
    assert payload["pine"]["examples"] and payload["pine"]["compat"]["counts"]["gap"] > 0
    broken = copy.deepcopy(payload)
    broken["pine"]["scripts"][0]["outputs"][0]["data"][0]["time"] += 1
    with pytest.raises(PayloadValidationError, match="is not a chart bar"):
        validate_payload(broken)
    broken = copy.deepcopy(payload)
    broken["pine"]["scripts"][0]["outputs"][2]["between"] = ["x", "y"]
    with pytest.raises(PayloadValidationError, match="fill must reference"):
        validate_payload(broken)


def test_input_override_changes_the_output():
    state, session = pine_state(MA)
    before, _ = payload_for(state, session)
    state, _ = PB.handle_pine_event(ev("pine_set_input", id="pine-1", index=0, value=3), state, session)
    after, _ = payload_for(state, session)
    fast_before = before["pine"]["scripts"][0]["outputs"][0]["data"][-1]["value"]
    fast_after = after["pine"]["scripts"][0]["outputs"][0]["data"][-1]["value"]
    assert fast_before != fast_after and after["pine"]["scripts"][0]["inputs"][0]["value"] == 3


def test_replay_runs_pine_on_revealed_bars_only():
    state, session = pine_state(MA)
    selected, resolution, frame = T._load(state)
    times = replay_model.frame_times(frame)
    ctx = T.context_for(T._bounds(frame), times)
    replaying, _ = apply_event(state, ev("enter_replay", start="2026-06-10T14:30"), ctx)
    revealed = replay_model.revealed(frame, replaying.replay)
    status = replay_model.info(replaying.replay, times)
    payload, _ = payload_for(replaying, session, revealed, status)
    cursor = status["cursor_timestamp"]
    outputs = payload["pine"]["scripts"][0]["outputs"]
    assert max(p["time"] for o in outputs for p in o.get("data", [])) <= cursor
    assert payload["mode"] == "replay"
    stepped, _ = apply_event(replaying, ev("step_forward"), ctx)
    payload2, _ = payload_for(stepped, session, replay_model.revealed(frame, stepped.replay), replay_model.info(stepped.replay, times))
    assert payload2["pine"]["scripts"][0]["executed"] == 1         # one new bar, executed incrementally


def test_runtime_errors_become_notices_not_crashes():
    source = "//@version=5\nindicator('boom')\nif bar_index == 5\n    runtime.error('stop here')\nplot(close)"
    state, session = pine_state(source)
    payload, notices = payload_for(state, session)
    script = payload["pine"]["scripts"][0]
    assert script["error"]["message"] == "runtime.error: stop here" and script["error"]["bar_index"] == 5
    assert any("Pine `boom`" in n["message"] for n in notices) and script["outputs"] == []


def test_historical_payload_without_scripts_is_unchanged_in_shape():
    state = TerminalState(dataset_key="EXNESS_XAUUSDM_M15", timeframe="15m")
    selected, resolution, frame = T._load(state)
    payload = T.build_terminal_payload(state=state, selected=selected, resolution=resolution,
                                       frame=frame.iloc[-100:].reset_index(drop=True), bounds=None, shown=None, logs=[],
                                       notices=[], watchlist=[])
    assert payload["pine"] is None and payload["mode"] == "historical"
