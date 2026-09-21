"""BTC Core V2 — Phase E: stability and integration study of the D2 A4-SHORT mirror.

Phase D produced one survivor. Phase E asks the Phase C questions of it — does
the edge appear in several independent periods, does one month carry it, does it
survive execution stress and tiny parameter changes — and adds the question
Phase D raised but could not answer: D2 displaced nine frozen T3 trades that
averaged +1.185R, so is D2 an addition or a substitution?

That last question gets its own machinery. The contention ledger classifies
every occasion where adding D2 changes a frozen-Core trade path, and two
deterministic integration policies are compared: the Phase D ordering, and one
where D2 may act only where the baseline frozen Core was idle. No third policy
is invented; the point is to separate D2's edge from its priority.

As in Phase C, subperiods and rolling windows slice the trades of one continuous
DEVELOPMENT run rather than re-running on truncated data, so that a cold start
cannot masquerade as a regime difference.
"""
from __future__ import annotations

from pathlib import Path
from statistics import median
from typing import Any, Iterable, Sequence

import pandas as pd

from core.adapters.audited_engine import run_universal_backtest
from core.trade_log import to_timestamp
from research.core_v2_phase_a import (
    DATASET_FINGERPRINT, DATASET_KEY, DEVELOPMENT_END, DEVELOPMENT_START,
    HOLDOUT_END, HOLDOUT_START, concentration, dataset_path, describe_stream,
    development_config, summarise, trade_delta,
)
from research.core_v2_phase_b import excursions
from research.core_v2_phase_c import _utc, block_bootstrap, leave_out, metrics, slice_rows
from research.core_v2_phase_d import SUBPERIODS, _monthly
from strategies.btc_core_v2_phase_d_families import D2_SETUP_ID, STANDALONE_IDS
from strategies.btc_core_v2_phase_e_variants import (
    ARM_BASELINE, D2_IMPLEMENTATION_HASH, MIRRORED_PARAMETERS, POLICY_IDS,
    SENSITIVITY_ARMS, SENSITIVITY_CORE_IDS, SENSITIVITY_IDS, assert_d2_unchanged,
    baseline_timeline, busy_intervals, order_events, phase_e_registry,
)
from strategies.btc_v3_a4_pullback_long import SETUP_ID as A4_SETUP_ID
from strategies.btc_v3_t3_breakout_short import TREND_SETUP_ID as T3_SETUP_ID

ROOT = Path(__file__).resolve().parents[1]
CORE_BASELINE_ID = "BTC_V3_CORE_V1_FROZEN"

BOOTSTRAP_SAMPLES = 10_000
#--- n^(1/3) for n=28 is 3.0. Blocks of 2-4 span the observed monthly clusters;
#--- 1 is the plain iid bootstrap, reported so the effect of blocking is visible.
BOOTSTRAP_BLOCKS: tuple[int, ...] = (1, 2, 3, 4)
PRIMARY_BLOCK = 3

EXECUTION_STRESS: tuple[tuple[str, float, float], ...] = (
    ("NATIVE", 1.0, 0.0),
    ("SPREAD_x1.10", 1.10, 0.0),
    ("SPREAD_x1.20", 1.20, 0.0),
    ("SLIPPAGE_0.02%", 1.0, 0.02),
    ("SLIPPAGE_0.05%", 1.0, 0.05),
    ("SPREAD_x1.20_SLIP_0.02%", 1.20, 0.02),
)


def run_arm(strategy_id: str, ledger_path: Path, **overrides):
    config = development_config(strategy_id)
    if overrides:
        from dataclasses import replace
        config = replace(config, **overrides)
    if config.end_date >= HOLDOUT_START:
        raise ValueError("Phase E must not read the holdout split.")
    return run_universal_backtest(dataset_path(), config, ledger_path=ledger_path,
                                  registry=phase_e_registry())


def _months(start: pd.Timestamp, end: pd.Timestamp) -> float:
    return max((end - start).total_seconds() / (60 * 60 * 24 * 30.4375), 1e-9)


def _stream(rows: Sequence[dict]) -> dict[str, Any]:
    payload = describe_stream(rows)
    payload.pop("months", None)
    return payload


def _split_displaced(rows: Sequence[dict]) -> dict[str, Any]:
    by_setup: dict[str, list[dict]] = {}
    for row in rows:
        by_setup.setdefault(row.get("setup_id") or "UNKNOWN", []).append(row)
    return {setup: {"trades": len(group),
                    "total_r": sum(item["realized_r"] for item in group)}
            for setup, group in sorted(by_setup.items())}


# --- A / B: sliced comparisons ----------------------------------------------------


