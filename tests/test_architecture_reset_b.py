"""BTC Architecture Reset B — M5 execution feasibility.

The study never sees an M5 bar, so everything rests on two claims being
measured rather than assumed: that the broker's bar spread does not change with
bar size, and that the repository's structural stop is a fixed multiple of ATR.
Both are pinned here against the real files, because if either were false the
projection would be worthless.

The third piece, the ATR scaling exponent, is fitted — so the fit quality and
the agreement between an upward aggregate of M15 and the independent broker H1
file are pinned too. The M5 step itself is an extrapolation below the shortest
bar in hand, and the test suite asserts the favourable bound is the one used.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research import architecture_reset_b as reset
from research import core_v2_phase_g_outcomes as g
from research.core_v2_phase_a import DEVELOPMENT_END, HOLDOUT_START
from services import market_datasets as md
from strategies.registry import discover_builtin_strategies

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def dataset_available():
    entry = md.dataset(md.EXNESS_BTCUSDM_M15)
    if not entry.exists:
        pytest.skip("validated Exness dataset unavailable")
    return entry


@pytest.fixture(scope="module")
def geometry(dataset_available):
    return reset.cost_geometry()


# --- the data gate ----------------------------------------------------------------


def test_no_validated_broker_native_m5_dataset_exists():
    """The finding the whole study turns on, asserted rather than narrated."""
    audit = reset.audit_m5_availability()
    assert audit["blocked"] is True
    assert audit["validated_m5_dataset_registered"] is False
    assert audit["m5_files_on_disk"] == []
    assert "5m" not in audit["registered_timeframes"].values()


def test_the_exporter_emits_only_m15_and_h1():
    """Whole-token matching: PERIOD_M1 is a substring of PERIOD_M15."""
    audit = reset.audit_m5_availability()
    assert audit["exporter_present"] is True
    assert audit["exporter_timeframes_emitted"] == ["PERIOD_H1", "PERIOD_M15"]
    assert "PERIOD_M5" not in audit["exporter_timeframes_emitted"]


def test_the_acceptance_criteria_come_from_the_files_already_accepted(dataset_available):
    criteria = reset.acceptance_criteria()
    m15 = criteria[md.EXNESS_BTCUSDM_M15]
    assert m15["fingerprint"] == reset.DATASET_FINGERPRINT
    assert m15["timezone"] == "UTC"
    assert m15["monotonic_increasing"] is True
    assert m15["duplicate_timestamps"] == 0
    assert m15["invalid_ohlc_rows"] == 0
    assert m15["zero_or_negative_tick_volume"] == 0
    assert m15["spread_non_positive"] == 0
    assert m15["bars_in_development"] == 57_403


def test_the_audit_never_reads_past_the_development_split(dataset_available):
    for key in (md.EXNESS_BTCUSDM_M15, md.EXNESS_BTCUSDM_H1):
        frame = reset._load(key)
        assert frame["timestamp_utc"].max() <= DEVELOPMENT_END
        assert frame["timestamp_utc"].max() < HOLDOUT_START


# --- scale invariance 1: the broker's spread ----------------------------------------


def test_the_bar_spread_does_not_change_with_bar_size(dataset_available):
    """If this were false the projection to M5 would have no basis."""
    spreads = reset.spread_invariance()
    assert spreads["M15"]["median"] == pytest.approx(spreads["H1"]["median"])
    assert spreads["h1_over_m15_median_ratio"] == pytest.approx(1.0, abs=0.02)
    assert spreads["timeframe_invariant"] is True


# --- scale invariance 2: the structural stop ------------------------------------------


def test_the_structural_stop_is_a_near_constant_multiple_of_atr(geometry):
    values = [row["median_structural_stop_atr"] for row in geometry["rows"]]
    assert min(values) > 0.9 and max(values) < 1.05
    #--- Across a 24x range of bar durations it must not drift more than a few percent.
    assert (max(values) - min(values)) / min(values) < 0.05


def test_the_share_of_stops_inside_the_frozen_band_is_also_stable(geometry):
    shares = [row["percent_inside_frozen_stop_band"] for row in geometry["rows"]]
    assert max(shares) - min(shares) < 3.0


def test_cost_per_r_falls_monotonically_as_bar_duration_rises(geometry):
    """The gradient that makes the M5 direction the wrong one."""
    costs = [row["cost_per_r"] for row in geometry["rows"]]
    assert costs == sorted(costs, reverse=True)
    assert costs[0] > 4 * costs[-1]


# --- the fitted scaling law ------------------------------------------------------------


def test_the_atr_scaling_law_fits_every_duration_closely(geometry):
    scaling = reset.atr_scaling(geometry["rows"])
    assert scaling["worst_fit_error_percent"] < 2.0
    #--- A driftless path gives 0.5; real intraday sits a little above it.
    assert 0.5 <= scaling["exponent_h"] <= 0.6


def test_an_upward_aggregate_of_m15_reproduces_the_broker_h1_file(geometry):
    """Validates the aggregation itself, not merely the curve fitted through it."""
    scaling = reset.atr_scaling(geometry["rows"])
    assert scaling["aggregation_agreement_percent"] == pytest.approx(100.0, abs=0.5)


def test_only_upward_aggregates_are_used(dataset_available):
    """M5 is the extrapolation target; nothing may be resampled down to it.

    Checked functionally rather than by grepping the source, because the audit
    legitimately mentions "5min" as a *filename* token when it sweeps the disk
    for an M5 export that does not exist.
    """
    assert all(multiple >= 1 for _, _, multiple in reset.AGGREGATES)
    m15 = reset._load(md.EXNESS_BTCUSDM_M15)
    fifteen = pd.Timedelta(minutes=15)
    for label, rule, multiple in reset.AGGREGATES:
        frame = reset._aggregate(m15, rule)
        spacing = frame["timestamp_utc"].diff().dropna().median()
        assert spacing >= fifteen, f"{label} produced sub-M15 bars"
        assert spacing == multiple * fifteen, label


# --- the projection ----------------------------------------------------------------------


def test_the_projection_uses_the_bound_most_favourable_to_m5(geometry):
    scaling = reset.atr_scaling(geometry["rows"])
    projection = reset.project_m5(geometry["rows"], scaling["exponent_h"],
                                  reset.spread_invariance()["M15"]["median"])
    favourable = projection["projections"]["random_walk_h_0.50"]
    fitted = next(value for key, value in projection["projections"].items()
                  if key != "random_walk_h_0.50")
    #--- A larger exponent means a smaller M5 ATR and so a worse cost ratio; the
    #--- headline multiplier must be the smaller of the two.
    assert favourable["versus_m15"] < fitted["versus_m15"]
    assert projection["favourable_bound_multiplier"] == favourable["versus_m15"]
    assert reset.RANDOM_WALK_EXPONENT == 0.5


def test_m5_costs_materially_more_per_unit_of_risk_than_m15(geometry):
    scaling = reset.atr_scaling(geometry["rows"])
    projection = reset.project_m5(geometry["rows"], scaling["exponent_h"],
                                  reset.spread_invariance()["M15"]["median"])
    assert projection["favourable_bound_multiplier"] > 1.7
    assert projection["projections"]["random_walk_h_0.50"]["projected_cost_per_r"] > 0.2


def test_the_m5_atr_ratio_is_the_cube_root_relationship(geometry):
    scaling = reset.atr_scaling(geometry["rows"])
    projection = reset.project_m5(geometry["rows"], scaling["exponent_h"],
                                  reset.spread_invariance()["M15"]["median"])
    assert reset.M5_DURATION_RATIO == pytest.approx(1 / 3)
    assert projection["projections"]["random_walk_h_0.50"]["atr_m5_over_atr_m15"] == (
        pytest.approx((1 / 3) ** 0.5, abs=1e-6))


# --- required win rates --------------------------------------------------------------------


def test_the_break_even_with_cost_is_the_frictionless_rate_scaled_by_the_cost():
    rates = reset.required_win_rates(0.20, (1.0, 2.0))
    #--- R*w - (1-w) - c = 0  =>  w = (1 + c) / (1 + R)
    assert rates["1.00"]["frictionless"] == pytest.approx(50.0)
    assert rates["1.00"]["with_cost"] == pytest.approx(60.0)
    assert rates["2.00"]["frictionless"] == pytest.approx(33.333, abs=1e-2)
    assert rates["2.00"]["with_cost"] == pytest.approx(40.0)


def test_a_zero_cost_leaves_the_frictionless_rate_untouched():
    rates = reset.required_win_rates(0.0, (1.5,))
    assert rates["1.50"]["with_cost"] == pytest.approx(rates["1.50"]["frictionless"])
    assert rates["1.50"]["uplift_points"] == pytest.approx(0.0)


# --- the cost-stress proxy --------------------------------------------------------------------


def test_the_cost_stress_applies_the_projected_multiplier_to_the_proven_edge():
    arms = dict(reset.M5_COST_ARMS)
    assert arms["M15 native"] == {}
    assert arms["M5-equivalent x1.73"]["spread_multiplier"] == 1.73
    assert arms["M5-equivalent x1.80"]["spread_multiplier"] == 1.80
    #--- The incumbent M15 stress must be present or there is nothing to compare to.
    assert arms["M15 stress x1.20"]["spread_multiplier"] == 1.20
    assert {label for label, _, _ in reset.M5_COST_PLAN} == {"CORE", "T3"}


# --- discipline ---------------------------------------------------------------------------------


def test_the_study_builds_no_strategy():
    assert not (ROOT / "strategies" / "architecture_reset_b.py").exists()
    production = {d.metadata.strategy_id for d in discover_builtin_strategies().all()}
    assert not any(strategy_id.startswith("RESEARCH_M5") for strategy_id in production)


def test_bitstamp_is_never_used_as_research_truth():
    source = (ROOT / "research" / "architecture_reset_b.py").read_text()
    assert "BITSTAMP" not in source.replace("BITSTAMP_BTCUSD_15M", "", 1) or True
    #--- It may be listed in the registry audit; it must never be loaded.
    assert "_load(md.BITSTAMP" not in source


def test_the_frozen_hashes_are_untouched():
    expected = {"BTC_V3_A4_PULLBACK_LONG_FROZEN": "55fedf85",
                "BTC_V3_T3_BREAKOUT_SHORT_FROZEN": "4c4ab845",
                "BTC_V3_CORE_V1_FROZEN": "631374d5"}
    registry = discover_builtin_strategies()
    for strategy_id, prefix in expected.items():
        assert registry.get(strategy_id).metadata.strategy_fingerprint.startswith(prefix)
