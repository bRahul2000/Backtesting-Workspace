"""BTC Architecture Reset A — reward/exit feasibility, DEVELOPMENT only.

Phase G closed the fixed-3R question: across 24 event x direction cells and
42,415 measured trades, no transition pool was distinguishable from the 25% that
a driftless path produces at 3:1, and the broker's spread was larger than any
gross drift. This study changes exactly one constraint — the 3 in that ratio —
and asks whether a lower target has a payoff zone that 3R did not.

It is a feasibility curve, not an optimizer. No entry is changed, no filter is
added, no family is built. The same events, the same structural stops and the
same frozen entry streams are re-evaluated at seven targets, and the question is
whether a *region* of adjacent targets is positive, not whether some single
value prints well.

Two structural facts shape how the results have to be read.

**The break-even rate moves with the target.** A target of R against a 1R stop
needs w = 1/(1+R): 50% at 1.0R, 40% at 1.5R, 33.3% at 2.0R, 25% at 3.0R. A
lower target buys a higher hit rate at exactly the rate it costs. Comparing raw
win rates across targets is meaningless; only the distance from each target's
own break-even means anything.

**Lowering the target is not a pure exit change in a single-position system.**
Trades finish sooner, the slot frees sooner, and later setups that were
previously blocked become reachable. Frozen A4 produces 93 filled trades at 3.0R
and 101 at 1.5R from an identical *signal* stream. Section A measures events
independently and so gives the pure payoff curve; sections B and C measure the
real system and so include the slot-recycling effect. Both are reported, because
they answer different questions and a reader who conflates them will
misattribute the difference.

Nothing here reads past ``DEVELOPMENT_END``.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import mean, median
from typing import Any, Sequence

import numpy as np
import pandas as pd

from core.adapters.audited_engine import run_universal_backtest
from core.config import BacktestConfig
from core.trade_log import to_timestamp
from engine.models import Candle
from research.core_v2_phase_a import (
    DATASET_FINGERPRINT, DATASET_KEY, DEVELOPMENT_END, DEVELOPMENT_START,
    HOLDOUT_END, HOLDOUT_START, dataset_path, development_config,
)
from research.core_v2_phase_c import _utc, metrics, slice_rows
from research.core_v2_phase_f import development_candles, months
from research.core_v2_phase_g import development_spreads
from research import core_v2_phase_g_outcomes as g
from strategies.btc_core_v2_phase_f_families import phase_f_registry

ROOT = Path(__file__).resolve().parents[1]

#--- The briefed grid, fixed before anything was run. 3.0 is the Phase G baseline.
TARGETS: tuple[float, ...] = (1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)
BASELINE_TARGET = 3.0

SUBPERIODS: tuple[tuple[str, str, str], ...] = (
    ("2023 partial", "2023-11-10 23:15", "2023-12-31 23:45"),
    ("2024 H1", "2024-01-01 00:00", "2024-06-30 23:45"),
    ("2024 H2", "2024-07-01 00:00", "2024-12-31 23:45"),
    ("2025 H1", "2025-01-01 00:00", "2025-06-30 23:45"),
)

#--- Brief section D. Native first; the rest are stress, not scenarios to pick from.
STRESS_ARMS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("native", {}),
    ("spread x1.10", {"spread_multiplier": 1.10}),
    ("spread x1.20", {"spread_multiplier": 1.20}),
    ("slippage 0.02%", {"slippage_percent": 0.02}),
    ("spread x1.20 + slippage 0.02%", {"spread_multiplier": 1.20, "slippage_percent": 0.02}),
)

#--- The frozen entry streams. Entries and stops are untouched; only the target moves.
FROZEN_STREAMS = {
    "A4": "BTC_V3_A4_PULLBACK_LONG_FROZEN",
    "T3": "BTC_V3_T3_BREAKOUT_SHORT_FROZEN",
    "CORE": "BTC_V3_CORE_V1_FROZEN",
}
#--- Phase F's raw opportunity streams, used here only as opportunity generators.
PHASE_F_STREAMS = {
    "F1a": "RESEARCH_F1a_STANDALONE",
    "F2a": "RESEARCH_F2a_STANDALONE",
    "F3a": "RESEARCH_F3a_STANDALONE",
    "CORE+F3a": "RESEARCH_CORE_PLUS_F3a",
}


def break_even_rate(target: float) -> float:
    """w such that ``target * w - 1 * (1 - w) == 0``, as a percentage."""
    return 100.0 / (1.0 + target)


# --- A: raw event payoff curves ---------------------------------------------------------


def resolve_targets(highs: np.ndarray, lows: np.ndarray, start: int, entry: float,
                    stop: float, long: bool,
                    targets: Sequence[float]) -> dict[float, str]:
    """Resolve one trade against every target in a single pass.

    The running maximum of favourable excursion is non-decreasing, so the first
    bar that reaches a level is a ``searchsorted`` on it rather than a fresh scan
    per target. The same trick on the running minimum gives the stop bar. Seven
    targets therefore cost one accumulate, not seven walks — and, more
    importantly, every target sees exactly the same path.
    """
    risk = abs(entry - stop)
    end = min(start + g.HORIZON_BARS, len(highs))
    if end <= start or risk <= 0:
        return {target: "NOT_REACHED" for target in targets}
    if long:
        favourable = (highs[start:end] - entry) / risk
        adverse = (lows[start:end] - entry) / risk
    else:
        favourable = (entry - lows[start:end]) / risk
        adverse = (entry - highs[start:end]) / risk

    best = np.maximum.accumulate(favourable)
    worst = -np.minimum.accumulate(adverse)          # non-decreasing
    stop_index = int(np.searchsorted(worst, 1.0, side="left"))
    stop_bar = stop_index if stop_index < len(worst) else None

    resolution: dict[float, str] = {}
    for target in targets:
        index = int(np.searchsorted(best, target, side="left"))
        target_bar = index if index < len(best) else None
        if target_bar is None and stop_bar is None:
            resolution[target] = "NOT_REACHED"
        elif target_bar is None:
            resolution[target] = "STOP_FIRST"
        elif stop_bar is None or target_bar < stop_bar:
            resolution[target] = "TARGET_FIRST"
        elif target_bar > stop_bar:
            resolution[target] = "STOP_FIRST"
        else:
            #--- One bar reached both. OHLC cannot order them.
            resolution[target] = "AMBIGUOUS_SAME_BAR"
    return resolution


@dataclass
class RawTrade:
    timestamp: pd.Timestamp
    reason: str
    events: tuple[str, ...]
    direction: str
    resolution: dict[float, str]


def raw_trades(candles: Sequence[Candle], bars: Sequence[g.BarContext],
               spreads: Sequence[float] | None) -> list[RawTrade]:
    """Phase G's event population, resolved against the whole target grid."""
    highs = np.array([c.high for c in candles], dtype=float)
    lows = np.array([c.low for c in candles], dtype=float)
    opens = np.array([c.open for c in candles], dtype=float)
    cost = (np.asarray(spreads, dtype=float) if spreads is not None
            else np.zeros(len(candles)))
    output: list[RawTrade] = []
    for bar in bars:
        if bar.reason not in g.TARGET_BUCKET_REASONS or not bar.events or not bar.atr:
            continue
        index = bar.index + 1
        if index >= len(opens):
            continue
        spread = float(cost[index])
        toward_long = bar.lean == "BULLISH_LEAN"
        for direction in g.DIRECTIONS:
            long = toward_long if direction == "TOWARD_H1" else not toward_long
            stop = (bar.stop_low - g.STOP_BUFFER_ATR * bar.atr if long
                    else bar.stop_high + g.STOP_BUFFER_ATR * bar.atr)
            entry = float(opens[index]) + (spread if long else 0.0)
            if not long:
                stop -= spread
            if (long and entry <= stop) or (not long and entry >= stop):
                continue
            risk_atr = abs(entry - stop) / bar.atr
            if not g.MIN_STOP_ATR <= risk_atr <= g.MAX_STOP_ATR:
                continue
            output.append(RawTrade(
                bar.timestamp, bar.reason, bar.events, direction,
                resolve_targets(highs, lows, index, entry, stop, long, TARGETS)))
    return output


