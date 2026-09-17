"""Hand-calculated Pine V2.2.0 Setup A rejection, permission, and order fixtures."""
from collections import Counter
from dataclasses import replace
from datetime import time
from types import SimpleNamespace

import pandas as pd
import pytest

from engine.backtester import run_backtest
from engine.models import (BacktestSettings, Candle, Direction, EntryModel,
                           ExecutionState, PendingOrder, Signal)
from research.exness_setup_a_validation import (executable_lots, period_worst_drawdown,
                                                 run_feed, setup_a_warmup)
from research.exness_native_validation import engine_frame
from services.exness_m15 import PROCESSED
from strategies.btc_v2_setup_a import (BtcV2SetupA, SETUP_ID, SetupAObservation,
                                       SetupAParameters, evaluate_setup_a)
from strategies.confirmed_h1 import H1TrendValue


T = pd.Timestamp("2025-01-01T10:15:00Z")
LONG_H1 = H1TrendValue(T.floor("h") - pd.Timedelta(hours=1), 120, 110, 105, 104)
SHORT_H1 = H1TrendValue(T.floor("h") - pd.Timedelta(hours=1), 90, 95, 100, 101)


def long_obs(**changes):
    return replace(SetupAObservation(Candle(T, 100, 103, 99, 102, 1),
                   LONG_H1, 101, 100, 20, 60, 2, 0), **changes)


def short_obs(**changes):
    return replace(SetupAObservation(Candle(T, 100, 101, 97, 98, 1),
                   SHORT_H1, 99, 100, 20, 40, 2, 0), **changes)


def test_original_defaults_and_hand_calculated_long_signal():
    p = SetupAParameters()
    assert (p.touch_lookback, p.pending_bars, p.entry_buffer_atr,
            p.stop_buffer_atr, p.reward_multiple) == (5, 2, .2, .3, 3)
    signal = evaluate_setup_a(long_obs(), p)
    assert signal.direction is Direction.LONG
    assert signal.entry_model is EntryModel.STOP_ENTRY_PENDING
    assert signal.setup_id == SETUP_ID
    assert signal.pending_entry_price == pytest.approx(103.4)
    assert signal.pending_stop_price == pytest.approx(98.4)
    assert signal.pending_expiry_bars == 2


def test_hand_calculated_short_signal():
    signal = evaluate_setup_a(short_obs(), SetupAParameters())
    assert signal.direction is Direction.SHORT
    assert signal.pending_entry_price == pytest.approx(96.6)
    assert signal.pending_stop_price == pytest.approx(101.6)


@pytest.mark.parametrize("changes", [
    {"h1": H1TrendValue(T, 99, 105, 100, 101)},
    {"ema_fast": 100}, {"adx": 17.999}, {"rsi": 53.999},
    {"rsi": 68.001}, {"bars_since_prior_touch": None},
    {"bars_since_prior_touch": 5},
    {"candle": Candle(T, 102, 103, 99, 100, 1)},
    {"candle": Candle(T, 100, 103, 99, 101, 1)},
    {"ema_slow": 101},
    {"candle": Candle(T, 100, 105, 99, 102, 1)},
])
def test_long_rejections(changes):
    assert evaluate_setup_a(long_obs(**changes), SetupAParameters()) is None


@pytest.mark.parametrize("changes", [
    {"h1": LONG_H1}, {"ema_fast": 100}, {"adx": 17.999},
    {"rsi": 31.999}, {"rsi": 46.001},
    {"bars_since_prior_touch": None}, {"bars_since_prior_touch": 5},
    {"candle": Candle(T, 98, 101, 97, 100, 1)},
    {"candle": Candle(T, 100, 101, 97, 99, 1)},
    {"ema_slow": 99},
])
def test_short_rejections(changes):
    assert evaluate_setup_a(short_obs(**changes), SetupAParameters()) is None


def test_close_location_tolerance_range_and_stop_edges():
    p = SetupAParameters()
    assert evaluate_setup_a(long_obs(adx=18, rsi=54,
                            bars_since_prior_touch=4), p) is not None
    assert evaluate_setup_a(short_obs(rsi=46), p) is not None
    assert evaluate_setup_a(long_obs(), replace(p, maximum_stop_atr=2.5)) is not None
    assert evaluate_setup_a(long_obs(), replace(p, maximum_stop_atr=2.499)) is None
    assert evaluate_setup_a(long_obs(candle=Candle(T, 100, 104, 99, 103, 1)), p) is not None
    assert evaluate_setup_a(long_obs(candle=Candle(T, 100, 104.01, 99, 103, 1)), p) is None


