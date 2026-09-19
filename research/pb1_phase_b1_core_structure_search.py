"""PB1 Phase B.1 — DEVELOPMENT-only core structure stability search.

Deterministic grid search over PB1's four core-structure parameters
(impulse minimum range, pullback retracement bounds, confirmation minimum
body) using the Phase 3B optimizer (research/optimizer.py). DEVELOPMENT
(2021-01-01 .. 2023-12-31) only — this module never reads or dates a
VALIDATION/FORWARD_VALIDATION request; ``validation_dataset_fingerprint``
is always ``None`` here (see ``guard_validation_dataset(None)`` in ``run``).

All other PB1Parameters fields stay at their Phase A.1 defaults: an override
dict only ever carries the four searched keys, so every unlisted field is
resolved by ``strategies.universal_catalog._parameterized`` from
``PB1Parameters()`` unchanged.

This module only orchestrates existing, unmodified infrastructure:
run_universal_backtest for execution, research.optimizer for the grid/
fingerprint/stability/persistence layer. No strategy or engine logic lives
here.
"""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

import pandas as pd

from core.adapters.audited_engine import run_universal_backtest
from core.config import BacktestConfig, DatasetRole
from research.optimizer import (
    CandidateResult, OptimizationRun, OptimizationStore, SearchParameter,
    apply_analysis_filters, candidate_fingerprint, candidate_from_result,
    candidate_id as build_candidate_id, generate_grid, guard_optimization,
    guard_validation_dataset, run_candidates, stability_for,
    validate_resume_compatibility,
)
from strategies.base_strategy import effective_parameter_payload
from strategies.registry import discover_builtin_strategies

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "btcusd_15m.csv"
STORE_PATH = ROOT / "experiments" / "optimizations.sqlite3"
RICH_METRICS_PATH = ROOT / "reports" / "pb1" / "phase_b1_candidate_metrics.json"

STRATEGY_ID = "BTC_PB1_SHALLOW_PULLBACK_V1"
OPTIMIZATION_ID = "PB1-PHASE-B1-CORE-STRUCTURE-V1"
DEVELOPMENT_START = pd.Timestamp("2021-01-01", tz="UTC")
DEVELOPMENT_END = pd.Timestamp("2023-12-31 23:45", tz="UTC")

# Exact Phase A.1 baseline reproduction gate.
BASELINE_TRADES = 810
BASELINE_PF = 0.9267538477539468
BASELINE_AVERAGE_R = -0.05081890315227994
BASELINE_TOTAL_R = -41.163311553346745
BASELINE_PARAMETER_FINGERPRINT = "9dd5e8642bcfbf48b1950552be1f7bb7415f77994358f4e3f30f86c896aa8ac8"

# Section 2: search only these four core-structure parameters.
SEARCH_PARAMETERS = (
    SearchParameter("impulse_minimum_range_atr", "float", 1.5,
                    choices=(1.20, 1.50, 1.80, 2.10)),
    SearchParameter("pullback_minimum_retracement_percent", "float", 0.20,
                    choices=(0.15, 0.20, 0.25)),
    SearchParameter("pullback_maximum_retracement_percent", "float", 0.45,
                    choices=(0.35, 0.45, 0.55)),
    SearchParameter("confirmation_minimum_body_percent", "float", 0.50,
                    choices=(0.40, 0.50, 0.60, 0.70)),
)

# Section 5: initial research viability thresholds (filters, not acceptance criteria).
VIABILITY = dict(minimum_trades=300, minimum_trades_per_month=8.0,
                 maximum_dd=10.0, minimum_pf=1.00, minimum_average_r=0.0)


def _config(strategy_parameters: dict[str, Any] | None = None) -> BacktestConfig:
    return BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD", strategy_id=STRATEGY_ID,
        timeframe="15m", higher_timeframes=("1h",),
        start_date=DEVELOPMENT_START, end_date=DEVELOPMENT_END,
        dataset_role=DatasetRole.DEVELOPMENT,
        strategy_parameters=strategy_parameters or {},
    )


