"""Deterministic tests for the PB3 confirmed-pivot reclaim/acceptance research component.

Indicator lengths are shrunk so every threshold is hand-checkable, then the real
state machine is run and the observed prices are verified against the arithmetic
the rules specify (trigger = acceptance high + entry buffer x ATR, stop = lowest
retest/reclaim/acceptance low - stop buffer x ATR).

The no-lookahead section is a release blocker for PB3 Phase A: a pivot must be
invisible until both of its right-side confirmation bars have completed, and no
later bar may retroactively change an earlier decision.
"""
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd
import pytest

from core.config import BacktestConfig, DatasetRole
from engine.models import (
    Candle, Direction, ExecutionState, PendingOrder, Position, Signal,
)
from strategies.base_strategy import (
    StrategyStatus, effective_parameter_payload, parameter_fingerprint,
)
from strategies.btc_pb3_pivot_acceptance_long import (
    BtcPB3PivotAcceptanceLong, PB3Parameters, PB3State, TUNABLE_PARAMETERS,
    _Structure, body_percent, close_location_percent,
)
from strategies.registry import discover_builtin_strategies

START = pd.Timestamp("2021-01-01 00:00", tz="UTC")
PB3_ID = "BTC_PB3_PIVOT_ACCEPTANCE_LONG_V1"
PIVOT_PRICE = 110.0


def _fast(**overrides) -> PB3Parameters:
    """Short indicators so ATR and the H1 regime converge within a few bars."""
    base = dict(h1_fast_ema=1, h1_slow_ema=2, h1_atr_length=1, h1_slope_lookback=1,
                m15_atr_length=3, m15_ema20_length=2, m15_ema50_length=3)
    base.update(overrides)
    return PB3Parameters(**base)


def _candles(rows) -> list[Candle]:
    return [Candle(START + pd.Timedelta(minutes=15 * index), open_, high, low, close, 1.0)
            for index, (open_, high, low, close) in enumerate(rows)]


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


# Eight warmup bars complete two H1 buckets with rising closes, which is what
# makes H1 EMA50 > EMA200. Bar 8 prints the 110.0 swing high; bars 9-10 are its
# right-side confirmation bars; then breakout, retest, reclaim, acceptance.
ROWS = [
    (100.0, 100.6, 99.6, 100.4), (100.4, 101.2, 100.2, 101.0),
    (101.0, 101.8, 100.8, 101.6), (101.6, 102.4, 101.4, 102.2),
    (102.2, 103.2, 102.0, 103.0), (103.0, 104.2, 102.8, 104.0),
    (104.0, 105.2, 103.8, 105.0), (105.0, 106.2, 104.8, 106.0),
    (106.0, 110.0, 105.8, 106.5),   # 8  pivot bar, high 110.0
    (106.5, 108.0, 106.0, 106.8),   # 9  first right bar
    (106.8, 107.0, 106.2, 106.6),   # 10 second right bar -> pivot confirmed
    (107.0, 112.0, 106.8, 111.6),   # 11 breakout
    (111.5, 111.7, 110.0, 110.3),   # 12 retest only (bearish -> not a reclaim)
    (110.3, 111.5, 110.2, 111.4),   # 13 reclaim
    (111.4, 112.2, 111.2, 112.0),   # 14 acceptance -> entry
]

PIVOT_INDEX = 8
FIRST_RIGHT_INDEX = 9
CONFIRMATION_INDEX = 10
BREAKOUT_INDEX = 11
RETEST_INDEX = 12
RECLAIM_INDEX = 13
ACCEPTANCE_INDEX = 14

# Same pivot, but the breakout arrives three quiet bars later. Filler highs fall
# monotonically so none of them can register a competing pivot and reset the age.
LATE_BREAKOUT_ROWS = list(ROWS[:11]) + [
    (106.6, 106.9, 106.3, 106.5),
    (106.5, 106.8, 106.2, 106.4),
    (106.4, 106.7, 106.1, 106.3),
    (106.3, 112.0, 106.1, 111.6),   # 14 breakout, pivot now 6 bars old
]


# --- Confirmed pivot detection ---------------------------------------------------------------


