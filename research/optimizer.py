from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import itertools
import json
from pathlib import Path
import random
import sqlite3
from statistics import median, pstdev
from typing import Any, Callable, Iterable, Mapping

from core.config import DatasetRole
from strategies.base_strategy import StrategyDescriptor, StrategyStatus, parameter_fingerprint

DEFAULT_SAFETY_LIMIT = 10_000


@dataclass(frozen=True)
class SearchParameter:
    name: str
    parameter_type: str
    default: Any
    minimum: float | int | None = None
    maximum: float | int | None = None
    step: float | int | None = None
    choices: tuple[Any, ...] = ()
    tunable: bool = True
    locked: bool = False
    display_name: str | None = None
    description: str = ""
    group: str = "Strategy Inputs"

    def values(self) -> tuple[Any, ...]:
        if self.locked or not self.tunable:
            return (self.default,)
        if self.parameter_type == "boolean":
            return (False, True)
        if self.choices:
            return tuple(self.choices)
        if self.minimum is None or self.maximum is None or self.step is None or self.step <= 0:
            raise ValueError(f"Tunable parameter {self.name} needs minimum, maximum, and step.")
        values = []
        current = self.minimum
        while current <= self.maximum + self.step / 100000:
            values.append(int(current) if self.parameter_type == "integer" else round(float(current), 12))
            current += self.step
        return tuple(values)


@dataclass(frozen=True)
class CandidateResult:
    candidate_id: str
    parameter_fingerprint: str
    parameters: dict[str, Any]
    run_id: str | None
    dataset_fingerprint: str
    strategy_fingerprint: str
    instrument_fingerprint: str
    broker_fingerprint: str
    total_trades: int | None = None
    trades_per_month: float | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    average_r: float | None = None
    pnl: float | None = None
    max_drawdown: float | None = None
    max_drawdown_duration: float | None = None
    max_losing_streak: int | None = None
    long_pf: float | None = None
    short_pf: float | None = None
    status: str = "COMPLETED"
    rejection_reason: str | None = None
    validation: dict[str, Any] | None = None
    stability: dict[str, Any] | None = None


@dataclass(frozen=True)
class StabilityConfig:
    neighbor_distance: int = 1
    profitable_threshold: float = 0.0
    positive_average_r_threshold: float = 0.0
    broad_plateau_neighbor_percent: float = 75.0
    moderate_neighbor_percent: float = 50.0
    fragile_neighbor_percent: float = 25.0
    weights: tuple[float, float, float] = (0.4, 0.4, 0.2)


@dataclass(frozen=True)
class OptimizationRun:
    optimization_id: str
    created_at: str
    strategy_id: str
    strategy_version: str
    search_method: str
    search_seed: int | None
    parameter_space: dict[str, list[Any]]
    candidate_count: int
    dataset_role: str
    dataset_fingerprint: str
    instrument_fingerprint: str
    broker_fingerprint: str
    engine_version: str
    status: str
    runtime_seconds: float | None = None


def search_parameters(descriptor: StrategyDescriptor) -> tuple[SearchParameter, ...]:
    return tuple(SearchParameter(
        name=parameter.name, parameter_type=parameter.parameter_type.value,
        default=parameter.default, minimum=parameter.minimum, maximum=parameter.maximum,
        step=parameter.step, choices=parameter.choices, tunable=parameter.optimization_allowed,
        locked=parameter.frozen, display_name=parameter.name.replace("_", " ").title(),
        description=parameter.description,
    ) for parameter in descriptor.parameters)


def guard_optimization(descriptor: StrategyDescriptor, role: DatasetRole) -> None:
    if descriptor.metadata.status is StrategyStatus.FROZEN:
        raise ValueError("OPTIMIZATION DISABLED - FROZEN STRATEGY")
    if role in {DatasetRole.FORWARD_VALIDATION, DatasetRole.HOLDOUT}:
        raise ValueError(f"OPTIMIZATION BLOCKED: {role.value} data is reserved for evaluation, not search.")
    if role not in {DatasetRole.DEVELOPMENT, DatasetRole.VALIDATION}:
        raise ValueError(f"OPTIMIZATION BLOCKED: unsupported dataset role {role.value}.")


