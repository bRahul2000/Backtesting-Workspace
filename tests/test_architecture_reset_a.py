"""BTC Architecture Reset A — reward/exit feasibility.

The study changes one number, so almost everything that could go wrong is a
conflation. The tests pin the three that matter: that the break-even moves with
the target (comparing raw win rates across targets is meaningless), that the
multi-target resolver sees exactly the path Phase G's single-target walk saw,
and that scoring an ambiguous same-bar outcome matches the engine's own
``SameBarResolution.SL_FIRST`` so the raw curve and the backtested curves can be
read side by side.

The fourth is documented rather than assumed: lowering the target is not a pure
exit change in a single-position system, because trades finish sooner and free
the slot for setups that were previously blocked.
"""
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from engine.models import ExecutionState, SameBarResolution, Signal
from research import architecture_reset_a as reset
from research import core_v2_phase_g_outcomes as g
from research.core_v2_phase_a import DEVELOPMENT_END, HOLDOUT_START
from strategies.registry import discover_builtin_strategies

ROOT = Path(__file__).resolve().parents[1]


def _arrays(bars):
    return (np.array([b[0] for b in bars], dtype=float),
            np.array([b[1] for b in bars], dtype=float))


# --- the arithmetic that makes the curve readable -------------------------------------


def test_the_break_even_rate_moves_with_the_target():
    assert reset.break_even_rate(1.00) == pytest.approx(50.0)
    assert reset.break_even_rate(1.25) == pytest.approx(44.4444, abs=1e-3)
    assert reset.break_even_rate(1.50) == pytest.approx(40.0)
    assert reset.break_even_rate(1.75) == pytest.approx(36.3636, abs=1e-3)
    assert reset.break_even_rate(2.00) == pytest.approx(33.3333, abs=1e-3)
    assert reset.break_even_rate(2.50) == pytest.approx(28.5714, abs=1e-3)
    assert reset.break_even_rate(3.00) == pytest.approx(25.0)


def test_the_break_even_rate_is_exactly_where_expectancy_is_zero():
    for target in reset.TARGETS:
        win = reset.break_even_rate(target) / 100.0
        assert target * win - 1.0 * (1 - win) == pytest.approx(0.0, abs=1e-12)


def test_the_briefed_target_grid_is_what_is_measured():
    assert reset.TARGETS == (1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)
    assert reset.BASELINE_TARGET == 3.0


# --- the multi-target resolver ----------------------------------------------------------


def test_the_resolver_matches_the_phase_g_walk_at_the_shared_target():
    """Seven targets in one pass must see the same path one target saw."""
    rng = np.random.default_rng(7)
    mismatches = 0
    for _ in range(500):
        count = int(rng.integers(1, 40))
        mid = 100 + np.cumsum(rng.standard_normal(count))
        highs = mid + rng.random(count) * 2
        lows = mid - rng.random(count) * 2
        for long, stop in ((True, 99.0), (False, 101.0)):
            fresh = reset.resolve_targets(highs, lows, 0, 100.0, stop, long,
                                          reset.TARGETS)[3.0]
            phase_g = g._walk(highs, lows, 0, 100.0, stop, long)["first_touch"]["3R"]
            mismatches += fresh != phase_g
    assert mismatches == 0


def test_a_lower_target_is_never_missed_when_a_higher_one_is_reached():
    rng = np.random.default_rng(11)
    for _ in range(300):
        count = int(rng.integers(1, 40))
        mid = 100 + np.cumsum(rng.standard_normal(count))
        highs, lows = mid + rng.random(count) * 2, mid - rng.random(count) * 2
        resolution = reset.resolve_targets(highs, lows, 0, 100.0, 99.0, True, reset.TARGETS)
        wins = [resolution[target] == "TARGET_FIRST" for target in reset.TARGETS]
        assert not any(wins[i + 1] and not wins[i] for i in range(len(wins) - 1))


def test_the_resolver_separates_the_four_outcomes():
    highs, lows = _arrays([(101.6, 99.5), (101.0, 98.5)])
    resolution = reset.resolve_targets(highs, lows, 0, 100.0, 99.0, True, reset.TARGETS)
    assert resolution[1.0] == "TARGET_FIRST"
    assert resolution[1.5] == "TARGET_FIRST"
    assert resolution[1.75] == "STOP_FIRST"
    assert resolution[3.0] == "STOP_FIRST"

    highs, lows = _arrays([(102.0, 98.0)])
    assert reset.resolve_targets(highs, lows, 0, 100.0, 99.0, True,
                                 reset.TARGETS)[2.0] == "AMBIGUOUS_SAME_BAR"

    highs, lows = _arrays([(100.2, 99.8)] * 5)
    assert reset.resolve_targets(highs, lows, 0, 100.0, 99.0, True,
                                 reset.TARGETS)[1.0] == "NOT_REACHED"


