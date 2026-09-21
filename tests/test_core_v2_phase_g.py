"""BTC Core V2 Phase G — the fixed-3R feasibility gate.

Phase G's whole output is a verdict about whether a number beats 25%, so the
machinery that produces that number carries the weight: the forward walk must
never order two touches inside one bar, the spread must be charged on the right
side of each direction, and the significance test must be right, because it is
what turns "27.96% looks good" into "p = 0.10 on 397 samples, which is nothing".

The controls are tested too. A gate that says "no edge" everywhere is only worth
reading if it can be shown to say "edge" somewhere, and here that somewhere is
the frozen T3's own setup bars.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from engine.models import Candle
from research import core_v2_phase_g as phase_g
from research import core_v2_phase_g_outcomes as outcomes
from research.core_v2_phase_a import DEVELOPMENT_END, HOLDOUT_START
from strategies.btc_v3_t3_breakout_short import V3T3FrozenParameters
from strategies.registry import discover_builtin_strategies

ROOT = Path(__file__).resolve().parents[1]
BASE = pd.Timestamp("2024-03-01T00:00:00Z")


def _arrays(bars):
    highs = np.array([b[0] for b in bars], dtype=float)
    lows = np.array([b[1] for b in bars], dtype=float)
    return highs, lows


# --- the arithmetic the whole phase is read against --------------------------------


def test_a_fixed_3r_against_a_1r_stop_breaks_even_at_25_percent():
    assert outcomes.REWARD_MULTIPLE == 3.0
    assert outcomes.BREAK_EVEN_3R_RATE == pytest.approx(25.0)
    #--- Stated as expectancy rather than as a rate, the same fact.
    assert 0.25 * 3.0 - 0.75 * 1.0 == pytest.approx(0.0)


def test_the_exact_binomial_tail_matches_a_direct_summation():
    from math import comb
    for trials, successes, probability in ((10, 4, 0.25), (40, 15, 0.25), (97, 30, 0.25)):
        direct = sum(comb(trials, k) * probability ** k * (1 - probability) ** (trials - k)
                     for k in range(successes, trials + 1))
        assert outcomes.binomial_tail_p(successes, trials, probability) == pytest.approx(direct)


def test_the_binomial_tail_handles_its_edges():
    assert outcomes.binomial_tail_p(0, 100, 0.25) == pytest.approx(1.0)
    assert outcomes.binomial_tail_p(1, 1, 0.25) == pytest.approx(0.25)
    assert outcomes.binomial_tail_p(101, 100, 0.25) == pytest.approx(0.25 ** 100)
    assert outcomes.binomial_tail_p(5, 0, 0.25) == 1.0


def test_the_reported_phase_g_p_values_are_reproducible():
    """The four cells that looked like leads before the significance gate."""
    for successes, trials, expected in ((111, 397, 0.0972), (442, 1703, 0.1888),
                                        (27, 98, 0.3151), (1640, 6526, 0.4087)):
        assert outcomes.binomial_tail_p(successes, trials, 0.25) == pytest.approx(
            expected, abs=1e-4)


# --- the forward walk ---------------------------------------------------------------


def test_the_target_is_recorded_when_it_comes_first():
    #--- 99.5, not 99: a low that touches the stop level *is* a stop hit.
    highs, lows = _arrays([(101, 99.5), (104, 100), (105, 104)])
    walk = outcomes._walk(highs, lows, 0, entry=100.0, stop=99.0, long=True)
    assert walk["resolution"] == "TARGET_3R"
    assert walk["first_touch"]["3R"] == "TARGET_FIRST"
    assert walk["bars"] == 1


def test_the_stop_is_recorded_when_it_comes_first():
    highs, lows = _arrays([(101, 99.5), (101, 98.5), (105, 104)])
    walk = outcomes._walk(highs, lows, 0, entry=100.0, stop=99.0, long=True)
    assert walk["resolution"] == "STOP_1R"
    assert walk["first_touch"]["3R"] == "STOP_FIRST"
    assert walk["bars"] == 1


def test_one_bar_spanning_both_levels_is_never_resolved_by_guessing():
    """Closed-bar OHLC cannot order two touches inside a bar, so it must not try."""
    highs, lows = _arrays([(104, 98)])
    walk = outcomes._walk(highs, lows, 0, entry=100.0, stop=99.0, long=True)
    assert walk["resolution"] == "AMBIGUOUS_SAME_BAR"
    assert walk["first_touch"]["3R"] == "AMBIGUOUS_SAME_BAR"


def test_a_path_that_reaches_neither_level_is_unresolved():
    highs, lows = _arrays([(100.5, 99.5)] * 10)
    walk = outcomes._walk(highs, lows, 0, entry=100.0, stop=99.0, long=True)
    assert walk["resolution"] == "UNRESOLVED"
    assert walk["first_touch"]["3R"] == "NOT_REACHED"


def test_the_short_side_is_the_mirror_of_the_long_side():
    highs, lows = _arrays([(100.5, 99), (100, 96), (97, 96)])
    walk = outcomes._walk(highs, lows, 0, entry=100.0, stop=101.0, long=False)
    assert walk["resolution"] == "TARGET_3R"
    assert walk["bars"] == 1


def test_excursions_are_measured_over_the_realised_path_only():
    """A move after the stop was hit is not something a trade experienced."""
    highs, lows = _arrays([(100.5, 98.5), (140, 139)])
    walk = outcomes._walk(highs, lows, 0, entry=100.0, stop=99.0, long=True)
    assert walk["resolution"] == "STOP_1R"
    assert walk["mfe_r"] == pytest.approx(0.5)


def test_intermediate_thresholds_are_ordered_consistently():
    #--- Bar 0 reaches +1.5R, bar 1 takes the stop: 1R landed, 2R and 3R did not.
    highs, lows = _arrays([(101.5, 99.5), (101, 98.5)])
    walk = outcomes._walk(highs, lows, 0, entry=100.0, stop=99.0, long=True)
    assert walk["first_touch"]["1R"] == "TARGET_FIRST"
    assert walk["first_touch"]["2R"] == "STOP_FIRST"
    assert walk["first_touch"]["3R"] == "STOP_FIRST"


def test_the_horizon_is_long_enough_for_the_frozen_core_s_own_winners():
    """The Core's slowest 3R winner took 425 bars; the horizon must clear it."""
    assert outcomes.HORIZON_BARS >= 425


