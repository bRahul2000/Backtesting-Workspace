"""Deterministic tests for the PB2 reclaim/acceptance research components.

Indicator lengths are shrunk so every threshold is hand-checkable, then the
real state machine is run and the observed prices are verified against the
arithmetic the rules specify (trigger = acceptance extreme + entry buffer x ATR,
stop = structural anchor -/+ stop buffer x ATR).
"""
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd
import pytest

from core.config import BacktestConfig, DatasetRole
from engine.models import (
    Candle, Direction, ExecutionState, PendingOrder, Position, Signal, Trade,
)
from strategies.base_strategy import (
    StrategyStatus, effective_parameter_payload, parameter_fingerprint,
)
from strategies.btc_pb2_reclaim_acceptance import (
    ACCEPTANCE_LEVEL_HOLD, ACCEPTANCE_MODES, ACCEPTANCE_RECLAIM_ONLY, ACCEPTANCE_STRICT,
    PB2Parameters, PB2State, TUNABLE_PARAMETERS, _Structure, body_percent,
    close_location_percent,
)
from strategies.btc_pb2_reclaim_long import BtcPB2ReclaimLong
from strategies.btc_pb2_reclaim_short import BtcPB2ReclaimShort
from strategies.registry import discover_builtin_strategies

START = pd.Timestamp("2021-01-01 00:00", tz="UTC")
MIRROR = 220.0
LONG_ID = "BTC_PB2_RECLAIM_LONG_V1"
SHORT_ID = "BTC_PB2_RECLAIM_SHORT_V1"


def _fast(**overrides) -> PB2Parameters:
    """Short indicators so ATR and the H1 regime converge within a few bars."""
    base = dict(h1_fast_ema=1, h1_slow_ema=2, h1_atr_length=1, h1_slope_lookback=1,
                m15_atr_length=3, m15_ema20_length=2, m15_ema50_length=3,
                structure_lookback=3)
    base.update(overrides)
    return PB2Parameters(**base)


def _candles(rows) -> list[Candle]:
    return [Candle(START + pd.Timedelta(minutes=15 * index), open_, high, low, close, 1.0)
            for index, (open_, high, low, close) in enumerate(rows)]


def _mirror(row):
    open_, high, low, close = row
    return (MIRROR - open_, MIRROR - low, MIRROR - high, MIRROR - close)


# Eight warmup bars complete two H1 buckets with rising closes, which is what
# makes H1 EMA50 > EMA200; then three structure bars set a 110.0 high; then
# displacement, retest, reclaim and acceptance.
LONG_ROWS = [
    (100.0, 100.6, 99.6, 100.4), (100.4, 101.2, 100.2, 101.0),
    (101.0, 101.8, 100.8, 101.6), (101.6, 102.4, 101.4, 102.2),
    (102.2, 103.2, 102.0, 103.0), (103.0, 104.2, 102.8, 104.0),
    (104.0, 105.2, 103.8, 105.0), (105.0, 106.2, 104.8, 106.0),
    (106.0, 110.0, 105.8, 108.0), (108.0, 110.0, 107.5, 109.0),
    (109.0, 110.0, 108.2, 109.5),
    (110.5, 116.0, 110.3, 115.6),   # displacement
    (115.0, 115.2, 110.1, 111.0),   # retest only (bearish -> not a reclaim)
    (111.0, 113.0, 110.8, 112.8),   # reclaim
    (112.9, 114.0, 112.5, 113.5),   # acceptance -> entry
]
SHORT_ROWS = [_mirror(row) for row in LONG_ROWS]

DISPLACEMENT_INDEX = 11
RETEST_INDEX = 12
RECLAIM_INDEX = 13
ACCEPTANCE_INDEX = 14


def _feed(strategy, rows, stop_after=None):
    signals = []
    for index, candle in enumerate(_candles(rows)):
        signals.append(strategy.on_candle(candle))
        if stop_after is not None and index == stop_after:
            break
    return signals


def _stages(strategy, stage):
    return [event for event in strategy.diagnostic_events if event.stage == stage]


def _rules(strategy):
    return {row.rule for row in strategy.xray_evaluations}


# --- H1 context ---------------------------------------------------------------------------