def generate_grid(parameters: Iterable[SearchParameter], *, safety_limit: int = DEFAULT_SAFETY_LIMIT) -> list[dict[str, Any]]:
    parameters = tuple(parameters)
    names = [parameter.name for parameter in parameters]
    value_sets = [parameter.values() for parameter in parameters]
    count = 1
    for values in value_sets:
        count *= len(values)
    if count > safety_limit:
        raise ValueError(f"OPTIMIZATION BLOCKED: {count} combinations exceeds safety limit {safety_limit}.")
    return [dict(zip(names, values)) for values in itertools.product(*value_sets)]


def generate_random(parameters: Iterable[SearchParameter], count: int, seed: int,
                    *, safety_limit: int = DEFAULT_SAFETY_LIMIT) -> list[dict[str, Any]]:
    if count > safety_limit:
        raise ValueError(f"OPTIMIZATION BLOCKED: {count} candidates exceeds safety limit {safety_limit}.")
    values = generate_grid(parameters, safety_limit=max(safety_limit, count))
    randomizer = random.Random(seed)
    randomizer.shuffle(values)
    return values[:min(count, len(values))]


def candidate_fingerprint(parameters: Mapping[str, Any]) -> str:
    return parameter_fingerprint(parameters)


def candidate_id(optimization_id: str, parameters: Mapping[str, Any]) -> str:
    return f"{optimization_id}-{candidate_fingerprint(parameters)[:12]}"


def candidate_from_result(optimization_id: str, parameters: Mapping[str, Any], result: Any,
                          *, dataset_fingerprint: str, strategy_fingerprint: str,
                          instrument_fingerprint: str, broker_fingerprint: str) -> CandidateResult:
    return CandidateResult(
        candidate_id=candidate_id(optimization_id, parameters),
        parameter_fingerprint=candidate_fingerprint(parameters), parameters=dict(parameters),
        run_id=result.run_id, dataset_fingerprint=dataset_fingerprint,
        strategy_fingerprint=strategy_fingerprint, instrument_fingerprint=instrument_fingerprint,
        broker_fingerprint=broker_fingerprint, total_trades=result.total_trades,
        trades_per_month=result.trades_per_month, win_rate=result.win_rate,
        profit_factor=result.profit_factor, average_r=result.average_r, pnl=result.pnl,
        max_drawdown=result.max_drawdown_percent, max_losing_streak=result.max_losing_streak,
        long_pf=result.long_statistics.profit_factor, short_pf=result.short_statistics.profit_factor,
    )


def _metric(values: list[CandidateResult], name: str) -> list[float]:
    return [float(getattr(item, name)) for item in values if getattr(item, name) is not None]


