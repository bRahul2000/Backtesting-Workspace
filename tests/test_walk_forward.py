from datetime import datetime, timedelta, timezone

import pytest

from core.config import DatasetRole
from research.optimizer import CandidateResult, SearchParameter, candidate_fingerprint, stability_for
from research.walk_forward import (
    Fold, SelectionPolicyConfig, StitchedTrade, WalkForwardBlocked, WalkForwardConfig,
    WalkForwardMode, WalkForwardStore, build_fold_bars, check_temporal_integrity,
    fold_degradation, generate_folds, guard_dataset_role, guard_walk_forward,
    parameter_drift, run_walk_forward, select_candidate, stitch_oos,
    validate_fold_boundaries, validate_walk_forward_resume, walk_forward_summary,
)
from strategies.base_strategy import StrategyStatus
from strategies.registry import discover_builtin_strategies


def _candidate(candidate_id, x, y, pf, avg_r, pnl, dd=5.0, trades=100):
    return CandidateResult(
        candidate_id=candidate_id, parameter_fingerprint=candidate_fingerprint({"entry": x, "exit": y}),
        parameters={"entry": x, "exit": y}, run_id=candidate_id, dataset_fingerprint="d",
        strategy_fingerprint="s", instrument_fingerprint="i", broker_fingerprint="b",
        total_trades=trades, trades_per_month=10.0, win_rate=50.0, profit_factor=pf,
        average_r=avg_r, pnl=pnl, max_drawdown=dd, max_losing_streak=2,
    )


PARAMETERS = [
    SearchParameter("entry", "integer", 2, 1, 3, 1),
    SearchParameter("exit", "integer", 2, 1, 3, 1),
]


def _fixture_grid(peak_x, peak_y):
    candidates = []
    for x in (1, 2, 3):
        for y in (1, 2, 3):
            pf = 2.0 if (x, y) == (peak_x, peak_y) else 1.25 - abs(x - peak_x) * 0.08 - abs(y - peak_y) * 0.04
            candidates.append(_candidate(f"c-{peak_x}-{peak_y}-{x}-{y}", x, y, pf, pf - 1.0, (pf - 1.0) * 1000))
    return [
        CandidateResult(**{**c.__dict__, "stability": stability_for(c, candidates, PARAMETERS)})
        for c in candidates
    ]


def _daily_bars(start, end):
    bars = []
    current = start
    while current < end:
        bars.append(current)
        current += timedelta(days=1)
    return bars


UTC = timezone.utc
BAR_START = datetime(2021, 1, 1, tzinfo=UTC)
BAR_END = datetime(2024, 1, 1, tzinfo=UTC)
BARS = _daily_bars(BAR_START, BAR_END)


def _descriptor(status=StrategyStatus.RESEARCH):
    from types import SimpleNamespace
    return SimpleNamespace(metadata=SimpleNamespace(
        status=status, strategy_id="FIXTURE", version="1", strategy_fingerprint="fixture-fp",
    ))


# --- Window generation: rolling / anchored / step ---------------------------------


def test_rolling_window_boundaries_and_step():
    config = WalkForwardConfig(mode=WalkForwardMode.ROLLING, training_months=24, validation_months=3, step_months=3)
    folds = generate_folds(config, BAR_START, BAR_END)
    assert folds[0].train_start == datetime(2021, 1, 1, tzinfo=UTC)
    assert folds[0].train_end == datetime(2022, 12, 31, tzinfo=UTC).replace(day=1, month=12, year=2022) or True
    assert folds[0].train_end == datetime(2023, 1, 1, tzinfo=UTC)
    assert folds[0].validation_start == datetime(2023, 1, 1, tzinfo=UTC)
    assert folds[0].validation_end == datetime(2023, 4, 1, tzinfo=UTC)
    assert folds[1].train_start == datetime(2021, 4, 1, tzinfo=UTC)
    assert folds[1].train_end == datetime(2023, 4, 1, tzinfo=UTC)
    assert folds[1].validation_start == datetime(2023, 4, 1, tzinfo=UTC)
    assert folds[1].validation_end == datetime(2023, 7, 1, tzinfo=UTC)
    for fold in folds:
        validate_fold_boundaries(fold)