def test_long_context_requires_fast_above_slow():
    strategy = BtcPB2ReclaimLong(_fast())
    _feed(strategy, LONG_ROWS, stop_after=DISPLACEMENT_INDEX)
    assert _stages(strategy, "context_evaluated")
    assert all(event.metadata["direction"] == "LONG"
               for event in _stages(strategy, "context_evaluated"))


def test_short_context_rejects_an_uptrend():
    """The LONG sequence is an uptrend, so the SHORT component must never qualify."""
    strategy = BtcPB2ReclaimShort(_fast())
    _feed(strategy, LONG_ROWS)
    assert not _stages(strategy, "context_evaluated")
    assert _stages(strategy, "context_rejected")
    assert strategy.state is PB2State.SEARCHING_DISPLACEMENT


def test_short_context_confirms_on_the_mirrored_downtrend():
    strategy = BtcPB2ReclaimShort(_fast())
    _feed(strategy, SHORT_ROWS, stop_after=DISPLACEMENT_INDEX)
    assert _stages(strategy, "context_evaluated")


# --- Structure level ----------------------------------------------------------------------


def test_structure_level_excludes_the_displacement_candle():
    """The lookback is the bars *preceding* the displacement, never the bar itself."""
    strategy = BtcPB2ReclaimLong(_fast())
    _feed(strategy, LONG_ROWS, stop_after=DISPLACEMENT_INDEX)
    detected = _stages(strategy, "displacement_detected")
    assert len(detected) == 1
    # Highs of the three preceding bars are all 110.0; the displacement bar's
    # own high of 116.0 must not raise the level.
    assert detected[0].metadata["structure_level"] == pytest.approx(110.0)
    assert detected[0].metadata["displacement_high"] == pytest.approx(116.0)


def test_structure_level_uses_the_full_production_lookback():
    strategy = BtcPB2ReclaimLong(_fast(structure_lookback=12))
    rows = list(LONG_ROWS[:8])
    # Twelve narrow structure bars, one of which prints the 110.0 high that
    # becomes the level; narrow ranges keep ATR small enough to displace.
    rows += [(107.0, 110.0 if index == 4 else 108.0, 107.0, 107.5) for index in range(12)]
    rows.append((110.5, 116.0, 110.3, 115.6))
    strategy_signals = _feed(strategy, rows)
    assert strategy_signals[-1] is None
    detected = _stages(strategy, "displacement_detected")
    assert len(detected) == 1
    assert detected[0].metadata["structure_level"] == pytest.approx(110.0)


# --- Displacement -------------------------------------------------------------------------


def test_valid_long_displacement_transitions_to_waiting_retest():
    strategy = BtcPB2ReclaimLong(_fast())
    _feed(strategy, LONG_ROWS, stop_after=DISPLACEMENT_INDEX)
    assert strategy.state is PB2State.WAITING_RETEST
    metadata = _stages(strategy, "displacement_detected")[0].metadata
    assert metadata["body_percent"] >= 0.70
    assert metadata["close_location"] >= 0.80
    assert metadata["range_atr"] >= 1.30


def test_valid_short_displacement_transitions_to_waiting_retest():
    strategy = BtcPB2ReclaimShort(_fast())
    _feed(strategy, SHORT_ROWS, stop_after=DISPLACEMENT_INDEX)
    assert strategy.state is PB2State.WAITING_RETEST
    metadata = _stages(strategy, "displacement_detected")[0].metadata
    assert metadata["body_percent"] >= 0.70
    assert metadata["close_location"] >= 0.80


def test_weak_displacement_is_rejected():
    """A small-bodied candle that still breaks the level must not displace."""
    strategy = BtcPB2ReclaimLong(_fast())
    rows = list(LONG_ROWS[:11]) + [(110.5, 116.0, 110.3, 111.5)]
    _feed(strategy, rows)
    assert strategy.state is PB2State.SEARCHING_DISPLACEMENT
    assert not _stages(strategy, "displacement_detected")
    assert _stages(strategy, "displacement_rejected")[-1].reason == "insufficient body"


def test_zero_range_candle_is_rejected_safely():
    assert body_percent(Candle(START, 100.0, 100.0, 100.0, 100.0, 1.0)) is None
    assert close_location_percent(Candle(START, 100.0, 100.0, 100.0, 100.0, 1.0)) is None


# --- Retest, invalidation, expiry ---------------------------------------------------------


