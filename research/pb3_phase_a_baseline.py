"""PB3 Phase A — DEVELOPMENT-only baseline for the confirmed-pivot LONG component.

Runs exactly one primary backtest on DEVELOPMENT (2021-01-01 .. 2023-12-31). No
alternate parameters, no architecture variants, no optimization, and no
VALIDATION or FORWARD_VALIDATION access of any kind: the window is asserted
before anything is executed and every produced trade timestamp is checked
against it afterwards.

The runner also re-proves the no-lookahead property on the real dataset by
checking that every breakout decision referenced a pivot whose confirmation
timestamp was strictly earlier than the deciding bar.

Everything here is reporting. The strategy, the audited execution engine and the
diagnostics infrastructure are untouched.
"""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core.adapters.audited_engine import run_universal_backtest
from core.config import BacktestConfig, DatasetRole
from strategies.base_strategy import effective_parameter_payload, parameter_fingerprint
from strategies.btc_pb3_pivot_acceptance_long import PB3Parameters
from strategies.registry import discover_builtin_strategies

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "btcusd_15m.csv"
REPORT = ROOT / "reports" / "pb3" / "phase_a_baseline.json"
SCRATCH_LEDGER = Path("/tmp") / "pb3_phase_a_scratch_ledger.sqlite3"

STRATEGY_ID = "BTC_PB3_PIVOT_ACCEPTANCE_LONG_V1"
DEVELOPMENT_START = pd.Timestamp("2021-01-01", tz="UTC")
DEVELOPMENT_END = pd.Timestamp("2023-12-31 23:45", tz="UTC")
DEVELOPMENT_YEARS = (2021, 2022, 2023)

# Historical context only (section 22). PB2 LONG is REJECTED and closed; nothing
# about PB3 is changed because of this number in Phase A.
PB2_LONG_BASELINE = {"closed_trades": 29, "trades_per_month": 0.91,
                     "source": "reports/pb2/RESEARCH_SUMMARY.md"}

FUNNEL_STAGES = (
    "context_evaluated", "context_rejected",
    "pivot_confirmed", "pivot_expired",
    "breakout_evaluated", "breakout_rejected", "breakout_confirmed",
    "waiting_retest", "retest_detected", "retest_expired", "structure_invalidated",
    "reclaim_evaluated", "reclaim_rejected", "reclaim_confirmed",
    "acceptance_evaluated", "acceptance_failed", "acceptance_confirmed",
    "risk_evaluated", "risk_rejected",
    "pending_created", "pending_expired", "pending_cancelled",
    "trade_entered", "trade_exited",
)

# Section 26: fixed bucket edges over the setup geometry PB3 recorded when it
# created each pending order. Declared before the run so no edge can be chosen
# to flatter a result.
DESCRIPTIVE_BUCKETS = {
    "pivot_age_bars": [0, 5, 9, 15, np.inf],
    "breakout_range_atr": [0.0, 1.25, 1.50, 2.00, np.inf],
    "breakout_distance_atr": [0.0, 0.25, 0.50, 1.00, np.inf],
    "bars_to_retest": [0, 1, 2, 3, np.inf],
    "retest_overshoot_atr": [-np.inf, -0.10, 0.0, 0.10, np.inf],
    "acceptance_distance_atr": [0.0, 0.25, 0.50, 1.00, np.inf],
    "stop_atr": [0.0, 1.00, 1.50, 2.00, 2.50],
}

SAMPLE_BANDS = (
    (30, "INSUFFICIENT"), (60, "VERY_SMALL"), (120, "SMALL"), (250, "MODERATE"),
)


def _config() -> BacktestConfig:
    """Section 3: the DEVELOPMENT boundary is enforced before anything executes."""
    if DEVELOPMENT_START < pd.Timestamp("2021-01-01", tz="UTC"):
        raise ValueError("PB3 Phase A must start at the DEVELOPMENT boundary.")
    if DEVELOPMENT_END >= pd.Timestamp("2024-01-01", tz="UTC"):
        raise ValueError("PB3 Phase A is DEVELOPMENT-only; 2024-2026 must never be requested.")
    return BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD", strategy_id=STRATEGY_ID,
        timeframe="15m", higher_timeframes=("1h",),
        start_date=DEVELOPMENT_START, end_date=DEVELOPMENT_END,
        dataset_role=DatasetRole.DEVELOPMENT,
    )


