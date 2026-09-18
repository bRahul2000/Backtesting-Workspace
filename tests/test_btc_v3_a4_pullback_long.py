from __future__ import annotations

import pandas as pd

from engine.execution import create_pending_order, fill_pending_order
from engine.models import BacktestSettings, Candle, Direction, Signal
from strategies.btc_v3_a4_pullback_long import (
    BtcV3A4PullbackLongFrozen,
    CONFIRMATION_MAX_BODY_PERCENT,
    MINIMUM_NORMALIZED_H1_SLOPE,
    SETUP_ID,
    V3A4FrozenParameters,
    confirmation_passes,
    h1_bullish,
)
from strategies.confirmed_h1_regime import ConfirmedH1Regime, H1RegimeValue

T = pd.Timestamp("2024-06-03 12:00:00", tz="UTC")


def _h1(*, close=120., fast=110., slow=100., past=99., atr=10.):
    return H1RegimeValue(T.floor("h") - pd.Timedelta(hours=1), close, fast, slow, past, atr)


def test_a4_frozen_defaults_exactly_match_validated_overrides_and_l2_defaults():
    p = V3A4FrozenParameters()
    assert (p.h1_fast_ema, p.h1_slow_ema, p.h1_atr_length, p.h1_slope_lookback) == (50, 200, 14, 4)
    assert p.h1_min_separation_atr == 1.00
    assert (p.ema_fast, p.ema_slow, p.min_adx) == (20, 50, 18.0)
    assert p.max_pullback_depth_below_ema20_atr == 1.00
    assert p.confirmation_min_body_percent == 0.70
    assert CONFIRMATION_MAX_BODY_PERCENT == 0.90
    assert MINIMUM_NORMALIZED_H1_SLOPE == 0.15
    assert (p.confirmation_rsi_min, p.confirmation_rsi_max) == (48.0, 70.0)
    assert (p.entry_buffer_atr, p.stop_buffer_atr) == (0.05, 0.20)
    assert (p.minimum_stop_atr, p.maximum_stop_atr) == (0.50, 3.00)
    assert (p.pending_bars, p.reward_multiple, p.max_trades_per_day) == (2, 3.0, 3)
    assert (p.session_start.hour, p.session_end.hour) == (0, 22)


def test_a4_confirmed_h1_never_exposes_current_hour():
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


def test_a4_normalized_slope_is_only_context_gate_not_h1_bullish_gate():
    p = V3A4FrozenParameters()
    h1 = _h1(past=99.0, slow=100.0, atr=10.0)  # normalized slope .10
    strategy = BtcV3A4PullbackLongFrozen()
    assert h1_bullish(h1, p) is True
    assert strategy._context_valid(h1, 110.0, 105.0, 20.0) is False


def test_a4_confirmation_body_cap_is_inclusive_and_uses_immediate_previous_high():
    p = V3A4FrozenParameters()
    prev = Candle(T, 100., 108., 99., 101., 1.)
    exactly_ninety = Candle(T + pd.Timedelta(minutes=15), 100., 110., 100., 109., 1.)
    assert confirmation_passes(exactly_ninety, prev, 105., 60., p)
    over_cap = Candle(exactly_ninety.timestamp, 100., 110., 100., 109.1, 1.)
    assert not confirmation_passes(over_cap, prev, 105., 60., p)
    higher_previous = Candle(T, 100., 109.5, 99., 101., 1.)
    assert not confirmation_passes(exactly_ninety, higher_previous, 105., 60., p)


def test_a4_frozen_constructor_accepts_no_parameter_override():
    try:
        BtcV3A4PullbackLongFrozen(V3A4FrozenParameters())
    except TypeError:
        pass
    else:
        raise AssertionError("Frozen A4 must not accept caller-supplied parameter overrides")


def test_a4_is_long_only_pending_expiry_and_3r_target():
    p = V3A4FrozenParameters()
    signal = Signal.pending_stop(Direction.LONG, 105., 100., p.pending_bars, SETUP_ID)
    settings = BacktestSettings(risk_percent=.25, risk_reward_ratio=3., commission_percent=0.)
    order = create_pending_order(signal, Candle(T, 100., 104., 99., 103., 1.), 10, 10_000., settings)
    assert order.direction is Direction.LONG
    assert order.expiry_bar_index == 12
    assert order.expiry_time == T + pd.Timedelta(minutes=30)
    fill = fill_pending_order(order, Candle(T + pd.Timedelta(minutes=15), 104., 106., 103., 105., 1.), 11, 1, settings)
    assert fill is not None and fill.direction is Direction.LONG
    assert fill.stop_loss == 100.
    assert fill.take_profit == fill.entry_price + 3.0 * (fill.entry_price - fill.stop_loss)


def test_a4_gap_reset_uses_original_l2_state_machine():
    strategy = BtcV3A4PullbackLongFrozen()
    strategy.last_broken_structure_level = 123.
    strategy.pullback_active = True
    strategy.on_data_gap()
    assert strategy.last_broken_structure_level is None
    assert strategy.pullback_active is False