def test_pivot_requires_strictly_higher_left_and_at_least_equal_right_bars():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    _feed(strategy, ROWS, stop_after=CONFIRMATION_INDEX)
    confirmed = _stages(strategy, "pivot_confirmed")
    assert len(confirmed) == 1
    metadata = confirmed[0].metadata
    assert metadata["pivot_price"] == pytest.approx(PIVOT_PRICE)
    assert metadata["left_bars"] == 2 and metadata["right_bars"] == 2


def test_a_monotonically_rising_sequence_registers_no_pivot():
    """Every warmup bar makes a new high, so nothing can be a swing high."""
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    _feed(strategy, ROWS, stop_after=7)
    assert not _stages(strategy, "pivot_confirmed")
    assert strategy.active_pivot is None


def test_a_flat_triple_high_registers_exactly_one_pivot():
    """Ties resolve deterministically: strict on the left, >= on the right, so a
    plateau yields the leftmost bar only and never two pivots."""
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    rows = list(ROWS[:8]) + [
        (106.0, 110.0, 105.8, 106.5),   # 8  plateau bar 1
        (106.5, 110.0, 106.0, 106.8),   # 9  plateau bar 2 (equal high)
        (106.8, 110.0, 106.2, 106.6),   # 10 plateau bar 3 (equal high)
        (106.6, 107.0, 106.1, 106.4),   # 11
        (106.4, 106.9, 106.0, 106.3),   # 12
    ]
    _feed(strategy, rows)
    confirmed = _stages(strategy, "pivot_confirmed")
    assert len(confirmed) == 1
    assert confirmed[0].metadata["pivot_timestamp"] == str(START + pd.Timedelta(minutes=15 * 8))


# --- NO-LOOKAHEAD (release blocker for Phase A) -----------------------------------------------


def test_pivot_is_unavailable_until_both_right_bars_have_completed():
    """The staged availability check demanded by the Phase A specification."""
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    candles = _candles(ROWS)

    for candle in candles[:PIVOT_INDEX + 1]:
        strategy.on_candle(candle)
    # The swing high has printed but is only visible historically.
    assert strategy.active_pivot is None

    strategy.on_candle(candles[FIRST_RIGHT_INDEX])
    assert strategy.active_pivot is None

    strategy.on_candle(candles[CONFIRMATION_INDEX])
    pivot = strategy.active_pivot
    assert pivot is not None
    assert pivot.price == pytest.approx(PIVOT_PRICE)
    assert pivot.timestamp == candles[PIVOT_INDEX].timestamp
    assert pivot.confirmation_timestamp == candles[CONFIRMATION_INDEX].timestamp

    # And only now may a breakout use it.
    strategy.on_candle(candles[BREAKOUT_INDEX])
    assert len(_stages(strategy, "breakout_confirmed")) == 1


def test_no_decision_ever_uses_a_pivot_confirmed_on_that_same_bar():
    """Pivot registration runs after the bar's decisions, so every evaluation
    references a pivot whose confirmation timestamp is strictly in the past."""
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    _feed(strategy, ROWS)
    evaluated = _stages(strategy, "breakout_evaluated")
    assert evaluated
    for event in evaluated:
        confirmation = pd.Timestamp(event.metadata["pivot_confirmation_timestamp"])
        assert confirmation < event.timestamp
    for event in _stages(strategy, "breakout_confirmed"):
        assert pd.Timestamp(event.metadata["pivot_confirmation_timestamp"]) < event.timestamp
        assert pd.Timestamp(event.metadata["pivot_timestamp"]) < event.timestamp


