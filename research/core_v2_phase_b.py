"""BTC Core V2 — Phase B: structural opportunity ablation on DEVELOPMENT.

Phase A's conclusion is carried in unchanged: both body thresholds stay at 0.70
and the reward multiple stays at 3R. Phase B moves structure instead of quality
— how long an A4 pullback may wait for confirmation, and how far back T3 looks
for the low it must break.

One finding shapes Experiment A and has to be stated before any table is read.
A4 has no one-bar confirmation window to widen: an armed pullback stays armed
until the frozen invalidation rules clear it, the median confirmation arrives on
the fourth bar of the pullback, and the tail runs to twenty-one. Bounded windows
are therefore *tighter* than the frozen behaviour. The arms below remove
opportunity rather than adding it, so both directions of the trade delta matter:
trades the arm withdraws, and trades it admits because the position slot came
free earlier.

The analysis helpers are Phase A's, unchanged, so the two phases are directly
comparable. Phase B adds excursion (MFE/MAE) statistics for the delta streams.
"""
from __future__ import annotations

from pathlib import Path
from statistics import mean
from typing import Any, Sequence

import pandas as pd

from core.adapters.audited_engine import run_universal_backtest
from core.config import BacktestConfig
from research.core_v2_phase_a import (
    DEVELOPMENT_END, DEVELOPMENT_START, HOLDOUT_END, HOLDOUT_START,
    DATASET_FINGERPRINT, DATASET_KEY, concentration, dataset_path,
    development_config, describe_stream, summarise, trade_delta,
)
from strategies.btc_core_v2_phase_b_variants import (
    A4_BASELINE_WINDOW, A4_CONFIRMATION_WINDOWS, A4_WINDOW_IDS,
    CORE_A4_WINDOW_IDS, CORE_T3_LOOKBACK_IDS, T3_BASELINE_LOOKBACK,
    T3_LOOKBACK_IDS, T3_STRUCTURE_LOOKBACKS, phase_b_registry, window_tag,
)

ROOT = Path(__file__).resolve().parents[1]

#--- (family, arm values, baseline value, id map)
FAMILIES: dict[str, dict[str, Any]] = {
    "A4_STANDALONE": {"values": A4_CONFIRMATION_WINDOWS, "baseline": A4_BASELINE_WINDOW,
                      "ids": A4_WINDOW_IDS, "label": "A4 confirmation window"},
    "CORE_WITH_A4_VARIANT": {"values": A4_CONFIRMATION_WINDOWS, "baseline": A4_BASELINE_WINDOW,
                             "ids": CORE_A4_WINDOW_IDS, "label": "Core · A4 window"},
    "T3_STANDALONE": {"values": T3_STRUCTURE_LOOKBACKS, "baseline": T3_BASELINE_LOOKBACK,
                      "ids": T3_LOOKBACK_IDS, "label": "T3 structure lookback"},
    "CORE_WITH_T3_VARIANT": {"values": T3_STRUCTURE_LOOKBACKS, "baseline": T3_BASELINE_LOOKBACK,
                             "ids": CORE_T3_LOOKBACK_IDS, "label": "Core · T3 lookback"},
}


def arm_key(value: Any) -> str:
    return window_tag(value) if value is None or isinstance(value, bool) else str(value)


def phase_b_config(strategy_id: str) -> BacktestConfig:
    return development_config(strategy_id)


def run_arm(strategy_id: str, ledger_path: Path):
    config = phase_b_config(strategy_id)
    if config.end_date >= HOLDOUT_START:
        raise ValueError("Phase B must not read the holdout split.")
    return run_universal_backtest(dataset_path(), config, ledger_path=ledger_path,
                                  registry=phase_b_registry())


# --- excursions ---------------------------------------------------------------


def _mean(values: Sequence[float | None]) -> float | None:
    usable = [value for value in values if value is not None]
    return mean(usable) if usable else None


