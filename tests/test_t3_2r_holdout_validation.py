"""BTC Final Candidate Validation — frozen T3 SHORT at 2.00R on HOLDOUT.

The holdout is spendable once, so the tests here are mostly about discipline
rather than arithmetic: the gates must be the declared four and nothing else,
the candidate must be the frozen T3 with only the engine's reward multiple set,
the holdout window must be exactly the reserved range, and the execution-stress
arms must be incapable of changing the verdict.

The gate values are pinned literally. If a later edit moves one, this test fails
and the change is visible in the diff instead of passing unnoticed.
"""
from pathlib import Path

import pandas as pd
import pytest

from core.config import DatasetRole
from research import t3_2r_holdout_validation as validation
from research.core_v2_phase_a import (
    DEVELOPMENT_END, DEVELOPMENT_START, HOLDOUT_END, HOLDOUT_START,
)
from strategies.btc_v3_t3_breakout_short import STRATEGY_ID as T3_STRATEGY_ID
from strategies.btc_v3_t3_breakout_short import V3T3FrozenParameters
from strategies.registry import discover_builtin_strategies

ROOT = Path(__file__).resolve().parents[1]


# --- the predeclaration -------------------------------------------------------------


def test_the_four_gates_are_exactly_the_declared_ones():
    assert validation.GATES == {
        "profit_factor_min": 1.10,
        "average_r_min_exclusive": 0.0,
        "total_r_min_exclusive": 0.0,
        "max_drawdown_percent_max_exclusive": 4.0,
    }


def test_the_candidate_is_the_frozen_t3_at_two_r_and_nothing_else():
    assert validation.CANDIDATE["strategy_id"] == T3_STRATEGY_ID
    assert validation.CANDIDATE["reward_multiple"] == 2.00


def test_only_the_reward_multiple_differs_from_the_frozen_defaults():
    """Entries, filters and the structural stop must be untouched."""
    frozen = V3T3FrozenParameters()
    assert frozen.shorts_enabled is True and frozen.longs_enabled is False
    assert frozen.trend_enabled is True and frozen.range_enabled is False
    #--- The engine applies the target; the strategy never sees it.
    source = (ROOT / "strategies" / "btc_v3_t3_breakout_short.py").read_text()
    assert "risk_reward_ratio" not in source


def test_the_holdout_config_is_the_reserved_window_and_role():
    config = validation.holdout_config()
    assert config.start_date == HOLDOUT_START == pd.Timestamp("2025-07-01 00:00", tz="UTC")
    assert config.end_date == HOLDOUT_END == pd.Timestamp("2026-09-20 07:15", tz="UTC")
    assert config.dataset_role is DatasetRole.HOLDOUT
    assert config.risk_reward_ratio == 2.00
    assert config.strategy_id == T3_STRATEGY_ID


def test_the_development_config_stays_inside_development():
    config = validation.development_config()
    assert config.start_date == DEVELOPMENT_START
    assert config.end_date == DEVELOPMENT_END
    assert config.end_date < HOLDOUT_START
    assert config.dataset_role is DatasetRole.DEVELOPMENT


def test_the_two_configs_differ_only_in_window_and_role():
    development, holdout = validation.development_config(), validation.holdout_config()
    for field in ("instrument", "broker_profile", "strategy_id", "timeframe",
                  "risk_per_trade_percent", "risk_reward_ratio", "spread",
                  "spread_source", "data_source", "spread_multiplier",
                  "slippage_percent"):
        assert getattr(development, field) == getattr(holdout, field), field


# --- the gate logic -------------------------------------------------------------------


def _summary(**over):
    payload = {"profit_factor": 1.5, "average_r": 0.2, "total_r": 10.0,
               "max_drawdown_percent": 2.0}
    payload.update(over)
    return payload


def test_a_candidate_meeting_all_four_gates_is_validated():
    result = validation.apply_gates(_summary())
    assert result["all_passed"] is True
    assert result["decision"] == "T3 2.0R OOS VALIDATED"
    assert result["failed"] == []