def test_retest_detected_within_the_window():
    strategy = BtcPB2ReclaimLong(_fast())
    _feed(strategy, LONG_ROWS, stop_after=RETEST_INDEX)
    retest = _stages(strategy, "retest_detected")
    assert len(retest) == 1
    assert retest[0].metadata["bars_to_retest"] == 1
    assert retest[0].metadata["retest_extreme"] == pytest.approx(110.1)
    assert strategy.state is PB2State.WAITING_RECLAIM


def test_retest_expires_when_price_never_returns():
    strategy = BtcPB2ReclaimLong(_fast(retest_maximum_bars=2))
    rows = list(LONG_ROWS[:12]) + [(115.6, 117.0, 115.4, 116.5), (116.5, 118.0, 116.3, 117.5)]
    _feed(strategy, rows)
    expired = _stages(strategy, "retest_expired")
    assert len(expired) == 1
    assert expired[0].reason == "structure level never retested"
    assert strategy.state is PB2State.SEARCHING_DISPLACEMENT
    assert strategy.structure is None


def test_structure_invalidated_by_a_close_through_the_displacement_low():
    strategy = BtcPB2ReclaimLong(_fast())
    rows = list(LONG_ROWS[:12]) + [(115.0, 115.2, 109.0, 109.5)]
    _feed(strategy, rows)
    invalidated = _stages(strategy, "structure_invalidated")
    assert len(invalidated) == 1
    assert invalidated[0].metadata["close"] < invalidated[0].metadata["displacement_low"]
    assert strategy.state is PB2State.SEARCHING_DISPLACEMENT


# --- Reclaim ------------------------------------------------------------------------------


def test_long_reclaim_confirms_and_waits_for_acceptance():
    strategy = BtcPB2ReclaimLong(_fast())
    _feed(strategy, LONG_ROWS, stop_after=RECLAIM_INDEX)
    confirmed = _stages(strategy, "reclaim_confirmed")
    assert len(confirmed) == 1
    assert confirmed[0].metadata["reclaim_close"] == pytest.approx(112.8)
    assert strategy.state is PB2State.WAITING_ACCEPTANCE


def test_short_reclaim_confirms_and_waits_for_acceptance():
    strategy = BtcPB2ReclaimShort(_fast())
    _feed(strategy, SHORT_ROWS, stop_after=RECLAIM_INDEX)
    assert len(_stages(strategy, "reclaim_confirmed")) == 1
    assert strategy.state is PB2State.WAITING_ACCEPTANCE


def test_same_bar_retest_and_reclaim_still_requires_a_separate_acceptance_bar():
    """One bar may both retest and reclaim, because a bar's close is by
    construction its last price: a low inside the retest tolerance necessarily
    precedes the reclaiming close, so no intrabar ordering is assumed. The
    conservative part is that acceptance is never collapsed into the same bar.
    """
    strategy = BtcPB2ReclaimLong(_fast())
    rows = list(LONG_ROWS[:12]) + [(111.0, 113.0, 110.1, 112.8)]
    signals = _feed(strategy, rows)
    assert len(_stages(strategy, "retest_detected")) == 1
    assert len(_stages(strategy, "reclaim_confirmed")) == 1
    retest_time = _stages(strategy, "retest_detected")[0].timestamp
    reclaim_time = _stages(strategy, "reclaim_confirmed")[0].timestamp
    assert retest_time == reclaim_time
    # No entry on that bar: acceptance is still owed a separate candle.
    assert signals[-1] is None
    assert strategy.state is PB2State.WAITING_ACCEPTANCE
    assert not _stages(strategy, "acceptance_evaluated")


# --- Acceptance ---------------------------------------------------------------------------


def test_acceptance_failure_resets_the_structure():
    strategy = BtcPB2ReclaimLong(_fast())
    rows = list(LONG_ROWS[:14]) + [(112.9, 113.0, 108.0, 109.0)]
    signals = _feed(strategy, rows)
    failed = _stages(strategy, "acceptance_failed")
    assert len(failed) == 1
    assert failed[0].reason == "close fell back through the structure level"
    assert signals[-1] is None
    assert strategy.state is PB2State.SEARCHING_DISPLACEMENT
    assert strategy.structure is None


def test_acceptance_requires_holding_the_reclaim_close():
    strategy = BtcPB2ReclaimLong(_fast())
    rows = list(LONG_ROWS[:14]) + [(112.9, 113.0, 111.0, 111.5)]
    _feed(strategy, rows)
    failed = _stages(strategy, "acceptance_failed")
    assert len(failed) == 1
    assert failed[0].reason == "close did not hold the reclaim close"


