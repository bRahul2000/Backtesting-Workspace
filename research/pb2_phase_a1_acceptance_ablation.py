"""PB2 Phase A.1 — acceptance gate selectivity and frequency audit.

A predeclared architecture ablation, not an optimization. Three variants are
run per direction and nothing else:

  A STRICT        the Phase A baseline: the acceptance bar must close beyond the
                  structure level *and* beyond the reclaim close.
  B LEVEL_HOLD    the separate acceptance bar remains, but only has to hold the
                  reclaimed level; the extra expansion requirement is dropped.
  C RECLAIM_ONLY  the separate acceptance bar is removed entirely and the reclaim
                  candle becomes the entry reference.

Every other rule — H1 context, structure lookback, displacement thresholds,
retest tolerance and window, stop bounds, RR — is untouched, and no parameter
value is searched. The variant is supplied as the fingerprinted
``acceptance_mode`` parameter, so a variant run can never be confused with the
baseline, and STRICT reproduces Phase A exactly (asserted before anything else).

DEVELOPMENT 2021-01-01 .. 2023-12-31 only. 2024-2026 are never requested.
"""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

import pandas as pd

from core.adapters.audited_engine import run_universal_backtest
from core.config import BacktestConfig, DatasetRole
from strategies.base_strategy import effective_parameter_payload, parameter_fingerprint
from strategies.btc_pb2_reclaim_acceptance import (
    ACCEPTANCE_LEVEL_HOLD, ACCEPTANCE_RECLAIM_ONLY, ACCEPTANCE_STRICT, PB2Parameters,
)
from strategies.registry import discover_builtin_strategies

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "btcusd_15m.csv"
REPORT = ROOT / "reports" / "pb2" / "phase_a1_acceptance_ablation.json"
SCRATCH_LEDGER = Path("/tmp") / "pb2_phase_a1_scratch_ledger.sqlite3"

DEVELOPMENT_START = pd.Timestamp("2021-01-01", tz="UTC")
DEVELOPMENT_END = pd.Timestamp("2023-12-31 23:45", tz="UTC")

COMPONENTS = {"LONG": "BTC_PB2_RECLAIM_LONG_V1", "SHORT": "BTC_PB2_RECLAIM_SHORT_V1"}
VARIANTS = {"A": ACCEPTANCE_STRICT, "B": ACCEPTANCE_LEVEL_HOLD, "C": ACCEPTANCE_RECLAIM_ONLY}
BASELINE_VARIANT = "A"

#: Phase A stored values. Variant A must reproduce these or the run aborts.
PHASE_A_BASELINE = {
    "LONG": {"closed_trades": 29, "profit_factor": 1.8656360038448085, "average_r": 0.5410},
    "SHORT": {"closed_trades": 14, "profit_factor": 0.2309911155042199, "average_r": -0.7143},
}

FUNNEL_STAGES = ("displacement_detected", "retest_detected", "reclaim_confirmed",
                 "acceptance_evaluated", "acceptance_confirmed", "acceptance_failed",
                 "risk_evaluated", "risk_rejected", "pending_created", "pending_expired",
                 "trade_entered", "trade_exited")
ACCEPTANCE_STAGES = ("acceptance_evaluated", "acceptance_confirmed", "acceptance_failed")
NOT_APPLICABLE = "NOT_APPLICABLE_ARCHITECTURE_ABLATION"

SAMPLE_BANDS = ((30, "INSUFFICIENT"), (60, "VERY_SMALL"), (120, "SMALL"),
                (250, "MODERATE"), (10 ** 9, "SUBSTANTIAL"))

#: How far below the baseline's Avg R the trades a loosened variant adds must
#: sit before the gate counts as materially selective rather than merely tighter.
MATERIAL_AVERAGE_R_MARGIN = 0.25


