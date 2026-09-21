"""BTC Core V2 — Phase F: transition-regime opportunity discovery, DEVELOPMENT only.

Phase D asked whether an additive family exists anywhere. Phase F asks it of one
specific place: the TRANSITION bucket, half the development split and almost
untouched by the frozen Core. The census in ``core_v2_phase_f_map`` establishes
the pool; this module measures what can actually be taken out of it.

Two measurements decide everything, and Phase E is the reason both are here.
D2 looked like a +15.20R incremental stream until the contention ledger showed
that 9 of the trades it "added" were really T3 trades it had blocked by holding
the position slot. So ``contention_ledger`` below is family-trade-centric and
splits a family's trades three ways: displacing a frozen trade on the same bar,
entering while the Core was flat and later blocking a frozen trade, and entering
while flat and costing nothing. Only the third is free.

``capacity`` is the second. A family that cannot reach the frequency target is
not worth a stability phase however good its handful of trades look, so the
funnel is reported end to end: raw events in the pool, setups the family finds,
fills it gets standalone, and trades the Core actually gains.

Nothing here reads past ``DEVELOPMENT_END``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from core.adapters.audited_engine import run_universal_backtest
from core.trade_log import to_timestamp
from engine.models import Candle, ExecutionState, Signal
from research.core_v2_phase_a import (
    DATASET_FINGERPRINT, DATASET_KEY, DEVELOPMENT_END, DEVELOPMENT_START,
    HOLDOUT_END, HOLDOUT_START, _timestamp, concentration, dataset_path,
    describe_stream, development_config, summarise, trade_delta,
)
from research.core_v2_phase_b import excursions
from research.core_v2_phase_c import _utc, metrics, slice_rows
from research import core_v2_phase_f_map as fmap
from strategies.btc_core_v2_phase_e_variants import order_events
from strategies.btc_core_v2_phase_f_families import (
    BASELINE_VARIANTS, CORE_IDS, FAMILY_LABELS, STANDALONE_IDS, VARIANTS,
    VARIANTS_BY_FAMILY, phase_f_registry,
)
from strategies.btc_v3_a4_pullback_long import SETUP_ID as A4_SETUP_ID
from strategies.btc_v3_t3_breakout_short import TREND_SETUP_ID as T3_SETUP_ID
from utils.data_validation import load_ohlcv_csv

ROOT = Path(__file__).resolve().parents[1]
CORE_BASELINE_ID = "BTC_V3_CORE_V1_FROZEN"

SUBPERIODS: tuple[tuple[str, str, str], ...] = (
    ("2023 partial", "2023-11-10 23:15", "2023-12-31 23:45"),
    ("2024 H1", "2024-01-01 00:00", "2024-06-30 23:45"),
    ("2024 H2", "2024-07-01 00:00", "2024-12-31 23:45"),
    ("2025 H1", "2025-01-01 00:00", "2025-06-30 23:45"),
)

#--- Phase F carry standard (brief section J), stated once so the verdict is mechanical.
MIN_INCREMENTAL_TRADES_PER_MONTH = 4.0
MIN_INCREMENTAL_PROFIT_FACTOR = 1.10
#--- Brief section I: below this, a family is rejected on capacity alone unless
#--- its edge is exceptional.
MINIMUM_VIABLE_TRADES_PER_MONTH = 2.0

#--- Which census events each family draws from, for the capacity funnel.
FAMILY_EVENT_POOL = {
    "F1": ("BREAKOUT_UP", "BREAKDOWN"),
    "F2": ("EMA20_CROSS_UP", "EMA20_CROSS_DOWN"),
    "F3": ("FAILED_BREAKOUT_REVERSAL_DOWN", "FAILED_BREAKDOWN_REVERSAL_UP"),
}

#--- Brief section C: every family that might duplicate a Phase F concept.
PRIOR_FAMILIES = {
    "PB1 shallow pullback": "BTC_PB1_SHALLOW_PULLBACK_V1",
    "PB2 reclaim LONG": "BTC_PB2_RECLAIM_LONG_V1",
    "PB2 reclaim SHORT": "BTC_PB2_RECLAIM_SHORT_V1",
    "PB3 pivot acceptance LONG": "BTC_PB3_PIVOT_ACCEPTANCE_LONG_V1",
    "V3-R2 range liquidity sweep": "BTC_V3_R2_RANGE_LIQUIDITY_SWEEP",
    "V3-M1 momentum expansion": "BTC_V3_M1_MOMENTUM_EXPANSION",
    "V3-MR1 intraday overshoot": "BTC_V3_MR1_INTRADAY_OVERSHOOT",
}


def run_arm(strategy_id: str, ledger_path: Path):
    config = development_config(strategy_id)
    if config.end_date >= HOLDOUT_START:
        raise ValueError("Phase F must not read the holdout split.")
    return run_universal_backtest(dataset_path(), config, ledger_path=ledger_path,
                                  registry=phase_f_registry())


def months() -> float:
    return (DEVELOPMENT_END - DEVELOPMENT_START).total_seconds() / (60 * 60 * 24 * 30.4375)


def development_candles() -> list[Candle]:
    frame = load_ohlcv_csv(dataset_path())
    frame = frame.loc[frame.timestamp.between(DEVELOPMENT_START, DEVELOPMENT_END)]
    return [Candle(r.timestamp, r.open, r.high, r.low, r.close, r.volume)
            for r in frame.itertuples(index=False)]


# --- reporting helpers -------------------------------------------------------------


def _monthly(rows: Sequence[dict]) -> dict[str, Any]:
    buckets: dict[str, list[dict]] = {}
    for row in rows:
        buckets.setdefault(_timestamp(row["entry_time"]).strftime("%Y-%m"), []).append(row)
    return {month: {"trades": len(group),
                    "total_r": sum(item["realized_r"] for item in group),
                    "wins": sum(1 for item in group if item["pnl"] > 1e-9)}
            for month, group in sorted(buckets.items())}


def _stream(rows: Sequence[dict]) -> dict[str, Any]:
    payload = describe_stream(rows)
    payload.pop("months", None)
    return payload


def lifecycle(result) -> dict[str, int]:
    events = result.execution_diagnostics.get("order_events", {})
    return {"setups": sum(events.values()), "orders": sum(events.values()),
            "fills": events.get("triggered", 0), "expired": events.get("expired", 0),
            "cancelled": events.get("cancelled", 0),
            "active_at_end": events.get("active_at_end", 0)}


def arm_metrics(result) -> dict[str, Any]:
    payload = summarise(result)
    payload.pop("monthly", None)
    payload["lifecycle"] = lifecycle(result)
    payload["subperiods"] = [
        {"label": label, **metrics(slice_rows(result.trade_log, _utc(start), _utc(end)),
                                   _utc(start), _utc(end))}
        for label, start, end in SUBPERIODS]
    payload["monthly"] = _monthly(result.trade_log)
    payload["excursions"] = excursions(result.trade_log)
    return payload


def _interval(row: dict) -> tuple[pd.Timestamp, pd.Timestamp]:
    return to_timestamp(row["entry_time"]), to_timestamp(row["exit_time"])


def _key(row: dict) -> tuple:
    return (row.get("setup_id"), row["direction"], to_timestamp(row["entry_time"]).isoformat())


def _by_setup(rows: Sequence[dict]) -> dict[str, Any]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row.get("setup_id") or "UNKNOWN", []).append(row)
    return {setup: {"trades": len(group),
                    "total_r": sum(item["realized_r"] for item in group)}
            for setup, group in sorted(groups.items())}


# --- the contention ledger ----------------------------------------------------------


def _describe(rows: Sequence[dict]) -> dict[str, Any]:
    total = sum(row["realized_r"] for row in rows)
    return {"count": len(rows), "total_r": total,
            "average_r": (total / len(rows)) if rows else None}


def contention_ledger(baseline, combined, standalone, family_setup_id: str) -> dict[str, Any]:
    """What each of the family's Core trades actually cost.

    Phase E's lesson, generalised: a trade that enters on a bar where the Core
    was flat still is not free if the family is *still holding* when A4 or T3
    next wants the slot. ``entered_flat_then_blocked_frozen`` is that case, kept
    separate from ``truly_additive``, because summing them is exactly the error
    that made D2 look like a +15R idea.
    """
    base_by_key = {_key(row): row for row in baseline.trade_log}
    combined_by_key = {_key(row): row for row in combined.trade_log}
    combined_intervals = sorted((*_interval(row), row) for row in combined.trade_log)
    baseline_intervals = sorted((*_interval(row), row) for row in baseline.trade_log)
    combined_pending = [(pd.Timestamp(event.created_time),
                         pd.Timestamp(event.fill_time if event.fill_time is not None
                                      else event.expiry_time), event.setup_id)
                        for event in order_events(combined)]

    def occupying(stamp, intervals):
        return next((row for start, end, row in intervals if start <= stamp <= end), None)

    #--- Baseline trades that no longer happen, and who took the slot.
    lost: dict[str, list[dict]] = {"displaced_same_bar": [], "blocked_while_holding": [],
                                   "lost_for_another_reason": []}
    lost_entry_times: list[pd.Timestamp] = []
    for key, row in base_by_key.items():
        if key in combined_by_key:
            continue
        entry = to_timestamp(row["entry_time"])
        occupant = occupying(entry, combined_intervals)
        if occupant is None or occupant.get("setup_id") != family_setup_id:
            lost["lost_for_another_reason"].append(row)
            continue
        same_bar = to_timestamp(occupant["entry_time"]) == entry
        lost["displaced_same_bar" if same_bar else "blocked_while_holding"].append(row)
        lost_entry_times.append(entry)

    #--- Family trades, classified by what they displaced or blocked.
    family_rows = [row for row in combined.trade_log
                   if row.get("setup_id") == family_setup_id]
    classes: dict[str, list[dict]] = {
        "truly_additive": [], "entered_flat_then_blocked_frozen": [],
        "displaced_a_frozen_trade_on_entry": []}
    for row in family_rows:
        start, end = _interval(row)
        entry_clash = any(b_start <= start <= b_end for b_start, b_end, _ in baseline_intervals)
        blocks_later = any(start < stamp <= end for stamp in lost_entry_times)
        if entry_clash and any(b_start == start for b_start, _, _ in baseline_intervals):
            classes["displaced_a_frozen_trade_on_entry"].append(row)
        elif blocks_later:
            classes["entered_flat_then_blocked_frozen"].append(row)
        elif entry_clash:
            classes["displaced_a_frozen_trade_on_entry"].append(row)
        else:
            classes["truly_additive"].append(row)

    #--- Family setups the frozen pair prevented from ever reaching the Core.
    reached = {to_timestamp(row["entry_time"]) for row in family_rows}
    suppressed: dict[str, list[dict]] = {"core_held_a_position": [], "core_held_a_pending_order": []}
    for row in standalone.trade_log:
        entry = to_timestamp(row["entry_time"])
        if entry in reached:
            continue
        occupant = occupying(entry, combined_intervals)
        if occupant is not None and occupant.get("setup_id") != family_setup_id:
            suppressed["core_held_a_position"].append(row)
            continue
        if any(start <= entry <= end and setup != family_setup_id
               for start, end, setup in combined_pending):
            suppressed["core_held_a_pending_order"].append(row)
        else:
            suppressed["core_held_a_position"].append(row)

    payload = {name: _describe(rows) for name, rows in classes.items()}
    payload.update({f"frozen_{name}": {**_describe(rows), "by_setup": _by_setup(rows)}
                    for name, rows in lost.items()})
    payload.update({f"family_setup_{name}": _describe(rows)
                    for name, rows in suppressed.items()})
    #--- The single number Phase E wished it had had on the first pass.
    free = classes["truly_additive"]
    cost = lost["displaced_same_bar"] + lost["blocked_while_holding"]
    payload["net_free_contribution_r"] = (sum(row["realized_r"] for row in free)
                                          - sum(row["realized_r"] for row in cost))
    payload["percent_of_family_trades_that_cost_a_frozen_trade"] = (
        round(100 * (len(classes["entered_flat_then_blocked_frozen"])
                     + len(classes["displaced_a_frozen_trade_on_entry"])) / len(family_rows), 2)
        if family_rows else None)
    return payload


# --- incremental contribution -------------------------------------------------------


def incremental(baseline, combined, family_setup_id: str) -> dict[str, Any]:
    delta = trade_delta(baseline.trade_log, combined.trade_log)
    added, displaced = delta.added, delta.displaced
    stream = _stream(added)
    monthly = _monthly(added)
    per_month = len(added) / months()
    return {
        "new_trades_added": len(added),
        "added_by_the_candidate": sum(1 for row in added
                                      if row.get("setup_id") == family_setup_id),
        "added_by_a_frozen_child": sum(1 for row in added
                                       if row.get("setup_id") != family_setup_id),
        "baseline_trades_displaced": len(displaced),
        "displaced_by_setup": _by_setup(displaced),
        "added_by_setup": _by_setup(added),
        "net_trades": combined.total_trades - baseline.total_trades,
        "incremental_trades_per_month": per_month,
        "incremental_win_rate": stream["win_rate"],
        "incremental_profit_factor": stream["profit_factor"],
        "incremental_average_r": stream["average_r"],
        "incremental_total_r": stream["total_r"],
        "incremental_monthly": monthly,
        "incremental_concentration": concentration({**stream, "months": monthly}),
        "excursions": excursions(added),
        "displaced_stream": _stream(displaced),
        "net_r_change": (sum(row["realized_r"] for row in combined.trade_log)
                         - sum(row["realized_r"] for row in baseline.trade_log)),
        "drawdown_delta_percent": (combined.max_drawdown_percent
                                   - baseline.max_drawdown_percent),
        "subperiod_net_r": [
            {"label": label,
             "added": len(slice_rows(added, _utc(start), _utc(end))),
             "added_r": sum(row["realized_r"] for row in slice_rows(added, _utc(start), _utc(end))),
             "displaced": len(slice_rows(displaced, _utc(start), _utc(end))),
             "displaced_r": sum(row["realized_r"]
                                for row in slice_rows(displaced, _utc(start), _utc(end)))}
            for label, start, end in SUBPERIODS],
    }


# --- frequency capacity --------------------------------------------------------------


def shadow_setups(variant_key: str, candles: Sequence[Candle]) -> int:
    """Setups the family finds with no position ever blocking it.

    The standalone backtest already throttles on its own single position slot,
    so its fill count understates the pool. This is the unconstrained count, and
    it is what "valid setups/month" in the capacity funnel has to mean.
    """
    from strategies.btc_core_v2_phase_f_families import VARIANT_FACTORIES

    strategy = VARIANT_FACTORIES[variant_key]()
    strategy.reset()
    found = 0
    for candle in candles:
        strategy.on_execution_state(ExecutionState(10_000.0, None, None, None, None))
        if isinstance(strategy.on_candle(candle), Signal):
            found += 1
    return found


def capacity(family: str, variant_key: str, event_map: dict[str, Any], setups: int,
             standalone, contribution: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    """Transition opportunity -> setup -> fill -> actual additional Core trade."""
    span = months()
    raw = sum(event_map.get(name, {}).get("events", 0) for name in FAMILY_EVENT_POOL[family])
    free = ledger["truly_additive"]["count"]
    return {
        "raw_events": raw,
        "raw_events_per_month": round(raw / span, 2),
        "valid_setups": setups,
        "valid_setups_per_month": round(setups / span, 2),
        "standalone_fills": standalone.total_trades,
        "standalone_fills_per_month": round(standalone.total_trades / span, 2),
        "incremental_core_trades_per_month": round(
            contribution["incremental_trades_per_month"], 2),
        "genuinely_free_core_trades": free,
        "genuinely_free_core_trades_per_month": round(free / span, 2),
        "conversion_event_to_setup_percent": round(100 * setups / raw, 2) if raw else None,
        "conversion_setup_to_fill_percent": (
            round(100 * standalone.total_trades / setups, 2) if setups else None),
        "conversion_fill_to_free_core_trade_percent": (
            round(100 * free / standalone.total_trades, 2) if standalone.total_trades else None),
    }


# --- the verdict ----------------------------------------------------------------------


def verdict(standalone, contribution: dict[str, Any], ledger: dict[str, Any],
            capacity_payload: dict[str, Any]) -> dict[str, Any]:
    """Brief sections I and J, applied mechanically and in that order."""
    rejections: list[str] = []
    shortfalls: list[str] = []

    standalone_pf = standalone.profit_factor
    if standalone_pf is None or standalone_pf < 1.0:
        rejections.append(f"standalone PF {standalone_pf} is below 1")

    per_month = contribution["incremental_trades_per_month"]
    factor = contribution["incremental_profit_factor"]
    average = contribution["incremental_average_r"]
    if contribution["new_trades_added"] == 0:
        rejections.append("adds no trade to the Core at all")
    if factor is not None and factor <= 1.0:
        rejections.append(f"incremental PF {factor:.4f} is not above 1")
    if average is not None and average <= 0:
        rejections.append(f"incremental Avg R {average:+.4f} is not positive")

    subperiods = contribution["subperiod_net_r"]
    traded = [item for item in subperiods if item["added"] or item["displaced"]]
    positive = [item for item in traded if item["added_r"] - item["displaced_r"] > 0]
    net_total = sum(item["added_r"] - item["displaced_r"] for item in traded)
    if traded and net_total > 0:
        best = max(item["added_r"] - item["displaced_r"] for item in traded)
        if best >= net_total:
            rejections.append("one subperiod carries the entire net contribution")
    monthly = contribution["incremental_monthly"]
    total_r = contribution["incremental_total_r"]
    if monthly and total_r > 0:
        best_month = max(item["total_r"] for item in monthly.values())
        if best_month >= total_r:
            rejections.append("the best single month carries the entire incremental total")

    costly = ledger["percent_of_family_trades_that_cost_a_frozen_trade"]
    if costly is not None and costly >= 50.0:
        rejections.append(f"{costly:.1f}% of the family's Core trades displace or "
                          "block a frozen trade")

    if per_month < MINIMUM_VIABLE_TRADES_PER_MONTH:
        rejections.append(f"incremental frequency {per_month:.2f}/month is below the "
                          f"{MINIMUM_VIABLE_TRADES_PER_MONTH:.0f}/month viability floor")

    mfe = contribution["excursions"].get("mfe_r")
    mae = contribution["excursions"].get("mae_r")
    if mfe is not None and mae is not None and mfe <= abs(mae):
        rejections.append(f"MFE {mfe:.2f}R does not exceed MAE {abs(mae):.2f}R")

    #--- Section J, the carry standard, checked only once nothing above fired.
    if factor is None or factor <= MIN_INCREMENTAL_PROFIT_FACTOR:
        shortfalls.append(f"incremental PF {factor} does not exceed "
                          f"{MIN_INCREMENTAL_PROFIT_FACTOR}")
    if per_month < MIN_INCREMENTAL_TRADES_PER_MONTH:
        shortfalls.append(f"incremental frequency {per_month:.2f}/month is below "
                          f"{MIN_INCREMENTAL_TRADES_PER_MONTH:.0f}/month")
    if len(positive) < 2:
        shortfalls.append(f"net contribution is positive in only {len(positive)} subperiod(s)")
    if capacity_payload["genuinely_free_core_trades_per_month"] < MIN_INCREMENTAL_TRADES_PER_MONTH:
        shortfalls.append(
            f"only {capacity_payload['genuinely_free_core_trades_per_month']:.2f} genuinely "
            f"free Core trades/month")

    return {
        "rejected": bool(rejections),
        "rejection_reasons": rejections,
        "carry_forward": not rejections and not shortfalls,
        "carry_shortfalls": shortfalls,
        "positive_subperiods": len(positive),
        "incremental_trades_per_month": per_month,
        "incremental_profit_factor": factor,
        "incremental_average_r": average,
    }


# --- prior-research audit --------------------------------------------------------------


def prior_research_audit(ledger_path: Path, bucket_by_bar: dict) -> dict[str, Any]:
    """Which regime buckets the already-rejected families actually traded in.

    Section C asks whether a Phase F concept duplicates a closed one. The
    decisive evidence is not the docstrings — it is whether those families were
    already running on these bars. Entry bars are used rather than signal bars,
    which puts each trade one to two bars after its setup; the bucket is stable
    over that distance and the conclusions here do not turn on single bars.
    """
    audit: dict[str, Any] = {}
    for label, strategy_id in PRIOR_FAMILIES.items():
        result = run_universal_backtest(dataset_path(), development_config(strategy_id),
                                        ledger_path=ledger_path, registry=phase_f_registry())
        counts: dict[str, int] = {}
        for row in result.trade_log:
            bucket = bucket_by_bar.get(to_timestamp(row["entry_time"]), "UNKNOWN")
            counts[bucket] = counts.get(bucket, 0) + 1
        total = result.total_trades
        audit[label] = {
            "strategy_id": strategy_id,
            "status": "REJECTED",
            "closed_trades": total,
            "total_r": sum(row["realized_r"] for row in result.trade_log),
            "profit_factor": result.profit_factor,
            "entries_by_bucket": counts,
            "percent_on_transition_bars": (
                round(100 * counts.get("TRANSITION", 0) / total, 2) if total else None),
        }
    return audit


# --- the phase ---------------------------------------------------------------------------


def run_phase_f(ledger_path: Path, *, include_audit: bool = True) -> dict[str, Any]:
    candles = development_candles()
    baseline = run_arm(CORE_BASELINE_ID, ledger_path)

    bars = fmap.census(candles)
    fmap.mark_coverage(bars, baseline.trade_log)
    census = fmap.summarise(bars, months())
    bucket_by_bar = {bar.timestamp: bar.bucket for bar in bars}

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
        "transition_census": census,
        "core_baseline": arm_metrics(baseline),
        "families": {},
    }
    if include_audit:
        payload["prior_research_audit"] = prior_research_audit(ledger_path, bucket_by_bar)

    event_map = census["events_on_transition_bars"]
    for family, label in FAMILY_LABELS.items():
        arms: dict[str, Any] = {}
        for variant in VARIANTS_BY_FAMILY[family]:
            standalone = run_arm(STANDALONE_IDS[variant.key], ledger_path)
            combined = run_arm(CORE_IDS[variant.key], ledger_path)
            contribution = incremental(baseline, combined, variant.setup_id)
            ledger = contention_ledger(baseline, combined, standalone, variant.setup_id)
            setups = shadow_setups(variant.key, candles)
            capacity_payload = capacity(family, variant.key, event_map, setups,
                                        standalone, contribution, ledger)
            arms[variant.key] = {
                "label": variant.label,
                "baseline_variant": variant.baseline,
                "standalone": arm_metrics(standalone),
                "core_combined": arm_metrics(combined),
                "incremental": contribution,
                "contention": ledger,
                "capacity": capacity_payload,
                "verdict": verdict(standalone, contribution, ledger, capacity_payload),
            }
        payload["families"][family] = {
            "label": label,
            "setup_id": VARIANTS_BY_FAMILY[family][0].setup_id,
            "baseline_variant": BASELINE_VARIANTS[family],
            "event_pool": list(FAMILY_EVENT_POOL[family]),
            "variants": arms,
        }
    return payload


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--skip-audit", action="store_true")
    args = parser.parse_args()
    payload = run_phase_f(args.ledger, include_audit=not args.skip_audit)
    args.out.write_text(json.dumps(payload, default=str, indent=1))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