def test_future_bars_cannot_retroactively_alter_an_earlier_decision():
    """Two runs sharing a prefix must agree on everything up to the divergence.

    The continuation is mutated aggressively — far higher highs, which is exactly
    what would move a pivot if the detector peeked forward — yet the already
    emitted signal, diagnostics and X-Ray rows must be byte-identical.
    """
    mutated = list(ROWS[:ACCEPTANCE_INDEX + 1]) + [
        (112.0, 130.0, 111.9, 129.5), (129.5, 145.0, 129.0, 144.0),
    ]
    original = list(ROWS[:ACCEPTANCE_INDEX + 1]) + [
        (112.0, 112.1, 111.0, 111.2), (111.2, 111.3, 110.0, 110.1),
    ]

    baseline = BtcPB3PivotAcceptanceLong(_fast())
    variant = BtcPB3PivotAcceptanceLong(_fast())
    baseline_signals = _feed(baseline, original)
    variant_signals = _feed(variant, mutated)

    prefix = ACCEPTANCE_INDEX + 1
    assert baseline_signals[:prefix] == variant_signals[:prefix]
    assert isinstance(baseline_signals[ACCEPTANCE_INDEX], Signal)

    def prefix_events(strategy):
        cutoff = START + pd.Timedelta(minutes=15 * ACCEPTANCE_INDEX)
        return [event for event in strategy.diagnostic_events
                if event.timestamp is None or event.timestamp <= cutoff]

    assert prefix_events(baseline) == prefix_events(variant)
    cutoff = START + pd.Timedelta(minutes=15 * ACCEPTANCE_INDEX)
    assert ([row for row in baseline.xray_evaluations if row.timestamp <= cutoff]
            == [row for row in variant.xray_evaluations if row.timestamp <= cutoff])


def test_raising_a_later_high_cannot_unmake_an_already_confirmed_pivot():
    """A pivot is a fact about completed bars; later highs start new pivots,
    they never revise the confirmed one."""
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    _feed(strategy, ROWS, stop_after=CONFIRMATION_INDEX)
    confirmed_before = strategy.active_pivot
    assert confirmed_before.price == pytest.approx(PIVOT_PRICE)
    recorded = list(_stages(strategy, "pivot_confirmed"))

    # A much higher bar arrives afterwards. It cannot edit the earlier record.
    strategy.on_candle(Candle(START + pd.Timedelta(minutes=15 * 11), 107.0, 140.0, 106.8, 139.0, 1.0))
    assert _stages(strategy, "pivot_confirmed")[:len(recorded)] == recorded
    assert recorded[0].metadata["pivot_price"] == pytest.approx(PIVOT_PRICE)


# --- Pivot age --------------------------------------------------------------------------------


def test_pivot_age_is_measured_from_the_pivot_bar():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    _feed(strategy, ROWS, stop_after=BREAKOUT_INDEX)
    confirmed = _stages(strategy, "breakout_confirmed")[0]
    # Pivot at bar 8, breakout at bar 11: three completed bars, which is also the
    # earliest a pivot can ever be used (right bars + 1).
    assert confirmed.metadata["pivot_age_bars"] == 3


def test_a_stale_pivot_expires_instead_of_producing_a_setup():
    aged = BtcPB3PivotAcceptanceLong(_fast(maximum_pivot_age_bars=5))
    _feed(aged, LATE_BREAKOUT_ROWS)
    expired = _stages(aged, "pivot_expired")
    assert len(expired) == 1
    assert expired[0].metadata["pivot_age_bars"] == 6
    assert not _stages(aged, "breakout_confirmed")
    assert aged.active_pivot is None
    assert aged.state is PB3State.SEARCHING_PIVOT_BREAKOUT


def test_the_same_late_breakout_is_accepted_within_the_baseline_age_cap():
    """Control for the expiry test: only the age cap differs."""
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    assert strategy.params.maximum_pivot_age_bars == 24
    _feed(strategy, LATE_BREAKOUT_ROWS)
    confirmed = _stages(strategy, "breakout_confirmed")
    assert len(confirmed) == 1
    assert confirmed[0].metadata["pivot_age_bars"] == 6
    assert not _stages(strategy, "pivot_expired")


# --- Breakout ---------------------------------------------------------------------------------


def test_valid_breakout_transitions_to_waiting_retest():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    _feed(strategy, ROWS, stop_after=BREAKOUT_INDEX)
    assert strategy.state is PB3State.WAITING_RETEST
    metadata = _stages(strategy, "breakout_confirmed")[0].metadata
    assert metadata["range_atr"] >= 1.00
    assert metadata["body_percent"] >= 0.60
    assert metadata["close_location"] >= 0.70
    assert metadata["breakout_distance_atr"] > 0


def test_a_weak_bodied_candle_through_the_pivot_is_rejected():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    rows = list(ROWS[:11]) + [(107.0, 112.0, 106.8, 110.1)]
    _feed(strategy, rows)
    assert strategy.state is PB3State.SEARCHING_PIVOT_BREAKOUT
    assert not _stages(strategy, "breakout_confirmed")
    assert _stages(strategy, "breakout_rejected")[-1].reason == "insufficient body"