def _profit_factor(frame: pd.DataFrame) -> float | None:
    profit = frame.loc[frame.pnl > 1e-9, "pnl"].sum()
    loss = frame.loc[frame.pnl < -1e-9, "pnl"].sum()
    return float(profit / abs(loss)) if loss else (float("inf") if profit else None)


def _max_drawdown_percent(frame: pd.DataFrame, starting_balance: float = 10_000.0) -> float:
    balance = peak = starting_balance
    worst = 0.0
    for pnl in frame.sort_values("exit_time").pnl:
        balance += pnl
        peak = max(peak, balance)
        worst = max(worst, (peak - balance) / peak * 100 if peak > 0 else 0.0)
    return float(worst)


def _year_block(frame: pd.DataFrame) -> dict[str, Any]:
    return {"trades": int(len(frame)),
            "win_rate": float(100 * (frame.pnl > 1e-9).mean()) if len(frame) else None,
            "profit_factor": _profit_factor(frame),
            "average_r": float(frame.r_multiple.mean()) if len(frame) else None,
            "total_r": float(frame.r_multiple.sum()),
            "max_drawdown_percent_within_year": _max_drawdown_percent(frame)}


def _excursion(frame: pd.DataFrame) -> dict[str, Any]:
    """Corrected normalization: excursion price distance / initial stop price distance."""
    def stats(column: str) -> dict[str, Any]:
        values = frame[column].dropna()
        if values.empty:
            return {"n": 0}
        return {"n": int(len(values)), "mean": float(values.mean()),
                "median": float(values.median()), "p75": float(values.quantile(.75)),
                "p90": float(values.quantile(.90)), "p95": float(values.quantile(.95)),
                "max": float(values.max())}
    return {"model": "BAR_BASED_APPROXIMATION", "mfe_r": stats("mfe_r"), "mae_r": stats("mae_r"),
            "note": ("Excursions use whole entry-to-exit-bar OHLC, so they include price action "
                     "inside the exit bar beyond the modelled fill; they are not an exact tick "
                     "path and must not be read as achievable pre-exit movement.")}


def _setup_geometry(result: Any) -> pd.DataFrame:
    """Geometry PB3 logged for each pending order it created, keyed to the trade.

    A pending stop order's signal_time is the bar after the acceptance candle
    (engine/execution.py adds 15m), so the join steps back one bar.
    """
    rows = []
    for event in result.signal_diagnostics:
        if event["stage"] != "pending_created":
            continue
        metadata = event.get("metadata") or {}
        rows.append({"acceptance_time": pd.Timestamp(event["timestamp"]), **metadata})
    frame = pd.DataFrame(rows)
    return frame.set_index("acceptance_time") if not frame.empty else frame


def _bucket_table(frame: pd.DataFrame, column: str, edges: list[float]) -> list[dict[str, Any]]:
    if frame.empty or column not in frame:
        return []
    labels = pd.cut(frame[column], bins=edges, include_lowest=True)
    rows = []
    for interval, group in frame.groupby(labels, observed=True):
        rows.append({"bucket": str(interval), "trades": int(len(group)),
                     "profit_factor": _profit_factor(group),
                     "average_r": float(group.r_multiple.mean()),
                     "win_rate": float(100 * (group.pnl > 1e-9).mean())})
    return rows


def _no_lookahead_proof(result: Any) -> dict[str, Any]:
    """Section 17, re-proved on the real dataset rather than only on fixtures.

    Every breakout decision records the pivot it consulted together with that
    pivot's confirmation timestamp. If registration ever leaked into the same
    bar, at least one decision would show confirmation >= decision time.
    """
    decisions = violations = 0
    minimum_lag_bars: int | None = None
    for event in result.signal_diagnostics:
        if event["stage"] not in ("breakout_evaluated", "breakout_confirmed"):
            continue
        metadata = event.get("metadata") or {}
        confirmation = metadata.get("pivot_confirmation_timestamp")
        if confirmation is None:
            continue
        decisions += 1
        confirmed_at = pd.Timestamp(confirmation)
        decided_at = pd.Timestamp(event["timestamp"])
        if confirmed_at >= decided_at:
            violations += 1
        lag = int((decided_at - confirmed_at) / pd.Timedelta(minutes=15))
        minimum_lag_bars = lag if minimum_lag_bars is None else min(minimum_lag_bars, lag)
    return {
        "breakout_decisions_checked": decisions,
        "decisions_using_a_pivot_not_yet_confirmed": violations,
        "minimum_confirmation_to_decision_lag_bars": minimum_lag_bars,
        "holds": violations == 0 and decisions > 0,
        "rule": ("Every breakout decision must reference a pivot whose confirmation timestamp "
                 "is strictly earlier than the deciding bar. A pivot needs both right-side bars, "
                 "and PB3 registers it only after the bar's own decisions, so the minimum lag "
                 "is one bar."),
    }


