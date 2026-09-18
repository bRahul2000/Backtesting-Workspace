"""Deterministic preservation check for frozen BTC V3 A4, T3 and Core v1.

This is a regression/reproduction harness, not an optimizer. It replays the
validated $10 synthetic Bid/Ask development and forward windows and fails loudly
if the permanent frozen modules drift from the accepted reference results.
"""
from __future__ import annotations

import json
from math import inf, isclose
from pathlib import Path
from statistics import mean

import pandas as pd

from engine.metrics import calculate_metrics
from engine.models import BacktestSettings, Direction
from research.exness_cost_calibrated import run_synthetic_segment
from research.v3_l2_trend_pullback_baseline import warmup_plan as l2_warmup, MONTH_DAYS
from research.v3_regime_adaptive_baseline import add_closed_trade_equity, v3_warmup_plan
from services.history import CANONICAL_DATA_FILE
from strategies.btc_v3_a4_pullback_long import BtcV3A4PullbackLongFrozen, V3A4FrozenParameters
from strategies.btc_v3_core_v1 import BtcV3CoreV1Frozen
from strategies.btc_v3_t3_breakout_short import BtcV3T3BreakoutShortFrozen, V3T3FrozenParameters
from utils.data_validation import continuous_segments, load_ohlcv_csv

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports/v3_core_v1_frozen"
SPREAD = 10.0
SETTINGS = BacktestSettings(
    starting_balance=10_000.0,
    risk_percent=0.25,
    risk_reward_ratio=3.0,
    commission_percent=0.0,
    slippage_percent=0.0,
    max_leverage=1.0,
)
PERIODS = {
    "development": (pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2024-12-31 23:45", tz="UTC")),
    "forward": (pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2026-09-17 01:30", tz="UTC")),
}
EXPECTED = {
    ("a4", "development"): {"trades": 225, "trades_per_month": 5.277223470862096, "pf": 1.2652042757297264, "avg_r": 0.1889792720059191, "pnl": 1059.9857263210415, "dd": 2.962718739433167},
    ("a4", "forward"): {"trades": 78, "trades_per_month": 4.024071190211346, "pf": 1.3403158387390555, "avg_r": 0.23176553579254794, "pnl": 448.25490611375494, "dd": 2.503002148914893},
    ("t3", "development"): {"trades": 247, "trades_per_month": 5.793218654679723, "pf": 1.1883715798306258, "avg_r": 0.12720930217837362, "pnl": 791.665696645391, "dd": 3.208929655393817},
    ("t3", "forward"): {"trades": 145, "trades_per_month": 7.480645161290323, "pf": 1.086805188305326, "avg_r": 0.06138354347320293, "pnl": 230.46703868117817, "dd": 3.733559129916781},
    ("core", "development"): {"trades": 472, "trades_per_month": 11.07044212554182, "pf": 1.224225831450077, "avg_r": 0.1566547327105722, "pnl": 1849.7794149888975, "dd": 3.2036378489188793},
    ("core", "forward"): {"trades": 223, "trades_per_month": 11.504716351501669, "pf": 1.1688791449202893, "avg_r": 0.12097903854454335, "pnl": 675.0148650072106, "dd": 3.7455941320390216},
}


def _pf(trades):
    gains = sum(t.pnl for t in trades if t.pnl > 1e-9)
    losses = sum(t.pnl for t in trades if t.pnl < -1e-9)
    return gains / abs(losses) if losses else inf if gains else None


def _max_loss_streak(trades):
    current = worst = 0
    for trade in trades:
        if trade.pnl < -1e-9:
            current += 1
            worst = max(worst, current)
        elif abs(trade.pnl) > 1e-9:
            current = 0
    return worst


def _strategy_and_start(kind: str, segment_start: pd.Timestamp):
    if kind == "a4":
        params = V3A4FrozenParameters()
        return BtcV3A4PullbackLongFrozen(), l2_warmup(params, segment_start).first_search_time
    if kind == "t3":
        params = V3T3FrozenParameters()
        return BtcV3T3BreakoutShortFrozen(), v3_warmup_plan(params, segment_start).first_search_time
    if kind == "core":
        a4_start = l2_warmup(V3A4FrozenParameters(), segment_start).first_search_time
        t3_start = v3_warmup_plan(V3T3FrozenParameters(), segment_start).first_search_time
        return BtcV3CoreV1Frozen(), max(a4_start, t3_start)
    raise ValueError(kind)


def run(kind: str, start: pd.Timestamp, end: pd.Timestamp, data_path: Path = CANONICAL_DATA_FILE) -> dict:
    data = load_ohlcv_csv(data_path)
    data = data.loc[data.timestamp.between(start, end)].reset_index(drop=True)
    pooled = []
    results = []
    usable_months = 0.0
    segment_rows = []
    for index, segment in enumerate(continuous_segments(data), 1):
        frame = data.loc[data.timestamp.between(segment.start, segment.end)].reset_index(drop=True)
        strategy, trade_start = _strategy_and_start(kind, segment.start)
        if trade_start > segment.end:
            continue
        result = run_synthetic_segment(frame, strategy, SPREAD, trade_start, SETTINGS)
        add_closed_trade_equity(result)
        pooled.extend(result.trades)
        results.append(result)
        months = len(frame.loc[frame.timestamp >= trade_start]) * 15 / (60 * 24 * MONTH_DAYS)
        usable_months += months
        segment_rows.append({
            "segment": f"S{index:02d}", "start": segment.start, "end": segment.end,
            "trade_start": trade_start, "trades": len(result.trades),
            "max_dd": calculate_metrics(result).max_drawdown_percent,
        })
    return {
        "trades": len(pooled),
        "trades_per_month": len(pooled) / usable_months,
        "win_rate": 100 * sum(t.pnl > 1e-9 for t in pooled) / len(pooled),
        "pf": _pf(pooled),
        "avg_r": mean(t.realized_r for t in pooled),
        "pnl": sum(t.pnl for t in pooled),
        "dd": max(calculate_metrics(r).max_drawdown_percent for r in results),
        "max_losing_streak": max(_max_loss_streak(r.trades) for r in results),
        "long_trades": sum(t.direction is Direction.LONG for t in pooled),
        "short_trades": sum(t.direction is Direction.SHORT for t in pooled),
        "usable_months": usable_months,
        "segments": segment_rows,
    }


def assert_reference(kind: str, period: str, actual: dict) -> None:
    expected = EXPECTED[(kind, period)]
    if actual["trades"] != expected["trades"]:
        raise AssertionError(f"{kind} {period}: trades {actual['trades']} != {expected['trades']}")
    for key in ("trades_per_month", "pf", "avg_r", "pnl", "dd"):
        if not isclose(actual[key], expected[key], rel_tol=0.0, abs_tol=1e-10):
            raise AssertionError(f"{kind} {period}: {key} {actual[key]} != {expected[key]}")


def main() -> dict:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    flat = []
    for kind in ("a4", "t3", "core"):
        summary[kind] = {}
        for period, (start, end) in PERIODS.items():
            actual = run(kind, start, end)
            assert_reference(kind, period, actual)
            summary[kind][period] = actual
            flat.append({"strategy": kind, "period": period, **{k: v for k, v in actual.items() if k != "segments"}})
    (OUTPUT / "reproduction_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    pd.DataFrame(flat).to_csv(OUTPUT / "reproduction_summary.csv", index=False)
    return summary


if __name__ == "__main__":
    result = main()
    for strategy, periods in result.items():
        for period, values in periods.items():
            print(strategy, period, {k: values[k] for k in ("trades", "trades_per_month", "pf", "avg_r", "pnl", "dd", "max_losing_streak")})