def test_a_close_that_does_not_clear_the_pivot_is_rejected():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    rows = list(ROWS[:11]) + [(107.0, 112.0, 106.8, 109.9)]
    _feed(strategy, rows)
    assert _stages(strategy, "breakout_rejected")[-1].reason == "close did not break the pivot high"


def test_zero_range_candle_is_handled_safely():
    assert body_percent(Candle(START, 100.0, 100.0, 100.0, 100.0, 1.0)) is None
    assert close_location_percent(Candle(START, 100.0, 100.0, 100.0, 100.0, 1.0)) is None


def test_one_confirmed_pivot_produces_at_most_one_structure_attempt():
    """Section 7: a pivot is retired the moment it generates a breakout, so a
    later candle cannot recycle it even after the structure is destroyed."""
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    rows = list(ROWS[:12]) + [
        (111.5, 111.7, 105.0, 105.5),   # 12 closes below the breakout low -> invalidated
        (105.5, 112.0, 105.3, 111.6),   # 13 a second breakout-shaped candle above 110.0
    ]
    _feed(strategy, rows)
    assert len(_stages(strategy, "structure_invalidated")) == 1
    # Only the original breakout exists; bar 13 never even evaluated, because the
    # pivot was retired and no new one had been confirmed yet.
    assert len(_stages(strategy, "breakout_confirmed")) == 1
    bar13 = START + pd.Timedelta(minutes=15 * 13)
    assert not [e for e in _stages(strategy, "breakout_evaluated") if e.timestamp == bar13]
    assert strategy.state is PB3State.SEARCHING_PIVOT_BREAKOUT


# --- Retest, invalidation, expiry ---------------------------------------------------------------


def test_retest_of_the_actual_pivot_level_is_detected():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    _feed(strategy, ROWS, stop_after=RETEST_INDEX)
    retest = _stages(strategy, "retest_detected")
    assert len(retest) == 1
    assert retest[0].metadata["bars_to_retest"] == 1
    assert retest[0].metadata["retest_low"] == pytest.approx(PIVOT_PRICE)
    assert retest[0].metadata["pivot_price"] == pytest.approx(PIVOT_PRICE)
    assert strategy.state is PB3State.WAITING_RECLAIM


def test_retest_tolerance_admits_a_low_that_stops_just_short_of_the_level():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    # ATR after the breakout bar is ~2.946, so the tolerance band is ~0.44 wide.
    rows = list(ROWS[:12]) + [(111.5, 111.7, 110.35, 110.5)]
    _feed(strategy, rows)
    retest = _stages(strategy, "retest_detected")
    assert len(retest) == 1
    assert retest[0].metadata["retest_overshoot_atr"] < 0  # never actually reached the level


def test_retest_expires_when_price_never_returns():
    strategy = BtcPB3PivotAcceptanceLong(_fast(retest_maximum_bars=2))
    rows = list(ROWS[:12]) + [(111.6, 113.0, 111.4, 112.8), (112.8, 114.0, 112.6, 113.8)]
    _feed(strategy, rows)
    expired = _stages(strategy, "retest_expired")
    assert len(expired) == 1
    assert expired[0].reason == "pivot level never retested"
    assert strategy.state is PB3State.SEARCHING_PIVOT_BREAKOUT
    assert strategy.structure is None


def test_structure_invalidated_by_a_close_below_the_breakout_low():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    rows = list(ROWS[:12]) + [(111.5, 111.7, 105.0, 105.5)]
    _feed(strategy, rows)
    invalidated = _stages(strategy, "structure_invalidated")
    assert len(invalidated) == 1
    assert invalidated[0].metadata["close"] < invalidated[0].metadata["breakout_low"]
    assert strategy.state is PB3State.SEARCHING_PIVOT_BREAKOUT


# --- Reclaim -----------------------------------------------------------------------------------


def test_reclaim_confirms_and_waits_for_acceptance():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    _feed(strategy, ROWS, stop_after=RECLAIM_INDEX)
    confirmed = _stages(strategy, "reclaim_confirmed")
    assert len(confirmed) == 1
    assert confirmed[0].metadata["reclaim_close"] == pytest.approx(111.4)
    assert confirmed[0].metadata["body_percent"] >= 0.50
    assert confirmed[0].metadata["close_location"] >= 0.65
    assert confirmed[0].metadata["range_atr"] <= 2.00
    assert strategy.state is PB3State.WAITING_ACCEPTANCE


