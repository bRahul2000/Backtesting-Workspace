"""BTC Core V2 — Phase D: complementary setup family discovery, DEVELOPMENT only.

Phases A–C closed parameter-level work on A4 and T3: every relaxation, timing
change and lookback change was rejected. Phase D stops adjusting the two frozen
children and looks for an additive third source of trades instead.

Each family is measured twice. Standalone tells you whether the idea works at
all. Inside Core, alongside both frozen children and the single global position,
tells you what it is actually worth — and those two numbers differ, because a
candidate can only trade when the frozen pair has not already taken the slot.
The incremental stream is the deciding measurement: trades the Core gains, and
trades it loses to displacement, reported separately and by which frozen child
was displaced.
"""
from __future__ import annotations

from pathlib import Path
from statistics import mean
from typing import Any, Sequence

import pandas as pd

from core.adapters.audited_engine import run_universal_backtest
from research.core_v2_phase_a import (
    DATASET_FINGERPRINT, DATASET_KEY, DEVELOPMENT_END, DEVELOPMENT_START,
    HOLDOUT_END, HOLDOUT_START, _timestamp, concentration, dataset_path,
    describe_stream, development_config, summarise, trade_delta,
)
from research.core_v2_phase_b import excursions
from research.core_v2_phase_c import _utc, metrics, slice_rows
from strategies.btc_core_v2_phase_d_families import (
    CORE_IDS, FAMILY_LABELS, FAMILY_SETUP_IDS, STANDALONE_IDS, phase_d_registry,
)
from strategies.btc_v3_a4_pullback_long import SETUP_ID as A4_SETUP_ID
from strategies.btc_v3_t3_breakout_short import TREND_SETUP_ID as T3_SETUP_ID

ROOT = Path(__file__).resolve().parents[1]
CORE_BASELINE_ID = "BTC_V3_CORE_V1_FROZEN"

SUBPERIODS: tuple[tuple[str, str, str], ...] = (
    ("2023 partial", "2023-11-10 23:15", "2023-12-31 23:45"),
    ("2024 H1", "2024-01-01 00:00", "2024-06-30 23:45"),
    ("2024 H2", "2024-07-01 00:00", "2024-12-31 23:45"),
    ("2025 H1", "2025-01-01 00:00", "2025-06-30 23:45"),
)

#--- Phase D carry-forward standard, stated once so the verdict is mechanical.
MIN_INCREMENTAL_TRADES_PER_MONTH = 4.0
MIN_INCREMENTAL_PROFIT_FACTOR = 1.10


def run_arm(strategy_id: str, ledger_path: Path):
    config = development_config(strategy_id)
    if config.end_date >= HOLDOUT_START:
        raise ValueError("Phase D must not read the holdout split.")
    return run_universal_backtest(dataset_path(), config, ledger_path=ledger_path,
                                  registry=phase_d_registry())


def _months() -> float:
    return (DEVELOPMENT_END - DEVELOPMENT_START).total_seconds() / (60 * 60 * 24 * 30.4375)


def lifecycle(result) -> dict[str, int]:
    events = result.execution_diagnostics.get("order_events", {})
    return {"setups": sum(events.values()), "orders": sum(events.values()),
            "fills": events.get("triggered", 0), "expired": events.get("expired", 0),
            "cancelled": events.get("cancelled", 0),
            "active_at_end": events.get("active_at_end", 0)}


def family_metrics(result) -> dict[str, Any]:
    payload = summarise(result)
    payload.pop("monthly", None)
    payload["lifecycle"] = lifecycle(result)
    payload["subperiods"] = [
        {"label": label, **metrics(slice_rows(result.trade_log, _utc(start), _utc(end)),
                                   _utc(start), _utc(end))}
        for label, start, end in SUBPERIODS
    ]
    payload["monthly"] = _monthly(result.trade_log)
    return payload


def _monthly(rows: Sequence[dict]) -> dict[str, Any]:
    buckets: dict[str, list[dict]] = {}
    for row in rows:
        buckets.setdefault(_timestamp(row["entry_time"]).strftime("%Y-%m"), []).append(row)
    return {month: {"trades": len(group),
                    "total_r": sum(item["realized_r"] for item in group),
                    "wins": sum(1 for item in group if item["pnl"] > 1e-9)}
            for month, group in sorted(buckets.items())}


