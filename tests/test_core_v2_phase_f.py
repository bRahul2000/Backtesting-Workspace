"""BTC Core V2 Phase F — the TRANSITION census and the three candidate families.

Phase F rests on one claim that everything else inherits: a family fires only on
bars the *frozen* gates call TRANSITION, so it cannot be competing with A4 or T3
for the same setup. That claim is pinned three ways here — against the Phase D
census expression, against the real development split, and against the frozen
children's own unconstrained setup population.

The second thing pinned is the contention ledger. Phase E's headline dissolved
when it turned out a "free" trade had blocked a later T3 trade by still holding
the slot, so ``entered_flat_then_blocked_frozen`` is tested as its own class
rather than folded into either neighbour.
"""
from dataclasses import dataclass, fields
from pathlib import Path

import pandas as pd
import pytest

from engine.models import Candle, Direction, ExecutionState, Signal
from research import core_v2_phase_f as phase_f
from research import core_v2_phase_f_map as fmap
from research.core_v2_opportunity_map import classify as phase_d_classify
from research.core_v2_phase_a import DEVELOPMENT_END, HOLDOUT_START
from strategies import btc_core_v2_phase_f_families as families
import strategies.btc_v3_t3_breakout_short as t3_module
from strategies.btc_v3_t3_breakout_short import V3T3FrozenParameters
from strategies.confirmed_h1_regime import H1RegimeValue
from strategies.registry import discover_builtin_strategies

ROOT = Path(__file__).resolve().parents[1]
BASE = pd.Timestamp("2024-03-01T00:00:00Z")


def _series(rows) -> list[Candle]:
    return [Candle(BASE + pd.Timedelta(minutes=15 * index), *row, 1.0)
            for index, row in enumerate(rows)]


def _h1(fast, slow, slope_from, atr, close=None) -> H1RegimeValue:
    return H1RegimeValue(hour=BASE, close=close if close is not None else slow,
                         fast_ema=fast, slow_ema=slow, slow_ema_lookback=slope_from, atr=atr)


@pytest.fixture(scope="module")
def dataset_available() -> Path:
    try:
        return phase_f.dataset_path()
    except (FileNotFoundError, ValueError) as exc:
        pytest.skip(f"validated Exness dataset unavailable: {exc}")


@pytest.fixture(scope="module")
def development_bars(dataset_available) -> list[fmap.FBar]:
    return fmap.census(phase_f.development_candles())


# --- the TRANSITION definition ------------------------------------------------------


def test_transition_is_not_a_concept_in_any_frozen_source():
    """The premise of the whole phase: TRANSITION is a research label, not frozen."""
    for name in ("btc_v3_a4_pullback_long.py", "btc_v3_t3_breakout_short.py",
                 "btc_v3_core_v1.py", "confirmed_h1_regime.py",
                 "btc_v3_l2_trend_pullback_long.py"):
        source = (ROOT / "strategies" / name).read_text()
        assert "TRANSITION" not in source, f"{name} names TRANSITION"


def test_the_strategy_side_bucket_matches_the_phase_d_census_expression():
    """``frozen_bucket`` is restated in the strategy module; it must not drift."""
    cases = [
        (_h1(110.0, 100.0, 99.0, 5.0), 11.0, 10.0, 25.0, 1.0, "BULLISH_TREND"),
        (_h1(90.0, 100.0, 101.0, 5.0), 10.0, 11.0, 25.0, 1.0, "BEARISH_TREND"),
        (_h1(102.0, 100.0, 99.0, 5.0), 11.0, 10.0, 25.0, 1.0, "NEUTRAL_RANGE"),
        (_h1(104.5, 100.0, 99.0, 5.0), 11.0, 10.0, 25.0, 1.0, "TRANSITION"),
        (_h1(110.0, 100.0, 99.0, 5.0), 11.0, 10.0, 10.0, 1.0, "TRANSITION"),
        (_h1(None, None, None, None), 11.0, 10.0, 25.0, 1.0, "WARMUP"),
    ]
    for h1, ema20, ema50, adx, atr, expected in cases:
        assert families.frozen_bucket(h1, ema20, ema50, adx, atr) == expected


def test_the_census_reproduces_the_phase_d_map_bar_for_bar(development_bars):
    phase_d = phase_d_classify(phase_f.development_candles())
    assert len(phase_d) == len(development_bars)
    mismatches = sum(1 for a, b in zip(development_bars, phase_d)
                     if a.bucket != b.h1_regime)
    assert mismatches == 0