def _config(strategy_id: str, mode: str) -> BacktestConfig:
    if DEVELOPMENT_END >= pd.Timestamp("2024-01-01", tz="UTC"):
        raise ValueError("PB2 Phase A.1 is DEVELOPMENT-only; 2024-2026 must never be requested.")
    return BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD", strategy_id=strategy_id,
        timeframe="15m", higher_timeframes=("1h",),
        start_date=DEVELOPMENT_START, end_date=DEVELOPMENT_END,
        dataset_role=DatasetRole.DEVELOPMENT,
        strategy_parameters={"acceptance_mode": mode},
    )


def _profit_factor(frame: pd.DataFrame) -> float | None:
    profit = frame.loc[frame.pnl > 1e-9, "pnl"].sum()
    loss = frame.loc[frame.pnl < -1e-9, "pnl"].sum()
    return float(profit / abs(loss)) if loss else (float("inf") if profit else None)


def _losing_streak(frame: pd.DataFrame) -> int:
    worst = current = 0
    for pnl in frame.sort_values("exit_time").pnl:
        current = current + 1 if pnl < -1e-9 else 0
        worst = max(worst, current)
    return worst


def _sample_band(trades: int) -> str:
    for threshold, label in SAMPLE_BANDS:
        if trades < threshold:
            return label
    return "SUBSTANTIAL"


def _year_block(frame: pd.DataFrame) -> dict[str, Any]:
    return {"trades": int(len(frame)), "profit_factor": _profit_factor(frame),
            "average_r": float(frame.r_multiple.mean()) if len(frame) else None,
            "total_r": float(frame.r_multiple.sum())}


def run_variant(label: str, strategy_id: str, variant: str, mode: str) -> dict[str, Any]:
    descriptor = discover_builtin_strategies().get(strategy_id)
    result = run_universal_backtest(DATA, _config(strategy_id, mode), ledger_path=SCRATCH_LEDGER)

    frame = pd.DataFrame(result.trade_log)
    if not frame.empty:
        for column in ("signal_time", "entry_time", "exit_time"):
            frame[column] = pd.to_datetime(frame[column], utc=True)
        if frame.exit_time.max() > DEVELOPMENT_END:
            raise ValueError(f"{label}/{variant} produced a trade outside DEVELOPMENT.")
        frame["year"] = frame.entry_time.dt.year
        frame["holding_minutes"] = (frame.exit_time - frame.entry_time).dt.total_seconds() / 60
        # A pending stop order's signal_time is the bar after the candle that
        # created it, so step back one bar to reach that candle's diagnostics.
        frame["trigger_time"] = frame.signal_time - pd.Timedelta(minutes=15)
        geometry = pd.DataFrame([
            {"trigger_time": pd.Timestamp(event["timestamp"]), **(event.get("metadata") or {})}
            for event in result.signal_diagnostics if event["stage"] == "pending_created"
        ])
        if not geometry.empty:
            frame = frame.join(geometry.set_index("trigger_time"), on="trigger_time",
                               rsuffix="_setup")

    stages: dict[str, int] = {}
    for event in result.signal_diagnostics:
        stages[event["stage"]] = stages.get(event["stage"], 0) + 1

    funnel: dict[str, Any] = {}
    for stage in FUNNEL_STAGES:
        if mode == ACCEPTANCE_RECLAIM_ONLY and stage in ACCEPTANCE_STAGES:
            funnel[stage] = NOT_APPLICABLE
        else:
            funnel[stage] = stages.get(stage, 0)
    funnel["open_at_end"] = len(result.open_positions_at_end)
    funnel["engine_order_events"] = result.execution_diagnostics.get("order_events", {})

    return {
        "component": label, "variant": variant, "acceptance_mode": mode,
        "strategy_id": strategy_id,
        "strategy_fingerprint": result.strategy_fingerprint,
        "parameter_fingerprint": result.parameter_fingerprint,
        "metrics": {
            "trades": int(result.total_trades),
            "trades_per_month": float(result.trades_per_month),
            "win_rate": float(result.win_rate),
            "profit_factor": result.profit_factor,
            "average_r": float(result.average_r),
            "total_r": float(frame.r_multiple.sum()) if not frame.empty else 0.0,
            "pnl": float(result.pnl),
            "max_drawdown_percent": float(result.max_drawdown_percent),
            "max_losing_streak": int(result.max_losing_streak),
            "average_holding_minutes": float(frame.holding_minutes.mean()) if not frame.empty else None,
            "median_holding_minutes": float(frame.holding_minutes.median()) if not frame.empty else None,
        },
        "sample_band": _sample_band(int(result.total_trades)),
        "yearly": {str(year): _year_block(group) for year, group in frame.groupby("year")}
                  if not frame.empty else {},
        "funnel": funnel,
        "_frame": frame,
        "_failed_acceptance_structures": sorted({
            (event.get("metadata") or {}).get("displacement_time")
            for event in result.signal_diagnostics if event["stage"] == "acceptance_failed"
        } - {None}),
    }