def _by_setup(rows: Sequence[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.get("setup_id") or "UNKNOWN"] = counts.get(row.get("setup_id") or "UNKNOWN", 0) + 1
    return counts


def incremental_contribution(baseline, combined, family_setup_id: str) -> dict[str, Any]:
    delta = trade_delta(baseline.trade_log, combined.trade_log)
    added, displaced = delta.added, delta.displaced
    from_family = [row for row in added if row.get("setup_id") == family_setup_id]
    from_frozen = [row for row in added if row.get("setup_id") != family_setup_id]
    stream = describe_stream(added)
    stream.pop("months", None)
    months = _months()
    return {
        "new_trades_added": len(added),
        "added_by_the_candidate": len(from_family),
        "added_by_a_frozen_child": len(from_frozen),
        "baseline_trades_displaced": len(displaced),
        "displaced_by_setup": _by_setup(displaced),
        "added_by_setup": _by_setup(added),
        "net_trade_frequency_gain": (combined.total_trades - baseline.total_trades) / months,
        "net_trades": combined.total_trades - baseline.total_trades,
        "incremental_win_rate": stream["win_rate"],
        "incremental_profit_factor": stream["profit_factor"],
        "incremental_average_r": stream["average_r"],
        "incremental_total_r": stream["total_r"],
        "incremental_trades_per_month": len(added) / months,
        "incremental_monthly": _monthly(added),
        "incremental_concentration": concentration({**stream, "months": _monthly(added)}),
        "excursions": excursions(added),
        "displaced_stream": {k: v for k, v in describe_stream(displaced).items() if k != "months"},
        "displaced_excursions": excursions(displaced),
        "net_r_change": (sum(row["realized_r"] for row in combined.trade_log)
                         - sum(row["realized_r"] for row in baseline.trade_log)),
        "drawdown_delta_percent": (combined.max_drawdown_percent
                                   - baseline.max_drawdown_percent),
        "subperiod_net_r": [
            {"label": label,
             "added": len(slice_rows(added, _utc(start), _utc(end))),
             "added_r": sum(row["realized_r"]
                            for row in slice_rows(added, _utc(start), _utc(end))),
             "displaced": len(slice_rows(displaced, _utc(start), _utc(end))),
             "displaced_r": sum(row["realized_r"]
                                for row in slice_rows(displaced, _utc(start), _utc(end)))}
            for label, start, end in SUBPERIODS
        ],
    }


def verdict(family_result, contribution) -> dict[str, Any]:
    """The Phase D carry-forward standard, applied mechanically."""
    months = _months()
    reasons: list[str] = []
    per_month = contribution["incremental_trades_per_month"]
    factor = contribution["incremental_profit_factor"]
    average = contribution["incremental_average_r"]
    subperiods = contribution["subperiod_net_r"]
    positive_subperiods = sum(1 for item in subperiods
                              if item["added_r"] - item["displaced_r"] > 0)
    monthly = contribution["incremental_monthly"]
    best_month_r = max((item["total_r"] for item in monthly.values()), default=0.0)
    total_r = contribution["incremental_total_r"]
    single_month = bool(monthly) and total_r > 0 and best_month_r >= total_r

    if contribution["new_trades_added"] == 0:
        reasons.append("adds no trade to Core at all")
    if average is None or average <= 0:
        reasons.append(f"incremental expectancy is not positive (Avg R {average})")
    if factor is None or factor <= MIN_INCREMENTAL_PROFIT_FACTOR:
        reasons.append(f"incremental PF {factor} does not exceed {MIN_INCREMENTAL_PROFIT_FACTOR}")
    if per_month < MIN_INCREMENTAL_TRADES_PER_MONTH:
        reasons.append(f"incremental frequency {per_month:.2f}/month is below "
                       f"{MIN_INCREMENTAL_TRADES_PER_MONTH:.0f}/month")
    if positive_subperiods < 2:
        reasons.append(f"net contribution is positive in only {positive_subperiods} subperiod(s)")
    if single_month:
        reasons.append("the entire incremental total comes from one month")
    if contribution["baseline_trades_displaced"] > contribution["added_by_the_candidate"]:
        reasons.append("displaces more baseline trades than the candidate itself adds")
    return {
        "carry_forward": not reasons,
        "failed_criteria": reasons,
        "incremental_trades_per_month": per_month,
        "incremental_profit_factor": factor,
        "incremental_average_r": average,
        "positive_subperiods": positive_subperiods,
        "development_months": months,
    }


def run_phase_d(ledger_path: Path) -> dict[str, Any]:
    baseline = run_arm(CORE_BASELINE_ID, ledger_path)
    payload: dict[str, Any] = {
        "split": {
            "development_start": DEVELOPMENT_START.isoformat(),
            "development_end": DEVELOPMENT_END.isoformat(),
            "holdout_start": HOLDOUT_START.isoformat(),
            "holdout_end": HOLDOUT_END.isoformat(),
            "holdout_touched": False,
        },
        "dataset": {"key": DATASET_KEY, "path": str(dataset_path().relative_to(ROOT)),
                    "fingerprint": DATASET_FINGERPRINT},
        "core_baseline": family_metrics(baseline),
        "families": {},
    }
    for key, label in FAMILY_LABELS.items():
        standalone = run_arm(STANDALONE_IDS[key], ledger_path)
        combined = run_arm(CORE_IDS[key], ledger_path)
        contribution = incremental_contribution(baseline, combined, FAMILY_SETUP_IDS[key])
        payload["families"][key] = {
            "label": label,
            "setup_id": FAMILY_SETUP_IDS[key],
            "standalone": family_metrics(standalone),
            "core_combined": family_metrics(combined),
            "incremental": contribution,
            "verdict": verdict(standalone, contribution),
        }
    return payload


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.write_text(json.dumps(run_phase_d(args.ledger), default=str, indent=1))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
