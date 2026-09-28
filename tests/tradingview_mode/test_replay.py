"""Historical bar replay: Python reveals bars up to the cursor and nothing after it."""
import copy
import json

import numpy as np
import pandas as pd
import pytest

from services.market_datasets import dataset
from strategies.registry import discover_builtin_strategies
from ui.tradingview_mode.component import replay as R
from ui.tradingview_mode.component import tester
from ui.tradingview_mode.component.protocol import EventValidationError, PayloadValidationError, parse_event, validate_payload
from ui.tradingview_mode.component.state import IndicatorInstance, TerminalState, apply_event
from ui.tradingview_mode.component.terminal import (
    _bounds, _load, build_terminal_payload, consume_event, context_for, dataset_bounds, empty_tester_session,
    handle_tester_event, tester_presentation as build_tester_section,
)
from ui.tradingview_mode.indicators import calculate_indicator

ALL_INDICATORS = (
    IndicatorInstance("ema-1", "ema", {"length": 20}, True, "#f5a623"),
    IndicatorInstance("sma-2", "sma", {"length": 50}, True, "#4aa3ff"),
    IndicatorInstance("vwap-3", "vwap", {}, True, "#c678dd"),
    IndicatorInstance("bb-4", "bb", {"length": 20, "stddev": 2.0}, True, "#56d4bc"),
    IndicatorInstance("rsi-5", "rsi", {"length": 14}, True, "#e5c07b"),
    IndicatorInstance("macd-6", "macd", {"fast": 12, "slow": 26, "signal": 9}, True, "#ff7a90"),
    IndicatorInstance("atr-7", "atr", {"length": 14}, True, "#98c379"),
)
_counter = iter(range(10**9))


def ev(kind, **data):
    return parse_event({"id": f"t-{next(_counter)}", "type": kind, "data": data})


def setup(key="EXNESS_BTCUSDM_M15", timeframe="15m", start="2026-06-10T14:37"):
    state = TerminalState(dataset_key=key, timeframe=timeframe, indicators=ALL_INDICATORS)
    selected, resolution, frame = _load(state)
    times = R.frame_times(frame)
    ctx = context_for(_bounds(frame), times)
    state, log = apply_event(state, ev("enter_replay", start=start), ctx)
    assert state.replay is not None, log.message
    return state, ctx, selected, resolution, frame, times


def payload_for(state, selected, resolution, frame, *, run=None, history=()):
    """Build the payload exactly as the terminal does, tester section included."""
    status = R.info(state.replay, R.frame_times(frame)) if state.replay else None
    shown_frame = R.revealed(frame, state.replay) if state.replay else frame.iloc[-500:].reset_index(drop=True)
    session = {**empty_tester_session(), "status": "completed" if run else "idle", "run": run, "history": list(history)}
    return build_terminal_payload(
        state=state, selected=selected, resolution=resolution, frame=shown_frame, bounds=_bounds(frame),
        shown=None, logs=[], notices=[], watchlist=[], replay_status=status,
        tester_payload=build_tester_section(session, discover_builtin_strategies(), status, resolution.target_seconds))


def all_times(payload):
    times = [bar["time"] for bar in payload["bars"]]
    for group in ("overlays", "panes"):
        for item in payload[group]:
            for series in item["series"]:
                times += [point["time"] for point in series["data"]]
    return times


# ---- 1-2. initialization and alignment ------------------------------------------

def test_replay_initialization_snapshots_dataset_and_timeframe():
    state, _, _, _, _, times = setup()
    replay = state.replay
    assert (replay.dataset_key, replay.timeframe, replay.playing, replay.speed) == ("EXNESS_BTCUSDM_M15", "15m", False, 1)
    info = R.info(replay, times)
    assert info["at_start"] and not info["at_end"] and info["total_available_bars"] == len(times)
    assert info["revealed_bar_count"] == R.CONTEXT_BARS + 1


def test_start_resolves_to_the_bar_at_or_before_the_requested_utc_time():
    times = np.array([0, 900, 1800, 2700], dtype=np.int64)
    assert R.align(times, 1799) == 1 and R.align(times, 1800) == 2 and R.align(times, 10**9) == 3
    with pytest.raises(R.ReplayError, match="before the first bar"):
        R.align(times, -1)
    state, *_ = setup(start="2026-06-10T14:37")
    assert state.replay.cursor_timestamp == int(pd.Timestamp("2026-06-10 14:30", tz="UTC").timestamp())
    exact, *_ = setup(start="2026-06-10T14:45")
    assert exact.replay.cursor_timestamp == int(pd.Timestamp("2026-06-10 14:45", tz="UTC").timestamp())


