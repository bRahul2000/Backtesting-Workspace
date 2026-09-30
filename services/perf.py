"""Opt-in performance/rerun instrumentation. Off (zero cost beyond one env lookup) unless ZONEFLOW_PERF_LOG names a
file; then every call appends one JSON line: {"t": epoch seconds, "name": ..., **fields}.

Used to count Streamlit reruns (full app runs vs terminal-only runs) and to time the TradingView Mode pipeline
stages, so performance claims are measured rather than guessed. Never logs payload contents.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
import threading
import time

PERF_ENV = "ZONEFLOW_PERF_LOG"
_lock = threading.Lock()


def enabled() -> bool:
    return bool(os.environ.get(PERF_ENV))


def event(name: str, **fields) -> None:
    path = os.environ.get(PERF_ENV)
    if not path:
        return
    line = json.dumps({"t": round(time.time(), 4), "name": name, **fields}, default=str)
    with _lock, open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


@contextmanager
def timed(stages: dict, name: str):
    """Accumulate the wall time of a block into stages[name] (milliseconds)."""
    start = time.perf_counter()
    try:
        yield
    finally:
        stages[name] = round(stages.get(name, 0.0) + (time.perf_counter() - start) * 1000, 2)
