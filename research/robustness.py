"""Phase 3D Monte Carlo & Bootstrap Robustness Lab.

Post-backtest robustness analysis operating on an already-completed, audited trade
sequence. Never alters strategy parameters, never generates trading signals, and
never feeds back into the Phase 3B optimizer or Phase 3C walk-forward selection.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence
import uuid

import numpy as np

from core.fingerprints import stable_fingerprint
from core.trade_log import to_timestamp as to_trade_timestamp
from research.walk_forward import FoldResult, StitchedTrade

RESERVED_DATASET_ROLES = ("FORWARD_VALIDATION", "HOLDOUT")
DEFAULT_SIMULATION_SAFETY_LIMIT = 20_000
PATH_SEMANTICS = "R_PATH_SIMULATION"


class RobustnessBlocked(ValueError):
    """Raised whenever a robustness-lab safety invariant is violated. Never caught silently."""


class RobustnessMethod(str, Enum):
    PERMUTATION = "PERMUTATION"
    IID_BOOTSTRAP = "IID_BOOTSTRAP"
    BLOCK_BOOTSTRAP = "BLOCK_BOOTSTRAP"


# ---------------------------------------------------------------------------
# Section 1: Source model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RobustnessTrade:
    trade_id: str
    timestamp: str
    side: str | None
    strategy_component: str | None
    realized_r: float
    pnl: float | None
    planned_risk: float | None
    duration: float | None
    dataset_role: str
    source_run_id: str
    fold_id: str | None = None


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    #--- Experiments stored before the trade-log timestamp fix carry epoch
    #--- nanoseconds, which reach here as a string of digits.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return to_trade_timestamp(value).to_pydatetime()
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return to_trade_timestamp(value).to_pydatetime()
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise RobustnessBlocked(f"ROBUSTNESS BLOCKED: unparseable timestamp {value!r}.") from exc
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    raise RobustnessBlocked(f"ROBUSTNESS BLOCKED: unsupported timestamp type {type(value)!r}.")


def _require_chronological(trades: Sequence[RobustnessTrade]) -> None:
    parsed = [_parse_timestamp(t.timestamp) for t in trades]
    for earlier, later in zip(parsed, parsed[1:]):
        if later < earlier:
            raise RobustnessBlocked("ROBUSTNESS BLOCKED: source trade sequence is not chronological.")


def trades_from_trade_log(
    trade_log: Sequence[Mapping[str, Any]],
    *,
    dataset_role: str,
    source_run_id: str,
) -> list[RobustnessTrade]:
    """Normalizes a UniversalBacktestResult/Experiment trade_log (list of dict rows) into
    RobustnessTrade observations. Never infers a missing realized R or timestamp."""
    trades: list[RobustnessTrade] = []
    for row in trade_log:
        realized_r = row.get("realized_r", row.get("r_multiple"))
        if realized_r is None:
            raise RobustnessBlocked(
                f"ROBUSTNESS BLOCKED: trade {row.get('trade_id')} is missing realized R; refusing to infer it."
            )
        timestamp = row.get("exit_time") or row.get("entry_time")
        if timestamp is None:
            raise RobustnessBlocked(f"ROBUSTNESS BLOCKED: trade {row.get('trade_id')} is missing a timestamp.")
        trades.append(RobustnessTrade(
            trade_id=str(row.get("trade_id")), timestamp=str(timestamp), side=row.get("direction"),
            strategy_component=row.get("setup_id"), realized_r=float(realized_r), pnl=row.get("pnl"),
            planned_risk=row.get("initial_risk"), duration=row.get("duration_minutes"),
            dataset_role=dataset_role, source_run_id=source_run_id, fold_id=None,
        ))
    _require_chronological(trades)
    return trades


def trades_from_walk_forward_oos(
    fold_results: Sequence[FoldResult],
    fold_trades: Mapping[str, Sequence[StitchedTrade]],
    *,
    walk_forward_id: str,
) -> list[RobustnessTrade]:
    """Builds RobustnessTrade observations from stitched Phase 3C OOS validation trades only.
    Training trades are never included; fold_id provenance is preserved."""
    from research.walk_forward import stitch_oos

    stitched = stitch_oos(fold_results, fold_trades)
    trades = [
        RobustnessTrade(
            trade_id=f"{trade.fold_id}-{index}", timestamp=trade.timestamp.isoformat(), side=None,
            strategy_component=None, realized_r=float(trade.r_multiple) if trade.r_multiple is not None else None,
            pnl=trade.pnl, planned_risk=None, duration=None, dataset_role="WALK_FORWARD_OOS",
            source_run_id=walk_forward_id, fold_id=trade.fold_id,
        )
        for index, trade in enumerate(stitched["stitched_trades"])
    ]
    for trade in trades:
        if trade.realized_r is None:
            raise RobustnessBlocked(f"ROBUSTNESS BLOCKED: stitched OOS trade {trade.trade_id} is missing realized R.")
    _require_chronological(trades)
    return trades


def deterministic_fixture_trades(source_run_id: str = "FIXTURE-RUN") -> list[RobustnessTrade]:
    """Hand-calculable known R series: two winners, three consecutive losses, a small
    recovery, one large winner, one more loss. Max drawdown, streaks, and rolling-N
    metrics for this exact series are hand-verified in tests/test_robustness.py."""
    values = [1.0, 1.0, -1.0, -1.0, -1.0, 2.0, 0.5, -0.5, 3.0, -1.0]
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        RobustnessTrade(
            trade_id=f"FIX-{i}", timestamp=(base.replace(day=1 + i)).isoformat(), side="LONG" if r >= 0 else "SHORT",
            strategy_component="fixture", realized_r=r, pnl=r * 100.0, planned_risk=100.0, duration=60.0,
            dataset_role="DEVELOPMENT", source_run_id=source_run_id, fold_id=None,
        )
        for i, r in enumerate(values)
    ]


def compute_source_fingerprint(trades: Sequence[RobustnessTrade]) -> str:
    return stable_fingerprint([asdict(t) for t in trades])


def reserved_data_warning(dataset_role: str) -> str | None:
    if dataset_role in RESERVED_DATASET_ROLES:
        return "RESERVED DATA ROBUSTNESS ANALYSIS — DO NOT RETUNE FROM THESE RESULTS"
    return None


# ---------------------------------------------------------------------------
# Section 5/9: Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapitalModel:
    starting_capital: float
    risk_fraction: float
    ruin_capital_threshold: float | None = None
    ruin_drawdown_percent: float | None = None

    def __post_init__(self) -> None:
        if self.starting_capital <= 0:
            raise ValueError("starting_capital must be positive.")
        if not (0 < self.risk_fraction < 1):
            raise ValueError("risk_fraction must be between 0 and 1 (exclusive).")
        if self.ruin_capital_threshold is None and self.ruin_drawdown_percent is None:
            raise ValueError("CapitalModel requires ruin_capital_threshold or ruin_drawdown_percent.")


@dataclass(frozen=True)
class RobustnessConfig:
    method: RobustnessMethod
    simulations: int = 5000
    seed: int = 42
    block_length: int = 5
    rolling_loss_window: int = 20
    drawdown_threshold_r: float | None = None
    capital_model: CapitalModel | None = None
    safety_limit: int = DEFAULT_SIMULATION_SAFETY_LIMIT

    def __post_init__(self) -> None:
        if self.simulations <= 0:
            raise ValueError("simulations must be positive.")
        if self.simulations > self.safety_limit:
            raise RobustnessBlocked(
                f"ROBUSTNESS BLOCKED: {self.simulations} simulations exceeds safety limit {self.safety_limit}."
            )
        if self.block_length <= 0:
            raise ValueError("block_length must be positive.")
        if self.rolling_loss_window <= 0:
            raise ValueError("rolling_loss_window must be positive.")

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["method"] = self.method.value
        return payload


# ---------------------------------------------------------------------------
# Section 2: Resampling methods
# ---------------------------------------------------------------------------


def permutation_paths(r_values: np.ndarray, *, simulations: int, seed: int) -> np.ndarray:
    """Shuffles the exact observed trades without replacement. Same trades, same count,
    same total R by construction — only order differs."""
    rng = np.random.default_rng(seed)
    base = np.broadcast_to(r_values, (simulations, len(r_values))).copy()
    return rng.permuted(base, axis=1)


def iid_bootstrap_paths(r_values: np.ndarray, *, simulations: int, seed: int) -> np.ndarray:
    """Samples N trades with replacement from the observed N trades.
    Assumes empirical trades are exchangeable/approximately independent; destroys clustering."""
    rng = np.random.default_rng(seed)
    n = len(r_values)
    idx = rng.integers(0, n, size=(simulations, n))
    return r_values[idx]


def block_bootstrap_paths(r_values: np.ndarray, *, simulations: int, seed: int, block_length: int) -> np.ndarray:
    """Samples contiguous blocks with replacement and concatenates until N observations are
    reached, truncating the final block to exactly N. Order within a sampled block is never
    reordered. If block_length exceeds the series length it is capped to the series length,
    producing one block covering the whole series (deterministic boundary behavior)."""
    n = len(r_values)
    effective_block_length = min(block_length, n)
    rng = np.random.default_rng(seed)
    num_possible_starts = n - effective_block_length + 1
    blocks_per_sim = -(-n // effective_block_length)  # ceil division
    starts = rng.integers(0, num_possible_starts, size=(simulations, blocks_per_sim))
    offsets = np.arange(effective_block_length)
    idx = starts[:, :, None] + offsets[None, None, :]
    gathered = r_values[idx].reshape(simulations, blocks_per_sim * effective_block_length)
    return gathered[:, :n]


def resample_paths(r_values: np.ndarray, config: RobustnessConfig) -> np.ndarray:
    if config.method is RobustnessMethod.PERMUTATION:
        return permutation_paths(r_values, simulations=config.simulations, seed=config.seed)
    if config.method is RobustnessMethod.IID_BOOTSTRAP:
        return iid_bootstrap_paths(r_values, simulations=config.simulations, seed=config.seed)
    return block_bootstrap_paths(r_values, simulations=config.simulations, seed=config.seed, block_length=config.block_length)


# ---------------------------------------------------------------------------
# Section 4/6: Path metrics (vectorized over simulations)
# ---------------------------------------------------------------------------


def _max_streak(paths: np.ndarray, *, negative: bool) -> np.ndarray:
    sign = paths < 0 if negative else paths > 0
    simulations, n = sign.shape
    streaks = np.zeros_like(sign, dtype=np.int64)
    streaks[:, 0] = sign[:, 0].astype(np.int64)
    for j in range(1, n):
        streaks[:, j] = np.where(sign[:, j], streaks[:, j - 1] + 1, 0)
    return streaks.max(axis=1)


def _longest_recovery_trades(paths: np.ndarray) -> np.ndarray:
    """Trades elapsed between a cumulative-R peak and the first later point the path
    returns to at-or-above that same peak value. Unrecovered trailing drawdowns at the
    end of the series do not count (recovery must complete within the observed series)."""
    simulations, n = paths.shape
    cum_all = np.cumsum(paths, axis=1)
    peak_all = np.maximum.accumulate(cum_all, axis=1)
    result = np.zeros(simulations, dtype=np.int64)
    for i in range(simulations):
        cum, peak = cum_all[i], peak_all[i]
        longest = 0
        in_drawdown = False
        drawdown_start = 0
        peak_index = 0
        for j in range(n):
            if cum[j] < peak[j]:
                if not in_drawdown:
                    in_drawdown = True
                    drawdown_start = peak_index
            else:
                if in_drawdown:
                    longest = max(longest, j - drawdown_start)
                in_drawdown = False
                peak_index = j
        result[i] = longest
    return result


def _worst_rolling_window_r(paths: np.ndarray, window: int) -> np.ndarray:
    simulations, n = paths.shape
    window = min(max(window, 1), n)
    padded = np.concatenate([np.zeros((simulations, 1)), np.cumsum(paths, axis=1)], axis=1)
    rolling = padded[:, window:] - padded[:, :-window]
    return rolling.min(axis=1)


def compute_path_metrics(paths: np.ndarray, *, rolling_window: int, drawdown_threshold_r: float | None) -> dict[str, np.ndarray]:
    cum = np.cumsum(paths, axis=1)
    running_max = np.maximum.accumulate(cum, axis=1)
    max_dd_r = (running_max - cum).max(axis=1)
    terminal_r = cum[:, -1]
    metrics = {
        "terminal_r": terminal_r,
        "max_dd_r": max_dd_r,
        "losing_streak": _max_streak(paths, negative=True),
        "winning_streak": _max_streak(paths, negative=False),
        "longest_recovery_trades": _longest_recovery_trades(paths),
        "worst_rolling_r": _worst_rolling_window_r(paths, rolling_window),
        "positive_terminal": (terminal_r > 0),
    }
    if drawdown_threshold_r is not None:
        metrics["drawdown_breach"] = max_dd_r >= drawdown_threshold_r
    return metrics


def compute_observed_metrics(r_values: np.ndarray, *, rolling_window: int, drawdown_threshold_r: float | None = None) -> dict[str, float]:
    path = r_values.reshape(1, -1)
    metrics = compute_path_metrics(path, rolling_window=rolling_window, drawdown_threshold_r=drawdown_threshold_r)
    return {key: (bool(value[0]) if value.dtype == bool else float(value[0])) for key, value in metrics.items()}


def cumulative_r_envelope(paths: np.ndarray, percentiles: tuple[int, ...] = (5, 25, 50, 75, 95)) -> dict[str, list[float]]:
    cum = np.cumsum(paths, axis=1)
    return {f"p{p}": np.percentile(cum, p, axis=0).tolist() for p in percentiles}


# ---------------------------------------------------------------------------
# Section 7: Distribution summary
# ---------------------------------------------------------------------------


def distribution_summary(values: np.ndarray) -> dict[str, float]:
    values = np.asarray(values, dtype=float)
    return {
        "minimum": float(np.min(values)), "p5": float(np.percentile(values, 5)),
        "p10": float(np.percentile(values, 10)), "p25": float(np.percentile(values, 25)),
        "median": float(np.percentile(values, 50)), "p75": float(np.percentile(values, 75)),
        "p90": float(np.percentile(values, 90)), "p95": float(np.percentile(values, 95)),
        "maximum": float(np.max(values)), "mean": float(np.mean(values)),
    }


def worst_tail_mean(values: np.ndarray, *, tail_percent: float = 5.0, high_is_worse: bool = True) -> float:
    values = np.asarray(values, dtype=float)
    n = len(values)
    k = max(1, int(np.ceil(n * tail_percent / 100)))
    sorted_values = np.sort(values)
    tail = sorted_values[-k:] if high_is_worse else sorted_values[:k]
    return float(np.mean(tail))


# ---------------------------------------------------------------------------
# Section 8: Drawdown risk
# ---------------------------------------------------------------------------


def drawdown_risk(observed_max_dd_r: float, simulated_max_dd_r: np.ndarray, drawdown_threshold_r: float | None) -> dict[str, Any]:
    breach_probability = float(np.mean(simulated_max_dd_r >= drawdown_threshold_r)) if drawdown_threshold_r is not None else None
    observed_percentile = float((simulated_max_dd_r <= observed_max_dd_r).mean() * 100)
    return {
        "label": "DRAWDOWN BREACH PROBABILITY",
        "observed_max_dd_r": observed_max_dd_r,
        "simulated_median_max_dd_r": float(np.percentile(simulated_max_dd_r, 50)),
        "simulated_p90_max_dd_r": float(np.percentile(simulated_max_dd_r, 90)),
        "simulated_p95_max_dd_r": float(np.percentile(simulated_max_dd_r, 95)),
        "simulated_p99_max_dd_r": float(np.percentile(simulated_max_dd_r, 99)),
        "drawdown_breach_threshold_r": drawdown_threshold_r,
        "drawdown_breach_probability": breach_probability,
        "observed_dd_percentile_within_simulated_distribution": observed_percentile,
        "worst_5_percent_mean_max_dd_r": worst_tail_mean(simulated_max_dd_r, tail_percent=5, high_is_worse=True),
    }


# ---------------------------------------------------------------------------
# Section 9: Risk of ruin — strict definition
# ---------------------------------------------------------------------------


def risk_of_ruin(paths: np.ndarray, capital_model: CapitalModel | None) -> dict[str, Any]:
    if capital_model is None:
        return {"risk_of_ruin": "N/A", "ruin_definition": None, "capital_model": None}

    factors = np.maximum(1.0 + capital_model.risk_fraction * paths, 0.0)
    equity = capital_model.starting_capital * np.cumprod(factors, axis=1)
    with_start = np.concatenate([np.full((equity.shape[0], 1), capital_model.starting_capital), equity], axis=1)
    peak = np.maximum.accumulate(with_start, axis=1)[:, 1:]

    if capital_model.ruin_capital_threshold is not None:
        threshold = capital_model.ruin_capital_threshold
        ruin_hit = (equity <= threshold).any(axis=1)
        definition = f"equity <= {threshold}"
    else:
        drawdown_percent = np.divide(peak - equity, peak, out=np.zeros_like(equity), where=peak > 0) * 100
        ruin_hit = (drawdown_percent >= capital_model.ruin_drawdown_percent).any(axis=1)
        definition = f"drawdown >= {capital_model.ruin_drawdown_percent}% from peak equity"

    return {
        "risk_of_ruin": float(np.mean(ruin_hit)),
        "ruin_definition": definition,
        "capital_model": asdict(capital_model),
    }


# ---------------------------------------------------------------------------
# Section 10: Sequence dependency
# ---------------------------------------------------------------------------


def sequence_dependency(observed_metrics: Mapping[str, float], permutation_metrics: Mapping[str, np.ndarray]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for key in ("max_dd_r", "losing_streak", "longest_recovery_trades", "worst_rolling_r"):
        if key not in observed_metrics or key not in permutation_metrics:
            continue
        observed_value = observed_metrics[key]
        simulated = permutation_metrics[key]
        report[key] = {
            "observed": observed_value,
            "percentile_within_permutations": float((simulated <= observed_value).mean() * 100),
        }
    warnings: list[str] = []
    dd_percentile = report.get("max_dd_r", {}).get("percentile_within_permutations")
    if dd_percentile is not None:
        if dd_percentile >= 95:
            warnings.append("OBSERVED PATH HAS UNUSUALLY SEVERE CLUSTERING")
        elif dd_percentile <= 5:
            warnings.append("OBSERVED PATH HAS LOWER-THAN-TYPICAL DRAWDOWN")
    report["warnings"] = warnings
    report["note"] = "Percentile location alone does not prove statistical dependence."
    return report


# ---------------------------------------------------------------------------
# Section 11: Outlier dependence
# ---------------------------------------------------------------------------


def _scenario_metrics(r_values: np.ndarray) -> dict[str, Any]:
    n = len(r_values)
    if n == 0:
        return {"trade_count": 0, "total_r": 0.0, "average_r": None, "profit_factor": None, "positive_expectancy": None}
    total_r = float(np.sum(r_values))
    average_r = float(np.mean(r_values))
    gross_win = float(np.sum(r_values[r_values > 0]))
    gross_loss = float(-np.sum(r_values[r_values < 0]))
    return {
        "trade_count": n, "total_r": total_r, "average_r": average_r,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
        "positive_expectancy": average_r > 0,
    }


def outlier_dependence(r_values: np.ndarray) -> dict[str, Any]:
    r_values = np.asarray(r_values, dtype=float)
    positive_idx = np.where(r_values > 0)[0]
    negative_idx = np.where(r_values < 0)[0]
    winners_order = positive_idx[np.argsort(-r_values[positive_idx])]
    losers_order = negative_idx[np.argsort(r_values[negative_idx])]
    gross_positive = float(r_values[positive_idx].sum()) if len(positive_idx) else 0.0

    def contribution(k: int) -> float | None:
        if gross_positive == 0 or not len(winners_order):
            return None
        k = min(k, len(winners_order))
        return float(r_values[winners_order[:k]].sum() / gross_positive * 100)

    top10_k = int(np.ceil(len(winners_order) * 0.10)) if len(winners_order) else 0

    def scenario(remove_k: int) -> dict[str, Any]:
        if remove_k <= 0 or not len(winners_order):
            remaining = r_values
        else:
            remove_idx = set(winners_order[:min(remove_k, len(winners_order))].tolist())
            keep_mask = np.array([i not in remove_idx for i in range(len(r_values))])
            remaining = r_values[keep_mask]
        return _scenario_metrics(remaining)

    return {
        "largest_winning_trade_r": float(r_values[winners_order[0]]) if len(winners_order) else None,
        "top_1_winner_contribution_percent": contribution(1),
        "top_3_winner_contribution_percent": contribution(3),
        "top_5_winner_contribution_percent": contribution(5),
        "top_10_percent_winners_contribution_percent": contribution(top10_k) if top10_k else None,
        "largest_loss_r": float(r_values[losers_order[0]]) if len(losers_order) else None,
        "worst_3_losses_r": [float(r_values[i]) for i in losers_order[:3]],
        "worst_5_losses_r": [float(r_values[i]) for i in losers_order[:5]],
        "scenarios": {
            "original": _scenario_metrics(r_values),
            "remove_largest_winner": scenario(1),
            "remove_top_3_winners": scenario(3),
            "remove_top_5_winners": scenario(5),
            "remove_top_10_percent_winners": scenario(top10_k),
        },
        "note": "Outlier dependence is descriptive; it does not by itself invalidate a strategy.",
    }


# ---------------------------------------------------------------------------
# Section 12: Tail loss analysis
# ---------------------------------------------------------------------------


def tail_loss_analysis(r_values: np.ndarray) -> dict[str, Any]:
    r_values = np.asarray(r_values, dtype=float)
    n = len(r_values)
    sorted_values = np.sort(r_values)
    k = max(1, int(np.ceil(n * 0.05))) if n else 0
    return {
        "trade_count": n,
        "small_sample_warning": n < 20,
        "p1_trade_r": float(np.percentile(r_values, 1)) if n else None,
        "p5_trade_r": float(np.percentile(r_values, 5)) if n else None,
        "lower_5_percent_mean_trade_r": float(np.mean(sorted_values[:k])) if n else None,
        "worst_trade_r": float(sorted_values[0]) if n else None,
    }


# ---------------------------------------------------------------------------
# Section 13: IID vs block comparison
# ---------------------------------------------------------------------------


def compare_iid_vs_block(iid_metrics: Mapping[str, np.ndarray], block_metrics: Mapping[str, np.ndarray]) -> dict[str, Any]:
    comparison: dict[str, Any] = {}
    for key in ("max_dd_r", "losing_streak", "terminal_r", "worst_rolling_r"):
        if key in iid_metrics and key in block_metrics:
            comparison[key] = {
                "iid_bootstrap": distribution_summary(iid_metrics[key]),
                "block_bootstrap": distribution_summary(block_metrics[key]),
            }
    comparison["note"] = "Neither method is treated as definitively correct; compare to assess clustering sensitivity."
    return comparison


# ---------------------------------------------------------------------------
# Section 16: Persistence / resume
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RobustnessRun:
    robustness_run_id: str
    created_at: str
    source_run_id: str
    source_fingerprint: str
    method: str
    config: dict[str, Any]
    seed: int
    simulations: int
    engine_version: str
    strategy_id: str | None
    strategy_version: str | None
    strategy_status: str | None
    dataset_role: str
    status: str
    simulation_fingerprint: str


def validate_robustness_resume(run: RobustnessRun, *, source_fingerprint: str, config: dict[str, Any]) -> RobustnessRun:
    mismatches = []
    if run.source_fingerprint != source_fingerprint:
        mismatches.append(f"source_fingerprint changed ({run.source_fingerprint} -> {source_fingerprint})")
    if run.config != config:
        mismatches.append("config changed")
    if mismatches:
        raise RobustnessBlocked("RESUME BLOCKED: " + "; ".join(mismatches))
    return run


class RobustnessStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS robustness_runs (
                    robustness_run_id TEXT PRIMARY KEY, metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS robustness_results (
                    robustness_run_id TEXT PRIMARY KEY, result_json TEXT NOT NULL
                );
                """
            )

    def save_run(self, run: RobustnessRun) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO robustness_runs VALUES (?,?)",
                (run.robustness_run_id, json.dumps(asdict(run), sort_keys=True, default=str)),
            )

    def save_result(self, robustness_run_id: str, result: dict[str, Any]) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO robustness_results VALUES (?,?)",
                (robustness_run_id, json.dumps(result, sort_keys=True, default=str)),
            )

    def load_run(self, robustness_run_id: str) -> RobustnessRun | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT metadata_json FROM robustness_runs WHERE robustness_run_id=?", (robustness_run_id,)
            ).fetchone()
        return RobustnessRun(**json.loads(row[0])) if row else None

    def load_result(self, robustness_run_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT result_json FROM robustness_results WHERE robustness_run_id=?", (robustness_run_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def list_runs(self) -> list[RobustnessRun]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT metadata_json FROM robustness_runs ORDER BY robustness_run_id DESC"
            ).fetchall()
        return [RobustnessRun(**json.loads(row[0])) for row in rows]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_robustness_analysis(
    *,
    trades: Sequence[RobustnessTrade],
    config: RobustnessConfig,
    engine_version: str,
    dataset_role: str,
    source_run_id: str,
    strategy_id: str | None = None,
    strategy_version: str | None = None,
    strategy_status: str | None = None,
    store: RobustnessStore | None = None,
) -> tuple[RobustnessRun, dict[str, Any]]:
    if not trades:
        raise RobustnessBlocked("ROBUSTNESS BLOCKED: no trades to analyze.")
    r_values = np.array([t.realized_r for t in trades], dtype=float)
    source_fp = compute_source_fingerprint(trades)

    paths = resample_paths(r_values, config)
    simulated_metrics = compute_path_metrics(paths, rolling_window=config.rolling_loss_window, drawdown_threshold_r=config.drawdown_threshold_r)
    observed_metrics = compute_observed_metrics(r_values, rolling_window=config.rolling_loss_window, drawdown_threshold_r=config.drawdown_threshold_r)

    distributions = {key: distribution_summary(value) for key, value in simulated_metrics.items() if value.dtype != bool}
    drawdown = drawdown_risk(observed_metrics["max_dd_r"], simulated_metrics["max_dd_r"], config.drawdown_threshold_r)
    ruin = risk_of_ruin(paths, config.capital_model)
    sequence = sequence_dependency(observed_metrics, simulated_metrics) if config.method is RobustnessMethod.PERMUTATION else None
    outliers = outlier_dependence(r_values)
    tail = tail_loss_analysis(r_values)
    envelope = cumulative_r_envelope(paths)
    warning = reserved_data_warning(dataset_role)

    simulation_fingerprint = stable_fingerprint({
        "source_fingerprint": source_fp, "method": config.method.value, "config": config.as_dict(),
        "engine_version": engine_version,
    })

    run = RobustnessRun(
        robustness_run_id="RB-" + uuid.uuid4().hex[:10].upper(),
        created_at=datetime.now(timezone.utc).isoformat(),
        source_run_id=source_run_id, source_fingerprint=source_fp, method=config.method.value,
        config=config.as_dict(), seed=config.seed, simulations=config.simulations, engine_version=engine_version,
        strategy_id=strategy_id, strategy_version=strategy_version, strategy_status=strategy_status,
        dataset_role=dataset_role, status="COMPLETED", simulation_fingerprint=simulation_fingerprint,
    )

    result = {
        "path_semantics": PATH_SEMANTICS,
        "observed": observed_metrics,
        "distributions": distributions,
        "drawdown_risk": drawdown,
        "risk_of_ruin": ruin,
        "sequence_dependency": sequence,
        "outlier_dependence": outliers,
        "tail_loss": tail,
        "cumulative_r_envelope": envelope,
        "reserved_data_warning": warning,
        "terminal_r_unchanged_by_construction": config.method is RobustnessMethod.PERMUTATION,
        "probability_terminal_r_positive": float(np.mean(simulated_metrics["positive_terminal"])),
    }

    if store:
        store.save_run(run)
        store.save_result(run.robustness_run_id, result)

    return run, result
