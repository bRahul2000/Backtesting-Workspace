"""Deterministic Setup B gate tests, independent of market-data outcomes."""
from dataclasses import replace

import pandas as pd
import pytest

from engine.models import Candle, Direction, EntryModel
from strategies.btc_v2_setup_b import (
    SETUP_ID, SetupBObservation, SetupBParameters, evaluate_setup_b,
)
from strategies.confirmed_h1 import H1TrendValue


T = pd.Timestamp("2025-01-01T10:15:00Z")
LONG_H1 = H1TrendValue(T.floor("h"), 120, 110, 105, 104)
SHORT_H1 = H1TrendValue(T.floor("h"), 90, 95, 100, 101)


def long_obs(**changes):
    base = SetupBObservation(
        Candle(T, 100, 103, 99, 102, 1), LONG_H1,
        101, 100, 20, 60, 2, 101, 99, 99, 103,
    )
    return replace(base, **changes)


def short_obs(**changes):
    base = SetupBObservation(
        Candle(T, 100, 101, 97, 98, 1), SHORT_H1,
        99, 100, 20, 40, 2, 101, 99, 97, 101,
    )
    return replace(base, **changes)


def test_complete_long_signal_has_structural_stop_and_pending_fields():
    signal = evaluate_setup_b(long_obs(), SetupBParameters())
    assert signal.direction is Direction.LONG
    assert signal.entry_model is EntryModel.STOP_ENTRY_PENDING
    assert signal.pending_entry_price == pytest.approx(103.1)
    assert signal.pending_stop_price == pytest.approx(98.6)
    assert signal.pending_expiry_bars == 2
    assert signal.setup_id == SETUP_ID


def test_complete_short_signal_has_structural_stop_and_pending_fields():
    signal = evaluate_setup_b(short_obs(), SetupBParameters())
    assert signal.direction is Direction.SHORT
    assert signal.pending_entry_price == pytest.approx(96.9)
    assert signal.pending_stop_price == pytest.approx(101.4)


@pytest.mark.parametrize("change", [
    {"h1": H1TrendValue(T, 120, 100, 105, 104)},
    {"ema_fast": 100},
    {"adx": 17.999},
    {"rsi": 49.999},
    {"rsi": 75.001},
    {"previous_high": 102},  # Equality is not a close breakout.
    {"ema_fast": 95.999},
    {"stop_low": 96},     # Planned stop distance above the maximum.
])
def test_long_filter_rejections(change):
    assert evaluate_setup_b(long_obs(**change), SetupBParameters()) is None


@pytest.mark.parametrize("change", [
    {"h1": H1TrendValue(T, 90, 105, 100, 101)},
    {"ema_fast": 100},
    {"adx": 17.999},
    {"rsi": 24.999},
    {"rsi": 50.001},
    {"previous_low": 98},
    {"ema_fast": 104.001},
])
def test_short_filter_rejections(change):
    assert evaluate_setup_b(short_obs(**change), SetupBParameters()) is None


@pytest.mark.parametrize("rsi", [50, 75])
def test_long_rsi_edges_inclusive(rsi):
    assert evaluate_setup_b(long_obs(rsi=rsi), SetupBParameters()) is not None


@pytest.mark.parametrize("rsi", [25, 50])
def test_short_rsi_edges_inclusive(rsi):
    assert evaluate_setup_b(short_obs(rsi=rsi), SetupBParameters()) is not None


def test_adx_boundary_inclusive():
    assert evaluate_setup_b(long_obs(adx=18), SetupBParameters()) is not None


def test_body_boundary_and_weak_body():
    assert evaluate_setup_b(long_obs(), SetupBParameters()) is not None  # 2/4 = 0.50
    weak = Candle(T, 100.1, 103, 99, 102, 1)
    assert evaluate_setup_b(long_obs(candle=weak), SetupBParameters()) is None


@pytest.mark.parametrize("range_ratio", [0.60, 2.75])
def test_range_atr_edges_inclusive(range_ratio):
    obs = long_obs(atr=4 / range_ratio)
    params = SetupBParameters(minimum_stop_atr=0.01, maximum_stop_atr=10)
    assert evaluate_setup_b(obs, params) is not None


@pytest.mark.parametrize("range_ratio", [0.599, 2.751])
def test_range_atr_outside_edges_rejected(range_ratio):
    obs = long_obs(atr=4 / range_ratio)
    params = SetupBParameters(minimum_stop_atr=0.01, maximum_stop_atr=10)
    assert evaluate_setup_b(obs, params) is None


def test_wick_only_breakout_rejected():
    # High crosses 101; close remains at the prior structure high.
    candle = Candle(T, 100, 103, 99, 101, 1)
    assert evaluate_setup_b(long_obs(candle=candle), SetupBParameters()) is None


def test_extension_threshold_exactly_passes_then_fails():
    assert evaluate_setup_b(long_obs(ema_fast=97, ema_slow=96), SetupBParameters()) is not None
    assert evaluate_setup_b(long_obs(ema_fast=96.999, ema_slow=96), SetupBParameters()) is None


def test_minimum_stop_distance_threshold():
    assert evaluate_setup_b(long_obs(), SetupBParameters(minimum_stop_atr=2.25)) is not None
    assert evaluate_setup_b(long_obs(), SetupBParameters(minimum_stop_atr=2.251)) is None


def test_stop_lookback_inputs_include_signal_candle():
    # The observation builder provides the low/high across the current candle
    # and the immediately previous candle; a lower previous low moves the stop.
    signal = evaluate_setup_b(long_obs(stop_low=98), SetupBParameters())
    assert signal.pending_stop_price == pytest.approx(97.6)
