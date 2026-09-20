"""R4 Stage 5 — forward demo monitoring and deployment readiness.

Stage 4 asks "does the broker do what the twin intended?". Stage 5 asks "over
enough trades, is this worth deploying?" — and answers with counted evidence,
not elapsed time.

Read-only. Nothing here can place an order.
"""
from __future__ import annotations

from dataclasses import dataclass
import statistics
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Minimum demo trades before execution quality means anything. Below ~20 the
#: slippage distribution is noise and one bad fill dominates every statistic.
MIN_DEMO_TRADES = 20
TARGET_DEMO_TRADES = 30
MAX_ACCEPTABLE_SL_MISMATCHES = 0
MAX_ACCEPTABLE_DUPLICATES = 0


@dataclass
class TradeRecord:
    client_tag: str
    setup_id: str
    entry_time: pd.Timestamp
    realized_r: float
    profit: float
    commission: float
    swap: float
    entry_slippage: float | None


def trades_from_executions(executions: pd.DataFrame) -> list[TradeRecord]:
    """Completed demo trades, in time order."""
    closed = executions[(executions.action == "CLOSE") & (executions.outcome == "ACCEPTED")]
    records: list[TradeRecord] = []
    for _, row in closed.iterrows():
        def num(value, default=0.0):
            try:
                return float(value)
            except (TypeError, ValueError):
                return default
        records.append(TradeRecord(
            client_tag=row.client_tag, setup_id=row.setup_id,
            entry_time=pd.Timestamp(row.event_time_utc),
            realized_r=num(row.get("realized_r", ""), 0.0) if hasattr(row, "get") else 0.0,
            profit=num(row.profit), commission=num(row.commission),
            swap=num(row.swap),
            entry_slippage=None))
    return sorted(records, key=lambda r: r.entry_time)


def drawdown_and_streaks(profits: list[float]) -> dict:
    """Peak-to-trough drawdown and the longest losing run."""
    balance = 0.0
    peak = 0.0
    max_dd = 0.0
    streak = worst_streak = 0
    for profit in profits:
        balance += profit
        peak = max(peak, balance)
        max_dd = max(max_dd, peak - balance)
        if profit < 0:
            streak += 1
            worst_streak = max(worst_streak, streak)
        else:
            streak = 0
    return {"max_drawdown": max_dd, "longest_losing_streak": worst_streak,
            "final_balance_delta": balance}


def slippage_distribution(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "mean": None, "median": None, "p95_abs": None,
                "worst": None, "stdev": None}
    magnitudes = sorted(abs(v) for v in values)
    index = max(0, int(round(0.95 * (len(magnitudes) - 1))))
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p95_abs": magnitudes[index],
        "worst": max(values, key=abs),
        "stdev": statistics.pstdev(values) if len(values) > 1 else 0.0,
    }


def weekly_summary(executions: pd.DataFrame) -> list[dict]:
    if executions.empty:
        return []
    frame = executions.copy()
    frame["_t"] = pd.to_datetime(frame.event_time_utc, utc=True, format="mixed")
    # to_period() drops the timezone; converting first keeps the week boundary
    # explicit and silences an otherwise noisy warning.
    frame["_week"] = frame["_t"].dt.tz_convert(None).dt.to_period("W").astype(str)
    out = []
    for week, group in frame.groupby("_week"):
        out.append({
            "week": week,
            "submissions": int((group.action == "SUBMIT").sum()),
            "accepted": int((group.outcome == "ACCEPTED").sum()),
            "rejected": int((group.outcome != "ACCEPTED").sum()),
            "closes": int((group.action == "CLOSE").sum()),
        })
    return out


def readiness(executions: pd.DataFrame, reconciliation: dict,
              divergences: int = 0) -> dict:
    """Deployment readiness, as counted evidence rather than elapsed time."""
    closes = int((executions.action == "CLOSE").sum()) if not executions.empty else 0
    profits = []
    if not executions.empty:
        for value in executions.loc[executions.action == "CLOSE", "profit"]:
            try:
                profits.append(float(value))
            except (TypeError, ValueError):
                pass
    risk = drawdown_and_streaks(profits)
    slips = [r["entry_slippage"] for r in reconciliation.get("rows", [])
             if r.get("entry_slippage") is not None]

    must = [
        ("no duplicate client tags",
         len(reconciliation.get("duplicate_client_tags", [])) <= MAX_ACCEPTABLE_DUPLICATES),
        ("no stop-loss placement mismatches",
         reconciliation.get("sl_mismatches", 0) <= MAX_ACCEPTABLE_SL_MISMATCHES),
        ("no take-profit placement mismatches",
         reconciliation.get("tp_mismatches", 0) == 0),
        ("no strategy-versus-broker divergence", divergences == 0),
        ("commission and swap captured on every close",
         closes == 0 or reconciliation.get("commission_total") is not None),
    ]
    observed = [
        (f"completed demo trades >= {MIN_DEMO_TRADES}", closes >= MIN_DEMO_TRADES,
         f"{closes}"),
        (f"target demo trades >= {TARGET_DEMO_TRADES}", closes >= TARGET_DEMO_TRADES,
         f"{closes}"),
    ]
    must_ok = all(ok for _, ok in must)
    observed_ok = all(ok for _, ok, _ in observed)
    if not must_ok:
        verdict = "BLOCKED — execution quality not established"
    elif observed_ok:
        verdict = "READY FOR DEPLOYMENT REVIEW"
    else:
        verdict = "AWAITING EVIDENCE — insufficient completed demo trades"
    return {
        "completed_trades": closes,
        "slippage": slippage_distribution(slips),
        "risk": risk,
        "commission_total": reconciliation.get("commission_total"),
        "swap_total": reconciliation.get("swap_total"),
        "weekly": weekly_summary(executions),
        "must": must, "observed": observed,
        "must_ok": must_ok, "observed_ok": observed_ok,
        "verdict": verdict,
    }
