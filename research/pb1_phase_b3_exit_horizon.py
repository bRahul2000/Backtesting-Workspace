"""PB1 Phase B.3 — DEVELOPMENT exit-horizon sensitivity.

Phase B.2 established that PB1's replicated failure mode is a *valid*
continuation that travels meaningfully in favour and then reverses before the
fixed 3R target. This phase asks one narrow structural question: is the 3R exit
horizon itself mismatched to PB1, and — more importantly — is the answer stable
across a small neighbourhood of fixed targets rather than peaking at one value?

Scope guards:
  * The three Phase B.1 entry representatives are imported unchanged from the
    Phase B.2 module, so the entry side is provably identical.
  * Only 1.5R / 2.0R / 2.5R / 3.0R are run. The four targets are predeclared;
    no further multiple is added after seeing results.
  * PB1's source and defaults are untouched. The reward multiple is supplied as
    execution configuration (BacktestConfig.risk_reward_ratio), which the
    audited engine already applies through engine/execution.py's existing
    fixed-R target logic. No new exit behaviour is introduced: no breakeven, no
    trailing, no partial, no time exit.
  * DEVELOPMENT (2021-01-01 .. 2023-12-31) only.

Because PB1 holds at most one pending order or position at a time, an earlier
target frees the component sooner and can change which later setups are
tradeable. Trade counts are therefore *not* expected to match across targets,
and the conversion analysis matches trades explicitly rather than assuming a
common trade population.
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
import pandas as pd

from core.adapters.audited_engine import run_universal_backtest
from core.config import BacktestConfig, DatasetRole
from research.pb1_phase_b2_regime_diagnosis import REPRESENTATIVES, STRATEGY_ID
from research.pb1_phase_b2_regime_features import (
    DATA, DEVELOPMENT_END, DEVELOPMENT_START,
)

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "pb1" / "phase_b3_report.json"
SCRATCH_LEDGER = Path("/tmp") / "pb1_phase_b3_scratch_ledger.sqlite3"

# Section 2: predeclared targets only.
TARGETS: tuple[float, ...] = (1.5, 2.0, 2.5, 3.0)
BASELINE_TARGET = 3.0

# Section 9: theoretical gross break-even win rate, 1 / (1 + R). These ignore
# spread, commission and same-bar resolution, all of which are included in the
# actual backtests, so they are context only — never a realized break-even.
BREAKEVEN_WIN_RATE = {target: 100.0 / (1.0 + target) for target in TARGETS}

# Section 10: retention floor below which a target is not a credible structure
# regardless of its ratios.
MINIMUM_RETENTION_PERCENT = 50.0


def _config(parameters: dict[str, float], target: float) -> BacktestConfig:
    return BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD", strategy_id=STRATEGY_ID,
        timeframe="15m", higher_timeframes=("1h",), start_date=DEVELOPMENT_START,
        end_date=DEVELOPMENT_END, dataset_role=DatasetRole.DEVELOPMENT,
        strategy_parameters=parameters, risk_reward_ratio=target,
    )


def _profit_factor(frame: pd.DataFrame) -> float | None:
    profit = frame.loc[frame.pnl > 1e-9, "pnl"].sum()
    loss = frame.loc[frame.pnl < -1e-9, "pnl"].sum()
    return float(profit / abs(loss)) if loss else (float("inf") if profit else None)


def _max_drawdown_r(frame: pd.DataFrame) -> float:
    curve = frame.sort_values("exit_time").r_multiple.cumsum()
    return float((curve.cummax() - curve).max()) if len(curve) else 0.0


def _max_drawdown_percent(frame: pd.DataFrame, starting_balance: float = 10_000.0) -> float:
    """Balance-walk drawdown over a trade subset, for per-year comparability.

    The engine's own max_drawdown_percent is reported per run; this
    reconstruction exists only so a single year can be compared across targets.
    """
    balance = peak = starting_balance
    worst = 0.0
    for pnl in frame.sort_values("exit_time").pnl:
        balance += pnl
        peak = max(peak, balance)
        worst = max(worst, (peak - balance) / peak * 100 if peak > 0 else 0.0)
    return float(worst)


def _losing_streak(frame: pd.DataFrame) -> int:
    worst = current = 0
    for pnl in frame.sort_values("exit_time").pnl:
        current = current + 1 if pnl < -1e-9 else 0
        worst = max(worst, current)
    return worst


def _direction_block(frame: pd.DataFrame) -> dict[str, Any]:
    return {"trades": int(len(frame)), "profit_factor": _profit_factor(frame),
            "average_r": float(frame.r_multiple.mean()) if len(frame) else None,
            "total_r": float(frame.r_multiple.sum()),
            "win_rate": float(100 * (frame.pnl > 1e-9).mean()) if len(frame) else None}


def _year_block(frame: pd.DataFrame) -> dict[str, Any]:
    return {"trades": int(len(frame)),
            "win_rate": float(100 * (frame.pnl > 1e-9).mean()) if len(frame) else None,
            "profit_factor": _profit_factor(frame),
            "average_r": float(frame.r_multiple.mean()) if len(frame) else None,
            "total_r": float(frame.r_multiple.sum()),
            "max_drawdown_r": _max_drawdown_r(frame),
            "max_drawdown_percent_within_year": _max_drawdown_percent(frame)}


def _counts(result: Any) -> dict[str, int]:
    """Section 3: the full order lifecycle, which shifts as the target changes."""
    stages: dict[str, int] = {}
    for event in result.signal_diagnostics:
        stages[event["stage"]] = stages.get(event["stage"], 0) + 1
    order_events = result.execution_diagnostics.get("order_events", {})
    return {
        "confirmed_setups": stages.get("confirmation_evaluated", 0),
        "pending_orders_created": stages.get("pending_order_created", 0),
        "entries": int(result.total_entries),
        "closed_trades": int(result.total_trades),
        "orders_expired": int(order_events.get("expired", 0)),
        "orders_cancelled": int(order_events.get("cancelled", 0)),
        "orders_active_at_end": int(order_events.get("active_at_end", 0)),
        "positions_open_at_end": len(result.open_positions_at_end),
    }


def run_one(name: str, parameters: dict[str, float], target: float) -> dict[str, Any]:
    result = run_universal_backtest(DATA, _config(parameters, target), ledger_path=SCRATCH_LEDGER)
    frame = pd.DataFrame(result.trade_log)
    for column in ("signal_time", "entry_time", "exit_time"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    frame["year"] = frame["entry_time"].dt.year
    frame["target"] = target
    frame["representative"] = name

    longs, shorts = frame[frame.direction == "LONG"], frame[frame.direction == "SHORT"]
    return {
        "representative": name, "target": target,
        "parameter_fingerprint": result.parameter_fingerprint,
        "dataset_fingerprint": result.dataset_fingerprint,
        "counts": _counts(result),
        "metrics": {
            "trades": int(result.total_trades),
            "trades_per_month": float(result.trades_per_month),
            "win_rate": float(result.win_rate),
            "profit_factor": result.profit_factor,
            "average_r": float(result.average_r),
            "total_r": float(frame.r_multiple.sum()),
            "pnl": float(result.pnl),
            "max_drawdown_percent": float(result.max_drawdown_percent),
            "max_losing_streak": int(result.max_losing_streak),
            "max_drawdown_r": _max_drawdown_r(frame),
        },
        "long": _direction_block(longs), "short": _direction_block(shorts),
        "yearly": {str(year): _year_block(group) for year, group in frame.groupby("year")},
        "breakeven_win_rate_gross": BREAKEVEN_WIN_RATE[target],
        "_frame": frame,
    }


def conversion_analysis(baseline: pd.DataFrame, variant: pd.DataFrame) -> dict[str, Any]:
    """Section 8: match actual executions rather than inferring from MFE.

    PB1 holds one position at a time, so (entry_time, direction) identifies a
    trade uniquely. Trades present in only one run are genuine availability
    differences created by the earlier or later exit, not bookkeeping noise.
    """
    key = ["entry_time", "direction"]
    merged = baseline.merge(variant, on=key, how="outer", suffixes=("_base", "_var"), indicator=True)
    both = merged[merged._merge == "both"]
    base_only = merged[merged._merge == "left_only"]
    variant_only = merged[merged._merge == "right_only"]

    base_won, variant_won = both.pnl_base > 1e-9, both.pnl_var > 1e-9
    converted = both[~base_won & variant_won]
    retained = both[base_won & variant_won]
    degraded = both[base_won & ~variant_won]
    unchanged = both[~base_won & ~variant_won]
    return {
        "matched_trades": int(len(both)),
        "baseline_only_trades": int(len(base_only)),
        "variant_only_trades": int(len(variant_only)),
        "losers_converted_to_winners": int(len(converted)),
        "winners_still_winners": int(len(retained)),
        "winners_degraded_to_losers": int(len(degraded)),
        "losers_still_losers": int(len(unchanged)),
        "matched_exit_timestamp_changed": int((both.exit_time_base != both.exit_time_var).sum()),
        "total_r_matched_baseline": float(both.r_multiple_base.sum()),
        "total_r_matched_variant": float(both.r_multiple_var.sum()),
        "total_r_from_matched_change": float(both.r_multiple_var.sum() - both.r_multiple_base.sum()),
        "total_r_lost_with_dropped_trades": float(-base_only.r_multiple_base.sum()),
        "total_r_gained_from_new_trades": float(variant_only.r_multiple_var.sum()),
        "average_r_of_dropped_trades": (float(base_only.r_multiple_base.mean())
                                        if len(base_only) else None),
        "average_r_of_new_trades": (float(variant_only.r_multiple_var.mean())
                                    if len(variant_only) else None),
    }


def target_response(runs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Section 6: per-representative response across the four targets."""
    table: dict[str, list[dict[str, Any]]] = {}
    for name in REPRESENTATIVES:
        rows = []
        for target in TARGETS:
            run = next(item for item in runs
                       if item["representative"] == name and item["target"] == target)
            metrics, yearly = run["metrics"], run["yearly"]
            positive_years = sum(1 for year in ("2021", "2022", "2023")
                                 if (yearly.get(year, {}).get("average_r") or 0) > 0)
            rows.append({
                "target": target, "profit_factor": metrics["profit_factor"],
                "average_r": metrics["average_r"], "total_r": metrics["total_r"],
                "max_drawdown_percent": metrics["max_drawdown_percent"],
                "trades": metrics["trades"], "trades_per_month": metrics["trades_per_month"],
                "positive_development_years": positive_years,
                "win_rate": metrics["win_rate"],
                "breakeven_win_rate_gross": run["breakeven_win_rate_gross"],
            })
        table[name] = rows
    return table


