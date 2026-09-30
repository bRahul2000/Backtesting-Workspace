"""Strategy Tester: custom test range (it changes what the strategy evaluates, not just what the list shows), the
chart window stays independent of the test universe, range persistence/reset, and the trade-list CSV export."""
from __future__ import annotations

import csv
import io

import pandas as pd
import pytest

from ui.tradingview_mode.component import pine_bridge, protocol, tester_export
from ui.tradingview_mode.component.protocol import FrontendEvent
from ui.tradingview_mode.component.state import TerminalState

from .pine.helpers import bars
from .test_strategy_workspace import STRATEGY

N = 900


def event(kind, **data):
    return FrontendEvent(f"e-{kind}-{sorted(data.items())!r}", kind, data)


def utc(frame, i):
    return frame["timestamp"].iloc[i].strftime("%Y-%m-%dT%H:%M")


def epoch(frame, i):
    return int(frame["timestamp"].iloc[i].timestamp())


def run(state, full, *, window=(0, N - 1), session=None, export_meta=None):
    """One historical payload: the chart shows bars window[0]..window[1]; strategies see their own test range."""
    frame = full.iloc[window[0]:window[1] + 1].reset_index(drop=True)
    calc = full.iloc[:window[1] + 1].reset_index(drop=True)
    times = [epoch(frame, i) for i in range(len(frame))]
    return pine_bridge.pine_payload(
        state, calc, session if session is not None else {}, identity=("t",), timeframe_seconds=900, ticker="T",
        tickerid="T:T", mintick=0.01, mode="historical", display_from=times[0], display_to=times[-1],
        display_times=times, full_frame=full, export_meta=export_meta)


def added(session=None):
    state = TerminalState(dataset_key="EXNESS_XAUUSDM_M15", timeframe="15m")
    state, _ = pine_bridge.handle_pine_event(event("pine_add", source=STRATEGY), state, session if session is not None else {})
    return state


def test_custom_range_changes_what_the_strategy_evaluates():
    full = bars(N)
    state = added()
    whole = run(state, full)["scripts"][0]
    assert whole["test_range"] == {"mode": "full", "start": None, "end": None, "first_time": epoch(full, 0),
                                   "last_time": epoch(full, N - 1), "bars": N}
    start, end = utc(full, 300), utc(full, 599)
    state, log = pine_bridge.handle_pine_event(event("pine_set_range", id="pine-1", start=start, end=end), state, {})
    assert log.level == "info" and state.pine[0].test_range == (start, end)
    ranged = run(state, full)["scripts"][0]
    assert ranged["test_range"]["mode"] == "custom" and ranged["test_range"]["bars"] == 300
    assert ranged["strategy"]["calc_range"] == {"bars": 300, "first_time": epoch(full, 300), "last_time": epoch(full, 599)}
    trades = ranged["strategy"]["trades"]
    assert trades and all(epoch(full, 300) <= t["entry_time"] <= epoch(full, 599) for t in trades)
    assert all(t["exit_time"] is None or t["exit_time"] <= epoch(full, 599) for t in trades)
    # not a filter of the full run: the strategy started fresh at the range start (its indicators warmed up there)
    inside_full = [t for t in whole["strategy"]["trades"] if epoch(full, 300) <= t["entry_time"] <= epoch(full, 599)]
    assert [t["entry_time"] for t in trades] != [t["entry_time"] for t in inside_full] or \
        ranged["strategy"]["metrics"] != whole["strategy"]["metrics"]
    assert ranged["strategy"]["metrics"]["total_closed_trades"] <= len(trades)


def test_range_boundaries_are_inclusive_on_bar_open_time_and_open_trades_stay_open():
    full = bars(N)
    frame = pine_bridge.strategy_frame(full, (utc(full, 100), utc(full, 199)))
    assert len(frame) == 100 and frame["timestamp"].iloc[0] == full["timestamp"].iloc[100]
    assert frame["timestamp"].iloc[-1] == full["timestamp"].iloc[199]
    # a trade still open at the range end is reported open (not force-closed), like TradingView
    state = added()
    for end in range(420, 700, 7):
        state, _ = pine_bridge.handle_pine_event(event("pine_set_range", id="pine-1", start=utc(full, 0),
                                                       end=utc(full, end)), state, {})
        report = run(state, full)["scripts"][0]["strategy"]
        if any(t["open"] for t in report["trades"]):
            open_trade = next(t for t in report["trades"] if t["open"])
            assert open_trade["exit_time"] is None and open_trade["entry_time"] <= epoch(full, end)
            break
    else:
        pytest.fail("no range end fell inside a trade")


