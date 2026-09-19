import numpy as np
import pytest

from research.robustness import (
    CapitalModel, RobustnessBlocked, RobustnessConfig, RobustnessMethod,
    RobustnessStore, RobustnessTrade, block_bootstrap_paths, compare_iid_vs_block,
    compute_observed_metrics, compute_path_metrics, compute_source_fingerprint,
    deterministic_fixture_trades, distribution_summary, drawdown_risk,
    iid_bootstrap_paths, outlier_dependence, permutation_paths,
    reserved_data_warning, resample_paths, risk_of_ruin, run_robustness_analysis,
    sequence_dependency, tail_loss_analysis, trades_from_trade_log,
    trades_from_walk_forward_oos, validate_robustness_resume,
)
from research.walk_forward import FoldResult, StitchedTrade

FIXTURE_R = [1.0, 1.0, -1.0, -1.0, -1.0, 2.0, 0.5, -0.5, 3.0, -1.0]


# --- Source model -------------------------------------------------------------------


def test_source_chronological_validation():
    trade_log = [
        {"trade_id": 1, "exit_time": "2024-01-02T00:00:00+00:00", "realized_r": 1.0},
        {"trade_id": 2, "exit_time": "2024-01-01T00:00:00+00:00", "realized_r": -1.0},
    ]
    with pytest.raises(RobustnessBlocked, match="not chronological"):
        trades_from_trade_log(trade_log, dataset_role="DEVELOPMENT", source_run_id="BT-1")


def test_missing_realized_r_never_inferred():
    trade_log = [{"trade_id": 1, "exit_time": "2024-01-01T00:00:00+00:00"}]
    with pytest.raises(RobustnessBlocked, match="missing realized R"):
        trades_from_trade_log(trade_log, dataset_role="DEVELOPMENT", source_run_id="BT-1")


def test_deterministic_fixture_has_known_shape():
    trades = deterministic_fixture_trades()
    assert [t.realized_r for t in trades] == FIXTURE_R
    assert all(t.dataset_role == "DEVELOPMENT" for t in trades)


def test_stitched_walk_forward_oos_source_isolation():
    fold = FoldResult("F1", 1, None, None, None, None, "SELECTED", "c1", {}, None, None, None, None, None, None)
    trades_by_fold = {"F1": [
        StitchedTrade("F1", __import__("datetime").datetime(2023, 1, 1, tzinfo=__import__("datetime").timezone.utc), 1.0, 100.0),
        StitchedTrade("F1", __import__("datetime").datetime(2023, 1, 2, tzinfo=__import__("datetime").timezone.utc), -0.5, -50.0),
    ]}
    trades = trades_from_walk_forward_oos([fold], trades_by_fold, walk_forward_id="WF-1")
    assert all(t.dataset_role == "WALK_FORWARD_OOS" for t in trades)
    assert all(t.fold_id == "F1" for t in trades)
    assert [t.realized_r for t in trades] == [1.0, -0.5]


# --- Resampling: permutation ---------------------------------------------------------


def test_permutation_preserves_exact_trade_multiset_and_terminal_r():
    r = np.array(FIXTURE_R)
    paths = permutation_paths(r, simulations=50, seed=1)
    for row in paths:
        assert sorted(row.tolist()) == sorted(r.tolist())
        assert row.sum() == pytest.approx(r.sum())


def test_permutation_changes_paths():
    r = np.array(FIXTURE_R)
    paths = permutation_paths(r, simulations=20, seed=1)
    assert not all(np.array_equal(paths[0], row) for row in paths[1:])


def test_deterministic_seeded_permutation():
    r = np.array(FIXTURE_R)
    a = permutation_paths(r, simulations=10, seed=7)
    b = permutation_paths(r, simulations=10, seed=7)
    assert np.array_equal(a, b)


# --- Resampling: IID bootstrap --------------------------------------------------------


def test_iid_bootstrap_length_and_replacement():
    r = np.array(FIXTURE_R)
    paths = iid_bootstrap_paths(r, simulations=30, seed=2)
    assert paths.shape == (30, len(r))
    assert all(value in r for row in paths for value in row)


def test_deterministic_seeded_iid_bootstrap():
    r = np.array(FIXTURE_R)
    a = iid_bootstrap_paths(r, simulations=10, seed=3)
    b = iid_bootstrap_paths(r, simulations=10, seed=3)
    assert np.array_equal(a, b)


# --- Resampling: block bootstrap -------------------------------------------------------


def test_block_bootstrap_preserves_within_block_order():
    r = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    paths = block_bootstrap_paths(r, simulations=1, seed=5, block_length=3)
    row = paths[0]
    # every contiguous run of 3 in the source must appear intact somewhere as a sub-triplet
    possible_blocks = {tuple(r[i:i + 3]) for i in range(len(r) - 2)}
    found = any(tuple(row[i:i + 3]) in possible_blocks for i in range(0, len(row) - 2, 3))
    assert found


