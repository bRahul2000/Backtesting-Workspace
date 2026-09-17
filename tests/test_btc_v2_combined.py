"""Deterministic original Pine A-before-B priority and shared-state tests."""
from types import SimpleNamespace

import pandas as pd
import pytest

from engine.models import Candle, Direction, ExecutionState, Signal
from research.exness_native_validation import engine_frame
from research.exness_setup_a_b_combined import run_combined_feed
from services.exness_m15 import PROCESSED
from strategies.btc_v2_combined import BtcV2Combined
from strategies.btc_v2_setup_a import SETUP_ID as A_ID, SetupAParameters
from strategies.btc_v2_setup_b import SETUP_ID as B_ID, SetupBParameters


T = pd.Timestamp("2025-01-01T10:15:00Z")


def candle(when=T):
    return Candle(when, 100, 101, 99, 100, 1)


def a_signal():
    return Signal.pending_stop(Direction.LONG, 105, 95, 2, A_ID)


def b_signal():
    return Signal.pending_stop(Direction.LONG, 106, 94, 2, B_ID)


def test_a_priority_suppresses_same_candle_b(monkeypatch):
    monkeypatch.setattr("strategies.btc_v2_combined.evaluate_setup_a",
                        lambda *args: a_signal())
    monkeypatch.setattr("strategies.btc_v2_combined.evaluate_setup_b",
                        lambda *args: b_signal())
    strategy = BtcV2Combined()
    strategy.on_execution_state(ExecutionState(10_000, None, None))
    action = strategy.on_candle(candle())
    assert action.setup_id == A_ID
    assert strategy.captured_signals[0]["setup_id"] == A_ID
    assert strategy.priority_suppressed == [{
        "signal_time": T + pd.Timedelta(minutes=15),
        "direction": "LONG", "reason": "A priority on same candle"}]


def test_b_is_emitted_when_a_fails(monkeypatch):
    monkeypatch.setattr("strategies.btc_v2_combined.evaluate_setup_a",
                        lambda *args: None)
    monkeypatch.setattr("strategies.btc_v2_combined.evaluate_setup_b",
                        lambda *args: b_signal())
    strategy = BtcV2Combined()
    strategy.on_execution_state(ExecutionState(10_000, None, None))
    assert strategy.on_candle(candle()).setup_id == B_ID
    assert strategy.priority_suppressed == []


@pytest.mark.parametrize("kind", ["pending", "position"])
def test_active_a_blocks_b_candidate_without_new_order(monkeypatch, kind):
    monkeypatch.setattr("strategies.btc_v2_combined.evaluate_setup_b",
                        lambda *args: b_signal())
    strategy = BtcV2Combined()
    blocker = SimpleNamespace(setup_id=A_ID, direction=Direction.LONG,
                              entry_price=100, quantity=1, entry_commission=0)
    state = (ExecutionState(10_000, blocker, None) if kind == "pending" else
             ExecutionState(10_000, None, blocker))
    strategy.on_execution_state(state)
    assert strategy.on_candle(candle()) is None
    assert len(strategy.blocked_by_a) == 1
    assert strategy.blocked_by_a[0]["blocker"] == f"A_{kind.upper()}"


def test_pending_a_cancelled_with_its_own_setup_id():
    strategy = BtcV2Combined()
    action = strategy.on_backtest_end(SimpleNamespace(setup_id=A_ID))
    assert action.setup_id == A_ID
    assert "range ended" in action.reason


def test_shared_inputs_must_match():
    with pytest.raises(ValueError, match="identical shared"):
        BtcV2Combined(SetupAParameters(minimum_adx=20), SetupBParameters())


def test_combined_real_exness_prefix_is_causal():
    bars = pd.read_csv(PROCESSED, parse_dates=["timestamp_utc"]).iloc[:4000].copy()
    base = engine_frame(bars, exness=True)
    altered = base.copy()
    altered.loc[altered.index[-20:], ["open", "high", "low", "close"]] *= 1.15
    left = run_combined_feed(base)["signals"]
    right = run_combined_feed(altered)["signals"]
    cutoff = base.timestamp.iloc[-21]
    columns = ["signal_time", "setup_id", "direction", "trigger", "stop"]
    a = left.loc[left.signal_time <= cutoff, columns].reset_index(drop=True)
    b = right.loc[right.signal_time <= cutoff, columns].reset_index(drop=True)
    assert not a.empty
    pd.testing.assert_frame_equal(a, b)