# --- constants come from the frozen source ---------------------------------------------


def test_every_phase_g_constant_is_a_frozen_t3_parameter():
    frozen = V3T3FrozenParameters()
    assert outcomes.STOP_LOOKBACK == frozen.trend_stop_lookback
    assert outcomes.STOP_BUFFER_ATR == frozen.stop_buffer_atr
    assert outcomes.MIN_STOP_ATR == frozen.minimum_stop_atr
    assert outcomes.MAX_STOP_ATR == frozen.maximum_stop_atr
    assert outcomes.REWARD_MULTIPLE == frozen.reward_multiple
    assert outcomes.STRONG_BODY == frozen.trend_minimum_body_percent
    assert outcomes.MIN_RANGE_ATR == frozen.trend_minimum_range_atr
    assert outcomes.MAX_RANGE_ATR == frozen.trend_maximum_range_atr


def test_the_two_target_buckets_are_the_ones_the_brief_named():
    assert outcomes.TARGET_BUCKET_REASONS == ("WIDE_BUT_M15_OPPOSED", "WIDE_BUT_WEAK_ADX")


def test_every_briefed_event_type_is_measured_in_both_directions():
    assert len(outcomes.EVENTS) == 10
    assert outcomes.DIRECTIONS == ("TOWARD_H1", "AGAINST_H1")


# --- spread costing ----------------------------------------------------------------------


def _ramp(count: int, start: float = 100.0, step: float = 0.0) -> list[Candle]:
    return [Candle(BASE + pd.Timedelta(minutes=15 * i), start + i * step,
                   start + i * step + 1, start + i * step - 1, start + i * step, 1.0)
            for i in range(count)]


