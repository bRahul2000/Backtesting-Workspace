"""PB2 Phase A — DEVELOPMENT-only baseline for the two reclaim components.

Runs exactly two primary backtests, one per direction, on DEVELOPMENT
(2021-01-01 .. 2023-12-31). No combined run, no parameter alternative, no
optimization, and no VALIDATION or FORWARD_VALIDATION access of any kind: the
window is asserted before anything is executed and every reported timestamp is
checked against it afterwards.

Everything here is reporting. The strategies, the audited execution engine and
the diagnostics infrastructure are untouched.
"""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
import pandas as pd

from core.adapters.audited_engine import run_universal_backtest
from core.config import BacktestConfig, DatasetRole
from strategies.base_strategy import effective_parameter_payload, parameter_fingerprint
from strategies.btc_pb2_reclaim_acceptance import PB2Parameters
from strategies.registry import discover_builtin_strategies

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "btcusd_15m.csv"
REPORT = ROOT / "reports" / "pb2" / "phase_a_baseline.json"
SCRATCH_LEDGER = Path("/tmp") / "pb2_phase_a_scratch_ledger.sqlite3"

DEVELOPMENT_START = pd.Timestamp("2021-01-01", tz="UTC")
DEVELOPMENT_END = pd.Timestamp("2023-12-31 23:45", tz="UTC")

COMPONENTS = {"LONG": "BTC_PB2_RECLAIM_LONG_V1", "SHORT": "BTC_PB2_RECLAIM_SHORT_V1"}

FUNNEL_STAGES = (
    "context_evaluated", "context_rejected", "displacement_evaluated", "displacement_detected",
    "displacement_rejected", "structure_level_created", "waiting_retest", "retest_detected",
    "retest_expired", "structure_invalidated", "reclaim_evaluated", "reclaim_confirmed",
    "reclaim_rejected", "acceptance_evaluated", "acceptance_confirmed", "acceptance_failed",
    "risk_evaluated", "risk_rejected", "pending_created", "pending_expired",
    "trade_entered", "trade_exited",
)

# Section 22: descriptive buckets over the setup geometry PB2 recorded when it
# created each pending order. Fixed edges so LONG and SHORT stay comparable.
ACCEPTANCE_BUCKETS = {
    "breakout_distance_atr": [0.0, 0.25, 0.50, 1.00, np.inf],
    "retest_overshoot_atr": [-np.inf, -0.10, 0.0, 0.10, np.inf],
    "bars_to_retest": [0, 1, 2, 3, np.inf],
    "reclaim_body_percent": [0.0, 0.60, 0.75, 0.90, 1.0],
    "acceptance_distance_atr": [0.0, 0.25, 0.50, 1.00, np.inf],
    "stop_atr": [0.0, 1.00, 1.50, 2.00, 2.50],
}


