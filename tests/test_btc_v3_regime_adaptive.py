from __future__ import annotations

from collections import Counter
from contextlib import nullcontext

import pandas as pd

from engine.execution import create_pending_order, fill_pending_order
from engine.models import BacktestSettings, Candle, Direction
from strategies.btc_v3_regime_adaptive import (
    BtcV3RegimeAdaptive, MarketRegime, RANGE_SETUP_ID, TREND_SETUP_ID,
    V3Observation, V3Parameters, classify_regime, evaluate_v3,
)
from strategies.confirmed_h1_regime import ConfirmedH1Regime, H1RegimeValue
from ui import backtest_dashboard, btc_v3_controls


T = pd.Timestamp("2024-06-03 12:00:00", tz="UTC")


def _h1_long(fast=110., slow=100., past=99., atr=10.):
    return H1RegimeValue(T.floor("h") - pd.Timedelta(hours=1), 111., fast, slow, past, atr)


def _h1_short(fast=90., slow=100., past=101., atr=10.):
    return H1RegimeValue(T.floor("h") - pd.Timedelta(hours=1), 89., fast, slow, past, atr)


def _trend_long_obs():
    candle = Candle(T, 100., 104., 99., 103., 1.)
    return V3Observation(candle, _h1_long(), 105., 100., 20., 60., 2.,
                         102., 98., 104., 96., 99., 104.)


def _trend_short_obs():
    candle = Candle(T, 100., 101., 96., 97., 1.)
    return V3Observation(candle, _h1_short(), 95., 100., 20., 40., 2.,
                         102., 98., 104., 96., 96., 101.)


def _range_long_obs():
    candle = Candle(T, 99.8, 101.2, 99.6, 100.8, 1.)
    h1 = H1RegimeValue(T.floor("h") - pd.Timedelta(hours=1), 100., 102., 100., 99.9, 5.)
    return V3Observation(candle, h1, 100.5, 100., 20., 40., 2.,
                         103., 97., 104., 100., 99.6, 101.2)


def _range_short_obs():
    candle = Candle(T, 100.2, 100.4, 98.8, 99.2, 1.)
    h1 = H1RegimeValue(T.floor("h") - pd.Timedelta(hours=1), 100., 98., 100., 100.1, 5.)
    return V3Observation(candle, h1, 99.5, 100., 20., 60., 2.,
                         103., 97., 100., 96., 98.8, 100.4)


def test_regime_classification_trend_range_chop_and_trend_priority():
    p = V3Parameters()
    assert classify_regime(_trend_long_obs(), p) == \
        classify_regime(_trend_long_obs(), p).__class__(MarketRegime.TREND, Direction.LONG, 1.0)
    range_decision = classify_regime(_range_long_obs(), p)
    assert range_decision.state is MarketRegime.RANGE
    chop = V3Observation(_range_long_obs().candle, _h1_long(), 99., 100., 30., 40., 2.,
                         103., 97., 104., 100., 99.6, 101.2)
    assert classify_regime(chop, p).state is MarketRegime.CHOP
    # Overlap 0.65-0.80 H1 ATR and ADX 18-24 resolves to TREND when alignment/slope agree.
    overlap_h1 = H1RegimeValue(T.floor("h") - pd.Timedelta(hours=1), 100., 107., 100., 99., 10.)
    overlap = V3Observation(_trend_long_obs().candle, overlap_h1, 105., 100., 20., 60., 2.,
                            102., 98., 104., 96., 99., 104.)
    assert classify_regime(overlap, p).state is MarketRegime.TREND


def test_confirmed_h1_regime_never_exposes_current_hour():
    h1 = ConfirmedH1Regime(fast_length=2, slow_length=3, atr_length=2, slope_lookback=1)
    bars = []
    for i in range(8):
        ts = pd.Timestamp("2024-01-01 00:00:00", tz="UTC") + pd.Timedelta(minutes=15 * i)
        price = 100 + i
        bars.append(Candle(ts, price, price + 1, price - 1, price + .5, 1.))
    for bar in bars[:4]:
        seen = h1.update(bar)
        assert seen.hour is None
    first_current = h1.update(bars[4])
    assert first_current.hour == pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
    assert h1.update(bars[5]).hour == first_current.hour
    assert h1.update(bars[6]).hour == first_current.hour
    assert h1.update(bars[7]).hour == first_current.hour
    next_hour = Candle(pd.Timestamp("2024-01-01 02:00:00", tz="UTC"), 200, 201, 199, 200.5, 1)
    confirmed = h1.update(next_hour)
    assert confirmed.hour == pd.Timestamp("2024-01-01 01:00:00", tz="UTC")
    assert confirmed.hour < next_hour.timestamp.floor("h")


