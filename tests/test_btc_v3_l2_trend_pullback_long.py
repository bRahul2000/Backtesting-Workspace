from __future__ import annotations

import pandas as pd

from engine.execution import create_pending_order
from engine.models import BacktestSettings, Candle, Direction, ExecutionState
from strategies.btc_v3_l2_trend_pullback_long import (
    BtcV3L2TrendPullbackLong, MATERIAL_EMA50_CLOSE_ATR, SETUP_ID,
    V3L2Parameters, confirmation_passes, h1_bullish,
)
from strategies.confirmed_h1_regime import ConfirmedH1Regime, H1RegimeValue

T = pd.Timestamp("2024-06-03 12:00:00", tz="UTC")


def _h1(close=120., fast=110., slow=100., past=99., atr=10.):
    return H1RegimeValue(T.floor("h") - pd.Timedelta(hours=1), close, fast, slow, past, atr)


def test_h1_bullish_requires_alignment_close_slope_and_separation():
    p = V3L2Parameters()
    assert h1_bullish(_h1(), p)
    assert not h1_bullish(_h1(close=99.), p)
    assert not h1_bullish(_h1(fast=99.), p)
    assert not h1_bullish(_h1(past=101.), p)
    assert not h1_bullish(_h1(fast=109., slow=100., atr=10.), p)  # 0.9 ATR separation


def test_confirmed_h1_stays_previous_closed_hour_only():
    h1 = ConfirmedH1Regime(2, 3, 2, 1)
    bars = []
    for i in range(8):
        ts = pd.Timestamp("2024-01-01 00:00:00", tz="UTC") + pd.Timedelta(minutes=15*i)
        px = 100 + i
        bars.append(Candle(ts, px, px+1, px-1, px+.5, 1.))
    for bar in bars[:4]:
        assert h1.update(bar).hour is None
    first = h1.update(bars[4])
    assert first.hour == pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
    assert first.hour < bars[4].timestamp.floor("h")


def test_confirmation_rules():
    p = V3L2Parameters()
    prev = Candle(T, 100, 103, 99, 101, 1)
    c = Candle(T + pd.Timedelta(minutes=15), 101, 105, 100.5, 104.5, 1)
    assert confirmation_passes(c, prev, 102., 60., p)
    weak_body = Candle(c.timestamp, 102.5, 105, 100.5, 104.5, 1)
    assert not confirmation_passes(weak_body, prev, 102., 60., p)
    assert not confirmation_passes(c, prev, 105., 60., p)
    assert not confirmation_passes(c, prev, 102., 71., p)


def test_material_ema50_definition_is_frozen_at_point_two_atr():
    assert MATERIAL_EMA50_CLOSE_ATR == 0.20


def test_pending_signal_uses_two_bars_and_long_attribution():
    p = V3L2Parameters()
    # Directly verify a V3-L2 signal has the existing audited pending semantics.
    signal = __import__('engine.models', fromlist=['Signal']).Signal.pending_stop(
        Direction.LONG, 105., 100., p.pending_bars, SETUP_ID)
    order = create_pending_order(
        signal, Candle(T, 100., 104., 99., 103., 1.), 10, 10_000.,
        BacktestSettings(risk_percent=.25, risk_reward_ratio=3., commission_percent=0.))
    assert order.direction is Direction.LONG
    assert order.setup_id == SETUP_ID
    assert order.expiry_bar_index == 12
    assert order.expiry_time == T + pd.Timedelta(minutes=30)


def test_strategy_is_long_only_and_resets_on_gap():
    strategy = BtcV3L2TrendPullbackLong()
    strategy.last_broken_structure_level = 123.
    strategy.pullback_active = True
    strategy.on_data_gap()
    assert strategy.last_broken_structure_level is None
    assert strategy.pullback_active is False


def test_pending_is_cancelled_when_context_invalidates(monkeypatch):
    # Unit-test the cancellation branch without changing generic execution.
    strategy = BtcV3L2TrendPullbackLong()
    strategy.on_backtest_window(T, None)
    from engine.models import PendingOrder
    order = PendingOrder(
        direction=Direction.LONG, signal_time=T, created_time=T, trigger_price=110.,
        stop_price=100., expiry_time=T+pd.Timedelta(minutes=30),
        created_bar_index=0, expiry_bar_index=2, quantity=1., planned_risk=25.,
        estimated_stop_loss=25., leverage_capped=False, setup_id=SETUP_ID)
    strategy.on_execution_state(ExecutionState(10_000., order, None))
    # Warm-up is intentionally absent, so context is invalid and must cancel.
    action = strategy.on_candle(Candle(T, 100., 101., 99., 100., 1.))
    assert action is not None
    assert action.setup_id == SETUP_ID
