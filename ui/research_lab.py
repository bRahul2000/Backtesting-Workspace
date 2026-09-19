from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import uuid
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.config import DatasetRole
from research.optimizer import (
    CandidateResult, OptimizationRun, OptimizationStore, SearchParameter,
    StabilityConfig, candidate_fingerprint, candidate_id, generate_grid,
    guard_optimization, guard_validation_dataset, stability_for, two_dimensional_heatmap,
)
from research.walk_forward import (
    SelectionPolicyConfig, StitchedTrade, WalkForwardBlocked, WalkForwardConfig,
    WalkForwardMode, WalkForwardStore, generate_folds, guard_dataset_role,
    guard_walk_forward, parameter_drift, run_walk_forward, stitch_oos,
    walk_forward_summary,
)
from strategies.base_strategy import StrategyStatus
from strategies.registry import discover_builtin_strategies

ROOT = Path(__file__).resolve().parents[1]
STORE = OptimizationStore(ROOT / "experiments" / "optimizations.sqlite3")
WF_STORE = WalkForwardStore(ROOT / "experiments" / "walk_forward.sqlite3")


def _fixture_candidates(optimization_id: str, parameters: list[dict]) -> list[CandidateResult]:
    results = []
    for values in parameters:
        x, y = values["entry_threshold"], values["exit_threshold"]
        peak = 2.0 if (x == 2 and y == 2) else 1.25 - abs(x - 2) * .08 - abs(y - 2) * .04
        results.append(CandidateResult(
            candidate_id=candidate_id(optimization_id, values),
            parameter_fingerprint=candidate_fingerprint(values), parameters=values,
            run_id=None, dataset_fingerprint="fixture", strategy_fingerprint="fixture",
            instrument_fingerprint="fixture", broker_fingerprint="fixture",
            total_trades=100 - abs(x - 2) * 4, trades_per_month=10.0,
            win_rate=52.0, profit_factor=peak, average_r=peak - 1.0,
            pnl=(peak - 1.0) * 1000, max_drawdown=4.0 + abs(x - 2) * 1.5,
            max_losing_streak=4,
        ))
    return results


def _candidate_table(candidates: list[CandidateResult], parameters: list[SearchParameter]) -> pd.DataFrame:
    rows = []
    for candidate in candidates:
        stability = candidate.stability or {}
        rows.append({
            "Candidate": candidate.candidate_id, "Parameters": str(candidate.parameters),
            "Trades": candidate.total_trades, "Trades/month": candidate.trades_per_month,
            "WR": candidate.win_rate, "PF": candidate.profit_factor, "Avg R": candidate.average_r,
            "PnL": candidate.pnl, "Max DD": candidate.max_drawdown,
            "Losing Streak": candidate.max_losing_streak,
            "Stability": stability.get("stability_score"),
            "Classification": stability.get("classification"),
            "Warnings": ", ".join(stability.get("warnings", [])),
            "Status": candidate.status, "Rejection": candidate.rejection_reason,
        })
    return pd.DataFrame(rows)


def _fixture_space() -> list[SearchParameter]:
    return [
        SearchParameter("entry_threshold", "integer", 2, 1, 3, 1, description="Synthetic fixture entry threshold"),
        SearchParameter("exit_threshold", "integer", 2, 1, 3, 1, description="Synthetic fixture exit threshold"),
    ]


def render_research_lab() -> None:
    st.markdown("# Research Lab")
    st.caption("Parameter surfaces, stability, and reproducibility. Results report differences; they do not choose winners.")
    tabs = st.tabs(["Optimizer", "Stability", "Optimization History", "Walk-Forward", "Walk-Forward History"])
    with tabs[0]:
        _render_optimizer()
    with tabs[1]:
        _render_stability()
    with tabs[2]:
        _render_history()
    with tabs[3]:
        _render_walk_forward_setup()
    with tabs[4]:
        _render_walk_forward_history()


