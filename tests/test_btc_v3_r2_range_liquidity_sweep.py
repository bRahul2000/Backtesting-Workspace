from __future__ import annotations

import pandas as pd

from engine.models import BacktestSettings, Candle, Direction
from engine.execution import create_pending_order
from strategies.btc_v3_r2_range_liquidity_sweep import (
    SETUP_ID, V3R2Parameters, body_percent, close_location, evaluate_sweep,
    range_regime, strong_trend_active,
)
from strategies.confirmed_h1_regime import ConfirmedH1Regime, H1RegimeValue

T = pd.Timestamp("2024-06-03 12:00:00", tz="UTC")


def _h1(close=100., fast=100.3, slow=100., past=99.9, atr=10.):
    return H1RegimeValue(T.floor("h") - pd.Timedelta(hours=1), close, fast, slow, past, atr)


def test_range_regime_requires_low_h1_and_m15_separation_and_low_adx():
    p = V3R2Parameters()
    assert range_regime(_h1(), 100.4, 100., 10., 20., p)
    assert not range_regime(_h1(fast=109., slow=100., atr=10.), 100.4, 100., 10., 20., p)
    assert not range_regime(_h1(), 108., 100., 10., 20., p)
    assert not range_regime(_h1(), 100.4, 100., 10., 25., p)


def test_strong_trend_exclusion_uses_directional_h1_and_m15_alignment():
    p = V3R2Parameters()
    bull = _h1(close=112., fast=111., slow=100., past=99., atr=10.)
    assert strong_trend_active(bull, 105., 103., 25., p)
    assert not strong_trend_active(bull, 102., 103., 25., p)


def test_confirmed_h1_never_exposes_current_incomplete_hour():
    h1 = ConfirmedH1Regime(2, 3, 2, 1)
    bars = []
    for i in range(8):
        ts = pd.Timestamp("2024-01-01 00:00:00", tz="UTC") + pd.Timedelta(minutes=15*i)
        px = 100 + i
        bars.append(Candle(ts, px, px+1, px-1, px+.5, 1.))
    for bar in bars[:4]:
        assert h1.update(bar).hour is None
    confirmed = h1.update(bars[4])
    assert confirmed.hour == pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
    assert confirmed.hour < bars[4].timestamp.floor("h")


def test_long_sweep_signal_uses_prior_range_and_two_bar_pending():
    p = V3R2Parameters()
    c = Candle(T, 97.5, 101.0, 97.0, 100.0, 1.)
    # ATR=2; range 98..104 = 3 ATR; sweep depth .5 ATR; upper close location 75%.
    out = evaluate_sweep(c, _h1(fast=100.2, slow=100., atr=10.), 100.2, 100., 2., 20., 44., 104., 98., p)
    assert out.signal is not None and out.signal.direction is Direction.LONG
    assert out.signal.pending_expiry_bars == 2
    assert out.signal.setup_id == SETUP_ID
    assert out.diagnostics["sweep_depth_atr"] == .5


def test_short_sweep_signal_is_mirror():
    p = V3R2Parameters()
    c = Candle(T, 104.5, 105.0, 101.0, 102.0, 1.)
    out = evaluate_sweep(c, _h1(fast=100.2, slow=100., atr=10.), 100.2, 100., 2., 20., 56., 104., 98., p)
    assert out.signal is not None and out.signal.direction is Direction.SHORT
    assert out.diagnostics["sweep_depth_atr"] == .5


def test_close_location_and_body_quality_are_symmetric():
    bull = Candle(T, 99., 101., 97., 100., 1.)
    bear = Candle(T, 103., 105., 101., 102., 1.)
    assert body_percent(bull) == .25  # deliberately weak in isolation
    assert close_location(bull) == .75
    assert close_location(bear) == .25


def test_pending_order_keeps_audited_stop_entry_semantics():
    p = V3R2Parameters()
    signal = __import__('engine.models', fromlist=['Signal']).Signal.pending_stop(
        Direction.LONG, 105., 100., p.pending_bars, SETUP_ID)
    order = create_pending_order(
        signal, Candle(T, 100., 104., 99., 103., 1.), 10, 10_000.,
        BacktestSettings(risk_percent=.25, risk_reward_ratio=2.5, commission_percent=0.))
    assert order.expiry_bar_index == 12
    assert order.expiry_time == T + pd.Timedelta(minutes=30)