def _funnel(result: Any, frame: pd.DataFrame) -> dict[str, Any]:
    stages: dict[str, int] = {}
    reasons: dict[str, int] = {}
    tradeable_pendings = 0
    eligible_pivots: set[str] = set()
    breakout_pivots: set[str] = set()
    for event in result.signal_diagnostics:
        stage = event["stage"]
        stages[stage] = stages.get(stage, 0) + 1
        metadata = event.get("metadata") or {}
        if event.get("passed") is False and event.get("reason"):
            key = f"{stage}/{event['reason']}"
            reasons[key] = reasons.get(key, 0) + 1
        if stage == "breakout_evaluated" and metadata.get("pivot_timestamp"):
            eligible_pivots.add(metadata["pivot_timestamp"])
        if stage == "breakout_confirmed" and metadata.get("pivot_timestamp"):
            breakout_pivots.add(metadata["pivot_timestamp"])
        if stage == "pending_created" and not metadata.get("before_trade_start"):
            tradeable_pendings += 1

    counts = {stage: stages.get(stage, 0) for stage in FUNNEL_STAGES}
    order_events = result.execution_diagnostics.get("order_events", {})
    return {
        "counts": counts,
        "confirmed_pivots": counts["pivot_confirmed"],
        # A confirmed pivot is "eligible" once PB3 actually consulted it for a
        # breakout: it was the latest pivot, still inside the age cap, on a bar
        # where H1 context qualified and no structure was already in progress.
        "eligible_pivots": len(eligible_pivots),
        "pivots_that_produced_a_breakout": len(breakout_pivots),
        "risk_valid_setups": counts["risk_evaluated"] - counts["risk_rejected"],
        "pending_created_in_tradeable_window": tradeable_pendings,
        "engine_order_events": order_events,
        "entries": counts["trade_entered"],
        "exits": counts["trade_exited"],
        "expired_pendings": counts["pending_expired"],
        "reconciliation": {
            "tradeable_pendings": tradeable_pendings,
            "engine_triggered_plus_expired": sum(
                int(value) for key, value in order_events.items()
                if key.lower() in ("triggered", "expired", "cancelled")),
            "strategy_pending_expired": counts["pending_expired"],
            "engine_trade_entered": counts["trade_entered"],
            "engine_trade_exited": counts["trade_exited"],
            "closed_trades": int(len(frame)),
            "note": ("pending_created counts every rule decision, including signals emitted "
                     "before the warmup boundary that the engine always discards; the "
                     "tradeable-window count is what reaches the order book."),
        },
        "largest_rejection_reasons": dict(sorted(reasons.items(), key=lambda item: -item[1])[:15]),
    }


def _sample_band(trades: int) -> str:
    for threshold, label in SAMPLE_BANDS:
        if trades < threshold:
            return label
    return "SUBSTANTIAL"


def _research_policy(trades: int) -> str:
    if trades < 60:
        return "DO_NOT_OPTIMIZE_PB3"
    if trades < 120:
        return "NARROW_ARCHITECTURE_DIAGNOSIS_ONLY"
    return "ELIGIBLE_FOR_A_CONTROLLED_DEVELOPMENT_STABILITY_SEARCH_SUBJECT_TO_YEAR_BEHAVIOUR"