# --- Entry, stop and target ---------------------------------------------------------------


def test_long_entry_prices_are_hand_verified():
    strategy = BtcPB2ReclaimLong(_fast())
    signals = _feed(strategy, LONG_ROWS)
    signal = signals[ACCEPTANCE_INDEX]
    assert isinstance(signal, Signal)
    assert signal.direction is Direction.LONG
    atr = strategy.atr._average.value
    # trigger = acceptance high + 0.05 ATR; stop = lowest low across the
    # retest/reclaim/acceptance bars (110.1) - 0.20 ATR.
    assert signal.pending_entry_price == pytest.approx(114.0 + 0.05 * atr)
    assert signal.pending_stop_price == pytest.approx(110.1 - 0.20 * atr)
    assert signal.pending_expiry_bars == 2
    assert strategy.state is PB2State.PENDING_ENTRY


def test_short_entry_prices_are_hand_verified():
    strategy = BtcPB2ReclaimShort(_fast())
    signals = _feed(strategy, SHORT_ROWS)
    signal = signals[ACCEPTANCE_INDEX]
    assert isinstance(signal, Signal)
    assert signal.direction is Direction.SHORT
    atr = strategy.atr._average.value
    assert signal.pending_entry_price == pytest.approx(MIRROR - 114.0 - 0.05 * atr)
    assert signal.pending_stop_price == pytest.approx(MIRROR - 110.1 + 0.20 * atr)


def test_pending_stop_never_carries_a_target():
    """The fixed 3R target belongs to the audited engine, not to PB2."""
    strategy = BtcPB2ReclaimLong(_fast())
    signal = _feed(strategy, LONG_ROWS)[ACCEPTANCE_INDEX]
    assert signal.take_profit is None
    assert signal.stop_loss == signal.pending_stop_price
    assert strategy.params.reward_multiple == 3.0


def _structure_for_stop_test(anchor: float) -> _Structure:
    return _Structure(
        direction=Direction.LONG, structure_level=110.0,
        structure_start=START, structure_end=START, displacement_time=START,
        displacement_high=116.0, displacement_low=110.3, displacement_range_atr=2.0,
        displacement_body_percent=0.9, displacement_close_location=0.93,
        breakout_distance_atr=1.0, reclaim_close=112.8, stop_anchor=anchor,
    )


def test_stop_below_the_minimum_atr_is_rejected():
    strategy = BtcPB2ReclaimLong(_fast())
    candle = Candle(START, 112.9, 114.0, 112.5, 113.5, 1.0)
    # Anchor just under the trigger: stop distance collapses below 0.50 ATR.
    signal = strategy._construct_entry(candle, _structure_for_stop_test(113.9), 10.0)
    assert signal is None
    assert _stages(strategy, "risk_rejected")[0].reason == "stop distance outside the safety range"
    assert strategy.state is PB2State.SEARCHING_DISPLACEMENT


def test_stop_above_the_maximum_atr_is_rejected():
    strategy = BtcPB2ReclaimLong(_fast())
    candle = Candle(START, 112.9, 114.0, 112.5, 113.5, 1.0)
    signal = strategy._construct_entry(candle, _structure_for_stop_test(100.0), 1.0)
    assert signal is None
    rejected = _stages(strategy, "risk_rejected")[0]
    assert rejected.metadata["stop_atr"] > 2.50


def test_structural_stop_anchors_on_the_deepest_structure_price():
    strategy = BtcPB2ReclaimLong(_fast())
    _feed(strategy, LONG_ROWS)
    risk = _stages(strategy, "risk_evaluated")[0]
    assert risk.metadata["stop_anchor"] == pytest.approx(110.1)
    assert risk.metadata["anchor_bars"] == 3  # retest, reclaim and acceptance bars
    assert 0.50 <= risk.metadata["stop_atr"] <= 2.50


# --- Order lifecycle and state isolation ---------------------------------------------------


def _pending(setup_id: str) -> PendingOrder:
    return PendingOrder(
        direction=Direction.LONG, signal_time=START, created_time=START,
        trigger_price=114.2, stop_price=109.5, expiry_time=START + pd.Timedelta(minutes=30),
        created_bar_index=14, expiry_bar_index=16, quantity=0.1, planned_risk=25.0,
        estimated_stop_loss=25.0, leverage_capped=False, setup_id=setup_id,
    )