def compare_window(label: str, start, end, baseline_rows, combined_rows,
                   added, displaced) -> dict[str, Any]:
    start, end = _utc(start), _utc(end)
    base_slice = slice_rows(baseline_rows, start, end)
    combined_slice = slice_rows(combined_rows, start, end)
    added_slice = slice_rows(added, start, end)
    displaced_slice = slice_rows(displaced, start, end)
    incremental = _stream(added_slice)
    return {
        "label": label, "start": start.isoformat(), "end": end.isoformat(),
        "baseline": metrics(base_slice, start, end),
        "combined": metrics(combined_slice, start, end),
        "added": incremental,
        "added_by_d2": sum(1 for row in added_slice if row.get("setup_id") == D2_SETUP_ID),
        "displaced": _stream(displaced_slice),
        "displaced_by_setup": _split_displaced(displaced_slice),
        "baseline_total_r": sum(row["realized_r"] for row in base_slice),
        "combined_total_r": sum(row["realized_r"] for row in combined_slice),
        "delta_total_r": (sum(row["realized_r"] for row in combined_slice)
                          - sum(row["realized_r"] for row in base_slice)),
        "incremental_profit_factor": incremental["profit_factor"],
        "incremental_average_r": incremental["average_r"],
    }


def rolling(length_months: int, baseline_rows, combined_rows, added, displaced) -> dict[str, Any]:
    windows: list[dict[str, Any]] = []
    start = DEVELOPMENT_START
    while start + pd.DateOffset(months=length_months) <= DEVELOPMENT_END + pd.Timedelta(minutes=15):
        end = min(start + pd.DateOffset(months=length_months) - pd.Timedelta(minutes=15),
                  DEVELOPMENT_END)
        windows.append(compare_window(f"{start.date()}→{end.date()}", start, end,
                                      baseline_rows, combined_rows, added, displaced))
        start = start + pd.DateOffset(months=1)
    deltas = [window["delta_total_r"] for window in windows]
    tolerance = 1 / 3
    return {
        "length_months": length_months, "step_months": 1, "windows": windows,
        "summary": {
            "count": len(windows),
            "improved": sum(1 for value in deltas if value > tolerance),
            "degraded": sum(1 for value in deltas if value < -tolerance),
            "neutral": sum(1 for value in deltas if abs(value) <= tolerance),
            "worst_delta_r": min(deltas) if deltas else None,
            "median_delta_r": median(deltas) if deltas else None,
            "best_delta_r": max(deltas) if deltas else None,
            "windows_with_added_trades": sum(1 for w in windows if w["added"]["trades"]),
            "neutral_tolerance_r": tolerance,
        },
    }


# --- G: contention ledger -----------------------------------------------------------


def _interval(row: dict) -> tuple[pd.Timestamp, pd.Timestamp]:
    return to_timestamp(row["entry_time"]), to_timestamp(row["exit_time"])


def _key(row: dict) -> tuple:
    return (row.get("setup_id"), row["direction"], to_timestamp(row["entry_time"]).isoformat())


def contention_ledger(baseline, combined, standalone) -> dict[str, Any]:
    """Every occasion where adding D2 changes a frozen-Core trade path."""
    base_by_key = {_key(row): row for row in baseline.trade_log}
    combined_by_key = {_key(row): row for row in combined.trade_log}
    combined_intervals = [(*_interval(row), row) for row in combined.trade_log]
    combined_intervals.sort()
    baseline_intervals = [(*_interval(row), row) for row in baseline.trade_log]
    baseline_intervals.sort()
    combined_pending = [(pd.Timestamp(event.created_time),
                         pd.Timestamp(event.fill_time if event.fill_time is not None
                                      else event.expiry_time), event.setup_id)
                        for event in order_events(combined)]

    def occupying(stamp: pd.Timestamp, intervals):
        return next((row for start, end, row in intervals if start <= stamp <= end), None)

    classes: dict[str, list[dict]] = {
        "d2_additive": [], "d2_displaces_t3": [], "d2_displaces_a4": [],
        "d2_blocks_later_t3": [], "d2_blocks_later_a4": [],
        "baseline_blocks_d2_open_position": [], "baseline_blocks_d2_pending_order": [],
        "baseline_trade_lost_other": [],
    }

    #--- Baseline trades that no longer happen once D2 is present.
    for key, row in base_by_key.items():
        if key in combined_by_key:
            continue
        entry = to_timestamp(row["entry_time"])
        occupant = occupying(entry, combined_intervals)
        side = "t3" if row.get("setup_id") == T3_SETUP_ID else (
            "a4" if row.get("setup_id") == A4_SETUP_ID else None)
        if occupant is None or side is None:
            classes["baseline_trade_lost_other"].append(row)
            continue
        if occupant.get("setup_id") != D2_SETUP_ID:
            classes["baseline_trade_lost_other"].append(row)
            continue
        same_bar = to_timestamp(occupant["entry_time"]) == entry
        classes[f"d2_{'displaces' if same_bar else 'blocks_later'}_{side}"].append(row)

    #--- D2 trades that reached the Core, and whether they cost anything.
    for row in combined.trade_log:
        if row.get("setup_id") != D2_SETUP_ID:
            continue
        start, end = _interval(row)
        clashes = any(not (b_end < start or b_start > end)
                      for b_start, b_end, _ in baseline_intervals)
        if not clashes:
            classes["d2_additive"].append(row)

    #--- D2 trades the frozen pair prevented: present standalone, absent combined.
    combined_d2_entries = {to_timestamp(row["entry_time"]) for row in combined.trade_log
                           if row.get("setup_id") == D2_SETUP_ID}
    for row in standalone.trade_log:
        entry = to_timestamp(row["entry_time"])
        if entry in combined_d2_entries:
            continue
        occupant = occupying(entry, combined_intervals)
        if occupant is not None and occupant.get("setup_id") != D2_SETUP_ID:
            classes["baseline_blocks_d2_open_position"].append(row)
            continue
        pending = any(start <= entry <= end and setup != D2_SETUP_ID
                      for start, end, setup in combined_pending)
        if pending:
            classes["baseline_blocks_d2_pending_order"].append(row)
        else:
            classes["baseline_blocks_d2_open_position"].append(row)

    return {
        name: {"count": len(rows),
               "total_r": sum(row["realized_r"] for row in rows),
               "average_r": (sum(row["realized_r"] for row in rows) / len(rows)) if rows else None}
        for name, rows in classes.items()
    }