def test_first_failed_gate_is_diagnostic():
    counts = Counter()
    assert evaluate_setup_a(long_obs(adx=17), SetupAParameters(), counts) is None
    assert counts["Failed: ADX pass"] == 1
    assert counts["Final Long Signals"] == 0


def test_prior_touch_excludes_current_candle(monkeypatch):
    observed = []
    monkeypatch.setattr("strategies.btc_v2_setup_a.evaluate_setup_a",
                        lambda obs, params, counters: observed.append(obs.bars_since_prior_touch))
    s = BtcV2SetupA()
    s.on_execution_state(ExecutionState(10_000, None, None))
    s.on_candle(Candle(T, 100, 101, 99, 100, 1))
    s.on_execution_state(ExecutionState(10_000, None, None))
    s.on_candle(Candle(T + pd.Timedelta(minutes=15), 100, 102, 100, 101, 1))
    assert observed == [None, 0]


def test_h1_confirmed_hour_and_prefix_causality():
    p = SetupAParameters(h1_fast_ema=2, h1_slow_ema=3, h1_slope_lookback=1)
    s = BtcV2SetupA(p)
    seen = []
    for i in range(20):
        stamp = pd.Timestamp("2025-01-01T00:00Z") + i * pd.Timedelta(minutes=15)
        s.on_execution_state(ExecutionState(10_000, None, None))
        s.on_candle(Candle(stamp, 100+i, 101+i, 99+i, 100+i, 1))
        seen.append(s.h1.confirmed.hour)
    assert seen[3] is None
    assert seen[4] == pd.Timestamp("2025-01-01T00:00Z")
    assert seen[7] == seen[4]
    assert seen[8] == pd.Timestamp("2025-01-01T01:00Z")
    s.on_data_gap()
    assert s.h1.confirmed.hour is None
    assert s._last_touch_index is None


def test_warmup_uses_confirmed_h1_and_one_search_candle():
    minimum, first = setup_a_warmup(SetupAParameters(), pd.Timestamp("2025-01-01T00:15Z"))
    assert minimum == 824
    assert first == pd.Timestamp("2025-01-09T14:00Z")


def _pending(when):
    return PendingOrder(Direction.LONG, when, when, 105, 95,
                        when + pd.Timedelta(minutes=30), 0, 2, 1, 25, 25,
                        False, SETUP_ID)


def test_session_weekday_and_daily_lock_cancel_pending():
    p = SetupAParameters(allowed_days=frozenset({2}))  # Wednesday.
    s = BtcV2SetupA(p)
    s.on_execution_state(ExecutionState(10_000, _pending(T), None))
    assert "session" in s.on_candle(Candle(T.normalize()+pd.Timedelta(hours=20), 100, 101, 99, 100, 1)).reason
    s.reset()
    s.on_execution_state(ExecutionState(10_000, _pending(T), None))
    assert "day" in s.on_candle(Candle(T+pd.Timedelta(days=1), 100, 101, 99, 100, 1)).reason
    s = BtcV2SetupA(SetupAParameters(max_trades_per_day=1))
    s.on_execution_state(ExecutionState(10_000, _pending(T), None,
                                        SimpleNamespace(direction=Direction.LONG)))
    assert "trades" in s.on_candle(Candle(T, 100, 101, 99, 100, 1)).reason


def test_daily_loss_and_monthly_equity_locks_do_not_force_exit():
    s = BtcV2SetupA(SetupAParameters(maximum_daily_losing_streak=1))
    s.on_execution_state(ExecutionState(10_000, None, None, None,
                                        SimpleNamespace(pnl=-25)))
    assert s.on_candle(Candle(T, 100, 101, 99, 100, 1)) is None
    assert s.risk.daily_streak_locked
    s = BtcV2SetupA()
    s.on_execution_state(ExecutionState(10_000, None, None))
    s.on_candle(Candle(T, 100, 101, 99, 100, 1))
    position = SimpleNamespace(direction=Direction.LONG, entry_price=100,
                               quantity=100, entry_commission=0)
    s.on_execution_state(ExecutionState(10_000, None, position))
    assert s.on_candle(Candle(T+pd.Timedelta(minutes=15), 90, 91, 89, 90, 1)) is None
    assert s.risk.monthly_locked
    assert s.execution_state.position is position