def test_pending_expiry_emits_a_diagnostic_and_resets():
    strategy = BtcPB2ReclaimLong(_fast())
    _feed(strategy, LONG_ROWS)
    strategy.on_execution_state(ExecutionState(10_000.0, _pending("PB2_RECLAIM_LONG"), None))
    strategy.on_execution_state(ExecutionState(10_000.0, None, None))
    expired = _stages(strategy, "pending_expired")
    assert len(expired) == 1
    assert strategy.state is PB2State.SEARCHING_DISPLACEMENT


def test_open_position_does_not_emit_a_phantom_expiry():
    """A filled pending must not look like an expiry on later bars."""
    strategy = BtcPB2ReclaimLong(_fast())
    position = Position(
        trade_id=1, direction=Direction.LONG, signal_time=START, entry_time=START,
        entry_price=114.2, stop_loss=109.5, take_profit=128.3, quantity=0.1,
        initial_risk=25.0, entry_commission=0.0, entry_bar_index=15,
    )
    strategy.on_execution_state(ExecutionState(10_000.0, _pending("PB2_RECLAIM_LONG"), None))
    strategy.on_execution_state(ExecutionState(10_000.0, None, position, opened_position=position))
    strategy.on_execution_state(ExecutionState(10_000.0, None, position))
    assert not _stages(strategy, "pending_expired")
    assert strategy.state is PB2State.IN_TRADE


def test_duplicate_entries_from_one_displacement_are_prevented():
    strategy = BtcPB2ReclaimLong(_fast())
    signals = _feed(strategy, LONG_ROWS)
    assert sum(1 for signal in signals if signal is not None) == 1
    # The structure is consumed at the signal, so no second entry can follow it.
    assert strategy.structure is None
    strategy.on_execution_state(ExecutionState(10_000.0, _pending("PB2_RECLAIM_LONG"), None))
    extra = strategy.on_candle(Candle(START + pd.Timedelta(minutes=15 * 15),
                                      113.5, 115.0, 113.0, 114.8, 1.0))
    assert extra is None


def test_long_and_short_components_keep_independent_state():
    long_strategy, short_strategy = BtcPB2ReclaimLong(_fast()), BtcPB2ReclaimShort(_fast())
    for candle in _candles(LONG_ROWS):
        long_strategy.on_candle(candle)
        short_strategy.on_candle(candle)
    assert long_strategy.state is PB2State.PENDING_ENTRY
    assert short_strategy.state is PB2State.SEARCHING_DISPLACEMENT
    assert long_strategy.structure is None and short_strategy.structure is None
    assert long_strategy.diagnostic_events is not short_strategy.diagnostic_events
    assert _stages(long_strategy, "pending_created")
    assert not _stages(short_strategy, "pending_created")


# --- Diagnostics and X-Ray -----------------------------------------------------------------


def test_diagnostic_events_cover_the_full_pipeline():
    strategy = BtcPB2ReclaimLong(_fast())
    _feed(strategy, LONG_ROWS)
    stages = {event.stage for event in strategy.diagnostic_events}
    assert {"context_evaluated", "context_rejected", "structure_level_created",
            "displacement_evaluated", "displacement_rejected", "displacement_detected",
            "waiting_retest", "retest_detected", "reclaim_evaluated", "reclaim_rejected",
            "reclaim_confirmed", "acceptance_evaluated", "acceptance_confirmed",
            "risk_evaluated", "pending_created"}.issubset(stages)


def test_xray_exposes_rule_level_values():
    strategy = BtcPB2ReclaimLong(_fast())
    _feed(strategy, LONG_ROWS)
    assert {"h1_direction", "h1_separation_atr", "h1_fast_slope_atr", "h1_slow_slope_atr",
            "structure_level", "displacement_range_atr", "displacement_body_percent",
            "displacement_close_location", "breakout_distance_atr", "bars_to_retest",
            "retest_overshoot_atr", "reclaim_body_percent", "reclaim_close_location",
            "reclaim_range_atr", "acceptance_distance_atr", "acceptance_range_atr",
            "stop_atr"}.issubset(_rules(strategy))
    assert all(row.result in ("PASS", "FAIL") for row in strategy.xray_evaluations)
    assert all(row.strategy_id == "BTC_PB2_RECLAIM_LONG_V1" for row in strategy.xray_evaluations)


