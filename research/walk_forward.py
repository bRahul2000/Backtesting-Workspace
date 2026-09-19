"""Phase 3C generic walk-forward analysis framework.

Reuses the Phase 3B optimizer/stability primitives (research/optimizer.py) for
candidate generation, stability classification, and result persistence style.
This module adds nothing that duplicates that optimizer; it only adds window
generation, temporal-integrity guarding, deterministic fold-selection policy,
freeze/validate orchestration, drift/stitching/summary reporting, and
persistence for walk-forward runs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import sqlite3
from statistics import median
from typing import Any, Callable, Mapping, Sequence
import uuid

from core.config import DatasetRole
from research.optimizer import CandidateResult, apply_analysis_filters
from strategies.base_strategy import StrategyDescriptor, StrategyStatus

RESERVED_DATASET_ROLES = (DatasetRole.FORWARD_VALIDATION, DatasetRole.HOLDOUT)

CLASSIFICATION_ORDER: dict[str, int] = {
    "Broad Plateau": 0,
    "Moderate Stability": 1,
    "Fragile Region": 2,
    "Insufficient Neighbors": 3,
}


class WalkForwardBlocked(ValueError):
    """Raised whenever a walk-forward safety invariant is violated. Never caught silently."""


class WalkForwardMode(str, Enum):
    ROLLING = "ROLLING"
    ANCHORED = "ANCHORED"


# ---------------------------------------------------------------------------
# Section 1: Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SelectionPolicyConfig:
    minimum_trades: int = 0
    minimum_trades_per_month: float | None = None
    maximum_dd: float | None = None
    minimum_pf: float | None = None
    require_positive_average_r: bool = True
    exclude_isolated_peak_if_alternative_exists: bool = True

    def __post_init__(self) -> None:
        if self.minimum_trades < 0:
            raise ValueError("minimum_trades must be >= 0.")


@dataclass(frozen=True)
class WalkForwardConfig:
    mode: WalkForwardMode = WalkForwardMode.ROLLING
    training_months: int = 24
    validation_months: int = 3
    step_months: int = 3
    embargo_bars: int = 0
    warmup_bars: int = 0
    minimum_training_bars: int = 1
    minimum_validation_bars: int = 1
    selection_policy: SelectionPolicyConfig = field(default_factory=SelectionPolicyConfig)
    search_method: str = "Grid Search"
    search_seed: int | None = 42
    safety_limit: int = 10_000

    def __post_init__(self) -> None:
        if self.training_months <= 0 or self.validation_months <= 0 or self.step_months <= 0:
            raise ValueError("training_months, validation_months, and step_months must be positive.")
        if self.embargo_bars < 0 or self.warmup_bars < 0:
            raise ValueError("embargo_bars and warmup_bars must be >= 0.")
        if self.minimum_training_bars < 0 or self.minimum_validation_bars < 0:
            raise ValueError("minimum bar counts must be >= 0.")

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["mode"] = self.mode.value
        return payload


# ---------------------------------------------------------------------------
# Section 2: Window generator
# ---------------------------------------------------------------------------


def _require_tz_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware.")


def _add_months(moment: datetime, months: int) -> datetime:
    month_index = moment.month - 1 + months
    year = moment.year + month_index // 12
    month = month_index % 12 + 1
    return moment.replace(year=year, month=month)


@dataclass(frozen=True)
class Fold:
    fold_id: str
    fold_number: int
    mode: str
    train_start: datetime
    train_end: datetime  # exclusive
    validation_start: datetime  # inclusive, == train_end
    validation_end: datetime  # exclusive


def generate_folds(config: WalkForwardConfig, data_start: datetime, data_end: datetime) -> list[Fold]:
    _require_tz_aware(data_start, "data_start")
    _require_tz_aware(data_end, "data_end")
    if data_start >= data_end:
        raise WalkForwardBlocked("WALK-FORWARD BLOCKED: data_start must precede data_end.")

    folds: list[Fold] = []
    train_start = data_start
    train_end = _add_months(train_start, config.training_months)
    validation_start = train_end
    validation_end = _add_months(validation_start, config.validation_months)
    fold_number = 1

    while validation_end <= data_end:
        if not (train_start < train_end <= validation_start < validation_end):
            raise WalkForwardBlocked(
                f"WALK-FORWARD BLOCKED: nonchronological or overlapping fold boundaries at fold {fold_number}."
            )
        fold = Fold(
            fold_id=f"FOLD-{fold_number:03d}-{train_start:%Y%m}-{validation_start:%Y%m}",
            fold_number=fold_number,
            mode=config.mode.value,
            train_start=train_start,
            train_end=train_end,
            validation_start=validation_start,
            validation_end=validation_end,
        )
        if folds and fold.train_start < folds[-1].train_start:
            raise WalkForwardBlocked("WALK-FORWARD BLOCKED: folds are not chronological.")
        folds.append(fold)

        next_train_end = _add_months(train_end, config.step_months)
        if config.mode is WalkForwardMode.ROLLING:
            train_start = _add_months(train_start, config.step_months)
        # ANCHORED keeps train_start fixed at the original anchor.
        train_end = next_train_end
        validation_start = train_end
        validation_end = _add_months(validation_start, config.validation_months)
        fold_number += 1

    return folds


def validate_fold_boundaries(fold: Fold) -> None:
    if not (fold.train_start < fold.train_end <= fold.validation_start < fold.validation_end):
        raise WalkForwardBlocked(f"WALK-FORWARD BLOCKED: invalid boundaries for {fold.fold_id}.")


# ---------------------------------------------------------------------------
# Section 3: Temporal integrity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FoldBars:
    fold_id: str
    training_timestamps: tuple[datetime, ...]
    warmup_timestamps: tuple[datetime, ...]
    validation_timestamps: tuple[datetime, ...]
    validation_trade_eligible_timestamps: tuple[datetime, ...]
    embargoed_timestamps: tuple[datetime, ...]


def build_fold_bars(
    fold: Fold,
    bar_timestamps: Sequence[datetime],
    *,
    embargo_bars: int,
    warmup_bars: int,
    minimum_training_bars: int,
    minimum_validation_bars: int,
) -> FoldBars:
    bars = sorted(bar_timestamps)
    training = tuple(t for t in bars if fold.train_start <= t < fold.train_end)
    validation = tuple(t for t in bars if fold.validation_start <= t < fold.validation_end)

    if len(training) < minimum_training_bars:
        raise WalkForwardBlocked(
            f"WALK-FORWARD BLOCKED: {fold.fold_id} has {len(training)} training bars, requires {minimum_training_bars}."
        )
    if len(validation) < minimum_validation_bars:
        raise WalkForwardBlocked(
            f"WALK-FORWARD BLOCKED: {fold.fold_id} has {len(validation)} validation bars, requires {minimum_validation_bars}."
        )

    warmup = training[-warmup_bars:] if warmup_bars > 0 else ()
    embargoed = validation[:embargo_bars]
    eligible = validation[embargo_bars:]
    if not eligible:
        raise WalkForwardBlocked(
            f"WALK-FORWARD BLOCKED: {fold.fold_id} has no validation bars remaining after embargo."
        )
    return FoldBars(fold.fold_id, training, warmup, validation, eligible, embargoed)


@dataclass(frozen=True)
class TemporalIntegrityReport:
    fold_id: str
    temporal_integrity_passed: bool
    training_end: datetime | None
    validation_start: datetime | None
    embargo_bars: int
    warmup_bars: int
    warmup_start: datetime | None
    warmup_end: datetime | None
    leakage_violations: tuple[str, ...]


def check_temporal_integrity(fold: Fold, fold_bars: FoldBars, *, embargo_bars: int, warmup_bars: int) -> TemporalIntegrityReport:
    violations: list[str] = []
    max_train = max(fold_bars.training_timestamps) if fold_bars.training_timestamps else None
    min_eligible = min(fold_bars.validation_trade_eligible_timestamps) if fold_bars.validation_trade_eligible_timestamps else None

    if max_train is None or min_eligible is None or not (max_train < min_eligible):
        violations.append("TRAINING DATA DOES NOT PRECEDE VALIDATION TRADE-ELIGIBLE DATA")
    if any(t >= fold.validation_start for t in fold_bars.warmup_timestamps):
        violations.append("WARMUP DATA OVERLAPS VALIDATION WINDOW")
    if set(fold_bars.warmup_timestamps) & set(fold_bars.validation_trade_eligible_timestamps):
        violations.append("WARMUP DATA LEAKED INTO VALIDATION TRADES")

    passed = not violations
    report = TemporalIntegrityReport(
        fold_id=fold.fold_id,
        temporal_integrity_passed=passed,
        training_end=max_train,
        validation_start=min_eligible,
        embargo_bars=embargo_bars,
        warmup_bars=warmup_bars,
        warmup_start=fold_bars.warmup_timestamps[0] if fold_bars.warmup_timestamps else None,
        warmup_end=fold_bars.warmup_timestamps[-1] if fold_bars.warmup_timestamps else None,
        leakage_violations=tuple(violations),
    )
    if not passed:
        raise WalkForwardBlocked(f"WALK-FORWARD BLOCKED: {fold.fold_id}: " + "; ".join(violations))
    return report


# ---------------------------------------------------------------------------
# Section 4/12: Guards
# ---------------------------------------------------------------------------


def guard_walk_forward(descriptor: StrategyDescriptor, role: DatasetRole) -> None:
    if descriptor.metadata.status is StrategyStatus.FROZEN:
        raise WalkForwardBlocked("WALK-FORWARD OPTIMIZATION DISABLED — FROZEN STRATEGY")
    if role is not DatasetRole.DEVELOPMENT:
        raise WalkForwardBlocked("WALK-FORWARD BLOCKED: training data must use DEVELOPMENT role.")


def guard_dataset_role(role: DatasetRole) -> None:
    if role in RESERVED_DATASET_ROLES:
        raise WalkForwardBlocked(
            "WALK-FORWARD BLOCKED: reserved FORWARD_VALIDATION/HOLDOUT data may not be consumed by walk-forward analysis."
        )


# ---------------------------------------------------------------------------
# Section 5: Deterministic parameter selection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SelectionRationale:
    fold_id: str
    policy: dict[str, Any]
    eligible_candidate_ids: tuple[str, ...]
    excluded_candidate_ids: tuple[str, ...]
    exclusion_reasons: dict[str, str]
    selected_candidate_id: str | None
    tie_break_order: tuple[str, ...]


def _desc(value: float | None) -> float:
    return -value if value is not None else float("inf")


def select_candidate(
    candidates: Sequence[CandidateResult],
    policy: SelectionPolicyConfig,
    *,
    fold_id: str,
) -> tuple[CandidateResult | None, SelectionRationale]:
    filtered = apply_analysis_filters(
        candidates,
        minimum_trades=policy.minimum_trades,
        minimum_trades_per_month=policy.minimum_trades_per_month,
        maximum_dd=policy.maximum_dd,
        minimum_pf=policy.minimum_pf,
        minimum_average_r=0.0 if policy.require_positive_average_r else None,
    )
    eligible = [c for c in filtered if c.status != "FILTERED"]
    exclusion_reasons = {c.candidate_id: c.rejection_reason for c in filtered if c.status == "FILTERED" and c.rejection_reason}

    if policy.exclude_isolated_peak_if_alternative_exists:
        non_isolated = [c for c in eligible if "ISOLATED PEAK PATTERN" not in ((c.stability or {}).get("warnings") or [])]
        if non_isolated:
            for candidate in eligible:
                if candidate not in non_isolated:
                    exclusion_reasons[candidate.candidate_id] = "ISOLATED PEAK PATTERN excluded (non-isolated alternative exists)"
            eligible = non_isolated

    def sort_key(candidate: CandidateResult) -> tuple:
        stability = candidate.stability or {}
        classification = stability.get("classification", "Insufficient Neighbors")
        return (
            CLASSIFICATION_ORDER.get(classification, len(CLASSIFICATION_ORDER)),
            _desc(stability.get("stability_score")),
            _desc(stability.get("median_neighbor_average_r")),
            _desc(candidate.average_r),
            _desc(candidate.profit_factor),
            candidate.max_drawdown if candidate.max_drawdown is not None else float("inf"),
            candidate.parameter_fingerprint,
        )

    ordered = sorted(eligible, key=sort_key)
    selected = ordered[0] if ordered else None
    rationale = SelectionRationale(
        fold_id=fold_id,
        policy=asdict(policy),
        eligible_candidate_ids=tuple(c.candidate_id for c in ordered),
        excluded_candidate_ids=tuple(exclusion_reasons.keys()),
        exclusion_reasons=exclusion_reasons,
        selected_candidate_id=selected.candidate_id if selected else None,
        tie_break_order=(
            "robustness_class", "stability_score_desc", "median_neighbor_average_r_desc",
            "candidate_average_r_desc", "pf_desc", "dd_asc", "parameter_fingerprint_asc",
        ),
    )
    return selected, rationale


# ---------------------------------------------------------------------------
# Section 6/7: Freeze, validate, fold results, zero-safe degradation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FoldFingerprints:
    parameter_fingerprint: str
    strategy_fingerprint: str
    dataset_fingerprint: str
    broker_fingerprint: str
    instrument_fingerprint: str


def _metrics_dict(candidate: CandidateResult) -> dict[str, Any]:
    return {
        "total_trades": candidate.total_trades,
        "trades_per_month": candidate.trades_per_month,
        "win_rate": candidate.win_rate,
        "profit_factor": candidate.profit_factor,
        "average_r": candidate.average_r,
        "pnl": candidate.pnl,
        "max_drawdown": candidate.max_drawdown,
        "max_losing_streak": candidate.max_losing_streak,
        "stability": candidate.stability,
    }


def _zero_safe_percent_change(train_value: float | None, validation_value: float | None) -> float | None:
    if train_value is None or validation_value is None:
        return None
    if train_value == 0:
        return None
    return (validation_value - train_value) / abs(train_value) * 100


def fold_degradation(training_metrics: Mapping[str, Any], validation_metrics: Mapping[str, Any]) -> dict[str, Any]:
    pf_undefined = training_metrics.get("profit_factor") is None or validation_metrics.get("profit_factor") is None
    return {
        "pf_degradation_percent": _zero_safe_percent_change(training_metrics.get("profit_factor"), validation_metrics.get("profit_factor")),
        "average_r_degradation_percent": _zero_safe_percent_change(training_metrics.get("average_r"), validation_metrics.get("average_r")),
        "trade_frequency_change_percent": _zero_safe_percent_change(training_metrics.get("total_trades"), validation_metrics.get("total_trades")),
        "dd_change_percent": _zero_safe_percent_change(training_metrics.get("max_drawdown"), validation_metrics.get("max_drawdown")),
        "pf_undefined": pf_undefined,
    }


@dataclass(frozen=True)
class FoldResult:
    fold_id: str
    fold_number: int
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    status: str  # SELECTED / NO_SELECTION
    selected_candidate_id: str | None
    selected_parameters: dict[str, Any] | None
    fingerprints: FoldFingerprints | None
    selection_rationale: SelectionRationale | None
    training: dict[str, Any] | None
    validation: dict[str, Any] | None
    degradation: dict[str, Any] | None
    temporal_integrity: TemporalIntegrityReport | None
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), default=str))


# ---------------------------------------------------------------------------
# Section 8: Parameter drift
# ---------------------------------------------------------------------------


def parameter_drift(fold_results: Sequence[FoldResult]) -> dict[str, Any]:
    selected = [f for f in fold_results if f.selected_parameters is not None]
    if len(selected) < 2:
        return {
            "changed_parameter_count": 0,
            "unchanged_parameter_count": len(selected[0].selected_parameters) if selected else 0,
            "values_by_fold": {f.fold_id: f.selected_parameters for f in selected},
            "per_parameter": {},
            "total_parameter_distance": 0.0,
        }

    names = sorted(set().union(*(f.selected_parameters.keys() for f in selected)))
    per_parameter: dict[str, Any] = {}
    total_distance = 0.0
    for name in names:
        values = [f.selected_parameters.get(name) for f in selected]
        changed = len(set(values)) > 1
        distances = []
        for left, right in zip(values, values[1:]):
            if isinstance(left, (int, float)) and isinstance(right, (int, float)) and not isinstance(left, bool) and not isinstance(right, bool):
                distances.append(abs(right - left))
            else:
                distances.append(0.0 if left == right else 1.0)
        per_parameter[name] = {
            "changed": changed,
            "values_by_fold": {f.fold_id: value for f, value in zip(selected, values)},
            "grid_step_distance_sum": sum(distances),
        }
        total_distance += sum(distances)

    changed_count = sum(1 for entry in per_parameter.values() if entry["changed"])
    return {
        "changed_parameter_count": changed_count,
        "unchanged_parameter_count": len(names) - changed_count,
        "values_by_fold": {f.fold_id: f.selected_parameters for f in selected},
        "per_parameter": per_parameter,
        "total_parameter_distance": total_distance,
    }


# ---------------------------------------------------------------------------
# Section 9: Stitched walk-forward OOS
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StitchedTrade:
    fold_id: str
    timestamp: datetime
    r_multiple: float | None
    pnl: float | None


def stitch_oos(fold_results: Sequence[FoldResult], fold_trades: Mapping[str, Sequence[StitchedTrade]]) -> dict[str, Any]:
    successful = [f for f in fold_results if f.status == "SELECTED"]
    trades: list[StitchedTrade] = []
    seen: set[tuple[str, datetime]] = set()
    for fold in successful:
        for trade in fold_trades.get(fold.fold_id, ()):
            key = (fold.fold_id, trade.timestamp)
            if key in seen:
                raise WalkForwardBlocked(f"WALK-FORWARD BLOCKED: duplicate OOS trade timestamp {key}.")
            seen.add(key)
            trades.append(trade)

    ordered_trades = sorted(trades, key=lambda t: (t.timestamp, t.fold_id))
    for earlier, later in zip(ordered_trades, ordered_trades[1:]):
        if later.timestamp < earlier.timestamp:
            raise WalkForwardBlocked("WALK-FORWARD BLOCKED: stitched OOS trades are not chronological.")

    total_trades = len(ordered_trades)
    r_values = [t.r_multiple for t in ordered_trades if t.r_multiple is not None]
    wins = [r for r in r_values if r > 0]
    gross_win = sum(r for r in r_values if r > 0)
    gross_loss = abs(sum(r for r in r_values if r < 0))
    pf = (gross_win / gross_loss) if gross_loss > 0 else None

    cumulative_r: list[float] = []
    running = 0.0
    streak = 0
    max_streak = 0
    for trade in ordered_trades:
        running += trade.r_multiple or 0.0
        cumulative_r.append(running)
        if trade.r_multiple is not None and trade.r_multiple < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    span_days = (ordered_trades[-1].timestamp - ordered_trades[0].timestamp).days if ordered_trades else 0
    months_span = span_days / 30.4375 if span_days > 0 else None

    return {
        "total_oos_trades": total_trades,
        "oos_trades_per_month": (total_trades / months_span) if months_span else None,
        "oos_win_rate": (len(wins) / total_trades * 100) if total_trades else None,
        "oos_pf": pf,
        "oos_avg_r": (sum(r_values) / len(r_values)) if r_values else None,
        "oos_cumulative_r": cumulative_r[-1] if cumulative_r else None,
        "oos_pnl": sum(t.pnl for t in ordered_trades if t.pnl is not None) if ordered_trades else None,
        "oos_max_dd": None,
        "max_losing_streak": max_streak,
        "fold_count": len(fold_results),
        "successful_fold_count": len(successful),
        "no_selection_fold_count": sum(1 for f in fold_results if f.status == "NO_SELECTION"),
        "equity_semantics": "NON_COMPOUNDED_FOLD_STITCH",
        "cumulative_r_series": cumulative_r,
        "stitched_trades": ordered_trades,
    }


# ---------------------------------------------------------------------------
# Section 10: Walk-forward summary
# ---------------------------------------------------------------------------


def walk_forward_summary(fold_results: Sequence[FoldResult]) -> dict[str, Any]:
    successful = [f for f in fold_results if f.status == "SELECTED" and f.validation]

    def value_of(fold: FoldResult, key: str) -> float | None:
        return (fold.validation or {}).get(key)

    profitable = [f for f in successful if (value_of(f, "pnl") or 0) > 0]
    positive_avg_r = [f for f in successful if (value_of(f, "average_r") or 0) > 0]
    pfs = [value_of(f, "profit_factor") for f in successful if value_of(f, "profit_factor") is not None]
    avgrs = [value_of(f, "average_r") for f in successful if value_of(f, "average_r") is not None]
    dds = [value_of(f, "max_drawdown") for f in successful if value_of(f, "max_drawdown") is not None]
    drift = parameter_drift(fold_results)

    return {
        "profitable_oos_folds_percent": (len(profitable) / len(successful) * 100) if successful else None,
        "positive_average_r_oos_folds_percent": (len(positive_avg_r) / len(successful) * 100) if successful else None,
        "median_oos_pf": median(pfs) if pfs else None,
        "median_oos_average_r": median(avgrs) if avgrs else None,
        "median_oos_dd": median(dds) if dds else None,
        "worst_fold_average_r": min(avgrs) if avgrs else None,
        "worst_fold_dd": max(dds) if dds else None,
        "parameter_changes_per_fold": drift["changed_parameter_count"],
        "selection_coverage_percent": (len(successful) / len(fold_results) * 100) if fold_results else None,
        "degradation_distribution": [f.degradation for f in successful if f.degradation],
    }


# ---------------------------------------------------------------------------
# Section 11: Persistence / resume
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WalkForwardRun:
    walk_forward_id: str
    created_at: str
    strategy_id: str
    strategy_version: str
    strategy_fingerprint: str
    config: dict[str, Any]
    dataset_fingerprint: str
    broker_fingerprint: str
    instrument_fingerprint: str
    engine_version: str
    status: str
    fold_count: int


def validate_walk_forward_resume(
    run: WalkForwardRun,
    *,
    strategy_fingerprint: str,
    dataset_fingerprint: str,
    broker_fingerprint: str,
    instrument_fingerprint: str,
    config: dict[str, Any],
) -> WalkForwardRun:
    mismatches = []
    if run.strategy_fingerprint != strategy_fingerprint:
        mismatches.append(f"strategy_fingerprint changed ({run.strategy_fingerprint} -> {strategy_fingerprint})")
    if run.dataset_fingerprint != dataset_fingerprint:
        mismatches.append(f"dataset_fingerprint changed ({run.dataset_fingerprint} -> {dataset_fingerprint})")
    if run.broker_fingerprint != broker_fingerprint:
        mismatches.append(f"broker_fingerprint changed ({run.broker_fingerprint} -> {broker_fingerprint})")
    if run.instrument_fingerprint != instrument_fingerprint:
        mismatches.append(f"instrument_fingerprint changed ({run.instrument_fingerprint} -> {instrument_fingerprint})")
    if run.config != config:
        mismatches.append("config changed")
    if mismatches:
        raise WalkForwardBlocked("RESUME BLOCKED: " + "; ".join(mismatches))
    return run


class WalkForwardStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS walk_forward_runs (
                    walk_forward_id TEXT PRIMARY KEY, metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS walk_forward_folds (
                    walk_forward_id TEXT NOT NULL, fold_id TEXT NOT NULL,
                    fold_json TEXT NOT NULL, PRIMARY KEY (walk_forward_id, fold_id)
                );
                """
            )

    def save_run(self, run: WalkForwardRun) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO walk_forward_runs VALUES (?,?)",
                (run.walk_forward_id, json.dumps(asdict(run), sort_keys=True, default=str)),
            )

    def save_fold(self, walk_forward_id: str, fold_result: FoldResult) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO walk_forward_folds VALUES (?,?,?)",
                (walk_forward_id, fold_result.fold_id, json.dumps(fold_result.as_dict(), sort_keys=True, default=str)),
            )

    def load_run(self, walk_forward_id: str) -> WalkForwardRun | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT metadata_json FROM walk_forward_runs WHERE walk_forward_id=?", (walk_forward_id,)
            ).fetchone()
        return WalkForwardRun(**json.loads(row[0])) if row else None

    def load_folds(self, walk_forward_id: str) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT fold_json FROM walk_forward_folds WHERE walk_forward_id=? ORDER BY fold_id",
                (walk_forward_id,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_runs(self) -> list[WalkForwardRun]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT metadata_json FROM walk_forward_runs ORDER BY walk_forward_id DESC"
            ).fetchall()
        return [WalkForwardRun(**json.loads(row[0])) for row in rows]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_walk_forward(
    *,
    descriptor: StrategyDescriptor,
    config: WalkForwardConfig,
    bar_timestamps: Sequence[datetime],
    data_role: DatasetRole,
    dataset_fingerprint: str,
    broker_fingerprint: str,
    instrument_fingerprint: str,
    engine_version: str,
    train_candidates_fn: Callable[[Fold, WalkForwardConfig], list[CandidateResult]],
    validate_fn: Callable[[Fold, dict[str, Any]], CandidateResult],
    store: WalkForwardStore | None = None,
) -> tuple[WalkForwardRun, list[FoldResult]]:
    guard_walk_forward(descriptor, data_role)
    guard_dataset_role(data_role)

    bars = sorted(bar_timestamps)
    if not bars:
        raise WalkForwardBlocked("WALK-FORWARD BLOCKED: no bar data supplied.")
    folds = generate_folds(config, bars[0], bars[-1])

    walk_forward_id = "WF-" + uuid.uuid4().hex[:10].upper()
    run = WalkForwardRun(
        walk_forward_id=walk_forward_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        strategy_id=descriptor.metadata.strategy_id,
        strategy_version=descriptor.metadata.version,
        strategy_fingerprint=descriptor.metadata.strategy_fingerprint,
        config=config.as_dict(),
        dataset_fingerprint=dataset_fingerprint,
        broker_fingerprint=broker_fingerprint,
        instrument_fingerprint=instrument_fingerprint,
        engine_version=engine_version,
        status="RUNNING",
        fold_count=len(folds),
    )
    if store:
        store.save_run(run)

    fold_results: list[FoldResult] = []
    for fold in folds:
        fold_bars = build_fold_bars(
            fold, bars, embargo_bars=config.embargo_bars, warmup_bars=config.warmup_bars,
            minimum_training_bars=config.minimum_training_bars, minimum_validation_bars=config.minimum_validation_bars,
        )
        integrity = check_temporal_integrity(fold, fold_bars, embargo_bars=config.embargo_bars, warmup_bars=config.warmup_bars)

        candidates = train_candidates_fn(fold, config)
        selected, rationale = select_candidate(candidates, config.selection_policy, fold_id=fold.fold_id)

        if selected is None:
            fold_result = FoldResult(
                fold_id=fold.fold_id, fold_number=fold.fold_number, train_start=fold.train_start,
                train_end=fold.train_end, validation_start=fold.validation_start, validation_end=fold.validation_end,
                status="NO_SELECTION", selected_candidate_id=None, selected_parameters=None, fingerprints=None,
                selection_rationale=rationale, training=None, validation=None, degradation=None,
                temporal_integrity=integrity, warnings=(),
            )
        else:
            validation_candidate = validate_fn(fold, dict(selected.parameters))
            fingerprints = FoldFingerprints(
                parameter_fingerprint=selected.parameter_fingerprint,
                strategy_fingerprint=selected.strategy_fingerprint,
                dataset_fingerprint=selected.dataset_fingerprint,
                broker_fingerprint=selected.broker_fingerprint,
                instrument_fingerprint=selected.instrument_fingerprint,
            )
            training_metrics = _metrics_dict(selected)
            validation_metrics = _metrics_dict(validation_candidate)
            fold_result = FoldResult(
                fold_id=fold.fold_id, fold_number=fold.fold_number, train_start=fold.train_start,
                train_end=fold.train_end, validation_start=fold.validation_start, validation_end=fold.validation_end,
                status="SELECTED", selected_candidate_id=selected.candidate_id, selected_parameters=dict(selected.parameters),
                fingerprints=fingerprints, selection_rationale=rationale, training=training_metrics,
                validation=validation_metrics, degradation=fold_degradation(training_metrics, validation_metrics),
                temporal_integrity=integrity, warnings=(),
            )

        fold_results.append(fold_result)
        if store:
            store.save_fold(walk_forward_id, fold_result)

    run = replace(run, status="COMPLETED")
    if store:
        store.save_run(run)
    return run, fold_results
