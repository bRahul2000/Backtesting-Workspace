"""End-to-end Setup B pending orders on synthetic completed M15 candles."""
from datetime import time

import pandas as pd
import pytest

from engine.backtester import run_backtest
from engine.models import BacktestSettings, Direction, EntryModel
from strategies.btc_v2_setup_b import BtcV2SetupB, SetupBParameters
from strategies.btc_v2_setup_b import SETUP_ID
from engine.models import Signal


def rising_candles(count=30, *, falling=False):
    rows = []
    for index in range(count):
        close = 130 - index if falling else 100 + index
        opening = close + 0.8 if falling else close - 0.8
        rows.append({
            "timestamp": pd.Timestamp("2025-01-01T00:00:00Z") +
                         pd.Timedelta(minutes=15 * index),
            "open": opening,
            "high": max(opening, close) + 0.1,
            "low": min(opening, close) - 0.1,
            "close": close,
            "volume": 1,
        })
    return pd.DataFrame(rows)


def fast_params(**overrides):
    values = dict(
        h1_fast_ema=2, h1_slow_ema=3, h1_slope_lookback=1,
        ema_fast=2, ema_slow=3, rsi_length=2, di_length=2,
        adx_smoothing=2, atr_length=2, structure_lookback=3,
        long_rsi_max=100, short_rsi_min=0,
        session_start=time(0), session_end=time(23, 59),
        max_trades_per_day=20, minimum_stop_atr=0.1,
        maximum_stop_atr=10,
    )
    values.update(overrides)
    return SetupBParameters(**values)


@pytest.mark.parametrize("falling,direction", [
    (False, Direction.LONG), (True, Direction.SHORT),
])
def test_strategy_creates_pending_then_fills_on_later_candle_at_three_r(
    falling, direction,
):
    strategy = BtcV2SetupB(fast_params())
    result = run_backtest(
        rising_candles(falling=falling), strategy,
        BacktestSettings(risk_percent=.25, risk_reward_ratio=3, max_leverage=100),
    )
    assert result.trades
    trade = result.trades[0]
    assert trade.direction is direction
    assert trade.entry_model is EntryModel.STOP_ENTRY_PENDING
    assert trade.entry_time >= trade.signal_time
    assert trade.entry_time == result.order_events[0].fill_time
    assert trade.entry_price == result.order_events[0].fill_price
    assert trade.pending_trigger_price != 0
    distance = abs(trade.entry_price - trade.stop_loss)
    expected_target = (trade.entry_price + 3 * distance if direction is Direction.LONG
                       else trade.entry_price - 3 * distance)
    assert trade.take_profit == pytest.approx(expected_target)
    assert result.order_events[0].status == "triggered"
    assert strategy.diagnostics[
        "Final Long Signals" if direction is Direction.LONG else "Final Short Signals"
    ] > 0


def test_future_candles_do_not_change_first_signal_or_pending_fill():
    original = rising_candles(30)
    altered = original.copy()
    altered["close"] = altered["close"].astype(float)
    altered.loc[15:, ["open", "high", "low", "close"]] *= 1.5
    settings = BacktestSettings(risk_percent=.25, risk_reward_ratio=3,
                                max_leverage=100)
    first = run_backtest(original, BtcV2SetupB(fast_params()), settings)
    second = run_backtest(altered, BtcV2SetupB(fast_params()), settings)
    a, b = first.order_events[0], second.order_events[0]
    assert (a.signal_time, a.trigger_price, a.stop_price, a.fill_time, a.fill_price) == (
        b.signal_time, b.trigger_price, b.stop_price, b.fill_time, b.fill_price,
    )


def test_signal_candle_high_does_not_fill_its_own_pending_order():
    result = run_backtest(
        rising_candles(12), BtcV2SetupB(fast_params()),
        BacktestSettings(risk_reward_ratio=3, max_leverage=100),
    )
    event = result.order_events[0]
    assert event.fill_time is not None
    assert event.fill_time >= event.signal_time
    assert event.fill_time > event.signal_time - pd.Timedelta(minutes=15)


def test_pending_order_is_cancelled_when_session_ends():
    class ForcedAtSessionEnd(BtcV2SetupB):
        def on_candle(self, candle):
            action = super().on_candle(candle)
            if candle.timestamp.time() == time(19, 30):
                return Signal.pending_stop(Direction.LONG, 105, 95, 5, SETUP_ID)
            return action

    rows = []
    for minute in (30, 45):
        rows.append(dict(timestamp=pd.Timestamp(f"2025-01-01T19:{minute}:00Z"),
                         open=100, high=101, low=99, close=100, volume=1))
    rows.append(dict(timestamp=pd.Timestamp("2025-01-01T20:00:00Z"),
                     open=100, high=101, low=99, close=100, volume=1))
    result = run_backtest(pd.DataFrame(rows), ForcedAtSessionEnd())
    assert len(result.order_events) == 1
    assert result.order_events[0].status == "cancelled"
    assert "session" in result.order_events[0].cancel_reason
    assert result.trades == []


def test_day_toggle_blocks_new_signals_at_day_boundary():
    p = fast_params(allowed_days=frozenset({2}))  # Wednesday only.
    strategy = BtcV2SetupB(p)
    result = run_backtest(rising_candles(120), strategy,
                          BacktestSettings(risk_reward_ratio=3, max_leverage=100))
    assert result.order_events
    assert all(event.signal_time.date() == pd.Timestamp("2025-01-01").date()
               for event in result.order_events)


def test_setup_b_two_bar_pending_expiry_precedes_third_bar_trigger():
    class Forced(BtcV2SetupB):
        def on_candle(self, candle):
            action = super().on_candle(candle)
            if candle.timestamp == pd.Timestamp("2025-01-01T10:00:00Z"):
                return Signal.pending_stop(Direction.LONG, 105, 95, 2, SETUP_ID)
            return action

    rows = []
    for minute, high in ((0, 101), (15, 101), (30, 101), (45, 106)):
        rows.append(dict(timestamp=pd.Timestamp(f"2025-01-01T10:{minute:02d}:00Z"),
                         open=100, high=high, low=99, close=100, volume=1))
    result = run_backtest(pd.DataFrame(rows), Forced())
    assert result.trades == []
    assert result.order_events[0].status == "expired"


def test_pending_order_cancelled_when_next_utc_day_is_disabled():
    class Forced(BtcV2SetupB):
        def on_candle(self, candle):
            action = super().on_candle(candle)
            if candle.timestamp == pd.Timestamp("2025-01-01T23:30:00Z"):
                return Signal.pending_stop(Direction.LONG, 105, 95, 5, SETUP_ID)
            return action

    rows = []
    for when in ("2025-01-01T23:30:00Z", "2025-01-01T23:45:00Z",
                 "2025-01-02T00:00:00Z"):
        rows.append(dict(timestamp=pd.Timestamp(when), open=100, high=101,
                         low=99, close=100, volume=1))
    p = fast_params(allowed_days=frozenset({2}))
    result = run_backtest(pd.DataFrame(rows), Forced(p))
    assert result.order_events[0].status == "cancelled"
    assert "day" in result.order_events[0].cancel_reason