# --- Registry and fingerprints --------------------------------------------------------------


def test_both_components_register_as_research():
    registry = discover_builtin_strategies()
    for strategy_id in (LONG_ID, SHORT_ID):
        descriptor = registry.get(strategy_id)
        assert descriptor.metadata.status is StrategyStatus.RESEARCH
        assert descriptor.metadata.supported_instruments == ("BTCUSD",)
        assert set(descriptor.required_timeframes) == {"15m", "1h"}


def test_components_have_independent_strategy_fingerprints():
    registry = discover_builtin_strategies()
    long_fingerprint = registry.get(LONG_ID).metadata.strategy_fingerprint
    short_fingerprint = registry.get(SHORT_ID).metadata.strategy_fingerprint
    assert long_fingerprint != short_fingerprint


def test_effective_parameter_fingerprint_covers_every_default():
    registry = discover_builtin_strategies()
    for strategy_id in (LONG_ID, SHORT_ID):
        descriptor = registry.get(strategy_id)
        payload = effective_parameter_payload(descriptor, {})
        assert payload == asdict(PB2Parameters())
        assert parameter_fingerprint(payload) != parameter_fingerprint({})
        # Indicator lengths are not exposed as tunable parameters but must still
        # be part of the reproducibility payload.
        assert payload["h1_slow_ema"] == 200
        assert payload["pending_expiry_bars"] == 2


def test_one_changed_parameter_changes_the_fingerprint():
    descriptor = discover_builtin_strategies().get(LONG_ID)
    baseline = parameter_fingerprint(effective_parameter_payload(descriptor, {}))
    changed = parameter_fingerprint(
        effective_parameter_payload(descriptor, {"displacement_minimum_range_atr": 1.5}))
    assert baseline != changed
    repeated = parameter_fingerprint(
        effective_parameter_payload(descriptor, {"displacement_minimum_range_atr": 1.5}))
    assert changed == repeated


def test_registered_parameters_are_tunable_except_the_reward_multiple():
    descriptor = discover_builtin_strategies().get(LONG_ID)
    tunable = {p.name: p.optimization_allowed for p in descriptor.parameters}
    assert set(TUNABLE_PARAMETERS).issubset(tunable)
    assert all(tunable[name] for name in TUNABLE_PARAMETERS)
    assert tunable["reward_multiple"] is False


# --- Acceptance architecture modes (Phase A.1 ablation) --------------------------------------


def test_strict_acceptance_is_the_default_and_demands_expansion():
    """STRICT is the Phase A baseline: holding the level is not enough."""
    assert PB2Parameters().acceptance_mode == ACCEPTANCE_STRICT
    strategy = BtcPB2ReclaimLong(_fast())
    rows = list(LONG_ROWS[:14]) + [(112.9, 113.0, 111.0, 111.5)]
    signals = _feed(strategy, rows)
    assert signals[-1] is None
    failed = _stages(strategy, "acceptance_failed")
    assert len(failed) == 1
    assert failed[0].reason == "close did not hold the reclaim close"
    assert failed[0].metadata["beyond_level"] is True


def test_level_hold_acceptance_admits_the_same_bar_strict_rejects():
    """Variant B keeps the separate bar but drops only the expansion demand."""
    strategy = BtcPB2ReclaimLong(_fast(acceptance_mode=ACCEPTANCE_LEVEL_HOLD))
    rows = list(LONG_ROWS[:14]) + [(112.9, 113.0, 111.0, 111.5)]
    signals = _feed(strategy, rows)
    assert not _stages(strategy, "acceptance_failed")
    confirmed = _stages(strategy, "acceptance_confirmed")
    assert len(confirmed) == 1
    assert confirmed[0].metadata["held_reclaim"] is False
    assert confirmed[0].metadata["acceptance_mode"] == ACCEPTANCE_LEVEL_HOLD
    signal = signals[-1]
    assert isinstance(signal, Signal)
    atr = strategy.atr._average.value
    assert signal.pending_entry_price == pytest.approx(113.0 + 0.05 * atr)