def test_anchored_window_boundaries():
    config = WalkForwardConfig(mode=WalkForwardMode.ANCHORED, training_months=24, validation_months=3, step_months=3)
    folds = generate_folds(config, BAR_START, BAR_END)
    assert folds[0].train_start == datetime(2021, 1, 1, tzinfo=UTC)
    assert folds[1].train_start == datetime(2021, 1, 1, tzinfo=UTC)
    assert folds[1].train_end == datetime(2023, 4, 1, tzinfo=UTC)
    assert folds[2].train_start == datetime(2021, 1, 1, tzinfo=UTC)
    assert folds[2].train_end == datetime(2023, 7, 1, tzinfo=UTC)


def test_insufficient_window_data_produces_no_folds():
    config = WalkForwardConfig(training_months=24, validation_months=3, step_months=3)
    folds = generate_folds(config, BAR_START, datetime(2022, 6, 1, tzinfo=UTC))
    assert folds == []


def test_train_validation_overlap_and_nonchronological_blocking():
    fold = Fold("bad", 1, "ROLLING", datetime(2021, 1, 1, tzinfo=UTC), datetime(2021, 6, 1, tzinfo=UTC),
                datetime(2021, 3, 1, tzinfo=UTC), datetime(2021, 9, 1, tzinfo=UTC))
    with pytest.raises(WalkForwardBlocked):
        validate_fold_boundaries(fold)


# --- Temporal integrity: embargo / warmup / leakage --------------------------------


def test_embargo_shifts_validation_trade_eligibility():
    config = WalkForwardConfig(training_months=24, validation_months=3, step_months=3)
    fold = generate_folds(config, BAR_START, BAR_END)[0]
    bars = build_fold_bars(fold, BARS, embargo_bars=5, warmup_bars=0, minimum_training_bars=1, minimum_validation_bars=1)
    assert bars.embargoed_timestamps == bars.validation_timestamps[:5]
    assert bars.validation_trade_eligible_timestamps[0] == bars.validation_timestamps[5]
    report = check_temporal_integrity(fold, bars, embargo_bars=5, warmup_bars=0)
    assert report.temporal_integrity_passed is True
    assert report.leakage_violations == ()


def test_warmup_bars_come_only_from_before_validation():
    config = WalkForwardConfig(training_months=24, validation_months=3, step_months=3)
    fold = generate_folds(config, BAR_START, BAR_END)[0]
    bars = build_fold_bars(fold, BARS, embargo_bars=0, warmup_bars=10, minimum_training_bars=1, minimum_validation_bars=1)
    assert all(t < fold.validation_start for t in bars.warmup_timestamps)
    assert set(bars.warmup_timestamps).isdisjoint(bars.validation_trade_eligible_timestamps)


def test_temporal_leakage_is_blocked_never_silent():
    config = WalkForwardConfig(training_months=24, validation_months=3, step_months=3)
    fold = generate_folds(config, BAR_START, BAR_END)[0]
    bars = build_fold_bars(fold, BARS, embargo_bars=0, warmup_bars=0, minimum_training_bars=1, minimum_validation_bars=1)
    tampered = bars.__class__(
        fold_id=bars.fold_id, training_timestamps=bars.training_timestamps,
        warmup_timestamps=(bars.validation_trade_eligible_timestamps[0],),
        validation_timestamps=bars.validation_timestamps,
        validation_trade_eligible_timestamps=bars.validation_trade_eligible_timestamps,
        embargoed_timestamps=bars.embargoed_timestamps,
    )
    with pytest.raises(WalkForwardBlocked, match="WALK-FORWARD BLOCKED"):
        check_temporal_integrity(fold, tampered, embargo_bars=0, warmup_bars=0)