def stability_for(candidate: CandidateResult, candidates: Iterable[CandidateResult],
                   parameters: Iterable[SearchParameter], config: StabilityConfig = StabilityConfig()) -> dict[str, Any]:
    peers = list(candidates)
    numeric = {parameter.name for parameter in parameters if parameter.parameter_type in {"integer", "float"}}
    neighbors = []
    for peer in peers:
        if peer.candidate_id == candidate.candidate_id:
            continue
        distance = sum(
            1 for name in numeric
            if peer.parameters.get(name) != candidate.parameters.get(name)
        )
        if distance <= config.neighbor_distance:
            neighbors.append(peer)
    pf = _metric(neighbors, "profit_factor")
    avg_r = _metric(neighbors, "average_r")
    dd = _metric(neighbors, "max_drawdown")
    profitable = _metric([item for item in neighbors if item.pnl is not None and item.pnl > config.profitable_threshold], "pnl")
    positive_r = _metric([item for item in neighbors if item.average_r is not None and item.average_r > config.positive_average_r_threshold], "average_r")
    neighbor_count = len(neighbors)
    profitable_percent = len(profitable) / neighbor_count * 100 if neighbor_count else None
    positive_percent = len(positive_r) / neighbor_count * 100 if neighbor_count else None
    pf_median = median(pf) if pf else None
    avg_median = median(avg_r) if avg_r else None
    dd_median = median(dd) if dd else None
    components = (profitable_percent or 0, positive_percent or 0, 100 - min(dd_median or 100, 100))
    score = sum(weight * value for weight, value in zip(config.weights, components)) if neighbor_count else None
    classification = "Insufficient Neighbors"
    if neighbor_count:
        level = min(profitable_percent or 0, positive_percent or 0)
        classification = "Broad Plateau" if level >= config.broad_plateau_neighbor_percent else (
            "Moderate Stability" if level >= config.moderate_neighbor_percent else "Fragile Region"
        )
    warnings = []
    if neighbor_count and candidate.profit_factor is not None and pf_median is not None and candidate.profit_factor > pf_median * 1.5:
        warnings.append("ISOLATED PEAK PATTERN")
    if any(candidate.parameters.get(parameter.name) in (parameter.values()[0], parameter.values()[-1])
           for parameter in parameters if parameter.parameter_type in {"integer", "float"}):
        warnings.append("BOUNDARY SENSITIVITY")
    if neighbor_count and pf and pstdev(pf) > max(abs(pf_median or 0) * .5, 0.25):
        warnings.append("FRAGILITY WARNING: UNSTABLE NEIGHBORING RESULTS")
    return {
        "neighbor_count": neighbor_count, "profitable_neighbor_percent": profitable_percent,
        "positive_average_r_neighbor_percent": positive_percent, "median_neighbor_pf": pf_median,
        "median_neighbor_average_r": avg_median, "median_neighbor_dd": dd_median,
        "pf_dispersion": pstdev(pf) if len(pf) > 1 else 0.0,
        "average_r_dispersion": pstdev(avg_r) if len(avg_r) > 1 else 0.0,
        "dd_dispersion": pstdev(dd) if len(dd) > 1 else 0.0,
        "stability_score": score, "classification": classification, "warnings": warnings,
        "formula": "0.4*profitable_neighbor_pct + 0.4*positive_avg_r_neighbor_pct + 0.2*(100-min(median_dd,100))",
    }


def validation_comparison(development: CandidateResult, validation: CandidateResult) -> dict[str, Any]:
    def degradation(left, right):
        if left in (None, 0) or right is None:
            return None
        return (left - right) / abs(left) * 100
    return {
        "development_pf": development.profit_factor, "validation_pf": validation.profit_factor,
        "development_average_r": development.average_r, "validation_average_r": validation.average_r,
        "development_dd": development.max_drawdown, "validation_dd": validation.max_drawdown,
        "development_trades": development.total_trades, "validation_trades": validation.total_trades,
        "pf_degradation_percent": degradation(development.profit_factor, validation.profit_factor),
        "average_r_degradation_percent": degradation(development.average_r, validation.average_r),
        "trade_frequency_change_percent": degradation(development.total_trades, validation.total_trades),
        "dd_change_percent": degradation(development.max_drawdown, validation.max_drawdown),
    }


def one_dimensional_analysis(candidates: Iterable[CandidateResult], parameter: str,
                             metric: str = "profit_factor") -> list[dict[str, Any]]:
    return [
        {"parameter_value": candidate.parameters.get(parameter), "metric": getattr(candidate, metric),
         "candidate_id": candidate.candidate_id, "status": candidate.status}
        for candidate in candidates
    ]


def two_dimensional_heatmap(candidates: Iterable[CandidateResult], x_parameter: str,
                            y_parameter: str, metric: str = "profit_factor") -> list[dict[str, Any]]:
    return [{"x": candidate.parameters.get(x_parameter), "y": candidate.parameters.get(y_parameter),
             "value": getattr(candidate, metric), "candidate_id": candidate.candidate_id}
            for candidate in candidates]


class OptimizationStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript("""
            CREATE TABLE IF NOT EXISTS optimization_runs (
                optimization_id TEXT PRIMARY KEY, metadata_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS optimization_candidates (
                optimization_id TEXT NOT NULL, candidate_id TEXT NOT NULL,
                candidate_json TEXT NOT NULL, PRIMARY KEY (optimization_id, candidate_id)
            );
            """)

    def save_run(self, run: OptimizationRun) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute("INSERT OR REPLACE INTO optimization_runs VALUES (?,?)",
                               (run.optimization_id, json.dumps(asdict(run), sort_keys=True, default=str)))

    def save_candidate(self, optimization_id: str, candidate: CandidateResult) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute("INSERT OR REPLACE INTO optimization_candidates VALUES (?,?,?)",
                               (optimization_id, candidate.candidate_id, json.dumps(asdict(candidate), sort_keys=True, default=str)))

    def load_run(self, optimization_id: str) -> OptimizationRun | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute("SELECT metadata_json FROM optimization_runs WHERE optimization_id=?", (optimization_id,)).fetchone()
        return OptimizationRun(**json.loads(row[0])) if row else None

    def load_candidates(self, optimization_id: str) -> list[CandidateResult]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute("SELECT candidate_json FROM optimization_candidates WHERE optimization_id=?", (optimization_id,)).fetchall()
        return [CandidateResult(**json.loads(row[0])) for row in rows]

    def list_runs(self) -> list[OptimizationRun]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute("SELECT metadata_json FROM optimization_runs ORDER BY optimization_id DESC").fetchall()
        return [OptimizationRun(**json.loads(row[0])) for row in rows]


def run_candidates(parameters: list[dict[str, Any]], optimization_id: str,
                   execute: Callable[[dict[str, Any]], CandidateResult], store: OptimizationStore,
                   *, workers: int = 1) -> list[CandidateResult]:
    if workers < 1:
        raise ValueError("workers must be >= 1")
    # Deliberately serialized in Phase 3B: deterministic execution and SQLite writes.
    results = []
    for values in parameters:
        fingerprint = candidate_fingerprint(values)
        existing = next((item for item in store.load_candidates(optimization_id)
                         if item.parameter_fingerprint == fingerprint), None)
        result = existing or execute(values)
        store.save_candidate(optimization_id, result)
        results.append(result)
    return results


def apply_analysis_filters(candidates: Iterable[CandidateResult], *, minimum_trades: int = 0,
                           minimum_trades_per_month: float | None = None,
                           maximum_dd: float | None = None, minimum_pf: float | None = None,
                           minimum_average_r: float | None = None) -> list[CandidateResult]:
    output = []
    for candidate in candidates:
        reasons = []
        if candidate.total_trades is not None and candidate.total_trades < minimum_trades:
            reasons.append(f"trades<{minimum_trades}")
        if minimum_trades_per_month is not None and (candidate.trades_per_month or 0) < minimum_trades_per_month:
            reasons.append(f"trades_per_month<{minimum_trades_per_month}")
        if maximum_dd is not None and (candidate.max_drawdown or float("inf")) > maximum_dd:
            reasons.append(f"max_dd>{maximum_dd}")
        if minimum_pf is not None and (candidate.profit_factor is None or candidate.profit_factor < minimum_pf):
            reasons.append(f"pf<{minimum_pf}")
        if minimum_average_r is not None and (candidate.average_r is None or candidate.average_r < minimum_average_r):
            reasons.append(f"average_r<{minimum_average_r}")
        output.append(CandidateResult(**{**asdict(candidate), "status": "FILTERED" if reasons else candidate.status,
                                         "rejection_reason": "; ".join(reasons) or candidate.rejection_reason}))
    return output