# ---- 3. no future bars -------------------------------------------------------------

def test_no_bar_or_indicator_value_after_the_cursor_is_serialized():
    state, _, selected, resolution, frame, _ = setup()
    payload = payload_for(state, selected, resolution, frame)
    cursor = payload["replay"]["cursor_timestamp"]
    assert max(all_times(payload)) == cursor == payload["bars"][-1]["time"]
    assert {"at_end", "cursor_timestamp", "total_available_bars"} <= set(payload["replay"])
    json.dumps(payload, allow_nan=False)


def test_payload_validation_rejects_any_future_value():
    state, _, selected, resolution, frame, _ = setup()
    payload = payload_for(state, selected, resolution, frame)
    leaked = copy.deepcopy(payload)
    leaked["bars"].append({**leaked["bars"][-1], "time": leaked["bars"][-1]["time"] + 900})
    with pytest.raises(PayloadValidationError, match="end exactly at the cursor"):
        validate_payload(leaked)
    leaked = copy.deepcopy(payload)
    leaked["panes"][0]["series"][0]["data"].append({"time": payload["replay"]["cursor_timestamp"] + 900, "value": 1.0})
    with pytest.raises(PayloadValidationError):
        validate_payload(leaked)


# ---- 4-7. stepping and boundaries ----------------------------------------------------

def test_step_forward_reveals_exactly_one_bar_and_step_backward_removes_it():
    state, ctx, selected, resolution, frame, _ = setup()
    before = payload_for(state, selected, resolution, frame)
    forward, _ = apply_event(state, ev("step_forward"), ctx)
    after = payload_for(forward, selected, resolution, frame)
    assert len(after["bars"]) == len(before["bars"]) + 1
    assert after["bars"][:-1] == before["bars"]
    assert after["bars"][-1]["time"] == before["bars"][-1]["time"] + 900
    back, _ = apply_event(forward, ev("step_backward"), ctx)
    assert payload_for(back, selected, resolution, frame)["bars"] == before["bars"]


def test_start_boundary_blocks_previous():
    state, ctx, *_ = setup()
    same, log = apply_event(state, ev("step_backward"), ctx)
    assert same == state and log.level == "error" and "start bar" in log.message


def test_end_boundary_blocks_next_and_stops_playback():
    state, ctx, _, _, _, times = setup()
    end, _ = apply_event(state, ev("jump_replay", to="2099-01-01T00:00"), ctx)
    assert end.replay.cursor_timestamp == int(times[-1]) and R.info(end.replay, times)["at_end"]
    same, log = apply_event(end, ev("step_forward"), ctx)
    assert same == end and log.level == "error"
    playing = TerminalState(**{**end.__dict__, "replay": R.ReplayState(**{**end.replay.__dict__, "playing": True})})
    stopped, log = apply_event(playing, ev("step_forward"), ctx)
    assert not stopped.replay.playing and stopped.replay.cursor_timestamp == int(times[-1])
    refused, log = apply_event(end, ev("play_replay"), ctx)
    assert refused == end and log.level == "error"


# ---- 8-10. indicators use revealed data only ------------------------------------------

def test_indicators_equal_a_calculation_on_the_revealed_history():
    state, ctx, selected, resolution, frame, times = setup()
    state, _ = apply_event(state, ev("step_forward"), ctx)
    payload = payload_for(state, selected, resolution, frame)
    anchor, cursor = R.index_of(times, state.replay.anchor_timestamp), R.index_of(times, state.replay.cursor_timestamp)
    history = frame.iloc[anchor:cursor + 1].reset_index(drop=True)
    items = {item["id"]: item for item in payload["overlays"] + payload["panes"]}
    for instance in ALL_INDICATORS:
        expected = calculate_indicator(history, instance.key, instance.params)
        for series in items[instance.id]["series"]:
            last = series["data"][-1]
            assert last["time"] == state.replay.cursor_timestamp
            assert last["value"] == pytest.approx(float(expected[series["name"]].iloc[-1]), rel=0, abs=1e-12), instance.id


def _perturb_future(frame, cursor_ts):
    future = frame["timestamp"] > pd.Timestamp(cursor_ts, unit="s", tz="UTC")
    changed = frame.copy()
    for column in ("open", "high", "low", "close"):
        changed.loc[future, column] = changed.loc[future, column] * 3.7 + 11.0
    changed.loc[future, "volume"] = changed.loc[future, "volume"] * 50 + 1
    return changed