def target_shape(rows: list[dict[str, Any]]) -> str:
    """Descriptive topology of a four-point target response.

    Four collinear points do not form a neighbourhood grid, so the Phase 3B
    stability score is deliberately not used here.
    """
    values = [row["average_r"] for row in rows]
    positive = [value > 0 for value in values]
    ascending = all(left <= right for left, right in zip(values, values[1:]))
    descending = all(left >= right for left, right in zip(values, values[1:]))
    if not any(positive):
        return "NO ROBUST EXIT REGION"
    if ascending or descending:
        return "MONOTONIC TARGET DEPENDENCE"
    if sum(positive) == 1:
        return "NARROW TARGET PEAK"
    adjacent_positive = any(left and right for left, right in zip(positive, positive[1:]))
    return "BROAD STABLE REGION" if adjacent_positive else "NARROW TARGET PEAK"


def cross_representative(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Section 7: a target only matters if all three representatives agree."""
    rows = []
    for target in TARGETS:
        selected = [run for run in runs if run["target"] == target]
        years = ("2021", "2022", "2023")

        def positive(run: dict[str, Any], year: str) -> bool:
            return (run["yearly"].get(year, {}).get("average_r") or 0) > 0

        rows.append({
            "target": target,
            "representatives_profitable_overall": sum(1 for run in selected
                                                      if run["metrics"]["average_r"] > 0),
            "representatives_positive_2021": sum(1 for run in selected if positive(run, "2021")),
            "representatives_positive_2022": sum(1 for run in selected if positive(run, "2022")),
            "representatives_positive_2023": sum(1 for run in selected if positive(run, "2023")),
            "representatives_positive_all_years": sum(
                1 for run in selected if all(positive(run, year) for year in years)),
            "median_profit_factor": median(run["metrics"]["profit_factor"] for run in selected),
            "median_average_r": median(run["metrics"]["average_r"] for run in selected),
            "median_max_drawdown_percent": median(run["metrics"]["max_drawdown_percent"]
                                                  for run in selected),
            "median_trades": median(run["metrics"]["trades"] for run in selected),
        })
    return rows


def classify(runs: list[dict[str, Any]], cross: list[dict[str, Any]]) -> dict[str, Any]:
    """Section 10: derive A/B/C from the stated requirements, not from a high PF."""
    baseline = {run["representative"]: run for run in runs if run["target"] == BASELINE_TARGET}
    qualifying = []
    detail = {}
    for target in TARGETS:
        selected = [run for run in runs if run["target"] == target]
        all_positive_overall = all(run["metrics"]["average_r"] > 0 for run in selected)
        all_positive_2022 = all((run["yearly"].get("2022", {}).get("average_r") or 0) > 0
                                for run in selected)
        improved_2022 = all(
            (run["yearly"].get("2022", {}).get("average_r") or 0)
            > (baseline[run["representative"]]["yearly"].get("2022", {}).get("average_r") or 0)
            for run in selected)
        # Failure relocation: a year that was positive at the 3R baseline must
        # not become negative at this target.
        relocated = [
            {"representative": run["representative"], "year": year}
            for run in selected for year in ("2021", "2022", "2023")
            if (run["yearly"].get(year, {}).get("average_r") or 0) <= 0
            and (baseline[run["representative"]]["yearly"].get(year, {}).get("average_r") or 0) > 0
        ]
        retention = min(100.0 * run["metrics"]["trades"]
                        / baseline[run["representative"]]["metrics"]["trades"] for run in selected)
        passes = (all_positive_overall and all_positive_2022 and not relocated
                  and retention >= MINIMUM_RETENTION_PERCENT)
        detail[str(target)] = {
            "all_representatives_positive_overall": all_positive_overall,
            "all_representatives_positive_2022": all_positive_2022,
            "improved_2022_for_every_representative": improved_2022,
            "years_relocated_into_loss": relocated,
            "minimum_trade_retention_percent": round(retention, 2),
            "qualifies": passes,
        }
        if passes:
            qualifying.append(target)

    adjacent = [(left, right) for left, right in zip(TARGETS, TARGETS[1:])
                if left in qualifying and right in qualifying]
    any_improvement = any(detail[str(target)]["improved_2022_for_every_representative"]
                          for target in TARGETS if target != BASELINE_TARGET)

    if adjacent:
        letter, label = "A", "EXIT ARCHITECTURE PROMISING"
    elif qualifying or any_improvement:
        letter, label = "B", "EXIT HORIZON HELPS BUT REMAINS FRAGILE"
    else:
        letter, label = "C", "PB1 V1 STRUCTURE SHOULD BE REJECTED/REDESIGNED"

    # The 2022 sub-metric can improve while the whole period deteriorates, so
    # the verdict carries the counterweights explicitly rather than leaving the
    # label to imply that a shorter target is an improvement.
    by_representative = {
        name: {run["target"]: run["metrics"]["average_r"]
               for run in runs if run["representative"] == name}
        for name in REPRESENTATIVES
    }
    shorter = [target for target in TARGETS if target != BASELINE_TARGET]
    caveats = {
        "every_shorter_target_worse_overall_than_baseline": all(
            values[target] < values[BASELINE_TARGET]
            for values in by_representative.values() for target in shorter),
        "representative_target_combinations_positive_in_all_three_years": sum(
            1 for run in runs
            if all((run["yearly"].get(year, {}).get("average_r") or 0) > 0
                   for year in ("2021", "2022", "2023"))),
        "representative_target_combinations_tested": len(runs),
        "average_r_monotone_increasing_in_target": {
            name: all(values[left] <= values[right] for left, right in zip(TARGETS, TARGETS[1:]))
            for name, values in by_representative.items()},
        "best_target_per_representative": {
            name: max(values, key=values.get) for name, values in by_representative.items()},
        "best_target_sits_at_the_top_of_the_tested_range": all(
            max(values, key=values.get) == max(TARGETS) for values in by_representative.values()),
        "note": ("Average R rises monotonically with the target for every representative and is "
                 "still rising at 3.0R, so the predeclared window does not bracket an interior "
                 "optimum. Whether the response continues beyond 3R is untested here by design."),
    }
    return {
        "classification": letter, "label": label,
        "qualifying_targets": qualifying,
        "adjacent_qualifying_pairs": [list(pair) for pair in adjacent],
        "per_target": detail,
        "targets_with_all_three_representatives_positive_every_year": [
            row["target"] for row in cross if row["representatives_positive_all_years"] == 3],
        "caveats": caveats,
    }


def build() -> dict[str, Any]:
    runs = [run_one(name, parameters, target)
            for name, parameters in REPRESENTATIVES.items()
            for target in TARGETS]

    frames = {(run["representative"], run["target"]): run.pop("_frame") for run in runs}
    conversions = [
        {"representative": name, "target": target, "baseline_target": BASELINE_TARGET,
         **conversion_analysis(frames[(name, BASELINE_TARGET)], frames[(name, target)])}
        for name in REPRESENTATIVES for target in TARGETS if target != BASELINE_TARGET
    ]
    response = target_response(runs)
    cross = cross_representative(runs)

    report = {
        "phase": "PB1 Phase B.3 — DEVELOPMENT exit horizon sensitivity",
        "dataset_role": "DEVELOPMENT",
        "period": {"start": DEVELOPMENT_START.isoformat(), "end": DEVELOPMENT_END.isoformat()},
        "representatives": REPRESENTATIVES,
        "targets": list(TARGETS),
        "reward_multiple_source": (
            "BacktestConfig.risk_reward_ratio, applied by the audited engine's existing "
            "fixed-R target logic in engine/execution.py. PB1's own source and its frozen "
            "reward_multiple parameter (3.0) are unchanged; non-3R runs therefore execute at a "
            "target that differs from PB1's declared default by experimental configuration."
        ),
        "breakeven_win_rate_gross": {str(target): value for target, value in BREAKEVEN_WIN_RATE.items()},
        "runs": runs,
        "target_response": response,
        "target_shape": {name: target_shape(rows) for name, rows in response.items()},
        "cross_representative": cross,
        "conversion_analysis": conversions,
    }
    report["verdict"] = classify(runs, cross)
    REPORT.write_text(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    output = build()
    for name, rows in output["target_response"].items():
        print(f"{name} [{output['target_shape'][name]}]")
        for row in rows:
            print(f"   {row['target']}R  n={row['trades']:3d}  PF={row['profit_factor']:.3f}  "
                  f"avgR={row['average_r']:+.4f}  totR={row['total_r']:+7.2f}  "
                  f"DD={row['max_drawdown_percent']:5.2f}%  WR={row['win_rate']:5.2f}% "
                  f"(gross BE {row['breakeven_win_rate_gross']:.2f}%)  "
                  f"positive years={row['positive_development_years']}/3")
    print("\nverdict:", output["verdict"]["classification"], output["verdict"]["label"])