def _config(strategy_id: str) -> BacktestConfig:
    if DEVELOPMENT_START < pd.Timestamp("2021-01-01", tz="UTC") or \
            DEVELOPMENT_END >= pd.Timestamp("2024-01-01", tz="UTC"):
        raise ValueError("PB2 Phase A is DEVELOPMENT-only; 2024-2026 must never be requested.")
    return BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD", strategy_id=strategy_id,
        timeframe="15m", higher_timeframes=("1h",),
        start_date=DEVELOPMENT_START, end_date=DEVELOPMENT_END,
        dataset_role=DatasetRole.DEVELOPMENT,
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
    """Phase A.1 semantics: excursion price distance / initial stop price distance."""
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
    """Geometry PB2 logged for each pending order it created, keyed to the trade.

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


def run_component(label: str, strategy_id: str) -> dict[str, Any]:
    descriptor = discover_builtin_strategies().get(strategy_id)
    payload = effective_parameter_payload(descriptor, {})
    result = run_universal_backtest(DATA, _config(strategy_id), ledger_path=SCRATCH_LEDGER)

    frame = pd.DataFrame(result.trade_log)
    for column in ("signal_time", "entry_time", "exit_time"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    if not frame.empty:
        latest = frame.exit_time.max()
        if latest > DEVELOPMENT_END:
            raise ValueError(f"{label} produced a trade outside DEVELOPMENT ({latest}).")
        frame["year"] = frame.entry_time.dt.year
        frame["holding_minutes"] = (frame.exit_time - frame.entry_time).dt.total_seconds() / 60
        frame["acceptance_time"] = frame.signal_time - pd.Timedelta(minutes=15)
        geometry = _setup_geometry(result)
        if not geometry.empty:
            frame = frame.join(geometry, on="acceptance_time", rsuffix="_setup")

    stages: dict[str, int] = {}
    reasons: dict[str, int] = {}
    tradeable_pendings = 0
    for event in result.signal_diagnostics:
        stage = event["stage"]
        stages[stage] = stages.get(stage, 0) + 1
        if event.get("passed") is False and event.get("reason"):
            reasons[f"{stage}/{event['reason']}"] = reasons.get(f"{stage}/{event['reason']}", 0) + 1
        if stage == "pending_created" and not (event.get("metadata") or {}).get("before_trade_start"):
            tradeable_pendings += 1

    return {
        "component": label, "strategy_id": strategy_id,
        "strategy_fingerprint": result.strategy_fingerprint,
        "parameter_fingerprint": result.parameter_fingerprint,
        "dataset_fingerprint": result.dataset_fingerprint,
        "effective_parameters": payload,
        "period": result.period, "dataset_role": result.dataset_role,
        "metrics": {
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
        },
        "yearly": {str(year): _year_block(group) for year, group in frame.groupby("year")}
                  if not frame.empty else {},
        "funnel": {stage: stages.get(stage, 0) for stage in FUNNEL_STAGES},
        "funnel_notes": {
            "pending_created_in_tradeable_window": tradeable_pendings,
            "engine_order_events": result.execution_diagnostics.get("order_events", {}),
            "explanation": ("pending_created counts every rule decision, including signals emitted "
                            "before the warmup boundary that the engine always discards; the "
                            "tradeable-window count is what reaches the order book."),
        },
        "rejection_reasons": dict(sorted(reasons.items(), key=lambda item: -item[1])[:15]),
        "excursion": _excursion(frame) if not frame.empty else {},
        "acceptance_buckets": {column: _bucket_table(frame, column, edges)
                               for column, edges in ACCEPTANCE_BUCKETS.items()}
                              if not frame.empty else {},
        "xray_rule_counts": _xray_counts(result),
        "_frame": frame,
    }


def _xray_counts(result: Any) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for row in result.xray_diagnostics:
        bucket = counts.setdefault(row["rule"], {"PASS": 0, "FAIL": 0})
        bucket[row["result"]] = bucket.get(row["result"], 0) + 1
    return counts


def classify(metrics: dict[str, Any]) -> dict[str, Any]:
    """Section 23: transparent descriptive classification, never a robustness claim."""
    trades = metrics["closed_trades"]
    average_r = metrics["average_r"]
    if trades < 30:
        label = "INSUFFICIENT_SAMPLE"
    elif average_r > 0.05:
        label = "BASELINE_POSITIVE"
    elif average_r < -0.05:
        label = "BASELINE_NEGATIVE"
    else:
        label = "BASELINE_NEAR_BREAKEVEN"
    return {
        "classification": label,
        "rule": ("closed trades < 30 -> INSUFFICIENT_SAMPLE; otherwise Avg R > +0.05 -> "
                 "BASELINE_POSITIVE, Avg R < -0.05 -> BASELINE_NEGATIVE, else "
                 "BASELINE_NEAR_BREAKEVEN. Descriptive only: no cross-year robustness is "
                 "claimed and nothing can become FROZEN from Phase A."),
        "closed_trades": trades, "average_r": average_r,
    }


def build() -> dict[str, Any]:
    components = {label: run_component(label, strategy_id)
                  for label, strategy_id in COMPONENTS.items()}
    frames = {label: component.pop("_frame") for label, component in components.items()}
    for label, component in components.items():
        component["baseline_classification"] = classify(component["metrics"])

    years = sorted({year for frame in frames.values() if not frame.empty
                    for year in frame.year.unique()})
    if any(int(year) not in (2021, 2022, 2023) for year in years):
        raise ValueError(f"PB2 Phase A touched a year outside DEVELOPMENT: {years}")

    report = {
        "phase": "PB2 Phase A — reclaim & acceptance baseline",
        "dataset_role": "DEVELOPMENT",
        "period": {"start": DEVELOPMENT_START.isoformat(), "end": DEVELOPMENT_END.isoformat()},
        "years_present": [int(year) for year in years],
        "baseline_parameters": asdict(PB2Parameters()),
        "components": components,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    output = build()
    for label, component in output["components"].items():
        metrics = component["metrics"]
        print(f"{label}: trades={metrics['closed_trades']} entries={metrics['total_entries']} "
              f"open_at_end={metrics['open_at_end']} "
              f"PF={metrics['profit_factor']} avgR={metrics['average_r']:+.4f} "
              f"totR={metrics['total_r']:+.2f} DD={metrics['max_drawdown_percent']:.2f}% "
              f"-> {component['baseline_classification']['classification']}")