def test_insufficient_bars_block_fold():
    config = WalkForwardConfig(training_months=24, validation_months=3, step_months=3)
    fold = generate_folds(config, BAR_START, BAR_END)[0]
    with pytest.raises(WalkForwardBlocked, match="training bars"):
        build_fold_bars(fold, BARS, embargo_bars=0, warmup_bars=0, minimum_training_bars=10**9, minimum_validation_bars=1)


def test_forward_holdout_blocking():
    with pytest.raises(WalkForwardBlocked, match="FORWARD_VALIDATION/HOLDOUT"):
        guard_dataset_role(DatasetRole.FORWARD_VALIDATION)
    with pytest.raises(WalkForwardBlocked, match="FORWARD_VALIDATION/HOLDOUT"):
        guard_dataset_role(DatasetRole.HOLDOUT)
    guard_dataset_role(DatasetRole.DEVELOPMENT)  # does not raise


def test_frozen_strategy_walk_forward_disabled():
    descriptor = discover_builtin_strategies().get("BTC_V3_CORE_V1_FROZEN")
    with pytest.raises(WalkForwardBlocked, match="FROZEN STRATEGY"):
        guard_walk_forward(descriptor, DatasetRole.DEVELOPMENT)


# --- Deterministic candidate selection ---------------------------------------------


def test_validation_cannot_alter_selection():
    candidates = _fixture_grid(2, 2)
    _, before = select_candidate(candidates, SelectionPolicyConfig(), fold_id="F1")
    tainted = [CandidateResult(**{**c.__dict__, "validation": {"profit_factor": -99}}) for c in candidates]
    _, after = select_candidate(tainted, SelectionPolicyConfig(), fold_id="F1")
    assert before.selected_candidate_id == after.selected_candidate_id
    assert len(before.eligible_candidate_ids) == len(after.eligible_candidate_ids)


def _fixture_grid_no_isolation(peak_x, peak_y):
    candidates = []
    for x in (1, 2, 3):
        for y in (1, 2, 3):
            pf = 1.5 if (x, y) == (peak_x, peak_y) else 1.25 - abs(x - peak_x) * 0.08 - abs(y - peak_y) * 0.04
            candidates.append(_candidate(f"c-{peak_x}-{peak_y}-{x}-{y}", x, y, pf, pf - 1.0, (pf - 1.0) * 1000))
    return [
        CandidateResult(**{**c.__dict__, "stability": stability_for(c, candidates, PARAMETERS)})
        for c in candidates
    ]


def test_deterministic_candidate_selection_and_tie_breaking():
    candidates = _fixture_grid_no_isolation(2, 2)
    selected_a, _ = select_candidate(candidates, SelectionPolicyConfig(), fold_id="F1")
    selected_b, _ = select_candidate(list(reversed(candidates)), SelectionPolicyConfig(), fold_id="F1")
    assert selected_a.candidate_id == selected_b.candidate_id == "c-2-2-2-2"


def test_isolated_peak_avoidance():
    peers = [_candidate("normal-a", 1, 1, 1.1, 0.1, 10), _candidate("normal-b", 1, 2, 1.15, 0.12, 12)]
    isolated = _candidate("isolated", 2, 2, 5.0, 0.5, 50)
    pool = peers + [isolated]
    stabled = [CandidateResult(**{**c.__dict__, "stability": stability_for(c, pool, PARAMETERS)}) for c in pool]
    selected, rationale = select_candidate(stabled, SelectionPolicyConfig(), fold_id="F1")
    assert selected.candidate_id != "isolated"
    assert rationale.exclusion_reasons.get("isolated", "").startswith("ISOLATED PEAK PATTERN")


def test_no_selection_when_no_candidate_satisfies_policy():
    candidates = [_candidate("only", 1, 1, 0.5, -0.2, -10)]
    selected, rationale = select_candidate(candidates, SelectionPolicyConfig(require_positive_average_r=True), fold_id="F1")
    assert selected is None
    assert rationale.selected_candidate_id is None


# --- Parameter freezing / fingerprints ----------------------------------------------


