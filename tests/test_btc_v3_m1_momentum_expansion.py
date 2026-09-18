from __future__ import annotations

import pandas as pd

from engine.models import Candle, Direction, ExecutionState, PendingOrder, Signal
from strategies.btc_v3_m1_momentum_expansion_continuation import (
    BtcV3M1MomentumExpansionContinuation,
    ExpansionState,
    SETUP_ID,
    V3M1Parameters,
)


def c(minute: int, o: float, h: float, l: float, cl: float) -> Candle:
    return Candle(pd.Timestamp("2024-01-01 12:00", tz="UTC") + pd.Timedelta(minutes=minute),
                  o, h, l, cl, 1.0)


def prior_compression() -> list[Candle]:
    rows = []
    for i in range(12):
        low = 100.0 + (i % 3) * 0.1
        high = 103.0 - (i % 2) * 0.1
        rows.append(c(i * 15, 101.0, high, low, 102.0))
    return rows


def test_default_parameters_match_frozen_m1_spec():
    p = V3M1Parameters()
    assert p.compression_lookback == 12
    assert p.compression_max_width_atr == 3.0
    assert p.prior_tr_average_max_atr == 0.90
    assert p.expansion_min_body_percent == 0.65
    assert (p.expansion_min_range_atr, p.expansion_max_range_atr) == (1.20, 2.75)
    assert p.follow_through_bars == 2
    assert p.pending_bars == 2
    assert (p.minimum_stop_atr, p.maximum_stop_atr) == (0.60, 3.00)
    assert p.reward_multiple == 3.0


def test_long_expansion_uses_only_prior_compression_window():
    s = BtcV3M1MomentumExpansionContinuation()
    prior = prior_compression()
    expansion = c(12 * 15, 102.9, 104.5, 102.8, 104.2)
    state = s._detect_expansion(expansion, 103.0, 102.0, 60.0, 1.0,
                                prior, [0.7] * 5)
    assert state is not None
    assert state.direction is Direction.LONG
    assert state.range_high == 103.0
    assert state.range_low == 100.0
    assert state.diagnostics["compression_width_atr"] == 3.0


def test_short_expansion_is_directional_mirror():
    s = BtcV3M1MomentumExpansionContinuation()
    prior = prior_compression()
    expansion = c(12 * 15, 100.2, 100.3, 98.6, 98.9)
    state = s._detect_expansion(expansion, 100.5, 101.5, 40.0, 1.0,
                                prior, [0.7] * 5)
    assert state is not None
    assert state.direction is Direction.SHORT


def test_compression_rejects_excess_prior_five_tr_average():
    s = BtcV3M1MomentumExpansionContinuation()
    prior = prior_compression()
    expansion = c(12 * 15, 102.9, 104.5, 102.8, 104.2)
    state = s._detect_expansion(expansion, 103.0, 102.0, 60.0, 1.0,
                                prior, [0.91] * 5)
    assert state is None


def _warm_for_followthrough(s: BtcV3M1MomentumExpansionContinuation,
                            previous: Candle) -> None:
    s.fast.value = 103.0
    s.slow.value = 102.0
    s.atr._average.value = 1.0
    s.atr.previous_close = previous.close
    s.last_atr = 1.0
    s.previous.append(previous)
    s.execution_state = ExecutionState(10_000.0, None, None)


def test_valid_followthrough_creates_pending_stop_and_attribution():
    s = BtcV3M1MomentumExpansionContinuation()
    exp_candle = c(0, 102.9, 104.5, 102.8, 104.2)
    _warm_for_followthrough(s, exp_candle)
    s.expansion = ExpansionState(
        Direction.LONG, exp_candle.timestamp, 103.0, 100.0, 103.65,
        exp_candle.low, exp_candle.high, 0,
        {"compression_width_atr": 2.5, "prior_5_average_tr_over_atr": 0.7,
         "expansion_range_atr": 1.7, "expansion_body_percent": 0.75,
         "expansion_close_location_percent": 82.0, "rsi": 60.0,
         "ema20_ema50_distance_atr": 1.0},
    )
    ft = c(15, 104.1, 104.8, 103.9, 104.6)
    action = s.on_candle(ft)
    assert isinstance(action, Signal)
    assert action.direction is Direction.LONG
    assert action.setup_id == SETUP_ID
    assert action.pending_expiry_bars == 2
    assert action.pending_entry_price > ft.high
    diag = s.signal_diagnostics[ft.timestamp + pd.Timedelta(minutes=15)]
    assert diag["follow_through_delay_bars"] == 1
    assert diag["side"] == Direction.LONG.value


def test_close_back_inside_invalidates_expansion_before_followthrough():
    s = BtcV3M1MomentumExpansionContinuation()
    exp_candle = c(0, 102.9, 104.5, 102.8, 104.2)
    _warm_for_followthrough(s, exp_candle)
    s.expansion = ExpansionState(Direction.LONG, exp_candle.timestamp, 103.0, 100.0,
                                 103.65, exp_candle.low, exp_candle.high, 0, {})
    ft = c(15, 103.4, 103.6, 102.8, 102.9)
    assert s.on_candle(ft) is None
    assert s.expansion is None


def test_followthrough_window_expires_after_two_bars():
    s = BtcV3M1MomentumExpansionContinuation()
    exp_candle = c(0, 102.9, 104.5, 102.8, 104.2)
    _warm_for_followthrough(s, exp_candle)
    s.expansion = ExpansionState(Direction.LONG, exp_candle.timestamp, 103.0, 100.0,
                                 103.65, exp_candle.low, exp_candle.high, 0, {})
    # Both closes stay above the old range high but below expansion midpoint,
    # so neither is valid follow-through and neither is an inside-range cancel.
    one = c(15, 103.2, 103.5, 103.1, 103.4)
    two = c(30, 103.3, 103.6, 103.2, 103.5)
    assert s.on_candle(one) is None
    assert s.expansion is not None
    s.execution_state = ExecutionState(10_000.0, None, None)
    assert s.on_candle(two) is None
    assert s.expansion is None


def test_pending_order_cancels_if_close_returns_inside_old_range():
    s = BtcV3M1MomentumExpansionContinuation()
    order = PendingOrder(
        Direction.LONG, pd.Timestamp("2024-01-01 12:15", tz="UTC"),
        pd.Timestamp("2024-01-01 12:15", tz="UTC"), 105.0, 102.0,
        pd.Timestamp("2024-01-01 12:45", tz="UTC"), 1, 3,
        0.1, 25.0, 25.0, False, SETUP_ID,
    )
    prev = c(0, 104.0, 104.5, 103.5, 104.2)
    s.fast.value = 103.0
    s.slow.value = 102.0
    s.atr._average.value = 1.0
    s.atr.previous_close = prev.close
    s.last_atr = 1.0
    s.previous.append(prev)
    s.execution_state = ExecutionState(10_000.0, order, None)
    s.pending_context = {"direction": Direction.LONG, "range_high": 103.0, "range_low": 100.0}
    action = s.on_candle(c(15, 103.3, 103.5, 102.7, 102.9))
    assert action is not None
    assert "compression range" in action.reason