def test_a_bearish_bar_at_the_level_is_not_a_reclaim():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    _feed(strategy, ROWS, stop_after=RETEST_INDEX)
    rejected = _stages(strategy, "reclaim_rejected")
    assert rejected and rejected[-1].reason == "candle not bullish"


def test_an_overextended_reclaim_range_is_rejected():
    strategy = BtcPB3PivotAcceptanceLong(_fast(reclaim_maximum_range_atr=0.25))
    _feed(strategy, ROWS, stop_after=RECLAIM_INDEX)
    assert _stages(strategy, "reclaim_rejected")[-1].reason == "range too wide"
    assert not _stages(strategy, "reclaim_confirmed")


def test_same_bar_retest_and_reclaim_still_requires_a_separate_acceptance_bar():
    """One bar may both retest and reclaim: a bar's close is by construction its
    last price, so a low inside the retest tolerance necessarily precedes the
    reclaiming close and no intrabar path has to be invented. The conservative
    part is that acceptance is never collapsed into the same bar.
    """
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    rows = list(ROWS[:12]) + [(110.3, 111.5, 110.0, 111.4)]
    signals = _feed(strategy, rows)
    assert len(_stages(strategy, "retest_detected")) == 1
    assert len(_stages(strategy, "reclaim_confirmed")) == 1
    assert (_stages(strategy, "retest_detected")[0].timestamp
            == _stages(strategy, "reclaim_confirmed")[0].timestamp)
    assert signals[-1] is None
    assert strategy.state is PB3State.WAITING_ACCEPTANCE
    assert not _stages(strategy, "acceptance_evaluated")


# --- Strict acceptance ---------------------------------------------------------------------------


def test_acceptance_uses_exactly_the_next_completed_bar():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    _feed(strategy, ROWS)
    evaluated = _stages(strategy, "acceptance_evaluated")
    assert len(evaluated) == 1
    reclaim_time = _stages(strategy, "reclaim_confirmed")[0].timestamp
    assert evaluated[0].timestamp == reclaim_time + pd.Timedelta(minutes=15)


def test_acceptance_failure_resets_the_structure_without_a_second_chance():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    # Bar 14 holds the pivot level but not the reclaim close.
    rows = list(ROWS[:14]) + [(111.4, 112.2, 110.5, 110.8)]
    signals = _feed(strategy, rows)
    failed = _stages(strategy, "acceptance_failed")
    assert len(failed) == 1
    assert failed[0].reason == "close did not hold the reclaim close"
    assert failed[0].metadata["beyond_level"] is True
    assert all(signal is None for signal in signals)
    assert strategy.state is PB3State.SEARCHING_PIVOT_BREAKOUT
    assert strategy.structure is None

    # A later bar that would have satisfied acceptance cannot rescue the dead
    # structure: acceptance is a single-bar test and it has already been spent.
    strategy.on_candle(Candle(START + pd.Timedelta(minutes=15 * 15),
                              110.8, 113.0, 110.7, 112.8, 1.0))
    assert len(_stages(strategy, "acceptance_evaluated")) == 1
    assert not _stages(strategy, "pending_created")


def test_acceptance_rejects_a_close_back_through_the_pivot_level():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    rows = list(ROWS[:14]) + [(111.4, 112.2, 109.0, 109.5)]
    signals = _feed(strategy, rows)
    assert signals[-1] is None
    assert _stages(strategy, "acceptance_failed")[0].reason == \
        "close fell back through the pivot level"


def test_invalidation_also_guards_the_acceptance_bar():
    """Section 9 runs until entry, so a close below the breakout low on the
    acceptance bar is recorded as an invalidation, not an acceptance failure."""
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    rows = list(ROWS[:14]) + [(111.4, 112.2, 104.0, 104.5)]
    signals = _feed(strategy, rows)
    assert signals[-1] is None
    assert len(_stages(strategy, "structure_invalidated")) == 1
    assert not _stages(strategy, "acceptance_failed")
    assert strategy.state is PB3State.SEARCHING_PIVOT_BREAKOUT


# --- Entry, stop and target -------------------------------------------------------------------