def test_start_of_day_equity_reference_and_daily_drawdown_lock():
    s = BtcV2SetupA()
    s.on_execution_state(ExecutionState(10_000, None, None))
    s.on_candle(Candle(T, 100, 101, 99, 100, 1))
    s.on_execution_state(ExecutionState(9_900, _pending(T), None))
    action = s.on_candle(Candle(T+pd.Timedelta(minutes=15), 100, 101, 99, 100, 1))
    assert "Daily equity" in action.reason
    assert s.risk.day_start_equity == 10_000
    s.on_execution_state(ExecutionState(9_900, None, None))
    s.on_candle(Candle(T+pd.Timedelta(days=1), 100, 101, 99, 100, 1))
    assert not s.risk.daily_equity_locked
    assert s.risk.day_start_equity == 9_900


def test_pending_fill_three_r_expiry_and_end_cancellation():
    class Forced(BtcV2SetupA):
        def on_candle(self, candle):
            super().on_candle(candle)
            return evaluate_setup_a(long_obs(), SetupAParameters()) if candle.timestamp == T else None

    def frame(highs):
        return pd.DataFrame([{"timestamp": T + i * pd.Timedelta(minutes=15),
                              "open": 100., "high": h, "low": 99.,
                              "close": 100., "volume": 1.}
                             for i, h in enumerate(highs)])

    settings = BacktestSettings(risk_percent=.25, risk_reward_ratio=3, max_leverage=100)
    filled = run_backtest(frame([101, 104, 101]), Forced(), settings)
    event = filled.order_events[0]
    assert event.status == "triggered" and event.fill_time == T + pd.Timedelta(minutes=15)
    assert filled.open_position.take_profit == pytest.approx(
        filled.open_position.entry_price + 3 * (
            filled.open_position.entry_price - filled.open_position.stop_loss))
    expired = run_backtest(frame([101, 101, 101, 104]), Forced(), settings)
    assert expired.order_events[0].status == "expired"
    ended = run_backtest(frame([101]), Forced(), settings)
    assert ended.order_events[0].status == "cancelled"
    assert ended.order_events[0].cancel_reason == "Backtest range ended."


def test_lot_size_rounds_down_and_never_rounds_up():
    assert executable_lots(.0099) == 0
    assert executable_lots(.0199) == .01
    assert executable_lots(.027) == .02
    assert executable_lots(201) == 200


def test_setup_a_real_exness_prefix_is_causal():
    bars = pd.read_csv(PROCESSED, parse_dates=["timestamp_utc"]).iloc[:4000].copy()
    base = engine_frame(bars, exness=True)
    future = base.copy()
    future.loc[future.index[-20:], ["open", "high", "low", "close"]] *= 1.15
    left = run_feed(base, "original")["signals"]
    right = run_feed(future, "altered")["signals"]
    cutoff = base.timestamp.iloc[-21]
    columns = ["signal_time", "direction", "trigger", "structural_stop"]
    before = left.loc[left.signal_time <= cutoff, columns].reset_index(drop=True)
    after = right.loc[right.signal_time <= cutoff, columns].reset_index(drop=True)
    assert not before.empty
    pd.testing.assert_frame_equal(before, after)


def test_drawdown_is_segment_local_and_cost_view_specific():
    trades = pd.DataFrame([
        {"segment_id": "S1", "exit_time": pd.Timestamp("2024-01-01T10:00Z"),
         "gross_pnl": -100., "net_pnl": -200.},
        {"segment_id": "S2", "exit_time": pd.Timestamp("2024-02-01T10:00Z"),
         "gross_pnl": -50., "net_pnl": -100.},
    ])
    assert period_worst_drawdown(trades, 2024, 2024) == pytest.approx(1.)
    assert period_worst_drawdown(trades, 2024, 2024, costed=True) == pytest.approx(2.)
