"""Strategy Tester trade-list CSV: the CURRENT result exactly as the tester shows it, in raw, machine-friendly form.

* one row per trade of the displayed report (closed trades, then any trade still open at the end of the test range)
* raw values: prices / quantities / P&L as full-precision numbers, times as UTC ISO text AND epoch seconds, booleans
  as true/false; empty cell = unknown / not applicable (e.g. the exit of an open trade)
* every row carries the strategy, symbol, timeframe and the tested range, so a file is self-describing
* UTF-8, deterministic filename: <Strategy>_<SYMBOL>_<TF>_<first test day>_<last test day>_trades.csv

R multiple is not exported for Pine strategies: the report carries no per-trade initial risk (stop), and an R value
without one would be invented.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import re

MT5_TIMEFRAMES = {"1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30", "1h": "H1", "2h": "H2", "4h": "H4",
                  "6h": "H6", "12h": "H12", "1d": "D1", "1w": "W1"}
PINE_COLUMNS = ("trade_number", "direction", "status", "entry_time_utc", "entry_time_epoch", "entry_price",
                "exit_time_utc", "exit_time_epoch", "exit_price", "quantity", "pnl", "pnl_percent", "commission",
                "max_runup", "max_drawdown", "bars_held", "entry_id", "entry_comment", "exit_id", "exit_reason",
                "exit_comment", "strategy", "symbol", "timeframe", "provider", "test_mode", "test_start_utc",
                "test_end_utc")


def _iso(epoch) -> str:
    if epoch is None:
        return ""
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _raw(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)                           # shortest exact round-trip text, never a rounded display value
    return str(value)


def filename(strategy: str, symbol: str, timeframe: str, first_time, last_time) -> str:
    name = re.sub(r"[^A-Za-z0-9.]+", "_", strategy).strip("_").replace(".", "_") or "strategy"
    tf = MT5_TIMEFRAMES.get(timeframe, timeframe)
    day = lambda epoch: _iso(epoch)[:10] if epoch is not None else "na"      # noqa: E731
    return f"{name}_{re.sub(r'[^A-Za-z0-9]+', '', symbol)}_{tf}_{day(first_time)}_{day(last_time)}_trades.csv"


def pine_trades_csv(*, strategy: str, symbol: str, timeframe: str, provider: str, report: dict,
                    test_range: dict) -> tuple[str, str]:
    """(filename, CSV text) for a Pine strategy report (pine/outputs.py render_strategy)."""
    first, last = test_range.get("first_time"), test_range.get("last_time")
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(PINE_COLUMNS)
    for t in report.get("trades", []):
        writer.writerow([_raw(v) for v in (
            t["number"], "long" if t["direction"] > 0 else "short", "open" if t["open"] else "closed",
            _iso(t["entry_time"]), t["entry_time"], t["entry_price"],
            _iso(t["exit_time"]), t["exit_time"], t["exit_price"], t["qty"], t["profit"], t["profit_percent"],
            t.get("commission"), t.get("max_runup"), t.get("max_drawdown"), t.get("bars_held"),
            t.get("entry_id"), t.get("entry_comment"), t.get("exit_id"), t.get("exit_kind"), t.get("exit_comment"),
            strategy, symbol, timeframe, provider, test_range.get("mode"), _iso(first), _iso(last))])
    return filename(strategy, symbol, timeframe, first, last), out.getvalue()