def incremental_analysis(baseline: pd.DataFrame, variant: pd.DataFrame) -> dict[str, Any]:
    """Section 9: compare actual executions, keyed by the originating structure.

    Variants can enter the same structure on a different bar (RECLAIM_ONLY fires
    a bar earlier than STRICT), so matching on entry time alone would misread
    those as new trades. The displacement timestamp identifies the structure
    across variants; entry time then separates "same structure, different entry"
    from genuinely additional structures.
    """
    def keyed(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty or "displacement_time" not in frame:
            return pd.DataFrame(columns=["displacement_time", "entry_time", "r_multiple", "pnl"])
        return frame[["displacement_time", "entry_time", "r_multiple", "pnl"]].copy()

    left, right = keyed(baseline), keyed(variant)
    left_keys, right_keys = set(left.displacement_time), set(right.displacement_time)
    shared = left_keys & right_keys
    added_keys = right_keys - left_keys
    dropped_keys = left_keys - right_keys

    shared_left = left[left.displacement_time.isin(shared)]
    shared_right = right[right.displacement_time.isin(shared)]
    same_structure_different_entry = int(sum(
        1 for key in shared
        if not left.loc[left.displacement_time == key, "entry_time"].isin(
            right.loc[right.displacement_time == key, "entry_time"]).all()))

    added = right[right.displacement_time.isin(added_keys)]
    dropped = left[left.displacement_time.isin(dropped_keys)]
    added_winners = added[added.pnl > 1e-9]
    added_losers = added[added.pnl < -1e-9]
    added_profit = float(added_winners.pnl.sum())
    added_loss = float(added_losers.pnl.sum())

    return {
        "shared_structures": len(shared),
        "same_structure_different_entry_time": same_structure_different_entry,
        "shared_total_r_baseline": float(shared_left.r_multiple.sum()),
        "shared_total_r_variant": float(shared_right.r_multiple.sum()),
        "trades_added": int(len(added)),
        "winners_added": int(len(added_winners)),
        "losers_added": int(len(added_losers)),
        "total_r_added": float(added.r_multiple.sum()),
        "average_r_of_incremental_trades": float(added.r_multiple.mean()) if len(added) else None,
        "profit_factor_of_incremental_trades": (
            float(added_profit / abs(added_loss)) if added_loss else
            (float("inf") if added_profit else None)),
        "structures_lost_to_downstream_availability": int(len(dropped)),
        "total_r_lost_to_downstream_availability": float(dropped.r_multiple.sum()),
    }


def rejection_cohort(baseline_run: dict[str, Any], variant_runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Section 10: setups that reclaimed but failed STRICT acceptance.

    Their displacement timestamps are looked up in each other variant's executed
    trades, which answers directly whether the strict gate discards mostly bad
    setups or potentially useful ones.
    """
    cohort = set(baseline_run["_failed_acceptance_structures"])
    output: dict[str, Any] = {"cohort_size": len(cohort)}
    for variant, run in variant_runs.items():
        frame = run["_frame"]
        if frame.empty or "displacement_time" not in frame:
            output[variant] = {"entries": 0}
            continue
        taken = frame[frame.displacement_time.isin(cohort)]
        winners = taken[taken.pnl > 1e-9]
        losers = taken[taken.pnl < -1e-9]
        output[variant] = {
            "entries": int(len(taken)), "winners": int(len(winners)), "losers": int(len(losers)),
            "average_r": float(taken.r_multiple.mean()) if len(taken) else None,
            "total_r": float(taken.r_multiple.sum()),
        }
    return output


def classify(component_runs: dict[str, dict[str, Any]], incremental: dict[str, Any]) -> dict[str, Any]:
    """Section 12/13: architecture evidence, deliberately not a PF beauty contest."""
    baseline = component_runs[BASELINE_VARIANT]["metrics"]
    bands = {variant: run["sample_band"] for variant, run in component_runs.items()}
    positive_years = {
        variant: sum(1 for year in ("2021", "2022", "2023")
                     if (run["yearly"].get(year, {}).get("average_r") or 0) > 0)
        for variant, run in component_runs.items()
    }

    adequate = {variant for variant, band in bands.items() if band != "INSUFFICIENT"}
    improves = {
        variant for variant in ("B", "C")
        if variant in adequate
        and (component_runs[variant]["metrics"]["average_r"] or 0) > 0
        and (incremental[variant]["average_r_of_incremental_trades"] or 0) > 0
        and positive_years[variant] >= 2
    }

    # Whether the gate earns its place is a question about the setups it
    # *rejects*, so the evidence is the incremental population, not the
    # baseline's own trade count: a gate can be demonstrably selective while the
    # surviving sample is still too small to claim an edge from. The incremental
    # trades must therefore be interpretable in aggregate and materially worse
    # than the baseline, and the baseline itself must at least be positive
    # across most of DEVELOPMENT so a losing strategy never "earns" its filter.
    incremental_trades = sum(incremental[variant]["trades_added"] for variant in ("B", "C"))
    incremental_margins = [
        baseline["average_r"] - (incremental[variant]["average_r_of_incremental_trades"] or 0)
        for variant in ("B", "C") if incremental[variant]["trades_added"] >= 10
    ]
    strict_earns = (
        baseline["average_r"] > 0
        and positive_years[BASELINE_VARIANT] >= 2
        and incremental_trades >= 30
        and len(incremental_margins) == 2
        and all(margin >= MATERIAL_AVERAGE_R_MARGIN for margin in incremental_margins)
    )

    if not adequate:
        letter, label = "D", "ARCHITECTURE STILL TOO SPARSE / UNRESOLVED"
    elif "C" in improves and "B" in improves:
        letter, label = "C", "SEPARATE ACCEPTANCE BAR IS NOT JUSTIFIED"
    elif "B" in improves:
        letter, label = "B", "LEVEL-HOLD ACCEPTANCE IS BETTER BALANCED"
    elif strict_earns:
        letter, label = "A", "STRICT ACCEPTANCE EARNS ITS PLACE"
    else:
        letter, label = "D", "ARCHITECTURE STILL TOO SPARSE / UNRESOLVED"

    return {
        "classification": letter, "label": label,
        "sample_bands": bands, "positive_years": positive_years,
        "variants_with_interpretable_sample": sorted(adequate),
        "variants_improving_on_evidence": sorted(improves),
        "strict_acceptance_earns_its_place": strict_earns,
        "incremental_trades_examined": incremental_trades,
        "incremental_average_r_margins": incremental_margins,
        "rule": ("A loosened variant counts as an improvement only if its sample is at least "
                 "VERY_SMALL, its overall Avg R is positive, the trades it adds over the "
                 "baseline are themselves positive on average, and at least two DEVELOPMENT "
                 "years are positive. Strict acceptance earns its place only if the baseline "
                 "is positive with at least two positive years and both loosenings add at "
                 f"least 10 trades each (>=30 combined) whose Avg R is at least "
                 f"{MATERIAL_AVERAGE_R_MARGIN}R below the baseline's. Highest PF never decides, "
                 "and neither verdict claims the surviving sample is large enough to trade."),
    }


def build() -> dict[str, Any]:
    runs: dict[str, dict[str, dict[str, Any]]] = {}
    for label, strategy_id in COMPONENTS.items():
        runs[label] = {variant: run_variant(label, strategy_id, variant, mode)
                       for variant, mode in VARIANTS.items()}
        baseline = runs[label][BASELINE_VARIANT]["metrics"]
        expected = PHASE_A_BASELINE[label]
        if baseline["trades"] != expected["closed_trades"] \
                or abs(baseline["profit_factor"] - expected["profit_factor"]) > 1e-12 \
                or abs(baseline["average_r"] - expected["average_r"]) > 1e-4:
            raise ValueError(
                f"BASELINE REPRODUCTION FAILED for {label}: variant A produced "
                f"{baseline['trades']} trades / PF {baseline['profit_factor']} / "
                f"Avg R {baseline['average_r']}, expected {expected}.")

    report: dict[str, Any] = {
        "phase": "PB2 Phase A.1 — acceptance gate selectivity and frequency audit",
        "experiment": "predeclared architecture ablation; no parameter value was searched",
        "dataset_role": "DEVELOPMENT",
        "period": {"start": DEVELOPMENT_START.isoformat(), "end": DEVELOPMENT_END.isoformat()},
        "variants": {variant: mode for variant, mode in VARIANTS.items()},
        "baseline_reproduction": {label: PHASE_A_BASELINE[label] for label in COMPONENTS},
        "parameter_fingerprints": {
            variant: parameter_fingerprint(effective_parameter_payload(
                discover_builtin_strategies().get(COMPONENTS["LONG"]), {"acceptance_mode": mode}))
            for variant, mode in VARIANTS.items()
        },
        "baseline_parameters": asdict(PB2Parameters()),
        "components": {},
    }

    years_seen: set[int] = set()
    for label, component_runs in runs.items():
        frames = {variant: run["_frame"] for variant, run in component_runs.items()}
        for frame in frames.values():
            if not frame.empty:
                years_seen |= set(int(year) for year in frame.year.unique())
        incremental = {variant: incremental_analysis(frames[BASELINE_VARIANT], frames[variant])
                       for variant in ("B", "C")}
        cohort = rejection_cohort(component_runs[BASELINE_VARIANT],
                                  {variant: component_runs[variant] for variant in ("B", "C")})
        verdict = classify(component_runs, incremental)
        report["components"][label] = {
            "runs": {variant: {key: value for key, value in run.items()
                               if not key.startswith("_")}
                     for variant, run in component_runs.items()},
            "incremental_analysis": incremental,
            "strict_rejection_cohort": cohort,
            "architecture_decision": verdict,
        }

    if years_seen - {2021, 2022, 2023}:
        raise ValueError(f"PB2 Phase A.1 touched a year outside DEVELOPMENT: {sorted(years_seen)}")
    report["years_present"] = sorted(years_seen)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    output = build()
    for label, component in output["components"].items():
        print(f"=== {label} ===")
        for variant, run in component["runs"].items():
            metrics = run["metrics"]
            print(f"  {variant} {run['acceptance_mode']:13s} n={metrics['trades']:3d} "
                  f"({run['sample_band']:12s}) PF={metrics['profit_factor']} "
                  f"avgR={metrics['average_r']:+.4f} totR={metrics['total_r']:+7.2f} "
                  f"DD={metrics['max_drawdown_percent']:.2f}%")
        print(f"  -> {component['architecture_decision']['classification']} "
              f"{component['architecture_decision']['label']}")