def excursions(rows: Sequence[dict]) -> dict[str, Any]:
    """MFE/MAE of a trade stream, in R and in price.

    The engine labels these BAR_BASED_APPROXIMATION: OHLC cannot reveal the
    intrabar path, so an extreme is the bar's extreme, not a tick-exact one.
    """
    if not rows:
        return {"trades": 0, "mfe_r": None, "mae_r": None, "median_mfe_r": None,
                "median_mae_r": None, "mfe_amount": None, "mae_amount": None,
                "capture_efficiency": None, "reached_1r": None, "reached_2r": None,
                "model": "UNAVAILABLE"}
    mfe = [row.get("mfe_r") for row in rows]
    mae = [row.get("mae_r") for row in rows]
    usable_mfe = sorted(value for value in mfe if value is not None)
    usable_mae = sorted(value for value in mae if value is not None)
    return {
        "trades": len(rows),
        "mfe_r": _mean(mfe),
        "mae_r": _mean(mae),
        "median_mfe_r": usable_mfe[len(usable_mfe) // 2] if usable_mfe else None,
        "median_mae_r": usable_mae[len(usable_mae) // 2] if usable_mae else None,
        "mfe_amount": _mean([row.get("mfe_amount") for row in rows]),
        "mae_amount": _mean([row.get("mae_amount") for row in rows]),
        "capture_efficiency": _mean([row.get("capture_efficiency") for row in rows]),
        #--- How far the admitted trades actually travelled: a stream that never
        #--- reaches 1R is not a 3R stream that got unlucky.
        "reached_1r": sum(1 for value in usable_mfe if value >= 1.0),
        "reached_2r": sum(1 for value in usable_mfe if value >= 2.0),
        "model": rows[0].get("excursion_model") or "BAR_BASED_APPROXIMATION",
    }


def describe_with_excursions(rows: Sequence[dict]) -> dict[str, Any]:
    stream = describe_stream(rows)
    stream["excursions"] = excursions(rows)
    return stream


def yearly_breakdown(rows: Sequence[dict]) -> dict[str, Any]:
    from research.core_v2_phase_a import _timestamp

    buckets: dict[str, list[dict]] = {}
    for row in rows:
        buckets.setdefault(_timestamp(row["entry_time"]).strftime("%Y"), []).append(row)
    return {year: {"trades": len(group),
                   "total_r": sum(item["realized_r"] for item in group),
                   "average_r": mean(item["realized_r"] for item in group)}
            for year, group in sorted(buckets.items())}


# --- the phase ----------------------------------------------------------------


def run_family(family: str, ledger_path: Path) -> dict[str, Any]:
    spec = FAMILIES[family]
    values, baseline_value, ids = spec["values"], spec["baseline"], spec["ids"]
    results = {value: run_arm(ids[value], ledger_path) for value in values}
    baseline = results[baseline_value]
    arms: dict[str, Any] = {}
    for index, value in enumerate(values):
        result = results[value]
        delta = trade_delta(baseline.trade_log, result.trade_log)
        added = describe_with_excursions(delta.added)
        withdrawn = describe_with_excursions(delta.displaced)
        previous = values[index - 1] if index else None
        marginal = (describe_with_excursions(
            trade_delta(results[previous].trade_log, result.trade_log).added)
            if previous is not None else describe_with_excursions([]))
        arms[arm_key(value)] = {
            "value": value,
            "strategy_id": ids[value],
            "is_baseline": value == baseline_value,
            "summary": summarise(result),
            "incremental": added,
            "incremental_concentration": concentration(added),
            "incremental_yearly": yearly_breakdown(delta.added),
            #--- A tighter arm removes trades; "displaced" is the baseline set it
            #--- no longer takes, whatever the cause.
            "withdrawn": withdrawn,
            "withdrawn_yearly": yearly_breakdown(delta.displaced),
            "marginal_band": {"from": arm_key(previous) if previous is not None else None,
                              "to": arm_key(value), **marginal},
            "common_trades": len(delta.common),
            "changed_execution": len(delta.changed),
            "net_r_change": (sum(row["realized_r"] for row in result.trade_log)
                             - sum(row["realized_r"] for row in baseline.trade_log)),
            "drawdown_delta_percent": (result.max_drawdown_percent
                                       - baseline.max_drawdown_percent),
            "frequency_change": {
                "closed_trades": result.total_trades - baseline.total_trades,
                "trades_per_month": result.trades_per_month - baseline.trades_per_month,
                "orders_created": (sum(result.execution_diagnostics.get("order_events", {}).values())
                                   - sum(baseline.execution_diagnostics.get("order_events", {}).values())),
            },
        }
    return {"family": family, "label": spec["label"],
            "baseline": arm_key(baseline_value), "arms": arms}


def run_phase_b(ledger_path: Path) -> dict[str, Any]:
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
        "carried_from_phase_a": {"a4_body": 0.70, "t3_body": 0.70, "reward_multiple": 3.0},
        "families": {name: run_family(name, ledger_path) for name in FAMILIES},
    }


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.write_text(json.dumps(run_phase_b(args.ledger), default=str, indent=1))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