def test_trend_long_and_short_entries_are_mirrored_pending_stops():
    p = V3Parameters()
    long_signal = evaluate_v3(_trend_long_obs(), p)
    short_signal = evaluate_v3(_trend_short_obs(), p)
    assert long_signal is not None and long_signal.direction is Direction.LONG
    assert short_signal is not None and short_signal.direction is Direction.SHORT
    assert long_signal.setup_id == short_signal.setup_id == TREND_SETUP_ID
    assert long_signal.pending_expiry_bars == short_signal.pending_expiry_bars == 2
    long_risk = long_signal.pending_entry_price - long_signal.pending_stop_price
    short_risk = short_signal.pending_stop_price - short_signal.pending_entry_price
    assert abs(long_risk - short_risk) < 1e-12


def test_range_sweep_reversal_long_and_short_and_attribution():
    p = V3Parameters()
    counters = Counter()
    long_signal = evaluate_v3(_range_long_obs(), p, counters)
    short_signal = evaluate_v3(_range_short_obs(), p, counters)
    assert long_signal is not None and long_signal.direction is Direction.LONG
    assert short_signal is not None and short_signal.direction is Direction.SHORT
    assert long_signal.setup_id == short_signal.setup_id == RANGE_SETUP_ID
    assert counters["Range LONG Signals"] == 1
    assert counters["Range SHORT Signals"] == 1


def test_range_sweep_depth_bounds_are_enforced():
    p = V3Parameters()
    obs = _range_long_obs()
    too_shallow = V3Observation(obs.candle, obs.h1, obs.ema_fast, obs.ema_slow,
                                obs.adx, obs.rsi, 20., obs.trend_previous_high,
                                obs.trend_previous_low, obs.range_previous_high,
                                obs.range_previous_low, obs.trend_stop_low,
                                obs.trend_stop_high)
    assert evaluate_v3(too_shallow, p) is None


def test_v3_pending_order_uses_two_future_bars_and_does_not_resize():
    signal = evaluate_v3(_trend_long_obs(), V3Parameters())
    assert signal is not None
    settings = BacktestSettings(risk_percent=.25, risk_reward_ratio=3., commission_percent=0.)
    order = create_pending_order(signal, _trend_long_obs().candle, 100, 10_000., settings)
    assert order.expiry_bar_index == 102
    assert order.expiry_time == T + pd.Timedelta(minutes=30)
    no_trigger_1 = Candle(T + pd.Timedelta(minutes=15), 100., 103., 99., 102., 1.)
    no_trigger_2 = Candle(T + pd.Timedelta(minutes=30), 101., 104., 100., 103., 1.)
    assert fill_pending_order(order, no_trigger_1, 101, 1, settings) is None
    assert fill_pending_order(order, no_trigger_2, 102, 1, settings) is None


def test_v3_strategy_option_is_added_without_changing_frozen_v2_options():
    assert backtest_dashboard.STRATEGY_OPTIONS == (
        "Demo EMA Strategy", "BTC V2.2 — Setup B Trend Breakout")
    assert backtest_dashboard.V3_STRATEGY_NAME in backtest_dashboard.BACKTEST_STRATEGY_OPTIONS
    params = V3Parameters()
    selected = backtest_dashboard.selected_strategy(
        backtest_dashboard.V3_STRATEGY_NAME, v3_params=params)
    assert isinstance(selected, BtcV3RegimeAdaptive)
    assert selected.params == params


class FakeStreamlit:
    def __init__(self):
        self.values = {}

    def columns(self, count):
        return [self] * count

    def expander(self, *args, **kwargs):
        return nullcontext()

    def number_input(self, label, **kwargs):
        self.values[label] = kwargs["value"]
        return kwargs["value"]

    def checkbox(self, label, **kwargs):
        self.values[label] = kwargs["value"]
        return kwargs["value"]

    def time_input(self, label, **kwargs):
        self.values[label] = kwargs["value"]
        return kwargs["value"]

    def caption(self, *args, **kwargs):
        return None


def test_v3_ui_defaults_match_strategy_defaults(monkeypatch):
    fake = FakeStreamlit()
    monkeypatch.setattr(btc_v3_controls, "st", fake)
    assert btc_v3_controls.render_v3_controls() == V3Parameters()
    assert fake.values["Trend Engine"] is True
    assert fake.values["Range Engine"] is True
    assert fake.values["H1 EMA200 Slope Lookback"] == 4
    assert fake.values["Trend Min EMA Separation (H1 ATR)"] == .65
    assert fake.values["Range Max EMA Separation (H1 ATR)"] == .80
    assert fake.values["Pending Bars"] == 2
    assert fake.values["Max Filled Trades / UTC Day"] == 3