def test_a_long_pays_the_spread_on_entry_and_a_short_pays_it_on_exit():
    """Both directions pay exactly one crossing; only the costed side differs."""
    source = (ROOT / "research" / "core_v2_phase_g_outcomes.py").read_text()
    assert "entry = float(opens[entry_index]) + (spread if long else 0.0)" in source
    assert "stop -= spread" in source


def test_charging_a_spread_never_improves_a_pool(dataset_available, contexts_and_candles):
    candles, bars = contexts_and_candles
    gross = outcomes.measure(candles, bars)
    net = outcomes.measure(candles, bars, phase_g.development_spreads())
    gross_rate = sum(1 for row in gross if row.resolution == "TARGET_3R") / len(gross)
    net_rate = sum(1 for row in net if row.resolution == "TARGET_3R") / len(net)
    assert net_rate < gross_rate


def test_the_spread_series_lines_up_with_the_development_candles(dataset_available,
                                                                contexts_and_candles):
    candles, _ = contexts_and_candles
    assert len(phase_g.development_spreads()) == len(candles)
    assert all(value > 0 for value in phase_g.development_spreads())


# --- what gets measured at all ---------------------------------------------------------


@pytest.fixture(scope="module")
def dataset_available() -> Path:
    try:
        from research.core_v2_phase_a import dataset_path
        return dataset_path()
    except (FileNotFoundError, ValueError) as exc:
        pytest.skip(f"validated Exness dataset unavailable: {exc}")


@pytest.fixture(scope="module")
def contexts_and_candles(dataset_available):
    from research.core_v2_phase_f import development_candles
    candles = development_candles()
    return candles, outcomes.contexts(candles)


def test_only_bars_in_the_two_target_buckets_are_measured(dataset_available,
                                                          contexts_and_candles):
    candles, bars = contexts_and_candles
    rows = outcomes.measure(candles, bars)
    assert {row.reason for row in rows} == set(outcomes.TARGET_BUCKET_REASONS)


def test_every_measured_trade_sits_inside_the_frozen_stop_band(dataset_available,
                                                               contexts_and_candles):
    candles, bars = contexts_and_candles
    rows = outcomes.measure(candles, bars)
    assert all(outcomes.MIN_STOP_ATR <= row.risk_atr <= outcomes.MAX_STOP_ATR
               for row in rows)
    assert outcomes.measure.rejected["stop_distance_outside_the_frozen_band"] > 0


def test_the_bucket_totals_match_the_phase_f_census(dataset_available, contexts_and_candles):
    _, bars = contexts_and_candles
    counts = {name: sum(1 for bar in bars if bar.reason == name)
              for name in outcomes.TARGET_BUCKET_REASONS}
    assert counts == {"WIDE_BUT_M15_OPPOSED": 12292, "WIDE_BUT_WEAK_ADX": 11689}


# --- the controls --------------------------------------------------------------------------


def test_an_unfiltered_pool_lands_on_the_random_walk_rate(dataset_available,
                                                          contexts_and_candles):
    """The null. If this were not ~25%, nothing else in the phase could be read."""
    candles, bars = contexts_and_candles
    control = phase_g.controls(candles, bars)
    for key in ("every_bar_no_filter_toward_h1", "every_bar_no_filter_against_h1"):
        assert control[key]["samples"] > 30_000
        assert 23.5 <= control[key]["percent_3r_first"] <= 25.5


def test_the_measurement_detects_the_edge_of_the_one_validated_strategy(
        dataset_available, contexts_and_candles):
    """T3 is frozen because it passed validation; the instrument must see it."""
    candles, bars = contexts_and_candles
    control = phase_g.controls(candles, bars)
    t3 = control["frozen_t3_setup_bars_short"]
    assert t3["percent_3r_first"] > outcomes.BREAK_EVEN_3R_RATE
    assert t3["binomial_p_value"] < 0.05


# --- the gate -------------------------------------------------------------------------------