def _render_optimizer() -> None:
    registry = discover_builtin_strategies()
    descriptors = registry.all()
    labels = [f"{item.metadata.name} · {item.metadata.status.value}" for item in descriptors]
    selected = st.selectbox("Research strategy", labels)
    descriptor = descriptors[labels.index(selected)]
    frozen = descriptor.metadata.status is StrategyStatus.FROZEN
    st.caption(f"Strategy version {descriptor.metadata.version} · fingerprint {descriptor.metadata.strategy_fingerprint}")
    if frozen:
        st.error("OPTIMIZATION DISABLED - FROZEN STRATEGY")
    fixture_mode = st.checkbox("Use deterministic test fixture surface", value=True)
    st.markdown("### Optimization Dataset")
    st.caption("DEVELOPMENT ONLY")
    role = DatasetRole(st.selectbox("Optimization dataset role", [DatasetRole.DEVELOPMENT.value], index=0))
    st.markdown("### Optional Validation Dataset")
    st.caption("SECONDARY EVALUATION ONLY")
    validation_role = st.selectbox("Validation dataset role", ["NONE", DatasetRole.VALIDATION.value], index=0)
    method = st.selectbox("Search method", ("Grid Search", "Random Search"))
    seed = st.number_input("Random seed", value=42, step=1)
    safety = st.number_input("Safety limit", min_value=1, max_value=100000, value=1000, step=100)
    parameters = _fixture_space() if fixture_mode else []
    if not fixture_mode:
        parameters = list(__import__("research.optimizer", fromlist=["search_parameters"]).search_parameters(descriptor))
    combinations = 0
    try:
        combinations = len(generate_grid(parameters, safety_limit=int(safety)))
    except ValueError as error:
        st.error(str(error))
    st.info(f"{combinations} parameter combinations · estimated backtests: {combinations}")
    if st.button("Start Optimization", type="primary", disabled=frozen or combinations == 0):
        try:
            guard_optimization(descriptor, role)
            if validation_role != "NONE":
                guard_validation_dataset(DatasetRole(validation_role))
        except ValueError as error:
            st.error(str(error))
            if "Parameter search is restricted to DEVELOPMENT data" in str(error):
                st.error("OPTIMIZATION BLOCKED\nParameter search is restricted to DEVELOPMENT data.")
            return
        optimization_id = "OPT-" + uuid.uuid4().hex[:10].upper()
        values = generate_grid(parameters, safety_limit=int(safety))
        candidates = _fixture_candidates(optimization_id, values) if fixture_mode else []
        for candidate in candidates:
            candidate = CandidateResult(**{**asdict(candidate), "stability": stability_for(candidate, candidates, parameters)})
            STORE.save_candidate(optimization_id, candidate)
        run = OptimizationRun(
            optimization_id, datetime.now(timezone.utc).isoformat(), descriptor.metadata.strategy_id,
            descriptor.metadata.version, method, int(seed) if method == "Random Search" else None,
            {parameter.name: list(parameter.values()) for parameter in parameters}, len(values), role.value,
            "fixture", descriptor.metadata.strategy_fingerprint, "fixture", "phase3b", "COMPLETED",
            optimization_dataset_role=role.value,
            optimization_dataset_fingerprint="fixture",
            development_dataset_fingerprint="fixture",
            validation_dataset_role=DatasetRole.VALIDATION.value if validation_role != "NONE" else None,
            validation_dataset_fingerprint=None,
        )
        STORE.save_run(run)
        st.session_state["active_optimization_id"] = optimization_id
        st.success(f"Completed {optimization_id}; all {len(values)} candidates retained.")
    active = st.session_state.get("active_optimization_id")
    if active:
        st.dataframe(_candidate_table(STORE.load_candidates(active), parameters), use_container_width=True, hide_index=True)