def test_level_hold_still_rejects_a_close_back_through_the_level():
    strategy = BtcPB2ReclaimLong(_fast(acceptance_mode=ACCEPTANCE_LEVEL_HOLD))
    rows = list(LONG_ROWS[:14]) + [(112.9, 113.0, 108.0, 109.0)]
    signals = _feed(strategy, rows)
    assert signals[-1] is None
    assert _stages(strategy, "acceptance_failed")[0].reason == \
        "close fell back through the structure level"


def test_reclaim_only_enters_from_the_reclaim_bar_without_an_acceptance_stage():
    """Variant C removes the separate bar entirely: the reclaim candle is the entry."""
    strategy = BtcPB2ReclaimLong(_fast(acceptance_mode=ACCEPTANCE_RECLAIM_ONLY))
    signals = _feed(strategy, LONG_ROWS)
    signal = signals[RECLAIM_INDEX]
    assert isinstance(signal, Signal)
    assert signals[ACCEPTANCE_INDEX] is None
    assert not _stages(strategy, "acceptance_evaluated")
    assert not _stages(strategy, "acceptance_confirmed")
    # Trigger comes off the reclaim candle's high (113.0), a bar earlier than STRICT.
    assert signal.pending_entry_price > 113.0
    assert _stages(strategy, "pending_created")[0].metadata["acceptance_mode"] == \
        ACCEPTANCE_RECLAIM_ONLY


def test_reclaim_only_short_enters_from_the_reclaim_bar():
    strategy = BtcPB2ReclaimShort(_fast(acceptance_mode=ACCEPTANCE_RECLAIM_ONLY))
    signals = _feed(strategy, SHORT_ROWS)
    assert isinstance(signals[RECLAIM_INDEX], Signal)
    assert signals[RECLAIM_INDEX].direction is Direction.SHORT
    assert signals[ACCEPTANCE_INDEX] is None


def test_acceptance_mode_is_part_of_the_parameter_fingerprint():
    descriptor = discover_builtin_strategies().get(LONG_ID)
    fingerprints = {
        mode: parameter_fingerprint(effective_parameter_payload(descriptor, {"acceptance_mode": mode}))
        for mode in ACCEPTANCE_MODES
    }
    assert len(set(fingerprints.values())) == 3
    # The default payload must be identical to an explicit STRICT override.
    assert fingerprints[ACCEPTANCE_STRICT] == parameter_fingerprint(
        effective_parameter_payload(descriptor, {}))


def test_acceptance_mode_is_overridable_but_never_optimizable():
    descriptor = discover_builtin_strategies().get(LONG_ID)
    parameter = next(p for p in descriptor.parameters if p.name == "acceptance_mode")
    assert parameter.optimization_allowed is False
    assert parameter.frozen is False
    assert set(parameter.choices) == set(ACCEPTANCE_MODES)
    assert descriptor.create({"acceptance_mode": ACCEPTANCE_RECLAIM_ONLY}).params.acceptance_mode \
        == ACCEPTANCE_RECLAIM_ONLY
    with pytest.raises(ValueError):
        PB2Parameters(acceptance_mode="SOMETHING_ELSE")


def test_phase_a_long_baseline_still_reproduces(tmp_path):
    """The stored Phase A LONG baseline must survive the architecture-mode change."""
    from math import isclose

    from core.adapters.audited_engine import run_universal_backtest

    config = BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD", strategy_id=LONG_ID,
        timeframe="15m", higher_timeframes=("1h",),
        start_date=pd.Timestamp("2021-01-01", tz="UTC"),
        end_date=pd.Timestamp("2023-12-31 23:45", tz="UTC"),
        dataset_role=DatasetRole.DEVELOPMENT,
    )
    result = run_universal_backtest(
        Path(__file__).resolve().parents[1] / "data" / "btcusd_15m.csv",
        config, ledger_path=tmp_path / "ledger.sqlite3")
    assert result.total_trades == 29
    assert isclose(result.profit_factor, 1.8656360038448085, abs_tol=1e-12)
    assert isclose(result.average_r, 0.5410, abs_tol=1e-4)


def test_parameter_validation_rejects_an_impossible_schema():
    with pytest.raises(ValueError, match="Stop ATR bounds"):
        PB2Parameters(minimum_stop_atr=3.0, maximum_stop_atr=1.0)
    with pytest.raises(ValueError, match="h1_fast_ema"):
        PB2Parameters(h1_fast_ema=200, h1_slow_ema=50)
