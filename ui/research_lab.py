from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import uuid
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from core.config import DatasetRole
from research.optimizer import (
    CandidateResult, OptimizationRun, OptimizationStore, SearchParameter,
    StabilityConfig, candidate_fingerprint, candidate_id, generate_grid,
    guard_optimization, stability_for, two_dimensional_heatmap,
)
from strategies.base_strategy import StrategyStatus
from strategies.registry import discover_builtin_strategies

ROOT = Path(__file__).resolve().parents[1]
STORE = OptimizationStore(ROOT / "experiments" / "optimizations.sqlite3")


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
    tabs = st.tabs(["Optimizer", "Stability", "Optimization History"])
    with tabs[0]:
        _render_optimizer()
    with tabs[1]:
        _render_stability()
    with tabs[2]:
        _render_history()


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