def _render_stability() -> None:
    optimization_id = st.session_state.get("active_optimization_id")
    runs = STORE.list_runs()
    if not optimization_id and runs:
        optimization_id = runs[0].optimization_id
    if not optimization_id:
        st.info("Run an optimization to inspect stability.")
        return
    candidates = STORE.load_candidates(optimization_id)
    if not candidates:
        st.info("This optimization has no completed candidates.")
        return
    selected_id = st.selectbox("Candidate neighborhood", [item.candidate_id for item in candidates])
    selected = next(item for item in candidates if item.candidate_id == selected_id)
    st.json({"candidate": asdict(selected), "stability": selected.stability})
    x_parameter, y_parameter = "entry_threshold", "exit_threshold"
    heatmap = pd.DataFrame(two_dimensional_heatmap(candidates, x_parameter, y_parameter, "profit_factor"))
    if not heatmap.empty:
        st.plotly_chart(px.density_heatmap(heatmap, x="x", y="y", z="value", text_auto=True, title="PF stability heatmap"), use_container_width=True)
    st.dataframe(_candidate_table(candidates, _fixture_space()), use_container_width=True, hide_index=True)


def _render_history() -> None:
    runs = STORE.list_runs()
    if not runs:
        st.info("No optimization runs stored yet.")
        return
    frame = pd.DataFrame([asdict(run) for run in runs])
    st.dataframe(frame, use_container_width=True, hide_index=True)
    selected = st.selectbox("Open optimization", frame.optimization_id.tolist())
    if st.button("Open Stored Optimization"):
        st.session_state["active_optimization_id"] = selected
        st.success(f"Loaded {selected} without rerunning candidates.")


def _wf_fixture_candidates(fold, parameters: list[SearchParameter]) -> list[CandidateResult]:
    """Deterministic per-fold surface: the training peak drifts with fold_number so
    walk-forward parameter drift/tie-break behavior is reproducible for screenshots and tests."""
    peak_x = 1 + (fold.fold_number % 3)
    peak_y = 2
    values = generate_grid(parameters)
    raw = []
    for combo in values:
        x, y = combo["entry_threshold"], combo["exit_threshold"]
        pf = 1.5 if (x, y) == (peak_x, peak_y) else 1.25 - abs(x - peak_x) * .08 - abs(y - peak_y) * .04
        raw.append(CandidateResult(
            candidate_id=candidate_id(fold.fold_id, combo), parameter_fingerprint=candidate_fingerprint(combo),
            parameters=combo, run_id=None, dataset_fingerprint="fixture", strategy_fingerprint="fixture",
            instrument_fingerprint="fixture", broker_fingerprint="fixture",
            total_trades=100 - abs(x - peak_x) * 4, trades_per_month=10.0, win_rate=52.0,
            profit_factor=pf, average_r=pf - 1.0, pnl=(pf - 1.0) * 1000,
            max_drawdown=4.0 + abs(x - peak_x) * 1.5, max_losing_streak=4,
        ))
    return [CandidateResult(**{**c.__dict__, "stability": stability_for(c, raw, parameters)}) for c in raw]


def _wf_fixture_validate(fold, parameters: dict, selection_parameters: list[SearchParameter]) -> CandidateResult:
    peak_x = 1 + (fold.fold_number % 3)
    x, y = parameters["entry_threshold"], parameters["exit_threshold"]
    pf = (1.5 if (x, y) == (peak_x, 2) else 1.15) * 0.85  # simulated OOS degradation, deterministic
    return CandidateResult(
        candidate_id=f"VAL-{fold.fold_id}", parameter_fingerprint=candidate_fingerprint(parameters),
        parameters=parameters, run_id=None, dataset_fingerprint="fixture", strategy_fingerprint="fixture",
        instrument_fingerprint="fixture", broker_fingerprint="fixture",
        total_trades=25, trades_per_month=8.0, win_rate=48.0, profit_factor=pf,
        average_r=pf - 1.0, pnl=(pf - 1.0) * 250, max_drawdown=5.5, max_losing_streak=3,
    )