def _year_consistency(frame: pd.DataFrame) -> dict[str, Any]:
    """Section 24. Descriptive only — Phase A makes no cross-regime claim."""
    total_trades = int(len(frame))
    gross_positive_r = float(frame.loc[frame.r_multiple > 0, "r_multiple"].sum())
    years: dict[str, Any] = {}
    for year in DEVELOPMENT_YEARS:
        group = frame[frame.year == year]
        positive_r = float(group.loc[group.r_multiple > 0, "r_multiple"].sum())
        years[str(year)] = {
            "trades": int(len(group)),
            "percent_of_trades": float(100 * len(group) / total_trades) if total_trades else 0.0,
            "total_r": float(group.r_multiple.sum()),
            "positive_r": positive_r,
            "percent_of_gross_positive_r": (float(100 * positive_r / gross_positive_r)
                                            if gross_positive_r > 0 else 0.0),
        }
    positive_years = [year for year, block in years.items() if block["total_r"] > 0]
    negative_years = [year for year, block in years.items() if block["total_r"] < 0]
    concentrated = [year for year, block in years.items()
                    if block["percent_of_trades"] >= 50.0
                    or block["percent_of_gross_positive_r"] >= 60.0]
    return {
        "years": years,
        "positive_development_years": f"{len(positive_years)}/3",
        "positive_years": positive_years,
        "negative_years": negative_years,
        "one_year_concentration": bool(concentrated),
        "concentrated_years": concentrated,
        "negative_year_dependency": bool(negative_years),
        "flag_rule": ("one_year_concentration when a single year holds >= 50% of trades or "
                      ">= 60% of gross positive R; negative_year_dependency when any "
                      "DEVELOPMENT year has negative total R."),
        "caveat": "Descriptive only. Phase A makes no cross-regime claim.",
    }


def classify(metrics: dict[str, Any], consistency: dict[str, Any]) -> dict[str, Any]:
    """Section 27. Sample size takes precedence over every performance reading."""
    trades = metrics["closed_trades"]
    average_r = metrics["average_r"]
    if trades < 60:
        label = "INSUFFICIENT_SAMPLE"
    elif average_r > 0.10 and len(consistency["positive_years"]) >= 2:
        label = "PROMISING_SAMPLE"
    elif average_r < -0.10:
        label = "NEGATIVE_SAMPLE"
    else:
        label = "NEAR_BREAKEVEN_SAMPLE"
    return {
        "classification": label,
        "rule": ("closed trades < 60 -> INSUFFICIENT_SAMPLE regardless of profit factor. "
                 "Otherwise: Avg R > +0.10 with at least 2 of 3 positive DEVELOPMENT years -> "
                 "PROMISING_SAMPLE; Avg R < -0.10 -> NEGATIVE_SAMPLE; else "
                 "NEAR_BREAKEVEN_SAMPLE. Descriptive only — Phase A claims nothing about "
                 "stability across regimes."),
        "closed_trades": trades, "average_r": average_r,
        "positive_development_years": consistency["positive_development_years"],
    }