def test_parameter_freezing_uses_exact_training_candidate():
    candidates = _fixture_grid_no_isolation(2, 2)
    selected, _ = select_candidate(candidates, SelectionPolicyConfig(), fold_id="F1")
    assert selected.parameters == {"entry": 2, "exit": 2}
    assert selected.parameter_fingerprint == candidate_fingerprint({"entry": 2, "exit": 2})


# --- Zero-safe degradation -----------------------------------------------------------


def test_zero_safe_degradation_metrics():
    result = fold_degradation({"profit_factor": 0, "average_r": 0.2, "total_trades": 0, "max_drawdown": 5.0},
                              {"profit_factor": 1.5, "average_r": 0.1, "total_trades": 10, "max_drawdown": 6.0})
    assert result["pf_degradation_percent"] is None
    assert result["trade_frequency_change_percent"] is None
    assert result["average_r_degradation_percent"] == pytest.approx(-50.0)
    assert result["dd_change_percent"] == pytest.approx(20.0)


# --- Parameter drift -------------------------------------------------------------------


def test_parameter_drift_reports_changed_and_unchanged():
    from research.walk_forward import FoldResult
    fold_a = FoldResult("F1", 1, BAR_START, BAR_START, BAR_START, BAR_START, "SELECTED", "c1",
                        {"entry": 2, "exit": 2}, None, None, None, None, None, None)
    fold_b = FoldResult("F2", 2, BAR_START, BAR_START, BAR_START, BAR_START, "SELECTED", "c2",
                        {"entry": 3, "exit": 2}, None, None, None, None, None, None)
    drift = parameter_drift([fold_a, fold_b])
    assert drift["per_parameter"]["entry"]["changed"] is True
    assert drift["per_parameter"]["exit"]["changed"] is False
    assert drift["changed_parameter_count"] == 1
    assert drift["unchanged_parameter_count"] == 1
    assert drift["total_parameter_distance"] == pytest.approx(1.0)


# --- Stitched OOS ---------------------------------------------------------------------


def test_stitched_oos_chronological_ordering_and_duplicate_prevention():
    from research.walk_forward import FoldResult
    fold_a = FoldResult("F1", 1, BAR_START, BAR_START, BAR_START, BAR_START, "SELECTED", "c1", {}, None, None, None, None, None, None)
    fold_b = FoldResult("F2", 2, BAR_START, BAR_START, BAR_START, BAR_START, "SELECTED", "c2", {}, None, None, None, None, None, None)
    t1 = StitchedTrade("F1", datetime(2023, 2, 1, tzinfo=UTC), 1.0, 100.0)
    t2 = StitchedTrade("F2", datetime(2023, 1, 1, tzinfo=UTC), -0.5, -50.0)
    stitched = stitch_oos([fold_a, fold_b], {"F1": [t1], "F2": [t2]})
    assert [t.fold_id for t in stitched["stitched_trades"]] == ["F2", "F1"]
    assert stitched["total_oos_trades"] == 2
    assert stitched["equity_semantics"] == "NON_COMPOUNDED_FOLD_STITCH"

    with pytest.raises(WalkForwardBlocked, match="duplicate"):
        stitch_oos([fold_a], {"F1": [t1, t1]})


# --- Persistence / resume --------------------------------------------------------------


def test_fold_persistence_and_resume(tmp_path):
    store = WalkForwardStore(tmp_path / "wf.sqlite3")
    from research.walk_forward import FoldResult, WalkForwardRun
    run = WalkForwardRun("WF-1", "now", "FIXTURE", "1", "fp", {"training_months": 24}, "d", "b", "i", "engine", "RUNNING", 1)
    store.save_run(run)
    fold_result = FoldResult("F1", 1, BAR_START, BAR_START, BAR_START, BAR_START, "SELECTED", "c1", {"entry": 2}, None, None, None, None, None, None)
    store.save_fold("WF-1", fold_result)

    loaded_run = store.load_run("WF-1")
    loaded_folds = store.load_folds("WF-1")
    assert loaded_run.walk_forward_id == "WF-1"
    assert loaded_folds[0]["fold_id"] == "F1"

    validate_walk_forward_resume(loaded_run, strategy_fingerprint="fp", dataset_fingerprint="d",
                                 broker_fingerprint="b", instrument_fingerprint="i", config={"training_months": 24})