def _cell(events=1000, target_first=280):
    return {"events": events, "events_per_month": events / 19.6,
            "expectancy_r_pessimistic": 0.12,
            "reaching_3r": {"target_first": target_first,
                            "percent_target_first": 100 * target_first / events,
                            "percent_target_first_optimistic": 100 * target_first / events},
            "expectancy_r_optimistic": 0.2}


def _stability(label_rates):
    return {label: {"CELL": {"events": 200,
                             "reaching_3r": {"percent_target_first": rate}}}
            for label, rate in label_rates.items()}


def test_a_rate_above_break_even_that_is_not_significant_does_not_qualify():
    """The Phase G finding in miniature: 27.96% on 397 samples is not an edge."""
    verdict = phase_g.leads(
        {"CELL": _cell(events=397, target_first=111)},
        _stability({"a": 30.0, "b": 28.0}),
        {"CELL": {"free_opportunities_per_month": 20.0}})
    assert verdict["CELL"]["qualifies"] is False
    assert any("not distinguishable" in reason for reason in verdict["CELL"]["failures"])
    assert verdict["CELL"]["binomial_p_value"] == pytest.approx(0.0972, abs=1e-4)


def test_a_rate_that_is_significant_and_stable_and_large_enough_does_qualify():
    verdict = phase_g.leads(
        {"CELL": _cell(events=4000, target_first=1160)},
        _stability({"a": 29.0, "b": 28.0}),
        {"CELL": {"free_opportunities_per_month": 20.0}})
    assert verdict["CELL"]["qualifies"] is True
    assert verdict["CELL"]["failures"] == []


def test_a_significant_rate_seen_in_only_one_subperiod_does_not_qualify():
    verdict = phase_g.leads(
        {"CELL": _cell(events=4000, target_first=1160)},
        _stability({"a": 29.0, "b": 21.0}),
        {"CELL": {"free_opportunities_per_month": 20.0}})
    assert verdict["CELL"]["qualifies"] is False
    assert any("subperiod" in reason for reason in verdict["CELL"]["failures"])


def test_a_significant_rate_without_capacity_does_not_qualify():
    verdict = phase_g.leads(
        {"CELL": _cell(events=4000, target_first=1160)},
        _stability({"a": 29.0, "b": 28.0}),
        {"CELL": {"free_opportunities_per_month": 1.0}})
    assert verdict["CELL"]["qualifies"] is False
    assert any("capacity" in reason for reason in verdict["CELL"]["failures"])


# --- discipline -----------------------------------------------------------------------------


def test_phase_g_builds_no_strategy_and_registers_nothing():
    """The gate was not met, so no family exists; nothing may have been added."""
    assert not (ROOT / "strategies" / "btc_core_v2_phase_g_families.py").exists()
    production = {d.metadata.strategy_id for d in discover_builtin_strategies().all()}
    assert not any(strategy_id.startswith("RESEARCH_G") for strategy_id in production)


def test_no_phase_g_run_can_reach_the_holdout():
    assert DEVELOPMENT_END < HOLDOUT_START
    assert phase_g.SUBPERIODS[-1][2] < HOLDOUT_START.strftime("%Y-%m-%d %H:%M")


def test_scipy_is_not_introduced_as_a_dependency():
    """The docstrings may explain why it is absent; the imports may not bring it back."""
    for name in ("core_v2_phase_g.py", "core_v2_phase_g_outcomes.py"):
        source = (ROOT / "research" / name).read_text()
        assert "import scipy" not in source
        assert "from scipy" not in source


def test_the_frozen_hashes_are_untouched():
    expected = {"BTC_V3_A4_PULLBACK_LONG_FROZEN": "55fedf85",
                "BTC_V3_T3_BREAKOUT_SHORT_FROZEN": "4c4ab845",
                "BTC_V3_CORE_V1_FROZEN": "631374d5"}
    registry = discover_builtin_strategies()
    for strategy_id, prefix in expected.items():
        assert registry.get(strategy_id).metadata.strategy_fingerprint.startswith(prefix)