def test_the_strategy_gate_agrees_with_the_census_on_the_real_split(development_bars):
    gate = families.TransitionGate(V3T3FrozenParameters())
    for candle, bar in zip(phase_f.development_candles(), development_bars):
        gate.update(candle)
        assert gate.bucket == bar.bucket, f"disagreed at {candle.timestamp}"


def test_the_transition_reasons_are_disjoint_and_exhaustive(development_bars):
    transition = [bar for bar in development_bars if bar.bucket == "TRANSITION"]
    assert transition, "no TRANSITION bars in the development split"
    assert all(bar.transition_reason in fmap.TRANSITION_REASONS for bar in transition)
    assert all(bar.transition_reason is None for bar in development_bars
               if bar.bucket != "TRANSITION")


def test_each_transition_reason_names_the_gate_that_actually_failed():
    #--- Separation short of 1.00 but above the range ceiling.
    assert fmap._transition_reason(0.9, 1.0, 30.0, _h1(104.5, 100.0, 99.0, 5.0),
                                   11.0, 10.0) == "EMERGING_SEPARATION"
    #--- Wide enough, but momentum has not confirmed.
    assert fmap._transition_reason(1.5, 1.0, 10.0, _h1(110.0, 100.0, 99.0, 5.0),
                                   11.0, 10.0) == "WIDE_BUT_WEAK_ADX"
    #--- EMAs point up, slope points down: the H1 disagrees with itself.
    assert fmap._transition_reason(1.5, -1.0, 30.0, _h1(110.0, 100.0, 101.0, 5.0),
                                   11.0, 10.0) == "WIDE_BUT_H1_UNALIGNED"
    #--- H1 agrees; the M15 stack faces the other way.
    assert fmap._transition_reason(1.5, 1.0, 30.0, _h1(110.0, 100.0, 99.0, 5.0),
                                   10.0, 11.0) == "WIDE_BUT_M15_OPPOSED"


def test_the_frozen_children_never_set_up_on_a_transition_bar(development_bars):
    """Structural, not incidental: both children require separation >= 1.00 and ADX >= 18."""
    assert sum(1 for bar in development_bars if bar.bucket == "TRANSITION" and bar.a4_setup) == 0
    assert sum(1 for bar in development_bars if bar.bucket == "TRANSITION" and bar.t3_setup) == 0
    assert sum(1 for bar in development_bars if bar.a4_setup) > 0
    assert sum(1 for bar in development_bars if bar.t3_setup) > 0


def test_separation_expansion_compares_confirmed_h1_bars_not_m15_bars():
    gate = families.TransitionGate(V3T3FrozenParameters())
    #--- Four M15 bars complete one H1 bar; nothing may change in between.
    readings = []
    for candle in _series([(100, 101, 99, 100)] * 12):
        gate.update(candle)
        readings.append((gate.hour, gate.separation))
    hours = {hour for hour, _ in readings if hour is not None}
    assert len(hours) <= 3, "the gate advanced its hour more often than H1 bars complete"


# --- F1 is the frozen T3 engine, moved ------------------------------------------------


def test_f1_parameters_change_only_the_regime_gate_and_the_enabled_sides():
    #--- The frozen dataclass is init=False, so its values live on the class and
    #--- ``vars()`` on an instance is empty; the field list is the real schema.
    frozen, moved = V3T3FrozenParameters(), families.f1_parameters()
    changed = {field.name for field in fields(frozen)
               if getattr(frozen, field.name) != getattr(moved, field.name)}
    #--- ``shorts_enabled`` is already True in the frozen defaults, so enabling it
    #--- is not a change; only the long side and the two regime gates move.
    assert changed == {"longs_enabled", "trend_min_h1_separation_atr", "trend_min_adx"}
    assert moved.shorts_enabled is True and moved.longs_enabled is True
    assert moved.reward_multiple == 3.0
    assert moved.trend_minimum_body_percent == frozen.trend_minimum_body_percent
    assert moved.trend_structure_lookback == frozen.trend_structure_lookback


def test_f1_only_changes_its_structure_lookback_when_a_variant_asks():
    assert families.F1EmergingBreakout().params.trend_structure_lookback == 5
    assert families.F1EmergingBreakout(structure_lookback=3).params.trend_structure_lookback == 3


