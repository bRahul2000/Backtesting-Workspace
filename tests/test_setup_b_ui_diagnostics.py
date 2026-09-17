"""Setup B selector, Pine defaults, and directional funnel counts."""
from collections import Counter
from contextlib import nullcontext
from types import SimpleNamespace

import pandas as pd

from engine.models import Candle
from strategies.btc_v2_setup_b import (
    BtcV2SetupB, STAGES, SetupBObservation, SetupBParameters, evaluate_setup_b,
)
from strategies.confirmed_h1 import H1TrendValue
from strategies.demo_strategy import DemoEmaCrossover, DemoParameters
from ui import btc_setup_b_controls, backtest_dashboard


class FakeStreamlit:
    def __init__(self):
        self.controls = {}

    def columns(self, count):
        return [self] * count

    def expander(self, *args, **kwargs):
        return nullcontext()

    def number_input(self, label, **kwargs):
        self.controls[label] = kwargs["value"]
        return kwargs["value"]

    def checkbox(self, label, **kwargs):
        self.controls[label] = kwargs["value"]
        return kwargs["value"]

    def time_input(self, label, **kwargs):
        self.controls[label] = kwargs["value"]
        return kwargs["value"]


def test_setup_b_ui_controls_match_source_defaults(monkeypatch):
    fake = FakeStreamlit()
    monkeypatch.setattr(btc_setup_b_controls, "st", fake)
    actual = btc_setup_b_controls.render_setup_b_controls()
    expected = SetupBParameters()
    assert actual == expected
    assert fake.controls["Max Trades / UTC Day"] == 3
    assert fake.controls["Max Daily Equity DD %"] == 1.0
    assert fake.controls["Max Daily Closed Loss Streak"] == 3
    assert fake.controls["Max Monthly Equity DD %"] == 6.0
    assert fake.controls["All-Time Equity Protection"] is False
    assert fake.controls["Max All-Time DD %"] == 10.0


def test_strategy_selector_dispatches_demo_and_setup_b():
    options = backtest_dashboard.STRATEGY_OPTIONS
    assert options == ("Demo EMA Strategy", "BTC V2.2 — Setup B Trend Breakout")
    btc = SetupBParameters()
    demo = DemoParameters(20, 50, 14, 1.5)
    assert isinstance(backtest_dashboard.selected_strategy(options[0], None, demo),
                      DemoEmaCrossover)
    selected = backtest_dashboard.selected_strategy(options[1], btc, None)
    assert isinstance(selected, BtcV2SetupB) and selected.params == btc


def test_diagnostics_have_directional_cumulative_gates_and_order_totals():
    timestamp = pd.Timestamp("2025-01-01T10:15:00Z")
    candle = Candle(timestamp, 100, 103, 99, 102, 1)
    h1 = H1TrendValue(timestamp.floor("h"), 120, 110, 105, 104)
    observation = SetupBObservation(candle, h1, 101, 100, 20, 60, 2,
                                    101, 99, 99, 103)
    counters = Counter()
    assert evaluate_setup_b(observation, SetupBParameters(), counters) is not None
    assert all(counters[stage] == 1 for stage in (
        "H1 long trend", "M15 long alignment", "ADX pass", "Long RSI pass",
        "Strong bullish candle", "Range ATR pass", "Long structure breakout",
        "Anti-chase pass", "Long stop-distance pass", "Final Long Signals",
    ))
    assert all(counters[stage] == 0 for stage in (
        "H1 short trend", "M15 short alignment", "Short RSI pass",
        "Strong bearish candle", "Short structure breakout",
        "Short stop-distance pass", "Final Short Signals",
    ))
    assert len(STAGES) == len(set(STAGES))
    counters["Eligible candles"] = 1
    events = [SimpleNamespace(status=status) for status in
              ("triggered", "expired", "cancelled")]
    result = SimpleNamespace(order_events=events, trades=[object()])
    counts = backtest_dashboard.setup_b_diagnostic_counts(result, counters)
    assert counts["Pending Orders Created"] == 3
    assert counts["Pending Filled"] == 1
    assert counts["Pending Expired"] == 1
    assert counts["Pending Cancelled"] == 1
    assert counts["Completed Trades"] == 1
    assert all(stage in counts for stage in STAGES)


def test_setup_b_run_uses_same_segment_warmup_without_downsampling():
    old = pd.date_range("2023-01-01T00:00:00Z", periods=3, freq="15min")
    recent = pd.date_range("2024-01-01T00:00:00Z", periods=5, freq="15min")
    data = pd.DataFrame({"timestamp": [*old, *recent],
                         "open": range(8), "high": range(8),
                         "low": range(8), "close": range(8),
                         "volume": [1] * 8})
    selected = data.iloc[-2:].reset_index(drop=True)
    run_data = backtest_dashboard.setup_b_run_data(data, selected)
    assert run_data.timestamp.tolist() == list(recent)
    assert run_data.timestamp.diff().dropna().eq(pd.Timedelta(minutes=15)).all()