@pytest.mark.parametrize("timeframe, start", [("15m", "2026-06-10T14:37"), ("4h", "2026-03-04T10:00")])
def test_changing_future_bars_changes_nothing_that_is_sent(timeframe, start):
    """The strongest leakage check: rewrite every bar after the cursor and the
    payload (bars, VWAP, bands, RSI/MACD/ATR panes, volume) must be identical."""
    state, _, selected, resolution, frame, _ = setup(timeframe=timeframe, start=start)
    original = payload_for(state, selected, resolution, frame)
    perturbed = payload_for(state, selected, resolution, _perturb_future(frame, state.replay.cursor_timestamp))
    assert json.dumps(original, sort_keys=True) == json.dumps(perturbed, sort_keys=True)


def test_vwap_session_uses_only_revealed_bars_of_the_day():
    state, _, selected, resolution, frame, times = setup(start="2026-06-10T14:37")
    payload = payload_for(state, selected, resolution, frame)
    vwap = next(o for o in payload["overlays"] if o["key"] == "vwap")["series"][0]["data"][-1]
    day = frame[(frame["timestamp"] >= pd.Timestamp("2026-06-10", tz="UTC"))
                & (frame["timestamp"] <= pd.Timestamp("2026-06-10 14:30", tz="UTC"))]
    typical = (day["high"] + day["low"] + day["close"]) / 3
    assert vwap["value"] == pytest.approx(float((typical * day["volume"]).sum() / day["volume"].sum()), abs=1e-9)


# ---- 11-15. events --------------------------------------------------------------------

def test_replay_events_apply_exactly_once():
    state, ctx, *_ = setup()
    raw = {"id": "dup-step", "type": "step_forward", "data": {}}
    once, _, last, _ = consume_event(state, raw, ctx, None)
    again, _, _, _ = consume_event(once, raw, ctx, last)
    assert again == once and once.replay.cursor_timestamp == state.replay.cursor_timestamp + 900


def test_play_pause_and_speed():
    state, ctx, *_ = setup()
    playing, _ = apply_event(state, ev("play_replay"), ctx)
    assert playing.replay.playing
    fast, _ = apply_event(playing, ev("set_replay_speed", speed=10), ctx)
    assert fast.replay.speed == 10 and fast.replay.playing
    paused, _ = apply_event(fast, ev("pause_replay"), ctx)
    assert not paused.replay.playing and paused.replay.speed == 10
    for bad in (3, 0, 10.0, "5", True):
        with pytest.raises(EventValidationError):
            parse_event({"id": "s", "type": "set_replay_speed", "data": {"speed": bad}})


def test_jump_moves_cursor_and_start_when_earlier():
    state, ctx, _, _, _, times = setup(start="2026-06-10T14:37")
    later, _ = apply_event(state, ev("jump_replay", to="2026-07-01T09:10"), ctx)
    assert later.replay.cursor_timestamp == int(pd.Timestamp("2026-07-01 09:00", tz="UTC").timestamp())
    assert later.replay.start_timestamp == state.replay.start_timestamp and not later.replay.playing
    earlier, _ = apply_event(later, ev("jump_replay", to="2026-05-01T00:00"), ctx)
    assert earlier.replay.start_timestamp == earlier.replay.cursor_timestamp
    restarted, _ = apply_event(later, ev("set_replay_start", start="2026-06-20T00:00"), ctx)
    assert restarted.replay.start_timestamp == restarted.replay.cursor_timestamp


def test_exit_restores_the_historical_view():
    state, ctx, selected, resolution, frame, _ = setup()
    historical, log = apply_event(state, ev("exit_replay"), ctx)
    assert historical.replay is None and "restored" in log.message
    payload = payload_for(historical, selected, resolution, frame)
    assert payload["replay"] == {"enabled": False}
    assert payload["bars"][-1]["time"] == int(R.frame_times(frame)[-1])
    assert not payload["view_key"].endswith("|replay")


def test_replay_events_require_replay_and_changes_of_market_are_blocked():
    plain = TerminalState(dataset_key="EXNESS_BTCUSDM_M15", timeframe="15m")
    same, log = apply_event(plain, ev("step_forward"), context_for())
    assert same == plain and "requires Replay" in log.message
    state, ctx, *_ = setup()
    for kind, data in (("select_timeframe", {"timeframe": "1h"}), ("select_dataset", {"dataset_key": "EXNESS_BTCUSDM_H1"}),
                       ("select_watchlist_item", {"dataset_key": "EXNESS_XAUUSDM_M15"}),
                       ("set_date_range", {"start": "2026-01-01", "end": "2026-02-01"})):
        blocked, log = apply_event(state, ev(kind, **data), ctx)
        assert blocked == state and "exit Replay" in log.message


