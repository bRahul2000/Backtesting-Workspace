"""BTC Final Candidate Validation — frozen T3 SHORT at a fixed 2.00R, on HOLDOUT.

This is the first and only use of the holdout split in this programme. Everything
that decides the outcome is written down in this module *above* the code that
runs anything, so the gates cannot drift after the numbers appear:

* ``CANDIDATE`` names the one configuration under test — the frozen T3 short
  strategy, entries, filters and structural stop untouched, with the engine's
  reward multiple fixed at 2.00R. Nothing else is varied, and no second
  configuration is run on the holdout at all.
* ``GATES`` is the locked pass/fail set: PF >= 1.10, Avg R > 0, total R > 0,
  Max DD < 4%. A test pins these four values so a later edit is visible in the
  diff rather than silent.
* ``DIAGNOSTICS_ONLY`` records what is reported but never judged — frequency,
  win rate, streaks, excursions, monthly and subperiod breakdowns, and the four
  execution-stress arms. A stress arm failing does not change the verdict; the
  brief is explicit that they are robustness diagnostics.

The development reference is re-run first and checked against Architecture Reset
A's recorded numbers. If the harness cannot reproduce PF 1.2596 and +14.05R on
DEVELOPMENT, nothing it says about HOLDOUT is worth reading, and the run stops
before the holdout is touched.

2.00R was selected on DEVELOPMENT in Architecture Reset A and is frozen here. No
alternative reward multiple is evaluated out of sample, and no parameter is
adjusted after the holdout result — that is the whole point of having kept the
split unread.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from core.adapters.audited_engine import run_universal_backtest
from core.config import BacktestConfig, DatasetRole
from core.trade_log import to_timestamp
from research.core_v2_phase_a import (
    DATASET_FINGERPRINT, DATASET_KEY, DEVELOPMENT_END, DEVELOPMENT_START,
    HOLDOUT_END, HOLDOUT_START, dataset_path,
)
from research.core_v2_phase_b import excursions
from research.core_v2_phase_c import _utc, metrics, slice_rows
from services import market_datasets as md
from strategies.btc_v3_t3_breakout_short import STRATEGY_ID as T3_STRATEGY_ID

ROOT = Path(__file__).resolve().parents[1]

# --- predeclared, before any run -------------------------------------------------------

CANDIDATE: dict[str, Any] = {
    "name": "T3 SHORT @ 2.00R",
    "strategy_id": T3_STRATEGY_ID,
    "entry_architecture": "frozen T3 SHORT, unchanged",
    "stop": "frozen T3 structural stop, unchanged",
    "filters": "all frozen T3 filters, unchanged",
    "reward_multiple": 2.00,
    "risk_per_trade_percent": 0.25,
    "selected_on": "DEVELOPMENT (Architecture Reset A)",
}

#--- Locked. A test pins every value; changing one shows up in the diff.
GATES: dict[str, Any] = {
    "profit_factor_min": 1.10,
    "average_r_min_exclusive": 0.0,
    "total_r_min_exclusive": 0.0,
    "max_drawdown_percent_max_exclusive": 4.0,
}

DIAGNOSTICS_ONLY: tuple[str, ...] = (
    "trades", "trades_per_month", "win_rate", "max_losing_streak",
    "monthly", "subperiods", "quarters", "excursions", "execution_stress",
)

#--- Robustness diagnostics only. Not gates. A failure here does not reject.
STRESS_ARMS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("native", {}),
    ("spread x1.10", {"spread_multiplier": 1.10}),
    ("spread x1.20", {"spread_multiplier": 1.20}),
    ("slippage 0.02%", {"slippage_percent": 0.02}),
    ("spread x1.20 + slippage 0.02%", {"spread_multiplier": 1.20, "slippage_percent": 0.02}),
)

#--- Architecture Reset A's recorded DEVELOPMENT result for this exact arm. The
#--- harness must reproduce it before the holdout is opened.
DEVELOPMENT_REFERENCE: dict[str, Any] = {
    "trades": 88, "win_rate": 38.64, "profit_factor": 1.2596,
    "average_r": 0.1596, "total_r": 14.05, "max_drawdown_percent": 1.46,
}

HOLDOUT_SUBPERIODS: tuple[tuple[str, str, str], ...] = (
    ("2025 H2", "2025-07-01 00:00", "2025-12-31 23:45"),
    ("2026 H1", "2026-01-01 00:00", "2026-06-30 23:45"),
    ("2026 partial", "2026-07-01 00:00", "2026-09-20 07:15"),
)


# --- configuration ------------------------------------------------------------------------


def _config(role: DatasetRole, start: pd.Timestamp, end: pd.Timestamp,
            **stress: Any) -> BacktestConfig:
    entry = md.dataset(DATASET_KEY)
    return BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD",
        strategy_id=CANDIDATE["strategy_id"], timeframe="15m", higher_timeframes=("1h",),
        start_date=start, end_date=end, dataset_role=role,
        risk_per_trade_percent=CANDIDATE["risk_per_trade_percent"],
        risk_reward_ratio=CANDIDATE["reward_multiple"],
        spread=0.0, spread_source=entry.spread_source, data_source=entry.key,
        notes=f"T3 2.0R final candidate validation ({role.name}).", **stress)


def development_config(**stress: Any) -> BacktestConfig:
    return _config(DatasetRole.DEVELOPMENT, DEVELOPMENT_START, DEVELOPMENT_END, **stress)


def holdout_config(**stress: Any) -> BacktestConfig:
    """The only function in this repository permitted to open the holdout split."""
    return _config(DatasetRole.HOLDOUT, HOLDOUT_START, HOLDOUT_END, **stress)


def _run(config: BacktestConfig, ledger_path: Path):
    return run_universal_backtest(dataset_path(), config, ledger_path=ledger_path)


# --- reporting ----------------------------------------------------------------------------


def _monthly(rows: Sequence[dict]) -> dict[str, Any]:
    buckets: dict[str, list[dict]] = {}
    for row in rows:
        buckets.setdefault(to_timestamp(row["entry_time"]).strftime("%Y-%m"), []).append(row)
    return {month: {"trades": len(group),
                    "total_r": round(sum(item["realized_r"] for item in group), 4),
                    "wins": sum(1 for item in group if item["pnl"] > 1e-9)}
            for month, group in sorted(buckets.items())}


def _quarterly(rows: Sequence[dict]) -> dict[str, Any]:
    buckets: dict[str, list[dict]] = {}
    for row in rows:
        stamp = to_timestamp(row["entry_time"])
        buckets.setdefault(f"{stamp.year}Q{(stamp.month - 1) // 3 + 1}", []).append(row)
    return {quarter: {"trades": len(group),
                      "total_r": round(sum(item["realized_r"] for item in group), 4),
                      "wins": sum(1 for item in group if item["pnl"] > 1e-9)}
            for quarter, group in sorted(buckets.items())}


def summarise(result, subperiods: Sequence[tuple[str, str, str]]) -> dict[str, Any]:
    rows = result.trade_log
    monthly = _monthly(rows)
    total_r = sum(row["realized_r"] for row in rows)
    best = max((item["total_r"] for item in monthly.values()), default=0.0)
    return {
        "trades": result.total_trades,
        "trades_per_month": round(result.trades_per_month, 4),
        "win_rate": round(result.win_rate, 4) if result.win_rate is not None else None,
        "profit_factor": result.profit_factor,
        "average_r": result.average_r,
        "total_r": round(total_r, 6),
        "pnl": round(result.pnl, 2),
        "max_drawdown_percent": round(result.max_drawdown_percent, 6),
        "max_losing_streak": result.max_losing_streak,
        "monthly": monthly,
        "quarters": _quarterly(rows),
        "positive_months": sum(1 for item in monthly.values() if item["total_r"] > 0),
        "negative_months": sum(1 for item in monthly.values() if item["total_r"] < 0),
        "best_month_r": round(best, 4),
        "best_month_share_of_total": (round(100 * best / total_r, 2)
                                      if total_r > 1e-9 else None),
        "excursions": excursions(rows),
        "subperiods": [
            {"label": label,
             **metrics(slice_rows(rows, _utc(start), _utc(end)), _utc(start), _utc(end))}
            for label, start, end in subperiods],
    }


def apply_gates(summary: dict[str, Any]) -> dict[str, Any]:
    """The locked gates, applied mechanically to the native holdout result."""
    factor = summary["profit_factor"]
    checks = [
        {"gate": f"PF >= {GATES['profit_factor_min']}",
         "observed": factor,
         "passed": factor is not None and factor >= GATES["profit_factor_min"]},
        {"gate": "Avg R > 0", "observed": summary["average_r"],
         "passed": summary["average_r"] is not None
         and summary["average_r"] > GATES["average_r_min_exclusive"]},
        {"gate": "total R > 0", "observed": summary["total_r"],
         "passed": summary["total_r"] > GATES["total_r_min_exclusive"]},
        {"gate": f"Max DD < {GATES['max_drawdown_percent_max_exclusive']}%",
         "observed": summary["max_drawdown_percent"],
         "passed": summary["max_drawdown_percent"]
         < GATES["max_drawdown_percent_max_exclusive"]},
    ]
    passed = all(check["passed"] for check in checks)
    return {
        "checks": checks,
        "all_passed": passed,
        "failed": [check["gate"] for check in checks if not check["passed"]],
        "decision": "T3 2.0R OOS VALIDATED" if passed else "REJECT T3 2.0R",
    }


def reproduces_development(summary: dict[str, Any]) -> dict[str, Any]:
    """Guard: the harness must reproduce the recorded DEVELOPMENT arm first."""
    checks = {
        "trades": (summary["trades"], DEVELOPMENT_REFERENCE["trades"], 0),
        "profit_factor": (summary["profit_factor"],
                          DEVELOPMENT_REFERENCE["profit_factor"], 5e-4),
        "average_r": (summary["average_r"], DEVELOPMENT_REFERENCE["average_r"], 5e-4),
        "total_r": (summary["total_r"], DEVELOPMENT_REFERENCE["total_r"], 5e-2),
        "max_drawdown_percent": (summary["max_drawdown_percent"],
                                 DEVELOPMENT_REFERENCE["max_drawdown_percent"], 5e-3),
    }
    detail = {name: {"observed": observed, "expected": expected,
                     "matches": abs(observed - expected) <= tolerance}
              for name, (observed, expected, tolerance) in checks.items()}
    return {"detail": detail, "reproduced": all(item["matches"] for item in detail.values())}


def run_validation(ledger_path: Path) -> dict[str, Any]:
    development = summarise(_run(development_config(), ledger_path),
                            (("full development", "2023-11-10 23:15", "2025-06-30 23:45"),))
    reproduction = reproduces_development(development)
    if not reproduction["reproduced"]:
        #--- Refuse to open the holdout on a harness that cannot reproduce a
        #--- known result. The split is spendable once.
        raise RuntimeError(
            f"DEVELOPMENT reference not reproduced; holdout not opened: {reproduction}")

    native = _run(holdout_config(), ledger_path)
    holdout = summarise(native, HOLDOUT_SUBPERIODS)
    gates = apply_gates(holdout)

    stress: dict[str, Any] = {}
    for name, arm in STRESS_ARMS:
        result = native if not arm else _run(holdout_config(**arm), ledger_path)
        stress[name] = {
            "trades": result.total_trades,
            "profit_factor": result.profit_factor,
            "average_r": result.average_r,
            "total_r": round(sum(row["realized_r"] for row in result.trade_log), 4),
            "max_drawdown_percent": round(result.max_drawdown_percent, 4),
            "win_rate": round(result.win_rate, 4) if result.win_rate is not None else None,
        }

    return {
        "candidate": CANDIDATE,
        "gates": GATES,
        "diagnostics_only": list(DIAGNOSTICS_ONLY),
        "split": {
            "development_start": DEVELOPMENT_START.isoformat(),
            "development_end": DEVELOPMENT_END.isoformat(),
            "holdout_start": HOLDOUT_START.isoformat(),
            "holdout_end": HOLDOUT_END.isoformat(),
            "holdout_opened": True,
            "holdout_configurations_run": 1,
            "alternative_reward_multiples_tested_on_holdout": 0,
        },
        "dataset": {"key": DATASET_KEY, "path": str(dataset_path().relative_to(ROOT)),
                    "fingerprint": DATASET_FINGERPRINT},
        "development_reference": DEVELOPMENT_REFERENCE,
        "development_reproduction": reproduction,
        "development": development,
        "holdout": holdout,
        "gate_result": gates,
        "execution_stress": stress,
    }


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    payload = run_validation(args.ledger)
    args.out.write_text(json.dumps(payload, default=str, indent=1))
    print(f"wrote {args.out}")
    print(f"DECISION: {payload['gate_result']['decision']}")


if __name__ == "__main__":
    main()