def policy_summary(baseline, result) -> dict[str, Any]:
    delta = trade_delta(baseline.trade_log, result.trade_log)
    added = _stream(delta.added)
    payload = summarise(result)
    payload.pop("monthly", None)
    return {
        "summary": payload,
        "d2_trades_retained": sum(1 for row in result.trade_log
                                  if row.get("setup_id") == D2_SETUP_ID),
        "baseline_trades_displaced": len(delta.displaced),
        "displaced_by_setup": _split_displaced(delta.displaced),
        "displaced_stream": _stream(delta.displaced),
        "incremental": added,
        "incremental_excursions": excursions(delta.added),
        "net_r_change": (sum(row["realized_r"] for row in result.trade_log)
                         - sum(row["realized_r"] for row in baseline.trade_log)),
        "drawdown_delta_percent": result.max_drawdown_percent - baseline.max_drawdown_percent,
    }


# --- the phase ----------------------------------------------------------------------


def run_phase_e(ledger_path: Path) -> dict[str, Any]:
    digest = assert_d2_unchanged()
    baseline = run_arm(CORE_BASELINE_ID, ledger_path)
    standalone = run_arm(STANDALONE_IDS["D2"], ledger_path)
    policy1 = run_arm(POLICY_IDS["POLICY1"], ledger_path)
    with baseline_timeline(busy_intervals(baseline)):
        policy2 = run_arm(POLICY_IDS["POLICY2"], ledger_path)

    delta = trade_delta(baseline.trade_log, policy1.trade_log)
    added, displaced = delta.added, delta.displaced

    payload: dict[str, Any] = {
        "d2_source_hash": digest,
        "d2_source_hash_expected": D2_IMPLEMENTATION_HASH,
        "split": {
            "development_start": DEVELOPMENT_START.isoformat(),
            "development_end": DEVELOPMENT_END.isoformat(),
            "holdout_start": HOLDOUT_START.isoformat(),
            "holdout_end": HOLDOUT_END.isoformat(),
            "holdout_touched": False,
        },
        "dataset": {"key": DATASET_KEY, "path": str(dataset_path().relative_to(ROOT)),
                    "fingerprint": DATASET_FINGERPRINT},
        "reference": {
            "core_baseline": {k: v for k, v in summarise(baseline).items() if k != "monthly"},
            "d2_standalone": {k: v for k, v in summarise(standalone).items() if k != "monthly"},
            "core_plus_d2": {k: v for k, v in summarise(policy1).items() if k != "monthly"},
            "incremental": {**_stream(added), "excursions": excursions(added)},
        },
        "mirrored_parameters": [{"parameter": name, "baseline": note}
                                for name, note in MIRRORED_PARAMETERS],
    }

    # A. subperiods, standalone and integrated
    payload["subperiods"] = {
        "standalone": [{"label": label,
                        **metrics(slice_rows(standalone.trade_log, _utc(start), _utc(end)),
                                  _utc(start), _utc(end))}
                       for label, start, end in SUBPERIODS],
        "integrated": [compare_window(label, start, end, baseline.trade_log,
                                      policy1.trade_log, added, displaced)
                       for label, start, end in SUBPERIODS],
    }

    # B. rolling
    payload["rolling"] = {f"{length}m": rolling(length, baseline.trade_log, policy1.trade_log,
                                                added, displaced)
                          for length in (3, 6)}

    # C. leave-one-out
    months = sorted({to_timestamp(row["entry_time"]).strftime("%Y-%m") for row in added})
    payload["leave_one_month_out"] = [leave_out(added, drop=month) for month in months]
    payload["leave_year_out"] = [leave_out(added, drop=str(year), by="year")
                                 for year in ("2023", "2024", "2025")]
    h1_2025 = [row for row in added
               if not (_utc("2025-01-01 00:00") <= to_timestamp(row["entry_time"])
                       <= _utc("2025-06-30 23:45"))]
    payload["leave_2025_h1_out"] = {**_stream(h1_2025), "dropped_trades": len(added) - len(h1_2025)}

    # D. bootstrap
    payload["bootstrap"] = {
        "primary_block": PRIMARY_BLOCK,
        "blocks": {str(block): block_bootstrap(added, block=block, samples=BOOTSTRAP_SAMPLES)
                   for block in BOOTSTRAP_BLOCKS},
        "caveat": ("Twenty-eight observations. These quantiles describe the spread this "
                   "sample implies under resampling; they are not a significance test."),
    }

    # E. local parameter stability
    payload["parameter_stability"] = _parameter_stability(baseline, ledger_path)

    # F. execution stress
    payload["execution_stress"] = _execution_stress(ledger_path)

    # G. contention and policies
    payload["contention_ledger"] = contention_ledger(baseline, policy1, standalone)
    payload["policies"] = {
        "baseline": {k: v for k, v in summarise(baseline).items() if k != "monthly"},
        "policy_1": policy_summary(baseline, policy1),
        "policy_2": policy_summary(baseline, policy2),
        "policy_2_suppressed_signals": getattr(policy2, "_suppressed", None),
    }
    payload["incremental_monthly"] = _monthly(added)
    payload["incremental_concentration"] = concentration(
        {**_stream(added), "months": _monthly(added)})
    return payload