def test_block_bootstrap_exact_final_length():
    r = np.array(FIXTURE_R)
    paths = block_bootstrap_paths(r, simulations=25, seed=6, block_length=4)
    assert paths.shape == (25, len(r))


def test_deterministic_seeded_block_bootstrap():
    r = np.array(FIXTURE_R)
    a = block_bootstrap_paths(r, simulations=10, seed=9, block_length=3)
    b = block_bootstrap_paths(r, simulations=10, seed=9, block_length=3)
    assert np.array_equal(a, b)


def test_block_length_longer_than_series_caps_to_series_length():
    r = np.array([1.0, -1.0, 2.0])
    paths = block_bootstrap_paths(r, simulations=5, seed=1, block_length=100)
    assert paths.shape == (5, 3)
    for row in paths:
        assert sorted(row.tolist()) == sorted(r.tolist())  # single full-series block, unshuffled


# --- Path metrics (hand-calculated) ------------------------------------------------------


def test_max_dd_losing_streak_winning_streak_recovery_and_rolling_n_hand_calculated():
    r = np.array(FIXTURE_R)
    metrics = compute_observed_metrics(r, rolling_window=3)
    assert metrics["max_dd_r"] == pytest.approx(3.0)
    assert metrics["terminal_r"] == pytest.approx(3.0)
    assert metrics["losing_streak"] == 3
    assert metrics["winning_streak"] == 2
    assert metrics["longest_recovery_trades"] == 7
    assert metrics["worst_rolling_r"] == pytest.approx(-3.0)
    assert metrics["positive_terminal"] is True


# --- Distribution summary / tail statistics --------------------------------------------


def test_quantiles_and_tail_means():
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    summary = distribution_summary(values)
    assert summary["minimum"] == 1.0
    assert summary["maximum"] == 10.0
    assert summary["median"] == pytest.approx(5.5)
    assert summary["mean"] == pytest.approx(5.5)


def test_breach_probability():
    simulated = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    risk = drawdown_risk(observed_max_dd_r=2.0, simulated_max_dd_r=simulated, drawdown_threshold_r=3.0)
    assert risk["drawdown_breach_probability"] == pytest.approx(3 / 5)
    assert risk["label"] == "DRAWDOWN BREACH PROBABILITY"


# --- Risk of ruin -------------------------------------------------------------------------


def test_explicit_risk_of_ruin_model():
    paths = np.array([[-1.0] * 10, [1.0] * 10])
    model = CapitalModel(starting_capital=1000.0, risk_fraction=0.5, ruin_drawdown_percent=50.0)
    result = risk_of_ruin(paths, model)
    assert result["risk_of_ruin"] == pytest.approx(0.5)  # exactly one of the two paths breaches 50% DD
    assert "drawdown >=" in result["ruin_definition"]


def test_ruin_unavailable_without_model():
    paths = np.array([[-1.0, 1.0]])
    result = risk_of_ruin(paths, None)
    assert result["risk_of_ruin"] == "N/A"
    assert result["ruin_definition"] is None


# --- Outlier dependence / top-winner concentration ---------------------------------------


def test_outlier_removal_metrics_and_top_winner_concentration():
    r = np.array(FIXTURE_R)  # winners: 1,1,2,0.5,3 -> gross positive = 7.5
    report = outlier_dependence(r)
    assert report["largest_winning_trade_r"] == pytest.approx(3.0)
    assert report["top_1_winner_contribution_percent"] == pytest.approx(3.0 / 7.5 * 100)
    original_total = report["scenarios"]["original"]["total_r"]
    removed_total = report["scenarios"]["remove_largest_winner"]["total_r"]
    assert removed_total == pytest.approx(original_total - 3.0)
    assert report["worst_3_losses_r"] == [-1.0, -1.0, -1.0]


# --- Tail loss metrics ----------------------------------------------------------------------


def test_tail_loss_metrics_and_small_sample_handling():
    r = np.array(FIXTURE_R)
    tail = tail_loss_analysis(r)
    assert tail["worst_trade_r"] == pytest.approx(-1.0)
    assert tail["small_sample_warning"] is True  # 10 trades < 20


# --- Sequence dependency ----------------------------------------------------------------------


def test_sequence_dependency_percentile():
    observed = {"max_dd_r": 3.0}
    simulated = {"max_dd_r": np.array([1.0, 2.0, 2.5, 2.9, 3.0, 3.1])}
    report = sequence_dependency(observed, simulated)
    assert report["max_dd_r"]["percentile_within_permutations"] == pytest.approx(5 / 6 * 100)


