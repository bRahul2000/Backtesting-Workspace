"""Shared helpers for the Pine engine tests (synthetic UTC bars, run a script)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ui.tradingview_mode.pine import PineExecution, compile_script, run_script
from ui.tradingview_mode.pine.engine import data_context


def bars(n: int = 600, seed: int = 3, start: str = "2026-01-05", freq: str = "15min", price: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = price + np.cumsum(rng.normal(0, 1, n))
    open_ = np.r_[close[0] + rng.normal(0, 0.3), close[:-1]]
    high = np.maximum(open_, close) + rng.uniform(0.05, 1.5, n)
    low = np.minimum(open_, close) - rng.uniform(0.05, 1.5, n)
    volume = rng.uniform(1, 100, n).round(3)
    return pd.DataFrame({"timestamp": pd.date_range(start, periods=n, freq=freq, tz="UTC"), "open": open_, "high": high,
                         "low": low, "close": close, "volume": volume})


def context(frame: pd.DataFrame, seconds: int = 900, forming_last: bool = False):
    return data_context(frame, timeframe_seconds=seconds, ticker="TEST", tickerid="TEST:TEST", mintick=0.01,
                        forming_last=forming_last)


def run(source: str, frame: pd.DataFrame | None = None, inputs: dict | None = None, seconds: int = 900):
    result = compile_script(source)
    assert result.ok, [d.text() for d in result.diagnostics]
    frame = bars() if frame is None else frame
    execution = PineExecution(result.program, inputs or {})
    out = run_script(execution, context(frame, seconds), ("test",), "t")
    assert out.error is None, out.error
    return out, frame


def plots(out) -> dict[str, list]:
    """title -> list of values (None for na) for every plot output."""
    return {o["title"]: [p["value"] for p in o["data"]] for o in out.outputs if o["kind"] == "plot"}


def script(body: str, title: str = "T", overlay: bool = False) -> str:
    return f'//@version=5\nindicator("{title}", overlay={"true" if overlay else "false"})\n' + body.strip("\n") + "\n"


def diagnostics(source: str) -> list[tuple[str, int, str]]:
    return [(d.kind, d.line, d.message) for d in compile_script(source).diagnostics]