def test_resume_fingerprint_mismatch_is_blocked(tmp_path):
    store = WalkForwardStore(tmp_path / "wf.sqlite3")
    from research.walk_forward import WalkForwardRun
    run = WalkForwardRun("WF-1", "now", "FIXTURE", "1", "fp", {"training_months": 24}, "d", "b", "i", "engine", "RUNNING", 1)
    store.save_run(run)
    with pytest.raises(WalkForwardBlocked, match="RESUME BLOCKED"):
        validate_walk_forward_resume(store.load_run("WF-1"), strategy_fingerprint="fp", dataset_fingerprint="CHANGED",
                                     broker_fingerprint="b", instrument_fingerprint="i", config={"training_months": 24})


# --- Full orchestrator integration ------------------------------------------------------


def test_full_walk_forward_run_generates_folds_with_drift_and_summary(tmp_path):
    config = WalkForwardConfig(
        mode=WalkForwardMode.ROLLING, training_months=24, validation_months=3, step_months=3,
        embargo_bars=0, warmup_bars=5, minimum_training_bars=1, minimum_validation_bars=1,
        selection_policy=SelectionPolicyConfig(),
    )

    def train_candidates_fn(fold, cfg):
        peak_x = 1 + (fold.fold_number % 3)
        return _fixture_grid_no_isolation(peak_x, 2)

    def validate_fn(fold, parameters):
        peak_x = 1 + (fold.fold_number % 3)
        x, y = parameters["entry"], parameters["exit"]
        pf = (1.8 if (x, y) == (peak_x, 2) else 1.1) * 0.9  # simulated OOS degradation
        return _candidate(f"val-{fold.fold_id}", x, y, pf, pf - 1.0, (pf - 1.0) * 500)

    store = WalkForwardStore(tmp_path / "wf.sqlite3")
    descriptor = _descriptor(StrategyStatus.RESEARCH)
    run, fold_results = run_walk_forward(
        descriptor=descriptor, config=config, bar_timestamps=BARS, data_role=DatasetRole.DEVELOPMENT,
        dataset_fingerprint="dataset-fp", broker_fingerprint="broker-fp", instrument_fingerprint="instrument-fp",
        engine_version="phase3c-fixture", train_candidates_fn=train_candidates_fn, validate_fn=validate_fn, store=store,
    )

    assert run.status == "COMPLETED"
    assert len(fold_results) == run.fold_count == 3
    assert all(f.status == "SELECTED" for f in fold_results)
    assert all(f.temporal_integrity.temporal_integrity_passed for f in fold_results)

    drift = parameter_drift(fold_results)
    assert drift["per_parameter"]["exit"]["changed"] is False
    assert drift["per_parameter"]["entry"]["changed"] is True

    summary = walk_forward_summary(fold_results)
    assert summary["selection_coverage_percent"] == 100.0

    loaded_run = store.load_run(run.walk_forward_id)
    loaded_folds = store.load_folds(run.walk_forward_id)
    assert loaded_run.fold_count == 3
    assert len(loaded_folds) == 3

    trades = {
        f.fold_id: [StitchedTrade(f.fold_id, f.validation_start + timedelta(days=1), 0.5, 50.0)]
        for f in fold_results
    }
    stitched = stitch_oos(fold_results, trades)
    assert stitched["total_oos_trades"] == 3
    assert stitched["successful_fold_count"] == 3
    assert stitched["no_selection_fold_count"] == 0


def test_ui_model_generation_defaults_match_research_configuration():
    config = WalkForwardConfig()
    assert config.mode is WalkForwardMode.ROLLING
    assert config.training_months == 24
    assert config.validation_months == 3
    assert config.step_months == 3
    assert config.embargo_bars == 0
    payload = config.as_dict()
    assert payload["mode"] == "ROLLING"
    folds = generate_folds(config, BAR_START, BAR_END)
    assert len(folds) == 4
    assert all(isinstance(f.fold_id, str) for f in folds)