def _fold_bar_timestamps(training_months: int, extra_months: int = 3) -> list[datetime]:
    """Deterministic daily-bar fixture spanning enough calendar months for the configured windows."""
    total_months = training_months + extra_months * 4 + 1
    start = datetime(2018, 1, 1, tzinfo=timezone.utc)
    bars = []
    current = start
    end_year = start.year + (start.month - 1 + total_months) // 12
    end_month = (start.month - 1 + total_months) % 12 + 1
    end = start.replace(year=end_year, month=end_month)
    while current < end:
        bars.append(current)
        current += timedelta(days=1)
    return bars


def _render_walk_forward_setup() -> None:
    st.markdown("### Walk-Forward Setup")
    registry = discover_builtin_strategies()
    descriptors = registry.all()
    labels = [f"{item.metadata.name} · {item.metadata.status.value}" for item in descriptors]
    selected_label = st.selectbox("Strategy", labels, key="wf_strategy")
    descriptor = descriptors[labels.index(selected_label)]
    frozen = descriptor.metadata.status is StrategyStatus.FROZEN
    st.caption(f"Strategy version {descriptor.metadata.version} · fingerprint {descriptor.metadata.strategy_fingerprint}")

    st.markdown("**Dataset**")
    st.caption("Historical data is partitioned internally into DEVELOPMENT/VALIDATION folds. "
               "Reserved FORWARD_VALIDATION/HOLDOUT data is never consumed here.")
    role = DatasetRole(st.selectbox("Dataset role", [DatasetRole.DEVELOPMENT.value], index=0, key="wf_role"))

    if frozen:
        st.error("WALK-FORWARD OPTIMIZATION DISABLED — FROZEN STRATEGY")

    mode = WalkForwardMode(st.selectbox("Mode", [WalkForwardMode.ROLLING.value, WalkForwardMode.ANCHORED.value], key="wf_mode"))
    col1, col2, col3 = st.columns(3)
    training_months = col1.number_input("Training months", min_value=1, value=24, step=1, key="wf_training_months")
    validation_months = col2.number_input("Validation months", min_value=1, value=3, step=1, key="wf_validation_months")
    step_months = col3.number_input("Step months", min_value=1, value=3, step=1, key="wf_step_months")
    col4, col5 = st.columns(2)
    embargo_bars = col4.number_input("Embargo bars", min_value=0, value=0, step=1, key="wf_embargo_bars")
    warmup_bars = col5.number_input("Warmup bars", min_value=0, value=0, step=1, key="wf_warmup_bars")

    st.markdown("**Optimizer configuration** (reuses the Phase 3B optimizer)")
    search_method = st.selectbox("Search method", ("Grid Search", "Random Search"), key="wf_search_method")
    seed = st.number_input("Random seed", value=42, step=1, key="wf_seed")
    safety = st.number_input("Safety limit", min_value=1, max_value=100000, value=1000, step=100, key="wf_safety")

    st.markdown("**Selection policy** (mechanical fold-selection, not a claim of universal optimality)")
    require_positive_avg_r = st.checkbox("Require positive Avg R", value=True, key="wf_require_avg_r")
    exclude_isolated = st.checkbox("Exclude isolated-peak candidates when a non-isolated alternative exists", value=True, key="wf_exclude_isolated")
    minimum_trades = st.number_input("Minimum trades", min_value=0, value=0, step=1, key="wf_min_trades")

    policy = SelectionPolicyConfig(
        minimum_trades=int(minimum_trades), require_positive_average_r=require_positive_avg_r,
        exclude_isolated_peak_if_alternative_exists=exclude_isolated,
    )
    config = WalkForwardConfig(
        mode=mode, training_months=int(training_months), validation_months=int(validation_months),
        step_months=int(step_months), embargo_bars=int(embargo_bars), warmup_bars=int(warmup_bars),
        minimum_training_bars=1, minimum_validation_bars=1, selection_policy=policy,
        search_method=search_method, search_seed=int(seed) if search_method == "Random Search" else None,
        safety_limit=int(safety),
    )

    bars = _fold_bar_timestamps(int(training_months))
    try:
        folds = generate_folds(config, bars[0], bars[-1])
    except WalkForwardBlocked as error:
        st.error(str(error))
        folds = []
    st.info(f"Generated fold count: {len(folds)}")

    if st.button("Start Walk-Forward", type="primary", disabled=frozen or not folds):
        try:
            guard_walk_forward(descriptor, role)
            guard_dataset_role(role)
        except WalkForwardBlocked as error:
            st.error(str(error))
            return
        parameters = _fixture_space()
        run, fold_results = run_walk_forward(
            descriptor=descriptor, config=config, bar_timestamps=bars, data_role=role,
            dataset_fingerprint="fixture-dataset", broker_fingerprint="fixture-broker",
            instrument_fingerprint="fixture-instrument", engine_version="phase3c-fixture",
            train_candidates_fn=lambda fold, cfg: _wf_fixture_candidates(fold, parameters),
            validate_fn=lambda fold, params: _wf_fixture_validate(fold, params, parameters),
            store=WF_STORE,
        )
        st.session_state["active_walk_forward_id"] = run.walk_forward_id
        st.success(f"Completed {run.walk_forward_id}: {len(fold_results)} folds.")

    active_id = st.session_state.get("active_walk_forward_id")
    if active_id:
        st.divider()
        _render_walk_forward_results(active_id)