def test_the_frozen_t3_module_globals_are_restored_after_every_f1_call():
    setup_id, evaluator = t3_module.TREND_SETUP_ID, t3_module.evaluate_v3
    strategy = families.F1EmergingBreakout()
    strategy.reset()
    for candle in _series([(100, 101, 99, 100)] * 8):
        strategy.on_execution_state(ExecutionState(10_000.0, None, None, None, None))
        strategy.on_candle(candle)
    assert t3_module.TREND_SETUP_ID == setup_id
    assert t3_module.evaluate_v3 is evaluator


def test_withdrawing_the_signal_does_not_skip_a_single_indicator_update():
    """The gate must suppress the output, never the state."""
    rows = [(100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(40)]
    open_gate = families.F1EmergingBreakout(require_expansion=False)
    shut_gate = families.F1EmergingBreakout(require_expansion=False)
    for strategy in (open_gate, shut_gate):
        strategy.reset()
    for candle in _series(rows):
        for strategy, blocked in ((open_gate, False), (shut_gate, True)):
            strategy.on_execution_state(ExecutionState(10_000.0, None, None, None, None))
            with families._withdrawn(blocked):
                super(families.F1EmergingBreakout, strategy).on_candle(candle)
    assert open_gate.fast.value == shut_gate.fast.value
    assert open_gate.slow.value == shut_gate.slow.value
    assert open_gate.atr._average.value == shut_gate.atr._average.value


def test_f1_never_signals_outside_the_transition_bucket(dataset_available, development_bars):
    bucket = {bar.timestamp: bar.bucket for bar in development_bars}
    strategy = families.F1EmergingBreakout()
    strategy.reset()
    fired = 0
    for candle in phase_f.development_candles():
        strategy.on_execution_state(ExecutionState(10_000.0, None, None, None, None))
        if isinstance(strategy.on_candle(candle), Signal):
            fired += 1
            assert bucket[candle.timestamp] == "TRANSITION"
    assert fired > 0


# --- F2 and F3 ---------------------------------------------------------------------------


def test_every_family_carries_its_own_setup_id():
    ids = {families.F1_SETUP_ID, families.F2_SETUP_ID, families.F3_SETUP_ID}
    assert len(ids) == 3
    registry = discover_builtin_strategies()
    existing = {descriptor.metadata.strategy_id for descriptor in registry.all()}
    assert not (ids & existing)
    assert t3_module.TREND_SETUP_ID not in ids
    assert t3_module.RANGE_SETUP_ID not in ids


def test_f2_arms_only_when_the_confirmed_h1_lean_agrees_with_the_cross():
    strategy = families.F2EmaInitiation()
    strategy.reset()
    obs = _observation(crossed_up=True, lean="BEARISH_LEAN")
    assert strategy.evaluate(obs) is None
    assert strategy.pending_direction is None
    strategy.evaluate(_observation(crossed_up=True, lean="BULLISH_LEAN"))
    assert strategy.pending_direction is Direction.LONG


def test_f2_forgets_a_cross_that_is_never_confirmed():
    strategy = families.F2EmaInitiation(confirmation_bars=2)
    strategy.reset()
    strategy.evaluate(_observation(crossed_up=True, lean="BULLISH_LEAN"))
    for _ in range(3):
        strategy.evaluate(_observation(lean="BULLISH_LEAN"))
    assert strategy.pending_direction is None


def test_f3_never_treats_one_bar_as_both_a_failure_and_a_new_break():
    strategy = families.F3FailedBreakReversal()
    strategy.reset()
    strategy.evaluate(_observation(close=110.0, structure_high=105.0, structure_low=95.0))
    assert strategy.break_direction is Direction.LONG
    armed_level = strategy.break_level
    #--- A bar that closes back below the level resolves the break and must not
    #--- immediately arm another one from the same bar.
    strategy.evaluate(_observation(close=90.0, structure_high=105.0, structure_low=95.0))
    assert strategy.break_direction is None
    assert armed_level == 105.0


def test_f3_places_its_stop_beyond_the_extreme_the_failed_break_reached():
    strategy = families.F3FailedBreakReversal()
    strategy.reset()
    #--- ATR 10 keeps the stop inside T3's own 0.50-3.00 ATR bounds; a 1.0 ATR
    #--- here would be a 21-ATR stop and the frozen validator would refuse it.
    strategy.evaluate(_observation(close=110.0, high=120.0, structure_high=105.0, atr=10.0))
    assert strategy.break_extreme == 120.0
    signal = strategy.evaluate(_observation(
        open_=104.0, high=104.5, low=99.0, close=100.0, structure_high=105.0,
        rsi=60.0, atr=10.0))
    assert isinstance(signal, Signal)
    assert signal.direction is Direction.SHORT
    assert signal.pending_stop_price > 120.0, "stop must sit beyond the failed break's high"
    assert signal.pending_entry_price < 100.0


def test_f3_acceptance_variant_needs_a_second_bar_through_the_level():
    strategy = families.F3FailedBreakReversal(require_acceptance=True)
    strategy.reset()
    strategy.evaluate(_observation(close=110.0, high=120.0, structure_high=105.0, atr=10.0))
    assert strategy.evaluate(_observation(
        open_=104.0, high=104.5, low=99.0, close=100.0, structure_high=105.0,
        rsi=60.0, atr=10.0)) is None
    assert strategy.reclaimed is True


def test_every_variant_emits_only_valid_stop_entries(dataset_available):
    """A stop entry on the wrong side of the close is rejected by the engine."""
    candles = phase_f.development_candles()[:6000]
    for key, factory in families.VARIANT_FACTORIES.items():
        strategy = factory()
        strategy.reset()
        for candle in candles:
            strategy.on_execution_state(ExecutionState(10_000.0, None, None, None, None))
            action = strategy.on_candle(candle)
            if not isinstance(action, Signal):
                continue
            if action.direction is Direction.LONG:
                assert action.pending_entry_price > candle.close, key
                assert action.pending_stop_price < action.pending_entry_price, key
            else:
                assert action.pending_entry_price < candle.close, key
                assert action.pending_stop_price > action.pending_entry_price, key


def test_the_reward_multiple_is_three_in_every_arm():
    for factory in families.VARIANT_FACTORIES.values():
        assert factory().params.reward_multiple == 3.0


def test_there_are_at_most_three_variants_per_family():
    for family, variants in families.VARIANTS_BY_FAMILY.items():
        assert len(variants) <= 3, family
        assert sum(1 for variant in variants if variant.baseline) == 1, family


# --- the Core composition -------------------------------------------------------------


def test_the_frozen_pair_keeps_priority_over_the_candidate():
    composed = families.CoreWithTransitionFamily("F1a")
    source = (ROOT / "strategies" / families.VARIANT_FILE).read_text()
    assert "if isinstance(core_action, Signal):\n            return core_action" in source
    assert composed.family_setup_id == families.F1_SETUP_ID


def test_only_the_owning_child_may_cancel_a_pending_order():
    composed = families.CoreWithTransitionFamily("F3a")
    assert composed.family_setup_id == families.F3_SETUP_ID
    assert composed.family_setup_id != t3_module.TREND_SETUP_ID


# --- research isolation ----------------------------------------------------------------


def test_the_phase_f_arms_never_reach_the_production_registry():
    production = {d.metadata.strategy_id for d in discover_builtin_strategies().all()}
    assert not (set(families.PHASE_F_STRATEGY_IDS) & production)
    isolated = {d.metadata.strategy_id for d in families.phase_f_registry().all()}
    assert set(families.PHASE_F_STRATEGY_IDS) <= isolated


def test_every_phase_f_arm_is_research_status():
    for descriptor in families._descriptors():
        assert descriptor.metadata.status.name == "RESEARCH"


def test_no_phase_f_run_can_reach_the_holdout():
    assert phase_f.development_config("BTC_V3_CORE_V1_FROZEN").end_date == DEVELOPMENT_END
    assert DEVELOPMENT_END < HOLDOUT_START


def test_the_frozen_hashes_are_untouched():
    expected = {"BTC_V3_A4_PULLBACK_LONG_FROZEN": "55fedf85",
                "BTC_V3_T3_BREAKOUT_SHORT_FROZEN": "4c4ab845",
                "BTC_V3_CORE_V1_FROZEN": "631374d5"}
    registry = discover_builtin_strategies()
    for strategy_id, prefix in expected.items():
        assert registry.get(strategy_id).metadata.strategy_fingerprint.startswith(prefix)


# --- the contention ledger ---------------------------------------------------------------


@dataclass
class _FakeResult:
    trade_log: list
    legacy_segment_results: tuple = ()
    total_trades: int = 0
    max_drawdown_percent: float = 0.0
    profit_factor: float | None = None


def _trade(setup_id, entry, exit_, realized_r=1.0, direction="LONG"):
    return {"setup_id": setup_id, "direction": direction,
            "entry_time": pd.Timestamp(entry, tz="UTC"),
            "exit_time": pd.Timestamp(exit_, tz="UTC"),
            "realized_r": realized_r, "pnl": realized_r * 100,
            "entry_price": 100.0, "exit_price": 100.0 + realized_r,
            "mfe_r": abs(realized_r), "mae_r": -0.5}


T3 = "BTC_V3_T3_BREAKOUT_SHORT_FROZEN"
FAM = families.F1_SETUP_ID


def test_a_family_trade_that_blocks_a_later_frozen_trade_is_not_counted_as_free():
    """Phase E's mistake, pinned so it cannot be repeated."""
    frozen = _trade(T3, "2024-03-02T00:00", "2024-03-02T06:00", 3.0)
    baseline = _FakeResult([frozen])
    #--- The family enters on a bar the baseline was flat, then holds across the
    #--- frozen entry, so that frozen trade never happens.
    family = _trade(FAM, "2024-03-01T20:00", "2024-03-02T10:00", 0.2)
    combined = _FakeResult([family])
    ledger = phase_f.contention_ledger(baseline, combined, _FakeResult([family]), FAM)
    assert ledger["entered_flat_then_blocked_frozen"]["count"] == 1
    assert ledger["truly_additive"]["count"] == 0
    assert ledger["frozen_blocked_while_holding"]["count"] == 1
    assert ledger["net_free_contribution_r"] == pytest.approx(-3.0)
    assert ledger["percent_of_family_trades_that_cost_a_frozen_trade"] == 100.0


def test_a_family_trade_that_costs_nothing_is_counted_as_free():
    frozen = _trade(T3, "2024-03-05T00:00", "2024-03-05T06:00", 3.0)
    baseline = _FakeResult([frozen])
    family = _trade(FAM, "2024-03-01T20:00", "2024-03-01T22:00", 0.5)
    combined = _FakeResult([frozen, family])
    ledger = phase_f.contention_ledger(baseline, combined, _FakeResult([family]), FAM)
    assert ledger["truly_additive"]["count"] == 1
    assert ledger["entered_flat_then_blocked_frozen"]["count"] == 0
    assert ledger["net_free_contribution_r"] == pytest.approx(0.5)
    assert ledger["percent_of_family_trades_that_cost_a_frozen_trade"] == 0.0


def test_a_same_bar_takeover_is_a_displacement_not_a_block():
    frozen = _trade(T3, "2024-03-02T00:00", "2024-03-02T06:00", 3.0)
    family = _trade(FAM, "2024-03-02T00:00", "2024-03-02T04:00", 0.5)
    ledger = phase_f.contention_ledger(_FakeResult([frozen]), _FakeResult([family]),
                                       _FakeResult([family]), FAM)
    assert ledger["displaced_a_frozen_trade_on_entry"]["count"] == 1
    assert ledger["frozen_displaced_same_bar"]["count"] == 1
    assert ledger["frozen_blocked_while_holding"]["count"] == 0


def test_family_setups_the_core_suppressed_are_reported_separately():
    frozen = _trade(T3, "2024-03-02T00:00", "2024-03-02T06:00", 3.0)
    blocked = _trade(FAM, "2024-03-02T02:00", "2024-03-02T05:00", 1.0)
    ledger = phase_f.contention_ledger(_FakeResult([frozen]), _FakeResult([frozen]),
                                       _FakeResult([blocked]), FAM)
    assert ledger["family_setup_core_held_a_position"]["count"] == 1
    assert ledger["truly_additive"]["count"] == 0


# --- the verdict and the capacity funnel ---------------------------------------------------


def _contribution(**over):
    payload = {
        "new_trades_added": 100, "incremental_trades_per_month": 5.0,
        "incremental_profit_factor": 1.5, "incremental_average_r": 0.4,
        "incremental_total_r": 40.0,
        "incremental_monthly": {"2024-01": {"total_r": 20.0}, "2024-02": {"total_r": 20.0}},
        "excursions": {"mfe_r": 2.0, "mae_r": -0.9},
        "subperiod_net_r": [{"label": "a", "added": 50, "added_r": 20.0,
                             "displaced": 0, "displaced_r": 0.0},
                            {"label": "b", "added": 50, "added_r": 20.0,
                             "displaced": 0, "displaced_r": 0.0}],
    }
    payload.update(over)
    return payload


def _ledger(percent=0.0):
    return {"truly_additive": {"count": 100},
            "percent_of_family_trades_that_cost_a_frozen_trade": percent}


def _capacity(free_per_month=5.0):
    return {"genuinely_free_core_trades_per_month": free_per_month}


def test_a_healthy_family_carries_forward():
    result = phase_f.verdict(_FakeResult([], profit_factor=1.4), _contribution(),
                             _ledger(), _capacity())
    assert result["rejected"] is False
    assert result["carry_forward"] is True
    assert result["carry_shortfalls"] == []


def test_a_family_whose_new_trades_mostly_cost_a_frozen_trade_is_rejected():
    result = phase_f.verdict(_FakeResult([], profit_factor=1.4), _contribution(),
                             _ledger(60.0), _capacity())
    assert result["rejected"] is True
    assert any("displace or block" in reason for reason in result["rejection_reasons"])


def test_a_family_below_the_viability_floor_is_rejected_on_frequency():
    result = phase_f.verdict(_FakeResult([], profit_factor=1.4),
                             _contribution(incremental_trades_per_month=1.2),
                             _ledger(), _capacity(1.2))
    assert result["rejected"] is True
    assert any("viability floor" in reason for reason in result["rejection_reasons"])


def test_a_single_month_carrying_the_whole_total_is_rejected():
    result = phase_f.verdict(
        _FakeResult([], profit_factor=1.4),
        _contribution(incremental_monthly={"2024-01": {"total_r": 40.0},
                                           "2024-02": {"total_r": 0.0}}),
        _ledger(), _capacity())
    assert result["rejected"] is True
    assert any("best single month" in reason for reason in result["rejection_reasons"])


def test_a_negative_standalone_profit_factor_is_rejected():
    result = phase_f.verdict(_FakeResult([], profit_factor=0.8), _contribution(),
                             _ledger(), _capacity())
    assert result["rejected"] is True
    assert any("standalone PF" in reason for reason in result["rejection_reasons"])


def test_mfe_below_mae_is_rejected():
    result = phase_f.verdict(_FakeResult([], profit_factor=1.4),
                             _contribution(excursions={"mfe_r": 0.8, "mae_r": -0.9}),
                             _ledger(), _capacity())
    assert result["rejected"] is True
    assert any("MFE" in reason for reason in result["rejection_reasons"])


def test_a_family_that_is_merely_short_of_the_carry_standard_is_not_rejected():
    result = phase_f.verdict(_FakeResult([], profit_factor=1.4),
                             _contribution(incremental_trades_per_month=3.0),
                             _ledger(), _capacity(3.0))
    assert result["rejected"] is False
    assert result["carry_forward"] is False
    assert result["carry_shortfalls"]


def test_the_capacity_funnel_reports_the_whole_conversion_chain():
    payload = phase_f.capacity(
        "F1", "F1a", {"BREAKOUT_UP": {"events": 3000}, "BREAKDOWN": {"events": 1000}},
        setups=200, standalone=_FakeResult([], total_trades=100),
        contribution={"incremental_trades_per_month": 2.0},
        ledger={"truly_additive": {"count": 40}})
    assert payload["raw_events"] == 4000
    assert payload["conversion_event_to_setup_percent"] == pytest.approx(5.0)
    assert payload["conversion_setup_to_fill_percent"] == pytest.approx(50.0)
    assert payload["conversion_fill_to_free_core_trade_percent"] == pytest.approx(40.0)
    assert payload["genuinely_free_core_trades"] == 40


def test_the_event_pool_of_every_family_exists_in_the_census():
    detector_source = (ROOT / "research" / "core_v2_phase_f_map.py").read_text()
    for family, events in phase_f.FAMILY_EVENT_POOL.items():
        assert set(events) <= set(families.FAMILY_LABELS) | set(events)
        for name in events:
            assert f'"{name}"' in detector_source, f"{family} draws on an unknown event {name}"


def _observation(*, open_=100.0, high=101.0, low=99.0, close=100.5, atr=1.0, rsi=55.0,
                 adx=20.0, ema20=100.0, ema50=100.0, bucket="TRANSITION",
                 lean="BULLISH_LEAN", expanding=True, crossed_up=False, crossed_down=False,
                 structure_high=None, structure_low=None):
    candle = Candle(BASE, open_, high, low, close, 1.0)
    return families.TransitionObservation(
        candle=candle, previous=(), ema20=ema20, ema50=ema50, atr=atr, rsi=rsi, adx=adx,
        bucket=bucket, lean=lean, expanding=expanding, crossed_up=crossed_up,
        crossed_down=crossed_down, stop_low=low, stop_high=high,
        structure_high=structure_high, structure_low=structure_low)