def payoff_cell(rows: Sequence[RawTrade], target: float) -> dict[str, Any]:
    """One (pool, target) cell.

    Ambiguous same-bar outcomes are scored as losses, matching the engine's own
    ``SameBarResolution.SL_FIRST``, so the raw curve and the backtested curves in
    sections B and C are on the same convention.
    """
    counts = Counter(row.resolution[target] for row in rows)
    total = len(rows)
    if not total:
        return {"events": 0}
    wins = counts["TARGET_FIRST"]
    losses = counts["STOP_FIRST"] + counts["AMBIGUOUS_SAME_BAR"]
    resolved = wins + losses
    expectancy = (target * wins - losses) / total
    return {
        "events": total,
        "target_first": wins,
        "stop_first": counts["STOP_FIRST"],
        "ambiguous_same_bar": counts["AMBIGUOUS_SAME_BAR"],
        "not_reached": counts["NOT_REACHED"],
        "required_break_even_rate": round(break_even_rate(target), 2),
        "actual_rate": round(100 * wins / total, 2),
        "actual_rate_of_resolved": round(100 * wins / resolved, 2) if resolved else None,
        "edge_over_break_even": round(100 * wins / total - break_even_rate(target), 2),
        "net_expectancy_r": round(expectancy, 4),
        "binomial_p_value": round(
            g.binomial_tail_p(wins, total, break_even_rate(target) / 100.0), 6),
    }