def _render_walk_forward_results(walk_forward_id: str) -> None:
    run = WF_STORE.load_run(walk_forward_id)
    fold_rows = WF_STORE.load_folds(walk_forward_id)
    if not run or not fold_rows:
        st.info("No walk-forward results stored yet for this run.")
        return

    st.markdown(f"### Walk-Forward Results · {walk_forward_id}")

    st.markdown("#### Timeline")
    timeline_rows = []
    for row in fold_rows:
        timeline_rows.append({"Fold": row["fold_id"], "Segment": "Train", "Start": row["train_start"], "End": row["train_end"]})
        timeline_rows.append({"Fold": row["fold_id"], "Segment": "Validation", "Start": row["validation_start"], "End": row["validation_end"]})
    timeline = pd.DataFrame(timeline_rows)
    if not timeline.empty:
        fig = px.timeline(timeline, x_start="Start", x_end="End", y="Fold", color="Segment")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Fold Table")
    table_rows = []
    for row in fold_rows:
        training = row.get("training") or {}
        validation = row.get("validation") or {}
        degradation = row.get("degradation") or {}
        table_rows.append({
            "Fold": row["fold_number"], "Train Period": f"{row['train_start']} → {row['train_end']}",
            "Validation Period": f"{row['validation_start']} → {row['validation_end']}",
            "Selected Parameters": row.get("selected_parameters"),
            "Train PF": training.get("profit_factor"), "Train Avg R": training.get("average_r"),
            "Train DD": training.get("max_drawdown"), "OOS Trades": validation.get("total_trades"),
            "OOS PF": validation.get("profit_factor"), "OOS Avg R": validation.get("average_r"),
            "OOS DD": validation.get("max_drawdown"), "Status": row["status"],
            "Warnings": ", ".join(row.get("warnings") or []),
        })
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    fold_results = _fold_results_from_rows(fold_rows)

    st.markdown("#### Stitched OOS")
    fold_trades = {
        f.fold_id: [StitchedTrade(f.fold_id, f.validation_start + timedelta(days=1),
                                   (f.validation or {}).get("average_r"), (f.validation or {}).get("pnl"))]
        for f in fold_results if f.status == "SELECTED"
    }
    stitched = stitch_oos(fold_results, fold_trades)
    st.json({k: v for k, v in stitched.items() if k != "stitched_trades"})
    if stitched["cumulative_r_series"]:
        st.plotly_chart(go.Figure(go.Scatter(y=stitched["cumulative_r_series"], mode="lines+markers", name="Cumulative R")).update_layout(title="Cumulative R (NON_COMPOUNDED_FOLD_STITCH)"), use_container_width=True)
    fold_metric_rows = [{"Fold": row["fold_number"], "PF": (row.get("validation") or {}).get("profit_factor"),
                          "Avg R": (row.get("validation") or {}).get("average_r")} for row in fold_rows]
    metric_frame = pd.DataFrame(fold_metric_rows)
    if not metric_frame.empty:
        st.plotly_chart(px.bar(metric_frame, x="Fold", y="Avg R", title="Fold-by-fold OOS Avg R"), use_container_width=True)
        st.plotly_chart(px.bar(metric_frame, x="Fold", y="PF", title="Fold-by-fold OOS PF"), use_container_width=True)

    st.markdown("#### Parameter Drift")
    drift = parameter_drift(fold_results)
    st.json(drift)

    st.markdown("#### Degradation (Train vs OOS)")
    summary = walk_forward_summary(fold_results)
    st.json(summary)

    st.markdown("#### Walk-Forward Integrity Panel")
    st.json({
        "dataset_fingerprint": run.dataset_fingerprint, "strategy_fingerprint": run.strategy_fingerprint,
        "broker_fingerprint": run.broker_fingerprint, "instrument_fingerprint": run.instrument_fingerprint,
        "number_of_folds": run.fold_count,
        "leakage_violations": [v for row in fold_rows for v in (row.get("temporal_integrity") or {}).get("leakage_violations", [])],
        "embargo_bars": run.config.get("embargo_bars"), "warmup_bars": run.config.get("warmup_bars"),
        "reserved_forward_holdout_used": "NO",
        "resume_compatibility": "Matches stored fingerprints/config" if run else "UNKNOWN",
        "selection_policy": run.config.get("selection_policy"),
        "equity_stitch_semantics": stitched["equity_semantics"],
    })


