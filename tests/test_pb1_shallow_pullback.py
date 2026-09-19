from datetime import timedelta

import pandas as pd
import pytest

from engine.models import Candle, Direction, ExecutionState, PendingOrder, Position, Trade
from strategies.base_strategy import StrategyStatus
from strategies.btc_pb1_shallow_pullback import (
    BtcPB1ShallowPullback, PB1Parameters, STRATEGY_ID, SETUP_ID, _Structure,
)
from strategies.registry import discover_builtin_strategies

UTC = "UTC"


def _fast_params(**overrides) -> PB1Parameters:
    base = dict(
        h1_fast_ema=1, h1_slow_ema=2, h1_atr_length=1, h1_slope_lookback=1,
        m15_ema_fast=2, m15_ema_slow=3, m15_atr_length=1,
        impulse_window_bars=3, impulse_minimum_range_atr=1.5,
        pullback_maximum_bars=3, pullback_minimum_retracement_percent=0.20,
        pullback_maximum_retracement_percent=0.45,
        confirmation_close_location_percent=0.35, confirmation_minimum_body_percent=0.50,
        confirmation_maximum_range_atr=2.0, entry_buffer_atr=0.10, stop_buffer_atr=0.20,
        minimum_stop_atr=0.50, maximum_stop_atr=2.50, pending_expiry_bars=2,
    )
    base.update(overrides)
    return PB1Parameters(**base)


LONG_ROWS = [
    (100.0, 101.0, 99.0, 100.5), (100.5, 101.5, 100.0, 101.0), (101.0, 102.0, 100.5, 101.5), (101.5, 102.5, 101.0, 102.0),
    (102.0, 103.0, 101.5, 102.5), (102.5, 103.5, 102.0, 103.0), (103.0, 104.0, 102.5, 103.5), (103.5, 104.5, 103.0, 104.0),
    (104.0, 105.0, 103.5, 104.8), (104.8, 106.0, 104.5, 105.8),
]