def verify_baseline(ledger_path: Path) -> Any:
    """Section 1: rerun the exact Phase A.1 baseline on DEVELOPMENT only."""
    result = run_universal_backtest(DATA, _config(), ledger_path=ledger_path)
    if result.total_trades != BASELINE_TRADES:
        raise ValueError(f"BASELINE MISMATCH: total_trades={result.total_trades}, expected {BASELINE_TRADES}.")
    if abs(result.profit_factor - BASELINE_PF) > 1e-9:
        raise ValueError(f"BASELINE MISMATCH: profit_factor={result.profit_factor}, expected {BASELINE_PF}.")
    if abs(result.average_r - BASELINE_AVERAGE_R) > 1e-9:
        raise ValueError(f"BASELINE MISMATCH: average_r={result.average_r}, expected {BASELINE_AVERAGE_R}.")
    if result.parameter_fingerprint != BASELINE_PARAMETER_FINGERPRINT:
        raise ValueError(
            f"BASELINE MISMATCH: parameter_fingerprint={result.parameter_fingerprint}, "
            f"expected {BASELINE_PARAMETER_FINGERPRINT}."
        )
    return result


def build_grid() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Section 2: 4x3x3x4 raw grid, enforcing pullback_min < pullback_max.

    Returns (raw_grid, valid_grid) — the retracement-ordering constraint happens
    to remove nothing here since {0.15,0.20,0.25} and {0.35,0.45,0.55} never
    overlap, but the check is applied explicitly rather than assumed.
    """
    raw = generate_grid(SEARCH_PARAMETERS, safety_limit=1_000)
    valid = [
        combo for combo in raw
        if combo["pullback_minimum_retracement_percent"] < combo["pullback_maximum_retracement_percent"]
    ]
    return raw, valid


def _rich_metrics(result: Any) -> dict[str, Any]:
    """Section 4 + 9 + 10: everything CandidateResult does not carry (yearly,
    direction trade counts/avg R, total R, entries/open-at-end reconciliation)."""
    total_r = sum(row["r_multiple"] for row in result.trade_log)
    return {
        "closed_trades": result.total_trades,
        "trades_per_month": result.trades_per_month,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor,
        "average_r": result.average_r,
        "total_r": total_r,
        "pnl": result.pnl,
        "max_drawdown_percent": result.max_drawdown_percent,
        "max_losing_streak": result.max_losing_streak,
        "long_statistics": asdict(result.long_statistics),
        "short_statistics": asdict(result.short_statistics),
        "yearly_statistics": result.yearly_statistics,
        "total_entries": result.total_entries,
        "open_positions_at_end": result.open_positions_at_end,
        "dataset_role": result.dataset_role,
        "period": result.period,
    }


def run(*, ledger_path: Path, store_path: Path = STORE_PATH,
        rich_metrics_path: Path = RICH_METRICS_PATH) -> dict[str, Any]:
    descriptor = discover_builtin_strategies().get(STRATEGY_ID)
    guard_optimization(descriptor, DatasetRole.DEVELOPMENT)
    # Proves this run never carries a validation/forward dataset (section 12).
    guard_validation_dataset(None)

    baseline = verify_baseline(ledger_path)

    raw_grid, grid = build_grid()
    store = OptimizationStore(store_path)

    rich_metrics_path.parent.mkdir(parents=True, exist_ok=True)
    rich_records: dict[str, dict[str, Any]] = (
        json.loads(rich_metrics_path.read_text()) if rich_metrics_path.exists() else {}
    )

    def execute(combo: dict[str, Any]) -> CandidateResult:
        try:
            result = run_universal_backtest(DATA, _config(combo), ledger_path=ledger_path)
        except Exception as exc:  # noqa: BLE001 - one bad candidate must not abort the grid
            payload = effective_parameter_payload(descriptor, combo)
            return CandidateResult(
                candidate_id=build_candidate_id(OPTIMIZATION_ID, combo),
                parameter_fingerprint=candidate_fingerprint(payload), parameters=dict(combo),
                run_id=None, dataset_fingerprint=baseline.dataset_fingerprint,
                strategy_fingerprint=baseline.strategy_fingerprint,
                instrument_fingerprint=baseline.instrument_fingerprint,
                broker_fingerprint=baseline.broker_fingerprint,
                status="FAILED", rejection_reason=str(exc),
            )
        candidate = candidate_from_result(
            OPTIMIZATION_ID, combo, result, dataset_fingerprint=result.dataset_fingerprint,
            strategy_fingerprint=result.strategy_fingerprint,
            instrument_fingerprint=result.instrument_fingerprint,
            broker_fingerprint=result.broker_fingerprint,
        )
        rich_records[candidate.candidate_id] = {
            "parameters": combo, "parameter_fingerprint": candidate.parameter_fingerprint,
            **_rich_metrics(result),
        }
        rich_metrics_path.write_text(json.dumps(rich_records, indent=2, sort_keys=True, default=str))
        return candidate

    run_record = OptimizationRun(
        optimization_id=OPTIMIZATION_ID, created_at=pd.Timestamp.now(tz="UTC").isoformat(),
        strategy_id=STRATEGY_ID, strategy_version=descriptor.metadata.version,
        search_method="GRID", search_seed=None,
        parameter_space={p.name: list(p.values()) for p in SEARCH_PARAMETERS},
        candidate_count=len(grid), dataset_role=DatasetRole.DEVELOPMENT.value,
        dataset_fingerprint=baseline.dataset_fingerprint,
        instrument_fingerprint=baseline.instrument_fingerprint,
        broker_fingerprint=baseline.broker_fingerprint, engine_version="phase3b",
        status="RUNNING", development_dataset_fingerprint=baseline.dataset_fingerprint,
        validation_dataset_role=None, validation_dataset_fingerprint=None,
    )
    existing_run = store.load_run(OPTIMIZATION_ID)
    if existing_run is not None:
        validate_resume_compatibility(existing_run, development_dataset_fingerprint=baseline.dataset_fingerprint,
                                      validation_dataset_fingerprint=None)
    store.save_run(run_record)

    candidates = run_candidates(grid, OPTIMIZATION_ID, execute, store, workers=1)
    store.save_run(OptimizationRun(**{**asdict(run_record), "status": "COMPLETED"}))

    successful = [c for c in candidates if c.status != "FAILED"]
    failed = [c for c in candidates if c.status == "FAILED"]
    unique_fingerprints = {c.parameter_fingerprint for c in candidates}
    stability = {
        c.candidate_id: stability_for(c, successful, SEARCH_PARAMETERS)
        for c in successful
    }
    filtered = apply_analysis_filters(successful, **VIABILITY)
    viable = [c for c in filtered if c.status != "FILTERED"]

    return {
        "baseline": baseline, "raw_grid": raw_grid, "grid": grid, "candidates": candidates,
        "successful": successful, "failed": failed,
        "rich_records": rich_records, "stability": stability,
        "filtered": filtered, "viable": viable,
        "unique_fingerprints": unique_fingerprints, "run": run_record,
    }


if __name__ == "__main__":
    import tempfile
    # A scratch ledger outside the repo: run_universal_backtest's per-run
    # ExperimentLedger.finish_run writes the full trade log/diagnostics for
    # every candidate (an append-only table), which grows fast across a
    # 144-candidate grid — never point this at the tracked experiments.sqlite3.
    scratch_ledger = Path(tempfile.gettempdir()) / "pb1_phase_b1_scratch_ledger.sqlite3"
    outcome = run(ledger_path=scratch_ledger)
    print(f"raw={len(outcome['raw_grid'])} generated={len(outcome['grid'])} "
          f"unique={len(outcome['unique_fingerprints'])} successful={len(outcome['successful'])} "
          f"failed={len(outcome['failed'])} viable={len(outcome['viable'])}")
