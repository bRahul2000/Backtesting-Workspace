"""Compare MT5 Setup A audit export with frozen Python results on identical dates.

No tolerance is applied to timestamps or directions. Price tolerance defaults to
one BTCUSDm point (USD 0.01). A comparison is a mismatch report, never a parity
certificate by itself.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.exness_native_validation import engine_frame
from research.exness_setup_a_validation import run_feed
from research.setup_a_v1_candidate import validate_frozen
from services.exness_m15 import PROCESSED


REQUIRED = {"event", "signal_time", "direction", "qualified", "trigger", "stop",
            "target", "fill_time", "fill_price", "exit_time", "exit_price", "pnl"}
PRICE_FIELDS = ("trigger", "stop", "target")
EVENTS = {"SIGNAL_EVALUATED", "ORDER_CREATED", "ORDER_FILLED", "STOP_LOSS",
          "TAKE_PROFIT", "POSITION_CLOSED", "ORDER_CANCELED", "ORDER_EXPIRED"}


def frozen_config() -> dict:
    """Load and verify the existing immutable freeze; never rewrite it."""
    return validate_frozen()


def parse_mt5_export(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, keep_default_na=False)
    missing = REQUIRED - set(frame.columns)
    if missing:
        raise ValueError(f"MT5 export lacks columns: {sorted(missing)}")
    frame = frame.loc[frame.event.isin(EVENTS)].copy()
    for column in ("signal_time", "fill_time", "exit_time"):
        frame[column] = pd.to_datetime(frame[column].replace("", pd.NaT),
                                         utc=True, errors="raise")
    for column in (*PRICE_FIELDS, "fill_price", "exit_price", "pnl"):
        frame[column] = pd.to_numeric(frame[column].replace("", pd.NA), errors="raise")
    frame["direction"] = frame.direction.astype(str).str.upper()
    if not set(frame.direction).issubset({"LONG", "SHORT", "NONE"}):
        raise ValueError("Unknown MT5 direction in audit export")
    if frame.loc[frame.event.eq("SIGNAL_EVALUATED") &
                 frame.qualified.astype(str).str.lower().eq("true"), "signal_time"].isna().any():
        raise ValueError("Qualified MT5 signal lacks timestamp")
    return frame


def _key(stamp, direction: str) -> tuple[pd.Timestamp, str]:
    return pd.Timestamp(stamp), direction.upper()


def _price_issue(field: str, expected: float, actual: float | None,
                 tolerance: float, key: tuple) -> dict | None:
    if actual is None or pd.isna(actual) or abs(float(expected) - float(actual)) > tolerance:
        return {"type": f"{field}_difference", "signal_time": str(key[0]),
                "direction": key[1], "python": float(expected),
                "mt5": None if actual is None or pd.isna(actual) else float(actual)}
    return None


def _exit_class(value: str) -> str:
    normalized = value.lower().replace("_", " ")
    if normalized.startswith("stop loss"):
        return "STOP_LOSS"
    if normalized.startswith("take profit"):
        return "TAKE_PROFIT"
    return normalized.upper()


def compare_exports(python_signals: pd.DataFrame, python_trades: pd.DataFrame,
                    mt5_events: pd.DataFrame, price_tolerance: float = .01) -> dict:
    if not 0 <= price_tolerance <= .01:
        raise ValueError("Price tolerance must be between zero and one BTCUSDm point")
    py_signals = {_key(row.signal_time, row.direction): row
                  for row in python_signals.itertuples(index=False)}
    mt5_signal_rows = mt5_events.loc[mt5_events.event.eq("SIGNAL_EVALUATED") &
                                  mt5_events.qualified.astype(str).str.lower().eq("true")]
    issues: list[dict] = []
    for row in mt5_signal_rows.loc[mt5_signal_rows.duplicated(
            ["signal_time", "direction"], keep="first")].itertuples(index=False):
        issues.append({"type": "duplicate_mt5_signal", "signal_time": str(row.signal_time),
                       "direction": row.direction})
    mt_signals = {_key(row.signal_time, row.direction): row
                  for row in mt5_signal_rows.itertuples(index=False)}
    py_keys, mt_keys = set(py_signals), set(mt_signals)
    for stamp, direction in sorted(py_keys - mt_keys):
        issue = "direction_mismatch" if (stamp, "SHORT" if direction == "LONG" else "LONG") in mt_keys else "missing_mt5_signal"
        issues.append({"type": issue, "signal_time": str(stamp), "direction": direction})
    for stamp, direction in sorted(mt_keys - py_keys):
        if (stamp, "SHORT" if direction == "LONG" else "LONG") not in py_keys:
            issues.append({"type": "extra_mt5_signal", "signal_time": str(stamp),
                           "direction": direction})
    py_trades = {_key(row.signal_time, row.direction): row
                 for row in python_trades.itertuples(index=False)}
    mt_fill_rows = mt5_events.loc[mt5_events.event.eq("ORDER_FILLED") &
                                   mt5_events.signal_time.notna()]
    for row in mt_fill_rows.loc[mt_fill_rows.duplicated(
            ["signal_time", "direction"], keep="first")].itertuples(index=False):
        issues.append({"type": "duplicate_mt5_fill", "signal_time": str(row.signal_time),
                       "direction": row.direction})
    mt_fills = {_key(row.signal_time, row.direction): row
                for row in mt_fill_rows.itertuples(index=False)}
    mt_exits = {}
    for row in mt5_events.loc[mt5_events.event.isin(
            ["STOP_LOSS", "TAKE_PROFIT", "POSITION_CLOSED"])].itertuples(index=False):
        if pd.isna(row.signal_time):
            continue
        key = _key(row.signal_time, row.direction)
        if key not in mt_exits or row.event != "POSITION_CLOSED":
            mt_exits[key] = row
    for key in sorted(py_keys & mt_keys):
        py, mt = py_signals[key], mt_signals[key]
        planned_target = float(py.trigger) + (1 if key[1] == "LONG" else -1) * float(py.planned_target_distance)
        for field, expected in (("trigger", py.trigger), ("stop", py.structural_stop),
                                ("target", planned_target)):
            issue = _price_issue(field, expected, getattr(mt, field), price_tolerance, key)
            if issue:
                issues.append(issue)
        py_trade, fill = py_trades.get(key), mt_fills.get(key)
        if py_trade is not None and fill is None:
            issues.append({"type": "missing_mt5_fill", "signal_time": str(key[0]), "direction": key[1]})
        elif py_trade is None and fill is not None:
            issues.append({"type": "extra_mt5_fill", "signal_time": str(key[0]), "direction": key[1]})
        elif py_trade is not None and fill is not None:
            if pd.Timestamp(py_trade.entry_time) != fill.fill_time:
                issues.append({"type": "fill_time_difference", "signal_time": str(key[0]), "direction": key[1],
                               "python": str(py_trade.entry_time), "mt5": str(fill.fill_time)})
            issue = _price_issue("fill_price", py_trade.entry_price, fill.fill_price, price_tolerance, key)
            if issue:
                issues.append(issue)
            exit_row = mt_exits.get(key)
            if exit_row is None:
                issues.append({"type": "missing_mt5_exit", "signal_time": str(key[0]), "direction": key[1]})
            else:
                if pd.Timestamp(py_trade.exit_time) != exit_row.exit_time:
                    issues.append({"type": "exit_time_difference", "signal_time": str(key[0]),
                                   "direction": key[1], "python": str(py_trade.exit_time),
                                   "mt5": str(exit_row.exit_time)})
                issue = _price_issue("exit_price", py_trade.exit_price, exit_row.exit_price,
                                     price_tolerance, key)
                if issue:
                    issues.append(issue)
                py_won = int(float(py_trade.gross_pnl) > 0) - int(float(py_trade.gross_pnl) < 0)
                mt_won = int(float(exit_row.pnl) > 0) - int(float(exit_row.pnl) < 0)
                if py_won != mt_won or _exit_class(str(py_trade.exit_reason)) != _exit_class(str(exit_row.event)):
                    issues.append({"type": "outcome_mismatch", "signal_time": str(key[0]),
                                   "direction": key[1], "python": str(py_trade.exit_reason),
                                   "mt5": str(exit_row.event)})
    counts = {kind: sum(row["type"] == kind for row in issues)
              for kind in sorted({row["type"] for row in issues})}
    return {"python_signals": len(py_keys), "mt5_signals": len(mt_keys),
            "exact_signal_matches": len(py_keys & mt_keys),
            "issue_counts": counts, "issues": issues,
            "price_tolerance_usd": price_tolerance}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mt5-export", type=Path, required=True)
    parser.add_argument("--start", required=True, help="UTC date, inclusive")
    parser.add_argument("--end", required=True, help="UTC date, inclusive")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--price-tolerance", type=float, default=.01)
    args = parser.parse_args()
    frozen_config()
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC") + pd.Timedelta(days=1)
    if start >= end:
        parser.error("start must be on or before end")
    native = pd.read_csv(PROCESSED, parse_dates=["timestamp_utc"])
    run = run_feed(engine_frame(native, exness=True), "exness_native")
    signals = run["signals"].loc[lambda x: x.signal_time.between(start, end, inclusive="left")]
    trades = run["trades"].loc[lambda x: x.signal_time.between(start, end, inclusive="left")]
    mt = parse_mt5_export(args.mt5_export)
    mt = mt.loc[mt.signal_time.between(start, end, inclusive="left")]
    result = compare_exports(signals, trades, mt, args.price_tolerance)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, default=str) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "issues"}, indent=2))
    print(f"Mismatch rows: {len(result['issues'])}; full report: {args.output}")


if __name__ == "__main__":
    main()
