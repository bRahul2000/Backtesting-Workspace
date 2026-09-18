from __future__ import annotations

import pandas as pd

from engine.execution import create_pending_order, fill_pending_order
from engine.models import BacktestSettings, Candle, Direction
from strategies.btc_v3_t3_breakout_short import (
    BtcV3T3BreakoutShortFrozen,
    MarketRegime,
    TREND_SETUP_ID,
    V3Observation,
    V3T3FrozenParameters,
    classify_regime,
    evaluate_v3,
)
from strategies.confirmed_h1_regime import ConfirmedH1Regime, H1RegimeValue

T = pd.Timestamp("2024-06-03 12:00:00", tz="UTC")


def _h1_short():
    return H1RegimeValue(T.floor("h") - pd.Timedelta(hours=1), 89., 90., 100., 101., 10.)


def _short_obs():
    # Range 1.5 ATR; bearish body 80%; close below prior 5-bar low.
    c = Candle(T, 100., 100.5, 97.5, 97.8, 1.)
    return V3Observation(c, _h1_short(), 95., 100., 20., 40., 2.,
                         103., 98.5, 104., 96., 97.5, 100.5)


def test_t3_frozen_defaults_exactly_match_validated_short_candidate():
    p = V3T3FrozenParameters()
    assert p.trend_enabled is True and p.range_enabled is False
    assert p.longs_enabled is False and p.shorts_enabled is True
    assert p.trend_min_h1_separation_atr == 1.00
    assert p.trend_min_adx == 18.0
    assert p.trend_structure_lookback == 5
    assert p.trend_minimum_body_percent == 0.70
    assert (p.trend_minimum_range_atr, p.trend_maximum_range_atr) == (0.60, 2.00)
    assert (p.trend_short_rsi_min, p.trend_short_rsi_max) == (24.0, 50.0)
    assert p.trend_maximum_extension_atr == 2.50
    assert p.trend_stop_lookback == 2
    assert (p.entry_buffer_atr, p.stop_buffer_atr) == (0.05, 0.20)
    assert (p.minimum_stop_atr, p.maximum_stop_atr) == (0.50, 3.00)
    assert (p.pending_bars, p.reward_multiple, p.max_trades_per_day) == (2, 3.0, 3)


def test_t3_confirmed_h1_is_previous_closed_hour_only():
    h1 = ConfirmedH1Regime(2, 3, 2, 1)
    for i in range(4):
        ts = pd.Timestamp("2024-01-01 00:00", tz="UTC") + pd.Timedelta(minutes=15*i)
        assert h1.update(Candle(ts, 100+i, 101+i, 99+i, 100.5+i, 1.)).hour is None
    current = Candle(pd.Timestamp("2024-01-01 01:00", tz="UTC"), 104., 105., 103., 104.5, 1.)
    confirmed = h1.update(current)
    assert confirmed.hour == pd.Timestamp("2024-01-01 00:00", tz="UTC")
    assert confirmed.hour < current.timestamp.floor("h")


def test_t3_emits_short_only_pending_entry_with_frozen_filters():
    p = V3T3FrozenParameters()
    obs = _short_obs()
    assert classify_regime(obs, p).state is MarketRegime.TREND
    signal = evaluate_v3(obs, p)
    assert signal is not None
    assert signal.direction is Direction.SHORT
    assert signal.setup_id == TREND_SETUP_ID
    assert signal.pending_expiry_bars == 2

    bullish_h1 = H1RegimeValue(T.floor("h") - pd.Timedelta(hours=1), 111., 110., 100., 99., 10.)
    longish = V3Observation(Candle(T, 100., 103., 99., 102.5, 1.), bullish_h1,
                            105., 100., 20., 60., 2., 102., 98., 104., 96., 99., 103.)
    assert evaluate_v3(longish, p) is None


def test_t3_structural_stop_pending_expiry_and_3r_target():
    p = V3T3FrozenParameters()
    signal = evaluate_v3(_short_obs(), p)
    assert signal is not None
    settings = BacktestSettings(risk_percent=.25, risk_reward_ratio=3., commission_percent=0.)
    order = create_pending_order(signal, _short_obs().candle, 10, 10_000., settings)
    assert order.expiry_bar_index == 12
    assert order.expiry_time == T + pd.Timedelta(minutes=30)
    fill_candle = Candle(T + pd.Timedelta(minutes=15), 98., 98.5, 97., 97.5, 1.)
    fill = fill_pending_order(order, fill_candle, 11, 1, settings)
    assert fill is not None and fill.direction is Direction.SHORT
    assert fill.take_profit == fill.entry_price - 3.0 * (fill.stop_loss - fill.entry_price)


def test_t3_gap_reset_preserves_strategy_direction_contract():
    strategy = BtcV3T3BreakoutShortFrozen()
    strategy.on_data_gap()
    assert strategy.params.longs_enabled is False
    assert strategy.params.shorts_enabled is True