def test_a_zero_length_window_resolves_to_nothing_reached():
    highs, lows = _arrays([(101, 99)])
    resolution = reset.resolve_targets(highs, lows, 5, 100.0, 99.0, True, reset.TARGETS)
    assert set(resolution.values()) == {"NOT_REACHED"}


# --- scoring ------------------------------------------------------------------------------


def _rows(target_first=0, stop_first=0, ambiguous=0, not_reached=0):
    def make(resolution):
        return reset.RawTrade(pd.Timestamp("2024-01-01T00:00:00Z"), "WIDE_BUT_WEAK_ADX",
                              ("STRONG_CLOSE_TOWARD_H1",), "TOWARD_H1",
                              {t: resolution for t in reset.TARGETS})
    return ([make("TARGET_FIRST")] * target_first + [make("STOP_FIRST")] * stop_first
            + [make("AMBIGUOUS_SAME_BAR")] * ambiguous
            + [make("NOT_REACHED")] * not_reached)


def test_an_ambiguous_bar_is_scored_as_a_loss_like_the_engine_does():
    """The engine resolves same-bar as SL_FIRST, so the raw curve must too."""
    assert SameBarResolution.SL_FIRST.name == "SL_FIRST"
    assert "SameBarResolution.SL_FIRST" in (
        ROOT / "core" / "adapters" / "audited_engine.py").read_text()
    cell = reset.payoff_cell(_rows(target_first=1, ambiguous=1), 1.0)
    assert cell["ambiguous_same_bar"] == 1
    assert cell["net_expectancy_r"] == pytest.approx(0.0)


def test_expectancy_is_zero_at_each_target_s_own_break_even_rate():
    for target, wins, losses in ((1.0, 50, 50), (1.5, 40, 60), (3.0, 25, 75)):
        cell = reset.payoff_cell(_rows(target_first=wins, stop_first=losses), target)
        assert cell["actual_rate"] == pytest.approx(reset.break_even_rate(target), abs=0.01)
        assert cell["net_expectancy_r"] == pytest.approx(0.0, abs=1e-9)
        assert cell["edge_over_break_even"] == pytest.approx(0.0, abs=0.01)


def test_an_unresolved_trade_dilutes_rather_than_scoring():
    cell = reset.payoff_cell(_rows(target_first=50, stop_first=50, not_reached=100), 1.0)
    assert cell["events"] == 200
    assert cell["not_reached"] == 100
    assert cell["actual_rate"] == pytest.approx(25.0)
    assert cell["actual_rate_of_resolved"] == pytest.approx(50.0)
    assert cell["net_expectancy_r"] == pytest.approx(0.0)


def test_an_empty_pool_reports_nothing_rather_than_a_fake_zero():
    assert reset.payoff_cell([], 2.0) == {"events": 0}


# --- the config the backtested curves use ---------------------------------------------------


def test_the_target_is_the_only_thing_the_arm_config_moves():
    base = reset.development_config("BTC_V3_A4_PULLBACK_LONG_FROZEN")
    arm = reset.arm_config("BTC_V3_A4_PULLBACK_LONG_FROZEN", 1.5)
    assert arm.risk_reward_ratio == 1.5
    assert base.risk_reward_ratio == 3.0
    for field in ("instrument", "timeframe", "start_date", "end_date", "dataset_role",
                  "risk_per_trade_percent", "spread", "spread_source", "data_source",
                  "spread_multiplier", "slippage_percent"):
        assert getattr(arm, field) == getattr(base, field), field


def test_each_stress_arm_lands_on_the_config():
    for _, stress in reset.STRESS_ARMS:
        arm = reset.arm_config("BTC_V3_A4_PULLBACK_LONG_FROZEN", 2.0, **stress)
        for field, value in stress.items():
            assert getattr(arm, field) == value


def test_no_arm_can_reach_the_holdout():
    for target in reset.TARGETS:
        assert reset.arm_config("BTC_V3_CORE_V1_FROZEN", target).end_date == DEVELOPMENT_END
    assert DEVELOPMENT_END < HOLDOUT_START