def _parameter_stability(baseline, ledger_path: Path) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for arm, (label, values, _) in SENSITIVITY_ARMS.items():
        arms: dict[str, Any] = {}
        for value in values:
            standalone = run_arm(SENSITIVITY_IDS[(arm, value)], ledger_path)
            combined = run_arm(SENSITIVITY_CORE_IDS[(arm, value)], ledger_path)
            delta = trade_delta(baseline.trade_log, combined.trade_log)
            arms[f"{value}"] = {
                "value": value,
                "is_baseline": value == ARM_BASELINE[arm],
                "standalone": {k: v for k, v in summarise(standalone).items() if k != "monthly"},
                "combined": {k: v for k, v in summarise(combined).items() if k != "monthly"},
                "added": _stream(delta.added),
                "displaced_by_setup": _split_displaced(delta.displaced),
                "baseline_trades_displaced": len(delta.displaced),
                "net_r_change": (sum(row["realized_r"] for row in combined.trade_log)
                                 - sum(row["realized_r"] for row in baseline.trade_log)),
            }
        output[arm] = {"parameter": label, "baseline": ARM_BASELINE[arm], "arms": arms}
    return output


def _execution_stress(ledger_path: Path) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for label, multiplier, slippage in EXECUTION_STRESS:
        overrides = {"spread_multiplier": multiplier, "slippage_percent": slippage}
        baseline = run_arm(CORE_BASELINE_ID, ledger_path, **overrides)
        standalone = run_arm(STANDALONE_IDS["D2"], ledger_path, **overrides)
        combined = run_arm(POLICY_IDS["POLICY1"], ledger_path, **overrides)
        delta = trade_delta(baseline.trade_log, combined.trade_log)
        output[label] = {
            "spread_multiplier": multiplier, "slippage_percent": slippage,
            "d2_standalone": {k: v for k, v in summarise(standalone).items() if k != "monthly"},
            "core_baseline": {k: v for k, v in summarise(baseline).items() if k != "monthly"},
            "core_plus_d2": {k: v for k, v in summarise(combined).items() if k != "monthly"},
            "incremental": _stream(delta.added),
            "displaced": _stream(delta.displaced),
            "net_r_change": (sum(row["realized_r"] for row in combined.trade_log)
                             - sum(row["realized_r"] for row in baseline.trade_log)),
        }
    return output


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.write_text(json.dumps(run_phase_e(args.ledger), default=str, indent=1))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