def _mirror(row: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    o, h, l, c = row
    return (200 - o, 200 - l, 200 - h, 200 - c)


SHORT_ROWS = [_mirror(row) for row in LONG_ROWS]


def _feed(strategy: BtcPB1ShallowPullback, rows, start="2024-01-01 00:00:00"):
    ts = pd.Timestamp(start, tz=UTC)
    signals = []
    for o, h, l, c in rows:
        candle = Candle(ts, o, h, l, c, 1.0)
        signals.append(strategy.on_candle(candle))
        ts += timedelta(minutes=15)
    return signals


# --- H1 context (section 2) ---------------------------------------------------------


def test_long_context_confirmed_after_warmup():
    strategy = BtcPB1ShallowPullback(_fast_params())
    _feed(strategy, LONG_ROWS[:10])
    regime = strategy.h1.confirmed
    assert regime.fast_ema > regime.slow_ema
    events = [e for e in strategy.diagnostic_events if e.stage == "h1_context_evaluated"]
    assert events
    assert events[0].metadata["direction"] == "LONG"


def test_short_context_confirmed_after_warmup():
    strategy = BtcPB1ShallowPullback(_fast_params())
    _feed(strategy, SHORT_ROWS[:10])
    regime = strategy.h1.confirmed
    assert regime.fast_ema < regime.slow_ema
    events = [e for e in strategy.diagnostic_events if e.stage == "h1_context_evaluated"]
    assert events[0].metadata["direction"] == "SHORT"


# --- Impulse / pullback / confirmation / entry end-to-end (sections 3-7) -------------


def test_long_confirmation_produces_pending_order_with_hand_verified_prices():
    strategy = BtcPB1ShallowPullback(_fast_params())
    signals = _feed(strategy, LONG_ROWS)
    signal = next(s for s in signals if s is not None)
    assert signal.direction is Direction.LONG
    assert signal.pending_entry_price == pytest.approx(106.15)
    assert signal.pending_stop_price == pytest.approx(104.2)
    assert signal.take_profit is None
    assert signal.pending_expiry_bars == 2
    assert signal.setup_id == SETUP_ID


def test_short_confirmation_produces_pending_order_with_hand_verified_prices():
    strategy = BtcPB1ShallowPullback(_fast_params())
    signals = _feed(strategy, SHORT_ROWS)
    signal = next(s for s in signals if s is not None)
    assert signal.direction is Direction.SHORT
    assert signal.pending_entry_price == pytest.approx(93.85)
    assert signal.pending_stop_price == pytest.approx(95.8)
    assert signal.take_profit is None


def test_impulse_detected_diagnostic_and_xray():
    strategy = BtcPB1ShallowPullback(_fast_params())
    _feed(strategy, LONG_ROWS)
    detected = [e for e in strategy.diagnostic_events if e.stage == "impulse_detected"]
    assert detected
    assert detected[0].metadata["impulse_size_atr"] == pytest.approx(1.6667, abs=1e-3)
    xray = [x for x in strategy.xray_evaluations if x.rule == "impulse_atr"]
    assert any(x.result == "PASS" for x in xray)


# --- Shallow pullback depth (section 4) ---------------------------------------------


def test_shallow_pullback_valid_depth_reaches_confirmation_stage():
    strategy = BtcPB1ShallowPullback(_fast_params())
    strategy.atr.update(Candle(pd.Timestamp("2024-01-01", tz=UTC), 100, 101.5, 100, 101, 1))
    structure = _Structure(Direction.LONG, impulse_high=105.0, impulse_low=102.5, impulse_size=2.5,
                           impulse_size_atr=1.6667, impulse_start=pd.Timestamp("2024-01-01", tz=UTC),
                           impulse_end=pd.Timestamp("2024-01-01", tz=UTC), deepest_price=105.0)
    strategy.state = strategy.state.__class__.PULLBACK
    strategy.structure = structure
    # retracement = (105.0 - 104.5) / 2.5 = 20% exactly -> valid, at the boundary.
    candle = Candle(pd.Timestamp("2024-01-01 02:15", tz=UTC), 104.8, 105.0, 104.5, 104.6, 1)
    strategy._advance_pullback(candle, ema_fast=100.0, ema_slow=100.0, atr=1.5)
    valid_events = [e for e in strategy.diagnostic_events if e.stage == "pullback_depth_valid"]
    assert valid_events
    assert valid_events[0].metadata["retracement_percent"] == pytest.approx(0.20)


def test_invalid_too_shallow_pullback_never_reaches_confirmation():
    strategy = BtcPB1ShallowPullback(_fast_params())
    structure = _Structure(Direction.LONG, impulse_high=105.0, impulse_low=102.5, impulse_size=2.5,
                           impulse_size_atr=1.6667, impulse_start=pd.Timestamp("2024-01-01", tz=UTC),
                           impulse_end=pd.Timestamp("2024-01-01", tz=UTC), deepest_price=105.0)
    strategy.state = strategy.state.__class__.PULLBACK
    strategy.structure = structure
    # retracement = (105.0 - 104.8) / 2.5 = 8%, below the 20% minimum.
    candle = Candle(pd.Timestamp("2024-01-01 02:15", tz=UTC), 104.9, 105.0, 104.8, 104.9, 1)
    signal = strategy._advance_pullback(candle, ema_fast=100.0, ema_slow=100.0, atr=1.5)
    assert signal is None
    assert not any(e.stage in ("pullback_depth_valid", "confirmation_evaluated") for e in strategy.diagnostic_events)
    assert strategy.state == strategy.state.__class__.PULLBACK  # still within the allowed window


def test_invalid_too_deep_pullback_is_rejected_immediately():
    strategy = BtcPB1ShallowPullback(_fast_params())
    structure = _Structure(Direction.LONG, impulse_high=105.0, impulse_low=102.5, impulse_size=2.5,
                           impulse_size_atr=1.6667, impulse_start=pd.Timestamp("2024-01-01", tz=UTC),
                           impulse_end=pd.Timestamp("2024-01-01", tz=UTC), deepest_price=105.0)
    strategy.state = strategy.state.__class__.PULLBACK
    strategy.structure = structure
    # retracement = (105.0 - 101.8) / 2.5 = 128%, far past the 45% maximum.
    candle = Candle(pd.Timestamp("2024-01-01 02:15", tz=UTC), 102.0, 102.2, 101.8, 102.0, 1)
    signal = strategy._advance_pullback(candle, ema_fast=100.0, ema_slow=100.0, atr=1.5)
    assert signal is None
    rejected = [e for e in strategy.diagnostic_events if e.stage == "pullback_rejected"]
    assert rejected and rejected[0].reason == "retracement exceeded maximum"
    assert strategy.state == strategy.state.__class__.IDLE
    assert strategy.structure is None


# --- Stop / risk (section 7) ---------------------------------------------------------


def test_long_stop_calculation_matches_pullback_low_minus_buffer():
    strategy = BtcPB1ShallowPullback(_fast_params())
    signals = _feed(strategy, LONG_ROWS)
    signal = next(s for s in signals if s is not None)
    # deepest_price = 104.5 (candle9 low), ATR9 = 1.5, stop = 104.5 - 0.20*1.5 = 104.2
    assert signal.pending_stop_price == pytest.approx(104.2)


def test_short_stop_calculation_matches_pullback_high_plus_buffer():
    strategy = BtcPB1ShallowPullback(_fast_params())
    signals = _feed(strategy, SHORT_ROWS)
    signal = next(s for s in signals if s is not None)
    # deepest_price = 95.5 (mirrored candle9 high), ATR9 = 1.5, stop = 95.5 + 0.20*1.5 = 95.8
    assert signal.pending_stop_price == pytest.approx(95.8)


def test_stop_atr_rejection_outside_safety_range():
    strategy = BtcPB1ShallowPullback(_fast_params())
    structure = _Structure(Direction.LONG, impulse_high=105.0, impulse_low=104.9, impulse_size=0.1,
                           impulse_size_atr=1.6667, impulse_start=pd.Timestamp("2024-01-01", tz=UTC),
                           impulse_end=pd.Timestamp("2024-01-01", tz=UTC), deepest_price=104.99)
    candle = Candle(pd.Timestamp("2024-01-01 02:15", tz=UTC), 104.99, 105.05, 104.98, 105.03, 1)
    signal = strategy._construct_entry(candle, structure, atr=0.01)
    assert signal is None
    rejected = [e for e in strategy.diagnostic_events if e.stage == "risk_stop_rejected"]
    assert rejected
    xray = next(x for x in strategy.xray_evaluations if x.rule == "stop_atr")
    assert xray.result == "FAIL"
    assert xray.observed_value > strategy.params.maximum_stop_atr


# --- Target (section 8) ---------------------------------------------------------------


def test_pending_stop_never_sets_take_profit():
    """Target is a fixed 3R applied by the audited engine's BacktestSettings.risk_reward_ratio;
    a strategy-supplied take_profit is structurally rejected by engine/execution.py."""
    strategy = BtcPB1ShallowPullback(_fast_params())
    signals = _feed(strategy, LONG_ROWS)
    signal = next(s for s in signals if s is not None)
    assert signal.take_profit is None
    assert strategy.params.reward_multiple == pytest.approx(3.0)


# --- Duplicate-structure prevention / expiry (section 9) -----------------------------


def test_duplicate_structure_prevention_while_pending_order_is_open():
    strategy = BtcPB1ShallowPullback(_fast_params())
    _feed(strategy, LONG_ROWS)  # warms H1 context and leaves state reset to IDLE post-signal
    pending = PendingOrder(
        direction=Direction.LONG, signal_time=pd.Timestamp("2024-01-01 02:15", tz=UTC),
        created_time=pd.Timestamp("2024-01-01 02:15", tz=UTC), trigger_price=106.15, stop_price=104.2,
        expiry_time=pd.Timestamp("2024-01-01 03:00", tz=UTC), created_bar_index=9, expiry_bar_index=11,
        quantity=1.0, planned_risk=100.0, estimated_stop_loss=104.2, leverage_capped=False, setup_id=SETUP_ID,
    )
    strategy.on_execution_state(ExecutionState(balance=10_000.0, pending_order=pending, position=None))
    # A fresh, otherwise-qualifying candle must not start a second structure while one is pending.
    candle = Candle(pd.Timestamp("2024-01-01 02:30", tz=UTC), 105.8, 108.0, 105.5, 107.5, 1)
    signal = strategy.on_candle(candle)
    assert signal is None
    assert strategy.state == strategy.state.__class__.IDLE
    assert strategy.structure is None


def test_pending_order_expiry_emits_diagnostic():
    strategy = BtcPB1ShallowPullback(_fast_params())
    pending = PendingOrder(
        direction=Direction.LONG, signal_time=pd.Timestamp("2024-01-01", tz=UTC),
        created_time=pd.Timestamp("2024-01-01", tz=UTC), trigger_price=106.15, stop_price=104.2,
        expiry_time=pd.Timestamp("2024-01-01 03:00", tz=UTC), created_bar_index=9, expiry_bar_index=11,
        quantity=1.0, planned_risk=100.0, estimated_stop_loss=104.2, leverage_capped=False, setup_id=SETUP_ID,
    )
    strategy.on_execution_state(ExecutionState(balance=10_000.0, pending_order=pending, position=None))
    strategy.on_execution_state(ExecutionState(balance=10_000.0, pending_order=None, position=None))
    expired = [e for e in strategy.diagnostic_events if e.stage == "pending_order_expired"]
    assert expired and expired[0].component == SETUP_ID


# --- Diagnostic events / X-Ray (section 11) -------------------------------------------


def test_diagnostic_events_cover_full_pipeline():
    strategy = BtcPB1ShallowPullback(_fast_params())
    _feed(strategy, LONG_ROWS)
    stages = {e.stage for e in strategy.diagnostic_events}
    for expected in ("h1_context_evaluated", "impulse_detected", "pullback_started",
                     "pullback_depth_valid", "confirmation_evaluated", "risk_stop_valid",
                     "pending_order_created"):
        assert expected in stages, f"missing diagnostic stage: {expected}"


def test_xray_values_expose_rule_level_checks():
    strategy = BtcPB1ShallowPullback(_fast_params())
    _feed(strategy, LONG_ROWS)
    rules = {x.rule for x in strategy.xray_evaluations}
    for expected in ("trend_direction", "ema_separation_atr", "impulse_atr", "retracement_percent",
                     "confirmation_body_percent", "confirmation_close_location",
                     "confirmation_range_atr", "stop_atr"):
        assert expected in rules, f"missing X-Ray rule: {expected}"
    stop_atr = next(x for x in strategy.xray_evaluations if x.rule == "stop_atr")
    assert stop_atr.observed_value == pytest.approx((106.15 - 104.2) / 1.5)


# --- Registry (section 10) --------------------------------------------------------------


def test_registry_status_is_research():
    descriptor = discover_builtin_strategies().get(STRATEGY_ID)
    assert descriptor.metadata.status is StrategyStatus.RESEARCH
    assert descriptor.metadata.supported_instruments == ("BTCUSD",)
    assert "15m" in descriptor.required_timeframes and "1h" in descriptor.required_timeframes


def test_registry_parameters_are_tunable_except_reward_multiple():
    descriptor = discover_builtin_strategies().get(STRATEGY_ID)
    tunable = {p.name: p.optimization_allowed for p in descriptor.parameters}
    assert tunable["impulse_minimum_range_atr"] is True
    assert tunable["reward_multiple"] is False  # frozen: matches the audited engine's fixed 3R


def test_registry_supports_parameter_overrides():
    descriptor = discover_builtin_strategies().get(STRATEGY_ID)
    strategy = descriptor.create({"impulse_minimum_range_atr": 1.8})
    assert strategy.params.impulse_minimum_range_atr == pytest.approx(1.8)


# --- Parameter validation -----------------------------------------------------------------


def test_invalid_parameter_ordering_rejected():
    with pytest.raises(ValueError, match="Pullback retracement"):
        PB1Parameters(pullback_minimum_retracement_percent=0.5, pullback_maximum_retracement_percent=0.3)