def test_no_frozen_strategy_reads_the_reward_ratio():
    """Entries cannot see the target, so the signal stream is target-independent."""
    for name in ("btc_v3_a4_pullback_long.py", "btc_v3_t3_breakout_short.py",
                 "btc_v3_core_v1.py", "btc_v3_l2_trend_pullback_long.py"):
        assert "risk_reward_ratio" not in (ROOT / "strategies" / name).read_text()


# --- the stable-region rule ----------------------------------------------------------------


def _cell(total_r, profit_factor=1.2, subperiod_rs=(1.0, 1.0), best_share=40.0):
    return {
        "total_r": total_r, "profit_factor": profit_factor,
        "best_month_share_of_total": best_share,
        "subperiods": [{"trades": 10, "total_r": value} for value in subperiod_rs],
    }


def _curve(**cells):
    targets = {f"{t:.2f}": _cell(-1.0) for t in reset.TARGETS}
    targets.update(cells)
    return {"label": "X", "strategy_id": "X", "targets": targets}


def test_two_adjacent_positive_targets_make_a_region():
    region = reset.stable_region(_curve(**{"1.50": _cell(5.0), "1.75": _cell(4.0)}))
    assert region["broad_region"] is True
    assert region["region"] == "1.50R-1.75R"


def test_an_isolated_target_is_not_a_region():
    """The brief's own example: 1.75 great, 1.5 bad, 2.0 bad is not acceptable."""
    region = reset.stable_region(_curve(**{"1.75": _cell(9.0)}))
    assert region["broad_region"] is False
    assert region["region"] is None
    assert region["targets_meeting_every_condition"] == ["1.75"]


def test_a_target_positive_in_only_one_subperiod_does_not_count():
    region = reset.stable_region(_curve(**{
        "1.50": _cell(5.0, subperiod_rs=(6.0, -1.0)),
        "1.75": _cell(4.0, subperiod_rs=(5.0, -1.0))}))
    assert region["targets_meeting_every_condition"] == []
    assert region["broad_region"] is False


def test_a_target_carried_by_one_month_does_not_count():
    region = reset.stable_region(_curve(**{
        "1.50": _cell(5.0, best_share=100.0), "1.75": _cell(4.0)}))
    assert region["targets_meeting_every_condition"] == ["1.75"]
    assert region["broad_region"] is False


# --- discipline -------------------------------------------------------------------------------


def test_the_study_builds_no_strategy():
    assert not (ROOT / "strategies" / "architecture_reset_a.py").exists()
    production = {d.metadata.strategy_id for d in discover_builtin_strategies().all()}
    assert not any(strategy_id.startswith("RESEARCH_RESET") for strategy_id in production)


def test_phase_g_is_reused_not_edited():
    """Architecture Reset A imports Phase G's pools; it must not rewrite them."""
    source = (ROOT / "research" / "architecture_reset_a.py").read_text()
    assert "core_v2_phase_g_outcomes as g" in source
    assert "g.STOP_BUFFER_ATR" in source and "g.MIN_STOP_ATR" in source


def test_the_frozen_hashes_are_untouched():
    expected = {"BTC_V3_A4_PULLBACK_LONG_FROZEN": "55fedf85",
                "BTC_V3_T3_BREAKOUT_SHORT_FROZEN": "4c4ab845",
                "BTC_V3_CORE_V1_FROZEN": "631374d5"}
    registry = discover_builtin_strategies()
    for strategy_id, prefix in expected.items():
        assert registry.get(strategy_id).metadata.strategy_fingerprint.startswith(prefix)


def test_the_stress_plan_covers_the_region_the_incumbent_and_the_frequency_case():
    """Section D stresses what section E found, plus something to compare it to."""
    assert set(reset.STRESS_PLAN) <= set({**reset.FROZEN_STREAMS, **reset.PHASE_F_STREAMS})
    assert reset.BASELINE_TARGET in reset.STRESS_PLAN["CORE"]
    assert all(target in reset.TARGETS
               for targets in reset.STRESS_PLAN.values() for target in targets)
    #--- The only configuration that reaches the frequency objective must be
    #--- stressed too, or the comparison has nothing on the other side.
    assert "CORE+F3a" in reset.STRESS_PLAN


def test_the_five_briefed_stress_arms_are_present_and_native_is_first():
    names = [name for name, _ in reset.STRESS_ARMS]
    assert names[0] == "native"
    assert names == ["native", "spread x1.10", "spread x1.20", "slippage 0.02%",
                     "spread x1.20 + slippage 0.02%"]
    assert dict(reset.STRESS_ARMS)["native"] == {}
