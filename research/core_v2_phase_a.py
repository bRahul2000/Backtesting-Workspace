"""BTC Core V2 — Phase A: local quality-gate ablation on the DEVELOPMENT split.

One question per experiment: what does the candle-body quality gate exclude,
and is what it excludes worth admitting? The frozen A4/T3/Core are immutable;
the arms are the wrappers in strategies/btc_core_v2_variants.py, each moving
exactly one number.

The decision rule is deliberately not "highest profit factor". A relaxation is
judged on the trades it *newly admits*, because aggregate metrics are dominated
by the legacy baseline trades that every arm shares. An arm whose incremental
trades lose money is rejected however good its headline looks.

The HOLDOUT split is never read here. HOLDOUT_START/END exist so the boundary is
stated in one place and so a test can assert no Phase A run crosses it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Sequence

import pandas as pd

from core.adapters.audited_engine import run_universal_backtest
from core.config import BacktestConfig, DatasetRole
from core.fingerprints import sha256_file
from core.result import UniversalBacktestResult
from services import market_datasets as md
from strategies.btc_core_v2_variants import (
    A4_VARIANT_IDS, BASELINE_THRESHOLD, BODY_THRESHOLDS, CORE_A4_VARIANT_IDS,
    CORE_T3_VARIANT_IDS, T3_VARIANT_IDS, phase_a_registry,
)

ROOT = Path(__file__).resolve().parents[1]

#--- Locked research split. Nothing in Phase A may read past DEVELOPMENT_END.
DEVELOPMENT_START = pd.Timestamp("2023-11-10 23:15", tz="UTC")
DEVELOPMENT_END = pd.Timestamp("2025-06-30 23:45", tz="UTC")
HOLDOUT_START = pd.Timestamp("2025-07-01 00:00", tz="UTC")
HOLDOUT_END = pd.Timestamp("2026-09-20 07:15", tz="UTC")

DATASET_KEY = md.EXNESS_BTCUSDM_M15
DATASET_FINGERPRINT = "80735a2cf521363747f48368814267ad6ca146eb294bb7bd7252666d06c76af3"

FAMILIES: dict[str, dict[float, str]] = {
    "A4_STANDALONE": A4_VARIANT_IDS,
    "T3_STANDALONE": T3_VARIANT_IDS,
    "CORE_WITH_A4_VARIANT": CORE_A4_VARIANT_IDS,
    "CORE_WITH_T3_VARIANT": CORE_T3_VARIANT_IDS,
}


def dataset_path() -> Path:
    entry = md.dataset(DATASET_KEY)
    digest = sha256_file(entry.path)
    if digest != DATASET_FINGERPRINT:
        raise ValueError(
            f"Dataset fingerprint changed: expected {DATASET_FINGERPRINT}, got {digest}.")
    return entry.path


def development_config(strategy_id: str) -> BacktestConfig:
    entry = md.dataset(DATASET_KEY)
    return BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD", strategy_id=strategy_id,
        timeframe="15m", higher_timeframes=("1h",),
        start_date=DEVELOPMENT_START, end_date=DEVELOPMENT_END,
        dataset_role=DatasetRole.DEVELOPMENT, risk_per_trade_percent=0.25,
        spread=0.0, spread_source=entry.spread_source, data_source=entry.key,
        notes="BTC Core V2 Phase A body-threshold ablation (DEVELOPMENT only).")


def run_arm(strategy_id: str, ledger_path: Path) -> UniversalBacktestResult:
    config = development_config(strategy_id)
    if config.end_date >= HOLDOUT_START:
        raise ValueError("Phase A must not read the holdout split.")
    return run_universal_backtest(dataset_path(), config, ledger_path=ledger_path,
                                  registry=phase_a_registry())


# --- metrics -----------------------------------------------------------------


def _timestamp(value: Any) -> pd.Timestamp:
    """Normalise a trade_log timestamp.

    core.adapters.audited_engine._trade_row unwraps any value exposing ``.value``
    before its pd.Timestamp branch can run, and pd.Timestamp exposes ``.value``
    as epoch nanoseconds — so trade_log timestamps arrive as integers, not ISO
    strings. pd.Timestamp accepts both, so this keeps working if that is fixed.
    """
    stamp = pd.Timestamp(value)
    return stamp if stamp.tzinfo is not None else stamp.tz_localize("UTC")


def _month(value: Any) -> str:
    return _timestamp(value).strftime("%Y-%m")


def _profit_factor(rows: Sequence[dict]) -> float | None:
    gains = sum(row["pnl"] for row in rows if row["pnl"] > 0)
    losses = -sum(row["pnl"] for row in rows if row["pnl"] < 0)
    if losses <= 0:
        return None if gains <= 0 else float("inf")
    return gains / losses


def _loss_streak(rows: Sequence[dict]) -> int:
    current = worst = 0
    for row in rows:
        if row["pnl"] < -1e-9:
            current += 1
            worst = max(worst, current)
        elif abs(row["pnl"]) > 1e-9:
            current = 0
    return worst


def _max_drawdown_r(rows: Sequence[dict]) -> float:
    """Worst peak-to-trough of the cumulative R of this trade stream alone.

    This is a property of the stream in isolation. It is NOT a decomposition of
    the run's max drawdown, which depends on how these trades interleave with
    every other trade and with compounding equity.
    """
    equity = peak = worst = 0.0
    for row in sorted(rows, key=lambda item: _timestamp(item["entry_time"])):
        equity += row["realized_r"]
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def summarise(result: UniversalBacktestResult) -> dict[str, Any]:
    rows = result.trade_log
    orders = result.execution_diagnostics.get("order_events", {})
    return {
        "closed_trades": result.total_trades,
        "entries": result.total_entries,
        "orders_created": sum(orders.values()),
        "order_events": dict(orders),
        "trades_per_month": result.trades_per_month,
        "win_rate": result.win_rate,
        "profit_factor": result.profit_factor,
        "average_r": result.average_r,
        "total_r": sum(row["realized_r"] for row in rows),
        "pnl": result.pnl,
        "max_drawdown_percent": result.max_drawdown_percent,
        "max_losing_streak": result.max_losing_streak,
        "monthly": result.monthly_statistics,
        "yearly": result.yearly_statistics,
        "long": result.long_statistics.trades,
        "short": result.short_statistics.trades,
        "open_at_end": len(result.open_positions_at_end),
    }


# --- incremental analysis ----------------------------------------------------


def _key(row: dict) -> tuple[str, str, str]:
    return (str(row.get("setup_id")), str(row["direction"]),
            _timestamp(row["entry_time"]).isoformat())


@dataclass(frozen=True)
class TradeDelta:
    added: list[dict]
    displaced: list[dict]
    common: list[dict]
    changed: list[dict]


def trade_delta(baseline: Sequence[dict], variant: Sequence[dict]) -> TradeDelta:
    """Split a variant's trades against the baseline's.

    A relaxation does not simply append trades: an earlier admitted trade takes
    the single global position slot and can displace a baseline trade entirely.
    Both directions have to be reported or the arm looks free.
    """
    base_by_key = {_key(row): row for row in baseline}
    variant_by_key = {_key(row): row for row in variant}
    added = [row for key, row in variant_by_key.items() if key not in base_by_key]
    displaced = [row for key, row in base_by_key.items() if key not in variant_by_key]
    common = [row for key, row in variant_by_key.items() if key in base_by_key]
    #--- Same setup and entry bar, different execution: worth surfacing rather
    #--- than silently counting as unchanged.
    changed = [row for row in common
               if row["entry_price"] != base_by_key[_key(row)]["entry_price"]
               or row["exit_price"] != base_by_key[_key(row)]["exit_price"]]
    return TradeDelta(added, displaced, common, changed)


def describe_stream(rows: Sequence[dict]) -> dict[str, Any]:
    if not rows:
        return {"trades": 0, "win_rate": None, "profit_factor": None, "average_r": None,
                "total_r": 0.0, "pnl": 0.0, "max_drawdown_r": 0.0, "months": {}}
    ordered = sorted(rows, key=lambda item: _timestamp(item["entry_time"]))
    months: dict[str, dict[str, Any]] = {}
    for row in ordered:
        month = _month(row["entry_time"])
        bucket = months.setdefault(month, {"trades": 0, "total_r": 0.0, "wins": 0})
        bucket["trades"] += 1
        bucket["total_r"] += row["realized_r"]
        bucket["wins"] += 1 if row["pnl"] > 1e-9 else 0
    return {
        "trades": len(ordered),
        "win_rate": 100 * sum(row["pnl"] > 1e-9 for row in ordered) / len(ordered),
        "profit_factor": _profit_factor(ordered),
        "average_r": mean(row["realized_r"] for row in ordered),
        "total_r": sum(row["realized_r"] for row in ordered),
        "pnl": sum(row["pnl"] for row in ordered),
        "max_drawdown_r": _max_drawdown_r(ordered),
        "max_losing_streak": _loss_streak(ordered),
        "months": months,
        "first_entry": _timestamp(ordered[0]["entry_time"]).isoformat(),
        "last_entry": _timestamp(ordered[-1]["entry_time"]).isoformat(),
    }


def concentration(stream: dict[str, Any]) -> dict[str, Any]:
    """How much of a stream's total R comes from its single best month."""
    months = stream.get("months") or {}
    if not months:
        return {"best_month": None, "best_month_r": 0.0, "share_of_total_r": None,
                "positive_months": 0, "negative_months": 0}
    best = max(months.items(), key=lambda item: item[1]["total_r"])
    worst = min(months.items(), key=lambda item: item[1]["total_r"])
    total = stream["total_r"]
    return {
        "best_month": best[0],
        "best_month_r": best[1]["total_r"],
        "worst_month": worst[0],
        "worst_month_r": worst[1]["total_r"],
        #--- A share of a negative total is not a concentration measure: it comes
        #--- out negative and reads as if the best month hurt. Only report it when
        #--- there is a positive total to concentrate.
        "share_of_total_r": (best[1]["total_r"] / total * 100) if total > 1e-12 else None,
        "months_observed": len(months),
        "positive_months": sum(1 for m in months.values() if m["total_r"] > 0),
        "negative_months": sum(1 for m in months.values() if m["total_r"] < 0),
    }