@pytest.mark.parametrize("field,value,gate", [
    ("profit_factor", 1.09, "PF >= 1.1"),
    ("average_r", 0.0, "Avg R > 0"),
    ("total_r", 0.0, "total R > 0"),
    ("max_drawdown_percent", 4.0, "Max DD < 4.0%"),
])
def test_any_single_gate_failure_rejects(field, value, gate):
    result = validation.apply_gates(_summary(**{field: value}))
    assert result["all_passed"] is False
    assert result["decision"] == "REJECT T3 2.0R"
    assert gate in result["failed"]


def test_the_boundaries_are_read_as_declared():
    """PF is inclusive at 1.10; the other three are strict."""
    assert validation.apply_gates(_summary(profit_factor=1.10))["all_passed"] is True
    assert validation.apply_gates(_summary(average_r=1e-9))["all_passed"] is True
    assert validation.apply_gates(_summary(max_drawdown_percent=3.999))["all_passed"] is True
    assert validation.apply_gates(_summary(max_drawdown_percent=4.0))["all_passed"] is False


def test_an_undefined_profit_factor_does_not_pass():
    assert validation.apply_gates(_summary(profit_factor=None))["all_passed"] is False


# --- stress cannot change the verdict ----------------------------------------------------


def test_the_stress_arms_are_diagnostics_not_gates():
    names = [name for name, _ in validation.STRESS_ARMS]
    assert names == ["native", "spread x1.10", "spread x1.20", "slippage 0.02%",
                     "spread x1.20 + slippage 0.02%"]
    assert dict(validation.STRESS_ARMS)["native"] == {}
    assert "execution_stress" in validation.DIAGNOSTICS_ONLY
    #--- ``apply_gates`` takes only the native summary, so a stress arm has no
    #--- path to the decision even if it fails.
    source = (ROOT / "research" / "t3_2r_holdout_validation.py").read_text()
    assert "apply_gates(holdout)" in source


def test_frequency_and_win_rate_are_reported_but_never_judged():
    for name in ("trades", "trades_per_month", "win_rate", "max_losing_streak",
                 "monthly", "subperiods", "quarters", "excursions"):
        assert name in validation.DIAGNOSTICS_ONLY


# --- the guard before the split is opened -------------------------------------------------


def test_the_holdout_is_refused_if_development_is_not_reproduced():
    bad = validation.reproduces_development(
        {"trades": 1, "profit_factor": 9.9, "average_r": 9.9, "total_r": 9.9,
         "max_drawdown_percent": 9.9})
    assert bad["reproduced"] is False
    good = validation.reproduces_development({
        "trades": 88, "profit_factor": 1.2596, "average_r": 0.1596,
        "total_r": 14.05, "max_drawdown_percent": 1.46})
    assert good["reproduced"] is True


def test_the_development_reference_is_the_one_reset_a_recorded():
    assert validation.DEVELOPMENT_REFERENCE["trades"] == 88
    assert validation.DEVELOPMENT_REFERENCE["profit_factor"] == pytest.approx(1.2596)
    assert validation.DEVELOPMENT_REFERENCE["total_r"] == pytest.approx(14.05)
    assert validation.DEVELOPMENT_REFERENCE["max_drawdown_percent"] == pytest.approx(1.46)


# --- no retuning ----------------------------------------------------------------------------


def test_only_one_reward_multiple_exists_anywhere_in_this_module():
    """No RR sweep may be run on the holdout, so no grid may exist here."""
    source = (ROOT / "research" / "t3_2r_holdout_validation.py").read_text()
    assert "TARGETS" not in source
    assert "for target in" not in source
    assert source.count("reward_multiple") >= 1


def test_the_frozen_t3_hash_is_untouched():
    registry = discover_builtin_strategies()
    fingerprint = registry.get(T3_STRATEGY_ID).metadata.strategy_fingerprint
    assert fingerprint == (
        "4c4ab845852ff973530f30ebee86061ea72bd29d68ff6165970dd5a9efde7910")


def test_a4_is_not_part_of_the_primary_candidate():
    assert "A4" not in validation.CANDIDATE["strategy_id"]
    source = (ROOT / "research" / "t3_2r_holdout_validation.py").read_text()
    assert "a4_pullback" not in source.lower()
