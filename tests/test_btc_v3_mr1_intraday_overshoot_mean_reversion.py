from datetime import time

from engine.models import Candle, Direction
from strategies.btc_v3_mr1_intraday_overshoot_mean_reversion import (
    FAIR_VALUE_REFERENCE, V3MR1Parameters, body_percent, close_location, regime_valid,
)


def test_mr1_frozen_baseline_defaults():
    p = V3MR1Parameters()
    assert FAIR_VALUE_REFERENCE == "EMA20"
    assert p.maximum_adx == 28.0
    assert p.maximum_ema_separation_atr == 1.50
    assert (p.minimum_distance_atr, p.maximum_distance_atr) == (1.75, 4.00)
    assert p.excursion_lookback == 5
    assert (p.long_rsi_max, p.short_rsi_min) == (35.0, 65.0)
    assert p.minimum_body_percent == 0.40
    assert (p.long_min_close_location, p.short_max_close_location) == (0.60, 0.40)
    assert (p.entry_buffer_atr, p.stop_buffer_atr) == (0.05, 0.20)
    assert (p.minimum_stop_atr, p.maximum_stop_atr) == (0.50, 2.50)
    assert p.pending_bars == 2
    assert p.reward_multiple == 2.0
    assert (p.session_start, p.session_end) == (time(0, 0), time(22, 0))
    assert p.max_trades_per_day == 3


def test_regime_boundaries_are_inclusive():
    p = V3MR1Parameters()
    assert regime_valid(100.0, 98.5, 1.0, 28.0, p)
    assert not regime_valid(100.0, 98.49, 1.0, 28.0, p)
    assert not regime_valid(100.0, 98.5, 1.0, 28.0001, p)


def test_candle_quality_helpers():
    c = Candle(None, 10.0, 12.0, 9.0, 11.5, 1.0)
    assert abs(body_percent(c) - 0.5) < 1e-12
    assert abs(close_location(c) - (2.5 / 3.0)) < 1e-12