def test_chart_window_is_independent_of_the_test_range():
    full = bars(N)
    state = added()
    a = run(state, full, window=(0, N - 1))["scripts"][0]
    b = run(state, full, window=(700, 800))["scripts"][0]           # zoomed / moved chart window
    assert a["strategy"]["trades"] == b["strategy"]["trades"]         # same backtest universe
    plot = next(o for o in b["outputs"] if o["kind"] == "plot")
    assert min(p["time"] for p in plot["data"]) == epoch(full, 700)
    assert max(p["time"] for p in plot["data"]) == epoch(full, 800)   # outputs clipped to the rendered bars
    # a custom range does not move the chart: outputs still cover only the chart's window
    state, _ = pine_bridge.handle_pine_event(event("pine_set_range", id="pine-1", start=utc(full, 100),
                                                   end=utc(full, 400)), state, {})
    c = run(state, full, window=(300, 350))["scripts"][0]
    plot = next(o for o in c["outputs"] if o["kind"] == "plot")
    assert all(epoch(full, 300) <= p["time"] <= epoch(full, 350) for p in plot["data"])
    assert c["drawings"]["first_bar_index"] == -200                    # strategy bar 0 = chart bar 100, window at 300
    d = run(state, full, window=(0, 500))["scripts"][0]
    assert d["drawings"]["first_bar_index"] == 100                      # starts inside the window: chart logical 100


@pytest.mark.parametrize("start, end, message", [
    ("2025-02-01T00:00", "2025-01-01T00:00", "after its end"),
    ("2025-02-01T00:00", None, "both"),
])
def test_invalid_ranges_are_rejected(start, end, message):
    state = added()
    same, log = pine_bridge.handle_pine_event(event("pine_set_range", id="pine-1", start=start, end=end), state, {})
    assert log.level == "error" and message in log.message and same.pine[0].test_range is None
    with pytest.raises(protocol.EventValidationError):
        protocol.parse_event({"id": "x", "type": "pine_set_range", "data": {"id": "pine-1", "start": "2025-13-01",
                                                                             "end": None}})


def test_clearing_the_range_returns_to_full_history_and_update_keeps_it():
    full = bars(N)
    state = added()
    state, _ = pine_bridge.handle_pine_event(event("pine_set_range", id="pine-1", start=utc(full, 10), end=utc(full, 20)),
                                             state, {})
    state, _ = pine_bridge.handle_pine_event(event("pine_update", id="pine-1", source=STRATEGY.replace("8)", "9)")),
                                             state, {})
    assert state.pine[0].test_range == (utc(full, 10), utc(full, 20))        # editing the script keeps its range
    state, log = pine_bridge.handle_pine_event(event("pine_set_range", id="pine-1", start=None, end=None), state, {})
    assert state.pine[0].test_range is None and "full available history" in log.message


def test_csv_export_is_the_current_result_in_raw_form():
    full = bars(N)
    session = {}
    state = added(session)
    state, _ = pine_bridge.handle_pine_event(event("pine_set_range", id="pine-1", start=utc(full, 200),
                                                   end=utc(full, 699)), state, session)
    state, log = pine_bridge.handle_pine_event(event("pine_export", id="pine-1"), state, session)
    assert log.level == "info"
    section = run(state, full, session=session,
                  export_meta={"symbol": "XAUUSDm", "timeframe": "15m", "provider": "Exness Technologies Ltd"})
    export = section["export"]
    report = section["scripts"][0]["strategy"]
    first, last = full["timestamp"].iloc[200], full["timestamp"].iloc[699]
    assert export["filename"] == f"Cross_XAUUSDm_M15_{first:%Y-%m-%d}_{last:%Y-%m-%d}_trades.csv"
    assert export["mime"] == "text/csv;charset=utf-8"
    rows = list(csv.DictReader(io.StringIO(export["content"])))
    assert list(rows[0]) == list(tester_export.PINE_COLUMNS)
    assert len(rows) == len(report["trades"])
    for row, trade in zip(rows, report["trades"]):
        assert int(row["trade_number"]) == trade["number"]
        assert float(row["entry_price"]) == trade["entry_price"]             # exact: raw repr, not display rounding
        assert int(row["entry_time_epoch"]) == trade["entry_time"]
        assert row["entry_time_utc"] == pd.Timestamp(trade["entry_time"], unit="s", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
        assert (row["exit_price"] == "") == (trade["exit_price"] is None)
        if trade["profit"] is not None:
            assert float(row["pnl"]) == trade["profit"]
        assert row["direction"] == ("long" if trade["direction"] > 0 else "short")
        assert row["status"] == ("open" if trade["open"] else "closed")
        assert (row["strategy"], row["symbol"], row["timeframe"], row["test_mode"]) == ("Cross", "XAUUSDm", "15m", "custom")
        assert row["test_start_utc"] == f"{first:%Y-%m-%dT%H:%M:%SZ}" and row["test_end_utc"] == f"{last:%Y-%m-%dT%H:%M:%SZ}"
    # delivered once: the next payload carries no export
    assert run(state, full, session=session)["export"] is None
    export["content"].encode("utf-8")


def test_export_filename_is_deterministic_and_safe():
    name = tester_export.filename("Gold Range Hunter V50.1", "XAUUSDm", "15m", 1735689600, 1767139200)
    assert name == "Gold_Range_Hunter_V50_1_XAUUSDm_M15_2025-01-01_2025-12-31_trades.csv"