# ---- 16-17. no mutation -------------------------------------------------------------------

def test_replay_does_not_mutate_the_source_dataframe():
    state, ctx, selected, resolution, frame, _ = setup()
    before = frame.copy(deep=True)
    payload_for(state, selected, resolution, frame)
    apply_event(state, ev("step_forward"), ctx)
    R.revealed(frame, state.replay)
    pd.testing.assert_frame_equal(frame, before)


@pytest.fixture(scope="module")
def backtest(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setattr(tester, "SCRATCH_LEDGER_PATH", tmp_path_factory.mktemp("ledger") / "scratch.sqlite3")
    try:
        run = tester.validate_run_request(
            {"strategy_id": "BTC_V3_CORE_V1_FROZEN", "dataset_key": "EXNESS_BTCUSDM_M15", "broker_profile": "EXNESS_STANDARD",
             "dataset_role": "DEVELOPMENT", "start": "2025-09-01", "end": "2026-09-20", "ledger_mode": "scratch"},
            registry=discover_builtin_strategies(), lookup_dataset=dataset, bounds=dataset_bounds)
        result = tester.execute_run(run)
    finally:
        mp.undo()
    return run, result, tester.build_run_payload(result, run, duration_seconds=1.0)


def test_replay_does_not_mutate_the_backtest_result(backtest):
    _, result, run_payload = backtest
    state, _, selected, resolution, frame, _ = setup(start="2026-06-10T14:37")
    before_result, before_payload = copy.deepcopy(result.as_dict()), copy.deepcopy(run_payload)
    payload_for(state, selected, resolution, frame, run=run_payload)
    assert result.as_dict() == before_result and run_payload == before_payload


# ---- 18-19. trade markers / SL-TP ------------------------------------------------------------

def test_trade_markers_and_sl_tp_only_for_trades_closed_by_the_cursor(backtest):
    _, _, run_payload = backtest
    state, _, selected, resolution, frame, _ = setup(start="2026-06-10T14:37")
    payload = payload_for(state, selected, resolution, frame, run=run_payload)
    cursor = payload["replay"]["cursor_timestamp"]
    placed = {item["key"] for item in payload["trade_overlay"]["trades"]}
    first_bar = payload["bars"][0]["time"]
    expected = {t["key"] for t in run_payload["trades"] if t["entry_time"] >= first_bar and t["exit_time"] < cursor + 900}
    assert placed == expected and placed
    assert all(run_payload["trades"][key]["exit_time"] < cursor + 900 for key in placed)
    later = [t for t in run_payload["trades"] if t["exit_time"] >= cursor + 900]
    assert later and not placed & {t["key"] for t in later}
    for item in payload["trade_overlay"]["trades"]:  # SL/TP segments are drawn between these bars only
        assert item["entry_bar"] <= item["exit_bar"] <= cursor
    leaked = copy.deepcopy(payload)
    leaked["trade_overlay"]["trades"].append({"key": later[0]["key"], "entry_bar": cursor, "exit_bar": cursor + 900})
    with pytest.raises(PayloadValidationError):
        validate_payload(leaked)


# ---- 20-22. UTC and identities ----------------------------------------------------------------

def test_replay_times_are_utc():
    assert R.parse_utc("2026-06-10T14:30") == R.parse_utc("2026-06-10T14:30Z") == 1781101800
    for bad in ("2026-06-10 14:30", "2026-06-10T14:30+02:00", "10/06/2026 14:30"):
        with pytest.raises(EventValidationError):
            parse_event({"id": "u", "type": "enter_replay", "data": {"start": bad}})
    state, _, selected, resolution, frame, _ = setup()
    payload = payload_for(state, selected, resolution, frame)
    assert all(type(bar["time"]) is int for bar in payload["bars"])
    assert pd.Timestamp(payload["replay"]["cursor_timestamp"], unit="s", tz="UTC") == pd.Timestamp("2026-06-10 14:30", tz="UTC")


def test_provider_and_timeframe_identity_are_preserved():
    for key, timeframe, start, step in (("EXNESS_BTCUSDM_M15", "15m", "2026-06-10T14:37", 900),
                                        ("EXNESS_BTCUSDM_M15", "4h", "2026-03-04T10:00", 14_400),
                                        ("BITSTAMP_BTCUSD_15M", "15m", "2026-01-05T08:07", 900)):
        state, ctx, selected, resolution, frame, _ = setup(key=key, timeframe=timeframe, start=start)
        state, _ = apply_event(state, ev("step_forward"), ctx)
        payload = payload_for(state, selected, resolution, frame)
        assert (payload["dataset_key"], payload["provider"], payload["timeframe"]) == (key, dataset(key).broker, timeframe)
        assert payload["source"]["provider"] == dataset(key).broker
        assert state.replay.dataset_key == key and state.replay.timeframe == timeframe
        assert payload["replay"]["cursor_timestamp"] % step == 0
        assert payload["bars"][-1]["time"] - payload["bars"][-2]["time"] == step


# ---- Strategy Tester during Replay: only what was knowable by the cursor ----------------

HISTORY_ROW = {"history_id": 1, "run_id": "BT-1", "ledger_mode": "scratch", "strategy": "S", "instrument": "BTCUSD",
               "dataset": "D", "start": "2025-09-01", "end": "2026-09-20", "total_trades": 57, "pnl": -89.15,
               "win_rate": 22.8}


def _replay_with_open_trade(run_payload):
    """Cursor inside a trade that is open across it (entered before, exits later)."""
    trade = next(t for t in run_payload["trades"][10:] if t["exit_time"] - t["entry_time"] >= 4 * 900)
    cursor = pd.Timestamp(trade["entry_time"] + 900, unit="s", tz="UTC")
    state, ctx, selected, resolution, frame, times = setup(start=cursor.strftime("%Y-%m-%dT%H:%M"))
    return state, ctx, selected, resolution, frame, trade


def test_replay_tester_hides_future_trades_and_open_trade_outcomes(backtest):
    _, _, run_payload = backtest
    state, _, selected, resolution, frame, open_trade = _replay_with_open_trade(run_payload)
    payload = payload_for(state, selected, resolution, frame, run=run_payload)
    knowable = payload["replay"]["cursor_timestamp"] + 900
    shown = {t["key"]: t for t in payload["tester"]["run"]["trades"]}
    # 1. future trades (entered after the cursor bar) are absent
    future = [t for t in run_payload["trades"] if t["entry_time"] >= knowable]
    assert future and not set(shown) & {t["key"] for t in future}
    # 2. the open trade shows entry facts only
    opened = shown[open_trade["key"]]
    assert opened["status"] == "open"
    assert not {"exit_time", "exit_price", "exit_reason", "exit_label", "pnl", "pnl_percent", "r_multiple",
                "bars_held", "exit_commission"} & set(opened)
    assert (opened["entry_price"], opened["stop_loss"], opened["take_profit"]) == (
        open_trade["entry_price"], open_trade["stop_loss"], open_trade["take_profit"])
    text = json.dumps(payload["tester"])
    assert repr(open_trade["pnl"]) not in text and repr(open_trade["pnl_percent"]) not in text
    if open_trade["exit_price"] not in (open_trade["stop_loss"], open_trade["take_profit"]):
        assert repr(open_trade["exit_price"]) not in text  # an SL/TP exit price equals a level known at entry
    # 3. trades closed before the cursor remain, exactly
    closed = [t for t in run_payload["trades"] if t["exit_time"] < knowable]
    assert closed and all(shown[t["key"]] == {**t, "status": "closed"} for t in closed)
    # counts only of what is shown; nothing reveals how many trades come later
    assert payload["tester"]["run"]["replay_view"]["closed_trades"] == len(closed)
    assert "hidden_trades" not in payload["tester"]["run"]["replay_view"]


def test_future_trades_cannot_be_selected_or_drawn(backtest):
    _, _, run_payload = backtest
    state, _, selected, resolution, frame, open_trade = _replay_with_open_trade(run_payload)
    payload = payload_for(state, selected, resolution, frame, run=run_payload)
    selectable = {t["key"] for t in payload["tester"]["run"]["trades"]}
    drawn = {item["key"] for item in payload["trade_overlay"]["trades"]}
    knowable = payload["replay"]["cursor_timestamp"] + 900
    assert drawn <= {t["key"] for t in payload["tester"]["run"]["trades"] if t["status"] == "closed"}
    assert open_trade["key"] in selectable and open_trade["key"] not in drawn
    assert not selectable & {t["key"] for t in run_payload["trades"] if t["entry_time"] >= knowable}


def test_overview_and_performance_statistics_are_hidden_in_replay(backtest):
    _, _, run_payload = backtest
    state, _, selected, resolution, frame, _ = setup(start="2026-06-10T14:37")
    payload = payload_for(state, selected, resolution, frame, run=run_payload, history=[HISTORY_ROW])
    run = payload["tester"]["run"]
    for aggregate in ("summary", "curves", "periods", "directional", "python_derived", "diagnostics", "open_positions"):
        assert aggregate not in run, aggregate
    assert run["replay_view"]["message"] == tester.HIDDEN_DURING_REPLAY
    assert payload["tester"]["history"] == [{k: v for k, v in HISTORY_ROW.items() if k not in ("total_trades", "pnl", "win_rate")}]
    for monthly in run_payload["periods"]["monthly"]:
        assert f'"{monthly["period"]}"' not in json.dumps(payload["tester"])


def test_changing_post_cursor_outcomes_changes_nothing_in_the_replay_tester(backtest):
    """Rewrite every outcome after the cursor and every whole-run aggregate: the
    replay tester payload must be identical."""
    _, _, run_payload = backtest
    state, _, selected, resolution, frame, _ = _replay_with_open_trade(run_payload)
    original = payload_for(state, selected, resolution, frame, run=run_payload)
    knowable = original["replay"]["cursor_timestamp"] + 900
    altered = copy.deepcopy(run_payload)
    for trade in altered["trades"]:
        if trade["exit_time"] >= knowable:
            trade.update(exit_price=1.0, pnl=12345.0, pnl_percent=99.0, r_multiple=42.0, exit_reason="Take profit",
                         exit_label="TP", bars_held=999, exit_commission=7.0, exit_time=trade["exit_time"] + 3600)
    altered["summary"] = {**altered["summary"], "pnl": 1e9, "win_rate": 100.0}
    altered["periods"] = {"monthly": [], "yearly": []}
    altered["curves"]["equity"][-1]["value"] = 1e9
    altered["python_derived"] = {**altered["python_derived"], "max_winning_streak": 99}
    changed = payload_for(state, selected, resolution, frame, run=altered)
    assert json.dumps(original["tester"], sort_keys=True) == json.dumps(changed["tester"], sort_keys=True)
    assert original["trade_overlay"] == changed["trade_overlay"]


def test_replay_view_does_not_mutate_the_stored_result(backtest):
    _, result, run_payload = backtest
    before_result, before_payload = copy.deepcopy(result.as_dict()), copy.deepcopy(run_payload)
    state, _, selected, resolution, frame, _ = _replay_with_open_trade(run_payload)
    payload_for(state, selected, resolution, frame, run=run_payload, history=[HISTORY_ROW])
    tester.replay_view(run_payload, 10**10)
    assert result.as_dict() == before_result and run_payload == before_payload


def test_exiting_replay_restores_the_complete_strategy_tester_result(backtest):
    _, _, run_payload = backtest
    state, ctx, selected, resolution, frame, _ = setup(start="2026-06-10T14:37")
    historical, _ = apply_event(state, ev("exit_replay"), ctx)
    payload = payload_for(historical, selected, resolution, frame, run=run_payload, history=[HISTORY_ROW])
    assert payload["tester"]["run"] == run_payload
    assert payload["tester"]["history"] == [HISTORY_ROW]


def test_exports_are_refused_during_replay(backtest):
    run, result, run_payload = backtest
    runs = {1: {"payload": run_payload, "result": result, "run": run}}
    session = {**empty_tester_session(), "run": run_payload, "history": [HISTORY_ROW]}
    export = lambda i: parse_event({"id": f"x-{i}", "type": "export_run", "data": {"history_id": 1, "kind": "trades_csv"}})
    new, _, log, _ = handle_tester_event(export(1), session, runs,
                                         registry=discover_builtin_strategies(), replay_active=True)
    assert new["export"] is None and log.level == "error" and "Replay" in log.message
    allowed, _, _, _ = handle_tester_event(export(2), session, runs,
                                           registry=discover_builtin_strategies(), replay_active=False)
    assert allowed["export"]["content"]


def test_replay_payload_must_use_the_replay_view(backtest):
    _, _, run_payload = backtest
    state, _, selected, resolution, frame, _ = setup(start="2026-06-10T14:37")
    payload = payload_for(state, selected, resolution, frame, run=run_payload)
    leaked = copy.deepcopy(payload)
    leaked["tester"]["run"] = run_payload
    with pytest.raises(PayloadValidationError, match="replay view"):
        validate_payload(leaked)