# --- IID vs block comparison ------------------------------------------------------------------


def test_iid_vs_block_comparison_reports_both_without_choosing():
    iid_metrics = {"max_dd_r": np.array([1.0, 2.0, 3.0])}
    block_metrics = {"max_dd_r": np.array([1.5, 2.5, 3.5])}
    comparison = compare_iid_vs_block(iid_metrics, block_metrics)
    assert "iid_bootstrap" in comparison["max_dd_r"]
    assert "block_bootstrap" in comparison["max_dd_r"]
    assert "note" in comparison


# --- Reserved-data warning ---------------------------------------------------------------------


def test_reserved_data_warning():
    assert reserved_data_warning("FORWARD_VALIDATION") == "RESERVED DATA ROBUSTNESS ANALYSIS — DO NOT RETUNE FROM THESE RESULTS"
    assert reserved_data_warning("HOLDOUT") is not None
    assert reserved_data_warning("DEVELOPMENT") is None


# --- Persistence / resume ---------------------------------------------------------------------


def test_persistence_and_reopen_without_rerun(tmp_path):
    store = RobustnessStore(tmp_path / "robustness.sqlite3")
    trades = deterministic_fixture_trades()
    config = RobustnessConfig(method=RobustnessMethod.PERMUTATION, simulations=50, seed=42)
    run, result = run_robustness_analysis(
        trades=trades, config=config, engine_version="test", dataset_role="DEVELOPMENT",
        source_run_id="BT-1", store=store,
    )
    loaded_run = store.load_run(run.robustness_run_id)
    loaded_result = store.load_result(run.robustness_run_id)
    assert loaded_run.robustness_run_id == run.robustness_run_id
    assert loaded_result["observed"]["terminal_r"] == pytest.approx(result["observed"]["terminal_r"])


def test_resume_fingerprint_mismatch_is_blocked(tmp_path):
    store = RobustnessStore(tmp_path / "robustness.sqlite3")
    trades = deterministic_fixture_trades()
    config = RobustnessConfig(method=RobustnessMethod.PERMUTATION, simulations=50, seed=42)
    run, _ = run_robustness_analysis(
        trades=trades, config=config, engine_version="test", dataset_role="DEVELOPMENT",
        source_run_id="BT-1", store=store,
    )
    with pytest.raises(RobustnessBlocked, match="RESUME BLOCKED"):
        validate_robustness_resume(run, source_fingerprint="CHANGED", config=config.as_dict())


# --- Reproducibility / UI model generation ------------------------------------------------------


def test_same_source_config_seed_reproduces_identical_output():
    trades = deterministic_fixture_trades()
    config = RobustnessConfig(method=RobustnessMethod.IID_BOOTSTRAP, simulations=200, seed=42)
    run_a, result_a = run_robustness_analysis(trades=trades, config=config, engine_version="v1", dataset_role="DEVELOPMENT", source_run_id="BT-1")
    run_b, result_b = run_robustness_analysis(trades=trades, config=config, engine_version="v1", dataset_role="DEVELOPMENT", source_run_id="BT-1")
    assert run_a.simulation_fingerprint == run_b.simulation_fingerprint
    assert result_a["distributions"]["terminal_r"] == result_b["distributions"]["terminal_r"]


def test_ui_model_generation_defaults():
    config = RobustnessConfig(method=RobustnessMethod.BLOCK_BOOTSTRAP)
    assert config.simulations == 5000
    assert config.seed == 42
    assert config.block_length == 5
    assert config.rolling_loss_window == 20
    payload = config.as_dict()
    assert payload["method"] == "BLOCK_BOOTSTRAP"


def test_simulation_safety_limit_blocks_excessive_simulations():
    with pytest.raises(RobustnessBlocked, match="safety limit"):
        RobustnessConfig(method=RobustnessMethod.PERMUTATION, simulations=999_999, safety_limit=1000)


def test_full_orchestrator_permutation_run_end_to_end():
    trades = deterministic_fixture_trades()
    config = RobustnessConfig(method=RobustnessMethod.PERMUTATION, simulations=500, seed=42, drawdown_threshold_r=2.5)
    run, result = run_robustness_analysis(
        trades=trades, config=config, engine_version="v1", dataset_role="DEVELOPMENT", source_run_id="BT-1",
        strategy_id="FIXTURE", strategy_version="1", strategy_status="RESEARCH",
    )
    assert run.status == "COMPLETED"
    assert result["path_semantics"] == "R_PATH_SIMULATION"
    assert result["terminal_r_unchanged_by_construction"] is True
    assert result["distributions"]["terminal_r"]["minimum"] == pytest.approx(result["distributions"]["terminal_r"]["maximum"])
    assert result["sequence_dependency"] is not None
    assert result["reserved_data_warning"] is None
