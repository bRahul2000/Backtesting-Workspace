"""Existing-strategy signal parity (BTC 15m only; no strategy or engine code is changed).

Each frozen BTC strategy is run by the unmodified ``engine.backtester.run_backtest``
on each feed separately, with default settings, on the IDENTICAL time grid (the
candles both feeds have), so only prices differ. The backtester refuses a
position that crosses missing candles, so every contiguous segment between the
Exness data gaps is its own trading window, identical for both feeds (earlier
candles are warm-up). Only signal timestamps and directions are compared, not
PnL. Because a strategy does not signal while in a position, one diverging trade
can shift later ones. No Gold strategy exists in the registry, so Gold has no
strategy parity.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine.backtester import run_backtest
from strategies.registry import discover_builtin_strategies

from . import metrics as M
from .data import feeds

STRATEGIES = ("BTC_V3_CORE_V1_FROZEN", "BTC_V3_A4_PULLBACK_LONG_FROZEN", "BTC_V3_T3_BREAKOUT_SHORT_FROZEN")
SECONDS = 900
#: Strategies read H1 context (e.g. H1 EMAs) from the 15m stream: both feeds get
#: at least this many of their own candles before the trading window opens.
STRATEGY_WARMUP_BARS = 3000


def _signals(frame: pd.DataFrame, strategy_id: str, windows: list[tuple[pd.Timestamp, pd.Timestamp]]) -> dict:
    descriptor = discover_builtin_strategies().get(strategy_id)
    out = {"LONG": [], "SHORT": []}
    trades = 0
    for start, end in windows:
        result = run_backtest(frame[frame["timestamp"] <= end], descriptor.create(), trade_start=start, trade_end=end)
        trades += len(result.trades)
        for trade in result.trades:
            out[str(getattr(trade.direction, "value", trade.direction)).upper()].append(int(pd.Timestamp(trade.signal_time).timestamp()))
    return {k: np.array(sorted(v), dtype=np.int64) for k, v in out.items()} | {"_trades": trades}


def contiguous_windows(timestamps: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Maximal runs of consecutive 15m candles inside [start, end]."""
    t = timestamps[(timestamps >= start) & (timestamps <= end)].reset_index(drop=True)
    breaks = t.diff() != pd.Timedelta(seconds=SECONDS)
    ids = breaks.cumsum()
    return [(group.iloc[0], group.iloc[-1]) for _, group in t.groupby(ids) if len(group) > 1]


def strategy_parity() -> dict:
    binance, _, exness = feeds("BTC", "15m")
    common = set(binance["timestamp"]) & set(exness.frame["timestamp"])
    b = binance[binance["timestamp"].isin(common)].reset_index(drop=True)
    e = exness.frame[exness.frame["timestamp"].isin(common)].reset_index(drop=True)
    start, end = b["timestamp"].iloc[STRATEGY_WARMUP_BARS], b["timestamp"].iloc[-1]
    windows = contiguous_windows(b["timestamp"], start, end)
    out = {"status": "PASS", "window": {"start": start.isoformat(), "end": end.isoformat(), "segments": len(windows),
                                        "grid_candles": len(b)},
           "note": " ".join(__doc__.split("\n\n")[1].split()), "strategies": {}}
    for strategy_id in STRATEGIES:
        try:
            sb = _signals(b, strategy_id, windows)
            se = _signals(e, strategy_id, windows)
        except Exception as exc:  # reported, never hidden
            out["strategies"][strategy_id] = {"error": f"{type(exc).__name__}: {exc}"}
            out["status"] = "FAIL"
            continue
        per_direction = {d: M.match_events(sb[d], se[d], SECONDS) for d in ("LONG", "SHORT")}
        pooled = M.pooled(*per_direction.values())
        out["strategies"][strategy_id] = {
            "binance_trades": sb["_trades"], "exness_trades": se["_trades"],
            "pooled": pooled,
            **{d: {k: v for k, v in r.items() if not k.startswith("_")} for d, r in per_direction.items()},
            "first_binance_only": [pd.Timestamp(t, unit="s", tz="UTC").isoformat()
                                   for t in (per_direction["LONG"]["_binance_only_times"] + per_direction["SHORT"]["_binance_only_times"])[:10]],
            "first_exness_only": [pd.Timestamp(t, unit="s", tz="UTC").isoformat()
                                  for t in (per_direction["LONG"]["_exness_only_times"] + per_direction["SHORT"]["_exness_only_times"])[:10]],
        }
    return out