def payoff_curve(rows: Sequence[RawTrade], gross_rows: Sequence[RawTrade]) -> dict[str, Any]:
    """The full curve for one pool, net and gross, with the cost drag between them."""
    curve: dict[str, Any] = {}
    for target in TARGETS:
        net = payoff_cell(rows, target)
        gross = payoff_cell(gross_rows, target)
        drag = (None if not net.get("events") or not gross.get("events")
                else round(gross["net_expectancy_r"] - net["net_expectancy_r"], 4))
        curve[f"{target:.2f}"] = {**net, "gross_expectancy_r": gross.get("net_expectancy_r"),
                                  "gross_rate": gross.get("actual_rate"),
                                  "spread_cost_drag_r": drag}
    return curve


def _select(rows: Sequence[RawTrade], *, reason: str | None = None,
            event: str | None = None, direction: str | None = None) -> list[RawTrade]:
    return [row for row in rows
            if (reason is None or row.reason == reason)
            and (direction is None or row.direction == direction)
            and (event is None or event in row.events)]


def raw_event_results(net: Sequence[RawTrade],
                      gross: Sequence[RawTrade]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for direction in g.DIRECTIONS:
        payload[f"ALL_EVENTS|{direction}"] = payoff_curve(
            _select(net, direction=direction), _select(gross, direction=direction))
    for reason in g.TARGET_BUCKET_REASONS:
        for direction in g.DIRECTIONS:
            payload[f"{reason}|{direction}"] = payoff_curve(
                _select(net, reason=reason, direction=direction),
                _select(gross, reason=reason, direction=direction))
    for event in g.EVENTS:
        for direction in g.DIRECTIONS:
            payload[f"{event}|{direction}"] = payoff_curve(
                _select(net, event=event, direction=direction),
                _select(gross, event=event, direction=direction))
    return payload


# --- B and C: frozen entry streams at every target ------------------------------------


def arm_config(strategy_id: str, target: float, **stress: Any) -> BacktestConfig:
    config = replace(development_config(strategy_id), risk_reward_ratio=target,
                     notes=f"Architecture Reset A: target {target:.2f}R (DEVELOPMENT only).",
                     **stress)
    if config.end_date >= HOLDOUT_START:
        raise ValueError("Architecture Reset A must not read the holdout split.")
    return config


def run_stream(strategy_id: str, target: float, ledger_path: Path, **stress: Any):
    return run_universal_backtest(dataset_path(), arm_config(strategy_id, target, **stress),
                                  ledger_path=ledger_path, registry=phase_f_registry())


def _monthly(rows: Sequence[dict]) -> dict[str, Any]:
    buckets: dict[str, list[dict]] = {}
    for row in rows:
        buckets.setdefault(to_timestamp(row["entry_time"]).strftime("%Y-%m"), []).append(row)
    return {month: {"trades": len(group),
                    "total_r": round(sum(item["realized_r"] for item in group), 4)}
            for month, group in sorted(buckets.items())}


def stream_metrics(result) -> dict[str, Any]:
    rows = result.trade_log
    total_r = sum(row["realized_r"] for row in rows)
    monthly = _monthly(rows)
    best_month = max((item["total_r"] for item in monthly.values()), default=0.0)
    return {
        "trades": result.total_trades,
        "trades_per_month": round(result.trades_per_month, 3),
        "win_rate": round(result.win_rate, 3) if result.win_rate is not None else None,
        "profit_factor": result.profit_factor,
        "average_r": result.average_r,
        "total_r": round(total_r, 4),
        "pnl": round(result.pnl, 2),
        "max_drawdown_percent": round(result.max_drawdown_percent, 4),
        "max_losing_streak": result.max_losing_streak,
        "monthly": monthly,
        #--- Brief section E: a zone carried by one month is not a zone.
        "best_month_r": round(best_month, 4),
        "best_month_share_of_total": (round(100 * best_month / total_r, 2)
                                      if total_r > 1e-9 else None),
        "positive_months": sum(1 for item in monthly.values() if item["total_r"] > 0),
        "negative_months": sum(1 for item in monthly.values() if item["total_r"] < 0),
        "subperiods": [
            {"label": label,
             **metrics(slice_rows(rows, _utc(start), _utc(end)), _utc(start), _utc(end))}
            for label, start, end in SUBPERIODS],
    }


def exit_curve(label: str, strategy_id: str, ledger_path: Path) -> dict[str, Any]:
    curve: dict[str, Any] = {}
    for target in TARGETS:
        result = run_stream(strategy_id, target, ledger_path)
        curve[f"{target:.2f}"] = {
            "required_break_even_rate": round(break_even_rate(target), 2),
            **stream_metrics(result),
        }
    return {"label": label, "strategy_id": strategy_id, "targets": curve}


def stress_curve(strategy_id: str, targets: Sequence[float],
                 ledger_path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for target in targets:
        arm: dict[str, Any] = {}
        for name, stress in STRESS_ARMS:
            result = run_stream(strategy_id, target, ledger_path, **stress)
            arm[name] = {
                "trades": result.total_trades,
                "profit_factor": result.profit_factor,
                "average_r": result.average_r,
                "total_r": round(sum(row["realized_r"] for row in result.trade_log), 4),
                "max_drawdown_percent": round(result.max_drawdown_percent, 4),
            }
        payload[f"{target:.2f}"] = arm
    return payload


# --- E: is there a broad stable region? ---------------------------------------------------


def stable_region(curve: dict[str, Any]) -> dict[str, Any]:
    """Brief section E, applied mechanically.

    A single target printing well is explicitly not acceptable, so the test is
    for a run of **adjacent** targets that are each positive, each positive in at
    least two subperiods, and none of which depends on one month.
    """
    positive: list[str] = []
    for key in (f"{target:.2f}" for target in TARGETS):
        cell = curve["targets"][key]
        subperiods = [item for item in cell["subperiods"] if item["trades"]]
        positive_subperiods = sum(1 for item in subperiods if item.get("total_r", 0) > 0)
        single_month = (cell["best_month_share_of_total"] is not None
                        and cell["best_month_share_of_total"] >= 100.0)
        if (cell["total_r"] > 0 and (cell["profit_factor"] or 0) > 1.0
                and positive_subperiods >= 2 and not single_month):
            positive.append(key)

    runs: list[list[str]] = []
    order = [f"{target:.2f}" for target in TARGETS]
    for key in order:
        if key in positive:
            if runs and order.index(runs[-1][-1]) == order.index(key) - 1:
                runs[-1].append(key)
            else:
                runs.append([key])
    longest = max(runs, key=len) if runs else []
    return {
        "targets_meeting_every_condition": positive,
        "longest_adjacent_run": longest,
        "broad_region": len(longest) >= 2,
        "region": (f"{longest[0]}R-{longest[-1]}R" if len(longest) >= 2 else None),
    }


def run_study(ledger_path: Path) -> dict[str, Any]:
    candles = development_candles()
    bars = g.contexts(candles)
    gross = raw_trades(candles, bars, None)
    net = raw_trades(candles, bars, development_spreads())

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
        "targets": list(TARGETS),
        "break_even_rates": {f"{target:.2f}": round(break_even_rate(target), 2)
                             for target in TARGETS},
        "raw_event_payoff": raw_event_results(net, gross),
        "exit_curves": {},
        "stable_regions": {},
    }
    for label, strategy_id in {**FROZEN_STREAMS, **PHASE_F_STREAMS}.items():
        curve = exit_curve(label, strategy_id, ledger_path)
        payload["exit_curves"][label] = curve
        payload["stable_regions"][label] = stable_region(curve)
    return payload


#--- Brief section D: stress only what survived section E, plus the incumbent 3R
#--- and the one configuration that actually reaches the frequency objective, so
#--- the comparison is against something rather than against nothing.
STRESS_PLAN: dict[str, tuple[float, ...]] = {
    "CORE": (1.75, 2.0, 3.0),
    "T3": (2.0, 3.0),
    "CORE+F3a": (2.0, 3.0),
}


def run_stress(ledger_path: Path) -> dict[str, Any]:
    streams = {**FROZEN_STREAMS, **PHASE_F_STREAMS}
    return {label: stress_curve(streams[label], targets, ledger_path)
            for label, targets in STRESS_PLAN.items()}


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    #--- The curves and the stress arms are separate runs so the expensive first
    #--- pass does not have to be repeated to add the second.
    parser.add_argument("--stress-only", action="store_true",
                        help="append execution stress to an existing --out payload")
    args = parser.parse_args()
    if args.stress_only:
        payload = json.loads(args.out.read_text())
        payload["execution_stress"] = run_stress(args.ledger)
        payload["stress_plan"] = {k: list(v) for k, v in STRESS_PLAN.items()}
    else:
        payload = run_study(args.ledger)
    args.out.write_text(json.dumps(payload, default=str, indent=1))
    print(f"wrote {args.out}")
    for label, region in payload.get("stable_regions", {}).items():
        print(f"  {label}: {region['region'] or 'NONE'}")


if __name__ == "__main__":
    main()
