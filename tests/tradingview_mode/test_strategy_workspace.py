"""Custom strategy workspace (Python side): duplicate strategy instances, Historical calculation on more history
than the chart shows, the report's derived fields, and the protocol's no-future rule for it."""
from __future__ import annotations

import copy

import pandas as pd
import pytest

from ui.tradingview_mode.component import pine_bridge, protocol
from ui.tradingview_mode.component.protocol import FrontendEvent, PayloadValidationError
from ui.tradingview_mode.component.state import TerminalState

from .pine.helpers import bars

STRATEGY = """//@version=6
strategy("Cross", overlay=true)
fast = ta.sma(close, 3)
slow = ta.sma(close, 8)
plot(fast, "fast")
if ta.crossover(fast, slow)
    strategy.entry("L", strategy.long, comment="GO_LONG")
if ta.crossunder(fast, slow)
    strategy.close("L", comment="OUT")
if bar_index % 50 == 0
    line.new(bar_index, low, bar_index + 3, high)
"""


def event(kind, **data):
    return FrontendEvent(f"e-{kind}-{len(data)}", kind, data)


def test_identical_strategy_is_not_added_twice_unless_asked():
    state, session = TerminalState(dataset_key="EXNESS_XAUUSDM_M15", timeframe="15m"), {}
    state, log = pine_bridge.handle_pine_event(event("pine_add", source=STRATEGY), state, session)
    assert len(state.pine) == 1 and log.level == "info"
    same, log = pine_bridge.handle_pine_event(event("pine_add", source=STRATEGY), state, session)
    assert len(same.pine) == 1 and log.level == "warning" and "already on the chart (pine-1)" in log.message
    assert session[pine_bridge.EDITOR_KEY]["duplicate_of"] == "pine-1"
    two, log = pine_bridge.handle_pine_event(event("pine_add", source=STRATEGY, another=True), state, session)
    assert [p.id for p in two.pine] == ["pine-1", "pine-2"] and log.level == "info"
    # a different script, or the same script with changed inputs, is not a duplicate
    other, _ = pine_bridge.handle_pine_event(event("pine_add", source=STRATEGY.replace("8)", "9)")), state, session)
    assert len(other.pine) == 2


def test_pine_add_event_schema_accepts_the_new_flags_only():
    ok = protocol.parse_event({"id": "a", "type": "pine_add", "data": {"source": STRATEGY, "another": True,
                                                                        "keep_editor": False}})
    assert ok.data["another"] is True
    with pytest.raises(protocol.EventValidationError):
        protocol.parse_event({"id": "b", "type": "pine_add", "data": {"source": STRATEGY, "force": True}})
    with pytest.raises(protocol.EventValidationError):
        protocol.parse_event({"id": "c", "type": "set_bottom_panel", "data": {"panel": "pine_strategy"}})


def _section(frame, display_from=None, mode="historical"):
    state = TerminalState(dataset_key="EXNESS_XAUUSDM_M15", timeframe="15m")
    state, _ = pine_bridge.handle_pine_event(event("pine_add", source=STRATEGY), state, {})
    return pine_bridge.pine_payload(state, frame, {}, identity=("t",), timeframe_seconds=900, ticker="T",
                                    tickerid="T:T", mintick=0.01, mode=mode, display_from=display_from)["scripts"][0]


def test_historical_calculation_covers_more_than_the_rendered_window():
    frame = bars(600)
    full = _section(frame)
    shown_from = int(frame["timestamp"].iloc[400].timestamp())
    windowed = _section(frame, display_from=shown_from)
    # the backtest is identical: it does not depend on how much of it the chart renders
    assert windowed["strategy"]["trades"] == full["strategy"]["trades"]
    assert windowed["strategy"]["calc_range"]["bars"] == 600 and windowed["calc_bars"] == 600
    assert any(t["entry_time"] < shown_from for t in windowed["strategy"]["trades"])
    # chart outputs are for the rendered bars only
    plot = next(o for o in windowed["outputs"] if o["kind"] == "plot")
    assert min(p["time"] for p in plot["data"]) == shown_from and len(plot["data"]) == 200
    # drawings keep their Pine coordinates; the chart's logical index is x + first_bar_index (negative = left)
    assert windowed["drawings"]["first_bar_index"] == -400 and full["drawings"]["first_bar_index"] == 0


def test_report_derived_fields():
    report = _section(bars(600))["strategy"]
    closed = [t for t in report["trades"] if not t["open"]]
    assert closed and all(t["bars_held"] == t["exit_bar"] - t["entry_bar"] for t in closed)
    t = closed[0]
    assert t["profit_percent"] == pytest.approx(t["profit"] / (t["entry_price"] * t["qty"]) * 100)
    assert report["metrics"]["avg_bars_in_trade"] == pytest.approx(sum(t["bars_held"] for t in closed) / len(closed))
    assert report["fill_count"] == report["fills_reported"] == len(report["fills"])
    assert {f["comment"] for f in report["fills"]} >= {"GO_LONG", "OUT"}


def _payload(script, frame, mode="historical"):
    times = [int(t.timestamp()) for t in frame["timestamp"]]
    shown = [t for t in times if script.get("display_from") is None or t >= script["display_from"]]
    return {"mode": mode, "pine": {"scripts": [script]}}, set(shown)


def test_protocol_allows_earlier_calculated_events_only_in_historical():
    frame = bars(600)
    shown_from = int(frame["timestamp"].iloc[400].timestamp())
    script = copy.deepcopy(_section(frame, display_from=shown_from))
    payload, bar_times = _payload(script, frame)
    protocol._validate_pine(payload, bar_times)                                      # historical: accepted
    replay, _ = _payload(script, frame, mode="replay")
    with pytest.raises(PayloadValidationError, match="Historical-only"):
        protocol._validate_pine(replay, bar_times)
    # never an event after the last rendered bar
    late = copy.deepcopy(script)
    late["strategy"]["fills"][-1]["time"] = max(bar_times) + 900
    with pytest.raises(PayloadValidationError, match="not on a chart bar"):
        protocol._validate_pine(_payload(late, frame)[0], bar_times)
    # without display_from, an event before the first rendered bar is still rejected
    strict = copy.deepcopy(script)
    strict["display_from"] = None
    strict["drawings"] = None
    with pytest.raises(PayloadValidationError):
        protocol._validate_pine(_payload(strict, frame)[0], bar_times)


def test_strategy_calculation_is_capped_at_the_pine_bar_limit():
    assert pine_bridge.MAX_PINE_BARS == 20_000
