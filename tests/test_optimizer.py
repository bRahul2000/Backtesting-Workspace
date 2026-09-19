from pathlib import Path
from types import SimpleNamespace

import pytest

from core.config import DatasetRole
from research.optimizer import (
    CandidateResult, OptimizationRun, OptimizationStore, SearchParameter,
    StabilityConfig, apply_analysis_filters, candidate_fingerprint,
    generate_grid, generate_random, guard_optimization, one_dimensional_analysis,
    run_candidates, stability_for, two_dimensional_heatmap, validation_comparison,
)
from strategies.base_strategy import StrategyStatus
from strategies.registry import discover_builtin_strategies


def candidate(name, x, y, pf, avg_r, pnl, dd=5, trades=100):
    return CandidateResult(
        candidate_id=name, parameter_fingerprint=candidate_fingerprint({"x": x, "y": y}),
        parameters={"x": x, "y": y}, run_id=name, dataset_fingerprint="d",
        strategy_fingerprint="s", instrument_fingerprint="i", broker_fingerprint="b",
        total_trades=trades, trades_per_month=10, win_rate=50, profit_factor=pf,
        average_r=avg_r, pnl=pnl, max_drawdown=dd, max_losing_streak=2,
    )


def test_typed_grid_random_and_duplicate_determinism():
    parameters = [
        SearchParameter("integer", "integer", 1, 1, 3, 1),
        SearchParameter("float", "float", .1, .1, .2, .1),
        SearchParameter("boolean", "boolean", False),
        SearchParameter("enum", "enum", "a", choices=("a", "b")),
    ]
    grid = generate_grid(parameters)
    assert len(grid) == 24
    assert len({candidate_fingerprint(item) for item in grid}) == 24
    assert generate_random(parameters, 5, 42) == generate_random(parameters, 5, 42)


def test_safety_limit_and_data_role_protection():
    with pytest.raises(ValueError, match="safety limit"):
        generate_grid([SearchParameter("x", "integer", 0, 0, 100, 1)], safety_limit=10)
    descriptor = discover_builtin_strategies().get("BTC_V3_CORE_V1_FROZEN")
    with pytest.raises(ValueError, match="FROZEN"):
        guard_optimization(descriptor, DatasetRole.DEVELOPMENT)
    research_descriptor = SimpleNamespace(metadata=SimpleNamespace(status=StrategyStatus.RESEARCH))
    with pytest.raises(ValueError, match="FORWARD_VALIDATION"):
        guard_optimization(research_descriptor, DatasetRole.FORWARD_VALIDATION)


def test_stability_plateau_peak_boundary_and_missing_cells():
    points = [candidate("a", 1, 1, 1.1, .1, 10), candidate("b", 2, 1, 1.2, .12, 12),
              candidate("c", 3, 1, 2.5, .5, 50), candidate("d", 1, 2, 1.1, .1, 10),
              candidate("e", 2, 2, 1.2, .12, 12)]
    stability = stability_for(points[2], points, [
        SearchParameter("x", "integer", 2, 1, 3, 1), SearchParameter("y", "integer", 1, 1, 2, 1)
    ])
    assert stability["neighbor_count"] == 2
    assert "ISOLATED PEAK PATTERN" in stability["warnings"]
    assert "BOUNDARY SENSITIVITY" in stability["warnings"]
    assert stability["stability_score"] is not None
    assert len(two_dimensional_heatmap(points, "x", "y", "profit_factor")) == 5
    assert len(one_dimensional_analysis(points, "x", "profit_factor")) == 5


def test_filters_preserve_rejected_candidates_and_validation_degradation():
    raw = [candidate("a", 1, 1, 1.1, .1, 10, trades=5)]
    filtered = apply_analysis_filters(raw, minimum_trades=10)
    assert filtered[0].status == "FILTERED"
    assert "trades<10" in filtered[0].rejection_reason
    validation = candidate("a-v", 1, 1, .9, .05, 5, trades=80)
    comparison = validation_comparison(raw[0], validation)
    assert comparison["pf_degradation_percent"] == pytest.approx(18.18181818)
    assert comparison["trade_frequency_change_percent"] == pytest.approx(-1500)


def test_persistence_resume_and_fingerprint_mismatch_is_detectable(tmp_path):
    store = OptimizationStore(tmp_path / "optimizer.sqlite3")
    run = OptimizationRun("OPT-1", "now", "fixture", "1", "GRID", None, {"x": [1, 2]}, 2,
                          "DEVELOPMENT", "d", "i", "b", "phase3b", "RUNNING")
    store.save_run(run)
    one = candidate("one", 1, 1, 1.2, .1, 10)
    run_candidates([one.parameters], "OPT-1", lambda _: one, store, workers=1)
    again = run_candidates([one.parameters], "OPT-1", lambda _: (_ for _ in ()).throw(AssertionError("reran")), store, workers=2)
    assert again[0].candidate_id == "one"
    assert store.load_run("OPT-1").dataset_fingerprint == "d"
    assert store.load_candidates("OPT-1")[0].parameter_fingerprint == one.parameter_fingerprint


def test_parallel_workers_are_conservative_and_deterministic():
    store_a = OptimizationStore("/tmp/optimizer-phase3b-a.sqlite3")
    store_b = OptimizationStore("/tmp/optimizer-phase3b-b.sqlite3")
    values = [{"x": 1}, {"x": 2}]
    execute = lambda params: candidate(str(params["x"]), params["x"], 1, 1.0 + params["x"] / 10, .1, 1)
    left = run_candidates(values, "OPT-A", execute, store_a, workers=1)
    right = run_candidates(values, "OPT-B", execute, store_b, workers=4)
    assert [(item.parameters, item.profit_factor) for item in left] == [(item.parameters, item.profit_factor) for item in right]