def test_entry_prices_are_hand_verified():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    signals = _feed(strategy, ROWS)
    signal = signals[ACCEPTANCE_INDEX]
    assert isinstance(signal, Signal)
    assert signal.direction is Direction.LONG
    atr = strategy.atr._average.value
    # trigger = acceptance high + 0.05 ATR; stop = lowest low across the
    # retest/reclaim/acceptance bars (110.0) - 0.20 ATR.
    assert signal.pending_entry_price == pytest.approx(112.2 + 0.05 * atr)
    assert signal.pending_stop_price == pytest.approx(110.0 - 0.20 * atr)
    assert signal.pending_expiry_bars == 2
    assert strategy.state is PB3State.PENDING_ENTRY


def test_structural_stop_anchors_on_the_lowest_of_three_bars():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    _feed(strategy, ROWS)
    risk = _stages(strategy, "risk_evaluated")[0]
    # Lows are 110.0 (retest), 110.2 (reclaim) and 111.2 (acceptance).
    assert risk.metadata["stop_anchor"] == pytest.approx(110.0)
    assert risk.metadata["anchor_bars"] == 3
    assert 0.50 <= risk.metadata["stop_atr"] <= 2.50


def _structure_for_stop_test(anchor: float) -> _Structure:
    return _Structure(
        pivot_price=PIVOT_PRICE, pivot_timestamp=START,
        pivot_confirmation_timestamp=START, pivot_age_bars=3, pivot_distance_atr=0.5,
        breakout_time=START, breakout_high=112.0, breakout_low=106.8,
        breakout_range_atr=1.77, breakout_body_percent=0.88,
        breakout_close_location=0.92, breakout_distance_atr=0.54,
        reclaim_close=111.4, stop_anchor=anchor,
    )


def test_stop_below_the_minimum_atr_is_rejected():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    candle = Candle(START, 111.4, 112.2, 111.2, 112.0, 1.0)
    signal = strategy._construct_entry(candle, _structure_for_stop_test(112.1), 10.0)
    assert signal is None
    assert _stages(strategy, "risk_rejected")[0].reason == "stop distance outside the safety range"
    assert _stages(strategy, "risk_rejected")[0].metadata["stop_atr"] < 0.50
    assert strategy.state is PB3State.SEARCHING_PIVOT_BREAKOUT


def test_stop_above_the_maximum_atr_is_rejected():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    candle = Candle(START, 111.4, 112.2, 111.2, 112.0, 1.0)
    signal = strategy._construct_entry(candle, _structure_for_stop_test(100.0), 1.0)
    assert signal is None
    assert _stages(strategy, "risk_rejected")[0].metadata["stop_atr"] > 2.50


def test_pending_stop_never_carries_a_target():
    """The fixed 3R target belongs to the audited engine, not to PB3."""
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    signal = _feed(strategy, ROWS)[ACCEPTANCE_INDEX]
    assert signal.take_profit is None
    assert signal.stop_loss == signal.pending_stop_price
    assert strategy.params.reward_multiple == 3.0


def test_the_engine_owns_the_three_r_exit_horizon():
    config = BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD", strategy_id=PB3_ID,
        timeframe="15m", higher_timeframes=("1h",),
        start_date=pd.Timestamp("2021-01-01", tz="UTC"),
        end_date=pd.Timestamp("2021-03-31", tz="UTC"), dataset_role=DatasetRole.DEVELOPMENT,
    )
    assert config.risk_reward_ratio == PB3Parameters().reward_multiple == 3.0


# --- Order lifecycle ----------------------------------------------------------------------------


def _pending(setup_id: str) -> PendingOrder:
    return PendingOrder(
        direction=Direction.LONG, signal_time=START, created_time=START,
        trigger_price=112.3, stop_price=109.6, expiry_time=START + pd.Timedelta(minutes=30),
        created_bar_index=14, expiry_bar_index=16, quantity=0.1, planned_risk=25.0,
        estimated_stop_loss=25.0, leverage_capped=False, setup_id=setup_id,
    )


def test_pending_expiry_emits_a_diagnostic_and_resets():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    _feed(strategy, ROWS)
    strategy.on_execution_state(ExecutionState(10_000.0, _pending("PB3_PIVOT_ACCEPTANCE_LONG"), None))
    strategy.on_execution_state(ExecutionState(10_000.0, None, None))
    assert len(_stages(strategy, "pending_expired")) == 1
    assert strategy.state is PB3State.SEARCHING_PIVOT_BREAKOUT