# --- the phase ---------------------------------------------------------------


def run_family(family: str, ledger_path: Path) -> dict[str, Any]:
    ids = FAMILIES[family]
    results = {value: run_arm(ids[value], ledger_path) for value in BODY_THRESHOLDS}
    baseline = results[BASELINE_THRESHOLD]
    arms: dict[str, Any] = {}
    for index, value in enumerate(BODY_THRESHOLDS):
        result = results[value]
        delta = trade_delta(baseline.trade_log, result.trade_log)
        #--- Each arm against the next-tighter one. Cumulative deltas against the
        #--- 0.70 control hide where a step stops paying, because a good band and
        #--- a bad band average into one number.
        previous = BODY_THRESHOLDS[index - 1] if index else None
        marginal = (describe_stream(
            trade_delta(results[previous].trade_log, result.trade_log).added)
            if previous is not None else describe_stream([]))
        added = describe_stream(delta.added)
        displaced = describe_stream(delta.displaced)
        arms[f"{value:.2f}"] = {
            "threshold": value,
            "strategy_id": ids[value],
            "summary": summarise(result),
            "incremental": added,
            "incremental_concentration": concentration(added),
            "displaced": displaced,
            "marginal_band": {"from": previous, "to": value, **marginal},
            "common_trades": len(delta.common),
            "changed_execution": len(delta.changed),
            "drawdown_delta_percent": (result.max_drawdown_percent
                                       - baseline.max_drawdown_percent),
            "frequency_gain": {
                "closed_trades": result.total_trades - baseline.total_trades,
                "trades_per_month": result.trades_per_month - baseline.trades_per_month,
                "orders_created": (sum(result.execution_diagnostics.get("order_events", {}).values())
                                   - sum(baseline.execution_diagnostics.get("order_events", {}).values())),
            },
        }
    return {"family": family, "baseline_threshold": BASELINE_THRESHOLD, "arms": arms}


def run_phase_a(ledger_path: Path) -> dict[str, Any]:
    return {
        "split": {
            "development_start": DEVELOPMENT_START.isoformat(),
            "development_end": DEVELOPMENT_END.isoformat(),
            "holdout_start": HOLDOUT_START.isoformat(),
            "holdout_end": HOLDOUT_END.isoformat(),
            "holdout_touched": False,
        },
        "dataset": {"key": DATASET_KEY, "path": str(dataset_path().relative_to(ROOT)),
                    "fingerprint": DATASET_FINGERPRINT},
        "thresholds": list(BODY_THRESHOLDS),
        "families": {name: run_family(name, ledger_path) for name in FAMILIES},
    }


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    payload = run_phase_a(args.ledger)
    args.out.write_text(json.dumps(payload, default=str, indent=1))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