def _fold_results_from_rows(fold_rows: list[dict]):
    from research.walk_forward import FoldResult, TemporalIntegrityReport

    def parse_dt(value):
        return datetime.fromisoformat(value) if isinstance(value, str) else value

    results = []
    for row in fold_rows:
        integrity_raw = row.get("temporal_integrity")
        integrity = None
        if integrity_raw:
            integrity = TemporalIntegrityReport(
                fold_id=integrity_raw["fold_id"], temporal_integrity_passed=integrity_raw["temporal_integrity_passed"],
                training_end=parse_dt(integrity_raw.get("training_end")), validation_start=parse_dt(integrity_raw.get("validation_start")),
                embargo_bars=integrity_raw["embargo_bars"], warmup_bars=integrity_raw["warmup_bars"],
                warmup_start=parse_dt(integrity_raw.get("warmup_start")), warmup_end=parse_dt(integrity_raw.get("warmup_end")),
                leakage_violations=tuple(integrity_raw.get("leakage_violations") or ()),
            )
        results.append(FoldResult(
            fold_id=row["fold_id"], fold_number=row["fold_number"], train_start=parse_dt(row["train_start"]),
            train_end=parse_dt(row["train_end"]), validation_start=parse_dt(row["validation_start"]),
            validation_end=parse_dt(row["validation_end"]), status=row["status"],
            selected_candidate_id=row.get("selected_candidate_id"), selected_parameters=row.get("selected_parameters"),
            fingerprints=None, selection_rationale=None, training=row.get("training"), validation=row.get("validation"),
            degradation=row.get("degradation"), temporal_integrity=integrity, warnings=tuple(row.get("warnings") or ()),
        ))
    return results


def _render_walk_forward_history() -> None:
    runs = WF_STORE.list_runs()
    if not runs:
        st.info("No walk-forward runs stored yet.")
        return
    frame = pd.DataFrame([asdict(run) for run in runs])
    st.dataframe(frame, use_container_width=True, hide_index=True)
    selected = st.selectbox("Open walk-forward run", frame.walk_forward_id.tolist())
    if st.button("Open Stored Walk-Forward Run"):
        st.session_state["active_walk_forward_id"] = selected
        st.success(f"Loaded {selected} without rerunning folds.")
        _render_walk_forward_results(selected)