def test_an_open_position_does_not_emit_a_phantom_expiry():
    """A filled pending must not look like an expiry on later bars (PB2 bug)."""
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    position = Position(
        trade_id=1, direction=Direction.LONG, signal_time=START, entry_time=START,
        entry_price=112.3, stop_loss=109.6, take_profit=120.4, quantity=0.1,
        initial_risk=25.0, entry_commission=0.0, entry_bar_index=15,
    )
    strategy.on_execution_state(ExecutionState(10_000.0, _pending("PB3_PIVOT_ACCEPTANCE_LONG"), None))
    strategy.on_execution_state(ExecutionState(10_000.0, None, position, opened_position=position))
    strategy.on_execution_state(ExecutionState(10_000.0, None, position))
    assert not _stages(strategy, "pending_expired")
    assert strategy.state is PB3State.IN_TRADE


def test_only_one_pending_order_comes_from_one_structure():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    signals = _feed(strategy, ROWS)
    assert sum(1 for signal in signals if signal is not None) == 1
    assert strategy.structure is None
    strategy.on_execution_state(ExecutionState(10_000.0, _pending("PB3_PIVOT_ACCEPTANCE_LONG"), None))
    extra = strategy.on_candle(Candle(START + pd.Timedelta(minutes=15 * 15),
                                      112.0, 114.0, 111.8, 113.8, 1.0))
    assert extra is None


def test_a_data_gap_clears_pivots_and_structure():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    _feed(strategy, ROWS, stop_after=BREAKOUT_INDEX)
    assert strategy.state is PB3State.WAITING_RETEST
    strategy.on_data_gap()
    assert strategy.active_pivot is None
    assert strategy.structure is None
    assert strategy.state is PB3State.SEARCHING_PIVOT_BREAKOUT


# --- Diagnostics and X-Ray -------------------------------------------------------------------


def test_diagnostic_events_cover_the_full_pipeline():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    _feed(strategy, ROWS)
    stages = {event.stage for event in strategy.diagnostic_events}
    assert {"context_evaluated", "context_rejected", "pivot_confirmed", "breakout_evaluated",
            "breakout_confirmed", "waiting_retest", "retest_detected", "reclaim_evaluated",
            "reclaim_rejected", "reclaim_confirmed", "acceptance_evaluated",
            "acceptance_confirmed", "risk_evaluated", "pending_created"}.issubset(stages)
    # The happy path cannot emit a rejection at every stage, so the remaining
    # funnel vocabulary is asserted by the dedicated tests above.
    assert "breakout_rejected" not in stages


def test_the_strategy_never_emits_the_generic_trade_stages():
    """DiagnosticStrategyObserver owns trade_entered/trade_exited; re-emitting
    them here would double-count entries and break reconciliation (PB2 bug)."""
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    _feed(strategy, ROWS)
    position = Position(
        trade_id=1, direction=Direction.LONG, signal_time=START, entry_time=START,
        entry_price=112.3, stop_loss=109.6, take_profit=120.4, quantity=0.1,
        initial_risk=25.0, entry_commission=0.0, entry_bar_index=15,
    )
    strategy.on_execution_state(ExecutionState(10_000.0, None, position, opened_position=position))
    stages = {event.stage for event in strategy.diagnostic_events}
    assert "trade_entered" not in stages and "trade_exited" not in stages


def test_xray_exposes_rule_level_values():
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    _feed(strategy, ROWS)
    assert {"h1_context_long", "h1_separation_atr", "h1_fast_slope_atr", "h1_slow_slope_atr",
            "pivot_price", "pivot_age_bars", "pivot_distance_atr", "breakout_range_atr",
            "breakout_body_percent", "breakout_close_location", "breakout_distance_atr",
            "bars_to_retest", "retest_overshoot_atr", "reclaim_body_percent",
            "reclaim_close_location", "reclaim_range_atr", "reclaim_distance_atr",
            "acceptance_distance_atr", "acceptance_range_atr", "reclaim_to_acceptance_atr",
            "stop_atr"}.issubset(_rules(strategy))
    assert all(row.result in ("PASS", "FAIL") for row in strategy.xray_evaluations)
    assert all(row.strategy_id == PB3_ID for row in strategy.xray_evaluations)