def build() -> dict[str, Any]:
    descriptor = discover_builtin_strategies().get(STRATEGY_ID)
    payload = effective_parameter_payload(descriptor, {})
    if payload != asdict(PB3Parameters()):
        raise ValueError("PB3 Phase A must run at frozen defaults.")
    config = _config()
    if config.risk_reward_ratio != PB3Parameters().reward_multiple:
        raise ValueError("Phase A requires the fixed 3.0R exit horizon.")

    result = run_universal_backtest(DATA, config, ledger_path=SCRATCH_LEDGER)

    frame = pd.DataFrame(result.trade_log)
    for column in ("signal_time", "entry_time", "exit_time"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    if not frame.empty:
        earliest, latest = frame.entry_time.min(), frame.exit_time.max()
        if earliest < DEVELOPMENT_START or latest > DEVELOPMENT_END:
            raise ValueError(f"PB3 produced a trade outside DEVELOPMENT ({earliest} .. {latest}).")
        frame["year"] = frame.entry_time.dt.year
        if set(frame.year.unique()) - set(DEVELOPMENT_YEARS):
            raise ValueError(f"PB3 touched a year outside DEVELOPMENT: {sorted(frame.year.unique())}")
        frame["holding_minutes"] = (frame.exit_time - frame.entry_time).dt.total_seconds() / 60
        frame["acceptance_time"] = frame.signal_time - pd.Timedelta(minutes=15)
        geometry = _setup_geometry(result)
        if not geometry.empty:
            frame = frame.join(geometry, on="acceptance_time", rsuffix="_setup")

    proof = _no_lookahead_proof(result)
    if not proof["holds"]:
        raise ValueError(f"PB3 no-lookahead proof failed: {proof}")

    metrics = {
        "closed_trades": int(result.total_trades),
        "total_entries": int(result.total_entries),
        "open_at_end": len(result.open_positions_at_end),
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
    }
    consistency = _year_consistency(frame) if not frame.empty else {}

    report = {
        "phase": "PB3 Phase A — confirmed pivot reclaim & acceptance baseline (LONG only)",
        "strategy_id": STRATEGY_ID,
        "dataset_role": "DEVELOPMENT",
        "period": {"start": DEVELOPMENT_START.isoformat(), "end": DEVELOPMENT_END.isoformat()},
        "years_present": sorted(int(year) for year in frame.year.unique()) if not frame.empty else [],
        "strategy_fingerprint": result.strategy_fingerprint,
        "parameter_fingerprint": result.parameter_fingerprint,
        "parameter_fingerprint_recomputed": parameter_fingerprint(payload),
        "dataset_fingerprint": result.dataset_fingerprint,
        "baseline_parameters": payload,
        "no_lookahead_proof": proof,
        "metrics": metrics,
        "yearly": {str(year): _year_block(group) for year, group in frame.groupby("year")}
                  if not frame.empty else {},
        "year_consistency": consistency,
        "funnel": _funnel(result, frame),
        "frequency_versus_pb2_long": {
            "pb3_closed_trades": metrics["closed_trades"],
            "pb3_trades_per_month": metrics["trades_per_month"],
            "pb2_long_historical": PB2_LONG_BASELINE,
            "note": ("Historical context only. PB2 is REJECTED and closed; nothing about PB3 "
                     "is changed because of this comparison in Phase A."),
        },
        "sample_size": {
            "closed_trades": metrics["closed_trades"],
            "band": _sample_band(metrics["closed_trades"]),
            "research_policy": _research_policy(metrics["closed_trades"]),
            "bands": "<30 INSUFFICIENT, 30-59 VERY_SMALL, 60-119 SMALL, 120-249 MODERATE, >=250 SUBSTANTIAL",
            "policy_rule": ("<60 do not optimize PB3; 60-119 only narrowly scoped architecture "
                            "diagnosis; >=120 eligible for a controlled DEVELOPMENT stability "
                            "search depending on year-by-year behaviour. Not overridable by PF."),
        },
        "excursion": _excursion(frame) if not frame.empty else {},
        "descriptive_buckets": {column: _bucket_table(frame, column, edges)
                                for column, edges in DESCRIPTIVE_BUCKETS.items()}
                               if not frame.empty else {},
        "data_exposure": {
            "development_only": True,
            "validation_2024_accessed": False,
            "forward_validation_2025_2026_accessed": False,
        },
    }
    report["baseline_classification"] = classify(metrics, consistency) if not frame.empty else {
        "classification": "INSUFFICIENT_SAMPLE", "closed_trades": 0}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, default=str))
    report["_frame"] = frame
    return report


if __name__ == "__main__":
    output = build()
    metrics = output["metrics"]
    print(f"strategy_fingerprint={output['strategy_fingerprint']}")
    print(f"parameter_fingerprint={output['parameter_fingerprint']}")
    print(f"no_lookahead_holds={output['no_lookahead_proof']['holds']} "
          f"checked={output['no_lookahead_proof']['breakout_decisions_checked']} "
          f"min_lag_bars={output['no_lookahead_proof']['minimum_confirmation_to_decision_lag_bars']}")
    print(f"trades={metrics['closed_trades']} entries={metrics['total_entries']} "
          f"open_at_end={metrics['open_at_end']} per_month={metrics['trades_per_month']:.2f} "
          f"win={metrics['win_rate']:.2f}% PF={metrics['profit_factor']} "
          f"avgR={metrics['average_r']:+.4f} totR={metrics['total_r']:+.2f} "
          f"DD={metrics['max_drawdown_percent']:.2f}%")
    for year, block in output["yearly"].items():
        print(f"  {year}: n={block['trades']} PF={block['profit_factor']} "
              f"avgR={block['average_r']:+.4f} totR={block['total_r']:+.2f}")
    print(f"sample={output['sample_size']['band']} policy={output['sample_size']['research_policy']}")
    print(f"classification={output['baseline_classification']['classification']}")