def test_xray_does_not_duplicate_the_trading_decision():
    """X-Ray records observed values against thresholds; it never re-decides."""
    strategy = BtcPB3PivotAcceptanceLong(_fast())
    _feed(strategy, ROWS)
    rules = [row for row in strategy.xray_evaluations if row.rule == "stop_atr"]
    assert len(rules) == 1
    assert rules[0].result == "PASS"
    assert set(_rules(strategy)).isdisjoint({"entry", "signal", "trade"})


# --- Registry and fingerprints ------------------------------------------------------------------


def test_pb3_registers_as_a_long_only_research_strategy():
    descriptor = discover_builtin_strategies().get(PB3_ID)
    assert descriptor.metadata.status is StrategyStatus.RESEARCH
    assert descriptor.metadata.strategy_id == PB3_ID
    assert descriptor.metadata.supported_instruments == ("BTCUSD",)
    assert set(descriptor.required_timeframes) == {"15m", "1h"}
    assert descriptor.create({}).direction is Direction.LONG


def test_no_short_pb3_component_exists_in_phase_a():
    registered = [descriptor.metadata.strategy_id
                  for descriptor in discover_builtin_strategies().all()
                  if descriptor.metadata.strategy_id.startswith("BTC_PB3")]
    assert registered == [PB3_ID]


def test_effective_parameter_fingerprint_covers_every_default():
    descriptor = discover_builtin_strategies().get(PB3_ID)
    payload = effective_parameter_payload(descriptor, {})
    assert payload == asdict(PB3Parameters())
    assert parameter_fingerprint(payload) != parameter_fingerprint({})
    # Indicator lengths are not exposed as tunable parameters but must still be
    # part of the reproducibility payload.
    assert payload["h1_slow_ema"] == 200
    assert payload["pivot_left_bars"] == 2 and payload["pivot_right_bars"] == 2
    assert payload["maximum_pivot_age_bars"] == 24
    assert payload["reward_multiple"] == 3.0


def test_one_changed_parameter_changes_the_fingerprint():
    descriptor = discover_builtin_strategies().get(PB3_ID)
    baseline = parameter_fingerprint(effective_parameter_payload(descriptor, {}))
    changed = parameter_fingerprint(
        effective_parameter_payload(descriptor, {"pivot_right_bars": 3}))
    assert baseline != changed
    repeated = parameter_fingerprint(
        effective_parameter_payload(descriptor, {"pivot_right_bars": 3}))
    assert changed == repeated


def test_pb3_fingerprint_is_independent_of_pb1_and_pb2():
    registry = discover_builtin_strategies()
    pb3 = registry.get(PB3_ID).metadata.strategy_fingerprint
    others = {registry.get(strategy_id).metadata.strategy_fingerprint for strategy_id in (
        "BTC_PB1_SHALLOW_PULLBACK_V1", "BTC_PB2_RECLAIM_LONG_V1", "BTC_PB2_RECLAIM_SHORT_V1")}
    assert pb3 not in others


def test_registered_parameters_are_tunable_except_the_reward_multiple():
    descriptor = discover_builtin_strategies().get(PB3_ID)
    tunable = {p.name: p.optimization_allowed for p in descriptor.parameters}
    assert set(TUNABLE_PARAMETERS).issubset(tunable)
    assert all(tunable[name] for name in TUNABLE_PARAMETERS)
    assert tunable["reward_multiple"] is False


def test_parameter_validation_rejects_an_impossible_age_cap():
    """A cap at or below pivot_right_bars could never admit any pivot."""
    with pytest.raises(ValueError, match="maximum_pivot_age_bars"):
        replace(PB3Parameters(), maximum_pivot_age_bars=2)


def test_pb3_does_not_import_pb1_or_pb2_implementations():
    """Section 28: PB3 may reuse generic infrastructure, never PB1/PB2 strategy code."""
    import strategies.btc_pb3_pivot_acceptance_long as module

    text = Path(module.__file__).read_text()
    imports = [line for line in text.splitlines()
               if line.startswith(("import ", "from ")) and "btc_pb" in line]
    assert imports == []
